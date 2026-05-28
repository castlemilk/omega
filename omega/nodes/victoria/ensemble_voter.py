"""omega/nodes/victoria/ensemble_voter.py
V146 Ensemble Voter — structured vote aggregation replacing weighted-sum composite.

Each signal casts a directional vote (long/short/abstain) with a confidence score.
The voter aggregates by majority direction, computing conviction as:
    conviction = agreement_ratio × max_confidence_of_majority

The ``composite`` field mirrors the sign convention of the existing weighted sum
(positive for long, negative for short, 0 for abstain) for drop-in backward compat.

Usage
-----
    voter = EnsembleVoter()
    result = voter.from_signal_dict(sig)
    # result.composite replaces the old weighted-sum composite
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Vote:
    """Vote from one signal."""

    direction: str  # "long", "short", or "abstain"
    confidence: float  # ∈ [0.0, 1.0]
    signal_name: str  # for attribution


@dataclass
class EnsembleResult:
    """Result of ensemble vote aggregation."""

    direction: str  # "long", "short", or "abstain"
    conviction: float  # agreement_ratio × max_confidence_of_majority ∈ [0, 1]
    agreement_ratio: float  # majority_count / total_non_abstaining ∈ [0, 1]
    n_votes: int
    n_abstain: int
    long_votes: int
    short_votes: int
    composite: float  # backward-compat: +conviction for long, -conviction for short, 0 for abstain
    vote_breakdown: list[dict] = field(default_factory=list)


class EnsembleVoter:
    """Aggregate signal votes into a direction + conviction score."""

    def __init__(self, noise_threshold: float = 0.05) -> None:
        self.noise_threshold = noise_threshold  # |value| < this → abstain

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def signal_to_vote(self, signal_name: str, value: float, max_expected: float = 1.0) -> Vote:
        """Convert a raw signal value to a Vote.

        Parameters
        ----------
        signal_name:
            Identifier for attribution (e.g. ``"momentum_signal"``).
        value:
            Raw signal value (positive = bullish, negative = bearish).
        max_expected:
            Expected maximum absolute magnitude used to normalise confidence.
            Clipped to [1e-6, ∞) to avoid division by zero.
        """
        abs_val = abs(value)
        if abs_val < self.noise_threshold:
            return Vote("abstain", 0.0, signal_name)
        direction = "long" if value > 0 else "short"
        confidence = min(abs_val / max(max_expected, 1e-6), 1.0)
        return Vote(direction, confidence, signal_name)

    def aggregate(self, votes: list[Vote]) -> EnsembleResult:
        """Aggregate a list of Votes into an EnsembleResult."""
        non_abstaining = [v for v in votes if v.direction != "abstain"]
        n_abstain = len(votes) - len(non_abstaining)

        if not non_abstaining:
            return EnsembleResult(
                direction="abstain",
                conviction=0.0,
                agreement_ratio=0.0,
                n_votes=len(votes),
                n_abstain=n_abstain,
                long_votes=0,
                short_votes=0,
                composite=0.0,
                vote_breakdown=[
                    {
                        "signal": v.signal_name,
                        "direction": v.direction,
                        "confidence": round(v.confidence, 4),
                    }
                    for v in votes
                ],
            )

        long_votes = [v for v in non_abstaining if v.direction == "long"]
        short_votes = [v for v in non_abstaining if v.direction == "short"]

        # majority: ties go to long (conservative: more evidence needed to short)
        if len(long_votes) >= len(short_votes):
            majority = long_votes
            direction = "long"
        else:
            majority = short_votes
            direction = "short"

        agreement_ratio = len(majority) / len(non_abstaining)
        max_confidence = max(v.confidence for v in majority) if majority else 0.0
        conviction = agreement_ratio * max_confidence

        composite = conviction if direction == "long" else -conviction

        vote_breakdown = [
            {
                "signal": v.signal_name,
                "direction": v.direction,
                "confidence": round(v.confidence, 4),
            }
            for v in votes
        ]

        return EnsembleResult(
            direction=direction,
            conviction=conviction,
            agreement_ratio=agreement_ratio,
            n_votes=len(votes),
            n_abstain=n_abstain,
            long_votes=len(long_votes),
            short_votes=len(short_votes),
            composite=composite,
            vote_breakdown=vote_breakdown,
        )

    def from_signal_dict(
        self,
        sig: dict,
        signal_keys: list[str] | None = None,
    ) -> EnsembleResult:
        """Build votes from a Victoria signal dict and return aggregated result.

        The Victoria signal dict contains keys such as ``"momentum_signal"``,
        ``"rsi_signal"``, ``"sma_crossover"``, etc., plus a ``"composite"`` key
        for the existing weighted sum.  This method extracts numeric signal keys
        and casts each to a Vote.

        Parameters
        ----------
        sig:
            Signal dict produced by the Victoria signal pipeline.
        signal_keys:
            Explicit list of keys to use.  If ``None``, all keys ending in
            ``"_signal"`` plus ``"sma_crossover"`` are used automatically.
        """
        if signal_keys is None:
            signal_keys = [k for k in sig if k.endswith("_signal") or k == "sma_crossover"]

        votes: list[Vote] = []
        for key in signal_keys:
            val = sig.get(key)
            if isinstance(val, (int, float)):
                votes.append(self.signal_to_vote(key, float(val)))

        if not votes:
            # fallback: treat existing composite as a single vote
            comp = float(sig.get("composite", 0.0))
            votes = [self.signal_to_vote("composite", comp, max_expected=0.5)]

        return self.aggregate(votes)
