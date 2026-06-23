# V233 — brief skeleton (branch-conditional on the V232 falsifier)

**Status:** SKELETON — pre-registered before the V232 grid completes (anti-
hypothesis-shaping). Four branches; the V232 crisis distributional Δ selects which
ships. Read `data/v232_dist/distribution.json → gates.crisis`:
- `delta.mean` = brake marginal mean-Δ (skew+brake − skew-only) across 3 windows.
- `delta_all_windows_positive` = min-Δ>0 (the per-window bar V227 failed).
- `per_window[].delta` for **snap_crisis_2024aug** specifically (the GATE-INERT tell).

## Branch-decision precedence
**Evaluate GATE INERT FIRST.** Check the 2024aug per-window Δ. If it is $0.00 (ON==OFF
byte-identical, as V227 was), the brake cannot move the worst window even if the
mean/min look fine on the other two — a *false SHIP*. Only if 2024aug Δ ≠ $0.00 do
SHIP / PARTIAL / REFUTED apply on the mean/min.

## The fork (V232 pre-registered falsifier)

### Branch SHIP — brake generalizes  (mean-Δ>0 AND min-Δ>0, all 3 windows; 2024aug Δ≠0)
The brake cleared the bar V227 failed.
→ **V233 = extend measurement to trend + recent distributions (full 3-gate, ~16h).**
- `GATES="crisis trend recent" bash scripts/v233_dist_grid.sh` (clone of v232 runner;
  same arms: skew+brake ON vs skew-only OFF).
- Windows: crisis ×3 (carry V232), trend ×2 (snap_trending_2023q4 + 2024q1), recent ×1
  (snap_20260414) — N=2 → (3+2+1)×2×2 = 24 cells.
- Bar: re-confirm crisis mean∧min>0 AND do not regress trend/recent mean-Δ below −$200
  (now measured distributionally, not the V232 spot-check). If it harms trend/recent →
  gate the brake crisis-only before flipping the default.
- On pass: flip `rv_term_brake_enabled` default → True; record the new crisis
  distributional high-water. Resolve the 3rd trend window / MATIC→POL recent fork.

### Branch PARTIAL — helps the mean, hurts a window  (mean-Δ>0 AND min-Δ≤0)
Window-luck signature (the V227 failure mode). Do NOT ship as-is.
→ **V233 = audit the failing window; build a window-conditional brake variant.**
- Audit: on the negative-Δ window, `scripts/trade_field_diff.py` over the brake-ON vs
  skew-only replicate trade CSVs to name the tickers/cycles the brake costs PnL on.
  Cross-reference `signal_contribs.jsonl` to split the negative Δ between the brake term
  and an interaction with the skew (double-brake: both fire same cycle → over-suppress).
- Variant: condition the brake on universe size or on "skew not already firing this
  cycle" (don't double-brake) — one-param guard, re-measured on the same 3-window grid.
  Falsifier unchanged (mean∧min>0).

### Branch REFUTED — brake does not help  (mean-Δ≤0)
Track B #1 (RV term-structure) is dead. Move to **Track B candidate #2 — cross-
sectional correlation spike.**
→ **V233 = ship an `xsec_corr_brake` additive brake.**
- Formula: per cycle, pairwise return correlation across the basket over a short
  lookback (5d) → basket mean |ρ|. A spike (mean |ρ| ≫ trailing baseline) is the
  "everything sells off together" crisis tell, orthogonal to both RV term-structure
  (vol-of-vol) and drawdown magnitude (level). `math.fsum` on every reduction.
- Gate: same V227 drawdown-AND-gate; additive `[-1,0]` in the post-demean block.
- Flag: `xsec_corr_brake_enabled: bool = False`, default-inert.
- Falsifier: identical bar (mean∧min>0 across the 3 crisis windows, no trend/recent
  regression below −$200), same v232/v233 crisis grid.

### Branch GATE INERT — brake inert on 2024aug  (2024aug per-window Δ == $0.00)
Same pathology V227 had: the drawdown-AND-gate so rarely fires on the 13/13 yen-carry
window (smoke: 1/60 gated cycles) that the brake can't move it. (Watch for this
masquerading as SHIP — a positive mean carried by 2020q1/2022h1 while 2024aug is $0.00.)
→ **V233 = "vol-OR" brake variant — brake fires on RV-inversion ALONE.**
- One-line change in `signal_generation._regime_gated_skew` call for the brake: fire on
  `(regime risk-off AND drawdown>thr) OR (rv_short/rv_long ≥ K)` — the inversion is
  itself sufficient, decoupling the brake from the inert drawdown gate.
- New flag `rv_term_brake_vol_or_enabled: bool = False` so the strict AND-gated brake
  stays byte-reachable as the control.
- ALSO test the application-site fix the V232 trace implicated (the real 2024aug
  obstacle is post-demean decision-inertness at weight 0.2): a pre-demean / partial-
  demean application OR weight > 0.2, measured as a 2×2 (gate × site) on the crisis grid.
- Re-run the crisis grid with the vol-OR arm; falsifier specifically requires 2024aug
  per-window Δ ≠ $0.00 (gate now fires) AND no harm to 2020q1/2022h1.

## V233 determinism pre-reqs (carry the arc)
`check_no_wallclock.py` + `check_frozen_http_fence.py` + `assert_cell_identity.py`
(now with `--expect-brake`) PASS per cell. Any new signal (xsec-corr) is OHLCV/
snapshot-fed → no HTTP fence; grep its producer for unsorted FP reductions, prefer
`math.fsum`.
