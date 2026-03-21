"""Tests for omega.bridge.memory_client.MemoryServiceClient."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from omega.bridge.memory_client import MemoryServiceClient, MemoryServiceError


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


# ── store_episode ──────────────────────────────────────────────────────────


class TestStoreEpisode:
    def test_returns_episode_id(self):
        client = MemoryServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"episodeId": "ep-42"})):
            eid = client.store_episode("node-1", "cycle_result", {"sharpe": "1.4"}, cycle=5)
        assert eid == "ep-42"

    def test_sends_correct_namespace(self):
        client = MemoryServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"episodeId": "x"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.store_episode(
                "node-abc",
                "improvement",
                content={"delta": 0.1},
                tags=["improvement"],
                importance=0.9,
                cycle=3,
            )

        assert captured["body"]["namespace"] == "node-abc"
        assert captured["body"]["eventType"] == "improvement"
        assert captured["body"]["importance"] == pytest.approx(0.9)
        assert "improvement" in captured["body"]["tags"]

    def test_encodes_non_string_content_values(self):
        client = MemoryServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"episodeId": "x"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.store_episode("n1", "test", content={"value": 0.5, "flag": True})

        # Non-string values should be JSON-encoded
        content = captured["body"]["content"]
        assert content["value"] == "0.5"
        assert content["flag"] == "true"

    def test_raises_on_error(self):
        client = MemoryServiceClient()
        with patch("urllib.request.urlopen", side_effect=_mock_http_error({"message": "db error"})):
            with pytest.raises(MemoryServiceError):
                client.store_episode("n1", "event")


# ── query_episodes ─────────────────────────────────────────────────────────


class TestQueryEpisodes:
    def test_returns_results(self):
        client = MemoryServiceClient()
        results = [{"episode": {"episodeId": "e1"}, "score": 0.8}]
        with patch("urllib.request.urlopen", return_value=_mock_response({"results": results})):
            out = client.query_episodes("node-1", top_k=5)
        assert len(out) == 1
        assert out[0]["score"] == pytest.approx(0.8)

    def test_sends_filters(self):
        client = MemoryServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"results": []})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.query_episodes("ns", regime_tag="bull", signal_type="momentum", top_k=15)

        assert captured["body"]["namespace"] == "ns"
        assert captured["body"]["regimeTag"] == "bull"
        assert captured["body"]["signalType"] == "momentum"
        assert captured["body"]["topK"] == 15

    def test_returns_empty_on_missing_key(self):
        client = MemoryServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({})):
            out = client.query_episodes("ns")
        assert out == []


# ── working memory ─────────────────────────────────────────────────────────


class TestWorkingMemory:
    def test_store_working_returns_true(self):
        client = MemoryServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"ok": True})):
            result = client.store_working("n1", "last_signal", {"value": 0.7}, ttl_seconds=300)
        assert result is True

    def test_store_working_json_encodes_value(self):
        client = MemoryServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"ok": True})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.store_working("n1", "key", [1, 2, 3], ttl_seconds=60)

        assert json.loads(captured["body"]["valueJson"]) == [1, 2, 3]
        assert captured["body"]["ttl"]["seconds"] == 60

    def test_store_working_no_ttl(self):
        client = MemoryServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"ok": True})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.store_working("n1", "k", "v")

        assert captured["body"]["ttl"] == {}

    def test_get_working_returns_decoded_value(self):
        client = MemoryServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response(
            {"found": True, "valueJson": json.dumps({"score": 1.5})}
        )):
            val = client.get_working("n1", "k")
        assert val == {"score": 1.5}

    def test_get_working_returns_none_when_not_found(self):
        client = MemoryServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"found": False})):
            val = client.get_working("n1", "missing")
        assert val is None

    def test_delete_working(self):
        client = MemoryServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"ok": True})):
            result = client.delete_working("n1", "key")
        assert result is True


# ── trigger_consolidation ──────────────────────────────────────────────────


class TestTriggerConsolidation:
    def test_returns_consolidation_result(self):
        client = MemoryServiceClient()
        cr = {"episodesExamined": 50, "promotedToSemantic": 3, "pruned": 10}
        with patch("urllib.request.urlopen", return_value=_mock_response({"result": cr})):
            result = client.trigger_consolidation("node-1")
        assert result["promotedToSemantic"] == 3

    def test_sends_namespace(self):
        client = MemoryServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"result": {}})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.trigger_consolidation("my-node")

        assert captured["body"]["namespace"] == "my-node"


# ── cycle lifecycle ────────────────────────────────────────────────────────


class TestCycleLifecycle:
    def test_begin_cycle(self):
        client = MemoryServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response(
            {"ok": True, "workingEntriesCleared": 5, "episodesDecayed": 2}
        )):
            result = client.begin_cycle(cycle_id=10, namespace="node-1")
        assert result["ok"] is True
        assert result["workingEntriesCleared"] == 5

    def test_begin_cycle_sends_fields(self):
        client = MemoryServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"ok": True})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.begin_cycle(cycle_id=7, namespace="ns-x")

        assert captured["body"]["cycle"] == 7
        assert captured["body"]["namespace"] == "ns-x"

    def test_end_cycle(self):
        client = MemoryServiceClient()
        with patch("urllib.request.urlopen", return_value=_mock_response({"episodeId": "ep-99"})):
            result = client.end_cycle(
                cycle_id=10,
                namespace="node-1",
                cycle_summary={"sharpe": "1.3"},
                trigger_consolidation=True,
            )
        assert result["episodeId"] == "ep-99"

    def test_end_cycle_encodes_summary(self):
        client = MemoryServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"episodeId": "x"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.end_cycle(3, cycle_summary={"score": 0.9}, trigger_consolidation=False)

        # score is float → should be JSON-encoded string
        assert captured["body"]["cycleSummary"]["score"] == "0.9"
        assert captured["body"]["triggerConsolidation"] is False


# ── query_semantic ─────────────────────────────────────────────────────────


class TestQuerySemantic:
    def test_returns_concepts(self):
        client = MemoryServiceClient()
        concepts = [{"conceptId": "c1", "concept": "momentum works in bull"}]
        with patch("urllib.request.urlopen", return_value=_mock_response({"concepts": concepts})):
            result = client.query_semantic("node-1", tag_filter="bull", top_k=5)
        assert result == concepts

    def test_sends_filters(self):
        client = MemoryServiceClient()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["body"] = json.loads(req.data)
            return _mock_response({"concepts": []})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            client.query_semantic("ns", tag_filter="bear", text_query="drawdown", top_k=3)

        assert captured["body"]["tagFilter"] == "bear"
        assert captured["body"]["textQuery"] == "drawdown"
        assert captured["body"]["topK"] == 3
