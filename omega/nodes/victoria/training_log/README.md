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

**V227 (2026-06-20) — SHIP; drawdown-gated crisis-skew helps crisis +$630 (fork #1) + recent determinism channel CLOSED.** V227 overturns V226's "twice-refuted" verdict by fixing V226's own fork-#3 root cause: the categorical VRP→regime gate over-fired (it called ~half of every benign window {crisis,high_vol}). Adding a second AND condition — fire only when the per-ticker **realized recent drawdown** (last 5 daily bars) exceeds **X=0.12** — turns the gate into a real crash selector. Calibrated X (regime-only fired 97/113/79; X=0.12 fires **12/21/29**, all < 40; X=0.10 fails recent at 42). Falsifier grid (X=0.12, OFF controls reproduce the standing mains exactly): **crisis −$3,621.25 → −$2,991.17 = +$630.08** (fork #1, crisis N=2 hermetic), **trend +$0.02, recent −$64.33** (both within ±$200). The realized downside-semivariance proxy is **sound**; the categorical label was the broken component. **SHIPPED**: `crisis_skew_enabled` + `crisis_skew_regime_gate_enabled` + `crisis_skew_drawdown_threshold=0.12` flipped ON by default. **Track C (determinism precondition):** V226's recent-OFF FAIL ($1,621.99) was NOT the V216→V221 float channel — `per_field_diff` named cycle-22 `basic_signals.value` but `signal_contribs` named the real channel: **`spy_signal` flapping in/out of the per-ticker composite** (cycle-83 NEARUSDT −0.1833 present r1, absent r2). Root cause: `SPYSignal`/`VIXSignal` fetch via **yfinance → curl_cffi/requests, bypassing the V215 urllib HTTP guard** (zero yahoo hosts in the 2,000+ urllib leak-log, yet yfinance present). Fenced both with `if OMEGA_FROZEN_CACHE: return 0.0`; shipped `check_frozen_http_fence.py` AST preflight (wired into `check_determinism.sh`) so the class can't silently return. **2/2 recent hermetic at $0.00** (OFF +$4,901.01, ON +$6,564.97). The fence also re-baselined the V226 trend-OFF drift (−$1,330.48 → clean −$217.71 — that "cross-snapshot drift" was partly the same yfinance leak). Track A (paid vendor) was conditional on B refuting → not needed. V228 = stack with the banked trend-IC overlay (+$2,206). See `V227.md`.

### V227-era baseline (2026-06-20, drawdown-gated crisis-skew SHIPPED — new main)

5 cells N=1 + crisis N=2 hermetic, all DETERMINISM PASS at $0.00, cell-identity PASS.
Decisive = drawdown-gated skew-ON (dd 0.12, W=0.2) vs within-grid skew-OFF control,
same fenced commit. OFF controls reproduce the standing mains exactly. **These ON
numbers are the new standing main** (flags default ON post-V227).

| Gate | skew-OFF (prior main) | **gated skew-ON (MAIN, dd 0.12)** | Δ (ON−OFF) | skew_on_cyc | Determinism |
|------|----------------------:|----------------------------------:|-----------:|:-----------:|-------------|
| trend  | −$217.71 (23t)   | **−$217.69 (23t)**   | +$0.02   | 12 | PASS $0.00 |
| crisis | −$3,621.25 (31t) | **−$2,991.17 (33t)** | **+$630.08** | 29 | PASS $0.00 (N=2) |
| recent | +$4,901.01 (22t) | **+$4,836.68 (22t)** | −$64.33  | 21 | PASS $0.00 |

Crisis post-fence high-water improves −$3,621.25 → **−$2,991.17** (V227). recent
+$4,901.01 high stands (gated skew is −$64 < floor on recent). trend flat.

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

**V217 (2026-06-09) — no high-water; THIRD determinism channel CLOSED → eval is 6/6 HERMETIC.** V217 named the third channel with a per-field IEEE-754 fingerprint (`basic_signals.value` diverging at ~1e-18 — summation-order float noise around zero) and traced it to **multi-threaded Apple Accelerate (vecLib) BLAS parallel-reduction order**. The fix pins BLAS to a single thread in frozen-backtest mode (5 thread-count env vars set before numpy load, piggybacked on the existing `PYTHONHASHSEED` self-re-exec in `run_training.py`; live path byte-unchanged). The full 3-gate × {ON,OFF} grid then came back **6/6 PASS at exactly $0.00 spread at sleep=10** — the first fully byte-identical eval in the V207→V217 arc. **Matrix mode unlocks (V218).** Single-threaded BLAS re-bases all numbers vs V216-era (different reduction order); the V217-era table below supersedes V216-era for post-V217 comparison. All V211 pre-fence highs **stand** as historical reference. See `V217.md`.

### V219-era committed-state baseline (2026-06-10, post macro-repair freeze — USE FOR ALL POST-V219 COMPARISON)

Real committed macro (V219 substrate freeze) + single-threaded BLAS (V217) + bar-time
sizing fence (V216) + HTTP guard (V215). **Reproducible from a clean checkout** — macro
inputs are byte-identical across replicates in every cell. 4-cell grid (sleep=10, N=2,
selector OFF + a trend ON control). Real macro makes recent/crisis materially more
negative than the V217-era (macro=0) numbers; trend stays weakly positive. **These
supersede the V217-era table for any post-V219 comparison.**

| Gate (sel. OFF) | Selector OFF (baseline)            | Selector ON (trend control) | Δ vs V217-era | Determinism      |
|-----------------|-----------------------------------:|----------------------------:|--------------:|------------------|
| recent          | **−$3,363.52 (22t)**               | not run                     | −$1,457.81    | PASS $6.52       |
| trend           | **NON-DET $902.94–$1,499.85 (27/26t)** | −$2,915.74 (24t)        | ≈ +$162 (mid) | **FAIL $596.91** |
| crisis          | **−$4,480.54 (30t)**               | not run                     | −$2,281.04    | PASS $0.00       |

**3/4 hermetic; trend_OFF determinism falsifier fired.** The macro repair surfaced a
**second order-channel in `basic_signals.value`** (same field as the V217 BLAS channel
but distinct — the BLAS pin is verified active) — summation-order float noise (~1e-18,
sign-flipping around zero), dormant while macro=0, now flipping one trade on the
boundary-adjacent trend_OFF arm (27↔26 → $597). NOT a substrate defect: `_macro_bias_score`
byte-identical across replicates (macro reads stable); recent_OFF carries the identical
$6.52 noise with no trade flip. Strong-inference root: an `id()`-ordered accumulation that
BLAS-pinning + PYTHONHASHSEED don't cover. (Falsifiers #2 tripwires 5/5 + #3 manifest
stability both PASS.) **V220.A**
re-closes it (canonical-sort/`fsum` the composite) before **V220.B** wires per-regime ICs
— the non-deterministic trend baseline blocks clean IC measurement. trend_ON selector
control PASSes $0.85 and still hurts trend (flips +$0.9–1.5K OFF → −$2.9K). See `V219.md`.

### V221-era hermetic baseline (2026-06-12, post demean-fsum + funding-fence — USE FOR ALL POST-V221 COMPARISON)

Both V221 fences (cross-sectional demean `math.fsum` at `signal_generation.py:1160`;
constant-history fence in `signals/funding_rate.py:_zscore_signal`) alter frozen-eval
behavior, so committed-state numbers shift again. **First 4/4 hermetic grid from
committed state** — every cell $0.00 spread, byte-identical PnL and trade ledgers.
Supersedes the V219-era table.

| Gate (sel. OFF) | Selector OFF (baseline) | Selector ON (trend control) | Δ vs V219-era | Determinism    |
|-----------------|------------------------:|----------------------------:|--------------:|----------------|
| recent          | **+$4,901.01 (22t)**    | not run                     | **+$8,264.53 (sign-flip)** | PASS $0.00 |
| trend           | **+$631.85 (23t)**      | −$7,802.98 (30t)            | ≈ −$570 (mid) | PASS $0.00 ×2  |
| crisis          | **−$3,599.74 (31t)**    | not run                     | +$880.80      | PASS $0.00     |

The recent sign-flip (−$3,364 → +$4,901) is the honest committed-state answer: the
V219-era number was contaminated by a flickering spurious funding signal (epsilon-guard
amplifier) and the demean order wobble — both real PnL inputs that are now deterministic.
Selector still hurts trend (−$8,435 Δ, both arms hermetic — the cleanest selector
measurement yet). All V211 pre-fence highs stand as historical anchors.

> ⚠️ **V222 control caveat — the V221-era trend/crisis numbers above are superseded for
> cross-version use.** The V222 IC-off control (`ic_seed_weighting:false`) reproduces
> recent **bit-exact** (+$4,901.01) but drifts on trend (+$631.85 → −$217.71) and crisis
> (−$3,599.74 → −$3,530.13), same trade counts (23/23, 31/31). Root cause: V222's `math.fsum`
> fence on `_ic_weighted_composite` (`signal_generation.py:246,253`) is **load-bearing, not
> dormant** — the `SignalDecayDetector` self-accumulates ≥3-signal IC mid-run and activates
> the weighted branch on the longer trend/crisis runs (recent stays equal-weight → bit-exact).
> A benign V211-class FP-order re-canonicalization (both versions deterministic at $0.00).
> Use the **V222-era IC grid** below for post-V222 trend/crisis comparison.

### V222-era IC grid (2026-06-13, sleep=10 — USE FOR POST-V222 trend/crisis COMPARISON)

7/7 hermetic at $0.00. IC-off controls re-anchor committed-state trend/crisis post the
`_ic_weighted_composite` fence (recent unchanged from V221-era). No high-water — IC-on loses
on recent & crisis, wins on trend but not past any standing best.

| Gate (sel. OFF) | IC-off (V222 control) | IC-on (seeded) | IC Δ (on−off) | Determinism |
|-----------------|----------------------:|---------------:|--------------:|-------------|
| recent | **+$4,901.01 (22t)** | +$1,995.86 (30t) | −$2,905.15 | PASS $0.00 |
| trend  | **−$217.71 (23t)**   | +$3,113.04 (35t) | **+$3,330.75** | PASS $0.00 |
| crisis | **−$3,530.13 (31t)** | −$8,301.35 (35t) | −$4,771.22 | PASS $0.00 |

(IC-on selector-ON trend control: −$3,822.92 / 32t, PASS $0.00 — better than V221's
selector-ON −$7,802.98 by +$3,980, still net-negative.)

### V224-era baseline (2026-06-15, IC RETIRED — equal-weight is main, USE FOR POST-V224 COMPARISON)

9/9 hermetic at sleep=10. The decisive comparison is **R3 empirical IC (gate ON) vs
within-grid equal-weight (IC-off)**, same commit `053d3d0` + caches. Equal-weight wins
net and on 2/3 gates → IC retired. These equal-weight numbers are the standing main.

| Gate (sel. OFF) | Equal-weight / IC-off (MAIN) | R3 empirical IC (gated) | Δ (R3 − eqw) | Determinism |
|-----------------|-----------------------------:|------------------------:|-------------:|-------------|
| trend  | **−$1,330.48 (23t)** | +$875.14 (27t)   | +$2,205.62 (IC wins) | both PASS $0.00 |
| crisis | **−$3,621.25 (31t)** | −$6,429.37 (37t) | −$2,808.12 (IC loses) | both PASS $0.00 |
| recent | **+$4,746.68 (23t)** | +$4,556.55 (24t) | −$190.13 (wash, < floor) | PASS $0.00 / $32.75 |

Net: equal-weight **−$205.05** > R3 empirical **−$997.68** > seed-on **−$4,837.73**. The
recent +$4,746.68 is just under the V221-era recent high (+$4,901.01 stands). The trend IC
edge (+$2,206 vs equal-weight, hermetic, 3×-replicated V222→V224) is the one durable IC
finding — parked as a future trend-only overlay, out of scope for V225.

### V226-era grid (2026-06-18, regime-gated crisis-skew REVERTED — equal-weight stays main)

11/12 replicate-pairs hermetic at sleep=10, N=2; 12/12 cell-identity PASS. Decisive =
**regime-gated crisis-skew (ON, W=0.2, fire only in {crisis,high_vol}) vs within-grid
equal-weight (OFF)**, same commit `ead8f2a` + caches. The gate **fails its purpose** — it
suppressed only ~half the cycles (`skew_on_cycles` 91/77/113) because the 1-cycle-lagged
VRP→regime label calls ~half of *every* window {crisis,high_vol} — and the gated brake is
still harmful. **REVERT; flags stay default OFF, main numerically unchanged.**

| Gate | Equal-weight / skew-OFF (MAIN) | Gated skew-ON (W=0.2) | Δ (ON − OFF) | skew_on_cyc | Determinism |
|------|-------------------------------:|----------------------:|-------------:|:-----------:|-------------|
| trend  | **−$1,330.48 (23t)** | −$3,781.72 (27t) | −$2,451.24 (gate harms; +4 net shorts) | 91 | both PASS $0.00 |
| crisis | **−$3,621.25 (31t)** | −$4,188.88 (32t) | −$567.63 (gated brake worsens target gate) | 77 | both PASS $0.00 |
| recent | **+$3,279.02 → +$4,901.01 (22t)** | +$4,975.56 (25t) | +$74…+$1,696 (control non-det) | 113 | ON PASS; **OFF FAIL $1,621.99** |

Realized downside-semivariance skew is now **twice-refuted** as a directional overlay
(always-on V225 + gated V226). No skew-ON cell is a usable result → **no high-water broken**.
Incidental: skew-OFF recent FAILed determinism ($1,621.99, NEARUSDT cycle 95↔93 entry flip) —
the V216→V221 signal-layer float-ordering channel resurfacing on the 06-18 snapshot, *not*
crisis_skew (it's the skew-disabled arm; r2 reproduces V225's +$4,901.01 exactly). V227 =
paid implied-skew vendor (forward-looking, last skew attempt) + regime-label forensics + close
the resurfaced recent determinism channel.

**V226 (2026-06-18) — no high-water; regime-gated crisis-skew REVERTED (gate fails + brake
still harmful).** V226 added a regime gate on V225's `crisis_skew` term — fire only when the
prior-cycle VRP-mapped label ∈ {crisis,high_vol}, W dropped 0.5→0.2, behind
`crisis_skew_regime_gate_enabled` (default OFF; grid ON). Pre-reg **forks #4 + #3 fired:**
trend gated-ON regresses **−$2,451** vs within-grid equal-weight (fork #4 — still a directional
bearish tilt, +4 net shorts), crisis got **−$568 worse** (target-gate thesis refuted), and the
gate left `skew_on_cycles` at **91 (trend) / 113 (recent) ≫ 40** (fork #3 — the VRP→regime
label calls ~half of every window {crisis,high_vol}, so the gate is a coin-flip, not a crisis
selector). The realized-semivariance proxy is twice-refuted; reverted (flags default OFF, gate
code dormant inside the flag block → main equal-weight numerically unchanged, no back-out
needed). Grid was **11/12 hermetic + 12/12 cell-identity PASS**; the one FAIL is the skew-OFF
recent control ($1,621.99) — the resurfaced V216→V221 signal-layer float channel, orthogonal
to the skew work. V227 = escalate to a **paid implied-skew vendor** (Deribit 25-Δ RR / DVOL,
V215 freeze recipe — the last realistic skew attempt; if it also fails, close the crisis-overlay
program), tighten the gate to a **drawdown-magnitude threshold**, and run determinism forensics
on the recent channel. The banked trend-IC overlay (+$2,206 hermetic) stays the only positive
durable finding. See `V226.md`.

### V225-era baseline (2026-06-16, additive crisis-skew REFUTED — equal-weight stays main)

6/6 hermetic at sleep=10, N=2; 12/12 cell-identity PASS (new `assert_cell_identity.py`).
Decisive comparison = **additive crisis-skew (ON) vs within-grid equal-weight (OFF)**, same
commit `58bcec1` + caches. Skew **harms all three gates** → reverted (flag default OFF, code
dormant). The within-grid equal-weight (OFF) numbers reproduce the V221/V222-era highs
exactly and are the standing main.

| Gate | Equal-weight / skew-OFF (MAIN) | Crisis-skew ON | Δ (ON − OFF) | Determinism |
|------|-------------------------------:|---------------:|-------------:|-------------|
| trend  | **−$217.71 (23t)**   | −$4,787.34 (31t) | −$4,569.63 (skew harms) | both PASS $0.00 |
| crisis | **−$3,519.91 (31t)** | −$4,490.21 (30t) | −$970.30 (skew harms target gate) | both PASS $0.00 |
| recent | **+$4,901.01 (22t)** | +$3,230.45 (35t) | −$1,670.56 (skew harms) | both PASS $0.00 |

Net: equal-weight **+$1,163.39** ≫ skew-ON **−$6,047.10**. The skew fired ~200/200 cycles in
*every* gate (`skew_on_cycles` 188/195/200) — an always-on bearish tilt, not a crisis signal.
recent skew-OFF +$4,901.01 **ties the V221-era recent high** (control arm, not a skew result;
no skew-ON cell beat its control → **no high-water broken**). V226 = make the brake
regime-conditional (fire only in {crisis,high_vol}, drop W) or escalate to a paid implied-skew
vendor.

**V225 (2026-06-16) — no high-water; additive crisis-skew REFUTED (harmful, not orthogonal).**
The V225 brief's lead (Deribit 25-delta historical skew) was unobtainable (no free historical
implied IV; DVOL misses 2020-Q1, is a level not a skew) and the literal cross-venue
funding-spread fallback unbuildable (snapshots hold one static funding scalar, no venue axis/
history) — so per the pre-committed "default to the deterministic fallback" rule, V225
implemented `crisis_skew_signal`: realized downside-semivariance skew + drawdown acceleration
from already-frozen OHLCV, added as a one-sided ([-1,0]) **additive post-demean term** (W=0.5,
applied after the cross-sectional demean so the common-mode tilt survives), flag
`crisis_skew_enabled` default OFF. Grid: **6/6 hermetic at $0.00, 12/12 cell-identity PASS**
(the new `assert_cell_identity.py` closes the V224 mislabeled-control bug class). Decisive
within-grid result: skew **regresses all three gates** (trend −$4,570, crisis −$970 *worse*,
recent −$1,671) → **HARMFUL/REVERT fork fires.** Mechanism named by observability:
`skew_on_cycles` ≈ 200 in every gate → the realized term is a near-constant bearish tilt, NOT
crisis-specific (the "≈0 outside crisis" assumption refuted — every 30-bar window has enough
downside semivariance + drawdown wobble to fire). Reverted: flag stays default OFF (main =
unchanged equal-weight), code dormant for a regime-gated V226 retry. Shipped + kept:
`assert_cell_identity.py` (control-identity preflight). See `V225.md`.

**V224 (2026-06-15) — no high-water; IC RETIRED (third refutation).** V224 replaced the
discredited pooled win-rate seeds with **empirical per-(regime, signal) ICs** fit on a
leave-one-snapshot-out OOS holdout (LOSO Spearman, 1-bar fwd return, ordinal tie-break,
fsum-fenced — `estimate_ics.py`, byte-reproducible), loaded under `OMEGA_R3_ICS=1`, gate
ON. The empirical ICs alone refuted the seed assumption (sma_crossover·normal +0.48→+0.05;
crisis +0.52→**−0.18** sign-flip; ollivier_ricci excluded-by-seed but real IC −0.51→+0.21 —
the seeds were win-rate priors, not correlations). **Post-grid control bug:** the original
"IC-off" cells ran `features='{}'`, but `ic_seed_weighting` defaults True → they ran
**seed-IC-on**, not equal-weight (the pre-registered control). A corrective equal-weight
run (`ic_seed_weighting:false`, same commit) supplied the real baseline. **Decisive (R3 vs
within-grid equal-weight): R3 wins 1/3** — trend +$2,206 (real, hermetic, replicated), but
crisis −$2,808 and recent −$190 (wash). Needed ≥2 → **IC retired.** Mechanism: empirical
re-estimation *narrowed* the crisis loss vs seed (+$1,860) but crisis is still worse than
equal-weight — the harm is **conviction concentration itself** on the 121 normal-labeled
crisis cycles, not wrong IC magnitudes (better ICs hurt less, still lose). Third refutation
(V222 always-on, V223 gated, V224 empirical-OOS). Equal-weight stays main; IC + regime-gate
path mothballed (flag-default-OFF, dormant). 9/9 determinism PASS — empirical ICs opened no
new selection channel. **V225 = pivot off IC to a new orthogonal crisis-predictive signal
class** (lead: options-skew / Deribit 25Δ put-call skew + term structure; fallback:
cross-asset funding-spread) as an *additive* composite member, NOT an IC re-weight; no-harm
falsifier (beat crisis > $200 without regressing trend/recent > $200). See `V224.md`.

**V223 (2026-06-14) — no high-water; regime-gated IC beats always-on IC on every cell
but loses to equal-weight net.** V223 added one flag (`regime_conditional_ic_weighting`,
default OFF) gating the IC-weighted conviction path on the **runtime regime label**: bypass
to equal-weight raw composite on `crisis`/`high_vol` cycles (denylist — the brief's allowlist
wording was refuted against the real label space), IC-on everywhere else. Bit-safe by
construction (membership test + early `return` of the existing IC-off expression — no new
float-sum site). 4-cell × N=2 grid: **8/8 hermetic at $0.00**, `check_no_wallclock` PASS.
The pre-grid 200-cycle regime probe (shipped IC-gate tally) found **snapshot name ≠ runtime
regime** — every snapshot is a mix (trend 48% bypass, crisis 40%, recent 57%), so the gate
is *true per-cycle regime conditioning*, not snapshot toggling. Results vs **V222-IC-on**:
trend **+$3,273.56 (Δ +$161)**, crisis **−$7,831.73 (Δ +$470)**, recent **+$3,849.56
(Δ +$1,854)**, trend+selector **−$4,101.98 (Δ −$279)** — V223 dominates always-on IC on
every cell. **But vs equal-weight IC-off the verdict flips:** net over the 3 cells is IC-off
**+$1,153** > V223 **−$709** > IC-on **−$3,192**. Disentanglement: trend Δ within ±$200 (NOT
the fsum-artifact falsifier — the +$3.5k trend IC edge is **real** and the gate preserves it,
holding at full IC-on level despite 97/200 bypass cycles); recent recovered 64% of the
IC-on→off gap; **crisis recovered only 10%** because its loss lives in the 121 *normal*-labeled
cycles the denylist leaves IC-on, not the 79 bypassed ones — the pooled seed ICs are
mis-oriented on crisis-period normal cycles, which gating structurally cannot fix. Standing
main stays **V221-era equal-weight (IC-off)**; flag kept but defaults OFF (correct structure
for IC, net-better than always-on, not promoted). IC now refuted twice vs equal-weight (V222
always-on, V223 gated). **V224 = IC re-estimation on a snapshot holdout (audit R3)** — replace
pooled seed ICs with data-derived per-(regime, signal) ICs (fsum-fenced), keep the gate ON;
pre-committed fork: R3 beats equal-weight on ≥2 cells → IC rehabilitated & gate+R3 becomes
main; else IC retired for good and V225 pivots to a new signal class. See `V223.md`.

**V222 (2026-06-13) — no high-water; IC wiring REFUTED in direction; effect is
regime-conditional.** V222 wired the IC subsystem (seeded pooled + per-regime ICs from
`retrospective-alpha-review.md` win rates, removed the empty-IC early-return, declared
`per_regime_ic_weighting`, fsum-fenced the conviction accumulators). 7-cell grid (3 IC-on
selector-OFF + 1 IC-on selector-ON + 3 IC-off controls): **7/7 hermetic at $0.00** (V221's
property holds; no new live channel). Pre-registered bet "recent goes UP" is **REFUTED** —
recent went **DOWN −$2,905** (+$4,901 → +$1,996). Within-V222 IC Δ (clean, fence is
common-mode → cancels): **trend +$3,330.75 (IC HELPS), crisis −$4,771.22 (IC HURTS), recent
−$2,905.15 (HURTS)**. IC weighting raises trade count on every gate (22→30, 23→35, 31→35) by
concentrating conviction on `sma_crossover`(0.54)+`ricci_curvature`(0.46) — net good in
trend, net bad in crisis/normal. Recent's whole edge was its **crisis sub-window** (+$6,292
of +$4,901); IC weighting gutted it to +$2,632. Wiring is correct & deterministic; the
**WR-derived crisis IC priors are over-confident** and the higher conviction inflates trade
count through an un-recalibrated threshold. **V223 = regime-conditional IC weighting** (seed
ICs only in trend/bull/normal; equal-weight fallback in crisis/high_vol — bank trend, kill
crisis). All V211 pre-fence highs stand. See `V222.md`.

**V221 (2026-06-12) — no high-water; BOTH residual channels CLOSED → 4/4 HERMETIC at $0.00, CONFIRMED.** V221 bisected V220's "sizing/exit PnL-magnitude channel" with the new trade-level tool (`scripts/trade_field_diff.py`, obs #13) and found it was two stacked *selection-side* channels: (1) the **cross-sectional demean order channel** — unsorted `signals.items()` iteration summed into `_basket_mean`, whose sub-ulp wobble flipped near-boundary basket membership (N 4↔3 → `budget/N` size jumps 5000↔6666; `math.fsum` fence at `signal_generation.py:1160`, `74fbf4e`; trend_OFF $2,851 → $255.59); then (2) the **funding z-score epsilon-guard amplifier** — `std=1e-8` zero-variance fallback in `signals/funding_rate.py` amplifying the rounding residue of a CONSTANT cached rate (`fl(n·r)/n ≠ r` at n=3,6,7,…) into an exact ±√((n-1)/n) signal (observed 0.408248 = √(2/3)/2 bit-for-bit) whose presence flickered with history length, phase-shifted across replicates by a ±1 swallowed-read offset (constant-history fence; $255.59 → **$0.00**). Methodology: the aggregate per-field fingerprint read "sub-ulp" because it samples `basic_signals.value` POST-demean (mean ≈ 0 by construction) — `signal_contribs.jsonl` per-trade `signal_traces` named the presence flap instantly (queued #18 pre-demean per-ticker fingerprint, #19 epsilon-amplifier AST tripwire; sibling site `geometry/market_manifold.py:424` documented dormant). Known dormant residual: trend_ON cycle-65 sub-ulp post-demean wobble, 1/136 cycles, never reaches trades. **Eval 4/4 hermetic from committed state for the first time → V222 IC wiring unblocked** (seed pooled ICs first — V218.B trap; fsum `_ic_weighted_composite`'s `total_w`/`weighted_mean` on activation). See `V221.md`.

**V220 (2026-06-11) — no high-water; entry-flip channel CLOSED, larger sizing/exit PnL-magnitude channel EXPOSED → REFUTED.** V220 fsum-fenced the `basic_signals` composite reduction (`victoria_node.py:965` + `signal_generation.py:_balanced_composite`; commits `78b2a0d`/`fad28da`) to close the V219 sub-ulp `basic_signals.value` sign-flip. **Falsifier #1 fired:** `trend_OFF` spread **$2,851** (floor $200) — hypothesis REFUTED. But the fence worked *at its layer*: V219's trend entry-flip (27↔26 → $597) is **gone — trade count now locked 26/26 on both trend arms.** With entries byte-stable, `trend_OFF` PnL still ranges **$697→$3,549 on the same 26 trades** — a **sizing/exit PnL-magnitude channel** the binary entry-flip was masking. `recent_OFF` regressed PASS→FAIL ($6.52→$1,168, 21↔22 — same magnitude channel surfacing on a 2nd gate); `crisis_OFF` stays hermetic ($0.72, 30/30). 4-cell grid: **1/4 PASS** (was 3/4 at V219). The eval has now peeled four order-channels (V211 basket → V217 BLAS → V219/V220 sub-ulp entry-flip → V220 sizing/exit magnitude); each fence reveals the next. **V221 = bisect the sizing/exit channel at the trade-PnL level (extend `per_field_diff.py` to entry/exit price, position size, slippage, fees); IC wiring pushed to V222, blocked until 4/4 determinism is restored.** All V211 highs **stand** (pre-fence anchor). See `V220.md` + `REFLECTION_V220.md`.

### V217-era hermetic baseline (2026-06-09 — HISTORICAL "pre-substrate-fix"; NOT comparable to V219+; superseded above)

Single-threaded BLAS + bar-time sizing fence (V216) + HTTP guard (V215), **but macro=0**
(failed-FRED cache) — so these are session-bound, not reproducible from committed state
(see ⚠️ below; V219 establishes the real-macro baseline). Every cell was byte-identical
($0.00 within-cell spread) across N replicates at sleep=10. Kept as a historical anchor only.

| Gate    | Selector OFF (baseline) | Selector ON   | Selector Δ (ON−OFF) | Determinism      |
|---------|------------------------:|--------------:|--------------------:|------------------|
| recent  | -$1,905.71 (38t)        | +$2,334.40 (39t) | **+$4,240.11** | both PASS $0.00 |
| trend   | +$1,039.24 (35t)        | -$6,392.99 (37t) | **−$7,432.23** | both PASS $0.00 |
| crisis  | -$2,199.50 (38t)        | -$3,420.26 (36t) | **−$1,220.76** | both PASS $0.00 |

Selector read (clean): ON **helps recent** strongly, **hurts trend** strongly (flips
profit→loss), **hurts crisis** mildly. Stays OFF on main; per-gate split is the V219
regime-gated-selector case.

> ⚠️ **The V217-era OFF numbers above are NOT reproducible from committed state** (discovered
> V218). They were measured on transient, uncommitted cache state: a failed-FRED `macro_cache`
> (all-zero VIX/yields — the eval has been running with no macro) + a session-specific
> `funding_rate_cache`. A committed-state no-op control (V218.B) gives +$4,530 / +$456 / −$2,863
> (22/25/31t), not −$1,906 / +$1,039 / −$2,200 (38/35/38t). Treat the V217-era table as
> session-bound until V219's eval-integrity fix (commit/freeze real macro + funding caches).

**V218 (2026-06-09) — no high-water; matrix of 3 cells, all NO-MERGE; uncovered two eval-integrity defects + one diagnostic.** First matrix-mode run (3 independent cells, selector OFF, sleep=10, N=2, all 18 audit runs determinism PASS $0.00). **V218.A (V199 carry plumbing)** — **inert**: the funding-carry signal needs `market_data["funding_rate"]` (absent from replay snapshots) then falls back to a live Binance fetch the V215 HTTP guard blocks (200 blocked `fundingRate` calls/cycle), so carry=0 every cycle and A's trade CSV is **byte-identical to the no-op control**. Code is correct but untestable until funding is frozen (V219). **V218.B (V170 per-regime IC weighting)** — **BLOCKED** (caught at kickoff by the new `IC-WEIGHTING INERT` probe): the whole IC-weighting subsystem is unwired in the eval (`update_signal_ics` has zero callers → `_signal_ics` empty → `_compute_weighted_conviction` early-returns the raw composite before the per-regime branch). Ran as a flag-only no-op (flag ON, Δ=$0.00) confirming inertness; V219.B-corrected wires pooled ICs first. **V218.E (snap_crisis_2020q1)** — **CANDIDATE**: under identical code+cache the crisis gate flips **−$2,863 (2022h1) → +$13,052 (2020q1)** (crisis regime verified firing: 8 crisis trades on 2020q1), so V217's crisis loss is **at least partly a single-window artifact, not structural** — but both runs used the zero-macro cache, so the magnitude is pending a real-macro re-run. **Eval-integrity findings (V219 blocker):** (1) macro_cache is all-`__failed__`/0.0 → the eval runs with **VIX/yields=0**; (2) funding_rate_cache is uncommitted + warm-up-overwritten → non-reproducible. Shipped obs: `IC-WEIGHTING INERT` + `per_regime_ic_weighting` banner probes, `scripts/v218_matrix_status.sh`, `SNAP_OVERRIDE`. `main` unchanged. See `V218-matrix.md`.

**V219 (2026-06-10) — no high-water; eval-substrate freeze SHIPPED; eval now 3/4 hermetic from committed state; trend_OFF determinism falsifier fired.** V219 fixed audit R1 (reproducible-from-committed-state eval): repaired `macro_cache.db` with real Yahoo values (FRED `DEMO_KEY`→HTTP 400; VIX/2Y/10Y/DXY proxies documented), committed `frozen_funding_cache.json`, added an md5 cache manifest + macro/funding health tripwires (`run_training.py` startup preflight), and anchored the frozen-mode macro read to the cache's `MAX(date)` instead of `now()` (kills silent expiry + same-day false-PASS). `main` strategy byte-unchanged. **Re-baseline grid (4 cells × N=2 @ sleep=10):** macro is no longer 0, so committed-state numbers shift — recent **−$3,364** (Δ −$1,458 vs V217-era), crisis **−$4,481** (Δ −$2,281), trend **weakly positive ~$900–$1,500**. **Determinism: 3/4 PASS** (crisis_OFF $0.00, trend_ON $0.85, recent_OFF $6.52) but **trend_OFF FAILs $596.91** — pre-registered falsifier #1. `per_field_diff.py` bisect names it: cycle-3 `basic_signals.value`, |Δ|=3.2e-18, a sub-ulp sign-flip around zero = **a second order-channel in the same field** as the V217 BLAS channel (the BLAS pin is verified active, so distinct from it; latent at macro=0, surfaced by real macro). **NOT a substrate defect** — `_macro_bias_score` byte-identical across replicates, macro reads reproducible; falsifiers #2 (tripwires 5/5) + #3 (manifest stable) PASS. Boundary-adjacency makes it flip one trade only on trend_OFF (27↔26). BLAS-pin + PYTHONHASHSEED don't cover it → strong-inference `id()`-ordered accumulation in the basic_signals composite. The non-det trend baseline blocks clean IC measurement, so **V220 splits: A = canonical-sort/`fsum` the composite (re-close the channel, 4/4 hermetic), then B = wire per-regime ICs** (audit R2). All V211 pre-fence highs stand as historical; V217-era table demoted to "pre-substrate-fix." See `V219.md`.

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
