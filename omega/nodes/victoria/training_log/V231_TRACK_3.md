# V231 — Track 3: V218.E reproducibility + V231 acceptance bar

**Scope:** Read-only analysis. (a) Reproduce V218.E from committed/on-disk artifacts. (b) Propose the concrete acceptance bar for V231's distributional re-baseline, per overlay. (c) Honest N=3 statistical framing. (d) Recommendation on whether to re-measure V229's trend-IC in V231 or defer to V232.

---

## (a) V218.E reproduction — CONFIRMED from on-disk artifacts

**Claim (V218-matrix.md:175, :212, :231–233):** under *identical code + cache*, the crisis gate flips
**−$2,862.86 (2022h1, 31t) → +$13,051.74 (2020q1, 28t)** purely by swapping
`snap_crisis_2022h1.json ↔ snap_crisis_2020q1.json`. The matrix headline rounds these to −$2,863 / +$13,052.

**Reproduction status: ✅ both numbers reproduce exactly, byte-for-byte across both determinism runs.**

| Quantity | Source artifact (on disk) | total_closed | total_pnl_usd | realised_pnl_engine | win_rate |
|---|---|---:|---:|---:|---:|
| Crisis 2022h1 (cell B no-op control), r1 | `.claude/worktrees/v218-b-v170-ic/data/v218b_audit_crisis_r1_results.json` | 31 | **−2862.86** | −2862.86 | 0.4194 |
| Crisis 2022h1 (cell B), r2 | `.../v218b_audit_crisis_r2_results.json` | 31 | **−2862.86** | −2862.86 | 0.4194 |
| Crisis 2020q1 (cell E), r1 | `.claude/worktrees/v218-e-snap-crisis-2020q1/data/v218e_audit_crisis_r1_results.json` | 28 | **+13051.74** | +13051.74 | 0.50 |
| Crisis 2020q1 (cell E), r2 | `.../v218e_audit_crisis_r2_results.json` | 28 | **+13051.74** | +13051.74 | 0.50 |

- **Within-cell determinism:** r1 == r2 exactly for both cells ($0.00 spread), matching the matrix's "6/6 PASS $0.00".
- **The swap is the only variable:** cell B and cell E share identical committed code + cache (the matrix's independence argument); E's `recent`/`trend` gates are noted as byte-identical to B since they run the standard snapshots. The crisis delta is therefore attributable solely to `snap_crisis_2020q1.json` vs `snap_crisis_2022h1.json`.
- **Both snapshots are present on disk:** `data/snapshots/snap_crisis_2020q1.json` (50K, 91 daily bars Jan–Apr 2020, spans the COVID crash) and `data/snapshots/snap_crisis_2022h1.json` (107.5K, 151 bars, LUNA/FTX). So the V218.E result is **re-runnable from committed state today.**

**Magnitude caveat (carried forward — load-bearing, do NOT bank the +$13k as a real edge):**
Per V218-matrix.md:238–239 and V230_DECISION.md:44, **macro is zero in BOTH runs** — `macro_cache` holds 4 rows (DGS2/DGS10/DTWEXBGS/VIXCLS) all with `date='__failed__'`, `value=0.0` from a failed FRED warm-up that silently persisted zeros. So both the −$2,863 and the +$13,052 ran with VIX=0, yields=0, dollar-index=0. The **sign-flip / window-dependence is real and reproducible**; the **+$13k magnitude is "suspect (zero-macro)"** and not bankable. This does not weaken V218.E's role as the V231 existence proof — its purpose is to demonstrate **between-window crisis variance ≈ $16k under identical code**, which it does at $0.00 internal spread.

**Discrepancy flag — the README V217 baseline is NOT the comparator.** V218-matrix.md:180–204 documents that the README V217 OFF baseline (−$1,905.71 / +$1,039.24 / −$2,199.50, 38/35/38t) is **not reproducible from committed state** (it depended on transient session-local cache: the failed-macro stub + a session-specific `funding_rate_cache` snapshot). The reproducible, cell-clean crisis 2022h1 baseline is the **cell-B no-op number −$2,862.86 (31t)**, which is what V218.E uses and what reproduces above. Anyone re-deriving V218.E must use cell B, not the README.

**Overlay-delta anchors (confirmed in source):**
- **V227 crisis-skew = +$630.08** standalone crisis Δ (V227.md:13, :139, :147). Baseline that run: crisis −$3,621.25 (31t) → skew-only −$2,991.17 (33t) → +$630.08 (29t target). Determinism N=2 confirm $0.00.
- **V229 drawdown-gated-IC = +$1,428.16** banked **trend-only** overlay, hermetic, N=2, X=0.12 (V229.md:21, :147, :202, :226). It is explicitly *un-promotable to the crisis/standing line* — trend-only.
- **V218.E between-window crisis swing ≈ $16k** (−$2,863 → +$13,052 = $15,915 gross). This is the spread the V230 pre-reg falsifier (< ~$2k) is testing against.

---

## (b) Proposed V231 acceptance bar (per overlay)

V231 is **harness + eval only — no `strategy.py` logic change** (V230_DECISION.md:55). It cannot move PnL; it re-baselines the standing main (equal-weight + V227 skew at X=0.12 ON) as a **distribution** across ≥3 windows per regime, and re-tests whether V227's +$630 and V229's +$1,428 survive the cross-window spread. The bar below operationalizes the V230 pre-reg falsifier (V230_DECISION.md:61).

### B0. Standing-main crisis spread — the primary instrument test
Run standing main (equal-weight + V227 skew ON @ X=0.12) on **≥3 crisis windows** (2020q1 + 2022h1 already frozen; add a 3rd via the V215 recipe). Report **mean ± spread** (spread = max − min across windows).

| Outcome | Criterion | Verdict on the 3-gate set |
|---|---|---|
| **Wide** (instrument was inadequate — V231 hypothesis CONFIRMED) | crisis cross-window spread **≥ ~$2k** | Single-window gate was hiding generalization. Distributional eval was the right call. Proceed: V232 ships Track B's RV-term-structure brake measured on this distribution. |
| **Narrow** (instrument was adequate — V231 hypothesis FALSIFIED) | crisis spread **< ~$2k** AND V227 +$630 + V229 +$1,428 reproduce within that spread on **every** window | The 3-gate set was representative all along; revert to shipping Track B's brake directly as "V231-redux", no harness change. |

The **$2k threshold is the pre-registered falsifier** (V230_DECISION.md:61, restated :44). It is well below the V218.E observed $16k swing, so the expected result is "wide" — but the test is genuine because zero-macro could be inflating that swing.

### B1. V227 crisis-skew (+$630 standalone) — "does it generalize?"
The +$630 is **one window**, ~52σ over the $12 noise floor *within* that window (V230_DECISION.md:44) — precise but possibly window-luck. Tiered bar, in increasing strength:

- **Minimum to keep ON (weak — "not actively harmful"):** crisis Δ (skew-ON minus skew-OFF) **> 0 on ≥2 of 3** windows AND **mean-Δ > 0**. Below this, the +$630 is one-window noise and skew should be reconsidered.
- **Target to call "generalizes" (recommended bar):** **mean-Δ > 0** AND **lower-quartile-Δ > 0** (with N=3, "lower-quartile" ≈ the min of the 3; i.e. **min-Δ > 0** — positive on *every* window). This is the honest "additive brake helps in every crisis we can see" bar.
- **Stretch (bankable as a durable edge):** min-Δ > 0 AND mean-Δ materially above the per-window noise floor (mean-Δ ≫ ~$12·√3).

**Recommendation:** adopt the **target** bar — `mean-Δ > 0 AND min-Δ > 0`. Requiring positivity on *every* window is the correct guard against Goodharting a single window (the explicit V230 diagnosis: "we are Goodharting three single windows").

### B2. V229 trend-IC (+$1,428 banked, trend-only) — same structure on the trend regime
Apply the identical tiered bar on **≥2 trend windows** (only 1 trend window is frozen today; a 2nd must be added via V215 recipe for any distributional read):
- **Minimum to keep parked-as-best-trend-lever:** trend Δ **> 0 on ≥half** the windows AND **mean-Δ > 0**.
- **Target:** **mean-Δ > 0 AND min-Δ > 0** across the trend windows.
- Note: this remains **trend-only / un-promotable** to the standing line regardless of outcome (V229.md:209). Passing the bar upgrades confidence in parking it for V232+, not in shipping it now.

### B3. V228 stack (crisis-skew + trend-IC) — only if re-measured
V228 stacking was refuted at single-window (REFLECTION_V229.md: 4th IC refutation). If re-measured distributionally, the bar is **interaction-positive**: stacked crisis-Δ **≥ max(skew-alone crisis-Δ, 0)** on mean AND min across windows — i.e. the stack must not *destroy* the skew's standalone gain. Given 5 prior selection/re-weight refutations, **default = do NOT re-measure V228 in V231** unless B0 comes back "wide" and there is spare window budget.

---

## (c) Honest statistical framing for N=3

**The user already knows N=3 is small. The real question is whether N=3 is a *meaningful upgrade over N=1* — and the answer is YES, but with sharply limited inferential reach.**

What N=3 (per regime) **can** support:
- **Existence / refutation of cross-window variance.** V218.E already proves with N=2 that crisis swings $16k under identical code. A 3rd window can only *confirm or shrink* that — it directly tests the falsifier (B0). This is the load-bearing inference and N=3 handles it.
- **Sign-consistency as a weak generalization signal.** "Positive on 3/3 windows" is genuinely more than "positive on 1/1." Under a null of 50/50 per-window sign, 3/3 same-sign has p ≈ 0.125 (one-tailed) — *suggestive, not significant*, but a real upgrade from N=1 where p = 0.5 (uninformative).
- **A range / spread, not a point.** Reporting mean ± (max−min) replaces a false-precision point estimate with an honest interval. That alone changes how every downstream verdict is read.

What N=3 **cannot** support (would need N≈10):
- **Any CI / t-test on the mean-Δ.** With N=3 the t-multiplier is ~4.3 (df=2, 95%); a "+$630 mean" with a few-$k spread has a CI spanning zero. You cannot claim "significantly > 0."
- **Distinguishing +$630 from +$200 from +$50.** The between-window SD swamps the effect size; magnitude is unrankable at N=3.
- **Detecting a real but modest brake** that helps in ~60% of crises — the power at N=3 is far too low; absence of a 3/3 sweep is *not* evidence of no effect.

**Framing verdict:** N=3 is **a meaningful upgrade over N=1 for the one question V231 exists to answer** (does the single-window number generalize / is the eval instrument hiding cross-window variance — a *yes/no, sign-and-spread* question). It is **not** enough to *bank* an effect size or claim statistical significance on any Δ. The acceptance bars in (b) are deliberately written as **sign-and-spread rules (mean-Δ>0, min-Δ>0, spread vs $2k)** — *not* significance tests — precisely because that is the strongest claim N=3 honestly supports. Treat every V231 verdict as **directional with an explicit "N=3, may not generalize" caveat**, exactly as V230_DECISION.md:55 already concedes for the fallback path.

---

## (d) Recommendation: re-measure V229 trend-IC in V231, or defer to V232?

**Recommendation: DEFER V229 trend-IC to V232 (or later); do the cheap part only if it's free.**

Reasoning:
1. **V231's pre-registered job is crisis-focused.** The hypothesis (V230_DECISION.md:61) is about whether single-window *crisis* gates hide generalization, anchored on V218.E's crisis swing. The crisis re-baseline (B0 + B1) is the load-bearing deliverable. Trend-IC is a secondary, **trend-only / un-promotable** lever (V229.md:209) — re-measuring it does not unblock the crisis decision or the V232 Track-B brake.
2. **Window budget is the binding constraint.** Crisis already has 2 frozen windows + needs a 3rd. A trend distributional read needs a **2nd trend window that does not yet exist** — it must be freshly frozen via the V215 recipe, which is the expensive, error-prone part (the secondary falsifier in V230_DECISION.md:61 is literally "if no additional window is freezable at acceptable effort"). Spending that effort on the trend lever competes with freezing the 3rd *crisis* window, which is higher priority.
3. **Diminishing inferential return.** With only 2 trend windows, the trend bar collapses to "positive on both" — barely above the N=1 it replaces, and on a lever we already classify as parked/trend-only. The marginal confidence gained does not justify pulling forward.

**Concrete proposal:**
- **V231 = crisis distributional re-baseline only.** Wire 2020q1 in as a 2nd crisis gate, add a 3rd crisis window if freezable, ship the "every declared flag does something" wiring-preflight, and run **B0 + B1** (standing-main crisis spread + V227 skew generalization). Report mean ± spread.
- **Defer B2 (V229 trend-IC) and B3 (V228 stack) to V232+**, bundled with Track B's RV-term-structure brake measurement — by then the distributional harness exists, and any *trend* windows freezable as a by-product of that work can fold in at near-zero marginal cost.
- **Cheap exception:** if a 2nd trend window already falls out of the V215 recipe work for free (no extra freeze effort), opportunistically run B2 as a bonus read — but do not gate V231 on it or let it delay the crisis result.

---

## Artifact / file index (all absolute under repo root `/Users/benebsworth/projects/omega/`)

- `omega/nodes/victoria/training_log/V218-matrix.md` — V218.E section (:128–:148), results (:167–:204), verdict (:206–:239)
- `.claude/worktrees/v218-b-v170-ic/data/v218b_audit_crisis_r{1,2}_results.json` — reproduces −$2,862.86 (2022h1 control)
- `.claude/worktrees/v218-e-snap-crisis-2020q1/data/v218e_audit_crisis_r{1,2}_results.json` — reproduces +$13,051.74 (2020q1)
- `data/snapshots/snap_crisis_2020q1.json`, `data/snapshots/snap_crisis_2022h1.json` — both present, re-runnable
- `omega/nodes/victoria/training_log/V227.md` — +$630.08 crisis-skew (:13, :139, :147)
- `omega/nodes/victoria/training_log/V229.md` — +$1,428.16 trend-IC, trend-only (:21, :147, :202, :226)
- `omega/nodes/victoria/training_log/REFLECTION_V229.md` — 5× IC refutation context; V227 additive-brake-not-selection lesson
- `omega/nodes/victoria/training_log/V230_DECISION.md` — V231 pre-reg + $2k falsifier (:55, :61), $16k swing (:44)

**Note on missing artifacts:** the V218 per-cell `*_results.json` and `*_trades.csv` live in the **`.claude/worktrees/v218-*`** worktrees, NOT in main `data/` (no `data/v218*` files exist on main — consistent with the repo convention that untracked `data/v*` files don't propagate to/from worktrees). The numbers are fully reproducible from those worktree artifacts; if the worktrees are ever `git worktree remove`'d, the +$13,052/−$2,863 results.json would be lost (the snapshots survive, so a re-run regenerates them). Consider copying the four `v218{b,e}_audit_crisis_r*_results.json` into main `data/` before worktree cleanup if these are to remain the canonical existence-proof artifacts.
