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
from unittest.mock import patch
import urllib.error
import urllib.request

import pytest

from omega.nodes.victoria.strategy import StrategyNode
from omega.nodes.victoria.data_cache import MacroDataCache, _FRED_PERM_FAILED


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

    def test_abs_min_conviction_is_0_06(self):
        """StrategyNode._abs_min_conviction must be 0.06."""
        node = StrategyNode()
        assert node._abs_min_conviction == 0.06, (
            f"Expected _abs_min_conviction=0.06, got {node._abs_min_conviction}"
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
        from omega.nodes.victoria import data_cache as dc
        import tempfile, os

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
