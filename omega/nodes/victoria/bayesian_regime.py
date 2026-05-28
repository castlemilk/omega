"""omega/nodes/victoria/bayesian_regime.py
Phase 5 (V147): Bayesian Regime Detector.

Replaces hard bear_prob/bull_prob threshold trees with a probabilistic
posterior P(regime | signals, LLM) over four regimes.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger(__name__)

REGIMES = ["crisis", "high_vol", "normal", "trending"]


@dataclass
class RegimePrior:
    """P(R | LLM_assessment) — uniform by default."""

    probs: dict[str, float] = field(
        default_factory=lambda: {
            "crisis": 0.25,
            "high_vol": 0.25,
            "normal": 0.25,
            "trending": 0.25,
        }
    )

    def normalize(self) -> None:
        total = sum(self.probs.values())
        if total > 0:
            self.probs = {k: v / total for k, v in self.probs.items()}

    def from_llm_assessment(self, regime_str: str, confidence: float = 0.7) -> None:
        """Set a peaked prior from an LLM regime assessment."""
        if regime_str not in REGIMES:
            return
        remaining = (1.0 - confidence) / (len(REGIMES) - 1)
        self.probs = {r: remaining for r in REGIMES}
        self.probs[regime_str] = confidence
        self.normalize()


@dataclass
class SignalDistribution:
    """Gaussian distribution P(signal | regime) for one signal."""

    mu: float = 0.0
    sigma: float = 0.3

    def log_likelihood(self, value: float) -> float:
        """Log P(value | this distribution). Returns 0 if sigma too small."""
        if self.sigma < 1e-6:
            return 0.0
        z = (value - self.mu) / self.sigma
        return -0.5 * z * z - math.log(self.sigma) - 0.5 * math.log(2 * math.pi)


class RegimeLikelihood:
    """
    P(signals | regime) — computed from observed signal distributions per regime.

    Updated incrementally as trades close with known regime labels.
    Uses online Welford algorithm for running mean and variance.
    """

    def __init__(self, signal_names: list[str]):
        self.signal_names = signal_names
        # Per-regime, per-signal running stats: {regime: {signal: [n, mean, M2]}}
        self._stats: dict[str, dict[str, list[float]]] = {
            regime: {sig: [0.0, 0.0, 0.0] for sig in signal_names} for regime in REGIMES
        }

    def update(self, regime: str, signal_values: dict[str, float]) -> None:
        """Welford online update for regime signal statistics."""
        if regime not in self._stats:
            return
        for sig_name, value in signal_values.items():
            if sig_name not in self._stats[regime]:
                continue
            n, mean, m2 = self._stats[regime][sig_name]
            n += 1
            delta = value - mean
            mean += delta / n
            delta2 = value - mean
            m2 += delta * delta2
            self._stats[regime][sig_name] = [n, mean, m2]

    def get_distribution(self, regime: str, signal: str) -> SignalDistribution:
        stats = self._stats.get(regime, {}).get(signal, [0.0, 0.0, 0.0])
        n, mean, m2 = stats
        if n < 3:
            return SignalDistribution(mu=0.0, sigma=0.3)  # uninformative prior
        sigma = math.sqrt(m2 / (n - 1)) if n > 1 else 0.3
        return SignalDistribution(mu=mean, sigma=max(sigma, 0.01))

    def log_likelihood(self, regime: str, signal_values: dict[str, float]) -> float:
        """Compute Σ log P(signal_i | regime) across all signals."""
        total = 0.0
        for sig_name, value in signal_values.items():
            dist = self.get_distribution(regime, sig_name)
            total += dist.log_likelihood(value)
        return total

    def to_dict(self) -> dict:
        return self._stats

    @classmethod
    def from_dict(cls, d: dict, signal_names: list[str]) -> RegimeLikelihood:
        obj = cls(signal_names)
        for regime, sigs in d.items():
            if regime in obj._stats:
                for sig, stats in sigs.items():
                    if sig in obj._stats[regime] and len(stats) == 3:
                        obj._stats[regime][sig] = list(stats)
        return obj


@dataclass
class RegimePosterior:
    """P(R | signals, LLM) ∝ P(signals | R) × P(R | LLM)"""

    probs: dict[str, float]

    @property
    def crisis(self) -> float:
        return self.probs.get("crisis", 0.25)

    @property
    def high_vol(self) -> float:
        return self.probs.get("high_vol", 0.25)

    @property
    def normal(self) -> float:
        return self.probs.get("normal", 0.25)

    @property
    def trending(self) -> float:
        return self.probs.get("trending", 0.25)

    @property
    def dominant(self) -> tuple[str, float]:
        """Return (regime_name, probability) of most likely regime."""
        best = max(self.probs, key=self.probs.get)  # type: ignore[arg-type]
        return best, self.probs[best]

    def long_affinity(self) -> float:
        """Composite long-favorability: trending + normal - crisis."""
        return (
            self.probs.get("trending", 0)
            + self.probs.get("normal", 0)
            - self.probs.get("crisis", 0)
        )

    def short_affinity(self) -> float:
        """Composite short-favorability: crisis + high_vol - trending."""
        return (
            self.probs.get("crisis", 0)
            + self.probs.get("high_vol", 0)
            - self.probs.get("trending", 0)
        )


class BayesianRegimeDetector:
    """
    Phase 5 (V147): Bayesian regime posterior.

    Replaces hard bear_prob/bull_prob threshold trees with P(regime | signals, LLM).
    Long/short sizing becomes proportional to long_affinity/short_affinity.

    Usage::

        detector = BayesianRegimeDetector(signal_names=list_of_signals)

        # Each cycle:
        posterior = detector.compute_posterior(signal_values, prior=None)
        long_scale = max(0.0, posterior.long_affinity())  # scale long positions
        short_scale = max(0.0, posterior.short_affinity())

        # After trade closes with known regime:
        detector.update_likelihood(regime="crisis", signal_values=sig_dict)
        detector.save_state()
    """

    _DEFAULT_SIGNAL_NAMES: ClassVar[list[str]] = [
        "momentum_signal",
        "rsi_signal",
        "macd_signal",
        "bb_signal",
        "volume_signal",
        "mfi_signal",
        "obv_signal",
        "sma_crossover",
    ]

    def __init__(
        self,
        signal_names: list[str] | None = None,
        state_file: Path = Path("data/bayesian_regime_state.json"),
    ):
        self.signal_names = signal_names or self._DEFAULT_SIGNAL_NAMES
        self.state_file = Path(state_file)
        self._prior = RegimePrior()
        self._likelihood = RegimeLikelihood(self.signal_names)
        self._n_updates = 0
        self._load_state()

    def compute_posterior(
        self,
        signal_values: dict[str, float],
        prior: RegimePrior | None = None,
    ) -> RegimePosterior:
        """
        Compute P(regime | signals) using Bayes' rule.

        Parameters
        ----------
        signal_values : {signal_name: value} dict from the cycle.
        prior         : Optional custom prior. Defaults to uniform.
        """
        _prior = prior or self._prior

        # Filter to known signals
        known_signals = {k: v for k, v in signal_values.items() if k in self.signal_names}

        log_posteriors: dict[str, float] = {}
        for regime in REGIMES:
            log_p_prior = math.log(max(_prior.probs.get(regime, 0.25), 1e-10))
            log_p_signals = self._likelihood.log_likelihood(regime, known_signals)
            log_posteriors[regime] = log_p_prior + log_p_signals

        # Normalize in log-space (subtract max for numerical stability)
        max_log = max(log_posteriors.values())
        unnorm = {r: math.exp(lp - max_log) for r, lp in log_posteriors.items()}
        total = sum(unnorm.values())
        probs = {r: v / total for r, v in unnorm.items()}

        return RegimePosterior(probs=probs)

    def update_likelihood(self, regime: str, signal_values: dict[str, float]) -> None:
        """Online update of signal distributions for a regime."""
        self._likelihood.update(regime, signal_values)
        self._n_updates += 1

    def set_prior_from_llm(self, regime_str: str, confidence: float = 0.7) -> None:
        """Update prior based on LLM meta-controller's regime assessment."""
        self._prior.from_llm_assessment(regime_str, confidence)

    # ── Persistence ──────────────────────────────────────────────────────

    def save_state(self) -> None:
        payload = {
            "version": 1,
            "n_updates": self._n_updates,
            "prior": self._prior.probs,
            "likelihood_stats": self._likelihood.to_dict(),
            "signal_names": self.signal_names,
        }
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(payload, indent=2, default=str))
        except Exception as exc:
            logger.warning("bayesian_regime: save failed: %s", exc)

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            raw = json.loads(self.state_file.read_text())
            if "prior" in raw:
                self._prior.probs = raw["prior"]
                self._prior.normalize()
            if "likelihood_stats" in raw:
                self._likelihood = RegimeLikelihood.from_dict(
                    raw["likelihood_stats"], self.signal_names
                )
            self._n_updates = raw.get("n_updates", 0)
            logger.debug("bayesian_regime: state loaded (%d updates)", self._n_updates)
        except Exception as exc:
            logger.warning("bayesian_regime: load failed: %s", exc)
