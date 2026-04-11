"""
omega.nodes.victoria.signal_confluence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Signal confluence analyzer — detects when sub-signals agree or diverge.

Currently signals are aggregated into a composite score but the per-signal
agreement structure is lost. This module exposes:

  1. ConfluenceResult — per-ticker agreement analysis
  2. ConfluenceAnalyzer — stateless scorer called per-ticker per-cycle
  3. Conviction and size modifiers derived from confluence strength

Wiring into strategy.py:
  - Call analyze(sig, direction) in the candidate loop after non-HOLD conviction
  - confluence.conviction_multiplier boosts w_conv for sizing (1.0–1.2)
  - confluence.size_multiplier reduces position size when uncertain (0.5 for weak confluence)
  - Log confluence data per decision via the DecisionTrace

Confluence score definition:
  agreement_ratio × (1.0 - magnitude_std / max_magnitude)

  agreement_ratio: fraction of directional sub-signals agreeing with composite direction
  magnitude_std: std of the agreeing signal magnitudes (low = consistent pull)
  max_magnitude: max absolute value among agreeing signals (normaliser)

When confluence_score > STRONG_THRESHOLD: conviction_multiplier = 1.2
When confluence_score < WEAK_THRESHOLD: size_multiplier = 0.5, is_uncertain = True
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger("omega.nodes.victoria.signal_confluence")

# Sub-signals considered for confluence analysis.
# Matches the keys checked in _compute_agreement_ratio in strategy.py.
_DIRECTIONAL_SIGNAL_KEYS = frozenset(
    {
        "rsi_signal",
        "macd_crossover",
        "bb_signal",
        "zscore_signal",
        "funding_rate_signal",
        "fear_greed_signal",
        "dxy_signal",
        "vix_signal",
        "yield_curve_signal",
        "spy_signal",
        "sma_crossover",
        "volume_signal",
        "btc_beta_signal",
        "ricci_curvature_signal",
        "ollivier_ricci_signal",
    }
)

# Thresholds for labelling confluence strength
STRONG_THRESHOLD: float = 0.65  # score above this → strong confluence → 1.2× conviction
WEAK_THRESHOLD: float = 0.30    # score below this → uncertain → 0.5× size


@dataclass
class ConfluenceResult:
    """Confluence analysis for one ticker in one cycle."""

    ticker: str

    # Agreement stats
    agreement_ratio: float = 0.0
    """Fraction of directional signals that agree with composite direction."""

    n_agreeing: int = 0
    n_dissenting: int = 0
    n_neutral: int = 0
    n_total: int = 0

    dissenting_signals: list[str] = field(default_factory=list)
    """Names of signals that oppose the composite direction."""

    agreeing_signals: list[str] = field(default_factory=list)
    """Names of signals that support the composite direction."""

    # Magnitude consistency of agreeing signals
    magnitude_consistency: float = 1.0
    """1.0 = all agreeing signals have identical magnitude. Computed as:
    1 - (std of agreeing magnitudes / max magnitude). Falls back to 1.0 if n_agreeing <= 1."""

    # Overall confluence score [0, 1]
    confluence_score: float = 0.0

    # Label
    label: str = "neutral"
    """'strong' | 'moderate' | 'weak' | 'neutral'"""

    # Strategy modifiers derived from confluence
    conviction_multiplier: float = 1.0
    """Multiply effective w_conv by this before sizing. 1.2 for strong, 1.0 otherwise."""

    size_multiplier: float = 1.0
    """Multiply final position size by this. 0.5 when uncertain (weak confluence)."""

    is_uncertain: bool = False
    """True when confluence is weak enough to flag the trade as uncertain."""

    def to_log_str(self) -> str:
        return (
            f"confluence={self.confluence_score:.2f}({self.label}), "
            f"agree={self.n_agreeing}/{self.n_total}, "
            f"dissent=[{','.join(self.dissenting_signals)}], "
            f"conv_mult={self.conviction_multiplier:.1f}, size_mult={self.size_multiplier:.1f}"
        )


class ConfluenceAnalyzer:
    """Stateless confluence scorer — no internal state, pure function."""

    def analyze(self, sig: dict, ticker: str = "", direction: str = "long") -> ConfluenceResult:
        """Compute confluence for a single ticker's signal dict.

        Args:
            sig: Per-ticker signal dict from the signals dict.
            ticker: Symbol name (for logging only).
            direction: 'long' or 'short' — determines what "agreement" means.
        """
        # Collect directional signal values
        signal_values: dict[str, float] = {}
        for k in _DIRECTIONAL_SIGNAL_KEYS:
            v = sig.get(k)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isnan(fv) or math.isinf(fv):
                continue
            signal_values[k] = fv

        n_total = len(signal_values)
        if n_total == 0:
            return ConfluenceResult(ticker=ticker)

        # Determine expected direction sign
        # long → we want positive signals; short → we want negative signals
        positive_is_agreeing = direction == "long"

        agreeing: list[tuple[str, float]] = []   # (name, value)
        dissenting: list[str] = []
        neutral: list[str] = []

        for name, val in signal_values.items():
            if abs(val) < 0.01:
                neutral.append(name)
            elif (val > 0) == positive_is_agreeing:
                agreeing.append((name, abs(val)))
            else:
                dissenting.append(name)

        n_agreeing = len(agreeing)
        n_dissenting = len(dissenting)
        n_neutral = len(neutral)
        effective_total = n_agreeing + n_dissenting  # neutral doesn't count toward ratio

        agreement_ratio = n_agreeing / effective_total if effective_total > 0 else 0.0

        # Magnitude consistency of agreeing signals
        if n_agreeing <= 1:
            magnitude_consistency = 1.0
        else:
            mags = [v for _, v in agreeing]
            mean_mag = sum(mags) / len(mags)
            max_mag = max(mags)
            std_mag = math.sqrt(sum((m - mean_mag) ** 2 for m in mags) / len(mags))
            magnitude_consistency = 1.0 - (std_mag / max_mag) if max_mag > 0 else 1.0
            magnitude_consistency = max(0.0, min(1.0, magnitude_consistency))

        # Confluence score
        confluence_score = agreement_ratio * magnitude_consistency

        # Label + modifiers
        if confluence_score >= STRONG_THRESHOLD and n_agreeing >= 3:
            label = "strong"
            conviction_multiplier = 1.2
            size_multiplier = 1.0
            is_uncertain = False
        elif confluence_score < WEAK_THRESHOLD or n_dissenting > n_agreeing:
            label = "weak"
            conviction_multiplier = 1.0
            size_multiplier = 0.5
            is_uncertain = True
        elif confluence_score >= STRONG_THRESHOLD:
            label = "moderate"  # strong score but few signals (n_agreeing < 3)
            conviction_multiplier = 1.1
            size_multiplier = 1.0
            is_uncertain = False
        else:
            label = "moderate"
            conviction_multiplier = 1.0
            size_multiplier = 1.0
            is_uncertain = False

        result = ConfluenceResult(
            ticker=ticker,
            agreement_ratio=agreement_ratio,
            n_agreeing=n_agreeing,
            n_dissenting=n_dissenting,
            n_neutral=n_neutral,
            n_total=n_total,
            dissenting_signals=dissenting,
            agreeing_signals=[name for name, _ in agreeing],
            magnitude_consistency=magnitude_consistency,
            confluence_score=confluence_score,
            label=label,
            conviction_multiplier=conviction_multiplier,
            size_multiplier=size_multiplier,
            is_uncertain=is_uncertain,
        )

        logger.debug(
            "Confluence %s (%s): %s",
            ticker,
            direction,
            result.to_log_str(),
        )

        return result
