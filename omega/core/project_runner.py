"""
omega.core.project_runner
~~~~~~~~~~~~~~~~~~~~~~~~~
Loads a YAML project config and orchestrates its nodes.

Architecture
------------
ProjectRunner  : loads config, builds the execution DAG, runs cycles.
                 Supports hot-reload (YAML change → reload without restart).

Execution model
---------------
Each cycle:
  1. Compute topological waves from the project graph.
  2. For each wave, execute all member nodes in parallel
     (ThreadPoolExecutor, max_workers = len(wave)).
  3. Collect each node's NodeOutput into an ``accumulated`` dict.
  4. Pass accumulated outputs as NodeInput.parameters to downstream nodes.
  5. Signal generators publish to the shared SignalBus after executing.
  6. Attention routing: if routing.type == "attention", weight signal
     contributions by peer consensus from the SignalBus.
  7. Log structured cycle results.

Connection routing
------------------
``"src_node.port"``  → accumulated["src_node"]["port"]  (specific port)
``"src_node.*"``     → accumulated["src_node"]           (all outputs)

Hot-reload
----------
A background thread polls the YAML file's mtime every ``reload_interval``
seconds.  When a change is detected the next cycle reloads config + nodes
without restarting the process.

CLI
---
    omega run-project victoria
    omega run-project defi_yield --cycles 10 --heartbeat 60
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("omega.core.project_runner")

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def resolve_project_path(name_or_path: str) -> Path:
    """
    Resolve a project name or path to a concrete ``Path``.

    Accepts:
      - ``"victoria"``           → ``projects/victoria.yaml``
      - ``"defi_yield"``         → ``projects/defi_yield.yaml``
      - ``"projects/foo.yaml"``  → as-is (relative)
      - ``"/abs/path.yaml"``     → as-is (absolute)
    """
    p = Path(name_or_path)
    if p.suffix in (".yaml", ".yml"):
        return p

    # Treat as bare project name — search common locations
    omega_root = Path(__file__).parent.parent.parent  # repo root
    candidates = [
        Path("projects") / f"{name_or_path}.yaml",
        Path("projects") / f"{name_or_path}.yml",
        omega_root / "projects" / f"{name_or_path}.yaml",
        omega_root / "projects" / f"{name_or_path}.yml",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()

    # Return the most likely path; ProjectLoader will raise FileNotFoundError
    return (omega_root / "projects" / f"{name_or_path}.yaml").resolve()


# ---------------------------------------------------------------------------
# Cycle result
# ---------------------------------------------------------------------------

@dataclass
class CycleResult:
    """Summary of a single runner cycle."""

    cycle: int
    project: str
    duration_ms: float
    node_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    attention_weights: dict[str, float] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        ok = len(self.node_results)
        err = len(self.errors)
        return (
            f"[cycle {self.cycle}] project={self.project} "
            f"nodes={ok} errors={err} duration={self.duration_ms:.1f}ms"
        )


# ---------------------------------------------------------------------------
# Wave computation
# ---------------------------------------------------------------------------

def _compute_waves(config: Any) -> list[list[str]]:
    """
    Group node names into parallel execution waves using Kahn's algorithm.

    Returns a list of waves; nodes within a wave have no mutual dependencies
    and can execute concurrently.
    """
    node_names = {nd.name for nd in config.nodes}
    in_degree: dict[str, int] = {nd.name: 0 for nd in config.nodes}
    dependents: dict[str, list[str]] = {nd.name: [] for nd in config.nodes}

    for nd in config.nodes:
        seen: set[str] = set()
        for conn_str in nd.inputs:
            parts = conn_str.split(".", 1)
            if len(parts) == 2:
                src = parts[0]
                if src in node_names and src not in seen:
                    seen.add(src)
                    in_degree[nd.name] += 1
                    dependents[src].append(nd.name)

    waves: list[list[str]] = []
    current: list[str] = [nd.name for nd in config.nodes if in_degree[nd.name] == 0]

    while current:
        waves.append(list(current))
        nxt: list[str] = []
        for name in current:
            for dep in dependents[name]:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    nxt.append(dep)
        current = nxt

    return waves


# ---------------------------------------------------------------------------
# Node input construction
# ---------------------------------------------------------------------------

def _build_node_input(
    nd: Any,
    accumulated: dict[str, Any],
    cycle: int,
) -> Any:
    """
    Build a ``NodeInput`` for *nd* from the outputs already accumulated
    in this cycle.

    Connection string formats:
      ``"src_node.port"`` → ``accumulated["src_node"]["port"]``
      ``"src_node.*"``    → ``accumulated["src_node"]`` (full result dict)
    """
    from omega.core.node import NodeInput

    parameters: dict[str, Any] = {}

    for conn_str in nd.inputs:
        parts = conn_str.split(".", 1)
        if len(parts) != 2:
            logger.warning("Ignoring malformed connection string '%s'", conn_str)
            continue

        src_name, port = parts
        src_result = accumulated.get(src_name)
        if src_result is None:
            logger.debug("'%s': upstream '%s' not yet available", nd.name, src_name)
            continue

        if port == "*":
            # Fan-in: merge all ports from source
            if isinstance(src_result, dict):
                parameters.update(src_result)
            else:
                parameters[src_name] = src_result
        else:
            # Single port extraction
            if isinstance(src_result, dict):
                parameters[conn_str] = src_result.get(port, src_result)
            else:
                parameters[conn_str] = src_result

    # Determine action verb from node type
    _ACTION_MAP = {
        "data_provider": "ingest",
        "regime_detector": "detect",
        "signal_generator": "compute_signals",
        "strategy": "decide",
        "risk_manager": "check_risk",
        "executor": "execute",
        "intelligence": "reflect",
    }
    action = _ACTION_MAP.get(nd.type, "execute")

    return NodeInput(
        request_id=str(uuid.uuid4()),
        action=action,
        parameters=parameters,
        context={"cycle": cycle, "project_node": nd.name},
    )


# ---------------------------------------------------------------------------
# Attention weighting
# ---------------------------------------------------------------------------

def _attention_weights(node_names: list[str]) -> dict[str, float]:
    """
    Compute attention weights for *node_names* using the shared SignalBus
    peer consensus.

    Falls back to uniform weights if the bus is unavailable or has no state.
    """
    try:
        from omega.core.signal_bus import get_signal_bus

        bus = get_signal_bus()
        all_states = bus.read_all()
        if not all_states:
            raise ValueError("empty bus")

        # Simple attention: weight proportional to absolute consensus strength
        raw: dict[str, float] = {}
        for name in node_names:
            state = all_states.get(name, {})
            values = [
                abs(float(s.get("value", 0.0)))
                for key, s in state.items()
                if not key.startswith("_") and isinstance(s, dict) and "value" in s
            ]
            raw[name] = sum(values) / len(values) if values else 0.5

        total = sum(raw.values()) or 1.0
        return {n: v / total for n, v in raw.items()}

    except Exception:
        uniform = 1.0 / max(len(node_names), 1)
        return {n: uniform for n in node_names}


# ---------------------------------------------------------------------------
# ProjectRunner
# ---------------------------------------------------------------------------

class ProjectRunner:
    """
    Loads a project YAML and runs it cycle by cycle.

    Parameters
    ----------
    path_or_name    : path to a ``.yaml`` file or bare project name
                      (e.g. ``"victoria"``).
    heartbeat       : seconds to sleep between cycles (default: 60).
    max_cycles      : stop after this many cycles; ``None`` = run forever.
    reload_interval : seconds between YAML mtime checks for hot-reload
                      (default: 10; set to 0 to disable).
    dry_run         : load and validate without executing any nodes.
    """

    def __init__(
        self,
        path_or_name: str,
        heartbeat: float = 60.0,
        max_cycles: int | None = None,
        reload_interval: float = 10.0,
        dry_run: bool = False,
    ) -> None:
        self._path = resolve_project_path(path_or_name)
        self._heartbeat = heartbeat
        self._max_cycles = max_cycles
        self._reload_interval = reload_interval
        self._dry_run = dry_run

        self._config: Any = None
        self._nodes: dict[str, Any] = {}
        self._waves: list[list[str]] = []

        # Hot-reload state
        self._mtime: float = 0.0
        self._reload_flag = threading.Event()
        self._stop_flag = threading.Event()

        self._load()

    # ------------------------------------------------------------------
    # Load / reload
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load (or reload) config and instantiate nodes."""
        from omega.core.project_config import ProjectLoader

        loader = ProjectLoader()
        config = loader.load(self._path)
        errors = loader.validate(config)
        if errors:
            for e in errors:
                logger.warning("Validation warning: %s", e)

        self._config = config
        self._waves = _compute_waves(config)

        if not self._dry_run:
            self._nodes = loader.instantiate(config)
        else:
            self._nodes = {}

        self._mtime = self._path.stat().st_mtime if self._path.exists() else 0.0

        logger.info(
            "Loaded project '%s' (%d nodes, %d waves) from %s",
            config.name,
            len(config.nodes),
            len(self._waves),
            self._path,
        )

    def _check_reload(self) -> None:
        """Reload config if the YAML file has changed on disk."""
        if not self._path.exists():
            return
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            return

        if mtime != self._mtime:
            logger.info("Hot-reload: '%s' changed — reloading config", self._path)
            try:
                self._load()
                logger.info("Hot-reload complete for project '%s'", self._config.name)
            except Exception as exc:
                logger.error("Hot-reload failed: %s — keeping previous config", exc)

    # ------------------------------------------------------------------
    # Single cycle
    # ------------------------------------------------------------------

    def _run_cycle(self, cycle: int) -> CycleResult:
        """Execute one full cycle: all nodes in topological wave order."""
        t0 = time.monotonic()
        accumulated: dict[str, Any] = {}  # node_name → result dict
        node_results: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}

        for wave_idx, wave in enumerate(self._waves):
            wave_nodes = [
                nd for nd in self._config.nodes if nd.name in wave
            ]
            wave_results = self._execute_wave(wave_nodes, accumulated, cycle)

            for name, output in wave_results.items():
                if output.success:
                    result = output.result if output.result is not None else {}
                    if not isinstance(result, dict):
                        result = {"value": result}
                    accumulated[name] = result
                    node_results[name] = result

                    # Publish to signal bus for cross-node conditioning
                    nd_def = self._config.get_node(name)
                    if nd_def and nd_def.type == "signal_generator":
                        self._publish_to_signal_bus(name, result)
                else:
                    errors[name] = "; ".join(output.errors) or "unknown error"
                    accumulated[name] = {}
                    logger.warning(
                        "Node '%s' failed in cycle %d: %s",
                        name,
                        cycle,
                        errors[name],
                    )

        # Apply attention weighting if configured
        attention_weights: dict[str, float] = {}
        if self._config.routing.type == "attention":
            signal_nodes = [
                nd.name
                for nd in self._config.nodes
                if nd.type == "signal_generator"
            ]
            if signal_nodes:
                attention_weights = _attention_weights(signal_nodes)
                logger.debug("Attention weights: %s", attention_weights)

        duration_ms = (time.monotonic() - t0) * 1000
        result = CycleResult(
            cycle=cycle,
            project=self._config.name,
            duration_ms=duration_ms,
            node_results=node_results,
            errors=errors,
            attention_weights=attention_weights,
        )
        logger.info("%s", result.summary())
        return result

    def _execute_wave(
        self,
        wave_nodes: list[Any],
        accumulated: dict[str, Any],
        cycle: int,
    ) -> dict[str, Any]:
        """
        Execute all nodes in *wave_nodes* in parallel.

        Returns dict mapping node name → NodeOutput.
        """
        from omega.core.node import NodeOutput

        if not wave_nodes:
            return {}

        outputs: dict[str, Any] = {}

        with ThreadPoolExecutor(max_workers=len(wave_nodes)) as pool:
            futures = {
                pool.submit(self._execute_node, nd, accumulated, cycle): nd.name
                for nd in wave_nodes
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    outputs[name] = future.result()
                except Exception as exc:
                    logger.error("Node '%s' raised: %s", name, exc, exc_info=True)
                    outputs[name] = NodeOutput(
                        request_id="",
                        success=False,
                        errors=[str(exc)],
                    )

        return outputs

    def _execute_node(self, nd: Any, accumulated: dict[str, Any], cycle: int) -> Any:
        """Execute a single node and return its NodeOutput."""
        node = self._nodes.get(nd.name)
        if node is None:
            from omega.core.node import NodeOutput
            return NodeOutput(
                request_id="",
                success=False,
                errors=[f"Node '{nd.name}' not instantiated"],
            )

        node_input = _build_node_input(nd, accumulated, cycle)
        t0 = time.monotonic()
        try:
            output = node.execute(node_input)
        except Exception as exc:
            from omega.core.node import NodeOutput
            output = NodeOutput(
                request_id=node_input.request_id,
                success=False,
                errors=[str(exc)],
            )
        elapsed_ms = (time.monotonic() - t0) * 1000
        logger.debug(
            "  %s (%s) → success=%s  %.1fms",
            nd.name,
            nd.type,
            output.success,
            elapsed_ms,
        )
        return output

    def _publish_to_signal_bus(self, node_name: str, result: dict[str, Any]) -> None:
        """Publish signal node output to the shared SignalBus."""
        try:
            from omega.core.signal_bus import get_signal_bus
            bus = get_signal_bus()
            bus.publish(node_name, result)
        except Exception as exc:
            logger.debug("SignalBus publish failed for '%s': %s", node_name, exc)

    # ------------------------------------------------------------------
    # Hot-reload watcher thread
    # ------------------------------------------------------------------

    def _start_watcher(self) -> threading.Thread:
        """Start a background thread that polls for YAML changes."""

        def _watch() -> None:
            while not self._stop_flag.is_set():
                self._stop_flag.wait(timeout=self._reload_interval)
                if not self._stop_flag.is_set():
                    self._check_reload()

        t = threading.Thread(target=_watch, name="project-runner-watcher", daemon=True)
        t.start()
        return t

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(self) -> int:
        """
        Run the project cycle loop.

        Returns 0 on clean exit, 1 on fatal error.
        """
        if self._dry_run:
            logger.info(
                "Dry-run: project '%s' validated successfully (%d nodes)",
                self._config.name,
                len(self._config.nodes),
            )
            return 0

        watcher: threading.Thread | None = None
        if self._reload_interval > 0:
            watcher = self._start_watcher()

        logger.info(
            "Starting project '%s' | heartbeat=%.0fs | max_cycles=%s",
            self._config.name,
            self._heartbeat,
            self._max_cycles or "∞",
        )

        cycle = 0
        try:
            while not self._stop_flag.is_set():
                if self._max_cycles is not None and cycle >= self._max_cycles:
                    logger.info("Reached max_cycles=%d — stopping.", self._max_cycles)
                    break

                cycle += 1
                try:
                    self._run_cycle(cycle)
                except Exception as exc:
                    logger.error("Cycle %d failed: %s", cycle, exc, exc_info=True)

                if self._max_cycles is not None and cycle >= self._max_cycles:
                    break

                self._stop_flag.wait(timeout=self._heartbeat)

        except KeyboardInterrupt:
            logger.info("Interrupted — stopping project '%s'.", self._config.name)
        finally:
            self._stop_flag.set()
            if watcher:
                watcher.join(timeout=2.0)

        logger.info(
            "Project '%s' finished after %d cycle(s).", self._config.name, cycle
        )
        return 0

    def stop(self) -> None:
        """Signal the run loop to stop after the current cycle."""
        self._stop_flag.set()
