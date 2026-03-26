"""
omega.core.signal_bus
~~~~~~~~~~~~~~~~~~~~~
SharedSignalState — thread-safe central registry where each node publishes
its latest signal state so other nodes can read peer states before computing
their own signals.

This enables cross-node conditioning:
  "derivatives signal is bearish AND news is bearish → higher conviction"

The 16-dim state tensor (VictoriaStateTensorSchema v1.0.0) is broadcast
alongside the raw signal dict so the Go attention router can also consume it.

Usage::

    bus = get_signal_bus()
    bus.publish("victoria_node_1", signals, tensor=[...])
    peers = bus.read_peers("victoria_node_1")  # excludes self
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger("omega.core.signal_bus")

# ---------------------------------------------------------------------------
# SharedSignalState
# ---------------------------------------------------------------------------


class SharedSignalState:
    """
    Thread-safe registry for inter-node signal broadcasting.

    Each node calls publish() after computing its signals.
    Other nodes can call read_peers() to get the latest state
    of all other registered nodes before computing their own.

    The 16-dim state tensor (optional) is broadcast alongside signals
    so the Go attention router can consume peer state for routing decisions.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[str, dict[str, Any]] = {}  # node_id → signal dict
        self._tensors: dict[str, list[float]] = {}  # node_id → 16-dim tensor
        self._timestamps: dict[str, float] = {}  # node_id → last publish time

    # ------------------------------------------------------------------
    # Write side
    # ------------------------------------------------------------------

    def publish(
        self,
        node_id: str,
        signals: dict[str, Any],
        tensor: list[float] | None = None,
    ) -> None:
        """
        Publish a node's latest signal state to the bus.

        Parameters
        ----------
        node_id  : Unique node identifier.
        signals  : Output of _do_compute_signals (may include _weights etc.)
        tensor   : Optional 16-dim state tensor for Go-side attention routing.
        """
        import time

        with self._lock:
            self._states[node_id] = dict(signals)
            if tensor is not None:
                self._tensors[node_id] = list(tensor)
            self._timestamps[node_id] = time.monotonic()

        logger.debug("signal_bus: node '%s' published %d signals", node_id, len(signals))

    # ------------------------------------------------------------------
    # Read side
    # ------------------------------------------------------------------

    def read_peers(self, node_id: str) -> dict[str, dict[str, Any]]:
        """
        Return the latest signal dicts for all nodes EXCEPT the caller.

        Returns a shallow copy to avoid lock contention on downstream reads.
        """
        with self._lock:
            return {nid: dict(s) for nid, s in self._states.items() if nid != node_id}

    def read_all(self) -> dict[str, dict[str, Any]]:
        """Return the latest signal dicts for all registered nodes."""
        with self._lock:
            return {nid: dict(s) for nid, s in self._states.items()}

    def read_tensors(self, node_id: str) -> dict[str, list[float]]:
        """
        Return 16-dim state tensors of all nodes EXCEPT the caller.

        Used by the Go attention router bridge to consume peer state.
        """
        with self._lock:
            return {nid: list(t) for nid, t in self._tensors.items() if nid != node_id}

    def registered_nodes(self) -> list[str]:
        """Return list of all registered node IDs."""
        with self._lock:
            return list(self._states.keys())

    def peer_count(self, node_id: str) -> int:
        """Number of peer nodes (excluding caller) currently registered."""
        with self._lock:
            return sum(1 for nid in self._states if nid != node_id)

    def get_timestamps(self) -> dict[str, float]:
        """Return last-publish monotonic timestamps per node."""
        with self._lock:
            return dict(self._timestamps)

    # ------------------------------------------------------------------
    # Consensus helpers
    # ------------------------------------------------------------------

    def compute_peer_consensus(self, node_id: str) -> dict[str, Any]:
        """
        Compute a simple directional consensus across all peer nodes.

        Returns a dict with:
          - peer_count: number of peers
          - bullish_peers: count with aggregate signal > 0.05
          - bearish_peers: count with aggregate signal < -0.05
          - consensus_direction: +1 (bull), -1 (bear), 0 (split)
          - consensus_strength: 0..1 (how lopsided the consensus is)
        """
        peers = self.read_peers(node_id)
        if not peers:
            return {
                "peer_count": 0,
                "bullish_peers": 0,
                "bearish_peers": 0,
                "consensus_direction": 0,
                "consensus_strength": 0.0,
            }

        bullish = 0
        bearish = 0
        for _nid, sigs in peers.items():
            values = [
                float(s.get("value", 0.0))
                for name, s in sigs.items()
                if not name.startswith("_") and isinstance(s, dict) and "value" in s
            ]
            if not values:
                continue
            avg = sum(values) / len(values)
            if avg > 0.05:
                bullish += 1
            elif avg < -0.05:
                bearish += 1

        n = bullish + bearish
        if n == 0:
            direction = 0
            strength = 0.0
        elif bullish > bearish:
            direction = 1
            strength = (bullish - bearish) / n
        elif bearish > bullish:
            direction = -1
            strength = (bearish - bullish) / n
        else:
            direction = 0
            strength = 0.0

        return {
            "peer_count": len(peers),
            "bullish_peers": bullish,
            "bearish_peers": bearish,
            "consensus_direction": direction,
            "consensus_strength": strength,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_BUS: SharedSignalState | None = None
_BUS_LOCK = threading.Lock()


def get_signal_bus() -> SharedSignalState:
    """Return (or lazily create) the process-level SharedSignalState singleton."""
    global _BUS
    if _BUS is None:
        with _BUS_LOCK:
            if _BUS is None:
                _BUS = SharedSignalState()
                logger.info("signal_bus: SharedSignalState singleton created")
    return _BUS


def reset_signal_bus() -> None:
    """Reset the singleton — useful for testing."""
    global _BUS
    with _BUS_LOCK:
        _BUS = None
