#!/usr/bin/env python3
"""Polymarket × Binance gap probe — Phase 0 telemetry MVP.

Pulls active BTC/ETH binary markets from Polymarket, computes Binance-implied
fair-value probabilities, logs the gap. Read-only; no orders.

Goals:
  - Validate that latency-arb gaps actually exist from our infrastructure.
  - Build a sample distribution before committing to the full Polymarket project.

Output: data/polymarket_gap_probe/{date}_{run_id}.jsonl, one row per market×poll.

Usage: python3 scripts/polymarket_gap_probe.py [--poll-seconds 5] [--duration-min 5]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path("data/polymarket_gap_probe")
_POLY_MARKETS = "https://gamma-api.polymarket.com/markets"
_POLY_BOOK = "https://clob.polymarket.com/book"
_BINANCE_TICKER = "https://fapi.binance.com/fapi/v1/ticker/price"


def _http_get(url: str, timeout: float = 8.0) -> dict | list | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "omega-poly-probe/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as exc:
        print(f"  http fetch failed {url[:80]}…: {exc}", file=sys.stderr)
        return None


def _binance_price(symbol: str) -> float | None:
    data = _http_get(_BINANCE_TICKER + "?" + urllib.parse.urlencode({"symbol": symbol}))
    if not data or "price" not in data:
        return None
    try:
        return float(data["price"])
    except (TypeError, ValueError):
        return None


def _fair_value_above_strike(spot: float, strike: float, time_to_expiry_s: float, sigma_per_year: float) -> float:
    """Black-Scholes-style probability that spot reaches strike at expiry.

    Lognormal model: P(S_T > K) = N(d2) where
      d2 = (ln(S/K) - 0.5σ²T) / (σ√T)

    Crude — assumes constant vol, no drift, no transaction costs. Good enough
    for a Phase 0 gap-detection telemetry probe; do NOT use for live sizing.
    """
    if spot <= 0 or strike <= 0 or time_to_expiry_s <= 0 or sigma_per_year <= 0:
        return 0.5
    T_years = time_to_expiry_s / (365.0 * 86400.0)
    if T_years <= 0:
        return 1.0 if spot > strike else 0.0
    d2 = (math.log(spot / strike) - 0.5 * sigma_per_year ** 2 * T_years) / (sigma_per_year * math.sqrt(T_years))
    # Standard normal CDF approximation
    return 0.5 * (1.0 + math.erf(d2 / math.sqrt(2.0)))


def _list_active_btc_eth_markets() -> list[dict]:
    """Fetch crypto-related Polymarket markets and filter to BTC/ETH binaries."""
    rows = _http_get(_POLY_MARKETS + "?active=true&limit=200&closed=false")
    if not isinstance(rows, list):
        return []
    out = []
    for m in rows:
        if not isinstance(m, dict):
            continue
        q = (m.get("question") or "").lower()
        if "bitcoin" not in q and "btc" not in q and "ethereum" not in q and "eth" not in q:
            continue
        # Want short-duration binaries — heuristic: end-time within next 7 days
        end_iso = m.get("endDate")
        if not end_iso:
            continue
        try:
            end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        except Exception:
            continue
        secs = (end_dt - datetime.now(timezone.utc)).total_seconds()
        if secs <= 0 or secs > 7 * 86400:
            continue
        out.append({
            "market_id": m.get("id"),
            "question": m.get("question"),
            "end_dt": end_iso,
            "seconds_to_expiry": int(secs),
            "outcomePrices": m.get("outcomePrices"),
            "volume": m.get("volume"),
            "liquidity": m.get("liquidity"),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--poll-seconds", type=float, default=10.0)
    ap.add_argument("--duration-min", type=float, default=5.0)
    ap.add_argument("--btc-vol", type=float, default=0.6, help="annualised BTC vol estimate (default 60%)")
    ap.add_argument("--eth-vol", type=float, default=0.7)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = OUT_DIR / f"{run_id}.jsonl"

    markets = _list_active_btc_eth_markets()
    print(f"Found {len(markets)} active BTC/ETH binary markets")
    if not markets:
        print("No active markets — exiting (probe inconclusive).")
        return 1

    deadline = time.time() + args.duration_min * 60.0
    fout = open(out_path, "w")
    poll_n = 0
    while time.time() < deadline:
        poll_n += 1
        ts = datetime.now(timezone.utc).isoformat()
        spot_btc = _binance_price("BTCUSDT")
        spot_eth = _binance_price("ETHUSDT")

        for m in markets:
            q = (m.get("question") or "").lower()
            is_btc = "bitcoin" in q or "btc" in q
            spot = spot_btc if is_btc else spot_eth
            sigma = args.btc_vol if is_btc else args.eth_vol
            if spot is None:
                continue
            # outcomePrices is "[\"0.42\",\"0.58\"]" string in some endpoints
            poly_yes_price = None
            outcomes = m.get("outcomePrices")
            if isinstance(outcomes, str):
                try:
                    outcomes = json.loads(outcomes)
                except Exception:
                    outcomes = None
            if isinstance(outcomes, list) and outcomes:
                try:
                    poly_yes_price = float(outcomes[0])
                except (TypeError, ValueError):
                    poly_yes_price = None

            secs_remaining = max(0, m.get("seconds_to_expiry", 0) - poll_n * args.poll_seconds)
            # Strike extraction is hard from natural-language questions — skip for now
            # and just record poly_yes_price + spot.
            row = {
                "ts": ts,
                "poll_n": poll_n,
                "market_id": m.get("market_id"),
                "question": m.get("question"),
                "secs_to_expiry": secs_remaining,
                "spot": spot,
                "poly_yes_price": poly_yes_price,
                "side": "btc" if is_btc else "eth",
            }
            fout.write(json.dumps(row) + "\n")
        fout.flush()
        time.sleep(args.poll_seconds)

    fout.close()
    print(f"Wrote {poll_n * len(markets)} rows to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
