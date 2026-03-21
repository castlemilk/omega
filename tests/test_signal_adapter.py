"""
Tests for omega.eval.signal_adapter — signal format normalisation.

The adapter must handle three input formats:
  1. Orchestrator-wrapped:  {node_id: {basic_signals: {...}, order_flow: {...}, ...}}
  2. Raw VectoraNode:       {basic_signals: {...}, order_flow: {...}, ...}
  3. Flat ticker:           {ticker: {"composite": float}, ...}

All must produce {ticker: {"composite": float, ...}} as output.
"""

import pytest

from omega.eval.signal_adapter import (
    adapt_signals,
    flatten_to_ticker_signals,
    is_orchestrator_format,
    is_raw_vectora_format,
    unwrap_orchestrator_signals,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TICKER = "BTCUSDT"
ETH = "ETHUSDT"

_BASIC_SIGNALS = {
    TICKER: {"composite": 0.6, "rsi": 45.0, "return_1d": 0.02},
    ETH: {"composite": -0.2, "rsi": 60.0, "return_1d": -0.01},
}

_RAW_VECTORA = {
    "basic_signals": _BASIC_SIGNALS,
    "order_flow": {"value": 0.3, "confidence": 0.8, "regime_tag": "bull", "raw": {}},
    "cross_asset": {"value": -0.1, "confidence": 0.5, "regime_tag": "neutral", "raw": {}},
    "_weights": {"basic_signals": 0.5, "order_flow": 0.3, "cross_asset": 0.2},
    "_regime": "default",
}

NODE_ID = "abc-123"

_ORCHESTRATOR_FORMAT = {NODE_ID: _RAW_VECTORA}

_FLAT_TICKER = {
    TICKER: {"composite": 0.6},
    ETH: {"composite": -0.2},
}


# ---------------------------------------------------------------------------
# is_orchestrator_format
# ---------------------------------------------------------------------------


class TestIsOrchestratorFormat:
    def test_detects_orchestrator_format(self):
        assert is_orchestrator_format(_ORCHESTRATOR_FORMAT) is True

    def test_rejects_raw_vectora(self):
        assert is_orchestrator_format(_RAW_VECTORA) is False

    def test_rejects_flat_ticker(self):
        assert is_orchestrator_format(_FLAT_TICKER) is False

    def test_rejects_empty(self):
        assert is_orchestrator_format({}) is False

    def test_multi_node_orchestrator(self):
        multi = {
            "node-1": _RAW_VECTORA,
            "node-2": {"basic_signals": {TICKER: {"composite": 0.1}}},
        }
        assert is_orchestrator_format(multi) is True


# ---------------------------------------------------------------------------
# is_raw_vectora_format
# ---------------------------------------------------------------------------


class TestIsRawVectoraFormat:
    def test_detects_raw_vectora(self):
        assert is_raw_vectora_format(_RAW_VECTORA) is True

    def test_detects_only_basic_signals(self):
        assert is_raw_vectora_format({"basic_signals": {TICKER: {"composite": 0.5}}}) is True

    def test_rejects_orchestrator_format(self):
        # The outer dict has node_id keys, not category names
        assert is_raw_vectora_format(_ORCHESTRATOR_FORMAT) is False

    def test_rejects_flat_ticker(self):
        assert is_raw_vectora_format(_FLAT_TICKER) is False

    def test_rejects_empty(self):
        assert is_raw_vectora_format({}) is False


# ---------------------------------------------------------------------------
# unwrap_orchestrator_signals
# ---------------------------------------------------------------------------


class TestUnwrapOrchestratorSignals:
    def test_unwraps_single_node(self):
        result = unwrap_orchestrator_signals(_ORCHESTRATOR_FORMAT)
        assert "basic_signals" in result
        assert "order_flow" in result
        assert "_regime" in result

    def test_unwraps_multi_node(self):
        node2_signals = {
            "basic_signals": {TICKER: {"composite": 0.9, "rsi": 30.0}},
            "_regime": "volatile",
        }
        multi = {"node-1": _RAW_VECTORA, "node-2": node2_signals}
        result = unwrap_orchestrator_signals(multi)
        # node-2 overwrites node-1's basic_signals and _regime
        assert result["_regime"] == "volatile"
        assert result["basic_signals"][TICKER]["composite"] == 0.9

    def test_empty_dict(self):
        assert unwrap_orchestrator_signals({}) == {}


# ---------------------------------------------------------------------------
# flatten_to_ticker_signals
# ---------------------------------------------------------------------------


class TestFlattenToTickerSignals:
    def test_expands_basic_signals(self):
        result = flatten_to_ticker_signals(_RAW_VECTORA)
        assert TICKER in result
        assert ETH in result
        assert result[TICKER]["composite"] == pytest.approx(0.6)
        assert result[ETH]["composite"] == pytest.approx(-0.2)

    def test_skips_metadata_keys(self):
        result = flatten_to_ticker_signals(_RAW_VECTORA)
        assert "_weights" not in result
        assert "_regime" not in result

    def test_scalar_categories_become_adv_entries(self):
        result = flatten_to_ticker_signals(_RAW_VECTORA)
        assert "adv_order_flow" in result
        assert result["adv_order_flow"]["composite"] == pytest.approx(0.3)
        assert "adv_cross_asset" in result
        assert result["adv_cross_asset"]["composite"] == pytest.approx(-0.1)

    def test_composite_signal_key_normalised(self):
        raw = {
            "basic_signals": {
                TICKER: {"composite_signal": 0.7, "rsi": 55.0},
            }
        }
        result = flatten_to_ticker_signals(raw)
        assert TICKER in result
        assert result[TICKER]["composite"] == pytest.approx(0.7)

    def test_empty_input(self):
        assert flatten_to_ticker_signals({}) == {}

    def test_no_basic_signals_no_tickers(self):
        raw = {"order_flow": {"value": 0.5, "confidence": 0.9, "regime_tag": "", "raw": {}}}
        result = flatten_to_ticker_signals(raw)
        assert "adv_order_flow" in result
        assert len([k for k in result if not k.startswith("adv_")]) == 0


# ---------------------------------------------------------------------------
# adapt_signals (main public function)
# ---------------------------------------------------------------------------


class TestAdaptSignals:
    def test_orchestrator_format(self):
        result = adapt_signals(_ORCHESTRATOR_FORMAT)
        assert TICKER in result
        assert ETH in result
        assert result[TICKER]["composite"] == pytest.approx(0.6)

    def test_raw_vectora_format(self):
        result = adapt_signals(_RAW_VECTORA)
        assert TICKER in result
        assert result[TICKER]["composite"] == pytest.approx(0.6)

    def test_flat_ticker_passthrough(self):
        result = adapt_signals(_FLAT_TICKER)
        assert result == _FLAT_TICKER

    def test_empty_returns_empty(self):
        assert adapt_signals({}) == {}

    def test_orchestrator_includes_adv_entries(self):
        result = adapt_signals(_ORCHESTRATOR_FORMAT)
        assert "adv_order_flow" in result

    def test_both_formats_produce_same_tickers(self):
        """Raw and orchestrator formats for same data should yield same tickers."""
        from_raw = adapt_signals(_RAW_VECTORA)
        from_orch = adapt_signals(_ORCHESTRATOR_FORMAT)
        assert set(from_raw.keys()) == set(from_orch.keys())
        for ticker in (TICKER, ETH):
            assert from_raw[ticker]["composite"] == pytest.approx(from_orch[ticker]["composite"])

    def test_composite_signal_key_handled(self):
        raw_with_cs = {
            "basic_signals": {
                TICKER: {"composite_signal": 0.55, "rsi": 40.0},
            },
            "_regime": "default",
        }
        result = adapt_signals(raw_with_cs)
        assert TICKER in result
        assert result[TICKER]["composite"] == pytest.approx(0.55)

    def test_multi_node_orchestrator(self):
        """Later nodes' keys overwrite earlier ones (simple dict update semantics)."""
        # When two nodes both have "basic_signals", node-2's dict overwrites node-1's.
        multi_orch = {
            "node-1": {"basic_signals": {TICKER: {"composite": 0.4}}},
            "node-2": {"basic_signals": {ETH: {"composite": -0.3}}},
        }
        result = adapt_signals(multi_orch)
        # Only ETH survives — node-2's basic_signals overwrites node-1's
        assert ETH in result
        assert result[ETH]["composite"] == pytest.approx(-0.3)
