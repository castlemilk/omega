"""
omega.nodes.victoria.providers.replay
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ReplayIngestionNode — drop-in replacement for DataIngestionNode that serves
OHLCV data from a frozen versioned snapshot instead of calling live APIs.

Usage (injected by run_training.py when --backtest-snapshot is set):

    victoria = VictoriaNode()
    snap = load_snapshot("data/snapshots/snap_20260414.json")
    victoria._ingestion = ReplayIngestionNode(snap)

Each call to execute() advances an internal cursor by one bar, returning a
windowed slice of the frozen series.  This simulates what DataIngestionNode
would have returned at each historical time-step.

WS signals (microstructure, whale_prints) are not present in snapshots and
will degrade to 0.0 via the standard feature-flag paths in SignalGenerationNode
(ws_microstructure=False / whale_prints=False in backtest mode).

Snapshot format (written by scripts/freeze_snapshot.py):

    {
      "_snapshot_id": "snap_20260414",
      "_created_at": 1744636800,
      "_date_range": ["2026-01-14", "2026-04-14"],
      "_symbols": ["ETHUSDT", ...],
      "ETHUSDT": {
        "close":      [float, ...],   // 90 values, oldest first
        "open":       [float, ...],
        "high":       [float, ...],
        "low":        [float, ...],
        "volume":     [float, ...],
        "timestamps": [int, ...],     // unix seconds
        "meta": {"symbol": "ETHUSDT", ...}
      },
      "_macro": {
        "funding_rates": {"ETHUSDT": 0.00012, ...},
        "fear_greed": 45,
        "btc_dominance": 0.523
      }
    }
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from omega.core.node import NodeInput, NodeOutput

logger = logging.getLogger("omega.nodes.victoria.providers.replay")

# Minimum window the signal pipeline needs to warm up.
_MIN_WINDOW = 30


def load_snapshot(path: str | Path) -> dict[str, Any]:
    """Load a frozen snapshot from disk. Raises if path doesn't exist."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Backtest snapshot not found: {p}")
    data = json.loads(p.read_text())
    sid = data.get("_snapshot_id", str(p.stem))
    logger.info("Loaded snapshot %s (%s → %s, %d symbols)",
                sid,
                data.get("_date_range", ["?", "?"])[0],
                data.get("_date_range", ["?", "?"])[-1],
                len(data.get("_symbols", [])))
    return data


class ReplayIngestionNode:
    """
    Duck-typed replacement for DataIngestionNode.

    Maintains an internal cursor that advances by one bar per execute() call,
    returning a rolling window of the frozen OHLCV series.  The cursor starts
    at `window` so the first call returns candles[0:window], giving signal
    indicators their full warm-up history from the first cycle.

    Parameters
    ----------
    snapshot : dict
        Parsed snapshot from load_snapshot().
    window : int
        Number of historical bars to return per call (default 30).
    """

    def __init__(self, snapshot: dict[str, Any], window: int = _MIN_WINDOW) -> None:
        if window < _MIN_WINDOW:
            raise ValueError(f"window must be >= {_MIN_WINDOW} (got {window})")

        self._snapshot = snapshot
        self._window = window
        self._snapshot_id = snapshot.get("_snapshot_id", "unknown")

        # Identify data symbols (skip metadata keys)
        self._symbols = [
            k for k in snapshot
            if not k.startswith("_") and isinstance(snapshot[k], dict)
        ]

        # Series length — use shortest series across symbols
        self._series_len = min(
            len(snapshot[sym].get("close", []))
            for sym in self._symbols
        )
        if self._series_len < window + 1:
            raise ValueError(
                f"Snapshot {self._snapshot_id} has only {self._series_len} bars "
                f"(need >= {window + 1})"
            )

        # Cursor starts at `window` — first call returns candles[0:window]
        self._cursor: int = window
        self._total_steps: int = self._series_len - window

        logger.info(
            "ReplayIngestionNode: snapshot=%s  symbols=%d  series=%d  window=%d  steps=%d",
            self._snapshot_id, len(self._symbols), self._series_len,
            window, self._total_steps,
        )

    # ------------------------------------------------------------------
    # DataIngestionNode interface
    # ------------------------------------------------------------------

    def execute(self, inp: NodeInput) -> NodeOutput:
        """
        Return a windowed slice of the frozen series at the current cursor.

        Advances cursor by one after each call.  When the end of the series
        is reached, wraps back to `window` (loops) so training runs of any
        length are supported.
        """
        start = max(0, self._cursor - self._window)
        end = self._cursor

        sliced: dict[str, Any] = {}
        for sym in self._symbols:
            sym_data = self._snapshot[sym]
            s: dict[str, Any] = {}
            for key, val in sym_data.items():
                s[key] = val[start:end] if isinstance(val, list) else val

            # Keep meta dict and update regularMarketPrice to last close in window
            meta = dict(sym_data.get("meta", {"symbol": sym}))
            closes = s.get("close", [])
            if closes:
                meta["regularMarketPrice"] = closes[-1]
            s["meta"] = meta
            sliced[sym] = s

        # Advance cursor, wrapping at series end
        self._cursor += 1
        if self._cursor > self._series_len:
            logger.debug("ReplayIngestionNode: series end reached, wrapping cursor to %d", self._window)
            self._cursor = self._window

        return NodeOutput(success=True, result=sliced)

    def _data_freshness_minutes(self) -> float:
        """Always fresh — data is from a frozen snapshot."""
        return 0.0

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def progress_pct(self) -> float:
        """How far through the snapshot we are (0.0–1.0)."""
        if self._total_steps <= 0:
            return 1.0
        return (self._cursor - self._window) / self._total_steps
