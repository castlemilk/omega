# Optimal Transport and Wasserstein Distances for Regime Detection

**Date:** 2026-04-20
**Research Series:** Omega Geometric Finance, Week 4
**Focus:** Applying optimal-transport methods to Victoria's regime detection, distribution-drift monitoring, and robust signal combination

---

## 1. Executive Summary

Optimal transport (OT) equips the space of probability measures with a rigorous geometry: the Wasserstein distance $W_p(\mu, \nu)$ measures the minimum work needed to morph one distribution into another, respecting the underlying metric of the sample space. Unlike KL divergence (Week 3), Wasserstein is a true metric — symmetric, satisfies the triangle inequality, and remains finite even when distributions have disjoint supports. These properties make it the natural tool for two problems Victoria already cares about: **regime detection** (is the return distribution today the same shape as yesterday's?) and **online drift monitoring** (has the joint distribution of my features changed enough to invalidate my trained weights?).

The core insight for Victoria is that the current regime classifier (`omega/nodes/victoria/bayesian_regime.py`) reduces each window to a handful of scalar summaries (realized vol, bear-probability, basket dispersion). A Wasserstein-based classifier instead compares the *full empirical distribution* of returns across windows, catching shape changes — fat-tail emergence, skew flips, bimodality — that moment-based detectors miss. Horvath, Issa, and Muguruza (2021) proved that Wasserstein k-means outperforms HMM and variance-based classifiers on non-Gaussian regimes, and Luan & Hamp (2023) extended this to multidimensional time series via the sliced Wasserstein distance — a $O(nL\log n)$ approximation that scales to the 10–30 correlated symbols Victoria trades.

This document covers the mathematical foundations of OT, the algorithms that make it tractable (Sinkhorn, sliced Wasserstein, Wasserstein barycenter), recent financial applications (2021–2025), and a concrete implementation path using the `POT` library for Victoria's regime and drift-monitoring pipeline.

---

## 2. Mathematical Foundations

### 2.1 The Wasserstein Distance

Let $(\mathcal{X}, d)$ be a metric space and let $\mu, \nu$ be two probability measures on $\mathcal{X}$ with finite $p$-th moment. The **$p$-Wasserstein distance** is

$$W_p(\mu, \nu) = \left(\inf_{\pi \in \Pi(\mu,\nu)} \int_{\mathcal{X}\times\mathcal{X}} d(x,y)^p \, d\pi(x,y)\right)^{1/p}$$

where $\Pi(\mu, \nu)$ is the set of **couplings** — joint distributions on $\mathcal{X} \times \mathcal{X}$ with marginals $\mu$ and $\nu$. Intuitively, $\pi(x,y)$ is the "amount of mass moved from $x$ to $y$", $d(x,y)^p$ is the cost per unit mass, and $W_p$ is the minimum total cost.

**1D closed form.** When $\mathcal{X} = \mathbb{R}$, the optimal coupling is the monotone rearrangement and the distance collapses to

$$W_p(\mu, \nu)^p = \int_0^1 |F_\mu^{-1}(t) - F_\nu^{-1}(t)|^p \, dt$$

i.e., the $L^p$ distance between inverse CDFs. For empirical distributions with $n$ samples each, this is just the sorted-sample $L^p$ distance — an $O(n\log n)$ computation.

**Why it beats KL for regime detection.** KL divergence $D_{KL}(p\|q)$ blows up to $+\infty$ when $p$ has mass where $q$ has none. An empirical return window with one extreme loss that wasn't seen in the reference window immediately becomes "infinitely far" under KL — not actionable. $W_p$ handles this gracefully: an outlier contributes at most $|x_{\text{outlier}} - x_{\text{nearest ref}}|^p$ to the total cost. This is the fundamental reason Wasserstein outperforms KL in the Horvath–Issa–Muguruza 2021 regime-clustering benchmarks.

### 2.2 The Kantorovich Dual and Sinkhorn Regularization

The primal LP above has $n^2$ variables for $n$-sample empirical distributions. The **Kantorovich dual**

$$W_1(\mu, \nu) = \sup_{\|f\|_{\text{Lip}}\le 1} \int f \, d(\mu - \nu)$$

reduces this to maximizing over 1-Lipschitz functions, which is how Wasserstein GANs work but is expensive for online use.

The practical breakthrough is **entropic regularization** (Cuturi 2013):

$$W_\varepsilon(\mu,\nu) = \inf_\pi \int d(x,y)^p\, d\pi + \varepsilon\, H(\pi \mid \mu \otimes \nu)$$

where $H$ is relative entropy. The regularized optimum is solved by **Sinkhorn iteration** — alternating matrix scaling on the transport plan — with $O(n^2/\varepsilon)$ complexity and GPU-friendly structure. Sinkhorn distances interpolate between MMD (large $\varepsilon$) and true Wasserstein (small $\varepsilon$).

### 2.3 Sliced Wasserstein — Tractable Multivariate OT

In $d$ dimensions, exact $W_p$ requires solving an assignment problem (roughly $O(n^3)$ for $n$ samples). For Victoria's feature spaces ($d \in [5, 30]$) this is too slow for intraday use.

The **sliced Wasserstein distance** exploits the 1D closed form:

$$SW_p(\mu,\nu)^p = \int_{S^{d-1}} W_p(P_\theta^* \mu, P_\theta^* \nu)^p \, d\sigma(\theta)$$

where $P_\theta^*\mu$ is the pushforward of $\mu$ onto the line through direction $\theta$. Monte-Carlo estimate with $L$ random projections costs $O(dL n + Ln\log n)$ — linear in $d$ and $n$ up to a log factor. Bonnotte (2013) proved $SW_p$ is a true metric on $\mathcal{P}_p(\mathbb{R}^d)$ topologically equivalent to $W_p$.

**Practical guidance.** $L = 50$ projections reproduces $W_2$ rankings to within 2% on 20-D Gaussian mixtures (Deshpande et al. 2019). $L = 100$ is safe for downstream clustering.

### 2.4 Wasserstein Barycenters

Given a set of distributions $\{\mu_i\}_{i=1}^K$ with weights $\lambda_i$, the **Wasserstein barycenter** is

$$\bar\mu = \arg\min_\nu \sum_i \lambda_i W_p^p(\nu, \mu_i).$$

It is the OT analogue of a mean. For 1D distributions the barycenter is itself a 1D distribution whose inverse CDF is $\sum_i \lambda_i F_{\mu_i}^{-1}$. Wasserstein k-means uses barycenters as cluster centroids: each cluster's "prototype" is the barycenter of its member distributions, and cluster assignment uses $W_p$ instead of Euclidean distance.

### 2.5 The Wasserstein k-means Algorithm

**Data.** Segment a time series into non-overlapping windows $W_1, \ldots, W_N$ (e.g., 20 bars each). Treat each window as an empirical distribution $\hat\mu_i$.

**Iteration.**
1. Initialize cluster centroids $c_1, \ldots, c_K$ (random windows).
2. **Assign:** $a(i) = \arg\min_k W_p(\hat\mu_i, c_k)$.
3. **Update:** $c_k = \text{WassersteinBarycenter}(\{\hat\mu_i : a(i) = k\})$.
4. Repeat until assignments stabilize.

Each regime is then a cluster of distributional windows, with the barycenter as the canonical representative. The algorithm's crucial advantage: it makes **no parametric assumption** about the regime's distribution (Gaussian, Student-t, etc.), unlike HMMs that must fit emission distributions.

---

## 3. Key Literature

### 3.1 Foundational OT Works

**Villani (2009)** — *Optimal Transport: Old and New.* Springer. The definitive modern reference. Covers the Monge–Kantorovich formulation, Wasserstein metric properties, and gradient flows in probability space.

**Peyré & Cuturi (2019)** — "Computational Optimal Transport." *Foundations and Trends in ML*, 11(5-6). The standard computational reference, covering Sinkhorn, sliced Wasserstein, barycenter algorithms, and numerical implementations.

**Cuturi (2013)** — "Sinkhorn Distances: Lightspeed Computation of Optimal Transport." NeurIPS. Introduced entropic regularization, reducing OT from $O(n^3\log n)$ to $O(n^2/\varepsilon)$ with massive parallelism.

### 3.2 Regime Detection

**Horvath, Issa, Muguruza (2021)** — "Clustering Market Regimes using the Wasserstein Distance." arXiv:2110.11848. Journal of Computational Finance (2024). The seminal paper showing that Wasserstein k-means identifies market regimes more reliably than HMM and variance-threshold methods, particularly when returns are non-Gaussian. Demonstrated on SPY with clean bull/bear/high-vol separation.

**Luan & Hamp (2023/2025)** — "Automated Regime Classification in Multidimensional Time Series Data using Sliced Wasserstein k-means Clustering." arXiv:2310.01285; final version in *Data Science in Finance & Economics* 5(3), 2025. Extends Horvath et al. to $d$-dimensional time series using $SW_p$, with detailed hyperparameter ablations and a multi-currency FX case study. **Directly applicable to Victoria's 10–30 symbol basket.**

**Cheng et al. (2020)** — "WATCH: Wasserstein Change-Point Detection for High-Dimensional Time Series." IEEE Big Data. Introduces a sliding-window change-point detector using $W_p$ between a reference distribution and a candidate window, with theoretical consistency guarantees and empirical false-positive rates below 3%.

### 3.3 Crypto-Specific Applications

**Akcora, Gel, Kantarcioglu et al. (2024)** — "A Topological Approach for Capturing High-Order Interactions in Graph Data with Applications to Anomaly Detection in Time-Varying Cryptocurrency Transaction Graphs." *Foundations of Data Science* 6(4). Combines topological features with Wasserstein distance on filtrations of Ethereum transaction graphs, achieving up to 20% gain in anomalous price-prediction over baseline change-point detectors. Direct crypto relevance.

**James, Menzies, Radchenko (2021, cited 2024)** — "Collective Correlations, Dynamics, and Behavioural Inconsistencies of the Cryptocurrency Market Over Time." *Nonlinear Dynamics* 107. Studies 52 large cryptocurrencies and constructs a Wasserstein-distance matrix between rolling volatility densities; regime transitions emerge as clusters in this metric space. Provides a template for applying $W_2$ to crypto cross-sectional volatility.

**Marti, Andler, Nielsen, Donnat (2021, ongoing)** — "Wasserstein Clustering of Financial Return Distributions." Builds Python tooling (now folded into POT) for clustering assets by return-distribution shape — a cross-sectional analogue of Horvath et al.'s time-axis clustering.

### 3.4 Robust Optimization and Portfolio Work (2024–2025)

**Nguyen et al. (2024)** — "Robustifying Conditional Portfolio Decisions via Optimal Transport." *Operations Research*. Data-driven portfolio selection using distributionally robust optimization with an OT ambiguity set. Directly applicable to sizing when Victoria suspects regime drift.

**Wang et al. (2024)** — "Sinkhorn Distributionally Robust Optimization." *Operations Research*. Derives convex dual reformulations for DRO with Sinkhorn (entropic-regularized) ambiguity sets, plus stochastic mirror descent solvers. Enables online robustification at Victoria's decision frequency.

**Farinelli & Sabatino (2024)** — "Wasserstein Clustering of Financial Institutions." *Mathematics and Financial Economics*. Applies WK-means to balance-sheet data; methodology carries over directly to asset-level clustering, and gives cleaner theoretical treatment of convergence than Horvath et al.

### 3.5 Computational Tools

**POT (Python Optimal Transport)** — `pythonot.github.io`. The reference library. Exposes `ot.emd` (exact $W_p$), `ot.sinkhorn` (entropic), `ot.sliced.sliced_wasserstein_distance`, `ot.bregman.barycenter`, and GPU backends via PyTorch. Actively maintained, permissive license.

**mirkovicdev / CLUSTERING-MARKET-REGIMES** — Reference Python implementation of Horvath et al. 2021 on GitHub. Includes WK-means, synthetic regime generators, and SPY validation. Use as a starting template.

**NannyML** — Provides a production-grade sliding-window Wasserstein drift detector (`UnivariateDriftCalculator`) with automatic thresholding. Appropriate for feature-drift monitoring on top of Victoria's regime signal.

---

## 4. Application to Victoria's Pipeline

### 4.1 Where This Fits Today

Victoria already has a regime classifier (`bayesian_regime.py`) that outputs bull/bear probabilities and a `{crisis, high_vol, normal}` label. The label drives the regime-adaptive conviction thresholds documented in `CLAUDE.md`:

- **CRISIS/BEAR** (bear_prob ≥ 0.55): long=0.20, short=0.05
- **BULL** (bull_prob ≥ 0.55): long=0.05, short=0.20
- **NORMAL**: long=0.10, short=0.05

The Bayesian component captures mean and variance shifts but not distributional *shape* shifts — e.g., the transition from Gaussian-ish normal to power-law crisis is smoothed over because the classifier only sees a few moments. Wasserstein-based detection fills that gap.

### 4.2 Three Integration Points

**(a) Shape-aware regime detector** — augment `bayesian_regime.py` with a `wasserstein_regime` feature: $W_2$ between a rolling return window and a reference library of labeled regimes. Output is a *distance to each regime archetype*, providing a finer signal than the current binary state.

**(b) Online drift monitor** — for the meta-analyst (the auto-apply audit gate in `v49_gates.py` gate #6), track $W_2$ between the distribution of features at training time and the live distribution. Trigger a "retrain recommended" alert when distance exceeds a cross-validated threshold — a true distributional analog to Victoria's current ad-hoc drift checks.

**(c) Regime discovery** — offline, run sliced WK-means on historical multi-symbol return windows to learn a regime taxonomy from data rather than hand-labeling `{crisis, high_vol, normal}`. Cross-check against the existing labels; mismatches are candidate new regimes (e.g., "high-vol but negatively skewed" vs. "high-vol symmetric").

### 4.3 Why the Geometry Matters

Wasserstein is a **cross-metric lift of the underlying return metric** — it respects the fact that a $-2$σ move is meaningfully closer to a $-1.5$σ move than to a $+1.5$σ move. KL divergence and Jensen-Shannon divergence treat all rearrangements of probability mass symmetrically and do not respect this geometric structure. That is why $W_2$ catches "the left tail fattened" shifts cleanly while KL treats them the same as "the right tail fattened."

For crypto specifically, where left-tail fattening (liquidation cascades) and right-tail fattening (squeeze rallies) are qualitatively different regimes that Victoria should *not* treat identically, Wasserstein's asymmetry-aware distance is the right primitive.

---

## 5. Code Sketches

### 5.1 1D Wasserstein Regime Distance

```python
import numpy as np

def wasserstein_1d(x: np.ndarray, y: np.ndarray, p: float = 2.0) -> float:
    """
    p-Wasserstein distance between two 1D empirical distributions.
    O(n log n). No external dependencies.
    """
    xs = np.sort(x)
    ys = np.sort(y)
    # Handle unequal sizes by resampling via quantile interpolation
    if len(xs) != len(ys):
        q = np.linspace(0, 1, max(len(xs), len(ys)))
        xs = np.quantile(xs, q)
        ys = np.quantile(ys, q)
    return float(np.mean(np.abs(xs - ys) ** p) ** (1.0 / p))


def regime_distance_vector(window: np.ndarray,
                           archetypes: dict[str, np.ndarray]) -> dict[str, float]:
    """
    For a return window, compute W_2 distance to each named archetype.
    Archetypes are reference return distributions for each regime label.
    """
    return {name: wasserstein_1d(window, ref, p=2.0)
            for name, ref in archetypes.items()}
```

**Victoria integration.** Compute `archetypes` once at training time by pooling returns labeled as `crisis`, `high_vol`, `normal` in the historical dataset. At live decision time, call `regime_distance_vector` on the current rolling-window returns; the argmin is a shape-aware regime label that can be fused with `bayesian_regime.py`'s probabilistic output.

### 5.2 Multivariate Sliced Wasserstein Regime Classifier

```python
import numpy as np
from numpy.random import default_rng

class SlicedWassersteinRegimeClassifier:
    """
    Multivariate regime classifier using sliced W_2 against a library
    of labeled archetypes. Each archetype is a (T, d) array of returns
    for d symbols over T bars.
    """
    def __init__(self, archetypes: dict[str, np.ndarray],
                 n_projections: int = 100, seed: int = 0):
        self.archetypes = archetypes
        self.L = n_projections
        self.rng = default_rng(seed)

    def _sample_projections(self, d: int) -> np.ndarray:
        theta = self.rng.standard_normal((self.L, d))
        theta /= np.linalg.norm(theta, axis=1, keepdims=True)
        return theta

    def sliced_w2(self, X: np.ndarray, Y: np.ndarray) -> float:
        """Monte-Carlo sliced W_2 between (n,d) and (m,d) samples."""
        d = X.shape[1]
        theta = self._sample_projections(d)  # (L, d)
        Xp = X @ theta.T  # (n, L)
        Yp = Y @ theta.T  # (m, L)
        # Sort each projected column; average squared L2 between sorted cols
        Xp_s = np.sort(Xp, axis=0)
        Yp_s = np.sort(Yp, axis=0)
        if Xp_s.shape[0] != Yp_s.shape[0]:
            q = np.linspace(0, 1, max(Xp_s.shape[0], Yp_s.shape[0]))
            Xp_s = np.quantile(Xp_s, q, axis=0)
            Yp_s = np.quantile(Yp_s, q, axis=0)
        slice_w2 = np.mean((Xp_s - Yp_s) ** 2, axis=0)  # (L,)
        return float(np.sqrt(np.mean(slice_w2)))

    def predict(self, window: np.ndarray) -> tuple[str, dict[str, float]]:
        """Return (best_label, distances_per_label)."""
        dists = {name: self.sliced_w2(window, ref)
                 for name, ref in self.archetypes.items()}
        best = min(dists, key=dists.get)
        return best, dists
```

**Use.** `predict()` returns both the best regime and the full distance vector. The distance vector itself becomes a new feature for the downstream conviction filter — closer archetypes exert more pull on the threshold, which is a smoother analog of today's hard regime switch.

### 5.3 Online Wasserstein Drift Monitor

```python
from collections import deque
import numpy as np

class WassersteinDriftMonitor:
    """
    WATCH-style online drift detector.
    Maintains a reference distribution and an updating test window.
    Emits an alert when W_p exceeds a threshold.
    """
    def __init__(self, reference: np.ndarray, window: int = 200,
                 p: float = 2.0, alert_multiplier: float = 3.0):
        self.reference = np.asarray(reference, dtype=float).ravel()
        self.buffer: deque[float] = deque(maxlen=window)
        self.p = p
        self.alert_multiplier = alert_multiplier
        self._calibrate()

    def _calibrate(self):
        # Split reference in half, bootstrap a null distribution of W_p
        rng = np.random.default_rng(0)
        half = len(self.reference) // 2
        null = []
        for _ in range(200):
            idx = rng.permutation(len(self.reference))
            a, b = self.reference[idx[:half]], self.reference[idx[half:2 * half]]
            null.append(wasserstein_1d(a, b, p=self.p))
        self.null_mean = float(np.mean(null))
        self.null_std = float(np.std(null))
        self.threshold = self.null_mean + self.alert_multiplier * self.null_std

    def observe(self, x: float) -> dict:
        self.buffer.append(float(x))
        if len(self.buffer) < self.buffer.maxlen // 2:
            return {"status": "warmup", "distance": None}
        dist = wasserstein_1d(np.asarray(self.buffer), self.reference, p=self.p)
        return {
            "status": "alert" if dist > self.threshold else "ok",
            "distance": dist,
            "threshold": self.threshold,
        }
```

**Victoria integration.** Instantiate one monitor per feature channel (basket return, realized vol, cross-section dispersion, funding rates). The `alert` signal feeds the meta-analyst as a hard gate: if more than $k$ channels are in alert, freeze auto-apply on the next training cycle. This is exactly the sort of principled robustness check V49+ gates were designed to support.

### 5.4 Wasserstein k-means with POT

```python
# pip install POT
import numpy as np
import ot

def wk_means_1d(windows: list[np.ndarray], K: int = 3,
                p: float = 2.0, max_iter: int = 30, seed: int = 0) -> tuple:
    """
    Wasserstein k-means for 1D return windows.
    Returns (assignments, centroids_as_quantile_arrays).
    """
    rng = np.random.default_rng(seed)
    n = len(windows)
    # Represent each window as a fixed-grid quantile vector
    q = np.linspace(0.01, 0.99, 99)
    Q = np.stack([np.quantile(w, q) for w in windows])  # (n, 99)

    # Initialize centroids by sampling
    idx = rng.choice(n, K, replace=False)
    C = Q[idx].copy()  # (K, 99)

    for _ in range(max_iter):
        # Assign: W_p^p between quantile vectors equals mean |Q - C|^p
        dists = np.mean(np.abs(Q[:, None, :] - C[None, :, :]) ** p, axis=2)
        a = np.argmin(dists, axis=1)
        # Update: 1D Wasserstein barycenter == mean of inverse CDFs
        C_new = np.stack([
            Q[a == k].mean(axis=0) if np.any(a == k) else C[k]
            for k in range(K)
        ])
        if np.allclose(C, C_new):
            break
        C = C_new
    return a, C
```

**Use.** Run offline on historical windows labeled by date. The learned cluster labels give Victoria's `{crisis, high_vol, normal}` taxonomy a data-driven grounding rather than a hand-tuned bear-probability threshold. Discrepancies between the learned clusters and the current hand labels are candidate new regimes worth investigating in forensics.

---

## 6. Implementation Plan for Victoria

### Phase 1 — Instrumentation (Week 1, low risk)

1. Add `omega/nodes/victoria/wasserstein_regime.py` with the four classes above (`wasserstein_1d`, `SlicedWassersteinRegimeClassifier`, `WassersteinDriftMonitor`, `wk_means_1d`). Pure NumPy, no new deps required for the shape monitor.
2. Plumb `POT` into the optional extras: `pyproject.toml` → `[project.optional-dependencies] geometry = ["POT>=0.9"]`. Keep core runtime minimal per `CLAUDE.md`.
3. Compute regime archetypes from historical data: pool the returns for each labeled regime window from `data/` training CSVs, save `data/regime_archetypes.npz`.
4. Emit `wasserstein_regime_distance` features alongside the existing regime probability in the signal bus. **Shadow mode only** — no decision effect yet.

### Phase 2 — Monitoring (Weeks 2–3)

5. Hook `WassersteinDriftMonitor` into the meta-analyst as gate #7 (extending the six V49 gates). Calibrate thresholds on 20 historical training cycles; require zero false-alerts on the calibration set.
6. Add a dashboard tile: per-feature distance + alert status, plus a heat-map of $W_2$ distance to each regime archetype over the last 24h. Use the existing Connect-RPC + shadcn stack (`web/dashboard/`).

### Phase 3 — Decision fusion (Weeks 4–5)

7. Replace the hard regime switch in `_apply_regime_adaptive_thresholds` with a **soft** interpolation across regimes weighted by a softmin of $W_2$ distances (temperature τ as a new config knob). Rationale: today the regime label flips at bear_prob=0.55, which produces threshold-jump artifacts visible in training v40+; soft interpolation eliminates the artifact.
8. A/B test against v49 baseline. Gate: PnL floor, regime-parity, drawdown-ceiling (the standard V49 hard gates) must all pass before merging.

### Phase 4 — Regime discovery (Weeks 6–8, R&D)

9. Run offline sliced WK-means with $K \in \{2, 3, 4, 5\}$ on the full training archive (`data/v*_trades.csv` + the per-cycle return matrices).
10. Cross-validate by silhouette-in-$W_2$ and by downstream Sharpe when each discovered cluster is used as a regime label. If $K=4$ or $5$ beats $K=3$ meaningfully, propose a new regime taxonomy for v50+.

### Risks and Mitigations

- **Compute.** Sliced $W_2$ with $L=100, n=200, d=20$ costs roughly 1ms per call — fine for Victoria's cadence, but confirm with a benchmark in `tests/perf/`.
- **Calibration drift.** Archetype distributions drift themselves. Plan a quarterly recalibration, triggered by the meta-analyst's drift alert.
- **Regime-label churn.** Soft-mixed thresholds can create oscillation if $W_2$ distances are noisy. Add a hysteresis buffer (3-bar confirmation before switching the dominant regime) matching the existing 2-cycle time filter in `strategy.py`.

---

## 7. Cross-References to Prior Weeks

- **Week 1 (Gauge Theory)** — Wasserstein distance on the space of measures is a Riemannian metric whose geodesics are the McCann interpolants. This is the optimal-transport analogue of the geodesic structure on the information manifold (Week 3). A rigorous cross-framework comparison would compose $W_2$ with the arbitrage curvature of Week 1, potentially yielding a unified "geometric arbitrage in Wasserstein space" formulation — flagged for a later deep dive.
- **Week 2 (TDA / Persistent Homology)** — Persistence diagrams themselves live naturally in Wasserstein space; the bottleneck distance between persistence diagrams is a special case of $W_\infty$. Composing Week 2's topological crash detector with this week's distributional regime detector gives two orthogonal views — topology of the correlation network vs. shape of the return distribution — that can be fused in a joint alert.
- **Week 3 (Information Geometry)** — KL divergence and $W_2$ are complementary: KL is the Bregman divergence of the neg-entropy potential (intrinsic to the simplex), while $W_2$ respects the extrinsic metric on the sample space. A hybrid regime detector could weight both — KL when distributions are close and share supports, $W_2$ when supports shift materially.

---

## 8. References

Villani, C. (2009). *Optimal Transport: Old and New.* Springer.

Peyré, G., & Cuturi, M. (2019). Computational Optimal Transport. *Foundations and Trends in Machine Learning*, 11(5-6).

Cuturi, M. (2013). Sinkhorn Distances: Lightspeed Computation of Optimal Transport. *NeurIPS*.

Horvath, B., Issa, Z., & Muguruza, A. (2021). Clustering Market Regimes using the Wasserstein Distance. arXiv:2110.11848. *Journal of Computational Finance* (2024).

Luan, Q., & Hamp, J. (2023/2025). Automated Regime Classification in Multidimensional Time Series Data using Sliced Wasserstein k-means Clustering. arXiv:2310.01285; *Data Science in Finance & Economics* 5(3), 2025.

Cheng, K., et al. (2020). WATCH: Wasserstein Change-Point Detection for High-Dimensional Time Series. *IEEE Big Data*.

Akcora, C. G., Gel, Y. R., Kantarcioglu, M., et al. (2024). A Topological Approach for Capturing High-Order Interactions in Graph Data with Applications to Anomaly Detection in Time-Varying Cryptocurrency Transaction Graphs. *Foundations of Data Science*, 6(4).

James, N., Menzies, M., Radchenko, P. (2021). Collective Correlations, Dynamics, and Behavioural Inconsistencies of the Cryptocurrency Market Over Time. *Nonlinear Dynamics*, 107.

Farinelli, S., & Sabatino, F. (2024/2025). The Geometry of Financial Institutions — Wasserstein Clustering of Financial Data. *Mathematics and Financial Economics*. arXiv:2305.03565.

Nguyen, V. A., et al. (2024). Robustifying Conditional Portfolio Decisions via Optimal Transport. *Operations Research*.

Wang, J., et al. (2024). Sinkhorn Distributionally Robust Optimization. *Operations Research*.

Bonnotte, N. (2013). Unidimensional and Evolution Methods for Optimal Transportation. PhD thesis, Orsay.

Deshpande, I., Hu, Y. T., Sun, R., et al. (2019). Max-Sliced Wasserstein Distance and its use for GANs. *CVPR*.

Marti, G., Andler, S., Nielsen, F., Donnat, P. (2021, ongoing). Wasserstein Clustering of Financial Return Distributions. *POT documentation / paper series*.

### Software

- POT (Python Optimal Transport): https://pythonot.github.io
- mirkovicdev / CLUSTERING-MARKET-REGIMES: https://github.com/mirkovicdev/CLUSTERING-MARKET-REGIMES
- NannyML UnivariateDriftCalculator: https://nannyml.readthedocs.io

---

*Research conducted by automated weekly research task. Next up (Week 5): Random Matrix Theory for correlation denoising.*
