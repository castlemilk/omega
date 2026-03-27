"""
omega.core.circuit_breaker
~~~~~~~~~~~~~~~~~~~~~~~~~~
Three-state circuit breaker: CLOSED → OPEN → HALF_OPEN → CLOSED.

Usage::

    cb = CircuitBreaker("binance", failure_threshold=3, recovery_timeout=300)
    result = cb.call(provider.fetch, pairs)  # returns None when OPEN
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("omega.core.circuit_breaker")


class CircuitBreaker:
    """
    Three-state circuit breaker.

    CLOSED    — normal operation, calls pass through.
    OPEN      — too many failures; calls are skipped (return None).
    HALF_OPEN — recovery probe; one call is allowed through to test health.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 300.0,
    ) -> None:
        self.name = name
        self.state: str = "CLOSED"
        self.failure_count: int = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time: float = 0.0

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Call *func* with *args*/*kwargs*, applying circuit-breaker logic.

        Returns None immediately when the circuit is OPEN and the recovery
        timeout has not elapsed. Re-raises on failure (so callers that want
        to catch the error can still do so).
        """
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                logger.info("CircuitBreaker '%s': OPEN → HALF_OPEN (probing)", self.name)
                self.state = "HALF_OPEN"
            else:
                logger.warning(
                    "CircuitBreaker '%s' OPEN — skipping call (%.0fs remaining)",
                    self.name,
                    self.recovery_timeout - (time.time() - self.last_failure_time),
                )
                return None

        try:
            result = func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                logger.info("CircuitBreaker '%s': HALF_OPEN → CLOSED (recovered)", self.name)
                self.state = "CLOSED"
                self.failure_count = 0
            return result
        except Exception as exc:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                if self.state != "OPEN":
                    logger.error(
                        "CircuitBreaker '%s' OPENED after %d failures (last: %s)",
                        self.name,
                        self.failure_count,
                        exc,
                    )
                self.state = "OPEN"
            raise
