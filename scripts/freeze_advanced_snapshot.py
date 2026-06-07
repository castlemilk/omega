#!/usr/bin/env python3
"""
V215 — one-shot capture of signals_advanced.py live HTTP fetches into a frozen
snapshot committed to the repo (data/frozen_advanced_signals.json).

This runs the UNFENCED live fetch path once (no OMEGA_FROZEN_CACHE, no backtest
HTTP guard) and records the values that `BTCDominanceSignal` and
`LongShortRatioSignal` would have fetched. Subsequent frozen backtests read this
file deterministically instead of hitting the network — closing the
`--frozen-cache` hole V214 localized.

Re-run only to refresh the snapshot (a deliberate, committed baseline change).

Usage:
    python3 scripts/freeze_advanced_snapshot.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# Ensure unfenced: this tool WANTS the live fetch.
os.environ.pop("OMEGA_FROZEN_CACHE", None)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "frozen_advanced_signals.json"


def _fetch_long_short_ratio() -> float | None:
    """Binance futures global long/short account ratio (often geo-blocked from US)."""
    url = (
        "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
        "?symbol=BTCUSDT&period=1h&limit=1"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return float(data[0]["longShortRatio"])
    except Exception as exc:  # noqa: BLE001
        print(f"  long_short_ratio: live fetch failed ({type(exc).__name__}: {exc}) "
              f"— using neutral fallback 1.0 (balanced positioning)")
        return None


def main() -> int:
    from omega.nodes.victoria.signals_advanced import BTCDominanceSignal

    print("V215 frozen-advanced-signals snapshot capture (unfenced live fetch):")

    btc_dom, mc_change = BTCDominanceSignal._fetch_dominance()
    if btc_dom is None:
        print("  btc_dominance: live fetch failed — using neutral fallback 45.0 "
              "(balanced_market)")
        btc_dom = 45.0
    else:
        print(f"  btc_dominance_pct      = {btc_dom}")
    if mc_change is None:
        mc_change = 0.0
    print(f"  market_cap_change_24h  = {mc_change}")

    ls_ratio = _fetch_long_short_ratio()
    if ls_ratio is None:
        ls_ratio = 1.0  # neutral / balanced_positioning
    print(f"  long_short_ratio       = {ls_ratio}")

    snapshot = {
        "_comment": (
            "V215 frozen snapshot of signals_advanced.py live HTTP fetches. "
            "Read by signals_advanced.py when OMEGA_FROZEN_CACHE=1 so frozen "
            "backtests are deterministic (closes the --frozen-cache hole V214 "
            "localized). Regenerate with scripts/freeze_advanced_snapshot.py."
        ),
        "_captured_utc": datetime.now(UTC).isoformat(),
        "btc_dominance_pct": round(float(btc_dom), 4),
        "market_cap_change_24h": round(float(mc_change), 4),
        "long_short_ratio": round(float(ls_ratio), 4),
    }
    OUT.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"\nWrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
