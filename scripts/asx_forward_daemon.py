#!/usr/bin/env python3
"""V309 — the forward ASX lane daemon.

Composes the platform's live-paper scheduler + crash-safe checkpoint + runner
around one ASX cycle function. No broker, no orders, no capital: the runner's
equity is a constant, and the lane's only product is an append-only store plus one
spread observation per week (see ``omega/nodes/asx/forward.py``).

Modes:
  (default)        the supervised loop; refuses to run unless SCHEDULER_ENABLED=1
  --once           run one cycle now, checkpoint it, exit (F1 / F2 smoke)
  --reconcile-v3   compute the weekly mark over the frozen substrate only (F3)
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from omega.live_paper.checkpoint import Checkpoint, CheckpointState  # noqa: E402
from omega.live_paper.config import SchedulerConfig  # noqa: E402
from omega.live_paper.runner import CycleContext, CycleResult, LivePaperRunner  # noqa: E402
from omega.live_paper.scheduler import DailyScheduler  # noqa: E402
from omega.nodes.asx.forward import (  # noqa: E402
    ForwardStore,
    PriceHistory,
    due_marks,
    intraday_doc,
    panel_doc,
    panel_shorts,
    prices_doc,
)
from omega.nodes.asx.intraday import FROZEN_INTRADAY  # noqa: E402
from omega.nodes.asx.shorted import ShortedClient, fetch_available_dates  # noqa: E402

log = logging.getLogger("asx_forward")

PANEL_PACE_S = 2.2  # under the anonymous 30/min limit even when the token fails
FIRST_PRICE_PERIOD = "1mo"  # closes the gap between the frozen v3 substrate and today
DAILY_PRICE_PERIOD = "5d"
V307_MANIFEST = FROZEN_INTRADAY / "MANIFEST.json"


# ---------------------------------------------------------------------------
# fetchers
# ---------------------------------------------------------------------------
def _token() -> str | None:
    try:
        from shorted_oauth import get_access_token

        return get_access_token(interactive=False)
    except Exception as exc:  # a token failure degrades to anonymous, loudly
        log.warning("oauth token unavailable (%s): using the anonymous tier", type(exc).__name__)
        return None


def refresh_panels(store: ForwardStore) -> dict[str, Any]:
    token = _token()
    tier = "token" if token else "anonymous"
    cl = ShortedClient(token=token, require_token=False)
    dates = fetch_available_dates(cl)
    new = []
    for d in dates:
        if store.has("short_panel", d):
            continue
        resp = cl.call(
            "GetMarketByDate",
            {"date": d, "limit": 1000, "includeZeroShortPositions": True},
            service="MarketService",
        )
        stocks = resp.get("stocks", [])
        if not stocks:
            log.warning("panel %s: empty response, not stored", d)
            continue
        store.write_once("short_panel", d, panel_doc(d, stocks, tier, resp.get("totalCount")))
        new.append(d)
        time.sleep(PANEL_PACE_S)
    return {
        "tier": tier,
        "available": len(dates),
        "latest": dates[-1] if dates else None,
        "new": new,
    }


def _yf_download(symbols: list[str], interval: str, period: str) -> Any:
    import yfinance as yf

    warnings.filterwarnings("ignore")
    return yf.download(
        symbols,
        interval=interval,
        period=period,
        progress=False,
        auto_adjust=False,
        group_by="ticker",
        threads=True,
    )


def refresh_prices(store: ForwardStore, codes: list[str]) -> dict[str, Any]:
    import math

    period = DAILY_PRICE_PERIOD if store.keys("prices") else FIRST_PRICE_PERIOD
    df = _yf_download([f"{c}.AX" for c in codes], "1d", period)
    by_session: dict[str, dict[str, list[float]]] = {}
    have = set(df.columns.get_level_values(0)) if hasattr(df.columns, "levels") else set()
    for c in codes:
        sym = f"{c}.AX"
        if sym not in have:
            continue
        d = df[sym].dropna(how="all")
        for ts, row in d.iterrows():
            close = float(row["Close"])
            if not math.isfinite(close) or close <= 0:
                continue
            by_session.setdefault(ts.strftime("%Y-%m-%d"), {})[c] = [
                close,
                float(row["Adj Close"]),
                float(row["Volume"]) if math.isfinite(float(row["Volume"])) else 0.0,
            ]
    # The most recent session may be partial if the tick fires mid-session; the
    # tick is after the close, but a session dated today is only stored when today
    # is over in Sydney terms — i.e. never before 06:10 UTC. Cheap guard: skip a
    # session dated after the cycle's own date.
    today = datetime.now(UTC).date().isoformat()
    new = []
    for sess in sorted(by_session):
        if sess > today or store.has("prices", sess):
            continue
        store.write_once("prices", sess, prices_doc(sess, by_session[sess]))
        new.append(sess)
    return {
        "period": period,
        "sessions_seen": sorted(by_session),
        "new": new,
        "codes_with_data": len(have & {f"{c}.AX" for c in codes}),
    }


def refresh_intraday(store: ForwardStore) -> dict[str, Any]:
    import math

    if not V307_MANIFEST.is_file():
        return {"skipped": "no V307 manifest"}
    man = json.loads(V307_MANIFEST.read_text())
    codes = sorted(k.split("/")[1][:-8] for k in man["files"] if k.startswith("1h/"))
    period = DAILY_PRICE_PERIOD if store.keys("intraday_1h") else FIRST_PRICE_PERIOD
    df = _yf_download([f"{c}.AX" for c in codes], "1h", period)
    have = set(df.columns.get_level_values(0)) if hasattr(df.columns, "levels") else set()
    by_session: dict[str, dict[str, list[list[Any]]]] = {}
    for c in codes:
        sym = f"{c}.AX"
        if sym not in have:
            continue
        d = df[sym].dropna(how="all")
        for ts, row in d.iterrows():
            close = float(row["Close"])
            if not math.isfinite(close):
                continue
            by_session.setdefault(ts.strftime("%Y-%m-%d"), {}).setdefault(c, []).append(
                [
                    ts.strftime("%Y-%m-%dT%H:%M"),
                    int(ts.timestamp() * 1000),
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    close,
                    float(row["Volume"]),
                ]
            )
    today = datetime.now(UTC).date().isoformat()
    new = []
    for sess in sorted(by_session):
        if sess > today or store.has("intraday_1h", sess):
            continue
        store.write_once("intraday_1h", sess, intraday_doc(sess, by_session[sess]))
        new.append(sess)
    return {"period": period, "new": new, "codes": len(codes)}


def write_marks(store: ForwardStore) -> list[dict[str, Any]]:
    hist = PriceHistory.load(store)
    already = {m["mark_date"] for m in store.marks()}
    written = []
    for rec in due_marks(store, hist, already, lane_start=store.lane_start()):
        rec["created_ts"] = datetime.now(UTC).isoformat()
        if store.append_mark(rec):
            written.append(rec)
    return written


# ---------------------------------------------------------------------------
# cycle
# ---------------------------------------------------------------------------
def make_cycle(store: ForwardStore):
    def cycle(ctx: CycleContext) -> CycleResult:
        store.ensure_lane_start(ctx.cycle_date.isoformat())
        panels = refresh_panels(store)
        latest = panels["latest"] or (store.keys("short_panel") or [None])[-1]
        codes = sorted(panel_shorts(store.read("short_panel", latest))) if latest else []
        prices = refresh_prices(store, codes) if codes else {"skipped": "no panel"}
        intraday = refresh_intraday(store)
        marks = write_marks(store)
        extra = {
            "panel_tier": panels["tier"],
            "panel_latest": panels["latest"],
            "new_panels": len(panels["new"]),
            "new_price_sessions": len(prices.get("new", [])),
            "codes_with_data": prices.get("codes_with_data"),
            "new_1h_sessions": len(intraday.get("new", [])),
            "marks_written": len(marks),
            "marks_total": len(store.marks()),
            "marks_forward": sum(1 for m in store.marks() if m.get("forward")),
            "last_mark": marks[-1]["mark_date"] if marks else None,
            "last_spread_q1_q5": marks[-1]["spread_q1_q5"] if marks else None,
            "note": "no capital, no orders: equity is a constant",
        }
        log.info(json.dumps({"event": "asx_forward_cycle", **extra}))
        return CycleResult(
            equity=ctx.initial_capital,
            realised_pnl=0.0,
            signals_state={"marks_total": len(store.marks()), "panel_latest": panels["latest"]},
            extra_log=extra,
        )

    return cycle


def run_once(store: ForwardStore, checkpoint: Checkpoint, runner_log: Path) -> dict[str, Any]:
    prior = checkpoint.load()
    now = datetime.now(UTC)
    store.ensure_lane_start(now.date().isoformat())
    ctx = CycleContext(
        cycle_date=now.date(), cycle_ts=now.isoformat(), prior=prior, initial_capital=0.0
    )
    result = make_cycle(store)(ctx)
    record = {
        "cycle_ts": ctx.cycle_ts,
        "cycle_date": ctx.cycle_date.isoformat(),
        "mode": "once",
        **result.extra_log,
    }
    state = CheckpointState(
        cycle_ts=ctx.cycle_ts,
        cycle_date=ctx.cycle_date.isoformat(),
        last_completed_date=ctx.cycle_date.isoformat(),
        equity=result.equity,
        realised_pnl=0.0,
        signals_state=result.signals_state,
        pnl_record=record,
    )
    checkpoint.save(state)
    runner_log.parent.mkdir(parents=True, exist_ok=True)
    with open(runner_log, "a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def reconcile_v3(out: Path) -> dict[str, Any]:
    """F3: the mark function over the frozen substrate only."""
    hist = PriceHistory.load(store=None)
    recs = due_marks(store=None, hist=hist, already=set())
    spreads = [r["spread_q1_q5"] for r in recs]
    excess = [r["excess_q1_vs_ew"] for r in recs]

    def st(xs: list[float]) -> dict[str, Any]:
        n = len(xs)
        if n < 2:
            return {"n": n, "mean_pct": xs[0] * 100 if xs else None}
        m, sd = statistics.fmean(xs), statistics.stdev(xs)
        return {
            "n": n,
            "mean_pct": m * 100,
            "sd_pct": sd * 100,
            "t": m / (sd / n**0.5) if sd else None,
        }

    res = {
        "version": "V309",
        "what": "weekly mark over frozen v3 prices + committed 91-date short panel",
        "weeks": [
            (r["formed_date"], r["mark_date"], r["panel_date"], r["eligible_n"]) for r in recs
        ],
        "spread_q1_q5": st(spreads),
        "excess_q1_vs_ew": st(excess),
        "v303_reference_pct_per_week": 0.298,
        "comparator": recs[0]["comparator"] if recs else None,
        "marks": recs,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="V309 forward ASX lane")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--reconcile-v3", action="store_true")
    ap.add_argument("--max-cycles", type=int, default=None)
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    if args.reconcile_v3:
        res = reconcile_v3(ROOT / "data" / "asx_runs" / "v309_reconcile_v3.json")
        print(json.dumps({k: v for k, v in res.items() if k not in ("marks", "weeks")}, indent=1))
        print(
            "weeks:",
            len(res["weeks"]),
            res["weeks"][:2],
            "…",
            res["weeks"][-1:] if res["weeks"] else None,
        )
        return 0

    store = ForwardStore(args.root)
    sched_cfg = SchedulerConfig.from_env()
    checkpoint = Checkpoint(store.root / "checkpoints", keep_days=sched_cfg.checkpoint_keep_days)
    runner_log = store.root / "runner_log.jsonl"

    if args.once:
        rec = run_once(store, checkpoint, runner_log)
        print(json.dumps(rec, indent=1, sort_keys=True))
        return 0

    if not sched_cfg.enabled:
        log.error("SCHEDULER_ENABLED is off. Refusing to loop; use --once for a smoke cycle.")
        return 3
    scheduler = DailyScheduler(sched_cfg)
    log.info("asx_forward daemon: tick=%s UTC root=%s", sched_cfg.tick_utc, store.root)
    runner = LivePaperRunner(
        scheduler, checkpoint, make_cycle(store), initial_capital=0.0, pnl_log_path=runner_log
    )
    completed = runner.run(max_cycles=args.max_cycles)
    log.info("asx_forward daemon exit: %d cycles", completed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
