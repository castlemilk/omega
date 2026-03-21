"""Tests for omega.bridge.improvement_client.ImprovementServiceClient."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from omega.bridge.improvement_client import ImprovementServiceClient, ImprovementServiceError


def _mock_response(body: dict):
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.read.return_value = json.dumps(body).encode()
    return mock


def _mock_http_error(body: dict, code: int = 500):
    import urllib.error
    return urllib.error.HTTPError(
        url="http://x",
        code=code,
        msg="err",
        hdrs=None,  # type: ignore[arg-type]
        fp=BytesIO(json.dumps(body).encode()),
    )


# ── due_nodes ──────────────────────────────────────────────────────────────


class TestDueNodes:
    def test_returns_list_of_node_ids(self):
        client = ImprovementServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"nodeIds": ["n1", "n2"]})):
            result = client.due_nodes(cycle=5)
        assert result == ["n1", "n2"]

    def test_returns_empty_when_none_due(self):
        client = ImprovementServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"nodeIds": []})):
            result = client.due_nodes()
        assert result == []

    def test_sends_cycle(self):
        client = ImprovementServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"nodeIds": []})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.due_nodes(cycle=42)

        assert captured["body"]["cycle"] == 42

    def test_raises_on_server_error(self):
        client = ImprovementServiceClient()
        with patch("urllib.request.urlopen", side_effect=_mock_http_error({"message": "fail"})):
            with pytest.raises(ImprovementServiceError):
                client.due_nodes()


# ── record_outcome ─────────────────────────────────────────────────────────


class TestRecordOutcome:
    def test_returns_schedule_response(self):
        client = ImprovementServiceClient()
        body = {"nextRunAt": {}, "updatedEntry": {"nodeId": "n1"}}
        with patch("urllib.request.urlopen", return_value=_mock_response(body)):
            result = client.record_outcome("n1", success=True, score=1.4, cycle=5)
        assert result["updatedEntry"]["nodeId"] == "n1"

    def test_sends_all_fields(self):
        client = ImprovementServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({})

        before = {"sharpe": 1.0}
        after = {"sharpe": 1.4}
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.record_outcome(
                "node-X",
                success=True,
                score=0.4,
                cycle=7,
                before_metrics=before,
                after_metrics=after,
            )

        assert captured["body"]["nodeId"] == "node-X"
        assert captured["body"]["success"] is True
        assert captured["body"]["score"] == pytest.approx(0.4)
        assert captured["body"]["cycle"] == 7
        assert captured["body"]["beforeMetrics"] == before
        assert captured["body"]["afterMetrics"] == after

    def test_outcome_kwarg_is_accepted_but_not_sent(self):
        """The outcome dict kwarg is accepted for API compat but not serialised."""
        client = ImprovementServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.record_outcome("n1", outcome={"extra": "data"}, success=True)

        assert "outcome" not in captured["body"]


# ── propose_trial_params ───────────────────────────────────────────────────


class TestProposeTrialParams:
    def test_returns_params_dict(self):
        client = ImprovementServiceClient()
        body = {"params": {"lr": 0.01, "window": 20.0}, "expectedImprovement": 0.05, "strategy": "tpe"}
        with patch("urllib.request.urlopen", return_value=_mock_response(body)):
            result = client.propose_trial_params("n1")
        assert result["params"]["lr"] == pytest.approx(0.01)
        assert result["strategy"] == "tpe"

    def test_sends_history(self):
        client = ImprovementServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"params": {}})

        history = [
            {"params": {"lr": 0.005}, "score": 1.2, "success": True, "cycle": 1},
            {"params": {"lr": 0.01}, "score": 1.4, "success": True, "cycle": 2},
        ]
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.propose_trial_params("n1", history=history)

        sent = captured["body"]["history"]
        assert len(sent) == 2
        assert sent[0]["params"] == {"lr": 0.005}
        assert sent[1]["score"] == pytest.approx(1.4)

    def test_encodes_param_space(self):
        client = ImprovementServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"params": {}})

        space = {
            "lr": {"low": 0.001, "high": 0.1, "log": True},
            "window": 20,
        }
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.propose_trial_params("n1", param_space=space)

        ps = captured["body"]["paramSpace"]
        # Non-string values should be JSON-encoded
        assert json.loads(ps["lr"])["log"] is True
        assert json.loads(ps["window"]) == 20


# ── compile_strategy ───────────────────────────────────────────────────────


class TestCompileStrategy:
    def test_returns_compiled_strategy(self):
        client = ImprovementServiceClient()
        body = {
            "strategyId": "strat-001",
            "checksum": "abc123",
            "nodeVersion": "v2",
            "compiledAt": "2026-01-01T00:00:00Z",
        }
        with patch("urllib.request.urlopen", return_value=_mock_response(body)):
            result = client.compile_strategy("n1", version="v2", parameters={"lr": 0.01})
        assert result["strategyId"] == "strat-001"
        assert result["checksum"] == "abc123"

    def test_sends_rules(self):
        client = ImprovementServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"strategyId": "x"})

        rules = [
            {
                "name": "buy_signal",
                "conditions": [{"fieldPath": "rsi", "operator": "lt", "threshold": 30.0}],
                "confidence": 0.8,
            }
        ]
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.compile_strategy("n1", version="v1", parameters={}, rules=rules)

        assert captured["body"]["rules"] == rules
        assert captured["body"]["nodeId"] == "n1"
        assert captured["body"]["nodeVersion"] == "v1"


# ── rollback_strategy ──────────────────────────────────────────────────────


class TestRollbackStrategy:
    def test_returns_true_on_ok(self):
        client = ImprovementServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"ok": True})):
            result = client.rollback_strategy("n1", version=3)
        assert result is True

    def test_returns_false_on_failure(self):
        client = ImprovementServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"ok": False})):
            result = client.rollback_strategy("n1", version=99)
        assert result is False

    def test_sends_target_version(self):
        client = ImprovementServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"ok": True})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.rollback_strategy("node-abc", version=5)

        assert captured["body"]["nodeId"] == "node-abc"
        assert captured["body"]["targetVersion"] == 5


# ── schedule / list ────────────────────────────────────────────────────────


class TestScheduleAndList:
    def test_get_improvement_schedule_returns_entry(self):
        client = ImprovementServiceClient()
        entry = {"nodeId": "n1", "priority": 1.0}
        with patch("urllib.request.urlopen", return_value=_mock_response({"entry": entry, "found": True})):
            result = client.get_improvement_schedule("n1")
        assert result == entry

    def test_get_improvement_schedule_returns_none_when_not_found(self):
        client = ImprovementServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"found": False})):
            result = client.get_improvement_schedule("n1")
        assert result is None

    def test_list_improved_nodes(self):
        client = ImprovementServiceClient()
        entries = [{"nodeId": "n1"}, {"nodeId": "n2"}]
        with patch("urllib.request.urlopen", return_value=_mock_response({"entries": entries})):
            result = client.list_improved_nodes()
        assert len(result) == 2
        assert result[0]["nodeId"] == "n1"
