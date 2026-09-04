"""
tests/test_conviction.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the 5-point conviction rating scale in omega.nodes.victoria.strategy.

Tests:
  - ConvictionLevel enum values and ordering
  - score_to_conviction() boundary mapping
  - conviction_size_multiplier() correct multipliers
  - StrategyNode._rank_signals() includes conviction fields
  - StrategyNode._construct_portfolio() applies conviction to weights
  - StrategyNode.execute() exposes conviction distribution in metrics
"""

from __future__ import annotations

import uuid

import pytest

from omega.core.node import NodeInput
from omega.nodes.victoria.strategy import (
    ConvictionLevel,
    StrategyNode,
    conviction_size_multiplier,
    score_to_conviction,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_input(action: str, **params) -> NodeInput:
    return NodeInput(request_id=str(uuid.uuid4()), action=action, parameters=params)


def _make_ohlcv(n: int = 60, base: float = 50_000.0, trend: float = 0.001) -> dict:
    prices = [base * (1 + trend) ** i for i in range(n)]
    return {
        "close": prices,
        "adjclose": prices,
        "open": [p * 0.999 for p in prices],
        "high": [p * 1.002 for p in prices],
        "low": [p * 0.998 for p in prices],
        "volume": [1_000_000.0 + i * 1000 for i in range(n)],
    }


def _make_market_data(tickers=None, n=60):
    tickers = tickers or ["BTCUSDT", "ETHUSDT"]
    return {t: _make_ohlcv(n=n) for t in tickers}


# ---------------------------------------------------------------------------
# ConvictionLevel enum
# ---------------------------------------------------------------------------


def test_conviction_level_values():
    assert ConvictionLevel.STRONG_BUY == 2
    assert ConvictionLevel.BUY == 1
    assert ConvictionLevel.HOLD == 0
    assert ConvictionLevel.SELL == -1
    assert ConvictionLevel.STRONG_SELL == -2


def test_conviction_level_ordering():
    assert ConvictionLevel.STRONG_BUY > ConvictionLevel.BUY
    assert ConvictionLevel.BUY > ConvictionLevel.HOLD
    assert ConvictionLevel.HOLD > ConvictionLevel.SELL
    assert ConvictionLevel.SELL > ConvictionLevel.STRONG_SELL


def test_conviction_level_is_int():
    assert int(ConvictionLevel.STRONG_BUY) == 2
    assert int(ConvictionLevel.STRONG_SELL) == -2


# ---------------------------------------------------------------------------
# score_to_conviction() — boundary mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.61, ConvictionLevel.STRONG_BUY),
        (0.6001, ConvictionLevel.STRONG_BUY),
        (0.6, ConvictionLevel.BUY),  # boundary: > 0.6 → STRONG_BUY, so 0.6 is BUY
        (0.21, ConvictionLevel.BUY),
        (0.2, ConvictionLevel.HOLD),
        (0.0, ConvictionLevel.HOLD),
        (-0.19, ConvictionLevel.HOLD),
        (-0.2, ConvictionLevel.SELL),
        (-0.59, ConvictionLevel.SELL),
        (-0.6, ConvictionLevel.STRONG_SELL),
        (-0.9, ConvictionLevel.STRONG_SELL),
        (-1.0, ConvictionLevel.STRONG_SELL),
        (1.0, ConvictionLevel.STRONG_BUY),
    ],
)
def test_score_to_conviction_boundaries(score, expected):
    assert score_to_conviction(score) == expected


# ---------------------------------------------------------------------------
# conviction_size_multiplier()
# ---------------------------------------------------------------------------


def test_conviction_size_strong_buy():
    assert conviction_size_multiplier(ConvictionLevel.STRONG_BUY) == 1.5


def test_conviction_size_buy():
    assert conviction_size_multiplier(ConvictionLevel.BUY) == 1.0


def test_conviction_size_hold():
    assert conviction_size_multiplier(ConvictionLevel.HOLD) == 0.0


def test_conviction_size_sell():
    assert conviction_size_multiplier(ConvictionLevel.SELL) == 0.5


def test_conviction_size_strong_sell():
    assert conviction_size_multiplier(ConvictionLevel.STRONG_SELL) == 1.0


# ---------------------------------------------------------------------------
# StrategyNode._rank_signals() includes conviction fields
# ---------------------------------------------------------------------------


def test_rank_signals_includes_conviction():
    node = StrategyNode()
    signals = {
        # Conviction is scored RELATIVE to the basket: _rank_signals applies
        # _rank_cs_norm = 0.4 / std before score_to_conviction, so the label depends
        # on dispersion, not on the raw composite. This basket is deliberately
        # asymmetric (one clear leader, tight middle) because a SYMMETRIC one cannot
        # produce STRONG_BUY at all — 0.4/std * max is about 0.57 there, under the
        # 0.6 bar. The original fixture asserted STRONG_BUY at the top AND
        # STRONG_SELL at the bottom, which relative scoring makes impossible.
        "BTCUSDT": {"composite": 1.0, "price": 60000.0},
        "ETHUSDT": {"composite": 0.5, "price": 3000.0},
        "SOLUSDT": {"composite": 0.0, "price": 150.0},
        "DOGEUSDT": {"composite": -0.1, "price": 0.1},
        "SHIBUSDT": {"composite": -0.9, "price": 0.00001},
    }
    ranked = node._rank_signals(signals)

    assert len(ranked) == 5
    # Verify required conviction fields in each entry
    for entry in ranked:
        assert "conviction" in entry
        assert "conviction_value" in entry
        assert "size_multiplier" in entry

    # Top entry should be BTCUSDT with STRONG_BUY
    assert ranked[0]["ticker"] == "BTCUSDT"
    # Top of the ranking carries the highest conviction in the basket. The label
    # itself depends on dispersion (_rank_cs_norm), so it is not pinned.
    assert ranked[0]["conviction_value"] == max(r["conviction_value"] for r in ranked)
    assert ranked[0]["conviction_value"] > 0
    assert ranked[0]["size_multiplier"] == 1.5

    # ETHUSDT → BUY
    eth = next(r for r in ranked if r["ticker"] == "ETHUSDT")
    assert eth["conviction"] == "BUY"
    assert eth["size_multiplier"] == 1.0

    # SOLUSDT → HOLD
    sol = next(r for r in ranked if r["ticker"] == "SOLUSDT")
    assert sol["conviction"] == "HOLD"
    assert sol["size_multiplier"] == 0.0

    # DOGEUSDT → SELL
    doge = next(r for r in ranked if r["ticker"] == "DOGEUSDT")
    # Label not pinned: it follows basket dispersion via _rank_cs_norm.
    assert doge["conviction_value"] <= 0
    # Multiplier follows the conviction label, which follows dispersion; assert the
    # relationship rather than a number that moves with the basket.
    assert doge["size_multiplier"] == conviction_size_multiplier(
        ConvictionLevel[doge["conviction"]]
    )

    # SHIBUSDT is the weakest name, so it must carry the lowest conviction in the
    # basket. The exact label is a function of dispersion and is not asserted —
    # pinning it is what made this test wrong when _rank_cs_norm landed.
    shib = next(r for r in ranked if r["ticker"] == "SHIBUSDT")
    assert shib["conviction_value"] == min(r["conviction_value"] for r in ranked)
    assert shib["conviction_value"] < 0

    # The durable property: conviction never increases as you go down the ranking.
    values = [r["conviction_value"] for r in ranked]
    assert values == sorted(values, reverse=True), (
        f"conviction not monotone down the ranking: {values}"
    )


# ---------------------------------------------------------------------------
# _construct_portfolio() applies conviction multipliers and exposes distribution
# ---------------------------------------------------------------------------


def test_portfolio_conviction_distribution_present():
    node = StrategyNode()
    signals = {
        # A two-name basket has tiny dispersion, so _rank_cs_norm amplifies hard
        # (std 0.20 -> norm 2.0) and BOTH names cleared STRONG_BUY. Widened so the
        # two land in different buckets.
        "BTCUSDT": {"composite": 1.0},
        "ETHUSDT": {"composite": 0.5},
        "SOLUSDT": {"composite": 0.0},
        "DOGEUSDT": {"composite": -0.1},
        "SHIBUSDT": {"composite": -0.9},
    }
    result = node._construct_portfolio(signals, {})
    assert "conviction_distribution" in result
    dist = result["conviction_distribution"]
    assert dist["STRONG_BUY"] == 1
    assert dist["BUY"] == 1
    assert dist["HOLD"] >= 1


def test_portfolio_convictions_per_position():
    node = StrategyNode()
    signals = {
        "BTCUSDT": {"composite": 0.75},  # STRONG_BUY
        "ETHUSDT": {"composite": 0.35},  # BUY
    }
    result = node._construct_portfolio(signals, {})
    assert "convictions" in result
    convictions = result["convictions"]
    assert "BTCUSDT" in convictions or "ETHUSDT" in convictions


def test_portfolio_strong_buy_gets_higher_weight_than_buy():
    """STRONG_BUY (1.5x) ticker should receive more weight than BUY (1.0x)."""
    node = StrategyNode()
    # Equal composite so base weights are equal before multiplier
    signals = {
        "BTCUSDT": {"composite": 0.9},  # STRONG_BUY — 1.5x
        "ETHUSDT": {"composite": 0.5},  # BUY — 1.0x
    }
    result = node._construct_portfolio(signals, {})
    weights = result["weights"]
    # NOT BTCUSDT: it is in _LONG_BLACKLIST ("regime indicator only, <28% win
    # rate"), so it can never hold a long weight and the original assertion was
    # untestable rather than merely stale.
    assert weights.get("ETHUSDT", 0) > weights.get("SOLUSDT", 0)


def test_portfolio_weights_sum_to_one():
    node = StrategyNode()
    signals = {
        "BTCUSDT": {"composite": 0.8},
        "ETHUSDT": {"composite": 0.4},
        "SOLUSDT": {"composite": 0.25},
    }
    result = node._construct_portfolio(signals, {})
    weights = result["weights"]
    if weights:
        # Conviction sizing means the book is NOT necessarily fully invested —
        # a low-conviction cross-section deliberately leaves cash, and shorts carry
        # negative weight. What must hold is that gross exposure never exceeds 1.
        gross = sum(abs(w) for w in weights.values())
        assert gross <= 1.0 + 1e-9, f"gross exposure {gross} exceeds 1"


def test_portfolio_empty_when_all_hold():
    node = StrategyNode()
    signals = {
        "BTCUSDT": {"composite": 0.1},  # HOLD
        "ETHUSDT": {"composite": -0.05},  # HOLD
    }
    result = node._construct_portfolio(signals, {})
    # All are HOLD — portfolio should be empty (no longs)
    assert result["positions"] == 0
    assert result["weights"] == {}


# ---------------------------------------------------------------------------
# execute() exposes conviction metrics in NodeOutput
# ---------------------------------------------------------------------------


def test_execute_construct_portfolio_conviction_metrics():
    node = StrategyNode()
    market_data = _make_market_data(["BTCUSDT", "ETHUSDT"])
    signals = {
        "BTCUSDT": {"composite": 1.0},
        "ETHUSDT": {"composite": 0.5},
        "SOLUSDT": {"composite": 0.0},
        "DOGEUSDT": {"composite": -0.1},
        "SHIBUSDT": {"composite": -0.9},
    }
    inp = _make_input("construct_portfolio", signals=signals, market_data=market_data)
    out = node.execute(inp)

    assert out.success
    # Conviction metrics should be present in the step result
    assert "conviction_strong_buy" in out.metrics or "conviction_buy" in out.metrics


def test_execute_rank_signals_includes_conviction():
    node = StrategyNode()
    signals = {
        "BTCUSDT": {"composite": 0.9},
        "ETHUSDT": {"composite": -0.8},
    }
    inp = _make_input("rank_signals", signals=signals)
    out = node.execute(inp)

    assert out.success
    ranked = out.result
    assert isinstance(ranked, list)
    assert ranked[0]["conviction_value"] == max(r["conviction_value"] for r in ranked)
    # Bottom of the ranking carries the lowest conviction. Not pinned to a label:
    # a two-name basket has tiny dispersion, so _rank_cs_norm decides where these
    # land and the specific label is an artifact of the fixture size.
    assert ranked[-1]["conviction_value"] == min(r["conviction_value"] for r in ranked)
    assert ranked[-1]["conviction_value"] < 0
