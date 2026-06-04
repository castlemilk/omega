# Omega Research Feed — 2026-05-27

## Items Reviewed
3 items reviewed. Twitter searches for @browomo, @zostaff, @hanakoxbt, @0xricker, @adiix_official, @data_sn13 returned no indexable recent posts/links via WebSearch (handles surfaced but tweet content not retrievable). Pivoted to recent arXiv q-fin.TR listings to identify research the target accounts are most likely to be discussing in late May 2026.

---

## The Anatomy of a Decentralized Prediction Market: Microstructure Evidence from the Polymarket Order Book
**Source:** arXiv — https://arxiv.org/abs/2604.24366 (uploaded 2026-05-14)
**Type:** paper
**Score:** 3/5 × 3/5 = 9/25 — Watch

**Summary:** Tick-level archive of Polymarket's public order book (30B events / 52 days / 600 markets) yields eight stylized facts: longshot spread premium, uniform depth profiles, concentrated maker wallets, ~1% wash (vs 25–70% on unregulated crypto), and sub-50ms ingest with multi-second outliers. Headline result: trade-direction inferred from the feed agrees with on-chain ground truth only ~59% of the time (vs ~80% Nasdaq) — Lee-Ready is unreliable on decentralized venues; Kyle's lambda and effective spreads shift in 50–67% of markets when computed feed-only vs on-chain-joined.

**Gap analysis:**
- Does Omega do this? Partial — Polymarket nodes exist (`omega/nodes/polymarket/`) but no LOB ingest or on-chain trade-direction join.
- What would change: New polymarket microstructure node (effective spread, Kyle's λ, longshot premium as features); on-chain OrderFilled enrichment for ground-truth direction.
- Dependencies: Polymarket order-book websocket archive + Polygon RPC for OrderFilled events; ~30B-event scale storage non-trivial.

**Recommendation:** Watch — Polymarket is a side surface for Omega, not core PnL. Useful if/when a polymarket signal is escalated to position-sizing. If pursued, start with feed-vs-on-chain trade-direction parity check on a 1-week sample to validate the 59% claim before building the full microstructure node.

---

## Exploring Microstructural Dynamics in Cryptocurrency Limit Order Books: Better Inputs Matter More Than Stacking Another Hidden Layer
**Source:** arXiv — https://arxiv.org/abs/2506.05764
**Type:** paper
**Score:** 4/5 × 2/5 = 8/25 — Watch

**Summary:** Bybit BTC/USDT LOB at 100ms–multi-second resolution, predicting short-horizon directional movement. Headline: with Kalman + Savitzky-Golay preprocessing, logistic regression and XGBoost match or beat DeepLOB / Conv1D+LSTM. Binary and ternary labelling both tested; simpler models also give faster inference and SHAP interpretability.

**Gap analysis:**
- Does Omega do this? No — stated gap "no order book/L2", and current signals run on bar data, not 100ms LOB.
- What would change: New `lob_imbalance` signal node consuming L2 snapshots; Kalman/Sav-Gol filter utility; XGBoost direction classifier feeding into the conviction composite.
- Dependencies: Bybit L2 websocket (geo-blocked from US per [reference_exchange_apis.md](../../.claude/projects/-Users-benebsworth-projects-omega/memory/reference_exchange_apis.md) — would need Coinbase/Kraken L2 instead, which changes the empirical baseline); streaming infra (Omega is currently all-polling).

**Recommendation:** Watch — high impact but the US geo-block on Bybit/Binance and the all-polling architecture make this a multi-week build, not a drop-in. Concrete next step if upgraded to Queue: prototype on Coinbase Advanced Trade L2 for BTC-USD only, replicate the Kalman+Sav-Gol → XGBoost pipeline on 1 week of cached snapshots, and measure whether a 100ms imbalance signal adds Sharpe vs the existing bar-level conviction filter (`omega/nodes/victoria/strategy.py:_passes_conviction_filters`).

---

## Explainable Patterns in Cryptocurrency Microstructure
**Source:** arXiv — https://arxiv.org/abs/2602.00776
**Type:** paper
**Score:** 4/5 × 2/5 = 8/25 — Watch

**Summary:** Binance Futures perp LOB + trades, 1-second freq, Jan 2022 → Oct 2025, across BTC/LTC/ETC/ENJ/ROSE. CatBoost with a direction-aware GMADL objective and time-series CV. Result: SHAP feature rankings and partial-effect shapes are **stable across assets spanning an order of magnitude in market cap** — i.e., portable LOB representation for short-horizon returns. Maker vs taker strategies diverge sharply during a flash-crash event, empirically validating adverse selection.

**Gap analysis:**
- Does Omega do this? No — same LOB gap as above; also no GMADL loss and no CatBoost in current ensemble (`omega/nodes/victoria/ensemble_voter.py`).
- What would change: Same LOB ingest as item 2, plus a CatBoost branch in the ensemble; cross-asset portability claim is attractive because Omega trades a multi-symbol basket.
- Dependencies: Binance Futures LOB (geo-blocked); GMADL objective implementation (not in betterproto/numpy stack); CatBoost dep (heavy).

**Recommendation:** Watch — the cross-asset portability claim is the genuinely novel piece (most LOB papers fit one symbol). Worth re-rating to Queue if/when item 2's geo-block problem is solved, because the two papers share infra and this one provides the multi-symbol justification Omega actually needs.

---

*Generated by omega-twitter-feed-monitor scheduled task*

---

## I Used a 2012 Market Microstructure Paper to Find Alpha in BTC. It Worked — But It's Dying.
**Source:** Tigro Blanc / Coinmonks (Medium) — https://medium.com/coinmonks/i-used-a-2012-market-microstructure-paper-to-find-alpha-in-btc-it-worked-but-its-dying-500f9bc0fc94 (Apr 2026)
**Type:** article (practitioner walk-forward study)
**Score:** 4/5 × 5/5 = 20/25 — Implement immediately (as a guardrail, not a new signal)

**Summary:** Author back-tests Easley/Lopez de Prado/O'Hara (2012) VPIN on BTCUSDT perp (Binance, 1m klines, Jan 2024–Feb 2026, 6 walk-forward folds). Gross alpha at 24h horizon decayed +82.3 bps (2024) → +38.5 bps (2025) → +12.4 bps (2026 YTD); net went −15.6 bps in 2026. Recommends using VPIN as a *regime filter layered on other strategies*, monitoring monthly net, exiting after 3 consecutive negative months, BTC-only, 5% sizing.

**Gap analysis:**
- Does Omega do this? **Partial — and this is the critical point.** V185 (per [[victoria_lessons_2026-05]]) just shipped VPIN + Kyle's lambda as composite signals. We do not yet have a decay-monitoring guardrail on them.
- What would change: add a rolling 30/60/90d Sharpe + net-bps monitor for the VPIN sub-signal in `omega/nodes/victoria/signal_generation.py` (or wherever V185 wired it), with a kill-switch in `meta_learner.py` that downweights VPIN to zero after 3 consecutive negative months. Surface the decay curve in the V185 forensics dashboard.
- Dependencies: per-sub-signal PnL attribution (this is the [[project_training_gaps]] "weight_applied / per-symbol convictions" gap — still open per memory).

**Recommendation:** This is a direct warning shot at V185. Two concrete next steps: (1) Run forensics comparing V185 VPIN signal contribution Jan–May 2026 by month — does the live decay curve match the author's? (2) Add a `signal_decay_guardrail.py` that computes rolling net-bps per sub-signal from `coordination_outcomes` and emits a downweight directive when the 90d net goes negative. The author's exit rule (3 consecutive negative months, BTC-only sizing) is a sensible default. Treat this as evidence that *every* microstructure-derived signal in Omega needs a decay monitor — not just VPIN.

---

## Six Market Microstructure Signals That Fire Before the Price Print
**Source:** HFT Advisory (Substack) — https://hftadvisory.substack.com/p/six-market-microstructure-signals
**Type:** article (execution-quality architecture)
**Score:** 4/5 × 2/5 = 8/25 — Watch (blocked by Omega's lack of L2 streaming)

**Summary:** Catalogues six pre-print signals on a T+0 → T+1s ladder: (1) cancel-side asymmetry, (2) refresh-latency widening (MM quote-update p95), (3) VPIN @ T+50ms, (4) multi-level LOB shift across 5+ depths, (5) top-of-book spread widening, (6) print + queue-position slippage. All six are computable from public trades + L1/L2 feeds — no private flow required.

**Gap analysis:**
- Does Omega do this? **No.** Per [[project_omega]], Omega has no order book / L2 ingestion and everything is polling-based, not streaming. V185 VPIN is computed from bar-level taker buy volume, not from a live LOB.
- What would change: requires a new streaming ingest layer (WS L2 from Coinbase + Kraken given US geo-block on Binance/Bybit per [[reference_exchange_apis]]), tick storage, and an HFT-cadence signal node. This is infrastructure work, not a signal node.
- Dependencies: WS L2 client, ring-buffer tick storage, sub-second scheduler (current heartbeat is multi-second), per-signal latency budget. V193 added dual-exchange WS for *trades* — extending to L2 is a natural follow-up but non-trivial.

**Recommendation:** Skip standalone implementation now — the infra cost is large and Omega's strategy operates on bar-level cycles, not sub-second. But keep on the watch list: signals (1) cancel-side asymmetry and (4) multi-level LOB imbalance are the highest-value additions *if* L2 streaming lands for another reason (e.g., execution-quality work). Re-score to 16+ once V193's WS layer is extended to L2 depth.

---
*Generated by omega-twitter-feed-monitor scheduled task (continuation run)*
