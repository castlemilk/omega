# Omega Research Feed — 2026-04-30

## Items Reviewed
3 items. Twitter searches for @browomo, @zostaff, @hanakoxbt, @0xricker, @adiix_official, @data_sn13 returned no indexable recent posts (X/Twitter not exposed via WebSearch). Pivoted to recent arXiv crypto-quant literature as a stand-in research surface. Three papers reviewed.

---

## CryptoPulse: Short-Term Cryptocurrency Forecasting with Dual-Prediction and Cross-Correlated Market Indicators
**Source:** arXiv 2502.19349 — https://arxiv.org/abs/2502.19349
**Type:** paper
**Score:** 2/5 × 4/5 = 8/25 — Watch

**Summary:** Next-day close-price forecasting that fuses macro signals, technical indicators (Stochastic %K/%D, Williams %R, A/D, momentum, ROC, disparity-7), and news-derived sentiment via a dual-prediction + sentiment-rescaling refinement step. Claims to beat 10 baselines on multi-asset crypto.

**Gap analysis:**
- Does Omega do this? Partial. Omega already runs SMA/RSI/MACD/BB/ATR/OBV plus FinBERT sentiment and a meta-model ensemble. The specific indicators (Williams %R, A/D, disparity-7) and the sentiment-rescaling fusion step are not implemented.
- What would change: Add three indicators in `omega/nodes/victoria/signal_generation.py`; add a sentiment-rescale post-processor in the meta-model stage.
- Dependencies: None new — sentiment pipeline already exists.

**Recommendation:** Skip-tier add. The novel piece is the rescaling fusion, but Omega's logistic-ensemble meta-model already learns sentiment weights. Implementing more TA primitives buys little marginal Sharpe. Park unless we see a regime where current sentiment weight is provably mis-scaled.

---

## Deep Learning Models Meet Financial Data Modalities (LOB-as-image)
**Source:** arXiv 2504.13521 — https://arxiv.org/abs/2504.13521
**Type:** paper
**Score:** 4/5 × 2/5 = 8/25 — Watch (strategic)

**Summary:** Treats sequential limit-order-book snapshots as multi-channel image inputs and combines with candles, order statistics, traded volume, and news flow. Reports SOTA on HFT-style benchmarks via this LOB-embedding approach.

**Gap analysis:**
- Does Omega do this? No. Memory file flags "no order book/L2" as a known gap. Omega is poll-only over 5–15 min bars; no L2 ingest, no microstructure features.
- What would change: New project node (e.g. `omega/nodes/microstructure/`) for L2 stream ingest + LOB-image encoder; new signal channel piped into meta-model.
- Dependencies: WebSocket L2 feeds (Coinbase + Kraken work from US), per-symbol storage tier (parquet/Arrow), GPU for the CNN encoder, and a new streaming subsystem in Go (current architecture is all polling).

**Recommendation:** Queue as a strategic capability, not an immediate implementation. Closing the L2 gap unlocks an entire microstructure signal class (queue imbalance, cancellation rate, trade-flow toxicity) that Omega cannot currently express. But the prerequisite — a streaming ingest layer — is a multi-week Go effort and shifts the platform model. Worth a one-page design doc before committing; revisit after the streaming-vs-polling decision lands.

---

## Reinforcement Learning-Based Cryptocurrency Portfolio Management (SAC/DDPG)
**Source:** arXiv 2511.20678 — https://arxiv.org/abs/2511.20678
**Type:** paper
**Score:** 4/5 × 3/5 = 12/25 — Queue

**Summary:** Compares SAC vs DDPG for continuous-action crypto portfolio allocation. SAC wins on stability/robustness in noisy markets thanks to its entropy-regularised objective. Both beat equal-weight and mean-variance baselines on cumulative return net of transaction costs.

**Gap analysis:**
- Does Omega do this? No. Memory file flags "no RL agent" as a known gap. Current sizing is Kelly + conviction-filter + regime-adaptive thresholds — all rules-based.
- What would change: New allocator node sitting above the existing signal stack (signals stay as feature inputs to the RL state vector). Replaces or augments the conviction-filter sizing in `strategy.py`.
- Dependencies: stable-baselines3 or CleanRL (SAC); a Gym-style env wrapper around Victoria's existing backtest harness; reward design (Sharpe-on-window vs DSR vs differential Sharpe). Training data: existing trade log + cycle metrics in `/tmp/{version}_metrics.jsonl`.

**Recommendation:** Queue for a focused spike. The fit is unusually clean: Omega already has the feature pipeline, the backtest harness, and a per-cycle metrics log — the missing piece is an env wrapper and a SAC training loop, which is a few days of work, not weeks. Concrete next steps: (1) prototype `omega/nodes/victoria/rl_allocator.py` with a Gym env that replays training-version cycles; (2) state = current signals + position + regime probs + recent PnL; action = continuous allocation per symbol bounded by Kelly; reward = differential Sharpe minus tx cost; (3) train on V49 data, evaluate against V49 baseline using the existing v49_gates.py harness so the same six gates apply. If SAC clears all gates on a single training version, promote to a candidate version.

---
*Generated by omega-twitter-feed-monitor scheduled task*
