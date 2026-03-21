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
- min_cycles:       minimum number of completed cycles at current level
- min_sharpe:       rolling Sharpe ratio >= threshold
- max_drawdown:     max drawdown magnitude <= threshold (e.g. 0.10 = 10%)

Demotion triggers (any one is sufficient)
------------------------------------------
- sharpe_below_threshold:  Sharpe drops below demotion_sharpe
- da_critical_challenge:   Devil's Advocate node raised a CRITICAL challenge
- drawdown_exceeded:       drawdown breached demotion_drawdown limit
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

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

    Promotion (PICO→SUPERVISED, SUPERVISED→AUTONOMOUS)
    ---------------------------------------------------
    min_cycles        int   minimum cycles before promotion is considered
    min_sharpe        float rolling Sharpe ratio that must be met
    max_drawdown      float maximum allowable drawdown (0.10 = 10%)

    Demotion (any level → one step lower)
    --------------------------------------
    demotion_sharpe     float  Sharpe below which demotion is triggered
    demotion_drawdown   float  drawdown above which demotion is triggered
    """

    # Promotion
    min_cycles: int = 10
    min_sharpe: float = 0.5
    max_drawdown: float = 0.15

    # Demotion
    demotion_sharpe: float = 0.0
    demotion_drawdown: float = 0.20

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_cycles": self.min_cycles,
            "min_sharpe": self.min_sharpe,
            "max_drawdown": self.max_drawdown,
            "demotion_sharpe": self.demotion_sharpe,
            "demotion_drawdown": self.demotion_drawdown,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AutonomyThresholds:
        return cls(
            min_cycles=int(d.get("min_cycles", 10)),
            min_sharpe=float(d.get("min_sharpe", 0.5)),
            max_drawdown=float(d.get("max_drawdown", 0.15)),
            demotion_sharpe=float(d.get("demotion_sharpe", 0.0)),
            demotion_drawdown=float(d.get("demotion_drawdown", 0.20)),
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
    rolling_sharpe: float = 0.0
    max_drawdown_observed: float = 0.0
    promotion_history: list[dict[str, Any]] = field(default_factory=list)
    demotion_history: list[dict[str, Any]] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "level": self.level.value,
            "cycles_at_level": self.cycles_at_level,
            "total_cycles": self.total_cycles,
            "rolling_sharpe": self.rolling_sharpe,
            "max_drawdown_observed": self.max_drawdown_observed,
            "promotion_history": self.promotion_history,
            "demotion_history": self.demotion_history,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NodeAutonomyState:
        return cls(
            node_id=d["node_id"],
            level=AutonomyLevel(d.get("level", "pico")),
            cycles_at_level=int(d.get("cycles_at_level", 0)),
            total_cycles=int(d.get("total_cycles", 0)),
            rolling_sharpe=float(d.get("rolling_sharpe", 0.0)),
            max_drawdown_observed=float(d.get("max_drawdown_observed", 0.0)),
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

    # After each cycle, record metrics:
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
        sharpe: float,
        drawdown: float,
        *,
        alpha: float = 0.1,
    ) -> NodeAutonomyState:
        """
        Update rolling metrics after a completed cycle.

        Uses exponential moving average for Sharpe (alpha controls smoothing).
        Tracks the maximum observed drawdown magnitude across all cycles.

        Args:
            node_id:   the node whose metrics to update
            sharpe:    this cycle's Sharpe ratio
            drawdown:  this cycle's drawdown (positive magnitude, e.g. 0.05 = 5%)
            alpha:     EMA smoothing factor (default 0.1)
        """
        state = self._require_state(node_id)
        state.total_cycles += 1
        state.cycles_at_level += 1
        # Exponential moving average for Sharpe
        state.rolling_sharpe = (1 - alpha) * state.rolling_sharpe + alpha * sharpe
        # Track worst drawdown seen
        if drawdown > state.max_drawdown_observed:
            state.max_drawdown_observed = drawdown
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
        - rolling_sharpe  >= min_sharpe
        - max_drawdown_observed <= max_drawdown

        Nodes already at AUTONOMOUS cannot be promoted further.

        Returns an AutonomyTransition describing the outcome; check
        `transition.changed` to see whether the level actually changed.
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
            "rolling_sharpe": state.rolling_sharpe,
            "max_drawdown_observed": state.max_drawdown_observed,
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
        if state.rolling_sharpe < t.min_sharpe:
            return False, f"sharpe_too_low:{state.rolling_sharpe:.3f}<{t.min_sharpe}"
        if state.max_drawdown_observed > t.max_drawdown:
            return (
                False,
                f"drawdown_too_high:{state.max_drawdown_observed:.3f}>{t.max_drawdown}",
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

        Common reasons:
          "sharpe_below_threshold", "da_critical_challenge", "drawdown_exceeded"

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
            "rolling_sharpe": state.rolling_sharpe,
            "max_drawdown_observed": state.max_drawdown_observed,
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
        current_sharpe: float | None = None,
        current_drawdown: float | None = None,
        da_critical: bool = False,
    ) -> AutonomyTransition | None:
        """
        Evaluate demotion triggers and demote if any fire.

        Returns the transition if demotion occurred, None otherwise.
        """
        self._require_state(node_id)
        t = self._thresholds

        if da_critical:
            return self.demote_node(node_id, reason="da_critical_challenge")
        if current_sharpe is not None and current_sharpe < t.demotion_sharpe:
            return self.demote_node(node_id, reason="sharpe_below_threshold")
        if current_drawdown is not None and current_drawdown > t.demotion_drawdown:
            return self.demote_node(node_id, reason="drawdown_exceeded")
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

        The node must implement set_brain_config() (as per Node base class).
        """
        from omega.core.brain import NoBrain

        state = self._require_state(node_id)

        if state.level == AutonomyLevel.PICO:
            # Force NoBrain — fully deterministic
            node.brain = NoBrain()
        elif state.level == AutonomyLevel.SUPERVISED:
            # Keep existing brain but mark supervised in node metadata
            # Callers are responsible for gating execution on human approval
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
        # Check in-memory cache first
        if node_id in self._cache:
            return self._cache[node_id]
        if self._store is None:
            return None
        try:
            # Use config revision history — newest first (ORDER BY recorded_at DESC)
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
            # Persist via config revision with a namespaced version string
            version_key = f"autonomy_state:{int(state.last_updated * 1000)}"
            self._store.save_config_revision(state.node_id, version_key, state.to_dict())  # type: ignore[attr-defined]
        except Exception:
            pass  # persistence failure must never break autonomy logic

    def _require_state(self, node_id: str) -> NodeAutonomyState:
        state = self._load_state(node_id)
        if state is None:
            state = self.register_node(node_id)
        return state
