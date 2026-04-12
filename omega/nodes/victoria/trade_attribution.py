"""
omega.nodes.victoria.trade_attribution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Per-signal PnL contribution decomposition — Shapley-value-like attribution.

## Method

For each signal in the entry signal dict:

  1. magnitude  = abs(signal_value)        — how strongly the signal fired
  2. alignment  = direction-match score:
       +1  if signal agrees with the trade direction AND outcome is profitable
       +1  if signal opposes the trade direction AND outcome is a loss (correct)
       -1  otherwise (signal was wrong)
       Special case: if signal_value ≈ 0 → contribution = 0 (signal was silent)
  3. raw_contribution = magnitude × alignment × abs(pnl)

  4. Normalize so that Σ contributions == total_pnl (preserving directional sign).
     If all magnitudes are zero (all signals silent), distribute evenly.

## Alignment rule

  expected_signal_sign = +1 for long, -1 for short
  outcome_sign         = +1 if pnl > 0, -1 if pnl <= 0

  A signal is "correct" if:
    sign(signal_value) == expected_signal_sign AND pnl > 0  (bullish + long win)
    sign(signal_value) != expected_signal_sign AND pnl <= 0 (bearish on long = correct warning)

  alignment_score = +1 if (sign(signal_value) == expected_signal_sign) == (pnl > 0)
                    -1  otherwise
                     0  if signal_value ≈ 0

## Example

  Trade: ETHUSDT long, PnL +$20.00
  Signals:
    sma_crossover     = +0.4  → aligned with long (bullish), outcome win → alignment +1
    rsi_signal        = -0.2  → opposed to long (bearish), outcome win → alignment -1
    funding_rate_sig  = +0.1  → aligned, win → +1
    fear_greed_signal =  0.0  → silent → 0

  raw_contributions:
    sma_crossover     = 0.4 × +1 × 20 = +8.0
    rsi_signal        = 0.2 × -1 × 20 = -4.0
    funding_rate_sig  = 0.1 × +1 × 20 = +2.0

  sum_raw = 8.0 - 4.0 + 2.0 = 6.0
  scale = 20.0 / 6.0 = 3.33
  normalized:
    sma_crossover     = +8.0 × 3.33 = +26.67
    rsi_signal        = -4.0 × 3.33 = -13.33
    funding_rate_sig  = +2.0 × 3.33 = +6.67
    total             = +20.00 ✓

## Usage

    from omega.nodes.victoria.trade_attribution import attribute_trade

    contribs = attribute_trade(
        entry_signals={"sma_crossover": 0.4, "rsi_signal": -0.2},
        pnl=20.0,
        side="long",
    )
    # → {"sma_crossover": +26.67, "rsi_signal": -13.33, ...}

    # Persist for analysis:
    import json
    with open("data/v106_attribution.jsonl", "a") as f:
        f.write(json.dumps({"cycle": c, "ticker": t, **contribs}) + "\\n")
"""

from __future__ import annotations

import math
from typing import Any

# Signals considered for attribution (must be numeric, ideally in [-1, 1])
_ATTRIBUTABLE_SIGNALS = {
    "sma_crossover",
    "rsi_signal",
    "macd_crossover",
    "zscore_signal",
    "volume_signal",
    "bb_signal",
    "vol_regime_signal",
    "btc_beta_signal",
    "funding_rate_signal",
    "fear_greed_signal",
    "dxy_signal",
    "vix_signal",
    "yield_curve_signal",
    # Microstructure
    "order_book_imbalance_signal",
    "trade_flow_signal",
    "spread_zscore_signal",
    "volume_profile_signal",
    "tick_momentum_signal",
    # Temporal
    "momentum_derivative",
    "conviction_trend",
    "agreement_trend",
}

_SILENCE_THRESHOLD = 1e-6  # signal values below this are treated as "silent" (no attribution)


def attribute_trade(
    entry_signals: dict[str, Any],
    pnl: float,
    side: str,
) -> dict[str, float]:
    """Decompose realized PnL into per-signal contributions.

    Args:
        entry_signals: Per-ticker signal dict at trade entry time.
                       Typically the `ts` dict from signal_generation.py.
        pnl:           Realized PnL in USD (positive = win, negative = loss).
        side:          "long" or "short".

    Returns:
        Dict mapping signal_name → PnL contribution (USD). Sum equals `pnl`.
        Returns empty dict if no attributable signals found.
    """
    if not entry_signals or pnl == 0.0:
        return {}

    # expected_dir: +1 for long (bullish signals help), -1 for short (bearish signals help)
    expected_dir = 1 if side == "long" else -1
    outcome_positive = pnl > 0

    raw: dict[str, float] = {}

    for sig_name in _ATTRIBUTABLE_SIGNALS:
        val = entry_signals.get(sig_name)
        if val is None:
            continue
        try:
            fval = float(val)
        except (TypeError, ValueError):
            continue
        if math.isnan(fval) or math.isinf(fval):
            continue
        if abs(fval) < _SILENCE_THRESHOLD:
            continue  # signal was silent — no contribution

        magnitude = abs(fval)
        # Alignment: did this signal point the right direction?
        # For long: positive signal is "correct direction"
        # For short: negative signal is "correct direction"
        signal_agrees = (fval > 0) == (expected_dir > 0)
        # Signal is "correct" when it agrees with direction AND we won,
        # OR opposes direction AND we lost (it was a warning we ignored).
        is_correct = signal_agrees == outcome_positive
        alignment = 1.0 if is_correct else -1.0

        raw[sig_name] = magnitude * alignment * abs(pnl)

    if not raw:
        return {}

    # Normalize so contributions sum to pnl
    sum_raw = sum(raw.values())
    if abs(sum_raw) < _SILENCE_THRESHOLD:
        # All signals silent or perfectly balanced — distribute evenly
        n = len(raw)
        return {k: pnl / n for k in raw}

    scale = pnl / sum_raw
    return {k: v * scale for k, v in raw.items()}


def attribution_summary(
    attributions: list[dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Aggregate per-signal attribution across multiple trades.

    Args:
        attributions: List of dicts from attribute_trade(), one per trade.

    Returns:
        Dict mapping signal_name → {"total_pnl": float, "n_trades": int, "avg_pnl": float}
    """
    totals: dict[str, list[float]] = {}
    for trade_attrs in attributions:
        for sig_name, contrib in trade_attrs.items():
            totals.setdefault(sig_name, []).append(contrib)

    return {
        sig_name: {
            "total_pnl": round(sum(contribs), 4),
            "n_trades": len(contribs),
            "avg_pnl": round(sum(contribs) / len(contribs), 4),
        }
        for sig_name, contribs in totals.items()
    }
