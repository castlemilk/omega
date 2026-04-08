"""
tests/test_v77_fixes.py
~~~~~~~~~~~~~~~~~~~~~~~
TDD tests for V77 fixes. These tests must FAIL before implementation.

Fixes covered:
  Fix 1 — Crisis short multi-cycle bypass (strategy.py)
  Fix 2 — Cross-asset signal null warnings (fear_greed, funding_rate)
  Fix 3 — Zero-streak watchdog escalation in strategy.py
"""
from __future__ import annotations

import logging
import urllib.request
from unittest.mock import patch

import pytest

from omega.nodes.victoria.signals.fear_greed import FearGreedSignal
from omega.nodes.victoria.signals.funding_rate import FundingRateSignal
from omega.nodes.victoria.strategy import StrategyNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _crisis_signals(ticker: str, composite: float = -1.0) -> dict:
    """Minimal signals dict that triggers crisis regime with one short candidate."""
    return {
        "_regime_hmm": "crisis",
        "_regime": "crisis",
        ticker: {"composite": composite},
    }


def _normal_signals(ticker: str, composite: float) -> dict:
    """Minimal signals dict in normal (sideways) regime."""
    return {
        "_regime_hmm": "sideways",
        "_regime": "normal",
        ticker: {"composite": composite},
    }


# ---------------------------------------------------------------------------
# Fix 1: Crisis short multi-cycle bypass
# ---------------------------------------------------------------------------


class TestCrisisShortBypass:
    """V77 Fix 1: crisis shorts with |composite| > 0.06 skip multi-cycle confirmation."""

    def setup_method(self):
        self.node = StrategyNode()

    def test_strong_crisis_short_bypasses_multicycle_on_first_call(self):
        """Crisis short with |composite| > 0.06 must enter candidates on first call.

        Before fix: multi-cycle check blocks first-cycle shorts in all regimes.
        After fix: bypass when is_crisis AND composite < -0.06.
        """
        sigs = _crisis_signals("SOLUSDT", composite=-1.0)
        result = self.node._construct_portfolio(sigs, {})
        weights = result.get("weights", {})
        # Without the fix this is empty (multi-cycle blocks the first cycle)
        assert weights, (
            "Strong crisis short (composite=-1.0) should bypass multi-cycle confirmation"
        )
        assert any(w < 0 for w in weights.values()), (
            "Short candidate should produce a negative weight"
        )

    def test_normal_regime_short_still_blocked_first_cycle(self):
        """Normal-regime shorts must still require two consecutive cycles."""
        sigs = _normal_signals("SOLUSDT", composite=-1.0)
        result = self.node._construct_portfolio(sigs, {})
        weights = result.get("weights", {})
        # Normal shorts need prior-cycle confirmation — first call always empty
        assert not weights or all(w >= 0 for w in weights.values()), (
            "Normal-regime short must not bypass multi-cycle confirmation"
        )

    def test_crisis_long_hard_blocked(self):
        """Crisis longs remain hard-blocked (long_thresh ≈ 0.99) regardless of composite."""
        sigs = _crisis_signals("SOLUSDT", composite=1.0)  # strong long signal
        result = self.node._construct_portfolio(sigs, {})
        weights = result.get("weights", {})
        # Longs in crisis should never appear (hard-blocked by 0.99 threshold)
        assert not weights or all(w < 0 for w in weights.values()), (
            "Crisis longs must remain hard-blocked"
        )

    def test_crisis_short_second_cycle_works_without_bypass(self):
        """Second crisis short cycle (2+ cycles apart) must produce candidates.

        After the bypass allows first-cycle entry and sets _last_trade_cycle,
        we simulate two more cycles (execution_count += 2) so the time filter clears.
        """
        node = StrategyNode()
        sigs = _crisis_signals("SOLUSDT", composite=-1.0)
        # First call: bypass lets it through, sets _last_trade_cycle = 0
        node._construct_portfolio(sigs, {})
        # Advance execution_count by 2 to clear the time filter (requires gap >= 2)
        node._execution_count += 2
        # Second call: time filter clear, prior "short" in history → produces candidate
        result2 = node._construct_portfolio(sigs, {})
        weights = result2.get("weights", {})
        assert weights and any(w < 0 for w in weights.values()), (
            "Second crisis short cycle (after time filter clears) must produce candidates"
        )


# ---------------------------------------------------------------------------
# Fix 2: Cross-asset signal null warnings
# ---------------------------------------------------------------------------


class TestFundingRateNullWarning:
    """V77 Fix 2: FundingRateSignal._fetch_all_rates should warn on network failure."""

    def test_network_failure_emits_warning_not_debug(self, caplog):
        """Network errors in _fetch_all_rates must log at WARNING level.

        Before fix: logger.debug("FundingRateSignal fetch failed: ...") — silent in prod.
        After fix:  logger.warning("...") — visible in training logs.
        """
        sig = FundingRateSignal()
        with patch.object(
            urllib.request, "urlopen", side_effect=Exception("429 Too Many Requests")
        ):
            with caplog.at_level(logging.DEBUG, logger="omega.nodes.victoria.signals.funding_rate"):
                sig._fetch_all_rates(["ETHUSDT"])

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            "_fetch_all_rates must emit WARNING on network failure so it shows in training logs"
        )


class TestFearGreedNullWarning:
    """V77 Fix 2: FearGreedSignal should warn when cold-cache fetch returns no data."""

    def test_cold_cache_fetch_failure_emits_warning(self, caplog):
        """On first fetch failure (cold cache), FearGreedSignal must warn.

        Before fix: no warning when _fetch() returns [] and cache is cold — silently returns 0.0.
        After fix: logger.warning emitted so training logs expose the null signal source.
        """
        sig = FearGreedSignal()
        # Ensure cache is cold
        sig._cache_ts = 0.0
        sig._cache = []
        sig._last_signal = 0.0

        with patch.object(sig, "_fetch", return_value=[]):
            with caplog.at_level(logging.DEBUG, logger="omega.nodes.victoria.signals.fear_greed"):
                result = sig.compute()

        assert result == 0.0, "Should still return 0.0 on failure"
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            "FearGreedSignal must warn when cold-cache fetch returns no data"
        )


# ---------------------------------------------------------------------------
# Fix 3: Zero-streak watchdog escalation in strategy.py
# ---------------------------------------------------------------------------


class TestZeroStreakWatchdog:
    """V77 Fix 3: StrategyNode should emit WARNING after >30 zero-candidate cycles."""

    def test_warning_emitted_after_threshold(self, caplog):
        """After 31 consecutive zero-candidate cycles, strategy must emit a WARNING.

        Before fix: no such counter or warning exists in strategy.py.
        After fix:  StrategyNode._zero_candidate_streak > 30 → logger.warning.
        """
        node = StrategyNode()
        # HOLD signals → always zero candidates
        hold_sigs = _normal_signals("ETHUSDT", composite=0.0)

        with caplog.at_level(logging.WARNING, logger="omega.nodes.victoria.strategy"):
            for _ in range(32):
                node._construct_portfolio(hold_sigs, {})

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            "StrategyNode must emit WARNING after >30 consecutive zero-candidate cycles"
        )
        # Warning must include diagnostic context
        combined = " ".join(r.message for r in warning_records).lower()
        assert any(kw in combined for kw in ("zero", "streak", "candidate", "watchdog")), (
            "Warning message must contain diagnostic context about the zero-streak"
        )

    def test_no_warning_before_threshold(self, caplog):
        """No warning before 30 zero-candidate cycles."""
        node = StrategyNode()
        hold_sigs = _normal_signals("ETHUSDT", composite=0.0)

        with caplog.at_level(logging.WARNING, logger="omega.nodes.victoria.strategy"):
            for _ in range(29):
                node._construct_portfolio(hold_sigs, {})

        # Filter for strategy-level zero-streak warnings (not other warnings)
        streak_warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and any(kw in r.message.lower() for kw in ("zero_candidate", "zero-candidate", "streak"))
        ]
        assert not streak_warnings, (
            "StrategyNode must not warn at 29 zero-candidate cycles (threshold is >30)"
        )

    def test_streak_resets_when_candidates_found(self, caplog):
        """Zero-streak counter resets when a cycle produces candidates."""
        node = StrategyNode()
        hold_sigs = _normal_signals("ETHUSDT", composite=0.0)

        # Accumulate 29 zero-candidate cycles
        for _ in range(29):
            node._construct_portfolio(hold_sigs, {})

        # One cycle that produces candidates (crisis short bypass)
        node._construct_portfolio(_crisis_signals("SOLUSDT", composite=-1.0), {})

        # Now run 5 more zero cycles — streak reset means no warning
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="omega.nodes.victoria.strategy"):
            for _ in range(5):
                node._construct_portfolio(hold_sigs, {})

        streak_warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and any(kw in r.message.lower() for kw in ("zero_candidate", "zero-candidate", "streak"))
        ]
        assert not streak_warnings, (
            "Zero-streak counter must reset after a cycle with candidates"
        )
