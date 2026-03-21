"""Tests for omega.core.errors — typed exception hierarchy."""

import pytest

from omega.core.errors import (
    AlignmentRejectionError,
    BrainError,
    ChallengeVetoError,
    DataProviderError,
    MemoryStoreError,
    NodeExecutionError,
    OmegaError,
    VerificationGateError,
)


class TestOmegaError:
    def test_base_message(self):
        err = OmegaError("something went wrong")
        assert str(err) == "something went wrong"

    def test_base_context_empty_by_default(self):
        err = OmegaError("msg")
        assert err.context == {}

    def test_base_context_provided(self):
        err = OmegaError("msg", context={"key": "val"})
        assert err.context["key"] == "val"

    def test_to_dict_includes_type(self):
        err = OmegaError("msg", context={"k": 1})
        d = err.to_dict()
        assert d["error_type"] == "OmegaError"
        assert d["message"] == "msg"
        assert d["k"] == 1

    def test_is_exception(self):
        with pytest.raises(OmegaError):
            raise OmegaError("boom")


class TestNodeExecutionError:
    def test_attributes(self):
        err = NodeExecutionError("exec failed", node_id="n-01", phase="execute")
        assert err.node_id == "n-01"
        assert err.phase == "execute"

    def test_context_populated(self):
        err = NodeExecutionError("exec failed", node_id="n-01", phase="improve", retry=3)
        assert err.context["node_id"] == "n-01"
        assert err.context["phase"] == "improve"
        assert err.context["retry"] == 3

    def test_is_omega_error(self):
        err = NodeExecutionError("fail", node_id="x", phase="evaluate")
        assert isinstance(err, OmegaError)

    def test_to_dict(self):
        err = NodeExecutionError("fail", node_id="abc", phase="execute")
        d = err.to_dict()
        assert d["error_type"] == "NodeExecutionError"
        assert d["node_id"] == "abc"


class TestAlignmentRejectionError:
    def test_attributes(self):
        err = AlignmentRejectionError("rejected", decision="improve_signals", reason="low confidence")
        assert err.decision == "improve_signals"
        assert err.reason == "low confidence"

    def test_context(self):
        err = AlignmentRejectionError("rejected", decision="d", reason="r", score=0.3)
        assert err.context["score"] == 0.3


class TestBrainError:
    def test_attributes(self):
        err = BrainError("API failed", provider="anthropic", model="claude-sonnet-4-6", operation="think")
        assert err.provider == "anthropic"
        assert err.model == "claude-sonnet-4-6"
        assert err.operation == "think"

    def test_to_dict(self):
        err = BrainError("fail", provider="openai", model="gpt-4o", operation="improve")
        d = err.to_dict()
        assert d["provider"] == "openai"
        assert d["model"] == "gpt-4o"


class TestDataProviderError:
    def test_attributes(self):
        err = DataProviderError("timeout", provider="binance", symbol="BTCUSDT")
        assert err.provider == "binance"
        assert err.symbol == "BTCUSDT"

    def test_symbol_default_empty(self):
        err = DataProviderError("down", provider="coingecko")
        assert err.symbol == ""

    def test_extra_context(self):
        err = DataProviderError("fail", provider="binance", symbol="ETHUSDT", status_code=429)
        assert err.context["status_code"] == 429


class TestMemoryStoreError:
    def test_attributes(self):
        err = MemoryStoreError("write failed", store_type="episodic", operation="write")
        assert err.store_type == "episodic"
        assert err.operation == "write"

    def test_does_not_shadow_builtin(self):
        """MemoryStoreError must not shadow the built-in MemoryError."""
        assert MemoryStoreError is not MemoryError

    def test_is_omega_error(self):
        err = MemoryStoreError("fail", store_type="state", operation="read")
        assert isinstance(err, OmegaError)


class TestVerificationGateError:
    def test_attributes(self):
        evidence = {"property": "sharpe > 0", "actual": -0.2}
        err = VerificationGateError("gate blocked", gate_type="property", evidence=evidence)
        assert err.gate_type == "property"
        assert err.evidence == evidence

    def test_context_includes_evidence(self):
        evidence = {"check": "invariant"}
        err = VerificationGateError("fail", gate_type="invariant", evidence=evidence)
        assert err.context["evidence"] == evidence


class TestChallengeVetoError:
    def test_attributes(self):
        err = ChallengeVetoError("vetoed", challenge_id="chall-01", severity="high")
        assert err.challenge_id == "chall-01"
        assert err.severity == "high"

    def test_extra_context(self):
        err = ChallengeVetoError("veto", challenge_id="c", severity="critical", ring="adversarial-ring-1")
        assert err.context["ring"] == "adversarial-ring-1"

    def test_is_omega_error(self):
        err = ChallengeVetoError("fail", challenge_id="x", severity="low")
        assert isinstance(err, OmegaError)
