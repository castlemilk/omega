"""
omega.core.degradation
~~~~~~~~~~~~~~~~~~~~~~
Singleton registry that tracks which platform components are degraded and
what fallbacks are in use.

Usage::

    from omega.core.degradation import get_registry
    reg = get_registry()
    reg.mark_degraded("binance", reason="HTTP 429", fallback="bybit")
    reg.mark_healthy("binance")
    print(reg.health_summary())
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger("omega.core.degradation")

# All known platform components. Used to compute healthy/degraded counts.
KNOWN_COMPONENTS: frozenset[str] = frozenset(
    {
        "binance",
        "coingecko",
        "bybit",
        "fear_greed",
        "defillama",
        "macro_signals",
        "derivatives_signals",
        "liquidation_signals",
        "database",
        "brain",
    }
)


class DegradationRegistry:
    """
    Tracks degraded components and their fallbacks.

    Thread-safety: not locked — single-threaded training loop only.
    """

    def __init__(self, known_components: frozenset[str] | None = None) -> None:
        self._known = known_components if known_components is not None else KNOWN_COMPONENTS
        self._degraded: dict[str, dict[str, Any]] = {}

    def mark_degraded(self, component: str, reason: str, fallback: str) -> None:
        """Record that *component* is degraded and *fallback* is being used."""
        self._degraded[component] = {
            "reason": reason,
            "since": time.time(),
            "fallback": fallback,
        }
        logger.warning("DEGRADED: %s — %s (using: %s)", component, reason, fallback)

    def mark_healthy(self, component: str) -> None:
        """Remove *component* from the degraded registry."""
        if component in self._degraded:
            del self._degraded[component]
            logger.info("RECOVERED: %s", component)

    def is_degraded(self, component: str) -> bool:
        return component in self._degraded

    def health_summary(self) -> dict[str, Any]:
        n_degraded_known = sum(1 for k in self._degraded if k in self._known)
        return {
            "total_components": len(self._known),
            "healthy": len(self._known) - n_degraded_known,
            "degraded": n_degraded_known,
            "details": dict(self._degraded),
        }


# ── Module-level singleton ───────────────────────────────────────────────────

_REGISTRY: DegradationRegistry | None = None


def get_registry() -> DegradationRegistry:
    """Return the process-wide DegradationRegistry singleton."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = DegradationRegistry()
    return _REGISTRY
