"""
omega.core.cycle
~~~~~~~~~~~~~~~~
Cycle management for the Omega main loop.

CycleContext   — immutable snapshot of the world at the start of each cycle.
CycleResult    — what happened during a cycle (signals, trades, flags, etc.).
CycleHistory   — rolling window of recent CycleResults for trend analysis.

Design notes
------------
- No external dependencies — stdlib only.
- CycleContext and CycleResult are frozen dataclasses so they are safe to
  share across subsystems without accidental mutation.
- CycleHistory is the authoritative in-process record used by the orchestrator
  for trend detection; persistence is handled externally (StateStore / SQLite).
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# CycleContext
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CycleContext:
    """
    Immutable snapshot describing the state of the world at the start of
    a single orchestrator cycle.

    Fields
    ------
    cycle_id        : UUID string that correlates all logs for this cycle.
    cycle_number    : Monotonically increasing counter (0-based).
    timestamp       : UNIX epoch seconds when the cycle began.
    regime          : Current market regime label (e.g. "normal", "volatile").
    active_node_ids : IDs of nodes that were active at cycle start.
    autonomy_levels : Mapping of node_id → AutonomyLevel value string.
    metadata        : Arbitrary extensible context (strategy params, etc.).
    """

    cycle_id: str
    cycle_number: int
    timestamp: float
    regime: str
    active_node_ids: tuple[str, ...]
    autonomy_levels: dict[str, str]  # node_id → "pico"|"supervised"|"autonomous"
    metadata: dict[str, Any]

    @classmethod
    def new(
        cls,
        cycle_number: int,
        regime: str = "normal",
        active_node_ids: tuple[str, ...] = (),
        autonomy_levels: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CycleContext:
        return cls(
            cycle_id=str(uuid.uuid4()),
            cycle_number=cycle_number,
            timestamp=time.time(),
            regime=regime,
            active_node_ids=active_node_ids,
            autonomy_levels=autonomy_levels or {},
            metadata=metadata or {},
        )


# ---------------------------------------------------------------------------
# CycleResult
# ---------------------------------------------------------------------------


@dataclass
class CycleResult:
    """
    Mutable record of everything that happened during one orchestrator cycle.

    Populated incrementally by the orchestrator as each subsystem runs;
    sealed before being stored in CycleHistory.

    Fields
    ------
    context               : The CycleContext this result corresponds to.
    duration_seconds      : Wall-clock time the cycle took.
    signals_generated     : Number of signals computed (across all nodes).
    trades_proposed       : Trades the strategy layer wanted to execute.
    trades_executed       : Trades that actually went through.
    adversarial_flags     : List of flag dicts from the adversarial layer.
    improvement_proposed  : Whether TPE improvement was proposed this cycle.
    regime_transition     : Whether a regime change was confirmed this cycle.
    node_results          : Per-node execution results {node_id: NodeOutput}.
    error_count           : Errors that occurred (but were caught) this cycle.
    metrics               : Arbitrary numeric metrics for trend analysis.
    """

    context: CycleContext
    duration_seconds: float = 0.0
    signals_generated: int = 0
    trades_proposed: int = 0
    trades_executed: int = 0
    adversarial_flags: list[dict[str, Any]] = field(default_factory=list)
    improvement_proposed: bool = False
    regime_transition: bool = False
    node_results: dict[str, Any] = field(default_factory=dict)
    error_count: int = 0
    metrics: dict[str, float] = field(default_factory=dict)
    proposals: list[dict[str, Any]] = field(default_factory=list)

    @property
    def cycle_id(self) -> str:
        return self.context.cycle_id

    @property
    def cycle_number(self) -> int:
        return self.context.cycle_number

    @property
    def had_adversarial_flag(self) -> bool:
        return len(self.adversarial_flags) > 0

    @property
    def had_critical_flag(self) -> bool:
        return any(f.get("severity") == "critical" for f in self.adversarial_flags)

    def add_adversarial_flag(
        self,
        ring: str,
        severity: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.adversarial_flags.append(
            {
                "ring": ring,
                "severity": severity,
                "reason": reason,
                "details": details or {},
            }
        )

    def to_summary(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary dict."""
        return {
            "cycle_id": self.cycle_id,
            "cycle_number": self.cycle_number,
            "regime": self.context.regime,
            "duration_s": round(self.duration_seconds, 4),
            "signals": self.signals_generated,
            "trades_proposed": self.trades_proposed,
            "trades_executed": self.trades_executed,
            "adversarial_flags": len(self.adversarial_flags),
            "critical_flags": self.had_critical_flag,
            "improvement_proposed": self.improvement_proposed,
            "regime_transition": self.regime_transition,
            "errors": self.error_count,
            "active_nodes": list(self.context.active_node_ids),
            "metrics": self.metrics,
        }


# ---------------------------------------------------------------------------
# CycleHistory
# ---------------------------------------------------------------------------


class CycleHistory:
    """
    Rolling window of recent CycleResults.

    Used by the orchestrator for:
    - Trend analysis (are signals improving? are errors spiking?)
    - Improvement eligibility checks (N cycles since last improvement)
    - Regime transition rate monitoring

    Thread-safety: single-threaded use assumed (main loop).

    Parameters
    ----------
    max_size : int
        Maximum number of cycle results to retain (oldest are dropped).
    """

    def __init__(self, max_size: int = 200) -> None:
        self._window: deque[CycleResult] = deque(maxlen=max_size)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def append(self, result: CycleResult) -> None:
        self._window.append(result)

    def clear(self) -> None:
        self._window.clear()

    # ------------------------------------------------------------------
    # Basic queries
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._window)

    def __iter__(self) -> Any:
        return iter(self._window)

    @property
    def latest(self) -> CycleResult | None:
        return self._window[-1] if self._window else None

    def recent(self, n: int) -> list[CycleResult]:
        """Return the last *n* results (most-recent last)."""
        return list(self._window)[-n:]

    # ------------------------------------------------------------------
    # Trend helpers
    # ------------------------------------------------------------------

    def cycles_since_improvement(self) -> int:
        """Number of cycles since the last improvement was proposed."""
        count = 0
        for result in reversed(self._window):
            if result.improvement_proposed:
                return count
            count += 1
        return count

    def regime_transition_rate(self, window: int = 50) -> float:
        """Fraction of recent cycles that had a regime transition."""
        recent = list(self._window)[-window:]
        if not recent:
            return 0.0
        return sum(1 for r in recent if r.regime_transition) / len(recent)

    def avg_signals_per_cycle(self, window: int = 20) -> float:
        recent = list(self._window)[-window:]
        if not recent:
            return 0.0
        return sum(r.signals_generated for r in recent) / len(recent)

    def error_rate(self, window: int = 20) -> float:
        recent = list(self._window)[-window:]
        if not recent:
            return 0.0
        return sum(r.error_count for r in recent) / len(recent)

    def adversarial_flag_rate(self, window: int = 20) -> float:
        recent = list(self._window)[-window:]
        if not recent:
            return 0.0
        return sum(1 for r in recent if r.had_adversarial_flag) / len(recent)

    def metric_trend(self, metric_key: str, window: int = 20) -> str:
        """
        Return 'improving', 'degrading', or 'stable' for a numeric metric.

        'improving' means the metric has grown by >5% over the window.
        'degrading' means it has shrunk by >5%.
        'stable' otherwise (or insufficient data).
        """
        recent = [r.metrics.get(metric_key) for r in list(self._window)[-window:]]
        vals = [v for v in recent if v is not None]
        if len(vals) < 2:
            return "stable"
        delta = vals[-1] - vals[0]
        magnitude = abs(delta) / max(abs(vals[0]), 1e-9) * 100
        if magnitude < 5:
            return "stable"
        return "improving" if delta > 0 else "degrading"

    def node_health_trend(self, node_id: str, window: int = 20) -> float:
        """Average health score for a node over recent cycles (0..1)."""
        recent = list(self._window)[-window:]
        healths = []
        for r in recent:
            nr = r.node_results.get(node_id)
            if nr and isinstance(nr, dict):
                h = nr.get("health")
                if h is not None:
                    healths.append(float(h))
        return sum(healths) / len(healths) if healths else 1.0
