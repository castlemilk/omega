"""
omega.core.decision_snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Structured per-cycle decision trace for Victoria's reasoning engine.

Captures the complete reasoning chain for every ticker every cycle:
  - Every signal's output + a human-readable rationale string
  - The full filter chain (conviction_check → ring1 → fiedler → position_limit)
  - Raw, demeaned, and final composite scores
  - Whether the ticker traded, was filtered, or held
  - Regime context at decision time

Written to the `victoria_decision_snapshots` Postgres table (same DB as trades),
mirrored to /tmp/{version}_decisions.jsonl as a fast local fallback.
The Go control plane reads from Postgres; the dashboard queries via REST.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_PSYCOPG2_AVAILABLE: bool
try:
    import psycopg2
    import psycopg2.extras

    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False

logger = logging.getLogger("omega.core.decision_snapshot")


# ---------------------------------------------------------------------------
# SignalTrace — one signal's contribution to the composite
# ---------------------------------------------------------------------------


@dataclass
class SignalTrace:
    """Trace record for a single signal's output for one ticker in one cycle."""

    signal_name: str
    """e.g. 'rsi_signal', 'sma_crossover', 'macd_crossover'"""

    raw_value: float
    """The computed signal value in [-1, 1]."""

    rationale_text: str
    """Human-readable explanation of WHY this value was produced.
    E.g. 'RSI=28.3 oversold (<30) → bullish +0.35'"""

    inputs_used: dict[str, Any] = field(default_factory=dict)
    """Key indicator values that produced this signal.
    E.g. {'rsi': 28.3, 'threshold_oversold': 30}"""

    weight_applied: float = 1.0
    """Momentum weight multiplier used in composite (1.0 or 2.0)."""


# ---------------------------------------------------------------------------
# TickerDecision — full decision trace for one ticker in one cycle
# ---------------------------------------------------------------------------


@dataclass
class TickerDecision:
    """Complete reasoning trace for a single ticker in a single cycle."""

    ticker: str

    # Signal-level outputs
    signal_traces: list[SignalTrace] = field(default_factory=list)
    """Every signal's output + rationale for this ticker."""

    # Composite computation
    raw_composite: float = 0.0
    """Unweighted mean of all directional signal values."""

    basket_mean: float = 0.0
    """Mean composite across all tickers in the basket (for demeaning)."""

    demeaned_composite: float = 0.0
    """composite - basket_mean: ticker's relative strength."""

    # Conviction
    conviction: str = "HOLD"
    """BUY / SELL / HOLD / STRONG_BUY / STRONG_SELL"""

    conviction_score: float = 0.0
    """IC-weighted composite used for conviction determination."""

    # Proposal and filter chain
    proposal: str = "NONE"
    """LONG / SHORT / NONE — based on conviction before filters."""

    filters_applied: list[str] = field(default_factory=list)
    """Ordered list of filter results, e.g.
    ['blacklist:pass', 'conviction_gate:pass', 'time_filter:pass',
     'agreement_ratio:pass(0.75>=0.60)', 'weighted_conviction:pass(0.31>=0.20)',
     'regime_block:pass', 'fiedler_floor:pass(scale=0.80)']"""

    final_action: str = "HOLD"
    """TRADE / FILTERED / HOLD / SIT_OUT"""

    filter_reason: str = ""
    """If FILTERED: the specific gate that blocked, e.g. 'agreement_ratio(0.45<0.60)'"""


# ---------------------------------------------------------------------------
# DecisionSnapshot — one cycle's full decision context
# ---------------------------------------------------------------------------


@dataclass
class DecisionSnapshot:
    """Full decision snapshot for one training cycle."""

    cycle: int
    timestamp: str
    version: str

    # Regime context
    regime: str = "unknown"
    regime_confidence: float = 0.0
    regime_hmm: str = "unknown"
    regime_w_bear: float = -1.0
    regime_w_bull: float = -1.0

    # Sit-out context
    sit_out_reason: str = "normal"
    sit_out_size_mult: float = 1.0

    # Fiedler / spectral graph state
    fiedler_scale: float = 1.0
    fiedler_regime: str = "warmup"
    fiedler_zscore: float = 0.0

    # Per-ticker decisions (keyed by ticker symbol)
    per_ticker: dict[str, TickerDecision] = field(default_factory=dict)

    # Aggregate stats for this cycle
    n_trades: int = 0
    n_filtered: int = 0
    n_hold: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dict."""
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DecisionSnapshot:
        """Deserialise from a dict (as loaded from JSONL)."""
        per_ticker_raw = d.pop("per_ticker", {})
        snap = cls(**{k: v for k, v in d.items() if k != "per_ticker"})
        for ticker, td_raw in per_ticker_raw.items():
            traces_raw = td_raw.pop("signal_traces", [])
            td = TickerDecision(**td_raw)
            td.signal_traces = [SignalTrace(**t) for t in traces_raw]
            snap.per_ticker[ticker] = td
        return snap


# ---------------------------------------------------------------------------
# _CREATE_TABLE_SQL — ensures the table exists in Postgres
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS victoria_decision_snapshots (
    id           BIGSERIAL PRIMARY KEY,
    cycle        INTEGER NOT NULL,
    version      TEXT NOT NULL DEFAULT '',
    regime       TEXT NOT NULL DEFAULT 'unknown',
    sit_out      TEXT NOT NULL DEFAULT 'normal',
    payload      JSONB NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_victoria_decisions_cycle
    ON victoria_decision_snapshots (cycle DESC);
CREATE INDEX IF NOT EXISTS idx_victoria_decisions_version
    ON victoria_decision_snapshots (version, cycle DESC);
"""


# ---------------------------------------------------------------------------
# DecisionWriter — writes snapshots to Postgres + local JSONL fallback
# ---------------------------------------------------------------------------


class DecisionWriter:
    """
    Writes DecisionSnapshot records to:
      1. Postgres `victoria_decision_snapshots` table (if DATABASE_URL configured)
      2. Local JSONL file /tmp/{version}_decisions.jsonl as a fast fallback

    The Go control plane reads from Postgres; the JSONL is for local debugging.
    """

    def __init__(self, version: str, db_url: str | None = None, output_dir: str = "/tmp") -> None:
        self._version = version
        self._db_url: str | None = db_url or os.environ.get("DATABASE_URL")
        self._path = Path(output_dir) / f"{version}_decisions.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._path, "a")
        self._db_ready = False

        if self._db_url and _PSYCOPG2_AVAILABLE:
            self._ensure_table()
        else:
            logger.info("DecisionWriter: no DB configured — writing JSONL only to %s", self._path)

    def _ensure_table(self) -> None:
        """Create the table if it doesn't exist (idempotent)."""
        try:
            conn = psycopg2.connect(self._db_url)
            with conn, conn.cursor() as cur:
                # Execute each statement separately (psycopg2 doesn't handle multi-statement)
                for stmt in _CREATE_TABLE_SQL.strip().split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        cur.execute(stmt)
            conn.close()
            self._db_ready = True
            logger.info("DecisionWriter: DB table ready, writing to Postgres + %s", self._path)
        except Exception as exc:
            logger.warning("DecisionWriter: DB setup failed (%s) — JSONL only", exc)
            self._db_ready = False

    @property
    def path(self) -> Path:
        return self._path

    def write(self, snapshot: DecisionSnapshot) -> None:
        """Write one snapshot to both DB and JSONL."""
        d = snapshot.to_dict()
        self._write_jsonl(d)
        if self._db_ready:
            self._write_db(snapshot, d)

    def _write_jsonl(self, d: dict) -> None:
        try:
            self._fh.write(json.dumps(d) + "\n")
            self._fh.flush()
        except Exception as exc:
            logger.warning("DecisionWriter: JSONL write failed: %s", exc)

    def _write_db(self, snapshot: DecisionSnapshot, d: dict) -> None:
        try:
            conn = psycopg2.connect(self._db_url)
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO victoria_decision_snapshots
                        (cycle, version, regime, sit_out, payload, recorded_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    """,
                    (
                        snapshot.cycle,
                        snapshot.version,
                        snapshot.regime,
                        snapshot.sit_out_reason,
                        json.dumps(d),
                    ),
                )
            conn.close()
        except Exception as exc:
            logger.debug("DecisionWriter: DB write failed: %s", exc)

    def close(self) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            self._fh.close()


# ---------------------------------------------------------------------------
# DecisionReader — load snapshots from JSONL for analysis
# ---------------------------------------------------------------------------


class DecisionReader:
    """Reads DecisionSnapshot records from a JSONL file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def read_all(self) -> list[DecisionSnapshot]:
        """Load all snapshots. Returns [] if file doesn't exist."""
        if not self._path.exists():
            logger.warning("DecisionReader: file not found: %s", self._path)
            return []
        snapshots: list[DecisionSnapshot] = []
        with open(self._path) as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    snapshots.append(DecisionSnapshot.from_dict(d))
                except Exception as exc:
                    logger.warning("DecisionReader: line %d parse error: %s", lineno, exc)
        return snapshots

    def iter_snapshots(self):
        """Generator — yields one DecisionSnapshot at a time (memory-efficient)."""
        if not self._path.exists():
            return
        with open(self._path) as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    yield DecisionSnapshot.from_dict(d)
                except Exception as exc:
                    logger.warning("DecisionReader: line %d parse error: %s", lineno, exc)


# ---------------------------------------------------------------------------
# Helpers used by strategy.py to build TickerDecision records
# ---------------------------------------------------------------------------


def build_ticker_decision(
    ticker: str,
    signal_traces: list[SignalTrace],
    raw_composite: float,
    basket_mean: float,
    conviction: str,
    conviction_score: float,
    proposal: str,
    filters_applied: list[str],
    final_action: str,
    filter_reason: str = "",
) -> TickerDecision:
    """Convenience constructor — computes demeaned_composite automatically."""
    return TickerDecision(
        ticker=ticker,
        signal_traces=signal_traces,
        raw_composite=raw_composite,
        basket_mean=basket_mean,
        demeaned_composite=raw_composite - basket_mean,
        conviction=conviction,
        conviction_score=conviction_score,
        proposal=proposal,
        filters_applied=filters_applied,
        final_action=final_action,
        filter_reason=filter_reason,
    )
