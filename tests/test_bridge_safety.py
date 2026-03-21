"""Tests for omega.bridge.safety_client.SafetyServiceClient."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from omega.bridge.safety_client import (
    CHALLENGE_RESOLUTION_RESOLVED,
    CHALLENGE_SEVERITY_HIGH,
    GATE_PHASE_PRE_CYCLE,
    SafetyServiceClient,
    SafetyServiceError,
)


def _mock_response(body: dict):
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.read.return_value = json.dumps(body).encode()
    return mock


def _mock_http_error(body: dict, code: int = 400):
    import urllib.error
    return urllib.error.HTTPError(
        url="http://x",
        code=code,
        msg="err",
        hdrs=None,  # type: ignore[arg-type]
        fp=BytesIO(json.dumps(body).encode()),
    )


# ── check_alignment ────────────────────────────────────────────────────────


class TestCheckAlignment:
    def test_returns_alignment_response(self):
        client = SafetyServiceClient()
        body = {
            "approved": True,
            "violations": [],
            "goodhartWarning": False,
            "reasons": [],
        }
        with patch("urllib.request.urlopen", return_value=_mock_response(body)):
            result = client.check_alignment(
                node_metrics=[{"nodeId": "n1", "metrics": {"sharpe": 1.4}}],
                portfolio={"position_pct": 0.05},
                cycle=3,
            )
        assert result["approved"] is True
        assert result["goodhartWarning"] is False

    def test_sends_node_metrics(self):
        client = SafetyServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"approved": True})

        nm = [{"nodeId": "n1", "metrics": {"sharpe": 1.2}}]
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.check_alignment(node_metrics=nm, portfolio={"drawdown_pct": 0.03}, cycle=5)

        assert captured["body"]["nodeMetrics"] == nm
        assert captured["body"]["portfolio"]["drawdown_pct"] == pytest.approx(0.03)
        assert captured["body"]["cycle"] == 5

    def test_raises_on_server_error(self):
        client = SafetyServiceClient()
        with patch("urllib.request.urlopen", side_effect=_mock_http_error({"message": "nope"})):
            with pytest.raises(SafetyServiceError):
                client.check_alignment(node_metrics=[])


# ── verify_gates ───────────────────────────────────────────────────────────


class TestVerifyGates:
    def test_returns_verification_result(self):
        client = SafetyServiceClient()
        body = {"allPassed": True, "results": [], "passedCount": 5, "failedCount": 0}
        with patch("urllib.request.urlopen", return_value=_mock_response(body)):
            result = client.verify_gates(checks={"node_id": "n1"}, phase=GATE_PHASE_PRE_CYCLE)
        assert result["allPassed"] is True
        assert result["passedCount"] == 5

    def test_sends_phase_and_context(self):
        client = SafetyServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"allPassed": False})

        checks = {"node_id": "abc", "cycle": "3"}
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.verify_gates(checks=checks, phase=GATE_PHASE_PRE_CYCLE, cycle=3)

        assert captured["body"]["phase"] == GATE_PHASE_PRE_CYCLE
        assert captured["body"]["context"]["node_id"] == "abc"
        assert captured["body"]["cycle"] == 3


# ── evaluate_goals ─────────────────────────────────────────────────────────


class TestEvaluateGoals:
    def test_returns_goal_evaluation(self):
        client = SafetyServiceClient()
        body = {
            "approved": True,
            "compositeScore": 0.82,
            "scorecard": {"sharpe": "0.9"},
            "subtasks": [],
        }
        with patch("urllib.request.urlopen", return_value=_mock_response(body)):
            result = client.evaluate_goals("node-1", metrics={"sharpe": 1.4}, cycle=5)
        assert result["approved"] is True
        assert result["compositeScore"] == pytest.approx(0.82)

    def test_injects_node_id_into_state(self):
        client = SafetyServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"approved": True})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.evaluate_goals("my-node", metrics={"win_rate": 0.6})

        assert captured["body"]["systemState"]["node_id"] == "my-node"


# ── record_outcome_score ───────────────────────────────────────────────────


class TestRecordOutcomeScore:
    def test_returns_true_on_ok(self):
        client = SafetyServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"ok": True})):
            result = client.record_outcome_score("n1", predicted=0.5, actual=0.6, cycle=2)
        assert result is True

    def test_sends_correct_fields(self):
        client = SafetyServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"ok": True})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.record_outcome_score("n1", predicted=0.3, actual=0.4, return_contribution=0.01, cycle=7)

        assert captured["body"]["nodeId"] == "n1"
        assert captured["body"]["predicted"] == pytest.approx(0.3)
        assert captured["body"]["actual"] == pytest.approx(0.4)
        assert captured["body"]["returnContribution"] == pytest.approx(0.01)


# ── has_blocking_challenges ────────────────────────────────────────────────


class TestHasBlockingChallenges:
    def test_returns_true_when_blocking(self):
        client = SafetyServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"hasBlocking": True})):
            assert client.has_blocking_challenges() is True

    def test_returns_false_when_clear(self):
        client = SafetyServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"hasBlocking": False})):
            assert client.has_blocking_challenges() is False

    def test_blocking_challenge_counts(self):
        client = SafetyServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response(
            {"hasBlocking": True, "criticalCount": 2, "highCount": 1}
        )):
            counts = client.blocking_challenge_counts()
        assert counts["criticalCount"] == 2
        assert counts["highCount"] == 1


# ── open_challenge ─────────────────────────────────────────────────────────


class TestOpenChallenge:
    def test_returns_challenge_id(self):
        client = SafetyServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"challengeId": "ch-123", "created": True})):
            cid = client.open_challenge("adversarial", "Ring 1 always passes", evidence="logs show 0% flag rate")
        assert cid == "ch-123"

    def test_sends_correct_fields(self):
        client = SafetyServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"challengeId": "x"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.open_challenge(
                target_subsystem="memory",
                description="episodes not decaying",
                evidence="count grows without bound",
                severity=CHALLENGE_SEVERITY_HIGH,
                challenge_id="my-id",
            )

        assert captured["body"]["targetSubsystem"] == "memory"
        assert captured["body"]["severity"] == CHALLENGE_SEVERITY_HIGH
        assert captured["body"]["challengeId"] == "my-id"


# ── resolve_challenge ──────────────────────────────────────────────────────


class TestResolveChallenge:
    def test_returns_true_on_ok(self):
        client = SafetyServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"ok": True})):
            result = client.resolve_challenge("ch-1", resolution=CHALLENGE_RESOLUTION_RESOLVED)
        assert result is True

    def test_sends_resolution(self):
        client = SafetyServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"ok": True})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.resolve_challenge("ch-99", notes="fixed in v2")

        assert captured["body"]["challengeId"] == "ch-99"
        assert captured["body"]["notes"] == "fixed in v2"
