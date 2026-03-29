"""
omega.core.dag_pipeline
~~~~~~~~~~~~~~~~~~~~~~~
Parallel DAG execution engine for Victoria's signal computation pipeline.

Signals are arranged as a directed acyclic graph where each node declares
its dependencies.  Independent signals within each topological wave execute
concurrently via ThreadPoolExecutor, reducing end-to-end latency.

Usage
-----
    from omega.core.dag_pipeline import DAGPipeline, SignalNode

    pipeline = DAGPipeline([
        SignalNode("market_data", deps=[], fn=fetch_prices),
        SignalNode("basic_signals", deps=["market_data"], fn=compute_basic),
        SignalNode("cross_asset",   deps=["market_data"], fn=compute_cross),
        SignalNode("rmt_signal",    deps=["cross_asset"],  fn=compute_rmt),
        SignalNode("strategy",      deps=["basic_signals", "cross_asset", "rmt_signal"],
                   fn=compute_strategy),
    ])

    result = pipeline.run(ctx={"regime": "default"})
    signals  = result.signals
    print(result.summary())

Each ``fn`` receives ``(accumulated: dict, ctx: dict)`` where:
  - ``accumulated`` contains results of all previously completed nodes
  - ``ctx``         is the shared context dict (read-only by convention)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("omega.core.dag_pipeline")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SignalNode:
    """A single node in the signal DAG."""

    name: str
    deps: list[str]
    fn: Callable[[dict[str, Any], dict[str, Any]], Any]
    description: str = ""


@dataclass
class NodeTiming:
    """Execution timing for a single signal node."""

    name: str
    start_time: float
    end_time: float
    duration_ms: float
    success: bool
    error: str | None = None


@dataclass
class PipelineResult:
    """Result of a full DAG pipeline run."""

    signals: dict[str, Any]
    timings: dict[str, NodeTiming]
    total_duration_ms: float
    critical_path: list[str]
    wave_durations: list[float]
    wave_membership: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        cp_ms = sum(self.timings[n].duration_ms for n in self.critical_path if n in self.timings)
        waves_str = ", ".join(f"{d:.1f}ms" for d in self.wave_durations)
        return (
            f"total={self.total_duration_ms:.1f}ms  "
            f"critical_path=[{' → '.join(self.critical_path)}]({cp_ms:.1f}ms)  "
            f"waves={len(self.wave_durations)}[{waves_str}]"
        )

    def slowest_signals(self, n: int = 5) -> list[tuple[str, float]]:
        """Return the n slowest signals by duration."""
        return sorted(
            [(name, t.duration_ms) for name, t in self.timings.items()],
            key=lambda x: x[1],
            reverse=True,
        )[:n]


# ---------------------------------------------------------------------------
# DAG execution engine
# ---------------------------------------------------------------------------


class DAGPipeline:
    """
    Execute a signal DAG in topological waves.

    Each wave contains all nodes whose dependencies have been satisfied.
    Nodes within a wave execute concurrently up to ``max_workers`` threads.
    Failed nodes produce ``None`` in the accumulated results dict; downstream
    nodes will still execute with that ``None`` value present.

    Parameters
    ----------
    nodes       : list of SignalNode defining the computation graph
    max_workers : maximum threads per wave (default 8)
    """

    def __init__(self, nodes: list[SignalNode], max_workers: int = 8) -> None:
        self._nodes = {n.name: n for n in nodes}
        self._max_workers = max_workers
        self._waves, self._wave_map = self._compute_waves()

    # ------------------------------------------------------------------
    # Topology
    # ------------------------------------------------------------------

    def _compute_waves(self) -> tuple[list[list[str]], dict[str, int]]:
        """Topological sort via Kahn's algorithm, producing parallel waves."""
        in_degree: dict[str, int] = {name: 0 for name in self._nodes}
        dependents: dict[str, list[str]] = defaultdict(list)

        for name, node in self._nodes.items():
            for dep in node.deps:
                if dep not in self._nodes:
                    raise ValueError(f"Signal '{name}' declares unknown dependency '{dep}'")
                in_degree[name] += 1
                dependents[dep].append(name)

        queue: deque[str] = deque(name for name, deg in in_degree.items() if deg == 0)
        waves: list[list[str]] = []
        wave_map: dict[str, int] = {}

        while queue:
            wave = list(queue)
            queue.clear()
            wave_idx = len(waves)
            waves.append(wave)

            for name in wave:
                wave_map[name] = wave_idx
                for dependent in dependents[name]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

        scheduled = sum(len(w) for w in waves)
        if scheduled != len(self._nodes):
            cycle_nodes = [n for n, d in in_degree.items() if d > 0]
            raise ValueError(f"DAG has a cycle involving: {cycle_nodes}")

        logger.debug(
            "DAG topology: %d nodes in %d waves: %s",
            scheduled,
            len(waves),
            [len(w) for w in waves],
        )
        return waves, wave_map

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(self, ctx: dict[str, Any] | None = None) -> PipelineResult:
        """
        Execute the DAG and return a PipelineResult.

        Parameters
        ----------
        ctx : shared read-only context forwarded to every node function.
              Typically contains ``market_data``, ``regime``, ``pico_mode``.
        """
        if ctx is None:
            ctx = {}

        pipeline_start = time.perf_counter()
        accumulated: dict[str, Any] = {}
        timings: dict[str, NodeTiming] = {}
        wave_durations: list[float] = []

        for wave_idx, wave in enumerate(self._waves):
            wave_start = time.perf_counter()

            if len(wave) == 1:
                # Single node — execute inline to avoid thread-pool overhead
                name = wave[0]
                t0, t1, result, error = self._exec_node(name, accumulated, ctx)
                accumulated[name] = result
                timings[name] = NodeTiming(
                    name=name,
                    start_time=t0,
                    end_time=t1,
                    duration_ms=(t1 - t0) * 1000,
                    success=error is None,
                    error=error,
                )
            else:
                # Multiple nodes — run concurrently
                # Snapshot accumulated so each worker gets the same view
                snap = dict(accumulated)
                with ThreadPoolExecutor(
                    max_workers=min(self._max_workers, len(wave)),
                    thread_name_prefix=f"dag_wave{wave_idx}",
                ) as executor:
                    future_to_name = {
                        executor.submit(self._exec_node, name, snap, ctx): name for name in wave
                    }
                    for future in as_completed(future_to_name):
                        name = future_to_name[future]
                        t0, t1, result, error = future.result()
                        accumulated[name] = result
                        timings[name] = NodeTiming(
                            name=name,
                            start_time=t0,
                            end_time=t1,
                            duration_ms=(t1 - t0) * 1000,
                            success=error is None,
                            error=error,
                        )

            wave_ms = (time.perf_counter() - wave_start) * 1000
            wave_durations.append(wave_ms)
            logger.debug("wave %d (%s): %.1f ms", wave_idx, wave, wave_ms)

        total_ms = (time.perf_counter() - pipeline_start) * 1000
        critical_path = self._find_critical_path(timings)

        result_obj = PipelineResult(
            signals=accumulated,
            timings=timings,
            total_duration_ms=total_ms,
            critical_path=critical_path,
            wave_durations=wave_durations,
            wave_membership=dict(self._wave_map),
        )

        logger.info("DAG pipeline: %s", result_obj.summary())
        slowest = result_obj.slowest_signals(3)
        logger.debug("Slowest: %s", slowest)

        return result_obj

    def _exec_node(
        self,
        name: str,
        accumulated: dict[str, Any],
        ctx: dict[str, Any],
    ) -> tuple[float, float, Any, str | None]:
        """Execute one node, returning (t0, t1, result, error_or_None)."""
        t0 = time.perf_counter()
        try:
            result = self._nodes[name].fn(accumulated, ctx)
            t1 = time.perf_counter()
            return t0, t1, result, None
        except Exception as exc:
            t1 = time.perf_counter()
            logger.warning("DAG node '%s' failed: %s", name, exc)
            return t0, t1, None, str(exc)

    # ------------------------------------------------------------------
    # Critical path analysis
    # ------------------------------------------------------------------

    def _find_critical_path(self, timings: dict[str, NodeTiming]) -> list[str]:
        """
        Find the critical path: the longest-latency route through the DAG.

        Uses DP over the topological wave order.  Each node's cumulative cost
        is the maximum parent cost plus its own duration.
        """
        # dp[name] = (cumulative_ms, path_list)
        dp: dict[str, tuple[float, list[str]]] = {}

        for wave in self._waves:
            for name in wave:
                node = self._nodes[name]
                own_ms = timings[name].duration_ms if name in timings else 0.0

                if not node.deps:
                    dp[name] = (own_ms, [name])
                else:
                    best_ms = 0.0
                    best_path: list[str] = []
                    for dep in node.deps:
                        if dep in dp:
                            dep_ms, dep_path = dp[dep]
                            if dep_ms > best_ms:
                                best_ms = dep_ms
                                best_path = dep_path
                    dp[name] = (best_ms + own_ms, [*best_path, name])

        if not dp:
            return []
        _, path = max(dp.values(), key=lambda x: x[0])
        return path
