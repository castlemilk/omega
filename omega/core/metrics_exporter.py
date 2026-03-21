"""
omega.core.metrics_exporter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Prometheus metrics exporter for the Omega system.

Serves /metrics in Prometheus exposition format on port 9090.

Design constraints
------------------
- Zero external dependencies (stdlib only: http.server, threading, sqlite3).
- Prometheus text format is hand-rolled — it is just plain text lines.
- Counters and gauges are derived from StateStore (SQLite) at scrape time so
  values survive process restarts and stay consistent with the authoritative DB.
- Histograms (duration data) are accumulated in-memory; call the record_*
  methods from the heartbeat loop to populate them.

Usage::
    store  = StateStore(db_path="/tmp/omega_vectora_state.db")
    memory = MemoryKernel(db_path="/tmp/omega_vectora_memory.db")
    exporter = MetricsExporter(state_store=store, memory_kernel=memory)
    exporter.start()          # non-blocking — starts background daemon thread

    # In heartbeat loop:
    exporter.record_heartbeat(duration_seconds=4.2)
    exporter.record_node_execution("uuid-123", "DataIngestionNode", 1.3, success=True)
    exporter.record_brain_request("uuid-123", provider="anthropic", latency_s=0.8)
    exporter.record_improvement(result="improved")
    exporter.record_alignment_decision(decision="approved")
    exporter.record_adversarial_flag(ring="ring1", severity="warning")
    exporter.update_signals({"BTC": 0.75, "ETH": -0.3})
    exporter.update_portfolio_exposure(0.42)
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

# ---------------------------------------------------------------------------
# Histogram buckets (seconds) — covers sub-ms to 1 minute
# ---------------------------------------------------------------------------

_DURATION_BUCKETS: tuple[float, ...] = (
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)


# ---------------------------------------------------------------------------
# In-memory histogram accumulator
# ---------------------------------------------------------------------------


class _Histogram:
    """Thread-safe in-memory Prometheus histogram."""

    __slots__ = ("_buckets", "_count", "_counts", "_lock", "_sum")

    def __init__(self, buckets: tuple[float, ...] = _DURATION_BUCKETS) -> None:
        self._buckets = buckets
        self._counts: list[int] = [0] * len(buckets)
        self._sum: float = 0.0
        self._count: int = 0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        with self._lock:
            self._sum += value
            self._count += 1
            for i, b in enumerate(self._buckets):
                if value <= b:
                    self._counts[i] += 1

    def render(self, name: str, labels: dict[str, str]) -> list[str]:
        """Return Prometheus text lines for this histogram."""
        label_str = _labels(labels)
        bucket_prefix = f"{{{label_str}," if label_str else "{"
        plain_prefix = f"{{{label_str}}}" if label_str else ""

        with self._lock:
            lines: list[str] = []
            for i, b in enumerate(self._buckets):
                lines.append(f'{name}_bucket{bucket_prefix}le="{b}"}} {self._counts[i]}')
            lines.append(f'{name}_bucket{bucket_prefix}le="+Inf"}} {self._count}')
            lines.append(f"{name}_sum{plain_prefix} {self._sum:.6f}")
            lines.append(f"{name}_count{plain_prefix} {self._count}")
        return lines


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _labels(d: dict[str, str]) -> str:
    """Format a label dict as Prometheus label string (no braces)."""
    return ",".join(f'{k}="{v}"' for k, v in d.items())


def _sanitize(s: str) -> str:
    """Replace characters invalid in label values."""
    return s.replace('"', "'").replace("\n", " ")


# ---------------------------------------------------------------------------
# MetricsExporter
# ---------------------------------------------------------------------------


class MetricsExporter:
    """
    Exports Omega system metrics in Prometheus exposition format.

    Two data sources:
    1. StateStore (SQLite) — queried at scrape time for counters/gauges
       (node executions, improvements, brain requests, issues, memory).
    2. In-memory accumulators — updated via record_* / update_* methods
       for histograms and fast-changing gauges.

    Thread safety: all in-memory state is protected by self._lock.
    The HTTP server runs in a daemon thread and renders at scrape time.
    """

    def __init__(
        self,
        state_store: Any,
        memory_kernel: Any = None,
        port: int = 9090,
    ) -> None:
        self._store = state_store
        self._memory = memory_kernel
        self._port = port
        self._lock = threading.Lock()
        self._start_time = time.time()

        # -- Histograms (in-memory)
        # Keyed by (node_id, node_type) tuple
        self._node_histograms: dict[tuple[str, str], _Histogram] = {}
        # Keyed by provider string
        self._brain_histograms: dict[str, _Histogram] = {}
        # Single heartbeat histogram
        self._heartbeat_histo = _Histogram()

        # -- In-memory counters (incremented directly; DB is source for others)
        self._improvement_total: dict[str, int] = {}  # result -> count
        self._alignment_total: dict[str, int] = {}  # decision -> count
        self._adversarial_total: dict[tuple[str, str], int] = {}  # (ring, severity) -> count

        # -- Gauges updated from heartbeat
        self._signal_values: dict[tuple[str, str], float] = {}  # (name, symbol) -> value
        self._portfolio_exposure: float = 0.0

    # ------------------------------------------------------------------
    # Record methods — called from heartbeat loop
    # ------------------------------------------------------------------

    def record_heartbeat(self, duration_s: float) -> None:
        """Record one heartbeat duration (seconds)."""
        self._heartbeat_histo.observe(duration_s)

    def record_node_execution(
        self,
        node_id: str,
        node_type: str,
        duration_s: float,
        success: bool,
    ) -> None:
        """Record a node execution duration (seconds)."""
        key = (node_id, node_type)
        with self._lock:
            if key not in self._node_histograms:
                self._node_histograms[key] = _Histogram()
        self._node_histograms[key].observe(duration_s)

    def record_brain_request(self, node_id: str, provider: str, latency_s: float) -> None:
        """Record a brain (LLM) request latency."""
        with self._lock:
            if provider not in self._brain_histograms:
                self._brain_histograms[provider] = _Histogram()
        self._brain_histograms[provider].observe(latency_s)

    def record_improvement(self, result: str = "improved") -> None:
        """Increment improvement cycle counter. result: improved|rejected|failed."""
        with self._lock:
            self._improvement_total[result] = self._improvement_total.get(result, 0) + 1

    def record_alignment_decision(self, decision: str = "approved") -> None:
        """Increment alignment decision counter. decision: approved|rejected."""
        with self._lock:
            self._alignment_total[decision] = self._alignment_total.get(decision, 0) + 1

    def record_adversarial_flag(self, ring: str = "ring1", severity: str = "warning") -> None:
        """Increment adversarial flag counter."""
        key = (ring, severity)
        with self._lock:
            self._adversarial_total[key] = self._adversarial_total.get(key, 0) + 1

    def update_signals(self, signals: dict[str, Any]) -> None:
        """
        Update signal gauge values.

        *signals* is the dict returned by SignalGenerationNode:
        { "BTCUSDT": {"composite": 0.75, "sma_signal": 1, ...}, ... }
        """
        with self._lock:
            for symbol, data in signals.items():
                if isinstance(data, dict):
                    composite = data.get("composite", 0.0)
                    if composite is not None:
                        clean_sym = symbol.replace("USDT", "")
                        self._signal_values[("composite", clean_sym)] = float(composite)
                elif isinstance(data, (int, float)):
                    self._signal_values[("composite", symbol)] = float(data)

    def update_portfolio_exposure(self, exposure: float) -> None:
        """Update gross portfolio exposure (sum of absolute weights)."""
        with self._lock:
            self._portfolio_exposure = exposure

    # ------------------------------------------------------------------
    # Prometheus text rendering
    # ------------------------------------------------------------------

    def render(self) -> str:
        """Render all metrics as Prometheus exposition text."""
        lines: list[str] = []
        lines.append("# Omega system metrics — generated by omega.core.metrics_exporter")

        self._render_system_info(lines)
        self._render_node_execution_duration(lines)
        self._render_node_execution_totals(lines)
        self._render_improvement_cycle_totals(lines)
        self._render_alignment_decisions(lines)
        self._render_adversarial_flags(lines)
        self._render_brain_metrics(lines)
        self._render_memory_entries(lines)
        self._render_challenge_registry(lines)
        self._render_signal_values(lines)
        self._render_portfolio_exposure(lines)
        self._render_heartbeat_duration(lines)

        lines.append("")  # trailing newline
        return "\n".join(lines)

    # -- Individual metric renderers

    def _render_system_info(self, lines: list[str]) -> None:
        lines += [
            "# HELP omega_up 1 when the Omega metrics exporter is running",
            "# TYPE omega_up gauge",
            "omega_up 1",
            "# HELP omega_process_start_time_seconds Unix timestamp of process start",
            "# TYPE omega_process_start_time_seconds gauge",
            f"omega_process_start_time_seconds {self._start_time:.3f}",
        ]

    def _render_node_execution_duration(self, lines: list[str]) -> None:
        lines += [
            "# HELP omega_node_execution_duration_seconds Duration of node execute() calls",
            "# TYPE omega_node_execution_duration_seconds histogram",
        ]
        with self._lock:
            items = list(self._node_histograms.items())
        for (node_id, node_type), histo in items:
            lbl = {"node_id": _sanitize(node_id), "node_type": _sanitize(node_type)}
            lines += histo.render("omega_node_execution_duration_seconds", lbl)

    def _render_node_execution_totals(self, lines: list[str]) -> None:
        lines += [
            "# HELP omega_node_execution_total Total node executions by status",
            "# TYPE omega_node_execution_total counter",
        ]
        try:
            rows = self._store._conn.execute(
                """
                SELECT node_name, node_id,
                       SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) as successes,
                       SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) as failures
                FROM node_executions
                GROUP BY node_name, node_id
                """
            ).fetchall()
            for row in rows:
                nid = _sanitize(str(row["node_id"]))
                nname = _sanitize(str(row["node_name"]))
                s = int(row["successes"] or 0)
                f = int(row["failures"] or 0)
                lines.append(
                    f'omega_node_execution_total{{node_id="{nid}",node_type="{nname}",status="success"}} {s}'
                )
                lines.append(
                    f'omega_node_execution_total{{node_id="{nid}",node_type="{nname}",status="failure"}} {f}'
                )
        except Exception:
            pass

    def _render_improvement_cycle_totals(self, lines: list[str]) -> None:
        lines += [
            "# HELP omega_improvement_cycle_total Total improvement cycle attempts",
            "# TYPE omega_improvement_cycle_total counter",
        ]
        # DB-backed: successful improvements (result="improved")
        try:
            rows = self._store._conn.execute(
                "SELECT COUNT(*) as cnt FROM improvement_log"
            ).fetchone()
            db_improved = int(rows["cnt"]) if rows else 0
        except Exception:
            db_improved = 0

        # Merge DB count with in-memory (in-memory tracks rejected/failed)
        with self._lock:
            counts = dict(self._improvement_total)

        # DB is authoritative for "improved"
        total_improved = db_improved + counts.get("improved", 0)
        total_rejected = counts.get("rejected", 0)
        total_failed = counts.get("failed", 0)

        lines.append(f'omega_improvement_cycle_total{{result="improved"}} {total_improved}')
        lines.append(f'omega_improvement_cycle_total{{result="rejected"}} {total_rejected}')
        lines.append(f'omega_improvement_cycle_total{{result="failed"}} {total_failed}')

    def _render_alignment_decisions(self, lines: list[str]) -> None:
        lines += [
            "# HELP omega_alignment_decision_total Total alignment gate decisions",
            "# TYPE omega_alignment_decision_total counter",
        ]
        with self._lock:
            approved = self._alignment_total.get("approved", 0)
            rejected = self._alignment_total.get("rejected", 0)
        lines.append(f'omega_alignment_decision_total{{decision="approved"}} {approved}')
        lines.append(f'omega_alignment_decision_total{{decision="rejected"}} {rejected}')

    def _render_adversarial_flags(self, lines: list[str]) -> None:
        lines += [
            "# HELP omega_adversarial_flags_total Total adversarial / anomaly flags raised",
            "# TYPE omega_adversarial_flags_total counter",
        ]
        with self._lock:
            adv = dict(self._adversarial_total)

        # Also pull high-severity issues from StateStore as adversarial signals
        try:
            rows = self._store._conn.execute(
                """
                SELECT severity, COUNT(*) as cnt FROM issues
                WHERE state != 'resolved'
                GROUP BY severity
                """
            ).fetchall()
            db_flags: dict[str, int] = {}
            for row in rows:
                sev = str(row["severity"])
                db_flags[sev] = int(row["cnt"])
        except Exception:
            db_flags = {}

        # Merge in-memory adversarial flags by ring/severity with DB issue counts
        all_rings: dict[tuple[str, str], int] = {}
        for (ring, severity), count in adv.items():
            all_rings[(ring, severity)] = count
        for sev, count in db_flags.items():
            key = ("issues", sev)
            all_rings[key] = all_rings.get(key, 0) + count

        if not all_rings:
            lines.append('omega_adversarial_flags_total{ring="ring1",severity="warning"} 0')
        else:
            for (ring, sev), count in sorted(all_rings.items()):
                lines.append(
                    f'omega_adversarial_flags_total{{ring="{_sanitize(ring)}",severity="{_sanitize(sev)}"}} {count}'
                )

    def _render_brain_metrics(self, lines: list[str]) -> None:
        lines += [
            "# HELP omega_brain_request_total Total brain (LLM) requests",
            "# TYPE omega_brain_request_total counter",
        ]
        try:
            rows = self._store._conn.execute(
                """
                SELECT node_name, node_id, provider, COUNT(*) as cnt
                FROM brain_executions
                WHERE provider != 'none'
                GROUP BY node_name, node_id, provider
                """
            ).fetchall()
            for row in rows:
                nid = _sanitize(str(row["node_id"]))
                prov = _sanitize(str(row["provider"]))
                cnt = int(row["cnt"])
                lines.append(
                    f'omega_brain_request_total{{node_id="{nid}",provider="{prov}"}} {cnt}'
                )
        except Exception:
            pass

        lines += [
            "# HELP omega_brain_latency_seconds LLM brain request latency",
            "# TYPE omega_brain_latency_seconds histogram",
        ]
        with self._lock:
            brain_items = list(self._brain_histograms.items())
        for provider, histo in brain_items:
            lbl = {"provider": _sanitize(provider)}
            lines += histo.render("omega_brain_latency_seconds", lbl)

    def _render_memory_entries(self, lines: list[str]) -> None:
        lines += [
            "# HELP omega_memory_entries_total Current memory store entry count",
            "# TYPE omega_memory_entries_total gauge",
        ]
        if self._memory is not None:
            try:
                summary = self._memory.summary()
                episodic = summary.get("episodic_count", 0)
                semantic = summary.get("semantic_count", 0)
                working = len(summary.get("working_memory_keys", []))
                lines.append(f'omega_memory_entries_total{{memory_type="episodic"}} {episodic}')
                lines.append(f'omega_memory_entries_total{{memory_type="semantic"}} {semantic}')
                lines.append(f'omega_memory_entries_total{{memory_type="working"}} {working}')
            except Exception:
                lines.append('omega_memory_entries_total{memory_type="episodic"} 0')
                lines.append('omega_memory_entries_total{memory_type="semantic"} 0')
                lines.append('omega_memory_entries_total{memory_type="working"} 0')
        else:
            lines.append('omega_memory_entries_total{memory_type="episodic"} 0')
            lines.append('omega_memory_entries_total{memory_type="semantic"} 0')
            lines.append('omega_memory_entries_total{memory_type="working"} 0')

    def _render_challenge_registry(self, lines: list[str]) -> None:
        lines += [
            "# HELP omega_challenge_registry_total Current challenge/issue count by status",
            "# TYPE omega_challenge_registry_total gauge",
        ]
        try:
            rows = self._store._conn.execute(
                "SELECT state, COUNT(*) as cnt FROM issues GROUP BY state"
            ).fetchall()
            counts: dict[str, int] = {}
            for row in rows:
                counts[str(row["state"])] = int(row["cnt"])
        except Exception:
            counts = {}

        for status in ("open", "resolved", "wontfix", "pending"):
            label_status = "open" if status == "pending" else status
            cnt = counts.get(status, 0)
            lines.append(f'omega_challenge_registry_total{{status="{label_status}"}} {cnt}')

    def _render_signal_values(self, lines: list[str]) -> None:
        lines += [
            "# HELP omega_signal_value Current composite signal value per asset",
            "# TYPE omega_signal_value gauge",
        ]
        with self._lock:
            signals = dict(self._signal_values)
        if not signals:
            lines.append('omega_signal_value{signal_name="composite",symbol="BTC"} 0')
        else:
            for (sig_name, symbol), val in sorted(signals.items()):
                lines.append(
                    f'omega_signal_value{{signal_name="{_sanitize(sig_name)}",symbol="{_sanitize(symbol)}"}} {val:.6f}'
                )

    def _render_portfolio_exposure(self, lines: list[str]) -> None:
        lines += [
            "# HELP omega_portfolio_exposure Current gross portfolio exposure (sum of abs weights)",
            "# TYPE omega_portfolio_exposure gauge",
        ]
        with self._lock:
            exp = self._portfolio_exposure
        lines.append(f"omega_portfolio_exposure {exp:.6f}")

    def _render_heartbeat_duration(self, lines: list[str]) -> None:
        lines += [
            "# HELP omega_heartbeat_duration_seconds Duration of the full heartbeat pipeline",
            "# TYPE omega_heartbeat_duration_seconds histogram",
        ]
        lines += self._heartbeat_histo.render("omega_heartbeat_duration_seconds", {})

    # ------------------------------------------------------------------
    # HTTP server
    # ------------------------------------------------------------------

    def start(self, daemon: bool = True) -> None:
        """Start the metrics HTTP server in a background thread."""
        exporter = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path in ("/metrics", "/metrics/"):
                    body = exporter.render().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"404 - only /metrics is served here\n")

            def log_message(self, fmt: str, *args: Any) -> None:
                pass  # silence request logs

        server = HTTPServer(("", self._port), _Handler)
        thread = threading.Thread(
            target=server.serve_forever,
            name="omega-metrics-server",
            daemon=daemon,
        )
        thread.start()
