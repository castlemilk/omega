# Omega Research Feed — 2026-06-09 12:10

## Items Reviewed
4 items from 6 accounts checked (@browomo, @zostaff, @hanakoxbt, @0xricker, @adiix_official, @data_sn13).

Note: the named handles do not surface directly via US-only WebSearch (X/Twitter is poorly indexed). The one concrete shared artifact found was @zostaff's GitHub repo; the remaining three are recent (Dec 2025 – Feb 2026) crypto-quant papers in the same microstructure/AI-research lane these accounts post about, surfaced via topic search. Opinion/price-prediction tweets were skipped per the brief.

---

## ai-quant-researcher — LLM strategy engine with Deflated-Sharpe gate
**Source:** @zostaff — https://github.com/zostaff/ai-quant-researcher
**Type:** repo
**Score:** 4/5 × 4/5 = 16/25 — Queue (implement the Deflated-Sharpe gate first)

**Summary:** An AI-quant loop where Claude proposes → codes → backtests strategies, gated by three adversarial checkpoints: an LLM "critic", a **Deflated Sharpe Ratio** p-value gate, and a survivor-correlation diversity check (max 0.6). The crux is `ResearchMemory` — a SQLite trial counter recording *every* hypothesis ever proposed (accepted/rejected/killed) so the deflated-Sharpe penalty uses an honest `n_trials`. It also ships AST-sandboxed code execution, leakage detection (centered rolling windows, forward-looking labels), and purged walk-forward CV.

**Gap analysis:**
- Does Omega do this? **Partial.** Omega already has a self-improvement loop and a 6-gate harness (`omega/eval/v49_gates.py`: PnL floor, regime parity, drawdown, trade count, signal integrity, auto-apply audit) plus Brier calibration and an overfitting gate. What Omega *lacks* is **honest trial-count accounting → Deflated Sharpe penalty**, the single most defensible guard against selecting an over-fit config across many training versions (V178→V217). The survivor-correlation diversity gate is also novel vs. Omega.
- What would change: add a `DeflatedSharpeGate` to `omega/eval/` that reads a persisted cross-version trial count (mirrors the noted "meta-harness param space" gap in `victoria_lessons_2026-05.md`) and penalizes Sharpe by the number of configs/params explored. Wire it into the gate sequence alongside the existing six.
- Dependencies: a persisted trial-count store (SQLite `state.db` already exists); `scipy.stats` for the DSR closed form. No new infra, no order-book data, Python-only.

**Recommendation:** **Queue and implement the DSR gate this iteration.** Concrete steps: (1) add `omega/eval/deflated_sharpe.py` implementing Bailey/López de Prado DSR given (observed Sharpe, n_trials, skew, kurtosis, sample length); (2) persist a cumulative `trials_explored` counter keyed by param-space cardinality into `state.db`, incremented per training version / per meta-harness sweep; (3) register it as gate #7 in `v49_gates.py` with a p<0.05 floor and write the verdict into `data/{version}_gate_result.json`. This directly hardens the "what gets merged" decision that the whole V### loop depends on, and matches Omega's Go/Python split (stays in the Python ML/eval layer). The correlation-diversity and leakage-detection ideas are worth a follow-up but DSR is the highest-leverage single addition.

---

## Explainable Patterns in Cryptocurrency Microstructure
**Source:** topic search (microstructure lane of @0xricker/@data_sn13) — https://arxiv.org/abs/2602.00776
**Type:** paper (Feb 2026)
**Score:** 4/5 × 2/5 = 8/25 — Watch

**Summary:** CatBoost with a direction-aware GMADL objective + SHAP on engineered L2 order-book and trade features across BTC/LTC/ETC/ENJ/ROSE (Binance Futures perps, 1-second, Jan 2022–Oct 2025). Finds stable cross-asset SHAP patterns tied to order-flow imbalance, spread, and adverse selection, and shows divergent taker-vs-maker behavior during a flash crash. Conservative backtests were tradable; maker strategies were vulnerable to adverse selection.

**Gap analysis:**
- Does Omega do this? **No.** This is exactly Omega's documented gap — "no order book/L2", "all polling (no streaming)". OFI/spread/adverse-selection features need 1-second L2 depth.
- What would change: a new microstructure signal family + an L2 ingestion path (streaming order-book snapshots from Coinbase/Kraken, the US-allowed venues).
- Dependencies: real-time L2 feed infra, depth storage, 1s resampling — substantial. Binance Futures (the paper's venue) is geo-blocked from the US, so the exact dataset isn't reproducible here.

**Recommendation:** Watch. High potential alpha but blocked by the streaming/L2 infrastructure gap; revisit only if/when an L2 ingestion path is built. Cheap intermediate step: prototype OFI from Coinbase L2 WS (already dual-exchange WS per V193) on a single pair to test whether the cross-asset SHAP stability replicates on US venues before committing to full infra.

---

## Microstructure Alpha: Hierarchical Learning & Cross-Asset Transfer
**Source:** topic search — https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2026.1811716/abstract
**Type:** paper (2026, Pindza)
**Score:** 2/5 × 2/5 = 4/25 — Skip (but log the lesson)

**Summary:** 3M+ minute-level obs across six majors (Binance spot + perps). Pipeline: hierarchical modeling, stability selection, gradient boosting + SHAP, meta-learning, purged walk-forward CV. Two hard negative results: (1) **gradient-boosted models overfit severely under proper leakage controls and no strategy survives realistic exchange fees**; (2) models **do not transfer across assets**, but **do transfer between spot/futures of the same asset**.

**Gap analysis:**
- Does Omega do this? Partial — Omega already uses purged-ish gating and fee/slippage in backtests.
- What would change: nothing to build; this is a cautionary calibration on microstructure ambitions.

**Recommendation:** Skip as an implementation, but the takeaways reinforce existing Omega discipline: keep fee/slippage modeling realistic (the item above's alpha may evaporate at retail fees) and **do not assume cross-asset signal transfer** — train/validate per asset, but spot↔futures reuse is safe. Worth a one-line addition to `victoria_lessons` if not already implied by the "gate stacking / R1-over-fit" notes.

---

## Optimal Signal Extraction from Order Flow (Matched-Filter Normalization)
**Source:** topic search — https://arxiv.org/abs/2512.18648
**Type:** paper (Dec 2025)
**Score:** 2/5 × 3/5 = 6/25 — Watch

**Summary:** Argues optimal flow-signal normalization must match the scaling of the signal-generating process: market-cap normalization (Sᴹᶜ) for capacity-constrained institutional flow, trading-value normalization (Sᵀⱽ) for VWAP/TWAP volume-targeters. Korean equities (2.7M stock-days, 2020–2024); matched filters give up to 1.99× higher signal correlation; no sign reversal at longer horizons (durable private info, not transient impact). **Equities only — no crypto validation.**

**Gap analysis:**
- Does Omega do this? Partial — Omega has OBV / funding / OI flow-type signals but normalizes them ad hoc, not by a matched-filter principle.
- What would change: a normalization choice (by market cap vs. by traded value) on existing volume/flow signals — a feature-engineering tweak, not new infra.
- Dependencies: market-cap series (CoinGecko already available) and traded-value series (have it). Low cost.

**Recommendation:** Watch. The generalizable idea — pick flow normalization to match who generates the flow — is a cheap, low-risk experiment on Omega's existing OBV/OI signals: A/B market-cap-normalized vs. traded-value-normalized variants in a training run and check IC. But it's an incremental tweak on an equities result with no crypto evidence, so it sits behind the DSR gate in priority.

---
*Generated by omega-twitter-feed-monitor scheduled task*
