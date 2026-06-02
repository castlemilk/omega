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

## High-water marks (as of 2026-06-02, post-V209)

Noise-floor status (V209 3-gate × 2-pair audit at V208a HEAD):
**crisis < $100** ($56 within-pair PnL spread, identical trade count
— 35× improvement over V206b's $1,978 crisis floor). Recent and trend
still drift > $100 ($2,773 and $1,500 spreads, trade Δ=3 each) —
V208a's $0.06 recent floor did NOT reproduce in V209. Second
gate-specific channel still alive. V210 = mandatory reflection
(eval-noise trigger fired).


| Gate    | Best version                          | PnL (seeded) | Trades | WR         | PF        | Notes                                                  |
|---------|---------------------------------------|-------------:|-------:|-----------:|----------:|--------------------------------------------------------|
| recent  | ~~V199~~ **DEMOTED**                  | ~~+$2,478~~  | 67     | 34.3%      | 1.13      | V203 σ=$2,547 (n=4); V209 within-pair σ $2,773 at fenced+sorted HEAD. No surviving recent high-water. |
| trend   | ~~V204~~ **RESCINDED (V206b)**        | ~~+$22,105~~ | 77     | 40.26%     | 2.30      | V209 trend r1/r2 read +$14,929 / +$16,429 (within-pair σ $1,500). V204 +$22,105 lies $5,676–$7,176 above V209 but inside cross-day envelope — not discriminable until V211+ closes the second channel. No surviving trend high-water. |
| crisis  | **V209 (working ceiling)**            | **−$17,763** |     65 |    32.31%  |     0.614 | V209 crisis r1/r2 = −$17,791 / −$17,735, within-pair σ ≈ $28 (n=1 pair). +$5,046 better than V206b's −$22,809 ceiling — clears 2σ comfortably, signal not noise. **New working crisis ceiling: −$17,763 ± $28 on seed=42 + PYTHONHASHSEED=42 + frozen funding cache + V208a canonical sort.** See V209.md for the audit. |

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
