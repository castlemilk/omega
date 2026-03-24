"""
omega.core.tracing
~~~~~~~~~~~~~~~~~~~
OpenTelemetry-inspired distributed tracing for the Omega framework.

Concepts:
  TraceContext  : immutable context carrier (trace_id + span_id + parent_span_id)
  Span          : a single unit of work with start/end timing and status
  Tracer        : factory for creating spans, backed by StateStore
  TracingMiddleware : wraps Node.execute() to auto-create spans

Usage::
    tracer = Tracer(state_store)

    # Start a root trace for this heartbeat
    root_ctx = tracer.start_trace(operation="heartbeat_cycle", cycle=3)

    # Execute a node with tracing
    out, child_ctx = tracer.execute_with_tracing(
        node, node_input, parent_ctx=root_ctx
    )

    # End the root trace
    tracer.end_span(root_ctx.span_id, status="ok")

    # Get trace waterfall
    waterfall = tracer.get_waterfall(root_ctx.trace_id)
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput
from omega.core.state_store import StateBackend as StateStore

logger = logging.getLogger("omega.core.tracing")


@dataclass(frozen=True)
class TraceContext:
    """
    Immutable context carrier. Propagate through the call chain.

    frozen=True so it can be used as a dict key and can't be mutated.

    trace_id and span_id conform to W3C Trace Context (RFC):
      trace_id : 32 lowercase hex chars (128-bit)
      span_id  : 16 lowercase hex chars (64-bit)
    """

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    cycle: int = 0

    @property
    def traceparent(self) -> str:
        """W3C traceparent header value: ``00-<trace_id>-<span_id>-01``."""
        return f"00-{self.trace_id}-{self.span_id}-01"

    def child(self, new_span_id: str) -> "TraceContext":
        """Create a child context with this span as parent."""
        return TraceContext(
            trace_id=self.trace_id,
            span_id=new_span_id,
            parent_span_id=self.span_id,
            cycle=self.cycle,
        )

    @classmethod
    def from_traceparent(cls, header: str, cycle: int = 0) -> "TraceContext | None":
        """Parse a W3C traceparent header and return a TraceContext.

        Returns None if the header is absent or malformed.  The resulting
        context represents the *remote* span and can be passed as ``parent_ctx``
        to :meth:`Tracer.start_span`, enabling Go→Python trace propagation so
        both runtimes appear in the same trace tree.

        Expected format: ``00-<trace_id>-<parent_id>-<flags>``
          trace_id  : 32 lowercase hex chars (128-bit)
          parent_id : 16 lowercase hex chars (64-bit)
        """
        if not header:
            return None
        parts = header.split("-")
        if len(parts) < 4:
            return None
        trace_id, span_id = parts[1], parts[2]
        if len(trace_id) != 32 or len(span_id) != 16:
            return None
        return cls(trace_id=trace_id, span_id=span_id, cycle=cycle)


@dataclass
class SpanData:
    """Mutable span data (not the context)."""

    span_id: str
    trace_id: str
    parent_span_id: str | None
    node_id: str | None
    node_name: str | None
    operation: str
    started_at: float
    ended_at: float | None = None
    duration_ms: float | None = None
    status: str = "ok"
    metadata: dict[str, Any] = field(default_factory=dict)
    cycle: int = 0

    @property
    def is_complete(self) -> bool:
        return self.ended_at is not None

    def end(self, status: str = "ok", metadata: dict | None = None) -> None:
        self.ended_at = time.time()
        self.duration_ms = (self.ended_at - self.started_at) * 1000
        self.status = status
        if metadata:
            self.metadata.update(metadata)


class Tracer:
    """
    Creates and manages trace spans, backed by StateStore.

    Thread-safety: not required (Victoria runs single-threaded heartbeats).
    """

    def __init__(self, store: StateStore) -> None:
        self._store = store
        self._active_spans: dict[str, SpanData] = {}  # span_id → SpanData

    def start_trace(
        self,
        operation: str = "heartbeat",
        cycle: int = 0,
        node_id: str | None = None,
        node_name: str | None = None,
    ) -> TraceContext:
        """Start a new root trace. Returns the root TraceContext."""
        trace_id = uuid.uuid4().hex  # 32 lowercase hex chars — W3C trace-id format
        span_id = self._store.begin_span(
            trace_id=trace_id,
            node_id=node_id or "orchestrator",
            node_name=node_name or "Orchestrator",
            operation=operation,
            parent_span_id=None,
            cycle=cycle,
        )
        self._active_spans[span_id] = SpanData(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=None,
            node_id=node_id,
            node_name=node_name,
            operation=operation,
            started_at=time.time(),
            cycle=cycle,
        )
        logger.debug("Started trace %s (span=%s, op=%s)", trace_id[:8], span_id[:8], operation)
        return TraceContext(trace_id=trace_id, span_id=span_id, cycle=cycle)

    def start_span(
        self,
        parent_ctx: TraceContext,
        operation: str,
        node_id: str | None = None,
        node_name: str | None = None,
    ) -> TraceContext:
        """Start a child span under parent_ctx. Returns child TraceContext."""
        span_id = self._store.begin_span(
            trace_id=parent_ctx.trace_id,
            node_id=node_id or "unknown",
            node_name=node_name or "Unknown",
            operation=operation,
            parent_span_id=parent_ctx.span_id,
            cycle=parent_ctx.cycle,
        )
        self._active_spans[span_id] = SpanData(
            span_id=span_id,
            trace_id=parent_ctx.trace_id,
            parent_span_id=parent_ctx.span_id,
            node_id=node_id,
            node_name=node_name,
            operation=operation,
            started_at=time.time(),
            cycle=parent_ctx.cycle,
        )
        return parent_ctx.child(span_id)

    def end_span(
        self, span_id: str, status: str = "ok", metadata: dict | None = None
    ) -> float | None:
        """End a span. Returns duration_ms or None if span not found."""
        span = self._active_spans.pop(span_id, None)
        if span:
            span.end(status=status, metadata=metadata)
            self._store.end_span(span_id, status=status, metadata=span.metadata)
            logger.debug(
                "Ended span %s (op=%s, dur=%.1fms, status=%s)",
                span_id[:8],
                span.operation,
                span.duration_ms or 0,
                status,
            )
            return span.duration_ms
        else:
            # Span not in active set — still end it in the store
            self._store.end_span(span_id, status=status, metadata=metadata)
            return None

    def execute_with_tracing(
        self,
        node: Node,
        node_input: NodeInput,
        parent_ctx: TraceContext,
        node_id: str | None = None,
        node_name: str | None = None,
    ) -> tuple[NodeOutput, TraceContext]:
        """
        Execute node.execute(input) wrapped in a trace span.

        Returns (NodeOutput, child_TraceContext).
        The child context's span_id is the span for THIS node execution.
        """
        # Get node identity
        try:
            state = node.get_state()
            nid = node_id or state.node_id
            nname = node_name or state.name
        except Exception:
            nid = node_id or "unknown"
            nname = node_name or "Unknown"

        operation = f"{nname}.{node_input.action}"
        child_ctx = self.start_span(parent_ctx, operation=operation, node_id=nid, node_name=nname)

        try:
            output = node.execute(node_input)
            status = "ok" if output.success else "error"
            metadata = {
                "action": node_input.action,
                "success": output.success,
                "latency_ms": output.metrics.get("latency_ms"),
            }
            if not output.success:
                metadata["errors"] = output.errors[:2] if output.errors else []
            self.end_span(child_ctx.span_id, status=status, metadata=metadata)
            return output, child_ctx
        except Exception as exc:
            self.end_span(child_ctx.span_id, status="error", metadata={"exception": str(exc)})
            raise

    def get_waterfall(self, trace_id: str) -> list[dict]:
        """Return spans for a trace ordered by start time, formatted for display."""
        spans = self._store.get_trace(trace_id)
        spans.sort(key=lambda s: s.get("started_at", 0))

        result = []
        for s in spans:
            dur = s.get("duration_ms") or 0
            result.append(
                {
                    "span_id": s.get("span_id", "")[:8],
                    "parent_span_id": (s.get("parent_span_id") or "")[:8] or None,
                    "node": s.get("node_name", "?"),
                    "operation": s.get("operation", "?"),
                    "duration_ms": round(dur, 1),
                    "status": s.get("status", "ok"),
                    "cycle": s.get("cycle", 0),
                }
            )
        return result

    def format_waterfall(self, trace_id: str) -> str:
        """Return a human-readable ASCII waterfall for this trace."""
        spans = self.get_waterfall(trace_id)
        if not spans:
            return f"(no spans for trace {trace_id[:8]})"

        lines = [f"Trace {trace_id[:8]} — {len(spans)} spans"]
        for _i, s in enumerate(spans):
            prefix = "  └─ " if s["parent_span_id"] else "  ├─ "
            status_icon = "✓" if s["status"] == "ok" else "✗"
            lines.append(
                f"{prefix}{status_icon} {s['node']} :: {s['operation']}  [{s['duration_ms']:.0f}ms]"
            )
        return "\n".join(lines)

    def continue_trace(
        self,
        traceparent: str,
        operation: str,
        cycle: int = 0,
        node_id: str | None = None,
        node_name: str | None = None,
    ) -> TraceContext | None:
        """Start a child span continuing a remote trace from a W3C traceparent header.

        Returns None if the header is absent or malformed — caller should fall
        back to :meth:`start_trace`.  When successful, the returned context
        belongs to the same trace as the remote span that sent the header,
        allowing Go→Python spans to be joined in a single trace tree.
        """
        parent = TraceContext.from_traceparent(traceparent, cycle=cycle)
        if parent is None:
            return None
        return self.start_span(parent, operation=operation, node_id=node_id, node_name=node_name)

    def active_span_count(self) -> int:
        return len(self._active_spans)


def create_tracer(state_store: StateStore) -> Tracer:
    """Factory function — convenience wrapper."""
    return Tracer(store=state_store)
