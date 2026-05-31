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

## High-water marks (as of 2026-05-31, post-V204 revert)

| Gate    | Best version                | PnL (seeded) | Trades | WR         | PF        | Notes                                                  |
|---------|-----------------------------|-------------:|-------:|-----------:|----------:|--------------------------------------------------------|
| recent  | ~~V199~~ **DEMOTED**        | ~~+$2,478~~  | 67     | 34.3%      | 1.13      | V203 σ=$2,547 (n=4). V204 V172-pinned reads −$4,472 — also within 2σ noise. Recent has no surviving high-water; new claims must clear V199×recent mean +$93 by ≥ 2σ = $5,094 (i.e. > +$5,187). |
| trend   | **V204 (V172 strategy.py)** | **+$22,105** | **77** | **40.26%** | **2.30**  | V204 seed=42 on `snap_trending_2023q4`, strategy.py reverted to commit `daa8304`. Replaces V172 logged +$18,437 (unseeded-protocol artefact) and V201 seeded +$11,550. 2σ floor for future trend claims: > +$22,107. |
| crisis  | V202-era (V199–V202 code)   | **−$19,042** | 63     | 33.33%     | —         | V203 σ≈$0.5; V202-era code holds best (least-negative). V204 V172 revert is *worse* on crisis at −$22,809 (−3,800σ) — the V173–V202 series delivered a real $3,767 crisis improvement that V204 surrenders. **V205+ salvage objective: re-introduce this crisis gain without losing the V204 trend ceiling.** No positive crisis run on record. |

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
