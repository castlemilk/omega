# Omega Research Feed — 2026-05-07 00:10

## Items Reviewed
3 items from accounts checked: @browomo (no results), @zostaff (active), @hanakoxbt (active), @0xricker (no results), @adiix_official (no results), @data_sn13 (no results). Twitter/X search returned little for most handles; supplemented with adjacent arXiv search to surface a paper @zostaff's recent Polymarket / prediction-market thread thematically aligns with.

---

## Do Prediction Markets Forecast Cryptocurrency Volatility? (Kalshi Macro Contracts)
**Source:** arXiv (Mohanty & Krishnamachari, USC) — https://arxiv.org/abs/2604.01431
**Type:** paper
**Score:** 4/5 × 4/5 = 16/25 — Queue

**Summary:** Constructs three macro signals from daily Kalshi event-contract probability changes — Fed rate repricing (KXFED), recession risk (KXRECSSNBER), CPI repricing (KXCPI) — and shows out-of-sample predictive power for BTC and altcoin volatility. BTC vol regression t-stat = 3.63 (p<0.001); altcoin OOS MSFE ratios 0.959 (ETH) / 0.979 (BTC via recession signal). Signals carry information beyond Fed Funds futures, Treasury yields, and Deribit IV. Sample: Jan 2023 – Mar 2026, 10 Kalshi series × 6 crypto assets.

**Gap analysis:**
- Does Omega do this? No. Omega's macro layer is Fear&Greed + funding + DeFi TVL; no prediction-market ingestion.
- What would change: New signal node `omega/nodes/victoria/prediction_market_macro.py` producing daily KXFED/KXCPI/KXRECSSNBER probability deltas; surfaces as features into `vol-regime` and `signal_generation` ensemble (likely as a vol-forecast adjuster rather than direction signal).
- Dependencies: Kalshi public data API (CSV history is free, real-time via authenticated API). Daily cadence fits Omega's polling model. Series IDs hard-coded; no streaming infra needed. Add Brier-calibration step before feeding into composite (existing infra).

**Recommendation:** Queue for V150-era work. Concrete next steps: (1) prototype `scripts/fetch_kalshi_history.py` pulling KXFED/KXCPI/KXRECSSNBER daily settlements; (2) replicate paper's daily-Δprob signal and run univariate regression on BTC realized vol from `data/training_version.txt` cohort; (3) if t-stat > 2 on our window, wire into `confidence_surface.py` as a vol-regime conditioner (not a directional signal — paper's evidence is on volatility, not return). Authors cite `Clark-West` and Benjamini-Hochberg corrections — port as gates in `omega/eval/v49_gates.py`. Risk: regime-conditional — most of paper's signal lives in monetary-policy windows (Fed meetings, CPI prints); may be quiet otherwise. Validate by cross-referencing Omega's `crisis`/`high_vol` regime labels against paper's high-information windows.

---

## @zostaff — AI weather trading bot for Polymarket
**Source:** @zostaff — https://x.com/zostaff/status/2049202919732293995
**Type:** tweet (thread, full content paywalled in fetch)
**Score:** 3/5 × 2/5 = 6/25 — Watch

**Summary:** Self-reported: weather-data → Polymarket weather-event-contracts trading bot. 240-day backtest, Sharpe +1.09, win rate 23.8% on markets where random ≈ 9%, max DD 6× smaller than naive baseline; claimed to beat ARIMA, XGBoost, and a 3-model ensemble. Methodology not fetched (X status code 402 on fetch); thread describes "how it works" but content not retrievable from this environment.

**Gap analysis:**
- Does Omega do this? No. Omega has no Polymarket ingestion despite `omega/nodes/polymarket/` directory existing as a project slot. No weather-data ingestion.
- What would change: Would require a new project node, not a Victoria signal — Polymarket weather contracts are an entirely separate market from crypto OHLC.
- Dependencies: Polymarket API + weather data provider (NOAA/Open-Meteo) + new project YAML + new strategy. Out-of-scope for the Victoria signal layer.

**Recommendation:** Skip for Victoria. Note in `projects/polymarket.yaml` backlog — interesting *if* Omega ever activates the Polymarket node, but the alpha here is event-specific (US weather contracts) and doesn't transfer to crypto signals. Worth re-examining only when @zostaff publishes the methodology (current claim is unverifiable from the tweet alone).

---

## @hanakoxbt — 56-agent multi-personality simulation terminal
**Source:** @hanakoxbt — https://x.com/hanakoxbt/status/2033250813355679756
**Type:** tweet
**Score:** 2/5 × 1/5 = 2/25 — Skip

**Summary:** Demo of a Claude-built terminal with 56 simulated agents, each with memory/personality/behavior, forming groups and shifting opinions in response to scenarios like "Fed cuts rates by 50bps". Concept piece, no quantitative validation.

**Gap analysis:**
- Does Omega do this? Partially — Omega has a richer multi-node coordination layer (orchestrator, memory bus, attention router) but not opinion-dynamics simulation.
- What would change: Nothing actionable; this is a UX demo, not a signal source.
- Dependencies: N/A.

**Recommendation:** Skip. No measurable PnL or Sharpe claim attached; agent-opinion-dynamics as a market-prediction tool has no published OOS evidence.

---

## Notes
- Twitter/X search via WebSearch was thin for most handles in the watch list; @browomo, @0xricker, @adiix_official, and @data_sn13 returned no specific posts. Consider replacing or augmenting these with handles that have higher retrieval signal in WebSearch (or wiring up a proper X API ingestion path) before the next scheduled run.
- The Kalshi-vol paper is the only Implement-Queue-tier item; recommend it gets a tracking issue separately from this feed report.

---
*Generated by omega-twitter-feed-monitor scheduled task*
