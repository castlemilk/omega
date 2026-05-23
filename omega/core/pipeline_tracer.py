"""Pipeline health tracer — node-boundary assertions + per-cycle snapshot.

Purpose: catch silent data-flow failures at every handoff in the trading
pipeline. The multi-week zero-trade pattern across v186-v196 was rooted in
ambiguity about whether per-ticker signals were reaching the strategy
node — there was no assertion at the boundary that would have answered
the question instantly. This module makes data flow observable.

Design:
    * `PipelineTracer.trace_handoff(from_node, to_node, data, expectations)`
      validates the data shape at any boundary, logs ERROR on violation,
      writes a sentinel file the health monitor can poll.
    * `PipelineTracer.snapshot(cycle, components)` writes a one-line JSON
      to `data/pipeline_health.jsonl` summarising data flow per stage so
      "where did it stop" is answerable from a single tail.

Cheap by design: counts, mins, maxes, set membership — no deep recursion,
no large allocations per call. Safe to enable in production.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("omega.core.pipeline_tracer")

_HEALTH_LOG_PATH = Path("data/pipeline_health.jsonl")
_VIOLATION_SENTINEL = Path("data/PIPELINE_VIOLATION")
_SIGNAL_HISTORY_LEN = 50  # for signal-range monitoring


@dataclass
class _SignalHistory:
    values: deque[float] = field(default_factory=lambda: deque(maxlen=_SIGNAL_HISTORY_LEN))


class PipelineTracer:
    """Singleton-style tracer. Hold one instance per process — the bridge
    server (`bridge.pipeline_server`) creates it; training scripts share it
    via the orchestrator."""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._signal_history: dict[str, _SignalHistory] = defaultdict(_SignalHistory)
        self._violation_count: int = 0
        self._handoff_count: int = 0
        try:
            _HEALTH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def trace_handoff(
        self,
        from_node: str,
        to_node: str,
        data: Any,
        *,
        min_keys: int = 0,
        required_keys: tuple[str, ...] = (),
        non_zero_keys: tuple[str, ...] = (),
        type_checks: dict[str, type] | None = None,
    ) -> list[str]:
        """Validate data passing between two nodes.

        Returns the list of violation strings (empty when OK).
        """
        if not self._enabled:
            return []
        self._handoff_count += 1
        violations: list[str] = []

        if not isinstance(data, dict):
            violations.append(f"data is not dict (got {type(data).__name__})")
        else:
            if len(data) < min_keys:
                violations.append(f"too few keys: {len(data)} < {min_keys}")
            for key in required_keys:
                if key not in data:
                    violations.append(f"missing required key: {key}")
            for key in non_zero_keys:
                v = data.get(key)
                try:
                    if float(v) == 0.0:
                        violations.append(f"zero value for key: {key}")
                except (TypeError, ValueError):
                    violations.append(f"non-numeric value for non-zero key: {key}")
            for key, expected_type in (type_checks or {}).items():
                if key in data and not isinstance(data[key], expected_type):
                    violations.append(
                        f"type mismatch for {key}: got {type(data[key]).__name__}, "
                        f"expected {expected_type.__name__}"
                    )

        if violations:
            self._violation_count += 1
            logger.error(
                "PIPELINE_VIOLATION %s→%s: %s",
                from_node, to_node, violations,
            )
            try:
                with _VIOLATION_SENTINEL.open("a") as f:
                    f.write(
                        json.dumps({
                            "ts": time.time(),
                            "from": from_node,
                            "to": to_node,
                            "violations": violations,
                            "sample_keys": list(data.keys())[:10] if isinstance(data, dict) else None,
                        }) + "\n"
                    )
            except Exception:
                pass
        else:
            logger.debug(
                "PIPELINE_OK %s→%s: %d keys",
                from_node, to_node,
                len(data) if isinstance(data, dict) else 0,
            )
        return violations

    def snapshot(self, cycle: int, components: dict[str, dict[str, Any]]) -> None:
        """Write one-line JSON per cycle to `data/pipeline_health.jsonl`.

        `components` keyed by stage name, values are stage-specific dicts.
        Caller is responsible for accurate counts; this method just persists.
        """
        if not self._enabled:
            return
        record = {
            "cycle": cycle,
            "ts": time.time(),
            **components,
            "_tracer": {
                "handoff_count": self._handoff_count,
                "violation_count": self._violation_count,
            },
        }
        try:
            with _HEALTH_LOG_PATH.open("a") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception as exc:
            logger.debug("pipeline_health write failed: %s", exc)

    def watch_signal(self, signal_name: str, value: float, dead_threshold: int = 20) -> bool:
        """Track rolling history of a signal value. Returns True when the
        signal has been 0.0 for `dead_threshold` consecutive observations —
        likely a silent upstream failure.
        """
        if not self._enabled:
            return False
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        hist = self._signal_history[signal_name]
        hist.values.append(v)
        if len(hist.values) < dead_threshold:
            return False
        recent = list(hist.values)[-dead_threshold:]
        if all(x == 0.0 for x in recent):
            logger.error(
                "SIGNAL_DEAD: %s has been 0.0 for %d consecutive observations",
                signal_name, dead_threshold,
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Reset / introspection (mostly for tests)
    # ------------------------------------------------------------------

    @property
    def violation_count(self) -> int:
        return self._violation_count

    @property
    def handoff_count(self) -> int:
        return self._handoff_count

    def reset(self) -> None:
        self._signal_history.clear()
        self._violation_count = 0
        self._handoff_count = 0


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------

_global_tracer: PipelineTracer | None = None


def get_tracer() -> PipelineTracer:
    """Return the process-wide PipelineTracer. Lazily creates one."""
    global _global_tracer
    if _global_tracer is None:
        enabled = os.environ.get("OMEGA_PIPELINE_TRACING", "1") != "0"
        _global_tracer = PipelineTracer(enabled=enabled)
    return _global_tracer
