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


def main() -> None:
    port = int(os.getenv("OMEGA_PIPELINE_PORT", "9090"))

    from omega.core.orchestrator_v2 import OmegaOrchestrator
    from omega.nodes.victoria.victoria_node import VictoriaNode

    orch = OmegaOrchestrator(name="victoria-pipeline-server")
    node = VictoriaNode()
    orch.register_node(node)

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
