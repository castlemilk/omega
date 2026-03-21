"""
omega.nodes.web_fetcher
~~~~~~~~~~~~~~~~~~~~~~~~
Fetches web content and demonstrates improvement via caching + retry logic.

Improvement arc
---------------
v1.0 — Simple urllib fetch, no retry, no caching.
v1.1 — In-memory response cache added (TTL-based).
v1.2 — Exponential back-off retry added (up to 3 attempts).

NOTE: This node makes real HTTP requests.  In tests / offline environments
pass ``dry_run=True`` to the constructor; all fetches return a stub response.
"""

import hashlib
import logging
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState

logger = logging.getLogger("omega.nodes.web_fetcher")

_DEFAULT_TIMEOUT_S = 10
_CACHE_TTL_S = 300  # 5-minute cache TTL
_MAX_RETRIES = 3
_RETRY_BASE_DELAY_S = 0.5


class WebFetcherNode(Node):
    """
    HTTP content fetcher node.

    Capabilities : fetch, fetch_text, fetch_status
    Improves via : response caching, retry with exponential back-off
    """

    def __init__(self, timeout_s: int = _DEFAULT_TIMEOUT_S, dry_run: bool = False) -> None:
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._timeout_s = timeout_s
        self._dry_run = dry_run

        self._use_cache = False
        self._use_retry = False
        self._cache: dict[str, tuple[str, float]] = {}  # url_hash → (content, expiry)

        self._execution_count = 0
        self._error_count = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._total_latency_ms = 0.0

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._node_id,
            name="WebFetcherNode",
            version=self._version,
            health=1.0
            if self._error_count == 0
            else max(0.0, 1.0 - self._error_count / max(1, self._execution_count)),
            capabilities=["fetch", "fetch_text", "fetch_status"],
            metrics={
                "avg_latency_ms": self._avg_latency_ms(),
                "cache_hit_rate": self._cache_hit_rate(),
                "error_rate": self._error_count / max(1, self._execution_count),
                "execution_count": float(self._execution_count),
            },
            metadata={
                "use_cache": self._use_cache,
                "use_retry": self._use_retry,
                "cached_urls": len(self._cache),
            },
        )

    def get_capabilities(self) -> list[str]:
        return ["fetch", "fetch_text", "fetch_status"]

    def describe(self) -> str:
        return (
            "Fetches HTTP content from a URL.  "
            "'fetch' returns the full response body as a string.  "
            "'fetch_text' returns only text/html bodies.  "
            "'fetch_status' returns just the HTTP status code.  "
            "Accepts parameter 'url' (str).  "
            "Can self-improve by adding response caching and retry logic."
        )

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        action = input.action.lower()
        url = input.parameters.get("url", "")

        if not url:
            elapsed = (time.perf_counter() - t0) * 1000
            self._error_count += 1
            self._execution_count += 1
            self._total_latency_ms += elapsed
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=["Missing required parameter: 'url'"],
                metrics={"latency_ms": elapsed},
            )

        if action not in self.get_capabilities():
            elapsed = (time.perf_counter() - t0) * 1000
            self._error_count += 1
            self._execution_count += 1
            self._total_latency_ms += elapsed
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[f"Unknown action '{action}'"],
                metrics={"latency_ms": elapsed},
            )

        # Cache lookup
        url_hash = hashlib.md5(url.encode()).hexdigest()
        now = time.time()

        if self._use_cache:
            cached = self._cache.get(url_hash)
            if cached and cached[1] > now:
                self._cache_hits += 1
                self._execution_count += 1
                elapsed = (time.perf_counter() - t0) * 1000
                self._total_latency_ms += elapsed
                result = cached[0] if action != "fetch_status" else 200
                return NodeOutput(
                    request_id=input.request_id,
                    success=True,
                    result=result,
                    metrics={"latency_ms": elapsed, "cache_hit": 1.0},
                )

        # Fetch
        content, status, error = self._do_fetch(url)
        elapsed = (time.perf_counter() - t0) * 1000
        self._execution_count += 1
        self._total_latency_ms += elapsed

        if error:
            self._error_count += 1
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[error],
                metrics={"latency_ms": elapsed},
            )

        if self._use_cache and content:
            self._cache[url_hash] = (content, now + _CACHE_TTL_S)
        self._cache_misses += 1

        result = status if action == "fetch_status" else content  # type: ignore[assignment]
        return NodeOutput(
            request_id=input.request_id,
            success=True,
            result=result,
            metrics={"latency_ms": elapsed, "cache_hit": 0.0, "status_code": float(status)},
        )

    def evaluate(self) -> dict[str, float]:
        return {
            "avg_latency_ms": self._avg_latency_ms(),
            "cache_hit_rate": self._cache_hit_rate(),
            "error_rate": self._error_count / max(1, self._execution_count),
        }

    def improve(self, feedback: dict[str, Any]) -> bool:
        changed = False

        if feedback.get("improve_latency") and not self._use_cache:
            self._use_cache = True
            self._version = "1.1"
            logger.info("WebFetcherNode improved to v1.1: response caching enabled")
            changed = True

        if (
            feedback.get("iteration", 0) >= 2
            and not self._use_retry
            and feedback.get("node_metrics", {}).get("error_rate", 0) > 0.1
        ):
            self._use_retry = True
            self._version = "1.2" if self._use_cache else "1.1r"
            logger.info("WebFetcherNode improved: retry logic enabled")
            changed = True

        return changed

    # ------------------------------------------------------------------
    # Internal fetch
    # ------------------------------------------------------------------

    def _do_fetch(self, url: str) -> tuple[str | None, int, str | None]:
        """
        Returns (content, status_code, error_message).
        On success error_message is None.
        """
        if self._dry_run:
            time.sleep(0.002)  # simulate tiny network delay
            return f"<stub response for {url}>", 200, None

        attempts = _MAX_RETRIES if self._use_retry else 1
        last_error: str | None = None

        for attempt in range(attempts):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "OmegaWebFetcherNode/1.0"},
                )
                with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                    content = resp.read().decode("utf-8", errors="replace")
                    return content, resp.status, None

            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code}: {exc.reason}"
                break  # HTTP errors don't benefit from retry
            except urllib.error.URLError as exc:
                last_error = f"URL error: {exc.reason}"
            except Exception as exc:
                last_error = str(exc)

            if attempt < attempts - 1:
                delay = _RETRY_BASE_DELAY_S * (2**attempt)
                logger.debug("Retry %d/%d in %.1fs for %s", attempt + 1, attempts, delay, url)
                time.sleep(delay)

        return None, 0, last_error or "Unknown fetch error"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _avg_latency_ms(self) -> float:
        return self._total_latency_ms / max(1, self._execution_count)

    def _cache_hit_rate(self) -> float:
        total = self._cache_hits + self._cache_misses
        return self._cache_hits / total if total > 0 else 0.0
