"""omega.core.improvement_engine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Improvement engine that uses TreeParzenEstimator to propose node parameter
changes and evaluates them against Sharpe ratio and drawdown metrics.

Design
------
- Each node gets its own TPE instance keyed by node_id.
- Candidate parameters are proposed, evaluated via ImprovementEvaluator,
  then either accepted (observed with positive score) or rejected (negative).
- History and best configs are persisted via StateStore.
"""

from __future__ import annotations

import logging
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from omega.core.bayesian_optimizer import (
    Param,
    TreeParzenEstimator,
)
from omega.core.convergence import ConvergenceDiagnostics
from omega.core.state_store import StateStore

logger = logging.getLogger("omega.core.improvement_engine")


def _sharpe_ratio(returns: list[float]) -> float:
    """Annualised Sharpe ratio. Returns 0.0 for empty/single-element inputs."""
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0.0:
        return 0.0
    return (mean / std) * math.sqrt(252)


def _max_drawdown(equity_curve: list[float]) -> float:
    """Maximum peak-to-trough drawdown (0..1, lower is worse → returned as negative)."""
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve[1:]:
        if v > peak:
            peak = v
        dd = (peak - v) / max(peak, 1e-12)
        if dd > max_dd:
            max_dd = dd
    return -max_dd  # negative so higher is better


def composite_score(
    sharpe: float,
    max_drawdown_negative: float,
    sharpe_weight: float = 0.7,
    dd_weight: float = 0.3,
) -> float:
    """Blend Sharpe and drawdown into a single scalar. Higher = better."""
    return sharpe_weight * sharpe + dd_weight * max_drawdown_negative


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ImprovementTrial:
    trial_id: str
    node_id: str
    params: dict[str, Any]
    score: float | None = None
    accepted: bool = False
    timestamp: float = field(default_factory=time.time)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeParamHistory:
    node_id: str
    param_space: list[Param]
    trials: list[ImprovementTrial] = field(default_factory=list)
    best_params: dict[str, Any] | None = None
    best_score: float = -math.inf


# ---------------------------------------------------------------------------
# Evaluator interface
# ---------------------------------------------------------------------------


class ImprovementEvaluator:
    """
    Evaluate a parameter configuration for a node.

    Override this base class to plug in real backtests, live paper-trading,
    or simulation. The default implementation returns a synthetic score so
    unit tests run without infrastructure.
    """

    def evaluate(
        self,
        node_id: str,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> tuple[float, dict[str, Any]]:
        """
        Returns (score, metrics_dict).

        score: higher is better. Should be normalised around 0.
        metrics_dict: arbitrary metrics for logging/storage.
        """
        raise NotImplementedError


class SyntheticEvaluator(ImprovementEvaluator):
    """
    Deterministic synthetic evaluator used in tests and demos.

    Uses a noisy quadratic bowl centred on target_params.
    Stdlib-only: uses random.Random for reproducibility.
    """

    def __init__(
        self,
        target_params: dict[str, float] | None = None,
        noise: float = 0.05,
        seed: int = 42,
    ) -> None:
        self._target = target_params or {}
        self._noise = noise
        self._rng = random.Random(seed)

    def evaluate(
        self,
        node_id: str,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> tuple[float, dict[str, Any]]:
        loss = 0.0
        for k, target in self._target.items():
            v = float(params.get(k, 0.0))
            loss += (v - target) ** 2
        noise_val = self._rng.gauss(0, self._noise) if self._noise > 0 else 0.0
        score = -loss + noise_val

        # Simulate 252 daily returns from a simple model
        n = 252
        mu = max(-0.3, min(0.3, score * 0.1))
        returns = [self._rng.gauss(mu / n, 0.01) for _ in range(n)]
        equity = [1.0]
        for r in returns:
            equity.append(equity[-1] * (1 + r))

        from omega.eval.sharpe import sharpe_ratio as _sharpe_ratio

        sharpe = _sharpe_ratio(returns)
        mdd = _max_drawdown(equity)

        metrics = {
            "sharpe": round(sharpe, 4),
            "max_drawdown": round(mdd, 4),
            "composite": round(composite_score(sharpe, mdd), 4),
        }
        return score, metrics


# ---------------------------------------------------------------------------
# ImprovementEngine
# ---------------------------------------------------------------------------


class ImprovementEngine:
    """
    Orchestrates TPE-based hyperparameter improvement for nodes.

    Usage::

        engine = ImprovementEngine(store=state_store)
        engine.register_node("node-123", param_space=[...])
        params = engine.propose("node-123")
        score, metrics = evaluator.evaluate("node-123", params)
        engine.record_outcome("node-123", params, score, metrics, accepted=(score > threshold))
    """

    def __init__(
        self,
        store: StateStore | None = None,
        evaluator: ImprovementEvaluator | None = None,
        gamma: float = 0.25,
        n_startup_trials: int = 10,
        seed: int | None = None,
        convergence_window: int = 20,
        convergence_epsilon: float = 0.01,
    ) -> None:
        self._store = store
        self._evaluator = evaluator or self._default_evaluator()
        self._gamma = gamma
        self._n_startup = n_startup_trials
        self._seed = seed

        # node_id -> NodeParamHistory
        self._histories: dict[str, NodeParamHistory] = {}
        # node_id -> TreeParzenEstimator
        self._optimizers: dict[str, TreeParzenEstimator] = {}
        # node_id -> ConvergenceDiagnostics
        self._convergence: dict[str, ConvergenceDiagnostics] = {}
        self._conv_window = convergence_window
        self._conv_epsilon = convergence_epsilon

    @staticmethod
    def _default_evaluator() -> ImprovementEvaluator:
        """Return BridgeEvaluator (honest walk-forward) when data is available,
        then BacktestEvaluator, then SyntheticEvaluator as final fallback."""
        try:
            from omega.core.bridge_evaluator import BridgeEvaluator
            from omega.core.node import NodeInput
            from omega.nodes.vectora.data_ingestion import DataIngestionNode

            node = DataIngestionNode()
            inp = NodeInput(
                action="ingest",
                parameters={
                    "symbols": ["BTCUSDT"],
                    "start_date": "2023-01-01",
                    "end_date": "2024-12-31",
                },
            )
            out = node.execute(inp)
            rows = out.result.get("data", {}).get("BTCUSDT", [])
            if len(rows) >= 200:
                ohlcv = [
                    {
                        "timestamp": i,
                        "open": float(r.get("open", r.get("close", 0))),
                        "high": float(r.get("high", r.get("close", 0))),
                        "low": float(r.get("low", r.get("close", 0))),
                        "close": float(r.get("close", 0)),
                        "volume": float(r.get("volume", 0)),
                    }
                    for i, r in enumerate(rows)
                ]
                return BridgeEvaluator(ohlcv=ohlcv)
        except Exception:
            pass

        try:
            from omega.core.backtest_evaluator import BacktestEvaluator

            return BacktestEvaluator()
        except Exception:
            return SyntheticEvaluator()

    def set_evaluator(self, evaluator: ImprovementEvaluator) -> None:
        """Replace the active evaluator at runtime."""
        self._evaluator = evaluator

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_node(
        self,
        node_id: str,
        param_space: list[Param],
        prior_trials: list[tuple[dict[str, Any], float]] | None = None,
    ) -> None:
        """Register a node with its parameter space and optional warm-start trials."""
        history = NodeParamHistory(node_id=node_id, param_space=param_space)
        tpe = TreeParzenEstimator(
            param_space=param_space,
            gamma=self._gamma,
            n_startup_trials=self._n_startup,
            seed=self._seed,
        )
        if prior_trials:
            tpe.fit(prior_trials)
            history.trials = [
                ImprovementTrial(
                    trial_id=str(uuid.uuid4()),
                    node_id=node_id,
                    params=p,
                    score=s,
                    accepted=True,
                )
                for p, s in prior_trials
            ]
            if prior_trials:
                best_p, best_s = max(prior_trials, key=lambda t: t[1])
                history.best_params = best_p
                history.best_score = best_s

        self._histories[node_id] = history
        self._optimizers[node_id] = tpe
        self._convergence[node_id] = ConvergenceDiagnostics(
            epsilon=self._conv_epsilon, window=self._conv_window
        )
        # Seed convergence tracker with any prior trials
        if prior_trials:
            for _, s in prior_trials:
                self._convergence[node_id].record(s)
        logger.info("Registered node %s with %d params", node_id, len(param_space))

    def is_registered(self, node_id: str) -> bool:
        return node_id in self._optimizers

    # ------------------------------------------------------------------
    # Core cycle
    # ------------------------------------------------------------------

    def propose(self, node_id: str) -> dict[str, Any]:
        """Propose next parameter configuration for a node."""
        if node_id not in self._optimizers:
            raise KeyError(f"Node {node_id!r} not registered. Call register_node() first.")
        params = self._optimizers[node_id].suggest()
        logger.debug("Proposed params for %s: %s", node_id, params)
        return params

    def evaluate_and_record(
        self,
        node_id: str,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
        acceptance_threshold: float = 0.0,
        cycle: int = 0,
    ) -> ImprovementTrial:
        """
        Evaluate params with the configured evaluator, record outcome,
        persist to StateStore if available.
        """
        score, metrics = self._evaluator.evaluate(node_id, params, context)
        accepted = score >= acceptance_threshold
        trial = self.record_outcome(node_id, params, score, metrics, accepted)

        if self._store is not None:
            try:
                self._persist_trial(trial, cycle)
            except Exception as exc:
                logger.warning("Failed to persist trial to StateStore: %s", exc)

        return trial

    def record_outcome(
        self,
        node_id: str,
        params: dict[str, Any],
        score: float,
        metrics: dict[str, Any] | None = None,
        accepted: bool = True,
    ) -> ImprovementTrial:
        """Record the outcome of a trial without re-evaluating."""
        if node_id not in self._optimizers:
            raise KeyError(f"Node {node_id!r} not registered.")

        trial = ImprovementTrial(
            trial_id=str(uuid.uuid4()),
            node_id=node_id,
            params=params,
            score=score,
            accepted=accepted,
            metrics=metrics or {},
        )

        self._optimizers[node_id].observe(params, score)
        self._histories[node_id].trials.append(trial)
        self._convergence[node_id].record(score)

        history = self._histories[node_id]
        if score > history.best_score:
            history.best_score = score
            history.best_params = params
            logger.info("New best for node %s: score=%.4f params=%s", node_id, score, params)

        return trial

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def best_params(self, node_id: str) -> dict[str, Any] | None:
        h = self._histories.get(node_id)
        return h.best_params if h else None

    def best_score(self, node_id: str) -> float:
        h = self._histories.get(node_id)
        return h.best_score if h else -math.inf

    def trial_count(self, node_id: str) -> int:
        h = self._histories.get(node_id)
        return len(h.trials) if h else 0

    def recent_trials(self, node_id: str, n: int = 10) -> list[ImprovementTrial]:
        h = self._histories.get(node_id)
        if not h:
            return []
        return h.trials[-n:]

    def all_node_ids(self) -> list[str]:
        return list(self._histories.keys())

    def has_converged(
        self,
        node_id: str,
        epsilon: float | None = None,
        window: int | None = None,
    ) -> bool:
        """
        Return True when the improvement rate for ``node_id`` has plateaued.

        Requires at least ``window`` recorded trials.
        """
        diag = self._convergence.get(node_id)
        if diag is None:
            return False
        return diag.has_converged(epsilon=epsilon, window=window)

    def improvement_rate(self, node_id: str, window: int | None = None) -> float:
        """Mean score improvement per trial over the last ``window`` trials."""
        diag = self._convergence.get(node_id)
        if diag is None:
            return 0.0
        return diag.improvement_rate(window)

    def convergence_diagnostics(self, node_id: str) -> ConvergenceDiagnostics | None:
        """Direct access to the ConvergenceDiagnostics object for a node."""
        return self._convergence.get(node_id)

    def sharpe_trend(self, node_id: str, window: int = 20) -> str:
        """Return 'improving', 'degrading', or 'stable' from recent Sharpe scores."""
        h = self._histories.get(node_id)
        if not h or len(h.trials) < 2:
            return "stable"
        sharpes = [
            t.metrics.get("sharpe", t.score) for t in h.trials[-window:] if t.score is not None
        ]
        if len(sharpes) < 2:
            return "stable"
        delta = sharpes[-1] - sharpes[0]
        magnitude = abs(delta) / max(abs(sharpes[0]), 1e-9) * 100
        if magnitude < 5:
            return "stable"
        return "improving" if delta > 0 else "degrading"

    # ------------------------------------------------------------------
    # StateStore persistence
    # ------------------------------------------------------------------

    def _persist_trial(self, trial: ImprovementTrial, cycle: int) -> None:
        """Write trial outcome to StateStore improvement_history if supported."""
        if not hasattr(self._store, "record_improvement"):
            return
        after_metrics = {
            "params": str(trial.params),
            "score": trial.score,
            "accepted": trial.accepted,
            **trial.metrics,
        }
        store: Any = self._store
        store.record_improvement(
            node_id=trial.node_id,
            node_name=trial.node_id,
            from_version="pre-tpe",
            to_version=f"tpe-{trial.trial_id[:8]}",
            before_metrics=None,
            after_metrics=after_metrics,
            triggered_by="tpe",
            cycle=cycle,
        )
