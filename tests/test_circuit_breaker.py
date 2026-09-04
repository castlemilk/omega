"""Tests for omega.core.circuit_breaker."""
import time

import pytest

from omega.core.circuit_breaker import CircuitBreaker


def test_closed_state_passes_calls():
    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=300)
    result = cb.call(lambda: 42)
    assert result == 42
    assert cb.state == "CLOSED"


def test_opens_after_threshold_failures():
    cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=300)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cb.state == "OPEN"


def test_open_returns_none_without_calling():
    calls = []
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=300)
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cb.state == "OPEN"
    result = cb.call(lambda: calls.append(1) or 99)
    assert result is None
    assert calls == []  # function was never called


def test_transitions_to_half_open_after_timeout():
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0)
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cb.state == "OPEN"
    time.sleep(0.01)
    # Next call should attempt (HALF_OPEN → CLOSED on success)
    result = cb.call(lambda: "ok")
    assert result == "ok"
    assert cb.state == "CLOSED"


def test_half_open_failure_reopens():
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0)
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("first")))
    time.sleep(0.01)
    with pytest.raises(RuntimeError):
        cb.call(lambda: (_ for _ in ()).throw(RuntimeError("second")))
    assert cb.state == "OPEN"
