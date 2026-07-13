#!/usr/bin/env python3
"""
V253 weekly live-paper soak audit — a MEASUREMENT instrument, not a strategy tool.

Reads the daemon's per-cycle PnL log (``$OMEGA_LIVE_PAPER_DIR/logs/pnl_curve.jsonl``,
schema per ``omega/live_paper/runner.py:_run_one``) and reports, for the 90-day
soak (V253):

  1. Equity curve   — ASCII sparkline + first/last/min/max equity (stdlib only;
     no numpy/matplotlib dependency, honoring the repo's minimal-core constraint).
  2. Cadence gaps   — days where cycle_date advanced by >1 calendar day (a missed
     tick / feed outage); the FALSIFIER "feed unavailability > 5 consecutive days".
  3. Checkpoint gaps— cycles present in the checkpoint dir but absent from the log
     (or vice-versa) — a crash-recovery integrity check.
  4. Drift alert    — realised cumulative PnL vs the V253 pre-registered band
     N(mean, sd) derived in training_log/V253.md. Flags |cum - expected| > 5·SE
     (the "measurement instrument problem, not alpha problem" falsifier).

This script NEVER touches strategy code, never places an order, and never mutates
the log. It is read-only. Anti-Goodhart: a drift alert is a FINDING to investigate
(feed drift? code-path bug?), never a signal to adjust the strategy.

Usage:
  python3 scripts/v253_weekly_audit.py \
      [--pnl-log <path>] [--checkpoint-dir <path>] [--json]

Defaults resolve from LivePaperConfig (OMEGA_AUDIT_OUTPUT_DIR / OMEGA_LIVE_PAPER_DIR).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import date
from pathlib import Path

# ── V253 pre-registered distribution (see training_log/V253.md) ────────────────
# Mean is the standing-baseline pooled per-cycle expectation; SD is grounded in the
# three per-regime sentinel ledgers' per-cycle PnL variance (recent ≈ $434,
# pooled ≈ $499). The falsifier keys off SD/SE, not the mean level.
PREREG_MEAN_PER_CYCLE = 3.63      # $/cycle, pooled (task-registered nominal)
PREREG_SD_PER_CYCLE = 499.0       # $/cycle, from backtest per-cycle variance
DRIFT_SIGMA = 5.0                 # |cum - expected| > 5·SE ⇒ measurement-instrument alert
MAX_FEED_GAP_DAYS = 5             # falsifier: >5 consecutive missing days


def _default_log() -> Path:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from omega.live_paper.config import LivePaperConfig

        return LivePaperConfig().log_dir / "pnl_curve.jsonl"
    except Exception:
        return Path("logs/pnl_curve.jsonl")


def _default_ckpt() -> Path:
    try:
        from omega.live_paper.config import checkpoint_dir

        return checkpoint_dir()
    except Exception:
        return Path("checkpoint")


def _sparkline(values: list[float]) -> str:
    if not values:
        return ""
    blocks = "▁▂▃▄▅▆▇█"
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    return "".join(blocks[min(len(blocks) - 1, int((v - lo) / span * (len(blocks) - 1)))] for v in values)


def load_pnl_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if ln:
            rows.append(json.loads(ln))
    rows.sort(key=lambda r: r.get("cycle_ts", ""))
    return rows


def cadence_gaps(rows: list[dict]) -> list[dict]:
    """Runs of missing calendar days between consecutive cycle_dates."""
    gaps = []
    prev: date | None = None
    for r in rows:
        cur = date.fromisoformat(r["cycle_date"])
        if prev is not None:
            delta = (cur - prev).days
            if delta > 1:
                gaps.append({"from": prev.isoformat(), "to": cur.isoformat(), "missing_days": delta - 1})
        prev = cur
    return gaps


def checkpoint_gaps(rows: list[dict], ckpt_dir: Path) -> dict:
    """Cross-check log cycle_dates against persisted checkpoint files."""
    log_dates = {r["cycle_date"] for r in rows}
    ckpt_dates: set[str] = set()
    if ckpt_dir.exists():
        for p in ckpt_dir.glob("*.json"):
            try:
                st = json.loads(p.read_text())
                d = st.get("cycle_date") or st.get("last_completed_date")
                if d:
                    ckpt_dates.add(str(d))
            except Exception:
                continue
    return {
        "in_log_not_checkpoint": sorted(log_dates - ckpt_dates),
        "in_checkpoint_not_log": sorted(ckpt_dates - log_dates),
    }


def drift_report(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n_cycles": 0, "alert": False, "reason": "no cycles yet"}
    # Prefer realised increments; fall back to equity deltas.
    equity = [float(r.get("equity", 0.0)) for r in rows]
    realised = [float(r.get("realised_pnl", 0.0)) for r in rows]
    cum_realised = realised[-1] if realised else (equity[-1] - equity[0])
    expected = PREREG_MEAN_PER_CYCLE * n
    se = PREREG_SD_PER_CYCLE / math.sqrt(n)
    band = DRIFT_SIGMA * se
    dev = cum_realised - expected
    return {
        "n_cycles": n,
        "cum_realised_pnl": round(cum_realised, 2),
        "expected_pnl": round(expected, 2),
        "se": round(se, 3),
        "drift_band_5se": round(band, 2),
        "deviation": round(dev, 2),
        "alert": abs(dev) > band,
        "reason": (
            f"|deviation ${dev:,.0f}| exceeds 5·SE band ${band:,.0f} — MEASUREMENT-instrument"
            f" alert (investigate feed drift / code-path bug; DO NOT touch strategy)"
            if abs(dev) > band else "within 5·SE of pre-registered mean"
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="V253 weekly live-paper soak audit (read-only)")
    ap.add_argument("--pnl-log", type=Path, default=None)
    ap.add_argument("--checkpoint-dir", type=Path, default=None)
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON only")
    args = ap.parse_args()

    log_path = args.pnl_log or _default_log()
    ckpt_dir = args.checkpoint_dir or _default_ckpt()

    rows = load_pnl_log(log_path)
    equity = [float(r.get("equity", 0.0)) for r in rows]
    cadence = cadence_gaps(rows)
    ckpt = checkpoint_gaps(rows, ckpt_dir)
    drift = drift_report(rows)
    max_gap = max((g["missing_days"] for g in cadence), default=0)

    summary = {
        "pnl_log": str(log_path),
        "checkpoint_dir": str(ckpt_dir),
        "n_cycles": len(rows),
        "first_cycle": rows[0]["cycle_date"] if rows else None,
        "last_cycle": rows[-1]["cycle_date"] if rows else None,
        "equity_first": round(equity[0], 2) if equity else None,
        "equity_last": round(equity[-1], 2) if equity else None,
        "equity_min": round(min(equity), 2) if equity else None,
        "equity_max": round(max(equity), 2) if equity else None,
        "cadence_gaps": cadence,
        "max_consecutive_missing_days": max_gap,
        "feed_falsifier_tripped": max_gap > MAX_FEED_GAP_DAYS,
        "checkpoint_gaps": ckpt,
        "drift": drift,
    }

    if args.json:
        print(json.dumps(summary, indent=1))
        return 0

    print("=== V253 weekly live-paper soak audit ===")
    print(f"log: {log_path}")
    if not rows:
        print("  no PnL cycles logged yet — soak not started or log path wrong.")
        return 0
    print(f"  cycles: {len(rows)}  ({summary['first_cycle']} → {summary['last_cycle']})")
    print(f"  equity: ${summary['equity_first']:,.0f} → ${summary['equity_last']:,.0f} "
          f"(min ${summary['equity_min']:,.0f} / max ${summary['equity_max']:,.0f})")
    print(f"  curve : {_sparkline(equity)}")
    print(f"  cadence gaps: {len(cadence)}  (max consecutive missing = {max_gap}d"
          f"{'  ⚠ FEED FALSIFIER TRIPPED' if summary['feed_falsifier_tripped'] else ''})")
    if ckpt["in_log_not_checkpoint"] or ckpt["in_checkpoint_not_log"]:
        print(f"  ⚠ checkpoint gaps: log-only={ckpt['in_log_not_checkpoint']} "
              f"ckpt-only={ckpt['in_checkpoint_not_log']}")
    else:
        print("  checkpoint gaps: none (log ↔ checkpoint consistent)")
    d = drift
    flag = "⚠ DRIFT ALERT" if d["alert"] else "ok"
    print(f"  drift : cum ${d['cum_realised_pnl']:,.0f} vs expected ${d['expected_pnl']:,.0f} "
          f"(dev ${d['deviation']:,.0f}, 5·SE band ${d['drift_band_5se']:,.0f})  [{flag}]")
    print(f"          {d['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
