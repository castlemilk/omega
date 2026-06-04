# Information Geometry and Natural Gradient for Signal Optimization

**Date:** 2026-04-13
**Research Series:** Omega Geometric Finance, Week 3
**Focus:** Applying information-geometric methods to Victoria's signal combination and parameter optimization

---

## 1. Executive Summary

Information geometry — the study of statistical manifolds equipped with the Fisher-Rao metric — provides the natural mathematical framework for optimizing signal combination weights, detecting regime shifts via distribution divergences, and performing parameter updates that respect the curved geometry of probability space. The core insight for Victoria is that **signal weights live on a statistical manifold, not in flat Euclidean space**, and optimization methods that ignore this geometry (plain SGD, grid search) are provably suboptimal. Natural gradient descent, which pre-multiplies gradients by the inverse Fisher information matrix, converges faster and produces more stable parameter trajectories — exactly the properties needed for online adaptation of trading signals.

This document covers the mathematical foundations of information geometry, its dual connection structure, practical applications to signal combination and regime detection, and concrete implementation paths using the `geomstats` library and custom lightweight code for Victoria's pipeline.

---

## 2. Mathematical Foundations

### 2.1 Statistical Manifolds and the Fisher-Rao Metric

A **statistical manifold** $\mathcal{S}$ is a smooth manifold whose points are probability distributions. For a parametric family $\{p_\theta : \theta \in \Theta \subset \mathbb{R}^n\}$, the manifold inherits a natural Riemannian structure.

**Fisher Information Matrix (FIM):** The metric tensor on $\mathcal{S}$ is:

$$g_{ij}(\theta) = \mathbb{E}_{p_\theta}\left[\frac{\partial \log p_\theta(x)}{\partial \theta_i} \cdot \frac{\partial \log p_\theta(x)}{\partial \theta_j}\right] = -\mathbb{E}_{p_\theta}\left[\frac{\partial^2 \log p_\theta(x)}{\partial \theta_i \partial \theta_j}\right]$$

This is the unique (up to scaling) Riemannian metric on $\mathcal{S}$ that is invariant under sufficient statistics — the Chentsov-Amari theorem. The Fisher-Rao distance between two distributions is the geodesic distance under this metric, and it captures the intrinsic difficulty of distinguishing them.

**Why this matters for trading:** When Victoria combines $n$ sub-signals with weights $w = (w_1, \ldots, w_n)$ living on the simplex $\Delta^{n-1}$, the performance landscape is inherently curved. The Fisher metric tells us which directions in weight space are "easy" (high Fisher information = signals are informative) vs. "hard" (low Fisher information = noisy/redundant signals). Ignoring this geometry leads to oscillatory, unstable optimization.

### 2.2 The Alpha-Connection Family

Amari's key insight: statistical manifolds carry not one but an entire family of affine connections $\nabla^{(\alpha)}$ parametrized by $\alpha \in \mathbb{R}$:

$$\Gamma_{ij,k}^{(\alpha)} = \mathbb{E}\left[\left(\partial_i \partial_j \ell + \frac{1-\alpha}{2}\partial_i \ell \cdot \partial_j \ell\right)\partial_k \ell\right]$$

where $\ell = \log p_\theta(x)$. Special cases:

- $\alpha = 0$: Levi-Civita connection (Riemannian geometry)
- $\alpha = 1$: exponential connection (e-connection), flat for exponential families
- $\alpha = -1$: mixture connection (m-connection), flat for mixture families

The pair $(\nabla^{(1)}, \nabla^{(-1)})$ forms a **dually flat structure**: the e-connection is flat in natural parameters $\eta$, the m-connection is flat in expectation parameters $\mu$, and they are dual with respect to the Fisher metric.

### 2.3 Dually Flat Structure and Bregman Divergences

When $\mathcal{S}$ is dually flat, we get the powerful toolkit:

**Bregman divergence:** For convex potential $\psi(\eta)$ (log-partition function for exponential families):

$$D_\psi(\theta \| \theta') = \psi(\eta(\theta)) - \psi(\eta(\theta')) - \langle \nabla\psi(\eta(\theta')), \eta(\theta) - \eta(\theta')\rangle$$

The KL divergence $D_{KL}(p \| q)$ is exactly the Bregman divergence for the negative entropy potential on exponential families.

**Pythagorean theorem:** For three points $P, Q, R$ on a dually flat manifold:

$$D(P \| R) = D(P \| Q) + D(Q \| R)$$

when $Q$ is the e-projection of $P$ onto the m-geodesic through $Q$ and $R$. This decomposition is the information-geometric basis for bias-variance tradeoffs and model selection.

### 2.4 Natural Gradient Descent

Standard gradient descent updates $\theta_{t+1} = \theta_t - \eta \nabla_\theta L$ using the Euclidean gradient. But on a statistical manifold, the steepest descent direction depends on the metric. The **natural gradient** is:

$$\tilde{\nabla}_\theta L = G(\theta)^{-1} \nabla_\theta L$$

where $G(\theta)$ is the Fisher information matrix. The update becomes:

$$\theta_{t+1} = \theta_t - \eta \cdot G(\theta_t)^{-1} \nabla_\theta L(\theta_t)$$

**Properties:**
- **Fisher-efficient:** converges to the Cramér-Rao lower bound asymptotically
- **Parameterization-invariant:** same trajectory regardless of coordinate choice
- **Faster convergence:** $O(1/t)$ vs. $O(1/\sqrt{t})$ for vanilla SGD on well-conditioned problems
- **No plateau problem:** avoids the slow convergence near saddle points that plagues SGD on probability manifolds

---

## 3. Key Literature

### 3.1 Foundational Works

**Amari (1998)** — "Natural Gradient Works Efficiently in Learning." Neural Computation, 10(2). The original paper establishing natural gradient descent. Proved that on statistical manifolds, the natural gradient is the steepest descent direction with respect to the KL divergence, and that it achieves asymptotically optimal convergence.

**Amari (2016)** — *Information Geometry and Its Applications.* Springer. The definitive textbook covering the full theory: alpha-connections, dually flat manifolds, divergence functions, and applications to statistics, machine learning, and signal processing.

**Nielsen (2018)** — "An Elementary Introduction to Information Geometry." arXiv: 1808.08271. Accessible survey covering the essential concepts with concrete examples.

### 3.2 Computational Tools

**Miolane et al. (2020, updated 2024)** — "Geomstats: A Python Package for Riemannian Geometry in Machine Learning." JMLR, 21(223). Open-source Python library implementing Riemannian geometry on manifolds including the Fisher-Rao information manifold. Supports geodesics, parallel transport, exponential/logarithmic maps, and statistical estimation on manifolds. Backends: NumPy, PyTorch, TensorFlow.

**Miolane et al. (2024)** — "Parametric Information Geometry with the Package Geomstats." ACM Transactions on Mathematical Software. Extended information geometry module with Fisher-Rao manifolds for normal, gamma, beta, Dirichlet, and other parametric families.

### 3.3 Natural Gradient Approximations (2024-2025)

**NeurIPS 2024** — "An Improved Empirical Fisher Approximation for Natural Gradient Descent." Shows that the empirical Fisher (using squared gradients) can be corrected to better approximate the true Fisher, making natural gradient practical for large-scale models.

**Luo et al. (2025)** — "Fisher-Orthogonal Projection Methods for Natural Gradient Descent with Large Batches." arXiv: 2508.13898. New method that consistently outperforms KFAC and AdamW across batch sizes >512 by projecting onto the Fisher-orthogonal complement.

**Squisher (2025)** — Efficiently approximates Fisher diagonal by recycling adaptive gradient optimizer statistics with negligible extra cost, making natural gradient nearly free on top of Adam/AdaGrad.

### 3.4 Financial Applications

**Clustering Financial Return Distributions Using the Fisher Information Metric (2020)** — Entropy, 22(9). Demonstrates that Fisher-Rao distance between fitted return distributions provides better clustering of financial assets than Euclidean distance on raw returns, capturing distributional shape differences (skewness, kurtosis) that Euclidean metrics miss.

**Short-term Kullback-Leibler Divergence Analysis to Extract Unstable Periods in Financial Time Series (2024)** — Evolutionary and Institutional Economics Review. Uses sliding-window KL divergence to detect regime transitions in financial markets, with Monte Carlo significance testing.

**Instability of Financial Time Series Revealed by Irreversibility Analysis (2025)** — Entropy, 27(4), 402. Integrates KL divergence with time-reversibility metrics to detect market instabilities, correlating detected events with known economic incidents.

---

## 4. Application to Victoria's Signal Pipeline

### 4.1 Signal Weights as Points on a Simplex Manifold

Victoria combines $n$ sub-signals with weights $w \in \Delta^{n-1}$ (the probability simplex). The simplex is **not flat** — it has the geometry of a dually flat manifold when equipped with the Fisher metric of the categorical distribution.

The natural parameters are $\eta_i = \log(w_i/w_n)$ (log-odds), and the Fisher metric in these coordinates is diagonal with entries $g_{ii} = 1/w_i + 1/w_n$. This means that small weights deserve more careful updates (high metric curvature) while large weights can absorb bigger changes — exactly the behavior we want for stable signal combination.

### 4.2 Natural Gradient for IC-Weighted Signal Combination

Victoria's current approach uses Information Coefficient (IC) weighting. We can formalize this as natural gradient optimization:

```python
import numpy as np
from scipy.special import softmax

class NaturalGradientSignalOptimizer:
    """
    Optimize signal combination weights using natural gradient descent
    on the probability simplex with Fisher-Rao metric.
    """
    
    def __init__(self, n_signals: int, learning_rate: float = 0.01):
        self.n = n_signals
        self.lr = learning_rate
        # Natural parameters (log-odds relative to last signal)
        self.eta = np.zeros(n_signals)
        # Running Fisher information estimate
        self.fisher_diag = np.ones(n_signals)
        self.fisher_ema_decay = 0.95
    
    @property
    def weights(self) -> np.ndarray:
        """Current signal weights (softmax of natural parameters)."""
        return softmax(self.eta)
    
    def compute_fisher(self, w: np.ndarray) -> np.ndarray:
        """
        Fisher information matrix for categorical distribution.
        For the softmax parameterization, F = diag(w) - w @ w.T
        Diagonal approximation: F_ii ≈ w_i * (1 - w_i)
        """
        return w * (1.0 - w) + 1e-8  # diagonal approx + regularization
    
    def update(self, signal_returns: np.ndarray, portfolio_return: float):
        """
        Perform one natural gradient step.
        
        signal_returns: array of shape (n_signals,), return of each signal
        portfolio_return: combined portfolio return (for loss gradient)
        """
        w = self.weights
        
        # Euclidean gradient of loss w.r.t. natural parameters
        # Loss = -portfolio_return (we want to maximize return)
        # d(loss)/d(eta_i) = -signal_returns[i] * w[i] + portfolio_return * w[i]
        #                   = w[i] * (portfolio_return - signal_returns[i])
        grad = w * (portfolio_return - signal_returns)
        
        # Update Fisher estimate (exponential moving average)
        fisher_sample = self.compute_fisher(w)
        self.fisher_diag = (
            self.fisher_ema_decay * self.fisher_diag
            + (1 - self.fisher_ema_decay) * fisher_sample
        )
        
        # Natural gradient = F^{-1} @ grad
        natural_grad = grad / self.fisher_diag
        
        # Update natural parameters
        self.eta -= self.lr * natural_grad
    
    def get_signal_importance(self) -> np.ndarray:
        """
        Fisher information per signal — measures how informative
        each signal is for the portfolio objective.
        Higher Fisher info = more informative signal.
        """
        return self.fisher_diag


class OnlineNaturalGradientCombiner:
    """
    Full online signal combiner with regime-aware natural gradient.
    Integrates with Victoria's conviction filter pipeline.
    """
    
    def __init__(
        self,
        signal_names: list[str],
        regime_lr: dict[str, float] = None,
    ):
        self.signal_names = signal_names
        self.n = len(signal_names)
        self.optimizer = NaturalGradientSignalOptimizer(self.n)
        
        # Regime-specific learning rates
        # Crisis: slow adaptation (preserve stability)
        # Normal: moderate adaptation
        # High_vol: fast adaptation (conditions changing)
        self.regime_lr = regime_lr or {
            'crisis': 0.002,
            'high_vol': 0.02,
            'normal': 0.01,
        }
    
    def combine_signals(
        self,
        signals: dict[str, float],
        regime: str = 'normal'
    ) -> float:
        """
        Combine sub-signals using current weights.
        Returns weighted conviction score.
        """
        w = self.optimizer.weights
        values = np.array([signals[name] for name in self.signal_names])
        return float(np.dot(w, values))
    
    def update_weights(
        self,
        signals: dict[str, float],
        realized_return: float,
        regime: str = 'normal'
    ):
        """
        Update weights based on realized outcome.
        Uses regime-adaptive learning rate.
        """
        self.optimizer.lr = self.regime_lr.get(regime, 0.01)
        signal_arr = np.array([signals[name] for name in self.signal_names])
        combined = float(np.dot(self.optimizer.weights, signal_arr))
        self.optimizer.update(signal_arr, realized_return)
    
    def get_diagnostics(self) -> dict:
        """Return current state for observability."""
        w = self.optimizer.weights
        fi = self.optimizer.get_signal_importance()
        return {
            'weights': {
                name: float(w[i])
                for i, name in enumerate(self.signal_names)
            },
            'fisher_info': {
                name: float(fi[i])
                for i, name in enumerate(self.signal_names)
            },
            'weight_entropy': float(-np.sum(w * np.log(w + 1e-10))),
            'effective_signals': float(np.exp(-np.sum(w * np.log(w + 1e-10)))),
        }
```

### 4.3 KL Divergence Regime Detection

Use the information-geometric distance between return distributions to detect regime transitions:

```python
import numpy as np
from scipy.stats import norm

class InfoGeometricRegimeDetector:
    """
    Detect regime transitions using KL divergence and Fisher-Rao
    distance between windowed return distributions.
    """
    
    def __init__(
        self,
        short_window: int = 20,
        long_window: int = 100,
        kl_threshold: float = 0.5,
        fisher_rao_threshold: float = 1.0,
    ):
        self.short_window = short_window
        self.long_window = long_window
        self.kl_threshold = kl_threshold
        self.fr_threshold = fisher_rao_threshold
        self.returns_buffer: list[float] = []
    
    def _fit_normal(self, returns: np.ndarray) -> tuple[float, float]:
        """Fit Gaussian to returns window."""
        mu = np.mean(returns)
        sigma = np.std(returns) + 1e-10
        return mu, sigma
    
    def kl_divergence_normal(
        self,
        mu1: float, sig1: float,
        mu2: float, sig2: float
    ) -> float:
        """
        KL(N(mu1,sig1^2) || N(mu2,sig2^2))
        Closed-form for univariate normals.
        """
        return (
            np.log(sig2 / sig1)
            + (sig1**2 + (mu1 - mu2)**2) / (2 * sig2**2)
            - 0.5
        )
    
    def fisher_rao_distance_normal(
        self,
        mu1: float, sig1: float,
        mu2: float, sig2: float
    ) -> float:
        """
        Fisher-Rao geodesic distance between two univariate normals.
        
        For the normal family, the Fisher-Rao metric is:
          ds^2 = (1/sigma^2) dmu^2 + (2/sigma^2) dsigma^2
        
        This is the Poincare half-plane metric (up to scaling),
        making the space of normals isometric to the hyperbolic plane H^2.
        
        Closed-form geodesic distance:
          d(p1, p2) = sqrt(2) * arccosh(1 + (mu1-mu2)^2/(2*sig1*sig2)
                       + (sig1^2 + sig2^2)/(2*sig1*sig2) - 1)
        
        Simplified for sig1 ≈ sig2 ≈ sig:
          d ≈ |mu1 - mu2| / sig  (Mahalanobis-like)
        """
        delta_mu = mu1 - mu2
        ratio = (sig1**2 + sig2**2) / (2 * sig1 * sig2)
        arg = ratio + delta_mu**2 / (2 * sig1 * sig2)
        # arccosh(x) = log(x + sqrt(x^2 - 1))
        arg = max(arg, 1.0)  # numerical safety
        return np.sqrt(2) * np.arccosh(arg)
    
    def symmetric_kl(
        self,
        mu1: float, sig1: float,
        mu2: float, sig2: float
    ) -> float:
        """Jensen-Shannon-like symmetric KL divergence."""
        return 0.5 * (
            self.kl_divergence_normal(mu1, sig1, mu2, sig2)
            + self.kl_divergence_normal(mu2, sig2, mu1, sig1)
        )
    
    def update(self, return_value: float) -> dict:
        """
        Add new return observation, compute regime signals.
        
        Returns dict with:
          kl_divergence: asymmetric KL(short || long)
          symmetric_kl: symmetrized KL
          fisher_rao_dist: geodesic distance on normal manifold
          regime_shift: bool, whether a shift is detected
          shift_direction: 'expansion' or 'contraction' or None
        """
        self.returns_buffer.append(return_value)
        
        # Need enough data
        if len(self.returns_buffer) < self.long_window:
            return {
                'kl_divergence': 0.0,
                'symmetric_kl': 0.0,
                'fisher_rao_dist': 0.0,
                'regime_shift': False,
                'shift_direction': None,
            }
        
        recent = np.array(self.returns_buffer[-self.short_window:])
        baseline = np.array(self.returns_buffer[-self.long_window:])
        
        mu_r, sig_r = self._fit_normal(recent)
        mu_b, sig_b = self._fit_normal(baseline)
        
        kl = self.kl_divergence_normal(mu_r, sig_r, mu_b, sig_b)
        skl = self.symmetric_kl(mu_r, sig_r, mu_b, sig_b)
        fr = self.fisher_rao_distance_normal(mu_r, sig_r, mu_b, sig_b)
        
        # Detect shift
        shift = fr > self.fr_threshold or kl > self.kl_threshold
        
        # Direction: expansion (vol up) or contraction (vol down)
        direction = None
        if shift:
            direction = 'expansion' if sig_r > sig_b else 'contraction'
        
        return {
            'kl_divergence': float(kl),
            'symmetric_kl': float(skl),
            'fisher_rao_dist': float(fr),
            'regime_shift': shift,
            'shift_direction': direction,
            'recent_mu': float(mu_r),
            'recent_sigma': float(sig_r),
            'baseline_mu': float(mu_b),
            'baseline_sigma': float(sig_b),
        }
```

### 4.4 Multivariate Fisher-Rao Distance for Cross-Asset Regime Detection

```python
import numpy as np

def multivariate_kl_normal(
    mu1: np.ndarray, cov1: np.ndarray,
    mu2: np.ndarray, cov2: np.ndarray,
) -> float:
    """
    KL(N(mu1, cov1) || N(mu2, cov2)) for d-dimensional normals.
    
    KL = 0.5 * (tr(cov2^{-1} cov1) + (mu2-mu1)^T cov2^{-1} (mu2-mu1)
               - d + log(det(cov2)/det(cov1)))
    """
    d = len(mu1)
    cov2_inv = np.linalg.inv(cov2 + 1e-6 * np.eye(d))
    delta = mu2 - mu1
    
    term1 = np.trace(cov2_inv @ cov1)
    term2 = delta @ cov2_inv @ delta
    term3 = np.log(np.linalg.det(cov2) / (np.linalg.det(cov1) + 1e-30) + 1e-30)
    
    return 0.5 * (term1 + term2 - d + term3)


class MultiAssetRegimeDetector:
    """
    Detect regime shifts in a multi-asset universe using
    information-geometric distance between joint return distributions.
    
    Key insight: the normal manifold N(mu, Sigma) for d assets has
    dimension d + d(d+1)/2 = d(d+3)/2. The Fisher-Rao metric
    captures changes in both location (returns) and shape
    (correlations, volatilities).
    """
    
    def __init__(
        self,
        asset_names: list[str],
        short_window: int = 20,
        long_window: int = 100,
    ):
        self.assets = asset_names
        self.d = len(asset_names)
        self.short_window = short_window
        self.long_window = long_window
        self.buffer: list[np.ndarray] = []
    
    def update(self, returns: dict[str, float]) -> dict:
        """
        Add multi-asset return observation, compute regime signals.
        """
        r = np.array([returns[a] for a in self.assets])
        self.buffer.append(r)
        
        if len(self.buffer) < self.long_window:
            return {'kl_divergence': 0.0, 'regime_shift': False}
        
        recent = np.array(self.buffer[-self.short_window:])
        baseline = np.array(self.buffer[-self.long_window:])
        
        mu_r, cov_r = np.mean(recent, axis=0), np.cov(recent.T)
        mu_b, cov_b = np.mean(baseline, axis=0), np.cov(baseline.T)
        
        # Ensure positive definiteness
        cov_r += 1e-6 * np.eye(self.d)
        cov_b += 1e-6 * np.eye(self.d)
        
        kl = multivariate_kl_normal(mu_r, cov_r, mu_b, cov_b)
        
        # Decompose: correlation change vs volatility change vs mean change
        # Standardize to isolate correlation
        std_r = np.sqrt(np.diag(cov_r))
        std_b = np.sqrt(np.diag(cov_b))
        corr_r = cov_r / np.outer(std_r, std_r)
        corr_b = cov_b / np.outer(std_b, std_b)
        
        # Frobenius distance between correlation matrices
        corr_dist = np.linalg.norm(corr_r - corr_b, 'fro')
        
        # Volatility ratio (geometric mean across assets)
        vol_ratio = np.exp(np.mean(np.log(std_r / std_b)))
        
        return {
            'kl_divergence': float(kl),
            'correlation_distance': float(corr_dist),
            'volatility_ratio': float(vol_ratio),
            'mean_shift': float(np.linalg.norm(mu_r - mu_b)),
            'regime_shift': kl > 2.0 * self.d,  # Scale threshold with dimension
        }
```

### 4.5 Information-Geometric Signal Quality Assessment

```python
import numpy as np

def signal_fisher_information(
    signal_values: np.ndarray,
    realized_returns: np.ndarray,
    n_bins: int = 20,
) -> float:
    """
    Estimate the Fisher information that a signal carries about
    future returns. Higher Fisher info = more informative signal.
    
    Method: discretize signal into bins, fit conditional return
    distribution p(return | signal_bin), compute Fisher info
    of the signal-indexed family.
    
    This gives a principled, information-geometric measure of
    signal quality that generalizes the Information Coefficient.
    """
    # Discretize signal into quantiles
    quantiles = np.linspace(0, 100, n_bins + 1)
    bin_edges = np.percentile(signal_values, quantiles)
    bin_indices = np.digitize(signal_values, bin_edges[1:-1])
    
    # Fit conditional distributions
    conditional_params = []
    for b in range(n_bins):
        mask = bin_indices == b
        if mask.sum() < 5:
            continue
        mu = np.mean(realized_returns[mask])
        sigma = np.std(realized_returns[mask]) + 1e-10
        conditional_params.append((mu, sigma, mask.sum()))
    
    if len(conditional_params) < 3:
        return 0.0
    
    # Fisher information: average of (d log p / d theta)^2
    # For the signal-indexed family, this measures how much
    # the return distribution changes as we move along the signal axis
    fisher = 0.0
    total_weight = sum(p[2] for p in conditional_params)
    
    for i in range(len(conditional_params) - 1):
        mu1, sig1, n1 = conditional_params[i]
        mu2, sig2, n2 = conditional_params[i + 1]
        
        # Approximate Fisher info as squared rate of change
        # of the natural parameters
        d_eta1 = (mu2 - mu1) / ((sig1 + sig2) / 2)  # change in mean/sigma
        d_eta2 = np.log(sig2 / sig1)  # change in log-sigma
        
        weight = (n1 + n2) / (2 * total_weight)
        fisher += weight * (d_eta1**2 + 2 * d_eta2**2)
    
    return float(fisher)


def rank_signals_by_fisher_info(
    signals: dict[str, np.ndarray],
    returns: np.ndarray,
) -> list[tuple[str, float]]:
    """
    Rank all signals by their Fisher information content.
    This is a principled replacement for simple IC ranking.
    """
    rankings = []
    for name, values in signals.items():
        fi = signal_fisher_information(values, returns)
        rankings.append((name, fi))
    
    rankings.sort(key=lambda x: x[1], reverse=True)
    return rankings
```

---

## 5. Integration with Victoria's Architecture

### 5.1 Where Information Geometry Fits

Victoria's conviction filter pipeline currently has four stages: time filter, agreement ratio, weighted conviction, and regime/vol gate. Information geometry enhances stages 2-4:

| Pipeline Stage | Current Approach | IG Enhancement |
|---|---|---|
| Agreement ratio | Count of sub-signals agreeing on direction | Fisher-Rao distance between bullish/bearish signal clusters |
| Weighted conviction | IC-weighted composite | Natural gradient-optimized weights on simplex manifold |
| Regime/vol gate | Fixed regime-adaptive thresholds | KL divergence-based regime detection with continuous transition scores |
| (New) Signal quality | Per-signal IC | Fisher information of signal-indexed return family |

### 5.2 Node Registration

```yaml
# In projects/victoria.yaml
signals:
  - name: info_geometry_regime
    type: signal
    description: "KL divergence and Fisher-Rao regime shift detector"
    inputs:
      - multi_asset_returns
    outputs:
      - kl_divergence
      - fisher_rao_distance
      - regime_shift_score
      - correlation_distance
    update_frequency: 5m

  - name: natural_gradient_combiner
    type: optimizer
    description: "Natural gradient signal weight optimizer on Fisher-Rao simplex"
    inputs:
      - sub_signal_values
      - realized_returns
      - current_regime
    outputs:
      - optimized_weights
      - signal_fisher_info
      - weight_diagnostics
    update_frequency: 1h  # Slower update for stability
```

### 5.3 File Layout

```
omega/nodes/victoria/signals/
    info_geometry_regime.py      # KL divergence regime detection
    natural_gradient_combiner.py # Natural gradient weight optimization
    fisher_signal_quality.py     # Fisher info signal ranking
omega/nodes/victoria/lib/
    fisher_rao.py                # Core Fisher-Rao metric computations
    natural_gradient.py          # Natural gradient optimizer
```

---

## 6. Connection to the Poincare Half-Plane

An elegant fact: the Fisher-Rao geometry of the univariate normal family $\{N(\mu, \sigma^2)\}$ is **isometric to the Poincare half-plane** $\mathbb{H}^2$ — the standard model of hyperbolic geometry. The mapping is:

$$(\mu, \sigma) \mapsto (\mu, \sqrt{2}\sigma) \in \mathbb{H}^2$$

with metric $ds^2 = (d\mu^2 + 2d\sigma^2)/\sigma^2$.

This means:
- **Geodesics** between normal distributions are semicircles (in the half-plane model)
- **Regime transitions** trace paths on the hyperbolic plane
- **Distance** between regimes grows logarithmically as volatility differs — a natural "compression" that prevents high-vol regimes from dominating
- **Hyperbolic embeddings** of return distributions (e.g., via Poincare ball models) could provide dimensionality reduction that preserves information-geometric structure

For Victoria, this means the space of possible market regimes (parameterized by return mean and volatility) has **hyperbolic geometry**. Recent ML work on hyperbolic neural networks could be leveraged for regime classification that respects this geometry.

---

## 7. Advanced: e-Mixture Optimal Signal Combination

On the exponential family manifold, the optimal combination of two distributions $p_1$ and $p_2$ can be computed via:

**e-mixture** (exponential mixture): $p_e = p_1^w \cdot p_2^{1-w} / Z$ — this is the e-geodesic on the manifold, corresponding to combining in natural parameter space.

**m-mixture** (mixture): $p_m = w \cdot p_1 + (1-w) \cdot p_2$ — the m-geodesic, corresponding to combining in expectation parameter space.

For signal combination in Victoria:
- **e-mixture** = multiply signal likelihoods (Bayesian update) — appropriate when signals measure the same quantity
- **m-mixture** = average signal predictions — appropriate when signals measure different aspects

The information-geometric framework tells us which combination rule is optimal: use e-mixture when signals are **redundant** (share information), use m-mixture when signals are **complementary** (provide independent information). The dual structure gives us a principled way to measure redundancy via the e-projection / m-projection decomposition.

---

## 8. Open Questions and Future Work

1. **Online Fisher estimation at scale**: Computing and inverting the full Fisher matrix is $O(n^3)$ for $n$ signal weights. For Victoria's moderate $n$ (5-15 signals) this is fine, but for larger signal sets, diagonal or Kronecker-factored approximations (KFAC) would be needed.

2. **Non-Gaussian information geometry**: Crypto returns are heavy-tailed. The normal family Fisher-Rao metric is well understood (Poincare half-plane), but the Fisher-Rao geometry of Student-t or stable distributions is less tractable. The `geomstats` library supports some non-Gaussian families.

3. **Connection to Week 1 (gauge theory)**: The gauge connection of Week 1 lives on a fiber bundle over market state space, while the information geometry connection lives on the space of return distributions. Can we unify these? The distribution of returns *conditioned on market state* gives a map from the gauge bundle to the information manifold — a "gauge-information correspondence."

4. **Connection to Week 2 (persistent homology)**: The topology of the information manifold (which distributions are "close") could be analyzed via persistent homology of the Fisher-Rao distance matrix, detecting when the manifold's topology changes (regime transitions that alter the structure of the distribution space).

5. **Adaptive alpha-connections**: Different values of $\alpha$ in Amari's alpha-connection may be optimal for different market conditions. $\alpha = 1$ (exponential) works well for normally-distributed returns; more robust values of $\alpha$ might handle crypto's fat tails better.

---

## 9. References

- Amari, S. (1998). "Natural Gradient Works Efficiently in Learning." Neural Computation, 10(2), 251-276.
- Amari, S. (2016). *Information Geometry and Its Applications.* Applied Mathematical Sciences, Vol. 194. Springer.
- Amari, S. (2021). "Information Geometry." International Statistical Review, 89(2), 250-273.
- Nielsen, F. (2018). "An Elementary Introduction to Information Geometry." arXiv: 1808.08271.
- Miolane, N. et al. (2020). "Geomstats: A Python Package for Riemannian Geometry in Machine Learning." JMLR, 21(223), 1-9.
- Miolane, N. et al. (2024). "Parametric Information Geometry with the Package Geomstats." ACM Transactions on Mathematical Software.
- NeurIPS (2024). "An Improved Empirical Fisher Approximation for Natural Gradient Descent."
- Luo et al. (2025). "Fisher-Orthogonal Projection Methods for Natural Gradient Descent." arXiv: 2508.13898.
- Springer (2024). "Short-term Kullback-Leibler Divergence Analysis to Extract Unstable Periods." Evolutionary and Institutional Economics Review.
- Entropy (2025). "Instability of Financial Time Series Revealed by Irreversibility Analysis." Entropy, 27(4), 402.
- PMC (2020). "Clustering Financial Return Distributions Using the Fisher Information Metric." Entropy, 22(9).
