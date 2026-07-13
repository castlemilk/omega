# LIVE_PAPER_SCOPE — Victoria Phase 2 live-paper harness (scoping only)

**Date:** 2026-07-13 · **Author:** claude (Opus 4.8)
**Type:** scoping document — NO code changes to strategy.py or any strategy file.
**Predecessors:** `V249.md` (Phase 1 CLOSE + phase transition), `CAMPAIGN_STATUS.md`
(resume criteria), `V249_MANIFEST_AUDIT.md` (calendar constraint).

**Mandate:** scope a live-**PAPER** harness (real-time market data → the frozen
strategy's decisions → **simulated** PnL; **no broker, no orders, no funds**) so
the calendar can manufacture the independent recent-regime windows the frozen
manifest structurally cannot (V249 resume criterion 1: N independent recent ≥ 20).
Live-paper is also the campaign's first genuinely out-of-sample validation of the
standing baseline (crisis +$599 / trend +$2,997 / recent +$30).

> **Headline for the impatient:** this is far more *build-reuse* than *build-new*.
> The live OHLCV path (`DataIngestionNode`), the fill/bookkeeping engine
> (`PaperTradingEngine`), and the un-frozen determinism posture **already exist and
> already run**. The strategy is a stateless-per-cycle Node that consumes
> `{signals, market_data}` dicts — it is **not** file-coupled, so there is **no
> fundamental blocker**. The genuinely new work is a scheduler/poller loop, a
> crash-safe checkpoint, and a quarterly freeze-and-label step. See §7 for the one
> conceptual trap (online "recent" regime is a mis-framing — §2.7).

---

## Section 1 — Current-state audit

### 1.1 Where the eval gets market data (frozen)

Eval OHLCV comes entirely from **frozen JSON snapshots**, injected by
`ReplayIngestionNode` which *replaces* the live ingestion node when
`--backtest-snapshot` is set (`scripts/run_training.py:984-991`; loader
`omega/nodes/victoria/providers/replay.py:60-74`). Enumerated paths:

- `data/snapshots/snap_20260414.json` — the standing GATE window.
- `data/snapshots/snap_crisis_{2020q1,2022h1,2024aug}.json`,
  `snap_trending_{2023q4,2024q1}.json` — named regime snapshots.
- `data/snapshots/walk_forward/snap_wf_YYYYMMDD.json` — the **32** rolling 90d
  windows (regime_counts: crisis 12 / trend 10 / recent 10 nominal), indexed by
  `data/walk_forward_manifest.json`, built by `scripts/walk_forward_freeze.py`.
- **Frozen macro/info inputs** (determinism-load-bearing, md5-pinned by
  `data/.cache_manifest.json`): `data/macro_cache.db` (FRED DGS2/DGS10/DTWEXBGS/
  VIXCLS + funding), `data/frozen_advanced_signals.json`, `data/frozen_funding_cache.json`.
- **V238 frozen-series store** `data/frozen_series/<name>.json` (FRED, GDELT,
  funding, OI, DVOL, FNG…) read as-of-bar by `SeriesProvider`
  (`series_provider.py:37,125-142`) — gated behind `frozen_series_enabled` (default
  **OFF** in the standing baseline).
- **Seed IC priors:** `data/signal_ic_history.json` (committed; loaded at startup).

Snapshot format = per-symbol `open/high/low/close/volume/timestamps` arrays +
`_macro` block (`replay.py:21-42`).

### 1.2 Where the strategy consumes bars (the decoupling that de-risks everything)

`StrategyNode.execute()` (`strategy.py:880`) dispatches `CONSTRUCT_PORTFOLIO` /
`BACKTEST_STRATEGY` and reads its inputs from **`params["signals"]` and
`params["market_data"]`** (`strategy.py:886-893`) — plain dicts. `market_data[sym]`
carries `close`/`adjclose` arrays; the engine's fill helper always uses `close[-1]`
(`paper_trading.py:148-163`). **The strategy has no knowledge of where those dicts
came from** — frozen replay or live REST are interchangeable at this seam. This is
the single most important audit finding: bar-driving the strategy is a *runner/
ingestion* problem, not a strategy problem.

Cycle timing: the runner is a **fixed-count `for i in range(n_cycles)` loop**
(`run_training.py:1280`), one `orch.run_one_cycle()` per iteration
(`orchestrator_v2.py:899`). Bars advance via the `ReplayIngestionNode` cursor
(one bar/cycle, `replay.py:116,140-159`), **not** the loop clock. `--sleep` is pure
pacing at cycle-end (`run_training.py:1840-1841`); backtests run `sleep=0` and it is
behaviorally inert (frozen determinism relies on this).

### 1.3 Cadence — DAILY (1d) bars (confirmed)

The historic "15-min" note refers to a defunct `v168_15min_micro` experiment
(threshold-multiplier comment at `strategy.py:1493-1495`); it is **not** the
standing configuration. The walk-forward eval and standing baseline are **daily**:
`freeze_snapshot.py:199` fetches `timeframe="1d"`; `walk_forward_freeze.py` recipe =
"ccxt/Binance 1d", `WINDOW_DAYS=90`; live default `interval="1d", limit=90`
(`data_ingestion.py:178-179`); `SeriesProvider` is daily as-of with
`MAX_STALE_DAYS=7`. A 90d window = ~60 honest cycles (`min_bars - 31`). **Live-paper
must run at daily cadence** to preserve fidelity with the frozen numbers.

### 1.4 State carried across cycles / restarts

- **In-process (lost on crash):** `progress`, `sit_out_counts`, watchdog/breaker,
  and `PaperTradingEngine` open/closed trades + `realised_pnl`.
- **Written per cycle (append/rewrite, monitoring only):** `{version}_trades.csv`,
  `{version}_metrics.jsonl`, `{version}_progress.json`, decision snapshots.
- **Committed, cross-restart inputs:** `signal_ic_history.json` (seed ICs);
  meta-learner state (saved every 50 cycles); `SignalDecayDetector` (each cycle);
  SQLite `omega_victoria_state.db` / `_memory.db` / `macro_cache.db`.
- **Optional Postgres backing:** `PaperTradingEngine(db_url=…)` already writes
  `paper_trade` open/close rows (`paper_trading.py:763-976`) — **but the runner
  never reloads open positions on start** (§1.6).

### 1.5 Sizing / risk infra (already complete)

`PaperTradingEngine` (`omega/core/paper_trading.py`, 1090 LoC) is the fill +
bookkeeping engine wired onto the strategy as `_paper_engine` (`strategy.py:587`,
set by `run_training.py:1082`):
- `execute_proposals()` opens positions; size = `raw_size_fraction *
  conv_size_scale * initial_capital` (`paper_trading.py:410`), gated by
  `_check_portfolio_limits` (max_portfolio_exposure, max_position_per_symbol).
- `mark_to_market()` closes via `exit_controller.should_close`, time-exit,
  stop-loss, trailing-stop (`paper_trading.py:587-745`).
- **Fill model = current-bar close, zero explicit slippage** (`_extract_price →
  close[-1]`, `paper_trading.py:148-163`; `"slippage": 0.0` in records). A separate
  `_calculate_slippage` (sqrt-impact model) exists in `strategy.py:4105` but the
  engine records 0.0.
- Portfolio equity = `initial_capital + realised_pnl + Σ unrealised`, recomputed
  each cycle for resilience/drawdown gates (`strategy.py:1862-1891`).
- Drawdown gates: V162 resilience `emergency_close()` flattens on drawdown
  (`strategy.py:1892-1907`).

### 1.6 Determinism fences and how they behave live

**All determinism fences are gated on `OMEGA_FROZEN_CACHE` / `--frozen-cache`, so
"live mode" is definitionally the un-frozen path.** No fence needs to be deleted —
the live harness simply runs with frozen-cache OFF and no `--backtest-snapshot`.

| Fence | Site | Live behavior |
|---|---|---|
| urllib `OpenerDirector.open` HTTP block (V215) | `run_training.py:807-835` | **Disarmed** live (must be — live needs real fetches) |
| BLAS 1-thread pin (V217) | `run_training.py:56-63` | Only armed for frozen argv; live skips (results non-bit-repro, acceptable) |
| Bar-time clock (V216) | `strategy.py:1794-1826` | Returns `None` live → correctly falls back to `datetime.now(UTC)` |
| Macro warm-up skip / frozen reads | `run_training.py:965-968`, `data_cache.py:193-217` | Auto-revert to live TTL refresh when unset |
| `math.fsum` summation sites | `strategy.py`, `signal_generation.py` (many) | **Stay ON** — correctness, harmless live |
| AST tripwires (no-wallclock, frozen-http) | `scripts/check_*.py` | CI-only, protect the *eval* path; no runtime effect |

**No per-run resume/checkpoint exists** (`run_training.py` has none; a crashed run
restarts from cycle 0). Resume exists only at the **grid level** (cell skip on
`summary.json` PASS, `walk_forward_grid.sh:88-91`). This is the single biggest
genuine gap for a months-long live run.

---

## Section 2 — Gap analysis for live-paper

| Requirement | Status | Evidence / what's missing |
|---|---|---|
| **Real-time OHLCV ingestion** | **EXISTS** | `DataIngestionNode` + `ProviderRegistry` (Binance klines primary → Bybit/Coinbase/Kraken/CryptoCompare), `interval="1d"` (`data_ingestion.py:37-44,178`). V249 confirmed Binance klines return. Only bypassed in eval; runs live when `--backtest-snapshot` is absent. |
| **Simulated fill model** | **EXISTS (reuse verbatim)** | `PaperTradingEngine` fills at `close[-1]`, same engine used in backtest → fidelity by construction (§6). No new fill code needed for MVP; slippage refinement is optional/later. |
| **Portfolio bookkeeping** | **PARTIAL** | Positions/equity/PnL fully tracked in-memory; Postgres `paper_trade` persistence exists (`paper_trading.py:763-976`). **GAP: no reload-open-positions-on-start** — engine starts empty every run. |
| **Live signal pipeline (6 signals)** | **PARTIAL** | 5/6 have live `compute()` feeds: fear_greed (Alternative.me), VIX (yfinance `^VIX`), DXY (FRED DTWEXBGS), yield_curve (FRED DGS2/10), gdelt (GDELT DOC 2.0). **funding_rate** has a live OKX feed but **no frozen source** (live-only). **GAP: no polling scheduler** — nothing polls on an interval today. VIX live path self-disables under frozen cache (yfinance), fine when unset. |
| **Determinism harness** | **EXISTS (as relaxation)** | Live = un-frozen path; all fences self-gate off `OMEGA_FROZEN_CACHE`. Keep ON: `fsum` sites, CI AST tripwires (protect eval). Relax: HTTP block, BLAS pin, bar-time clock, macro-freeze. No code change — just don't set the flag. |
| **Resume-on-crash** | **GAP (biggest)** | No checkpoint/reload in `run_training.py`. Need: periodic snapshot of engine positions + equity + `signal_ic`/decay/meta state, and load-on-start. Postgres schema is a head-start; wiring the reload is new. |
| **Regime detection at live cadence** | **GAP — but mis-framed; see §2.7** | The window classifier is **retrospective**; "recent" is not an online state. The correct move is NOT online recent-detection. |

### 2.7 The regime-detection framing correction (read before §7)

The mandate asks for an "online version" of the regime classifier "so we know when
we're IN a recent regime to count the window." **This is a category error, and it
is the most important thing in this document.**

`walk_forward_freeze.py:regime_label` (`:116-121`) is **fully ex-post**: it labels a
window from that window's *whole-90d* `max_dd` and end-to-end `basket_ret`. `recent`
is the **residual bucket** (`return "recent"` = "neither crisis nor trend over the
full window"), named for gate continuity, **not a market state**. The code says so
itself: the standing "recent" gate window mechanically **relabels to crisis** once
it contains the April-2026 crash (`walk_forward_freeze.py:240-243`, *"'recent' was
always a temporal name, not a regime."*). **You cannot be "in a recent regime" in
real time** — `trend` (+20% end-to-end) and `recent` (the residual) are unknowable
until the 90 days close.

The resume criterion does **not** require online recent-detection. It requires:
1. Run the strategy live, regime-agnostic. The strategy already uses **causal**
   runtime labels (`normal`/`high_vol`/`crisis`, 1-cycle lag, `features.py:970-973`;
   `HMMRegimeDetector` bull/bear/sideways, `regime_detector.py:495-747`) for its own
   thresholds — those are fine online and need no change.
2. **Every elapsed quarter, freeze the trailing 90d of live bars into a
   `snap_wf_YYYYMMDD.json` and run the *same retrospective* `regime_label` on it.**
   That post-hoc label is what adds an independent recent/crisis/trend window to the
   manifest. Counting toward N≥20 is an **offline, after-the-fact** step — exactly
   the classifier we already have, applied to newly-elapsed calendar.

So "online regime detection" is **not on the critical path**. The critical path is
faithful live execution + a quarterly freeze-and-label job reusing existing code.

---

## Section 3 — Recommended architecture

### 3.1 Reuse vs new

**Reuse verbatim (no strategy edits):** `StrategyNode`, `PaperTradingEngine`,
`DataIngestionNode` + `ProviderRegistry`, all six signal `compute()` paths,
`SeriesProvider`, `walk_forward_freeze.py` (for the quarterly freeze/label), the
orchestrator's `run_one_cycle`, the whole un-frozen determinism posture.

**New components (thin, platform-side, Go-preferred per CLAUDE.md where it's
scheduler/persistence; Python only where it touches the signal/strategy layer):**
1. A **daily scheduler/poller** that, once per UTC day after bar close, fetches
   fresh bars + macro/info feeds and invokes one strategy cycle. (Replaces
   `range(n_cycles)` + `sleep` with a real bar trigger.)
2. A **crash-safe checkpoint store** (engine positions + equity + signal state) with
   load-on-start.
3. A **quarterly freeze-and-label job** (cron) that snapshots trailing 90d live bars
   → `snap_wf_*.json`, labels via the existing classifier, appends to the manifest,
   and bumps the recent-N counter.
4. A **paper-vs-backtest reconciliation harness** (offline; §6) that replays the
   same 32 historic windows through the live-paper cycle path and asserts match
   within 2·SE.

### 3.2 File structure (proposed, all new files under gitignored/new dirs)

```
omega/live_paper/                 # NEW module (platform layer)
├── __init__.py
├── scheduler.py                  # daily UTC bar-close trigger → one cycle
├── cycle_runner.py               # thin: fetch → signals → strategy.execute → engine → persist
├── checkpoint.py                 # snapshot/restore engine + signal state (crash-safe)
├── feeds.py                      # per-signal poll cadence wrapper (daily / 8h / 15min)
├── reconcile.py                  # replay 32 frozen windows through live path, assert 2·SE
└── config.py                     # LivePaperConfig schema (universe, capital, cadence, paths)
scripts/
├── live_paper_run.sh             # headless entrypoint (nohup-friendly, PID-tracked)
└── live_paper_freeze_quarter.sh  # quarterly freeze + retrospective label + manifest append
data/live_paper/                  # NEW (gitignore) — checkpoints, PnL log, live snapshots
├── checkpoint.json / .db
├── pnl_curve.jsonl
├── regime_state.jsonl
└── snapshots/snap_wf_<newquarter>.json
```

Config should be **protobuf** (project convention) if it crosses the Go↔Python
seam; a Python dataclass is acceptable if the harness is Python-only for the MVP.

### 3.3 Data flow (one daily cycle)

```
UTC bar close (daily)
  → scheduler fires
  → feeds.fetch_all(): DataIngestionNode OHLCV (Binance 1d) + macro/info feeds
      (fear_greed daily, DXY/yield FRED daily, VIX 15m latest, funding 8h latest,
       gdelt 15m latest)
  → SignalGenerationNode → per-ticker composite (existing pipeline, unchanged)
  → StrategyNode.execute(CONSTRUCT_PORTFOLIO, {signals, market_data})
  → PaperTradingEngine.execute_proposals + mark_to_market  (fills at close[-1])
  → checkpoint.snapshot(): positions, equity, realised_pnl, signal_ic/decay/meta
  → append pnl_curve.jsonl + regime_state.jsonl
  → sleep until next UTC bar close
```

### 3.4 Cadence

**Daily (1d) bars** — confirmed §1.3. One strategy decision per UTC day, fired after
the daily bar closes (00:00 UTC). Info feeds poll at their native cadence but are
sampled as-of the daily bar: fear_greed/DXY/yield daily; VIX/gdelt 15-min (use
latest ≤ bar); funding 8h settlement. This keeps every input bar-aligned exactly as
the frozen `SeriesProvider` as-of logic does.

### 3.5 State model

**Both, split by role:**
- **SQLite/Postgres** for the durable ledger (positions, closed trades, equity) —
  extend the existing `paper_trade` schema; add an `open_positions` reload path.
- **JSON checkpoints** for signal-adjacent state (`signal_ic_history.json`,
  decay detector, meta-learner) — these are already file-based; the checkpoint just
  guarantees atomic write + load-on-start.

Rationale: the DB gives queryable history + the reconciliation harness a clean
source of truth; JSON matches how signal state is already persisted.

### 3.6 Observability

- **PnL curve** `pnl_curve.jsonl` (per cycle: equity, realised, unrealised, open N).
- **Regime state** `regime_state.jsonl` (per cycle: causal runtime label +
  HMM state — for diagnostics, NOT for counting recent windows).
- **Per-cycle signal values** (reuse `signal_contribs.jsonl` writer).
- **Quarterly window ledger** — each frozen+labelled window with its ex-post regime,
  incrementing the recent-N tracker toward the N≥20 resume gate.
- Optional: stream metrics into the existing OTel/Grafana stack (`make otel-up`).

---

## Section 4 — Build vs buy

| Option | Fit | Verdict |
|---|---|---|
| **Zipline / Backtrader / Vectorbt** | Backtest engines, daily-bar OK, but each imposes its *own* order/fill/portfolio abstraction. Adopting one means re-expressing `StrategyNode` + `PaperTradingEngine` in its API — **destroying backtest-vs-live fidelity** (the reconciliation in §6 would compare two different engines). | **Reject.** The fidelity requirement (match the existing 32-window numbers within 2·SE) is only cheap if live-paper reuses the *same* `PaperTradingEngine`. |
| **freqtrade / QuantConnect** | Full crypto trading platforms with paper modes. Heavy; opinionated data + strategy DSL; QuantConnect is cloud/broker-oriented. Would replace, not embed, the whole stack. | **Reject** for MVP — massive integration surface, and QC steers toward live-broker (out of scope). |
| **CCXT for market data** | **Already effectively in use** via `ProviderRegistry` (Binance klines). Could standardize the feed layer. | **Optional adopt** later; not needed for MVP (the provider layer works). |
| **Build custom (thin harness over existing components)** | Scheduler + checkpoint + reconcile + quarterly-freeze. Reuses everything that carries fidelity. | **Recommended.** |

**Cost estimates (rough):**
- Build custom thin harness: **~6–10 engineering-days** (scheduler ~1–2d,
  checkpoint/resume ~2–3d, reconciliation harness ~1–2d, quarterly-freeze job ~1d,
  soak hardening ~1–2d).
- Integrate freqtrade/Zipline: **~15–25 days** *and* forfeits fidelity — net
  negative.

The decisive factor: the fill engine and live data path already exist, so the "buy"
options add integration cost **and** break the one property (same-engine fidelity)
that makes the campaign's reconciliation gate cheap.

---

## Section 5 — MVP scope

**Minimum viable live-paper** that ingests real-time daily bars for the 10-name
selective universe, runs the standing V240-selective config (all V241–V248 flags
OFF; V243-A optional), simulates fills via `PaperTradingEngine`, logs PnL + regime
state daily, persists across restarts, and runs headless ≥90 days unattended.

**What it is:**
1. `omega/live_paper/scheduler.py` + `cycle_runner.py` — daily trigger → one cycle
   through the *unchanged* signal→strategy→engine path (frozen-cache OFF).
2. `omega/live_paper/checkpoint.py` — atomic snapshot after each cycle; load-on-start
   (positions, equity, `signal_ic`/decay/meta). **This is the load-bearing new code.**
3. `omega/live_paper/feeds.py` — per-signal poll wrappers at native cadence,
   sampled as-of the daily bar.
4. `scripts/live_paper_run.sh` — nohup/PID-tracked headless entrypoint with a
   watchdog restart.
5. `omega/live_paper/reconcile.py` — the acceptance gate (§6): replay the 32 frozen
   windows through the live cycle path, assert per-regime match within 2·SE **before**
   trusting any live number.

**What it is NOT (deferred):** slippage/spread refinement beyond the current
zero-slippage close fill; intraday cadence; new signal feeds; Go rewrite of the
scheduler (Python MVP acceptable, Go migration is a fast-follow per platform rule);
any broker/order path (permanently out of scope).

**Size:** ~800–1200 LoC net-new (checkpoint ~300, scheduler+runner ~300, feeds ~200,
reconcile ~200, shell/config ~100). **~6–10 days** as in §4. Zero lines changed in
`strategy.py` / `signal_generation.py` / `features.py`.

---

## Section 6 — Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| **Fill-model divergence from backtest** | HIGH (it's the acceptance gate) | Reuse `PaperTradingEngine` verbatim so live and backtest share one fill engine. **Gate: `reconcile.py` replays the same 32 historic windows through the live cycle path and must match the walk-forward per-regime means within 2·SE** (pooled MDE ~$875, recent 2·SE ~$727–$1,043 per V247/V249). Any mismatch = a bar-alignment or as-of bug, fix before going live. |
| **Data-feed reliability (Binance/FRED/GDELT outages, geo-block)** | HIGH | Provider failover already exists (Binance→Bybit→Coinbase→Kraken→CryptoCompare). Add: per-feed staleness guard (existing `MAX_STALE_MINUTES=5`, `stale_data` sit-out `run_training.py:1320-1322`); on total feed loss, **skip the cycle** (no trade) rather than trade on stale bars; alert. Note Binance/Bybit US geo-block (memory) — confirm the run host's egress. |
| **State corruption on crash** | HIGH | Atomic checkpoint (write-temp-then-rename); load-on-start reconstructs open positions from the DB ledger; a startup self-check reconciles checkpoint equity vs recomputed Σ positions. Add a restart test to CI. |
| **Regime online-vs-offline confusion** | MEDIUM (design trap, not runtime) | Resolved by §2.7: never classify "recent" online; count windows via the quarterly ex-post freeze-and-label using the existing classifier. Runtime causal labels drive only the strategy's own thresholds, unchanged. |
| **funding_rate live-only (no frozen source)** | MEDIUM | Live path exists (OKX); it will contribute in live-paper where it was 0.0 in frozen eval. This is a *known* live-vs-frozen delta — the reconciliation must **hold funding at its frozen value (0.0) when replaying historic windows** so the 2·SE match isn't polluted by a signal the backtest never had. |
| **Timezone/DST bugs** | MEDIUM | Everything UTC (bars, FRED as-of, settlement). Bar trigger keyed to 00:00 UTC. No local time anywhere; assert UTC in config. |
| **Determinism relaxation hides a real bug** | LOW-MED | Live is non-deterministic by design (real clock, network). Keep `fsum` + AST tripwires ON to protect the eval path; the reconciliation gate is the safety net that catches any live-path logic drift against frozen numbers. |
| **Silent universe/blacklist drift** | LOW | Standing config = `universe_selective_enabled` blacklist {BTC,DOT,LINK} → 10 names. Assert the effective universe at startup (V235 universe-revalidation discipline). |
| **Long-run resource/disk creep** | LOW | Redirect verbose audit writes via `OMEGA_AUDIT_OUTPUT_DIR` (existing); rotate `pnl_curve.jsonl`; `df -h` guard before each quarterly freeze. |

---

## Section 7 — Recommended next steps + decision gates

Four V###-style tasks. Each gated; **none touch strategy files** except where noted
(none do).

### V250 — Live data-feed integration + one-cycle live smoke
- **Build:** `feeds.py` + `cycle_runner.py`; run **one** live cycle end-to-end
  (frozen-cache OFF): fetch daily bars for the 10-name universe + all 6 feeds →
  signals → `StrategyNode.execute` → `PaperTradingEngine` → log. No scheduler yet.
- **Entry:** V249 closed; host egress reaches Binance/FRED/GDELT/OKX.
- **Exit:** one live cycle produces a valid portfolio + (possibly empty) trade set
  with all 6 signals populated (funding non-zero, VIX non-zero live), no exceptions,
  bars confirmed daily + UTC-aligned.

### V251 — Fill-model + backtest reconciliation (**the gate**)
- **Build:** `reconcile.py` — replay the 32 frozen windows through the live cycle
  path (holding funding at frozen 0.0 per §6) and compare per-regime means.
- **Entry:** V250 exit met.
- **Exit (HARD GATE):** live-path per-regime means match the walk-forward baseline
  within **2·SE** for crisis/trend/recent. **If it fails, STOP** — it means the live
  cycle path diverges from the backtest engine; diagnose bar-alignment/as-of before
  any live accumulation. This is the go/no-go for the whole phase.

### V252 — MVP integration: scheduler + crash-safe checkpoint
- **Build:** `scheduler.py`, `checkpoint.py`, `live_paper_run.sh`; load-on-start;
  restart test (kill mid-run, verify positions/equity/PnL reconstruct exactly).
- **Entry:** V251 gate PASSED.
- **Exit:** harness survives ≥3 forced restarts with byte-stable ledger; runs
  unattended for a 7-day burn-in with daily PnL + regime logs.

### V253 — 90-day headless soak + first quarterly freeze-and-label
- **Build:** `live_paper_freeze_quarter.sh` — freeze trailing 90d live bars, label
  via existing classifier, append to manifest, increment recent-N.
- **Entry:** V252 exit met; harness soaking.
- **Exit:** ≥90 days unattended; **at least 1 new independent window** frozen and
  correctly labelled; recent-N tracker advanced. Report live-vs-baseline PnL as the
  first out-of-sample read. (Loop resumes to V254+ training only when recent-N ≥ 20 —
  ~4+ quarters out — or a new data source fires resume criterion 2.)

---

### ⚠️ Prominent flags (per mandate guardrails)

1. **No fundamental coupling blocker.** The strategy is a Node consuming
   `{signals, market_data}` dicts (`strategy.py:886-893`); the live OHLCV path
   (`DataIngestionNode`) and fill engine (`PaperTradingEngine`) already exist and
   run. Bar-driving is a runner concern, fully feasible. Phase 2 is **build-reuse**,
   not a rewrite.
2. **The "online recent-regime detector" ask is a mis-framing (§2.7)** — "recent"
   is an ex-post residual label, not a live state. Counting windows toward N≥20 is an
   **offline quarterly freeze-and-label** step reusing the existing classifier. Do
   NOT build an online recent-detector; it cannot exist and is not needed.
3. **The V251 reconciliation is a hard go/no-go**, and its cheapness depends entirely
   on reusing `PaperTradingEngine` — which is why §4 rejects every third-party engine.
4. **Live-PAPER only.** No broker, no orders, no funds, no live-broker recommendation
   of any kind. The standing "never execute a trade / move money" guardrail is
   absolute and this scope honors it end-to-end.
