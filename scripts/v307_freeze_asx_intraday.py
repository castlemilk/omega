#!/usr/bin/env python3
"""V307 — freeze the ASX intraday corpus (1h study substrate, 5m audit corpus, daily pair).

Pre-registration: ``training_log/V307_ASX_INTRADAY.md``.

Universe: the top ``--top`` codes by median AUD dollar-volume over the 250 sessions
ending ``--as-of`` (the 1h window's FIRST day), read from the frozen v3 substrate,
so membership is decided with information available at the start of the window.

Source: yfinance ``{CODE}.AX``. It is a ROLLING window — ``period=730d`` from
today — so this is a freeze-ONCE: the script refuses to overwrite an existing
manifest without ``--force``, and ``--verify`` hashes the committed files against
the manifest rather than re-downloading (a re-download cannot be byte-identical).

Per code, three files:
  1h/{CODE}.json.gz     730d of hourly bars — the study substrate (committed)
  5m/{CODE}.json.gz     60d of 5-minute bars — audit only (gitignored)
  daily/{CODE}.json.gz  730d of daily close + adjusted close — for ex-dividend
                        detection on the overnight bucket (committed)

Frozen files carry only data provenance (no wall-clock); the download date lives
in MANIFEST.json alone. Holes (codes yfinance cannot serve, or serves partially)
are recorded in the manifest, not dropped.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
import warnings
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from omega.nodes.asx.intraday import (  # noqa: E402
    COLUMNS,
    FROZEN_INTRADAY,
    TZ,
    encode_frozen,
    md5_of,
)

V3 = ROOT / "data" / "frozen_series" / "asx" / "v3"

INTERVAL_PERIOD = {"1h": "730d", "5m": "60d", "1d": "730d"}
# Bars per session at each interval, for the coverage fraction. 1d is one bar.
EXPECTED_PER_SESSION = {"1h": 7, "5m": 74, "1d": 1}


# ---------------------------------------------------------------------------
# universe
# ---------------------------------------------------------------------------
def pit_universe(as_of: str, top: int, window: int = 250) -> list[dict[str, Any]]:
    """Top ``top`` codes by median dollar ADV over ``window`` sessions ending ``as_of``."""
    names = json.loads((V3 / "codes.json").read_text())
    rows: list[tuple[str, float]] = []
    for f in sorted((V3 / "prices").glob("*.csv")):
        code = f.stem
        with f.open() as fh:
            hist = [r for r in csv.DictReader(fh) if r["date"] <= as_of]
        if len(hist) < window:
            continue
        tail = hist[-window:]
        adv = [float(r["close"]) * float(r["volume"]) for r in tail if r["volume"] and r["close"]]
        if len(adv) < int(0.8 * window):
            continue
        rows.append((code, statistics.median(adv)))
    rows.sort(key=lambda x: -x[1])
    return [
        {"rank": i + 1, "code": c, "median_adv_aud": adv, "name": names.get(c, {}).get("name", "")}
        for i, (c, adv) in enumerate(rows[:top])
    ]


# ---------------------------------------------------------------------------
# download → frozen doc
# ---------------------------------------------------------------------------
def _download(symbols: list[str], interval: str) -> Any:
    import yfinance as yf

    warnings.filterwarnings("ignore")
    return yf.download(
        symbols,
        interval=interval,
        period=INTERVAL_PERIOD[interval],
        progress=False,
        auto_adjust=False,
        group_by="ticker",
        threads=True,
    )


def _frame_for(df: Any, symbol: str) -> Any:
    try:
        d = df[symbol]
    except KeyError:
        return None
    d = d.dropna(how="all")
    return d if len(d) else None


def intraday_doc(code: str, symbol: str, interval: str, d: Any) -> dict[str, Any]:
    import math

    bars: list[list[Any]] = []
    dropped = 0
    for ts, row in d.iterrows():
        close = float(row["Close"])
        if not math.isfinite(close):
            dropped += 1
            continue
        bars.append(
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
    bars.sort(key=lambda b: b[1])
    n_sessions = len({b[0][:10] for b in bars})
    return {
        "code": code,
        "symbol": symbol,
        "interval": interval,
        "source": f"yfinance download interval={interval} period={INTERVAL_PERIOD[interval]} auto_adjust=False",
        "tz": TZ,
        "columns": list(COLUMNS),
        "n_bars": len(bars),
        "n_sessions": n_sessions,
        "dropped_nan_close": dropped,
        "first_ts": bars[0][0] if bars else None,
        "last_ts": bars[-1][0] if bars else None,
        "bars": bars,
    }


def daily_doc(code: str, symbol: str, d: Any) -> dict[str, Any]:
    import math

    rows: list[list[Any]] = []
    for ts, row in d.iterrows():
        close, adj = float(row["Close"]), float(row["Adj Close"])
        if not (math.isfinite(close) and math.isfinite(adj)):
            continue
        rows.append([ts.strftime("%Y-%m-%d"), close, adj, float(row["Volume"])])
    rows.sort(key=lambda r: r[0])
    return {
        "code": code,
        "symbol": symbol,
        "interval": "1d",
        "source": "yfinance download interval=1d period=730d auto_adjust=False",
        "columns": ["date", "close", "adjusted_close", "volume"],
        "n_rows": len(rows),
        "first_date": rows[0][0] if rows else None,
        "last_date": rows[-1][0] if rows else None,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# freeze
# ---------------------------------------------------------------------------
def freeze(out: Path, universe: list[dict[str, Any]], intervals: list[str]) -> dict[str, Any]:
    symbols = [f"{u['code']}.AX" for u in universe]
    manifest: dict[str, Any] = {
        "freeze": "v307_asx_intraday",
        "downloaded_on": time.strftime("%Y-%m-%d"),
        "tz": TZ,
        "source": "yfinance (rolling window — freeze-once; --verify hashes, never re-downloads)",
        "universe": universe,
        "intervals": intervals,
        "files": {},
        "holes": [],
    }
    for interval in intervals:
        print(f"[freeze] downloading {len(symbols)} symbols at {interval} …", flush=True)
        t0 = time.time()
        df = _download(symbols, interval)
        print(f"[freeze]   {time.time() - t0:.1f}s", flush=True)
        sub = "daily" if interval == "1d" else interval
        (out / sub).mkdir(parents=True, exist_ok=True)
        for u in universe:
            code, symbol = u["code"], f"{u['code']}.AX"
            d = _frame_for(df, symbol)
            if d is None:
                manifest["holes"].append({"code": code, "interval": interval, "reason": "no data"})
                continue
            doc = (
                daily_doc(code, symbol, d)
                if interval == "1d"
                else intraday_doc(code, symbol, interval, d)
            )
            blob = encode_frozen(doc)
            path = out / sub / f"{code}.json.gz"
            path.write_bytes(blob)
            n = doc.get("n_bars", doc.get("n_rows", 0))
            entry: dict[str, Any] = {"md5": md5_of(blob), "n": n}
            if interval != "1d":
                entry["n_sessions"] = doc["n_sessions"]
                entry["first_ts"], entry["last_ts"] = doc["first_ts"], doc["last_ts"]
            manifest["files"][f"{sub}/{code}.json.gz"] = entry
        # Partial coverage is a hole too: flag anything under 90% of the modal bar count.
        counts = [v["n"] for k, v in manifest["files"].items() if k.startswith(f"{sub}/")]
        if counts:
            modal = statistics.mode(counts)
            for k, v in manifest["files"].items():
                if k.startswith(f"{sub}/") and v["n"] < 0.9 * modal:
                    manifest["holes"].append(
                        {
                            "code": k.split("/")[1][:-8],
                            "interval": interval,
                            "reason": f"partial: {v['n']} bars vs modal {modal}",
                        }
                    )
    return manifest


def verify(out: Path) -> int:
    man = json.loads((out / "MANIFEST.json").read_text())
    ok = bad = missing = 0
    for rel, info in sorted(man["files"].items()):
        p = out / rel
        if not p.exists():
            missing += 1
            print(f"  MISSING {rel}")
            continue
        got = md5_of(p.read_bytes())
        if got != info["md5"]:
            bad += 1
            print(f"  DIFFER  {rel}: {info['md5']} -> {got}")
        else:
            ok += 1
    print(f"[verify] identical={ok} differing={bad} missing={missing}")
    if bad or missing:
        print("BYTE-IDENTITY: FAIL")
        return 1
    print("BYTE-IDENTITY: PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="V307 ASX intraday freeze")
    ap.add_argument("--as-of", default="2023-10-26", help="universe selection date (window start)")
    ap.add_argument("--top", type=int, default=120)
    ap.add_argument("--intervals", default="1h,5m,1d")
    ap.add_argument("--out", type=Path, default=FROZEN_INTRADAY)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite an existing freeze")
    args = ap.parse_args()

    out: Path = args.out
    if args.verify:
        return verify(out)
    if (out / "MANIFEST.json").exists() and not args.force:
        print(f"REFUSED: {out / 'MANIFEST.json'} exists — this is a freeze-once; pass --force")
        return 2

    universe = pit_universe(args.as_of, args.top)
    print(
        f"[freeze] universe: {len(universe)} codes as of {args.as_of}; "
        f"rank {len(universe)} ADV = {universe[-1]['median_adv_aud'] / 1e6:.1f}M AUD"
    )
    manifest = freeze(out, universe, args.intervals.split(","))
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"[freeze] files={len(manifest['files'])} holes={len(manifest['holes'])}")
    for h in manifest["holes"]:
        print(f"  HOLE {h}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
