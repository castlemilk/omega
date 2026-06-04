# Omega Research Feed — 2026-05-18

## Items Reviewed
3 items from accounts checked: @browomo, @zostaff, @hanakoxbt, @0xricker, @adiix_official, @data_sn13.
Most account-handle searches returned generic/promotional results; substantive items came from arXiv references surfaced via the @zostaff prediction-markets thread and related crypto-quant searches. The @zostaff tweet itself (status/2031100908185018664) could not be fetched directly (HTTP 402 from x.com) — only the snippet from search index was usable.

---

## Microstructural Dynamics in Crypto LOBs — "Better Inputs Matter More Than Stacking Another Hidden Layer"
**Source:** arXiv 2506.05764 (surfaced via crypto-quant search; topic adjacent to @browomo / @data_sn13 focus areas) — https://arxiv.org/abs/2506.05764
**Type:** paper
**Score:** 4/5 × 2/5 = 8/25 — Watch

**Summary:** Benchmarks logistic regression, XGBoost, DeepLOB, and Conv1D+LSTM on BTC/USDT Bybit LOB snapshots (100ms–multi-sec) using Kalman + Savitzky-Golay filtered inputs. Headline finding: with proper preprocessing, simpler models match or beat deep architectures on out-of-sample directional accuracy with far lower inference latency. Validates a "filter the inputs, don't deepen the net" thesis.

**Gap analysis:**
- Does Omega do this? **No.** Omega has 16+ signals but zero L2/order-book ingestion (documented gap in `project_omega.md`). All current signals are derived from candle/tick data via CoinGecko/Coinbase/Kraken polling.
- What would change: New `omega/nodes/victoria/lob_*.py` signal layer + an LOB ingestion path in the Python bridge (or Go streaming layer). Would also introduce Kalman/Savitzky-Golay preprocessing utilities reusable elsewhere.
- Dependencies: Streaming WS connection to Coinbase/Kraken L2 (Bybit blocked geo); buffered snapshot store; new feature extractor; offline labeling pipeline.

**Recommendation:** Watch — high impact but infrastructure cost is large (we have no streaming layer, all polling). If/when the streaming initiative is started, this paper is the right starting blueprint: implement Kalman + S-G filters first, get a logistic + XGBoost baseline before ever touching DeepLOB. Don't chase architectures.

---

## Toward Black–Scholes for Prediction Markets: A Unified Kernel and Market-Maker's Handbook
**Source:** arXiv 2510.15205 (directly relevant to @zostaff's "trade the divergence between price and the model" prediction-market thread) — https://arxiv.org/html/2510.15205v1
**Type:** paper
**Score:** 4/5 × 3/5 = 12/25 — Queue

**Summary:** Derives a logit-space jump-diffusion pricing kernel for event contracts (Polymarket-style). Maps `p_t → x_t = log(p/(1-p))`, models dx with risk-neutral drift + belief vol σ_b + jump term, and pins drift via martingale constraint. Produces a calibration pipeline (Kalman + EM separates diffusion vs jumps, builds σ_b(τ, m) surface) and an Avellaneda-Stoikov market-making formula in logit space.

**Gap analysis:**
- Does Omega do this? **Partial.** `omega/nodes/polymarket/` exists (per repo structure) but per `project_omega.md` Omega has no IV-surface / no derivatives-pricing kernel for events. Current polymarket usage is signal-only, not a structured pricing model.
- What would change: New `omega/nodes/polymarket/pricing_kernel.py` for logit transform + σ_b surface; calibration via existing Kalman utilities; new signal = (market p) − (model implied p) in logit space (i.e. divergence-from-model — the exact framing @zostaff highlighted).
- Dependencies: Polymarket bid/ask/trade tape (not just last price); resolution-time calendar; scheduled-announcement metadata. No new heavy compute — closed-form formulas + standard filters.

**Recommendation:** Queue (score 12). Concrete next steps: (1) audit current `omega/nodes/polymarket/` for what data it already pulls; (2) prototype the logit-space divergence signal in isolation — `divergence_i = logit(p_market) − logit(p_model)` against any of Omega's existing probabilistic outputs (HMM regime probs are natural candidates); (3) if signal shows promise, build the full σ_b calibration. This is the highest-leverage idea today because it cleanly extends an existing project node and matches an explicit named gap ("no LLM-native / no options-IV-surface"). Worth a forensics-style A/B once prototyped.

---

## Explainable Patterns in Cryptocurrency Microstructure (CatBoost + GMADL + SHAP)
**Source:** arXiv 2602.00776 (cross-asset universality study, found alongside the LOB paper) — https://arxiv.org/html/2602.00776v1
**Type:** paper
**Score:** 3/5 × 5/5 = 15/25 — Queue (drop-in subset)

**Summary:** Trains CatBoost on relative microstructure features across BTC/LTC/ETC/ENJ/ROSE, using the **Generalized Mean Absolute Directional Loss (GMADL)** — a direction-aware loss emphasizing sign correctness over MSE. Walk-forward CV with purging. SHAP shows order-flow imbalance, bid-ask spread, and VWAP-to-mid deviations dominate across all caps. Taker execution profitable on mid/long-tail with p<0.05, including through Oct-10-2025 flash crash; maker execution destroyed by adverse selection.

**Gap analysis:**
- Does Omega do this? **Partial.** Omega already has gradient-boosted ensembling and SHAP-style explainability (`meta_learner.py`). The drop-in piece is **GMADL as a loss function** — Omega's meta-model is logistic ensemble, not direction-aware-loss-trained. The microstructure features (OFI, spread, VWAP-mid) require L2 data we don't have (see paper #1).
- What would change: `omega/nodes/victoria/meta_learner.py` — add GMADL as an optional training objective alongside log-loss; expose it as a config flag for the next training run (`v149` or later). Walk-forward purging is already done in `omega/eval/v49_gates.py`-adjacent pipeline.
- Dependencies: None for the GMADL retrofit — pure Python, uses existing data. The microstructure-feature half is gated on the same LOB-streaming infra as paper #1.

**Recommendation:** Queue (score 15 for the loss-function retrofit alone). Concrete next steps: (1) implement GMADL in `omega/eval/` as a sklearn-compatible scorer; (2) wire it into `meta_learner.py` as `--loss=gmadl` option; (3) run V149 training with `--loss=gmadl` vs baseline log-loss, compare via the standard forensics tool (`omega.tools.forensics.run_diff`) — gate on PnL floor, regime parity, win-rate. If win-rate or Sharpe improves without regime regression, promote to default. This is the cheapest-to-test high-impact item in today's feed.

---
*Generated by omega-twitter-feed-monitor scheduled task*
