"""The liquidity and price screens, which are load-bearing rather than cosmetic.

Before these were live the engine ranked sub-cent stocks where one tick is a +20%
return. A single half-cent name (AEU, $0.0140 -> $0.3500 in a week) contributed
+200% to one period and drove weekly excess-return sd to 11.2%. With the screens
on, sd is 3.75% and the apparent edge disappears — which is the correct answer,
arrived at honestly. These tests exist so the screens cannot silently switch off.
"""

from __future__ import annotations

from omega.nodes.asx.portfolio import PortfolioSpec, build_target


def _day(n: int = 20, price: float = 1.0, adv: float | None = 5e6) -> dict:
    out = {}
    for i in range(n):
        row = {"short": i / 100.0, "price": price}
        if adv is not None:
            row["adv20_aud"] = adv
        out[f"C{i:02d}"] = row
    return out


def test_price_floor_excludes_sub_cent_names() -> None:
    day = _day(20, price=1.0)
    day["PENNY"] = {"short": 0.0, "price": 0.005, "adv20_aud": 5e6}  # ranks FIRST
    t = build_target("2024-01-01", day, PortfolioSpec())
    assert "PENNY" not in t.weights
    assert t.diagnostics["dropped"]["below_min_price"] == 1


def test_illiquid_name_excluded_even_when_best_ranked() -> None:
    day = _day(20, price=1.0)
    day["THIN"] = {"short": 0.0, "price": 1.0, "adv20_aud": 10_000.0}
    t = build_target("2024-01-01", day, PortfolioSpec())
    assert "THIN" not in t.weights
    assert t.diagnostics["dropped"]["below_min_adv_or_unknown"] == 1


def test_missing_adv_is_excluded_not_waved_through() -> None:
    """An absent liquidity number is not evidence of liquidity (V279)."""
    day = _day(20, price=1.0)
    day["NOADV"] = {"short": 0.0, "price": 1.0}  # no adv20_aud key
    t = build_target("2024-01-01", day, PortfolioSpec())
    assert "NOADV" not in t.weights


def test_screens_run_before_ranking() -> None:
    """An excluded name must not shift the quantile boundary either."""
    clean = build_target("2024-01-01", _day(20), PortfolioSpec())
    dirty = dict(_day(20))
    dirty["PENNY"] = {"short": -1.0, "price": 0.001, "adv20_aud": 5e6}
    after = build_target("2024-01-01", dirty, PortfolioSpec())
    assert set(after.weights) == set(clean.weights)


def test_adv_filter_reports_inert_without_volume_data() -> None:
    """A panel with no volume must SAY the filter is inert rather than pass everything."""
    t = build_target("2024-01-01", _day(20, adv=None), PortfolioSpec())
    assert t.diagnostics["adv_data_present"] is False
    assert "adv_filter_inert" in t.diagnostics
    assert t.weights  # still trades, but the inertness is on the record


def test_refuses_to_trade_when_screens_leave_too_few() -> None:
    t = build_target("2024-01-01", _day(12, price=0.01), PortfolioSpec())
    assert t.weights == {}
    assert "too few eligible" in t.diagnostics["reason"]
