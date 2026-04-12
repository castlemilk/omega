"""
omega.nodes.victoria.trade_reinforcement
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
TradeReinforcer — EMA-based per-signal reinforcement learning from closed trades.

## Concept

At each trade close, we know which signals were present at entry and whether the
trade was profitable. Signals that were "aligned" with the outcome (bullish signal
on a winning long, bearish signal on a winning short) get positive reinforcement;
signals that were opposed get negative reinforcement.

EMA (alpha=0.1) accumulates a reinforcement score per signal name. Once 5+ trades
have been observed, scores are converted to multipliers applied to signal values
in signal_generation.py BEFORE composite computation.

## Alignment definition

For a trade with realized PnL p and direction side:
  aligned_direction = +1 if side=="long" else -1   (expected signal sign)
  For each signal s with value v at entry:
    alignment = +1 if sign(v) == aligned_direction, else -1
    outcome   = +1 if p > 0 (winner), else -1
    reinforcement_delta = alignment × outcome  ∈ {-1, +1}

EMA update: score = alpha × delta + (1 - alpha) × score

## Score → multiplier mapping

  score ∈ [-1, +1], clamped at clip boundaries.
  multiplier = 1.0 + score × 0.5  →  range [0.5, 1.5]
  Then clamped to [0.2, 1.5].

  Positive score → multiplier > 1 (amplify signal)
  Negative score → multiplier < 1 (dampen signal)

## Persistence

State persists to `data/reinforcement_state.json`:
{
  "updated_at": "...",
  "n_trades": 42,
  "scores": {"sma_crossover": 0.12, "rsi_signal": -0.07, ...}
}

## Usage

    from omega.nodes.victoria.trade_reinforcement import TradeReinforcer

    reinforcer = TradeReinforcer()
    reinforcer.load()

    # After signal generation for a ticker (before strategy):
    reinforcer.snapshot(ticker, per_ticker_signal_dict)

    # After trade close:
    reinforcer.on_trade_close(ticker, pnl=12.50, side="short")

    # Before composite computation (in signal_generation.py):
    adjustments = reinforcer.get_weight_adjustments()
    for sig_name, mult in adjustments.items():
        if sig_name in ts:
            ts[sig_name] = ts[sig_name] * mult

    # End of run:
    reinforcer.persist()
"""

from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("omega.victoria.trade_reinforcement")

_DEFAULT_PATH = "data/reinforcement_state.json"
_EMA_ALPHA = 0.1
_MIN_TRADES = 5           # trades before adjustments activate
_MULT_SCALE = 0.5         # score * scale → offset from 1.0
_MULT_FLOOR = 0.2
_MULT_CEIL = 1.5

# Signal names eligible for reinforcement (must be numeric scalars in [-1, 1])
_REINFORCEABLE_SIGNALS = {
    "sma_crossover",
    "rsi_signal",
    "macd_crossover",
    "zscore_signal",
    "volume_signal",
    "bb_signal",
    "vol_regime_signal",
    "btc_beta_signal",
    "funding_rate_signal",
    "fear_greed_signal",
    "dxy_signal",
    "vix_signal",
    "yield_curve_signal",
    # Microstructure (Phase 1)
    "order_book_imbalance_signal",
    "trade_flow_signal",
    "spread_zscore_signal",
    "volume_profile_signal",
    "tick_momentum_signal",
    # Temporal (Phase 2)
    "momentum_derivative",
    "conviction_trend",
    "agreement_trend",
}


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


class TradeReinforcer:
    """EMA-based per-signal reinforcement from closed trade outcomes.

    Thread-safety: not thread-safe; all calls should happen from the training loop.
    """

    def __init__(self, path: str = _DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._scores: dict[str, float] = {}   # signal_name → EMA score ∈ [-1, 1]
        self._n_trades: int = 0
        # Last seen signal snapshots per ticker (keyed by ticker symbol)
        self._snapshots: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------ I/O

    def load(self) -> None:
        """Load persisted reinforcement state. Silent no-op if file absent."""
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            self._scores = raw.get("scores", {})
            self._n_trades = int(raw.get("n_trades", 0))
            logger.info(
                "TradeReinforcer: loaded %d signal scores, n_trades=%d from %s",
                len(self._scores),
                self._n_trades,
                self._path,
            )
        except Exception as exc:
            logger.warning("TradeReinforcer: failed to load state: %s", exc)

    def persist(self) -> None:
        """Write reinforcement state to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "updated_at": datetime.now(UTC).isoformat(),
                "n_trades": self._n_trades,
                "scores": {k: round(v, 6) for k, v in self._scores.items()},
            }
            self._path.write_text(json.dumps(payload, indent=2))
        except Exception as exc:
            logger.warning("TradeReinforcer: failed to persist: %s", exc)

    # ------------------------------------------------------------------ snapshot

    def snapshot(self, ticker: str, signals: dict[str, Any]) -> None:
        """Record the current signal dict for a ticker.

        Called from signal_generation.py after computing per-ticker signals.
        These are retrieved at trade close to compute signal alignment.
        """
        self._snapshots[ticker] = {
            k: float(v)
            for k, v in signals.items()
            if k in _REINFORCEABLE_SIGNALS and isinstance(v, (int, float))
            and not math.isnan(float(v)) and not math.isinf(float(v))
        }

    # ------------------------------------------------------------------ on_trade_close

    def on_trade_close(self, ticker: str, pnl: float, side: str) -> None:
        """Update EMA reinforcement scores from a closed trade.

        Args:
            ticker:  Symbol (e.g. "ETHUSDT").
            pnl:     Realized PnL in USD. Positive = win, negative = loss.
            side:    "long" or "short".
        """
        entry_signals = self._snapshots.get(ticker)
        if not entry_signals:
            logger.debug("TradeReinforcer: no snapshot for %s — skipping", ticker)
            return

        # Expected signal direction for this side: long wants positive signals, short wants negative
        expected_dir = 1 if side == "long" else -1
        outcome = 1 if pnl > 0 else -1

        updated = 0
        for sig_name, sig_val in entry_signals.items():
            alignment = 1 if _sign(sig_val) == expected_dir else -1
            delta = float(alignment * outcome)  # ∈ {-1.0, +1.0}

            prior = self._scores.get(sig_name, 0.0)
            self._scores[sig_name] = _EMA_ALPHA * delta + (1 - _EMA_ALPHA) * prior
            updated += 1

        self._n_trades += 1
        logger.debug(
            "TradeReinforcer: trade close %s %s pnl=%.2f — updated %d signal scores (n=%d)",
            ticker,
            side,
            pnl,
            updated,
            self._n_trades,
        )

        if self._n_trades % 10 == 0:
            self.persist()
            self._log_top_adjustments()

    # ------------------------------------------------------------------ get_weight_adjustments

    def get_weight_adjustments(self) -> dict[str, float]:
        """Return per-signal multipliers based on reinforcement scores.

        Returns empty dict until MIN_TRADES observations are available.
        Multiplier = 1.0 + score × MULT_SCALE, clamped to [MULT_FLOOR, MULT_CEIL].
        """
        if self._n_trades < _MIN_TRADES:
            return {}

        adjustments: dict[str, float] = {}
        for sig_name, score in self._scores.items():
            mult = 1.0 + score * _MULT_SCALE
            mult = max(_MULT_FLOOR, min(_MULT_CEIL, mult))
            adjustments[sig_name] = mult

        return adjustments

    # ------------------------------------------------------------------ introspection

    def summary(self) -> dict[str, Any]:
        """Return a summary dict suitable for logging / monitoring."""
        adjustments = self.get_weight_adjustments()
        return {
            "n_trades": self._n_trades,
            "active": self._n_trades >= _MIN_TRADES,
            "n_signals_scored": len(self._scores),
            "adjustments": {k: round(v, 3) for k, v in adjustments.items()},
        }

    def _log_top_adjustments(self) -> None:
        adjs = self.get_weight_adjustments()
        if not adjs:
            return
        top = sorted(adjs.items(), key=lambda x: abs(x[1] - 1.0), reverse=True)[:5]
        logger.info(
            "TradeReinforcer top adjustments (n=%d): %s",
            self._n_trades,
            ", ".join(f"{k}={v:.3f}" for k, v in top),
        )
