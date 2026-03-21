"""omega.eval.report — Collect scenario results and write a JSON eval report."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScenarioResult:
    """Result of a single eval scenario."""

    name: str
    passed: bool
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""
    duration_ms: float = 0.0
    rpc_calls: list[dict] = field(default_factory=list)
    assertions: list[dict] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "rpc_calls": self.rpc_calls,
            "assertions": self.assertions,
            "notes": self.notes,
        }


class ScenarioBuilder:
    """Helper for building a ScenarioResult with timing and RPC tracking."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._start = time.monotonic()
        self._rpc_calls: list[dict] = []
        self._assertions: list[dict] = []
        self._notes: list[str] = []
        self._error = ""

    def record_rpc(self, service: str, method: str, latency_ms: float, ok: bool = True) -> None:
        self._rpc_calls.append(
            {"service": service, "method": method, "latency_ms": round(latency_ms, 2), "ok": ok}
        )

    def assert_true(self, condition: bool, message: str) -> bool:
        self._assertions.append({"message": message, "passed": condition})
        return condition

    def note(self, msg: str) -> None:
        self._notes.append(msg)

    def build(self, passed: bool, error: str = "") -> ScenarioResult:
        duration_ms = (time.monotonic() - self._start) * 1000
        return ScenarioResult(
            name=self.name,
            passed=passed,
            error=error or self._error,
            duration_ms=duration_ms,
            rpc_calls=self._rpc_calls,
            assertions=self._assertions,
            notes="; ".join(self._notes),
        )

    def build_skip(self, reason: str) -> ScenarioResult:
        duration_ms = (time.monotonic() - self._start) * 1000
        return ScenarioResult(
            name=self.name,
            passed=True,  # skips count as pass (not a failure)
            skipped=True,
            skip_reason=reason,
            duration_ms=duration_ms,
        )


class EvalReport:
    """Collects scenario results and produces a summary JSON report."""

    def __init__(self) -> None:
        self._results: list[ScenarioResult] = []
        self._start_ts = time.time()

    def add(self, result: ScenarioResult) -> None:
        self._results.append(result)

    @property
    def total_count(self) -> int:
        return len(self._results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self._results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self._results if not r.passed)

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self._results if r.skipped)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self._results)

    @property
    def p50_latency_ms(self) -> float:
        """Median per-RPC call latency across all scenarios."""
        latencies = [call["latency_ms"] for r in self._results for call in r.rpc_calls]
        if not latencies:
            return 0.0
        latencies.sort()
        mid = len(latencies) // 2
        return float(latencies[mid])

    @property
    def p99_latency_ms(self) -> float:
        latencies = [call["latency_ms"] for r in self._results for call in r.rpc_calls]
        if not latencies:
            return 0.0
        latencies.sort()
        idx = int(len(latencies) * 0.99)
        return float(latencies[min(idx, len(latencies) - 1)])

    def summary(self) -> dict:
        all_rpc: list[dict] = [call for r in self._results for call in r.rpc_calls]
        total_rpc = len(all_rpc)
        failed_rpc = sum(1 for c in all_rpc if not c["ok"])

        return {
            "total": self.total_count,
            "passed": self.passed_count,
            "failed": self.failed_count,
            "skipped": self.skipped_count,
            "all_passed": self.all_passed,
            "rpc": {
                "total_calls": total_rpc,
                "failed_calls": failed_rpc,
                "p50_latency_ms": round(self.p50_latency_ms, 2),
                "p99_latency_ms": round(self.p99_latency_ms, 2),
            },
        }

    def to_dict(self) -> dict:
        return {
            "generated_at": self._start_ts,
            "summary": self.summary(),
            "scenarios": [r.to_dict() for r in self._results],
        }

    def write(self, output_dir: str = "eval_results") -> Path:
        """Write JSON report to output_dir/eval_<timestamp>.json and return the path."""
        os.makedirs(output_dir, exist_ok=True)
        ts = int(self._start_ts)
        path = Path(output_dir) / f"eval_{ts}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path
