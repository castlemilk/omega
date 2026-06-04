# Omega Research Feed — 2026-05-28

## Items Reviewed
3 items reviewed from arXiv (crypto microstructure + RL).

Note: web search returned no actionable recent tweets from the configured handles
(@browomo, @zostaff, @hanakoxbt, @0xricker, @adiix_official, @data_sn13). X/Twitter
content is not indexed by general web search. Fell back to crypto-quant arXiv discovery
to keep the pipeline productive; consider switching this monitor to direct X API or
RSS-style sources.

---

## Exploring Microstructural Dynamics in Cryptocurrency Limit Order Books — "Better inputs matter more than another hidden layer"
**Source:** arXiv — https://arxiv.org/abs/2506.05764
**Type:** paper
**Score:** 4/5 × 3/5 = 12/25 — Queue

**Summary:** Benchmarks logistic-regression / XGBoost baselines vs DeepLOB and Conv1D+LSTM on
BTC/USDT L2 snapshots (Bybit, 100ms–multi-second sampling). Finding: with Kalman or
Savitzky-Golay preprocessing of LOB features, simple models match or beat deep
architectures. Implication is that feature engineering on the book (queue imbalance,
filtered mid-price, depth slopes) beats architecture complexity for short-horizon
prediction.

**Gap analysis:**
- Does Omega do this? **No.** Omega has no L2 / order-book signals (memory: known gap).
  Cycle-grain features only (SMA, RSI, VPIN/Kyle from trade data).
- What would change: add a new signal family `omega/nodes/victoria/signals/lob.py` consuming
  the V193 dual-exchange WS feed (already in repo), producing queue-imbalance, micro-price,
  depth-slope features at the cycle boundary.
- Dependencies: V193 WS layer must expose L2 depth (not just trades), and a Savitzky-Golay
  or Kalman pass before downsampling to cycle. Replay/backtest path needs L2 capture.

**Recommendation:** Worth queuing behind current V198 work. The "simple model + good features"
framing is on-brand for the existing meta-model layer — these can plug straight into the
logistic ensemble rather than demanding a new model class. First spike: capture 24h of L2
from Coinbase/Kraken (US-allowed per `reference_exchange_apis.md`), compute queue imbalance
and filtered micro-price, score IC vs forward returns at the next cycle. If IC > existing
trade-based VPIN, escalate to full signal node. Track as part of [[victoria_lessons_2026-05]]
follow-ups.

---

## The Anatomy of a Decentralized Prediction Market: Polymarket Order Book Microstructure
**Source:** arXiv — https://arxiv.org/abs/2604.24366
**Type:** paper
**Score:** 3/5 × 4/5 = 12/25 — Queue

**Summary:** 30B order-book events over 52 days across 600 Polymarket markets, joined to
on-chain OrderFilled records. Eight stylized facts incl. longshot spread premium, ~50ms
median feed lag with multi-second spikes, and 1% (median) / 22% (tail) self-counterparty
trades. Critical finding: **trade direction inferred from Polymarket's public feed agrees
with on-chain ground truth only ~59% of the time** — public-feed direction is effectively
noise.

**Gap analysis:**
- Does Omega do this? **Partial.** Omega has a Polymarket node, but I have not verified
  whether trade-direction is sourced from the public feed or on-chain `OrderFilled` events.
  If it's the public feed, every Polymarket-derived signal is built on a 59%-correct label.
- What would change: `omega/nodes/polymarket/` — swap trade-direction ingestion to read
  `OrderFilled` blockchain events; add wash-trade filter (drop self-counterparty rows).
- Dependencies: Polygon RPC access (already required for Polymarket); replication package
  in the paper provides the join logic.

**Recommendation:** Audit `omega/nodes/polymarket/` data ingestion this week — this is a
correctness fix, not a feature. If we're inferring direction from the feed, every downstream
Polymarket signal needs to be re-evaluated. Cheap to check (single file read), high-leverage
if broken. Also worth wiring the 50ms feed-lag distribution into a freshness gate so we
don't trade on stale book state.

---

## Meta-RL-Crypto: Meta-Learning RL for Crypto-Return Prediction
**Source:** arXiv — https://arxiv.org/html/2509.09751v1
**Type:** paper
**Score:** 4/5 × 1/5 = 4/25 — Skip

**Summary:** Transformer-based closed-loop system with actor / judge / meta-judge roles,
starting from an instruction-tuned LLM and self-refining both policy and evaluation criteria
via internal preference feedback. Multimodal inputs: on-chain, news, social sentiment.
Reports outperforming LLM-based baselines (no Sharpe / vs non-LLM quant baselines disclosed
in abstract).

**Gap analysis:**
- Does Omega do this? **No** — no RL agent, no LLM-native signal layer (known gaps).
- What would change: would require an entirely new agent runtime, LLM serving infra, and
  preference-feedback memory store.
- Dependencies: LLM hosting, fine-tuning pipeline, multimodal ingestion (news + social),
  RL training harness — none of which exist.

**Recommendation:** Skip for now. The infrastructure delta is too large vs the reported
upside (paper compares to other LLM baselines, not to traditional quant Sharpe). Revisit if
a smaller-scope component — e.g. an LLM "judge" reviewing the existing meta-model's trade
decisions — becomes tractable. Falls into the same bucket as the LLM tie-breaker that
already failed in [[victoria_lessons_2026-05]].

---
*Generated by omega-twitter-feed-monitor scheduled task*
