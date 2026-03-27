"""Tests for omega.core.degradation."""
from omega.core.degradation import DegradationRegistry, get_registry

KNOWN = frozenset({
    "binance", "coingecko", "bybit", "fear_greed", "defillama",
    "macro_signals", "derivatives_signals", "liquidation_signals",
    "database", "brain",
})


def test_starts_fully_healthy():
    reg = DegradationRegistry(known_components=KNOWN)
    s = reg.health_summary()
    assert s["degraded"] == 0
    assert s["healthy"] == len(KNOWN)


def test_mark_degraded_and_healthy():
    reg = DegradationRegistry(known_components=KNOWN)
    reg.mark_degraded("binance", reason="HTTP 429", fallback="bybit")
    assert reg.is_degraded("binance")
    s = reg.health_summary()
    assert s["degraded"] == 1
    reg.mark_healthy("binance")
    assert not reg.is_degraded("binance")
    assert reg.health_summary()["degraded"] == 0


def test_details_contain_reason_and_fallback():
    reg = DegradationRegistry(known_components=KNOWN)
    reg.mark_degraded("coingecko", reason="timeout", fallback="cached_data")
    details = reg.health_summary()["details"]
    assert "coingecko" in details
    assert details["coingecko"]["reason"] == "timeout"
    assert details["coingecko"]["fallback"] == "cached_data"
    assert "since" in details["coingecko"]


def test_unknown_component_does_not_inflate_known_count():
    reg = DegradationRegistry(known_components=KNOWN)
    reg.mark_degraded("some_future_component", reason="x", fallback="y")
    s = reg.health_summary()
    # total_components reflects known set only
    assert s["total_components"] == len(KNOWN)
    # The unknown component does NOT count toward degraded/healthy known counts
    assert s["degraded"] == 0


def test_singleton_returns_same_instance():
    a = get_registry()
    b = get_registry()
    assert a is b
