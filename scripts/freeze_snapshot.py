#!/usr/bin/env python3
"""
scripts/freeze_snapshot.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Fetch and freeze a versioned OHLCV + macro snapshot for deterministic backtesting.

The snapshot is written to data/snapshots/snap_YYYYMMDD.json and never modified
after creation. All subsequent version comparisons (V128, V129, …) that reference
the same snapshot file run against identical historical market data.

Usage:
    python3 scripts/freeze_snapshot.py
    python3 scripts/freeze_snapshot.py --lookback 90 --out data/snapshots/snap_custom.json
    python3 scripts/freeze_snapshot.py --force   # re-fetch even if today's snapshot exists

Output:
    data/snapshots/snap_YYYYMMDD.json

Format:
    {
      "_snapshot_id": "snap_20260414",
      "_created_at": 1744636800,
      "_date_range": ["2026-01-14", "2026-04-14"],
      "_symbols": [...],
      "ETHUSDT": {"close": [...], "open": [...], ...},
      ...
      "_macro": {"funding_rates": {...}, "fear_greed": N, "btc_dominance": F}
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("freeze_snapshot")

SNAPSHOT_DIR = ROOT / "data" / "snapshots"

ALL_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOTUSDT", "AVAXUSDT", "LINKUSDT", "MATICUSDT",
    "NEARUSDT", "SUIUSDT", "ARBUSDT",
]


def _load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def fetch_ohlcv(symbols: list[str], lookback: int) -> dict:
    """
    Fetch OHLCV for all symbols via DataIngestionNode.
    Returns {symbol: {close: [...], open: [...], high: [...], low: [...], volume: [...],
                       timestamps: [...], meta: {...}}}.
    """
    from omega.core.actions import NodeAction
    from omega.core.node import NodeInput
    from omega.nodes.victoria.data_ingestion import DataIngestionNode

    logger.info("Fetching OHLCV for %d symbols, lookback=%d days…", len(symbols), lookback)
    ingestion = DataIngestionNode()
    ingestion._pairs = symbols

    out = ingestion.execute(
        NodeInput(
            action=NodeAction.FETCH_MARKET_DATA.value,
            parameters={"limit": lookback},
        )
    )
    if not out.success or not out.result:
        raise RuntimeError(f"DataIngestionNode failed: {out.error}")

    market_data: dict = out.result
    result = {}
    for sym in symbols:
        if sym not in market_data:
            logger.warning("Symbol %s missing from fetch result", sym)
            continue
        d = market_data[sym]
        if not isinstance(d, dict):
            logger.warning("Symbol %s returned non-dict: %r", sym, type(d))
            continue
        closes = d.get("close") or d.get("adjclose") or []
        if not closes:
            logger.warning("Symbol %s has no close data", sym)
            continue

        # Normalise keys — DataIngestionNode uses various field names
        result[sym] = {
            "close":      list(d.get("close") or d.get("adjclose", [])),
            "open":       list(d.get("open", [])),
            "high":       list(d.get("high", [])),
            "low":        list(d.get("low", [])),
            "volume":     list(d.get("volume", [])),
            "timestamps": list(d.get("timestamps") or d.get("timestamp", [])),
            "meta":       dict(d.get("meta", {"symbol": sym})),
        }
        n = len(result[sym]["close"])
        logger.info("  %s: %d bars", sym, n)

    return result


def fetch_macro() -> dict:
    """Fetch current macro state: funding rates, fear/greed, BTC dominance."""
    macro: dict = {}

    # Funding rates via MacroDataCache (OKX primary)
    try:
        from omega.nodes.victoria.data_cache import MacroDataCache
        cache = MacroDataCache()
        funding = {}
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "NEARUSDT", "ARBUSDT"]:
            rate = cache.get_funding_rate(sym)
            if rate is not None:
                funding[sym] = rate
        macro["funding_rates"] = funding
        logger.info("Macro: %d funding rates fetched", len(funding))
    except Exception as exc:
        logger.warning("Macro: funding rates unavailable: %s", exc)
        macro["funding_rates"] = {}

    # Fear & Greed Index
    try:
        from omega.nodes.victoria.data_providers import FearGreedProvider
        fg = FearGreedProvider()
        result = fg.get_fear_greed()
        macro["fear_greed"] = int(result) if result is not None else None
        logger.info("Macro: fear_greed=%s", macro["fear_greed"])
    except Exception as exc:
        logger.warning("Macro: fear/greed unavailable: %s", exc)
        macro["fear_greed"] = None

    # BTC dominance (best-effort via CoinGecko)
    try:
        from omega.nodes.victoria.data_providers import CoinGeckoProvider
        cg = CoinGeckoProvider()
        dom = cg.get_btc_dominance()
        macro["btc_dominance"] = float(dom) if dom is not None else None
        logger.info("Macro: btc_dominance=%.3f", macro["btc_dominance"] or 0)
    except Exception as exc:
        logger.warning("Macro: btc_dominance unavailable: %s", exc)
        macro["btc_dominance"] = None

    return macro


def build_snapshot(symbols: list[str], lookback: int) -> dict:
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    logger.info("Building snapshot for %s…", today)
    ohlcv = fetch_ohlcv(symbols, lookback)

    if not ohlcv:
        raise RuntimeError("No OHLCV data fetched — check exchange connectivity")

    # Compute actual date range from timestamps where available
    all_ts: list[int] = []
    for d in ohlcv.values():
        ts = d.get("timestamps", [])
        if ts:
            all_ts.extend(ts)
    if all_ts:
        start_dt = datetime.fromtimestamp(min(all_ts), tz=timezone.utc).strftime("%Y-%m-%d")
        end_dt = datetime.fromtimestamp(max(all_ts), tz=timezone.utc).strftime("%Y-%m-%d")
    else:
        end_dt = today
        start_dt = f"{now.year}-{now.month:02d}-{max(1, now.day - lookback):02d}"

    macro = fetch_macro()

    snap: dict = {
        "_snapshot_id": f"snap_{today.replace('-', '')}",
        "_created_at": int(time.time()),
        "_date_range": [start_dt, end_dt],
        "_symbols": list(ohlcv.keys()),
        "_lookback": lookback,
        **ohlcv,
        "_macro": macro,
    }

    series_lengths = {sym: len(ohlcv[sym]["close"]) for sym in ohlcv}
    logger.info(
        "Snapshot %s: %d symbols, %d–%d bars each",
        snap["_snapshot_id"],
        len(ohlcv),
        min(series_lengths.values()),
        max(series_lengths.values()),
    )
    return snap


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Freeze a versioned OHLCV snapshot for deterministic backtesting"
    )
    parser.add_argument(
        "--lookback", type=int, default=90,
        help="Days of OHLCV history to fetch per symbol (default: 90)"
    )
    parser.add_argument(
        "--out", type=str, default=None,
        help="Output path (default: data/snapshots/snap_YYYYMMDD.json)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-fetch even if today's snapshot already exists"
    )
    parser.add_argument(
        "--symbols", type=str, default=None,
        help="Comma-separated symbol list (default: all 13 pairs)"
    )
    args = parser.parse_args()

    _load_env()

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else ALL_SYMBOLS
    )

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_path = Path(args.out) if args.out else SNAPSHOT_DIR / f"snap_{today}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not args.force:
        logger.info("Snapshot already exists: %s (use --force to overwrite)", out_path)
        snap = json.loads(out_path.read_text())
        logger.info(
            "  id=%s  created=%s  symbols=%d",
            snap.get("_snapshot_id"),
            datetime.fromtimestamp(snap.get("_created_at", 0), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            len(snap.get("_symbols", [])),
        )
        return

    snap = build_snapshot(symbols, args.lookback)

    out_path.write_text(json.dumps(snap, default=str))
    size_kb = out_path.stat().st_size / 1024
    logger.info("Snapshot written → %s (%.1f KB)", out_path, size_kb)
    logger.info(
        "Use with: python3 scripts/run_training.py --backtest-snapshot %s", out_path
    )


if __name__ == "__main__":
    main()
