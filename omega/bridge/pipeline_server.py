"""omega.bridge.pipeline_server — Connect-RPC pipeline step server for Python.

Serves the PipelineService over HTTP/1.1 Connect-RPC JSON protocol.
Zero external dependencies (stdlib only).

Connect unary protocol (inbound — Python is the server):
  POST /omega.v1.PipelineService/<MethodName>
  Content-Type: application/json
  Connect-Protocol-Version: 1
  Body: JSON proto message (camelCase fields)

Usage::

    registry = StepHandlerRegistry()
    registry.register("DATA_INGESTION", my_handler)
    server, thread = start_pipeline_server(port=9090, registry=registry)
    # later:
    server.shutdown()
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from omega.bridge.pipeline_types import ExecuteStepRequest, ExecuteStepResponse, PingResponse

log = logging.getLogger(__name__)

_SERVICE_PATH = "/omega.v1.PipelineService/"

StepHandler = Callable[[ExecuteStepRequest], ExecuteStepResponse]


class StepHandlerRegistry:
    """Maps (project_id, node_type) to step handler callables.

    Lookup order: (project_id, node_type) → ("", node_type) → error.
    Use project_id="" to register a global fallback handler.
    """

    def __init__(self) -> None:
        # Key is (project_id, node_type); project_id="" means global.
        self._handlers: dict[tuple[str, str], StepHandler] = {}

    def register(
        self,
        node_type: str,
        handler: StepHandler,
        project_id: str = "",
    ) -> None:
        key = (project_id, node_type)
        self._handlers[key] = handler
        log.debug(
            "Registered pipeline handler for project_id=%r node_type=%r",
            project_id,
            node_type,
        )

    def dispatch(self, req: ExecuteStepRequest) -> ExecuteStepResponse:
        # Try project-scoped handler first, then fall back to global.
        handler = self._handlers.get((req.project_id, req.node_type)) or self._handlers.get(
            ("", req.node_type)
        )
        if handler is None:
            return ExecuteStepResponse(
                success=False,
                error_text=f"no handler registered for node_type={req.node_type!r}",
            )
        t0 = time.perf_counter()
        try:
            resp = handler(req)
            resp.duration_ms = (time.perf_counter() - t0) * 1000
            return resp
        except Exception as exc:
            return ExecuteStepResponse(
                success=False,
                error_text=str(exc),
                duration_ms=(time.perf_counter() - t0) * 1000,
            )


@dataclass
class _ServerContext:
    registry: StepHandlerRegistry


def _make_handler(ctx: _ServerContext) -> type[BaseHTTPRequestHandler]:
    """Factory that closes over the server context for the HTTP handler class."""

    class _Handler(BaseHTTPRequestHandler):
        # Redirect access logs to our logger at DEBUG level to keep stdout clean.
        def log_message(self, fmt: str, *args: object) -> None:
            log.debug(fmt, *args)

        def do_POST(self) -> None:
            if not self.path.startswith(_SERVICE_PATH):
                self._send_error(404, "not found")
                return

            method = self.path[len(_SERVICE_PATH) :]
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"

            try:
                body = json.loads(raw)
            except Exception as exc:
                self._send_error(400, f"invalid JSON: {exc}")
                return

            traceparent = self.headers.get("traceparent", "")

            if method == "ExecuteStep":
                self._handle_execute_step(body, traceparent)
            elif method == "Ping":
                self._handle_ping()
            else:
                self._send_error(404, f"unknown method: {method!r}")

        def _handle_execute_step(self, body: dict, traceparent: str) -> None:
            req = ExecuteStepRequest.from_json(body)
            # If trace fields are absent in the JSON body but present in the
            # traceparent header, extract them from the header.
            if traceparent and not req.trace_id:
                parts = traceparent.split("-")
                if len(parts) >= 3:
                    req.trace_id = parts[1]
                    req.parent_span_id = parts[2]

            log.debug(
                "ExecuteStep: step=%r node_type=%r cycle=%d trace=%s",
                req.step_name,
                req.node_type,
                req.cycle,
                req.trace_id[:8] if req.trace_id else "",
            )
            resp = ctx.registry.dispatch(req)
            self._send_json(resp.to_json())

        def _handle_ping(self) -> None:
            self._send_json(PingResponse(ok=True).to_json())

        def _send_json(self, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_error(self, code: int, message: str) -> None:
            data = json.dumps({"code": "not_found", "message": message}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return _Handler


def start_pipeline_server(
    port: int = 9090,
    registry: StepHandlerRegistry | None = None,
    host: str = "",
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the pipeline server in a daemon background thread.

    Args:
        port:     TCP port to listen on.
        registry: Step handler registry. A default (stub-only) registry is
                  used if not provided.
        host:     Bind address (empty string = all interfaces).

    Returns:
        ``(server, thread)`` — call ``server.shutdown()`` to stop cleanly.
    """
    if registry is None:
        registry = StepHandlerRegistry()
    ctx = _ServerContext(registry=registry)
    handler_cls = _make_handler(ctx)
    server = ThreadingHTTPServer((host, port), handler_cls)
    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="pipeline-server",
    )
    thread.start()
    log.info("Pipeline server listening on %s:%d", host or "0.0.0.0", port)
    return server, thread
