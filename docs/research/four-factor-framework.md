# Four-Factor Prediction-Market Scoring Framework — Evaluation

**Date:** 2026-04-14
**Status:** Research / evaluation only. No implementation in this pass.
**Provenance:** A Twitter/X post claiming a Citadel prediction-markets fund scores contracts on four factors (cross-market divergence, disposition coefficient, capital velocity, pair network correlation), sourcing data from `github.com/warproxxx/poly_data`. Tweet ends in a copytrade funnel (`kreo.app/@1743116`) and a "$800 → $11.5k, 70% WR over 280 trades, $25/mo infra" performance pitch.

---

## 1. Summary Verdict

The **narrative** is almost certainly marketing. The **four concepts**, stripped from the tweet's framing, are each legitimate quant primitives with decades of academic and industry precedent. Treat the tweet as a pointer to a concept set, not as a trading system.

- **Cross-market divergence** — standard stat-arb / basis trading. Already partially covered in Victoria (`pairs_signals`, `signal_correlation`).
- **Disposition coefficient** — Shefrin & Statman (1985). **Most actionable for Victoria right now.** Our postmortems show we hold losers and cut winners — textbook disposition effect. An exit-discipline metric lands immediately against a real pathology.
- **Capital velocity** — inventory turnover. Interesting for sizing/capacity, not a direction signal. Low priority.
- **Pair network correlation** — correlation networks / Ollivier-Ricci on graphs. Victoria's `curvature_signal.py` and `geometry/ollivier_ricci.py` already explore this surface.

**Single net takeaway:** implement a disposition-coefficient exit-discipline metric for Victoria. Defer everything else. Do not fund the Polymarket extension as a separate track yet; park it as an optional Phase-3 item.

---

## 2. Credibility Pass

| Claim | Assessment |
|---|---|
| `warproxxx/poly_data` is a real public repo | Yes. Publicly accessible; data-pipeline tooling for Polymarket markets/orders/trades. README does not explicitly document "86M trades with per-wallet attribution" — dataset size is unverified from the repo surface. |
| Citadel runs a prediction-market fund | No public confirmation. Coverage is speculative. Confirmed active on Polymarket: Susquehanna, Jump, Founders Fund — not Citadel. Treat as unverified. |
| 70% WR over 280 trades | N=280 is underpowered for a 70% WR to be durable against luck + selection bias. No independently audited track record. |
| $800 → $11.5k on $25/mo infra | ~14x gross. Standard survivorship-bias pattern for copytrade funnels. |
| `kreo.app/@1743116` copytrade link | Affiliate funnel. Revenue from follower fees, not edge. |

Red flags: copytrade monetisation, unaudited returns, small N, unverifiable fund attribution. The **concepts** survive the critique; the **pitch** does not.

---

## 3. Factor-by-Factor Analysis

### 3.1 Cross-Market Divergence

**Definition.** Given two or more venues/instruments tracking the same (or cointegrated) underlying, let `s_t = p^A_t − f(p^B_t)` be a residual. Divergence is a statistically abnormal `s_t`: `z_t = (s_t − μ_w)/σ_w` over rolling window `w`, entering on `|z| > θ`, exiting on `|z| < θ_exit` or on cointegration breakdown (ADF p-value crosses threshold).

**Data needs.** Synchronous quotes on ≥2 venues, low-latency timestamps, rolling stats, cointegration monitor.

**Precedent.** Engle & Granger (1987); Gatev, Goetzmann, Rouwenhorst (2006) pairs trading. First-principles stat-arb.

**Victoria status.** Partially covered. `pairs_signals.py` does ETH/BTC and SOL/ETH cointegration with z-score entries. We do not track cross-venue basis (Binance perp vs. Bybit perp vs. spot), which is the most direct "cross-market divergence" reading.

**Novelty:** ~30%. Duplicates existing pairs work. Venue-basis is incremental.

**Polymarket applicability.** Direct. Polymarket vs. Kalshi vs. PredictIt on matched events gives a clean basis; settlement/fee differences become the fair-value adjustment.

---

### 3.2 Disposition Coefficient (Exit Discipline)

**Definition.** The disposition effect (Shefrin & Statman, 1985; Odean 1998) is the tendency to realise gains early and hold losses long. A usable coefficient:

```
PGR = winners_closed / (winners_closed + winners_open)
PLR = losers_closed  / (losers_closed  + losers_open)
DE  = PGR − PLR                         (Odean)
```

Or the tweet's framing (fraction-of-move capture):

```
win_capture  = realised_winner_PnL / MFE_winner
loss_capture = realised_loss       / MAE_loser
```

"Top wallets capture 86% of winner value, cut losers at 12%; average 58% / 41%." The exact numbers are unverified, but the framing — **compare realised capture vs. path extremes** — is the right quant object. Victoria's `paper_trading.py` already logs MAE and MFE per trade, which is precisely what's required.

**Data needs.** Per-trade entry/exit, running MAE/MFE, realised PnL. All present.

**Precedent.** Shefrin & Statman 1985; Odean 1998; Barberis & Xiong 2009.

**Victoria status.** No disposition metric currently computed, despite postmortem evidence that we hold losers (into MAE floor) and cut winners (before MFE). **Pathology-to-metric match.**

**Novelty:** High. Nothing in our 20+ signals measures exit quality; they all feed *entry* conviction.

**Proposed implementation (independent of tweet provenance):**

1. **Per-trade exit-discipline score.** At close:
   - `win_capture = pnl / MFE` if winner, else NaN
   - `loss_capture = loss / MAE` if loser, else NaN
   - `exit_score = win_capture − loss_capture` (higher is better; top-wallet claim ≈ 0.74)
   - Persist on closed trade record.

2. **Aggregate version-level metric.** Report alongside PF/WR:
   - `median_win_capture`, `median_loss_capture`, `disposition_coefficient`
   - Backfill across closed paper-trading history.

3. **Optional exit controller (gated).** If unrealised PnL crosses a high MFE quantile, tighten trail; if a losing position crosses a low MAE-budget quantile, force-exit. Only after ≥200 descriptive trades.

4. **Dashboard surface.** Add to `dashboard.py`; include in postmortem template.

This is the **one idea worth implementing in Victoria now.** It does not depend on any Citadel/Polymarket claim being true.

---

### 3.3 Capital Velocity

**Definition.** `velocity = Σ|notional| / avg_deployed_capital` over a period. "49x per recycle cycle" is the top-cohort turnover vs. median-trader turnover ratio. Accounting analogue: inventory turnover / asset turnover applied to working capital.

**Data needs.** Trade notionals, capital base, elapsed time. Trivial.

**Precedent.** Inventory turnover is first-year finance. In HFT/MM: queue-position velocity, per-unit-capital throughput.

**Victoria status.** Not tracked. Single aggregate metric.

**Novelty:** Low as a signal. Moderate as a **capacity/constraint diagnostic**: velocity × edge-per-trade is the throughput bound, and drops in velocity with unchanged signal generation are a tell for execution friction.

**Why not a direction signal.** Velocity describes intensity, not direction.

**Recommendation.** Add as a lightweight dashboard metric. Low cost, low priority.

---

### 3.4 Pair Network Correlation

**Definition.** Build a graph `G` with markets as nodes and rolling correlations (or a geometric derivative such as Ollivier-Ricci curvature) as edges. Features: MST edge density, average curvature, spectral gap, community structure. Regime changes drive signals.

"42 pair correlations across 11 markets" is just thresholded C(11,2)=55. Basic correlation-network setup.

**Data needs.** Price series for N markets, rolling covariance, graph layer.

**Precedent.** Mantegna (1999) MSTs; Onnela et al. (2003); Ollivier-Ricci on financial networks (Sandhu, Georgiou, Tannenbaum 2016; Samal et al. on crash prediction). Matches Omega's Week 2 persistent-homology research and existing `curvature_signal.py` / `geometry/ollivier_ricci.py`.

**Victoria status.** Actively explored. A pair-correlation-network module would sit alongside curvature work.

**Novelty:** Low. Overlaps directly with existing geometric work.

**Recommendation.** No new work. Ship the existing curvature signal into live evaluation rather than add another module.

---

## 4. Victoria Integration Plan (Prioritised)

### Priority 1 — Disposition / Exit-Discipline Metric (ship now)

- **P1.1** Extend `paper_trading.py` close path to compute `win_capture`, `loss_capture`, `exit_score` per closed trade. Uses existing MAE/MFE.
- **P1.2** Add aggregate `disposition_coefficient` and capture medians to version-level stats (alongside PF/WR/expectancy).
- **P1.3** Backfill across existing closed-trade history.
- **P1.4** Surface on `dashboard.py`; include in postmortem template.
- **P1.5 (deferred)** Exit controller: trail-tightening on winners past MFE quantile, forced exit on losers past MAE-budget quantile. Gated on ≥200 closed trades of descriptive data.

**Effort:** ~1 day for P1.1–P1.4. Controller is a separate epic.

**Success criterion:** after N=100 paper trades, we can tell whether Victoria's disposition coefficient is above or below zero and whether it tracks PF.

### Priority 2 — Cross-Venue Basis Signal (optional, medium)

Extend pairs/divergence from same-underlying-different-asset (ETH/BTC) to same-asset-different-venue (Binance vs. Bybit vs. spot). Only worth it if we intend to route across venues.

### Priority 3 — Capital Velocity Metric (cheap, low priority)

Single ratio on the paper-trading dashboard. No controller semantics.

### Non-priorities

- Pair-network-correlation module — duplicates curvature work.
- Anything depending on the tweet's Citadel-fund claim.

---

## 5. Polymarket Extension Plan (Optional Track)

Omega has a Polymarket stub (`internal/polymarket/client.go`, `projects/polymarket.yaml`, tests). The four factors port cleanly, but the scoring-head question is whether a standalone node is worth funding.

**Phase 0 — Decision.** Do we want Omega to paper-bet Polymarket contracts in parallel with perps? If no, stop here.

**Phase 1 — Data ingest (1–2 weeks).** Fork or vendor `warproxxx/poly_data`. Validate the 86M-trades claim empirically (row counts, per-wallet cardinality, date coverage). Land into Omega storage. Add market-metadata ingest (resolution date, liquidity, volume, category).

**Phase 2 — Factor computation (1–2 weeks).**
- Cross-market divergence: Polymarket vs. Kalshi on matched events (requires Kalshi ingest — extra scope).
- Disposition: per-wallet win/loss capture from the trade log. Rank wallets; isolate a top cohort as a signal source (smart-money-style).
- Capital velocity: per-wallet and per-market turnover. Market-level velocity is a liquidity/flow proxy.
- Pair-network correlation: across contracts within a category (e.g. 2028 election contracts).

**Phase 3 — Paper-betting harness (1 week).** Polymarket-specific engine mirroring `paper_trading.py` with binary-outcome PnL (payoff ∈ {0,1} at resolution, entry = price paid). MFE/MAE on mid-price traversals. Disposition coefficient feeds back into the Victoria-side metric.

**Phase 4 — Live evaluation.** WR, PF, Brier score, log-loss, calibration curves. Polymarket is probability-forecasting first; standard metrics are Brier and reliability, not PF.

**Risks specific to Polymarket.** Small-event illiquidity; resolution / oracle (UMA) disputes; wallet-level analytics poisoned by copy-trading clusters (ironically, the kind the tweet promotes).

**Recommendation.** Don't greenlight off the tweet. Revisit after Victoria's disposition work has delivered a real lift; Polymarket then becomes a natural extension for the same metric.

---

## 6. Risks and Skepticism

- **Narrative-led quant** is how retail funnels dress up. The four factors are legitimate *because they pre-date the tweet by 20–40 years*, not because the tweet frames them well.
- **"Top wallets 86/12"** is unverified. The pattern (cut losers hard, ride winners) is real; specific fractions should be re-estimated on `poly_data` before being used as a target.
- **Citadel attribution** is almost certainly false. Don't cite it except to flag it.
- **Copytrade funnel incentives** mean the promoter has reason to conflate correlation with edge.
- **Our own bias** toward mathematical elegance can duplicate existing work under a new name. Pair-network correlation is the canonical example.

---

## 7. Appendix — Minimal disposition-coefficient implementation sketch

*Sketch only; do not implement in this pass.*

```python
# omega/core/paper_trading.py — on close_trade()
if realised_pnl >= 0:
    win_capture  = realised_pnl / mfe if mfe > 0 else float("nan")
    loss_capture = float("nan")
else:
    win_capture  = float("nan")
    loss_capture = realised_pnl / mae if mae < 0 else float("nan")

exit_score = (0.0 if math.isnan(win_capture)  else win_capture) \
           - (0.0 if math.isnan(loss_capture) else loss_capture)
```

```python
# aggregate — emit alongside PF/WR
median_win_capture       = nanmedian([t.win_capture  for t in closed])
median_loss_capture      = nanmedian([t.loss_capture for t in closed])
disposition_coefficient  = median_win_capture - median_loss_capture
```

Target posture: `disposition_coefficient > 0.3` acceptable; `> 0.5` good; top-wallet claim ≈ 0.74. Current Victoria behavior likely sits negative.

---

*Companion to Week 1–3 geometry research; fits alongside `cross-asset-signals.md`. Will be updated if/when the disposition metric ships.*
