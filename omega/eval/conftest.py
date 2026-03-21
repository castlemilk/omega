"""omega.eval.conftest — Pytest fixtures for e2e eval tests.

Provides:
  go_server  — session-scoped: starts the Go API once per test session
  rpc_clients — session-scoped: all service clients pointed at the running server
  state_client — session-scoped: StateServiceClient alias
  clean_namespace — function-scoped: unique namespace string for memory isolation
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from omega.bridge.state_client import StateServiceClient
from omega.eval.e2e_runner import GoServer, RpcClients


@pytest.fixture(scope="session")
def go_server() -> Generator[GoServer, None, None]:
    """Start the Go API server once for the whole test session.

    Uses temp SQLite databases so tests never touch production state.
    Cleans up temp files on teardown.
    """
    server = GoServer(startup_timeout=90.0)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def rpc_clients(go_server: GoServer) -> RpcClients:
    """Return all service clients pointed at the running Go server."""
    return RpcClients(base_url=go_server.base_url)


@pytest.fixture(scope="session")
def state_client(rpc_clients: RpcClients) -> StateServiceClient:
    """Direct StateServiceClient (mirrors omega.bridge.state_client usage)."""
    return rpc_clients.state


@pytest.fixture
def clean_namespace() -> str:
    """Return a unique namespace string for memory-isolation in each test."""
    import uuid

    return f"eval-test-{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="session")
def test_db(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Paths to the temp SQLite databases created for this test session.

    The go_server fixture already creates its own temp DBs via GoServer.
    This fixture exposes those paths for test inspection if needed.
    Returns a dict with keys 'state_db' and 'memory_db'.
    """
    tmp = tmp_path_factory.mktemp("omega_eval_db")
    return {
        "state_db": str(tmp / "state.db"),
        "memory_db": str(tmp / "memory.db"),
    }
