"""
omega/nodes/victoria/meta_learner.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Phase 2 (V144): Meta-Learning Layer

Tracks rolling 20-trade profit factor per regime and per signal family IC,
then adjusts confidence surface temperatures (T) and centers (μ) without
requiring an LLM call.

Learning rules (adaptive-engine-v2.md §3):
  regime_PF > 1.5  →  T -= 0.01  (sharpen: system is well-calibrated here)
  regime_PF < 0.8  →  T += 0.02  (soften: system is miscalibrated here)
  T bounded ∈ [0.05, 0.30]
  μ adjusts via EMA toward the mean entry-value of winning trades.

State is persisted to data/meta_learner_state.json across cycles and runs,
matching the pattern of reinforcement_state.json.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omega.nodes.victoria.confidence_surface import SurfaceConfig

logger = logging.getLogger(__name__)

_DEFAULT_STATE_FILE = Path("data/meta_learner_state.json")

ROLLING_WINDOW = 20  # trades per regime buffer

T_MIN: float = 0.05
T_MAX: float = 0.30
T_SHARPEN: float = 0.01  # delta when PF > PF_HIGH
T_SOFTEN: float = 0.02  # delta when PF < PF_LOW
PF_HIGH: float = 1.5
PF_LOW: float = 0.8
CENTER_ALPHA: float = 0.05  # EMA weight for center adjustment toward winners

SIGNAL_FAMILIES = [
    "momentum",
    "mean_reversion",
    "microstructure",
    "macro",
    "sentiment",
    "geometry",
]

# Maps (regime, side) → which surface dimension to adjust
_REGIME_SIDE_SURFACE = {
    ("crisis", "long"): "bear_long",
    ("crisis", "short"): "bear_short",
    ("high_vol", "long"): "bear_long",
    ("high_vol", "short"): "bear_short",
    ("normal", "long"): "composite_long",
    ("normal", "short"): "composite_short",
    ("trending", "long"): "composite_long",
    ("trending", "short"): "composite_short",
}


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass
class _TradeEntry:
    pnl: float
    side: str
    entry_confidence: float
    entry_value: float  # bear_prob for crisis, composite magnitude for normal


@dataclass
class _RegimeBuffer:
    """Rolling window of at most ROLLING_WINDOW trades for one regime."""

    trades: list[dict] = field(default_factory=list)

    def push(self, entry: _TradeEntry) -> None:
        self.trades.append(
            {
                "pnl": entry.pnl,
                "side": entry.side,
                "entry_confidence": entry.entry_confidence,
                "entry_value": entry.entry_value,
            }
        )
        if len(self.trades) > ROLLING_WINDOW:
            self.trades.pop(0)

    def profit_factor(self) -> float | None:
        """Return rolling PF, or None if fewer than 5 trades."""
        if len(self.trades) < 5:
            return None
        wins = [t["pnl"] for t in self.trades if t["pnl"] > 0]
        losses = [abs(t["pnl"]) for t in self.trades if t["pnl"] < 0]
        if not losses:
            return 9.99 if wins else None
        return sum(wins) / sum(losses) if wins else 0.0

    def mean_entry_value_winners(self) -> float | None:
        winners = [t["entry_value"] for t in self.trades if t["pnl"] > 0]
        return sum(winners) / len(winners) if winners else None

    def to_dict(self) -> dict:
        return {"trades": self.trades, "pf": self.profit_factor()}

    @classmethod
    def from_dict(cls, d: dict) -> _RegimeBuffer:
        buf = cls()
        buf.trades = d.get("trades", [])
        # trim to window in case saved state had a different window size
        buf.trades = buf.trades[-ROLLING_WINDOW:]
        return buf


@dataclass
class _SurfaceState:
    """Learned T and center for one confidence surface dimension."""

    center: float
    temperature: float
    initial_center: float
    initial_temperature: float
    n_adjustments: int = 0

    def to_dict(self) -> dict:
        return {
            "center": round(self.center, 6),
            "temperature": round(self.temperature, 6),
            "initial_center": self.initial_center,
            "initial_temperature": self.initial_temperature,
            "n_adjustments": self.n_adjustments,
        }

    @classmethod
    def from_dict(cls, d: dict, defaults: _SurfaceState) -> _SurfaceState:
        return cls(
            center=d.get("center", defaults.center),
            temperature=d.get("temperature", defaults.temperature),
            initial_center=d.get("initial_center", defaults.initial_center),
            initial_temperature=d.get("initial_temperature", defaults.initial_temperature),
            n_adjustments=d.get("n_adjustments", 0),
        )


# ---------------------------------------------------------------------------
# MetaLearner
# ---------------------------------------------------------------------------


class MetaLearner:
    """
    Adaptive parameter learner for the confidence surface (Phase 2 / V144).

    Usage in strategy.py::

        # Initialise once:
        self._meta_learner = MetaLearner()

        # Before each cycle's surface evaluation:
        if self._meta_learner:
            cfg = self._meta_learner.get_surface_config()
            surface = ConfidenceSurface(cfg)

    Usage in run_training.py after new_closed flush::

        if strat._meta_learner:
            for t in new_closed:
                strat._meta_learner.record_trade(
                    pnl=float(t.get("pnl", 0)),
                    side=t.get("side", "long"),
                    regime=regime,
                )
            if cycle_num % 50 == 0:
                strat._meta_learner.save_state()
    """

    def __init__(self, state_file: Path = _DEFAULT_STATE_FILE) -> None:
        self.state_file = Path(state_file)
        self._regime_buffers: dict[str, _RegimeBuffer] = {
            "crisis": _RegimeBuffer(),
            "high_vol": _RegimeBuffer(),
            "normal": _RegimeBuffer(),
            "trending": _RegimeBuffer(),
        }
        self._signal_ic: dict[str, float] = {f: 0.0 for f in SIGNAL_FAMILIES}
        self._surfaces: dict[str, _SurfaceState] = self._default_surfaces()
        self._load_state()

    # ── Defaults ──────────────────────────────────────────────────────────

    def _default_surfaces(self) -> dict[str, _SurfaceState]:
        # Mirror SurfaceConfig defaults from confidence_surface.py
        return {
            "bear_long": _SurfaceState(0.35, 0.12, 0.35, 0.12),
            "bear_short": _SurfaceState(0.35, 0.12, 0.35, 0.12),
            "composite_long": _SurfaceState(0.08, 0.04, 0.08, 0.04),
            "composite_short": _SurfaceState(0.05, 0.03, 0.05, 0.03),
        }

    # ── Persistence ───────────────────────────────────────────────────────

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            raw = json.loads(self.state_file.read_text())
            for name, d in raw.get("surfaces", {}).items():
                if name in self._surfaces:
                    self._surfaces[name] = _SurfaceState.from_dict(d, self._surfaces[name])
            for regime, d in raw.get("regime_buffers", {}).items():
                if regime in self._regime_buffers:
                    self._regime_buffers[regime] = _RegimeBuffer.from_dict(d)
            for family, ic in raw.get("signal_ic", {}).items():
                if family in self._signal_ic:
                    self._signal_ic[family] = float(ic)
            logger.debug("meta_learner: state loaded from %s", self.state_file)
        except Exception as exc:
            logger.warning("meta_learner: could not load state: %s", exc)

    def save_state(self) -> None:
        payload = {
            "version": 2,
            "updated_at": datetime.now(UTC).isoformat(),
            "surfaces": {name: s.to_dict() for name, s in self._surfaces.items()},
            "regime_buffers": {r: b.to_dict() for r, b in self._regime_buffers.items()},
            "signal_ic": {f: round(ic, 6) for f, ic in self._signal_ic.items()},
        }
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(payload, indent=2, default=str))
        except Exception as exc:
            logger.warning("meta_learner: could not save state: %s", exc)

    # ── Core update ───────────────────────────────────────────────────────

    def record_trade(
        self,
        pnl: float,
        side: str,
        regime: str,
        entry_confidence: float = 0.5,
        entry_value: float = 0.0,
        signal_contribs: dict[str, float] | None = None,
    ) -> None:
        """
        Record a closed trade and apply the learning rule.

        Parameters
        ----------
        pnl               : Realised PnL in USD.
        side              : "long" or "short".
        regime            : Regime label at trade open ("crisis", "high_vol", "normal").
        entry_confidence  : Surface confidence at entry (0–1). Defaults to 0.5.
        entry_value       : Primary surface input (bear_prob for crisis trades,
                            |composite| for normal trades). Used for center adjustment.
        signal_contribs   : Optional {family: weight} for signal IC tracking.
        """
        regime_key = regime if regime in self._regime_buffers else "normal"
        side_key = side.lower()

        entry = _TradeEntry(
            pnl=pnl,
            side=side_key,
            entry_confidence=max(0.0, min(1.0, entry_confidence)),
            entry_value=entry_value,
        )
        self._regime_buffers[regime_key].push(entry)

        if signal_contribs:
            self._update_signal_ic(signal_contribs, pnl > 0)

        self._apply_learning_rule(regime_key, side_key)

    def _apply_learning_rule(self, regime: str, side: str) -> None:
        surface_key = _REGIME_SIDE_SURFACE.get((regime, side))
        if not surface_key:
            return

        buf = self._regime_buffers[regime]
        pf = buf.profit_factor()
        if pf is None:
            return

        surf = self._surfaces[surface_key]

        # Temperature adjustment
        old_temp = surf.temperature
        if pf > PF_HIGH:
            surf.temperature = max(T_MIN, surf.temperature - T_SHARPEN)
        elif pf < PF_LOW:
            surf.temperature = min(T_MAX, surf.temperature + T_SOFTEN)

        if surf.temperature != old_temp:
            surf.n_adjustments += 1
            logger.debug(
                "meta_learner [%s]: T %.4f→%.4f  (regime=%s side=%s PF=%.2f n=%d)",
                surface_key,
                old_temp,
                surf.temperature,
                regime,
                side,
                pf,
                surf.n_adjustments,
            )

        # Center adjustment: EMA toward mean entry_value of winners
        win_val = buf.mean_entry_value_winners()
        if win_val is not None and 0.0 < abs(win_val) < 1.0:
            surf.center = (1.0 - CENTER_ALPHA) * surf.center + CENTER_ALPHA * win_val
            surf.center = max(0.01, min(0.95, surf.center))

    # ── Signal IC ─────────────────────────────────────────────────────────

    def _update_signal_ic(self, contribs: dict[str, float], was_win: bool) -> None:
        outcome = 1.0 if was_win else -1.0
        for family, weight in contribs.items():
            if family not in self._signal_ic:
                continue
            signal = 1.0 if weight > 0 else (-1.0 if weight < 0 else 0.0)
            ic_sample = signal * outcome
            self._signal_ic[family] = 0.95 * self._signal_ic[family] + 0.05 * ic_sample

    # ── Outputs ───────────────────────────────────────────────────────────

    def get_surface_config(self) -> SurfaceConfig:
        """
        Return a SurfaceConfig populated with current learned parameters.

        Lazy import to avoid circular dependency at module load time.
        """
        from omega.nodes.victoria.confidence_surface import (
            SurfaceConfig,
            SurfaceParams,
        )

        defaults = SurfaceConfig()
        return SurfaceConfig(
            bear_long=SurfaceParams(
                center=self._surfaces["bear_long"].center,
                temperature=self._surfaces["bear_long"].temperature,
            ),
            bear_short=SurfaceParams(
                center=self._surfaces["bear_short"].center,
                temperature=self._surfaces["bear_short"].temperature,
            ),
            composite_long=SurfaceParams(
                center=self._surfaces["composite_long"].center,
                temperature=self._surfaces["composite_long"].temperature,
            ),
            composite_short=SurfaceParams(
                center=self._surfaces["composite_short"].center,
                temperature=self._surfaces["composite_short"].temperature,
            ),
            regime_weights=defaults.regime_weights,
            min_confidence=defaults.min_confidence,
        )

    def get_signal_family_emphasis(self) -> dict[str, float]:
        """
        Return per-family multipliers for signal weighting.
        High IC → emphasis > 1.0; low/negative IC → < 1.0.
        Range: [0.5, 1.5].
        """
        return {family: max(0.5, min(1.5, 1.0 + ic)) for family, ic in self._signal_ic.items()}

    def summary(self) -> dict:
        return {
            "surfaces": {
                name: {
                    "center": round(s.center, 4),
                    "T": round(s.temperature, 4),
                    "n_adj": s.n_adjustments,
                }
                for name, s in self._surfaces.items()
            },
            "regime_pf": {
                r: round(pf, 3) if (pf := b.profit_factor()) is not None else None
                for r, b in self._regime_buffers.items()
            },
            "signal_ic": {k: round(v, 4) for k, v in self._signal_ic.items()},
        }

    def reset(self) -> None:
        """Reset all learned parameters to defaults (useful for testing)."""
        self._regime_buffers = {
            "crisis": _RegimeBuffer(),
            "high_vol": _RegimeBuffer(),
            "normal": _RegimeBuffer(),
            "trending": _RegimeBuffer(),
        }
        self._signal_ic = {f: 0.0 for f in SIGNAL_FAMILIES}
        self._surfaces = self._default_surfaces()
