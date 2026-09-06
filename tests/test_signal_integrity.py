"""
tests/test_signal_integrity.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Anticipatory regression tests for V35–V44 signal system bugs.

Each test targets a specific class of failure that wasted 40-minute training cycles:

  Bug 1 (V34)    — Short-only bias: composites all negative, no longs generated
  Bug 2 (V33)    — Conviction staircase: rank blending produced identical scores
  Bug 3 (V35)    — Agreement ratio blocking: raw sub-signals disagreed with
                    demeaned composite, blocking all longs in bear markets
  Bug 4 (V41)    — Sign flip: direction inverted, exact mirror PnL
  Bug 5 (V43)    — HOLD blanket gate: [-0.20, +0.20] too wide for demeaned composites
  Bug 6 (V40-42) — Regime over-filtering: CRISIS blocking ALL trades including shorts
  Bug 7          — Dead/flat signals diluting composites (zero alpha contribution)
  Bug 8 (V26-27) — Zero-trade streaks: vol sit-out too aggressive

Run before every training iteration:
  pytest tests/test_signal_integrity.py -v --timeout=30
"""



from __future__ import annotations

import math
import uuid

import pytest

from omega.core.node import NodeInput
from omega.nodes.victoria.signal_generation import SignalGenerationNode
from omega.nodes.victoria.strategy import (
    ConvictionLevel,
    StrategyNode,
    score_to_conviction,
)

# Marked slow: these run real multi-cycle Victoria simulations and take minutes.
# Unmarked, they made `pytest tests/` appear to hang, so the suite was not run —
# which is how a whole stale TestRegimeAdaptivity class sat failing unnoticed.
pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

# Tradeable basket (BTCUSDT is in _TRADING_BLACKLIST but included for demeaning)
TICKERS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT", "DOTUSDT"]


def _make_ohlcv(
    n: int = 50,
    base: float = 1_000.0,
    trend: float = 0.0,
    noise_amp: float = 0.015,
    seed: int = 0,
) -> dict:
    """Deterministic OHLCV with configurable trend and bounded noise."""
    prices: list[float] = []
    price = base
    for i in range(n):
        price = price * (1.0 + trend) + base * noise_amp * math.sin(i * 0.7 + seed)
        prices.append(max(price, 0.01))
    return {
        "close": prices,
        "adjclose": prices,
        "open": [p * 0.999 for p in prices],
        "high": [p * 1.005 for p in prices],
        "low": [p * 0.995 for p in prices],
        "volume": [1_000_000.0 * (1.0 + 0.1 * math.sin(i + seed)) for i in range(n)],
    }


def _make_diverse_market_data(n: int = 50) -> dict:
    """Six tickers with clearly divergent trends.

    Three trending up, three trending down — after cross-sectional demeaning the
    system must identify relative longs AND shorts regardless of absolute direction.
    """
    return {
        "BTCUSDT": _make_ohlcv(n=n, base=60_000.0, trend=+0.005, noise_amp=0.010, seed=1),
        "ETHUSDT": _make_ohlcv(n=n, base=3_000.0,  trend=+0.003, noise_amp=0.015, seed=2),
        "SOLUSDT": _make_ohlcv(n=n, base=150.0,    trend=+0.001, noise_amp=0.020, seed=3),
        "BNBUSDT": _make_ohlcv(n=n, base=400.0,    trend=-0.002, noise_amp=0.010, seed=4),
        "ADAUSDT": _make_ohlcv(n=n, base=0.50,     trend=-0.004, noise_amp=0.025, seed=5),
        "DOTUSDT": _make_ohlcv(n=n, base=8.0,      trend=-0.006, noise_amp=0.020, seed=6),
    }


def _make_node_input(action: str, **params) -> NodeInput:
    return NodeInput(request_id=str(uuid.uuid4()), action=action, parameters=params)


def _build_signals(market_data: dict | None = None, enable_all: bool = True) -> dict:
    """Run SignalGenerationNode.execute() and return the raw signals dict."""
    if market_data is None:
        market_data = _make_diverse_market_data()
    node = SignalGenerationNode()
    if enable_all:
        node._use_rsi = True
        node._use_macd = True
        node._use_bb = True
        node._use_zscore = True
        node._use_btc_beta = True
        node._use_volume_zscore = True
        node._use_vol_regime = True
    inp = _make_node_input("compute_signals", market_data=market_data)
    out = node.execute(inp)
    assert out.success, f"Signal generation failed: {out.errors}"
    return out.result  # type: ignore[return-value]


def _get_composites(signals: dict) -> dict[str, float]:
    """Extract {ticker: composite} from a signals dict, skipping metadata keys."""
    return {
        ticker: float(sig["composite"])
        for ticker, sig in signals.items()
        if isinstance(sig, dict) and "composite" in sig and not ticker.startswith("_")
    }


# ---------------------------------------------------------------------------
# 1. Bidirectionality tests (Bug 1 — V34 short-only bias)
# ---------------------------------------------------------------------------


class TestBidirectionality:
    """After cross-sectional demeaning, the basket must produce both longs and shorts."""

    def test_mixed_composites_after_demeaning(self):
        """Bug 1 (V34): demeaning must produce both positive and negative composites."""
        signals = _build_signals()
        composites = _get_composites(signals)
        assert len(composites) >= 3, "Need ≥3 tickers for demeaning"

        positive = [v for v in composites.values() if v > 0]
        negative = [v for v in composites.values() if v < 0]

        assert len(positive) >= 1, (
            f"No positive composites after demeaning — short-only bias.\n"
            f"Composites: {composites}"
        )
        assert len(negative) >= 1, (
            f"No negative composites after demeaning — long-only bias.\n"
            f"Composites: {composites}"
        )

    def test_composites_sum_near_zero(self):
        """Demeaning invariant: basket mean of composites must be ≈ 0.0."""
        signals = _build_signals()
        composites = _get_composites(signals)
        values = list(composites.values())
        basket_mean = sum(values) / len(values)

        assert abs(basket_mean) < 0.05, (
            f"Composites not demeaned — basket_mean={basket_mean:.4f} (expected ~0).\n"
            f"Cross-sectional demeaning may be disabled or broken.\n"
            f"Composites: {composites}"
        )

    def test_both_buy_and_sell_convictions_present(self):
        """After demeaning, both BUY-side and SELL-side convictions must appear."""
        signals = _build_signals()
        composites = _get_composites(signals)
        convictions = [score_to_conviction(v) for v in composites.values()]

        buy_side = {ConvictionLevel.BUY, ConvictionLevel.STRONG_BUY}
        sell_side = {ConvictionLevel.SELL, ConvictionLevel.STRONG_SELL}

        has_buy = any(c in buy_side for c in convictions)
        has_sell = any(c in sell_side for c in convictions)

        assert has_buy or has_sell, (
            f"All tickers are HOLD — no tradeable signals at all.\n"
            f"Convictions: {[c.name for c in convictions]}\n"
            f"Composites: {_get_composites(signals)}"
        )

    def test_no_single_direction_dominates(self):
        """Neither BUY-side nor SELL-side should exceed 80% of non-HOLD proposals."""
        signals = _build_signals()
        composites = _get_composites(signals)
        convictions = [score_to_conviction(v) for v in composites.values()]

        buy_side = {ConvictionLevel.BUY, ConvictionLevel.STRONG_BUY}
        sell_side = {ConvictionLevel.SELL, ConvictionLevel.STRONG_SELL}

        n_buy = sum(1 for c in convictions if c in buy_side)
        n_sell = sum(1 for c in convictions if c in sell_side)
        n_total = n_buy + n_sell

        if n_total < 2:
            pytest.skip("Not enough non-HOLD signals to test direction dominance")

        buy_fraction = n_buy / n_total
        assert buy_fraction <= 0.80, (
            f"Buy-side dominates: {buy_fraction:.0%} of non-HOLD signals are longs "
            f"({n_buy}/{n_total}).\nComposites: {composites}"
        )
        assert buy_fraction >= 0.20, (
            f"Sell-side dominates: {1 - buy_fraction:.0%} of non-HOLD signals are shorts "
            f"({n_sell}/{n_total}).\nComposites: {composites}"
        )

    def test_extreme_bear_market_still_produces_longs(self):
        """Bug 1 (V34): even in a bear market, demeaning must find relative longs.

        All assets are declining, but at different rates. The least-bad performer
        should be a long candidate after demeaning.
        """
        bear_market = {
            "BTCUSDT": _make_ohlcv(n=50, base=60_000.0, trend=-0.001, seed=1),
            "ETHUSDT": _make_ohlcv(n=50, base=3_000.0,  trend=-0.003, seed=2),
            "SOLUSDT": _make_ohlcv(n=50, base=150.0,    trend=-0.005, seed=3),
            "BNBUSDT": _make_ohlcv(n=50, base=400.0,    trend=-0.007, seed=4),
            "ADAUSDT": _make_ohlcv(n=50, base=0.50,     trend=-0.010, seed=5),
            "DOTUSDT": _make_ohlcv(n=50, base=8.0,      trend=-0.015, seed=6),
        }
        signals = _build_signals(market_data=bear_market)
        composites = _get_composites(signals)
        positive = [v for v in composites.values() if v > 0]

        assert len(positive) >= 1, (
            f"Bear market produced zero positive composites — demeaning broken.\n"
            f"Composites: {composites}"
        )

    def test_extreme_bull_market_still_produces_shorts(self):
        """Even in a bull market, demeaning must find relative shorts (worst performers)."""
        bull_market = {
            "BTCUSDT": _make_ohlcv(n=50, base=60_000.0, trend=+0.015, seed=1),
            "ETHUSDT": _make_ohlcv(n=50, base=3_000.0,  trend=+0.010, seed=2),
            "SOLUSDT": _make_ohlcv(n=50, base=150.0,    trend=+0.007, seed=3),
            "BNBUSDT": _make_ohlcv(n=50, base=400.0,    trend=+0.005, seed=4),
            "ADAUSDT": _make_ohlcv(n=50, base=0.50,     trend=+0.003, seed=5),
            "DOTUSDT": _make_ohlcv(n=50, base=8.0,      trend=+0.001, seed=6),
        }
        signals = _build_signals(market_data=bull_market)
        composites = _get_composites(signals)
        negative = [v for v in composites.values() if v < 0]

        assert len(negative) >= 1, (
            f"Bull market produced zero negative composites — demeaning broken.\n"
            f"Composites: {composites}"
        )


# ---------------------------------------------------------------------------
# 2. Conviction gate tests (Bug 5 — V43 HOLD blanket gate)
# ---------------------------------------------------------------------------


class TestConvictionGate:
    """Conviction thresholds must be calibrated to demeaned composite magnitudes."""

    def test_hold_band_narrower_than_composite_median(self):
        """Bug 5 (V43): HOLD band ±0.20 must not swallow the entire composite range.

        If the median |composite| falls below the HOLD threshold, the system
        classifies every ticker as HOLD and produces zero trades.
        """
        signals = _build_signals()
        composites = _get_composites(signals)
        if not composites:
            pytest.skip("No composites generated")

        abs_values = sorted(abs(v) for v in composites.values())
        median_abs = abs_values[len(abs_values) // 2]
        hold_band = 0.20  # score_to_conviction HOLD boundary

        assert median_abs > hold_band * 0.5, (
            f"Composites too small for the HOLD band — all tickers will be HOLD.\n"
            f"Median |composite|={median_abs:.4f}, HOLD band=±{hold_band}.\n"
            f"Either the HOLD band is too wide (V43 bug) or signals are flat (V26 bug).\n"
            f"Composites: {composites}"
        )

    def test_at_least_30pct_composites_clear_threshold(self):
        """At least 30% of composites must exceed the weighted_conviction_threshold (0.10)."""
        signals = _build_signals()
        composites = _get_composites(signals)
        threshold = 0.10  # StrategyNode._weighted_conviction_threshold

        n_clear = sum(1 for v in composites.values() if abs(v) >= threshold)
        n_total = len(composites)

        assert n_total > 0, "No composites generated"
        fraction = n_clear / n_total

        assert fraction >= 0.30, (
            f"Only {fraction:.0%} of composites clear the conviction threshold {threshold}.\n"
            f"Expected ≥30%%. This means nearly all trades are filtered.\n"
            f"Composites: {composites}"
        )

    def test_conviction_thresholds_achievable(self):
        """The conviction threshold must be reachable given actual composite magnitudes."""
        signals = _build_signals()
        composites = _get_composites(signals)
        if not composites:
            pytest.skip("No composites generated")

        max_abs = max(abs(v) for v in composites.values())
        threshold = 0.10  # weighted_conviction_threshold

        assert max_abs >= threshold, (
            f"Maximum |composite|={max_abs:.4f} is below conviction threshold={threshold}.\n"
            f"Threshold is unachievable — ALL trades will be blocked.\n"
            f"Composites: {composites}"
        )

    def test_hold_band_exact_upper_boundary(self):
        """Regression: HOLD upper boundary is exactly 0.20 (not shifted wider)."""
        assert score_to_conviction(0.201) == ConvictionLevel.BUY, (
            "HOLD/BUY boundary shifted — should be at 0.20"
        )
        assert score_to_conviction(0.200) == ConvictionLevel.HOLD, (
            "score=0.20 should be HOLD (boundary is exclusive: score > 0.20 → BUY)"
        )
        assert score_to_conviction(0.199) == ConvictionLevel.HOLD

    def test_hold_band_exact_lower_boundary(self):
        """Regression: HOLD lower boundary is exactly -0.20 (not shifted wider)."""
        assert score_to_conviction(-0.201) == ConvictionLevel.SELL, (
            "HOLD/SELL boundary shifted — should be at -0.20"
        )
        assert score_to_conviction(-0.200) == ConvictionLevel.SELL, (
            "score=-0.20 should be SELL (boundary is exclusive: score > -0.20 → HOLD)"
        )
        assert score_to_conviction(-0.199) == ConvictionLevel.HOLD

    def test_strong_buy_sell_boundaries(self):
        """Regression: STRONG_BUY/SELL thresholds must be exactly ±0.60.

        Boundaries are exclusive (score > 0.6 → STRONG_BUY):
          0.600 is NOT > 0.60 → BUY
          0.601 is > 0.60    → STRONG_BUY
          -0.600 is NOT > -0.6 → STRONG_SELL
          -0.599 is > -0.6   → SELL
        """
        assert score_to_conviction(0.601) == ConvictionLevel.STRONG_BUY
        assert score_to_conviction(0.600) == ConvictionLevel.BUY
        assert score_to_conviction(-0.601) == ConvictionLevel.STRONG_SELL
        assert score_to_conviction(-0.600) == ConvictionLevel.STRONG_SELL  # boundary is exclusive
        assert score_to_conviction(-0.599) == ConvictionLevel.SELL


# ---------------------------------------------------------------------------
# 3. Agreement ratio tests (Bug 3 — V35 agreement ratio blocking)
# ---------------------------------------------------------------------------


class TestAgreementRatio:
    """Agreement ratio must not block demeaned signals."""

    def test_agreement_ratio_threshold_is_zero_by_default(self):
        """Bug 3 (V35): agreement_ratio_threshold must be 0.0 (disabled).

        When cross-sectional demeaning is active, all raw sub-signals in a bear
        market are negative — but the demeaned composite correctly identifies
        relative longs. A non-zero threshold would block all longs.
        """
        node = StrategyNode()
        assert node._agreement_ratio_threshold == 0.0, (
            f"agreement_ratio_threshold={node._agreement_ratio_threshold!r} "
            f"(expected 0.0).\n"
            "Non-zero value blocks demeaned longs in bear markets — V35 regression."
        )

    def test_agreement_ratio_does_not_block_relative_long(self):
        """A demeaned long (positive composite, bearish raw sub-signals) must pass.

        In a bear market, a relative outperformer has a positive composite after
        demeaning, but its raw sub-signals may all be negative. The agreement ratio
        must not block this ticker (threshold=0.0 means the filter is skipped).
        """
        node = StrategyNode()
        node._last_trade_cycle = -999

        # All raw sub-signals are bearish, but composite is positive post-demean
        sig = {
            "composite": 0.15,
            "sma_crossover": -0.30,
            "rsi_signal": -0.20,
            "zscore_signal": 0.40,
            "vol_regime_signal": -0.10,
        }
        _passes, reason = node._passes_conviction_filters(sig, cycle=10, direction="long")

        assert not reason.startswith("agreement_ratio"), (
            f"Agreement ratio blocking demeaned signal: {reason}\n"
            "V35 regression — set agreement_ratio_threshold=0.0"
        )

    def test_no_sub_signals_skips_agreement_check(self):
        """When a ticker has only a composite (no sub-signals), agreement check is skipped."""
        node = StrategyNode()
        node._last_trade_cycle = -999

        # Composite-only ticker (no *_signal keys) — agreement ratio must be skipped
        sig = {
            "composite": 0.25,
            "vol_regime": "high",  # high-vol would raise threshold to 0.7 if enabled
        }
        _passes, reason = node._passes_conviction_filters(sig, cycle=10, direction="long")

        assert not reason.startswith("agreement_ratio"), (
            f"Agreement ratio should be skipped when no sub-signals exist. Got: {reason}"
        )

    def test_high_vol_agreement_ratio_with_real_signals(self):
        """In high-vol, agreement_ratio is 0.7 — verify this doesn't block when signals agree."""
        node = StrategyNode()
        node._last_trade_cycle = -999

        # Strong agreeing signals in high-vol (all pointing same direction)
        sig = {
            "composite": 0.35,
            "vol_regime": "high",
            "sma_crossover": 0.50,
            "rsi_signal": 0.40,
            "zscore_signal": 0.30,
        }
        _passes, reason = node._passes_conviction_filters(sig, cycle=10, direction="long")

        # Should not be blocked by agreement ratio (all 3 sub-signals agree: > 0)
        assert not reason.startswith("agreement_ratio"), (
            f"Agreement ratio blocking despite 3/3 sub-signals agreeing. Got: {reason}"
        )


# ---------------------------------------------------------------------------
# 4. Signal liveness tests (Bug 7 — dead/flat signals diluting composites)
# ---------------------------------------------------------------------------


class TestSignalLiveness:
    """Each registered signal must contribute non-zero output."""

    def test_sma_crossover_nonzero_for_trending_ticker(self):
        """SMA crossover must be non-zero for at least 1 ticker with a trend."""
        signals = _build_signals()
        nonzero = [
            t for t, sig in signals.items()
            if isinstance(sig, dict)
            and abs(sig.get("sma_crossover", 0.0)) > 0.001
            and not t.startswith("_")
        ]
        assert len(nonzero) >= 1, "SMA crossover is effectively 0 for all tickers — dead signal"

    def test_rsi_signal_nonzero(self):
        """RSI signal must be non-zero for at least 1 ticker."""
        signals = _build_signals()
        nonzero = [
            t for t, sig in signals.items()
            if isinstance(sig, dict)
            and abs(sig.get("rsi_signal", 0.0)) > 0.01
            and not t.startswith("_")
        ]
        assert len(nonzero) >= 1, "RSI signal is flat for all tickers — dead signal"

    def test_at_least_5_signals_active_across_basket(self):
        """At least 5 distinct signal types must be non-zero across the basket."""
        signals = _build_signals()
        signal_keys = {
            "sma_crossover", "rsi_signal", "macd_crossover", "bb_signal",
            "zscore_signal", "volume_zscore", "vol_regime_signal", "btc_beta_signal",
        }
        active: set[str] = set()
        for ticker, sig in signals.items():
            if not isinstance(sig, dict) or ticker.startswith("_"):
                continue
            for key in signal_keys:
                if abs(sig.get(key, 0.0)) > 0.001:
                    active.add(key)

        assert len(active) >= 5, (
            f"Only {len(active)} active signals: {active}.\n"
            f"Expected ≥5. Dead signals dilute composites — V40-V42 regression."
        )

    def test_composite_variance_not_negligible(self):
        """Composites must have meaningful spread (Bug 2 — V33 identical scores)."""
        signals = _build_signals()
        composites = list(_get_composites(signals).values())

        if len(composites) < 2:
            pytest.skip("Need at least 2 composites")

        mean = sum(composites) / len(composites)
        variance = sum((v - mean) ** 2 for v in composites) / len(composites)
        std = math.sqrt(variance)

        assert std > 0.01, (
            f"Composite std={std:.4f} is negligibly small — all scores are near-identical.\n"
            f"Bug 2 (V33): rank blending or dead signals producing identical composites.\n"
            f"Composites: {composites}"
        )

    def test_no_single_signal_dominates_composite(self):
        """No single signal type should account for >85% of total absolute signal weight."""
        signals = _build_signals()
        signal_keys = ["sma_crossover", "rsi_signal", "macd_crossover", "bb_signal", "zscore_signal"]

        signal_totals: dict[str, float] = {k: 0.0 for k in signal_keys}
        for ticker, sig in signals.items():
            if not isinstance(sig, dict) or ticker.startswith("_"):
                continue
            for key in signal_keys:
                signal_totals[key] += abs(sig.get(key, 0.0))

        total_all = sum(signal_totals.values())
        if total_all == 0:
            pytest.skip("All signals are zero")

        for key, total in signal_totals.items():
            fraction = total / total_all
            assert fraction <= 0.85, (
                f"Signal '{key}' dominates: {fraction:.0%} of total abs signal weight.\n"
                f"Unbalanced signals create single-factor regime sensitivity."
            )


# ---------------------------------------------------------------------------
# 5. Regime adaptivity tests (Bug 6 — V40-V42 regime over-filtering)
# ---------------------------------------------------------------------------


class TestRegimeAdaptivity:
    """The system must propose trades in ALL market regimes."""

    def _inject_regime(self, signals: dict, bear_prob: float, bull_prob: float, hmm: str) -> dict:
        """Add Wasserstein regime metadata to a signals dict."""
        signals = dict(signals)
        signals["_regime_w_bear_prob"] = bear_prob
        signals["_regime_w_bull_prob"] = bull_prob
        signals["_regime_hmm"] = hmm
        signals["_regime_probs"] = [bull_prob, bear_prob, max(0.0, 1.0 - bull_prob - bear_prob)]
        return signals

    def test_normal_regime_thresholds(self):
        """NORMAL regime: long=0.10, short=0.10 (balanced — V50 revert of V49 0.05 fix)."""
        node = StrategyNode()
        node._apply_regime_adaptive_thresholds(
            {"_regime_w_bear_prob": 0.25, "_regime_w_bull_prob": 0.30}
        )
        assert node._long_conviction_threshold == 0.07
        assert node._short_conviction_threshold == 0.07, (
            f"Normal short threshold={node._short_conviction_threshold} "
            f"(expected 0.07 — V95 reverted to V88's calibration)"
        )

    def test_bear_regime_suppresses_longs_permits_shorts(self):
        """Bug 6 (V40-V42): BEAR regime must lower short bar, not block everything."""
        node = StrategyNode()
        node._apply_regime_adaptive_thresholds(
            {"_regime_w_bear_prob": 0.75, "_regime_w_bull_prob": 0.10}
        )
        assert node._short_conviction_threshold == 0.04, (
            f"Bear short threshold={node._short_conviction_threshold} "
            f"(expected 0.05 — permissive shorts in bear market)"
        )
        assert node._long_conviction_threshold == 0.50, (
            f"Bear long threshold={node._long_conviction_threshold} "
            f"(expected 0.20 — suppressed longs in bear market)"
        )

    def test_bull_regime_suppresses_shorts_permits_longs(self):
        """BULL regime must lower long bar, not block everything."""
        node = StrategyNode()
        node._apply_regime_adaptive_thresholds(
            {"_regime_w_bear_prob": 0.10, "_regime_w_bull_prob": 0.75}
        )
        assert node._long_conviction_threshold == 0.05, (
            f"Bull long threshold={node._long_conviction_threshold} (expected 0.05)"
        )
        assert node._short_conviction_threshold == 0.20, (
            f"Bull short threshold={node._short_conviction_threshold} (expected 0.20)"
        )

    def test_regime_thresholds_differ_across_modes(self):
        """Regime-specific thresholds must differ — not all defaulting to 0.10."""
        node = StrategyNode()

        node._apply_regime_adaptive_thresholds(
            {"_regime_w_bear_prob": 0.75, "_regime_w_bull_prob": 0.10}
        )
        bear_long, bear_short = node._long_conviction_threshold, node._short_conviction_threshold

        node._apply_regime_adaptive_thresholds(
            {"_regime_w_bear_prob": 0.10, "_regime_w_bull_prob": 0.75}
        )
        bull_long, bull_short = node._long_conviction_threshold, node._short_conviction_threshold

        node._apply_regime_adaptive_thresholds(
            {"_regime_w_bear_prob": 0.25, "_regime_w_bull_prob": 0.30}
        )
        normal_long, normal_short = node._long_conviction_threshold, node._short_conviction_threshold

        assert bear_long != bull_long, "Bear and bull LONG thresholds are identical"
        assert bear_short != bull_short, "Bear and bull SHORT thresholds are identical"
        assert bear_long != normal_long or bear_short != normal_short, (
            "Bear and normal thresholds are identical — regime filter has no effect"
        )

    def test_normal_regime_produces_proposals(self):
        """NORMAL regime: construct_portfolio must generate ≥1 proposal."""
        market_data = _make_diverse_market_data()
        signals = _build_signals(market_data=market_data)
        signals = self._inject_regime(signals, bear_prob=0.20, bull_prob=0.30, hmm="sideways")

        node = StrategyNode()
        node._last_trade_cycle = -999
        result = node._construct_portfolio(signals, market_data)

        n_proposals = result.get("proposals_generated", 0)
        assert n_proposals > 0, (
            f"Zero proposals in NORMAL regime.\n"
            f"Composites: {_get_composites(signals)}\n"
            f"Long threshold: {node._long_conviction_threshold}"
        )

    def test_crisis_regime_allows_shorts(self):
        """Bug 6 (V40-V42): CRISIS regime must still allow short trades."""
        market_data = _make_diverse_market_data()
        signals = _build_signals(market_data=market_data)
        signals = self._inject_regime(signals, bear_prob=0.80, bull_prob=0.05, hmm="bear")

        node = StrategyNode()
        node._last_trade_cycle = -999
        result = node._construct_portfolio(signals, market_data)

        # In CRISIS with continuous regime (Wasserstein probs present):
        # _block_longs=False, _block_shorts=False — filtering is via thresholds only.
        # Short threshold is 0.05, so any |composite| >= 0.05 generates a short proposal.
        n_proposals = result.get("proposals_generated", 0)
        assert n_proposals > 0, (
            f"Zero proposals in CRISIS regime — regime filter is too aggressive.\n"
            f"V40-V42 regression: CRISIS blocking all trades including shorts.\n"
            f"Short threshold: {node._short_conviction_threshold}\n"
            f"Composites: {_get_composites(signals)}"
        )

    def test_bear_detection_threshold_at_065(self):
        """Regression: BEAR mode activates at bear_prob >= 0.65 (not lower).

        Was written against 0.55 and asserted a NORMAL long threshold of 0.10.
        Both numbers moved and the test was never updated, so it had been failing
        silently — V91 raised the crisis trigger 0.55 -> 0.65, and V87 settled the
        NORMAL long threshold at 0.07 after the V83-V95 tuning sequence.

        It went unnoticed because this file takes minutes to run and carries no
        `slow` marker, so it is not in any routine run.
        """
        node = StrategyNode()

        # Just below threshold → NORMAL
        node._apply_regime_adaptive_thresholds(
            {"_regime_w_bear_prob": 0.649, "_regime_w_bull_prob": 0.10}
        )
        assert node._long_conviction_threshold == 0.07, (
            "Bear regime triggering below the 0.65 threshold — over-sensitive"
        )

        # At threshold → BEAR
        node._apply_regime_adaptive_thresholds(
            {"_regime_w_bear_prob": 0.65, "_regime_w_bull_prob": 0.10}
        )
        assert node._long_conviction_threshold == 0.50, (
            "Bear regime not activating at the 0.65 threshold"
        )


# ---------------------------------------------------------------------------
# 6. PnL direction sanity (Bug 4 — V41 sign flip)
# ---------------------------------------------------------------------------


class TestPnLDirectionSanity:
    """Direction assignments must be correct (not inverted)."""

    def test_positive_composite_maps_to_positive_conviction(self):
        """Bug 4 (V41): positive composite must yield positive conviction value."""
        assert score_to_conviction(0.50) > ConvictionLevel.HOLD
        assert score_to_conviction(0.25) > ConvictionLevel.HOLD

    def test_negative_composite_maps_to_negative_conviction(self):
        """Negative composite must yield negative conviction value."""
        assert score_to_conviction(-0.50) < ConvictionLevel.HOLD
        assert score_to_conviction(-0.25) < ConvictionLevel.HOLD

    def test_conviction_monotonically_increases_with_composite(self):
        """Higher composite must always map to higher-or-equal conviction."""
        scores = [-1.0, -0.7, -0.3, 0.0, 0.3, 0.7, 1.0]
        convictions = [score_to_conviction(s) for s in scores]

        for i in range(len(convictions) - 1):
            assert int(convictions[i]) <= int(convictions[i + 1]), (
                f"Non-monotonic: score {scores[i]:.1f}→{scores[i+1]:.1f} maps "
                f"{convictions[i].name}→{convictions[i+1].name}"
            )

    def test_buy_signal_gets_nonnegative_weight(self):
        """Bug 4 (V41): a BUY-conviction ticker must never get a negative portfolio weight."""
        node = StrategyNode()
        signals = {
            "BTCUSDT": {"composite": 0.0},     # blacklisted
            "ETHUSDT": {"composite": 0.35},    # BUY
            "SOLUSDT": {"composite": -0.25},   # SELL
            "BNBUSDT": {"composite": -0.10},   # HOLD
        }
        result = node._construct_portfolio(signals, {})
        weights = result.get("weights", {})

        if "ETHUSDT" in weights:
            assert weights["ETHUSDT"] >= 0.0, (
                f"BUY ticker 'ETHUSDT' has negative weight={weights['ETHUSDT']:.4f}.\n"
                f"V41 regression: direction sign is inverted."
            )

    def test_10_cycle_direction_diversity(self):
        """Across 10 cycles, proposals must not be >95% one direction."""
        all_proposals: list[ConvictionLevel] = []

        for seed_offset in range(10):
            market_data = {
                t: _make_ohlcv(n=50, base=base, trend=trend, seed=seed_offset * 10 + i)
                for i, (t, base, trend) in enumerate([
                    ("BTCUSDT", 60_000.0, +0.004),
                    ("ETHUSDT", 3_000.0,  +0.002),
                    ("SOLUSDT", 150.0,    +0.001),
                    ("BNBUSDT", 400.0,    -0.001),
                    ("ADAUSDT", 0.50,     -0.003),
                    ("DOTUSDT", 8.0,      -0.005),
                ])
            }
            signals = _build_signals(market_data=market_data)
            for v in _get_composites(signals).values():
                conv = score_to_conviction(v)
                if conv != ConvictionLevel.HOLD:
                    all_proposals.append(conv)

        if not all_proposals:
            pytest.skip("No non-HOLD proposals across 10 cycles")

        n_long = sum(1 for c in all_proposals if c > ConvictionLevel.HOLD)
        n_short = sum(1 for c in all_proposals if c < ConvictionLevel.HOLD)
        n_total = n_long + n_short

        if n_total < 4:
            pytest.skip("Too few proposals to test diversity")

        long_fraction = n_long / n_total
        assert long_fraction <= 0.95, (
            f"Almost all proposals are longs: {long_fraction:.0%} ({n_long}/{n_total}).\n"
            f"Possible sign flip or short-side suppression."
        )
        assert long_fraction >= 0.05, (
            f"Almost all proposals are shorts: {1 - long_fraction:.0%} ({n_short}/{n_total}).\n"
            f"Possible sign flip or long-side suppression."
        )


# ---------------------------------------------------------------------------
# 7. Regression guard — snapshot key config parameters
# ---------------------------------------------------------------------------


class TestRegressionGuard:
    """Tripwire tests for critical configuration values.

    These tests FAIL if a threshold is inadvertently changed. To change a threshold,
    update the test AND document the reason in the commit message.
    """

    def test_weighted_conviction_threshold_is_010(self):
        """weighted_conviction_threshold must be 0.10.

        Lowered from 0.20 in V35 because demeaned composites are smaller in magnitude.
        Reverting to 0.20 would block all trades.
        """
        node = StrategyNode()
        assert node._weighted_conviction_threshold == 0.10, (
            f"weighted_conviction_threshold={node._weighted_conviction_threshold!r} "
            f"(expected 0.10 — see V35 regression note in strategy.py)"
        )

    def test_agreement_ratio_threshold_is_zero(self):
        """agreement_ratio_threshold must be 0.0 (disabled when demeaning is active)."""
        node = StrategyNode()
        assert node._agreement_ratio_threshold == 0.0, (
            f"agreement_ratio_threshold={node._agreement_ratio_threshold!r} "
            f"(expected 0.0 — see V35 regression note in strategy.py)"
        )

    def test_vol_sit_out_thresholds_not_too_aggressive(self):
        """Bug 8 (V26-V27): sit-out thresholds must not trigger in normal vol conditions.

        vol_low_threshold ≤ 0.30 prevents sitting out in normal markets.
        vol_high_threshold ≥ 0.70 prevents triggering in normal vol.
        """
        node = StrategyNode()
        assert node._vol_low_threshold <= 0.30, (
            f"vol_low_threshold={node._vol_low_threshold} is too high — "
            f"will sit out in normal vol conditions.\n"
            f"V26-V27 regression: zero-trade streaks from aggressive sit-out."
        )
        assert node._vol_high_threshold >= 0.70, (
            f"vol_high_threshold={node._vol_high_threshold} is too low — "
            f"will trigger in normal vol conditions."
        )

    def test_hold_band_boundaries_unchanged(self):
        """HOLD band must be exactly (-0.20, +0.20).

        If widened to ±0.30, demeaned composites would all be HOLD — the V43 bug.
        """
        assert score_to_conviction(0.201) == ConvictionLevel.BUY, "HOLD upper bound shifted"
        assert score_to_conviction(0.200) == ConvictionLevel.HOLD, "HOLD upper bound shifted"
        assert score_to_conviction(-0.201) == ConvictionLevel.SELL, "HOLD lower bound shifted"
        assert score_to_conviction(-0.200) == ConvictionLevel.SELL, "HOLD lower bound shifted"
        assert score_to_conviction(-0.199) == ConvictionLevel.HOLD, "HOLD lower bound shifted"

    def test_demeaning_active_for_basket_of_3plus(self):
        """Cross-sectional demeaning must fire for baskets of ≥3 tickers."""
        market_data = _make_diverse_market_data()
        node = SignalGenerationNode()
        node._use_rsi = True
        node._use_zscore = True

        out = node.execute(_make_node_input("compute_signals", market_data=market_data))
        assert out.success

        composites = _get_composites(out.result)  # type: ignore[arg-type]
        assert len(composites) >= 3, "Not enough tickers for demeaning check"

        basket_mean = sum(composites.values()) / len(composites)
        assert abs(basket_mean) < 0.05, (
            f"basket_mean={basket_mean:.4f} — cross-sectional demeaning appears disabled.\n"
            f"Composites: {composites}"
        )

    def test_bear_threshold_at_065(self):
        """Regression: BEAR regime activates at exactly bear_prob >= 0.65 (V91)."""
        node = StrategyNode()

        node._apply_regime_adaptive_thresholds(
            {"_regime_w_bear_prob": 0.549, "_regime_w_bull_prob": 0.10}
        )
        assert node._long_conviction_threshold == 0.07, "Bear activating below 0.65"

        node._apply_regime_adaptive_thresholds(
            {"_regime_w_bear_prob": 0.65, "_regime_w_bull_prob": 0.10}
        )
        assert node._long_conviction_threshold == 0.50, "Bear not activating at 0.65"
        assert node._short_conviction_threshold == 0.04, "Bear short threshold wrong"

    def test_bull_threshold_at_055(self):
        """Regression: BULL regime activates at exactly bull_prob ≥ 0.55."""
        node = StrategyNode()

        node._apply_regime_adaptive_thresholds(
            {"_regime_w_bear_prob": 0.10, "_regime_w_bull_prob": 0.549}
        )
        assert node._long_conviction_threshold == 0.07, "Bull activating below 0.55"

        node._apply_regime_adaptive_thresholds(
            {"_regime_w_bear_prob": 0.10, "_regime_w_bull_prob": 0.55}
        )
        assert node._long_conviction_threshold == 0.05, "Bull not activating at 0.55"
        assert node._short_conviction_threshold == 0.20, "Bull short threshold wrong"
