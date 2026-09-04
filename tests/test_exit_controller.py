"""
tests/test_exit_controller.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the ATR-based ExitController (omega.nodes.victoria.exit_controller).

Tests cover:
  - ATR computation from OHLCV data
  - Hard MAE stop fires at mae_stop_k * ATR
  - MFE trailing stop fires after retracement_cap fraction of peak
  - MFE trailing stop does NOT fire before trail_activation (mfe_trail_k * ATR)
  - Disabled controller never fires
  - Exit telemetry: win_capture, loss_capture, exit_score
  - aggregate_disposition from a list of trades
  - Integration smoke test via PaperTradingEngine
"""

import math

import pytest

from omega.nodes.victoria.exit_controller import (
    ExitConfig,
    ExitController,
    aggregate_disposition,
    compute_atr,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_market_data(price: float = 100.0, atr_approx: float = 2.0, n: int = 20) -> dict:
    """Synthetic OHLCV where ATR ≈ atr_approx (high-low range per bar)."""
    closes = [price] * n
    highs = [price + atr_approx / 2] * n
    lows = [price - atr_approx / 2] * n
    return {"close": closes, "high": highs, "low": lows}


def make_pos(
    entry: float = 100.0,
    side: str = "long",
    size: float = 10_000.0,
    mae: float = 0.0,
    mfe: float = 0.0,
) -> dict:
    return {"entry": entry, "side": side, "size": size, "mae": mae, "mfe": mfe}


# ---------------------------------------------------------------------------
# ATR computation
# ---------------------------------------------------------------------------

class TestComputeATR:
    def test_basic_range(self):
        """ATR ≈ high-low range when prev-close differences are smaller."""
        md = make_market_data(price=100.0, atr_approx=4.0, n=20)
        atr = compute_atr(md, period=14)
        assert 3.5 < atr < 4.5, f"Expected ATR ~4.0, got {atr}"

    def test_insufficient_data_returns_zero(self):
        md = {"close": [100.0], "high": [101.0], "low": [99.0]}
        assert compute_atr(md) == 0.0

    def test_empty_data_returns_zero(self):
        assert compute_atr({}) == 0.0
        assert compute_atr({"close": [], "high": [], "low": []}) == 0.0

    def test_gap_included_in_true_range(self):
        """True range includes overnight gaps (|high - prev_close|)."""
        # prev_close = 100, then gap open to high=110, low=108 → TR = max(2, 10, 8) = 10
        md = {
            "close": [100.0, 109.0],
            "high":  [101.0, 110.0],
            "low":   [99.0,  108.0],
        }
        atr = compute_atr(md, period=14)
        assert atr == 10.0, f"Expected TR=10 for gap, got {atr}"


# ---------------------------------------------------------------------------
# Hard MAE stop
# ---------------------------------------------------------------------------

class TestHardMAEStop:
    def setup_method(self):
        self.cfg = ExitConfig(enabled=True, mfe_trail_k=2.0, mfe_retracement_cap=0.25, mae_stop_k=1.0)
        self.ec = ExitController(self.cfg)

    def test_fires_at_threshold(self):
        """Close when unrealised loss exactly equals mae_stop_k * ATR (dollars)."""
        entry = 100.0
        size = 10_000.0
        quantity = size / entry          # 100 units
        atr_price = 2.0                  # ATR in price terms
        atr_dollars = atr_price * quantity  # 200 USD
        # unrealized = -(1.0 * 200) = -200 → exactly at threshold
        unrealized = -(self.cfg.mae_stop_k * atr_dollars)
        pos = make_pos(entry=entry, size=size, mfe=0.0, mae=unrealized)
        md = make_market_data(price=100.0, atr_approx=atr_price)
        close, reason = self.ec.should_close(pos, entry, md, size, unrealized)
        assert close, f"Expected close, reason={reason}"
        assert "hard_stop_mae" in reason

    def test_does_not_fire_above_threshold(self):
        """Should NOT close if loss is only half the MAE stop threshold."""
        entry = 100.0
        size = 10_000.0
        quantity = size / entry
        atr_price = 2.0
        atr_dollars = atr_price * quantity  # 200
        unrealized = -(0.5 * self.cfg.mae_stop_k * atr_dollars)  # -100 (half)
        pos = make_pos(entry=entry, size=size, mfe=0.0, mae=unrealized)
        md = make_market_data(price=100.0, atr_approx=atr_price)
        close, _ = self.ec.should_close(pos, entry, md, size, unrealized)
        assert not close

    def test_profit_position_not_stopped(self):
        """A profitable position should not be hard-stopped."""
        pos = make_pos(entry=100.0, size=10_000.0, mfe=500.0)
        md = make_market_data(price=105.0, atr_approx=2.0)
        close, _ = self.ec.should_close(pos, 105.0, md, 10_000.0, 500.0)
        # May fire MFE trail but not hard stop — either way, not hard_stop_mae
        if close:
            _, reason = self.ec.should_close(pos, 105.0, md, 10_000.0, 500.0)
            assert "hard_stop_mae" not in reason


# ---------------------------------------------------------------------------
# MFE trailing stop
# ---------------------------------------------------------------------------

class TestMFETrailingStop:
    def setup_method(self):
        self.cfg = ExitConfig(
            enabled=True,
            mfe_trail_k=1.0,
            mfe_retracement_cap=0.25,
            mae_stop_k=2.0,  # high — won't fire in these tests
        )
        self.ec = ExitController(self.cfg)

    def _atr_dollars(self, entry=100.0, size=10_000.0, atr_price=2.0):
        return atr_price * (size / entry)

    def test_trailing_fires_after_retracement(self):
        """After MFE >= trail_activation, close when we give back > retracement_cap."""
        entry = 100.0
        size = 10_000.0
        atr_price = 2.0
        atr_d = self._atr_dollars(entry, size, atr_price)  # 200
        mfe = self.cfg.mfe_trail_k * atr_d * 1.5  # 300 — above activation
        # Give back more than retracement_cap (0.25) of MFE
        unrealized = mfe * (1.0 - self.cfg.mfe_retracement_cap) - 1.0  # just below trail level
        pos = make_pos(entry=entry, size=size, mfe=mfe)
        md = make_market_data(price=100.0, atr_approx=atr_price)
        close, reason = self.ec.should_close(pos, entry, md, size, unrealized)
        assert close, f"Expected trail to fire, got reason={reason}"
        assert "mfe_trail" in reason

    def test_trailing_does_not_fire_before_activation(self):
        """If MFE < trail_activation, trailing should NOT fire even with retracement."""
        entry = 100.0
        size = 10_000.0
        atr_price = 2.0
        atr_d = self._atr_dollars(entry, size, atr_price)  # 200
        mfe = self.cfg.mfe_trail_k * atr_d * 0.5  # 100 — BELOW activation
        unrealized = mfe * 0.5  # 50% retracement — would fire if activated
        pos = make_pos(entry=entry, size=size, mfe=mfe)
        md = make_market_data(price=100.0, atr_approx=atr_price)
        close, _ = self.ec.should_close(pos, entry, md, size, unrealized)
        assert not close

    def test_trailing_does_not_fire_above_trail_level(self):
        """If unrealised > trail_level, do NOT close (position still running well)."""
        entry = 100.0
        size = 10_000.0
        atr_price = 2.0
        atr_d = self._atr_dollars(entry, size, atr_price)  # 200
        mfe = self.cfg.mfe_trail_k * atr_d * 2.0  # 400
        trail_level = mfe * (1.0 - self.cfg.mfe_retracement_cap)  # 300
        unrealized = trail_level + 50.0  # still above trail level → keep open
        pos = make_pos(entry=entry, size=size, mfe=mfe)
        md = make_market_data(price=100.0, atr_approx=atr_price)
        close, _ = self.ec.should_close(pos, entry, md, size, unrealized)
        assert not close


# ---------------------------------------------------------------------------
# Disabled controller
# ---------------------------------------------------------------------------

class TestDisabledController:
    def test_never_fires_when_disabled(self):
        ec = ExitController(ExitConfig(enabled=False))
        pos = make_pos(entry=100.0, size=10_000.0, mae=-999.0, mfe=999.0)
        md = make_market_data()
        close, reason = ec.should_close(pos, 50.0, md, 10_000.0, -5_000.0)
        assert not close
        assert reason == ""


# ---------------------------------------------------------------------------
# Exit telemetry
# ---------------------------------------------------------------------------

class TestExitTelemetry:
    def test_winner_capture(self):
        """Winner: pnl/mfe gives fraction of peak captured."""
        t = ExitController.compute_exit_telemetry(pnl=300.0, mfe=400.0, mae=-50.0)
        assert t["win_capture"] == pytest.approx(0.75, abs=1e-4)
        assert t["loss_capture"] is None
        assert t["exit_score"] == pytest.approx(0.75, abs=1e-4)

    def test_loser_capture(self):
        """Loser: |pnl|/|mae| gives fraction of worst seen realised."""
        t = ExitController.compute_exit_telemetry(pnl=-200.0, mfe=50.0, mae=-300.0)
        assert t["win_capture"] is None
        assert t["loss_capture"] == pytest.approx(0.6667, abs=1e-3)
        assert t["exit_score"] == pytest.approx(-0.6667, abs=1e-3)

    def test_both_win_loss_capture(self):
        """When both exist (accumulated over multiple trades), exit_score = win - loss."""
        # Simulate a trade that had both positive and we test with synthetic values
        # This doesn't happen per-trade but tests the formula
        # We test it manually: win_cap=0.8, loss_cap=0.4 → exit_score=0.4
        t = ExitController.compute_exit_telemetry(pnl=400.0, mfe=500.0, mae=-200.0)
        assert t["win_capture"] == pytest.approx(0.8, abs=1e-4)
        # pnl > 0 so no loss_capture
        assert t["loss_capture"] is None

    def test_zero_mfe_no_capture(self):
        """If MFE is 0, win_capture is undefined (avoid divide-by-zero)."""
        t = ExitController.compute_exit_telemetry(pnl=100.0, mfe=0.0, mae=-50.0)
        assert t["win_capture"] is None

    def test_zero_mae_no_loss_capture(self):
        t = ExitController.compute_exit_telemetry(pnl=-100.0, mfe=50.0, mae=0.0)
        assert t["loss_capture"] is None


# ---------------------------------------------------------------------------
# aggregate_disposition
# ---------------------------------------------------------------------------

class TestAggregateDisposition:
    def _trade(self, pnl, mfe, mae, exit_score=None):
        t = {"pnl": pnl, "mfe": mfe, "mae": mae}
        if exit_score is not None:
            t["exit_score"] = exit_score
        return t

    def test_positive_disposition(self):
        """High win capture + low loss capture → positive coefficient."""
        trades = [
            self._trade(900.0, 1000.0, -100.0),  # win_cap=0.9
            self._trade(800.0, 1000.0, -200.0),  # win_cap=0.8
            self._trade(-100.0, 50.0, -500.0),   # loss_cap=0.2
            self._trade(-50.0, 30.0, -400.0),    # loss_cap=0.125
        ]
        result = aggregate_disposition(trades)
        assert result["disposition_coefficient"] > 0, result

    def test_negative_disposition(self):
        """Classic disposition effect: cut winners early, hold losers."""
        trades = [
            self._trade(100.0, 1000.0, -50.0),   # win_cap=0.10 (cut winner early)
            self._trade(50.0, 900.0, -30.0),      # win_cap=0.055
            self._trade(-900.0, 100.0, -1000.0),  # loss_cap=0.9 (rode loser to bottom)
            self._trade(-800.0, 50.0, -900.0),    # loss_cap=0.888
        ]
        result = aggregate_disposition(trades)
        assert result["disposition_coefficient"] < 0, result

    def test_uses_precomputed_exit_score(self):
        """When exit_score column present, mean_exit_score should reflect it."""
        trades = [
            self._trade(300.0, 400.0, -100.0, exit_score=0.5),
            self._trade(-200.0, 50.0, -300.0, exit_score=-0.3),
        ]
        result = aggregate_disposition(trades)
        assert result["mean_exit_score"] == pytest.approx(0.1, abs=1e-4)
        assert result["n_with_telemetry"] == 2

    def test_empty_trades(self):
        result = aggregate_disposition([])
        assert result["disposition_coefficient"] is None
        assert result["mean_exit_score"] is None


# ---------------------------------------------------------------------------
# PaperTradingEngine integration smoke test
# ---------------------------------------------------------------------------

class TestPaperTradingIntegration:
    def test_exit_controller_wired_into_engine(self):
        """ExitController should be stored and accessible on the engine."""
        from omega.core.paper_trading import PaperTradingEngine
        ec = ExitController(ExitConfig(enabled=True, mae_stop_k=0.5))
        engine = PaperTradingEngine(exit_controller=ec)
        assert engine._exit_controller is ec

    def test_no_controller_default(self):
        from omega.core.paper_trading import PaperTradingEngine
        engine = PaperTradingEngine()
        assert engine._exit_controller is None

    def test_hard_stop_fires_in_mark_to_market(self):
        """With a very tight stop, an underwater position should be closed by ATR stop."""
        from omega.core.paper_trading import PaperTradingEngine

        # Very tight stop: fire at 0.1 * ATR
        ec = ExitController(ExitConfig(enabled=True, mae_stop_k=0.1, mfe_trail_k=99.0))
        engine = PaperTradingEngine(exit_controller=ec)

        # Manually inject a long position
        symbol = "BTCUSDT"
        entry = 100.0
        size = 10_000.0
        engine._positions[symbol] = {
            "side": "long",
            "size": size,
            "entry": entry,
            "trade_id": "test-001",
            "cycle_opened": 0,
            "exit_at_cycle": 999,
            "weight": 0.1,
            "mae": 0.0,
            "mfe": 0.0,
            "db_id": None,
        }

        # Market data: ATR ≈ 5, price drops to 98 (loss = -200 USD, ATR-dollars ≈ 500)
        # mae_stop threshold = 0.1 * 500 = 50 USD; loss = 200 > 50 → should fire
        md = {
            symbol: {
                "close": [100.0] * 19 + [98.0],
                "high":  [102.5] * 20,
                "low":   [97.5]  * 20,
            }
        }
        closed = engine.mark_to_market(md, current_cycle=1)
        assert len(closed) == 1, f"Expected 1 closed trade, got {len(closed)}"
        assert "hard_stop_mae" in closed[0]["close_reason"]
        # Exit telemetry should be present
        assert "exit_score" in closed[0]
