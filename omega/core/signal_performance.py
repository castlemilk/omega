"""
omega.core.signal_performance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Automated signal performance tracker.

Tracks per-signal metrics across training cycles:

  IC (information coefficient)
    Pearson correlation between signal value and next-period return.
    Range [-1, 1]; positive means the signal predicts direction correctly.

  hit_rate
    Fraction of cycles where the signal's direction matched a profitable trade.
    Counts only cycles with a non-trivial signal (|value| > epsilon).

  value_added
    Signal-weighted PnL minus the flat (equal-weight) portfolio PnL baseline.
    Positive means this signal adds alpha beyond holding equal weights.

  stability
    Lag-1 autocorrelation of signal values clipped to [0, 1].
    High-stability signals are reliable for position holding; noisy signals
    that flip every cycle are down-weighted.

Composite score (used for rankings and DynamicWeightAllocator IC updates):
    composite = 0.40 * |IC| + 0.30 * hit_rate + 0.20 * stability
                + 0.10 * max(0, value_added_normalised)

Persistence:
    signal_performance(signal_name, cycle, ic, hit_rate, value_added,
                       stability, composite_score, timestamp)
    UNIQUE constraint on (signal_name, cycle) — safe to call every cycle.

Usage::
    tracker = SignalPerformanceTracker(SIGNAL_NAMES)
    # each cycle after signals + realized return known:
    tracker.record_cycle(cycle, signal_values, forward_return, trade_pnl)
    # feed IC back into weight allocator:
    ic_map = tracker.get_ic_updates()
    weight_allocator.update_ic_batch(ic_map)
    # persist
    tracker.persist_to_db(cycle)
    # get rankings
    rankings = tracker.get_signal_rankings()
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("omega.core.signal_performance")

# ── Composite score weights ────────────────────────────────────────────────────
_IC_WEIGHT = 0.40
_HIT_RATE_WEIGHT = 0.30
_STABILITY_WEIGHT = 0.20
_VALUE_ADDED_WEIGHT = 0.10

# Rolling window for metric computation
_DEFAULT_WINDOW = 50

# Minimum samples before metrics are considered meaningful
_MIN_SAMPLES = 5

# Signal threshold below which a value is treated as "no signal"
_SIGNAL_EPSILON = 1e-4

# Persist every N cycles (avoids DB hammering on fast cycles)
_PERSIST_INTERVAL = 5


@dataclass
class SignalRanking:
    """Performance summary for a single signal, sorted by composite_score."""

    signal_name: str
    ic: float            # information coefficient (Pearson r)
    hit_rate: float      # profitable-direction match rate
    value_added: float   # PnL vs flat portfolio baseline
    stability: float     # lag-1 autocorrelation [0, 1]
    composite_score: float
    sample_count: int


class SignalPerformanceTracker:
    """
    Tracks per-signal performance metrics across training cycles.

    Parameters
    ----------
    signal_names : list[str]
        The canonical list of signal names to track (e.g. SIGNAL_NAMES from
        victoria_node).
    window : int
        Rolling history window.  Default 50 cycles.
    persist_interval : int
        Write to DB every N cycles.  Default 5.
    """

    def __init__(
        self,
        signal_names: list[str],
        window: int = _DEFAULT_WINDOW,
        persist_interval: int = _PERSIST_INTERVAL,
    ) -> None:
        self._signals = list(signal_names)
        self._window = window
        self._persist_interval = persist_interval

        # history[name] = list of (signal_value, forward_return, trade_pnl)
        self._history: dict[str, list[tuple[float, float, float]]] = {
            name: [] for name in signal_names
        }
        self._cycles_since_persist = 0

    # ── Public API ─────────────────────────────────────────────────────────────

    def record_cycle(
        self,
        cycle: int,
        signal_values: dict[str, float],
        forward_return: float,
        trade_pnl: float = 0.0,
    ) -> None:
        """
        Record one cycle's observations.

        Call this at the *start* of cycle N+1 with the realized return from
        cycle N so the signal-at-T and return-T→T+1 are correctly paired.

        Parameters
        ----------
        cycle         : training cycle number (used for logging)
        signal_values : {signal_name: float} — signal values from the *previous* cycle
        forward_return: realized next-period return (e.g. BTC % change T→T+1)
        trade_pnl     : PnL from the trade executed in that cycle (proxy for value_added)
        """
        for name in self._signals:
            val = float(signal_values.get(name, 0.0))
            self._history[name].append((val, forward_return, trade_pnl))
            if len(self._history[name]) > self._window:
                self._history[name].pop(0)

        self._cycles_since_persist += 1
        logger.debug(
            "record_cycle: cycle=%d n_signals=%d fwd_ret=%.4f pnl=%.4f",
            cycle,
            len(signal_values),
            forward_return,
            trade_pnl,
        )

    def get_signal_rankings(self) -> list[SignalRanking]:
        """
        Return signals ordered by composite performance score (descending).

        Signals with fewer than _MIN_SAMPLES observations are ranked last.
        """
        rankings: list[SignalRanking] = []
        for name in self._signals:
            history = self._history[name]
            n = len(history)
            if n < _MIN_SAMPLES:
                rankings.append(
                    SignalRanking(
                        signal_name=name,
                        ic=0.0,
                        hit_rate=0.0,
                        value_added=0.0,
                        stability=0.0,
                        composite_score=0.0,
                        sample_count=n,
                    )
                )
                continue

            values = [h[0] for h in history]
            returns = [h[1] for h in history]
            pnls = [h[2] for h in history]

            ic = _pearson_correlation(values, returns)
            hit_rate = _compute_hit_rate(values, returns, pnls)
            value_added = _compute_value_added(values, pnls)
            stability = _compute_stability(values)

            # Normalise value_added to [0, 1] range for composite mixing:
            # use a soft sigmoid-like clamp so a single large-pnl outlier
            # doesn't dominate the score.
            va_norm = max(0.0, math.tanh(value_added * 10.0))

            composite = (
                _IC_WEIGHT * abs(ic)
                + _HIT_RATE_WEIGHT * hit_rate
                + _STABILITY_WEIGHT * stability
                + _VALUE_ADDED_WEIGHT * va_norm
            )

            rankings.append(
                SignalRanking(
                    signal_name=name,
                    ic=ic,
                    hit_rate=hit_rate,
                    value_added=value_added,
                    stability=stability,
                    composite_score=composite,
                    sample_count=n,
                )
            )

        rankings.sort(key=lambda r: r.composite_score, reverse=True)
        return rankings

    def get_ic_updates(self) -> dict[str, float]:
        """
        Return {signal_name: ic_value} suitable for
        DynamicWeightAllocator.update_ic_batch().

        Uses the last 20 observations (more responsive than the full window)
        so the allocator adapts to recent regime changes.
        """
        result: dict[str, float] = {}
        for name in self._signals:
            history = self._history[name]
            if len(history) < _MIN_SAMPLES:
                continue
            recent = history[-20:]
            values = [h[0] for h in recent]
            returns = [h[1] for h in recent]
            result[name] = _pearson_correlation(values, returns)
        return result

    def get_composite_quality(self) -> float:
        """
        Return a [0, 1] quality score for the whole signal ensemble.

        Used to update the VictoriaNode state tensor's ``signal_quality``
        dimension so the attention router has an empirically grounded quality
        signal rather than a simple confidence average.

        Scores are typically in [0, 0.5]; multiply by 2 to fill the [0, 1]
        output range.
        """
        rankings = self.get_signal_rankings()
        scored = [r for r in rankings if r.sample_count >= _MIN_SAMPLES]
        if not scored:
            return 0.5  # neutral until enough data
        avg = sum(r.composite_score for r in scored) / len(scored)
        return min(1.0, avg * 2.0)

    def persist_to_db(
        self,
        cycle: int,
        db_url: str | None = None,
        force: bool = False,
    ) -> None:
        """
        Write per-signal metrics to the ``signal_performance`` table.

        Skips the write unless ``force=True`` or ``_persist_interval`` cycles
        have elapsed since the last write, to reduce DB round-trips.

        The table is auto-created if it does not exist (idempotent DDL).

        Parameters
        ----------
        cycle   : current training cycle number
        db_url  : Postgres DSN; falls back to DATABASE_URL env var
        force   : bypass the interval throttle and write immediately
        """
        if not force and self._cycles_since_persist < self._persist_interval:
            return

        try:
            import psycopg  # type: ignore[import]
        except ImportError:
            logger.debug("persist_to_db: psycopg not available — skipping")
            return

        url = db_url or os.getenv("DATABASE_URL")
        if not url:
            logger.debug("persist_to_db: DATABASE_URL not set — skipping")
            return

        rankings = self.get_signal_rankings()
        if not rankings:
            return

        upsert_sql = """
            INSERT INTO signal_performance
                (signal_name, cycle, ic, hit_rate, value_added, stability,
                 composite_score, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (signal_name, cycle)
            DO UPDATE SET
                ic              = EXCLUDED.ic,
                hit_rate        = EXCLUDED.hit_rate,
                value_added     = EXCLUDED.value_added,
                stability       = EXCLUDED.stability,
                composite_score = EXCLUDED.composite_score,
                timestamp       = EXCLUDED.timestamp
        """
        try:
            with psycopg.connect(url) as conn, conn.cursor() as cur:
                _ensure_table(cur)
                for r in rankings:
                    cur.execute(
                        upsert_sql,
                        (
                            r.signal_name,
                            cycle,
                            r.ic,
                            r.hit_rate,
                            r.value_added,
                            r.stability,
                            r.composite_score,
                        ),
                    )
            self._cycles_since_persist = 0
            logger.debug(
                "persist_to_db: wrote %d signal rows for cycle=%d",
                len(rankings),
                cycle,
            )
        except Exception as exc:
            logger.warning("persist_to_db failed: %s", exc)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_metrics(self, name: str) -> dict[str, float]:
        """Return raw metric dict for a single signal (for testing / diagnostics)."""
        history = self._history.get(name, [])
        if len(history) < _MIN_SAMPLES:
            return {"ic": 0.0, "hit_rate": 0.0, "value_added": 0.0, "stability": 0.0, "n": float(len(history))}
        values = [h[0] for h in history]
        returns = [h[1] for h in history]
        pnls = [h[2] for h in history]
        return {
            "ic": _pearson_correlation(values, returns),
            "hit_rate": _compute_hit_rate(values, returns, pnls),
            "value_added": _compute_value_added(values, pnls),
            "stability": _compute_stability(values),
            "n": float(len(history)),
        }


# ── Table DDL ──────────────────────────────────────────────────────────────────

def _ensure_table(cur: Any) -> None:
    """Create signal_performance table if it does not exist (idempotent)."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_performance (
            id              SERIAL PRIMARY KEY,
            signal_name     TEXT    NOT NULL,
            cycle           INTEGER NOT NULL,
            ic              REAL    NOT NULL DEFAULT 0.0,
            hit_rate        REAL    NOT NULL DEFAULT 0.0,
            value_added     REAL    NOT NULL DEFAULT 0.0,
            stability       REAL    NOT NULL DEFAULT 0.0,
            composite_score REAL    NOT NULL DEFAULT 0.0,
            timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (signal_name, cycle)
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_signal_performance_name
            ON signal_performance (signal_name)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_signal_performance_cycle
            ON signal_performance (cycle DESC)
        """
    )


# ── Statistical helpers ────────────────────────────────────────────────────────

def _pearson_correlation(xs: list[float], ys: list[float]) -> float:
    """
    Pearson correlation coefficient between xs and ys.

    Returns 0.0 when there is insufficient variance (e.g. constant signal).
    Result is clamped to [-1, 1].
    """
    n = len(xs)
    if n < 2 or len(ys) != n:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    var_x = sum((x - mx) ** 2 for x in xs)
    var_y = sum((y - my) ** 2 for y in ys)
    denom = math.sqrt(var_x * var_y)
    if denom < 1e-10:
        return 0.0
    return max(-1.0, min(1.0, num / denom))


def _compute_hit_rate(
    values: list[float],
    returns: list[float],
    pnls: list[float],
) -> float:
    """
    Fraction of cycles where:
      1. The signal was non-trivial (|value| > _SIGNAL_EPSILON), and
      2. The signal direction matched the return direction, and
      3. The realized PnL was positive (the trade was profitable).

    Conditions 2+3 ensure we only count genuinely useful predictions.
    Returns 0.0 when there are no eligible cycles.
    """
    eligible = 0
    hits = 0
    for v, r, pnl in zip(values, returns, pnls):
        if abs(v) <= _SIGNAL_EPSILON:
            continue  # no signal — skip
        eligible += 1
        signal_dir = 1 if v > 0 else -1
        return_dir = 1 if r > 0 else -1
        if signal_dir == return_dir and pnl > 0:
            hits += 1
    return hits / eligible if eligible > 0 else 0.0


def _compute_value_added(values: list[float], pnls: list[float]) -> float:
    """
    PnL contribution of this signal relative to a flat (constant-weight) baseline.

    Approximation:
      weighted_pnl  = Σ(|signal_value| × pnl) / Σ|signal_value|
      flat_pnl      = mean(pnl)
      value_added   = weighted_pnl - flat_pnl

    Positive means the signal steers capital toward better trades.
    """
    if not pnls:
        return 0.0
    n = len(pnls)
    flat_pnl = sum(pnls) / n
    signal_weights = [abs(v) for v in values]
    total_w = sum(signal_weights)
    if total_w < 1e-10:
        return 0.0
    weighted_pnl = sum(w * p for w, p in zip(signal_weights, pnls)) / total_w
    return weighted_pnl - flat_pnl


def _compute_stability(values: list[float]) -> float:
    """
    Lag-1 autocorrelation of signal values, clipped to [0, 1].

    High autocorrelation (> 0.7) means the signal is persistent and reliable
    for holding positions across cycles.  Negative autocorrelation (mean-
    reverting noise) is floored at 0 so it doesn't penalise the composite
    score beyond zero.
    """
    if len(values) < 3:
        return 0.0
    acf = _pearson_correlation(values[:-1], values[1:])
    return max(0.0, acf)
