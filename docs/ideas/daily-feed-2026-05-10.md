# Omega Research Feed — 2026-05-10

## Items Reviewed
3 items reviewed from broader crypto-quant arXiv surface (Twitter handle searches @browomo, @zostaff, @hanakoxbt, @0xricker, @adiix_official, @data_sn13 returned no specific tweets via WebSearch — pivoted to surfaced arXiv papers from same query domain).

---

## Kalshi Prediction Markets Forecast Crypto Volatility (arXiv 2604.01431)
**Source:** surfaced via @data_sn13 query — https://arxiv.org/abs/2604.01431
**Type:** paper
**Score:** 5/5 × 4/5 = 20/25 — **Implement immediately**

**Summary:** Daily volume-weighted probability shifts in Kalshi macro markets (Fed rate KXFED, recession KXRECSSNBER, CPI KXCPI) predict 5-day-ahead realized volatility for BTC/ETH/SOL/ADA/LINK. Bitcoin-Fed (t=3.63) and Chainlink-CPI specs survive Benjamini-Hochberg multiple testing. Recession-risk signal is OOS-stable (MSFE=0.979, p=0.020); CPI repricing predicts altcoin vol (t = -2.1 to -3.4). Orthogonalised against Fed Funds futures, Treasury yields, and Deribit IV — i.e., adds info beyond existing macro/IV proxies.

**Gap analysis:**
- Does Omega do this? **No.** Omega has no prediction-market signals, no macro-rate channel, no recession proxy. Closest existing signal is Fear&Greed.
- What would change: New macro-channel signal node (`omega/nodes/victoria/kalshi_macro.py`) feeding regime detector + vol-regime + meta-model. Touches `signal_generation.py`, weights map, and Bayesian regime prior.
- Dependencies: Kalshi data (REST API, free historical event-prob endpoint or paid feed), daily polling fits existing scheduler — no streaming required. Symbol set already covers BTC/ETH/SOL/LINK in Omega.

**Recommendation:** Highest-priority candidate this cycle. Build a `kalshi_signal` node that pulls KXFED/KXRECSSNBER/KXCPI daily probability changes, orthogonalises against Treasury yields, and emits a per-symbol vol-forecast adjustment that the regime detector and meta-model can consume. Wire as a new sub-signal in the Victoria conviction stack with low initial weight (0.05) and let auto-tuning adjust. Validate by replicating paper's BTC-Fed and LINK-CPI specifications on Omega's training data before activating live. File targets: new `omega/nodes/victoria/kalshi_macro.py`, register in `signal_generation.py`, add to `meta_learner.py` feature vector, add `KALSHI_API_KEY` to env config.

---

## Walk-Forward Parameter Optimization with Double Out-of-Sample (arXiv 2602.10785)
**Source:** surfaced via @data_sn13 query — https://arxiv.org/abs/2602.10785
**Type:** paper + GitHub repo (github.com/tmr-crypto/wf_optim_crypto_analysis)
**Score:** 4/5 × 5/5 = 20/25 — **Implement immediately**

**Summary:** Treats training/testing window lengths as optimisation variables (1–28 days, 81 combinations) using Robust Sharpe Ratio, then validates only the top-2 configurations on truly held-out data — avoids the implicit overfitting in single-OOS walk-forward. Cross-asset validation (BTC→BNB/ETH transfer). Yields 50% drawdown reduction vs Buy-and-Hold when combined; profitable up to ~0.4% fees.

**Gap analysis:**
- Does Omega do this? **Partial.** Omega has TPE Bayesian optimisation and an overfitting gate, but window lengths themselves are not part of the search space — they're configured per-version. Single-OOS only.
- What would change: Extend `omega/eval/v49_gates.py` and the meta-harness param space to include training/testing window lengths; add a second held-out slice to gate evaluation.
- Dependencies: None new — fits existing TPE+gate pipeline. Mostly config + a second data split.

**Recommendation:** Direct upgrade to the training pipeline. Add `train_window_days` and `test_window_days` to TPE search space (range 7–28). Split the training corpus into three regions: optimisation, OOS-1 (model selection), OOS-2 (gate). Promote a version only if it passes gates on OOS-2 — not on OOS-1, which already saw the top-K parameter set. This directly targets the existing `project_training_gaps.md` overfitting concern. File targets: `omega/eval/v49_gates.py`, `scripts/run_training.py` (split logic), TPE config under `omega/optimization/`.

---

## Probabilistic / Quantile Crypto Volatility Forecasting (arXiv 2508.15922, DSAA'25)
**Source:** surfaced via @data_sn13 query — https://arxiv.org/abs/2508.15922
**Type:** paper
**Score:** 3/5 × 4/5 = 12/25 — **Queue**

**Summary:** Converts point volatility forecasts into conditional quantile estimates using Quantile Estimation through Residual Simulation (QRS). Surprising result: QRS on linear models with log-transformed RV beats LSTM/RF/MLP. Probabilistic stacking provides robust uncertainty estimates. Models tested: HAR, GARCH, ARFIMA + LASSO/SVR/MLP/RF/LSTM.

**Gap analysis:**
- Does Omega do this? **No.** Omega has Brier calibration on direction, but no quantile vol forecasts — vol is a point estimate from `vol_regime` and ATR.
- What would change: Replace/augment `vol_regime` to emit conditional quantiles (e.g. 0.1/0.5/0.9). Kelly sizing and exit_controller could consume quantiles instead of point estimates for tail-aware sizing.
- Dependencies: HAR/ARFIMA implementation (statsmodels), QRS residual sim — pure Python, fits existing signal layer.

**Recommendation:** Queue behind Kalshi + walk-forward upgrade. The compelling angle is the "linear-models-win" finding which means low implementation cost and high interpretability, and quantile vol would let `exit_controller.py` do tail-aware stop placement (high p90 → wider stop) and `strategy.py` Kelly do downside-aware sizing. Worth a small spike: add HAR-RV with QRS as a sibling to `vol_regime` and check whether p90/p10 spreads correlate with subsequent stop-out events on training data. If yes, promote to live.

---

*Generated by omega-twitter-feed-monitor scheduled task*
