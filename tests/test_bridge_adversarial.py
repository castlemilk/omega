"""Tests for omega.bridge.adversarial_client.AdversarialServiceClient."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from omega.bridge.adversarial_client import AdversarialServiceClient, AdversarialServiceError


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


# ── run_pressure ───────────────────────────────────────────────────────────


class TestRunPressure:
    def test_returns_report_dict(self):
        client = AdversarialServiceClient()
        report = {
            "cycle": 5,
            "ring1": {"flagged": False, "disagreementScore": 0.1},
            "overallFlagged": False,
        }
        with patch("urllib.request.urlopen", return_value=_mock_response({"report": report})):
            result = client.run_pressure(cycle=5)
        assert result["overallFlagged"] is False
        assert result["ring1"]["flagged"] is False

    def test_wraps_variant_outputs(self):
        client = AdversarialServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"report": {}})

        variants = {"v1": {"sharpe": 1.2}, "v2": {"sharpe": 0.8}}
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.run_pressure(cycle=1, variant_outputs=variants)

        wrapped = captured["body"]["variantOutputs"]
        assert wrapped["v1"] == {"metrics": {"sharpe": 1.2}}
        assert wrapped["v2"] == {"metrics": {"sharpe": 0.8}}

    def test_sends_flags_correctly(self):
        client = AdversarialServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"report": {}})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.run_pressure(cycle=3, run_ring2=True, run_ring3=True, run_debate=False)

        assert captured["body"]["runRing2"] is True
        assert captured["body"]["runRing3"] is True
        assert captured["body"]["runDebate"] is False

    def test_raises_on_server_error(self):
        client = AdversarialServiceClient()
        with patch("urllib.request.urlopen", side_effect=_mock_http_error({"message": "oops"})):
            with pytest.raises(AdversarialServiceError):
                client.run_pressure(cycle=1)

    def test_returns_raw_response_if_no_report_key(self):
        client = AdversarialServiceClient()
        raw = {"overallFlagged": True}
        with patch("urllib.request.urlopen", return_value=_mock_response(raw)):
            result = client.run_pressure(cycle=1)
        assert result["overallFlagged"] is True


# ── run_debate ─────────────────────────────────────────────────────────────


class TestRunDebate:
    def test_returns_verdict(self):
        client = AdversarialServiceClient()
        verdict = {"direction": "TRADE_DIRECTION_BUY", "confidence": 0.75, "winningSide": "bull"}
        with patch("urllib.request.urlopen", return_value=_mock_response({"verdict": verdict})):
            result = client.run_debate({"compositeSignal": 0.6})
        assert result["winningSide"] == "bull"

    def test_sends_context(self):
        client = AdversarialServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"verdict": {}})

        ctx = {"compositeSignal": 0.5, "rsi": 45.0}
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.run_debate(ctx)

        assert captured["body"]["context"] == ctx


# ── resolve_risk ───────────────────────────────────────────────────────────


class TestResolveRisk:
    def test_returns_result(self):
        client = AdversarialServiceClient()
        result_body = {"finalPositionScale": 0.6, "dominantPersona": "neutral"}
        with patch("urllib.request.urlopen", return_value=_mock_response({"result": result_body})):
            result = client.resolve_risk({"basePositionScale": 0.8, "portfolioDrawdown": 0.05})
        assert result["finalPositionScale"] == pytest.approx(0.6)

    def test_sends_context(self):
        client = AdversarialServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"result": {}})

        ctx = {"basePositionScale": 0.5, "kellyFraction": 0.25}
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.resolve_risk(ctx)

        assert captured["body"]["context"] == ctx


# ── record_gate_result ─────────────────────────────────────────────────────


class TestRecordGateResult:
    def test_returns_true_on_ok(self):
        client = AdversarialServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"ok": True})):
            result = client.record_gate_result(cycle=1, gate_name="ring1", result="pass")
        assert result is True

    def test_sends_gate_info(self):
        client = AdversarialServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"ok": True})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.record_gate_result(cycle=7, gate_name="ring2", result="fail", details="too low")

        assert captured["body"]["cycle"] == 7
        assert captured["body"]["gateName"] == "ring2"
        assert captured["body"]["result"] == "fail"
        assert captured["body"]["details"] == "too low"


# ── get_adversarial_report ─────────────────────────────────────────────────


class TestGetAdversarialReport:
    def test_returns_report_when_found(self):
        client = AdversarialServiceClient()
        report = {"cycle": 3, "overallFlagged": True}
        with patch("urllib.request.urlopen", return_value=_mock_response({"report": report, "found": True})):
            result = client.get_adversarial_report(3)
        assert result is not None
        assert result["cycle"] == 3

    def test_returns_none_when_not_found(self):
        client = AdversarialServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"found": False})):
            result = client.get_adversarial_report(99)
        assert result is None


# ── convenience wrappers ───────────────────────────────────────────────────


class TestConvenienceWrappers:
    def test_run_ensemble_pressure_disables_ring2_ring3(self):
        client = AdversarialServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"report": {"ring1": {"flagged": False}}})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.run_ensemble_pressure("n1", {"v1": {"sharpe": 1.0}})

        assert captured["body"]["runRing2"] is False
        assert captured["body"]["runRing3"] is False
        assert captured["body"]["runDebate"] is False

    def test_run_scenario_pressure_enables_ring2(self):
        client = AdversarialServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"report": {"ring2": {}}})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.run_scenario_pressure("n1", {"signal": 0.5})

        assert captured["body"]["runRing2"] is True

    def test_run_evolutionary_pressure_enables_ring3(self):
        client = AdversarialServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"report": {"ring3": {}}})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.run_evolutionary_pressure({"lr": 0.01})

        assert captured["body"]["runRing3"] is True
