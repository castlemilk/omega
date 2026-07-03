# REFLECTION_V235 — the campaign's priors were measured on a contaminated yardstick

**Date:** 2026-07-03
**Author:** claude (Fable 5)
**Trigger:** Goodhart tripwire (trigger 0: 8 consecutive refutations on
`snap_crisis_2024aug`) + the V235 walk-forward requirement itself (this reflection
was pre-committed in `V235.md` — "recent reproduction" falsifier fired).
**Inputs:** `V235_WALKFORWARD_RESULTS.md` (64/64 cells, 0 determinism FAILs),
wrap-seam forensic (commit c244568), `V235_UNIVERSE_REVIEW.md`.

## TL;DR

The walk-forward distribution changed every standing verdict at once. The
campaign's single positive number (recent +$4,901) does not reproduce (honest
mean **−$516**, n=10). The banked trend-IC +$1,428 does not ship (mean-Δ
**−$831**, min-Δ −$6,136, n=10). Crisis — the target of 8 consecutive
interventions — is actually the sign-POSITIVE regime (mean **+$819**, n=12);
"crisis is broken" was window selection on wrap-contaminated snapshots. And the
48-cell interim read "trend-IC helps crisis (+$896)" inverted to **−$79 / min
−$7,497** when the last 4 crisis windows landed — partial distributions are not
verdicts either.

## 1. Recent's edge was contamination

+$4,901 sat at N=1 since V221 and anchored the "recent carries the system"
narrative. Its window (90 bars) looped ~3.3× under the 200-cycle replay wrap, and
it was one draw from a distribution whose honest read is mean −$516 / median
−$1,571 / p25 −$2,551 / max +$6,551 (n=10). The best honest recent window
(snap_wf_20260228, +$6,551) shows the magnitude is *reachable* — but the
expectation is negative. Recent is now the **worst** honest regime and the
correct next intervention target.

## 2. The trend-IC bank was contamination

+$1,428 (V229, single 2023q4 window) fails its own pre-committed distributional
bar by a wide margin: mean-Δ −$831, min-Δ −$6,136 on n=10 trend windows.
Worse, it isn't even a benign no-op elsewhere: crisis min-Δ −$7,497
(snap_wf_20250901). The V229 bank entry is annotated REFUTED-BY-DISTRIBUTION;
V236 executes its refutation branch (zero code ships).

## 3. Crisis was never the broken regime

Honest crisis distribution: mean +$819, median +$249, n=12 — sign-positive.
Eight refutations (V227→V234) were aimed at one wrap-contaminated 63-bar window
(snap_crisis_2024aug, looping ~6× at 200 cycles) drawn from a wide distribution.
The Goodhart tripwire existed precisely for this; it fired late because the
walk-forward instrument didn't exist yet. Crisis's real issue is **tail width**
(p25 −$2,135, min −$5,819), a risk-control problem, not a sign problem.

## 4. The partial-grid inversion (a second-order Goodhart lesson)

At 48/64 cells the crisis Δ read +$896 pro-trendic and briefly suggested "ship
trend-IC for crisis — inverse of the brief." The final 4 crisis windows
(20241205 Δ−$2,330, 20250901 Δ−$7,497) flipped the mean negative. Rule: **a
distribution verdict is only readable at its pre-registered n.** Interim means
from a partially-complete grid have the same epistemic status as single windows.

## 5. The wrap-seam retroactively invalidates V225–V234 measurements

Every standing single-window number was produced by 200-cycle runs on 60–90-bar
windows — all wrapped, all booking PnL across a fictitious price seam. This
includes both sides of every V225–V234 Δ. Deltas *may* partially cancel the
artifact (same seam both arms) but positions differ across arms, so no pre-V235
Δ can be certified. All V225–V234 verdicts are hereby downgraded to
"directionally unknown"; nothing shipped in that span except V227's skew gate,
which survives only as the standing-main definition the V235 distribution itself
was measured on (its +$630 justification is void, but the config IS the measured
baseline now — changing it requires a new walk-forward run, not a revert).

## 6. Consequences for V236 / V237 / V238

- **V236 (was: ship trend-IC):** refutation branch executes — no ship, for ANY
  regime (trend bar failed; the interim crisis-inversion idea died at 64 cells).
  V236 is re-pointed at the worst honest regime: **recent** (mean −$516).
- **V237 (was: portfolio-level crisis cap as the LAST crisis intervention):**
  crisis is sign-positive; per V237's own closing rule the *crisis optimization
  program closes* — but as OBE (overtaken by evidence), not as a 9th refutation:
  the mechanism was never tested against the honest baseline. Crisis becomes a
  monitored tail-risk report. The portfolio-level corr-spike cap mechanism is
  retargeted as a **tail-width risk control measured on the full 32-window
  distribution** (crisis p25 −$2,135 and recent p25 −$2,551 are the tails it
  must move) rather than a crisis-mean intervention.
- **V238 (universe/blacklist flip):** unchanged in intent, but its baseline is
  now the walk-forward distribution; its pre-registration must quote these
  numbers, not any pre-V235 scalar.
- All three MUST measure against `data/walk_forward_manifest.json` distributions.
  Single-window bars in their texts are void.

## Skill-mandated sections

### Eval stability & noise floor
64/64 cells DETERMINISM PASS at $0.00 spread; three N=2 sentinels (one per
regime) byte-identical at sleep=0 from committed state. The V214→V221 arc's
noise floor ($0.00 hermetic) holds on the new window set. Eval stability is NOT
the problem this reflection addresses — objective validity was.

### Variance estimate
Across-window σ (main): crisis ≈ $4.3k, trend ≈ $3.9k, recent ≈ $3.5k (n=10–12).
**Any future claim must clear the distribution bar (mean + tail floor), not a
per-window dollar threshold.** Within-window replicate variance is $0.00
(hermetic), so multi-seed runs are not the lever; multi-WINDOW is.

### Subsystem audit
V227–V234: 8 hypotheses, all crisis-mean-targeted (additive terms ×4, site ×1,
weight ×1, sizing ×1, selection pre-work ×1) — the audited subsystem was fine;
the OBJECTIVE was invalid. This reflection retires the crisis-mean objective
itself, which is the deeper version of the subsystem-loop rule.

### Revert-and-branch
No revert: standing main (V227-skew config) is the measured baseline of the new
yardstick. Branch point is objective-level, not code-level.

### Untouched dimensions (source list for V236+)
Recent-regime interventions (NEVER directly targeted — recent was assumed won);
tail-width/risk-control objectives (vs mean objectives); portfolio-level exposure
mechanics (V237 mechanism, still untested); universe composition (V238);
exit-strategy layer (untouched since V184 profit-lock); cross-window robust
sizing (sizing that degrades gracefully across regime draws).

### Observability-gap audit (what would have caught this sooner?)
1. **Wrap-seam guard (SHIPPED, c244568):** replay wrap now logs WARNING; grid
   caps cycles at min_bars−31. Was a `debug` log — a 200-cycle run on 63 bars
   wrapped ~6× silently for ten versions. Cost of the gap: V225–V234.
2. **Distribution-first reporting (SHIPPED, this grid):** aggregator emits
   per-regime mean/p25/min + pre-registered verdicts; README now carries
   distributions, not high-waters.
3. **Partial-grid guard (SHIP with V236, S):** aggregator should refuse verdict
   emission when cells_done < cells_total for the targeted regime (the 48-cell
   crisis inversion would have been suppressed). → OBSERVABILITY-BACKLOG if not
   in V236.
4. **Window-provenance stamp (queued, S):** every results.json should carry
   `bars, cycles, wrapped: bool` so any future consumer can detect seam exposure
   mechanically. → OBSERVABILITY-BACKLOG.
5. **Host-tmp redirect assertion (SHIPPED, this session):** run_training.py now
   asserts tmp sinks follow OMEGA_AUDIT_OUTPUT_DIR and banners their location —
   the ENOSPC class that killed three grids (V232/V233/V235) is closed.
