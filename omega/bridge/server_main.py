"""omega.bridge.server_main — Pipeline server entry point for Go→Python bridge.

Starts the Connect-RPC pipeline server with VictoriaNode registered so that
Go's orchestrator can call ExecuteStep() and have it routed to the correct
node handler.

Environment variables
---------------------
OMEGA_PIPELINE_PORT   TCP port to listen on (default 9090).

Usage::

    python -m omega.bridge.server_main
    OMEGA_PIPELINE_PORT=9091 python -m omega.bridge.server_main
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("omega.bridge.server_main")


def _register_polymarket_nodes(orch: object) -> None:
    """Register Polymarket weather pipeline nodes if the project config exists."""
    import pathlib

    project_config = pathlib.Path(__file__).parents[2] / "projects" / "polymarket.yaml"
    if not project_config.exists():
        return

    try:
        from omega.nodes.polymarket.edge_detection import EdgeDetectionNode
        from omega.nodes.polymarket.pricing import PolymarketPricingNode
        from omega.nodes.polymarket.weather_ensemble import WeatherEnsembleNode

        weather_node = WeatherEnsembleNode()
        pricing_node = PolymarketPricingNode()
        edge_node = EdgeDetectionNode()

        for n in (weather_node, pricing_node, edge_node):
            orch.register_node(n)  # type: ignore[attr-defined]

        logger.info(
            "Polymarket nodes registered: %s, %s, %s",
            weather_node.get_state().name,
            pricing_node.get_state().name,
            edge_node.get_state().name,
        )
    except Exception as exc:
        logger.warning("Failed to register Polymarket nodes: %s — continuing without them", exc)


def main() -> None:
    port = int(os.getenv("OMEGA_PIPELINE_PORT", "9090"))

    from omega.core.orchestrator_v2 import OmegaOrchestrator
    from omega.nodes.victoria.victoria_node import VictoriaNode

    orch = OmegaOrchestrator(name="victoria-pipeline-server")
    node = VictoriaNode()
    orch.register_node(node)

    # Register Polymarket nodes when projects/polymarket.yaml is present.
    _register_polymarket_nodes(orch)

    # Wire state store for cycle-result persistence and history seeding.
    # Wire tracer for Go→Python distributed trace propagation.
    try:
        from omega.core.state_store import make_state_backend
        from omega.core.tracing import Tracer

        store = make_state_backend()
        orch.set_state_store(store)
        orch.set_tracer(Tracer(store))
        logger.info("StateStore and Tracer wired into pipeline server")
    except Exception as exc:
        logger.warning("StateStore/Tracer wiring failed: %s — continuing without persistence", exc)

    # Wire PaperTradingEngine so signal values are persisted to victoria_signals
    # and victoria_signal_history on every SignalResearch cycle.
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            from omega.core.paper_trading import PaperTradingEngine

            paper_trading = PaperTradingEngine(db_url=db_url)
            orch.set_paper_trading(paper_trading)
            logger.info("PaperTradingEngine wired (db_url configured: True)")
        except Exception as exc:
            logger.warning("PaperTradingEngine not wired: %s", exc)
    else:
        logger.info("DATABASE_URL not set — signal history persistence disabled")

    server, thread = orch.start_pipeline_server(port=port)
    logger.info("Victoria pipeline server ready on port %d", port)
    logger.info("Registered capabilities: %s", node.get_capabilities())

    def _shutdown(sig: int, frame: object) -> None:
        logger.info("Shutting down pipeline server (signal %d)", sig)
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        while thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        logger.info("Pipeline server stopped")


if __name__ == "__main__":
    main()
