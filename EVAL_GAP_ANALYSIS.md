# Omega Eval Framework — Gap Analysis

**Date:** 2026-03-21
**Scope:** All eval modules, core subsystems, integration tests, signals/strategy layer
**Verdict:** The framework has solid structural bones but would be rejected by any quant fund risk committee. The gaps are not stylistic — they are methodological and would produce misleading alpha estimates.

---

## A. Statistical Rigor

### A1. Bootstrap CIs exist but are never used in production reports

`sharpe.py` implements `compute_sharpe_confidence_interval()` correctly (bootstrap percentile method, seeded). It is never called from `build_eval_report()` in `metrics.py`. Every `EvalReport` that flows out of `backtest_bridge.py` or `BacktestEvaluator` carries a bare point-estimate Sharpe with no uncertainty bounds. A Sharpe of 1.2 on 100 bars has a 95% CI of roughly [0.4, 2.0] — the point estimate is meaningless without it.

`sharpe_difference_significant()` in `sharpe.py` exists but is also never called from any comparison report. The `_compare()` function in `backtest.py` returns raw deltas with no significance test at all.

### A2. No multiple-comparison correction

TPE (`tpe_eval.py`, `improvement_engine.py`) proposes and evaluates dozens to hundreds of parameter configurations. Each is tested against the same OOS window. The `_statistical_test` in `tpe_eval.py` runs a single Welch t-test comparing aggregate TPE vs random scores — it does not correct for the number of configurations explored. With 100 trials and p < 0.05 as the threshold, 5 false discoveries are expected by chance. No Bonferroni, Holm, or Benjamini-Hochberg correction is applied anywhere in the codebase.

### A3. The OOS window is contaminated by TPE

`backtest_evaluator.py` defaults `oos_start="2024-01-01"` and `oos_end="2024-12-31"`. This fixed OOS window is used as the objective function for **all** TPE trials. If TPE runs 200 trials, it has evaluated 200 configurations against the same window. That window is no longer out-of-sample — it is the training signal for the hyperparameter search. A proper design requires a held-out test set that TPE never sees, with OOS used only for candidate selection. The framework has no such third split.

### A4. Annualised return uses arithmetic mean, not CAGR

`compute_annualised_return()` in `metrics.py` does `sum(r) / len(r) * periods_per_year`. For any multi-year backtest, this overstates compound growth because arithmetic mean > geometric mean when variance is nonzero. The correct formula is `(equity_curve[-1] / equity_curve[0]) ** (periods_per_year / n) - 1`. This is a textbook error that inflates headline return numbers.

### A5. Normal approximation used for small samples

`sharpe_difference_significant()` in `sharpe.py` explicitly warns at line 144: "For small n this is an approximation." The minimum sample size for a t-distribution to approximate normal is ~30. Backtests of 60–100 cycles will produce materially incorrect p-values from this function — and it is never called anyway (see A1).

---

## B. Data Integrity

### B1. Silent fallback to synthetic data everywhere

Both `backtest.py:BacktestEngine._load_data()` and `backtest_evaluator.py:BacktestEvaluator._load_prices()` silently fall back to deterministic synthetic data when the DataIngestionNode is unavailable. The fallback is a linear congruential generator (LCG) producing ±2% random returns with no autocorrelation, no volatility clustering, no fat tails, no correlation structure. Every integration test and the entire TPE optimization loop runs on this data by default. There is no test that verifies the system behaves differently on real vs synthetic data, and no CI gate that fails if real data is unavailable.

This means all Sharpe numbers produced in development are artifacts of the LCG seed, not market signal.

### B2. Walk-forward is real in the bridge but fake in the evaluator

`backtest_bridge.py` correctly splits 60% in-sample / 40% OOS via `TRAIN_FRACTION = 0.60`. This is the **only** place walk-forward separation is enforced. `backtest_evaluator.py` — the module that the TPE improvement loop actually calls — uses a hardcoded calendar window. All TPE evaluations score against the same calendar period. There is no expanding window, no rolling window, and no bar-count-based split in the evaluator.

The walk-forward metrics (`in_sample_sharpe`, `out_of_sample_sharpe`) reported in `EvalReport` are computed correctly post-hoc in `build_eval_report()`, but they have no enforcement mechanism: nothing prevents the upstream TPE from selecting parameters that maximise OOS Sharpe on the fixed window.

### B3. Look-ahead bias in backtest.py entry pricing

`_sma_crossover_strategy()` in `backtest.py` (lines 365–383) enters a long position at `bars[i].close` when the SMA crossover triggers at bar `i`, then computes the bar's daily return as `position * (closes[i] - closes[i-1]) / closes[i-1]`. The bar `i` return is already realised before the crossover signal can be acted upon — the strategy earns the return of the bar that generated the entry signal. In live trading, the earliest possible entry is `bars[i+1].open`. `backtest_bridge.py` correctly uses `next_bar["open"]` for fills, but the standalone `backtest.py` engine does not. Any Sharpe from `BacktestEngine._run_pico()` or `_run_omega()` is look-ahead biased.

### B4. Equity curve computation in backtest.py is additive, not multiplicative

`_compute_metrics()` in `backtest.py` computes drawdown on `cumulative = sum(daily_returns)` — simple additive P&L, not a multiplicative equity curve. The correct drawdown calculation requires a multiplicative curve (`∏(1 + r_i)`). `metrics.py:build_equity_curve()` does this correctly, but `backtest.py` does not use it. Additive drawdown understates losses after a strong winning period.

### B5. No survivorship bias handling

The asset universe is BTC, ETH, SOL — all of which are survivors. There is no framework for including delisted or failed assets (e.g., LUNA, FTX Token) that existed in historical data. Any cross-asset signal trained on this universe is survivorship-biased.

---

## C. Market Realism

### C1. Flat commission, no market impact

`backtest_bridge.py` uses `commission=0.001` (10bps round-trip) applied uniformly. There is no:
- Market impact model (Almgren-Chriss or similar)
- Bid-ask spread model (the `MicrostructureSignal` in `signals_advanced.py` tracks spreads but the backtest never uses them for execution cost)
- Partial fill simulation
- Slippage as a function of order size and liquidity
- Maker/taker fee differentiation

For a crypto strategy at any meaningful scale, market impact dominates transaction costs. A 0.1% flat fee assumption will produce Sharpe ratios that are 30–50% too high for AUM > $1M.

### C2. Execution always at next bar open

The bridge fills at `next_bar["open"]`. This is better than filling at signal-bar close, but it assumes:
1. The order is always filled (no partial fills, no order rejection)
2. Open prices are achievable (gaps, circuit breakers, and illiquid opens are ignored)
3. No queuing delay — the order arrives instantaneously at open

### C3. Commission applied asymmetrically

In `backtest_bridge.py` (lines 256–271): when closing a position, commission is subtracted from PnL (`net_pnl = raw_pnl - self.commission`). When opening a position, commission is added to entry price (`entry_price = next_open * (1.0 + self.commission * abs(target_position))`). This double-counts: the open commission inflates the entry price (reducing paper gain) AND the close commission is subtracted from net PnL. Round-trip costs are being applied asymmetrically, which overstates losses.

### C4. No latency model

`signals_advanced.py` computes VPIN, lead-lag correlations, and microstructure signals. These require order book data that in practice has 100ms–1s latency. The backtest assumes instantaneous signal computation and instantaneous execution. There is no end-to-end latency model.

---

## D. Regime Testing

### D1. Ring 1 precision/recall is measured against synthetic ground truth

`ring1_eval.py:Ring1Evaluator` runs with `inject_flags=True` by default. The "flags" are synthetically injected by `_inject_synthetic_flags()` using a random process calibrated to `flag_rate_target`. The "ground truth" counterfactual PnL comes from `_Ring1InstrumentedNode`, which generates random Gaussian PnL with a hardcoded `loss_rate=0.35`. The reported precision/recall numbers are properties of the injection random seed, not properties of a real adversarial model evaluated against real market outcomes.

There is no test that evaluates Ring 1 against real historically labelled losing trades.

### D2. Ablation Sharpe attribution is noise-to-noise comparison

`ablation.py:AblationHarness` uses `_AblationNode`, which generates returns as:
```python
raw = self._rng.gauss(self._base_sharpe / 252, 0.01)
```
The "full" run gets Gaussian noise with positive drift. The "ablated" run (e.g., `no_signals`) gets Gaussian noise with half the drift (`composite = self._rng.gauss(0.0, 0.04) * 0.5`). The Sharpe "attribution" computed by `compute_attribution()` is the difference in Sharpe between two RNG configurations — it measures nothing about the actual system. When `nodes=None` (the default), the ablation tells you nothing about whether real signal subsystems add alpha.

### D3. Regime detection never validated against real historical regimes

The `test_regime_detection_fires` integration test uses `SyntheticMarketNode` which outputs `"volatile"` with `changepoint_prob=0.90` after bar 200. The `RegimeTransitionHandler` correctly detects this. But this validates only that the confirmation logic works — not that the regime labelling is correct on real data. There is no test with historically labelled regime periods (e.g., 2020 COVID crash = "crisis", 2021 BTC bull = "trending").

### D4. No historical crash stress tests

None of the following real events are tested:
- March 2020 COVID crash (BTC -50% in 48 hours)
- May 2021 crypto crash (-55% drawdown)
- June 2022 LUNA collapse and 3AC liquidations
- November 2022 FTX collapse
- 2022 full crypto winter (-75% peak to trough)

All stress testing uses synthetic Gaussian data. Fat-tailed regime events cannot be captured by `rng.gauss()`.

---

## E. Adversarial Robustness

### E1. The adversarial check in production is a no-op

`orchestrator_v2.py:_step_adversarial()` (lines 490–511) flags a proposal only if `not isinstance(proposal, dict)`. Since `_step_strategy()` already filters to `isinstance(p, dict)`, no proposal can reach the adversarial step in non-dict form. The `AdversarialPressureV2` instance is accepted as a constructor argument but its logic is never invoked in `_step_adversarial()`. The variable `self._adversarial` is set but never called. The production adversarial layer provides zero actual adversarial pressure.

The test `test_adversarial_flags_occur` works around this by using `_FlagAllProposalsOrchestrator`, a subclass that overrides `_step_adversarial` to flag everything — explicitly bypassing the production code to make the test pass.

### E2. No concept drift measurement

There is no test or metric that measures model degradation when the training regime and test regime differ. The DynamicWeightAllocator tracks IC EMA but does not have a stale-signal alarm. If a signal that was predictive in 2023 becomes anti-predictive in 2024, the IC EMA will slowly decay but there is no explicit alert or circuit breaker.

### E3. All synthetic adversarial data is Gaussian

Every synthetic price series uses `rng.gauss()`. Crypto markets have return kurtosis of 5–15 (fat tails). A strategy that looks robust on Gaussian noise can catastrophically fail on a 10σ move. There is no fat-tail stress testing anywhere in the eval suite.

---

## F. Self-Improvement Validation

### F1. TPE is validated on a toy quadratic bowl, not real metrics

`tpe_eval.py:TPEEvaluator` uses `SyntheticEvaluator` from `improvement_engine.py`. The objective function is `score = -sum((param - target)^2) + gaussian_noise`. TPE will always beat random search on this — it is analytically guaranteed for smooth unimodal bowls. This tells you the TPE implementation is correct, not that it finds good trading parameters.

`ImprovementEngine._default_evaluator()` attempts to use `BacktestEvaluator` and falls back to `SyntheticEvaluator` on any exception. In practice, since the DataIngestionNode requires network access, all CI/CD runs use the synthetic evaluator. The "real" improvement loop has never been validated end-to-end.

### F2. The same OOS window is the TPE objective — it cannot detect overfitting

As noted in A3, all TPE trials in `BacktestEvaluator` score against the same calendar period. `improvement_engine.py:has_converged()` detects convergence in the TPE score series, not in generalization performance. There is no train/test Sharpe divergence monitor. A trial that perfectly overfits the 2024 OOS window would score highest and be accepted as the best configuration.

### F3. Self-improvement loop is not validated end-to-end

`test_improvement_engine_proposes` in `test_full_pipeline.py` only asserts `engine.trial_count(node_id) >= 1` — that TPE ran at least once. It does not verify that the proposed params were evaluated against real data, that the resulting Sharpe is meaningful, or that subsequent cycles performed better. The test passes trivially with the synthetic evaluator.

### F4. No overfitting detection by design

`StrategyNode.improve()` in `strategy.py` upgrades the weighting scheme based on `iteration` count and `self._last_sharpe`. `_last_sharpe` is the Sharpe from the inline backtest in `_construct_portfolio()`, which uses the same data used to generate signals. There is no held-out period to evaluate whether the new weighting scheme generalises.

---

## G. Missing Eval Categories

### G1. Monte Carlo simulation
No Monte Carlo path simulation. No bootstrap equity curve distribution. The system reports a single realised equity curve with no uncertainty bounds.

### G2. CVaR / Expected Shortfall
No tail risk metrics. Sortino ratio (`metrics.py`) is computed but CVaR at the 5th percentile is not. For a crypto strategy, VaR dramatically underestimates tail risk.

### G3. Regime-conditional performance breakdown
No decomposition of Sharpe by regime (trending/ranging/high-vol). The `EvalReport` has a single Sharpe, not "Sharpe during trending = 1.8, Sharpe during ranging = -0.3."

### G4. Capacity and liquidity analysis
No analysis of maximum AUM before market impact degrades performance. No position size limits linked to average daily volume. The signals in `signals_advanced.py` include VPIN and order flow, but these are never used to size positions or estimate market impact.

### G5. Turnover analysis
No turnover metric (e.g., daily turnover as % of portfolio). High-frequency signal changes could produce 100%+ annual turnover, which at 10bps per trade would destroy any Sharpe below 1.5.

### G6. Live/backtest reconciliation
No framework to compare live (or paper trading) P&L against backtest predictions bar-by-bar. There is no "backtest vs live divergence" alert.

### G7. Factor exposure analysis
No regression of returns against standard factors (crypto market beta, size, momentum, liquidity). All alpha claims could be disguised beta.

### G8. Correlation analysis between strategies/signals
`dynamic_weights.py` weights signals by IC, but there is no analysis of signal correlations. If 3 of the 4 signals are highly correlated (e.g., order flow, microstructure, and sentiment all spike in the same crash), diversification is illusory.

---

## H. Integration Gaps

### H1. Integration tests use a stub node, not the real VictoriaNode

Every test in `tests/integration/test_full_pipeline.py` and `test_feedback_loop.py` uses `SyntheticMarketNode` from `conftest.py`. The real `VictoriaNode` with `signals_advanced.py`, `dynamic_weights.py`, and real data ingestion is never exercised in integration tests. The "no mocking of core logic" claim in the test file docstring is inaccurate — `SyntheticMarketNode` is an equivalent mock.

### H2. The backtest bridge injects data via a private attribute

`backtest_bridge.py` line 214: `self._node._last_market_data = market_data`. This accesses a private attribute of `VictoriaNode` that is not part of the `Node` interface. There is no contract that this attribute exists or is respected. If `VictoriaNode` is refactored, the bridge silently breaks without any test catching it.

### H3. AdversarialPressureV2 is wired in tests but not in production cycles

`test_adversarial_flags_occur` passes `adversarial=AdversarialPressureV2()` to the orchestrator but then overrides `_step_adversarial()` in the test. `test_feedback_loop.py` passes `AdversarialPressureV2()` to the real orchestrator, but the orchestrator's `_step_adversarial()` never invokes it. The adversarial object exists in the constructor but is unused.

### H4. Memory consolidation is tested with pre-seeded records, not real cycle output

`test_memory_consolidation_runs` pre-populates `pipeline._short_term` with 20 hand-crafted `MemoryRecord` objects and then runs 30 cycles. It does not test whether cycles actually produce memories that get consolidated. The consolidation pipeline is tested in isolation, not as part of the live cycle feedback loop.

### H5. TPE evaluator silently uses synthetic data in all automated runs

The `_default_evaluator()` in `ImprovementEngine` catches all exceptions from `BacktestEvaluator` and falls back to `SyntheticEvaluator`. Since `DataIngestionNode` requires network access, every test environment uses the synthetic evaluator. There is no log warning at ERROR level and no test assertion that verifies which evaluator was actually used. TPE "improvement" in CI is always measuring improvement on a synthetic quadratic bowl.

---

## I. Industry Comparison: What a Quant Fund Requires Before Going Live

A systematic fund's risk committee would require the following before allocating capital. None of these are currently present:

| Requirement | Status in Omega |
|---|---|
| 5+ years of real tick/OHLCV data, multiple regimes | Synthetic LCG data with silent fallback |
| Expanding or rolling walk-forward with truly held-out test set | Fixed calendar OOS window used as TPE objective |
| Bootstrap CIs on all key metrics (Sharpe, drawdown, win rate) | CI function exists, never called in reports |
| Multiple-comparison correction for parameter search | None |
| Transaction cost model including market impact | Flat 10bps, no impact model |
| Tick-level execution simulation | Bar-level only; entry at same-bar close in backtest.py |
| Scenario analysis against real crash dates | None; all stress data is Gaussian |
| Kill-switch and circuit-breaker testing | Not tested |
| Position and concentration limits | No AUM or concentration caps |
| Risk decomposition: factor exposures | None |
| Paper trading period with live/backtest reconciliation | No framework for this |
| Full audit trail for signals and orders | Logging only; no immutable audit log |
| Capacity and liquidity analysis | None |
| Regime-conditional Sharpe breakdown | Not in EvalReport |
| Tail risk metrics (CVaR, ES) | Not computed |
| Signal correlation and diversification analysis | None |
| Statistically significant alpha vs benchmarks (corrected p-value) | Single t-test, no correction |

### The Core Problem

The framework confuses **operational correctness** (does the pipeline run without errors?) with **statistical validity** (is the measured alpha real?). The integration tests verify the former thoroughly. The eval modules address the latter in their interface design but not in their implementation: the CI function is never called, the OOS window is contaminated, the ablation uses synthetic noise, the adversarial layer is a no-op, and the improvement loop optimises on a toy bowl.

The most dangerous gap is the silent synthetic data fallback. Every Sharpe number produced in development is a function of an LCG seed, not market microstructure. A team that reads `EvalReport(sharpe=1.4)` and sees no red flag — because the system logged no warning — will draw incorrect conclusions about strategy viability.

**Minimum viable fixes to make the eval honest:**
1. Fail loudly (not silently) when real data is unavailable; mark all synthetic-data results as INVALID.
2. Add a mandatory third split: train/validate(OOS for TPE)/test(never seen by TPE).
3. Call `compute_sharpe_confidence_interval()` and include the CI in every `EvalReport`.
4. Fix `backtest.py`'s entry-at-signal-close look-ahead (use next bar's open).
5. Fix the multiplicative equity curve in `backtest.py:_compute_metrics()`.
6. Implement real adversarial logic in `orchestrator_v2._step_adversarial()`.
7. Run `AblationHarness` against the real `VictoriaNode` on real data, not `_AblationNode` on Gaussian noise.
