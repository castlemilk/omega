"""
omega.nodes.victoria.hmm_regime
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Hidden Markov Model regime detector — 3-state Gaussian HMM (bull/bear/sideways).

This is a first-class Wave 1 signal node in the Victoria DAG.  It operates on
raw OHLCV close prices (same dependency as ``basic_signals``, ``order_flow``,
etc.) and is intentionally distinct from the Wasserstein regime detector, which
operates on the *derived signal vector*.  The two detectors model different
aspects:

  - HMM         : latent state in the *return* process (Gaussian emissions)
  - Wasserstein : nearest-neighbour in *signal space* (distribution distance)

When they agree: high-confidence regime identification.
When they disagree: regime transition in progress (surfaced via the
``hmm_wasserstein_divergence`` Wave 3 node).

Algorithm
---------
1. Collect rolling window of log-returns from BTC close prices (default 120 bars).
2. Fit a 3-state GaussianHMM every ``refit_every`` cycles (default 20).
   - Uses ``hmmlearn`` if available; falls back to a pure-numpy EM/GMM.
3. Label states deterministically: highest-mean state → bull, lowest → bear,
   middle → sideways (stable across re-fits).
4. Viterbi-decode the window to get the most likely state sequence; read the
   last element for ``current_state``.
5. Track ``state_duration``: how many consecutive cycles the current state has
   been active.
6. Emit ``fit_quality`` (normalised log-likelihood) so callers can gate on
   model freshness.

References
----------
Baum, L. & Petrie, T. (1966) "Statistical Inference for Probabilistic Functions
of Finite State Markov Chains".  Hamilton, J.D. (1989) "A New Approach to the
Economic Analysis of Nonstationary Time Series and the Business Cycle".
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger("omega.nodes.victoria.hmm_regime")

# ---------------------------------------------------------------------------
# Optional hmmlearn import
# ---------------------------------------------------------------------------

try:
    from hmmlearn import hmm as _hmmlearn_hmm

    _HMMLEARN_AVAILABLE = True
    logger.debug("hmmlearn available — using GaussianHMM")
except ImportError:
    _HMMLEARN_AVAILABLE = False
    logger.warning("hmmlearn not available — using numpy GMM fallback")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BULL = "bull"
BEAR = "bear"
SIDEWAYS = "sideways"
REGIMES = [BULL, BEAR, SIDEWAYS]

_N_STATES = 3
_MIN_FIT_BARS = 30  # minimum bars needed before first fit
_DEFAULT_WINDOW = 120  # rolling bars used for fitting
_DEFAULT_REFIT_EVERY = 20  # refit model every N cycles
_DEFAULT_N_ITER = 50  # EM iterations for hmmlearn
_FALLBACK_N_ITER = 30  # EM iterations for numpy fallback


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class HMMRegimeResult:
    """Output of one HMMRegimeDetector update call."""

    current_state: str
    state_probs: list[float]  # [bull_prob, bear_prob, sideways_prob]
    transition_matrix: list[float]  # 3×3 row-major flat (9 elements)
    state_duration: int  # consecutive cycles in current_state
    fit_quality: float  # normalised log-likelihood (nats per sample); 0 if no fit yet
    bull_prob: float
    bear_prob: float
    sideways_prob: float
    source: str = "hmm"


# ---------------------------------------------------------------------------
# Numpy GMM fallback
# ---------------------------------------------------------------------------


class _NumpyGMM:
    """
    Lightweight Gaussian Mixture Model fitted via EM.

    This is a *stationary* mixture — it has no transition dynamics — but it
    provides a good approximation when hmmlearn is unavailable.  It gives us:
      - 3 Gaussians with distinct means/variances
      - Per-point posterior responsibilities (used as state probabilities)
      - A proxy transition matrix derived from the Viterbi-like state sequence
    """

    def __init__(self, n_components: int = 3, n_iter: int = _FALLBACK_N_ITER) -> None:
        self.n_components = n_components
        self.n_iter = n_iter
        self.means_: np.ndarray | None = None  # (K,)
        self.vars_: np.ndarray | None = None  # (K,)
        self.weights_: np.ndarray | None = None  # (K,)
        self._log_likelihood: float = -np.inf

    def fit(self, X: np.ndarray) -> "_NumpyGMM":
        """
        Fit GMM to 1-D data X using EM with k-means++ initialisation.

        Parameters
        ----------
        X : (n_samples,) array of log-returns
        """
        n = len(X)
        K = self.n_components

        # ----- Initialisation via k-means++ -----
        idx = np.random.default_rng(seed=42).choice(n, size=K, replace=False)
        means = X[idx].copy()
        for _ in range(10):  # Lloyd iterations
            dists = np.abs(X[:, None] - means[None, :])  # (n, K)
            labels = np.argmin(dists, axis=1)
            for k in range(K):
                mask = labels == k
                if mask.sum() > 0:
                    means[k] = X[mask].mean()

        vars_ = np.full(K, np.var(X) / K + 1e-8)
        weights = np.full(K, 1.0 / K)

        # ----- EM -----
        for _ in range(self.n_iter):
            # E-step: responsibilities
            log_likelihoods = -0.5 * np.log(2 * np.pi * vars_[None, :]) - 0.5 * (
                (X[:, None] - means[None, :]) ** 2 / vars_[None, :]
            )
            log_resp = np.log(weights[None, :] + 1e-300) + log_likelihoods
            log_resp -= log_resp.max(axis=1, keepdims=True)
            resp = np.exp(log_resp)
            resp /= resp.sum(axis=1, keepdims=True)

            # M-step
            Nk = resp.sum(axis=0) + 1e-10
            weights = Nk / Nk.sum()
            means = (resp * X[:, None]).sum(axis=0) / Nk
            vars_ = (resp * (X[:, None] - means[None, :]) ** 2).sum(axis=0) / Nk
            vars_ = np.maximum(vars_, 1e-8)

        self.means_ = means
        self.vars_ = vars_
        self.weights_ = weights

        # Compute log-likelihood
        ll = np.log(
            (
                weights[None, :]
                * (
                    np.exp(
                        -0.5 * (X[:, None] - means[None, :]) ** 2 / vars_[None, :]
                    )
                    / np.sqrt(2 * np.pi * vars_[None, :])
                )
            ).sum(axis=1)
            + 1e-300
        ).sum()
        self._log_likelihood = float(ll)
        return self

    def score(self, X: np.ndarray) -> float:
        """Return total log-likelihood."""
        if self.means_ is None:
            return -np.inf
        return self._log_likelihood

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return (n_samples, K) posterior responsibilities."""
        if self.means_ is None:
            return np.full((len(X), self.n_components), 1.0 / self.n_components)
        log_likelihoods = -0.5 * np.log(2 * np.pi * self.vars_[None, :]) - 0.5 * (
            (X[:, None] - self.means_[None, :]) ** 2 / self.vars_[None, :]
        )
        log_resp = np.log(self.weights_[None, :] + 1e-300) + log_likelihoods
        log_resp -= log_resp.max(axis=1, keepdims=True)
        resp = np.exp(log_resp)
        resp /= resp.sum(axis=1, keepdims=True)
        return resp

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return most likely component index per sample."""
        return np.argmax(self.predict_proba(X), axis=1)

    def transmat_from_sequence(self, state_seq: np.ndarray) -> np.ndarray:
        """
        Estimate a (K, K) transition matrix from an observed state sequence
        via counting (Laplace-smoothed).
        """
        K = self.n_components
        counts = np.ones((K, K))  # Laplace smoothing
        for i in range(len(state_seq) - 1):
            counts[state_seq[i], state_seq[i + 1]] += 1
        return counts / counts.sum(axis=1, keepdims=True)


# ---------------------------------------------------------------------------
# HMMRegimeDetector
# ---------------------------------------------------------------------------


class HMMRegimeDetector:
    """
    Rolling 3-state Gaussian HMM regime detector.

    Parameters
    ----------
    window : int
        Number of log-return bars to keep in the rolling window.
    refit_every : int
        Re-fit the model every ``refit_every`` update calls.
    min_fit_bars : int
        Minimum bars required before the first fit attempt.
    n_iter : int
        Maximum EM iterations when fitting the model.
    """

    def __init__(
        self,
        window: int = _DEFAULT_WINDOW,
        refit_every: int = _DEFAULT_REFIT_EVERY,
        min_fit_bars: int = _MIN_FIT_BARS,
        n_iter: int = _DEFAULT_N_ITER,
    ) -> None:
        self._window = window
        self._refit_every = refit_every
        self._min_fit_bars = min_fit_bars
        self._n_iter = n_iter

        self._close_prices: deque[float] = deque(maxlen=window + 1)  # extra slot for returns
        self._cycle_count: int = 0  # total update calls
        self._cycles_since_fit: int = refit_every  # trigger fit on first eligible call

        # Fitted model state
        self._model: Any = None  # GaussianHMM or _NumpyGMM
        self._state_label_map: dict[int, str] = {}  # model_state_index → regime label
        self._transmat: np.ndarray = np.full((_N_STATES, _N_STATES), 1.0 / _N_STATES)
        self._fit_quality: float = 0.0

        # Runtime state tracking
        self._current_state: str = SIDEWAYS
        self._state_duration: int = 0
        self._last_probs: dict[str, float] = {BULL: 1 / 3, BEAR: 1 / 3, SIDEWAYS: 1 / 3}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, market_data: dict[str, Any]) -> HMMRegimeResult:
        """
        Ingest one cycle's market data and return a regime estimate.

        Parameters
        ----------
        market_data : dict
            Same structure as ``ctx["market_data"]`` in the Victoria DAG.
            Looks for close prices under ``market_data["BTCUSDT"]["close"]``
            with fallback to ``market_data["close"]``.
        """
        closes = self._extract_closes(market_data)
        for c in closes:
            self._close_prices.append(c)

        self._cycle_count += 1
        self._cycles_since_fit += 1

        n_bars = len(self._close_prices)
        if n_bars < self._min_fit_bars + 1:
            return self._warmup_result(n_bars)

        # Re-fit model on schedule
        if self._cycles_since_fit >= self._refit_every or self._model is None:
            self._fit()
            self._cycles_since_fit = 0

        if self._model is None:
            return self._warmup_result(n_bars)

        # Decode current state from the latest returns
        returns = self._compute_returns()
        probs_vec = self._decode_probs(returns)

        new_state = REGIMES[int(np.argmax(probs_vec))]

        if new_state == self._current_state:
            self._state_duration += 1
        else:
            self._current_state = new_state
            self._state_duration = 1

        self._last_probs = {
            BULL: float(probs_vec[REGIMES.index(BULL)]),
            BEAR: float(probs_vec[REGIMES.index(BEAR)]),
            SIDEWAYS: float(probs_vec[REGIMES.index(SIDEWAYS)]),
        }

        transmat_flat = self._transmat_in_regime_order().flatten().tolist()

        logger.debug(
            "hmm_regime state=%s duration=%d bull=%.3f bear=%.3f sideways=%.3f fit_quality=%.4f",
            self._current_state,
            self._state_duration,
            self._last_probs[BULL],
            self._last_probs[BEAR],
            self._last_probs[SIDEWAYS],
            self._fit_quality,
        )

        return HMMRegimeResult(
            current_state=self._current_state,
            state_probs=[self._last_probs[BULL], self._last_probs[BEAR], self._last_probs[SIDEWAYS]],
            transition_matrix=transmat_flat,
            state_duration=self._state_duration,
            fit_quality=self._fit_quality,
            bull_prob=self._last_probs[BULL],
            bear_prob=self._last_probs[BEAR],
            sideways_prob=self._last_probs[SIDEWAYS],
        )

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def _fit(self) -> None:
        """Fit (or re-fit) the HMM/GMM on the current rolling return window."""
        returns = self._compute_returns()
        if len(returns) < self._min_fit_bars:
            return

        try:
            if _HMMLEARN_AVAILABLE:
                self._fit_hmmlearn(returns)
            else:
                self._fit_numpy(returns)
        except Exception as exc:
            logger.warning("hmm_regime fit failed: %s — keeping previous model", exc)

    def _fit_hmmlearn(self, returns: np.ndarray) -> None:
        """Fit hmmlearn GaussianHMM."""
        model = _hmmlearn_hmm.GaussianHMM(
            n_components=_N_STATES,
            covariance_type="full",
            n_iter=self._n_iter,
            random_state=42,
        )
        X = returns.reshape(-1, 1)
        model.fit(X)

        ll = model.score(X)
        self._fit_quality = float(ll / len(returns))
        self._model = model

        means = model.means_.flatten()  # (3,)
        self._state_label_map = self._label_states(means)
        self._transmat = np.array(model.transmat_)

        logger.info(
            "hmm_regime fitted (hmmlearn): fit_quality=%.4f states=%s",
            self._fit_quality,
            {v: round(float(means[k]), 5) for k, v in self._state_label_map.items()},
        )

    def _fit_numpy(self, returns: np.ndarray) -> None:
        """Fit numpy GMM fallback."""
        gmm = _NumpyGMM(n_components=_N_STATES, n_iter=self._n_iter)
        gmm.fit(returns)

        ll = gmm.score(returns)
        self._fit_quality = float(ll / len(returns))
        self._model = gmm

        means = gmm.means_  # (3,)
        self._state_label_map = self._label_states(means)

        state_seq = gmm.predict(returns)
        self._transmat = gmm.transmat_from_sequence(state_seq)

        logger.info(
            "hmm_regime fitted (numpy GMM): fit_quality=%.4f states=%s",
            self._fit_quality,
            {v: round(float(means[k]), 5) for k, v in self._state_label_map.items()},
        )

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------

    def _decode_probs(self, returns: np.ndarray) -> np.ndarray:
        """
        Return probability vector [bull_prob, bear_prob, sideways_prob] for the
        most recent bar, using the fitted model.
        """
        if self._model is None:
            return np.array([1 / 3, 1 / 3, 1 / 3])

        last_return = returns[-1:]  # shape (1,) or (1, 1)

        if _HMMLEARN_AVAILABLE and isinstance(self._model, _hmmlearn_hmm.GaussianHMM):
            # Use the posterior for the full sequence, take the last step
            try:
                log_probs, posteriors = self._model.score_samples(returns.reshape(-1, 1))
                raw_probs = posteriors[-1]  # (n_states,)
            except Exception:
                # Fallback to single-point scoring
                raw_probs = np.full(_N_STATES, 1.0 / _N_STATES)
        else:
            raw_probs = self._model.predict_proba(last_return)[0]

        # Re-index from model state order → [bull, bear, sideways] order
        out = np.zeros(3)
        for model_idx, label in self._state_label_map.items():
            regime_idx = REGIMES.index(label)
            out[regime_idx] = raw_probs[model_idx]

        # Normalise (should already sum to ~1 but guard against numerical drift)
        total = out.sum()
        if total > 0:
            out /= total
        else:
            out = np.array([1 / 3, 1 / 3, 1 / 3])

        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _label_states(means: np.ndarray) -> dict[int, str]:
        """
        Assign bull/bear/sideways labels to model state indices based on
        mean returns.  Highest mean → bull, lowest → bear, middle → sideways.

        This is deterministic — the labelling depends only on relative means,
        not on which index the model happens to assign.
        """
        order = np.argsort(means)  # ascending: [bear_idx, sideways_idx, bull_idx]
        return {
            int(order[0]): BEAR,
            int(order[1]): SIDEWAYS,
            int(order[2]): BULL,
        }

    def _compute_returns(self) -> np.ndarray:
        """Compute log-returns from the close price deque."""
        prices = np.array(list(self._close_prices), dtype=float)
        prices = np.where(prices > 0, prices, np.nan)
        valid = prices[~np.isnan(prices)]
        if len(valid) < 2:
            return np.array([0.0])
        returns = np.diff(np.log(valid))
        return returns

    def _transmat_in_regime_order(self) -> np.ndarray:
        """
        Return the 3×3 transition matrix with rows/columns reordered to
        [bull, bear, sideways] order (matching REGIMES constant).
        """
        if not self._state_label_map:
            return self._transmat
        regime_to_model = {v: k for k, v in self._state_label_map.items()}
        idx = [regime_to_model.get(r, 0) for r in REGIMES]
        return self._transmat[np.ix_(idx, idx)]

    @staticmethod
    def _extract_closes(market_data: dict[str, Any]) -> list[float]:
        """
        Extract BTC close prices from market_data.

        Follows the same lookup pattern used by ``signals_advanced.py``:
          market_data["BTCUSDT"]["close"]  → primary
          market_data["BTC-USDT"]["close"] → secondary
          market_data["close"]             → test/legacy fallback
        """
        for ticker_key in ("BTCUSDT", "BTC-USDT", "btcusdt", "BTC/USDT", "BTCUSD"):
            sub = market_data.get(ticker_key)
            if isinstance(sub, dict):
                closes = sub.get("close", [])
                if isinstance(closes, (list, np.ndarray)) and len(closes) > 0:
                    return [float(c) for c in closes if c]
        # Top-level fallback (used in unit tests)
        closes = market_data.get("close", [])
        if isinstance(closes, (list, np.ndarray)) and len(closes) > 0:
            return [float(c) for c in closes if c]
        return []

    def _warmup_result(self, n_bars: int) -> HMMRegimeResult:
        return HMMRegimeResult(
            current_state=SIDEWAYS,
            state_probs=[1 / 3, 1 / 3, 1 / 3],
            transition_matrix=[1 / 9] * 9,
            state_duration=0,
            fit_quality=0.0,
            bull_prob=1 / 3,
            bear_prob=1 / 3,
            sideways_prob=1 / 3,
            source=f"warmup({n_bars}/{self._min_fit_bars})",
        )
