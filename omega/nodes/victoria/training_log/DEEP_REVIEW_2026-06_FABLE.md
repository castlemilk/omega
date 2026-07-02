# DEEP REVIEW — V148→V234 campaign (Fable 5, fresh-perspective)

**Date:** 2026-07-02
**Author:** claude (Fable 5) — strategic review, NOT a V### iteration
**Scope:** the whole V148→V234 arc: training_log read broadly, `strategy.py` read
end-to-end, `signal_generation.py` composite/demean core, REFLECTION_V202→V234,
STRATEGIC_AUDIT_2026-06, V230_DECISION, V231→V235.
**Status:** advisory. No strategy.py change, no grid run.
**Deliverable-of-record for:** "is the current approach even the right approach?"

---

## Executive summary

- **The campaign's durable output is a world-class evaluation instrument and
  approximately zero shipped alpha.** The determinism arc (V207→V221, ~14 versions)
  and the distributional harness (V231) are genuinely excellent engineering. But the
  only strategy change ever shipped in the V222→V234 overlay arc — V227's +$630
  crisis skew — was refuted by the campaign's own better instrument three versions
  later (V231: mean-Δ +$69, min-Δ −$425, window-luck). Shipped-and-surviving
  strategy improvements over 13 versions: **zero**.
- **Eight consecutive refutations on one window (V227→V234 on `snap_crisis_2024aug`)
  is not bad luck; it is the system telling you the target is wrong.** 2024aug is one
  draw from a distribution whose measured cross-window spread is $25,435 (V231).
  Optimizing the minimum of an N=3 sample is Goodhart squared. The crisis
  *distribution mean is already positive* (+$933 OFF / +$1,001 ON).
- **The two profitable gates (recent +$4,901, trend-IC banked +$1,428) have NEVER
  been measured distributionally.** Only crisis got the V231 treatment. The entire
  "recent carries the system" narrative rests on exactly one window — the same
  epistemic position crisis was in before V231 blew it up. This is the single
  biggest unexamined risk in the campaign.
- **The effective trading universe is 4 symbols, not 13.** `_TRADING_BLACKLIST`
  in `strategy.py` excludes 9 of 13 names (BTC, DOT, MATIC, XRP, SOL, AVAX, LINK,
  BNB, SUI), each on single-run evidence of ~2–30 trades from the V55–V93 era.
  Cross-sectional demeaning and "basket" construction operate on ETH, ADA, NEAR,
  ARB. Market-neutral construction over 4 correlated alts is not a portfolio; the
  22–47 trades per 200-cycle window are a hand of poker, not a sample.
- **`strategy.py` is 4,000 lines of sedimented single-window fixes.** ~30
  interacting overlays (V63 confirmation, V77/V79/V82/V84 bypass threshold
  oscillation, V95 geodesic gates, V102 crisis_short_bias, V141/V142/V155/V164
  regime blocks, LLM veto, FFG, Fiedler, surfaces…), each calibrated against one
  run of one window at a noise floor that wasn't established until V203–V211.
  Most of the pre-V203 rationale comments cite PnL deltas now known to be 60–70%
  noise (REFLECTION_V202). The strategy is an overfit archaeology site.
- **The binding constraint is statistical power, not the signal universe and not
  the intervention site.** V227–V234 walked signal → site → weight → sizing →
  (proposed) selection. The dimension never walked: N. Per-regime N=1–3 windows,
  ~25 trades/window, daily bars. No signal class, sizing rule, or selector can be
  *distinguished from noise* under that yardstick — which is exactly why every
  grid returns $0.00 or a refutation.
- **Recommendation in one line:** stop iterating per-window interventions; spend
  the next 2–3 versions making the yardstick able to see (walk-forward
  distributional eval, all three regimes, N≥10 windows), re-baseline everything
  against it, then re-open strategy bets — starting with the already-banked
  trend-IC overlay and a portfolio-level crisis exposure cap, and a composite/
  universe simplification. **V235 as pre-registered should NOT proceed.**

---

## Lens 1 — What has actually produced durable value?

### 1.1 Durable (will still matter in 12 months)

All of it is **instrumentation**:

| Asset | Version | Why it's durable |
|---|---|---|
| Byte-identical hermetic eval ($0.00 across replicates, from committed state) | V207→V221 arc (HTTP guard V215, bar-time fence V216, BLAS pin V217, substrate freeze V219, fsum fences V220/V221/V222) | Every future measurement stands on it. Six independent non-determinism channels found and closed, incl. a novel class (epsilon-guard amplifier). |
| Distributional eval harness + 3 crisis windows | V231 | The paradigm win of the campaign. Changed a verdict (V227) the first time it ran. |
| Pre-registration + falsifier discipline, reflection triggers | REFLECTION_V202 onward | V234's falsifier fired **pre-grid** and saved the burn — the process now catches its own dead ends cheaply. |
| Cell-identity / wiring preflights (`assert_cell_identity.py`, IC-INERT probe, wiring banner, `check_no_wallclock.py`, `check_frozen_http_fence.py`) | V213–V229 | Structurally ended the "tune inert code for 10 versions" failure mode (strategy_selector, V170 IC, DAG_PARALLEL…). |
| SESSION_STATE + provenance manifests + resumable grids + gamma redirect | V228→V233 | Operational resilience; grids survive ENOSPC and session death. |
| Forensics toolchain (`per_field_diff`, `trade_field_diff`, `fingerprint_diff`, `signal_contribs.jsonl`) | V210–V221 | Reusable trade-ledger bisection. |

### 1.2 Durable strategy alpha

Honest list:

- **Shipped and surviving: none.** V227 crisis-skew shipped default-ON, then failed
  the distributional bar in V231 (kept ON as the standing main but its claimed edge
  is dead: mean-Δ +$69 ≈ noise).
- **Banked, unshipped:** drawdown-gated trend-IC overlay (V229, trend +$1,428
  hermetic, up to +$2,786 at X=0.08) — the strongest live candidate, parked because
  it loses crisis/recent and can't be promoted un-gated. Measured on ONE trend
  window.
- **Negative knowledge (real value, not PnL):** IC-as-selection is crisis-
  incompatible (5 refutations); additive-composite crisis terms can't move 2024aug
  (7 refutations across signal/site/weight); realized/lagging selectors are
  structurally blind to pre-reversal shorts (V234); the selector is a regime-bias
  amplifier, not a detector (V215–V217).

### 1.3 Churn accounting

V222→V234 = 13 versions. Outcomes: 1 instrument win (V231), 1 synthesis sprint
(V230), 1 ship-later-refuted (V227), **10 refutations/no-merges**. Counting the
whole V199→V234 span (~36 logged versions): ~14 were the determinism/eval arc
(necessary, high-value), ~5 produced process/observability wins, and **~17 were
strategy bets of which 0 survive the current yardstick**. Roughly: **>95% of
surviving value is the instrument; ~0% is shipped alpha.** That ratio is the
campaign's honest report card — and it is not necessarily bad if the next phase
cashes the instrument in. It is bad if the next phase keeps buying more
refutations on the same window.

### 1.4 Deferred/avoided (the roads not taken)

Consistently deferred, every one still open: trend/recent distributional windows
(B2, MATIC→POL fork — deferred in V231, V232, V233, V234, V235); portfolio-level
crisis intervention (first named in V235's own falsifier branch 3); walk-forward
eval (never proposed as such); universe/blacklist revisit (never — blacklist
entries from V55–V93 have NEVER been re-validated on the hermetic eval);
higher-frequency bars (dismissed once, V168-era); paid options data (correctly
parked, Track A); live-paper Phase B (Fork C of the strategic audit, untouched).

---

## Lens 2 — Structural constraints: where is the actual ceiling?

### 2.1 The ceiling is statistical, and it's brutal

Numbers already in the log, assembled:

- Trades per 200-cycle window: 22–47. Per-window PnL is dominated by a handful of
  trades (the V218.E crisis flip was traceable to single-name selection changes).
- Cross-window crisis spread under identical code: **$25,435** (V231). The
  overlay effects being hunted: $200–$1,400. **Signal-to-window-noise ratio ≈ 0.03.**
- Per-regime windows: crisis 3, trend 1 (2024q1 built but unused), recent 1.
- The V203 2σ noise floors ($5,094 recent!) were computed then largely bypassed by
  the determinism arc — within-config σ→$0, but *between-window* σ was never
  brought into any gate's acceptance bar except crisis's (V231).

Under this yardstick, essentially no strategy hypothesis of realistic effect size
is testable. The campaign didn't run out of ideas; it ran out of resolution. This
is the actual wall behind the 2024aug $0.00 wall.

### 2.2 The universe constraint (new finding of this review)

`freeze_snapshot.py` ALL_SYMBOLS = 13. `strategy.py:_TRADING_BLACKLIST` = 9 of
them. **Tradeable set: ETHUSDT, ADAUSDT, NEARUSDT, ARBUSDT** (with NEAR and ARB
also short-suppressed under `postmortem_signal_filter`). Consequences:

- Cross-sectional demeaning — the architectural heart of the composite — is
  computed over ≤13 names but *acted on* over 4 highly-correlated alts. "Long the
  relative outperformer of 4 beta-1 alts in a crash" is structurally the trade
  that loses 2024aug: on a broad correlated grind-down there IS no cross-sectional
  spread to harvest, which is why every per-name intervention returned Δ=$0.00.
- Each blacklisting was single-window-era evidence (SOL: 10 trades; SUI: 2 trades;
  AVAX: 3 trades) from BEFORE the eval was deterministic or distributional. The
  most consequential portfolio decisions in the system have the weakest evidence.
- 2020q1's +$15,928 outlier on the 7/13 universe already told us universe
  composition swamps overlay effects.

### 2.3 Architecture constraints (real, but second-order behind 2.1/2.2)

- **Composite is a demeaned linear blend of momentum/mean-reversion transforms of
  the same daily OHLCV** — Track B proved OHLCV is the *only* time series in the
  snapshots. All "orthogonal" candidates are transforms of one data stream; true
  orthogonality (funding history, basis history, OI, options) requires feed-build
  work that has been repeatedly identified and repeatedly deferred.
- **Two-fold quantization** (score→5-level conviction→size step) plus ~10
  multiplicative size modifiers (Kelly, Fiedler, ORC, sit-out, time-of-day,
  regime-continuous, csb, resilience, hv, surface…). The sizing pipeline is so
  layered that V216 found the eval had been running in a uniform 0.375× sizing
  regime *by accident* (daily bars → both intraday damp windows always fire).
  That artifact is still baked into every current number.
- **No portfolio state.** Entries are per-ticker independent; there is no gross
  exposure, no basket-beta budget, no correlation-spike kill-switch. Every crisis
  intervention tried was per-name; the crisis failure mode (correlated grind-down)
  is portfolio-level by definition.
- **No memory in sizing** (Kelly's 50-trade deque is the only state, and it's
  regime-blind).

**Verdict: the ceiling ordering is (1) eval resolution, (2) universe/portfolio
construction, (3) signal universe.** The campaign has been working the list
bottom-up.

---

## Lens 3 — Alternative directions (avoided or unconsidered)

Scored: Effort S/M/L × Expected impact 1–5 × Conviction 1–5.

### (a) Walk-forward distributional eval, all regimes — THE unlock
Roll a 60–90-day window across 2020→2026 Binance daily OHLCV (the V215 freeze
recipe already builds windows on demand), tag each window's realized regime
ex-post, and make the gate unit "mean ± spread over N≈20–30 windows per regime"
with a pre-registered acceptance bar (mean>0 AND p25>floor, or sign-rank). V231
at N=3 changed one verdict immediately; N=25 changes *every* verdict, including
ones we currently trust. Handles the MATIC→POL fork by making basket-identity a
per-window attribute instead of a blocker. Effort **M** (harness exists; this is
snapshot generation + aggregation + wall-clock; worktree-pool parallelism is
already on the parking lot). Impact **5**. Conviction **5**. Falsifier: if
cross-window spreads collapse (they won't — $25k measured) the current gates were
fine.

### (b) Portfolio-level crisis intervention (exposure cap, not per-name gates)
A gross-exposure / net-short-beta ceiling gated on portfolio-level observables
(aggregate realized drawdown of the basket, cross-sectional correlation spike —
Track B #2, mean pairwise correlation is computable from frozen OHLCV in all
windows). Acts at `raw_weights` normalization (the retained V234 actuator site),
scaling the WHOLE book, so it cannot be blind to which name loses — the exact
blindness that killed V227–V234. This is V235's own falsifier-branch-3 escape
hatch, promoted to the main line. Effort **S–M**. Impact **3**. Conviction **4**.
Falsifier: measured on the crisis distribution with the V232 bar; if the cap
can't beat Δ>0 mean without regressing 2020q1's +$15.9k, crisis is declared
uneconomic and the program closes honorably (option (i) below).

### (c) Universe re-expansion + composite simplification (Fork A, finally)
Un-blacklist the 9 names behind a flag and re-measure on the walk-forward
distribution; prune the composite to the signals with verified cross-regime IC
(sma_crossover + the 2–3 that survive re-estimation on N≈25 windows); delete or
default-OFF the sedimented V63–V165 micro-gates that no current test covers.
13 names ≈ 3× the cross-sectional width and ≈ 3× the trades/window → directly
attacks the statistical ceiling AND the 2024aug "no spread to harvest" failure.
Effort **M–L** (it re-bases everything; do it right after (a) so the new baseline
is measured once). Impact **4**. Conviction **3** — some blacklistings may be
genuinely protective; that's what the distribution is for.

### (d) Ship the banked trend-IC overlay, regime-gated, measured on trend windows
The only positive live candidate in the bank (+$1,428 hermetic, +$2,786 at
X=0.08, trend edge replicated 3× across V222/V224/V229). Needs the trend
distribution from (a) (2023q4 + 2024q1 already frozen + 2–3 more). If it
generalizes, it's the first real shipped alpha of the campaign; gate it on the
runtime regime so crisis/recent stay equal-weight. Effort **S** (flags exist).
Impact **3**. Conviction **4**.

### (e) Higher-frequency eval track (1h bars)
24× more bars → more trades per window → real statistical power, and it kills the
V216 daily-bar sizing degeneracy honestly instead of fencing it. Binance 1h
history is freezable with the same recipe. This is the *other* road to N. Effort
**L** (cadence assumptions leak everywhere: hold-cycle counts, SMA windows,
funding cadence). Impact **4**. Conviction **2–3**. Do after (a); (a) is cheaper
and reuses everything.

### (f) ML meta-composite (GBM/logistic over signals)
Premature. On N=3 windows × 25 trades it would be an overfit machine with extra
steps. Becomes reasonable ONLY after (a) provides walk-forward CV folds. Effort
**L**. Impact **3**. Conviction **2**. Explicitly de-prioritized.

### (g) Paid options-vol history (Tardis, ~$300)
Track A's verdict stands: covers 2/3 crisis windows, needs a feed build anyway,
and (a) changes the question. Re-open only if a specific vol-signal hypothesis
survives (a)'s yardstick on the windows DVOL does cover. Effort **S–M** + spend.
Impact **2**. Conviction **2**.

### (h) Live-paper Phase B (Fork C)
The frozen daily eval is structurally blind to microstructure/WS signals (V185).
A long-running paper track is the only honest measurement for that class — but
it's a different program with month-scale feedback loops. Park deliberately, not
accidentally. Effort **M** ongoing. Impact **2–4** (wide). Conviction **2**.

### (i) Declare crisis uneconomic and stand down that program
The blunt option. Distribution mean is already positive; the loss is one window's
tail; per-name interventions are 8× refuted. Under (i), crisis becomes a
*risk-control* objective (cap the left tail via (b), report the distribution,
never optimize its min). This is 80% right. The 20% wrong: (b) is cheap and
portfolio-level, and hasn't been tried — earn the retirement by refuting the one
intervention class that matches the failure's actual structure.

---

## Lens 4 — Structural changes to the loop itself

1. **Distributional acceptance is mandatory, not crisis-only.** No V### may claim
   a win from a single window for ANY gate. This is just extending the V231/V232
   bar (mean-Δ>0 AND min-Δ>0) to trend/recent. The loop already half-knows this —
   it has deferred B2 five consecutive times.
2. **Pre-work separator proofs before grids — keep; it worked.** V234's pre-grid
   forensic and V235's "prove a separator exists before any grid" clause are the
   right generalization: *no grid until an env-gated probe shows the gate variable
   actually discriminates on the binding window.* Cost: ~2 short runs. Saved V234's
   entire burn. Make it a standing skill rule.
3. **Add a Goodhart tripwire to the reflection triggers:** ≥3 consecutive
   refutations *on the same window* ⇒ the next version MUST question the target,
   not the mechanism. V227→V233 took 7 versions to escalate from signal → site →
   sizing; the reflection system fired correctly each time but each REFLECTION
   re-aimed at the same window. The triggers police the *subsystem* dimension;
   they don't police the *objective* dimension. This review exists because that
   tripwire didn't.
4. **Time-box strategic audits on cadence** (every ~10 versions or on any
   trigger). STRATEGIC_AUDIT_2026-06 predicted essentially everything that
   happened in V222–V234 (single-window Goodhart, R3 distributional eval, Fork A
   composite-strip, Fork B "is crisis even a gate") — and R3/Fork B were only
   acted on after 5 more refutations. The audits are cheap and have been right;
   their recommendations should get pre-registered follow-ups, not parking-lot
   entries.
5. **Retire "high-water" language for single-window numbers.** The README's
   high-water table is an N=1 artifact museum (V211 anchors, rescinded ceilings,
   demoted highs). Under (a), the standing main is a distribution per regime;
   track mean/p25/min, not a best-ever scalar. The table's history of RESCINDED/
   DEMOTED entries is itself the evidence.

---

## Lens 5 — What I would actually do

### Top priority — V235′ = walk-forward distributional eval for ALL regimes (Lens 3a)

One version, instrument-only, zero strategy risk, and it converts every future
version from a coin-flip into a measurement. Concretely: freeze ~25–30 rolling
60–90d windows across 2020-01→2026-06 (13/13 where possible, tagged universe
where not), run the standing main across all of them (sequential, gamma-redirected,
resumable — all solved problems), and publish the *regime-tagged distribution* as
the new standing baseline. Include trend and recent. Expect casualties: the recent
+$4,901 "carry" of the whole system gets its first honest test. Budget: harness
work is days; the grid is wall-clock (~25 windows × N=2 ≈ several nights,
sequential — acceptable, or take the worktree-pool item off the parking lot).

### Second — portfolio-level crisis cap (Lens 3b), measured on that distribution

The one crisis intervention class that matches the failure's structure and hasn't
been tried. Pre-register with the V232 bar + a Δtrades≠0 requirement. If it fails
→ crisis program formally closes (Lens 3i) with 9 refutations as its tombstone,
and crisis becomes a monitored risk report.

### Third — cash the bank: trend-IC overlay on the trend distribution (Lens 3d), then composite/universe simplification (Lens 3c)

(d) is the fastest path to the campaign's first surviving shipped alpha. (c) is
the bigger structural payoff (more names → more trades → more power → everything
downstream improves) and should be the first *strategy-side* project of the new
yardstick era.

### Ranked table

| # | Direction | Effort | Impact | Conviction | Sequence |
|---|---|:---:|:---:|:---:|---|
| 1 | Walk-forward distributional eval, all 3 regimes, N≥10/regime | M | 5 | 5 | V235′ (instrument-only) |
| 2 | Portfolio-level crisis exposure cap (corr-spike / basket-dd gated) | S–M | 3 | 4 | V236 |
| 3 | Ship banked trend-IC overlay, regime-gated, on trend distribution | S | 3 | 4 | V237 (needs #1's windows) |
| 4 | Universe re-expansion + composite simplification (Fork A) | M–L | 4 | 3 | V238+ |
| 5 | 1h-bar eval track | L | 4 | 2–3 | after #1 proves insufficient |

De-prioritized: ML meta-composite (needs #1's folds), Tardis spend (Track A verdict
stands), live-paper Phase B (separate program — park deliberately).

### V235 — proceed or pivot? **PIVOT.**

Do **not** run V235 as pre-registered. The plan is a 9th intervention aimed at the
same window, and its own falsifier branch 3 already names the exit ("stop
iterating on this window; redirect to portfolio-level crisis risk and the
deferred distributions"). Every input to that branch is already in evidence:
2024aug is one draw of a $25k-spread distribution; the losers are shorts into
reversals, i.e. regime-unpredictable at entry *by the campaign's own forensics*;
and the crisis mean is positive without any fix. The cheap concession: V235's
pre-work (the entry-time separator probe, ~2 short runs) may run **as an
appendix** to the pivot if desired — but pre-commit that a found "separator" on
one window is a *hypothesis for the walk-forward eval*, never a license for
another single-window grid. Branch 3 fires today, at cost $0, on the evidence
already collected. Take it.

---

## Appendix — quantitative trajectory V148→V234

**Log inventory:** 57 V-prefixed docs, 8 REFLECTIONs, 2 audits, 1 decision doc.

**Phase breakdown (logged versions, V199→V234):**

| Phase | Versions | Outcome class |
|---|---|---|
| Threshold/carry tuning era | V199–V205 (7) | 2 "high-waters" later rescinded/demoted by V206b/V211 noise audits; net: negative knowledge |
| Determinism arc | V206b–V217, V219–V221 (14) | 6 channels closed; eval byte-identical from committed state; **the campaign's main durable asset** |
| Selector detour | V212–V213 (2) | Refuted; exposed the network leak (accidental win) |
| Matrix / eval-integrity | V218, V219 (2) | 0 cells merged; found the 2 substrate defects + V218.E window-flip existence proof |
| IC overlay arc | V222–V224, V228–V229 (5) | IC-as-selection refuted 5×; trend-IC overlay banked (+$1,428, unshipped) |
| Crisis-skew arc | V225–V227, V230–V234 (8) | 1 ship (V227) refuted by V231; distributional harness (V231) = paradigm win; site/sizing exhausted on 2024aug |

**Standing main today (V227-skew flags ON):**
- crisis: **distribution** +$1,001 mean / $25,435 spread / N=3 (min −$9,508 2024aug, max +$15,503 2020q1)
- trend: −$217.69 (23t) — N=1 window; banked overlay would put it +$1,428
- recent: +$4,836.68 (22t) — N=1 window, never distributionally tested
- Everything hermetic at $0.00; reproducible from committed state.

**Shipped strategy changes surviving their own best measurement: 0.**
**Instrument assets in daily use: ~10.**
**Refutations logged V222→V234: 10 of 13 versions.**
**Same-window (2024aug) consecutive refutations: 8.**
**Effective tradeable universe: 4 of 13 symbols** (blacklist evidence: 2–30 trades
each, pre-hermetic era, never re-validated).

The instrument is ready. Point it at a target worth hitting.
