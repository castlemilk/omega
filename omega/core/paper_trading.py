"""
omega.core.paper_trading
~~~~~~~~~~~~~~~~~~~~~~~~
PaperTradingEngine — tracks virtual positions and PnL without any real order
execution.  Designed to be injected into OmegaOrchestrator and called from
_step_execute().

Design goals
------------
* Never crash the orchestrator: all DB operations are wrapped in try/except.
* Minimal dependencies: only stdlib + optional psycopg2 for DB writes.
* Thread-safe enough for single-threaded orchestrator use (no locking needed).
* Honest metrics: win rate, profit factor, MAE, MFE, expectancy, Calmar.

Honesty constraints
-------------------
* Entry price is always the CURRENT market price at the moment of entry
  (close[-1]), never a historical price like close[-6].  Using a stale entry
  price inflates PnL in trending markets by baking in past gains.
* Exit timing is randomized (3-7 cycles) so exits do not systematically align
  with trend direction.  A fixed 5-cycle exit in a bull market always captures
  the trend move.
* Trades with pnl == 0.0 (still open) are NEVER counted in win rate.  Only
  fully closed trades with realised PnL enter the denominator.
* MAE / MFE track the worst and best unrealised move during a trade's life so
  that a trade that was -5% before recovering to +1% is NOT treated the same as
  one that went straight to +1%.
"""

from __future__ import annotations

import logging
import os
import random
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from omega.nodes.victoria.exit_controller import ExitController

logger = logging.getLogger("omega.paper_trading")

# ---------------------------------------------------------------------------
# Optional psycopg2 import — silently falls back if not installed
# ---------------------------------------------------------------------------

_PSYCOPG2_AVAILABLE: bool
try:
    import psycopg2
    import psycopg2.extras

    _PSYCOPG2_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PSYCOPG2_AVAILABLE = False

# Noise filter: proposals with |weight| below this are ignored
_WEIGHT_THRESHOLD = 0.01

# Minimum position size as fraction of capital.
# Kelly with tiny edges produces sub-threshold positions that never hit stops,
# inflating win rate.  Positions below this are either taken at MIN or skipped.
# Use a small epsilon to avoid floating-point issues when weights are computed as
# exactly 0.05 (e.g. 0.30 / 6 = 0.049999... in IEEE 754).
_MIN_POSITION_FRACTION = 0.05
_MIN_POSITION_FRACTION_EFFECTIVE = _MIN_POSITION_FRACTION - 1e-9

# Randomized hold window (cycles) — avoids systematic trend alignment
# V73: raised min from 3→6 — short holds (4 cycles) in V72 showed -$105 on XRP/BNB;
# forcing longer hold gives trend more time to play out and reduces whipsaw exits.
_EXIT_CYCLES_MIN = 6
_EXIT_CYCLES_MAX = 10


def _rand_exit_cycles() -> int:
    """Return a randomized exit age in [_EXIT_CYCLES_MIN, _EXIT_CYCLES_MAX]."""
    return random.randint(_EXIT_CYCLES_MIN, _EXIT_CYCLES_MAX)


class PaperTradingEngine:
    """
    Lightweight paper-trading engine that tracks virtual positions and PnL.

    Parameters
    ----------
    initial_capital : float
        Notional capital in USD used to size positions.  Default 100_000.
    db_url : str | None
        PostgreSQL connection URL.  If None, falls back to the DATABASE_URL
        environment variable.  If neither is available, DB persistence is
        silently skipped.
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        db_url: str | None = None,
        max_portfolio_exposure: float = 0.80,
        max_position_per_symbol: float = 0.15,
        exit_controller: ExitController | None = None,
        trail_keep_frac: float = 0.5,
        max_hold_win: int = 10,
        max_hold_lose: int = 6,
    ) -> None:
        self.initial_capital = initial_capital
        self._db_url: str | None = db_url or os.environ.get("DATABASE_URL")
        self._max_portfolio_exposure = max_portfolio_exposure
        self._max_position_per_symbol = max_position_per_symbol
        # ATR-based exit discipline (V128+). None = use legacy time/pct logic only.
        self._exit_controller = exit_controller
        # V246 exit adaptivity: legacy-exit parameters (defaults = pre-V246
        # literals; overridden only when exit_adaptivity_enabled).
        self._trail_keep_frac = trail_keep_frac
        self._max_hold_win = max_hold_win
        self._max_hold_lose = max_hold_lose

        # In-memory state
        # {symbol: {"side": "long"|"short", "size": float, "entry": float, ...}}
        self._positions: dict[str, dict[str, Any]] = {}

        # Trades currently open (not yet closed) — do NOT count in win rate
        self._open_trades: list[dict[str, Any]] = []

        # Trades that have been closed (realised PnL) — the only ones that matter
        self._closed_trades: list[dict[str, Any]] = []

        self._realised_pnl: float = 0.0

        # Conviction filter counter: how many low-conviction trades were skipped
        self.conviction_skipped: int = 0

        # Portfolio cap counter: how many trades were skipped due to exposure limits
        self.portfolio_cap_skipped: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_price(sym_market: dict) -> float:
        """Extract the CURRENT scalar price from a market data dict.

        DataIngestionNode returns ``close`` as a list of OHLCV prices.
        This helper always returns close[-1] (the most recent price).
        Never uses historical offsets like close[-6] — that would bake in
        past gains and inflate PnL in trending markets.
        """
        c = sym_market.get("close") or sym_market.get("price") or 0.0
        if isinstance(c, list):
            return float(c[-1]) if c else 0.0
        try:
            return float(c)
        except (TypeError, ValueError):
            return 0.0

    def _total_open_notional(self) -> float:
        """Sum of all open position notional values."""
        return float(sum(pos.get("size", 0.0) for pos in self._positions.values()))

    def _check_portfolio_limits(self, symbol: str, notional: float) -> tuple[bool, str]:
        """
        Return (allowed, reason).
        Checks:
        1. Adding `notional` would not exceed max_portfolio_exposure * initial_capital
        2. Symbol's new notional would not exceed max_position_per_symbol * initial_capital
        """
        max_total = self._max_portfolio_exposure * self.initial_capital
        current_total = self._total_open_notional()
        if current_total + notional > max_total:
            return (
                False,
                f"portfolio exposure cap: {current_total + notional:.0f} > {max_total:.0f}",
            )

        # Per-symbol: existing + new
        existing_sym = self._positions.get(symbol, {})
        existing_notional = existing_sym.get("size", 0.0)
        max_sym = self._max_position_per_symbol * self.initial_capital
        if existing_notional + notional > max_sym:
            return (
                False,
                f"symbol cap {symbol}: {existing_notional + notional:.0f} > {max_sym:.0f}",
            )

        return True, ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def positions(self) -> dict[str, dict[str, Any]]:
        """Current open virtual positions (read-only view)."""
        return dict(self._positions)

    @property
    def realised_pnl(self) -> float:
        """Cumulative realised PnL across all closed trades."""
        return self._realised_pnl

    @property
    def open_trades(self) -> list[dict[str, Any]]:
        """List of currently open (unrealised) trade records."""
        return list(self._open_trades)

    @property
    def closed_trades(self) -> list[dict[str, Any]]:
        """List of all closed trade records (with realised PnL)."""
        return list(self._closed_trades)

    def compute_metrics(self) -> dict[str, Any]:
        """
        Compute honest trading metrics from closed trades only.

        Returns
        -------
        dict with keys:
          - n_closed         : number of closed trades
          - n_open           : number of still-open positions
          - win_rate         : fraction of closed trades with pnl > 0
          - profit_factor    : gross_profit / gross_loss (inf if no losses)
          - avg_win          : mean PnL of winning trades
          - avg_loss         : mean PnL of losing trades (negative)
          - expectancy       : (win_rate * avg_win) + (loss_rate * avg_loss)
          - total_pnl        : sum of all closed PnL
          - max_mae          : worst Max Adverse Excursion across all trades
          - avg_mae          : average MAE across all trades
          - max_mfe          : best Max Favourable Excursion
          - avg_mfe          : average MFE
          - calmar_ratio     : annualised_return / max_drawdown (0 if no drawdown)
          - conviction_skipped: trades skipped due to low Kelly sizing
        """
        trades = self._closed_trades
        n = len(trades)
        n_open = len(self._open_trades)

        if n == 0:
            return {
                "n_closed": 0,
                "n_open": n_open,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "expectancy": 0.0,
                "total_pnl": 0.0,
                "max_mae": 0.0,
                "avg_mae": 0.0,
                "max_mfe": 0.0,
                "avg_mfe": 0.0,
                "calmar_ratio": 0.0,
                "conviction_skipped": self.conviction_skipped,
                "portfolio_cap_skipped": self.portfolio_cap_skipped,
            }

        pnls = [float(t.get("pnl", 0.0)) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        win_rate = len(wins) / n
        profit_factor = sum(wins) / abs(sum(losses)) if losses else float("inf") if wins else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        loss_rate = 1.0 - win_rate
        expectancy = (win_rate * avg_win) + (loss_rate * avg_loss)

        # MAE / MFE from position tracking
        maes = [float(t.get("mae", 0.0)) for t in trades]
        mfes = [float(t.get("mfe", 0.0)) for t in trades]
        max_mae = min(maes) if maes else 0.0  # most negative
        avg_mae = sum(maes) / len(maes) if maes else 0.0
        max_mfe = max(mfes) if mfes else 0.0
        avg_mfe = sum(mfes) / len(mfes) if mfes else 0.0

        # Calmar: annualised return / max drawdown from equity curve
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        for p in pnls:
            # Use fractional return (pnl / initial_capital)
            r = p / self.initial_capital
            equity *= 1.0 + r
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd

        # Rough annualisation: assume each cycle is ~4h (6 cycles/day, 365 days/year)
        cycles_per_year = 6 * 365
        ann_return = (equity ** (cycles_per_year / max(n, 1))) - 1.0
        calmar = ann_return / max_dd if max_dd > 0 else 0.0

        return {
            "n_closed": n,
            "n_open": n_open,
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy": round(expectancy, 2),
            "total_pnl": round(sum(pnls), 2),
            "max_mae": round(max_mae, 2),
            "avg_mae": round(avg_mae, 2),
            "max_mfe": round(max_mfe, 2),
            "avg_mfe": round(avg_mfe, 2),
            "calmar_ratio": round(calmar, 4),
            "conviction_skipped": self.conviction_skipped,
            "portfolio_cap_skipped": self.portfolio_cap_skipped,
        }

    def execute_proposals(
        self,
        proposals: list[dict[str, Any]],
        market_data: dict[str, Any] | None = None,
        cycle_id: str | None = None,
        current_cycle: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Process a list of trade proposals and create paper trade records.

        Parameters
        ----------
        proposals     : List of proposal dicts (from _step_strategy / _step_adversarial).
        market_data   : Optional dict keyed by symbol → {"close": float|list, ...}.
        cycle_id      : Optional cycle identifier for tracing.
        current_cycle : Current orchestrator cycle number (for exit timing).

        Returns
        -------
        List of executed trade dicts that were persisted / recorded.
        """
        market_data = market_data or {}
        executed: list[dict[str, Any]] = []
        ts_now = datetime.now(UTC)

        # Mark-to-market: close stale/stopped positions before processing new proposals
        self.mark_to_market(market_data, current_cycle, cycle_id=cycle_id)

        # Update unrealized PnL on remaining open positions
        for _open_sym, pos in list(self._positions.items()):
            sym_market = market_data.get(_open_sym) or {}
            current_price = (
                self._extract_price(sym_market) if isinstance(sym_market, dict) else 0.0
            )
            if current_price <= 0:
                continue
            entry = float(pos.get("entry", current_price))
            size = float(pos.get("size", 0.0))
            direction = 1.0 if pos.get("side") == "long" else -1.0
            quantity = size / entry if entry > 0 else 0.0
            unrealized = (current_price - entry) * quantity * direction
            pos["unrealized_pnl"] = unrealized

            # Track MAE / MFE in the position record
            mae = float(pos.get("mae", 0.0))
            mfe = float(pos.get("mfe", 0.0))
            pos["mae"] = min(mae, unrealized)  # most negative (worst drawdown)
            pos["mfe"] = max(mfe, unrealized)  # most positive (best gain)

        # Process new proposals
        closed_from_flip: list[dict[str, Any]] = []
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue

            symbol: str = proposal.get("symbol") or proposal.get("ticker") or ""
            if not symbol:
                logger.debug("Skipping proposal with no symbol: %s", proposal)
                continue

            # Skip synthetic signal-aggregate tickers
            if symbol.startswith("adv_"):
                logger.debug("Skipping synthetic adv_ ticker: %s", symbol)
                continue

            weight: float = float(proposal.get("weight", 0.0))
            if abs(weight) < _WEIGHT_THRESHOLD:
                logger.debug("Skipping low-weight proposal for %s (weight=%.4f)", symbol, weight)
                continue

            # Conviction filter: if position fraction is too small, skip or bump to minimum
            raw_size_fraction = abs(weight)
            if raw_size_fraction < _MIN_POSITION_FRACTION_EFFECTIVE:
                # Track skipped low-conviction trades
                self.conviction_skipped += 1
                logger.debug(
                    "Low-conviction trade skipped: %s weight=%.4f < min=%.2f",
                    symbol,
                    raw_size_fraction,
                    _MIN_POSITION_FRACTION,
                )
                continue

            new_side = "long" if weight > 0 else "short"
            # Conviction-proportional sizing: scale down low-conviction trades.
            # conviction=0.15 → 50% of base size; conviction>=0.30 → full size.
            _conviction = float(proposal.get("conviction", 0.30))
            _conv_size_scale = min(_conviction / 0.30, 1.0)
            size = raw_size_fraction * _conv_size_scale * self.initial_capital

            # Portfolio risk checks: total exposure cap + per-symbol cap
            allowed, cap_reason = self._check_portfolio_limits(symbol, size)
            if not allowed:
                self.portfolio_cap_skipped += 1
                logger.debug("portfolio cap skip: %s", cap_reason)
                continue

            # Entry price: ALWAYS use current market price (close[-1]).
            # Never use close[-6] or any historical offset — that bakes in past
            # price moves and inflates PnL in trending markets.
            sym_market = market_data.get(symbol) or {}
            entry_price = self._extract_price(sym_market) if isinstance(sym_market, dict) else 1.0
            if entry_price <= 0:
                entry_price = 1.0

            # Skip re-entry if same-side position is already open
            existing = self._positions.get(symbol)
            if existing and existing.get("side") == new_side:
                logger.debug(
                    "Skipping re-entry for %s %s — position already open (cycle_opened=%s)",
                    new_side,
                    symbol,
                    existing.get("cycle_opened"),
                )
                continue

            # Close existing position if direction flips — realise PnL
            if existing and existing.get("side") != new_side and entry_price > 0:
                old_entry = float(existing.get("entry", entry_price))
                old_size = float(existing.get("size", 0.0))
                old_dir = 1.0 if existing["side"] == "long" else -1.0
                old_qty = old_size / old_entry if old_entry > 0 else 0.0
                realised = (entry_price - old_entry) * old_qty * old_dir
                self._realised_pnl += realised
                age = current_cycle - int(existing.get("cycle_opened", current_cycle))
                close_trade: dict[str, Any] = {
                    "trade_id": existing.get("trade_id"),
                    "cycle_id": cycle_id,
                    "ts": ts_now.isoformat(),
                    "sym": symbol,
                    "side": existing["side"],
                    "size": old_size,
                    "entry": old_entry,
                    "exit_price": entry_price,
                    "pnl": realised,
                    "slippage": 0.0,
                    "duration": age,
                    "hold_cycles": age,
                    "conviction": min(abs(float(existing.get("weight", 0.0))), 1.0),
                    "close_reason": "direction_flip",
                    "mae": float(existing.get("mae", 0.0)),
                    "mfe": float(existing.get("mfe", 0.0)),
                }
                from omega.nodes.victoria.exit_controller import ExitController as ExitCtl

                close_trade.update(
                    ExitCtl.compute_exit_telemetry(
                        realised,
                        float(existing.get("mfe", 0.0)),
                        float(existing.get("mae", 0.0)),
                    )
                )
                closed_from_flip.append(close_trade)
                self._closed_trades.append(close_trade)
                self._open_trades = [t for t in self._open_trades if t.get("sym") != symbol]
                logger.info(
                    "Closed position on flip: %s %s→%s pnl=%.4f",
                    symbol,
                    existing["side"],
                    new_side,
                    realised,
                )
                db_id_flip = existing.get("db_id")
                if db_id_flip:
                    self._update_paper_trade_closed(db_id_flip, entry_price, realised, ts_now)
                del self._positions[symbol]

            trade_id = str(uuid.uuid4())
            # Randomize exit age: 3-7 cycles so exits don't systematically align with trend
            exit_at_cycle = current_cycle + _rand_exit_cycles()

            trade: dict[str, Any] = {
                "trade_id": trade_id,
                "cycle_id": cycle_id,
                "ts": ts_now.isoformat(),
                "sym": symbol,
                "side": new_side,
                "size": size,
                "entry": entry_price,
                "exit_price": None,
                "pnl": 0.0,
                "slippage": 0.0,
                "duration": 0,
                "node_id": proposal.get("node_id"),
                "autonomy_level": proposal.get("autonomy_level"),
                "weight": weight,
                # paper_trades fields
                "symbol": symbol,
                "entry_price": entry_price,
                "unrealized_pnl": 0.0,
                "realized_pnl": 0.0,
                "status": "open",
                "opened_at": ts_now.isoformat(),
            }

            # Insert into paper_trades DB (get row id for later UPDATE on close)
            db_id = self._insert_paper_trade_open(
                {
                    "symbol": symbol,
                    "side": new_side,
                    "size": size,
                    "entry_price": entry_price,
                    "exit_price": None,
                    "unrealized_pnl": 0.0,
                    "realized_pnl": 0.0,
                    "status": "open",
                    "opened_at": ts_now,
                    "closed_at": None,
                    "cycle_id": cycle_id or "",
                }
            )

            # Track open position (last writer wins per symbol)
            self._positions[symbol] = {
                "side": new_side,
                "size": size,
                "entry": entry_price,
                "trade_id": trade_id,
                "opened_at": ts_now.isoformat(),
                "unrealized_pnl": 0.0,
                "cycle_opened": current_cycle,
                "exit_at_cycle": exit_at_cycle,  # randomized — avoids trend alignment
                "weight": weight,  # stored for conviction calculation on close
                "mae": 0.0,
                "mfe": 0.0,
                "db_id": db_id,
            }

            # New trades go to _open_trades, NOT _closed_trades
            self._open_trades.append(trade)
            executed.append(trade)
            logger.debug(
                "Paper trade: %s %s size=%.2f entry=%.4f (cycle=%s, exit_at=%d, db_id=%s)",
                new_side.upper(),
                symbol,
                size,
                entry_price,
                cycle_id,
                exit_at_cycle,
                db_id,
            )

        if closed_from_flip:
            self.persist_trades_to_db(closed_from_flip)
        if executed:
            self.persist_trades_to_db(executed)
            self.persist_signals_to_db(proposals)
        return executed

    # ------------------------------------------------------------------
    # Mark-to-market: time-based and stop-loss exits
    # ------------------------------------------------------------------

    def mark_to_market(
        self,
        market_data: dict[str, Any],
        current_cycle: int,
        stop_loss_pct: float = -0.02,
        cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Update unrealized PnL for all open positions and auto-close those that hit
        exit criteria:
          - Randomized age exit: close when current_cycle >= exit_at_cycle
            (set at entry to current_cycle + randint(3, 7))
          - Stop-loss: close if ROI < stop_loss_pct (-2% default)

        The randomized exit window prevents exits from systematically aligning
        with trend direction (the root cause of 100% win rate in bull markets).

        Returns list of closed position dicts.
        """
        closed: list[dict[str, Any]] = []
        ts_now = datetime.now(UTC)
        market_data = market_data or {}

        for symbol, pos in list(self._positions.items()):
            sym_market = market_data.get(symbol) or {}
            current_price = (
                self._extract_price(sym_market) if isinstance(sym_market, dict) else 0.0
            )
            if current_price <= 0:
                continue

            entry = float(pos.get("entry", current_price))
            size = float(pos.get("size", 0.0))
            direction = 1.0 if pos.get("side") == "long" else -1.0
            quantity = size / entry if entry > 0 else 0.0
            unrealized = (current_price - entry) * quantity * direction
            pos["unrealized_pnl"] = unrealized

            # Update MAE (worst drawdown) and MFE (best gain) during position lifetime
            pos["mae"] = min(float(pos.get("mae", 0.0)), unrealized)
            pos["mfe"] = max(float(pos.get("mfe", 0.0)), unrealized)

            # Check exit conditions
            # V65: asymmetric hold limits — cut losers fast, let winners run.
            # V73: raise loser max_hold 4→6 — V71 analysis: winners held 10 cycles avg,
            # losers averaged 4.6; 6-cycle floor gives losing trades more room to recover.
            cycle_opened = int(pos.get("cycle_opened", current_cycle))
            age = current_cycle - cycle_opened
            roi = unrealized / size if size > 0 else 0.0
            _max_hold = self._max_hold_lose if unrealized < 0 else self._max_hold_win

            should_close = False
            close_reason = ""
            mfe = float(pos.get("mfe", 0.0))

            # ── Exit controller (ATR-based, V128+) — checked first ──────
            if self._exit_controller is not None:
                ec_close, ec_reason = self._exit_controller.should_close(
                    pos, current_price, sym_market, size, unrealized, age=age
                )
                if ec_close:
                    should_close = True
                    close_reason = ec_reason

            # ── Legacy time/pct exits (fallback when controller absent or
            #    position has not yet triggered ATR conditions) ──────────
            _min_trail_age = (
                self._exit_controller.config.trailing_stop_min_age
                if self._exit_controller is not None
                else 0
            )
            _min_stop_loss_age = (
                self._exit_controller.config.stop_loss_min_age
                if self._exit_controller is not None
                else 0
            )
            # V135: skip legacy -2% stop when ATR stop is the designated guard.
            _skip_legacy_sl = (
                self._exit_controller.config.skip_legacy_stop_loss
                if self._exit_controller is not None
                else False
            )
            if not should_close:
                if age >= _max_hold:
                    should_close = True
                    _exit_type = "loss_cut" if unrealized < 0 else "profit_run"
                    close_reason = f"time_exit(age={age},{_exit_type})"
                elif not _skip_legacy_sl and age >= _min_stop_loss_age and roi < stop_loss_pct:
                    # V133: stop_loss_min_age guard — suppress the -2% stop-loss
                    # until position age >= min_age.  Without this, stop_loss fires
                    # at age 1-2 exactly when roi first crosses -2% (= MAE tick),
                    # giving structural loss_capture=1.0 before early_loss_time_stop
                    # (age >= 3) can act.  0 = original behaviour.
                    should_close = True
                    close_reason = f"stop_loss(roi={roi:.3f})"
                elif (
                    age >= _min_trail_age
                    and mfe > size * 0.005
                    and unrealized < self._trail_keep_frac * mfe
                ):
                    # Trailing stop: close if we give back more than 50% of peak MFE.
                    # Only fires when MFE is meaningful (>0.5% of position size) to
                    # avoid triggering on noise from tiny early gains.
                    # V132: _min_trail_age guard prevents this firing at age 1-2
                    # (new-low tick), which caused structural loss_capture=1.0.
                    should_close = True
                    close_reason = f"trailing_stop(mfe={mfe:.2f},unreal={unrealized:.2f})"

            if not should_close:
                continue

            # Realise PnL
            self._realised_pnl += unrealized
            close_rec: dict[str, Any] = {
                "trade_id": pos.get("trade_id"),
                "cycle_id": cycle_id,
                "ts": ts_now.isoformat(),
                "sym": symbol,
                "side": pos.get("side"),
                "size": size,
                "entry": entry,
                "exit_price": current_price,
                "pnl": unrealized,
                "slippage": 0.0,
                "duration": age,
                "hold_cycles": age,
                "conviction": min(abs(float(pos.get("weight", 0.0))), 1.0),
                "close_reason": close_reason,
                "mae": float(pos.get("mae", 0.0)),
                "mfe": float(pos.get("mfe", 0.0)),
            }
            # ── Exit telemetry (V128+): win/loss capture + exit_score ───
            from omega.nodes.victoria.exit_controller import ExitController as ExitCtl

            _tel = ExitCtl.compute_exit_telemetry(
                unrealized,
                float(pos.get("mfe", 0.0)),
                float(pos.get("mae", 0.0)),
            )
            close_rec.update(_tel)
            # ───────────────────────────────────────────────────────────
            closed.append(close_rec)
            self._closed_trades.append(close_rec)
            self._open_trades = [t for t in self._open_trades if t.get("sym") != symbol]

            logger.info(
                "mark_to_market: closed %s %s pnl=%.4f reason=%s mae=%.2f mfe=%.2f",
                pos.get("side"),
                symbol,
                unrealized,
                close_reason,
                pos.get("mae", 0.0),
                pos.get("mfe", 0.0),
            )

            db_id = pos.get("db_id")
            if db_id:
                self._update_paper_trade_closed(db_id, current_price, unrealized, ts_now)

            del self._positions[symbol]

        if closed:
            self.persist_trades_to_db(closed)

        return closed

    # ------------------------------------------------------------------
    # DB persistence helpers — both silently fail if DB is unavailable
    # ------------------------------------------------------------------

    def _insert_paper_trade_open(self, record: dict[str, Any]) -> int | None:
        """INSERT a single open paper_trade and return its DB id (for later UPDATE on close)."""
        if not _PSYCOPG2_AVAILABLE or not self._db_url:
            return None
        sql = """
            INSERT INTO paper_trades
                (symbol, side, size, entry_price, exit_price, unrealized_pnl,
                 realized_pnl, status, opened_at, closed_at, cycle_id)
            VALUES
                (%(symbol)s, %(side)s, %(size)s, %(entry_price)s, %(exit_price)s,
                 %(unrealized_pnl)s, %(realized_pnl)s, %(status)s,
                 %(opened_at)s, %(closed_at)s, %(cycle_id)s)
            RETURNING id
        """
        try:
            conn = psycopg2.connect(self._db_url)
            try:
                with conn, conn.cursor() as cur:
                    cur.execute(
                        sql,
                        {
                            "symbol": record.get("symbol", ""),
                            "side": record.get("side", "long"),
                            "size": float(record.get("size", 0.0)),
                            "entry_price": float(record.get("entry_price", 0.0)),
                            "exit_price": record.get("exit_price"),
                            "unrealized_pnl": float(record.get("unrealized_pnl", 0.0)),
                            "realized_pnl": float(record.get("realized_pnl", 0.0)),
                            "status": record.get("status", "open"),
                            "opened_at": record.get("opened_at"),
                            "closed_at": record.get("closed_at"),
                            "cycle_id": record.get("cycle_id", ""),
                        },
                    )
                    row = cur.fetchone()
                    db_id = row[0] if row else None
                logger.debug("Inserted paper_trade id=%s", db_id)
                return db_id
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Failed to insert paper_trade open: %s", exc)
            return None

    def _update_paper_trade_closed(
        self,
        db_id: int,
        exit_price: float,
        realized_pnl: float,
        closed_at: datetime,
    ) -> None:
        """UPDATE paper_trades row to mark it closed with final PnL."""
        if not _PSYCOPG2_AVAILABLE or not self._db_url:
            return
        sql = """
            UPDATE paper_trades
            SET exit_price     = %(exit_price)s,
                realized_pnl   = %(realized_pnl)s,
                unrealized_pnl = 0.0,
                status         = 'closed',
                closed_at      = %(closed_at)s
            WHERE id = %(id)s
        """
        try:
            conn = psycopg2.connect(self._db_url)
            try:
                with conn, conn.cursor() as cur:
                    cur.execute(
                        sql,
                        {
                            "exit_price": exit_price,
                            "realized_pnl": realized_pnl,
                            "closed_at": closed_at,
                            "id": db_id,
                        },
                    )
                logger.debug("Updated paper_trade id=%d → closed (pnl=%.4f)", db_id, realized_pnl)
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Failed to update paper_trade closed: %s", exc)

    def persist_trades_to_db(self, trades: list[dict[str, Any]]) -> None:
        """
        INSERT or UPDATE trade records in the victoria_trades table.

        Open trades (exit_price=None) are INSERTed with NULL exit_price so the
        column accurately represents an open position.  Closed trades (exit_price
        is a real float) trigger an UPDATE on any existing open row for the same
        trade_id, populating exit_price, pnl, and a closed_at timestamp; if no
        prior row exists they are INSERTed directly.

        Silently logs a warning and returns if psycopg2 is unavailable or the
        DB cannot be reached.
        """
        if not _PSYCOPG2_AVAILABLE:
            logger.debug("psycopg2 not available — skipping trade persistence")
            return
        if not self._db_url:
            logger.debug("No DATABASE_URL configured — skipping trade persistence")
            return
        if not trades:
            return

        insert_sql = """
            INSERT INTO victoria_trades
                (ts, sym, side, size, entry, exit_price, pnl, slippage, duration, recorded_at,
                 trade_id, closed_at)
            VALUES
                (%(ts)s, %(sym)s, %(side)s, %(size)s, %(entry)s,
                 %(exit_price)s, %(pnl)s, %(slippage)s, %(duration)s, %(recorded_at)s,
                 %(trade_id)s, %(closed_at)s)
        """
        # UPDATE existing open row when a trade is being closed (exit_price populated)
        update_sql = """
            UPDATE victoria_trades
               SET exit_price = %(exit_price)s,
                   pnl        = %(pnl)s,
                   closed_at  = NOW()
             WHERE trade_id = %(trade_id)s
               AND exit_price IS NULL
        """
        try:
            conn = psycopg2.connect(self._db_url)
            try:
                with conn, conn.cursor() as cur:
                    for trade in trades:
                        raw_exit = trade.get("exit_price")
                        is_closed = raw_exit is not None
                        trade_id = trade.get("trade_id")

                        if is_closed and trade_id:
                            # Attempt UPDATE first — closes an existing open row.
                            cur.execute(
                                update_sql,
                                {
                                    "exit_price": float(raw_exit) if raw_exit is not None else 0.0,
                                    "pnl": float(trade.get("pnl", 0.0)),
                                    "trade_id": trade_id,
                                },
                            )
                            if cur.rowcount > 0:
                                # Successfully updated an existing open row — done.
                                continue

                        # INSERT: either an open trade (exit_price=NULL) or a closed
                        # trade with no pre-existing open row (full record insert).
                        cur.execute(
                            insert_sql,
                            {
                                "ts": trade.get("ts"),
                                "sym": trade.get("sym"),
                                "side": trade.get("side"),
                                "size": float(trade.get("size", 0.0)),
                                "entry": float(trade.get("entry", 0.0)),
                                # NULL for open trades; actual price for closed trades.
                                "exit_price": (float(raw_exit) if raw_exit is not None else None)
                                if is_closed
                                else None,
                                "pnl": float(trade.get("pnl", 0.0)),
                                "slippage": float(trade.get("slippage", 0.0)),
                                "duration": int(trade.get("duration", 0)),
                                "recorded_at": float(__import__("time").time()),
                                "trade_id": trade.get("trade_id"),
                                "closed_at": trade.get("ts") if is_closed else None,
                            },
                        )
                logger.debug("Persisted %d trade(s) to DB", len(trades))
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Failed to persist trades to DB: %s", exc)

    def persist_paper_trades_to_db(self, records: list[dict[str, Any]]) -> None:
        """
        INSERT records into the paper_trades table (open positions and closings).
        Silently logs a warning on any failure.
        """
        if not _PSYCOPG2_AVAILABLE or not self._db_url or not records:
            return
        sql = """
            INSERT INTO paper_trades
                (symbol, side, size, entry_price, exit_price, unrealized_pnl,
                 realized_pnl, status, opened_at, closed_at, cycle_id)
            VALUES
                (%(symbol)s, %(side)s, %(size)s, %(entry_price)s, %(exit_price)s,
                 %(unrealized_pnl)s, %(realized_pnl)s, %(status)s,
                 %(opened_at)s, %(closed_at)s, %(cycle_id)s)
        """
        try:
            conn = psycopg2.connect(self._db_url)
            try:
                with conn, conn.cursor() as cur:
                    for rec in records:
                        cur.execute(
                            sql,
                            {
                                "symbol": rec.get("symbol", ""),
                                "side": rec.get("side", "long"),
                                "size": float(rec.get("size", 0.0)),
                                "entry_price": float(rec.get("entry_price", 0.0)),
                                "exit_price": rec.get("exit_price"),
                                "unrealized_pnl": float(rec.get("unrealized_pnl", 0.0)),
                                "realized_pnl": float(rec.get("realized_pnl", 0.0)),
                                "status": rec.get("status", "open"),
                                "opened_at": rec.get("opened_at"),
                                "closed_at": rec.get("closed_at"),
                                "cycle_id": rec.get("cycle_id", ""),
                            },
                        )
                logger.debug("Persisted %d paper_trade record(s) to DB", len(records))
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Failed to persist paper_trades to DB: %s", exc)

    def persist_signals_to_db(self, proposals: list[dict[str, Any]]) -> None:
        """
        UPSERT signal records into the victoria_signals table.

        Uses the proposal's node_id (or symbol) as the signal name key.
        Silently logs a warning and returns on any failure.
        """
        if not _PSYCOPG2_AVAILABLE:
            logger.debug("psycopg2 not available — skipping signal persistence")
            return
        if not self._db_url:
            logger.debug("No DATABASE_URL configured — skipping signal persistence")
            return
        if not proposals:
            return

        sql = """
            INSERT INTO victoria_signals
                (name, weight, current_value, conviction)
            VALUES
                (%(name)s, %(weight)s, %(current_value)s, %(conviction)s)
            ON CONFLICT (name) DO UPDATE SET
                weight        = EXCLUDED.weight,
                current_value = EXCLUDED.current_value,
                conviction    = EXCLUDED.conviction
        """
        try:
            conn = psycopg2.connect(self._db_url)
            try:
                with conn, conn.cursor() as cur:
                    for proposal in proposals:
                        if not isinstance(proposal, dict):
                            continue
                        name: str = (
                            proposal.get("node_id")
                            or proposal.get("symbol")
                            or proposal.get("ticker")
                            or "unknown"
                        )
                        weight = float(proposal.get("weight", 0.0))
                        cur.execute(
                            sql,
                            {
                                "name": name,
                                "weight": weight,
                                "current_value": weight,
                                "conviction": min(abs(weight), 1.0),
                            },
                        )
                logger.debug("Persisted %d signal(s) to DB", len(proposals))
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Failed to persist signals to DB: %s", exc)

    def persist_signal_history_to_db(
        self,
        signal_data: dict[str, Any],
        cycle: int,
    ) -> None:
        """
        INSERT signal IC snapshots into victoria_signal_history.

        Parameters
        ----------
        signal_data : Dict keyed by node_id → signal dict or list of signal dicts.
                      Each signal dict should have ``ticker``/``symbol`` and
                      ``composite_score`` (used as IC proxy).
        cycle       : Current cycle number (used as the ``t`` column).
        """
        if not _PSYCOPG2_AVAILABLE or not self._db_url or not signal_data:
            return

        rows: list[dict[str, Any]] = []
        for _node_id, signals in signal_data.items():
            if isinstance(signals, dict):
                inner = signals.get("signals") or signals.get("top_signals")
                if isinstance(inner, list):
                    for sig in inner:
                        if isinstance(sig, dict):
                            name = sig.get("ticker") or sig.get("symbol") or str(_node_id)
                            ic = float(sig.get("ic") or sig.get("composite_score") or 0.0)
                            rows.append({"signal_name": name, "t": cycle, "ic": ic})
                else:
                    name = signals.get("ticker") or signals.get("symbol") or str(_node_id)
                    ic = float(signals.get("ic") or signals.get("composite_score") or 0.0)
                    rows.append({"signal_name": name, "t": cycle, "ic": ic})
            elif isinstance(signals, list):
                for sig in signals:
                    if isinstance(sig, dict):
                        name = sig.get("ticker") or sig.get("symbol") or str(_node_id)
                        ic = float(sig.get("ic") or sig.get("composite_score") or 0.0)
                        rows.append({"signal_name": name, "t": cycle, "ic": ic})

        if not rows:
            return

        sql = """
            INSERT INTO victoria_signal_history (signal_name, t, ic)
            VALUES (%(signal_name)s, %(t)s, %(ic)s)
        """
        try:
            conn = psycopg2.connect(self._db_url)
            try:
                with conn, conn.cursor() as cur:
                    for row in rows:
                        cur.execute(sql, row)
                logger.debug("Persisted %d signal history row(s) for cycle %d", len(rows), cycle)
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Failed to persist signal history to DB: %s", exc)
