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
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

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
    ) -> None:
        self.initial_capital = initial_capital
        self._db_url: str | None = db_url or os.environ.get("DATABASE_URL")

        # In-memory state
        # {symbol: {"side": "long"|"short", "size": float, "entry": float}}
        self._positions: dict[str, dict[str, Any]] = {}
        self._closed_trades: list[dict[str, Any]] = []
        self._realised_pnl: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_price(sym_market: dict) -> float:
        """Extract a scalar price from a market data dict.

        DataIngestionNode returns ``close`` as a list of OHLCV prices.
        This helper handles both list and scalar values.
        """
        c = sym_market.get("close") or sym_market.get("price") or 0.0
        if isinstance(c, list):
            return float(c[-1]) if c else 0.0
        try:
            return float(c)
        except (TypeError, ValueError):
            return 0.0

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
    def closed_trades(self) -> list[dict[str, Any]]:
        """List of all closed trade records."""
        return list(self._closed_trades)

    def execute_proposals(
        self,
        proposals: list[dict[str, Any]],
        market_data: dict[str, Any] | None = None,
        cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Process a list of trade proposals and create paper trade records.

        Parameters
        ----------
        proposals   : List of proposal dicts (from _step_strategy / _step_adversarial).
        market_data : Optional dict keyed by symbol → {"close": float, ...}.
        cycle_id    : Optional cycle identifier for tracing.

        Returns
        -------
        List of executed trade dicts that were persisted / recorded.
        """
        market_data = market_data or {}
        executed: list[dict[str, Any]] = []
        ts_now = datetime.now(UTC)

        # Mark-to-market existing open positions and close those that flip direction
        closed_from_flip: list[dict[str, Any]] = []
        for open_sym, pos in list(self._positions.items()):
            sym_market = market_data.get(open_sym) or {}
            current_price = (
                self._extract_price(sym_market) if isinstance(sym_market, dict) else 0.0
            )
            if current_price <= 0:
                continue
            entry = float(pos.get("entry", current_price))
            size = float(pos.get("size", 0.0))
            direction = 1.0 if pos.get("side") == "long" else -1.0
            quantity = size / entry if entry > 0 else 0.0
            pos["unrealized_pnl"] = (current_price - entry) * quantity * direction

        # Process new proposals
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue

            symbol: str = proposal.get("symbol") or proposal.get("ticker") or ""
            if not symbol:
                logger.debug("Skipping proposal with no symbol: %s", proposal)
                continue

            # Skip synthetic signal-aggregate tickers — they are not real tradeable assets
            if symbol.startswith("adv_"):
                logger.debug("Skipping synthetic adv_ ticker: %s", symbol)
                continue

            weight: float = float(proposal.get("weight", 0.0))
            if abs(weight) < _WEIGHT_THRESHOLD:
                logger.debug("Skipping low-weight proposal for %s (weight=%.4f)", symbol, weight)
                continue

            new_side = "long" if weight > 0 else "short"
            size = abs(weight) * self.initial_capital

            # Resolve current price for entry
            sym_market = market_data.get(symbol) or {}
            entry_price = self._extract_price(sym_market) if isinstance(sym_market, dict) else 1.0
            if entry_price <= 0:
                entry_price = 1.0

            # Close existing position if direction flips — realise PnL
            existing = self._positions.get(symbol)
            if existing and existing.get("side") != new_side and entry_price > 0:
                old_entry = float(existing.get("entry", entry_price))
                old_size = float(existing.get("size", 0.0))
                old_dir = 1.0 if existing["side"] == "long" else -1.0
                old_qty = old_size / old_entry if old_entry > 0 else 0.0
                realised = (entry_price - old_entry) * old_qty * old_dir
                self._realised_pnl += realised
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
                    "duration": 0,
                }
                closed_from_flip.append(close_trade)
                logger.info(
                    "Closed position on flip: %s %s→%s pnl=%.4f",
                    symbol,
                    existing["side"],
                    new_side,
                    realised,
                )
                del self._positions[symbol]

            trade_id = str(uuid.uuid4())
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

            # Track open position (last writer wins per symbol)
            self._positions[symbol] = {
                "side": new_side,
                "size": size,
                "entry": entry_price,
                "trade_id": trade_id,
                "opened_at": ts_now.isoformat(),
                "unrealized_pnl": 0.0,
            }

            self._closed_trades.append(trade)
            executed.append(trade)
            logger.debug(
                "Paper trade: %s %s size=%.2f entry=%.4f (cycle=%s)",
                new_side.upper(),
                symbol,
                size,
                entry_price,
                cycle_id,
            )

        if closed_from_flip:
            self.persist_trades_to_db(closed_from_flip)
        if executed:
            self.persist_trades_to_db(executed)
            self.persist_signals_to_db(proposals)
        return executed

    # ------------------------------------------------------------------
    # DB persistence helpers — both silently fail if DB is unavailable
    # ------------------------------------------------------------------

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
                (ts, sym, side, size, entry, exit_price, pnl, slippage, duration, recorded_at)
            VALUES
                (%(ts)s, %(sym)s, %(side)s, %(size)s, %(entry)s,
                 %(exit_price)s, %(pnl)s, %(slippage)s, %(duration)s, %(recorded_at)s)
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
                # signals is a single signal dict or a dict of symbol→signal
                inner = signals.get("signals") or signals.get("top_signals")
                if isinstance(inner, list):
                    for sig in inner:
                        if isinstance(sig, dict):
                            name = sig.get("ticker") or sig.get("symbol") or str(_node_id)
                            # Prefer explicit ic field; fall back to composite_score proxy
                            ic = float(sig.get("ic") or sig.get("composite_score") or 0.0)
                            rows.append({"signal_name": name, "t": cycle, "ic": ic})
                else:
                    # Flat signal dict: each key may be a symbol
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
