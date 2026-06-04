# Victoria training log

One markdown file per training version. Source of truth for what was
tried, what happened, and what's next. Replaces ad-hoc notes in run
dirs, memory files, and chat history.

## How to use

- Write a new `V###.md` **before** kicking off the run (hypothesis +
  planned change), update it **after** the run (gate results +
  conclusion + next steps).
- Use `_template.md` as the starting point.
- Update the high-water-mark table below whenever a new run beats an
  existing per-gate best.
- Linked from `.claude/skills/victoria-training-loop/SKILL.md` — the
  skill enforces the loop.

## High-water marks (as of 2026-06-03, post-V211)

Noise-floor status (V211 2-pair × 3-gate audit, 12 runs): **eval-noise
floor finally trustworthy at $1–166 across all three gates**. V211
applied two `sorted()` wraps to the basket_std (`strategy.py:1722`) and
basket_mean (`:2130`) aggregations — the channel V210 localized. Recent
collapsed ~2,400× ($1,386 → $1), trend ~9× ($750 → $166), crisis
~2.3× ($28 → $12). Crisis V209 ceiling (−$17,763) **rescinded** — it
was a partial-canonicalization artifact; the structurally correct
deterministic crisis number at V211 HEAD is −$24,828 (62 trades, same
WR/PF; V210 predicted asymmetric crisis cycle-1 drift = 1e-2 would
move selection once the basket sort closed). All three gates
re-anchored at V211 single-seed=42 headlines below.

| Gate    | Best version                          | PnL (V211 anchor) | Trades | WR    | PF    | Noise σ | Notes                                                  |
|---------|---------------------------------------|------------------:|-------:|------:|------:|--------:|--------------------------------------------------------|
| recent  | **V211 (re-baselined)**               |        +$2,177.06 |     69 | 0.3333| 1.112 | **$1**  | Within-pair max $0.95, cross-pair max $0.95, Δtrades=0 across 4 runs. ~2,400× collapse vs V210's ≥$1,386 floor. V199 +$2,478 stays DEMOTED — was unreproducible at HEAD and rode the unsorted basket channel. |
| trend   | **V211 (re-baselined)**               |        +$8,328.87 |    106 | 0.3774| 1.281 | **$166**| 3 of 4 runs identical at 106 trades / ≈$8,330; trend_p1_r2 outlier at 105 trades / $8,165 (residual 4th channel — parking lot for V212/V213). V204 +$22,105 stays RESCINDED. |
| crisis  | **V211 (re-baselined)**               |       −$24,827.90 |     62 | 0.3226| 0.512 | **$12** | Within-pair max $11.82, cross-pair max $11.82, Δtrades=0 across 4 runs. V209 −$17,763 ceiling **RESCINDED** — V210 predicted asymmetric crisis cycle-1 drift = 1e-2; the basket sort canonicalized the deterministic answer to −$24,828. Same WR/PF as V209's 65-trade version, 3 fewer trades. Whether −$24,828 vs alternative canonicalizations is "the" structural answer is a V212+ parking-lot question; for now this is the working floor. |

### V203 variance baseline (2σ noise floors for future claims)

| Gate    | Cell measured                    | Mean PnL  | σ      | 2σ threshold |
|---------|----------------------------------|----------:|-------:|-------------:|
| recent  | V199 code × snap_20260414        | +$93      | $2,547 | **$5,094**   |
| crisis  | V199 code × snap_crisis_2022h1   | −$19,042  | $0.5   | **$1**       |
| trend   | V201 code × snap_trending_2023q4 | +$11,550  | $1     | **$2**       |

Process change: every V###.md must compare new gate deltas against
these 2σ thresholds before claiming a high-water break. Single-seed
deltas below threshold are reported as "in noise" and do NOT update
this table. See `V203.md` for the full methodology and
`REFLECTION_V202.md` for the trigger that commissioned it.

Regime parity is the #1 open problem: trend & recent positive, crisis
consistently negative across V170s–V200s. V201 diagnosed the V172
trend regression as the `crisis_short_bias` threshold discount;
removing it recovered ~60% of the V172→V199 trend gap. V202 then
tested the sizing-is-the-lever theory (remove size amp + restore
crisis half-Kelly) and **refuted it**: crisis flat (−$19,003 vs
−$18,996), trend regressed (+$8,830 vs +$12,996) because the
half-Kelly skip was load-bearing for trend's crisis-labeled cycles.
Crisis is structurally **exit-side** — same trade count, same loss
magnitude across two opposite sizing regimes. V203 = revert the
half-Kelly restoration + crisis trail tightener.

## Phase index

| File             | Phase                          | Key takeaway                                                                 |
|------------------|--------------------------------|------------------------------------------------------------------------------|
| [V148.md](V148.md) | Pre-loop baseline              | meta_learner_exit_only + continuous_sizing — last commit on main pre-loop    |
| [V172.md](V172.md) | IC + ensemble foundation       | Ridge calibrator + signal pruning. Best trend number to date.                |
| [V176.md](V176.md) | Live ensemble high-water       | V175 loosened thresholds + vix in composite. +$1,189 live, 31 trades.        |
| [V185.md](V185.md) | Microstructure (VPIN/Kyle/OFI) | Strong on snapshots, anemic live (needs WS accumulation).                    |
| [V189.md](V189.md) | Gate stacking diminishing returns | Symbol blacklist + min hold + damp hours. V184 60d barely positive PF 1.04. |
| [V191.md](V191.md) | Range/carry attempt            | Range sub-strategy + funding-carry signal — carry gated behind range_bound=1.0 (rarely fires). |
| [V197.md](V197.md) | Observability reset            | PipelineTracer wired at all 6 boundaries; strategy_selector silent-override bug caught & fixed. |
| [V199.md](V199.md) | Carry-only sub-strategy        | New recent high-water (+$2,478, 67 trades). Trend regressed — fix in V200.    |
| [V200.md](V200.md) | Trend-regime carry suppressor  | Refuted: suppressor never fired on trend snapshot (trades identical to V199); recent regressed (+$427). V201 = tracer-driven diagnosis. |
| [V201.md](V201.md) | Remove crisis_short_bias threshold discount | Mixed: trend +$12,996 (confirmed — discount, not carry, drove V172 regression); recent +$223 (discount was helping recent); crisis −$18,996 (binding constraint is sizing, not selection). V202 = remove size amplifier + restore crisis half-Kelly. |
| [V202.md](V202.md) | Remove crisis size amp + restore half-Kelly | **Refuted.** Crisis unchanged (−$19,003 vs −$18,996); trend regressed (+$8,830 vs +$12,996) — half-Kelly skip was load-bearing for trend's crisis-labeled cycles. Crisis is structurally exit-side, not sizing. V203 = revert half-Kelly + crisis trail tightener. |
| [REFLECTION_V202.md](REFLECTION_V202.md) | Mandatory reflection (4 triggers fired) | Identified 60–70% per-trade PnL drift on no-op changes; commissioned V203 variance batch. Process change: 2σ noise floor required for high-water claims. |
| [V203.md](V203.md) | Variance re-baseline (no code change) | **σ_recent=$2,547, σ_crisis≈$0, σ_trend≈$1.** V199 recent high-water REFUTED (Δ=−$2,239 vs logged +$2,478 at seed=42, +0.94σ from $0). Recent high-water DEMOTED. V204 = Route C (revert strategy.py to V172). |
| [V204.md](V204.md) | Route C — revert strategy.py to V172 baseline | **Trend high-water broken** (+$22,105, seed=42). Crisis regressed −$3,767 to −$22,809; recent within noise. Decomposition pivot: 1e743de strategy.py portion is cosmetic — the V173–V202 worktree deletions are what produced the crisis improvement. V205 = strip one architectural component (V157 CRISIS weights). |
| [V205.md](V205.md) | Strip V157 CRISIS regime weights | **Crisis high-water broken** (−$8,533, +$14,277 vs V204; first crisis movement clearing V203 noise floor). Trend collapsed −$15,874 to +$6,231 — V157 CRISIS damping was load-bearing on trend snapshot's crisis sub-periods. Lever too coarse for stacked solution. V206 = revert V205 + try V170 per-regime IC weighting in isolation. |
| [V206b.md](V206b.md) | Noise audit — funding-cache leak | Within-pair PnL noise floors $0.49–$1,978 across gates; crisis $1,978 σ rescinded V204/V205 claims. Funding cache identified as primary leak. V207 = fence the cache + pin PYTHONHASHSEED. |
| [V207a.md](V207a.md) | PYTHONHASHSEED=42 + frozen funding cache | Crisis spread 17× reduction ($1,978→$113). Recent+trend got **worse** ($3,257 / $14,047) — third channel unmasked. V207b = localize it. |
| [V207b.md](V207b.md) | Static cycle-1 bisect | Localized to `strategy.py:_construct_portfolio` sizing chain (lines 3143-3192). Most-likely root: `_compute_weighted_conviction` rolling z-score over shared-pool `_signal_history`. V208 = falsifier-branch test. |
| [V208.md](V208.md) | **Kill third channel via canonical sort** | **Recent spread $3,257 → $0.06 (54,000×).** Sub-experiment A (canonical sort across `_construct_portfolio` items()) passed first try with identical trade count. V209 = redo full 3-gate × 2-pair audit at new noise floor. |
| [V209.md](V209.md) | **Full 3-gate × 2-pair audit at V208a HEAD** | **Partial pass.** Crisis $56 spread (Δ=0) — new working ceiling −$17,763 ± $28 (+$5,046 vs V206b). Recent $2,773 / trend $1,500 spreads, trade Δ=3 each — V208a's $0.06 recent floor did NOT reproduce. Cycle-1 composite drift unchanged on recent. Second gate-specific channel alive. **V210 = mandatory reflection** (eval-noise trigger fired). |
| [REFLECTION_V209.md](REFLECTION_V209.md) | Mandatory reflection (trigger #2) | V208a $0.06 was a one-pair fluke; n=1 spreads do not establish σ. Noise-floor claim rule: ≥2-pair audit OR structural argument. Crisis fence is real (selection-stable from regime architecture, not from the determinism fixes). Operating thresholds until V211: σ_recent≥$1,386, σ_trend≥$750, σ_crisis≈$28. |
| [V210.md](V210.md) | Cycle-1 bisect on V209 artifacts | **Localized third channel** to `signals.items()` unsorted at `strategy.py:1722` (basket_std) and `:2130` (basket_mean). Crisis 65/65 trade match (selection-stable); recent first bifurcates cycle 184; trend first bifurcates cycle 38. Sub-signal values identical at every common trade event — sub-signal layer is clean. V211 = canonical-sort fix on the two unsorted aggregations, pre-registered ≥2-pair audit acceptance. |
| [V211.md](V211.md) | **Sort basket_std + basket_mean** | **Pre-registered acceptance met on all 3 gates.** 2-pair × 3-gate audit (12 runs). Recent noise floor $1,386 → $1 (~2,400×); trend $750 → $166 (~9×); crisis $28 → $12 (~2.3×). Crisis V209 ceiling −$17,763 RESCINDED — basket sort canonicalized to −$24,828 (62 trades, same WR/PF); V210 predicted this asymmetric move. Trend p1_r2 outlier (105 vs 106 trades) flags one residual 4th channel — parking lot. V212 = n=4 variance batch + strategy_selector audit at V211 HEAD. |

## The loop

The continual-improvement loop is codified in
`.claude/skills/victoria-training-loop/SKILL.md`. Short version:

1. Read latest `V###.md` → its **next steps** are the brief for V###+1.
2. Create `V###+1.md` with hypothesis + planned change.
3. Implement.
4. Run `scripts/run_training.py --version v###+1 --cycles 200` (or
   per-gate snapshots: `recent`, `trend`, `crisis`).
5. Fill in gate results, conclusion, next steps.
6. Update this README's high-water table if a record was broken.
7. Commit + push.
