# Research findings — 2026-05

Seven research items reviewed for Victoria. Each entry has: source,
key result, fit to current stack, implementation priority, and the
first viable PR pointer.

Priorities: **P1** = build immediately (low cost, high expected ROI),
**P2** = build after P1 validates live, **P3** = scope only, defer.

---

## P1 — VPIN (Volume-synchronized Probability of Informed Trading)

* **Source:** 2026 paper "VPIN as a Predictor of Bitcoin Price Jumps."
* **Key result:** VPIN spikes (z-score ≥ 2 on volume-bucketed OFI)
  precede significant BTC price moves by 1-3 cycles. Magnitude is
  predicted; direction is not.
* **Fit:** strong — `ws_feeds.py` already computes a trade-count VPIN
  proxy. The 2026 paper insists on volume-bucketed VPIN (canonical
  Easley/López de Prado).
* **Status: BUILT.**
  - `omega/nodes/victoria/signals/vpin.py` — z-score + spike wrapper.
  - `ws_feeds.py` — VPIN bucket logic upgraded to volume-bucketed
    (symbol-specific thresholds in `_VPIN_VOLUME_BUCKETS`).
  - `signal_generation.py:1124-1144` — per-ticker injection.
  - `strategy.py:1063` — ensemble `size_mult` × `vpin_conviction_multiplier`
    (default 1.3) on spike.
  - Preset: `v185_phase_a` (V176 + VPIN + Kyle + LOB), `v185_vpin` (just VPIN).
* **Validation:** WS-only — inactive in backtest snapshots. v185_vpin_live
  launched as the live A/B (PID 67807, 192 cycles).

## P1 — Kyle's Lambda

* **Source:** "Continuous Auctions and Insider Trading" (Kyle, 1985);
  recent re-validation on crypto microstructure (2025-26 papers).
* **Key result:** λ = Cov(ΔP, signed_vol) / Var(signed_vol). High λ
  indicates market makers are demanding more compensation per unit
  flow → informed trading detected. Complementary to VPIN: VPIN
  measures imbalance, λ measures price impact.
* **Fit:** strong — uses the same WS aggressor-tagged tape as VPIN.
* **Status: BUILT.**
  - `omega/nodes/victoria/signals/kyles_lambda.py` — rolling 200-tick
    OLS slope + rolling 100-λ z-score + spike detector.
  - `ws_feeds.py:get_ticks()` — public accessor for the trade tape.
  - Wired into `signal_generation.py` and `strategy.py` (multiplier
    1.2 on spike).
* **Validation:** WS-only. Will be exercised by v185_phase_a live run.

## P2 — TradingAgents (multi-agent LLM debate framework)

* **Source:** https://github.com/TauricResearch/TradingAgents
* **Key result:** LangGraph-orchestrated bull-vs-bear research debate
  plus aggressive-vs-conservative risk debate. Each round is an LLM
  call. Authors report robust performance on slow-cadence stock
  decisions.
* **Fit:** partial. Full architecture is too LLM-heavy for 15-min
  cadence (20+ LLM calls per cycle would cost ~$100/day). The
  *patterns* are useful — see `docs/research/tradingagents-evaluation.md`
  for three ideas worth porting (LLM tie-breaker on split ensemble,
  post-decision risk-scaling call, reflection-driven entry penalty).
* **Status:** evaluated, not built. Tie-breaker (Idea 1) is the
  cheapest viable port (1 LLM call only when ensemble would otherwise
  sit out).
* **Next step:** add `llm_tiebreaker` feature flag, snapshot ablate,
  then live A/B vs vanilla ensemble.

## P3 — LOB (Limit Order Book) feature engineering

* **Source:** Recent CatBoost-on-LOB literature showing cross-asset
  predictive stability of multi-level OFI, trade-arrival-rate-burst,
  and adverse-selection.
* **Key result:** depth-weighted OFI across 5 levels has IC 2-3× that
  of top-of-book imbalance alone. Arrival-rate bursts (z ≥ 2) precede
  large directional moves.
* **Fit:** strong — `ws_feeds.py` already stores top-20 book each side.
* **Status: BUILT.**
  - `omega/nodes/victoria/signals/lob_features.py` —
    `multi_level_imbalance`, `trade_arrival_rate_z`, `adverse_selection`.
  - `ws_feeds.py:get_book()` and `get_ticks()` public accessors.
  - Wired into `signal_generation.py`.
  - In `v185_phase_a` preset.
* **Validation:** WS-only. Live test via v185_phase_a.

## P3 — EMGNN (Evolving Multi-Graph Neural Network)

* **Key result:** dynamic correlation graphs evolved via edge-attention
  outperform fixed-window correlation estimates at regime transitions.
* **Fit:** would replace `rmt_denoise` + `wasserstein_regime` as the
  regime classifier.
* **Cost:** high — needs PyTorch + graph convolutions, which the
  Python layer (numpy/scipy guard) doesn't currently carry.
* **Verdict:** defer. Pre-condition: count "wrong regime" episodes in
  current regime traces. If >5% of cycles, EMGNN is worth the cost.
  Until then, the existing Wasserstein regime detector likely
  dominates the marginal value.

## P3 — Meta-RL-Crypto (online policy-gradient trading agent)

* **Key result:** self-improving RL agent uses meta-learning to adapt
  to regime shifts within a few episodes.
* **Fit:** superficially overlaps with our `meta_harness` +
  `auto_improve` loop. Difference: meta_harness is offline parameter
  search on snapshots; this is online policy gradient on live PnL.
* **Cost:** very high — reward shaping, action discretization, stability
  work for live PnL targets (noisy).
* **Verdict:** defer. The composite-PnL offline loop captures most of
  the same adaptation benefit at <1% complexity.

## P3 — CryptoPulse (cross-market LLM-style forecasting)

* **Key result:** fine-tuned cross-modal encoder takes equity / forex /
  commodity macro features and forecasts crypto returns. Attention
  over multi-asset state, not per-feature contributions.
* **Fit:** complements our simple dxy/spy/vix z-score signals which
  treat each cross-market input independently.
* **Verdict:** maybe. First step is a cheap forensic — check
  `data/signal_ic_history.json` for current dxy/spy/vix IC values.
  If low, build a minimal version (cross-asset PCA or simple
  attention-weighted combiner). If already high, defer.

---

## Implementation summary

What's live or in code as of this turn:
* VPIN (volume-bucketed) — built + live
* Kyle's Lambda — built, in V185 Phase A preset
* LOB features — built, in V185 Phase A preset
* TradingAgents — evaluated, three ideas scoped

Snapshot ablation caveat: VPIN/Kyle/LOB are all WS-only. The fresh_0508
snapshot ablation of `v185_phase_a` will measure no signal contribution
(WS data does not replay). Live A/B is the only valid test.

Live A/B currently running:
* v177_ensemble_extended_c — V176 ensemble baseline
* v185_vpin_live — V184 lock50 + VPIN multiplier
* (v185_phase_a_live not yet launched — pending after Phase A snapshot
  smoke test confirms parity with baseline)
