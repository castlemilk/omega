# Omega Research Feed — 2026-06-04 00:11

## Items Reviewed
3 items. Twitter handles (@browomo, @zostaff, @hanakoxbt, @0xricker, @adiix_official, @data_sn13) were not indexed by WebSearch — pivoted to recent arXiv/GitHub crypto-quant content in adjacent topic space (LOB microstructure, HFT backtesting) which is where these accounts typically share.

---

## Explainable Patterns in Cryptocurrency Microstructure (Binance Futures, 2022–2025)
**Source:** arXiv — https://arxiv.org/abs/2602.00776
**Type:** paper
**Score:** 5/5 × 3/5 = 15/25 — Queue

**Summary:** CatBoost with a direction-aware GMADL objective trained on 1-second Binance Futures LOB data across 5 assets (BTC, LTC, ETC, ENJ, ROSE) spanning Jan-2022 → Oct-2025. Key finding: feature importance and SHAP patterns are stable across vastly different liquidity tiers — order flow imbalance, spread, and adverse selection cost form a portable cross-asset microstructure feature library. Taker and maker backtests validate tradability, including flash-crash regimes.

**Gap analysis:**
- Does Omega do this? **No.** Known gap: "no order book/L2" data. Omega's signal stack is all bar/aggregate based.
- What would change: New `omega/nodes/victoria/signals/microstructure.py` computing OFI, micro-price, adverse-selection cost from L2 book snapshots; new ingest path for Binance/Bybit depth streams; meta-model gains a microstructure-flavoured feature group.
- Dependencies: L2 book ingestion (WebSocket diff feed → reconstructed book), storage of book snapshots, CatBoost in py-deps (already permitted as optional). Geo-block on Binance from US is a blocker — would need Coinbase L2 + Kraken L2 substitutes; cross-asset portability claim may need re-validation outside Binance.

**Recommendation:** Queue behind L2 ingestion infrastructure. The portability finding is the load-bearing claim — if it holds, this is a high-Sharpe addition. Pre-work: validate that Coinbase + Kraken L2 streams can be reliably collected from our env (paired with the dual-exchange WS work landed in V193). Once book data lands, port the three baseline features (OFI, spread, adverse selection) and run them as standalone signals first — do NOT adopt the CatBoost meta-model wholesale (we have ensemble V176; stacking another tree-based meta risks the gate-stacking failure mode flagged in `victoria_lessons_2026-05`). Defer until after the current V21x cycle.

---

## Exploring Microstructural Dynamics in Cryptocurrency LOBs — "Better Inputs Matter More Than Stacking Another Hidden Layer"
**Source:** arXiv — https://arxiv.org/abs/2506.05764
**Type:** paper
**Score:** 4/5 × 4/5 = 16/25 — Queue

**Summary:** Benchmarks logistic regression, XGBoost, DeepLOB, and Conv1D+LSTM on Bybit BTC/USDT LOB data at 100ms–multi-second sampling. Conclusion: with Kalman filtering / Savitzky-Golay smoothing of inputs and proper label encoding (binary vs ternary), simpler models match or beat deep nets on out-of-sample accuracy, with better inference latency and interpretability.

**Gap analysis:**
- Does Omega do this? **Partial.** We have logistic-meta-model and XGBoost-style ensemble (V176), but inputs are not LOB-derived and there's no Kalman/Savitzky-Golay preprocessing.
- What would change: Apply Kalman smoothing to noisy micro-features (funding rate, VPIN already in V185, Kyle's lambda) before they enter the meta-model. Add Savitzky-Golay as a configurable preprocessor in the signal pipeline.
- Dependencies: scipy.signal (already a dep). No new infra. Wins independent of the L2 work above.

**Recommendation:** Queue as a low-risk preprocessing experiment for a future V### bullet. Hypothesis: smoothing the existing high-frequency micro-signals (VPIN, Kyle, funding-rate delta) reduces meta-model overfitting and stabilises conviction scores. Concrete next step — in a future iteration, A/B test: identical V21x config but with `_apply_kalman(window=5)` wrapped around the high-noise sub-signals before they enter `_passes_conviction_filters`. Measure: regime-parity stability (current pain point) and Sharpe delta vs. baseline. Keep behind a feature flag; this is exactly the kind of change that the V49 hard gates were built to police. Do NOT merge into V21x mid-cycle.

---

## hftbacktest — full L2/L3 tick backtester with queue-position and latency simulation
**Source:** GitHub — https://github.com/nkaz001/hftbacktest
**Type:** repo
**Score:** 3/5 × 2/5 = 6/25 — Watch

**Summary:** Open-source Rust+Python framework (latest release Dec 2025) for HFT and market-making backtests. Reconstructs full L2/L3 book from tick feeds, models feed and order latencies, simulates queue position for realistic fills. Binance Futures + Bybit supported out of the box.

**Gap analysis:**
- Does Omega do this? **No.** Omega's backtest harness is bar-based; no queue-position or latency simulation. But Omega is not currently a market-making system — Victoria operates on conviction-filtered signal-driven entries, not passive resting orders.
- What would change: Only relevant if Omega were to add passive/maker strategies. Could become a reference for how to model fill realism if we ever simulate post-only entries.
- Dependencies: Rust toolchain (acceptable), exchange tick archives (geo-blocked Binance issue again).

**Recommendation:** Watch. Mismatched abstraction level for Omega's current strategy class. Revisit only if we decide to layer a passive-maker execution mode on top of the existing signal stack — at which point this would be a stronger candidate than building queue-position simulation from scratch.

---
*Generated by omega-twitter-feed-monitor scheduled task*
