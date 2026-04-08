"""
omega.core.registry
~~~~~~~~~~~~~~~~~~~~
In-memory node registry.

Nodes register themselves here; the orchestrator queries by capability.
"""

from __future__ import annotations

import logging

from omega.core.node import Node, NodeState

logger = logging.getLogger("omega.registry")


class NodeRegistry:
    """
    Thread-unsafe in-memory registry of Node instances.

    Provides:
    - Registration / deregistration
    - Capability-based lookup
    - Health-filtered lookup
    """

    def __init__(self) -> None:
        # node_id → Node instance
        self._nodes: dict[str, Node] = {}
        # capability verb → set of node_ids
        self._capability_index: dict[str, set] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, node: Node) -> None:
        """Add *node* to the registry and index its capabilities."""
        state = node.get_state()
        node_id = state.node_id

        if node_id in self._nodes:
            logger.warning("Node %s already registered; replacing.", node_id)

        self._nodes[node_id] = node
        for cap in state.capabilities:
            self._capability_index.setdefault(cap, set()).add(node_id)

        logger.info(
            "Registered node '%s' (id=%s) with capabilities: %s",
            state.name,
            node_id,
            state.capabilities,
        )

    def deregister(self, node_id: str) -> bool:
        """Remove a node by id. Returns True if it was present."""
        node = self._nodes.pop(node_id, None)
        if node is None:
            return False

        for cap_set in self._capability_index.values():
            cap_set.discard(node_id)

        logger.info("Deregistered node id=%s", node_id)
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def all_nodes(self) -> list[Node]:
        return list(self._nodes.values())

    def nodes_for_capability(
        self,
        capability: str,
        healthy_only: bool = True,
        health_threshold: float = 0.5,
    ) -> list[Node]:
        """
        Return nodes that advertise *capability*.

        If *healthy_only* is True (default), only nodes whose current
        health >= *health_threshold* are returned.
        """
        ids = self._capability_index.get(capability, set())
        candidates = [self._nodes[i] for i in ids if i in self._nodes]

        if not healthy_only:
            return candidates

        healthy = []
        for node in candidates:
            try:
                state = node.get_state()
                if state.health >= health_threshold:
                    healthy.append(node)
            except Exception as exc:
                logger.warning(
                    "get_state() raised for node %s during health check: %s",
                    id(node),
                    exc,
                )
        return healthy

    def all_capabilities(self) -> list[str]:
        return [cap for cap, ids in self._capability_index.items() if ids]

    def all_states(self) -> list[NodeState]:
        states = []
        for node in self._nodes.values():
            try:
                states.append(node.get_state())
            except Exception as exc:
                logger.warning("get_state() raised: %s", exc)
        return states

    def __len__(self) -> int:
        return len(self._nodes)

    def __repr__(self) -> str:
        return f"NodeRegistry(nodes={len(self._nodes)}, capabilities={self.all_capabilities()})"
