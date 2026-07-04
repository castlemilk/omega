"""V238 — SeriesProvider contract + frozen-path signal tests.

Covers the pre-registered contract (training_log/V238.md):
- as-of semantics with business-day gaps
- raises SeriesOutOfRange (never wraps) before first obs, after last obs +
  grace, and across interior gaps beyond the staleness cap
- frozen_series_enabled defaults OFF (byte-identical V235 baseline)
- compute_from_series paths return NaN (not 0.0) on short/absent windows
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import pytest

from omega.nodes.victoria.series_provider import (
    SeriesOutOfRange,
    SeriesProvider,
)


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso + "T00:00:00+00:00").timestamp()


@pytest.fixture()
def provider(tmp_path):
    series = {
        # business-day style series with a weekend gap (06/07) and an interior
        # 10-day hole (2024-01-15 .. 2024-01-24 inclusive missing)
        "2024-01-02": 10.0,
        "2024-01-03": 11.0,
        "2024-01-04": 12.0,
        "2024-01-05": 13.0,
        "2024-01-08": 14.0,
        "2024-01-09": 15.0,
        "2024-01-10": 16.0,
        "2024-01-11": 17.0,
        "2024-01-12": 18.0,
        "2024-01-25": 19.0,
        "2024-01-26": 20.0,
    }
    (tmp_path / "demo.json").write_text(json.dumps({"name": "demo", "series": series}))
    return SeriesProvider(base_dir=tmp_path)


def test_as_of_exact_and_weekend(provider):
    assert provider.get("demo", _ts("2024-01-05")) == 13.0
    # Saturday/Sunday resolve to Friday's value (as-of, within staleness cap)
    assert provider.get("demo", _ts("2024-01-06")) == 13.0
    assert provider.get("demo", _ts("2024-01-07")) == 13.0


def test_before_first_raises(provider):
    with pytest.raises(SeriesOutOfRange):
        provider.get("demo", _ts("2023-12-25"))


def test_after_last_plus_grace_raises_never_wraps(provider):
    # within grace: serves the last observation
    assert provider.get("demo", _ts("2024-01-28")) == 20.0
    # past grace: refuses (never wraps, never serves stale)
    with pytest.raises(SeriesOutOfRange):
        provider.get("demo", _ts("2024-03-01"))


def test_interior_gap_beyond_staleness_raises(provider):
    # 2024-01-22 is 10 days after the last obs before the hole (2024-01-12)
    with pytest.raises(SeriesOutOfRange):
        provider.get("demo", _ts("2024-01-22"))


def test_missing_series_raises(provider):
    with pytest.raises(SeriesOutOfRange):
        provider.get("nope", _ts("2024-01-05"))
    assert not provider.available("nope")


def test_get_window_pairs(provider):
    pairs = provider.get_window_pairs("demo", _ts("2024-01-10"), 7)
    assert pairs == [
        ("2024-01-04", 12.0),
        ("2024-01-05", 13.0),
        ("2024-01-08", 14.0),
        ("2024-01-09", 15.0),
        ("2024-01-10", 16.0),
    ]
    assert provider.get_window("demo", _ts("2024-01-10"), 7) == [12.0, 13.0, 14.0, 15.0, 16.0]


def test_flag_defaults_off(monkeypatch):
    from omega.nodes.victoria.features import VictoriaFeatures

    monkeypatch.delenv("VICTORIA_FEATURES", raising=False)
    feats = VictoriaFeatures.from_env()
    assert feats.frozen_series_enabled is False


def test_fear_greed_from_series_nan_on_short():
    from omega.nodes.victoria.signals.fear_greed import FearGreedSignal

    sig = FearGreedSignal()
    assert math.isnan(sig.compute_from_series([50.0, 50.0]))
    # extreme-fear latest vs a greedy month → contrarian long, no network
    vals = [80.0] * 29 + [10.0]
    assert sig.compute_from_series(vals) == 1.0


def test_vix_from_series_threshold_mode():
    from omega.nodes.victoria.signals.vix_signal import VIXSignal

    sig = VIXSignal()
    assert math.isnan(sig.compute_from_series([20.0] * 3))
    # VIX 40 → full risk-off -0.7 regardless of yfinance availability
    assert sig.compute_from_series([20.0] * 29 + [40.0]) == pytest.approx(-0.7)
    # capitulation: 3+ days above 35 → +0.5
    assert sig.compute_from_series([20.0] * 27 + [36.0, 37.0, 38.0]) == pytest.approx(0.5)


def test_yield_curve_from_series_stateless_inversion():
    from omega.nodes.victoria.signals.yield_curve import YieldCurveSignal

    sig = YieldCurveSignal()
    days = [f"2024-01-{d:02d}" for d in range(1, 29)]
    # deep stable inversion: 2Y 5.0, 10Y 4.5 → spread -50bp → bearish
    p10 = [(d, 4.5) for d in days]
    p2 = [(d, 5.0) for d in days]
    val = sig.compute_from_series(p10, p2)
    assert -0.6 <= val < -0.3
    # too short → NaN
    assert math.isnan(sig.compute_from_series(p10[:3], p2[:3]))


def test_whale_flow_from_series():
    from omega.nodes.victoria.signals.whale_flow import WhaleFlowSignals

    wf = WhaleFlowSignals()
    out = wf.compute_all_from_series(None, None)
    assert all(math.isnan(v) for v in out.values())
    out = wf.compute_all_from_series([100.0, 101.0, 103.0], [1000.0, 1002.0])
    # OI rising ~1.5%/day avg → positive, scaled by /0.02
    assert out["oi_rate_of_change"] == pytest.approx(
        ((101 / 100 - 1) + (103 / 101 - 1)) / 2 / 0.02
    )
    assert out["stablecoin_velocity"] == pytest.approx((1002 / 1000 - 1) / 0.005)
    assert math.isnan(out["exchange_net_flow"])


def test_bar_ordinal_is_utc():
    # 23:59 UTC stays same date; guards against local-tz drift (V216 fence)
    ts = datetime(2024, 1, 5, 23, 59, tzinfo=UTC).timestamp()
    assert SeriesProvider._bar_ordinal(ts) == datetime(2024, 1, 5, tzinfo=UTC).date().toordinal()
