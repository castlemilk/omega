# Victoria training log

One markdown file per training version. Source of truth for what was
tried, what happened, and what's next. Replaces ad-hoc notes in run
dirs, memory files, and chat history.

## How to use

- Write a new `V###.md` **before** kicking off the run (hypothesis +
  planned change), update it **after** the run (gate results +
  conclusion + next steps).
- Use `_template.md` as the starting point.
- Update the walk-forward baseline table below whenever a new full-grid
  run moves a regime's distribution (never from a single window).
- Linked from `.claude/skills/victoria-training-loop/SKILL.md` — the
  skill enforces the loop.

> **Campaign status (2026-07-13):** the training loop's **Phase 1 (V241–V249)
> is COMPLETE — paused, not abandoned.** The standing baseline below IS the
> Phase-1 deliverable. V249 found recent-regime alpha is calendar-bound
> (unadjudicable at present data, *not* absent); the loop resumes at V250+ when N
> independent recent windows ≥ 20 (via live-paper accumulation) OR a new data
> source changes regime structure. Full phase tracker + resume criteria:
> `CAMPAIGN_STATUS.md`; the transition rationale: `V249.md`. Every V241–V248 flag
> stays OFF.

## Standing baseline — walk-forward distributions (as of 2026-07-11, V240 SELECTIVE UNIVERSE)

**High-water language is RETIRED.** The acceptance unit is the per-regime
walk-forward DISTRIBUTION (`data/walk_forward_manifest.json`: 32 × 90-day
windows 2020→2026, crisis 12 / trend 10 / recent 10). Standing main = V227-skew
config (`crisis_skew` ON, gate ON, X=0.12; IC OFF; brake OFF; **frozen_series
OFF**) **+ `universe_selective_enabled` (V240.A ADOPTED)** — 10-name universe
(ETH/ADA/NEAR/ARB + SOL/BNB/AVAX/XRP/SUI/MATIC; effective blacklist
{BTC, DOT, LINK}). Full tables: `V240_UNIVERSE_CONFIRM_RESULTS.md`.

| Regime | n | mean | median | p25 | min | max |
|---|---:|---:|---:|---:|---:|---:|
| crisis | 12 | **+$599** | +$65 | −$1,089 | −$5,005 | +$10,343 |
| trend  | 10 | **+$2,997** | +$1,012 | −$572 | −$2,066 | +$17,367 |
| recent | 10 | **+$30** | −$644 | −$857 | −$2,544 | +$3,451 |

**V240.A (2026-07-11) adopted the selective universe** — bar (pooled mean-Δ >
−$300 AND every regime mean-Δ > −$500, vs the 4-name legacy): measured pooled
**+$418** (n=32), crisis **−$221**, trend **+$1,056**, recent **+$546**; 32/32
selective cells DETERMINISM PASS $0.00. Crisis's −$221 mean is bought upside;
its p25 tightens −$1,089 vs −$2,135 and min lifts −$5,005 vs −$5,819 (the
V239 "lost upside, not worse tails" read, now confirmed full-run). Per-regime
means are within recent 2·SE ≈ $2,400 of the legacy numbers — the adopt claim
is "passes the does-not-regress bar with more breadth", not a significance
claim. Previous (V235/V238/V239-era, 4-name legacy) baseline for reference:
crisis +$819 / trend +$1,941 / recent −$516.

**V274 (2026-08-20) certified this table's provenance and re-ran it.** V273's H3
flagged `ic_seed_weighting` / `per_regime_ic_weighting` as **defaults-ON** in
`features.py` and its §7 concluded these three numbers "were all produced with
retrospectively-derived IC weights in the conviction filter". **That conclusion was
wrong** — inferred from the defaults, never checked against the run record. All
**32/32** cells behind this table record `"ic_seed_weighting": false` explicitly
(the arm at `scripts/v240_wf_grid.sh:48`), reproduce the table's means to the cent,
and re-ran on 2026-08-20 at **0.000000 drift** (crisis $1,149.76 / trend $4,679.67 /
recent $771.98 sentinels, exact). **The standing baseline is the causal control, not
the contaminated arm.** The IC-ON counterfactual was measured over the same 32
windows: it moves **all 32 cells**, changes 31 trade counts, flips **8 signs**, and
swings one crisis window 7× — yet every family mean-Δ lands inside its own MDE
(crisis +$78/$2,329, trend +$892/$2,383, recent −$6/$1,060, pooled +$306/$1,174).
A heavy-coupling knob with a large per-cell footprint and no resolvable direction:
it stays OFF. See `V274.md`.

> **⚠ V276 (2026-08-27) — these numbers have only ever been reproduced on ONE host.**
> V276's paired control (run to attribute an unrelated delta) re-ran the three
> sentinels on a second machine and got **crisis $1,082.80** (−$66.96) and
> **recent $824.81** (+$52.83); trend reproduced exactly. Trade counts matched the
> record on all three (9 / 6 / 13), and the deviation is present **before** any V276
> change — it is environmental, not a regression, and V276's own effect was $0.00.
> V274's certification above covers the *data* provenance and remains valid; what is
> NOT pinned anywhere is the **code environment** (interpreter, numpy version, and the
> optional signal deps `yfinance` / `websockets` / `scikit-learn`, all absent on the
> second host). Until `V277` lands an environment manifest, **do not compare a number
> measured on a different machine to this table.** See `V276.md` §6 R5.

**V238 (2026-07-10) re-confirmed these numbers to the cent** — its `main` cells
are byte-identical to the V235 grid (`nonzero_diffs: {}`, 32/32), so the
frozen-series feed build did NOT move the standing baseline. The **"signals
degrade to 0.0" era is retired**: five info feeds (fear_greed, vix, dxy,
yield_curve, funding/OI) now serve real frozen history and the `SeriesProvider`
+ freeze-gap validator ship as infra. But series-ON is **flag-gated, NOT
adopted** — it improves crisis (+$3,148 mean-Δ) at a real trend (−$2,693) /
recent (−$1,161) cost (pooled ≈flat −$24), failing the −$500 regime floor.
`V238_WALKFORWARD_RESULTS.md` has the full OFF-vs-ON distribution.

Verdicts measured on this grid: recent's +$4,901 **DOES NOT REPRODUCE**; the
banked V229 trend-IC overlay **DOES NOT SHIP** (trend mean-Δ −$831 / min-Δ
−$6,136; crisis mean-Δ −$79 / min-Δ −$7,497); crisis is sign-POSITIVE — the
V227→V234 "crisis is broken" arc was window-selection artifact. See
`REFLECTION_V235.md`. V236's chop-throttle mechanism was refuted at $0 by its
pre-grid separator proof (ER/VR do not separate recent winners from losers —
`V236_SEPARATOR_ANALYSIS.md`); baselines above remain the standing numbers.

> **Replay wrap-seam footnote (why pre-V235 numbers are contaminated):**
> `ReplayIngestionNode` wraps at series end, so 200-cycle runs on 60–90-bar
> snapshot windows replayed the data ~2–6× and booked PnL across a fictitious
> last-bar→first-bar price jump (forensic: 6 seam trades = −$114k on one
> wrapped window). Every single-window standing number quoted below this line
> — including recent +$4,901, trend-IC +$1,428, crisis −$2,991 — carries the
> artifact; V225–V234 verdicts are directionally unknown. Fixed in c244568
> (per-window cycle caps = min_bars−31). The historical entries below are
> preserved as narrative, NOT as baselines.

## [RETIRED 2026-07-03] High-water marks (as of 2026-06-03, post-V211)

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

**V250 (2026-07-13) — ADOPT live-feed layer (default OFF `LIVE_PAPER_ENABLED=0`, KEEP FLAG-GATED); first Phase-2 build step — data-feed ONLY, zero strategy lines, backtest byte-identical by construction.** Recon first (measure before asserting): the handoff claimed a prior V250 session "landed Phases 0-3 and pushed" — **false**; `git log` had no V250 commits, no branch, no worktree, no `omega/live_paper/`, only `LIVE_PAPER_SCOPE.md`. Built from scratch: `omega/live_paper/{config,feeds}.py` — a **live analogue of `SeriesProvider`** (each poller fetches the same raw upstream series the frozen store holds and emits the **identical frozen schema**, so live/frozen are interchangeable at the `strategy.py:886` `{signals,market_data}` seam), plus the frozen-path guard (`assert_live_source`→`FrozenPathViolation`), atomic+checksummed cache (`write_cache`/`verify_cache`, temp→fsync→`os.replace`→`.md5`), and `as_of_pick` staleness parity with `SeriesProvider.MAX_STALE_DAYS`. **Retrospective smoke** (`scripts/live_paper_smoke.py`, last 3 UTC days Fri/Sat/Sun 2026-07-10..12 — same falsifier surface as a 72h prospective run at ~0h wall-clock): **23/25 series reachable**, **7 of 8 pre-registered falsifiers PASS, zero FAIL.** F1 crypto-fresh-0d all 3 days ✓ (20/21); F2 macro weekend-stale/weekday-fresh ✓ for VIX (Yahoo ^VIX) + DXY (Yahoo DX-Y.NYB) = fresh/stale-1d/stale-2d exactly, **BLOCKED** for yield_curve (FRED DGS2 needs a key — `DEMO_KEY` rejected 400, `FRED_API_KEY` unset — env gap, not a fault); F3 no Binance failover ✓; F4 schema ⊇ frozen manifest ✓; F5 frozen-path guard ✓ (blocks `data/frozen_*`/`file://`/`macro_cache.db`, allows http); F6 past-date reproducibility ✓ (ETH past dates byte-stable across 2 fetches; full-doc md5 differs only on the still-forming newest bar); F7 cache atomic+checksummed ✓ (23/23); F8 restart-mid-fetch ✓ (stray truncated `.tmp` never corrupts the committed file). **The one F1 flag is a TRUE-POSITIVE catch, not a bug: `ohlcv_close_maticusdt` `out_of_range/668d`** — MATICUSDT live klines stop 2024-09-10 (MATIC→POL rebrand/delisting), while POLUSDT is fresh; the frozen series retains MATIC from `data.binance.vision` archives so **backtest is blind to a symbol that cannot be traded live** — the exact live-vs-frozen drift the smoke exists to surface. Universe left unchanged (faithful to V240-selective; a remap needs the V251 reconciliation, not a silent edit) → **#1 V251 item.** 7 network-free unit tests pass (`tests/test_live_paper_feeds.py`). **No V240 confirm-grid run** — `omega/live_paper/` is imported by ZERO eval-path files (grep-verified) and no strategy file was touched, so byte-identity is structural, not empirical. **Deferred (per scope §7):** `reconcile.py`/V251 gate, `scheduler.py`+`checkpoint.py`/V252, quarterly freeze/V253. **Observability→V251:** (1) MATIC→POL remap P0; (2) run-host provisioning — real FRED key + GDELT egress (both dark here); (3) GDELT dated-tone via GKG timeline; (4) funding archive depth for the freeze; (5) chain Bybit/Coinbase/Kraken failover into `fetch_ohlcv`. **No high-water break** (infra version, no PnL). See `V250.md`.

**V249 (2026-07-13) — campaign-level PHASE TRANSITION; Training Loop Phase 1 CLOSED (no code / no flag / no grid). Recent-regime alpha is CALENDAR-BOUND — "no adjudication," NOT "no alpha."** After V248 exhausted the exit space under the current manifest, the only live lever was the V247 α sub-path (widen the manifest to add independent recent windows, lowering the 2·SE bar). Phase 0 audit (`V249_MANIFEST_AUDIT.md`) found it **calendar-infeasible for recent**: the primary 90d/90d grid **already tiles the full 2020-01-01→2026-06-30 span with zero gaps** — 26 independent slots, ALL used, only **4 assigned to recent** (the nominal "recent n=10" is 4 independent + 6 overlapping ±45d offsets = literal data reuse). Doubling recent N 10→20 cannot be manufactured from frozen data at any cost short of waiting for future recent months. The **one** executable widening (refetch the 20 non-recent offset windows) grows **pooled** N 32→52 / MDE ~$875→~$750 but leaves **recent** MDE $1,043 unchanged, flips **zero** near-misses to ADOPT (V248's +$494 stays below even the tightened pooled bar), and costs a permanent ~60% grid-time bump → **decision: do NOT refetch.** (OHLCV re-fetch was empirically probed this session and works — no geo-block STOP; feasibility was never the blocker, the calendar is.) **The precise finding:** V248 +$494 / V246 +$627 / V243-A +$232 are all positive and all *might* be real; the recent 2·SE noise floor ($727–$1,043) sits above them, so they cannot be adjudicated — the V241→V248 "8 refutations" were the objective going sub-resolution, and the V247 ruler is what let us see it. **Phase 1 deliverable = the standing baseline** (crisis +$599 / trend +$2,997 / recent +$30, cushion in 2 of 3 regimes) — shippable under honest pooled-MDE bars; every V241–V248 flag stays OFF. **Two families formally CLOSED** (portfolio-correlation, sealed by V244; entry-side info feeds *at daily bars*, 5 pooled-flat bets V236→V245); exit-side SATURATED (V246+V248 near-miss band). **Recommended next phase = live PAPER trading** (real market data → SIMULATED PnL, explicitly NOT live-broker execution / NOT moving money): each elapsed 90d = 1 new independent, zero-overlap, correctly-labelled recent window at ~1/quarter — the only source of the windows the frozen manifest cannot supply, and the first genuinely out-of-sample measurement the campaign will have. **Resume criteria (V250+):** (1) N independent recent windows ≥ 20 via live-paper accumulation, or (2) a new data source that changes regime structure (intraday OHLCV / on-chain / options). Retained infra: `training_log/`, walk-forward eval harness + determinism fences, reflection discipline, the `victoria-training-loop` skill (now carries a Phase-transition section + calendar-independent-N preflight). See `V249.md` + `V249_MANIFEST_AUDIT.md` + `CAMPAIGN_STATUS.md`.

**V248 (2026-07-13) — REFUTED_AT_SCORING ($0 grid); regime-conditional exit params fall $131 short of the re-derived V247 bar — the first candidate adjudicated entirely under the ruler, and it works.** REFLECTION_V246 §5 priority #1: let each RUNTIME regime (normal/high_vol/crisis; 1-cycle causal lag via `set_current_regime`) carry its own (trail_keep_frac, max_hold_win, max_hold_lose), recovering the compromise cost a single global pair (V246) had to pay. The $0 scorer (`scripts/v248_exit_scorer.py` — extends the v2 exact bar-mark replay with per-regime rules read from each OFF window's committed `signal_fingerprint.jsonl` regime series; per-regime OFAT `trail_k∈{.25,.75}`/`hold_win∈{8,14}`/`hold_lose∈{4}` + best-per-regime composition, Δ vs replayed incumbent 0.5/10/6) tops out at **pooled mean-Δ +$494** (composition: normal:trail_k=.25 + high_vol:hold_win=8 + crisis:trail_k=.25). It CLEARS two of three gate legs — recent Δ +$61 ≥ −$360, pooled level-p25 Δ +$285 ≥ 0 — but the binding **pooled-mean bar +$625 (V247 low-coupling 2·SE) is unmet by $131**, landing squarely in the pre-registered **[+$400,+$625) "inside noise, no adopt"** band. Per the pre-reg *"no grid unless a cell passes"*, the 32-cell grid was **NOT run — $0 grid spent**, versus the full grid V246 burned to reach an equivalent +$627≈2·SE near-miss. Instrument note: incumbent replay 99.1% exit-cycle / 91.5% exact-pnl (the `INVALID_REPLAY` flag) is **intrinsic to the replay class — `v246_exit_scorer_v2` is byte-identical on the same V240-confirm ledgers, NOT a V248 regression**; the Δ metric is robust because the best cell moves only 20.1% of trades, so ~80% replay identically on both arms and contribute exactly $0 to Δ (the rounding lives in unmoved trades and cancels). Engine committed **DORMANT** (`exit_regime_adaptivity_enabled` default OFF; defaults = legacy 0.5/10/6; `regime_exit_params=None` ⇒ pre-V248 code path — OFF byte-identical verified). **No high-water break.** 4th consecutive exit/portfolio refutation (V244/V245/V246/V248) and the standing conclusion: **exit-side mechanism space is SATURATED under the current manifest** (global V246 +$627 & regime-conditional V248 +$494 both in the near-miss band) — do NOT grind more exit OFAT (that IS the queue V247 killed); the only lever that moves the verdict is the RULER (V247 Phase 1 α — widen the window manifest to add independent recent windows, lowering the 2·SE bar, re-derived pre-reg). See `V248.md` + `$AUDIT/v248/scorer.json`.

**V247 (2026-07-13) — instrument-only (no candidate, no high-water); re-derives the acceptance bars after REFLECTION_V246 exposed the objective as noise-floor-blind.** Phase 0 (`V247_RULER.md`): per-regime variance table + MDE — recent MDE $1,043 at n=10, a $500 recent effect needs ~46 windows, pooled resolves the $875-class for low-coupling mechanisms. Phase 1 (`V247_RULER_CANDIDATES.md`): repair path **β ADOPTED** — pooled-gated bars (2·SE by coupling class: low/exit-only ≈ $625) + a recent no-regression floor (−$360, ~1·SE), a gated LEVEL-p25 tail (Δ-p25 reported not gated), seeded-bootstrap CI, 0 det FAILs; **γ (free-n within a window) REFUTED by measurement** (within-window trade Δs anti-correlated 4–11×), **α (widen manifest) partial/deferred** (~10–15 independent recent windows are attainable via `walk_forward_freeze`). Phase 2 shipped observability (`scripts/wf_obs.py`): dual-tail (level-p25 AND Δ-p25) report + open-key re-entry coupling counter, validated on V246 ledgers (320/343 open-keys matched; 7/7 creations are re-entries after mechanism-created exits). See `V247_RULER.md` + `V247_RULER_CANDIDATES.md`.

**V246 (2026-07-13) — REFUTED (bars honored on a genuinely interesting near-miss); exit adaptivity stays FLAG-GATED OFF — and the 3rd consecutive refutation fires REFLECTION_V246.** The last untouched dimension (exit side): scout found exits NOT un-built — the baseline already runs bar-mark legacy exits (−2% ROI stop, 50%-giveback trail, 6/10 time exits) plus the dormant V131-era ExitController. Scorer v1 (threshold-fill counterfactual) was VOIDED on sight (+$52k fiction — it re-described incumbent rules with unattainable fills); **scorer v2 = exact bar-mark replay from frozen closes (validated: 340/343 exit-cycles reproduce, pnl residual p99 $17)** passed the pre-registered gate on ONE cell: `trail_keep 0.5→0.25 + hold_win 10→8`. Implementation: `PaperTradingEngine` legacy-exit literals parametrized behind `exit_adaptivity_enabled` (default OFF, byte-identical smoke-proven). Grid (32 windows, 0 det FAILs): **pooled mean-Δ +$627 — exactly at 2·SE ($625), the first plausibly-real pooled effect since V240; level-p25 tightened in EVERY regime** — but the falsifier gates the Δ-distribution and recent: recent mean-Δ +$72 (<+$100, 2·SE $727) AND recent p25-Δ −$407; pooled Δ-p25 −$378 < $0 → REFUTED, flag stays OFF (V239 precedent: the bar is the bar). Scorer-vs-grid post-mortem: per-trade replays cannot see re-entry/capital coupling (343→327 trades); recent prediction inverted (+$231 → +$72). **REFLECTION_V246 (stagnation trigger, V244/V245/V246): the dead end is the OBJECTIVE — "recent mean-Δ ≥ +$100" is 7× below the n=10 noise floor (2·SE ≈ $727); V247 must re-derive bars from the variance table (pooled-gated or more recent windows, fixed in pre-reg) before drawing from the untouched list (regime-conditional exits; V243-A re-score).** See `V246.md` + `V246_WALKFORWARD_RESULTS.md` + `REFLECTION_V246.md`.

**V245 (2026-07-13) — REFUTED; gdelt solo is the fifth pooled-flat-with-variance info-feed bet — flag stays OFF (no baseline move).** The V244 refuted-branch target: `gdelt_solo` (V240.C frozen geopolitical feed, `frozen_series_signals="gdelt"` + `geopolitical_signals`, zero new code) vs the reused V240 selective cells over the full 32-window manifest. Phase-0 PASSED (all 10 series cover all windows; `geo_*_signal` composite-visible; ON≠OFF with a trade flip on the Ukraine window) and the grid was clean — **64 cells, 0 missing, 0 det FAILs, 3 sentinels N=2 at $0.00** — but the pre-registered falsifier fired twice: **recent mean-Δ −$129 (<+$100) AND recent p25-Δ −$641 (<+$400); pooled p25-Δ −$716 (<$0)**. Crisis +$220 / trend −$236 pass their −$300 floors; pooled mean-Δ −$31 with $5.7k Δ-spread, Δ-median negative in ALL regimes (20/32 windows hurt). Level-p25 nuance recorded (crisis −$638 vs −$1,089, trend −$137 vs −$572 — it compresses some tail windows while taxing the median), but the verdict is the bar, not the nuance. Pattern now explicit: five info-class/conditioning bets since V236 (chop throttle, β-residual, series-ON, whale-gate, gdelt) are ALL pooled-flat-with-variance — the entry-side composite looks saturated at daily bars. Next: **V246 exit-side adaptivity** (last untouched dimension; $0 pre-scorer on the ledgers' mae/mfe/capture columns first, per the V244 protocol). See `V245.md` + `V245_WALKFORWARD_RESULTS.md`.

**V244 (2026-07-13) — REFUTED AT SCORING ($0, no grid); corr-spike portfolio tail cap fails its pre-registered sanity gate — the portfolio-correlation mechanism family CLOSES.** The REFLECTION_V241 §5 top candidate (V237 spec: trailing pairwise-corr detector → drop-only new-entry sizing cap at the `raw_weights` site) was killed by its own $0 offline counterfactual scorer (`scripts/v244_offline_calibration.py`) before any implementation: on the 343 trades / 32 V240-confirm ledgers joined to the frozen snapshots (7-bar entry-bar detector, 1,888 obs, 0 unmapped), **0/12 (τ∈{p60..p90} × s∈{0.5,0.7,0.9}) cells pass** the gate (pooled p25-Δ>+$100 AND recent mean-Δ>+$100) — 11/12 WORSEN pooled p25, 12/12 worsen recent mean. Forensics: **winners' median entry-bar corr 0.704 vs losers' 0.708** (zero separation — same failure shape as V236's ER and V237's β-contamination) and the high-corr tercile is net PROFITABLE (+$74/trade, +$8,470 pooled), so the cap shaves winners, not tail; the basket simply lives at high correlation (τ_p60=0.758). Even the look-ahead window-level proxy fails the recent bar (+$55 < +$100). Zero code, zero flags, baseline unchanged; V237's standing clause activates: **no further portfolio-corr work without new data feeds.** Baseline reproducibility re-certified same day (4/4 V240 confirm cells byte-identical ex-timestamp). Separator-first has now killed three conditioning bets (V236/V237/V244) at $0 total grid burn. Next: **V245 gdelt solo** (pre-registered refuted-branch target). See `V244.md`.

**V241 (2026-07-12) — REFUTED; reasoning layer is ACTIVE but adds variance, not expectancy — stays FLAG-GATED OFF (no baseline move).** Full falsifier eval of the V240.D scaffolding: 32-window walk-forward, `reasoning_on` (selective universe + `reasoning_layer_enabled`, Gemini 3.1 Pro Low via agy served ENTIRELY from the committed `data/frozen_llm_cache/` — 691 entries, filled 4h16m under grid-identical frozen conditions via the new `OMEGA_LLM_CACHE_FILL=1` override so fill/replay prompts hash-match) vs the reused V240 selective cells (OFF arm not re-run; 4-window reproducibility spot-check identical ex-run-timestamp). **0 determinism FAILs, 3 sentinels N=2 at $0.00, 100% cache hits, zero `LLMCacheMiss`.** Phase-0 inertness tracer (new standing instrument, `OMEGA_REASONING_TRACE` + `scripts/v241_intervention_report.py`): 691 calls, **99.6% intervention, 42.6% of candidates dropped**, p50 15.2s — emphatically not inert. But the pre-registered conjunction fails both recent clauses: **recent mean-Δ +$227 (< +$400; 2·SE ≈ $1,050, 5/10 windows negative, mean carried by ONE sentinel window +$3,991) and recent p25-Δ −$705 (< +$500)**; trend −$69 / crisis −$48 pass no-regression. Pooled Δ +$31 with **$27,345 spread** (one trend window −$18,733, another +$8,612): whole-basket LLM review at this granularity reshuffles PnL violently with ~zero mean — variance for nothing. Contract note: scale cap tightened [0,1.5]→**[0,1]** (drop/scale-DOWN only, per launch directive) before any fill call. Named dead end: whole-basket LLM review as an expectancy source; any veto-only revisit is gated on the counterfactual drop scorer (obs backlog) first showing negative-PnL skew in the drop set on EXISTING ledgers. V242/V243 consumed by parallel Opus tracks (whale_flow regime gate REFUTED; {ADA,NEAR,ARB} blacklist extension parked at a $18 gate miss on branch `v243-portfolio-sep`) → next pre-reg is **V244**. See `V241.md` + `V241_WALKFORWARD_RESULTS.md` + `REFLECTION_V241.md`.

**V240 (2026-07-11) — four tracks; SELECTIVE UNIVERSE ADOPTED (baseline moved), gdelt built, reasoning layer scaffolded.** **(A)** Per-ticker forensics on the V239 flip (`scripts/v240_universe_forensics.py`, trade-log reconstruction over the V239 grid's 32 `universe_full` trades.csv): the crisis −$522 regression is carried by **DOT (−$1,686 crisis, negative every regime), LINK (−$1,340, negative everywhere), BTC (−$703, short-only)**; 32/512 keep-subsets pass the bar. Shipped `universe_selective_enabled` (effective blacklist {BTC, DOT, LINK} → 10-name universe) and confirmed full-run (32 selective cells vs the reused V239 legacy arm, **0 det FAILs**): pooled **+$418**, crisis **−$221**, trend **+$1,056**, recent **+$546** — all four bars pass (reconstruction predicted +$512/−$211/+$1,250/+$643 — mean-level interactions roughly cancel). **ADOPTED as standing baseline** (table above; crisis p25 tightens −$1,089 vs −$2,135). **(B)** `frozen_series_signals` per-signal allowlist + 160-cell solo-feed grid (`scripts/v240_signal_grid.sh`, 0 det FAILs): **whale_flow alone carries ~90% of series-ON's trend floor breach (−$2,433 of −$2,693) AND ~65% of its crisis benefit (+$2,063 of +$3,148)**; fear_greed/vix secondary trend draggers (−$637/−$672); dxy/yield_curve benign but near-inert (pooled p25 = $0). The V238 crisis/trend tradeoff is ONE signal's tradeoff — regime-gated whale_flow is the queued bet. `V240_SIGNAL_FORENSICS.md`. **(C)** gdelt frozen source BUILT (10 series, 2019-12→2026-07, daily; `scripts/v240_freeze_gdelt.py`; V213-class `geo_*_signal` alias fix) — see `V240_GDELT_ADD.md`. **(D)** Reasoning-layer scaffolding: `reasoning_layer.py`, **Gemini via `agy`** (DeepSeek/Kimi/OpenRouter unavailable — `V240.md` Model choice), hermetic `data/frozen_llm_cache/` + `LLMCacheMiss`, flag `reasoning_layer_enabled` default OFF; smoke PASS (frozen replay identical, repeat-sampling identical). Falsifier eval = V241. See `V240.md` + `V240_UNIVERSE_FORENSICS.md` + `V240_UNIVERSE_CONFIRM_RESULTS.md`.

**V239 (2026-07-10) — universe/blacklist flip; MARGINAL miss, KEEP the 4-name universe (no baseline move).** New flag `universe_full_enabled` (default OFF, byte-identical) empties `_TRADING_BLACKLIST` at `strategy.py:2335/3652`, opening 4 names (ETH/ADA/NEAR/ARB) → the full 13-name snapshot universe (+ BTC/DOT/MATIC/XRP/SOL/AVAX/LINK/BNB/SUI) per `V235_UNIVERSE_REVIEW.md` (new blacklist = ∅). Grid = 32 windows × {`universe_legacy`, `universe_full`} × N=1 (3 sentinels N=2) = 64 cells, **0 determinism FAILs**; `universe_legacy` **byte-identical to the V238 `main` grid** (`nonzero_diffs: {}`, 32/32) → the flag is a clean no-op OFF (infra SHIP). **Adopt-full verdict: NO** — bar = pooled mean-Δ > −$300 AND every regime > −$500; the flip **passes pooled (+$210, net-positive) and helps trend (+$1,051) and recent (+$248)** but **crisis regresses −$522**, tripping the −$500 floor by $22. Honoring the pre-reg: KEEP LEGACY. **Key nuance (V240 hook):** crisis's regression is lost UPSIDE, not worse tails — the full universe *tightens* crisis p25 (−$1,004 vs −$2,135) and lifts min; the −$522 mean drop is one gate-tripping number, so V240 does **per-ticker forensics** (which of the 9 re-included names carries the crisis mean loss vs the tail benefit) rather than a blanket breadth reject. Trend/recent gains are inside recent 2·SE ≈ $2,400 (directional, not significant). Standing baseline unchanged; `universe_full_enabled` stays default-OFF. See `V239.md` + `V239_WALKFORWARD_RESULTS.md`.

**V238 (2026-07-10) — frozen-series feed build; infra SHIPS, series-ON stays FLAG-GATED (no baseline move).** Built the `series/` freeze section + a bar-aligned `SeriesProvider` (raises on out-of-range, never wraps — the c244568 seam lesson as a hard contract) + a freeze-gap coverage validator, wiring six info-class signals that had degraded to 0.0/stale under the V215 hermetic guards. Grid = 32 windows × {main=OFF, series=ON} × N=1 (3 sentinels N=2) = 64 cells, **0 determinism FAILs, all $0.00 spread**. **OFF-path byte-identical to the V235 grid** (`nonzero_diffs: {}`, 32/32) → default flag-OFF is a true no-op, standing baseline unchanged. Five feeds now serve REAL frozen history (fear_greed fng[2018→2026], vix fred_vixcls[1990→2026], dxy fred_dtwexbgs, yield_curve fred_dgs10+dgs2, funding/OI frozen_funding_cache manifest-OK); **gdelt honestly ABSENT** (no frozen source yet — neutral by the no-silent-zeros contract, queued V240). **Adopt-ON verdict: NO.** Bar = pooled mean-Δ(series−main) > −$300 AND every regime mean-Δ > −$500; measured pooled **−$24** (n=32, passes clause 1) but **trend −$2,693 / recent −$1,161** breach the −$500 regime floor. The information set nets ≈flat pooled while re-shuffling exposure: **crisis +$3,148 mean-Δ** (p25 +$581, 9/12 windows positive — clears the recent 2·SE ≈ $2,400 noise bar) bought with a real trend/recent tax. `frozen_series_enabled` stays default-OFF; V240 does per-signal forensics (which of the five helps crisis without the tax) + builds the gdelt frozen source. See `V238.md` + `V238_WALKFORWARD_RESULTS.md`.

**V235 (2026-07-03) — instrument-only; walk-forward distribution (32 windows, 64 cells, 0 det FAILs) inverts the campaign's priors.** Built the walk-forward instrument (`walk_forward_freeze.py` → 32 regime-tagged 90d windows 2020→2026; `walk_forward_grid.sh` + `walk_forward_aggregate.py`), plus two forensics: (a) **universe re-validation** (`V235_UNIVERSE_REVIEW.md` — all 9 blacklist entries noise-founded on ~99 pre-hermetic trades; flip deferred to V238); (b) **the replay wrap-seam** (c244568): `ReplayIngestionNode` wraps at series end, so every pre-V235 single-window number was booked partly against a fictitious price seam — V225–V234 verdicts downgraded to directionally unknown. Grid results: **recent +$4,901 DOES NOT REPRODUCE** (honest mean −$516/p25 −$2,551, n=10 — recent is the WORST regime); **trend-IC DOES NOT SHIP** (trend mean-Δ −$831/min −$6,136; the 48-cell interim "helps crisis +$896" INVERTED to −$79/min −$7,497 at 64 cells — partial grids are not verdicts); **crisis is sign-POSITIVE** (mean +$819/median +$249, n=12) — the 8-refutation "crisis is broken" arc was window selection. Baselines re-anchored to the distribution table above; V236 executes the trend-IC refutation branch and retargets recent; V237's crisis program closes OBE, mechanism retargets tail width. See `V235.md` + `V235_WALKFORWARD_RESULTS.md` + `REFLECTION_V235.md`.

**V234 (2026-07-01) — REFUTED (falsifier branch 3, pre-grid); the 2024aug loss is a candidate-SELECTION failure, not sizing — the V227 drawdown gate never selects the traded losers.** V234 moved downstream of the composite (per V233 branch 4) to throttle crisis position SIZE on the V227 drawdown-AND-gate. A **pre-grid forensic** (env-gated stderr probes at the `raw_weights` throttle site, run against the exact grid config on `snap_crisis_2024aug`) refuted it before any burn: (1) **no wiring bug** — the throttle site is on the live training path (weighted proposals originate in `StrategyNode._construct_portfolio`), the throttle IS reached on trade cycles, and `_skew_dd_mag` is present on **100%** of candidates → the session-entry "not propagated to the sizing site" hypothesis is **disproved**; (2) **the throttle fires on 0 candidates** because traded 2024aug candidates max `_skew_dd_mag` = **0.0644 at entry** (200-cycle; 0% exceed 0.08, let alone the 0.12 gate) → at thresh 0.12 every cell is guaranteed **Δ == $0.00**, so the grid was **NOT launched** (burn saved). **Structural finding + correction to V233:** `_skew_dd_mag` is *realized PAST* drawdown; the 2024aug losers are **shorts entered before reversals** (~0 pre-entry drawdown), so a lagging selector is structurally blind. V233's "the V227 gate fires correctly on 2024aug (0.292)" cites a **non-traded** ticker — the gate and the traded losers are **disjoint sets**. Eight interventions (V227–V234) all failed on 2024aug for the *same* reason: each keys off a signal that does not discriminate the losing set at entry. **No high-water break.** Reflection-trigger fired → `REFLECTION_V234.md`; **V235 pivots to the candidate-SELECTION layer** with an entry-time (forward/cross-sectional) discriminator, mandatory pre-work to prove a separator exists before any grid (`V235.md`). The default-inert throttle *actuator* is retained for V235 reuse with a better gate. See `V234.md` + `REFLECTION_V234.md`.

**V233 (2026-06-29) — REFUTED (falsifier branch 4); the 2024aug crisis deadband is NOT at the additive-composition SITE — pivot to sizing/exit.** Tested the V227-skew probe under 4 application-site variants × 3 crisis windows (12 cells N=2, **all DETERMINISM PASS $0.00**, cell-identity PASS), Δ vs the V227-skew standing main. **The binding window (snap_crisis_2024aug, −$9,508) stayed byte-identical at Δ == $0.00 under pre-demean injection at EVERY weight (0.2/0.4/0.6)** — weight escalation never crosses a trade-decision boundary on the correlated yen-carry grind-down. `pre_demean_common_mode_w0.2` (the directional-tilt re-injection meant to move `w_conv` across a floor) moved 2024aug only **+$6.31** (same 47 trades, **0 trades flipped** — a price-level rounding perturbation) while regressing 2020q1 (−$182.34) → fails branch-1. Pre-demean was not merely inert but **actively HARMFUL on 2022h1** (−$4,461 → −$4,485 → −$4,852, monotone in weight). **Structural conclusion: 2024aug's $0.00 is a downstream decision-boundary deadband (sizing/exit), NOT an additive-composition-site artifact** — the site dimension joins the four prior additive-term signals (V227/V231/V232) that all hit the same wall. **No high-water break** (crisis main stays the V227-skew standing main, mean +$1,001 / spread $25k, N=3); conditional trend/recent spot-check correctly did NOT run (no crisis winner). Reflection-trigger fired → `REFLECTION_V233.md` (additive-term-at-composite subsystem exhausted for 2024aug); **V234 pivots to a sizing/exit-layer crisis intervention** (`V234.md`). (Op note: grid stopped 10/12 on a host `ENOSPC` at 2026-06-25 — here-doc temp files land in host `$TMPDIR`, not the gamma redirect; resumed 2026-06-29, 10 PASS cells auto-skipped, 2 missing 2024aug cells filled.) See `V233.md` + `V233_dist_results.md` + `REFLECTION_V233.md`.

**V232 (2026-06-24) — REFUTED; RV-term-structure inversion brake net-HURTS the crisis distribution (mean-Δ −$345.82, no high-water break).** First crisis bet measured on the V231 distribution (3 windows × {skew, skew+brake} × N=2, 6 cells all PASS $0.00 determinism; OFF reproduces the V227-skew mains to the cent). Added an additive `[-1,0]` brake from short-RV(3d)/long-RV(14d) inversion (`signals/rv_term_structure.py`), post-demean fsum-add after V227 skew, reusing the V227 drawdown-AND-gate. **Falsifier (mean-Δ>0 AND min-Δ>0) failed on both clauses:** 2020q1 Δ **$0.00** (inert), 2022h1 Δ **−$1,037.46** (fired and HURT — same 33 trades, $1,037 worse), 2024aug Δ **$0.00** (GATE INERT, exactly the V227 pathology). **Key structural finding (Track A pre-trace, grid-confirmed):** the worst window (2024aug −$9,508) is **immune to ANY post-demean weight-0.2 additive crisis term** — the V227 gate *fires* (drawdown 0.292 = 2.4× threshold) but the demean+0.2-weight nudge never crosses a trade-decision boundary; both V227 skew AND the V232 brake produce exactly $0.00 there. The blocker is the application **site/weight**, not the signal menu. Crisis high-water remains the V227-skew standing main (**mean +$1,001 / spread $25k, N=3**). V233 pivots to the application-site dimension (pre-demean / weight escalation) before any 4th signal. (Mid-grid the host disk hit 100% → one `ENOSPC` crash on 2024aug_on; environment fault, cleaned + resumed, 4 PASS cells skipped.) See `V232.md` + `V233.md`.

**V231 (2026-06-22) — instrument-only; distributional crisis eval CONFIRMS we were Goodharting one window ($25,435 cross-window spread) and V227's +$630 does NOT generalize.** Built a ≥3-window-per-regime eval harness (NO strategy change) and re-measured the standing main across **3 crisis windows** (2020q1 7/13, 2022h1 11/13, **2024aug 13/13 — new, V215-frozen**). All 6 cells PASS $0.00 determinism. **Falsifier Branch A fired (B0):** standing-main crisis PnL = **+$15,928 (2020q1) / −$3,621 (2022h1) / −$9,508 (2024aug)** → **spread $25,435 ≫ $2k** (bigger than V218.E's ~$16k). The −$2,991 "crisis" number quoted throughout V227→V230 is the **2022h1 single window** (ON reproduces it to the cent). **B1: V227's +$630 is window-luck** — reproduces exactly on 2022h1 (+$630.08) but min-Δ **−$424.50** (hurts 2020q1) and **$0.00 on 2024aug** (regime/drawdown gate inert); mean-Δ +$68.53 → **fails mean>0 AND min>0**. **No high-water break (instrument-only).** The single-window "crisis −$2,991 / +$630" framing is RETIRED; the standing-main crisis baseline is now a **distribution: +$933 mean / $25k spread (N=3)**. V232 = ship Track B's RV-term-structure brake **measured on this distribution** (the bar V227 failed). See `V231.md` + `V231_dist_results.md`.

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

**V229 (2026-06-21) — no high-water; drawdown-gating the trend-IC overlay does NOT make
IC crisis-safe at ANY X (fork #1 REFUTED) → IC retired for crisis (5th refutation); V230
pivots to a third signal class.** V229 applied V227's fix (replace the categorical
{crisis,high_vol} bypass with a per-ticker realized-drawdown discriminator) to the trend-IC
overlay: bypass IC to equal-weight when `_realized_drawdown_mag > ic_drawdown_threshold`
regardless of the label, catching the 121/200 normal-labeled crisis cycles V228 blamed.
Two new flags (`ic_drawdown_gate_enabled` default OFF, `ic_drawdown_threshold=0.12`);
`_skew_dd_mag` stash hoisted unconditional; pure boolean branch, **no new float-sum**;
new `ic_dd_skips` counter + `OMEGA_IC_DD_LOG` sink. **6/6 grid hermetic at $0.00, 6/6
cell-identity PASS** (after fixing the cosmetic OFF-cell gate-flag false-FAIL in
`assert_cell_identity.py`); both-OFF reproduces the V227 mains to the cent. **Primary
(X=0.12): crisis Δ −$2,008.59 ≫ −$200 → fork #1 REFUTED** — the gate fired 42×/run on
crisis with only −$16 effect, so **the crisis IC harm is structural, NOT drawdown-tail-
localized**. The pre-registered X-sweep confirms **no X recovers crisis** (X=0.08
**catastrophic −$8,999**, X=0.05 floor −$1,559 — crisis Δ is non-monotonic because
per-ticker IC↔equal-weight mixing churns basket SELECTION, not a clean fade to the IC-off
number). **IC is now structurally crisis-incompatible across 5 refutations** (V222/V223/
V224/V228/V229); the crisis-IC-overlay program is closed. **Bonus, banked trend-only:** the
drawdown gate makes the trend-IC overlay a *better* trend lever — **trend +$1,428 hermetic
(N=2, X=0.12)** vs V224 IC-only +$875 and equal-weight main −$218, up to **+$2,786** (N=1,
X=0.08), trend edge *grows* as X drops. **NOT promotable to main** (crisis −$2,009, recent
−$212), so it supersedes V224 IC as the strongest parked trend-only overlay. Standing main
**unchanged from V227**; `ic_drawdown_gate_enabled` default OFF. V230 = pivot to a third
orthogonal crisis-safe signal class (options-implied skew via paid vendor, additive — NOT an
IC re-weight). See `V229.md`.

### V229-era grid (2026-06-21, drawdown-gated IC REFUTED for crisis — V227 main unchanged)

6/6 hermetic at $0.00 (X=0.12, N=2, sleep=10) + a 4-cell X-sweep (N=1). Decisive =
V229-stack-ON (crisis-skew + trend-IC + ic_drawdown_gate) vs within-grid both-OFF
equal-weight, same commit + frozen caches. Both-OFF reproduces the V227 mains exactly.

| Gate | both-OFF / equal-weight (MAIN) | stack-ON (X=0.12) | Δ (ON−OFF) | ic_dd skips/run | Determinism |
|------|-------------------------------:|------------------:|-----------:|:---------------:|-------------|
| trend  | **−$217.71 (23t)**   | +$1,428.16 (26t) | +$1,645.87 | 9  | PASS $0.00 |
| crisis | **−$3,621.25 (31t)** | −$5,629.84 (37t) | −$2,008.59 | 42 | PASS $0.00 |
| recent | **+$4,901.01 (22t)** | +$4,688.60 (24t) | −$212.41   | 6  | PASS $0.00 |

X-sweep (N=1, the calibration step): trend Δ +$1,646/+$3,004/+$2,676 and crisis Δ
−$2,009/**−$8,999**/−$1,559 at X = 0.12/0.08/0.05 — no X recovers crisis; trend strong at
all X. (crisis high-water stays V227 −$2,991.17; recent stays V221-era +$4,901.01; the
drawdown-gated-IC trend +$1,428 is a trend-only overlay, un-promotable — loses crisis/recent.)

**V228 (2026-06-20) — no high-water; stacking the drawdown-gated crisis-skew with the
trend-IC overlay does NOT compose net-positive (fork #2).** V228 turned BOTH shipped-
behind-flags overlays ON simultaneously — V227's drawdown-gated crisis-skew (default ON)
+ the V224 trend-IC overlay (R3 empirical, `OMEGA_R3_ICS=1` + `regime_conditional_ic_
weighting`). Pure flag-stack, **no production code change**; the composition site was
already `math.fsum`-fenced (V221/V222). 6/6 cells N=2 @ sleep=10 **all DETERMINISM PASS
$0.00 + all CELL-IDENTITY PASS** (both overlays confirmed firing every ON cell: skew
on_cycles 12/29/21, ic on_cycles 103/121/87, source R3) — the V227 brief's one technical
question ("do they compose without a new determinism channel?") is answered **yes**.
**But the strategic result is fork #2:** the overlays compose **cleanly additively**, and
additivity drags the trend-IC overlay's *known V224 crisis harm* (−$2,808) into the stack:
**trend +$1,092.87 ✓ (= V224 IC-ON +$875.16 to the cent, skew inert on trend), crisis
−$1,992.57 ✗, recent −$408.79 ✗** (net stack −$246 vs net both-OFF +$1,062 = −$1,308
worse). Decomposition confirms no novel interaction (crisis predicted −$5,799 vs observed
−$5,614). The trend-IC overlay **is not regime-orthogonal in net** — its categorical
`{crisis,high_vol}` bypass leaves 121/200 crisis-snapshot cycles *normal*-labeled → IC-on →
the V224 conviction-concentration loss, which no crisis-skew gain offsets. **SHIP NEITHER
STACKED**; V227's crisis-skew stays the incumbent (flags unchanged), the trend-IC overlay
stays default-OFF (a trend-only finding, as V224 retired it). Standing main **unchanged
from V227**; both-OFF controls reproduced the V227 mains to the cent (eval stable, no
reflection trigger). V229 = drawdown-gate the IC overlay the same way V227 fixed the skew
(realized-drawdown bypass, not categorical label), to make the +$875 trend edge crisis-safe;
else pivot to a third crisis-safe signal class. See `V228.md`.

### V228-era grid (2026-06-20, stack REFUTED — V227 main unchanged)

6/6 hermetic at sleep=10, N=2; 6/6 cell-identity PASS. Decisive = stack-ON (crisis-skew +
trend-IC) vs within-grid both-OFF equal-weight, same commit + frozen caches. Both-OFF
reproduces the V227 mains exactly. No skew-ON-or-IC-ON cell beats its both-OFF control net.

| Gate | both-OFF / equal-weight (MAIN) | stack-ON (skew + trend-IC) | Δ (ON−OFF) | skew_on / ic_on | Determinism |
|------|-------------------------------:|---------------------------:|-----------:|:---------------:|-------------|
| trend  | **−$217.71 (23t)**   | +$875.16 (27t)   | +$1,092.87 | 12 / 103 | PASS $0.00 |
| crisis | **−$3,621.25 (31t)** | −$5,613.82 (38t) | −$1,992.57 | 29 / 121 | PASS $0.00 |
| recent | **+$4,901.01 (22t)** | +$4,492.22 (24t) | −$408.79   | 21 / 87  | PASS $0.00 |

(crisis high-water stays V227 −$2,991.17; recent stays V221-era +$4,901.01; the trend-IC
+$875 was already banked in V224 and cannot be promoted to main — loses on crisis/recent.)

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
