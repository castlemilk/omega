"""omega.bridge.adversarial_client — HTTP client for the Go AdversarialService.

Uses Connect-RPC unary JSON protocol. Zero external dependencies (stdlib only).

Connect unary protocol:
  POST <base_url>/omega.v1.AdversarialService/<MethodName>
  Content-Type: application/json
  Connect-Protocol-Version: 1
  Body: proto JSON (camelCase field names)

Usage:
    client = AdversarialServiceClient("http://localhost:8080")

    # Run all three adversarial rings for a cycle
    report = client.run_pressure(cycle=5, variant_outputs={...})

    # Run just the Bull/Bear debate
    verdict = client.run_debate(signal_context={...})

    # Risk debate for position sizing
    result = client.resolve_risk(risk_context={...})
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_BASE_PATH = "/omega.v1.AdversarialService/"


class AdversarialServiceError(Exception):
    """Raised when the Go AdversarialService returns an error response."""


class AdversarialServiceClient:
    """HTTP client for the Go AdversarialService Connect-RPC endpoint (JSON protocol)."""

    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _call(self, method: str, body: dict) -> Any:
        url = self._base_url + _BASE_PATH + method
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
            raise AdversarialServiceError(f"{method} failed ({exc.code}): {msg}") from exc
        except Exception as exc:
            raise AdversarialServiceError(f"{method} unavailable: {exc}") from exc

    # ── RunPressure ────────────────────────────────────────────────────────

    def run_pressure(
        self,
        cycle: int,
        variant_outputs: dict[str, dict[str, float]] | None = None,
        current_signals: dict[str, float] | None = None,
        strategy_params: dict[str, float] | None = None,
        run_ring2: bool = True,
        run_ring3: bool = False,
        run_debate: bool = True,
    ) -> dict[str, Any]:
        """Execute all three adversarial rings for a cycle.

        Args:
            cycle: Orchestrator cycle number.
            variant_outputs: {variant_name: {metric_name: value}} — output from
                each strategy variant. Used by Ring 1 ensemble disagreement.
            current_signals: Current market signals for Ring 2 scenario simulation.
            strategy_params: Strategy hyperparameters for Ring 3 tournament.
            run_ring2: Whether to activate Ring 2 scenario simulation.
            run_ring3: Whether to activate Ring 3 evolutionary tournament.
            run_debate: Whether to run the Bull/Bear DebateGate if Ring 1 flags.

        Returns:
            AdversarialReportV2 dict with keys: cycle, ring1, ring2, ring3,
            debateVerdict, riskDebate, overallFlagged, completedAt.
        """
        # Wrap inner metric maps in the VariantOutputs envelope
        wrapped_variants: dict[str, dict] = {}
        for name, metrics in (variant_outputs or {}).items():
            wrapped_variants[name] = {"metrics": metrics}

        resp = self._call(
            "RunPressure",
            {
                "cycle": cycle,
                "variantOutputs": wrapped_variants,
                "currentSignals": current_signals or {},
                "strategyParams": strategy_params or {},
                "runRing2": run_ring2,
                "runRing3": run_ring3,
                "runDebate": run_debate,
            },
        )
        return resp.get("report", resp)

    # ── RunDebate ──────────────────────────────────────────────────────────

    def run_debate(self, signal_context: dict[str, float]) -> dict[str, Any]:
        """Run the Bull/Bear debate gate on a signal context.

        Args:
            signal_context: Dict with fields matching SignalContext proto:
                compositeSignal, icShort, icLong, volRegime, regimeIc,
                recentSharpe, nodeErrorRate, atlDistance, rsi.

        Returns:
            DebateVerdict dict: {direction, confidence, positionScale,
            bullEvidence, bearEvidence, winningSide}
        """
        resp = self._call("RunDebate", {"context": signal_context})
        return resp.get("verdict", resp)

    # ── ResolveRisk ────────────────────────────────────────────────────────

    def resolve_risk(self, risk_context: dict[str, Any]) -> dict[str, Any]:
        """Run the three-persona risk debate for position sizing.

        Args:
            risk_context: Dict matching RiskContext proto fields:
                basePositionScale, portfolioDrawdown, currentVolatility,
                recentWinRate, kellyFraction, correlationMatrixFlat,
                correlationMatrixSize.

        Returns:
            RiskDebateResult dict: {finalPositionScale, verdicts, dominantPersona}
        """
        resp = self._call("ResolveRisk", {"context": risk_context})
        return resp.get("result", resp)

    # ── RecordGateResult ───────────────────────────────────────────────────

    def record_gate_result(
        self,
        cycle: int,
        gate_name: str,
        result: str,
        details: str = "",
    ) -> bool:
        """Persist the result of a simulation gate evaluation.

        Args:
            result: "pass" | "fail" | "skip"
        """
        resp = self._call(
            "RecordGateResult",
            {
                "cycle": cycle,
                "gateName": gate_name,
                "result": result,
                "details": details,
            },
        )
        return bool(resp.get("ok", False))

    # ── GetAdversarialReport ───────────────────────────────────────────────

    def get_adversarial_report(self, cycle: int) -> dict[str, Any] | None:
        """Retrieve the stored adversarial report for a cycle.

        Returns:
            AdversarialReportV2 dict, or None if not found.
        """
        resp = self._call("GetAdversarialReport", {"cycle": cycle})
        if not resp.get("found", False):
            return None
        return resp.get("report")

    # ── Convenience wrappers matching the task spec API ────────────────────

    def run_ensemble_pressure(
        self,
        node_id: str,
        predictions: dict[str, dict[str, float]],
        cycle: int = 0,
    ) -> dict[str, Any]:
        """Ring 1 only: check ensemble disagreement for a set of variant predictions.

        Args:
            node_id: Node ID (embedded in variant keys if needed).
            predictions: {variant_name: {metric: value}} dict.

        Returns:
            Ring1DisagreementResult portion of the full pressure report.
        """
        report = self.run_pressure(
            cycle=cycle,
            variant_outputs=predictions,
            run_ring2=False,
            run_ring3=False,
            run_debate=False,
        )
        return report.get("ring1", report)

    def run_scenario_pressure(
        self,
        node_id: str,
        scenarios: dict[str, float],
        cycle: int = 0,
    ) -> dict[str, Any]:
        """Ring 2 only: run scenario simulation pressure gate.

        Args:
            scenarios: Current signals fed to Ring 2 scenarios.

        Returns:
            Ring2SimulationReport portion of the full pressure report.
        """
        report = self.run_pressure(
            cycle=cycle,
            current_signals=scenarios,
            run_ring2=True,
            run_ring3=False,
            run_debate=False,
        )
        return report.get("ring2", report)

    def run_evolutionary_pressure(
        self,
        population: dict[str, float],
        cycle: int = 0,
    ) -> dict[str, Any]:
        """Ring 3 only: run evolutionary tournament over a strategy population.

        Args:
            population: Strategy parameters fed to the tournament.

        Returns:
            Ring3TournamentResult portion of the full pressure report.
        """
        report = self.run_pressure(
            cycle=cycle,
            strategy_params=population,
            run_ring2=False,
            run_ring3=True,
            run_debate=False,
        )
        return report.get("ring3", report)
