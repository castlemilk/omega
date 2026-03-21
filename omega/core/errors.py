"""
omega.core.errors
~~~~~~~~~~~~~~~~~
Typed exception hierarchy for the Omega framework.

Every exception carries structured context (as a dict) so it can be
included directly in JSON log records without extra formatting.

Hierarchy::

    OmegaError
    ├── NodeExecutionError      (node_id, phase)
    ├── AlignmentRejectionError (decision, reason)
    ├── BrainError              (provider, model, operation)
    ├── DataProviderError       (provider, symbol)
    ├── MemoryStoreError        (store_type, operation)
    ├── VerificationGateError   (gate_type, evidence)
    └── ChallengeVetoError      (challenge_id, severity)

Usage::

    from omega.core.errors import NodeExecutionError
    raise NodeExecutionError("fetch failed", node_id="ingestion-01", phase="execute")
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class OmegaError(Exception):
    """Base class for all Omega framework errors.

    Every subclass stores its domain-specific fields both as named
    attributes AND inside ``self.context`` so callers can log the full
    dict without knowing the concrete error type.
    """

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.context: Dict[str, Any] = context or {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the error to a plain dict for structured logging."""
        return {
            "error_type": type(self).__name__,
            "message": str(self),
            **self.context,
        }


class NodeExecutionError(OmegaError):
    """Raised when a node fails during its execute/improve/evaluate cycle.

    Args:
        message: Human-readable description.
        node_id: The unique ID of the failing node.
        phase:   The lifecycle phase that failed (``"execute"``, ``"improve"``,
                 ``"evaluate"``, etc.).
        **extra: Any additional key/value pairs stored in ``context``.
    """

    def __init__(self, message: str, node_id: str, phase: str, **extra: Any) -> None:
        super().__init__(message, context={"node_id": node_id, "phase": phase, **extra})
        self.node_id = node_id
        self.phase = phase


class AlignmentRejectionError(OmegaError):
    """Raised when the alignment subsystem rejects an action or proposed improvement.

    Args:
        message:  Human-readable description.
        decision: The rejected decision identifier.
        reason:   Why the alignment check rejected it.
        **extra:  Additional context.
    """

    def __init__(self, message: str, decision: str, reason: str, **extra: Any) -> None:
        super().__init__(message, context={"decision": decision, "reason": reason, **extra})
        self.decision = decision
        self.reason = reason


class BrainError(OmegaError):
    """Raised when a brain adapter fails to produce a valid response.

    Args:
        message:   Human-readable description.
        provider:  Brain provider name (``"anthropic"``, ``"openai"``, …).
        model:     Model identifier used for the call.
        operation: What was being requested (``"think"``, ``"improve"``, …).
        **extra:   Additional context (e.g. HTTP status, raw response snippet).
    """

    def __init__(
        self,
        message: str,
        provider: str,
        model: str,
        operation: str,
        **extra: Any,
    ) -> None:
        super().__init__(
            message,
            context={"provider": provider, "model": model, "operation": operation, **extra},
        )
        self.provider = provider
        self.model = model
        self.operation = operation


class DataProviderError(OmegaError):
    """Raised when an external data provider (Binance, CoinGecko, …) fails.

    Args:
        message:  Human-readable description.
        provider: Data provider name.
        symbol:   Ticker symbol being fetched (empty string if N/A).
        **extra:  Additional context (e.g. HTTP status, response body snippet).
    """

    def __init__(
        self,
        message: str,
        provider: str,
        symbol: str = "",
        **extra: Any,
    ) -> None:
        super().__init__(message, context={"provider": provider, "symbol": symbol, **extra})
        self.provider = provider
        self.symbol = symbol


class MemoryStoreError(OmegaError):
    """Raised when the MemoryKernel or StateStore encounters an unrecoverable error.

    Named ``MemoryStoreError`` (not ``MemoryError``) to avoid shadowing
    the Python built-in ``MemoryError``.

    Args:
        message:    Human-readable description.
        store_type: Which store failed (``"state"``, ``"memory"``, ``"episodic"``, …).
        operation:  The operation that failed (``"read"``, ``"write"``, ``"migrate"``, …).
        **extra:    Additional context (e.g. table name, SQLite error).
    """

    def __init__(
        self,
        message: str,
        store_type: str,
        operation: str,
        **extra: Any,
    ) -> None:
        super().__init__(
            message,
            context={"store_type": store_type, "operation": operation, **extra},
        )
        self.store_type = store_type
        self.operation = operation


class VerificationGateError(OmegaError):
    """Raised when a verification gate blocks an action from proceeding.

    Args:
        message:   Human-readable description.
        gate_type: Which gate fired (``"property"``, ``"invariant"``, ``"convergence"``, …).
        evidence:  Structured evidence dict from the gate's evaluation.
        **extra:   Additional context.
    """

    def __init__(
        self,
        message: str,
        gate_type: str,
        evidence: Dict[str, Any],
        **extra: Any,
    ) -> None:
        super().__init__(
            message,
            context={"gate_type": gate_type, "evidence": evidence, **extra},
        )
        self.gate_type = gate_type
        self.evidence = evidence


class ChallengeVetoError(OmegaError):
    """Raised when an adversarial challenge ring vetoes an action.

    Args:
        message:      Human-readable description.
        challenge_id: Identifier of the adversarial challenge.
        severity:     Veto severity (``"low"``, ``"medium"``, ``"high"``, ``"critical"``).
        **extra:      Additional context (e.g. ring name, veto score).
    """

    def __init__(
        self,
        message: str,
        challenge_id: str,
        severity: str,
        **extra: Any,
    ) -> None:
        super().__init__(
            message,
            context={"challenge_id": challenge_id, "severity": severity, **extra},
        )
        self.challenge_id = challenge_id
        self.severity = severity
