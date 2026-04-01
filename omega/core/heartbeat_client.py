"""
omega/core/heartbeat_client.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Lightweight Python heartbeat client that reports node status and training
diagnostics to the Go control plane over plain HTTP/JSON.

The client is fire-and-forget: if the Go service is unreachable it logs a
warning and continues — it will never block or crash the training loop.

Usage (training loop)::

    from omega.core.heartbeat_client import HeartbeatClient
    hb = HeartbeatClient()                        # defaults to localhost:8080

    # Every cycle
    hb.send_diagnostics(
        node_id="victoria_training",
        cycle=cycle_num,
        regime=regime,
        data_freshness_seconds=freshness_min * 60,
        active_signals=active,
        total_signals=total,
        sit_out=sit_out_reason != "normal",
        sit_out_reason=sit_out_reason,
        open_trades=len(open_pos),
        closed_trades=len(closed),
        pnl=pnl,
        longs=n_longs,
        shorts=n_shorts,
        blockers=blockers,
        ticker_convictions=convictions,
    )

    # Ad-hoc from any Python node
    hb.send_heartbeat(
        node_id="victoria_signal_node",
        node_type="SIGNAL_GENERATOR",
        health="healthy",
        metrics={"execution_count": "42"},
        blockers=[],
    )
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)


class HeartbeatClient:
    """HTTP/JSON client for the Omega control-plane heartbeat endpoints.

    All methods are safe to call even when the Go service is not running —
    failures are logged at WARNING level and silently swallowed.
    """

    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 5.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    # ── Public API ────────────────────────────────────────────────────────────

    def send_heartbeat(
        self,
        node_id: str,
        node_type: str = "",
        health: str = "healthy",
        metrics: dict[str, str] | None = None,
        blockers: list[str] | None = None,
    ) -> bool:
        """POST a generic heartbeat for any Python node.

        Returns True on success, False if the service is unreachable.
        """
        payload: dict[str, Any] = {
            "node_id": node_id,
            "node_type": node_type,
            "health": health,
            "metrics": metrics or {},
            "blockers": blockers or [],
        }
        return self._post("/api/v1/heartbeat", payload)

    def send_diagnostics(
        self,
        *,
        node_id: str,
        cycle: int,
        regime: str = "",
        data_freshness_seconds: float = 0.0,
        active_signals: int = 0,
        total_signals: int = 0,
        sit_out: bool = False,
        sit_out_reason: str = "normal",
        open_trades: int = 0,
        closed_trades: int = 0,
        pnl: float = 0.0,
        longs: int = 0,
        shorts: int = 0,
        blockers: list[str] | None = None,
        ticker_convictions: dict[str, float] | None = None,
    ) -> bool:
        """POST rich training-loop diagnostics.

        Returns True on success, False if the service is unreachable.
        """
        payload: dict[str, Any] = {
            "node_id": node_id,
            "cycle": cycle,
            "regime": regime,
            "data_freshness_seconds": float(data_freshness_seconds),
            "active_signals": active_signals,
            "total_signals": total_signals,
            "sit_out": sit_out,
            "sit_out_reason": sit_out_reason,
            "open_trades": open_trades,
            "closed_trades": closed_trades,
            "pnl": float(pnl),
            "longs": longs,
            "shorts": shorts,
            "blockers": blockers or [],
            "ticker_convictions": ticker_convictions or {},
        }
        return self._post("/api/v1/diagnostics", payload)

    def post_decision(
        self,
        node_id: str,
        cycle: int,
        snapshot_json: str,
    ) -> bool:
        """POST a per-cycle decision snapshot to the Go control plane.

        snapshot_json should be the JSON-serialised DecisionSnapshot from
        omega.core.decision_snapshot.  Returns True on success.
        """
        payload: dict[str, Any] = {
            "cycle": cycle,
            "snapshot_json": snapshot_json,
        }
        return self._post(f"/api/v1/nodes/{node_id}/decisions", payload)

    def report_lifecycle(
        self,
        node_id: str,
        from_state: str,
        to_state: str,
        reason: str = "",
    ) -> bool:
        """POST a lifecycle state transition to the Go control plane.

        States: STARTING | WARMING_UP | RUNNING | DEGRADED | STOPPED
        Returns True on success.
        """
        payload: dict[str, Any] = {
            "from_state": from_state,
            "to_state": to_state,
            "reason": reason,
        }
        return self._post(f"/api/v1/nodes/{node_id}/lifecycle", payload)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _post(self, path: str, payload: dict[str, Any]) -> bool:
        url = self._base + path
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                _ = resp.read()
            return True
        except urllib.error.URLError as exc:
            log.warning("heartbeat: %s unreachable (%s) — continuing", url, exc.reason)
        except Exception as exc:
            log.warning("heartbeat: POST %s failed (%s) — continuing", path, exc)
        return False
