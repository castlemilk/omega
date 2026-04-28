#!/usr/bin/env python3
"""Capture 15-min OHLCV snapshot from Binance fapi for backtest replay.

Output: data/snapshots/snap_15min_live.json with the same structure as
snap_20260414.json but bars at 15-min resolution. ~672 bars = 7 days of history.

Usage: python3 scripts/capture_15min_snapshot.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("data/snapshots/snap_15min_live.json")
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOTUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT",
    "NEARUSDT", "ARBUSDT",
]
INTERVAL = "15m"
LIMIT = 672  # 7 days × 96 bars/day = 672

_BINANCE_KLINES = "https://fapi.binance.com/fapi/v1/klines"


def _fetch_klines(symbol: str, interval: str, limit: int) -> list[list]:
    url = _BINANCE_KLINES + "?" + urllib.parse.urlencode({
        "symbol": symbol, "interval": interval, "limit": limit,
    })
    req = urllib.request.Request(url, headers={"User-Agent": "omega/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def main() -> int:
    out: dict = {
        "_snapshot_id": "snap_15min_live",
        "_created_at": int(time.time()),
        "_date_range": [None, None],
        "_symbols": SYMBOLS,
        "_lookback": LIMIT,
        "_interval": INTERVAL,
    }
    first_ts = None
    last_ts = None
    for sym in SYMBOLS:
        try:
            bars = _fetch_klines(sym, INTERVAL, LIMIT)
        except Exception as exc:
            print(f"  {sym}: FAILED — {exc}", file=sys.stderr)
            continue
        # Binance kline: [openTime, open, high, low, close, volume, closeTime, ...]
        ts = [int(b[0]) // 1000 for b in bars]
        opens = [float(b[1]) for b in bars]
        highs = [float(b[2]) for b in bars]
        lows = [float(b[3]) for b in bars]
        closes = [float(b[4]) for b in bars]
        vols = [float(b[5]) for b in bars]
        out[sym] = {
            "close": closes,
            "open": opens,
            "high": highs,
            "low": lows,
            "volume": vols,
            "timestamps": ts,
            "meta": {"interval": INTERVAL, "source": "binance_fapi"},
        }
        if first_ts is None or ts[0] < first_ts:
            first_ts = ts[0]
        if last_ts is None or ts[-1] > last_ts:
            last_ts = ts[-1]
        print(f"  {sym}: {len(ts)} bars  {datetime.fromtimestamp(ts[0], timezone.utc).date()} → "
              f"{datetime.fromtimestamp(ts[-1], timezone.utc).date()}")

    if first_ts and last_ts:
        out["_date_range"] = [
            datetime.fromtimestamp(first_ts, timezone.utc).strftime("%Y-%m-%d"),
            datetime.fromtimestamp(last_ts, timezone.utc).strftime("%Y-%m-%d"),
        ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f)
    print(f"\nWrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
