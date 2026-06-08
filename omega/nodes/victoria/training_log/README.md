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

**V212 (2026-06-05) — no high-water; selector activation breaks regime-gate determinism.** V212 restored + enabled the V156 `strategy_selector` (inert on `main` for the whole V199–V211 arc). Pre-reg **falsifier #3 fired**: with byte-identical frozen inputs (V211↔V212 fingerprints identical, cross-day drift = 0), the selector keeps **recent** deterministic ($0.66 spread) but **regresses it −$583** (real), while **trend** and **crisis** become non-reproducible — 4 identical-input runs span **$18,720** (trend) and **$8,399** (crisis), far beyond their $166/$12 floors. The apparent trend +$5,821 / crisis +$7,312 "gains" are non-determinism artifacts, not high-waters. All three V211 highs **stand**. Selector stays flag-OFF. V213 = isolate/fence the selector-induced non-determinism before re-measuring. See `V212.md`.

**V213 (2026-06-06) — no high-water; sort hypothesis REFUTED, channel relocalized to a sleep/async trigger.** V213 pre-registered that the selector non-determinism was the residual basket_mean cross-sectional-demean order channel (`signal_generation.py:1149`) and shipped a canonical sort. A control matrix **refuted it on both branches**: (1) at the canonical **sleep=10**, ON-trend FAILS with *and* without the sort ($3,724 vs $3,431, same 81↔83 entry flip) — the sort is **not load-bearing**; (2) the apparent sleep=0 collapse ($18,720→$132) was a **cross-sleep confound** (V212 ran sleep=10, the V213 audit sleep=0; at sleep=0/3 the channel is dormant regardless of the sort); (3) the sort is **harmful** — a pre-sort control proved it regressed OFF-trend determinism $89→$1,442 by shifting the baseline onto a separate latent channel. **Fix A reverted** (`23c9b3c`). The real channel is a **sleep/wall-clock/async-timing** dependency (dormant ≤3s, active at 10s, flips actual entries). All V211 highs **stand**; selector still not evaluable. Kept: the two observability deltas (subsystem wiring banner + `check_determinism.sh` with a `--sleep` knob) that *enabled* the refutation. V214 = chase the sleep/async channel. See `V213.md`.

**V214 (2026-06-07) — no high-water; channel LOCALIZED — `--frozen-cache` has a hole (live network leakage).** A prior V214 attempt pivoted the bet to `dag_pipeline.py` concurrency; that is **refuted** (`DAG_PARALLEL` is never set anywhere → the DAG path is dead code in the eval; the gate proves it for free by also not setting it). V214 instead shipped the two queued observability deltas — **#3 mode-switch trace + #4 per-cycle signal-values fingerprint** (`run_training.py`) + `scripts/fingerprint_diff.py` — and ran the determinism gate at the canonical **sleep=10** (trend, selector ON, 4 replicates): **FAIL, spread $1,510**. The fingerprint diff localized the divergence to **cycle 1** in `btc_dominance` (0.3 vs 0.5), `long_short_ratio`, `vrp` — signals in `signals_advanced.py` that make **direct `urllib` calls** (Binance long/short `:730`; CoinGecko/CoinPaprika dominance `:871/:885`) gated only by a module-level 1h TTL, **bypassing `OMEGA_FROZEN_CACHE`**. Each replicate process fetches live at its own startup wall-clock; the "sleep channel" is really **wall-clock separation between replicates** (sleep=0 → all finish in minutes → consistent; sleep=10 → r1→r4 span ~2.5h → drifted live data). **Strong inference (V215 control pending):** the selector doesn't *induce* the non-determinism — it *amplifies* this pre-existing input leak (OFF ≈ V211's residual $166 "4th channel"; ON's discrete regime threshold blows it to $1,500–18,000). All V211 highs **stand**; selector still not evaluable. **The fix (freeze these fetches) is V215** — it shifts backtest baselines vs all prior runs, so it needs its own pre-reg. See `V214.md`.

**V215 (2026-06-07) — no high-water; network channel CONFIRMED + FIXED, gate still FAILs on a sizing-side wall-clock channel.** V215 shipped the freeze: option **A** snapshot-feeds the two localized `signals_advanced` signals (`data/frozen_advanced_signals.json`), and option **C** — the strongest queued obs delta — installs a centralized HTTP guard in `run_training.py` that monkeypatches **`urllib.request.OpenerDirector.open`** (import-style-agnostic; catches `from urllib.request import urlopen` too) to block + log + count *all* outbound HTTP when `OMEGA_FROZEN_CACHE=1`. Result at the canonical **sleep=10**: the signal layer is **now fully hermetic** — ON on_r1==on_r2 byte-identical (−$7,880) and **signal fingerprints identical 200/200** (ON on_r1 vs on_r4; OFF off_r1 vs off_r2). The leak was **far broader than V214's 3 signals** — the guard blocked **2,637 live HTTP calls/run** (FearGreed, Binance, GitHub dev-activity, news RSS, onchain MVRV, …); the centralized guard was the right architecture. **But the gate still FAILs** (ON spread $2,584, OFF $2,717) on a **second, non-network, sizing-side** channel: `core/risk_manager.py:316` `time_risk_multiplier` reads `datetime.now(UTC)` and applies a 0.50 size cut during **14:30–15:30 UTC**; replicates straddling the window halve their sizing (on_r4 fully inside → 46 trades vs 70). Definitionally non-network (guard blocked 100% of HTTP) and downstream of signals (fingerprints identical) — the **V214 §1 parking-lot site**, realized. **OFF also FAILs → the residual is selector-INDEPENDENT** (confirms V214 #4: selector *amplifies*, doesn't *induce*). Preliminary clean selector cost on trend, from the no-window replicates: **ON −$7,880 (PF 0.747, losing) vs OFF +$14,110 (PF 1.43, winning) ≈ −$22k** — strongly negative for trend on the hermetic baseline (direction robust: identical signals, PF flips losing→winning; magnitude soft — one no-window OFF sample, full N-seed audit is V216). Sharpens V212's −$583 recent. All V211 highs **stand**; **baseline shift is real & broad** (hermetic trend −$7,880 ON / +$14,110 OFF vs V214's leaky ~+$15k — pre-freeze numbers are historical). No full audit (Step-4 rule; eval one channel from hermetic). V216 = bar-time fence the sizing-side wall-clock sites. See `V215.md` + `REFLECTION_V215.md`.

**V216 (2026-06-08) — no high-water; sizing wall-clock channel CONFIRMED + FIXED (trend hermetic both arms), THIRD channel surfaced.** V216 threaded the current bar's UTC timestamp into the two sizing-side time-of-day sites in frozen backtest (`strategy._backtest_now_ts` → `time_risk_multiplier`'s existing `now` param + the strategy damp window), gated on `OMEGA_FROZEN_CACHE` (live path byte-unchanged). **Pre-registered acceptance MET:** trend determinism collapsed from V215's $2,584 (ON) / $2,717 (OFF) to **exactly $0.00** in both arms (ON N=4 −$4,008.60 ×4 / 32t; OFF N=2 +$3,043.34 ×2 / 35t) — the **first byte-identical trend gate at sleep=10** in the V207→V216 arc; the wall-clock localization was correct. Shipped obs-delta **#8** — `scripts/check_no_wallclock.py`, an AST tripwire that fails preflight on any unguarded `datetime.now`/`time.time` in the sizing path (would have caught this leak), wired into `check_determinism.sh`. **The 3-gate × {ON,OFF} audit then surfaced a THIRD channel:** 4/6 cells byte-identical ($0.00) but **recent-OFF FAILs ($995)** and **crisis-ON FAILs ($1,790)** — the fingerprint `fp` hash diverges at cycle 1–2 while *every* named scalar is byte-identical, so it is a **signal-layer full-precision-float / iteration-ordering** non-determinism (the V211 residual "4th channel," now dominant) — NOT network (guard blocks 100%), NOT the sizing wall-clock (fenced). **Daily-bar consequence (pre-registered fork):** the trend snapshot is daily bars at 00:00 UTC, so bar-time → both intraday windows fire every cycle → uniform ~0.375× sizing → a **new V216-era baseline** (not comparable to V211 pre-fence; the selector ON-vs-OFF Δ stays valid since both arms share the multiplier). **Selector verdict (honest, REFUTES V215's −$22k):** that figure was a single-sample no-window artifact; on the hermetic 0.375× baseline the selector is **bad for trend only** (Δ = **−$7,052, CLEAN, flips profit→loss**) and **mildly positive for recent (+$1,610) / crisis (+$1,026), both SOFT** (their opposite arms non-det). All V211 highs **stand** (pre-fence anchor). V217 = close the third channel (ship a per-field full-precision fingerprint hash to name it), then re-measure recent/crisis selector Δ cleanly, then matrix. **Matrix still waits — eval is 4/6 hermetic, not 6/6.** See `V216.md`.

### V216-era hermetic baseline (2026-06-08, post bar-time fence — NOT comparable to pre-fence highs)

Daily-bar bar-time → uniform ~0.375× sizing (both intraday windows fire every cycle); a
distinct sizing regime from the V211 pre-fence high-water table above. Deterministic cells
only (the 2 FAIL cells await the V217 third-channel fix). Use these — not the pre-fence
highs — as the reference for any post-V216 comparison until V217 re-baselines.

| Gate    | Selector OFF (baseline)      | Selector ON                | Selector Δ (ON−OFF)      | Determinism |
|---------|-----------------------------:|---------------------------:|-------------------------:|-------------|
| recent  | +$459.04 (mean, **non-det**) | +$2,069.37 (33t, det)      | ≈ +$1,610 (soft)         | OFF FAILs $995 |
| trend   | **+$3,043.34** (35t, det)    | −$4,008.60 (32t, det)      | **−$7,051.94 (clean)**   | both PASS $0.00 |
| crisis  | **−$3,438.69** (39t, det)    | −$2,412.42 (mean, non-det) | ≈ +$1,026 (soft)         | ON FAILs $1,790 |

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
| [V212.md](V212.md) | Restore + enable V156 strategy_selector | **No high-water; falsifier #3 fired.** Selector was inert on main the whole V199–V211 arc (flag undeclared + silent ImportError). Enabled, it keeps recent deterministic (−$583 real regression) but makes trend/crisis non-reproducible at sleep=10 ($18,720 / $8,399 spreads). V213 = fence the non-determinism. |
| [V213.md](V213.md) | **Sort hypothesis REFUTED — channel is sleep/async, not basket_mean** | **No high-water; Fix A reverted (`23c9b3c`).** Pre-reg: basket_mean demean order is the channel → canonical sort. Control matrix refuted it: at canonical sleep=10, ON-trend FAILS with *and* without the sort ($3,724/$3,431, same 81↔83 entry flip) → not load-bearing; the sleep=0 "$18,720→$132 collapse" was a **cross-sleep confound** (channel dormant at sleep≤3); pre-sort control proved the sort **regressed** OFF-trend $89→$1,442. Real root = a **sleep/wall-clock/async-timing** channel that flips entries. Kept the 2 observability deltas (wiring banner + `check_determinism.sh --sleep`) that enabled the refutation. V214 = chase the sleep/async channel. |

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
