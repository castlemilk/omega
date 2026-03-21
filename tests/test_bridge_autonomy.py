"""Tests for omega.bridge.autonomy_client.AutonomyServiceClient."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from omega.bridge.autonomy_client import (
    AUTONOMY_LEVEL_MANUAL,
    AUTONOMY_LEVEL_SUPERVISED,
    AutonomyServiceClient,
    AutonomyServiceError,
)


def _mock_response(body: dict, status: int = 200):
    """Return a mock HTTP response that urllib.request.urlopen can use as context manager."""
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.read.return_value = json.dumps(body).encode()
    mock.status = status
    return mock


def _mock_http_error(body: dict, code: int = 400):
    import urllib.error

    err = urllib.error.HTTPError(
        url="http://x",
        code=code,
        msg="err",
        hdrs=None,  # type: ignore[arg-type]
        fp=BytesIO(json.dumps(body).encode()),
    )
    return err


# ── record_cycle_metrics ───────────────────────────────────────────────────


class TestRecordCycleMetrics:
    def test_returns_true_on_ok(self):
        client = AutonomyServiceClient("http://localhost:9999")
        with patch("urllib.request.urlopen", return_value=_mock_response({"ok": True})):
            result = client.record_cycle_metrics("node-1", cycle=5, metrics={"sharpe": 1.4})
        assert result is True

    def test_returns_false_when_not_ok(self):
        client = AutonomyServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"ok": False})):
            result = client.record_cycle_metrics("node-1", cycle=1, metrics={})
        assert result is False

    def test_sends_correct_payload(self):
        client = AutonomyServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"ok": True})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.record_cycle_metrics("node-X", cycle=3, metrics={"win_rate": 0.6}, success=False)

        assert captured["body"]["nodeId"] == "node-X"
        assert captured["body"]["cycle"] == 3
        assert captured["body"]["metrics"]["win_rate"] == pytest.approx(0.6)
        assert captured["body"]["success"] is False

    def test_raises_on_http_error(self):
        client = AutonomyServiceClient()
        with patch("urllib.request.urlopen", side_effect=_mock_http_error({"message": "bad"}, 500)), pytest.raises(AutonomyServiceError, match="RecordCycleMetrics failed"):
            client.record_cycle_metrics("node-1", cycle=1, metrics={})


# ── get_autonomy_level ─────────────────────────────────────────────────────


class TestGetAutonomyLevel:
    def test_returns_dict(self):
        client = AutonomyServiceClient()
        body = {
            "nodeId": "node-1",
            "level": AUTONOMY_LEVEL_SUPERVISED,
            "confidence": 0.85,
            "cyclesAtLevel": 12,
        }
        with patch("urllib.request.urlopen", return_value=_mock_response(body)):
            result = client.get_autonomy_level("node-1")
        assert result["level"] == AUTONOMY_LEVEL_SUPERVISED
        assert result["confidence"] == pytest.approx(0.85)

    def test_sends_node_id(self):
        client = AutonomyServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"nodeId": "abc", "level": "AUTONOMY_LEVEL_MANUAL"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.get_autonomy_level("abc")

        assert captured["body"]["nodeId"] == "abc"


# ── request_promotion ──────────────────────────────────────────────────────


class TestRequestPromotion:
    def test_returns_true_when_approved(self):
        client = AutonomyServiceClient()
        resp = {"approved": True, "grantedLevel": AUTONOMY_LEVEL_SUPERVISED, "reasons": []}
        with patch("urllib.request.urlopen", return_value=_mock_response(resp)):
            result = client.request_promotion("node-1", justification="12 clean cycles")
        assert result is True

    def test_returns_false_when_denied(self):
        client = AutonomyServiceClient()
        resp = {"approved": False, "reasons": ["insufficient cycles"]}
        with patch("urllib.request.urlopen", return_value=_mock_response(resp)):
            result = client.request_promotion("node-1", justification="try")
        assert result is False

    def test_sends_justification_as_reason(self):
        client = AutonomyServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"approved": True})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.request_promotion(
                "node-1",
                justification="great performance",
                requested_level=AUTONOMY_LEVEL_SUPERVISED,
                supporting_metrics={"sharpe": 1.8},
                cycle=10,
            )

        assert captured["body"]["reason"] == "great performance"
        assert captured["body"]["requestedLevel"] == AUTONOMY_LEVEL_SUPERVISED
        assert captured["body"]["supportingMetrics"]["sharpe"] == pytest.approx(1.8)


# ── record_promotion ───────────────────────────────────────────────────────


class TestRecordPromotion:
    def test_returns_true_on_ok(self):
        client = AutonomyServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"ok": True})):
            result = client.record_promotion(
                "node-1", AUTONOMY_LEVEL_MANUAL, AUTONOMY_LEVEL_SUPERVISED
            )
        assert result is True


# ── get_autonomy_history ───────────────────────────────────────────────────


class TestGetAutonomyHistory:
    def test_returns_events_list(self):
        client = AutonomyServiceClient()
        events = [{"nodeId": "n1", "trigger": "promotion"}]
        with patch("urllib.request.urlopen", return_value=_mock_response({"events": events})):
            result = client.get_autonomy_history("n1")
        assert result == events

    def test_returns_empty_when_missing(self):
        client = AutonomyServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({})):
            result = client.get_autonomy_history("n1")
        assert result == []


# ── stream_node_metrics ────────────────────────────────────────────────────


class TestStreamNodeMetrics:
    def test_yields_events_and_stops_at_max(self):
        client = AutonomyServiceClient()
        event = {"nodeId": "n1", "cycle": 1, "metrics": {"sharpe": 1.2}}
        call_count = 0

        def fake_urlopen(req, timeout):
            nonlocal call_count
            call_count += 1
            return _mock_response(event)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("time.sleep"):  # don't actually sleep
            results = list(
                client.stream_node_metrics(node_id="n1", max_events=3, poll_interval_ms=100)
            )

        assert len(results) == 3
        assert results[0]["nodeId"] == "n1"

    def test_handles_events_list_response(self):
        client = AutonomyServiceClient()
        events = [
            {"nodeId": "n1", "cycle": 1},
            {"nodeId": "n2", "cycle": 1},
        ]

        def fake_urlopen(req, timeout):
            return _mock_response({"events": events})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("time.sleep"):
            results = list(
                client.stream_node_metrics(max_events=2, poll_interval_ms=50)
            )

        assert len(results) == 2
