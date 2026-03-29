"""
omega.core.node_adapter
~~~~~~~~~~~~~~~~~~~~~~~
Universal adapter layer that wraps existing Victoria modules into composable nodes.

Every existing signal function, strategy, executor, or data source can be plugged
into the Omega node network by wrapping it in the appropriate adapter subclass.

Design intent
-------------
- NodeAdapter   : abstract base — lifecycle + process contract
- SignalAdapter : wraps any signal function into a SignalGeneratorNode
- StrategyAdapter: wraps strategy.py's StrategyNode
- ExecutorAdapter: wraps paper_trading.py's PaperTradingEngine
- DataAdapter   : wraps data_resilience.py's multi-provider fetch
- NodeMessage   : inter-node message protocol
- @omega_node   : decorator for auto-registration of adapter subclasses
- discover_plugins: scans omega/nodes/ and registers decorated adapters
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import pkgutil
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inter-node message protocol
# ---------------------------------------------------------------------------


@dataclass
class NodeMessage:
    """Envelope passed between composable nodes."""

    source: str  # e.g. "victoria.basic_signals"
    target: str  # e.g. "victoria.strategy" or "*" for broadcast
    msg_type: str  # "signal" | "trade_decision" | "regime_change"
    payload: dict[str, Any]
    timestamp: float
    confidence: float  # 0.0–1.0


# ---------------------------------------------------------------------------
# Health and metadata
# ---------------------------------------------------------------------------


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    STOPPED = "stopped"


@dataclass
class NodeHealth:
    status: HealthStatus
    latency_ms: float = 0.0
    error_rate: float = 0.0
    last_error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeMetadata:
    name: str
    node_type: str
    version: str
    inputs: list[str]
    outputs: list[str]
    description: str = ""
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# NodeAdapter — abstract base
# ---------------------------------------------------------------------------


class NodeAdapter(ABC):
    """Wraps any existing module into the composable node interface.

    Subclasses must implement:
        _process(inputs)  — the actual work
        get_metadata()    — static description of the adapter

    Optionally override:
        _on_startup()     — one-time initialisation
        _on_shutdown()    — cleanup
    """

    def __init__(self, name: str, version: str = "1.0.0") -> None:
        self._name = name
        self._version = version
        self._started = False
        self._call_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
        self._last_error: str | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def startup(self) -> None:
        """Initialise the adapter and validate dependencies."""
        await self._on_startup()
        self._started = True
        logger.info("NodeAdapter %s started", self._name)

    async def shutdown(self) -> None:
        """Release resources."""
        await self._on_shutdown()
        self._started = False
        logger.info("NodeAdapter %s stopped", self._name)

    @abstractmethod
    async def _on_startup(self) -> None:  # pragma: no cover
        """Override to add custom initialisation."""
        ...

    @abstractmethod
    async def _on_shutdown(self) -> None:  # pragma: no cover
        """Override to add custom cleanup."""
        ...

    # ── Core interface ─────────────────────────────────────────────────────

    async def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Run one processing cycle, tracking latency and error metrics."""
        if not self._started:
            raise RuntimeError(f"NodeAdapter {self._name!r} not started — call startup() first")
        t0 = time.monotonic()
        try:
            result = await self._process(inputs)
            self._call_count += 1
            self._total_latency_ms += (time.monotonic() - t0) * 1000
            return result
        except Exception as exc:
            self._error_count += 1
            self._call_count += 1
            self._last_error = str(exc)
            self._total_latency_ms += (time.monotonic() - t0) * 1000
            raise

    @abstractmethod
    async def _process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Subclasses implement the actual processing logic here."""
        ...

    def health_check(self) -> NodeHealth:
        """Return current health derived from observed metrics."""
        if not self._started:
            return NodeHealth(status=HealthStatus.STOPPED)
        error_rate = self._error_count / max(1, self._call_count)
        if error_rate > 0.5:
            status = HealthStatus.UNHEALTHY
        elif error_rate > 0.1:
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.HEALTHY
        avg_latency = self._total_latency_ms / max(1, self._call_count)
        return NodeHealth(
            status=status,
            latency_ms=avg_latency,
            error_rate=error_rate,
            last_error=self._last_error,
            details={"call_count": self._call_count, "error_count": self._error_count},
        )

    # Alias so callers can use either name
    def get_health(self) -> NodeHealth:
        return self.health_check()

    @abstractmethod
    def get_metadata(self) -> NodeMetadata: ...


# ---------------------------------------------------------------------------
# Concrete adapters
# ---------------------------------------------------------------------------


class SignalAdapter(NodeAdapter):
    """Wraps any signal function (basic_signals, geometric, rmt, etc.) into a
    SignalGeneratorNode-compatible adapter.

    The wrapped *signal_fn* receives ``market_data`` (a dict keyed by ticker)
    and must return a dict.  Both sync and async callables are supported.
    """

    def __init__(
        self,
        signal_fn: Callable[[dict[str, Any]], dict[str, Any]],
        name: str,
        output_keys: list[str] | None = None,
        version: str = "1.0.0",
    ) -> None:
        super().__init__(name=name, version=version)
        self._signal_fn = signal_fn
        self._output_keys = output_keys or ["signals"]

    async def _process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        market_data = inputs.get("market_data", inputs)
        loop = asyncio.get_event_loop()
        if asyncio.iscoroutinefunction(self._signal_fn):
            result = await self._signal_fn(market_data)
        else:
            result = await loop.run_in_executor(None, self._signal_fn, market_data)
        if not isinstance(result, dict):
            result = {"signals": result}
        return result

    def get_metadata(self) -> NodeMetadata:
        return NodeMetadata(
            name=self._name,
            node_type="signal_generator",
            version=self._version,
            inputs=["market_data"],
            outputs=self._output_keys,
            description=f"Signal generator: {self._name}",
            tags=["signal", "victoria"],
        )


class StrategyAdapter(NodeAdapter):
    """Wraps strategy.py's StrategyNode into the adapter interface.

    Converts a flat ``inputs`` dict into a ``NodeInput`` and unwraps the
    resulting ``NodeOutput`` back to a plain dict.
    """

    def __init__(self, strategy_node: Any, version: str = "1.0.0") -> None:
        super().__init__(name="victoria.strategy", version=version)
        self._strategy = strategy_node

    async def _on_startup(self) -> None:
        caps = (
            self._strategy.get_capabilities()
            if hasattr(self._strategy, "get_capabilities")
            else []
        )
        logger.info("StrategyAdapter capabilities: %s", caps)

    async def _process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        from omega.core.node import NodeInput  # local import avoids circular deps

        action = inputs.get("action", "construct_portfolio")
        params = {k: v for k, v in inputs.items() if k != "action"}
        node_input = NodeInput(
            request_id=str(time.time()),
            action=action,
            parameters=params,
            context={},
        )
        loop = asyncio.get_event_loop()
        if asyncio.iscoroutinefunction(self._strategy.execute):
            output = await self._strategy.execute(node_input)
        else:
            output = await loop.run_in_executor(None, self._strategy.execute, node_input)
        return {
            "success": output.success,
            "proposals": output.result.get("proposals", []) if output.result else [],
            "metrics": output.metrics or {},
            "errors": output.errors or [],
        }

    def get_metadata(self) -> NodeMetadata:
        return NodeMetadata(
            name=self._name,
            node_type="strategy",
            version=self._version,
            inputs=["signals", "market_data", "action"],
            outputs=["proposals", "metrics"],
            description="Portfolio construction strategy",
            tags=["strategy", "victoria"],
        )


class ExecutorAdapter(NodeAdapter):
    """Wraps paper_trading.py's PaperTradingEngine into the adapter interface.

    Supported ``action`` values in *inputs*:
      - ``"execute"``        — execute_proposals(proposals, market_data, ...)
      - ``"mark_to_market"`` — mark_to_market(market_data, ...)
      - ``"metrics"``        — compute_metrics()
    """

    def __init__(self, engine: Any, version: str = "1.0.0") -> None:
        super().__init__(name="victoria.executor", version=version)
        self._engine = engine

    async def _process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        action = inputs.get("action", "execute")
        market_data = inputs.get("market_data", {})
        cycle_id = inputs.get("cycle_id")
        current_cycle = inputs.get("current_cycle", 0)
        loop = asyncio.get_event_loop()

        if action == "execute":
            proposals = inputs.get("proposals", [])
            executed = await loop.run_in_executor(
                None,
                lambda: self._engine.execute_proposals(
                    proposals, market_data, cycle_id, current_cycle
                ),
            )
            return {
                "executed_trades": executed,
                "positions": dict(self._engine.positions),
            }

        if action == "mark_to_market":
            stop_loss_pct = inputs.get("stop_loss_pct", -0.02)
            closed = await loop.run_in_executor(
                None,
                lambda: self._engine.mark_to_market(
                    market_data, current_cycle, stop_loss_pct, cycle_id
                ),
            )
            return {
                "closed_trades": closed,
                "metrics": self._engine.compute_metrics(),
            }

        if action == "metrics":
            return {"metrics": self._engine.compute_metrics()}

        raise ValueError(f"ExecutorAdapter: unknown action {action!r}")

    def get_metadata(self) -> NodeMetadata:
        return NodeMetadata(
            name=self._name,
            node_type="executor",
            version=self._version,
            inputs=["proposals", "market_data", "action", "cycle_id", "current_cycle"],
            outputs=["executed_trades", "closed_trades", "positions", "metrics"],
            description="Paper trading execution engine",
            tags=["executor", "trading", "victoria"],
        )


class DataAdapter(NodeAdapter):
    """Wraps data_resilience.py's multi-provider fetch into the adapter interface.

    If no *resilience_layer* is supplied it is lazily resolved at startup via
    ``get_resilience_layer()``.
    """

    def __init__(
        self,
        resilience_layer: Any | None = None,
        version: str = "1.0.0",
    ) -> None:
        super().__init__(name="victoria.data", version=version)
        self._layer = resilience_layer

    async def _on_startup(self) -> None:
        if self._layer is None:
            from omega.core.data_resilience import get_resilience_layer  # local import

            self._layer = get_resilience_layer()

    async def _process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        pairs = inputs.get("pairs", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        interval = inputs.get("interval", "1d")
        limit = inputs.get("limit", 90)
        loop = asyncio.get_event_loop()
        market_data = await loop.run_in_executor(
            None,
            lambda: self._layer.fetch_with_failover(pairs, interval, limit),
        )
        health = self._layer.get_health_status()
        return {"market_data": market_data, "data_health": health}

    def get_metadata(self) -> NodeMetadata:
        return NodeMetadata(
            name=self._name,
            node_type="data_source",
            version=self._version,
            inputs=["pairs", "interval", "limit"],
            outputs=["market_data", "data_health"],
            description="Multi-provider market data with circuit-breaker failover",
            tags=["data", "victoria", "resilience"],
        )


# ---------------------------------------------------------------------------
# Plugin discovery via @omega_node decorator
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[NodeAdapter]] = {}


def omega_node(
    name: str,
    *,
    version: str = "1.0.0",
    tags: list[str] | None = None,
) -> Callable[[type[NodeAdapter]], type[NodeAdapter]]:
    """Class decorator that registers a NodeAdapter subclass in the plugin registry.

    Usage::

        @omega_node("my_signal", tags=["signal"])
        class MySignalAdapter(NodeAdapter):
            async def _process(self, inputs):
                ...
            def get_metadata(self):
                ...
    """

    def decorator(cls: type[NodeAdapter]) -> type[NodeAdapter]:
        if not (isinstance(cls, type) and issubclass(cls, NodeAdapter)):
            raise TypeError(f"@omega_node requires a NodeAdapter subclass, got {cls!r}")
        _REGISTRY[name] = cls
        cls._omega_node_name = name  # type: ignore[attr-defined]
        cls._omega_node_version = version  # type: ignore[attr-defined]
        cls._omega_node_tags = tags or []  # type: ignore[attr-defined]
        logger.debug("Registered omega_node %r → %s", name, cls.__name__)
        return cls

    return decorator


def discover_plugins(nodes_package: str = "omega.nodes") -> dict[str, type[NodeAdapter]]:
    """Scan *nodes_package* for Python modules that contain ``@omega_node``-decorated
    classes and register any that are not already in the registry.

    Returns the (updated) registry dict.
    """
    try:
        pkg = importlib.import_module(nodes_package)
    except ImportError:
        logger.warning("discover_plugins: package %r not importable, skipping", nodes_package)
        return _REGISTRY

    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is None:
        return _REGISTRY

    for _finder, modname, _ispkg in pkgutil.walk_packages(pkg_path, prefix=nodes_package + "."):
        try:
            mod = importlib.import_module(modname)
        except Exception as exc:
            logger.debug("discover_plugins: skipping %s — %s", modname, exc)
            continue

        for _attr, obj in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(obj, NodeAdapter)
                and obj is not NodeAdapter
                and hasattr(obj, "_omega_node_name")
                and obj._omega_node_name not in _REGISTRY
            ):
                _REGISTRY[obj._omega_node_name] = obj
                logger.debug(
                    "discover_plugins: registered %r from %s",
                    obj._omega_node_name,
                    modname,
                )

    return _REGISTRY


def get_registry() -> dict[str, type[NodeAdapter]]:
    """Return a snapshot of the current plugin registry."""
    return dict(_REGISTRY)
