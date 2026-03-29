"""
omega.core.alerting
~~~~~~~~~~~~~~~~~~~
DB auto-recovery buffer and system health scoring for the Omega platform.

DB Write Buffer
---------------
Buffers up to 100 signal batches when the DB is unreachable.  On each cycle,
``DBWriteBuffer.try_flush()`` attempts reconnection; on success it replays
pending writes in order and logs the recovery.

System Health Score
-------------------
``compute_health_score()`` returns a 0–100 integer representing current
platform health, plus a ``position_scale`` multiplier (0.0–1.0) that
Victoria uses to proportionally reduce position sizes when health < 50.

Deductions (from 100):
    -10 per data provider in OPEN/down state
    -20 if DB writes are failing
    -5  per signal stuck at 0 (value == 0.0 and confidence == 0.0)
    -10 if regime is UNKNOWN / UNKN / unknown

Usage::

    from omega.core.alerting import DBWriteBuffer, compute_health_score

    buf = DBWriteBuffer()
    buf.add(rows)                         # buffer a batch
    flushed, n = buf.try_flush(db_url)    # attempt reconnect + replay

    result = compute_health_score(
        provider_statuses=health["providers"],
        db_down=buf.is_down,
        signals=last_signals,
        regime=last_regime,
    )
    if result["score"] < 50:
        scale = result["position_scale"]   # 0.0–1.0
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

logger = logging.getLogger("omega.core.alerting")

# Maximum number of write batches held in memory
_BUFFER_CAPACITY = 100


# ─── DB Write Buffer ───────────────────────────────────────────────────────────


class DBWriteBuffer:
    """
    In-memory buffer for failed DB signal writes.

    When ``_persist_signals_to_db`` fails, call ``add(rows)`` to enqueue the
    batch.  On the next cycle, call ``try_flush(db_url)`` — it will attempt to
    reconnect and replay all pending batches in insertion order.

    Oldest batches are evicted automatically once the buffer reaches
    ``_BUFFER_CAPACITY`` (100 batches).
    """

    def __init__(self) -> None:
        self._buffer: deque[list[dict[str, Any]]] = deque(maxlen=_BUFFER_CAPACITY)
        self._db_down: bool = False
        self._down_since: float = 0.0
        self._recovered_at: float = 0.0

    @property
    def is_down(self) -> bool:
        """True when the last DB write attempt failed and we haven't recovered."""
        return self._db_down

    @property
    def pending_count(self) -> int:
        """Number of buffered write batches waiting to be replayed."""
        return len(self._buffer)

    def add(self, rows: list[dict[str, Any]]) -> None:
        """
        Enqueue a failed write batch for later replay.

        Also marks the DB as down (if not already) and emits a warning.
        """
        if not self._db_down:
            self._db_down = True
            self._down_since = time.time()
            logger.warning(
                "DBWriteBuffer: DB marked DOWN — buffering writes "
                "(capacity=%d)",
                _BUFFER_CAPACITY,
            )
        self._buffer.append(rows)
        logger.debug(
            "DBWriteBuffer: buffered batch (%d rows), total pending=%d",
            len(rows),
            len(self._buffer),
        )

    def try_flush(self, db_url: str) -> tuple[bool, int]:
        """
        Attempt to reconnect to *db_url* and replay all pending batches.

        Returns
        -------
        (success, flushed_batches)
            ``success`` — True if the connection succeeded (even if buffer was
            empty).  ``flushed_batches`` — number of batches written.
        """
        if not db_url:
            return False, 0

        try:
            import psycopg2
        except ImportError:
            return False, 0

        # Probe connection first
        try:
            probe = psycopg2.connect(db_url)
            probe.close()
        except Exception as exc:
            logger.debug("DBWriteBuffer: reconnect probe failed: %s", exc)
            return False, 0

        # Connection is live — was it previously down?
        if self._db_down:
            downtime = time.time() - self._down_since
            self._recovered_at = time.time()
            logger.info(
                "DBWriteBuffer: DB RECOVERED after %.0fs — replaying %d buffered batch(es)",
                downtime,
                len(self._buffer),
            )

        if not self._buffer:
            # DB is healthy and nothing to flush
            self._db_down = False
            return True, 0

        sql = """
            INSERT INTO victoria_signals (name, weight, current_value, conviction)
            VALUES (%(name)s, %(weight)s, %(current_value)s, %(conviction)s)
            ON CONFLICT (name) DO UPDATE SET
                weight        = EXCLUDED.weight,
                current_value = EXCLUDED.current_value,
                conviction    = EXCLUDED.conviction
        """

        flushed = 0
        try:
            conn = psycopg2.connect(db_url)
            try:
                with conn, conn.cursor() as cur:
                    while self._buffer:
                        batch = self._buffer[0]
                        for row in batch:
                            cur.execute(sql, row)
                        self._buffer.popleft()
                        flushed += 1
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                "DBWriteBuffer: flush failed after %d batch(es): %s",
                flushed,
                exc,
            )
            return False, flushed

        self._db_down = False
        logger.info(
            "DBWriteBuffer: replayed %d buffered batch(es) successfully",
            flushed,
        )
        return True, flushed

    def status_dict(self) -> dict[str, Any]:
        """Return buffer state for inclusion in health payloads."""
        return {
            "db_down": self._db_down,
            "pending_batches": self.pending_count,
            "down_since": self._down_since if self._db_down else None,
            "last_recovered_at": self._recovered_at or None,
        }


# ─── System Health Score ───────────────────────────────────────────────────────


def compute_health_score(
    provider_statuses: dict[str, Any],
    db_down: bool,
    signals: dict[str, Any],
    regime: str,
) -> dict[str, Any]:
    """
    Compute a 0–100 system health score and a position scaling multiplier.

    Parameters
    ----------
    provider_statuses:
        Dict of provider name → status dict, as returned by
        ``DataResilienceLayer.get_provider_health_summary()``.
        Each entry must contain a ``"status"`` key:
        ``"healthy"`` | ``"degraded"`` | ``"down"``.
    db_down:
        Whether DB writes are currently failing (``DBWriteBuffer.is_down``).
    signals:
        Last computed signals dict (``_last_signals``).  Keys starting with
        ``_`` are skipped.  A signal is "stuck at 0" when both ``value`` and
        ``confidence`` are 0.0.
    regime:
        Current regime label.  ``"UNKNOWN"`` / ``"UNKN"`` / ``"unknown"``
        each deduct 10 points.

    Returns
    -------
    dict with keys:
        ``score``          — int 0–100
        ``position_scale`` — float 0.0–1.0 (1.0 when score ≥ 50)
        ``deductions``     — list of (reason, amount) tuples for logging
    """
    score = 100
    deductions: list[tuple[str, int]] = []

    # Provider failures: -10 each for providers in "down" state
    for name, pstatus in provider_statuses.items():
        status = pstatus.get("status", "healthy") if isinstance(pstatus, dict) else "healthy"
        if status == "down":
            score -= 10
            deductions.append((f"provider:{name}:down", 10))

    # DB down: -20
    if db_down:
        score -= 20
        deductions.append(("db:down", 20))

    # Signals stuck at 0: -5 each
    for sig_name, sig_val in signals.items():
        if sig_name.startswith("_"):
            continue
        if not isinstance(sig_val, dict):
            continue
        val = float(sig_val.get("value", sig_val.get("composite", 1.0)))
        conf = float(sig_val.get("confidence", 1.0))
        if val == 0.0 and conf == 0.0:
            score -= 5
            deductions.append((f"signal:{sig_name}:stuck_at_zero", 5))

    # Regime unknown: -10
    if str(regime).upper() in ("UNKNOWN", "UNKN", ""):
        score -= 10
        deductions.append(("regime:unknown", 10))

    score = max(0, min(100, score))

    if score >= 50:
        position_scale = 1.0
    else:
        # Linear scale-down from 50 → 0 maps to 1.0 → 0.0
        position_scale = round(score / 50.0, 3)

    if deductions:
        logger.info(
            "SystemHealth: score=%d/100  scale=%.3f  deductions=%s",
            score,
            position_scale,
            [(r, -d) for r, d in deductions],
        )
    else:
        logger.debug("SystemHealth: score=100/100  scale=1.000  all systems nominal")

    if score < 50:
        logger.warning(
            "SystemHealth: score %d < 50 — reducing Victoria position sizes to %.1f%%",
            score,
            position_scale * 100,
        )

    return {
        "score": score,
        "position_scale": position_scale,
        "deductions": deductions,
    }


# ─── Module-level singleton ────────────────────────────────────────────────────

_write_buffer: DBWriteBuffer | None = None


def get_write_buffer() -> DBWriteBuffer:
    """Return the process-wide DBWriteBuffer singleton."""
    global _write_buffer
    if _write_buffer is None:
        _write_buffer = DBWriteBuffer()
    return _write_buffer
