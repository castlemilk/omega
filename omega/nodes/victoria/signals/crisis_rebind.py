"""V275: recompute-proofing seam for the additive crisis term (flag-gated).

## Why this module exists

The V227 crisis-skew term (`omega/nodes/victoria/signals/crisis_skew.py`) is
applied ONCE, additively, onto each ticker's ``composite`` at
``signal_generation.py`` (the post-demean site). It lives ONLY in ``composite``
— it is deliberately *not* a ``*_signal`` key, so the equal-weight basket
selector and the IC machinery never see it (that is what stops the one-sided
term from being trimmed away).

That design makes the term's efficacy hostage to three defaults, each of which
DISCARDS ``composite`` and rebuilds it from the ``*_signal`` keys — silently
dropping the crisis term while its fire counters keep incrementing:

1. ``strategy._compute_weighted_conviction`` — with ``ic_seed_weighting`` ON
   (opt-in since V275; 18 seeded ICs) the IC-weighted return
   ``fsum(weighted_terms)/total_ic`` never reads ``composite`` at all.
2. ``strategy._apply_regime_signal_weights`` — recomputes ``composite`` as a
   plain mean of ``*_signal`` keys. Inert only because
   ``strategy_selector_enabled`` defaults False.
3. ``strategy._construct_portfolio``'s V141 crisis-dampening and V153
   trend-dampening blocks — the same mean-of-``*_signal`` recompute, inside the
   per-ticker candidate loop, immediately before ``_passes_conviction_filters``.
   The V141 one fires under ``_is_bear_context`` — i.e. exactly when the crisis
   term fires. Inert only because the dampening weights default 1.0.

So the term's measured effect is conditional on three unrelated flags staying
at their current defaults. This module is the seam that makes it INVARIANT.

## Contract

- **The gate is never re-evaluated here.** The bind site stashes the *applied*
  term (``weight * gated_value``) via :func:`stash_applied_term`; this module
  only ever re-applies that stashed float. If the cycle's regime label, the
  drawdown magnitude, or the weight changed after the stash, the STASH is still
  what gets rebound — the stash is the cycle's truth, and the term that entered
  the composite is the term that must survive a recompute of that composite.
  Re-deriving the gate here would be a second, differently-timed gate decision
  and a new determinism channel.
- **Idempotent.** Rebinding twice in a row is a no-op (see
  ``_BOUND_COMPOSITE_KEY``).
- **Flag-gated at the caller.** Every call site checks
  ``features.crisis_term_rebind_enabled`` first; this module additionally
  short-circuits on a missing stash, so an accidental call is inert.
- **Determinism.** The only arithmetic is a 2-element ``math.fsum`` plus the
  same ``[-1, 1]`` clamp the original bind site uses — exact-rounded and
  permutation-invariant (V221 discipline). No new accumulation site.

Counters are integers, observability-only, never fed to a numeric path.
"""

from __future__ import annotations

import math

# Key holding the APPLIED crisis term for this ticker-cycle: ``weight * value``
# as computed at the bind site. Leading underscore ⇒ never picked up by the
# ``*_signal`` basket selectors or the IC loop.
APPLIED_TERM_KEY = "_crisis_term_applied"

# Key holding the composite value that resulted from the most recent bind/rebind.
# The idempotence guard: if ``ts["composite"]`` still equals this, the term is
# already inside the composite and re-adding it would double-count. Any
# recompute replaces ``composite`` with a value derived from the ``*_signal``
# keys, which no longer matches → the seam rebinds.
_BOUND_COMPOSITE_KEY = "_crisis_term_bound_composite"

# Run-scoped fire counters (module-global, mirroring signal_generation's
# ``_CRISIS_SKEW_STATE`` / ``_RV_BRAKE_STATE``). Read by scripts/run_training.py
# into ``results.json['observability']``. Integer-only ⇒ zero determinism impact.
_CRISIS_REBIND_STATE: dict[str, int | bool] = {
    "enabled": False,
    # Number of rebinds onto a recomputed ``composite`` (sites 2 and 3).
    "composite_cycles": 0,
    # Number of IC-weighted conviction returns that carried the term (site 1).
    "ic_cycles": 0,
}


def reset_state() -> None:
    """Reset the run-scoped counters (tests; never called in the training path)."""
    _CRISIS_REBIND_STATE["enabled"] = False
    _CRISIS_REBIND_STATE["composite_cycles"] = 0
    _CRISIS_REBIND_STATE["ic_cycles"] = 0


def stash_applied_term(ts: dict, applied_term: float, bound_composite: float) -> None:
    """Record the term the bind site just added, and the composite it produced.

    Called ONLY from the crisis-term bind site in ``signal_generation``, and only
    when ``crisis_term_rebind_enabled`` is ON — so with the flag OFF these two
    keys never appear in the signal dict at all (no new keys ⇒ no change to any
    key-iterating consumer, fingerprint writer or trace).
    """
    _CRISIS_REBIND_STATE["enabled"] = True
    ts[APPLIED_TERM_KEY] = float(applied_term)
    ts[_BOUND_COMPOSITE_KEY] = float(bound_composite)


def applied_term(ts: dict) -> float:
    """The stashed applied term for this ticker-cycle (0.0 when never stashed)."""
    try:
        return float(ts.get(APPLIED_TERM_KEY, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def apply_crisis_terms(ts: dict) -> bool:
    """Re-apply the stashed crisis term onto ``ts['composite']``, idempotently.

    Returns True iff the term was (re)applied by this call.

    Call this at the END of any site that recomputes ``composite`` — the seam is
    a no-op when there is nothing stashed, when the stashed term is 0.0, when
    ``composite`` is missing/non-numeric, or when ``composite`` is already the
    bound value.
    """
    if not isinstance(ts, dict):
        return False
    term = applied_term(ts)
    if term == 0.0:
        return False
    comp = ts.get("composite")
    if comp is None or not isinstance(comp, (int, float)) or isinstance(comp, bool):
        return False
    comp_f = float(comp)
    if math.isnan(comp_f) or math.isinf(comp_f):
        return False
    bound = ts.get(_BOUND_COMPOSITE_KEY)
    if bound is not None and float(bound) == comp_f:
        # Already carries the term (this is the double-application guard).
        return False
    adj = math.fsum([comp_f, term])
    adj = max(-1.0, min(1.0, adj))
    ts["composite"] = adj
    ts[_BOUND_COMPOSITE_KEY] = adj
    _CRISIS_REBIND_STATE["composite_cycles"] = (
        int(_CRISIS_REBIND_STATE["composite_cycles"]) + 1
    )
    return True


def bind_ic_conviction(ts: dict, ic_value: float) -> float:
    """Add the stashed crisis term to an IC-weighted conviction value.

    The IC path (``strategy._compute_weighted_conviction``) builds its return
    from the ``*_signal`` keys only, so the crisis term — which lives solely in
    ``composite`` — is absent from it. This adds the SAME magnitude the composite
    path used (the stashed ``weight * value``; the weight is never re-derived
    here), with the same 2-element ``fsum`` + ``[-1, 1]`` clamp, so the two paths
    carry an identical term.

    No-op (returns ``ic_value`` unchanged) when nothing is stashed.
    """
    term = applied_term(ts)
    if term == 0.0:
        return ic_value
    adj = math.fsum([float(ic_value), term])
    adj = max(-1.0, min(1.0, adj))
    _CRISIS_REBIND_STATE["ic_cycles"] = int(_CRISIS_REBIND_STATE["ic_cycles"]) + 1
    return adj
