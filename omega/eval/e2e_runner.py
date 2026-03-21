"""omega.eval.e2e_runner — End-to-end evaluation runner for the Omega Go←→Python bridge.

Starts the Go API server as a subprocess, waits for it to be healthy,
runs eval scenarios via Connect-RPC, collects results, and shuts the server down.

Usage (standalone):
    python -m omega.eval.e2e_runner
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from omega.bridge.state_client import StateServiceClient

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_BASE_URL = "http://localhost:8080"


# ---------------------------------------------------------------------------
# Generic Connect-RPC client base
# ---------------------------------------------------------------------------


class RpcError(Exception):
    """Raised when a Connect-RPC call fails."""


class _ConnectClient:
    """Base class for Connect-RPC unary JSON clients (stdlib only)."""

    _service: str  # e.g. "OrchestratorService"

    def __init__(self, base_url: str = _DEFAULT_BASE_URL, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _call(self, method: str, body: dict) -> Any:
        url = f"{self._base_url}/omega.v1.{self._service}/{method}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Connect-Protocol-Version": "1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                err_body = json.loads(exc.read())
                msg = err_body.get("message", str(exc))
            except Exception:
                msg = str(exc)
            raise RpcError(f"{self._service}/{method} ({exc.code}): {msg}") from exc
        except Exception as exc:
            raise RpcError(f"{self._service}/{method} unavailable: {exc}") from exc

    @staticmethod
    def _encode_map(d: dict | None) -> Any:
        if not d:
            return {}
        return {k: json.dumps(v) if not isinstance(v, str) else v for k, v in d.items()}


# ---------------------------------------------------------------------------
# Service clients
# ---------------------------------------------------------------------------


class OrchestratorClient(_ConnectClient):
    _service = "OrchestratorService"

    def get_health(self) -> Any:
        return self._call("GetHealth", {})

    def list_nodes(self) -> Any:
        resp = self._call("ListNodes", {})
        return resp.get("nodes", [])

    def get_node(self, node_id: str) -> Any:
        return self._call("GetNode", {"nodeId": node_id})

    def get_adversarial_results(self) -> Any:
        resp = self._call("GetAdversarialResults", {})
        return resp.get("results", [])

    def get_alignment_decisions(self) -> Any:
        resp = self._call("GetAlignmentDecisions", {})
        return resp.get("decisions", [])

    def get_memory_stats(self) -> Any:
        return self._call("GetMemoryStats", {})

    def get_goal_tracking(self) -> Any:
        resp = self._call("GetGoalTracking", {})
        return resp.get("tracking", [])


class AutonomyClient(_ConnectClient):
    _service = "AutonomyService"

    def record_cycle_metrics(
        self,
        node_id: str,
        cycle: int,
        metrics: dict,
        success: bool = True,
    ) -> Any:
        return self._call(
            "RecordCycleMetrics",
            {
                "nodeId": node_id,
                "cycle": cycle,
                "metrics": self._encode_map(metrics),
                "success": success,
            },
        )

    def get_autonomy_level(self, node_id: str) -> Any:
        return self._call("GetAutonomyLevel", {"nodeId": node_id})

    def request_promotion(
        self,
        node_id: str,
        requested_level: str,
        reason: str,
        supporting_metrics: dict,
    ) -> Any:
        return self._call(
            "RequestPromotion",
            {
                "nodeId": node_id,
                "requestedLevel": requested_level,
                "reason": reason,
                "supportingMetrics": self._encode_map(supporting_metrics),
            },
        )

    def get_autonomy_history(self, node_id: str, limit: int = 20) -> Any:
        return self._call("GetAutonomyHistory", {"nodeId": node_id, "limit": limit})


class MemoryClient(_ConnectClient):
    _service = "MemoryService"

    def store_episode(
        self,
        namespace: str,
        event_type: str,
        content: dict | None = None,
        tags: list[str] | None = None,
        importance: float = 0.5,
        cycle: int = 0,
    ) -> str:
        # content is map<string,string> per proto definition
        encoded_content = self._encode_map(content or {})
        resp = self._call(
            "StoreEpisode",
            {
                "namespace": namespace,
                "eventType": event_type,
                "content": encoded_content,
                "tags": tags or [],
                "importance": importance,
                "cycle": cycle,
            },
        )
        return str(resp.get("episodeId", ""))

    def query_episodes(
        self,
        namespace: str,
        top_k: int = 10,
    ) -> Any:
        resp = self._call(
            "QueryEpisodes",
            {"namespace": namespace, "topK": top_k},
        )
        # Response field is "results" (list of ScoredEpisode), not "episodes"
        return resp.get("results", resp.get("episodes", []))

    def get_memory_stats(self, namespace: str) -> Any:
        return self._call("GetMemoryStats", {"namespace": namespace})

    def store_working(self, namespace: str, key: str, value_json: str, ttl: int = 0) -> None:
        self._call(
            "StoreWorking",
            {"namespace": namespace, "key": key, "valueJson": value_json, "ttl": ttl},
        )

    def get_working(self, namespace: str, key: str) -> Any:
        return self._call("GetWorking", {"namespace": namespace, "key": key})


class AdversarialClient(_ConnectClient):
    _service = "AdversarialService"

    def run_pressure(
        self,
        cycle: int,
        variant_outputs: list[dict] | None = None,
        current_signals: dict | None = None,
        run_ring2: bool = False,
        run_ring3: bool = False,
        run_debate: bool = False,
    ) -> Any:
        return self._call(
            "RunPressure",
            {
                "cycle": cycle,
                "variantOutputs": variant_outputs or [],
                "currentSignals": self._encode_map(current_signals),
                "runRing2": run_ring2,
                "runRing3": run_ring3,
                "runDebate": run_debate,
            },
        )

    def get_adversarial_report(self, cycle: int) -> Any:
        return self._call("GetAdversarialReport", {"cycle": cycle})

    def record_gate_result(
        self, cycle: int, gate_name: str, result: bool, details: dict | None = None
    ) -> None:
        self._call(
            "RecordGateResult",
            {
                "cycle": cycle,
                "gateName": gate_name,
                "result": result,
                "details": self._encode_map(details),
            },
        )


class SafetyClient(_ConnectClient):
    _service = "SafetyService"

    def check_alignment(
        self,
        node_metrics: dict | None = None,
        system_metrics: dict | None = None,
        portfolio: list[dict] | None = None,
        cycle: int = 0,
    ) -> Any:
        return self._call(
            "CheckAlignment",
            {
                "nodeMetrics": self._encode_map(node_metrics),
                "systemMetrics": self._encode_map(system_metrics),
                "portfolio": portfolio or [],
                "cycle": cycle,
            },
        )

    def evaluate_goals(
        self,
        metrics: dict | None = None,
        system_state: dict | None = None,
        cycle: int = 0,
    ) -> Any:
        return self._call(
            "EvaluateGoals",
            {
                "metrics": self._encode_map(metrics),
                "systemState": self._encode_map(system_state),
                "cycle": cycle,
            },
        )

    def verify_gates(
        self,
        phase: str = "PRE_CYCLE",
        context: dict | None = None,
        cycle: int = 0,
    ) -> Any:
        return self._call(
            "VerifyGates",
            {
                "phase": phase,
                "context": self._encode_map(context),
                "cycle": cycle,
            },
        )


# ---------------------------------------------------------------------------
# RpcClients container
# ---------------------------------------------------------------------------


class RpcClients:
    """All service clients wired to a single base URL."""

    def __init__(self, base_url: str = _DEFAULT_BASE_URL) -> None:
        self.base_url = base_url
        self.state = StateServiceClient(base_url)
        self.orchestrator = OrchestratorClient(base_url)
        self.autonomy = AutonomyClient(base_url)
        self.memory = MemoryClient(base_url)
        self.adversarial = AdversarialClient(base_url)
        self.safety = SafetyClient(base_url)


# ---------------------------------------------------------------------------
# Go server lifecycle manager
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Return a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(s.getsockname()[1])


class GoServer:
    """Manages the Go API server subprocess for eval runs."""

    def __init__(
        self,
        base_url: str | None = None,
        port: int | None = None,
        state_db: str | None = None,
        memory_db: str | None = None,
        startup_timeout: float = 60.0,
        repo_root: Path | None = None,
    ) -> None:
        self._port = port  # resolved in start()
        self.base_url: str = base_url or ""  # resolved in start()
        self._state_db = state_db
        self._memory_db = memory_db
        self._startup_timeout = startup_timeout
        self._repo_root = repo_root or _REPO_ROOT
        self._proc: subprocess.Popen | None = None
        self._tmpdir: tempfile.TemporaryDirectory | None = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        """Start the Go API server subprocess and wait for /healthz."""
        self._tmpdir = tempfile.TemporaryDirectory(prefix="omega_e2e_")
        tmp = self._tmpdir.name

        state_db = self._state_db or os.path.join(tmp, "state.db")
        memory_db = self._memory_db or os.path.join(tmp, "memory.db")

        port = self._port or _find_free_port()
        self._port = port
        self.base_url = f"http://localhost:{port}"

        env = os.environ.copy()
        env["OMEGA_STATE_DB_PATH"] = state_db
        env["OMEGA_MEMORY_DB_PATH"] = memory_db
        env["OMEGA_API_PORT"] = str(port)

        log.info("Starting Go API server on port %d (cwd=%s)", port, self._repo_root)
        self._proc = subprocess.Popen(
            ["go", "run", "./cmd/omega-api"],
            cwd=str(self._repo_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self._wait_for_health()
        log.info("Go API server ready at %s", self.base_url)

    def _wait_for_health(self) -> None:
        deadline = time.monotonic() + self._startup_timeout
        last_err: Exception | None = None

        while time.monotonic() < deadline:
            # Check if process died already
            if self._proc and self._proc.poll() is not None:
                stderr = b""
                if self._proc.stderr:
                    stderr = self._proc.stderr.read(4096)
                raise RuntimeError(
                    f"Go API server exited early (rc={self._proc.returncode}): "
                    f"{stderr.decode(errors='replace')}"
                )

            try:
                with urllib.request.urlopen(f"{self.base_url}/healthz", timeout=2) as resp:
                    if resp.status == 200:
                        return
            except Exception as exc:
                last_err = exc

            time.sleep(0.5)

        # Dump stderr for debugging
        if self._proc and self._proc.stderr:
            stderr = self._proc.stderr.read(4096)
            log.error("Go server stderr: %s", stderr.decode(errors="replace"))

        raise RuntimeError(
            f"Go API server did not become healthy within {self._startup_timeout}s: {last_err}"
        )

    def stop(self) -> None:
        """Terminate the Go API server and clean up temp files."""
        if self._proc is not None:
            log.info("Stopping Go API server (pid=%d)", self._proc.pid)
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                log.warning("Server did not stop gracefully, killing")
                self._proc.kill()
                self._proc.wait(timeout=5)
            self._proc = None

        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None

    def __enter__(self) -> GoServer:
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


def run_eval(output_dir: str = "eval_results") -> int:
    """Start server, run all scenarios, write report. Returns exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from omega.eval.report import EvalReport
    from omega.eval.scenarios import ALL_SCENARIOS

    report = EvalReport()

    with GoServer(startup_timeout=90.0) as server:
        clients = RpcClients(server.base_url)

        for name, fn in ALL_SCENARIOS:
            log.info("Running scenario: %s", name)
            result = fn(clients)
            report.add(result)
            status = "PASS" if result.passed else "FAIL"
            log.info("  %s %s (%.1fms)", status, name, result.duration_ms)

    report.write(output_dir)
    log.info("Report written to %s/", output_dir)
    log.info(
        "Summary: %d/%d passed, bridge p50=%.1fms",
        report.passed_count,
        report.total_count,
        report.p50_latency_ms,
    )
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    import sys

    sys.exit(run_eval())
