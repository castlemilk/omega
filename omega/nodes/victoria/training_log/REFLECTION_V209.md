# Reflection — V209 (post-V209, blocking V210 pre-registration)

**Date:** 2026-06-03
**Author:** claude (mandatory reflection trigger #2: pre-registered no-op moves gate by >>2σ)
**Scope:** V208a's published recent noise floor ($0.06) failed to reproduce in V209's audit ($2,773 spread). Second gate-specific channel still alive on recent/trend. Crisis fence holds.

This reflection answers the five questions the skill mandates before any new V### pre-registration.

---

## 1. Eval stability — what the artifacts on disk actually say

V209 ran a full 3-gate × 2-pair audit at the V208a HEAD strategy.py with seeds and caches pinned identically across all six runs (sha256-verified frozen-cache pre/post). Yet:

| Gate | r1 vs r2 PnL spread | Trade Δ | Cycle-1 composite Δ |
|---|---:|---:|---:|
| recent | **$2,773** | 3 | 1e-4 |
| trend  | **$1,500** | 3 | 0 (cycle 26: 3e-4) |
| crisis | **$56**    | 0 | **1e-2** |

The V208a single-pair recent measurement ($0.06, Δ=0) did NOT reproduce in V209. V209 recent_r1 reproduces V208a r1 to within $0.03 (−$2,292.98 vs V208a's −$2,292.95) — so r1 is deterministic-against-V208a — but V209 recent_r2 = +$480.51 whereas V208a recent_r2 = −$2,292.89. **V208a's r2 was the outlier**, not V209's.

Direct evidence from trades.csv (trade-by-trade alignment across r1/r2 by `(cycle, symbol, side)`):

- **Crisis**: 65/65 trade match. Selection is fully decision-stable. Only exit-side PnL drifts (first diff at cycle 30 ADA short: −$775.64 vs −$781.94, $6 drift). Within-pair σ ≈ $28 across all trades' accumulated exit-side noise.
- **Recent**: 68/71 vs 68 common; r1 has 3 extra trades (earliest cycle 184 NEAR long). Entry prices identical on all common trades. First PnL drift at cycle 59 ETH long (entry identical, exit Δ $0.06). Selection is decision-stable through cycle 183; one late marginal candidate bifurcates.
- **Trend**: 82 common / 88 r1 / 91 r2. First trade with **differing entry_price** at cycle 38 ETH long (r1=$2,243.37 vs r2=$2,192.95 — $50 apart, same cycle, same side). Selection bifurcates at cycle 38 (entry) and cycle 39 (only-r2 ARB short).

**Verdict.** V208a's $0.06 was a one-pair fluke produced by a coincidence of accumulated exit-side drift that nearly cancelled. The structural noise floor on recent at V208a HEAD is **whatever the σ of the accumulated exit-side drift × marginal-trade-bifurcation distribution is** — V209's single-pair measurement says it's ~$2,700, but n=1 is not a σ.

**Rule going forward.** A noise-floor claim requires ≥2 pairs OR a structural argument why the fix must work. Single-pair drops to $0.06 are *suggestive*, not *proof*.

---

## 2. Variance estimate (and the 2σ threshold for V210 onward)

We have one pair per gate at V208a HEAD. That's n=1; σ is undefined. The honest summary:

| Gate | n | Mean PnL | Within-pair spread | Inferred σ floor* |
|---|---:|---:|---:|---:|
| recent | 1 pair | −$906 | $2,773 | ≥ $1,386 (half-spread) — call it $2,773 until we have n≥4 |
| trend  | 1 pair | +$15,679 | $1,500 | ≥ $750 — call it $1,500 |
| crisis | 1 pair | −$17,763 | $56 | ≥ $28 — call it $28 |

\* For n=1, the spread/2 is a lower-bound on σ. A real σ requires the variance batch V203 ran (seeds {1,2,3,42} × cell). That batch is the right move *after* the second channel is closed on recent/trend, not before — running it now would only re-confirm the noise we already see.

**Operating rules until then:**
- **Crisis**: σ ≈ $28. V210/V211 high-water claims on crisis need Δ > $56 (2σ).
- **Recent**: σ ≥ $1,386 (likely $2,773+). V210/V211 high-water claims on recent need Δ > $5,547 OR an n≥4 batch first. Single-seed deltas on recent are **"in noise"** until proven otherwise.
- **Trend**: σ ≥ $750 (likely $1,500). Trend claims need Δ > $3,000.

These supersede V203's variance table for the post-V208a code state.

---

## 3. Subsystem-patching audit

The last three versions all targeted the eval-noise infrastructure, not strategy.py-as-strategy:

| Version | Subsystem touched | Mechanism |
|---|---|---|
| V207a | run env + funding cache | PYTHONHASHSEED=42 pin + frozen funding cache |
| V207b | `_construct_portfolio` rolling-z over `_signal_history` | static bisect — root-cause localization, no code change |
| V208  | `_construct_portfolio` `.items()` traversals | canonical `sorted(..., key=ticker)` × 8 call-sites |
| V209  | methodology only | 3-gate × 2-pair audit at V208a HEAD |

This is **not** "patching the same subsystem 3 versions running" in the dead-end sense the reflection trigger guards against, because:
1. Each patch was structurally distinct (env vs cache vs sort) and each measurably collapsed a known leak channel.
2. Strategy.py-as-strategy hasn't been touched — these are eval-instrumentation fixes. The gate movement they're chasing is "noise floor", not "PnL high-water".
3. Crisis fence is now real — V209 establishes −$17,763 ± $28 as the first working crisis ceiling whose floor is defended by a structural argument (sort) and a 2-pair measurement (Δ=0).

But it IS the same broader subsystem ("eval determinism") three versions running. The recent/trend channel hasn't been closed; V210 must localize it *before* attempting another fence patch — V207b-style diff-the-artifacts-not-rerun is the correct move.

**Decision.** Continue the eval-determinism patching one more iteration to localize the recent/trend channel. If V211's fence-patch fails to collapse recent to <$200, escalate to:
- Either an n=4 variance batch on V208a HEAD recent — accept "$2,500 is the structural noise floor of this snapshot's marginal-trade distribution" and rebaseline thresholds to be insensitive at that scale,
- Or revert-and-branch from V204 (last surviving trend high-water) and re-derive crisis from a different architectural starting point.

---

## 4. Revert-and-branch option

Crisis high-water is now V209 (current HEAD). Recent has no surviving high-water. Trend's V204 +$22,105 is unreproducible at V208a HEAD; V209 reads +$14,929/+$16,429.

Structural delta HEAD vs V204: V208a's canonical sort across `_construct_portfolio`. V204 itself was a strategy.py revert to V172. V204's trend number was measured *before* the eval-determinism work — it sits at an unknown point in the within-pair spread distribution of un-fenced V172 code (V206b showed V172's trend spread > $14,000 pre-fence). So V204 +$22,105 is **almost certainly inside the V172-era trend noise envelope**, not a real high-water.

**No revert is justified.** The current HEAD has the strongest defensible crisis ceiling we've ever measured (−$17,763 ± $28, 35× tighter than V206b's $1,978 crisis floor). Reverting would discard that win without buying a confirmable trend or recent number.

---

## 5. Untouched dimensions (for V211+ once eval is trusted)

If V210/V211 close the recent/trend channel, the next strategy.py-as-strategy version should come from this list, NOT from another threshold tweak:

1. **Strategy_selector_enabled flag** — V204/V205 audit confirmed every V156/V157/V170/V172_pruned path is runtime-inert under `v93_baseline`. Turning the flag on is a structural change with no parameter knob.
2. **Snapshot diversity** — V199–V209 has measured 3 snapshots. The variance batch needs to extend to 6–8 snapshots (different regime cohorts) before any signal-edge claim is generalizable.
3. **Exit-side architecture** — crisis loss is structurally exit-side per V202 (same trade count, same loss across opposite sizing regimes). The crisis short-bias path is decision-stable but exit-loss-heavy. A pure exit experiment (e.g., regime-conditional trailing stop, time-bounded MAE cap) is untried since V199.
4. **Marginal-candidate stabilization** — recent's one-trade-at-cycle-184 bifurcation is the canonical "near-threshold candidate flips on noise" pathology. Hysteresis (require N consecutive cycles above threshold before entry) would dampen this without changing strong-signal behavior.
5. **Composite-formation determinism (V211 candidate)** — `basket_std` (strategy.py:1722-1735) and `basket_mean` (strategy.py:2130-2138) both iterate `signals.items()` unsorted before summing. Floating-point summation order-sensitivity here produces the cycle-1 1e-4 composite drift on recent and 1e-2 on crisis. This is the next eval-determinism fence, not a strategy change.

---

## V210 deliverable

V210 is **methodology-only** — cycle-1 sub-signal/sub-trade bisect on V209's existing artifacts, no rerun, no strategy.py change. Output:
1. Identify the first cycle/symbol where r1 and r2 trade behavior bifurcates per gate.
2. Identify the structural code path responsible.
3. Explain the crisis-vs-recent/trend asymmetry.
4. Pre-register V211 as the fence-patch on whatever path V210 localizes.

Crisis high-water is locked at **−$17,763 ± $28** as the working ceiling. Recent and trend remain "noise-floor unresolved".
