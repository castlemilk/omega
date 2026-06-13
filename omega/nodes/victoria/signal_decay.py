"""
omega.nodes.victoria.signal_decay
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
SignalDecayDetector — tracks rolling Information Coefficient (IC) per signal and
warns when a signal's predictive power is decaying or has inverted.

## What is IC?

IC (Information Coefficient) is the Pearson correlation between a signal's value at
trade entry and the realized forward return of that trade. IC=1.0 is a perfect
predictor; IC=0.0 is pure noise; IC=-1.0 is perfectly anti-predictive.

Industry thresholds (from Grinold & Kahn, Active Portfolio Management):
  IC > 0.05: useful signal, worth keeping
  0.0 < IC < 0.05: weak signal, borderline
  IC < 0.0: anti-predictive (betting against the signal would be better)

## How IC is computed here

At each trade close, the caller passes:
  - signals: dict of signal_name → value at entry (or entry-cycle proxy)
  - forward_return: (exit_price - entry_price) / entry_price for longs,
                   (entry_price - exit_price) / entry_price for shorts

These pairs accumulate in a rolling window of the last 20 observations per signal.
Once 5+ observations are available, IC is computed as Pearson r(signal, forward_return).

## IC history

Persisted to `data/signal_ic_history.json`. Structure:
{
  "updated_at": "2026-04-07T10:00:00+00:00",
  "signals": {
    "sma_crossover": {
      "ic": 0.12,
      "n_obs": 18,
      "status": "active",
      "obs": [[signal_val, forward_return], ...]
    },
    "rsi_signal": {
      "ic": 0.04,
      "n_obs": 20,
      "status": "decaying",
      ...
    }
  }
}

## Statuses

  "active":         IC >= 0.05 (signal is contributing)
  "weak":           0.0 <= IC < 0.05 (borderline, watch)
  "decaying":       IC < 0.05 (below useful threshold) [warning logged]
  "anti-predictive":IC < -0.05 (signal predicts wrong direction) [warning logged]
  "insufficient":   fewer than MIN_OBS observations (no verdict yet)

## Usage in the training loop

    from omega.nodes.victoria.signal_decay import SignalDecayDetector
    detector = SignalDecayDetector()
    detector.load()  # load prior history

    # At each trade close:
    forward_return = compute_forward_return(trade)
    detector.update(signals_at_entry, forward_return)

    # Periodically check for warnings:
    detector.log_warnings()
    detector.persist()
"""

import json
import logging
import math
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("omega.nodes.victoria.signal_decay")

_DEFAULT_PATH = "data/signal_ic_history.json"
_WINDOW = 20  # rolling window size
_MIN_OBS = 5  # minimum observations before reporting IC
_ACTIVE_THRESHOLD = 0.05
_ANTI_PRED_THRESHOLD = -0.05

# Signal keys to track (must end in _signal or be sma_crossover/macd_crossover/etc.)
_TRACKED_SIGNALS = {
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
}


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation of two equal-length sequences. None if insufficient variance."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    var_x = sum((x - mx) ** 2 for x in xs)
    var_y = sum((y - my) ** 2 for y in ys)
    denom = math.sqrt(var_x * var_y)
    if denom == 0.0:
        return None
    return num / denom


class _SignalRecord:
    """Rolling observation buffer for a single signal."""

    __slots__ = ("name", "obs")

    def __init__(self, name: str, obs: list[tuple[float, float]] | None = None) -> None:
        self.name = name
        self.obs: deque[tuple[float, float]] = deque(obs or [], maxlen=_WINDOW)

    def add(self, signal_val: float, forward_return: float) -> None:
        self.obs.append((signal_val, forward_return))

    def ic(self) -> float | None:
        if len(self.obs) < _MIN_OBS:
            return None
        xs = [o[0] for o in self.obs]
        ys = [o[1] for o in self.obs]
        return _pearson(xs, ys)

    def status(self) -> str:
        ic = self.ic()
        if ic is None:
            return "insufficient"
        if ic < _ANTI_PRED_THRESHOLD:
            return "anti-predictive"
        if ic < 0.0:
            return "decaying"
        if ic < _ACTIVE_THRESHOLD:
            return "weak"
        return "active"

    def to_dict(self) -> dict[str, Any]:
        ic = self.ic()
        return {
            "ic": round(ic, 4) if ic is not None else None,
            "n_obs": len(self.obs),
            "status": self.status(),
            "obs": [[round(s, 6), round(r, 6)] for s, r in self.obs],
        }

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any]) -> "_SignalRecord":
        obs = [tuple(pair) for pair in d.get("obs", [])]
        return cls(name, obs)


class SignalDecayDetector:
    """
    Tracks rolling IC per signal and warns when predictive power decays.

    Typical usage in the training loop:

        detector = SignalDecayDetector()
        detector.load()

        # inside per-trade close loop:
        fwd = (exit_price - entry_price) / entry_price  # long
        detector.update(current_signals_dict, fwd)
        detector.log_warnings()

        # end of run:
        detector.persist()
    """

    def __init__(self, path: str = _DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._records: dict[str, _SignalRecord] = {}

    # ------------------------------------------------------------------ I/O

    def load(self) -> None:
        """Load prior IC history from disk. Silent no-op if file absent."""
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            for name, d in raw.get("signals", {}).items():
                self._records[name] = _SignalRecord.from_dict(name, d)
            logger.debug(
                "SignalDecayDetector: loaded %d signal records from %s",
                len(self._records),
                self._path,
            )
        except Exception as exc:
            logger.warning("SignalDecayDetector: failed to load history: %s", exc)

    def persist(self) -> None:
        """Write IC history to disk.

        V222: read-modify-write — unknown top-level keys (the committed
        seeded_pooled_ics / seeded_regime_ics / seed_provenance seed tables)
        are preserved, not wiped. This detector owns only `updated_at` and
        `signals`.
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {}
            if self._path.exists():
                try:
                    existing = json.loads(self._path.read_text())
                    if isinstance(existing, dict):
                        payload = existing
                except Exception:
                    payload = {}
            payload["updated_at"] = datetime.now(UTC).isoformat()
            payload["signals"] = {name: rec.to_dict() for name, rec in self._records.items()}
            self._path.write_text(json.dumps(payload, indent=2))
        except Exception as exc:
            logger.warning("SignalDecayDetector: failed to persist: %s", exc)

    # ------------------------------------------------------------------ update

    def update(
        self,
        signals: dict[str, Any],
        forward_return: float,
        symbol: str = "",
        side: str = "",
    ) -> None:
        """
        Record one observation for every tracked signal present in *signals*.

        Args:
            signals: Per-ticker signal dict (e.g. last_signals.get(symbol)).
                     Only keys in _TRACKED_SIGNALS are recorded.
            forward_return: Signed return of the trade (positive = profit direction).
                     For longs: (exit - entry) / entry.
                     For shorts: (entry - exit) / entry.
            symbol: Ticker (for logging only).
            side: "long" | "short" (for logging only).
        """
        recorded = 0
        for key in _TRACKED_SIGNALS:
            val = signals.get(key)
            if val is None:
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            if key not in self._records:
                self._records[key] = _SignalRecord(key)
            self._records[key].add(fval, forward_return)
            recorded += 1

        if recorded:
            logger.debug(
                "SignalDecayDetector: recorded %d signal obs (symbol=%s side=%s fwd=%.4f)",
                recorded,
                symbol,
                side,
                forward_return,
            )

    # ------------------------------------------------------------------ reporting

    def log_warnings(self) -> list[dict[str, Any]]:
        """
        Log warnings for signals whose IC has fallen below thresholds.

        Returns a list of warning dicts (empty if no warnings).
        """
        warnings: list[dict[str, Any]] = []
        for name, rec in self._records.items():
            ic = rec.ic()
            if ic is None:
                continue
            status = rec.status()
            if status == "anti-predictive":
                logger.warning(
                    "SignalDecay [ANTI-PREDICTIVE] %s: IC=%.3f (n=%d) — "
                    "signal is systematically wrong; consider disabling",
                    name,
                    ic,
                    len(rec.obs),
                )
                warnings.append(
                    {"signal": name, "ic": ic, "status": status, "n_obs": len(rec.obs)}
                )
            elif status == "decaying":
                logger.warning(
                    "SignalDecay [DECAYING] %s: IC=%.3f (n=%d) — below useful threshold (%.2f)",
                    name,
                    ic,
                    len(rec.obs),
                    _ACTIVE_THRESHOLD,
                )
                warnings.append(
                    {"signal": name, "ic": ic, "status": status, "n_obs": len(rec.obs)}
                )
        return warnings

    def summary(self) -> dict[str, Any]:
        """Return a summary dict of all signal ICs, suitable for logging."""
        out: dict[str, Any] = {}
        for name, rec in self._records.items():
            ic = rec.ic()
            out[name] = {
                "ic": round(ic, 4) if ic is not None else None,
                "n": len(rec.obs),
                "status": rec.status(),
            }
        return out

    def ic_for(self, signal_name: str) -> float | None:
        """Return current IC for a specific signal, or None if insufficient data."""
        rec = self._records.get(signal_name)
        return rec.ic() if rec is not None else None

    def all_statuses(self) -> dict[str, str]:
        """Return {signal_name: status} for all tracked signals with enough data."""
        return {name: rec.status() for name, rec in self._records.items() if rec.ic() is not None}
