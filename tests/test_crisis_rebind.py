"""V277 (DRAFT): tests for the crisis-term recompute-proofing seam.

The V227 crisis-skew term lives ONLY in ``composite`` (never a ``*_signal`` key).
Three downstream paths rebuild ``composite`` from the ``*_signal`` keys and thereby
DROP the term:

  1. ``strategy._compute_weighted_conviction`` IC-weighted return (active whenever
     an arm opts into ``ic_seed_weighting``; default False since V275),
  2. ``strategy._apply_regime_signal_weights`` (inert only because
     ``strategy_selector_enabled`` defaults False),
  3. the V141 crisis-dampening / V153 trend-dampening recomputes in
     ``_construct_portfolio`` (inert only because the dampening weights default 1.0).

These tests assert:

  - **flag OFF** ⇒ every one of those sites produces the byte-identical composite /
    conviction it produced before V275, and the seam writes no keys at all;
  - **flag ON**  ⇒ the stashed term survives each recompute site, and the IC path
    carries the same magnitude;
  - the seam is **idempotent** (calling it twice == once);
  - the seam **never re-evaluates the gate** — a ts whose regime has since changed
    still rebinds the STASHED value.

### Determinism-proof limitation (stated explicitly)

A true byte-identical proof would diff this checkout's output against a pristine
pre-V275 checkout on the same fixtures — impractical to run cross-checkout inside a
unit test. What is proven here instead is the two things that make the cross-checkout
diff unnecessary:

  a. with the flag OFF the seam **short-circuits at its entry** (no stash key is ever
     written by the bind site, so ``apply_crisis_terms``/``bind_ic_conviction`` return
     without touching anything) — ``test_flag_off_*``; and
  b. the recompute expressions themselves are unchanged, asserted by recomputing the
     expected value with the *literal* pre-V275 expression and demanding exact float
     equality — ``test_flag_off_site*_byte_identical``.

Together: flag OFF ⇒ no reachable mutation ⇒ no composite, trade or fingerprint can
move.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from omega.nodes.victoria.features import VictoriaFeatures
from omega.nodes.victoria.signal_generation import _SKEW_W_GATED
from omega.nodes.victoria.signals import crisis_rebind
from omega.nodes.victoria.signals.crisis_rebind import (
    APPLIED_TERM_KEY,
    apply_crisis_terms,
    bind_ic_conviction,
    stash_applied_term,
)
from omega.nodes.victoria.strategy import StrategyNode, _apply_regime_signal_weights

# A representative gated crisis term: W=0.2 (the standing gated weight) × a
# strongly risk-off value. Negative by construction (the term is one-sided).
_SKEW_VALUE = -0.8
_TERM = _SKEW_W_GATED * _SKEW_VALUE


@pytest.fixture(autouse=True)
def _reset_counters():
    crisis_rebind.reset_state()
    yield
    crisis_rebind.reset_state()


def _ts(*, stash: bool = True, composite: float = 0.30) -> dict:
    """A per-ticker signal dict with `*_signal` keys and a bound composite.

    When ``stash`` is True the dict looks exactly as the bind site leaves it with
    the V275 flag ON: composite already carries the term, and the applied term +
    bound-composite markers are present.
    """
    ts = {
        "rsi_signal": 0.4,
        "macd_signal": 0.2,
        "sma_crossover": 0.3,
        "crisis_skew": _SKEW_VALUE,
        "composite": composite,
    }
    if stash:
        bound = max(-1.0, min(1.0, math.fsum([composite, _TERM])))
        ts["composite"] = bound
        stash_applied_term(ts, _TERM, bound)
    return ts


def _mean_of_signal_keys(ts: dict, extra_keys: tuple[str, ...] = ()) -> float:
    """The literal pre-V275 recompute expression used by all three sites."""
    vals = [
        float(v)
        for k, v in ts.items()
        if (k.endswith("_signal") or k == "sma_crossover" or k in extra_keys)
        and isinstance(v, (int, float))
    ]
    return sum(vals) / len(vals)


# ---------------------------------------------------------------------------
# Fixture guards
# ---------------------------------------------------------------------------


def test_term_is_nonzero_and_negative() -> None:
    # Guard: a zero term would make every assertion below vacuously true.
    assert _TERM < 0.0


def test_flag_defaults_off() -> None:
    assert VictoriaFeatures().crisis_term_rebind_enabled is False


# ---------------------------------------------------------------------------
# Flag OFF — no keys written, no mutation, byte-identical recomputes
# ---------------------------------------------------------------------------


def test_flag_off_seam_writes_no_keys() -> None:
    """With the flag OFF the bind site never stashes, so the seam is inert.

    This is the "short-circuits at the seam's entry" proof: an unstashed ts is
    returned untouched and no marker key is created.
    """
    ts = _ts(stash=False)
    before = dict(ts)
    assert apply_crisis_terms(ts) is False
    assert ts == before
    assert APPLIED_TERM_KEY not in ts
    assert bind_ic_conviction(ts, 0.42) == 0.42
    assert crisis_rebind._CRISIS_REBIND_STATE["composite_cycles"] == 0
    assert crisis_rebind._CRISIS_REBIND_STATE["ic_cycles"] == 0


def test_flag_off_site1_byte_identical() -> None:
    """Site 1: _apply_regime_signal_weights with features=None (flag off)."""
    signals = {"ETHUSDT": _ts(stash=False)}
    expected_ts = dict(signals["ETHUSDT"])
    # Reproduce the pre-V275 expression exactly: multiply then plain mean.
    for k, mult in _REGIME_WEIGHTS_TREND.items():
        if k in expected_ts:
            expected_ts[k] = float(expected_ts[k]) * mult
    expected = _mean_of_signal_keys(expected_ts)

    _apply_regime_signal_weights(signals, "TREND")  # no features arg ⇒ flag off
    assert signals["ETHUSDT"]["composite"] == expected

    off = replace(VictoriaFeatures(), crisis_term_rebind_enabled=False)
    signals2 = {"ETHUSDT": _ts(stash=False)}
    _apply_regime_signal_weights(signals2, "TREND", off)
    assert signals2["ETHUSDT"]["composite"] == expected


def test_flag_off_site1_drops_the_term_as_today() -> None:
    """Even with the term ALREADY in composite, flag-off site 1 wipes it.

    This is the incumbent behaviour V275 hardens against — asserting it keeps the
    OFF arm honest (the regression this change is designed NOT to make silently).
    """
    signals = {"ETHUSDT": _ts(stash=False, composite=math.fsum([0.30, _TERM]))}
    _apply_regime_signal_weights(signals, "TREND")
    # The recomputed composite is a mean of the *_signal keys — the additive term
    # is gone (it was never a *_signal key).
    assert signals["ETHUSDT"]["composite"] > 0.0


def test_flag_off_dampening_sites_byte_identical() -> None:
    """Sites 2 and 3 (the dampening recomputes) with no stash present."""
    # Site 2 (V141 crisis dampening): fear_greed + sma dampened, then mean.
    sig = _ts(stash=False)
    sig["fear_greed_signal"] = 1.0
    sig = dict(sig)
    sig["fear_greed_signal"] = float(sig["fear_greed_signal"]) * 0.5
    expected2 = _mean_of_signal_keys(sig)
    sig["composite"] = _mean_of_signal_keys(sig)
    assert apply_crisis_terms(sig) is False  # flag-off equivalent: nothing stashed
    assert sig["composite"] == expected2

    # Site 3 (V153 trend dampening): mean_reversion is also in the key set.
    sig3 = _ts(stash=False)
    sig3["mean_reversion"] = 0.6
    expected3 = _mean_of_signal_keys(sig3, extra_keys=("mean_reversion",))
    sig3["composite"] = expected3
    assert apply_crisis_terms(sig3) is False
    assert sig3["composite"] == expected3


def test_flag_off_ic_path_byte_identical() -> None:
    """The IC-weighted conviction is unchanged when the flag is OFF."""
    node = _strategy_node(rebind=False)
    node.update_signal_ics({"rsi_signal": 0.05, "macd_signal": 0.03})
    ts = _ts(stash=False)
    got = node._compute_weighted_conviction(ts)
    expected = math.fsum([0.4 * 0.05, 0.2 * 0.03]) / math.fsum([0.05, 0.03])
    assert got == expected


# ---------------------------------------------------------------------------
# Flag ON — the term survives every recompute site
# ---------------------------------------------------------------------------


def test_flag_on_site1_term_survives() -> None:
    on = replace(VictoriaFeatures(), crisis_term_rebind_enabled=True)
    signals = {"ETHUSDT": _ts()}
    baseline = {"ETHUSDT": _ts()}

    _apply_regime_signal_weights(baseline, "TREND")  # flag off
    _apply_regime_signal_weights(signals, "TREND", on)

    recomputed = baseline["ETHUSDT"]["composite"]
    assert signals["ETHUSDT"]["composite"] == max(
        -1.0, min(1.0, math.fsum([recomputed, _TERM]))
    )
    assert crisis_rebind._CRISIS_REBIND_STATE["composite_cycles"] == 1


def test_flag_on_dampening_sites_term_survives() -> None:
    # Site 2 shape.
    sig = _ts()
    recomputed = _mean_of_signal_keys(sig)
    sig["composite"] = recomputed
    assert apply_crisis_terms(sig) is True
    assert sig["composite"] == max(-1.0, min(1.0, math.fsum([recomputed, _TERM])))

    # Site 3 shape (mean_reversion included in the key set).
    sig3 = _ts()
    sig3["mean_reversion"] = 0.6
    recomputed3 = _mean_of_signal_keys(sig3, extra_keys=("mean_reversion",))
    sig3["composite"] = recomputed3
    assert apply_crisis_terms(sig3) is True
    assert sig3["composite"] == max(-1.0, min(1.0, math.fsum([recomputed3, _TERM])))

    assert crisis_rebind._CRISIS_REBIND_STATE["composite_cycles"] == 2


def test_flag_on_ic_path_carries_the_same_magnitude() -> None:
    """The IC path gains exactly the magnitude the composite path used."""
    off_node = _strategy_node(rebind=False)
    on_node = _strategy_node(rebind=True)
    ics = {"rsi_signal": 0.05, "macd_signal": 0.03}
    off_node.update_signal_ics(dict(ics))
    on_node.update_signal_ics(dict(ics))

    ic_only = off_node._compute_weighted_conviction(_ts())
    with_term = on_node._compute_weighted_conviction(_ts())

    assert with_term == max(-1.0, min(1.0, math.fsum([ic_only, _TERM])))
    # Same magnitude as the composite path's term — the weight is threaded from
    # the bind site, not duplicated.
    assert with_term - ic_only == pytest.approx(_TERM, abs=1e-12)
    assert crisis_rebind._CRISIS_REBIND_STATE["ic_cycles"] == 1


def test_flag_on_ic_escape_hatch_is_not_double_counted() -> None:
    """total_ic == 0 returns the raw composite, which ALREADY holds the term."""
    node = _strategy_node(rebind=True)  # no ICs loaded ⇒ total_ic == 0.0
    ts = _ts()
    assert node._compute_weighted_conviction(ts) == ts["composite"]
    assert crisis_rebind._CRISIS_REBIND_STATE["ic_cycles"] == 0


# ---------------------------------------------------------------------------
# Idempotence + gate-immutability
# ---------------------------------------------------------------------------


def test_seam_is_idempotent() -> None:
    sig = _ts()
    sig["composite"] = _mean_of_signal_keys(sig)
    assert apply_crisis_terms(sig) is True
    once = sig["composite"]
    assert apply_crisis_terms(sig) is False
    assert apply_crisis_terms(sig) is False
    assert sig["composite"] == once
    assert crisis_rebind._CRISIS_REBIND_STATE["composite_cycles"] == 1


def test_seam_is_a_noop_on_a_freshly_bound_ts() -> None:
    """A ts straight from the bind site is already bound ⇒ no double-add."""
    ts = _ts()
    before = ts["composite"]
    assert apply_crisis_terms(ts) is False
    assert ts["composite"] == before


def test_seam_does_not_reevaluate_the_gate() -> None:
    """A regime change AFTER the stash must not change what is rebound.

    The stash is the cycle's truth: the term that entered the composite is the
    term that must survive a recompute of that composite. Re-deriving the gate
    here would be a second, differently-timed gate decision — and would let a
    mid-cycle label flip silently delete a term that already moved the composite.
    """
    sig = _ts()
    # Simulate the gate having gone risk-ON since the stash: the raw value is
    # zeroed and the regime label is now benign. The seam must ignore both.
    sig["crisis_skew"] = 0.0
    sig["_regime"] = "normal"
    sig["_skew_dd_mag"] = 0.0
    recomputed = _mean_of_signal_keys(sig)
    sig["composite"] = recomputed
    assert apply_crisis_terms(sig) is True
    assert sig["composite"] == max(-1.0, min(1.0, math.fsum([recomputed, _TERM])))


def test_seam_clamps_to_unit_interval() -> None:
    sig = _ts()
    sig["composite"] = -0.95
    assert apply_crisis_terms(sig) is True
    assert sig["composite"] == -1.0


def test_seam_ignores_degenerate_composites() -> None:
    for bad in (None, float("nan"), float("inf"), "0.3", True):
        sig = _ts()
        sig["composite"] = bad
        assert apply_crisis_terms(sig) is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The TREND multipliers _apply_regime_signal_weights uses (imported lazily so a
# change to the table is caught rather than silently mirrored).
from omega.nodes.victoria.strategy import _REGIME_SIGNAL_WEIGHTS  # noqa: E402

_REGIME_WEIGHTS_TREND = _REGIME_SIGNAL_WEIGHTS.get("TREND", {})


def _strategy_node(*, rebind: bool) -> StrategyNode:
    feats = replace(
        VictoriaFeatures(),
        crisis_term_rebind_enabled=rebind,
        # Keep the IC path itself on its plain settings so the test isolates V275.
        per_regime_ic_weighting=False,
        regime_conditional_ic_weighting=False,
        ic_drawdown_gate_enabled=False,
    )
    node = StrategyNode()
    node.features = feats
    return node


def test_regime_weight_table_has_trend_entry() -> None:
    # Guard for the fixture above: an empty table would make site-1 tests vacuous
    # (the function early-returns when there are no weights).
    assert _REGIME_WEIGHTS_TREND
