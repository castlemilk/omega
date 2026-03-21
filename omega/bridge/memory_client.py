"""omega.bridge.memory_client — HTTP client for the Go MemoryService.

Uses Connect-RPC unary JSON protocol. Zero external dependencies (stdlib only).

Connect unary protocol:
  POST <base_url>/omega.v1.MemoryService/<MethodName>
  Content-Type: application/json
  Connect-Protocol-Version: 1
  Body: proto JSON (camelCase field names)

The MemoryService manages the triple-tier memory system:
  - Working memory: in-process TTL-aware key/value store
  - Episodic memory: timestamped SQLite-backed event log
  - Semantic memory: generalized pattern store consolidated from episodes

All writes go through this service so Go owns the SQLite layer.

Usage:
    client = MemoryServiceClient("http://localhost:8080")

    episode_id = client.store_episode(
        node_id="node-1",
        event_type="cycle_result",
        content={"sharpe": "1.4", "action": "buy"},
        importance=0.8,
        cycle=5,
    )
    episodes = client.query_episodes(namespace="node-1", top_k=10)
    client.store_working("node-1", "last_signal", {"value": 0.7}, ttl_seconds=300)
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

_BASE_PATH = "/omega.v1.MemoryService/"


class MemoryServiceError(Exception):
    """Raised when the Go MemoryService returns an error response."""


class MemoryServiceClient:
    """HTTP client for the Go MemoryService Connect-RPC endpoint (JSON protocol)."""

    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 5.0) -> None:
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
            raise MemoryServiceError(f"{method} failed ({exc.code}): {msg}") from exc
        except Exception as exc:
            raise MemoryServiceError(f"{method} unavailable: {exc}") from exc

    @staticmethod
    def _encode_content(d: dict | None) -> dict[str, str]:
        """Encode a content dict to map<string,string> by JSON-encoding non-string values."""
        if not d:
            return {}
        return {k: json.dumps(v) if not isinstance(v, str) else v for k, v in d.items()}

    # ── StoreEpisode ───────────────────────────────────────────────────────

    def store_episode(
        self,
        node_id: str,
        event_type: str,
        content: dict | None = None,
        tags: list[str] | None = None,
        importance: float = 0.5,
        cycle: int = 0,
    ) -> str:
        """Write a new episodic memory entry.

        Args:
            node_id: Namespace (node ID or subsystem).
            event_type: e.g. "cycle_result", "improvement", "alignment_decision".
            content: Arbitrary dict; values are JSON-encoded to str for proto.
            tags: Optional tag list for filtering.
            importance: [0, 1] — higher survives decay and consolidation.
            cycle: Orchestrator cycle number.

        Returns:
            The assigned episode ID.
        """
        resp = self._call(
            "StoreEpisode",
            {
                "namespace": node_id,
                "eventType": event_type,
                "content": self._encode_content(content),
                "tags": tags or [],
                "importance": importance,
                "cycle": cycle,
            },
        )
        return str(resp.get("episodeId", ""))

    # ── QueryEpisodes ──────────────────────────────────────────────────────

    def query_episodes(
        self,
        namespace: str,
        regime_tag: str = "",
        signal_type: str = "",
        current_regime: str = "",
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """Retrieve episodic memories matching the given filters.

        Returns:
            List of ScoredEpisode dicts: {episode: Episode, score: float}
        """
        resp = self._call(
            "QueryEpisodes",
            {
                "namespace": namespace,
                "regimeTag": regime_tag,
                "signalType": signal_type,
                "currentRegime": current_regime,
                "topK": top_k,
            },
        )
        return resp.get("results", [])

    # ── Working memory ─────────────────────────────────────────────────────

    def store_working(
        self,
        node_id: str,
        key: str,
        value: Any,
        ttl_seconds: int = 0,
    ) -> bool:
        """Write a key/value entry to working memory.

        Args:
            node_id: Namespace (node ID).
            key: Entry key.
            value: Any JSON-serialisable value.
            ttl_seconds: TTL in seconds; 0 = no expiry.

        Returns:
            True if the server acknowledged the write.
        """
        ttl_proto = {"seconds": ttl_seconds, "nanos": 0} if ttl_seconds else {}
        resp = self._call(
            "StoreWorking",
            {
                "namespace": node_id,
                "key": key,
                "valueJson": json.dumps(value),
                "ttl": ttl_proto,
            },
        )
        return bool(resp.get("ok", False))

    def get_working(self, node_id: str, key: str) -> Any | None:
        """Read a working memory entry by key.

        Returns:
            The decoded value, or None if absent/expired.
        """
        resp = self._call("GetWorking", {"namespace": node_id, "key": key})
        if not resp.get("found", False):
            return None
        value_json = resp.get("valueJson", "")
        if not value_json:
            return None
        return json.loads(value_json)

    def delete_working(self, node_id: str, key: str) -> bool:
        """Remove an entry from working memory."""
        resp = self._call("DeleteWorking", {"namespace": node_id, "key": key})
        return bool(resp.get("ok", False))

    # ── Consolidation ──────────────────────────────────────────────────────

    def trigger_consolidation(self, node_id: str) -> dict[str, Any]:
        """Run the consolidation pipeline for a namespace.

        Promotes high-importance episodes to semantic memories.

        Returns:
            ConsolidationResult: {episodesExamined, promotedToSemantic,
            pruned, newConceptIds}
        """
        resp = self._call("TriggerConsolidation", {"namespace": node_id})
        return resp.get("result", resp)

    # ── Semantic memory ────────────────────────────────────────────────────

    def query_semantic(
        self,
        namespace: str,
        tag_filter: str = "",
        text_query: str = "",
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Retrieve semantic memory concepts by tag and/or text search.

        Returns:
            List of MemoryConcept dicts.
        """
        resp = self._call(
            "QuerySemantic",
            {
                "namespace": namespace,
                "tagFilter": tag_filter,
                "textQuery": text_query,
                "topK": top_k,
            },
        )
        return resp.get("concepts", [])

    # ── Cycle lifecycle ────────────────────────────────────────────────────

    def begin_cycle(self, cycle_id: int, namespace: str = "global") -> dict[str, Any]:
        """Clear working memory and apply episodic decay for a new cycle.

        Returns:
            {ok, workingEntriesCleared, episodesDecayed}
        """
        return self._call("BeginCycle", {"namespace": namespace, "cycle": cycle_id})

    def end_cycle(
        self,
        cycle_id: int,
        namespace: str = "global",
        cycle_summary: dict | None = None,
        summary_importance: float = 0.5,
        trigger_consolidation: bool = False,
    ) -> dict[str, Any]:
        """Store the cycle summary episode and optionally trigger consolidation.

        Returns:
            {episodeId, consolidation: ConsolidationResult | None}
        """
        return self._call(
            "EndCycle",
            {
                "namespace": namespace,
                "cycle": cycle_id,
                "cycleSummary": self._encode_content(cycle_summary),
                "summaryImportance": summary_importance,
                "triggerConsolidation": trigger_consolidation,
            },
        )

    # ── Stats ──────────────────────────────────────────────────────────────

    def get_memory_stats(self, namespace: str) -> dict[str, Any]:
        """Return aggregate memory counts for a namespace.

        Returns:
            {namespace, episodicCount, semanticCount, workingCount,
            contradictionCount, regimeHistory}
        """
        return self._call("GetMemoryStats", {"namespace": namespace})
