# Omega Research Feed — 2026-06-06 00:10

## Items Reviewed
4 items from accounts checked: @browomo, @zostaff, @hanakoxbt, @0xricker, @adiix_official, @data_sn13

> Note: Direct handle-scoped timeline scraping returned little (these are niche handles, sparsely indexed by web search). The strongest find — `ai-quant-researcher` — surfaced directly from @zostaff. The other three are crypto-quant arXiv papers surfaced via the accounts' topic searches; they are scored on merit even though attribution to a specific tweet could not be confirmed.

---

## ai-quant-researcher — AI strategy engine with deflated-Sharpe + purged-CV gates
**Source:** @zostaff — https://github.com/zostaff/ai-quant-researcher
**Type:** repo
**Score:** 4/5 × 4/5 = 16/25 — Queue

**Summary:** An AI-driven quant research engine where Claude proposes → codes → backtests strategies, wrapped in heavy statistical-rigor guardrails. Novel components: a **ResearchMemory** SQLite tamper-evident trial counter (honest N for multiple-testing correction), a **three-gate validation system** (LLM adversarial critic pre-backtest, **Deflated Sharpe Ratio** test correcting for selection bias across trials, and a correlation gate to kill redundant strategies), an **AST-based leakage detector** (catches centered windows, forgotten shifts, label leakage), and **purged walk-forward CV** with embargo gaps. ~$10 generates 1,000 strategy proposals; deps are minimal (Python 3.11+, 5 packages).

**Gap analysis:**
- Does Omega do this? **Partial.** Omega already has a self-improvement loop, episodic/semantic memory, an overfitting gate, Brier calibration, and the v49 hard-gate suite. But it does **not** have: deflated-Sharpe correction for multiple-testing across the many Victoria training variants, an AST leakage detector, or purged walk-forward CV with embargo.
- What would change: `omega/eval/v49_gates.py` (add a Deflated Sharpe gate keyed off a real trial counter), a new standalone leakage-detector pass over signal code, and the backtest/replay harness (purged + embargoed CV).
- Dependencies: a persistent honest trial counter (the training-version history in `data/training_version.txt` + per-version results already approximates this); scipy for the deflated-Sharpe distribution math (already an optional extra).

**Recommendation:** Queue and prioritise the **Deflated Sharpe Ratio gate** first. The Victoria lessons memory (`victoria_lessons_2026-05.md`) repeatedly flags over-fitting — "gate stacking," "R1-recommended over-fits" — as the dominant failure mode across V178–V198. Deflated Sharpe directly penalises a strategy's Sharpe by the number of configurations tried, which is exactly the missing correction when we sweep dozens of V### variants and cherry-pick the winner. It is a pure statistics function (≈40 lines) that slots into `omega/eval/v49_gates.py` as gate #7, reading the trial count from the training-version ledger. Follow with the AST leakage detector as a CI check on `omega/nodes/victoria/strategy.py`. Both are drop-in to the existing Python eval layer with no new infrastructure.

---

## Hawkes Processes on Limit-Order-Book data for crypto forecasting
**Source:** @0xricker (topic match) — https://arxiv.org/abs/2312.16190
**Type:** paper
**Score:** 4/5 × 2/5 = 8/25 — Watch

**Summary:** Applies multivariate **Hawkes (self-exciting point) processes** to Level-2 limit-order-book data to forecast short-horizon crypto price direction, deriving order-flow-imbalance features from the Hawkes intensity functions. The method itself is well-established; the novelty is the crypto-LOB application. Inputs are high-frequency L2 snapshots (arrivals/cancellations/volumes per price level); estimation is MLE that scales with event count and dimension.

**Gap analysis:**
- Does Omega do this? **No.** Omega's documented gaps include "no order book/L2" and "all polling (no streaming)." This is squarely in unaddressed territory.
- What would change: a new microstructure signal node, plus L2 ingestion (Coinbase/Kraken streaming order book) and a tick store.
- Dependencies: streaming L2 feeds + storage + a Hawkes MLE estimator — none of which exist today; Binance/Bybit L2 is geo-blocked from the US.

**Recommendation:** Watch. High potential alpha (microstructure is a genuinely new capability), but feasibility is low: it requires the streaming + L2 infrastructure Omega has deliberately not built, which is a multi-week platform investment rather than a signal-layer add. Revisit if/when an L2 ingestion path lands; the Hawkes estimator would then be the natural first consumer.

---

## The Limits of Lognormal — crypto VaR via Geometric Brownian Motion
**Source:** @data_sn13 / @browomo (topic match) — https://arxiv.org/abs/2601.14272
**Type:** paper
**Score:** 2/5 × 3/5 = 6/25 — Watch

**Summary:** Ekleen Kaur applies textbook GBM (MLE + correlated Monte Carlo via Cholesky of historical covariance) to crypto portfolios (XRP/SOL/ADA) and computes 1-year 5% VaR. Finding: GBM's lognormal-returns assumption breaks down badly for crypto — heavy-tailed, non-Gaussian returns produce far higher VaR-breach failure rates than the matched equity portfolio (AAPL/TSLA/NVDA). It is a cautionary baseline, not a new method.

**Gap analysis:**
- Does Omega do this? **Partial / already respected.** Omega sizes via Kelly and reads vol-regime, ATR, VRP, and a 2-state HMM rather than relying on a Gaussian VaR — so it already avoids the trap this paper warns about.
- What would change: nothing structural; at most a note that any future VaR/risk-of-ruin module must use a fat-tailed (Student-t / EVT) distribution, not lognormal.
- Dependencies: none.

**Recommendation:** Watch — mostly confirmatory. Useful as a guardrail reference if a VaR-based position-sizing or drawdown-ceiling module is ever added (don't use lognormal; use Student-t or EVT tails). No action.

---

## Simulation-based crypto portfolio risk framework (volatility / hedging / contagion / MC)
**Source:** @browomo (topic match) — https://arxiv.org/abs/2507.08915
**Type:** paper
**Score:** 3/5 × 3/5 = 9/25 — Watch

**Summary:** A modular risk framework integrating four pieces — volatility stress testing, stablecoin (USDT) hedging, correlation-based **contagion propagation**, and Monte Carlo price-path simulation with mean-variance optimisation — validated on 2020–2024 BTC/ETH/USDT data. Explicitly an incremental integration of established techniques adapted to crypto. Inputs: historical prices + correlation matrices; compute unspecified but light.

**Gap analysis:**
- Does Omega do this? **Partial.** Omega has BTC-beta, vol-regime, cross-asset momentum, and a liquidation-cascade signal (a form of contagion), but no explicit correlation-based contagion-propagation model or Monte-Carlo portfolio stress test.
- What would change: an optional portfolio-risk node doing correlation-matrix contagion propagation + MC stress paths, feeding the conviction/sizing layer.
- Dependencies: a multi-asset correlation matrix (already derivable from the PCA-regime pipeline); numpy MC.

**Recommendation:** Watch. The single transferable idea is **correlation-based contagion propagation** as a regime-risk input, but it overlaps materially with the existing liquidation-cascade and PCA-regime signals, so the marginal Sharpe is uncertain. Lower priority than the deflated-Sharpe gate above; reconsider only if a dedicated portfolio-risk node is on the roadmap.

---
*Generated by omega-twitter-feed-monitor scheduled task*
