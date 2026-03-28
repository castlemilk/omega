# AlphaEar / Awesome-Finance-Skills — Research Notes

*Source: RKiding/Awesome-finance-skills (GitHub), AlphaEar architecture docs*
*Compiled: 2026-03-28*

---

## 1. AlphaEar Architecture

AlphaEar is a four-layer intelligence pipeline for financial signal generation.
Each layer is a distinct processing stage; outputs flow top-to-bottom with
feedback loops at the boundary of Layer 3 → Layer 1.

```
┌────────────────────────────────────────────────────────┐
│  Layer 1 — Discovery                                   │
│  Raw data ingestion: news feeds, social media, filings │
│  SEC EDGAR, Bloomberg, Twitter/X, Reddit, earnings     │
│  → Unstructured text + time-series market data         │
├────────────────────────────────────────────────────────┤
│  Layer 2 — Analysis                                    │
│  NLP + statistical analysis of ingested data           │
│  FinBERT sentiment, named entity recognition,          │
│  event classification (M&A, earnings, macro)           │
│  → Structured feature vectors per asset                │
├────────────────────────────────────────────────────────┤
│  Layer 3 — Prediction                                  │
│  Time-series forecasting on feature vectors            │
│  Kronos foundation model + classical quant models      │
│  Ensemble: XGBoost / LightGBM + Kronos blending        │
│  → Probabilistic return forecasts + confidence bands   │
├────────────────────────────────────────────────────────┤
│  Layer 4 — Output                                      │
│  Portfolio construction + signal qualification         │
│  ISQ validation, risk overlay, position sizing         │
│  → Trade signals with confidence scores + reasoning    │
└────────────────────────────────────────────────────────┘
```

Feedback: Layer 4 performance (realized PnL, signal IC) feeds back into
Layer 2's weighting and Layer 3's ensemble blend weights.

---

## 2. The 8 Core Skill Modules

AlphaEar decomposes intelligence into eight reusable skill modules.
Each module is independently versionable and has a declared input/output schema.

| # | Module | Technique | Omega Mapping |
|---|--------|-----------|---------------|
| 1 | **SentimentAnalyzer** | FinBERT fine-tuned on financial text | `sentiment` signal (funding rate proxy) |
| 2 | **EventClassifier** | BERT NER + rule-based event ontology | `alt_data` signal (news + macro events) |
| 3 | **TimeSeriesForecaster** | Kronos foundation model + ARIMA fallback | `basic_signals` + momentum signals |
| 4 | **CrossAssetCorrelator** | Rolling Pearson / DCC-GARCH correlation | `cross_asset` signal |
| 5 | **RegimeDetector** | HMM + Wasserstein distance regimes | `vrp` + Wasserstein regime detector |
| 6 | **RiskOverlay** | VaR + Kelly sizing + drawdown constraints | `RiskManagementNode` |
| 7 | **SignalQualifier** | ISQ template — data freshness, consistency | `ISQValidator` in `node_skills.py` |
| 8 | **PortfolioConstructor** | Mean-variance + Black-Litterman blending | `StrategyNode` |

---

## 3. Kronos Foundation Model for Time-Series

**What it is:** Kronos is Amazon's zero-shot time-series foundation model (2024).
Trained on a large corpus of time-series data across multiple domains, it
generates probabilistic forecasts without per-dataset fine-tuning.

**Key properties:**
- Zero-shot: no training data required from the target asset
- Probabilistic: outputs full predictive distributions (10th, 50th, 90th percentile)
- Context window: up to 4096 time steps
- Architectures: T5-based (encoder-decoder), trained on 27.5M time series

**AlphaEar usage:**
1. Kronos produces 5-day return forecasts for each asset in the universe.
2. A calibration layer corrects for domain shift (crypto vs. training distribution).
3. Forecasts are blended with classical signals (XGBoost on technical features)
   using a learned convex combination (updated weekly by backtest).

**Omega mapping:**
- Kronos is not yet implemented in Omega (no Python dependency).
- The `basic_signals` node (SMA/RSI/MACD) plays the role of the classical
  fallback component.
- A Kronos integration would slot into `SignalGenerationNode` as a new
  `skill_version="2.0.0"` of the `basic_signals` skill.

---

## 4. FinBERT for Sentiment

**What it is:** FinBERT (ProsusAI, 2019) is BERT fine-tuned on financial text
from Reuters and Bloomberg news. It classifies text as Positive / Neutral / Negative
with a calibrated confidence score.

**AlphaEar usage:**
1. Layer 1 pulls news headlines and social posts (Twitter/X, Reddit WSB/crypto).
2. FinBERT scores each document: `{positive: 0.72, neutral: 0.18, negative: 0.10}`.
3. Aggregation: exponentially-weighted average over a 4-hour sliding window.
4. The resulting sentiment score is a feature in Layer 3 forecasting.

**Key finding (from AlphaEar benchmarks):**
- FinBERT sentiment leads price by 2–4 hours in crypto markets.
- IC degrades sharply beyond 6 hours → only use for intraday signals.
- Negative sentiment has higher predictive power than positive (fear > greed asymmetry).

**Omega mapping:**
- `SentimentSignal` (`omega/nodes/victoria/signals_advanced.py`) uses
  funding rate as a proxy for sentiment (direct FinBERT is not wired in).
- The `sentiment` NodeSkill declares `model="FinBERT / funding-rate proxy"`.
- A direct FinBERT integration would require a huggingface or newsapi pipeline;
  the `alt_data` node can serve as the hook for this upgrade.

---

## 5. News-Projection Layer Pattern

AlphaEar introduces a **news-projection layer** between Layer 1 and Layer 2:

```
Raw News → [FinBERT] → Sentiment Score
         → [Event Classifier] → Event Type + Magnitude
         → [Named Entity Recognition] → Asset Mentions
         → [News Projector] → Per-Asset Feature Vector
```

The News Projector maps raw NLP outputs into asset-specific feature vectors:
- It knows which assets are mentioned and weights news by mention frequency.
- It applies a time-decay kernel (half-life: 2 hours for crypto, 24h for equities).
- Cross-asset news projection: news about BTC affects ETH/SOL features with a
  correlation-weighted decay.

**Implementation pattern (pseudo-code):**
```python
def project_news(news_items, asset_universe, correlation_matrix):
    features = {asset: [] for asset in asset_universe}
    for item in news_items:
        sentiment = finbert.classify(item.text)
        mentions = ner.extract_assets(item.text)
        age_weight = exp(-item.age_hours / half_life)
        for asset in mentions:
            features[asset].append(sentiment * age_weight)
        # Cross-asset propagation
        for mentioned in mentions:
            for related in asset_universe:
                corr = correlation_matrix[mentioned][related]
                if corr > 0.5:
                    features[related].append(sentiment * age_weight * corr * 0.3)
    return {a: mean(v) for a, v in features.items() if v}
```

**Omega mapping:**
- `alt_data` + `news_signals` nodes partially implement this pattern.
- The cross-asset propagation step maps to `CrossAssetSignal`.
- Full news-projection requires wiring NewsAPI → FinBERT → `cross_asset` conditioning.

---

## 6. Mapping to Omega's Node Architecture

The AlphaEar 4-layer model maps cleanly onto Omega's existing node hierarchy:

```
AlphaEar Layer         Omega Component
──────────────────────────────────────────────────────────
Layer 1: Discovery   → DataIngestionNode (Binance/CoinGecko/Bybit)
                       AltDataSignalProvider (NewsAPI/OpenMeteo)
Layer 2: Analysis    → SignalGenerationNode (technical)
                       SentimentSignal, OrderFlowSignal, OnChainSignal
                       CrossAssetSignal, MicrostructureSignal
Layer 3: Prediction  → DynamicWeightAllocator (IC-EMA weighting)
                       WassersteinRegimeDetector, RMTDenoiser
                       CrossSectionalMomentumSignal, CarrySignal
Layer 4: Output      → StrategyNode (portfolio construction)
                       RiskManagementNode (debate gate + VaR)
                       ISQValidator (signal qualification)
```

### What AlphaEar has that Omega lacks

| AlphaEar Feature | Priority | Omega Gap |
|------------------|----------|-----------|
| Kronos foundation model | Medium | Only classical TA; no zero-shot forecasting |
| FinBERT direct integration | Medium | Funding-rate proxy only |
| News-projection cross-asset | Low | partial (alt_data) |
| Signal lifecycle tracking | ✅ ADDED | `SignalEvolutionTracker` in node_skills.py |
| ISQ qualification | ✅ ADDED | `ISQValidator` in node_skills.py |
| Per-node skill registry | ✅ ADDED | `SkillRegistry` in node_skills.py |
| Per-node RAG context | ✅ ADDED | `NodeRAGContext` (BM25 + cosine) |

---

## 7. Implementation — `omega/core/node_skills.py`

The `node_skills.py` module implements AlphaEar-inspired intelligence for
each Victoria node. See the module docstring for full API reference.

### Key classes

```python
# 1. Skill Registry
NodeSkill(name, description, model, confidence_score, skill_version)
SkillRegistry.register(skill)
SkillRegistry.record_execution(name, success)  # EMA confidence update

# 2. Signal Evolution Tracker
SignalLifecycle: EMERGING → STRENGTHENING → STABLE → WEAKENING → FALSIFIED
SignalEvolutionTracker.observe_many({"sentiment": 0.3, "momentum": -0.1})

# 3. ISQ Validation
ISQTemplate(node_name, data_freshness_max_seconds, consistency_threshold, ...)
ISQValidator.qualify(signals, market_data, context) → ISQResult

# 4. RAG Context
NodeRAGContext.record_episode(content, score)
NodeRAGContext.add_knowledge(text, source)
NodeRAGContext.retrieve(query, top_k=5)  # BM25 ranked

# 5. Facade
NodeSkillFramework(node_name, isq_template)
framework.register_skill(skill)
framework.observe_signals(signals) → {name: SignalLifecycle}
framework.qualify(signals, market_data) → ISQResult
framework.record_cycle(signals, result, score)
framework.get_metrics() → dict[str, float]
```

### Victoria wiring

`VictoriaNode.__init__` creates a `NodeSkillFramework` with the
`victoria_isq_template()` and registers all 16 `victoria_skills()`.

On every `_do_compute_signals` cycle:
1. `observe_signals(signals)` → updates lifecycle states → stored as `_skill_states`
2. `qualify(signals, market_data, context)` → ISQ score → stored as `_isq_score` / `_isq_passed`
3. `record_cycle(signals, result, score)` → adds to RAG context
4. `get_metrics()` → emitted in `evaluate()` for orchestrator / Prometheus

### Signal lifecycle metrics

`_skill_states` in the signals dict shows the lifecycle state of each signal:
```json
{
  "_skill_states": {
    "sentiment": "STRENGTHENING",
    "momentum_factor": "STABLE",
    "onchain": "EMERGING",
    "pairs": "WEAKENING"
  }
}
```

### ISQ score interpretation

| Score Range | Meaning |
|-------------|---------|
| 0.80 – 1.00 | High confidence — all checks pass, fresh data, consistent signals |
| 0.60 – 0.79 | Good — minor concerns, proceed with normal position sizing |
| 0.40 – 0.59 | Moderate — concerns present, consider reduced sizing |
| < 0.40      | Low — ISQ FAIL, flag output as low-confidence, widen risk limits |

Default `qualification_threshold` for VictoriaNode: **0.40**
(conservative given crypto signal noise floor).

---

## 8. Future Work

1. **Kronos integration** — wrap `chronos-forecasting` (pip package) as a
   `NodeSkill(model="Kronos-T5-Small")` inside `SignalGenerationNode`.
   Requires `torch` + `transformers` dependencies.

2. **Live FinBERT** — replace funding-rate proxy in `SentimentSignal` with
   actual FinBERT inference on NewsAPI + Twitter/X feed.
   Candidate model: `ProsusAI/finbert` from HuggingFace Hub.

3. **RAG knowledge seeding** — pre-populate `NodeRAGContext._knowledge` with
   domain research (e.g. Jegadeesh-Titman 1993, VRP crypto literature).
   Hook: `framework.rag.add_knowledge(text, source="jt1993")` at startup.

4. **ISQ persistence** — write `ISQResult` history to a `victoria_isq_log`
   Postgres table for longitudinal analysis of signal qualification drift.

5. **Skill version tracking** — when `improve()` bumps a signal's IC weight
   significantly, auto-increment `NodeSkill.skill_version` and log the change.
