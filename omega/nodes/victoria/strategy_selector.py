"""omega/nodes/victoria/strategy_selector.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Regime-adaptive strategy mode selector (V156).

The manifold analysis (docs/research/manifold-v153.md) proved that a single
parameter set cannot win across all regime snapshots: the crisis protection
flags that make V141+ work in bear markets actively destroy performance in
bull/trend markets. This module solves that by switching between three
SPECIALISED strategy modes based on what regime the market is actually in.

Architecture
------------
Three modes, each with a dict of feature overrides applied on top of the
base VictoriaFeatures config every cycle:

  TREND   — sustained bull_prob > threshold for trend_window cycles.
             Disables the crisis protections that fight uptrends:
             regime_hysteresis, high_vol_entry_block, bear_prob_long_block,
             llm_crisis_mode, tight trailing stops, early-exit cycles.

  CRISIS  — sustained bear_prob > threshold for crisis_window cycles.
             Activates the full crisis alpha stack from V141:
             aggressive long block, tight hysteresis, LLM crisis veto,
             signal dampening, exit asymmetry.

  DEFAULT — neither condition met. Uses the base config unchanged.

Transitions
-----------
Hysteresis prevents oscillation:
  - Enter TREND: bull_prob >= trend_bull_threshold for `trend_window` consecutive cycles.
  - Exit TREND:  bull_prob < trend_bull_threshold for `trend_exit_window` consecutive cycles.
  - Enter CRISIS: bear_prob >= crisis_bear_threshold for `crisis_window` consecutive cycles.
  - Exit CRISIS:  bear_prob < crisis_bear_threshold for `crisis_exit_window` consecutive cycles.
  - CRISIS takes priority over TREND when both conditions would fire.

Usage
-----
The selector is instantiated in StrategyNode.__init__ when
`features.strategy_selector_enabled` is True.

Each cycle, call:
    selector.update(signals, features)

This mutates `features` in-place with the mode-appropriate overrides.
Callers see `selector.mode` for the current StrategyMode.
"""
from __future__ import annotations

import logging
from collections import deque
from enum import Enum
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from omega.nodes.victoria.features import VictoriaFeatures

logger = logging.getLogger("omega.victoria.strategy_selector")


class StrategyMode(Enum):
    DEFAULT = "DEFAULT"
    TREND = "TREND"
    CRISIS = "CRISIS"


# ---------------------------------------------------------------------------
# Mode override dicts
# Each entry is (field_name, value_in_this_mode).
# Only fields that DIFFER from the base v153_trend_only config are listed.
# The selector restores the base value when leaving a mode.
# ---------------------------------------------------------------------------

# TREND mode: remove crisis protections that block profitable trend entries.
# Root causes confirmed by V142 forensics + manifold analysis:
#   1. regime_hysteresis locked crisis label into early Q4-2023 bull volatility
#   2. high_vol_entry_block killed all entries in volatile early bull market
#   3. bear_prob_long_block_threshold=0.55 fires on brief bear_prob spikes in uptrends
#   4. llm_crisis_mode vetoes bull-market longs via crisis preamble
#   5. long_trail_multiplier=0.5 cuts winners too early in sustained trends
#   6. zero_mfe_early_exit_cycles=2 exits positions before trend develops
_TREND_OVERRIDES: dict[str, Any] = {
    "regime_hysteresis_enabled": False,       # don't lock crisis label
    "high_vol_entry_block": False,             # allow entries in volatile bull
    "bear_prob_long_block_threshold": 0.80,   # only block in confirmed bear
    "llm_crisis_mode_enabled": False,          # don't veto trend longs
    "long_trail_multiplier": 1.5,             # let winners run in trends
    "short_trail_multiplier": 1.0,            # symmetric trailing in bull
    "zero_mfe_early_exit_cycles": 0,          # no early exits in trends
    "fear_greed_crisis_weight": 1.0,          # restore full fear/greed signal
    "sma_crisis_weight": 1.0,                 # restore full SMA signal
    "crisis_long_block": False,               # don't hard-block longs
}

# CRISIS mode: activate the full V141 crisis alpha stack.
# These are the values that V141-V153 added vs V139 baseline — confirmed to
# improve crisis performance without hurting normal regime.
_CRISIS_OVERRIDES: dict[str, Any] = {
    "regime_hysteresis_enabled": True,
    "bear_prob_hysteresis_gate": 0.50,
    "high_vol_entry_block": True,
    "bear_prob_long_block_threshold": 0.55,
    "llm_crisis_mode_enabled": True,
    "long_trail_multiplier": 0.5,
    "short_trail_multiplier": 1.5,
    "zero_mfe_early_exit_cycles": 2,
    "fear_greed_crisis_weight": 0.1,
    "sma_crisis_weight": 0.2,
    "crisis_long_block": True,
}

# DEFAULT mode: restore every field to the base preset value.
# Populated dynamically from the base features in __init__.
_DEFAULT_OVERRIDES: dict[str, Any] = {}


class StrategySelector:
    """Per-cycle regime-adaptive strategy mode switcher.

    Instantiate once in StrategyNode.__init__, then call update() every cycle.
    """

    def __init__(self, features: "VictoriaFeatures") -> None:
        cfg = features

        # Transition windows (from feature flags)
        self._trend_window = int(cfg.strategy_selector_trend_window)
        self._crisis_window = int(cfg.strategy_selector_crisis_window)
        self._trend_exit_window = int(cfg.strategy_selector_trend_exit_window)
        self._crisis_exit_window = int(cfg.strategy_selector_crisis_exit_window)
        self._trend_bull_thresh = float(cfg.strategy_selector_trend_bull_threshold)
        self._crisis_bear_thresh = float(cfg.strategy_selector_crisis_bear_threshold)

        # State
        self._mode: StrategyMode = StrategyMode.DEFAULT
        self._bull_prob_above: int = 0   # consecutive cycles bull_prob >= threshold
        self._bull_prob_below: int = 0   # consecutive cycles bull_prob < threshold (exit counter)
        self._bear_prob_above: int = 0
        self._bear_prob_below: int = 0
        self._cycle: int = 0

        # V162: mode transition blend
        self._blend_enabled = bool(getattr(cfg, "mode_transition_blend", False))
        self._blend_total = max(1, int(getattr(cfg, "blend_cycles", 5)))
        self._blend_remaining: int = 0        # cycles left in active blend
        self._blend_from: StrategyMode | None = None
        self._blend_to: StrategyMode | None = None

        # V160/V161: crisis-label contamination window.
        # Tracks whether any cycle in the last trend_window cycles had a crisis/high_vol
        # regime label.  Two effects when contaminated (V160+V161 dual-duty):
        #   1. TREND entry is vetoed (bull_prob capped below threshold).
        #   2. DEFAULT mode applies CRISIS overrides instead of base values.
        # Rationale: Q4-2023 genuine bull had sustained "normal" labels; 2022 pre-crash
        # "normal" periods were interleaved with "crisis"/"high_vol" labels, and the
        # selector's crisis_window counter kept resetting on every "normal" cycle,
        # leaving DEFAULT mode without crisis protections during the crash.
        self._crisis_label_window: deque = deque(
            [False] * self._trend_window, maxlen=self._trend_window
        )
        self._trend_veto_enabled: bool = getattr(
            cfg, "strategy_selector_trend_crisis_veto", True
        )
        self._crisis_contaminated: bool = False  # updated every cycle in update()

        # Snapshot of base feature values for every field we might override
        # (used to restore DEFAULT on mode exit)
        from dataclasses import asdict
        base = asdict(features)
        self._base_values: dict[str, Any] = {
            k: base[k]
            for k in set(_TREND_OVERRIDES) | set(_CRISIS_OVERRIDES)
            if k in base
        }

        logger.info(
            "StrategySelector: trend_window=%d(%.2f) crisis_window=%d(%.2f)",
            self._trend_window, self._trend_bull_thresh,
            self._crisis_window, self._crisis_bear_thresh,
        )

    @property
    def mode(self) -> StrategyMode:
        return self._mode

    def update(self, signals: dict[str, Any], features: "VictoriaFeatures") -> StrategyMode:
        """Detect regime from signals, update mode, apply overrides to features.

        Called at the start of each cycle before _apply_regime_adaptive_thresholds.
        Mutates features in-place; returns the active mode.
        """
        self._cycle += 1

        bull_prob = float(signals.get("_bull_prob", -1.0))
        bear_prob = float(signals.get("_bear_prob", -1.0))

        # Fall back to label-based detection when probabilities unavailable.
        # V158: "normal" regime is ambiguous — it appears in both bull markets
        # (Q4-2023 trend) and pre-crash periods (2022 H1 calm before crisis).
        # We disambiguate using _basket_breakout: the mean Donchian breakout signal
        # across all tickers.  Positive breakout → prices making new highs → genuine
        # uptrend.  Negative/zero → mean-reversion territory → stay cautious.
        # Only requires breakout_signal_enabled=True (V157+).
        regime_label = str(signals.get("_regime", "")).lower()
        basket_breakout = float(signals.get("_basket_breakout", 0.0))
        basket_mtf = float(signals.get("_basket_mtf_alignment", 0.0))

        # V160: update crisis-label contamination window BEFORE computing bull_prob.
        # Any crisis/high_vol/bear label in the window blocks TREND entry.
        is_crisis_label = regime_label in ("crisis", "high_vol", "bear")
        self._crisis_label_window.append(is_crisis_label)
        crisis_contaminated = self._trend_veto_enabled and any(self._crisis_label_window)

        if bull_prob < 0.0:
            if regime_label in ("bull", "trending"):
                bull_prob = 0.65  # explicit bull label — full credit
            elif regime_label == "normal":
                # V158: only count as bullish when price structure confirms it.
                # breakout > 0.10 means >10% of assets at channel highs on average.
                # MTF > 0 means short and long-term momentum both positive.
                # Either condition alone is partial evidence; both together = 0.65.
                if basket_breakout > 0.10 and basket_mtf > 0.0:
                    bull_prob = 0.65  # trend confirmed by price structure
                elif basket_breakout > 0.10 or basket_mtf > 0.0:
                    bull_prob = 0.40  # partial evidence — warm but below threshold
                else:
                    bull_prob = 0.20  # normal with no trend evidence — stay cautious
            else:
                bull_prob = 0.0

        # V160: veto TREND entry when crisis contamination present in window.
        # Cap bull_prob so it cannot cross trend_bull_threshold (default 0.55).
        # This prevents TREND mode from firing during oscillating crisis/normal periods
        # (e.g. 2022 pre-crash Jan-Feb) while leaving genuine bull markets unaffected.
        if crisis_contaminated:
            bull_prob = min(bull_prob, self._trend_bull_thresh - 0.01)

        if bear_prob < 0.0:
            bear_prob = 0.65 if regime_label in ("bear", "crisis", "high_vol") else 0.0

        # Update rolling counters
        if bull_prob >= self._trend_bull_thresh:
            self._bull_prob_above += 1
            self._bull_prob_below = 0
        else:
            self._bull_prob_below += 1
            self._bull_prob_above = 0

        if bear_prob >= self._crisis_bear_thresh:
            self._bear_prob_above += 1
            self._bear_prob_below = 0
        else:
            self._bear_prob_below += 1
            self._bear_prob_above = 0

        new_mode = self._compute_mode()
        if new_mode != self._mode:
            logger.info(
                "StrategySelector: %s → %s  (cycle=%d  bull_prob=%.2f  bear_prob=%.2f  "
                "bull_above=%d  bear_above=%d  crisis_veto=%s)",
                self._mode.value, new_mode.value, self._cycle,
                bull_prob, bear_prob,
                self._bull_prob_above, self._bear_prob_above,
                crisis_contaminated,
            )
            # V162: start a blend ramp from the old mode to the new one
            if self._blend_enabled:
                self._blend_from = self._mode
                self._blend_to = new_mode
                self._blend_remaining = self._blend_total
            self._mode = new_mode
        elif crisis_contaminated and self._cycle % 50 == 0:
            logger.debug(
                "StrategySelector: TREND veto active (cycle=%d  crisis_window_count=%d/%d)",
                self._cycle, sum(self._crisis_label_window), self._trend_window,
            )

        # V161: store contamination state for _apply_overrides to consume.
        # When contaminated and in DEFAULT mode, apply CRISIS protections
        # (prevents longs from entering during oscillating-regime crash periods).
        self._crisis_contaminated = crisis_contaminated

        self._apply_overrides(features)
        return self._mode

    def _compute_mode(self) -> StrategyMode:
        """Determine target mode based on current counters. CRISIS > TREND > DEFAULT."""
        in_crisis = self._mode == StrategyMode.CRISIS
        in_trend = self._mode == StrategyMode.TREND

        # Crisis entry / stay
        if self._bear_prob_above >= self._crisis_window:
            return StrategyMode.CRISIS
        # Crisis exit: require enough below-threshold cycles
        if in_crisis:
            if self._bear_prob_below < self._crisis_exit_window:
                return StrategyMode.CRISIS  # still in hysteresis exit window
            # Fallen through: exiting crisis

        # Trend entry / stay (only when not in crisis)
        if self._bull_prob_above >= self._trend_window:
            return StrategyMode.TREND
        # Trend exit
        if in_trend:
            if self._bull_prob_below < self._trend_exit_window:
                return StrategyMode.TREND  # still in hysteresis exit window

        return StrategyMode.DEFAULT

    def _apply_overrides(self, features: "VictoriaFeatures") -> None:
        """Mutate features in-place with the active mode's overrides.

        V161 dual-duty veto: when the crisis-label contamination window is hot
        and the computed mode is DEFAULT (i.e. bear_prob_above < crisis_window),
        apply CRISIS overrides anyway.  This handles oscillating-regime periods
        where "normal" labels interrupt the crisis_window counter before it arms,
        leaving DEFAULT mode without any crisis protections.

        Effective mode hierarchy:
          TREND active             → TREND overrides
          CRISIS active            → CRISIS overrides
          DEFAULT + contaminated   → CRISIS overrides (V161 dual-duty)
          DEFAULT + clean          → base_values (original behaviour)
        """
        if self._mode == StrategyMode.TREND:
            overrides = _TREND_OVERRIDES
        elif self._mode == StrategyMode.CRISIS:
            overrides = _CRISIS_OVERRIDES
        elif getattr(self, "_crisis_contaminated", False):
            # V161: contaminated DEFAULT → apply CRISIS protections
            overrides = _CRISIS_OVERRIDES
        else:
            overrides = self._base_values  # clean DEFAULT — restore base

        # V162: blend overrides during a mode transition.  Numeric fields
        # interpolate linearly from the `from`-mode value to the `to`-mode
        # value; boolean fields flip at the midpoint (⌈N/2⌉) cycles remaining.
        if (
            self._blend_enabled
            and self._blend_remaining > 0
            and self._blend_from is not None
            and self._blend_to is not None
        ):
            from_ov = self._mode_overrides(self._blend_from)
            to_ov = self._mode_overrides(self._blend_to)
            # progress ∈ [0, 1] = fraction toward the target mode
            progress = 1.0 - (self._blend_remaining - 1) / max(1, self._blend_total)
            midpoint = (self._blend_total + 1) // 2  # ⌈N/2⌉
            bool_flipped = (self._blend_total - self._blend_remaining + 1) >= midpoint
            blended: dict[str, Any] = {}
            for field in set(from_ov.keys()) | set(to_ov.keys()):
                fv = from_ov.get(field)
                tv = to_ov.get(field)
                if isinstance(fv, bool) or isinstance(tv, bool):
                    blended[field] = tv if bool_flipped else fv
                elif isinstance(fv, (int, float)) and isinstance(tv, (int, float)):
                    blended[field] = fv + (tv - fv) * progress
                else:
                    blended[field] = tv if bool_flipped else fv
            overrides = blended
            self._blend_remaining -= 1
            if self._blend_remaining <= 0:
                self._blend_from = None
                self._blend_to = None

        # V196 preset-override safety: when features.preset_override_mode=True,
        # the selector does NOT mutate the features dataclass — instead it logs
        # what it WOULD have changed. Preserves the selector's diagnostic value
        # while preventing silent overrides of user-set preset values.
        _safe = bool(getattr(features, "preset_override_mode", False))
        for field, value in overrides.items():
            try:
                if _safe:
                    _current = getattr(features, field, None)
                    if _current != value:
                        logger.warning(
                            "preset_override_mode: selector would set %s=%r (current=%r) — suppressed",
                            field, value, _current,
                        )
                    continue
                setattr(features, field, value)
            except AttributeError:
                pass  # field may not exist in older configs

    def _mode_overrides(self, mode: StrategyMode) -> dict[str, Any]:
        """Return the override dict that mode `mode` would apply (without blending)."""
        if mode == StrategyMode.TREND:
            return _TREND_OVERRIDES
        if mode == StrategyMode.CRISIS:
            return _CRISIS_OVERRIDES
        return self._base_values

    def summary(self) -> dict[str, Any]:
        return {
            "mode": self._mode.value,
            "cycle": self._cycle,
            "bull_prob_above": self._bull_prob_above,
            "bull_prob_below": self._bull_prob_below,
            "bear_prob_above": self._bear_prob_above,
            "bear_prob_below": self._bear_prob_below,
            "crisis_contamination_count": sum(self._crisis_label_window),
            "trend_veto_active": any(self._crisis_label_window),
        }
