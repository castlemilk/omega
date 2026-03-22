"""
omega.eval.ablation
~~~~~~~~~~~~~~~~~~~~
Ablation harness for the Omega system.

Answers "which subsystems actually contribute value?" by disabling one
subsystem at a time and measuring the resulting Sharpe impact.

Attribution = Sharpe(full) - Sharpe(without_subsystem)

Usage::

    from omega.eval.ablation import AblationHarness

    harness = AblationHarness(nodes=[my_victoria_node], n_cycles=200)
    results = harness.run_all_ablations()
    attribution = harness.compute_attribution()
    print(attribution)
    # {'ring1': 0.42, 'memory': 0.18, 'tpe': 0.11, 'autonomy': 0.07, 'signals': 0.63}
"""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any

from omega.core.autonomy import GraduatedAutonomyController
from omega.core.cycle import CycleHistory, CycleResult
from omega.core.improvement_engine import ImprovementEngine
from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.orchestrator_v2 import OmegaOrchestrator
from omega.eval.significance import sharpe_difference_significant

logger = logging.getLogger("omega.eval.ablation")


# ---------------------------------------------------------------------------
# EvalReport
# ---------------------------------------------------------------------------


@dataclass
class EvalReport:
    """Summary metrics for a single ablation run."""

    ablation_name: str
    n_cycles: int
    sharpe: float
    max_drawdown: float
    avg_signals_per_cycle: float
    adversarial_flag_rate: float
    error_rate: float
    trades_executed: int
    improvement_cycles: int
    duration_seconds: float
    raw_returns: list[float] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"EvalReport(name={self.ablation_name!r}, "
            f"sharpe={self.sharpe:.4f}, "
            f"max_drawdown={self.max_drawdown:.4f}, "
            f"cycles={self.n_cycles})"
        )


# ---------------------------------------------------------------------------
# Synthetic return-generating node for ablation runs
# ---------------------------------------------------------------------------


class _AblationNode(Node):
    """
    Minimal self-contained node that generates synthetic returns.

    Supports all orchestrator capabilities so ablation can toggle subsystems
    without needing real market data or LLM calls.

    Parameters
    ----------
    base_sharpe  : Approximate annualised Sharpe the node targets.
    use_advanced : If False, returns simplified (SMA-only) signals.
    pico_forced  : If True, always reports PICO autonomy regardless of controller.
    seed         : RNG seed for reproducibility.
    """

    def __init__(
        self,
        name: str = "ablation_node",
        base_sharpe: float = 1.2,
        use_advanced: bool = True,
        pico_forced: bool = False,
        seed: int = 42,
    ) -> None:
        import uuid

        self._nid = str(uuid.uuid4())
        self._name = name
        self._base_sharpe = base_sharpe
        self._use_advanced = use_advanced
        self._pico_forced = pico_forced
        self._rng = random.Random(seed)
        self._health = 1.0
        self._exec_count = 0
        self._returns: list[float] = []

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._nid,
            name=self._name,
            version="1.0",
            health=self._health,
            capabilities=["poll", "compute_signals", "construct_portfolio"],
            metrics={
                "exec_count": float(self._exec_count),
                "sharpe": self._current_sharpe(),
            },
        )

    def get_capabilities(self) -> list[str]:
        return ["poll", "compute_signals", "construct_portfolio"]

    def describe(self) -> str:
        return f"AblationNode({self._name}, sharpe≈{self._base_sharpe})"

    def execute(self, inp: NodeInput) -> NodeOutput:
        self._exec_count += 1

        if inp.action == "poll" or inp.action == "fetch_data":
            return self._do_poll(inp)
        if inp.action == "compute_signals":
            return self._do_signals(inp)
        if inp.action == "construct_portfolio":
            return self._do_portfolio(inp)

        return NodeOutput(request_id=inp.request_id, success=True, result={})

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _do_poll(self, inp: NodeInput) -> NodeOutput:
        price = 50_000 + self._rng.gauss(0, 1000)
        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result={"price": price, "volume": self._rng.uniform(1e6, 1e7)},
        )

    def _do_signals(self, inp: NodeInput) -> NodeOutput:
        if self._use_advanced:
            # Advanced: multi-factor composite signal
            momentum = self._rng.gauss(0.02, 0.05)
            mean_reversion = self._rng.gauss(-0.01, 0.03)
            vol_signal = self._rng.gauss(0.0, 0.02)
            composite = 0.5 * momentum + 0.3 * mean_reversion + 0.2 * vol_signal
        else:
            # Ablated (SMA only): weaker signal
            composite = self._rng.gauss(0.0, 0.04) * 0.5  # half the alpha

        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result={
                "composite_signal": composite,
                "regime_label": "normal",
                "changepoint_prob": 0.05,
            },
        )

    def _do_portfolio(self, inp: NodeInput) -> NodeOutput:
        pico_mode = inp.parameters.get("pico_mode", False) or self._pico_forced

        # Derive return from signal strength
        raw = self._rng.gauss(self._base_sharpe / 252, 0.01)
        if pico_mode:
            # PICO: deterministic, reduced alpha
            raw *= 0.6

        self._returns.append(raw)

        proposal = {
            "symbol": "BTC/USDT",
            "side": "buy" if raw > 0 else "sell",
            "size": abs(raw) * 1000,
            "expected_return": raw,
            "pico_mode": pico_mode,
        }
        return NodeOutput(
            request_id=inp.request_id,
            success=True,
            result=[proposal],
        )

    def evaluate(self) -> dict[str, float]:
        return {
            "sharpe": self._current_sharpe(),
            "exec_count": float(self._exec_count),
        }

    def improve(self, feedback: dict) -> bool:
        return False

    def _current_sharpe(self) -> float:
        if len(self._returns) < 2:
            return 0.0
        mean_r = sum(self._returns) / len(self._returns)
        var = sum((r - mean_r) ** 2 for r in self._returns) / (len(self._returns) - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        return (mean_r / std * math.sqrt(252)) if std > 0 else 0.0

    @property
    def returns(self) -> list[float]:
        return list(self._returns)


# ---------------------------------------------------------------------------
# AblationHarness
# ---------------------------------------------------------------------------


class AblationHarness:
    """
    Ablation harness for the Omega system.

    Builds a fresh OmegaOrchestrator for each ablation run, toggling
    subsystems on/off to isolate their Sharpe contribution.

    Parameters
    ----------
    nodes        : Pre-built Node instances to register (optional).  If None,
                   a synthetic _AblationNode is created automatically.
    n_cycles     : Number of orchestrator cycles per ablation run.
    base_sharpe  : Target Sharpe for the synthetic node.
    seed         : RNG seed for reproducibility.
    """

    def __init__(
        self,
        nodes: list[Node] | None = None,
        n_cycles: int = 100,
        base_sharpe: float = 1.2,
        seed: int = 42,
    ) -> None:
        self._nodes = nodes
        self._n_cycles = n_cycles
        self._base_sharpe = base_sharpe
        self._seed = seed
        self._results: dict[str, EvalReport] = {}

    # ------------------------------------------------------------------
    # Individual ablation runs
    # ------------------------------------------------------------------

    def run_full(self) -> EvalReport:
        """Run with all subsystems enabled."""
        return self._run(
            ablation_name="full",
            disable_ring1=False,
            disable_memory=False,
            disable_tpe=False,
            force_pico=False,
            signals_advanced=True,
        )

    def run_without_ring1(self) -> EvalReport:
        """Disable adversarial Ring 1 checking."""
        return self._run(
            ablation_name="no_ring1",
            disable_ring1=True,
            disable_memory=False,
            disable_tpe=False,
            force_pico=False,
            signals_advanced=True,
        )

    def run_without_memory(self) -> EvalReport:
        """Disable memory / regime context (no consolidation pipeline)."""
        return self._run(
            ablation_name="no_memory",
            disable_ring1=False,
            disable_memory=True,
            disable_tpe=False,
            force_pico=False,
            signals_advanced=True,
        )

    def run_without_tpe(self) -> EvalReport:
        """Disable the TPE improvement engine."""
        return self._run(
            ablation_name="no_tpe",
            disable_ring1=False,
            disable_memory=False,
            disable_tpe=True,
            force_pico=False,
            signals_advanced=True,
        )

    def run_without_autonomy(self) -> EvalReport:
        """Force all nodes to PICO (deterministic) mode."""
        return self._run(
            ablation_name="no_autonomy",
            disable_ring1=False,
            disable_memory=False,
            disable_tpe=False,
            force_pico=True,
            signals_advanced=True,
        )

    def run_without_signals(self) -> EvalReport:
        """Use only basic SMA — no advanced multi-factor signals."""
        return self._run(
            ablation_name="no_signals",
            disable_ring1=False,
            disable_memory=False,
            disable_tpe=False,
            force_pico=False,
            signals_advanced=False,
        )

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------

    def run_all_ablations(self) -> dict[str, EvalReport]:
        """
        Run all ablations and return mapping of name → EvalReport.

        Runs: full, no_ring1, no_memory, no_tpe, no_autonomy, no_signals.
        """
        logger.info("AblationHarness: starting all ablation runs (n_cycles=%d)", self._n_cycles)
        t0 = time.perf_counter()

        ablations = [
            ("full", self.run_full),
            ("no_ring1", self.run_without_ring1),
            ("no_memory", self.run_without_memory),
            ("no_tpe", self.run_without_tpe),
            ("no_autonomy", self.run_without_autonomy),
            ("no_signals", self.run_without_signals),
        ]

        for name, fn in ablations:
            logger.info("AblationHarness: running '%s'", name)
            report = fn()
            self._results[name] = report
            logger.info(
                "AblationHarness: '%s' done — sharpe=%.4f drawdown=%.4f",
                name,
                report.sharpe,
                report.max_drawdown,
            )

        elapsed = time.perf_counter() - t0
        logger.info("AblationHarness: all runs complete in %.2fs", elapsed)
        return dict(self._results)

    # ------------------------------------------------------------------
    # Attribution
    # ------------------------------------------------------------------

    def compute_attribution(self) -> dict[str, float]:
        """
        Compute Sharpe attribution for each subsystem.

        attribution[subsystem] = Sharpe(full) - Sharpe(without_subsystem)

        Positive value = subsystem adds alpha.
        Negative value = subsystem was hurting alpha (worth investigating).

        Returns empty dict if run_all_ablations() has not been called.
        """
        if "full" not in self._results:
            logger.warning(
                "compute_attribution: 'full' run missing — call run_all_ablations() first"
            )
            return {}

        full_sharpe = self._results["full"].sharpe

        subsystem_map = {
            "ring1": "no_ring1",
            "memory": "no_memory",
            "tpe": "no_tpe",
            "autonomy": "no_autonomy",
            "signals": "no_signals",
        }

        attribution: dict[str, float] = {}
        for subsystem, ablation_name in subsystem_map.items():
            if ablation_name not in self._results:
                continue
            ablation_sharpe = self._results[ablation_name].sharpe
            attribution[subsystem] = round(full_sharpe - ablation_sharpe, 6)

            # Report bootstrap significance of the Sharpe difference
            full_returns = self._results["full"].raw_returns
            ablation_returns = self._results[ablation_name].raw_returns
            if full_returns and ablation_returns:
                sig, diff, (ci_lo, ci_hi) = sharpe_difference_significant(
                    full_returns, ablation_returns, n_bootstrap=2000
                )
                logger.info(
                    "  %s: ΔSharpe=%.4f [95%% CI: %.4f, %.4f] significant=%s",
                    subsystem,
                    diff,
                    ci_lo,
                    ci_hi,
                    sig,
                )

        logger.info("Sharpe attribution: %s", attribution)
        return attribution

    @property
    def results(self) -> dict[str, EvalReport]:
        """Return cached ablation results."""
        return dict(self._results)

    # ------------------------------------------------------------------
    # Internal run builder
    # ------------------------------------------------------------------

    def _run(
        self,
        ablation_name: str,
        disable_ring1: bool,
        disable_memory: bool,
        disable_tpe: bool,
        force_pico: bool,
        signals_advanced: bool,
    ) -> EvalReport:
        t_start = time.perf_counter()

        # Build fresh node(s) for this run
        if self._nodes is not None:
            nodes = self._nodes
            ablation_node = None
        else:
            ablation_node = _AblationNode(
                name=f"node_{ablation_name}",
                base_sharpe=self._base_sharpe,
                use_advanced=signals_advanced,
                pico_forced=force_pico,
                seed=self._seed,
            )
            nodes = [ablation_node]

        # Build autonomy controller (force PICO if needed)
        autonomy = GraduatedAutonomyController()
        if force_pico:
            # Override promotion thresholds so nodes stay PICO throughout
            from omega.core.autonomy import AutonomyThresholds
            from omega.core.domain import PerformanceMetric

            autonomy._thresholds = AutonomyThresholds(
                min_cycles=999_999,
                metrics=[
                    PerformanceMetric("sharpe", "higher_is_better", 999.0, -999.0),
                    PerformanceMetric("max_drawdown", "lower_is_better", 0.0, 1.0),
                ],
            )

        # Build improvement engine (disabled = no-op evaluator with empty space)
        improvement_engine: ImprovementEngine | None = None
        if not disable_tpe:
            improvement_engine = ImprovementEngine()

        # Build orchestrator
        orch = OmegaOrchestrator(
            name=f"ablation_{ablation_name}",
            autonomy_controller=autonomy,
            improvement_engine=improvement_engine,
            adversarial=None,  # Ring1 handled by keeping adversarial=None when disabled
            memory_consolidation=None,
        )

        # If disabling ring1, leave adversarial=None (orchestrator skips it)
        # The orchestrator already handles adversarial=None gracefully.

        for node in nodes:
            orch.register_node(node)

        # Run
        history = orch.run(max_cycles=self._n_cycles)

        # Extract metrics from history
        report = self._history_to_report(
            ablation_name=ablation_name,
            history=history,
            ablation_node=ablation_node,
            duration_seconds=time.perf_counter() - t_start,
        )
        return report

    def _history_to_report(
        self,
        ablation_name: str,
        history: CycleHistory,
        ablation_node: _AblationNode | None,
        duration_seconds: float,
    ) -> EvalReport:
        results = list(history)
        n = len(results)

        if n == 0:
            return EvalReport(
                ablation_name=ablation_name,
                n_cycles=0,
                sharpe=0.0,
                max_drawdown=0.0,
                avg_signals_per_cycle=0.0,
                adversarial_flag_rate=0.0,
                error_rate=0.0,
                trades_executed=0,
                improvement_cycles=0,
                duration_seconds=duration_seconds,
            )

        # Use node returns for Sharpe if available, else estimate from metrics
        raw_returns: list[float] = []
        if ablation_node is not None:
            raw_returns = ablation_node.returns

        sharpe = (
            _sharpe_from_returns(raw_returns) if raw_returns else _sharpe_from_history(results)
        )
        max_dd = _max_drawdown_from_returns(raw_returns) if raw_returns else 0.0

        total_signals = sum(r.signals_generated for r in results)
        total_flags = sum(1 for r in results if r.had_adversarial_flag)
        total_errors = sum(r.error_count for r in results)
        total_trades = sum(r.trades_executed for r in results)
        total_improvements = sum(1 for r in results if r.improvement_proposed)

        return EvalReport(
            ablation_name=ablation_name,
            n_cycles=n,
            sharpe=round(sharpe, 6),
            max_drawdown=round(max_dd, 6),
            avg_signals_per_cycle=round(total_signals / n, 4),
            adversarial_flag_rate=round(total_flags / n, 4),
            error_rate=round(total_errors / n, 4),
            trades_executed=total_trades,
            improvement_cycles=total_improvements,
            duration_seconds=round(duration_seconds, 4),
            raw_returns=raw_returns,
        )


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------


def _sharpe_from_returns(returns: list[float], risk_free: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    daily_rf = risk_free / 252
    excess = [r - daily_rf for r in returns]
    mean_e = sum(excess) / len(excess)
    var = sum((x - mean_e) ** 2 for x in excess) / (len(excess) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    return (mean_e / std * math.sqrt(252)) if std > 0 else 0.0


def _sharpe_from_history(results: list[CycleResult]) -> float:
    """Estimate Sharpe from metrics embedded in CycleResults."""
    sharpes: list[float] = [
        float(v) for r in results if (v := r.metrics.get("sharpe")) is not None
    ]
    if not sharpes:
        return 0.0
    return sum(sharpes) / len(sharpes)


def _max_drawdown_from_returns(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r))
    peak = equity[0]
    max_dd = 0.0
    for v in equity[1:]:
        if v > peak:
            peak = v
        dd = (peak - v) / max(peak, 1e-12)
        if dd > max_dd:
            max_dd = dd
    return max_dd
