"""
scripts/signal_audit.py
~~~~~~~~~~~~~~~~~~~~~~~
Diagnostic: measure each signal's individual predictive power.

For each directional sub-signal in SignalGenerationNode, computes:
  - IC (Information Coefficient): Pearson correlation with 5-bar forward returns
  - Solo win rate: when |signal| > 0.3, does price move in predicted direction?
  - SNR: mean / std of signal values
  - Extreme hit rate: when |signal| > 0.7

Runs 200 simulated cycles on real Binance OHLCV data via a sliding window.
Writes per-signal ICs to data/signal_ics.json for use by StrategyNode.

Usage:
    python scripts/signal_audit.py
"""

from __future__ import annotations

import json
import logging
import math
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from omega.eval.run_honest_backtest import get_ohlcv  # noqa: E402
from omega.nodes.victoria.signal_generation import SignalGenerationNode  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("signal_audit")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

N_CYCLES = 200
WINDOW_SIZE = 80  # bars of history per cycle (enough for MACD slow=26 + signal=9)
FORWARD_BARS = 5  # forecast horizon (5-bar forward return)
KILL_IC_THRESHOLD = 0.0  # IC ≤ 0 → kill
KILL_WINRATE_THRESHOLD = 0.40  # solo win rate < 40% → kill

SYMBOLS = [
    ("BTC/USDT", "BTCUSDT"),
    ("ETH/USDT", "ETHUSDT"),
]


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def pearson_ic(x: list[float], y: list[float]) -> float:
    """Pearson correlation coefficient between signal values and forward returns."""
    n = len(x)
    if n < 5:
        return 0.0
    try:
        return statistics.correlation(x, y)
    except statistics.StatisticsError:
        return 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> tuple[list[dict], list[str], dict[str, float]]:
    # ------------------------------------------------------------------
    # 1. Load OHLCV data
    # ------------------------------------------------------------------
    logger.info("Loading OHLCV data (%d cycles planned)...", N_CYCLES)
    all_bars: dict[str, list[dict]] = {}
    for symbol, ticker in SYMBOLS:
        all_bars[ticker] = get_ohlcv(symbol, days=365)
        logger.info("  %s: %d bars", ticker, len(all_bars[ticker]))

    # ------------------------------------------------------------------
    # 2. Build signal node with all indicators enabled (v1.2 state)
    # ------------------------------------------------------------------
    node = SignalGenerationNode()
    node._use_rsi = True
    node._use_macd = True
    node._use_bb = True
    node._use_zscore = True
    node._use_volume_zscore = True
    node._use_btc_beta = True
    node._use_vol_regime = True

    # ------------------------------------------------------------------
    # 3. Slide a window through the price series, recording signal values
    #    and the corresponding 5-bar forward returns
    # ------------------------------------------------------------------
    # signal_name → list of (signal_value, forward_return) pairs
    signal_obs: dict[str, list[tuple[float, float]]] = {}

    btc_bars = all_bars["BTCUSDT"]
    n_bars = len(btc_bars)
    max_start = n_bars - WINDOW_SIZE - FORWARD_BARS
    step = max(1, max_start // N_CYCLES)

    cycles_run = 0
    for start_i in range(0, max_start, step):
        if cycles_run >= N_CYCLES:
            break
        end_i = start_i + WINDOW_SIZE

        # Build market_data dict for this sliding window
        market_data: dict[str, dict] = {}
        valid = True
        for ticker, bars in all_bars.items():
            if end_i + FORWARD_BARS >= len(bars):
                valid = False
                break
            window = bars[start_i:end_i]
            market_data[ticker] = {
                "close": [b["close"] for b in window],
                "volume": [b["volume"] for b in window],
            }
        if not valid:
            continue

        # Compute signals
        try:
            signals = node._compute_all_signals(market_data)
        except Exception as exc:
            logger.debug("Signal error at cycle %d: %s", cycles_run, exc)
            continue

        # For each ticker, record sub-signal values → 5-bar forward return
        for ticker, sig_dict in signals.items():
            ticker_bars = all_bars.get(ticker)
            if ticker_bars is None:
                continue
            entry_price = ticker_bars[end_i - 1]["close"]
            exit_price = ticker_bars[end_i + FORWARD_BARS - 1]["close"]
            if entry_price == 0:
                continue
            fwd_ret = (exit_price - entry_price) / entry_price

            for k, v in sig_dict.items():
                if not (k.endswith("_signal") or k == "sma_crossover"):
                    continue
                if not isinstance(v, (int, float)):
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if math.isnan(fv) or math.isinf(fv):
                    continue
                signal_obs.setdefault(k, []).append((fv, fwd_ret))

        cycles_run += 1

    logger.info("Completed %d cycles. Signals observed: %s", cycles_run, list(signal_obs))

    # ------------------------------------------------------------------
    # 4. Compute per-signal statistics
    # ------------------------------------------------------------------
    results: list[dict] = []
    kill_list: list[str] = []

    for sig_name, pairs in signal_obs.items():
        if len(pairs) < 10:
            logger.warning("Too few observations for %s (%d) — skipping", sig_name, len(pairs))
            continue

        vals = [p[0] for p in pairs]
        rets = [p[1] for p in pairs]

        # Information Coefficient
        ic = pearson_ic(vals, rets)

        # Signal-to-noise ratio
        mean_v = statistics.mean(vals)
        std_v = statistics.pstdev(vals) or 1.0
        snr = mean_v / std_v

        # Solo win rate: when |signal| > 0.3, does direction match forward return?
        strong_pairs = [(v, r) for v, r in pairs if abs(v) > 0.3]
        if strong_pairs:
            solo_wins = sum(1 for v, r in strong_pairs if (v > 0 and r > 0) or (v < 0 and r < 0))
            solo_wr = solo_wins / len(strong_pairs)
        else:
            solo_wr = 0.5  # no information

        # Extreme hit rate: when |signal| > 0.7
        extreme_pairs = [(v, r) for v, r in pairs if abs(v) > 0.7]
        if extreme_pairs:
            extreme_wins = sum(
                1 for v, r in extreme_pairs if (v > 0 and r > 0) or (v < 0 and r < 0)
            )
            extreme_wr = extreme_wins / len(extreme_pairs)
        else:
            extreme_wr = float("nan")

        should_kill = ic <= KILL_IC_THRESHOLD or solo_wr < KILL_WINRATE_THRESHOLD
        if should_kill:
            kill_list.append(sig_name)

        results.append(
            {
                "signal": sig_name,
                "ic": ic,
                "solo_wr": solo_wr,
                "snr": snr,
                "extreme_wr": extreme_wr,
                "n_obs": len(pairs),
                "kill": should_kill,
            }
        )

    # Sort by IC descending (best predictors first)
    results.sort(key=lambda x: x["ic"], reverse=True)

    # ------------------------------------------------------------------
    # 5. Print ranked table
    # ------------------------------------------------------------------
    print()
    print(f"Signal Audit — {cycles_run} cycles, {FORWARD_BARS}-bar forward return")
    print("=" * 78)
    header = f"{'Signal':<25} {'IC':>8} {'SoloWR':>8} {'SNR':>8} {'ExtremeWR':>10} {'N':>5} {'Status':>8}"
    print(header)
    print("-" * 78)
    for r in results:
        ewr = f"{r['extreme_wr']:.3f}" if not math.isnan(r["extreme_wr"]) else "  n/a"
        status = "KILL" if r["kill"] else "keep"
        print(
            f"{r['signal']:<25} {r['ic']:>8.4f} {r['solo_wr']:>8.3f} "
            f"{r['snr']:>8.4f} {ewr:>10} {r['n_obs']:>5} {status:>8}"
        )
    print("=" * 78)
    print()
    print(f"KILL list ({len(kill_list)}): {kill_list}")
    print()
    print("Signals to keep (positive IC):")
    keep = [r for r in results if not r["kill"]]
    for r in keep:
        print(f"  {r['signal']:<25}  IC={r['ic']:+.4f}  solo_wr={r['solo_wr']:.3f}")
    print()

    # ------------------------------------------------------------------
    # 6. Write ICs to JSON for StrategyNode.update_signal_ics()
    # ------------------------------------------------------------------
    ics: dict[str, float] = {r["signal"]: r["ic"] for r in results if not r["kill"]}
    ic_path = REPO_ROOT / "data" / "signal_ics.json"
    ic_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ic_path, "w") as f:
        json.dump(ics, f, indent=2, sort_keys=True)
    logger.info(
        "ICs written to %s (%d signals kept, %d killed)", ic_path, len(ics), len(kill_list)
    )

    return results, kill_list, ics


if __name__ == "__main__":
    main()
