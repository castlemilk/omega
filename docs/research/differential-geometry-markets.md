# Differential Geometry & Information Geometry Applied to Financial Markets

**Research Document — Omega / Victoria**
**Date:** 2026-04-08
**Status:** Active Research

---

## Table of Contents

1. [Core Mathematical Framework: Information Geometry](#1-core-mathematical-framework-information-geometry)
2. [Fisher Information Metric for Markets](#2-fisher-information-metric-for-markets)
3. [Ricci Curvature as a Regime Indicator](#3-ricci-curvature-as-a-regime-indicator)
4. [Geodesics on Statistical Manifolds](#4-geodesics-on-statistical-manifolds)
5. [Ollivier-Ricci Curvature on Market Graphs](#5-ollivier-ricci-curvature-on-market-graphs)
6. [Practical Implementations in Literature](#6-practical-implementations-in-literature)
7. [Implementation Sketch for Victoria](#7-implementation-sketch-for-victoria)
8. [Visualization Approaches](#8-visualization-approaches)
9. [References](#9-references)

---

## 1. Core Mathematical Framework: Information Geometry

### 1.1 Statistical Manifolds

A **statistical manifold** is a smooth manifold $\mathcal{M}$ whose points are probability distributions. Given a parametric family of distributions $\{p(x|\theta) : \theta \in \Theta \subseteq \mathbb{R}^n\}$, the parameter space $\Theta$ inherits differential-geometric structure from the probability distributions it indexes.

The foundational insight of information geometry (Amari, 1985; Amari & Nagaoka, 2000) is that families of probability distributions carry a natural Riemannian structure — the **Fisher-Rao metric** — plus a family of affine connections — the **α-connections** — that encode how distributions relate to each other geometrically.

For financial markets, the key objects are:
- **Points on the manifold:** market states parameterized by distribution parameters (e.g., rolling mean $\mu$, variance $\sigma^2$, skewness $\gamma$, kurtosis $\kappa$ of return distributions)
- **Tangent vectors:** infinitesimal changes in distribution parameters (regime shifts)
- **Geodesics:** "shortest paths" between market states in distribution space
- **Curvature:** measures of how distribution space bends, indicating regime dynamics

### 1.2 The Fisher-Rao Metric

The **Fisher information matrix** defines the unique (up to rescaling) Riemannian metric on a statistical manifold that is invariant under sufficient statistics (Chentsov's theorem, 1972). For a parametric family $p(x|\theta)$ with parameters $\theta = (\theta^1, \ldots, \theta^n)$:

$$g_{ij}(\theta) = \mathbb{E}\left[\frac{\partial \log p(x|\theta)}{\partial \theta^i} \cdot \frac{\partial \log p(x|\theta)}{\partial \theta^j}\right] = -\mathbb{E}\left[\frac{\partial^2 \log p(x|\theta)}{\partial \theta^i \partial \theta^j}\right]$$

This is the **Fisher information matrix** $G(\theta) = [g_{ij}(\theta)]$, and it serves as the metric tensor of the statistical manifold. The key property: $g_{ij}$ measures how "distinguishable" two infinitesimally close distributions $p(x|\theta)$ and $p(x|\theta + d\theta)$ are. The infinitesimal distance is:

$$ds^2 = \sum_{i,j} g_{ij}(\theta) \, d\theta^i \, d\theta^j$$

**Why this matters for markets:** Two market states might have similar means but very different tail behavior. The Fisher-Rao metric captures this — it naturally weights differences in parameters by how much those differences affect the observable distribution of returns.

### 1.3 Closed-Form Fisher Metrics for Common Distributions

**Univariate Normal $\mathcal{N}(\mu, \sigma^2)$:**

Parameters $\theta = (\mu, \sigma)$. The Fisher information matrix is:

$$G = \begin{pmatrix} 1/\sigma^2 & 0 \\ 0 & 2/\sigma^2 \end{pmatrix}$$

This is the **Poincaré half-plane metric** (up to scaling). The manifold of normal distributions is hyperbolic space $\mathbb{H}^2$ with constant negative curvature $-1/2$. The geodesic distance between $\mathcal{N}(\mu_1, \sigma_1)$ and $\mathcal{N}(\mu_2, \sigma_2)$ has the closed form:

$$d_{FR}(\theta_1, \theta_2) = \sqrt{2} \cosh^{-1}\left(\frac{(\mu_1 - \mu_2)^2 + \sigma_1^2 + \sigma_2^2}{2\sigma_1 \sigma_2}\right)$$

**Multivariate Normal $\mathcal{N}(\mu, \Sigma)$:**

The Fisher-Rao distance between two multivariate normals $(\mu_1, \Sigma_1)$ and $(\mu_2, \Sigma_2)$ involves the generalized eigenvalues of $(\Sigma_1, \Sigma_2)$. No general closed form exists, but efficient computational methods are available. For zero-mean distributions with differing covariances:

$$d_{FR}^2 = \frac{1}{2} \sum_{k=1}^{n} (\log \lambda_k)^2$$

where $\lambda_k$ are the generalized eigenvalues of $\Sigma_1^{-1}\Sigma_2$.

**Student-t Distribution $t_\nu(\mu, \sigma)$:**

More appropriate for financial returns (heavy tails). The Fisher information matrix depends on the degrees of freedom $\nu$, location $\mu$, and scale $\sigma$. No closed-form geodesic distance exists; must be computed numerically. However, the metric tensor entries are:

$$g_{\mu\mu} = \frac{\nu + 1}{(\nu + 3)\sigma^2}, \quad g_{\sigma\sigma} = \frac{2\nu}{(\nu + 3)\sigma^2}, \quad g_{\mu\sigma} = 0$$

(for the location-scale subfamily with fixed $\nu$).

**Generalized Pareto Distribution (for tails):**

Relevant for extreme value theory in finance. The Fisher information matrix for the GPD $\text{GPD}(\xi, \sigma)$ with shape $\xi$ and scale $\sigma$ is:

$$G = \frac{1}{\sigma^2} \begin{pmatrix} 2(1+\xi)^2 & (1+\xi) \\ (1+\xi) & 1 \end{pmatrix}^{-1}$$

for $\xi > -1/2$, which is the regime relevant for financial risk.

### 1.4 α-Connections and Duality

Amari introduced a one-parameter family of affine connections $\nabla^{(\alpha)}$ on statistical manifolds, indexed by $\alpha \in \mathbb{R}$. The connection coefficients are:

$$\Gamma_{ij,k}^{(\alpha)} = \mathbb{E}\left[\left(\frac{\partial^2 \log p}{\partial \theta^i \partial \theta^j} + \frac{1-\alpha}{2} \frac{\partial \log p}{\partial \theta^i} \frac{\partial \log p}{\partial \theta^j}\right) \frac{\partial \log p}{\partial \theta^k}\right]$$

Key special cases:
- **$\alpha = 0$:** Levi-Civita connection (Riemannian geometry)
- **$\alpha = 1$:** Exponential connection ($e$-connection)
- **$\alpha = -1$:** Mixture connection ($m$-connection)

The $e$-connection and $m$-connection are **dual** with respect to the Fisher metric:

$$X \langle Y, Z \rangle = \langle \nabla^{(1)}_X Y, Z \rangle + \langle Y, \nabla^{(-1)}_X Z \rangle$$

### 1.5 Dual Affine Coordinates and Dually Flat Manifolds

For **exponential families** (which include the normal family), the statistical manifold is **dually flat** — flat with respect to both the $e$-connection and $m$-connection simultaneously. This yields two global coordinate systems:

- **Natural parameters** $\eta$ (e-affine coordinates): the exponential family canonical parameters
- **Expectation parameters** $\mu$ (m-affine coordinates): the expected sufficient statistics

These are connected by the Legendre transform of the log-partition function $\psi(\eta)$:

$$\mu_i = \frac{\partial \psi}{\partial \eta_i}, \qquad \eta_i = \frac{\partial \phi}{\partial \mu_i}$$

where $\phi(\mu)$ is the dual potential (negative entropy).

The **Bregman divergence** associated with $\psi$ is the KL-divergence:

$$D_{KL}(p_\eta \| p_{\eta'}) = D_\psi(\eta' \| \eta) = \psi(\eta') - \psi(\eta) - \langle \nabla\psi(\eta), \eta' - \eta \rangle$$

**Financial implication:** On a dually flat manifold, the $e$-geodesic from state A to state B and the $m$-geodesic are *different curves* that together define a Pythagorean-like theorem. The $e$-geodesic preserves exponential family structure (useful for likelihood-based forecasting), while the $m$-geodesic preserves mixture structure (useful for portfolio blending).

---

## 2. Fisher Information Metric for Markets

### 2.1 Construction from Rolling OHLCV Data

Given a universe of $N$ assets with return time series $\{r_t^{(i)}\}_{i=1}^N$, we construct a time-varying point on a statistical manifold as follows:

**Step 1: Rolling Window Estimation**

For each time $t$, take a rolling window $[t-W, t]$ of returns. Estimate distribution parameters:

- **Mean vector:** $\hat{\mu}_t = \frac{1}{W}\sum_{s=t-W}^{t} r_s$
- **Covariance matrix:** $\hat{\Sigma}_t = \frac{1}{W-1}\sum_{s=t-W}^{t}(r_s - \hat{\mu}_t)(r_s - \hat{\mu}_t)^\top$
- **Higher moments:** rolling skewness $\hat{\gamma}_t$, kurtosis $\hat{\kappa}_t$ (element-wise or multivariate)

This gives a trajectory $\theta(t) = (\hat{\mu}_t, \hat{\Sigma}_t, \hat{\gamma}_t, \hat{\kappa}_t, \ldots)$ on the parameter manifold.

**Step 2: Fisher Metric Computation**

At each time $t$, compute the Fisher information matrix $G(\theta_t)$ for the estimated distribution family. For the multivariate normal case with parameters $(\mu, \Sigma)$:

$$g_{\mu_i, \mu_j} = [\Sigma^{-1}]_{ij}$$

$$g_{\Sigma_{ij}, \Sigma_{kl}} = \frac{1}{2}[\Sigma^{-1}]_{ik}[\Sigma^{-1}]_{jl} + \frac{1}{2}[\Sigma^{-1}]_{il}[\Sigma^{-1}]_{jk}$$

The mixed terms $g_{\mu_i, \Sigma_{jk}} = 0$ for the normal family.

**Step 3: Geodesic Distance Between Market States**

The Fisher-Rao distance between market states at times $t_1$ and $t_2$:

$$d_{FR}(\theta_{t_1}, \theta_{t_2}) = \inf_{\gamma} \int_0^1 \sqrt{\dot{\gamma}(s)^\top G(\gamma(s)) \dot{\gamma}(s)} \, ds$$

where the infimum is over all smooth paths $\gamma: [0,1] \to \Theta$ with $\gamma(0) = \theta_{t_1}$ and $\gamma(1) = \theta_{t_2}$.

### 2.2 Practical Approximations

**For univariate analysis (single asset or index):**

Using the normal model $\mathcal{N}(\mu, \sigma^2)$, the closed-form Fisher-Rao distance is available (see Section 1.3). This is fast and exact.

**For multivariate analysis:**

The full covariance parameterization lives in $\mathbb{R}^{N + N(N+1)/2}$ dimensions (means + unique covariance entries). For $N = 500$ assets, this is ~125,750 dimensions. The Fisher metric is computable but geodesic distances require numerical ODE integration.

**Computational shortcut — Affine-invariant distance on SPD cone:**

The space of symmetric positive definite (SPD) matrices $\mathcal{S}_{++}^N$ is a Riemannian manifold with the affine-invariant metric:

$$d(\Sigma_1, \Sigma_2) = \|\log(\Sigma_1^{-1/2} \Sigma_2 \Sigma_1^{-1/2})\|_F = \sqrt{\sum_{k=1}^N (\log \lambda_k)^2}$$

This is proportional to the Fisher-Rao distance for the zero-mean normal family and is widely used in computer vision and brain-computer interfaces. Libraries: `pyriemann`, `geomstats`.

### 2.3 What the Metric Captures

The Fisher-Rao metric on market states captures:

1. **Distributional distance, not just parametric distance:** A change from $\sigma = 10\%$ to $\sigma = 15\%$ is measured differently than from $\sigma = 40\%$ to $\sigma = 45\%$ (the former is more "significant" in Fisher-Rao terms because distributions are more distinguishable in the low-volatility regime).

2. **Correlation regime changes:** Two states with similar marginals but different correlation structures are far apart on the manifold.

3. **Tail behavior differences:** If using Student-t or GPD parameterizations, changes in tail thickness are captured with appropriate geometric weighting.

4. **Asymmetric sensitivity:** The metric naturally weights parameters by their statistical informativeness — it is large in directions where data is informative and small where data provides little discrimination.

---

## 3. Ricci Curvature as a Regime Indicator

### 3.1 Ricci Curvature on Riemannian Manifolds

The **Ricci curvature** $\text{Ric}(v, v)$ in direction $v$ at a point $p$ of a Riemannian manifold measures the average rate at which geodesics emanating from $p$ in a pencil around $v$ converge or diverge:

$$\text{Ric}(v, v) = \sum_{i=1}^{n-1} K(v, e_i)$$

where $K(v, e_i)$ is the sectional curvature in the plane spanned by $v$ and the orthonormal frame vector $e_i$.

**Geometric interpretation for market dynamics:**

- **Positive Ricci curvature:** Nearby geodesics converge. Neighboring market states "attract" each other — the system is **mean-reverting**. Distribution parameters tend to return to a central tendency.

- **Negative Ricci curvature:** Nearby geodesics diverge. Neighboring market states "repel" each other — the system is **trending** or **destabilizing**. Small perturbations in distribution parameters amplify.

- **Zero Ricci curvature:** Flat geometry. Market states evolve independently — **random walk** behavior in distribution space.

This is fundamentally different from other regime detection methods (HMM, threshold-based, etc.) because it uses the intrinsic geometric structure of the space of distributions, not ad hoc features extracted from price time series.

### 3.2 Scalar Curvature of the Statistical Manifold

The **scalar curvature** $R$ is the trace of the Ricci tensor — a single number summarizing the overall curvature at a point:

$$R = g^{ij} R_{ij}$$

For the manifold of normal distributions $\mathcal{N}(\mu, \sigma^2)$, the scalar curvature is constant: $R = -1$ (hyperbolic space). But for richer families (Student-t, skew-normal, mixture models), $R$ varies across the manifold and can serve as a state-dependent regime indicator.

**Key insight:** As market return distributions move from the "normal regime" (low $R$, near-Gaussian) toward the "crisis regime" (high kurtosis, skewed), the curvature of the statistical manifold changes. Tracking $R(\theta_t)$ over time gives a geometric regime signal.

### 3.3 Numerical Computation of Ricci Curvature on Statistical Manifolds

For a parametric family with metric $g_{ij}(\theta)$:

**Step 1: Christoffel symbols**

$$\Gamma^k_{ij} = \frac{1}{2} g^{kl}\left(\frac{\partial g_{il}}{\partial \theta^j} + \frac{\partial g_{jl}}{\partial \theta^i} - \frac{\partial g_{ij}}{\partial \theta^l}\right)$$

Compute via finite differences of the metric tensor:

$$\frac{\partial g_{ij}}{\partial \theta^k} \approx \frac{g_{ij}(\theta + h e_k) - g_{ij}(\theta - h e_k)}{2h}$$

**Step 2: Riemann curvature tensor**

$$R^l{}_{ijk} = \frac{\partial \Gamma^l_{jk}}{\partial \theta^i} - \frac{\partial \Gamma^l_{ik}}{\partial \theta^j} + \Gamma^l_{im}\Gamma^m_{jk} - \Gamma^l_{jm}\Gamma^m_{ik}$$

**Step 3: Ricci tensor**

$$R_{ij} = R^k{}_{ikj} = \sum_k R^k{}_{ikj}$$

**Step 4: Scalar curvature**

$$R = g^{ij} R_{ij}$$

For a 2D manifold (e.g., normal family parameterized by $\mu, \sigma$), this reduces to the Gaussian curvature and is computationally cheap. For higher-dimensional families, the tensor algebra grows as $O(n^4)$ where $n$ is the number of parameters, but remains feasible for moderate $n$.

### 3.4 Sectional Curvature for Specific Market Directions

Rather than computing the full Ricci tensor, we can focus on sectional curvatures in financially meaningful directions:

- **$K(\partial_\mu, \partial_\sigma)$:** curvature in the mean-volatility plane. Measures the tendency for mean-volatility trajectories to converge or diverge.
- **$K(\partial_\sigma, \partial_\gamma)$:** curvature in the volatility-skewness plane. Captures the geometric relationship between vol expansion and skew dynamics.
- **$K(\partial_\gamma, \partial_\kappa)$:** curvature in the skewness-kurtosis plane. Relates to the onset of tail risk.

---

## 4. Geodesics on Statistical Manifolds

### 4.1 Geodesic Equations

Geodesics on the statistical manifold satisfy:

$$\frac{d^2\theta^k}{ds^2} + \Gamma^k_{ij} \frac{d\theta^i}{ds} \frac{d\theta^j}{ds} = 0$$

For the normal manifold $\mathcal{N}(\mu, \sigma)$, geodesics are semicircles in the upper half-plane model (the Poincaré disk), and can be computed analytically.

For general parametric families, geodesics must be computed by numerically integrating the geodesic ODE. Standard methods: 4th-order Runge-Kutta with adaptive step size on the geodesic equation.

### 4.2 Geodesic Distance to Historical Crash States

**Core application:** Define a set of "reference crash states" $\{\theta_{\text{crash}}^{(k)}\}$ — the distribution parameters estimated during known crisis periods (2008 GFC, 2020 COVID, 2022 rate shock, etc.). At each time $t$, compute:

$$d_{\text{crash}}(t) = \min_k d_{FR}(\theta_t, \theta_{\text{crash}}^{(k)})$$

This measures "how far the current market state is from a historical crash" **in distribution space**. Unlike Euclidean distance on parameters, this properly accounts for the geometry — a shift in volatility from 10% to 20% is much more significant (in Fisher-Rao terms) than from 40% to 50%.

**Advantages over raw parameter tracking:**
- Invariant under reparameterization of the distribution family
- Naturally weights moments by their statistical informativeness
- Captures multivariate interactions between parameters
- Provides a single, principled distance measure

### 4.3 Geodesic Velocity and Acceleration

The **geodesic velocity** at time $t$ is:

$$v(t) = \sqrt{g_{ij}(\theta_t) \dot{\theta}_t^i \dot{\theta}_t^j}$$

This measures how fast the market state is moving through distribution space. Spikes in geodesic velocity correspond to rapid regime transitions.

The **geodesic acceleration** measures deviation from geodesic motion:

$$a^k(t) = \ddot{\theta}^k_t + \Gamma^k_{ij}(\theta_t) \dot{\theta}^i_t \dot{\theta}^j_t$$

Nonzero acceleration means the market trajectory is being "forced" off the natural geodesic path — an external perturbation is acting on the system.

### 4.4 Exponential and Logarithmic Maps

The **exponential map** $\text{Exp}_p(v)$ takes a tangent vector $v$ at point $p$ and returns the point reached by following the geodesic from $p$ in direction $v$ for unit time. The **logarithmic map** $\text{Log}_p(q)$ is its inverse — the initial velocity of the geodesic from $p$ to $q$.

These are essential for:
- **Geodesic interpolation:** generating intermediate market states between two observed states
- **Fréchet mean:** computing the "average" market state on the manifold (not the Euclidean average of parameters)
- **Parallel transport:** comparing tangent vectors (rate of change of distributions) at different points on the manifold

---

## 5. Ollivier-Ricci Curvature on Market Graphs

### 5.1 Discrete Ricci Curvature via Optimal Transport

The **Ollivier-Ricci curvature** (Ollivier, 2009) is a discrete analogue of Ricci curvature defined on metric spaces equipped with a family of probability measures. For a graph $G = (V, E)$ with edge weights, the curvature of an edge $(x, y)$ is:

$$\kappa(x, y) = 1 - \frac{W_1(m_x, m_y)}{d(x, y)}$$

where:
- $d(x, y)$ is the graph distance (or weighted distance) between nodes $x$ and $y$
- $m_x$ is a probability measure on the neighbors of $x$ (typically the lazy random walk measure)
- $W_1(m_x, m_y)$ is the **Wasserstein-1 distance** (earth mover's distance) between $m_x$ and $m_y$

**Interpretation:** If the neighborhoods of $x$ and $y$ are "close" (many shared neighbors, strong overlap), then $W_1(m_x, m_y) < d(x, y)$ and $\kappa > 0$ (positive curvature). If the neighborhoods are "far apart" (dispersed, few shared neighbors), then $W_1(m_x, m_y) > d(x, y)$ and $\kappa < 0$ (negative curvature).

### 5.2 Construction of Market Correlation Networks

Following Sandhu et al. (2016), the market graph is constructed as:

**Step 1: Correlation matrix estimation**

For a rolling window $[t-W, t]$, compute the sample correlation matrix $C_t$ from log-returns.

**Step 2: Distance transformation**

Convert correlations to distances:

$$d_{ij} = \sqrt{2(1 - C_{ij})}$$

This is the standard Mantegna distance (1999), based on the fact that $\sqrt{2(1-\rho)}$ is a proper metric on $[-1, 1]$.

**Step 3: Graph construction**

- Compute the **Minimum Spanning Tree (MST)** of the complete distance graph
- Add back edges with correlation above a threshold $\rho_{\min}$ (typically 0.5-0.7)
- This produces a sparse but connected graph that captures the essential correlation structure

**Step 4: Edge weighting**

Weight edges by the correlation magnitude: $w_{ij} = |C_{ij}|$.

### 5.3 Computing Ollivier-Ricci Curvature

**Probability measures on neighborhoods:**

For each node $x$, define the lazy random walk measure:

$$m_x(z) = \begin{cases} p & \text{if } z = x \\ (1-p) \cdot \frac{w_{xz}}{\sum_{y \sim x} w_{xy}} & \text{if } z \sim x \\ 0 & \text{otherwise} \end{cases}$$

where $p$ is the laziness parameter (commonly $p = 0.5$), and $z \sim x$ means $z$ is a neighbor of $x$.

**Wasserstein distance computation:**

$W_1(m_x, m_y)$ is the solution to the linear program:

$$W_1(m_x, m_y) = \min_{\pi \in \Pi(m_x, m_y)} \sum_{i,j} d(i, j) \pi(i, j)$$

where $\Pi(m_x, m_y)$ is the set of all transport plans (joint distributions with marginals $m_x$ and $m_y$). This is a standard optimal transport problem solvable by the simplex method or network flow algorithms.

**Aggregate curvature:**

The **average Ollivier-Ricci curvature** of the market graph at time $t$:

$$\bar{\kappa}(t) = \frac{1}{|E|} \sum_{(x,y) \in E} \kappa(x, y)$$

Or the **weighted average** using edge weights:

$$\bar{\kappa}_w(t) = \frac{\sum_{(x,y) \in E} w_{xy} \kappa(x, y)}{\sum_{(x,y) \in E} w_{xy}}$$

### 5.4 Empirical Results: Curvature and Market Crashes

Sandhu et al. (2016), published in *Science Advances*, computed Ollivier-Ricci curvature for the S&P 500 correlation network over the period 1998-2013. Key findings:

1. **Curvature drops precede crashes.** Average curvature $\bar{\kappa}$ shows significant decline in the months preceding both the 2000 dotcom crash and the 2008 financial crisis.

2. **Negative correlation with fragility.** Ricci curvature and network fragility are negatively correlated — as fragility increases (network becomes more susceptible to perturbation), curvature decreases.

3. **Stronger signal than entropy.** The curvature indicator outperforms network entropy as an early warning signal.

4. **Computational tractability.** The curvature computation is a linear program, making it more tractable and well-behaved than entropy-based measures.

Subsequent work by Samal et al. (2021) in *Royal Society Open Science* confirmed these findings and extended them to Forman-Ricci curvature (a combinatorial variant that is even cheaper to compute).

Bochner, Guillen & Fargues (2024) further validated the indicator by testing the elasticity of the Ollivier-Ricci curvature with respect to different network construction parameters, confirming the robustness of the signal across the 2008 GFC, the 2020 COVID crash, and other stress events.

Recent work (2025) by researchers studying the NASDAQ 100 has used **Ricci flow** — the evolution equation $\frac{\partial g_{ij}}{\partial t} = -2R_{ij}$ — on the market graph to study the *intrinsic* evolution of market geometry, finding that Ricci flow "smooths out" transient noise while preserving structural features.

### 5.5 Forman-Ricci Curvature (Faster Alternative)

The **Forman-Ricci curvature** is a combinatorial analogue that avoids the optimal transport computation:

$$F(e) = w_e \left(\frac{w_{v_1}}{w_e} + \frac{w_{v_2}}{w_e} - \sum_{e' \sim e} \frac{w_e}{\sqrt{w_e \cdot w_{e'}}}\right)$$

where $e = (v_1, v_2)$ is an edge, $w$ denotes weights, and the sum is over edges sharing a vertex with $e$.

Computational complexity: $O(|E| \cdot d_{\max})$ where $d_{\max}$ is the maximum node degree — linear in practice. No LP solver needed.

---

## 6. Practical Implementations in Literature

### 6.1 Gidea & Katz (2018) — Topological Data Analysis for Crash Prediction

**Paper:** "Topological Data Analysis of Financial Time Series: Landscapes of Crashes," *Physica A*, 491, 820-834.

**Method:**
- Take sliding windows of daily returns for major US indices (DJIA, Nasdaq, Russell 2000, S&P 500), 1989-2016
- Map each window to a point cloud in $\mathbb{R}^d$ via time-delay embedding
- Build Vietoris-Rips simplicial complexes at multiple scales
- Compute **persistent homology** — track the birth and death of topological features (connected components = $H_0$, loops = $H_1$, voids = $H_2$) across scales
- Encode persistence in **persistence landscapes** $\lambda_k: \mathbb{R} \to \mathbb{R}$
- Track the $L^p$-norms of persistence landscapes over time

**Key result:** The $L^p$-norms of persistence landscapes exhibit strong upward trends ~250 trading days before both the 2000 dotcom crash and the 2008 Lehman bankruptcy. The spectral density at low frequencies of these norms provides an early warning signal.

**Connection to our work:** Persistent homology captures *topological* features of the market state space. The geodesic distance framework from information geometry captures *metric* features. These are complementary — homology detects "holes" and "tunnels" in the distribution manifold that geodesic distances miss, while geodesics provide quantitative distance measures that homology lacks. A combined approach would be strictly more powerful than either alone.

**Status in Victoria:** We already have TDA/persistent homology research documented in `2026-04-06-persistent-homology-tda-crash-prediction.md`. The information-geometric framework should integrate with, not replace, the TDA pipeline.

### 6.2 Sandhu et al. (2016) — Ricci Curvature for Market Fragility

**Paper:** "Ricci curvature: An economic indicator for market fragility and systemic risk," *Science Advances*, 2(5), e1501495.

**Method:** See Section 5.4 above. Core contribution: demonstrating that Ollivier-Ricci curvature on the stock correlation network serves as a leading indicator of market crashes, outperforming entropy-based measures.

### 6.3 Samal et al. (2021) — Network Geometry and Market Instability

**Paper:** "Network geometry and market instability," *Royal Society Open Science*, 8(2), 201734.

**Method:** Compared multiple discrete curvature measures (Ollivier-Ricci, Forman-Ricci, augmented Forman-Ricci) on financial correlation networks. Found that both Ollivier-Ricci and Forman-Ricci capture market instabilities, with Forman-Ricci being computationally cheaper while maintaining similar predictive power.

### 6.4 Random Matrix Theory Connections (Laloux et al.)

**Paper:** Laloux, Cizeau, Bouchaud & Potters (1999), "Noise Dressing of Financial Correlation Matrices," *Physical Review Letters*.

**Key result:** ~94% of the eigenvalue spectrum of empirical correlation matrices for S&P 500 stocks is indistinguishable from the Marchenko-Pastur distribution (i.e., noise). Only the few eigenvalues exceeding the upper MP bound $\lambda_+ = \sigma^2(1 + \sqrt{N/T})^2$ carry genuine signal.

**Connection to information geometry:** The eigenvalue distribution of the correlation matrix lives on a specific manifold — the **Wishart manifold** for sample covariance matrices, or the **SPD manifold** $\mathcal{S}_{++}^N$ for the true correlation matrix. The Fisher-Rao metric on this manifold naturally separates signal from noise:

- Eigenvalues within the MP bulk contribute negligible Fisher-Rao distance
- Eigenvalues exceeding the MP bound dominate the metric
- **Denoised Fisher-Rao distance:** compute the Fisher-Rao metric using only the signal eigenvalues (those above $\lambda_+$), zeroing out the noise eigenvalues. This gives a cleaner geometric signal.

### 6.5 Amari & Nagaoka — Information Geometry for Statistical Inference

**Book:** Amari & Nagaoka (2000), "Methods of Information Geometry," AMS/Oxford.

Foundational text establishing the framework. Key results relevant to finance:
- Dual structure of statistical manifolds enables efficient projection (e-projection and m-projection correspond to maximum likelihood and moment matching, respectively)
- Pythagorean theorem on statistical manifolds: for projections onto exponential/mixture subfamilies
- α-divergence family unifies KL-divergence, Hellinger distance, and χ²-divergence

### 6.6 Recent Developments (2024-2025)

**Turkish Market Structural Break (2024):** Analysis of BIST-100 documented an extraordinary mid-2022 structural break featuring dimensional collapse (from 2.4 to 0.43 intrinsic dimensions), network density surge to 0.97, and Ricci curvature spike to 16.0, establishing a persistent hypersynchronized regime through 2024-2025.

**NASDAQ 100 Ricci Flow (2025):** Application of discrete Ricci flow to the NASDAQ 100 correlation graph, using the flow to study the intrinsic geometric evolution of the market over time. The Ricci flow smooths the graph geometry, revealing persistent structural features.

**Quantum Algorithms for ORC (2025):** Exploration of quantum algorithms for estimating Ollivier-Ricci curvature, potentially offering speedups for large-scale market graph computations (relevant for scaling to the full Russell 3000 or global equities).

---

## 7. Implementation Sketch for Victoria

### 7.1 Computing Fisher Metric from Rolling OHLCV Data

```
ALGORITHM: Rolling Fisher Metric Computation
─────────────────────────────────────────────
Input:  OHLCV data for N assets, window size W, step size S
Output: Time series of Fisher metric tensors G(t)

For each time step t = W, W+S, W+2S, ..., T:
    1. Extract returns r[t-W:t] for all N assets
    
    2. Estimate distribution parameters:
       a. μ_t = mean(r[t-W:t], axis=0)           # N-vector
       b. Σ_t = cov(r[t-W:t])                     # N×N matrix
       c. (Optional) Fit Student-t: ν_t via MLE
       d. (Optional) Compute rolling skewness, kurtosis
    
    3. Compute Fisher information matrix:
       
       Option A — Normal model (fast, closed-form):
         G_μμ = Σ_t^{-1}                          # N×N block
         G_ΣΣ[ij,kl] = 0.5 * Σ_t^{-1}[ik] * Σ_t^{-1}[jl]
                      + 0.5 * Σ_t^{-1}[il] * Σ_t^{-1}[jk]
         (Full G is (N + N(N+1)/2) × (N + N(N+1)/2))
       
       Option B — Numerical (any distribution):
         For each parameter pair (i,j):
           Compute g_ij via Monte Carlo:
           g_ij ≈ (1/M) Σ_{m=1}^{M} (∂log p/∂θ_i)(x_m) * (∂log p/∂θ_j)(x_m)
           where x_m ~ p(x|θ_t) and derivatives are via finite differences
    
    4. Store G(t)
```

**Dimensional reduction for tractability:**

For $N = 500$ assets, the full multivariate normal Fisher metric lives in $\sim$125K dimensions. Practical approaches:

- **Factor model reduction:** Fit a $K$-factor model ($K \approx 10$-$50$). The Fisher metric on the factor parameter space is much smaller.
- **Sector-level aggregation:** Compute sector-level return distributions (11 GICS sectors → 11-dimensional problem).
- **SPD manifold shortcut:** Use only the covariance matrix $\Sigma_t$ and compute the affine-invariant distance $d(\Sigma_1, \Sigma_2) = \|\log(\Sigma_1^{-1/2}\Sigma_2\Sigma_1^{-1/2})\|_F$. This discards mean information but is fast and well-supported by `pyriemann`.

### 7.2 Numerical Ricci Curvature Approximation

```
ALGORITHM: Numerical Scalar Curvature on 2D Statistical Manifold
────────────────────────────────────────────────────────────────
Input:  Parameter point θ = (θ¹, θ²), metric function g(θ), step size h
Output: Scalar curvature R(θ)

1. Compute metric tensor components:
   g₁₁, g₁₂, g₂₂ at θ and at 4 neighboring points (±h in each direction)

2. Compute partial derivatives via central differences:
   ∂g_ij/∂θ^k ≈ (g_ij(θ + h·eₖ) - g_ij(θ - h·eₖ)) / (2h)

3. Compute inverse metric: g^{ij} = inv([g₁₁, g₁₂; g₂₁, g₂₂])

4. Compute Christoffel symbols (8 independent components for 2D):
   Γ^k_{ij} = 0.5 * g^{kl} * (∂g_{il}/∂θ^j + ∂g_{jl}/∂θ^i - ∂g_{ij}/∂θ^l)

5. Compute partial derivatives of Christoffel symbols:
   ∂Γ^k_{ij}/∂θ^l via finite differences (requires metric at 8 more points)

6. Compute Riemann tensor:
   R^l_{ijk} = ∂Γ^l_{jk}/∂θ^i - ∂Γ^l_{ik}/∂θ^j + Γ^l_{im}·Γ^m_{jk} - Γ^l_{jm}·Γ^m_{ik}

7. Contract to get Gaussian curvature (= scalar curvature / 2 in 2D):
   K = R^1_{212} / det(g)

8. Return R = 2K
```

For higher-dimensional manifolds, the same algorithm scales as $O(n^4)$ in the number of parameters $n$. For $n \leq 10$ (factor model), this is fast. For $n > 50$, consider stochastic curvature estimation.

### 7.3 Geodesic Distance Computation

```
ALGORITHM: Geodesic Distance via Shooting Method
────────────────────────────────────────────────
Input:  Start point θ₀, end point θ₁, metric function g(θ)
Output: Geodesic distance d(θ₀, θ₁)

1. Initial guess: v₀ = θ₁ - θ₀ (Euclidean direction)

2. Solve geodesic ODE from θ₀ with initial velocity v₀:
   d²θ^k/ds² + Γ^k_{ij}(θ(s)) · (dθ^i/ds)(dθ^j/ds) = 0
   θ(0) = θ₀, dθ/ds(0) = v₀
   
   Integrate via RK4 with adaptive step size to s = 1

3. Compute endpoint error: e = θ(1) - θ₁

4. If ||e|| > tolerance:
   Adjust v₀ using Newton-Raphson on the exponential map
   (requires computing the Jacobi field / sensitivity matrix)
   Go to step 2

5. Compute geodesic length:
   d = ∫₀¹ √(g_{ij}(θ(s)) · θ̇^i(s) · θ̇^j(s)) ds
```

**Faster alternative for SPD manifold:** Use the closed-form expression $d(\Sigma_1, \Sigma_2) = \sqrt{\sum_k (\log \lambda_k)^2}$ where $\lambda_k$ are generalized eigenvalues.

### 7.4 Ollivier-Ricci Curvature Pipeline

```
ALGORITHM: Market Graph ORC Computation
───────────────────────────────────────
Input:  Returns matrix R[T×N], window W, correlation threshold ρ_min
Output: Time series of average ORC κ̄(t)

For each time step t:
    1. Compute correlation matrix C_t from R[t-W:t]
    
    2. Convert to distance: d_ij = sqrt(2(1 - C_ij))
    
    3. Build MST from distance matrix (Kruskal/Prim)
    
    4. Add edges where C_ij > ρ_min (augmented MST)
    
    5. For each edge (i,j) in the graph:
       a. Define lazy random walk measures:
          m_i(k) = 0.5 if k==i, else 0.5 * w_ik / Σ_l w_il
          m_j(k) = 0.5 if k==j, else 0.5 * w_jk / Σ_l w_jl
       
       b. Solve optimal transport LP:
          W₁(m_i, m_j) = min Σ_{k,l} d(k,l) * π(k,l)
          subject to: Σ_l π(k,l) = m_i(k), Σ_k π(k,l) = m_j(l)
       
       c. Compute edge curvature:
          κ(i,j) = 1 - W₁(m_i, m_j) / d(i,j)
    
    6. Compute aggregate curvature:
       κ̄(t) = mean over edges of κ(i,j)
       (or weighted mean using correlation magnitudes)

Python libraries: NetworkX + POT (Python Optimal Transport)
                  or GraphRicciCurvature package (does all of this)
```

### 7.5 Turning Curvature into a Tradeable Signal

**Signal 1: Curvature Z-score**

$$z_\kappa(t) = \frac{\bar{\kappa}(t) - \text{mean}_{[t-L, t]}(\bar{\kappa})}{\text{std}_{[t-L, t]}(\bar{\kappa})}$$

where $L$ is a lookback period (e.g., 252 trading days). Large negative $z_\kappa$ → market fragility increasing → reduce risk exposure.

**Signal 2: Curvature momentum**

$$\Delta\kappa(t) = \bar{\kappa}(t) - \bar{\kappa}(t - \tau)$$

Sustained decline in curvature over period $\tau$ (e.g., 20-60 days) → trending toward fragility → defensive positioning.

**Signal 3: Geodesic distance to crash states**

$$d_{\text{crash}}(t) = \min_k d_{FR}(\theta_t, \theta_{\text{crash}}^{(k)})$$

When $d_{\text{crash}}$ falls below a threshold → market state is approaching a historical crash regime → maximum defensiveness.

**Signal 4: Curvature dispersion**

$$\text{Disp}(t) = \text{std}_{(i,j) \in E}\left[\kappa(i,j)\right]$$

High dispersion in edge curvatures → heterogeneous stress (some sectors stressed, others not) → sector rotation opportunity.

**Integration with existing Victoria signals:**

These geometric signals should be combined with existing alpha sources via the standard signal combination framework. The curvature signals are inherently *meta-signals* (signals about the regime/state of the market) rather than directional signals. They are best used as:

- **Position sizing modulators:** scale positions inversely with fragility
- **Regime switch triggers:** shift between mean-reversion and trend-following strategies
- **Risk budget allocation:** redistribute risk across sectors based on sectoral curvature

### 7.6 Computational Cost Analysis

**Target: 10-second cycle time for Victoria**

| Component | Complexity | N=500, W=60 | Time Est. |
|-----------|-----------|-------------|-----------|
| Rolling correlation matrix | $O(W \cdot N^2)$ | 15M ops | ~1ms |
| MST construction | $O(N^2 \log N)$ | 2.2M ops | ~0.5ms |
| Graph augmentation | $O(N^2)$ | 250K ops | ~0.1ms |
| ORC per edge (LP solve) | $O(d^3)$ per edge | ~500 edges × ~10³ | ~50ms |
| ORC total (all edges) | $O(\|E\| \cdot d_{\max}^3)$ | | ~50ms |
| Fisher metric (normal, closed-form) | $O(N^3)$ for inversion | 125M ops | ~5ms |
| Fisher metric (SPD distance) | $O(N^3)$ for eigendecomp | 125M ops | ~5ms |
| Scalar curvature (2D reduced) | $O(1)$ | constant | ~0.01ms |
| Scalar curvature (10D factor) | $O(n^4) = O(10^4)$ | 10K ops | ~0.1ms |
| Geodesic distance (SPD, closed-form) | $O(N^3)$ | 125M ops | ~5ms |
| Geodesic distance (shooting, 2D) | $O(K \cdot n)$ per iteration | ~100 RK4 steps | ~1ms |

**Total estimated time per cycle: ~60-70ms**

This is well within the 10-second cycle budget. The dominant cost is the ORC computation (solving one LP per edge). For the full S&P 500 graph with ~500-1000 edges in the augmented MST, this takes ~50ms using an optimized LP solver (e.g., `scipy.optimize.linprog` with HiGHS backend).

**Optimizations for production:**

1. **Incremental updates:** When the rolling window slides by one bar, only the correlation matrix changes slightly. Use rank-1 updates to the Cholesky factorization instead of recomputing from scratch.
2. **Parallel LP solves:** The ORC computation for each edge is independent — parallelize across edges using ThreadPool or GPU.
3. **Forman-Ricci as fast fallback:** If ORC is too slow, Forman-Ricci curvature is $O(|E| \cdot d_{\max})$ with no LP — ~1ms total.
4. **Precomputed crash reference states:** Store reference distribution parameters and precompute their metric tensors.

---

## 8. Visualization Approaches

### 8.1 Manifold Embedding (2D Projection of Fisher Metric Over Time)

**Method:** Multidimensional scaling (MDS) or t-SNE using Fisher-Rao distances.

- Compute pairwise Fisher-Rao distances between all market states $\{\theta_t\}_{t=1}^T$
- Apply classical MDS to embed these into 2D while preserving distances
- Color points by time (gradient from blue → red)
- Mark known crisis periods in a distinct color
- Add arrows showing the temporal flow direction

**What to look for:** Clusters indicate persistent regimes. Rapid jumps between clusters indicate regime transitions. The proximity of recent states to crisis clusters signals elevated risk.

### 8.2 Curvature Heatmaps (Time × Frequency)

**Method:** Wavelet decomposition of the curvature time series.

- Compute $\bar{\kappa}(t)$ at multiple rolling window sizes $W \in \{20, 40, 60, 120, 252\}$
- Create a heatmap with time on the x-axis and window size (frequency) on the y-axis
- Color by curvature value (red = negative/fragile, blue = positive/stable)

**What to look for:** Vertical bands of red spanning multiple frequencies indicate broad-based fragility. Localized red patches at specific frequencies indicate frequency-specific stress.

### 8.3 Geodesic Flow Visualization

**Method:** Streamlines on the parameter manifold.

- At each point $\theta_t$, compute the velocity vector $\dot{\theta}_t$
- Project the manifold into 2D (via MDS or PCA on parameters)
- Draw streamlines showing the flow direction
- Color by speed (geodesic velocity magnitude)
- Overlay the curvature field as a background color map

**What to look for:** Converging streamlines (positive curvature regions) indicate mean-reversion. Diverging streamlines (negative curvature regions) indicate trending. Stagnation points indicate equilibria.

### 8.4 Network Curvature Visualization

**Method:** Graph layout with edge coloring by ORC.

- Layout the market graph using a force-directed algorithm (Fruchterman-Reingold)
- Color edges by their Ollivier-Ricci curvature: red (negative) → white (zero) → blue (positive)
- Node size proportional to degree or sector market cap
- Animate over time to show the evolution of curvature structure

**What to look for:** Clusters of red edges indicate bottleneck regions where correlation structure is fragile. The transition from blue-dominant to red-dominant indicates systemic stress building.

### 8.5 Connection to Existing TDA/Persistent Homology Research

The information geometry framework and the persistent homology framework (documented in `2026-04-06-persistent-homology-tda-crash-prediction.md`) provide complementary views:

| Aspect | Information Geometry | Persistent Homology |
|--------|---------------------|-------------------|
| What it measures | Metric structure (distances, curvature) | Topological structure (holes, voids, connectivity) |
| Input | Parameterized distributions | Point clouds / simplicial complexes |
| Key output | Ricci curvature, geodesic distances | Betti numbers, persistence diagrams |
| Crash signal | Curvature → negative (fragility) | Persistent $H_1$ loops grow (instability) |
| Regime detection | Curvature sign/magnitude | Topological phase transitions |
| Computational cost | $O(N^3)$ for SPD metric; $O(\|E\| \cdot d^3)$ for ORC | $O(n^3)$ for Rips complex; $O(n^\omega)$ for persistence |
| Uniqueness | Invariant metric ↔ information content | Invariant under continuous deformation |

**Unified pipeline for Victoria:**

```
OHLCV Data
  ├──→ Rolling Distribution Estimation
  │      ├──→ Fisher Metric → Geodesic Distance to Crash States  → Signal
  │      ├──→ Scalar Curvature of Statistical Manifold           → Signal
  │      └──→ SPD Manifold Velocity/Acceleration                 → Signal
  │
  ├──→ Correlation Network Construction
  │      ├──→ Ollivier-Ricci Curvature → Fragility Index         → Signal
  │      ├──→ Forman-Ricci Curvature (fast) → Cross-check        → Signal
  │      └──→ Ricci Flow → Structural Evolution                  → Signal
  │
  └──→ Point Cloud / Time-Delay Embedding
         ├──→ Persistent Homology → Persistence Landscapes       → Signal
         ├──→ Betti Curves → Topological Regime                  → Signal
         └──→ Wasserstein Distance on Diagrams                   → Signal
```

### 8.6 Gauge Theory Connection

The α-connections from information geometry are closely related to the gauge connections discussed in `2026-03-30-gauge-theory-fiber-bundles-arbitrage.md`. Specifically:

- The **Fisher-Rao metric** on the statistical manifold is the base metric, analogous to the spacetime metric in gauge theory.
- The **α-connections** are a family of affine connections, analogous to gauge connections on a fiber bundle.
- The **curvature of the α-connection** (distinct from Ricci curvature of the Fisher metric) measures the non-commutativity of parallel transport on the statistical manifold — this is directly related to the **arbitrage curvature** discussed in the gauge theory document.
- When $\alpha \neq 0$, the connection has torsion, and the holonomy of the connection around a closed loop in parameter space is nonzero — this corresponds to a "statistical arbitrage" in the information-geometric sense.

This suggests a unified geometric framework: gauge theory captures the fiber bundle structure (asset price dynamics over a base space of market states), while information geometry captures the intrinsic geometry of the base space itself (the manifold of market state distributions).

---

## 9. References

### Foundational Texts

- Amari, S. (1985). *Differential-Geometrical Methods in Statistics.* Lecture Notes in Statistics, Springer.
- Amari, S. & Nagaoka, H. (2000). *Methods of Information Geometry.* AMS/Oxford University Press.
- Chentsov, N. N. (1972). *Statistical Decision Rules and Optimal Inference.* Nauka (English translation: AMS, 1982).

### Fisher-Rao Metric and Information Geometry

- Rao, C. R. (1945). "Information and the accuracy attainable in the estimation of statistical parameters." *Bulletin of the Calcutta Mathematical Society*, 37, 81-91.
- Nielsen, F. (2020). "An Elementary Introduction to Information Geometry." *Entropy*, 22(10), 1100.
- Miyamoto, H. et al. (2023). "On Closed-Form Expressions for the Fisher–Rao Distance." arXiv:2304.14885.

### Ricci Curvature in Financial Markets

- Sandhu, R. S. et al. (2016). "Ricci curvature: An economic indicator for market fragility and systemic risk." *Science Advances*, 2(5), e1501495.
- Samal, A. et al. (2021). "Network geometry and market instability." *Royal Society Open Science*, 8(2), 201734.
- Bochner, B., Guillen, L., & Fargues, M. (2024). "On the Ollivier-Ricci curvature as fragility indicator of the stock markets." arXiv:2405.07134.
- (2025). "Intrinsic Geometry of the Stock Market from Graph Ricci Flow." arXiv:2510.15942.

### Ollivier-Ricci Curvature (Mathematical Foundations)

- Ollivier, Y. (2009). "Ricci curvature of Markov chains on metric spaces." *Journal of Functional Analysis*, 256(3), 810-864.
- Lin, Y. & Yau, S.-T. (2010). "Ricci curvature and eigenvalue estimate on locally finite graphs." *Mathematical Research Letters*, 17(2), 343-356.
- Lott, J. & Villani, C. (2009). "Ricci curvature for metric-measure spaces via optimal transport." *Annals of Mathematics*, 169(3), 903-991.
- Sturm, K.-T. (2006). "On the geometry of metric measure spaces." *Acta Mathematica*, 196(1), 65-131.

### Topological Data Analysis

- Gidea, M. & Katz, Y. (2018). "Topological Data Analysis of Financial Time Series: Landscapes of Crashes." *Physica A*, 491, 820-834.
- Bubenik, P. (2015). "Statistical Topological Data Analysis using Persistence Landscapes." *JMLR*, 16, 77-102.

### Random Matrix Theory

- Laloux, L., Cizeau, P., Bouchaud, J.-P., & Potters, M. (1999). "Noise Dressing of Financial Correlation Matrices." *Physical Review Letters*, 83(7), 1467-1470.
- Marchenko, V. A. & Pastur, L. A. (1967). "Distribution of eigenvalues for some sets of random matrices." *Mathematics of the USSR-Sbornik*, 1(4), 457-483.

### Optimal Transport

- Villani, C. (2008). *Optimal Transport: Old and New.* Springer.
- Peyré, G. & Cuturi, M. (2019). "Computational Optimal Transport." *Foundations and Trends in Machine Learning*, 11(5-6), 355-607.

### Software Libraries

- `GraphRicciCurvature` (Python): Compute Ollivier-Ricci and Forman-Ricci curvature on NetworkX graphs.
- `POT` (Python Optimal Transport): Efficient Wasserstein distance computation.
- `pyriemann`: Riemannian geometry for SPD matrices (BCI-oriented but applicable).
- `geomstats`: General-purpose Riemannian geometry in Python.
- `giotto-tda`: Topological data analysis (persistent homology, Vietoris-Rips).
- `GUDHI`: Comprehensive TDA library with alpha complexes, Rips complexes, persistence.

---

*This document should be read alongside:*
- `2026-04-06-persistent-homology-tda-crash-prediction.md` — TDA/persistent homology pipeline
- `2026-03-30-gauge-theory-fiber-bundles-arbitrage.md` — Gauge theory / fiber bundle framework
- `cross-asset-signals.md` — Existing signal architecture
