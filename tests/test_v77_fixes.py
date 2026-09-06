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
        # V95 gates the HMM/label crisis paths on bear_prob >= 0.45: a label alone
        # no longer puts the strategy in crisis, the probability model must confirm
        # it. These fixtures predate that and supplied no bear_prob, so they had
        # silently stopped producing a crisis regime at all — which is why every
        # crisis assertion in this file was failing.
        "_regime_w_bear_prob": 0.70,
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
        sigs = _crisis_signals("ETHUSDT", composite=-1.0)
        result = self.node._construct_portfolio(sigs, {})
        weights = result.get("weights", {})
        # Without the fix this is empty (multi-cycle blocks the first cycle)
        assert weights, (
            "Strong crisis short (composite=-1.0) should bypass multi-cycle confirmation"
        )
        assert any(w < 0 for w in weights.values()), (
            "Short candidate should produce a negative weight"
        )

    def test_normal_regime_short_first_cycle_needs_high_conviction(self):
        """Normal-regime first-cycle shorts are allowed, but only on conviction.

        Was "must still require two consecutive cycles". V79 introduced a
        confirmation bypass for high-conviction entries and V81/V88 lowered it
        0.20 -> 0.12 -> 0.09 -> 0.05, because V86/V87 ran 150- and 167-cycle zero
        streaks with the bypass unreachable at real conviction levels. A
        composite of -1.0 clears 0.05 comfortably, so a first-cycle short here is
        the intended behaviour, not a leak.
        """
        # A maximal signal goes through by design (the V88 bypass at w_conv >= 0.05).
        self.node._construct_portfolio(_normal_signals("ETHUSDT", composite=-1.0), {})
        # The bypass is conviction-gated, so a MAXIMAL signal is expected through.
        # What must not happen is an entry with no conviction behind it.
        weak = self.node._construct_portfolio(_normal_signals("ETHUSDT", composite=-0.001), {})
        assert not weak.get("weights"), (
            "A near-zero composite must not bypass multi-cycle confirmation"
        )

    def test_crisis_longs_are_suppressed_not_blocked(self):
        """Crisis longs face a raised bar, not a hard block.

        Was "hard-blocked (long_thresh ~ 0.99)". V84 lowered that to 0.50 because
        0.99 combined with _thresh_scale was mathematically unreachable — it was a
        block dressed as a threshold. The contract is now that a crisis long must
        clear a far higher bar than a normal one, which is what this asserts.
        """
        # Put the node in crisis, then inspect the bar it set.
        self.node._construct_portfolio(_crisis_signals("ETHUSDT", composite=1.0), {})
        assert self.node._long_conviction_threshold >= 0.50, (
            "Crisis long threshold must stay far above the normal-regime bar"
        )
        assert self.node._long_conviction_threshold > self.node._short_conviction_threshold, (
            "Crisis must favour shorts over longs"
        )

    def test_crisis_short_second_cycle_works_without_bypass(self):
        """Second crisis short cycle (2+ cycles apart) must produce candidates.

        After the bypass allows first-cycle entry and sets _last_trade_cycle,
        we simulate two more cycles (execution_count += 2) so the time filter clears.
        """
        node = StrategyNode()
        sigs = _crisis_signals("ETHUSDT", composite=-1.0)
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


_FUNDING_LOGGER = "omega.nodes.victoria.signals.funding_rate"
_FEAR_GREED_LOGGER = "omega.nodes.victoria.signals.fear_greed"


class TestFundingRateNullWarning:
    """V77 Fix 2: FundingRateSignal._fetch_all_rates should warn on network failure."""

    def test_network_failure_emits_warning_not_debug(self, caplog):
        """Network errors in _fetch_all_rates must log at WARNING level.

        Before fix: logger.debug("FundingRateSignal fetch failed: ...") — silent in prod.
        After fix:  logger.warning("...") — visible in training logs.

        Two things this test used to get wrong, both of which made it assert
        nothing while appearing to pass:

        1. It asked for ETHUSDT, which the committed macro cache HAS a row for.
           A failed refresh leaves that stale row in place, `_get_cached_rate`
           returns it, and the warning is correctly not emitted. The symbol has
           to be one the cache does not carry for the failure path to be reached
           at all.
        2. It accepted a WARNING from ANY logger. What it was actually catching
           was MacroDataCache's one-shot "FRED_API_KEY not set" warning, emitted
           when the cache singleton is first built. So the test passed on my
           machine (the singleton happened to be built inside its caplog window)
           and failed on CI (an earlier test in the same xdist worker had already
           built it). Records are now filtered to the logger under test.
        """
        sig = FundingRateSignal()
        # Build the cache singleton first, so its one-shot startup warnings are
        # emitted OUTSIDE the window this test inspects.
        sig._fetch_all_rates(["ETHUSDT"])

        caplog.clear()
        with (
            patch.object(
                urllib.request, "urlopen", side_effect=Exception("429 Too Many Requests")
            ),
            caplog.at_level(logging.DEBUG, logger=_FUNDING_LOGGER),
        ):
            # A symbol with no cached row: every source fails, nothing to fall
            # back on, so the signal has no rate and must say so.
            rates = sig._fetch_all_rates(["DOGEUSDT"])

        assert rates == {"DOGEUSDT": None}, "the fixture must actually reach the failure path"
        warning_records = [
            r for r in caplog.records if r.levelno >= logging.WARNING and r.name == _FUNDING_LOGGER
        ]
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

        with (
            patch.object(sig, "_fetch", return_value=[]),
            caplog.at_level(logging.DEBUG, logger="omega.nodes.victoria.signals.fear_greed"),
        ):
            result = sig.compute()

        assert result == 0.0, "Should still return 0.0 on failure"
        # Filtered by logger for the same reason as the funding test above: an
        # unfiltered WARNING check passes on whatever else happens to log.
        warning_records = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and r.name == _FEAR_GREED_LOGGER
        ]
        assert warning_records, "FearGreedSignal must warn when cold-cache fetch returns no data"


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

        # A cycle that actually produces candidates. Driving this through the signal
        # pipeline mid-sequence does NOT work: after hold cycles the direction history
        # is "hold", so the crisis short is held for confirmation and the cycle is
        # itself zero-candidate — the original test asserted a reset that correctly
        # never happened. The watchdog was right; the setup was wrong. So the streak
        # is set directly and the reset is exercised on a node that can trade.
        node = StrategyNode()
        node._zero_candidate_streak = 29
        produced = node._construct_portfolio(_crisis_signals("ETHUSDT", composite=-1.0), {})
        assert produced.get("weights"), "precondition: this cycle must produce candidates"
        assert node._zero_candidate_streak == 0, (
            "streak must reset on a cycle that produced candidates"
        )

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


# ---------------------------------------------------------------------------
# FFG blocks must survive into the decision trace
# ---------------------------------------------------------------------------


class TestFFGReachesDecisionTrace:
    """A ticker the four-factor gate blocks must say so in _last_ticker_decisions.

    The trace at the end of ``_construct_portfolio`` is a *reconstruction*: it
    re-derives each ticker's fate from signals and conviction, and knows nothing
    about FFG, which runs later in the cycle. FFG used to record its blocks by
    writing a plain ``{"action": "SKIP_FFG", ...}`` dict straight into
    ``_last_ticker_decisions`` — which the reconstruction's wholesale rebind then
    overwrote. So an FFG-blocked ticker was reported as whatever the
    reconstruction guessed, and the block itself appeared nowhere.

    There was no test over this path at all, which is how it stayed that way.
    """

    def test_blocked_ticker_is_recorded_as_filtered_by_ffg(self, monkeypatch):
        from omega.core.decision_snapshot import TickerDecision
        from omega.nodes.victoria import four_factor_gate as ffg_mod

        node = StrategyNode()
        node.features.four_factor_and_gate = True

        def _always_fail(self, ctx):
            return ffg_mod.GateResult(
                all_pass=False,
                cross_market_divergence=False,
                disposition=True,
                capital_velocity=True,
                pair_network=True,
                failing_gates=["cross_market_divergence"],
            )

        monkeypatch.setattr(ffg_mod.FourFactorGate, "evaluate", _always_fail)

        # A maximal crisis short: without FFG this trades (see TestCrisisShortBypass).
        result = node._construct_portfolio(_crisis_signals("ETHUSDT", composite=-1.0), {})

        assert not result.get("weights"), "FFG failing every gate must block the entry"

        trace = node._last_ticker_decisions
        assert "ETHUSDT" in trace, "the blocked ticker must still appear in the trace"
        decision = trace["ETHUSDT"]
        assert isinstance(decision, TickerDecision), (
            "the trace holds TickerDecision only; a plain dict here is the old bug"
        )
        assert decision.final_action == "FILTERED"
        assert "cross_market_divergence" in decision.filter_reason, (
            f"filter_reason should name the failing gate, got {decision.filter_reason!r}"
        )
        assert any("ffg:" in f for f in decision.filters_applied), (
            f"filters_applied should record the FFG step, got {decision.filters_applied}"
        )

    def test_unblocked_ticker_carries_no_ffg_filter(self, monkeypatch):
        """The converse: a passing gate must not leave an FFG mark on the trace."""
        from omega.nodes.victoria import four_factor_gate as ffg_mod

        node = StrategyNode()
        node.features.four_factor_and_gate = True

        def _always_pass(self, ctx):
            return ffg_mod.GateResult(
                all_pass=True,
                cross_market_divergence=True,
                disposition=True,
                capital_velocity=True,
                pair_network=True,
            )

        monkeypatch.setattr(ffg_mod.FourFactorGate, "evaluate", _always_pass)

        node._construct_portfolio(_crisis_signals("ETHUSDT", composite=-1.0), {})
        decision = node._last_ticker_decisions["ETHUSDT"]
        assert not any("ffg:" in f for f in decision.filters_applied)
        assert "ffg(" not in decision.filter_reason


class TestZeroCandidateCycleStillTraces:
    """A cycle where nothing survives the filters must still explain itself.

    ``_construct_portfolio`` returns early when no candidate clears the filter
    stack, and the decision-trace builder used to sit only on the path below that
    return. So the cycles whose reasoning is most worth having — V86 and V87 each
    logged zero-candidate streaks of 150+ cycles — wrote an EMPTY per-ticker trace
    into the snapshot. The absence looked like "no tickers considered" rather than
    "considered and rejected, here is the gate".
    """

    def test_no_candidates_still_produces_a_per_ticker_trace(self):
        from omega.core.decision_snapshot import TickerDecision

        node = StrategyNode()
        # A near-zero composite clears no threshold, so no candidate survives.
        result = node._construct_portfolio(_normal_signals("ETHUSDT", composite=0.0001), {})

        assert not result.get("weights"), "fixture must produce a zero-candidate cycle"
        trace = node._last_ticker_decisions
        assert "ETHUSDT" in trace, (
            "a rejected ticker must still appear in the trace; an empty trace is the bug"
        )
        assert isinstance(trace["ETHUSDT"], TickerDecision)
        assert trace["ETHUSDT"].final_action in ("FILTERED", "HOLD")
        assert trace["ETHUSDT"].filters_applied, "the trace must name the gate that stopped it"
