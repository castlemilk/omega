"""
omega.nodes.victoria.disagreement_signal
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
DisagreementSignalComputer — computes a disagreement feature vector from the
current signal set and exposes it as an additional signal the meta-model can use.

Key insight (Simons / Renaissance approach):
  The PATTERN of disagreement is predictive, not just its magnitude.
  - When all signals except one agree → the outlier is usually wrong
  - When signals split 50/50 → stay out (high uncertainty)
  - When all signals agree with high conviction → strongest entry

Features computed
-----------------
  max_disagreement          max pairwise |v_i - v_j| between signal values
  mean_pairwise_disagreement  mean of all pairwise |v_i - v_j|
  cluster_count             how many distinct signal clusters exist (bull/bear/neutral)
  conviction_entropy        Shannon entropy of |conviction| distribution
  signal_skewness           skewness of signal value distribution
  outlier_count             signals that deviate > 2 std dev from mean
  consensus_direction       -1..+1 (bearish..bullish aggregate)
  split_score               0..1 (0 = full consensus, 1 = perfect 50-50 split)
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# DisagreementFeatures
# ---------------------------------------------------------------------------


@dataclass
class DisagreementFeatures:
    """Feature vector describing the structure of signal disagreement."""

    max_disagreement: float  # max pairwise |v_i - v_j|
    mean_pairwise_disagreement: float  # mean pairwise |v_i - v_j|
    cluster_count: int  # distinct signal clusters (1-3)
    conviction_entropy: float  # entropy of |conviction| distribution
    signal_skewness: float  # skewness of signal values
    outlier_count: int  # signals deviating > 2 std dev from mean
    consensus_direction: float  # -1..+1 directional aggregate
    split_score: float  # 0..1; 0 = consensus, 1 = 50-50 split


# ---------------------------------------------------------------------------
# DisagreementSignalComputer
# ---------------------------------------------------------------------------


class DisagreementSignalComputer:
    """
    Computes disagreement features from a set of signal values.

    Wired as an additional signal (``"disagreement"``) in the Victoria
    signal pipeline so the meta-model can observe *how* signals disagree,
    not just *whether* they disagree.

    Usage::

        computer = DisagreementSignalComputer()
        features = computer.compute(signals)
        sig_dict = computer.to_signal_dict(features)
        # sig_dict follows the standard {value, confidence, regime_tag, raw} format
    """

    def compute(self, signals: dict[str, Any]) -> DisagreementFeatures:
        """
        Compute disagreement features from a signal dict.

        Parameters
        ----------
        signals : dict
            Output of _do_compute_signals — may include _weights, _regime etc.
            Only non-underscore keys with a numeric ``value`` field are used.

        Returns
        -------
        DisagreementFeatures
        """
        values = self._extract_values(signals)

        if len(values) < 2:
            # Degenerate: single signal or no signals
            return DisagreementFeatures(
                max_disagreement=0.0,
                mean_pairwise_disagreement=0.0,
                cluster_count=1,
                conviction_entropy=0.0,
                signal_skewness=0.0,
                outlier_count=0,
                consensus_direction=values[0] if values else 0.0,
                split_score=0.0,
            )

        n = len(values)

        # ── Pairwise disagreements ────────────────────────────────────────
        pairs: list[float] = []
        for i in range(n):
            for j in range(i + 1, n):
                pairs.append(abs(values[i] - values[j]))

        max_disagreement = max(pairs)
        mean_pairwise = sum(pairs) / len(pairs)

        # ── Cluster count: bull / bear / neutral ─────────────────────────
        bullish = sum(1 for v in values if v > 0.05)
        bearish = sum(1 for v in values if v < -0.05)
        neutral = n - bullish - bearish
        cluster_count = sum(1 for c in [bullish, bearish, neutral] if c > 0)

        # ── Conviction entropy ────────────────────────────────────────────
        # Use absolute signal magnitudes as proxy for conviction
        abs_vals = [abs(v) for v in values]
        total_abs = sum(abs_vals) or 1.0
        probs = [a / total_abs for a in abs_vals]
        conviction_entropy = -sum(p * math.log(p + 1e-12) for p in probs)

        # ── Skewness ──────────────────────────────────────────────────────
        signal_skewness = self._skewness(values)

        # ── Outlier count (|z-score| > 2) ────────────────────────────────
        if n >= 3:
            mean_v = statistics.mean(values)
            std_v = statistics.stdev(values)
            outlier_count = sum(
                1 for v in values if std_v > 1e-10 and abs(v - mean_v) / std_v > 2.0
            )
        else:
            outlier_count = 0

        # ── Consensus direction ───────────────────────────────────────────
        consensus_direction = sum(values) / n

        # ── Split score ───────────────────────────────────────────────────
        # 0 = full one-sided consensus, 1 = perfect 50-50 split
        # Formula: 1 - |bull_frac - bear_frac|, rescaled to 0..1
        bull_frac = bullish / n
        bear_frac = bearish / n
        split_score = 1.0 - abs(bull_frac - bear_frac)
        # Scale: at perfect 50-50, bull_frac == bear_frac → split = 1; at full consensus → 0
        split_score = min(max(split_score, 0.0), 1.0)

        return DisagreementFeatures(
            max_disagreement=max_disagreement,
            mean_pairwise_disagreement=mean_pairwise,
            cluster_count=cluster_count,
            conviction_entropy=conviction_entropy,
            signal_skewness=signal_skewness,
            outlier_count=outlier_count,
            consensus_direction=consensus_direction,
            split_score=split_score,
        )

    def to_signal_dict(self, features: DisagreementFeatures) -> dict[str, Any]:
        """
        Convert DisagreementFeatures to the standard signal dict format.

        The composite ``value`` is negative when signals split badly
        (uncertainty signal discourages entry).  ``confidence`` is high
        when signals agree.

        Returns
        -------
        dict with keys: value, confidence, regime_tag, raw
        """
        # High split_score → lower value (uncertainty penalty)
        # High max_disagreement → amplifies the penalty
        composite = -(features.split_score * (1.0 + features.max_disagreement))
        composite = max(-1.0, min(1.0, composite))

        # Confidence: high when signals agree (low split), low when they split
        confidence = 1.0 - features.split_score
        confidence = max(0.0, min(1.0, confidence))

        return {
            "value": composite,
            "confidence": confidence,
            "regime_tag": self._regime_from_features(features),
            "raw": {
                "max_disagreement": features.max_disagreement,
                "mean_pairwise_disagreement": features.mean_pairwise_disagreement,
                "cluster_count": features.cluster_count,
                "conviction_entropy": features.conviction_entropy,
                "signal_skewness": features.signal_skewness,
                "outlier_count": features.outlier_count,
                "consensus_direction": features.consensus_direction,
                "split_score": features.split_score,
            },
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_values(signals: dict[str, Any]) -> list[float]:
        """Extract numeric signal values, skipping metadata keys."""
        values: list[float] = []
        for name, sig in signals.items():
            if name.startswith("_"):
                continue
            if isinstance(sig, dict) and "value" in sig:
                values.append(float(sig["value"]))
        return values

    @staticmethod
    def _skewness(values: list[float]) -> float:
        """Pearson's moment coefficient of skewness."""
        n = len(values)
        if n < 3:
            return 0.0
        mean_v = sum(values) / n
        variance = sum((v - mean_v) ** 2 for v in values) / n
        std_v = variance**0.5
        if std_v < 1e-10:
            return 0.0
        return float(sum(((v - mean_v) / std_v) ** 3 for v in values) / n)

    @staticmethod
    def _regime_from_features(features: DisagreementFeatures) -> str:
        """Map disagreement features to a human-readable regime label."""
        if features.split_score > 0.75:
            return "high_disagreement"
        if features.outlier_count > 0 and features.cluster_count <= 2:
            return "outlier_present"
        if features.cluster_count == 1:
            return "consensus"
        if features.split_score < 0.25:
            return "soft_consensus"
        return "mixed"
