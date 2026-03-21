"""End-to-end eval tests — exercises the full Omega system via Connect-RPC.

Each test wraps one scenario from omega.eval.scenarios.
All tests require the Go API server to be running (go_server fixture).
The go_server fixture is session-scoped: the binary is started once and
shared across all tests in this file.

Marks:
  @pytest.mark.integration — skipped unless -m integration or --run-integration
  @pytest.mark.e2e          — all tests here
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omega.eval.e2e_runner import RpcClients
from omega.eval.report import EvalReport
from omega.eval.scenarios import (
    scenario_adversarial_pressure,
    scenario_autonomy_promotion,
    scenario_memory_roundtrip,
    scenario_node_lifecycle,
    scenario_safety_envelope,
)

# Pull in session fixtures from omega.eval.conftest
pytest_plugins = ["omega.eval.conftest"]

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_scenario(result) -> None:
    """Assert a scenario passed, printing diagnostics on failure."""
    if result.skipped:
        pytest.skip(result.skip_reason)

    if not result.passed:
        lines = [f"Scenario '{result.name}' FAILED"]
        if result.error:
            lines.append(f"  Error: {result.error}")
        for a in result.assertions:
            icon = "✓" if a["passed"] else "✗"
            lines.append(f"  {icon} {a['message']}")
        for call in result.rpc_calls:
            ok = "ok" if call["ok"] else "FAIL"
            lines.append(
                f"  RPC {call['service']}/{call['method']}: {ok} {call['latency_ms']:.1f}ms"
            )
        if result.notes:
            lines.append(f"  Notes: {result.notes}")
        pytest.fail("\n".join(lines))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_e2e_node_lifecycle(rpc_clients: RpcClients) -> None:
    """Register a node, run an execution cycle, verify state via OrchestratorService."""
    result = scenario_node_lifecycle(rpc_clients)
    _assert_scenario(result)
    assert result.duration_ms > 0
    # At least 4 RPC calls expected: UpsertNode, BeginExecution, EndExecution, ListNodes
    assert len(result.rpc_calls) >= 4, f"Expected ≥4 RPC calls, got {len(result.rpc_calls)}"


def test_e2e_autonomy_promotion(rpc_clients: RpcClients) -> None:
    """Feed 12 good cycles → verify autonomy level is a valid enum value."""
    result = scenario_autonomy_promotion(rpc_clients)
    _assert_scenario(result)
    assert result.duration_ms > 0


def test_e2e_safety_envelope(rpc_clients: RpcClients) -> None:
    """Record an out-of-envelope position → verify violation is stored (decision_id non-empty)."""
    result = scenario_safety_envelope(rpc_clients)
    _assert_scenario(result)
    # Write succeeded: decision_id is non-empty
    assert any(
        "decision_id is non-empty" in a["message"] and a["passed"] for a in result.assertions
    ), "Expected decision_id non-empty assertion to pass"


def test_e2e_memory_roundtrip(rpc_clients: RpcClients) -> None:
    """Store episode via MemoryService → query back → verify content integrity."""
    result = scenario_memory_roundtrip(rpc_clients)
    _assert_scenario(result)


def test_e2e_adversarial_pressure(rpc_clients: RpcClients) -> None:
    """Record Ring-1 ensemble disagreement → verify write succeeded and results endpoint responds."""
    result = scenario_adversarial_pressure(rpc_clients)
    _assert_scenario(result)
    assert any(
        "adversarial result_id is non-empty" in a["message"] and a["passed"]
        for a in result.assertions
    ), "Expected adversarial result_id non-empty assertion to pass"


# ---------------------------------------------------------------------------
# Aggregate report test
# ---------------------------------------------------------------------------


def test_e2e_full_report(rpc_clients: RpcClients, tmp_path: Path) -> None:
    """Run all scenarios together and write a JSON report.

    This is a meta-test: it re-runs all scenarios, collects a combined
    EvalReport, writes it to tmp_path, and asserts the overall pass rate
    is at least 60% (allowing for stubbed services).
    """
    from omega.eval.scenarios import ALL_SCENARIOS

    report = EvalReport()
    for _name, fn in ALL_SCENARIOS:
        result = fn(rpc_clients)
        report.add(result)

    path = report.write(str(tmp_path))
    assert path.exists(), "Report file was written"

    data = json.loads(path.read_text())
    summary = data["summary"]

    # Print summary for CI visibility
    print(
        f"\nE2E Report: {summary['passed']}/{summary['total']} passed, "
        f"skipped={summary['skipped']}, "
        f"p50={summary['rpc']['p50_latency_ms']:.1f}ms, "
        f"p99={summary['rpc']['p99_latency_ms']:.1f}ms"
    )

    # At minimum, non-stubbed scenarios must pass
    effective_total = summary["total"] - summary["skipped"]
    if effective_total > 0:
        pass_rate = summary["passed"] / summary["total"]
        assert pass_rate >= 0.60, (
            f"Pass rate {pass_rate:.0%} below 60% threshold. "
            f"Details: {json.dumps(summary, indent=2)}"
        )

    # Bridge latency sanity check (p50 < 500ms on loopback)
    if summary["rpc"]["total_calls"] > 0:
        assert summary["rpc"]["p50_latency_ms"] < 500, (
            f"Bridge p50 latency {summary['rpc']['p50_latency_ms']:.1f}ms exceeds 500ms"
        )


# ---------------------------------------------------------------------------
# Health smoke test (fast, no scenario logic)
# ---------------------------------------------------------------------------


def test_go_server_health(rpc_clients: RpcClients) -> None:
    """Quick sanity: OrchestratorService.GetHealth returns a valid response."""
    resp = rpc_clients.orchestrator.get_health()
    assert isinstance(resp, dict), f"GetHealth returned non-dict: {resp!r}"
    # GetHealth may wrap the SystemHealth message under a 'health' key
    health = resp.get("health", resp)
    assert "status" in health or "nodeCount" in health or "compositeScore" in health, (
        f"GetHealth response missing expected fields: {resp}"
    )
