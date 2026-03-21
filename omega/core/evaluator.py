"""
omega.core.evaluator
~~~~~~~~~~~~~~~~~~~~~
Evaluation harness for the Omega system.

Responsibilities
----------------
- Define which metrics matter for a given goal (goal → MetricSpec).
- Store iteration snapshots in SQLite (no external deps).
- Compare performance across iterations (mean, stddev, delta).
- Decide whether an improvement is statistically meaningful.
- Generate human-readable evaluation reports.
"""

import logging
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger("omega.evaluator")


# ---------------------------------------------------------------------------
# Metric spec: what counts as good for a given goal
# ---------------------------------------------------------------------------


@dataclass
class MetricSpec:
    """Describes a single metric and its improvement direction."""

    name: str
    direction: str = "minimize"  # "minimize" or "maximize"
    weight: float = 1.0
    threshold: float | None = None  # target value; None = no hard target

    def is_better(self, new_val: float, old_val: float) -> bool:
        if self.direction == "minimize":
            return new_val < old_val
        return new_val > old_val

    def delta(self, new_val: float, old_val: float) -> float:
        """Positive delta = improvement in the desired direction."""
        if self.direction == "minimize":
            return old_val - new_val
        return new_val - old_val


@dataclass
class GoalSpec:
    """Binds a goal string to a set of MetricSpecs."""

    goal: str
    metrics: list[MetricSpec] = field(default_factory=list)
    description: str = ""

    def add_metric(
        self,
        name: str,
        direction: str = "minimize",
        weight: float = 1.0,
        threshold: float | None = None,
    ) -> "GoalSpec":
        self.metrics.append(MetricSpec(name, direction, weight, threshold))
        return self


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class _Store:
    """Thin SQLite wrapper.  Schema created on first use."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS iterations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                goal        TEXT    NOT NULL,
                iteration   INTEGER NOT NULL,
                timestamp   TEXT    NOT NULL,
                notes       TEXT
            );

            CREATE TABLE IF NOT EXISTS node_metrics (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                iteration_id INTEGER NOT NULL REFERENCES iterations(id),
                node_id      TEXT    NOT NULL,
                node_name    TEXT    NOT NULL,
                metric_name  TEXT    NOT NULL,
                metric_value REAL    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS system_metrics (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                iteration_id INTEGER NOT NULL REFERENCES iterations(id),
                metric_name  TEXT    NOT NULL,
                metric_value REAL    NOT NULL
            );
        """)
        self._conn.commit()

    def record_iteration(
        self,
        goal: str,
        iteration: int,
        node_snapshots: list[dict[str, Any]],
        system_metrics: dict[str, float],
        notes: str = "",
    ) -> int:
        ts = datetime.now().isoformat()
        cur = self._conn.execute(
            "INSERT INTO iterations (goal, iteration, timestamp, notes) VALUES (?,?,?,?)",
            (goal, iteration, ts, notes),
        )
        iter_id = cur.lastrowid

        for snap in node_snapshots:
            for metric_name, metric_value in snap.get("metrics", {}).items():
                self._conn.execute(
                    "INSERT INTO node_metrics (iteration_id, node_id, node_name, metric_name, metric_value) "
                    "VALUES (?,?,?,?,?)",
                    (iter_id, snap["node_id"], snap["node_name"], metric_name, metric_value),
                )

        for metric_name, metric_value in system_metrics.items():
            self._conn.execute(
                "INSERT INTO system_metrics (iteration_id, metric_name, metric_value) VALUES (?,?,?)",
                (iter_id, metric_name, metric_value),
            )

        self._conn.commit()
        return iter_id  # type: ignore[return-value]

    def get_system_metric_history(self, goal: str, metric_name: str) -> list[tuple[int, float]]:
        """Return [(iteration, value), …] ordered by iteration."""
        rows = self._conn.execute(
            """
            SELECT i.iteration, sm.metric_value
            FROM system_metrics sm
            JOIN iterations i ON i.id = sm.iteration_id
            WHERE i.goal = ? AND sm.metric_name = ?
            ORDER BY i.iteration
            """,
            (goal, metric_name),
        ).fetchall()
        return [(r["iteration"], r["metric_value"]) for r in rows]

    def get_node_metric_history(
        self, goal: str, node_id: str, metric_name: str
    ) -> list[tuple[int, float]]:
        rows = self._conn.execute(
            """
            SELECT i.iteration, nm.metric_value
            FROM node_metrics nm
            JOIN iterations i ON i.id = nm.iteration_id
            WHERE i.goal = ? AND nm.node_id = ? AND nm.metric_name = ?
            ORDER BY i.iteration
            """,
            (goal, node_id, metric_name),
        ).fetchall()
        return [(r["iteration"], r["metric_value"]) for r in rows]

    def last_n_system_metrics(self, goal: str, metric_name: str, n: int = 2) -> list[float]:
        history = self.get_system_metric_history(goal, metric_name)
        return [v for _, v in history[-n:]]


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def _pct_change(old: float, new: float) -> float:
    if old == 0:
        return 0.0
    return (new - old) / abs(old) * 100.0


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class Evaluator:
    """
    Stores, compares, and reports on system performance across iterations.

    Usage::

        ev = Evaluator(db_path="omega.db")
        spec = GoalSpec("fast_math")
        spec.add_metric("avg_latency_ms", direction="minimize", weight=2.0)
        spec.add_metric("accuracy", direction="maximize", weight=3.0)
        ev.register_goal(spec)

        # after each orchestrator iteration:
        ev.record(goal="fast_math", iteration=0, node_states=[...], system_metrics={...})
        report = ev.report(goal="fast_math")
        improved = ev.has_improved(goal="fast_math")
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._store = _Store(db_path)
        self._goal_specs: dict[str, GoalSpec] = {}

    def register_goal(self, spec: GoalSpec) -> None:
        self._goal_specs[spec.goal] = spec
        logger.info("Registered goal '%s' with %d metrics", spec.goal, len(spec.metrics))

    def record(
        self,
        goal: str,
        iteration: int,
        node_states: list[Any],  # List[NodeState]
        system_metrics: dict[str, float],
        notes: str = "",
    ) -> int:
        snapshots = [
            {
                "node_id": s.node_id,
                "node_name": s.name,
                "metrics": s.metrics,
            }
            for s in node_states
        ]
        iter_id = self._store.record_iteration(goal, iteration, snapshots, system_metrics, notes)
        logger.debug("Recorded iteration %d for goal '%s' (iter_id=%d)", iteration, goal, iter_id)
        return iter_id

    def has_improved(self, goal: str, metric_name: str, min_delta_pct: float = 1.0) -> bool:
        """
        Return True if the last iteration improved *metric_name* by at least
        *min_delta_pct* percent compared to the previous iteration.
        """
        spec = self._goal_specs.get(goal)
        metric_spec = None
        if spec:
            for ms in spec.metrics:
                if ms.name == metric_name:
                    metric_spec = ms
                    break

        history = self._store.last_n_system_metrics(goal, metric_name, n=2)
        if len(history) < 2:
            return False

        old, new = history[0], history[1]
        direction = metric_spec.direction if metric_spec else "minimize"

        if direction == "minimize":
            delta_pct = _pct_change(old, new) * -1  # improvement = negative change
        else:
            delta_pct = _pct_change(old, new)

        return delta_pct >= min_delta_pct

    def score(self, goal: str, system_metrics: dict[str, float]) -> float:
        """
        Compute a weighted composite score for *system_metrics* against the
        registered GoalSpec.  Higher is always better.
        """
        spec = self._goal_specs.get(goal)
        if not spec or not spec.metrics:
            return 0.0

        total_weight = sum(ms.weight for ms in spec.metrics)
        weighted_sum = 0.0

        for ms in spec.metrics:
            val = system_metrics.get(ms.name, 0.0)
            if ms.direction == "minimize":
                # invert so higher = better; guard against zero
                normalised = 1.0 / (1.0 + val) if val >= 0 else 0.0
            else:
                normalised = val / (1.0 + abs(val))
            weighted_sum += ms.weight * normalised

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def report(self, goal: str) -> str:
        """Generate a human-readable evaluation report for *goal*."""
        spec = self._goal_specs.get(goal)
        lines = [
            "=" * 60,
            f"Evaluation Report — Goal: '{goal}'",
            "=" * 60,
        ]

        if spec:
            lines.append(f"Description : {spec.description or '(none)'}")
            lines.append(f"Metrics     : {[ms.name for ms in spec.metrics]}")
            lines.append("")

            lines.append("Metric history (system-level):")
            lines.append(f"  {'Metric':<28} {'Values'}")
            lines.append("  " + "-" * 56)

            for ms in spec.metrics:
                history = self._store.get_system_metric_history(goal, ms.name)
                if not history:
                    continue
                vals = [v for _, v in history]
                trend = "↓" if ms.direction == "minimize" else "↑"
                if len(vals) >= 2:
                    delta = ms.delta(vals[-1], vals[-2])
                    delta_pct = abs(_pct_change(vals[-2], vals[-1]))
                    arrow = "✓" if delta > 0 else ("✗" if delta < 0 else "=")
                    summary = f"{arrow} {vals[-1]:.4f}  ({delta_pct:.1f}% {trend})"
                else:
                    summary = f"  {vals[-1]:.4f}"
                lines.append(f"  {ms.name:<28} {summary}")
                lines.append(
                    f"  {'  history:':<28} " + "  ".join(f"{v:.3f}@{i}" for i, v in history)
                )
        else:
            lines.append("(No GoalSpec registered — raw metric history below)")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)
