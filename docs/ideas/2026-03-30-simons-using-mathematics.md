# Jim Simons — "Using Mathematics to Make Money" (SSRN #4668072)

**Source**: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4668072
**Date added**: 2026-03-30

---

## Three Pillars of RenTec's Approach

1. **Iterative model development** — Models are never "done." RenTec runs continuous improvement loops: backtest → deploy → measure → refine. No single grand theory; thousands of small signals composited together. Each signal adds a marginal edge; the aggregate is the moat.

2. **Scientists over finance people** — Hire mathematicians, physicists, and statisticians with zero finance background. Finance training introduces biases and false priors. Raw pattern-finding ability matters more than domain knowledge. The best researchers don't know what "should" work.

3. **Shared model architecture** — All researchers work on the same unified model. No siloed strategies. Every discovered signal feeds the same composite. This creates a compounding effect: each new researcher's work benefits from and contributes to the entire signal library.

---

## RenTec Techniques (inferred from Simons' public talks + paper)

| Technique | Description |
|-----------|-------------|
| **Statistical arbitrage** | Mean reversion on correlated instrument pairs; exploit transient mispricings at high frequency |
| **Hidden Markov Models (HMM)** | Regime detection and sequence modeling; latent state inference over price/volume time series |
| **Kernel methods** | Non-parametric classification and regression (SVM, kernel regression) on financial features |
| **Neural networks** | Pattern recognition in raw price/microstructure data; used alongside classical methods |
| **Signal processing (Fourier/wavelet)** | Spectral decomposition of price series; wavelet transforms for multi-scale feature extraction |
| **Stochastic calculus** | Rigorous modeling of continuous-time processes; underpins options pricing and risk models |
| **Massive data ingestion** | Everything: tick data, weather, satellite, shipping, sentiment — raw ingestion before hypothesis formation |
| **Full automation** | Zero human discretion in execution; model fires, position is taken. Human role is research only. |

---

## Gap Analysis vs. Omega

### What We HAVE

| Component | Omega Implementation |
|-----------|---------------------|
| Regime detection | `wasserstein_regime.py` — Wasserstein distance-based distributional shift detection |
| Spectral methods | `spectral_signals.py` — spectral graph theory signals on asset correlation networks |
| Neural gradient optimizer | `natural_gradient.py` — natural gradient descent for signal weight optimization |
| DAG pipeline | `dag_pipeline.py` — directed acyclic graph execution engine for signal composition |
| Attention router | `coordination/attention_router.go` — Go-side attention-weighted signal routing |
| Full automation | `omega run` stack — Victoria runs fully automated end-to-end |

### What We're MISSING

#### 1. Hidden Markov Model Regime Detector
- **Gap**: Wasserstein detects distributional shift but doesn't model latent regime *sequences* with transition probabilities. HMM gives you: "we are in regime X with 87% confidence, and there's a 12% chance we transition to regime Y next period."
- **Add**: `omega/nodes/victoria/hmm_regime.py` — standalone HMM alongside Wasserstein. Feed both into the meta-model. Let disagreement between them become a signal itself (regime uncertainty).
- **Library**: `hmmlearn` or `pomegranate`

#### 2. Wavelet Transform Signal Decomposition
- **Gap**: Fourier/FFT gives frequency content but assumes stationarity. Financial data is non-stationary. Wavelets decompose signals across both time and frequency simultaneously — critical for detecting transient patterns (momentum at different timescales).
- **Add**: `omega/nodes/victoria/wavelet_signals.py` — continuous wavelet transform (CWT) on price/volume. Extract energy at each scale as features. Feed into existing factor model.
- **Library**: `PyWavelets (pywt)`

#### 3. Feature Discovery Engine
- **Gap**: All current signals are hypothesis-driven ("I think momentum matters → write momentum signal"). RenTec's edge comes partly from exhaustive search over raw microstructure data with no prior hypothesis. We don't have a systematic scan of raw feature interactions.
- **Add**: `omega/nodes/victoria/feature_discovery.py` — systematic scan engine. Given raw OHLCV + microstructure data, auto-generate candidate features (lagged ratios, cross-asset spreads, rolling statistics), run significance tests, score by IC (information coefficient) and add to signal library if they pass.
- **Note**: Requires careful overfitting controls — Bonferroni correction or walk-forward IS/OOS split before any feature graduates to production.

---

## Action Items for Backlog

- [ ] **BACKLOG**: Implement `hmm_regime.py` — 3-state HMM (bull/bear/transition) using Gaussian emissions on returns + volume. Run in parallel with Wasserstein detector. Expose regime uncertainty as a meta-signal.
- [ ] **BACKLOG**: Implement `wavelet_signals.py` — CWT decomposition on BTC/ETH price. Extract per-scale energy features (1h, 4h, 1d, 1w timescales). Add wavelet momentum (energy shift across scales) as a signal.
- [ ] **BACKLOG**: Implement `feature_discovery.py` — automated feature scan with IC scoring, IS/OOS gating, and auto-registration of surviving signals into the signal library.
- [ ] **RESEARCH**: Read Simons' original paper (SSRN #4668072) for specific algorithmic details on ensemble combination — may inform our meta-model weighting.
- [ ] **DESIGN**: Consider shared model constraint: all researchers (nodes) contribute to the same composite model rather than per-node private weights. Currently Victoria nodes have some private state — evaluate consolidation.
