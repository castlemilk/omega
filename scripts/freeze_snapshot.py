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


def fetch_ohlcv_historical(symbols: list[str], start_date: str, end_date: str) -> dict:
    """
    Fetch historical OHLCV for a specific date range using ccxt (Binance public API).

    Returns {symbol: {close: [...], open: [...], high: [...], low: [...], volume: [...],
                       timestamps: [...], meta: {...}}}.
    """
    try:
        import ccxt
    except ImportError as exc:
        raise RuntimeError("ccxt not installed. Run: pip install ccxt") from exc

    from datetime import UTC
    exchange = ccxt.binance({"enableRateLimit": True})
    start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    since_ms = int(start_dt.timestamp() * 1000)
    days = (end_dt - start_dt).days + 5

    result = {}
    for sym in symbols:
        # ccxt uses BTC/USDT not BTCUSDT
        ccxt_sym = sym[:-4] + "/" + sym[-4:] if sym.endswith("USDT") else sym
        logger.info("Fetching %s  %s → %s  (%d bars)…", ccxt_sym, start_date, end_date, days)
        try:
            raw = exchange.fetch_ohlcv(ccxt_sym, timeframe="1d", since=since_ms, limit=days)
        except Exception as exc:
            logger.warning("  %s: fetch failed: %s", sym, exc)
            continue

        closes, opens, highs, lows, volumes, timestamps = [], [], [], [], [], []
        for row in raw:
            bar_date = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).date().isoformat()
            if bar_date < start_date or bar_date > end_date:
                continue
            timestamps.append(int(row[0] // 1000))
            opens.append(float(row[1]))
            highs.append(float(row[2]))
            lows.append(float(row[3]))
            closes.append(float(row[4]))
            volumes.append(float(row[5]))

        if not closes:
            logger.warning("  %s: no bars in range %s – %s", sym, start_date, end_date)
            continue

        result[sym] = {
            "close": closes,
            "open": opens,
            "high": highs,
            "low": lows,
            "volume": volumes,
            "timestamps": timestamps,
            "meta": {"symbol": sym, "regularMarketPrice": closes[-1]},
        }
        logger.info("  %s: %d bars", sym, len(closes))

    return result


def build_snapshot(
    symbols: list[str],
    lookback: int = 90,
    start_date: str | None = None,
    end_date: str | None = None,
    snapshot_id: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    if start_date and end_date:
        logger.info("Building historical snapshot %s → %s…", start_date, end_date)
        ohlcv = fetch_ohlcv_historical(symbols, start_date, end_date)
        sid = snapshot_id or f"snap_{start_date.replace('-', '')}_{end_date.replace('-', '')}"
        actual_start, actual_end = start_date, end_date
    else:
        logger.info("Building recent snapshot (last %d days)…", lookback)
        ohlcv = fetch_ohlcv(symbols, lookback)
        sid = snapshot_id or f"snap_{today.replace('-', '')}"
        # Compute date range from timestamps
        all_ts: list[int] = []
        for d in ohlcv.values():
            ts = d.get("timestamps", [])
            if ts:
                all_ts.extend(ts)
        if all_ts:
            actual_start = datetime.fromtimestamp(min(all_ts), tz=timezone.utc).strftime("%Y-%m-%d")
            actual_end = datetime.fromtimestamp(max(all_ts), tz=timezone.utc).strftime("%Y-%m-%d")
        else:
            actual_end = today
            actual_start = f"{now.year}-{now.month:02d}-{max(1, now.day - lookback):02d}"

    if not ohlcv:
        raise RuntimeError("No OHLCV data fetched — check exchange connectivity")

    macro = fetch_macro()

    snap: dict = {
        "_snapshot_id": sid,
        "_created_at": int(time.time()),
        "_date_range": [actual_start, actual_end],
        "_symbols": list(ohlcv.keys()),
        "_lookback": lookback,
        **ohlcv,
        "_macro": macro,
    }

    series_lengths = {sym: len(ohlcv[sym]["close"]) for sym in ohlcv}
    logger.info(
        "Snapshot %s: %d symbols, %d–%d bars each",
        sid, len(ohlcv),
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
        help="Days of OHLCV history to fetch (recent mode only, default: 90)"
    )
    parser.add_argument(
        "--start-date", type=str, default=None, metavar="YYYY-MM-DD",
        help="Historical window start date (enables historical mode, requires ccxt)"
    )
    parser.add_argument(
        "--end-date", type=str, default=None, metavar="YYYY-MM-DD",
        help="Historical window end date (requires --start-date)"
    )
    parser.add_argument(
        "--out", type=str, default=None,
        help="Output path (default: data/snapshots/snap_YYYYMMDD.json or derived from dates)"
    )
    parser.add_argument(
        "--id", type=str, default=None, dest="snapshot_id",
        help="Snapshot ID string (default: derived from dates)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-fetch even if output file already exists"
    )
    parser.add_argument(
        "--symbols", type=str, default=None,
        help="Comma-separated symbol list (default: all 13 pairs)"
    )
    args = parser.parse_args()

    if bool(args.start_date) != bool(args.end_date):
        parser.error("--start-date and --end-date must be used together")

    _load_env()

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else ALL_SYMBOLS
    )

    # Determine output path
    if args.out:
        out_path = Path(args.out)
    elif args.start_date and args.end_date:
        sid = args.snapshot_id or f"snap_{args.start_date.replace('-','')}_{args.end_date.replace('-','')}"
        out_path = SNAPSHOT_DIR / f"{sid}.json"
    else:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        out_path = SNAPSHOT_DIR / f"snap_{today}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not args.force:
        logger.info("Snapshot already exists: %s (use --force to overwrite)", out_path)
        snap = json.loads(out_path.read_text())
        logger.info(
            "  id=%s  range=%s → %s  symbols=%d",
            snap.get("_snapshot_id"),
            snap.get("_date_range", ["?", "?"])[0],
            snap.get("_date_range", ["?", "?"])[-1],
            len(snap.get("_symbols", [])),
        )
        return

    snap = build_snapshot(
        symbols,
        lookback=args.lookback,
        start_date=args.start_date,
        end_date=args.end_date,
        snapshot_id=args.snapshot_id,
    )

    out_path.write_text(json.dumps(snap, default=str))
    size_kb = out_path.stat().st_size / 1024
    logger.info("Snapshot written → %s (%.1f KB)", out_path, size_kb)
    logger.info(
        "Use with: python3 scripts/run_training.py --backtest-snapshot %s --seed 42", out_path
    )


if __name__ == "__main__":
    main()
