"""
omega.math.bayesian
~~~~~~~~~~~~~~~~~~~
Bayesian signal aggregator with log-odds representation for numerical stability.

This module implements the core probabilistic updating logic used by the
Victoria signal aggregation layer. All multi-signal fusion should go through
the functions here rather than ad-hoc probability arithmetic.

Mathematical Background
-----------------------
Bayes' Theorem:

    P(H|E) = P(E|H) · P(H) / P(E)

Log-Odds Representation (avoids floating-point underflow near 0 and 1):

    log_odds(p) = log(p / (1-p))

Sequential Bayesian updating in log-odds space:

    LO_posterior = LO_prior + Σ_i log(LR_i)

where LR_i = P(E_i|H) / P(E_i|¬H) is the likelihood ratio for evidence i.
Each signal contributes an additive term — signals are assumed conditionally
independent given the hypothesis.

Confidence-Weighted Aggregation:
    Weight each signal by the inverse of its Brier score (lower BS = better
    calibrated = higher weight). Weights are normalised to sum to 1.

Shannon Entropy:
    H(p) = -p·log₂(p) - (1-p)·log₂(1-p)

    H = 0 at certainty (p = 0 or p = 1), H = 1 at maximum uncertainty (p = 0.5).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

# ---------------------------------------------------------------------------
# Primitive conversions
# ---------------------------------------------------------------------------


def log_odds(p: float) -> float:
    """
    Convert a probability to log-odds (logit).

    log_odds(p) = log(p / (1 - p))

    Parameters
    ----------
    p : Probability in (0, 1). Values at the boundary are clamped to
        (1e-15, 1 - 1e-15) to avoid ±∞.

    Returns
    -------
    Log-odds as float in (-∞, +∞).

    Examples
    --------
    >>> log_odds(0.5)
    0.0
    >>> log_odds(0.9)
    2.197...
    """
    p_clamped = float(np.clip(p, 1e-15, 1.0 - 1e-15))
    return math.log(p_clamped / (1.0 - p_clamped))


def log_odds_to_prob(lo: float) -> float:
    """
    Convert log-odds back to probability (inverse logit / sigmoid).

    prob(lo) = 1 / (1 + exp(-lo))

    Parameters
    ----------
    lo : Log-odds value. Extreme values (|lo| > 700) are handled via clamping
         to prevent overflow.

    Returns
    -------
    Probability in (0, 1).

    Examples
    --------
    >>> log_odds_to_prob(0.0)
    0.5
    >>> log_odds_to_prob(log_odds(0.9))
    0.9...
    """
    # Numerically stable sigmoid
    lo_clamped = float(np.clip(lo, -500.0, 500.0))
    return float(1.0 / (1.0 + math.exp(-lo_clamped)))


# ---------------------------------------------------------------------------
# Bayesian updating
# ---------------------------------------------------------------------------


def bayesian_update(
    prior: float,
    likelihood_ratios: Sequence[float],
) -> float:
    """
    Update a prior probability with a sequence of likelihood ratios.

    Performs sequential Bayesian updating in log-odds space for numerical
    stability:

        LO_posterior = LO_prior + Σ_i log(LR_i)

    Parameters
    ----------
    prior             : Prior probability P(H) in (0, 1).
    likelihood_ratios : Sequence of likelihood ratios LR_i = P(E_i|H)/P(E_i|¬H).
                        LR > 1 is evidence for H, LR < 1 is evidence against H.
                        LR = 1 is uninformative (neutral).

    Returns
    -------
    Posterior probability P(H|E_1,...,E_n) in (0, 1).

    Raises
    ------
    ValueError
        If any likelihood ratio is ≤ 0.

    Notes
    -----
    Assumes conditional independence of evidence given the hypothesis.
    For correlated signals, prefer aggregate_signals() which includes
    a Brier-score based confidence weighting.

    Examples
    --------
    >>> bayesian_update(0.5, [3.0, 2.0])   # two confirming signals
    0.857...
    """
    lrs = list(likelihood_ratios)
    if any(lr <= 0 for lr in lrs):
        raise ValueError("All likelihood ratios must be > 0")

    lo = log_odds(prior)
    for lr in lrs:
        lo += math.log(lr)

    return log_odds_to_prob(lo)


# ---------------------------------------------------------------------------
# Confidence-weighted aggregation
# ---------------------------------------------------------------------------


def aggregate_signals(
    signals: Sequence[float],
    brier_scores: Sequence[float],
    prior: float = 0.5,
) -> float:
    """
    Aggregate multiple probability signals weighted by their calibration quality.

    Weights are the inverse of each signal source's Brier score (better
    calibrated sources get higher weight). Aggregation is performed as a
    weighted average in probability space, then combined with the prior via
    a single Bayesian update step.

    Strategy:
    1. Compute weights w_i = 1 / BS_i, normalised so Σw_i = 1.
    2. Compute weighted consensus probability: p_consensus = Σ w_i · s_i.
    3. Convert consensus to likelihood ratio: LR = p_consensus / (1 - p_consensus).
    4. Update prior with that single LR.

    Parameters
    ----------
    signals      : Sequence of probability estimates s_i ∈ (0, 1), one per source.
    brier_scores : Sequence of Brier scores BS_i > 0 for each source.
                   Must be the same length as signals.
                   Lower BS = better calibrated = higher weight.
    prior        : Prior probability P(H). Default 0.5 (uninformative).

    Returns
    -------
    Posterior probability in (0, 1).

    Raises
    ------
    ValueError
        If lengths differ, any Brier score ≤ 0, or signals are out of range.

    Examples
    --------
    >>> aggregate_signals([0.7, 0.8], [0.05, 0.02], prior=0.5)
    0.77...
    """
    s = np.asarray(signals, dtype=float)
    bs = np.asarray(brier_scores, dtype=float)

    if len(s) != len(bs):
        raise ValueError(
            f"signals and brier_scores must have the same length, got {len(s)} and {len(bs)}"
        )
    if len(s) == 0:
        return float(prior)
    if np.any(bs <= 0):
        raise ValueError("All Brier scores must be > 0")
    if np.any((s <= 0) | (s >= 1)):
        raise ValueError("All signals must be in (0, 1)")

    weights = 1.0 / bs
    weights = weights / weights.sum()

    p_consensus = float(np.dot(weights, s))
    # Guard against exact 0 or 1 after weighting
    p_consensus = float(np.clip(p_consensus, 1e-15, 1.0 - 1e-15))

    lr = p_consensus / (1.0 - p_consensus)
    return bayesian_update(prior, [lr])


# ---------------------------------------------------------------------------
# Uncertainty quantification
# ---------------------------------------------------------------------------


def entropy(p: float) -> float:
    """
    Compute binary Shannon entropy in bits.

    H(p) = -p·log₂(p) - (1-p)·log₂(1-p)

    Parameters
    ----------
    p : Probability in [0, 1]. p = 0 or p = 1 returns 0.0 (certainty).
        p = 0.5 returns 1.0 (maximum uncertainty).

    Returns
    -------
    Entropy in [0, 1] bits.

    Examples
    --------
    >>> entropy(0.5)
    1.0
    >>> entropy(0.0)
    0.0
    >>> entropy(1.0)
    0.0
    """
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return float(-p * math.log2(p) - (1.0 - p) * math.log2(1.0 - p))


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------


def posterior_summary(
    prior: float,
    evidence_list: Sequence[float],
    brier_scores: Sequence[float] | None = None,
) -> dict[str, float]:
    """
    Compute a full posterior summary from a prior and a sequence of signals.

    If brier_scores is provided, uses confidence-weighted aggregation
    (aggregate_signals). Otherwise treats each value in evidence_list as a
    likelihood ratio and uses bayesian_update.

    Parameters
    ----------
    prior         : Prior probability in (0, 1).
    evidence_list : Either:
                    - Probability estimates from each signal source (0, 1)
                      when brier_scores is provided.
                    - Likelihood ratios LR > 0 when brier_scores is None.
    brier_scores  : Brier scores for each signal source. Optional.

    Returns
    -------
    dict with keys:
        'posterior'  : float — posterior probability in (0, 1)
        'log_odds'   : float — posterior in log-odds representation
        'entropy'    : float — Shannon entropy of posterior (bits)
        'n_signals'  : int   — number of evidence items processed

    Examples
    --------
    >>> posterior_summary(0.5, [0.7, 0.8], brier_scores=[0.05, 0.02])
    {'posterior': 0.77..., 'log_odds': 1.2..., 'entropy': 0.9..., 'n_signals': 2}
    """
    if brier_scores is not None:
        posterior = aggregate_signals(evidence_list, brier_scores, prior=prior)
    else:
        posterior = bayesian_update(prior, evidence_list)

    return {
        "posterior": posterior,
        "log_odds": log_odds(posterior),
        "entropy": entropy(posterior),
        "n_signals": len(list(evidence_list)),
    }
