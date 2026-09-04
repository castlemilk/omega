# V306 — A suite nobody could run, and the guards that rotted inside it

**Date:** 2026-09-03
**Status:** infrastructure repaired; 31 stale guards triaged, not yet fixed

## 1. Three faults, one cause

`pytest tests/` appeared to hang. It did not: ten Victoria files run real
multi-cycle simulations taking minutes each and none carried the `slow` marker the
repo already defines. Because the suite was unrunnable, two things rotted inside
it unseen:

1. **Regression guards asserting superseded constants.** `TestRegimeAdaptivity`,
   `TestRegressionGuard` and `test_v49_short_threshold_regression` all assert a
   threshold contract from around V50. It has moved four times since (V84, V87,
   V91, V95). Fixed.
2. **The suite dirtied its own substrate.** `MacroDataCache` resolved its path
   from `__file__` with no override, so any test opening the cache wrote the
   committed `data/macro_cache.db`. `test_cache_manifest` then failed after every
   run — a guard that always fires is one nobody reads, and this one exists
   because that exact file drifted silently once before. Fixed via
   `$OMEGA_MACRO_CACHE_PATH` and a session-scoped autouse fixture.

Verified: `macro_cache.db` is byte-identical after a full run, and
`cache_manifest` failures went 1 → 0.

## 2. The threshold contract, verified directly

Established by calling `_apply_regime_adaptive_thresholds` at each boundary rather
than trusting any of the four sources that described it:

| regime | trigger | long | short |
|---|---|---|---|
| NORMAL | else | **0.07** | **0.07** |
| CRISIS/BEAR | bear_prob ≥ **0.65** (V91, was 0.55) | **0.50** (V84, was a 0.99 block) | **0.04** |
| BULL | bull_prob ≥ 0.55 | 0.05 | 0.20 |

The code was right throughout. The tests, the method's docstring, its own debug
log line, and CLAUDE.md were all wrong — four hand-maintained copies of one table.

## 3. A test that greps source cannot tell a refactor from a regression

`test_v49_short_threshold_regression` asserted by **regex over strategy.py's
source**, which is why its failure message read "strategy.py may have been
refactored; update this regression test to match". That message is the defect: the
test could not distinguish an intentional rename from a behavioural change, so its
failure carried no information.

Rewritten to call the method and assert what it sets, plus the *property* V50 was
actually defending — that the two legs are equal in a regime with no directional
view. Every specific number has moved; the property has held through all of it.
Six tests now pass where two failed.

## 4. The remaining 31, triaged not fixed

Full run: 2,434 passed, 33 failed, all pre-existing (`test_conviction` fails
identically at HEAD with this branch stashed).

| file | n | apparent class |
|---|---|---|
| test_signal_integration | 8 | unexamined |
| test_conviction | 5 | conviction mapping moved (`BUY` where `STRONG_BUY` expected) |
| test_v49_gate_wiring | 4 | V49-era, likely same stale-constant class |
| test_v77_fixes / test_v79_fixes | 6 | version-pinned |
| test_vrp_signal | 2 | unexamined |
| test_orchestrator_v2 | 2 | unexamined |
| standing_gates / grid_ruler / backtest_evaluator / adversarial_v2 | 4 | unexamined |

They are **not** mass-fixed on purpose. Updating an assertion to match current
behaviour is only correct when the behaviour is intentional, and telling a stale
guard from a real regression needs the same per-case check done here for the
thresholds. Doing that in bulk is how a genuine regression gets papered over —
which is exactly the failure this version exists to describe.

## 5. The rule this adds

A test nobody runs is worse than no test: it reports coverage while guarding a
contract that moved ninety versions ago. Two supporting corollaries, both bought
here:

- **A slow test must be marked.** Unmarked, it does not cost minutes, it costs the
  whole suite.
- **A guard that always fires is a broken guard.** `test_cache_manifest` was
  correct on every run and useless on every run, because the signal was constant.
