"""
omega.core.cross_node_memory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
CrossNodeMemory — records which signal combinations are predictive by tracking
co-occurrence of agreements/disagreements paired with trade outcomes.

Design
------
When a trade closes (win or loss), we record which signals agreed and disagreed
with each other at the time the trade was entered.  Over time this builds a
co-occurrence matrix:

  (signal_i, signal_j) → {agree_wins, agree_losses, disagree_wins, disagree_losses}

Key insight: if signal_A and signal_B tend to agree on winning trades, their
joint agreement is a positive feature.  If they tend to agree on losing trades,
their disagreement is actually informative.

After MIN_TRADES_FOR_RELIABLE_STATS (100) trades, this matrix becomes a
powerful input feature for the meta-model and attention router.

Persistence
-----------
Outcomes are persisted to the ``victoria_signal_cooccurrence`` Postgres table:

  CREATE TABLE victoria_signal_cooccurrence (
      id          BIGSERIAL PRIMARY KEY,
      cycle_id    TEXT,
      signal_values  JSONB,   -- {signal_name: float}
      pnl         FLOAT,
      won         BOOLEAN,
      recorded_at TIMESTAMPTZ
  );
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("omega.core.cross_node_memory")

# Minimum closed trades before co-occurrence stats are considered reliable
MIN_TRADES_FOR_RELIABLE_STATS = 100


# ---------------------------------------------------------------------------
# CrossNodeMemory
# ---------------------------------------------------------------------------


class CrossNodeMemory:
    """
    Tracks which signal combinations produce winning vs losing trades.

    Usage::

        mem = CrossNodeMemory()
        # after a trade closes:
        mem.record_outcome(signals, pnl=+250.0, cycle_id="cycle-42")
        # before entering the next trade:
        features = mem.get_feature_vector(current_signals)
        # features["expected_win_rate"] → 0.62  (use to scale conviction)
    """

    def __init__(self, db_url: str | None = None) -> None:
        self._db_url = db_url or os.environ.get("DATABASE_URL")

        # In-memory co-occurrence matrix
        # key: (sig_i, sig_j) with sig_i < sig_j (alphabetical)
        # value: {agree_wins, agree_losses, disagree_wins, disagree_losses}
        self._cooccurrence: dict[tuple[str, str], dict[str, int]] = {}
        self._total_trades: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        signals: dict[str, Any],
        pnl: float,
        cycle_id: str | None = None,
    ) -> None:
        """
        Record the outcome of a closed trade alongside the signal state.

        Parameters
        ----------
        signals  : signal dict at the time of trade entry (output of _do_compute_signals)
        pnl      : realised PnL (positive = win, negative = loss)
        cycle_id : optional cycle identifier for tracing
        """
        won = pnl > 0
        sig_values = self._extract_signal_values(signals)
        signal_names = sorted(sig_values.keys())

        if len(signal_names) < 2:
            return  # Need at least 2 signals to build co-occurrence

        # Update all pairs
        for i, si in enumerate(signal_names):
            for sj in signal_names[i + 1 :]:
                vi = sig_values[si]
                vj = sig_values[sj]
                # "agree" = same directional sign (both positive or both negative)
                agree = (vi > 0) == (vj > 0)
                key = (si, sj)  # already alphabetically ordered by enumerate order... wait
                # ensure canonical ordering
                key = (min(si, sj), max(si, sj))
                if key not in self._cooccurrence:
                    self._cooccurrence[key] = {
                        "agree_wins": 0,
                        "agree_losses": 0,
                        "disagree_wins": 0,
                        "disagree_losses": 0,
                    }
                entry = self._cooccurrence[key]
                if agree and won:
                    entry["agree_wins"] += 1
                elif agree and not won:
                    entry["agree_losses"] += 1
                elif not agree and won:
                    entry["disagree_wins"] += 1
                else:
                    entry["disagree_losses"] += 1

        self._total_trades += 1
        logger.debug(
            "cross_node_memory: recorded outcome pnl=%.2f won=%s total_trades=%d",
            pnl,
            won,
            self._total_trades,
        )

        # Persist to DB asynchronously (fire-and-forget; fails silently)
        if self._db_url and sig_values:
            self._persist_outcome(sig_values, pnl, won, cycle_id)

    def get_pair_stats(self, signal_i: str, signal_j: str) -> dict[str, Any]:
        """
        Return win rate statistics for a specific signal pair.

        Returns
        -------
        dict with keys:
          reliable        : bool — True if MIN_TRADES_FOR_RELIABLE_STATS reached
          agree_win_rate  : float — win rate when both signals agree
          disagree_win_rate : float — win rate when they disagree
          agree_total     : int
          disagree_total  : int
        """
        key = (min(signal_i, signal_j), max(signal_i, signal_j))
        entry = self._cooccurrence.get(key)
        if not entry:
            return {
                "reliable": False,
                "agree_win_rate": 0.5,
                "disagree_win_rate": 0.5,
                "agree_total": 0,
                "disagree_total": 0,
            }

        agree_total = entry["agree_wins"] + entry["agree_losses"]
        disagree_total = entry["disagree_wins"] + entry["disagree_losses"]

        return {
            "reliable": self._total_trades >= MIN_TRADES_FOR_RELIABLE_STATS,
            "agree_win_rate": entry["agree_wins"] / agree_total if agree_total > 0 else 0.5,
            "disagree_win_rate": (
                entry["disagree_wins"] / disagree_total if disagree_total > 0 else 0.5
            ),
            "agree_total": agree_total,
            "disagree_total": disagree_total,
        }

    def get_feature_vector(self, signals: dict[str, Any]) -> dict[str, float]:
        """
        Compute a feature vector from co-occurrence stats for the current signals.

        Returns features the meta-model can use to scale conviction.  All
        values default to neutral (0.5) until MIN_TRADES_FOR_RELIABLE_STATS
        is reached.

        Returns
        -------
        dict with keys:
          co_occurrence_reliable : 0.0 or 1.0
          expected_win_rate      : 0..1
          pair_count             : number of reliable pairs contributing
          total_trades           : total closed trades seen so far
          high_synergy_pairs     : count of pairs with agree_win_rate > 0.6
        """
        if self._total_trades < MIN_TRADES_FOR_RELIABLE_STATS:
            return {
                "co_occurrence_reliable": 0.0,
                "expected_win_rate": 0.5,
                "pair_count": 0.0,
                "total_trades": float(self._total_trades),
                "high_synergy_pairs": 0.0,
            }

        sig_values = self._extract_signal_values(signals)
        signal_names = sorted(sig_values.keys())

        win_rates: list[float] = []
        high_synergy = 0

        for i, si in enumerate(signal_names):
            for sj in signal_names[i + 1 :]:
                stats = self.get_pair_stats(si, sj)
                if not stats["reliable"]:
                    continue
                vi = sig_values[si]
                vj = sig_values[sj]
                agree = (vi > 0) == (vj > 0)
                wr = stats["agree_win_rate"] if agree else stats["disagree_win_rate"]
                win_rates.append(wr)
                if stats["agree_win_rate"] > 0.60:
                    high_synergy += 1

        expected_win_rate = sum(win_rates) / len(win_rates) if win_rates else 0.5

        return {
            "co_occurrence_reliable": 1.0,
            "expected_win_rate": expected_win_rate,
            "pair_count": float(len(win_rates)),
            "total_trades": float(self._total_trades),
            "high_synergy_pairs": float(high_synergy),
        }

    @property
    def total_trades(self) -> int:
        """Total number of closed trade outcomes recorded."""
        return self._total_trades

    @property
    def is_reliable(self) -> bool:
        """True when enough trades have been recorded for reliable statistics."""
        return self._total_trades >= MIN_TRADES_FOR_RELIABLE_STATS

    def top_synergistic_pairs(self, n: int = 5) -> list[dict[str, Any]]:
        """
        Return the top-N signal pairs by agree_win_rate.

        Only pairs with >= 10 agree observations are included.
        """
        rows: list[tuple[float, str, str, int]] = []
        for (si, sj), entry in self._cooccurrence.items():
            agree_total = entry["agree_wins"] + entry["agree_losses"]
            if agree_total < 10:
                continue
            wr = entry["agree_wins"] / agree_total
            rows.append((wr, si, sj, agree_total))
        rows.sort(key=lambda r: r[0], reverse=True)
        return [
            {"signal_i": si, "signal_j": sj, "agree_win_rate": wr, "agree_total": tot}
            for wr, si, sj, tot in rows[:n]
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_signal_values(signals: dict[str, Any]) -> dict[str, float]:
        """Extract numeric signal values, skipping metadata keys."""
        result: dict[str, float] = {}
        for name, sig in signals.items():
            if name.startswith("_"):
                continue
            if isinstance(sig, dict) and "value" in sig:
                result[name] = float(sig["value"])
        return result

    def _persist_outcome(
        self,
        sig_values: dict[str, float],
        pnl: float,
        won: bool,
        cycle_id: str | None,
    ) -> None:
        """
        Persist trade outcome to victoria_signal_cooccurrence.

        Schema::

            CREATE TABLE IF NOT EXISTS victoria_signal_cooccurrence (
                id           BIGSERIAL PRIMARY KEY,
                cycle_id     TEXT,
                signal_values JSONB,
                pnl          FLOAT,
                won          BOOLEAN,
                recorded_at  TIMESTAMPTZ DEFAULT NOW()
            );
        """
        try:
            import psycopg2

            sql = """
                INSERT INTO victoria_signal_cooccurrence
                    (cycle_id, signal_values, pnl, won, recorded_at)
                VALUES (%s, %s, %s, %s, %s)
            """
            conn = psycopg2.connect(self._db_url)
            try:
                with conn, conn.cursor() as cur:
                    cur.execute(
                        sql,
                        (
                            cycle_id or "",
                            json.dumps(sig_values),
                            float(pnl),
                            bool(won),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
            finally:
                conn.close()
            logger.debug("cross_node_memory: outcome persisted for cycle %s", cycle_id)
        except Exception as exc:
            # Never crash the caller — persistence is best-effort
            logger.debug("cross_node_memory: DB persist failed: %s", exc)

    def ensure_schema(self) -> None:
        """
        Create the victoria_signal_cooccurrence table if it does not exist.

        Safe to call repeatedly (CREATE TABLE IF NOT EXISTS).
        """
        if not self._db_url:
            return
        ddl = """
            CREATE TABLE IF NOT EXISTS victoria_signal_cooccurrence (
                id            BIGSERIAL PRIMARY KEY,
                cycle_id      TEXT,
                signal_values JSONB,
                pnl           FLOAT,
                won           BOOLEAN,
                recorded_at   TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS victoria_signal_cooccurrence_cycle_idx
                ON victoria_signal_cooccurrence (cycle_id);
        """
        try:
            import psycopg2

            conn = psycopg2.connect(self._db_url)
            try:
                with conn, conn.cursor() as cur:
                    cur.execute(ddl)
            finally:
                conn.close()
            logger.info("cross_node_memory: schema ensured")
        except Exception as exc:
            logger.debug("cross_node_memory: schema creation failed: %s", exc)
