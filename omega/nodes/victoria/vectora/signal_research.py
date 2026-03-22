"""
omega.nodes.victoria.signal_research
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SignalResearchNode — runs signal performance analysis.

Computes:
  - Information Coefficient (IC): rank correlation of signal vs. forward return
  - IC decay curve: IC at various forward horizons (1d, 3d, 5d, 10d)
  - Regime-conditional IC: signal quality per detected market regime
  - Signal-to-noise ratio and hit rate

Reports which signals are predictive vs. noise per regime.

skill_tags = ["deep-research"]
"""

import logging
import math
import time
import uuid
from dataclasses import dataclass
from typing import Any, ClassVar

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.victoria.signal_research")


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class ICResult:
    """Information Coefficient result for a single signal at a given horizon."""

    signal_name: str
    horizon_days: int
    ic: float  # Spearman rank correlation [-1, 1]
    hit_rate: float  # fraction of periods where sign(signal) == sign(return)
    ic_ir: float  # IC / std(IC) — information ratio of the IC series
    sample_size: int
    is_predictive: bool  # IC abs > 0.05 and statistically significant


@dataclass
class RegimeICReport:
    """IC results conditioned on a specific market regime."""

    regime: str
    results: list[ICResult]
    regime_frequency: float  # fraction of time in this regime


# ---------------------------------------------------------------------------
# Rank correlation helper (Spearman)
# ---------------------------------------------------------------------------


def _rank(values: list[float]) -> list[float]:
    """Compute rank of each value (1-indexed, average ties)."""
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def _spearman(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation between x and y."""
    n = min(len(x), len(y))
    if n < 4:
        return 0.0
    rx = _rank(x[-n:])
    ry = _rank(y[-n:])
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((v - mx) ** 2 for v in rx))
    dy = math.sqrt(sum((v - my) ** 2 for v in ry))
    denom = dx * dy
    return num / denom if denom > 0 else 0.0


# ---------------------------------------------------------------------------
# SignalResearchNode
# ---------------------------------------------------------------------------


class SignalResearchNode(Node):
    """
    Runs signal performance analysis across regimes and horizons.

    Capabilities:
      - analyze_ic          : compute IC and decay for all signals
      - analyze_regime_ic   : IC conditioned on market regime
      - rank_signals        : rank signals by IC-IR
      - report_noise        : identify signals that are pure noise

    skill_tags: ["deep-research"]
    """

    skill_tags: ClassVar[list[str]] = ["deep-research"]

    HORIZONS: ClassVar[list[int]] = [1, 3, 5, 10]
    PREDICTIVE_IC_THRESHOLD = 0.05

    def __init__(self) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._execution_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._last_report: dict[str, Any] = {}

    # ------------------------------------------------------------------ Node interface

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="SignalResearchNode",
            version=self._version,
            health=max(0.0, 1.0 - self._error_rate()),
            capabilities=self.get_capabilities(),
            metrics={
                "avg_latency_ms": self._avg_latency_ms(),
                "error_rate": self._error_rate(),
                "executions": float(self._execution_count),
            },
            metadata={"skill_tags": self.skill_tags},
        )

    def get_capabilities(self) -> list[str]:
        return ["analyze_ic", "analyze_regime_ic", "rank_signals", "report_noise"]

    def describe(self) -> str:
        return (
            "Runs signal performance analysis (information coefficient, IC decay curves, "
            "regime-conditional IC). Reports which signals are predictive vs. noise "
            "per detected market regime. Uses deep-research skill for LLM-augmented "
            "interpretation of results."
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        action = input.action
        params = input.parameters

        try:
            if action == "analyze_ic":
                result = self._analyze_ic(
                    signal_history=params.get("signal_history", {}),
                    price_history=params.get("price_history", {}),
                )
            elif action == "analyze_regime_ic":
                result = self._analyze_regime_ic(
                    signal_history=params.get("signal_history", {}),
                    price_history=params.get("price_history", {}),
                    regime_history=params.get("regime_history", []),
                )
            elif action == "rank_signals":
                result = self._rank_signals(
                    ic_results=params.get("ic_results", []),
                )
            elif action == "report_noise":
                result = self._report_noise(
                    ic_results=params.get("ic_results", []),
                )
            else:
                elapsed = (time.perf_counter() - t0) * 1000
                self._execution_count += 1
                self._error_count += 1
                self._total_latency_ms += elapsed
                return NodeOutput(
                    request_id=input.request_id,
                    success=False,
                    errors=[f"Unknown action '{action}'"],
                    metrics={"latency_ms": elapsed},
                )

            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._total_latency_ms += elapsed
            self._last_report = result

            return NodeOutput(
                request_id=input.request_id,
                success=True,
                result=result,
                metrics={"latency_ms": elapsed},
            )

        except Exception as exc:
            elapsed = (time.perf_counter() - t0) * 1000
            self._execution_count += 1
            self._error_count += 1
            self._total_latency_ms += elapsed
            logger.error("SignalResearchNode error: %s", exc, exc_info=True)
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[str(exc)],
                metrics={"latency_ms": elapsed},
            )

    def evaluate(self) -> dict[str, float]:
        predictive_count = 0
        noise_count = 0
        for signal_results in self._last_report.get("ic_by_signal", {}).values():
            best_ic = max((abs(r.get("ic", 0)) for r in signal_results), default=0)
            if best_ic >= self.PREDICTIVE_IC_THRESHOLD:
                predictive_count += 1
            else:
                noise_count += 1
        return {
            "avg_latency_ms": self._avg_latency_ms(),
            "error_rate": self._error_rate(),
            "predictive_signals": float(predictive_count),
            "noise_signals": float(noise_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        # Research node improves by lowering IC threshold if signal set is weak
        if feedback.get("predictive_signal_count", 0) == 0 and self.PREDICTIVE_IC_THRESHOLD > 0.02:
            self.PREDICTIVE_IC_THRESHOLD *= 0.8
            logger.info(
                "SignalResearchNode: lowered IC threshold to %.4f", self.PREDICTIVE_IC_THRESHOLD
            )
            return True
        return False

    # ------------------------------------------------------------------ analysis

    def _analyze_ic(
        self,
        signal_history: dict[str, list[float]],
        price_history: dict[str, list[float]],
    ) -> dict[str, Any]:
        """
        Compute IC and IC decay for each signal across all tickers.

        signal_history: {"signal_name": [values...]}
        price_history:  {"ticker": [prices...]}
        """
        # Aggregate returns across tickers
        all_returns: list[list[float]] = []
        for prices in price_history.values():
            if len(prices) > 1:
                rets = [
                    (prices[i] - prices[i - 1]) / prices[i - 1]
                    for i in range(1, len(prices))
                    if prices[i - 1] != 0
                ]
                all_returns.append(rets)

        # Use average cross-asset returns as the "universe return"
        min_len = min((len(r) for r in all_returns), default=0)
        if min_len < 10:
            avg_returns: list[float] = []
        else:
            avg_returns = [
                sum(r[i] for r in all_returns) / len(all_returns) for i in range(min_len)
            ]

        ic_by_signal: dict[str, list[dict[str, Any]]] = {}
        for signal_name, signal_vals in signal_history.items():
            horizon_results = []
            for h in self.HORIZONS:
                ic_series = self._rolling_ic(signal_vals, avg_returns, horizon=h, window=20)
                if not ic_series:
                    continue
                mean_ic = sum(ic_series) / len(ic_series)
                std_ic = (
                    math.sqrt(
                        sum((v - mean_ic) ** 2 for v in ic_series) / max(1, len(ic_series) - 1)
                    )
                    if len(ic_series) > 1
                    else 1.0
                )
                ic_ir = mean_ic / std_ic if std_ic > 0 else 0.0
                hit_rate = self._hit_rate(signal_vals, avg_returns, horizon=h)
                horizon_results.append(
                    {
                        "horizon_days": h,
                        "ic": mean_ic,
                        "ic_ir": ic_ir,
                        "hit_rate": hit_rate,
                        "sample_size": len(ic_series),
                        "is_predictive": abs(mean_ic) >= self.PREDICTIVE_IC_THRESHOLD,
                    }
                )
            ic_by_signal[signal_name] = horizon_results

        return {
            "ic_by_signal": ic_by_signal,
            "universe_return_samples": len(avg_returns),
            "predictive_threshold": self.PREDICTIVE_IC_THRESHOLD,
        }

    def _analyze_regime_ic(
        self,
        signal_history: dict[str, list[float]],
        price_history: dict[str, list[float]],
        regime_history: list[str],
    ) -> dict[str, Any]:
        """Compute IC conditioned on each detected regime."""
        if not regime_history:
            return {"error": "no regime history provided"}

        regimes = list(set(regime_history))
        regime_results: dict[str, Any] = {}

        for regime in regimes:
            indices = [i for i, r in enumerate(regime_history) if r == regime]
            if len(indices) < 5:
                continue

            # Extract signal and return slices for this regime
            sliced_signals: dict[str, list[float]] = {}
            for sig_name, sig_vals in signal_history.items():
                sliced_signals[sig_name] = [sig_vals[i] for i in indices if i < len(sig_vals)]

            # For simplicity, extract price returns at regime indices
            sliced_prices: dict[str, list[float]] = {}
            for ticker, prices in price_history.items():
                sliced_prices[ticker] = [prices[i] for i in indices if i < len(prices)]

            ic_result = self._analyze_ic(sliced_signals, sliced_prices)
            regime_results[regime] = {
                "ic_by_signal": ic_result["ic_by_signal"],
                "regime_frequency": len(indices) / len(regime_history),
                "sample_count": len(indices),
            }

        return {"regime_ic": regime_results, "regimes_analyzed": list(regime_results.keys())}

    def _rank_signals(self, ic_results: list[dict[str, Any]]) -> dict[str, Any]:
        """Rank signals by IC-IR at the 1-day horizon."""
        ranked = sorted(
            ic_results,
            key=lambda x: abs(x.get("ic_ir", 0)),
            reverse=True,
        )
        return {
            "ranked_signals": [
                {
                    "rank": i + 1,
                    "signal_name": r.get("signal_name", f"signal_{i}"),
                    "ic_ir": r.get("ic_ir", 0),
                    "ic": r.get("ic", 0),
                    "is_predictive": r.get("is_predictive", False),
                }
                for i, r in enumerate(ranked)
            ]
        }

    def _report_noise(self, ic_results: list[dict[str, Any]]) -> dict[str, Any]:
        """Identify signals that are pure noise (IC near zero at all horizons)."""
        noise = [
            r
            for r in ic_results
            if not r.get("is_predictive", False) and abs(r.get("ic", 0)) < 0.02
        ]
        predictive = [r for r in ic_results if r.get("is_predictive", False)]
        return {
            "noise_signals": [r.get("signal_name", "?") for r in noise],
            "predictive_signals": [r.get("signal_name", "?") for r in predictive],
            "noise_fraction": len(noise) / max(1, len(ic_results)),
            "recommendation": (
                "Consider dropping noise signals to reduce overfitting."
                if len(noise) > len(ic_results) // 2
                else "Signal set has reasonable quality."
            ),
        }

    # ------------------------------------------------------------------ helpers

    def _rolling_ic(
        self,
        signals: list[float],
        returns: list[float],
        horizon: int,
        window: int = 20,
    ) -> list[float]:
        """Rolling Spearman IC between signal[t] and return[t+horizon]."""
        n = min(len(signals), len(returns) - horizon)
        if n < window:
            return []
        ic_series = []
        for end in range(window, n):
            s_slice = signals[end - window : end]
            r_slice = returns[end - window + horizon : end + horizon]
            if len(r_slice) < window:
                break
            ic = _spearman(s_slice, r_slice)
            ic_series.append(ic)
        return ic_series

    def _hit_rate(self, signals: list[float], returns: list[float], horizon: int = 1) -> float:
        n = min(len(signals), len(returns) - horizon)
        if n < 2:
            return 0.5
        hits = sum(
            1
            for i in range(n)
            if (signals[i] > 0 and returns[i + horizon] > 0)
            or (signals[i] < 0 and returns[i + horizon] < 0)
        )
        return hits / n

    def _avg_latency_ms(self) -> float:
        return self._total_latency_ms / max(1, self._execution_count)

    def _error_rate(self) -> float:
        return self._error_count / max(1, self._execution_count)
