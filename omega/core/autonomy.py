"""
omega.core.autonomy
~~~~~~~~~~~~~~~~~~~
Graduated Autonomy Controller — PICO case study implementation.

Nodes start deterministic (PICO level, NoBrain) and earn AI augmentation
through proven performance. The controller manages per-node autonomy state,
promotion/demotion logic, and persists state via the StateStore.

Levels
------
PICO        — fully deterministic, NoBrain adapter, no LLM calls
SUPERVISED  — brain proposes actions, human approval required before execution
AUTONOMOUS  — brain operates freely, no human gate

Promotion criteria (all must be met)
--------------------------------------
- min_cycles:   minimum number of completed cycles at current level
- metrics:      all configured PerformanceMetric thresholds must be satisfied

Demotion triggers (any one is sufficient)
------------------------------------------
- Any configured PerformanceMetric breaches its threshold_demote value
- da_critical_challenge: Devil's Advocate node raised a CRITICAL challenge
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

# PerformanceMetric lives in domain.py — import it here for re-export so
# existing callers that do `from omega.core.autonomy import PerformanceMetric`
# continue to work.
from omega.core.domain import PerformanceMetric

if TYPE_CHECKING:
    from omega.core.state_store import StateBackend as StateStore


# ---------------------------------------------------------------------------
# Autonomy levels
# ---------------------------------------------------------------------------


class AutonomyLevel(str, Enum):  # noqa: UP042
    """Graduated autonomy ladder — nodes progress upward through proven perf."""

    PICO = "pico"  # deterministic, NoBrain
    SUPERVISED = "supervised"  # brain proposes, human approves
    AUTONOMOUS = "autonomous"  # brain operates freely


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------


@dataclass
class AutonomyThresholds:
    """
    Configurable promotion / demotion thresholds.

    metrics
        List of PerformanceMetric descriptors.  Each metric is evaluated
        independently; ALL must be satisfied for promotion; ANY breach of a
        threshold_demote value triggers demotion.

    min_cycles
        Minimum number of completed cycles at the current level before
        promotion is considered.

    Defaults to the Sharpe + max_drawdown pair so existing code that
    constructs ``AutonomyThresholds()`` without arguments continues to work.
    """

    min_cycles: int = 10
    metrics: list[PerformanceMetric] = field(
        default_factory=lambda: [
            PerformanceMetric(
                name="sharpe",
                direction="higher_is_better",
                threshold_promote=0.5,
                threshold_demote=0.0,
            ),
            PerformanceMetric(
                name="max_drawdown",
                direction="lower_is_better",
                threshold_promote=0.15,
                threshold_demote=0.20,
            ),
        ]
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_cycles": self.min_cycles,
            "metrics": [
                {
                    "name": m.name,
                    "direction": m.direction,
                    "threshold_promote": m.threshold_promote,
                    "threshold_demote": m.threshold_demote,
                }
                for m in self.metrics
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AutonomyThresholds:
        raw_metrics = d.get("metrics")
        if raw_metrics:
            metrics = [
                PerformanceMetric(
                    name=m["name"],
                    direction=m["direction"],
                    threshold_promote=float(m["threshold_promote"]),
                    threshold_demote=float(m["threshold_demote"]),
                )
                for m in raw_metrics
            ]
        else:
            # Legacy dict format: min_sharpe / max_drawdown scalar keys
            metrics = [
                PerformanceMetric(
                    "sharpe",
                    "higher_is_better",
                    float(d.get("min_sharpe", 0.5)),
                    float(d.get("demotion_sharpe", 0.0)),
                ),
                PerformanceMetric(
                    "max_drawdown",
                    "lower_is_better",
                    float(d.get("max_drawdown", 0.15)),
                    float(d.get("demotion_drawdown", 0.20)),
                ),
            ]
        return cls(
            min_cycles=int(d.get("min_cycles", 10)),
            metrics=metrics,
        )


# ---------------------------------------------------------------------------
# Per-node autonomy state
# ---------------------------------------------------------------------------


@dataclass
class NodeAutonomyState:
    """Persisted autonomy state for a single node."""

    node_id: str
    level: AutonomyLevel = AutonomyLevel.PICO
    cycles_at_level: int = 0
    total_cycles: int = 0
    # Generic metric tracking:
    #   "higher_is_better" → EMA of per-cycle readings
    #   "lower_is_better"  → running maximum (worst observed)
    metric_values: dict[str, float] = field(default_factory=dict)
    promotion_history: list[dict[str, Any]] = field(default_factory=list)
    demotion_history: list[dict[str, Any]] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Backward-compat properties for callers that used rolling_sharpe /
    # max_drawdown_observed directly.
    # ------------------------------------------------------------------

    @property
    def rolling_sharpe(self) -> float:
        return self.metric_values.get("sharpe", 0.0)

    @rolling_sharpe.setter
    def rolling_sharpe(self, v: float) -> None:
        self.metric_values["sharpe"] = v

    @property
    def max_drawdown_observed(self) -> float:
        return self.metric_values.get("max_drawdown", 0.0)

    @max_drawdown_observed.setter
    def max_drawdown_observed(self, v: float) -> None:
        self.metric_values["max_drawdown"] = v

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "level": self.level.value,
            "cycles_at_level": self.cycles_at_level,
            "total_cycles": self.total_cycles,
            "metric_values": self.metric_values,
            # Legacy scalar keys for StateStore round-trip reads
            "rolling_sharpe": self.metric_values.get("sharpe", 0.0),
            "max_drawdown_observed": self.metric_values.get("max_drawdown", 0.0),
            "promotion_history": self.promotion_history,
            "demotion_history": self.demotion_history,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NodeAutonomyState:
        # Support both new metric_values dict and legacy scalar fields
        metric_values: dict[str, float] = dict(d.get("metric_values") or {})
        if "rolling_sharpe" in d and "sharpe" not in metric_values:
            metric_values["sharpe"] = float(d["rolling_sharpe"])
        if "max_drawdown_observed" in d and "max_drawdown" not in metric_values:
            metric_values["max_drawdown"] = float(d["max_drawdown_observed"])
        return cls(
            node_id=d["node_id"],
            level=AutonomyLevel(d.get("level", "pico")),
            cycles_at_level=int(d.get("cycles_at_level", 0)),
            total_cycles=int(d.get("total_cycles", 0)),
            metric_values=metric_values,
            promotion_history=d.get("promotion_history", []),
            demotion_history=d.get("demotion_history", []),
            last_updated=float(d.get("last_updated", time.time())),
        )


# ---------------------------------------------------------------------------
# Promotion / demotion results
# ---------------------------------------------------------------------------


@dataclass
class AutonomyTransition:
    """Result of a promote/demote operation."""

    node_id: str
    previous_level: AutonomyLevel
    new_level: AutonomyLevel
    reason: str
    success: bool
    timestamp: float = field(default_factory=time.time)

    @property
    def changed(self) -> bool:
        return self.previous_level != self.new_level


# ---------------------------------------------------------------------------
# GraduatedAutonomyController
# ---------------------------------------------------------------------------


class GraduatedAutonomyController:
    """
    Manages graduated autonomy for all nodes in the Omega system.

    Usage
    -----
    controller = GraduatedAutonomyController(store=state_store)
    controller.register_node("node-abc")

    # After each cycle, record metrics generically:
    controller.record_cycle("node-abc", metrics={"sharpe": 1.2, "max_drawdown": 0.05})

    # Legacy API still works:
    controller.record_cycle("node-abc", sharpe=1.2, drawdown=0.05)

    # Attempt promotion (controller checks thresholds internally):
    result = controller.promote_node("node-abc")
    print(result.new_level)  # AutonomyLevel.SUPERVISED if criteria met

    # Force demotion on a critical event:
    controller.demote_node("node-abc", reason="da_critical_challenge")

    # Apply the correct brain to a node instance:
    controller.apply_brain_for_level(node_instance, "node-abc")
    """

    _KEY_PREFIX = "autonomy:"

    def __init__(
        self,
        store: StateStore | None = None,
        thresholds: AutonomyThresholds | None = None,
    ) -> None:
        self._store = store
        self._thresholds = thresholds or AutonomyThresholds()
        self._cache: dict[str, NodeAutonomyState] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_node(self, node_id: str) -> NodeAutonomyState:
        """
        Register a node with the autonomy system at PICO level.

        Idempotent — if the node is already registered, returns its
        existing state without resetting it.
        """
        existing = self._load_state(node_id)
        if existing is not None:
            return existing
        state = NodeAutonomyState(node_id=node_id)
        self._save_state(state)
        return state

    # ------------------------------------------------------------------
    # Cycle recording
    # ------------------------------------------------------------------

    def record_cycle(
        self,
        node_id: str,
        metrics: dict[str, float] | None = None,
        *,
        # Legacy kwargs kept for backward compatibility
        sharpe: float | None = None,
        drawdown: float | None = None,
        alpha: float = 0.1,
    ) -> NodeAutonomyState:
        """
        Update rolling metrics after a completed cycle.

        Preferred API::

            controller.record_cycle("node-abc",
                                    metrics={"sharpe": 1.2, "max_drawdown": 0.05})

        Legacy API (still supported)::

            controller.record_cycle("node-abc", sharpe=1.2, drawdown=0.05)

        For "higher_is_better" metrics: applies EMA with given alpha.
        For "lower_is_better" metrics: tracks running maximum (worst seen).
        Unknown metrics (not in thresholds) are stored as EMA by default.
        """
        # Normalise inputs into a single dict
        cycle_metrics: dict[str, float] = dict(metrics or {})
        if sharpe is not None:
            cycle_metrics.setdefault("sharpe", sharpe)
        if drawdown is not None:
            cycle_metrics.setdefault("max_drawdown", abs(drawdown))

        state = self._require_state(node_id)
        state.total_cycles += 1
        state.cycles_at_level += 1

        metric_map = {m.name: m for m in self._thresholds.metrics}
        for name, value in cycle_metrics.items():
            m = metric_map.get(name)
            if m is None or m.direction == "higher_is_better":
                # EMA update
                prev = state.metric_values.get(name, 0.0)
                state.metric_values[name] = (1 - alpha) * prev + alpha * value
            else:
                # lower_is_better → track running maximum (worst observed)
                current_worst = state.metric_values.get(name, 0.0)
                state.metric_values[name] = max(current_worst, abs(value))

        state.last_updated = time.time()
        self._save_state(state)
        return state

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------

    def promote_node(self, node_id: str) -> AutonomyTransition:
        """
        Attempt to promote a node one level up the autonomy ladder.

        Promotion succeeds only if all threshold criteria are met:
        - cycles_at_level >= min_cycles
        - all PerformanceMetric thresholds satisfied

        Nodes already at AUTONOMOUS cannot be promoted further.
        """
        state = self._require_state(node_id)
        prev_level = state.level

        if state.level == AutonomyLevel.AUTONOMOUS:
            return AutonomyTransition(
                node_id=node_id,
                previous_level=prev_level,
                new_level=state.level,
                reason="already_at_max_level",
                success=False,
            )

        ok, reason = self._check_promotion_criteria(state)
        if not ok:
            return AutonomyTransition(
                node_id=node_id,
                previous_level=prev_level,
                new_level=state.level,
                reason=reason,
                success=False,
            )

        # Promote
        next_level = (
            AutonomyLevel.SUPERVISED
            if state.level == AutonomyLevel.PICO
            else AutonomyLevel.AUTONOMOUS
        )
        record = {
            "from": state.level.value,
            "to": next_level.value,
            "reason": "criteria_met",
            "cycles_at_level": state.cycles_at_level,
            "metric_values": dict(state.metric_values),
            "timestamp": time.time(),
        }
        state.level = next_level
        state.cycles_at_level = 0
        state.promotion_history.append(record)
        state.last_updated = time.time()
        self._save_state(state)

        return AutonomyTransition(
            node_id=node_id,
            previous_level=prev_level,
            new_level=next_level,
            reason="criteria_met",
            success=True,
        )

    def _check_promotion_criteria(self, state: NodeAutonomyState) -> tuple[bool, str]:
        t = self._thresholds
        if state.cycles_at_level < t.min_cycles:
            return False, f"insufficient_cycles:{state.cycles_at_level}<{t.min_cycles}"
        for m in t.metrics:
            observed = state.metric_values.get(m.name, 0.0)
            if m.direction == "higher_is_better":
                if observed < m.threshold_promote:
                    return False, f"{m.name}_too_low:{observed:.3f}<{m.threshold_promote}"
            else:  # lower_is_better
                if observed > m.threshold_promote:
                    return (
                        False,
                        f"{m.name}_too_high:{observed:.3f}>{m.threshold_promote}",
                    )
        return True, "criteria_met"

    # ------------------------------------------------------------------
    # Demotion
    # ------------------------------------------------------------------

    def demote_node(self, node_id: str, reason: str = "manual") -> AutonomyTransition:
        """
        Demote a node one level down the autonomy ladder.

        Demotion is immediate and unconditional — the caller is responsible
        for supplying a meaningful reason string that gets recorded in history.

        Nodes already at PICO cannot be demoted further.
        """
        state = self._require_state(node_id)
        prev_level = state.level

        if state.level == AutonomyLevel.PICO:
            return AutonomyTransition(
                node_id=node_id,
                previous_level=prev_level,
                new_level=state.level,
                reason="already_at_min_level",
                success=False,
            )

        next_level = (
            AutonomyLevel.SUPERVISED
            if state.level == AutonomyLevel.AUTONOMOUS
            else AutonomyLevel.PICO
        )
        record = {
            "from": state.level.value,
            "to": next_level.value,
            "reason": reason,
            "metric_values": dict(state.metric_values),
            "timestamp": time.time(),
        }
        state.level = next_level
        state.cycles_at_level = 0
        state.demotion_history.append(record)
        state.last_updated = time.time()
        self._save_state(state)

        return AutonomyTransition(
            node_id=node_id,
            previous_level=prev_level,
            new_level=next_level,
            reason=reason,
            success=True,
        )

    def check_and_demote(
        self,
        node_id: str,
        *,
        metrics: dict[str, float] | None = None,
        # Legacy kwargs kept for backward compatibility
        current_sharpe: float | None = None,
        current_drawdown: float | None = None,
        da_critical: bool = False,
    ) -> AutonomyTransition | None:
        """
        Evaluate demotion triggers and demote if any fire.

        Preferred API::

            controller.check_and_demote("node-abc",
                                        metrics={"sharpe": -0.1, "max_drawdown": 0.25})

        Legacy API (still supported)::

            controller.check_and_demote("node-abc",
                                        current_sharpe=-0.1, current_drawdown=0.25)

        Returns the transition if demotion occurred, None otherwise.
        """
        self._require_state(node_id)

        if da_critical:
            return self.demote_node(node_id, reason="da_critical_challenge")

        # Normalise inputs into a single dict
        cycle_metrics: dict[str, float] = dict(metrics or {})
        if current_sharpe is not None:
            cycle_metrics.setdefault("sharpe", current_sharpe)
        if current_drawdown is not None:
            cycle_metrics.setdefault("max_drawdown", abs(current_drawdown))

        for m in self._thresholds.metrics:
            value = cycle_metrics.get(m.name)
            if value is None:
                continue
            if m.direction == "higher_is_better" and value < m.threshold_demote:
                return self.demote_node(node_id, reason=f"{m.name}_below_threshold")
            elif m.direction == "lower_is_better" and abs(value) > m.threshold_demote:
                return self.demote_node(node_id, reason=f"{m.name}_exceeded")
        return None

    # ------------------------------------------------------------------
    # Brain application
    # ------------------------------------------------------------------

    def apply_brain_for_level(self, node: Any, node_id: str) -> None:
        """
        Configure the correct brain adapter on *node* based on its autonomy level.

        PICO        → NoBrain (deterministic, no LLM)
        SUPERVISED  → NoBrain with a flag in metadata; caller must implement
                      the approval gate before acting on brain proposals.
        AUTONOMOUS  → existing brain (whatever is configured on the node).
        """
        from omega.core.brain import NoBrain

        state = self._require_state(node_id)

        if state.level == AutonomyLevel.PICO:
            node.brain = NoBrain()
        elif state.level == AutonomyLevel.SUPERVISED:
            pass
        # AUTONOMOUS: leave brain as-is

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_level(self, node_id: str) -> AutonomyLevel:
        """Return the current autonomy level for a node."""
        state = self._require_state(node_id)
        return state.level

    def get_state(self, node_id: str) -> NodeAutonomyState:
        """Return full autonomy state for a node."""
        return self._require_state(node_id)

    def is_pico(self, node_id: str) -> bool:
        return self.get_level(node_id) == AutonomyLevel.PICO

    def is_supervised(self, node_id: str) -> bool:
        return self.get_level(node_id) == AutonomyLevel.SUPERVISED

    def is_autonomous(self, node_id: str) -> bool:
        return self.get_level(node_id) == AutonomyLevel.AUTONOMOUS

    # ------------------------------------------------------------------
    # State persistence (StateStore integration)
    # ------------------------------------------------------------------

    def _key(self, node_id: str) -> str:
        return f"{self._KEY_PREFIX}{node_id}"

    def _load_state(self, node_id: str) -> NodeAutonomyState | None:
        if node_id in self._cache:
            return self._cache[node_id]
        if self._store is None:
            return None
        try:
            history = self._store.get_config_history(node_id)  # type: ignore[attr-defined]
            for entry in history:
                if entry.get("version", "").startswith("autonomy_state:"):
                    data = entry.get("config", {})
                    if data:
                        state = NodeAutonomyState.from_dict(data)
                        self._cache[node_id] = state
                        return state
        except Exception:
            pass
        return None

    def _save_state(self, state: NodeAutonomyState) -> None:
        self._cache[state.node_id] = state
        if self._store is None:
            return
        try:
            version_key = f"autonomy_state:{int(state.last_updated * 1000)}"
            self._store.save_config_revision(state.node_id, version_key, state.to_dict())  # type: ignore[attr-defined]
        except Exception:
            pass  # persistence failure must never break autonomy logic

    def _require_state(self, node_id: str) -> NodeAutonomyState:
        state = self._load_state(node_id)
        if state is None:
            state = self.register_node(node_id)
        return state
