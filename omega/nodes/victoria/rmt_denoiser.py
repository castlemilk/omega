"""
omega.nodes.victoria.rmt_denoiser
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Random Matrix Theory (RMT) denoising for signal correlation matrices.

The Marchenko-Pastur distribution describes the eigenvalue spectrum of a
*random* correlation matrix.  Eigenvalues **above** the MP upper bound
carry genuine statistical structure; eigenvalues **below** it are noise.

Primary uses
------------
1. ``denoise_correlation`` — clean the N×N signal correlation matrix so that
   downstream geometric methods (Riemannian distance, curvature, TDA) operate
   on signal rather than noise.

2. ``compute`` — standalone signal: the fraction of signal eigenvalues above
   the MP bound ("information content") tells the strategy whether signals are
   collectively structured (trade) or collectively random (sit out).

Wiring
------
- TransferEntropyAnalyzer uses the denoised C to refine causal weights.
- DynamicWeightAllocator uses per-signal RMT quality scores to scale IC EMAs.
- VictoriaNode exposes ``rmt_signal`` as a first-class signal in SIGNAL_NAMES.

References
----------
- Marchenko & Pastur (1967) "Distribution of eigenvalues for some sets of
  random matrices", Soviet Mathematics Doklady.
- Laloux et al. (1999) "Noise Dressing of Financial Correlation Matrices",
  PRL 83(7):1467.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

import numpy as np

from omega.nodes.victoria.information_flow import SIGNAL_NAMES

logger = logging.getLogger("omega.nodes.victoria.rmt_denoiser")

N_SIGNALS = len(SIGNAL_NAMES)
MIN_SAMPLES_RMT = 30   # minimum history before eigenvalue analysis is reliable
_EPS = 1e-8


@dataclass
class SignalValue:
    """Mirrors the SignalValue contract used by the other advanced signal nodes."""

    value: float       # z-scored information ratio; >0 = structured, <0 = noisy
    confidence: float  # 0..1; grows with history length
    regime_tag: str    # "structured" | "noisy" | "transitioning" | "warmup"
    raw: dict


class RMTDenoiser:
    """
    Marchenko-Pastur correlation matrix denoiser.

    Parameters
    ----------
    window : int
        Rolling window length for the signal history matrix (T rows × N cols).
        Larger T reduces estimation noise but lags regime transitions.
    """

    def __init__(self, window: int = 100) -> None:
        self._signal_history: deque[list[float]] = deque(maxlen=window)
        self._info_ratio_history: deque[float] = deque(maxlen=50)

    # ------------------------------------------------------------------ public

    def denoise_correlation(self, signal_vectors: np.ndarray) -> np.ndarray:
        """
        Clean a correlation matrix using the Marchenko-Pastur distribution.

        Parameters
        ----------
        signal_vectors : ndarray, shape (T, N)
            Matrix of T observations × N signals.

        Returns
        -------
        C_clean : ndarray, shape (N, N)
            Denoised correlation matrix with diagonal = 1.0.

        Algorithm
        ---------
        1. Compute correlation matrix C from signal_vectors.
        2. Eigendecompose: C = Q Λ Qᵀ.
        3. MP upper bound: λ⁺ = (1 + √(N/T))²,  q = N/T.
        4. Replace noise eigenvalues (λ < λ⁺) with their mean.
        5. Reconstruct and normalise back to a correlation matrix.
        """
        T, N = signal_vectors.shape

        if T < N + 2:
            # Underdetermined: return identity (all signals uncorrelated → equal weight)
            return np.eye(N)

        # Guard: replace NaN/Inf with 0
        mat = np.nan_to_num(signal_vectors, nan=0.0, posinf=0.0, neginf=0.0)

        # Correlation matrix (N×N)
        C = np.corrcoef(mat.T)
        C = np.nan_to_num(C, nan=0.0)

        # Eigendecompose (eigh guarantees real + sorted eigenvalues)
        eigenvalues, eigenvectors = np.linalg.eigh(C)

        # Marchenko-Pastur bounds
        q = N / T                            # ratio signals / time-points
        lambda_plus = (1.0 + np.sqrt(q)) ** 2

        # Split noise vs signal eigenmodes
        noise_mask = eigenvalues < lambda_plus
        signal_mask = ~noise_mask

        # Replace noise eigenvalues with their bulk mean (trace-preserving)
        cleaned = eigenvalues.copy()
        if noise_mask.any():
            noise_avg = eigenvalues[noise_mask].mean()
            cleaned[noise_mask] = noise_avg

        # Reconstruct
        C_clean = eigenvectors @ np.diag(cleaned) @ eigenvectors.T

        # Normalise to proper correlation matrix (diagonal = 1)
        d = np.sqrt(np.maximum(np.diag(C_clean), _EPS))
        C_clean = C_clean / np.outer(d, d)
        np.fill_diagonal(C_clean, 1.0)

        n_signal_modes = int(signal_mask.sum())
        logger.debug(
            "RMT denoise: T=%d N=%d q=%.3f λ⁺=%.3f signal_modes=%d/%d",
            T, N, q, lambda_plus, n_signal_modes, N,
        )

        return C_clean

    def compute(self, signal_vector: dict) -> SignalValue:
        """
        Compute the RMT information-content signal.

        Interprets the fraction of eigenvalues above the MP bound as a measure
        of how much real structure exists in the current signal ensemble.

        High ``value``  → signals are correlated with genuine structure; the
                          market is carrying information.  Trade more aggressively.
        Low ``value``   → signals look like a random matrix; noise-dominated.
                          Reduce exposure / sit out.

        Parameters
        ----------
        signal_vector : dict
            {signal_name: float} — current cycle values for SIGNAL_NAMES.

        Returns
        -------
        SignalValue
            value      : z-scored information ratio (mean 0, std ≈ 1 over history)
            confidence : 0→1 based on warmup progress
            regime_tag : "structured" | "noisy" | "transitioning" | "warmup"
            raw        : {"n_signal_modes", "n_total", "info_ratio", "lambda_plus", "q"}
        """
        vec = [float(signal_vector.get(s, 0.0)) for s in SIGNAL_NAMES]
        self._signal_history.append(vec)

        n_hist = len(self._signal_history)
        confidence = min(1.0, (n_hist - MIN_SAMPLES_RMT) / max(1, 100 - MIN_SAMPLES_RMT))

        if n_hist < MIN_SAMPLES_RMT:
            return SignalValue(
                value=0.0,
                confidence=max(0.0, n_hist / MIN_SAMPLES_RMT) * 0.3,
                regime_tag="warmup",
                raw={"n_signal_modes": 0, "n_total": N_SIGNALS, "info_ratio": 0.0,
                     "lambda_plus": 0.0, "q": 0.0},
            )

        data = np.array(self._signal_history, dtype=float)
        T, N = data.shape
        data = np.nan_to_num(data, nan=0.0)

        # Compute eigenvalues of the normalised correlation matrix
        C = np.corrcoef(data.T)
        C = np.nan_to_num(C, nan=0.0)
        eigenvalues = np.linalg.eigvalsh(C)

        q = N / T
        lambda_plus = (1.0 + np.sqrt(q)) ** 2

        n_signal_modes = int(np.sum(eigenvalues > lambda_plus))
        info_ratio = n_signal_modes / N          # fraction of signals carrying real info

        self._info_ratio_history.append(info_ratio)

        # Z-score vs recent info_ratio history
        hist = np.array(self._info_ratio_history)
        if len(hist) >= 5:
            mu, sigma = hist.mean(), hist.std()
            z = (info_ratio - mu) / (sigma + _EPS)
        else:
            z = 0.0

        # Clip to ±3σ and scale to roughly [-1, 1]
        value = float(np.clip(z / 3.0, -1.0, 1.0))

        if value > 0.2:
            regime_tag = "structured"
        elif value < -0.2:
            regime_tag = "noisy"
        else:
            regime_tag = "transitioning"

        raw = {
            "n_signal_modes": n_signal_modes,
            "n_total": N,
            "info_ratio": round(info_ratio, 4),
            "lambda_plus": round(float(lambda_plus), 4),
            "q": round(float(q), 4),
        }

        logger.debug(
            "RMT signal: info_ratio=%.3f n_signal=%d/%d z=%.3f regime=%s",
            info_ratio, n_signal_modes, N, z, regime_tag,
        )

        return SignalValue(
            value=value,
            confidence=min(1.0, confidence),
            regime_tag=regime_tag,
            raw=raw,
        )

    def get_denoised_correlation(self) -> np.ndarray | None:
        """
        Return the denoised correlation matrix from current history.

        Returns None if insufficient history is available.
        """
        if len(self._signal_history) < MIN_SAMPLES_RMT:
            return None
        data = np.array(self._signal_history, dtype=float)
        data = np.nan_to_num(data, nan=0.0)
        return self.denoise_correlation(data)

    def signal_quality_scores(self) -> dict[str, float]:
        """
        Per-signal quality score based on RMT-filtered correlation structure.

        A signal is "high quality" when it participates strongly in the
        eigenmodes above the MP bound.

        Returns
        -------
        dict : {signal_name: quality_score}
            quality_score ∈ [0, 1]; higher = more structure-carrying.
        """
        C_clean = self.get_denoised_correlation()
        if C_clean is None:
            return {s: 1.0 for s in SIGNAL_NAMES}  # equal quality when no history

        # Use L2 norm of each signal's off-diagonal correlations in denoised C
        # as proxy for how much genuine co-movement that signal carries
        scores = {}
        for i, name in enumerate(SIGNAL_NAMES):
            off_diag = np.delete(C_clean[i], i)
            score = float(np.sqrt(np.mean(off_diag ** 2)))
            scores[name] = score

        # Normalise to [0, 1]
        max_s = max(scores.values()) or 1.0
        return {k: v / max_s for k, v in scores.items()}
