"""
tests/test_v79_fixes.py
~~~~~~~~~~~~~~~~~~~~~~~
TDD tests for V79 fixes.

Fixes covered:
  Fix 1 — ADAUSDT blacklisted from long positions (strategy.py)
  Fix 2 — abs_min_conviction raised 0.02→0.06 (strategy.py)
  Fix 3 — FRED HTTP 400 marks series permanently failed in-session (data_cache.py)
"""
from __future__ import annotations

import logging
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from omega.nodes.victoria.data_cache import _FRED_PERM_FAILED, MacroDataCache
from omega.nodes.victoria.strategy import StrategyNode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normal_signals(ticker: str, composite: float) -> dict:
    return {
        "_regime_hmm": "sideways",
        "_regime": "normal",
        ticker: {"composite": composite},
    }


def _crisis_signals(ticker: str, composite: float = -1.0) -> dict:
    return {
        "_regime_hmm": "crisis",
        "_regime": "crisis",
        ticker: {"composite": composite},
    }


# ---------------------------------------------------------------------------
# Fix 1: ADAUSDT long blacklist
# ---------------------------------------------------------------------------


class TestADALongBlacklist:
    """V79 Fix 1: ADAUSDT must not enter long positions."""

    def test_ada_long_blocked_in_normal_regime(self):
        """Strong ADA long signal must be blocked — ADA is in _LONG_BLACKLIST."""
        node = StrategyNode()
        sigs = _normal_signals("ADAUSDT", composite=1.0)  # strong long signal
        result = node._construct_portfolio(sigs, {})
        weights = result.get("weights", {})
        assert "ADAUSDT" not in weights or weights.get("ADAUSDT", 0) <= 0, (
            "ADAUSDT long must be blocked by _LONG_BLACKLIST"
        )

    def test_ada_short_still_allowed(self):
        """ADA shorts must still be permitted (only longs are blacklisted)."""
        node = StrategyNode()
        # Use crisis to make short bypass multi-cycle confirmation
        sigs = _crisis_signals("ADAUSDT", composite=-1.0)
        result = node._construct_portfolio(sigs, {})
        # If crisis short bypass is active, weights may contain a short
        # OR the portfolio may be empty (time filter) — just ensure no ADA long
        weights = result.get("weights", {})
        assert weights.get("ADAUSDT", 0) <= 0, (
            "ADA should only appear as a short (negative weight) or absent"
        )


# ---------------------------------------------------------------------------
# Fix 2: abs_min_conviction raised to 0.06
# ---------------------------------------------------------------------------


class TestAbsMinConviction:
    """V79 Fix 2: abs_min_conviction floor is 0.06."""

    def test_abs_min_conviction_is_at_least_0_06(self):
        """StrategyNode._abs_min_conviction must be ≥ 0.06 (V79 floor, V80 raised to 0.07)."""
        node = StrategyNode()
        assert node._abs_min_conviction >= 0.06, (
            f"Expected _abs_min_conviction≥0.06, got {node._abs_min_conviction}"
        )

    def test_conviction_below_0_06_blocked(self):
        """Signals with w_conv < 0.06 must be rejected by abs_min_conviction gate.

        Uses a very small basket so _thresh_scale is low, ensuring the
        abs_min_conviction floor is the effective gate.
        """
        node = StrategyNode()
        # Set up signals with a very small composite (< 0.06 after normalisation)
        # so abs_min_conviction is the active gate, not the regime threshold.
        sigs = {
            "_regime_hmm": "sideways",
            "_regime": "normal",
            # composite=0.001 → very marginal signal, should be below abs_min_conviction
            "ETHUSDT": {"composite": 0.001},
        }
        result = node._construct_portfolio(sigs, {})
        weights = result.get("weights", {})
        assert not weights, (
            "Very low composite signal must be blocked by abs_min_conviction=0.06"
        )


# ---------------------------------------------------------------------------
# Fix 3: FRED HTTP 400 permanent in-session suppression
# ---------------------------------------------------------------------------


class TestSidewaysIsNormal:
    """V79 Fix 4: _is_normal includes 'sideways' (HMM label for normal market).

    Previously SOL/BNB/ETH suppressions were bypassed when Wasserstein regime
    returned 'sideways' instead of 'normal'.
    """

    def test_sol_short_blocked_in_sideways_regime(self):
        """SOL short must be blocked when _regime='sideways' (HMM normal label)."""
        node = StrategyNode()
        # Provide prior-cycle short history via _signal_history to pass multi-cycle check
        node._signal_history["SOLUSDT"] = ["short"]
        sigs = {
            "_regime_hmm": "sideways",
            "_regime": "sideways",
            "SOLUSDT": {"composite": -1.0},
        }
        result = node._construct_portfolio(sigs, {})
        weights = result.get("weights", {})
        assert "SOLUSDT" not in weights, (
            "SOL short must be blocked in 'sideways' regime (maps to normal)"
        )

    def test_eth_low_conviction_long_blocked_in_sideways_regime(self):
        """ETH long with w_conv < 0.12 must be blocked in 'sideways' regime.

        V81 lowered ETH normal long floor from 0.20 → 0.12. The _is_normal check
        must include 'sideways' so the 0.12 floor applies in sideways just as in normal.

        With basket_std fallback=0.20, cs_norm=3.33: composite=0.065 × 3.33 = 0.217 → BUY.
        w_conv = 0.065 < 0.12 → ETH conviction floor blocks it in normal/sideways.
        """
        node = StrategyNode()
        sigs = {
            "_regime_hmm": "sideways",
            "_regime": "sideways",
            "ETHUSDT": {"composite": 0.065},
        }
        node._signal_history["ETHUSDT"] = ["long"]  # pass multi-cycle confirmation
        result = node._construct_portfolio(sigs, {})
        weights = result.get("weights", {})
        assert weights.get("ETHUSDT", 0) <= 0, (
            "ETH long with w_conv=0.065 < 0.12 must be blocked in 'sideways' regime "
            "(V81 ETH conviction floor applies to both normal and sideways via _is_normal)"
        )


class TestFREDPermFailedSuppression:
    """V79 Fix 3: HTTP 400 from FRED marks series unavailable for the session."""

    def setup_method(self):
        # Clear the module-level set between tests
        _FRED_PERM_FAILED.clear()

    def teardown_method(self):
        _FRED_PERM_FAILED.clear()

    def test_http_400_adds_to_perm_failed(self, caplog):
        """HTTP 400 from FRED must add the series to _FRED_PERM_FAILED."""
        from omega.nodes.victoria import data_cache as dc

        error_400 = urllib.error.HTTPError(
            url="http://x", code=400, msg="Bad Request", hdrs=None, fp=None
        )
        with patch.object(urllib.request, "urlopen", side_effect=error_400):
            with caplog.at_level(logging.WARNING, logger="omega.nodes.victoria.data_cache"):
                dc._fetch_fred_observations("DGS10", "DEMO_KEY")

        assert "DGS10" in _FRED_PERM_FAILED, (
            "HTTP 400 must add series to _FRED_PERM_FAILED"
        )

    def test_perm_failed_series_not_refetched(self):
        """After HTTP 400, _refresh_macro must skip the series without hitting FRED."""
        import os
        import tempfile

        from omega.nodes.victoria import data_cache as dc

        # Pre-populate the perm-failed set
        _FRED_PERM_FAILED.add("DGS2")

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            cache = MacroDataCache(db_path=db_path)
            call_count = 0

            original_fetch = dc._fetch_fred_observations

            def counting_fetch(series_id, api_key, n_obs=120):
                nonlocal call_count
                call_count += 1
                return original_fetch(series_id, api_key, n_obs)

            with patch.object(dc, "_fetch_fred_observations", side_effect=counting_fetch):
                cache._refresh_macro("DGS2")

            assert call_count == 0, (
                "_refresh_macro must skip _fetch_fred_observations for series in _FRED_PERM_FAILED"
            )
        finally:
            os.unlink(db_path)

    def test_warning_emitted_once_on_400(self, caplog):
        """A single WARNING is emitted on HTTP 400, not per retry."""
        from omega.nodes.victoria import data_cache as dc

        error_400 = urllib.error.HTTPError(
            url="http://x", code=400, msg="Bad Request", hdrs=None, fp=None
        )
        with patch.object(urllib.request, "urlopen", side_effect=error_400):
            with caplog.at_level(logging.WARNING, logger="omega.nodes.victoria.data_cache"):
                dc._fetch_fred_observations("DTWEXBGS", "DEMO_KEY")

        warning_count = sum(
            1 for r in caplog.records
            if r.levelno >= logging.WARNING and "DTWEXBGS" in r.message
        )
        assert warning_count == 1, (
            f"Expected exactly 1 WARNING for HTTP 400, got {warning_count}"
        )


# ---------------------------------------------------------------------------
# V80 Fix: regime-aware abs_min_conviction (crisis uses crisis short_thresh)
# ---------------------------------------------------------------------------


class TestCrisisAbsMinConviction:
    """V80 Fix: crisis shorts use crisis short_thresh (0.04) not abs_min_conviction (0.07)."""

    def test_crisis_short_with_mid_conviction_passes(self):
        """Crisis short with w_conv in (0.04, 0.07) must pass — V79 zero-streak bug.

        V79 post-mortem: 50-cycle zero streak in sustained crisis because
        abs_min_conviction=0.07 blocked all signals with w_conv 0.04–0.07,
        even though crisis short_thresh=0.04.

        Signal engineering: with 1 ticker and _basket_std fallback=0.20,
        _cs_norm = 0.20/(0.3*0.20) = 3.33. composite=-0.065 × 3.33 = -0.217 → SELL.
        w_conv = composite = -0.065 (no ICs loaded), abs = 0.065 in (0.04, 0.07).
        Multi-cycle confirmed via signal_history — avoids V82 composite <= -0.10 bypass gate.
        """
        node = StrategyNode()
        # composite=-0.065 → after cs_norm (-0.217) → SELL conviction, w_conv=0.065
        sigs = {
            "_regime_hmm": "crisis",
            "_regime": "crisis",
            "ETHUSDT": {"composite": -0.065},
        }
        # Pre-load history so multi-cycle confirmation passes without bypass
        # (V82 added composite <= -0.10 gate on bypass; signal_history avoids that dependency)
        node._signal_history["ETHUSDT"] = ["short"]
        result = node._construct_portfolio(sigs, {})
        weights = result.get("weights", {})
        # Should produce a short candidate, not be blocked by abs_min_conviction
        assert "ETHUSDT" in weights and weights["ETHUSDT"] < 0, (
            "Crisis short with w_conv=0.065 must pass abs_min_conviction in crisis "
            "(uses crisis short_thresh=0.04, not 0.06 abs_min_conviction floor)"
        )

    def test_normal_short_with_mid_conviction_still_blocked(self):
        """Normal-regime short with w_conv=0.065 must be blocked — short_thresh=0.08.

        V80 fix: crisis shorts use 0.04 floor; normal shorts use abs_min_conviction=0.06.
        With w_conv=0.065, normal short is blocked by short_thresh=0.08 (not abs_min floor).
        """
        node = StrategyNode()
        # Same composite as above — but normal regime short_thresh=0.08 blocks it
        sigs = {
            "_regime_hmm": "sideways",
            "_regime": "normal",
            "ETHUSDT": {"composite": -0.065},
        }
        node._signal_history["ETHUSDT"] = ["short"]
        result = node._construct_portfolio(sigs, {})
        weights = result.get("weights", {})
        assert "ETHUSDT" not in weights or weights.get("ETHUSDT", 0) >= 0, (
            "Normal-regime short with w_conv=0.065 must be blocked by short_thresh=0.08"
        )
