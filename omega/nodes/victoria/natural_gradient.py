"""
omega.nodes.victoria.natural_gradient
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Natural gradient optimizer for signal weight updates.

Replaces simple EMA IC updates with geometry-aware optimization using the
Fisher information metric.  The natural gradient descends along the steepest
direction on the statistical manifold rather than in flat Euclidean space,
converging faster and avoiding the flat spots of vanilla gradient descent.

Reference: Amari (1998) "Natural Gradient Works Efficiently in Learning"
"""

from __future__ import annotations

import logging
from collections import deque

import numpy as np

logger = logging.getLogger("omega.nodes.victoria.natural_gradient")

# Minimum observations before the Fisher estimate is reliable
_MIN_SAMPLES = 30
# Tikhonov regularisation added to the Fisher matrix diagonal
_FISHER_REG = 1e-6
# Hard floor on any single weight to prevent collapse to zero
_MIN_WEIGHT = 0.01


class NaturalGradientOptimizer:
    """
    Uses Fisher information matrix to compute natural gradient for signal
    weight updates.  Replaces simple EMA IC updates with geometry-aware
    optimisation.

    The linear signal model is::

        return_t ≈ signals_t @ weights + noise_t,  noise ~ N(0, σ²)

    The log-likelihood score is::

        ∂log p / ∂w_i  =  signal_i * (return - predicted) / σ²

    The Fisher information matrix is approximated by the outer-product
    average of the score::

        F ≈ (1/T) Σ_t  score_t  score_t^T

    The natural gradient update is::

        w ← w − lr * F^{-1} * ∇L

    where ∇L is the ordinary (Euclidean) gradient of the MSE loss.

    Args:
        n_signals:     Number of signals being weighted.
        learning_rate: Step size for weight updates (default 0.01).
        window:        Rolling window length for history (default 100).
    """

    def __init__(
        self,
        n_signals: int,
        learning_rate: float = 0.01,
        window: int = 100,
    ) -> None:
        self.n = n_signals
        self.lr = learning_rate
        self._weights = np.ones(n_signals) / n_signals
        self._fisher = np.eye(n_signals)
        self._signal_history: deque[np.ndarray] = deque(maxlen=window)
        self._return_history: deque[float] = deque(maxlen=window)

    # ------------------------------------------------------------------ public

    @property
    def weights(self) -> np.ndarray:
        """Current weight vector (copy)."""
        return self._weights.copy()

    def update(self, signal_values: np.ndarray, forward_return: float) -> np.ndarray:
        """
        Ingest one new observation and return the updated weight vector.

        Args:
            signal_values:   Array of shape (n_signals,) with signal readings.
            forward_return:  The realised return for this bar.

        Returns:
            Updated weight vector of shape (n_signals,), sums to 1.
        """
        signal_values = np.asarray(signal_values, dtype=float)
        if signal_values.shape != (self.n,):
            raise ValueError(
                f"Expected signal_values of length {self.n}, got {signal_values.shape}"
            )

        self._signal_history.append(signal_values)
        self._return_history.append(float(forward_return))

        if len(self._signal_history) < _MIN_SAMPLES:
            logger.debug(
                "natural_gradient: warming up (%d/%d samples)",
                len(self._signal_history),
                _MIN_SAMPLES,
            )
            return self._weights.copy()

        signals = np.array(self._signal_history)  # (T, n)
        returns = np.array(self._return_history)  # (T,)

        # ---- 1. Euclidean gradient of MSE loss --------------------------
        predicted = signals @ self._weights  # (T,)
        residuals = returns - predicted  # (T,)
        variance = max(float(np.var(residuals)), 1e-10)

        # ∇L = -1/T  Σ_t  signal_t * residual_t   (MSE gradient w.r.t. w)
        euclidean_grad = -signals.T @ residuals / len(signals)

        # ---- 2. Fisher information matrix --------------------------------
        # score_t = signal_t * residual_t / σ²   shape (T, n)
        scores = signals * residuals[:, None] / variance
        self._fisher = scores.T @ scores / len(scores) + _FISHER_REG * np.eye(self.n)

        # ---- 3. Natural gradient = F^{-1} * ∇L --------------------------
        try:
            natural_grad = np.linalg.solve(self._fisher, euclidean_grad)
        except np.linalg.LinAlgError:
            logger.warning("natural_gradient: Fisher solve failed, falling back to Euclidean grad")
            natural_grad = euclidean_grad

        # ---- 4. Gradient step --------------------------------------------
        self._weights -= self.lr * natural_grad

        # ---- 5. Project onto the probability simplex ---------------------
        self._weights = np.maximum(self._weights, _MIN_WEIGHT)
        self._weights /= self._weights.sum()

        logger.debug(
            "natural_gradient: weights updated — min=%.4f max=%.4f",
            self._weights.min(),
            self._weights.max(),
        )
        return self._weights.copy()

    def weight_dict(self, signal_names: list[str]) -> dict[str, float]:
        """Return current weights as a {name: weight} dict."""
        if len(signal_names) != self.n:
            raise ValueError(f"signal_names length {len(signal_names)} != n_signals {self.n}")
        return dict(zip(signal_names, self._weights.tolist(), strict=False))

    def reset(self) -> None:
        """Reset optimizer state (but keep hyper-parameters)."""
        self._weights = np.ones(self.n) / self.n
        self._fisher = np.eye(self.n)
        self._signal_history.clear()
        self._return_history.clear()
