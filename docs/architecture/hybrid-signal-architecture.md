# Hybrid Signal Architecture: LLM + Math + Data

**Status**: Design (V139+ territory) — Phase 1 implementation complete  
**Date**: 2026-04-17  
**Scope**: Victoria node signal pipeline augmentation

---

## 1. Overview: LLM-as-Analyst Pattern

The core insight is that LLMs and quant systems have complementary failure modes:

| Quant system | LLM analyst |
|---|---|
| Optimal for: statistical patterns, regime signals, cross-asset correlations | Optimal for: qualitative reasoning, news synthesis, macro narrative |
| Fails on: structural regime breaks, black swans, narrative-driven markets | Fails on: precise quantification, overfitting risk, hallucination |
| Latency: microseconds | Latency: 1–3 seconds |
| Cost: fixed compute | Cost: per-token API |

**Design principle**: The LLM acts as a **conviction modifier**, not a decision-maker. It returns a scalar `conviction_modifier ∈ [0.0, 1.5]` that scales the IC-weighted composite before threshold comparison. The quant system retains full veto authority.

```
signals → IC-weighted composite → × conviction_modifier → threshold gate → trade/pass
                                         ↑
                                    LLM analyst
                                    (0.0–1.5 scale)
```

This architecture guarantees:
1. The quant signal floor is preserved (LLM can dampen, never override to +inf)
2. Backtest determinism via SHA256-keyed file cache
3. Graceful degradation: any API failure → `modifier=1.0` (no effect)

---

## 2. Math + LLM Synergy

### Where math wins

The existing Victoria pipeline already captures:
- **Geometric alpha**: Ricci curvature, Fiedler eigenvalue, ORC stress (market manifold topology)
- **Microstructure**: VPIN, book depth velocity, whale prints
- **Cross-regime**: bear_prob / bull_prob from ensemble (BTC+ETH+market regime)
- **Temporal memory**: conviction_trend, momentum_derivative, regime_duration

These signals are numerically precise, backtestable, and capture intra-day structure that LLMs cannot perceive from text.

### Where LLM adds value

1. **Macro regime breaks**: A sudden Fed pivot, banking contagion, or regulatory announcement creates a structural shift. Quant signals adapt slowly (EMA decay); LLMs can act on the narrative immediately.

2. **Sanctions / geopolitical tail risk**: GDELT provides article counts; LLM provides *interpretation* (is this noise or a genuine supply-chain threat to crypto infrastructure?).

3. **Cross-market correlation shifts**: LLM can reason about why BTC-NASDAQ correlation might change regime (e.g., ETF flows changing the investor base) before the 50-cycle rolling correlation detects it.

4. **False positive dampening**: When all signals are borderline-positive but the macro narrative is clearly bearish, the LLM can suppress the modifier below 1.0.

### Interaction design

The LLM sees:
- Ticker, proposal (LONG/SHORT/FLAT), regime, bear/bull probabilities
- Top 6 signals by absolute value (not the full 40+ signal vector)
- Quant composite score

The LLM does NOT see:
- Raw price data (avoids hallucination on exact price levels)
- Portfolio state (avoids position-aware bias)
- Previous modifier values (avoids autocorrelation)

---

## 3. Implementation Phases

### Phase 1 (V139) — conviction_modifier only ✅

`omega/nodes/victoria/signals/llm_analyst.py`

- `LLMAnalystSignal.compute()` → `LLMAnalystResult(conviction_modifier, reasoning, confidence)`
- Modifier applied: `adjusted_composite = composite * modifier` before threshold gate
- Cache: `data/cache/llm_analyst/{sha256_16}.json` (input-hash keyed, no TTL)
- Cycle gate: call every `llm_analyst_call_every_n` cycles (default 10); reuse last modifier between calls
- Model: `claude-haiku-4-5-20251001` (low latency, low cost)
- Parsed but not applied: `regime_override`, `signal_adjustments`

**Wire-in point** (to be added in V139 strategy.py):
```python
if self.features.llm_analyst_enabled and _cycle % self.features.llm_analyst_call_every_n == 0:
    _llm = _llm_analyst.compute(ticker, regime, composite, proposal, signals, ...)
    composite = composite * _llm.conviction_modifier
```

### Phase 2 (V140) — regime context injection

Add structured macro context to the LLM prompt:
- `geopolitical_signals` output (geo_event_intensity, geo_sentiment)
- On-chain metrics summary (exchange flows, stablecoin velocity)
- Recent news headlines (GDELT article titles, not full text)

Expected lift: better modifier accuracy during geopolitical events. Requires geopolitical_signals to be backtest-safe (timestamp-gated replay).

### Phase 3 (V141) — signal_adjustments application

The LLM already returns `signal_adjustments: dict[str, float]` but Phase 1 ignores it.  
Phase 3 applies bounded per-signal multipliers:

```python
adjusted_signals = {
    k: v * max(0.5, min(2.0, signal_adjustments.get(k, 1.0)))
    for k, v in signals.items()
}
```

Risk: signal_adjustments are LLM hallucinations on specific signal names. Requires validation that returned keys exist in the signal dict.

### Phase 4 (V142) — ensemble LLM committee

Run 2–3 calls with different system prompts (bull-biased analyst, bear-biased analyst, neutral analyst) and take the median modifier. Reduces hallucination variance at 3× token cost.

---

## 4. Data Fusion Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Victoria signal pipeline                      │
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │ Math signals │   │  Data signals│   │  LLM analyst         │ │
│  │              │   │              │   │                      │ │
│  │ • Ricci/ORC  │   │ • GDELT geo  │   │ Input:               │ │
│  │ • VPIN       │   │ • Whale flow │   │   top-6 signals      │ │
│  │ • Momentum   │   │ • Funding    │   │   composite score    │ │
│  │ • Regime     │   │ • Fear&Greed │   │   regime context     │ │
│  └──────┬───────┘   └──────┬───────┘   │                      │ │
│         │                  │           │ Output:               │ │
│         └──────────────────┤           │   conviction_modifier │ │
│                            ▼           │   reasoning (text)    │ │
│                    ┌───────────────┐   └──────────┬───────────┘ │
│                    │ IC-weighted   │              │             │ │
│                    │ composite     │◄─────────────┘             │ │
│                    └──────┬────────┘  (× modifier)             │ │
│                           ▼                                     │ │
│                    ┌───────────────┐                            │ │
│                    │ AND-gate      │                            │ │
│                    │ (4-factor)    │                            │ │
│                    └──────┬────────┘                            │ │
│                           ▼                                     │ │
│                    ┌───────────────┐                            │ │
│                    │ Trade/Pass    │                            │ │
│                    └───────────────┘                            │ │
└─────────────────────────────────────────────────────────────────┘
```

### Cache architecture

```
data/cache/
├── gdelt/           # GDELT queries: 15-min TTL (live), immutable (historical)
│   └── {query}_{YYYYMMDD_HHmm}.json
└── llm_analyst/     # LLM calls: no TTL (input-hash keyed, deterministic)
    └── {sha256_16}.json
```

The SHA256 key includes `_model` so changing model versions invalidates old cache entries automatically.

---

## 5. Cost and Latency Analysis

### Phase 1 baseline (Haiku, every 10 cycles)

| Metric | Estimate | Notes |
|---|---|---|
| Tokens per call | ~350 in, ~50 out | Prompt + JSON response |
| Cost per call | ~$0.0002 | Haiku pricing |
| Calls per 500-cycle run (10 tickers) | 500 | 500 cycles ÷ 10 × 10 tickers |
| Total cost per run | ~$0.10 | Negligible |
| Latency per call | 1–3 seconds | Haiku is fast |
| Latency impact | ~0.2s/cycle | Amortized across 10-cycle gap |

The cycle-gate design (call every N cycles) makes latency irrelevant for backtesting — all calls are cached. In live mode, the 1–3s call is fire-and-forget: Victoria operates on a minutes-per-cycle cadence, so the LLM result is ready well before the next entry decision.

### Cache hit rates in backtest

In a 500-cycle backtest with 10 tickers, the same market snapshot repeats across identical signal states. Expected cache hit rate: 85–95% (most states recur). This means net API cost for a full 3-snapshot Phase A run is < $0.50.

---

## 6. Backtest Challenge: Determinism and Temporal Contamination

The primary risk with LLM signals in backtesting is **temporal leakage**: the model's training data includes post-hoc information about the period being backtested.

### Mitigation approach

1. **Input-hash cache**: For any given set of inputs, the same modifier is returned deterministically. This prevents cycle-to-cycle variance from model non-determinism.

2. **No real-time market data in prompt**: The LLM only sees signal values already computed by the quant system. It cannot query current prices or news.

3. **Temperature = 0 equivalent**: The structured JSON response format and caching together achieve deterministic behavior across runs.

### Residual risk

The LLM model was trained on data through August 2025. Backtesting against H1-2022 (crisis snapshot) means the model has seen what happened during that period. This creates **look-ahead bias**: the model may correctly predict bear market outcomes because it "remembers" the outcome, not because it has genuine analytical skill.

**Accepted limitation for Phase 1**: The conviction_modifier is bounded to [0.0, 1.5] and the quant composite remains the primary decision variable. Even with look-ahead bias, the LLM's influence is capped at 1.5× amplification. Phase A benchmarks will compare V139 vs V138.1 (no LLM) to measure lift attributable to LLM signals.

**Longer-term mitigation**: Use a model fine-tuned only on pre-backtest data, or restrict the LLM to processing only signals already computed by the quant system (no raw market data in prompt). Current Phase 1 implementation already follows this constraint.

---

## 7. Integration Checklist

- [x] `LLMAnalystSignal` class with cache, graceful degradation, urllib API client
- [x] `llm_analyst_enabled` and `llm_analyst_call_every_n` feature flags in `VictoriaFeatures`
- [ ] Wire into `strategy.py` before threshold gate (V139)
- [ ] Add `llm_modifier` field to `DecisionTrace` for observability
- [ ] Add `llm_analyst_signal` to `activation_traces` schema
- [ ] Phase A benchmark: V139 vs V138.1 (500 cycles × 3 snapshots)
- [ ] Gate check: V139 agg PnL ≥ V138.1 AND modifier IC > 0.05
