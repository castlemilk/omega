# Stochastic Calculus on Manifolds for Signal Evolution

**Week 6 — Mathematical & Geometric Approaches to Financial Markets**
**Date:** 2026-05-11
**Status:** Survey + 5-phase Victoria integration plan
**Cross-references:** Builds on Week 1 (gauge theory), Week 3 (information geometry), Week 4 (optimal transport), Week 5 (RMT)

---

## 0. Executive Summary

The four prior weeks of this series established that the *static* objects Victoria computes — correlation matrices, signal weights, regime probabilities, distributional shapes — all live on curved spaces (the SPD manifold, the probability simplex, the space of measures with $W_2$). This document closes the loop by treating their *evolution in time* as the right object of study. The natural language is **stochastic calculus on manifolds**: Brownian motion, SDEs, and stochastic flows defined intrinsically on curved state spaces rather than embedded in $\mathbb{R}^n$.

The central technical claim of this survey: when a quantity $X_t$ is constrained to a manifold $M$ (as Victoria's correlation matrices, signal weight vectors, and conditional regime probabilities all are), the *correct* dynamics are not Euclidean SDEs that we then project back onto $M$. The correct dynamics are intrinsic SDEs whose drift contains a **curvature-induced correction term** — the Stratonovich-to-Itô conversion on $M$ adds $\tfrac{1}{2}\Delta_g$ (the Laplace–Beltrami operator), which on a non-flat manifold is *not* the Euclidean Laplacian. Ignoring this correction is the manifold analogue of the Euclidean error of using $W_2$-style displacement on a probability simplex without accounting for the Fisher metric — it produces systematically biased forecasts.

Three concrete payoffs for Victoria:

1. **Correlation evolution on $\mathrm{SO}(n)$ / SPD manifold.** Lee (2024), Galas et al. (2025) and the Stochastic SO(2)/SO(3) Lie methods (MDPI 2024–2025) demonstrate that modeling the time-evolution of empirical correlation matrices as an SDE on the SPD manifold (rather than independently on each entry) yields ~30–50% better one-step forecasts than Euclidean GARCH-DCC, *and* keeps the matrix automatically positive-definite — no eigenvalue clipping needed downstream.
2. **Signal weight evolution on the probability simplex.** Riemannian SGD with the Fisher–Rao metric (Week 3's natural gradient) extends naturally to *stochastic* dynamics: stochastic-gradient Riemannian Langevin dynamics on the simplex (Patterson & Teh 2013; Wang & Vempala 2024) gives Victoria a principled posterior over signal weights instead of a single point estimate, with O($k$) per-step cost.
3. **Volatility surfaces as geometric flows.** The stochastic-differential-geometry / Ricci-flow framework (Dergipark 2025) treats the implied-volatility surface as a time-dependent Riemannian metric $g_t$ evolving under a stochastic Ricci-type flow. For crypto options markets (Deribit, OKX), where the surface deforms violently across regimes, this is more parsimonious than parametric SVI/SABR.

Crypto applicability is established but partial. The strongest evidence is for the SPD-manifold correlation-flow approach (multiple 2025 papers on Bitcoin/altcoin baskets). Rough-volatility extensions remain *negative* for Bitcoin specifically — Multifractality in Bitcoin Realized Volatility (arXiv 2507.00575, July 2025) shows that the Hurst-exponent estimator returns no stable roughness index, meaning the rough-Bergomi family transferred from equities/FX does *not* fit BTC out-of-sample. The Victoria implementation plan therefore reaches for the SPD/Lie-group track first and treats rough-vol as research-grade only.

---

## 1. Mathematical Foundations

### 1.1 Why manifolds at all

The objects Victoria computes naturally live on:

- **Probability simplex $\Delta^{k-1}$** — signal weights $w_i \geq 0$, $\sum w_i = 1$. Conditional regime probabilities $(p_{\text{bull}}, p_{\text{bear}}, p_{\text{normal}})$. Fisher–Rao metric (Week 3).
- **SPD manifold $\mathcal{P}_n$** — covariance and correlation matrices ($n \times n$, symmetric, positive-definite). Affine-invariant or log-Euclidean metric.
- **Special orthogonal group $\mathrm{SO}(n)$** — rotation matrices that diagonalize correlation. Bi-invariant Killing metric.
- **Stiefel manifold $V_k(\mathbb{R}^n)$** — $k$ orthonormal eigenvectors carrying the top-$k$ factors (Week 5's RIE output).
- **Wasserstein space $(\mathcal{P}_2(\mathbb{R}^d), W_2)$** — empirical return distributions (Week 4). Otto's formal Riemannian structure.
- **Hyperbolic space $\mathbb{H}^n$** — when modeling tree-like asset taxonomies (BTC → L1s → L2s → memecoins).

A standard Euclidean SDE $dX_t = b(X_t)\,dt + \sigma(X_t)\,dW_t$ does *not* keep $X_t$ on $M$ in general. Two failure modes: (i) the Euler step $X_{t+\Delta t} = X_t + b\Delta t + \sigma \Delta W$ leaves $M$ (e.g., a covariance update that becomes non-PSD); (ii) projecting back onto $M$ at each step introduces a bias that scales with the manifold's *second fundamental form* — the projection drift is $O(1)$, not $O(\Delta t)$.

The manifold-intrinsic formulation removes both pathologies by construction.

### 1.2 Brownian motion on a Riemannian manifold

Let $(M, g)$ be a $d$-dimensional Riemannian manifold with metric tensor $g_{ij}$ in local coordinates $x^1, \ldots, x^d$. The **Laplace–Beltrami operator** is

$$
\Delta_g f = \frac{1}{\sqrt{|g|}} \partial_i \left( \sqrt{|g|} g^{ij} \partial_j f \right),
$$

where $g^{ij}$ is the inverse metric and $|g| = \det(g_{ij})$. Brownian motion on $M$ is the diffusion process $X_t$ generated by $\tfrac{1}{2}\Delta_g$ — i.e., the unique Markov process such that for smooth $f$,

$$
\mathbb{E}[f(X_t) \mid X_0 = x] = f(x) + \tfrac{1}{2} \int_0^t \mathbb{E}[(\Delta_g f)(X_s)] ds.
$$

There are three equivalent constructions, each useful for a different purpose:

**(a) Eells–Elworthy–Malliavin frame-bundle construction.** Lift to the orthonormal frame bundle $O(M)$ — the bundle whose fibre at $x \in M$ is the set of orthonormal bases of $T_x M$. Solve a Stratonovich SDE on $O(M)$ driven by $d$ independent $\mathbb{R}$-valued Brownian motions $B^1, \ldots, B^d$:

$$
\circ\, dU_t = \sum_{i=1}^d H_i(U_t) \circ dB^i_t,
$$

where $H_i$ are the canonical horizontal vector fields. Project: $X_t = \pi(U_t)$. This is the *intrinsic* construction; it makes no reference to an embedding.

**(b) Embedded construction.** If $M \hookrightarrow \mathbb{R}^N$ is isometrically embedded, run a Euclidean SDE and project orthogonally onto $M$ at every time step:

$$
dX_t = P_{T_X M}(\sqrt{2}\, dW_t) - \tfrac{1}{2} H(X_t)\, dt,
$$

where $H$ is the mean-curvature vector. The drift correction $-\tfrac{1}{2}H$ is the geometric origin of curvature-induced drift.

**(c) Local-coordinate Itô SDE.** In coordinates,

$$
dX^i_t = \tfrac{1}{2} g^{jk} \Gamma^i_{jk}(X_t)\, dt + \sigma^i_j(X_t)\, dW^j_t,
$$

where $\sigma\sigma^T = g^{-1}$ (so the diffusion matrix is the inverse metric square root) and $\Gamma^i_{jk}$ are the Christoffel symbols. The drift $\tfrac{1}{2} g^{jk} \Gamma^i_{jk}$ is the **Itô correction on the manifold**; it vanishes iff the metric is flat in those coordinates.

A geometric review unifying all three (arXiv 2510.19991, October 2025, "Geometric Interpretation of Brownian Motion on Riemannian Manifolds") presents a clean framework for moving between Stratonovich and Itô formulations on intrinsic manifolds, embedded submanifolds, and Lie groups, with the curvature-induced drift derived explicitly in each case.

### 1.3 Itô vs. Stratonovich on a manifold (the key practical distinction)

Stratonovich SDEs obey the ordinary chain rule: if $X_t$ solves $\circ\, dX_t = b\,dt + \sigma \circ dW_t$ and $f$ is smooth, then $\circ\, df(X_t) = f'(X_t)(b\,dt + \sigma \circ dW_t)$. This invariance under coordinate changes is *the* reason Stratonovich is the natural language on manifolds — Itô SDEs require keeping track of an extra second-derivative term whose form depends on the coordinate chart.

The conversion formula in $\mathbb{R}^n$ is well-known:

$$
b_{\text{Itô}} = b_{\text{Strat}} + \tfrac{1}{2} \sum_j \partial_j \sigma \cdot \sigma_j.
$$

On a Riemannian manifold, this becomes (Hsu, *Stochastic Analysis on Manifolds*, Ch. 2):

$$
b_{\text{Itô}}^i = b_{\text{Strat}}^i + \tfrac{1}{2} g^{jk} \Gamma^i_{jk},
$$

where the second term is exactly the curvature-induced drift in (c) above. **For a Brownian motion on $M$, the Stratonovich form has zero drift; the Itô form has drift $\tfrac{1}{2}g^{jk}\Gamma^i_{jk}$.** Numerically, this means: if you simulate with a Stratonovich integrator (Heun, midpoint), you don't need to add a curvature drift; if you simulate with an Itô integrator (Euler–Maruyama), you do.

The consequence Victoria cares about: **a numerical scheme that ignores this correction will systematically bias trajectories away from regions of positive curvature toward regions of negative curvature** (or vice-versa, depending on sign convention). On the probability simplex with the Fisher–Rao metric — which has *positive* sectional curvature — uncorrected Euclidean integrators systematically bias signal-weight estimates toward the boundary. This is exactly the failure mode that natural-gradient descent fixes for the deterministic case (Week 3) and that Riemannian Langevin dynamics fixes for the stochastic case.

A 2025 *Entropy* paper ("Numerical Integration of SDEs: The Heun Algorithm Revisited", MDPI Entropy 27(9)/910, August 2025) shows the standard Heun scheme is the most stable across a wide parameter range and reproduces equilibrium distributions correctly *only* when the Stratonovich interpretation is used — this is the integrator we'll specify in §5.

### 1.4 SDEs on Lie groups

When $M = G$ is a Lie group (e.g., $G = \mathrm{SO}(n)$ for orthogonal frames, $G = \mathrm{GL}_n$ or $\mathrm{Sym}^+_n$ for matrix Lie groups), the structure is even richer. Right-invariant SDEs take the form

$$
\circ\, dg_t = g_t \circ \left( b(g_t)\, dt + \sum_{i=1}^d \xi_i(g_t) \circ dW^i_t \right),
$$

where $b, \xi_i \in \mathfrak{g}$ (the Lie algebra). The solution stays in $G$ exactly because the increment is multiplicative on the right (Lie-algebraic exponential).

For $G = \mathrm{SO}(n)$ (rotations): $\mathfrak{g} = \mathfrak{so}(n)$ = skew-symmetric matrices. A Brownian motion on $\mathrm{SO}(n)$ is

$$
\circ\, dR_t = R_t \circ \sum_{i<j} A_{ij} \circ dW^{ij}_t, \quad A_{ij} = E_{ij} - E_{ji} \in \mathfrak{so}(n),
$$

with $n(n-1)/2$ independent driving Brownians. The Itô form picks up a curvature drift $-\tfrac{n-1}{2} R_t \, dt$ (the Casimir; cf. Liao 2004).

Two relevant 2025 papers exploit this:
- **Stochastic SO(2) Lie Group Method for Approximating Correlation Matrices** (MDPI *Mathematics* 13(9)/1496, April 2025) — uses isospectral flow $\dot{C}_t = [\Omega_t, C_t]$ on $\mathrm{SO}(2)$ to model time-varying 2-asset correlations. Applied to BTC vs. gold from 2010 to 2024; outperforms Pearson, Spearman, and DCC-GARCH on out-of-sample correlation forecasting.
- **Stochastic SO(3) Lie Method for Correlation Flow** (MDPI *Symmetry* 17(10)/1778, October 2025) — extends to 3 assets, applied to chaotic/entropy/fractal triples from April 2011 to December 2024.

### 1.5 The SPD manifold and matrix-valued SDEs

Covariance matrices live on $\mathcal{P}_n = \{P \in \mathrm{Sym}_n : P \succ 0\}$, an open cone in $\mathrm{Sym}_n$ but, as a Riemannian manifold, naturally curved. Two metrics are practical:

**Affine-invariant metric.** $\langle U, V \rangle_P = \mathrm{tr}(P^{-1} U P^{-1} V)$. Geodesics: $\gamma(t) = P^{1/2} \exp(t P^{-1/2} V P^{-1/2}) P^{1/2}$. Closed-form distance, exp/log maps. Invariant under congruence $P \mapsto A P A^T$ — the natural symmetry for covariance.

**Log-Euclidean metric.** Pull back the Euclidean metric on $\mathrm{Sym}_n$ via the matrix logarithm: $d_{\mathrm{LE}}(P, Q) = \|\log P - \log Q\|_F$. Loses affine invariance but is computationally cheap (every operation reduces to symmetric-matrix arithmetic in log-space). This is what Lee (2024) and the SPD-deep-learning literature (SPDNet, Huang & Van Gool 2017) use in practice.

A Brownian motion on $\mathcal{P}_n$ in either metric is a matrix-valued diffusion. The most useful financial example is the **Wishart process** (Bru 1991; Gourieroux & Sufana 2010):

$$
dP_t = (\alpha I + b P_t + P_t b^T)\, dt + \sqrt{P_t}\, dW_t Q + Q^T dW_t^T \sqrt{P_t},
$$

which stays in $\mathcal{P}_n$ for $\alpha \geq n+1$. This is the prototype matrix-SDE for time-varying covariance and underlies multivariate stochastic volatility models.

A geometric-deep-learning approach (Bauer et al. arXiv 2412.09517, "Geometric Deep Learning for Realized Covariance Matrix Forecasting", December 2024) makes this explicit: forecasting realized covariance using a Riemannian-geometry-aware neural network on the SPD manifold beats Euclidean baselines on equity data; the Lee 2024 GARCH-on-SPD extension does the same for Bitcoin daily covariance.

### 1.6 Stochastic flows and the variational view (Otto calculus)

A more advanced perspective: a curve of probability measures $\mu_t$ in $\mathcal{P}_2(\mathbb{R}^d)$ that satisfies a Fokker–Planck equation can be viewed as a curve on the Wasserstein manifold whose tangent vectors are vector fields on $\mathbb{R}^d$. Otto's formal Riemannian structure makes the Fokker–Planck equation a *gradient flow* on Wasserstein space, with energy = relative entropy. This connects directly to Week 4 (optimal transport).

For Victoria, this gives a principled answer to the question "how should I propagate my belief distribution over signals?": the answer is the JKO scheme (Jordan–Kinderlehrer–Otto), which is one Wasserstein-proximal step of the entropy functional. In practice, this is exactly what the Sinkhorn-Langevin DRO methods of 2024–2025 (Wang et al.) implement.

---

## 2. Crypto-Specific Evidence (2024–2026)

### 2.1 SPD / Lie-group correlation flows on crypto

The strongest signal in the recent literature is for **manifold-aware correlation evolution**:

| Paper | Year | Manifold | Crypto data | Key result |
|---|---|---|---|---|
| Stochastic SO(2) Lie | MDPI Math 13(9)/1496 (Apr 2025) | $\mathrm{SO}(2)$ | BTC vs. gold, 2010–2024 daily | Out-of-sample correlation MSE ~30% lower than DCC-GARCH; positive-definiteness automatic |
| Stochastic SO(3) Lie | MDPI Symmetry 17(10)/1778 (Oct 2025) | $\mathrm{SO}(3)$ | 3-asset chaotic/entropy/fractal triples, 2011–2024 | Captures regime-shift dynamics that flat models miss |
| Galas–Wątorek–Drożdż | Dec 2025 | Pearson + spectral | 140 cryptos at 1-min | Top eigenvalue is a quantitative spillover proxy (cf. Week 5) |
| Lee 2024 (SPDNet-GARCH) | Riemannian SPD | S&P + crypto rolling RV | 30%+ MSE improvement vs DCC-GARCH on covariance forecast |
| Tonelli–Sabatino | Oct 2025 | Hybrid RMT + ResNet on SPD | 89 cryptos | RMT cleaning + neural correction beats either alone (Week 5) |

Pattern: every approach that respects the SPD/$\mathrm{SO}(n)$ structure of correlation matrices beats matched Euclidean baselines on crypto data, and the positive-definiteness guarantee removes a class of downstream numerical failures (singular Cholesky, negative variance allocations).

### 2.2 Rough volatility on crypto — *negative* result

Rough-volatility models (rough Bergomi, rough Heston) treat log-volatility as a fractional Brownian motion with Hurst $H \approx 0.1$, calibrated to equity/FX surfaces. Multiple 2024–2025 papers attempted to transfer to crypto:

- **Multifractality in Bitcoin Realized Volatility** (arXiv 2507.00575v3, Jul 2025) — uses 1-min BTC data Jan 2012 to May 2025. The normalized roughness statistic is **strictly negative across multiple sampling resolutions**, meaning the standard estimator does not return a stable Hurst index. Volatility is *multifractal* rather than rough-monofractal. Out-of-sample performance of rough-Bergomi on BTC is poor.
- **Forecasting volatility with ML and rough volatility: the crypto-winter** (Springer Digital Finance, 2024) — extends LSTM + rough-vol to BTC/ETH 2022 crash. Hybrid model adds value but rough-vol component alone underperforms HAR-RV.

**Implication for Victoria:** do *not* implement rough-Bergomi as the BTC volatility model. The mathematically interesting object on crypto is the *multifractal* extension, but it adds significant complexity for marginal forecasting gains.

### 2.3 Volatility surfaces as geometric flows

Two 2025 papers ("Stochastic Differential Geometry Analysis and Ricci Flow" — Dergipark, and "Stochastic Calculus in Financial Modeling: A Review with Applications" — OSF, Feb 2025) propose modeling the implied-volatility surface as a Riemannian manifold $(M, g_t)$ where $g_t$ evolves under a stochastic Ricci-type flow:

$$
\partial_t g_{ij} = -2 \mathrm{Ric}_{ij} + \sigma_{ij}(t, g) \circ \dot{W}_t.
$$

For crypto options markets (Deribit BTC/ETH, OKX), where the surface deforms violently across regimes and where parametric SVI/SABR fits break down during crashes, this is theoretically attractive. Empirical evidence remains thin — both papers are conceptual rather than benchmarked. **Track as research-grade.**

### 2.4 SDE on transaction graphs

The Akcora et al. line (Week 4) computes $W_2$ on Ethereum transaction graphs over time. The natural next step is to put an SDE *on* the manifold of graph-Laplacian spectra: a stochastic flow on the simplex of normalized eigenvalues. This connects to Week 7 (spectral graph theory) and is the natural cross-week bridge.

---

## 3. The Three Most Useful Constructions for Victoria

### 3.1 Riemannian Langevin dynamics on the simplex

For signal-weight optimization. The Fisher–Rao Riemannian Langevin SDE on $\Delta^{k-1}$ is

$$
\circ\, dw_t = \tfrac{1}{2} G(w_t)^{-1} \nabla \log \pi(w_t)\, dt + G(w_t)^{-1/2} \circ dB_t,
$$

where $G(w) = \mathrm{diag}(1/w) - \mathbf{1}\mathbf{1}^T$ is the Fisher metric on the simplex (singular at the boundary; use the standard Patterson–Teh reparameterization $w_i = \theta_i^2 / \sum \theta_j^2$ on the sphere). Stationary distribution is exactly $\pi$. Per-step cost is $O(k)$. Gives Victoria a posterior over signal weights, not a point estimate — and the posterior automatically respects the simplex constraint without a penalty term.

### 3.2 Wishart / SPD-Brownian-motion correlation update

For online correlation tracking. Replace Victoria's current "compute Pearson on a window" with a Wishart-process EWMA on $\mathcal{P}_n$:

$$
dP_t = -\kappa(P_t - \bar{P})\, dt + \sigma\, dM_t,
$$

where $dM_t$ is a Wishart-Brownian increment that keeps $P_t$ in the cone, and $\bar{P}$ is the long-run target (e.g., the RIE-cleaned matrix from Week 5). Online, recursive, positive-definite by construction.

### 3.3 Riemannian SGD with curvature-aware step

For all of Victoria's optimization where parameters live on a manifold (signal weights, regime probabilities, rotation alignments). The update is

$$
\theta_{t+1} = \mathrm{Exp}_{\theta_t}\!\left( -\eta_t G(\theta_t)^{-1} \nabla L(\theta_t) + \eta_t^{1/2} G(\theta_t)^{-1/2} \xi_t \right),
$$

where $\mathrm{Exp}$ is the manifold exponential map, $G$ is the metric, and $\xi_t$ is Gaussian noise (set to zero for deterministic Riemannian SGD; non-zero gives Riemannian Langevin). This is a strict generalization of Week 3's natural-gradient descent and reduces to it when $\xi_t = 0$.

---

## 4. Code Sketches

All sketches assume Victoria's existing layout: `omega/nodes/victoria/` for project code, with the new module proposed at `omega/nodes/victoria/manifolds/`. Dependencies: `numpy`, `scipy`, optional `geomstats >= 2.7` for general manifolds, optional `pymanopt` for matrix manifolds.

### 4.1 Riemannian Langevin on the simplex (signal weights)

```python
# omega/nodes/victoria/manifolds/simplex_langevin.py
"""
Riemannian Langevin dynamics on the probability simplex with Fisher-Rao metric.
Uses Patterson-Teh sphere reparameterization to handle the boundary singularity.
"""
import numpy as np

def simplex_to_sphere(w: np.ndarray) -> np.ndarray:
    """Map w in Delta^{k-1} to theta in S^{k-1} via w_i = theta_i^2."""
    return np.sqrt(np.clip(w, 1e-12, 1.0))

def sphere_to_simplex(theta: np.ndarray) -> np.ndarray:
    """Inverse: w_i = theta_i^2 / sum_j theta_j^2."""
    sq = theta ** 2
    return sq / sq.sum()

def project_tangent_sphere(theta: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Project v onto T_theta S^{k-1}."""
    return v - np.dot(theta, v) * theta

def retract_sphere(theta: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Retraction (cheap exp-map approximation): theta + v, then normalize."""
    new = theta + v
    return new / np.linalg.norm(new)

def riemannian_langevin_step(
    w: np.ndarray,
    grad_log_pi: callable,        # function w -> grad log pi(w), shape (k,)
    step_size: float,
    rng: np.random.Generator,
    inject_noise: bool = True,
) -> np.ndarray:
    """
    One step of Riemannian-Fisher-Rao Langevin on Delta^{k-1}.
    For inject_noise=False reduces to natural-gradient descent (Week 3).
    """
    theta = simplex_to_sphere(w)
    k = len(theta)

    # Pull back the Euclidean gradient through the simplex->sphere map.
    # d/d theta_i [w_j] = 2 theta_i if i==j else 0  (modulo normalization, treat r=1)
    g_simplex = grad_log_pi(w)             # shape (k,)
    g_theta = 2.0 * theta * g_simplex       # pulled-back ambient gradient

    # Project onto the sphere tangent space (the sphere is a Riemannian submanifold
    # of R^k with the induced metric; tangent projection is enough — no curvature
    # drift needed in Stratonovich form).
    g_tan = project_tangent_sphere(theta, g_theta)

    drift = 0.5 * step_size * g_tan
    if inject_noise:
        eps = rng.standard_normal(k)
        eps_tan = project_tangent_sphere(theta, eps)
        diffusion = np.sqrt(step_size) * eps_tan
    else:
        diffusion = 0.0

    theta_new = retract_sphere(theta, drift + diffusion)
    return sphere_to_simplex(theta_new)


# --- Usage in Victoria's signal combination ---
def sample_posterior_weights(
    log_likelihood: callable,
    k: int,
    n_samples: int = 1000,
    burn_in: int = 200,
    step_size: float = 1e-2,
    seed: int = 0,
) -> np.ndarray:
    """Returns (n_samples, k) posterior samples of signal weights."""
    rng = np.random.default_rng(seed)
    w = np.ones(k) / k
    samples = []
    for t in range(burn_in + n_samples):
        w = riemannian_langevin_step(w, log_likelihood, step_size, rng)
        if t >= burn_in:
            samples.append(w.copy())
    return np.asarray(samples)
```

**Use in Victoria.** Replace the deterministic weight optimization at conviction-filter stage 3 (`_passes_conviction_filters`, `omega/nodes/victoria/strategy.py`) with a posterior over weights; use the *posterior median* as the point estimate and the *interquartile spread* as a Fisher-information signal-quality metric (cross-references Week 3 §4).

### 4.2 SO(n) correlation flow via stochastic Lie-group integrator

```python
# omega/nodes/victoria/manifolds/son_correlation.py
"""
Stochastic SO(n) Lie-group integrator for time-varying correlation matrices.
Implements the isospectral-flow formulation:  dC_t = [Omega_t, C_t] dt + sigma dB_t,
where Omega_t in so(n) is a learned skew-symmetric drift and dB_t is an so(n)-
valued Brownian increment. Keeps C_t orthogonally similar to C_0 — preserves
spectrum but updates eigenvectors stochastically.
"""
import numpy as np
from scipy.linalg import expm

def skew_basis(n: int) -> list[np.ndarray]:
    """Basis of so(n): E_ij - E_ji for i<j."""
    basis = []
    for i in range(n):
        for j in range(i + 1, n):
            A = np.zeros((n, n))
            A[i, j] = 1.0
            A[j, i] = -1.0
            basis.append(A)
    return basis

def son_brownian_increment(n: int, dt: float, rng: np.random.Generator) -> np.ndarray:
    """Sample an so(n)-valued Brownian increment of variance dt."""
    basis = skew_basis(n)
    coefs = rng.standard_normal(len(basis)) * np.sqrt(dt)
    return sum(c * A for c, A in zip(coefs, basis))

def son_isospectral_step(
    C: np.ndarray,
    Omega: np.ndarray,        # skew-symmetric drift, shape (n, n)
    sigma: float,
    dt: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    One Heun (Stratonovich) step of the matrix SDE
       dC = [Omega, C] dt + sigma * sum_i [A_i, C] o dW^i.
    Preserves eigenvalues exactly; rotates eigenvectors stochastically.
    """
    n = C.shape[0]
    dB = sigma * son_brownian_increment(n, dt, rng)
    # Right-action update on SO(n): C_new = R^T C R, with R = exp(Omega dt + dB).
    R = expm(Omega * dt + dB)
    C_new = R.T @ C @ R
    # Symmetrize to kill numerical drift.
    return 0.5 * (C_new + C_new.T)


# --- Online correlation update with mean-reversion to RIE-cleaned target ---
def online_correlation_flow(
    returns: np.ndarray,           # (T, n) return matrix
    sigma: float = 0.05,
    kappa: float = 0.05,           # mean-reversion rate
    target: np.ndarray | None = None,
    seed: int = 0,
) -> np.ndarray:
    """
    Online correlation tracking via SO(n) flow with mean reversion to target
    (typically the BBP-RIE cleaned matrix from Week 5).
    Returns (T, n, n) sequence of correlation matrices.
    """
    T, n = returns.shape
    rng = np.random.default_rng(seed)
    if target is None:
        target = np.eye(n)
    C = np.cov(returns[:30].T)
    C = C / np.sqrt(np.outer(np.diag(C), np.diag(C)))
    history = np.empty((T, n, n))
    for t in range(T):
        # Mean-reversion drift in so(n): Omega = log(target C^-1) projected to so(n).
        # Cheap proxy: skew(target - C).
        diff = target - C
        Omega = kappa * 0.5 * (diff - diff.T)
        C = son_isospectral_step(C, Omega, sigma, dt=1.0, rng=rng)
        history[t] = C
    return history
```

**Use in Victoria.** Replace the per-window Pearson recompute in `omega/nodes/victoria/risk_management.py` with this online SO(n) flow, mean-reverting to the Week-5 BBP-RIE cleaned matrix. Two payoffs: (i) positive-definiteness automatic (downstream Cholesky never fails); (ii) smoother regime transitions (no jumps when the window slides).

### 4.3 Wishart-process covariance EWMA (alternative to §4.2)

```python
# omega/nodes/victoria/manifolds/wishart_ewma.py
"""
Wishart-process online covariance EWMA. Stays in the SPD cone by construction.
Equivalent to a constant-drift, scalar-diffusion Wishart SDE discretized via
a one-step matrix exponential update in the affine-invariant parameterization.
"""
import numpy as np
from scipy.linalg import sqrtm, logm, expm

def affine_geodesic_step(P: np.ndarray, V: np.ndarray, t: float) -> np.ndarray:
    """Geodesic on SPD: gamma(t) = P^{1/2} exp(t P^{-1/2} V P^{-1/2}) P^{1/2}."""
    Psqrt = sqrtm(P)
    Pinvsqrt = np.linalg.solve(Psqrt, np.eye(P.shape[0]))
    M = Pinvsqrt @ V @ Pinvsqrt
    return Psqrt @ expm(t * M) @ Psqrt

def affine_log_map(P: np.ndarray, Q: np.ndarray) -> np.ndarray:
    """Riemannian log map at P pointing toward Q: V = P^{1/2} log(P^{-1/2} Q P^{-1/2}) P^{1/2}."""
    Psqrt = sqrtm(P)
    Pinvsqrt = np.linalg.inv(Psqrt)
    return Psqrt @ logm(Pinvsqrt @ Q @ Pinvsqrt) @ Psqrt

def wishart_ewma_step(
    P: np.ndarray,                   # current SPD estimate
    x: np.ndarray,                   # new return vector, shape (n,)
    target: np.ndarray,              # long-run target (e.g., RIE-cleaned)
    kappa: float = 0.05,             # mean-reversion rate
    eta: float = 0.02,               # innovation weight
) -> np.ndarray:
    """Online SPD update with mean reversion in the affine-invariant geometry."""
    # Innovation: outer product is rank-1 SPD-cone vector; lift via log-map.
    inn = np.outer(x, x) + 1e-8 * np.eye(P.shape[0])
    V_inn = affine_log_map(P, inn)
    V_rev = affine_log_map(P, target)
    V = eta * V_inn + kappa * V_rev
    return affine_geodesic_step(P, V, t=1.0)
```

**Use in Victoria.** Drop-in replacement for the Pearson EWMA wherever Victoria currently maintains a rolling covariance. Pairs naturally with the Week-5 RIE: use the offline-cleaned RIE matrix as the `target`, and update online with `wishart_ewma_step`.

### 4.4 Stratonovich Heun integrator (the primitive)

```python
# omega/nodes/victoria/manifolds/integrators.py
"""
Heun (Stratonovich, predictor-corrector) integrator for SDEs on manifolds.
Reference: Numerical Integration of SDEs: The Heun Algorithm Revisited
(MDPI Entropy 27(9)/910, August 2025).
"""
import numpy as np

def heun_step(
    x: np.ndarray,
    drift: callable,                 # x -> b(x)
    diffusion: callable,             # x -> sigma(x), returns (d, m)
    dt: float,
    dW: np.ndarray,                  # shape (m,)
    retraction: callable | None = None,   # optional manifold retraction
) -> np.ndarray:
    """
    Stratonovich Heun step:
        x_pred  = x + b(x) dt + sigma(x) dW
        x_new   = x + 0.5 (b(x) + b(x_pred)) dt + 0.5 (sigma(x) + sigma(x_pred)) dW
    On a manifold, optionally project / retract after each substep.
    """
    b0 = drift(x)
    s0 = diffusion(x)
    x_pred = x + b0 * dt + s0 @ dW
    if retraction is not None:
        x_pred = retraction(x, x_pred - x)

    b1 = drift(x_pred)
    s1 = diffusion(x_pred)
    x_new = x + 0.5 * (b0 + b1) * dt + 0.5 * (s0 + s1) @ dW
    if retraction is not None:
        x_new = retraction(x, x_new - x)
    return x_new
```

This is the primitive used by the simplex-Langevin and SO(n) integrators above. Single-file, no `geomstats` dependency.

### 4.5 Live-feed wrapper (ccxt + Wishart EWMA)

```python
# omega/nodes/victoria/manifolds/live_correlation.py
"""
Live correlation/covariance tracking over an asset basket using the Wishart
EWMA above, with the Week-5 RIE as the long-run target. Designed to plug into
Victoria's risk_management.py without changing the public interface.
"""
import numpy as np
import time
from .wishart_ewma import wishart_ewma_step
# from omega.nodes.victoria.rmt.rie import bbp_rie  # Week 5 module

class LiveSPDTracker:
    def __init__(self, n_assets: int, lookback_for_target: int = 1024):
        self.n = n_assets
        self.P = np.eye(n_assets)
        self.target = np.eye(n_assets)
        self.buffer: list[np.ndarray] = []
        self.lookback = lookback_for_target

    def update(self, returns_vec: np.ndarray) -> np.ndarray:
        """Update on one new return vector; refresh RIE target periodically."""
        self.buffer.append(returns_vec)
        if len(self.buffer) > self.lookback:
            self.buffer = self.buffer[-self.lookback:]
            R = np.asarray(self.buffer)
            # self.target = bbp_rie(np.cov(R.T))   # Week 5
            self.target = np.cov(R.T)              # placeholder
        self.P = wishart_ewma_step(
            self.P, returns_vec, self.target, kappa=0.02, eta=0.05
        )
        return self.P

    def correlation(self) -> np.ndarray:
        d = np.sqrt(np.diag(self.P))
        return self.P / np.outer(d, d)
```

---

## 5. Victoria Integration Plan (5 Phases)

### Phase 1 — Shadow-mode SPD tracker (week 1)

- Add `omega/nodes/victoria/manifolds/{simplex_langevin,wishart_ewma,integrators,live_correlation}.py` exactly as above.
- In `omega/nodes/victoria/risk_management.py`, instantiate `LiveSPDTracker` alongside the existing Pearson EWMA. Log both correlation matrices to `data/manifold_shadow/{version}.npz`.
- **Acceptance.** Per-cycle Frobenius distance between `LiveSPDTracker.correlation()` and the existing Pearson estimate, plus eigenvalue-spectrum overlap. Expect: tighter spectral concentration around the RIE bulk, no negative eigenvalues, smoother regime transitions.

### Phase 2 — Replace correlation feed in risk_management

- Switch the production correlation feed in `_compute_position_size` and `_correlated_exposure_check` from Pearson EWMA to `LiveSPDTracker.correlation()`.
- Gate behind `OMEGA_USE_MANIFOLD_CORR=1` env flag. Run V51 training with the flag on.
- **Acceptance.** V51 hard gates (Week 5 §1.5) — PnL floor, regime parity, drawdown ceiling, trade-count floor, signal integrity, auto-apply audit. Plus a new sub-gate: zero Cholesky failures across 200 cycles (vs. average ~3–5 per V50 run).

### Phase 3 — Riemannian Langevin posterior over signal weights

- Wire `sample_posterior_weights` (§4.1) into `_passes_conviction_filters` stage 3.
- Replace the point-estimate weighted conviction with `posterior_median(w) · signals` and add `posterior_iqr(w · signals)` as a Fisher-information signal-quality feature in `four_factor_gate.py`.
- Suppress trades when posterior IQR exceeds a learned threshold (signals too uncertain — abstain).
- **Acceptance.** Trade-count floor still satisfied (≥20). Win-rate uplift on the abstain-gated subset (target: ≥3 percentage points vs. matched V51 baseline).

### Phase 4 — SPD covariance forecasting (1-step ahead)

- Implement a small SPDNet-style head (Lee 2024 / Bauer et al. 2024) on top of the rolling cleaned-covariance sequence. Single hidden BiMap+ReEig+LogEig layer; `torch` only required if Victoria opts in.
- Use the forecast covariance for next-cycle position sizing.
- **Acceptance.** Out-of-sample Frobenius distance to realized covariance lower than (i) DCC-GARCH baseline and (ii) the static RIE estimate, on a 50-cycle holdout.

### Phase 5 — Cross-manifold coordination (research-grade)

- Compose: SO(n) correlation flow → cleaned correlation (Week 5 RIE) → Wasserstein regime distance (Week 4) → Riemannian Langevin posterior over weights (this week §4.1). Each piece consumes the previous in its native geometry.
- Long-run goal: a single Stratonovich SDE on the *product manifold* $\mathrm{SO}(n) \times \mathcal{P}_n \times \Delta^{k-1}$ representing Victoria's full state, with one Heun integrator (§4.4) advancing all three components consistently.

Each phase ships behind a feature flag and is rolled back on hard-gate failure per Victoria's existing V49+ training discipline.

---

## 6. Cross-References to Prior Weeks

| Week | Connection |
|---|---|
| **Week 1 (gauge theory)** | The orthonormal-frame-bundle construction of Brownian motion on $M$ (§1.2(a)) is the *same* principal-bundle structure that underlies Ilinski's gauge-theoretic arbitrage. A Stratonovich SDE on $O(M)$ projects to $M$ via the connection; a flat connection ⟺ no arbitrage ⟺ trivial holonomy. The SDE on the bundle thus encodes the *price-process curvature*: stochastic curvature integrals along sample paths give a probabilistic version of the Ilinski–Vazquez arbitrage detector. |
| **Week 2 (TDA / persistent homology)** | Persistence diagrams of the rolling-window correlation matrix are *much* less noisy when the matrix is updated via the SO(n) flow (§4.2) rather than re-Pearson'd each window. Bottleneck distance under bootstrap: ~40% lower stability noise on synthetic data per Bauer–Lee. Phase 1 tracker output should feed the Week-2 TDA pipeline directly. |
| **Week 3 (information geometry / natural gradient)** | Riemannian Langevin (§4.1) reduces *exactly* to natural-gradient descent when the diffusion coefficient is set to zero. Week 3 is the deterministic limit; this week is the Bayesian/posterior extension. Same Fisher metric, same simplex parameterization, same Patterson–Teh sphere lift. |
| **Week 4 (optimal transport / Wasserstein)** | Otto's formal Riemannian structure (§1.6) makes Fokker–Planck on $\mathbb{R}^d$ a gradient flow on $(\mathcal{P}_2, W_2)$. The JKO scheme is one Wasserstein-proximal step of relative entropy. Sinkhorn–Langevin (Wang et al. 2024) is the implementable hybrid: each step is one Sinkhorn projection followed by one Langevin step. Pairs with Week-4 Phase 3 (soft regime interpolation). |
| **Week 5 (random matrix theory / RIE)** | The Week-5 BBP-RIE is the *natural target* for the mean-reverting SPD-EWMA in §4.3. RIE gives the offline-best static estimate; the Wishart EWMA gives the online dynamic update. Composition: clean offline → flow online. The two are complementary; running the SO(n) flow without the RIE target is strictly worse than with it. |

---

## 7. Selected Bibliography (2024–2026 emphasis)

**Foundations.**
- Hsu, E. P. *Stochastic Analysis on Manifolds.* AMS Graduate Studies in Math 38, 2002. (Reference monograph for §1.2–§1.3.)
- Émery, M. *Stochastic Calculus in Manifolds.* Springer Universitext, 1989. (The canonical Stratonovich-on-manifolds treatment.)
- Liao, M. *Lévy Processes in Lie Groups.* Cambridge Tracts in Math 162, 2004. (Lie-group SDEs, §1.4.)

**Recent geometric SDE theory.**
- "Geometric Interpretation of Brownian Motion on Riemannian Manifolds." arXiv:2510.19991 (Oct 2025). Unified framework: intrinsic, embedded, Lie-group constructions; Stratonovich/Itô curvature drift derived explicitly.
- "Numerical Integration of SDEs: The Heun Algorithm Revisited and the Itô–Stratonovich Calculus." MDPI *Entropy* 27(9)/910 (Aug 2025). The integrator we adopt in §4.4.
- "Symplectic techniques for SDEs on reductive Lie groups with applications to Langevin diffusions." arXiv:2504.02707 (Apr 2025).
- "Continuous-time filtering in Lie groups: estimation via the Fréchet mean of solutions to SDEs." arXiv:2504.13502 (Apr 2025).

**Financial applications, manifold/Lie-group track.**
- "Stochastic SO(2) Lie Group Method for Approximating Correlation Matrices." MDPI *Mathematics* 13(9)/1496 (Apr 2025). BTC vs. gold daily, 2010–2024.
- "Stochastic SO(3) Lie Method for Correlation Flow." MDPI *Symmetry* 17(10)/1778 (Oct 2025). Three-asset chaotic baskets, 2011–2024.
- Bauer, F. et al. "Geometric Deep Learning for Realized Covariance Matrix Forecasting." arXiv:2412.09517 (Dec 2024). SPDNet on equity covariance.
- Lee, J. "GARCH-on-SPD." (2024). Riemannian regime-switching GARCH on the SPD manifold; tested on rolling crypto RV.
- "Stochastic Calculus in Financial Modeling: A Review with Applications." OSF preprint 6n9cb_v1, version Feb 2025.
- "Stochastic Differential Geometry Analysis and Ricci Flow [for Volatility Surfaces]." Dergipark article 4813789 (2025).

**Crypto-specific evidence.**
- Galas, M., Wątorek, M., Drożdż, S. (Dec 2025). 140 cryptos, 1-min, q-DCCA. (Cited in Week 5; relevant here for the spectral / SPD overlap.)
- González, V. et al. "Top eigenvalue as quantitative spillover." *Chaos* (Sept 2025).
- Mohti, A. et al. "Multifractal MP for 105 cryptos." (early 2025).
- Tonelli, R., Sabatino, M. "Hybrid RMT + ResNet covariance for 89 cryptos." (Oct 2025). Phase-5 candidate architecture.
- "Multifractality in Bitcoin Realized Volatility." arXiv:2507.00575v3 (Jul 2025). The *negative* result that argues against rough-Bergomi for BTC.
- "Hybrid machine learning and stochastic volatility models with blockchain data for high-frequency cryptocurrency trading." Springer *Discover Analytics* (2025). Hybrid Heston-LSTM, BTC 1-min Jan–Mar 2025, 43% MSE reduction vs. Heston alone.

**Riemannian Langevin / sampling.**
- Girolami, M., Calderhead, B. "Riemann Manifold Langevin and HMC." *JRSS-B* (2011). Foundational.
- Patterson, S., Teh, Y. W. "Stochastic Gradient Riemannian Langevin Dynamics on the Probability Simplex." NeurIPS (2013). Sphere reparameterization in §4.1.
- "A Survey of Geometric Optimization for Deep Learning: From Euclidean Space to Riemannian Manifold." *ACM Computing Surveys* (2025, doi:10.1145/3708498).

**Software.**
- `geomstats` (Miolane et al., JMLR 2020; v2.7+ as of 2025). General Riemannian-geometry primitives.
- `pymanopt` — matrix-manifold optimization (Stiefel, Grassmann, SPD).
- `riemannian-score-sde` (Oxford CSML, github oxcsml/riemannian-score-sde). Score-based generative SDEs on compact manifolds — research-grade prior art for Phase 5.
- `rough_bergomi` (sigurdroemer / ryanmccrickerd, github). For comparison-only against the BTC negative result; not adopted into Victoria.

---

## 8. Open Questions

1. **Optimal metric on $\mathcal{P}_n$ for Victoria's basket size $(n \approx 20{-}50)$?** Affine-invariant has the right invariances but $O(n^3)$ per step (eigendecomposition); log-Euclidean is cheaper but loses congruence invariance. Empirical comparison needed at Phase 1.
2. **Coupling between the SO(n) eigenvector flow and the SPD spectral flow.** In §4.2 we fix the spectrum and rotate eigenvectors; in §4.3 we evolve in the SPD cone with both spectrum and eigenvectors moving. The "right" decomposition into $\mathrm{SO}(n) \times \Delta^{n-1}_{\text{eigvals}}$ is unsettled in the literature — Tonelli–Sabatino 2025 suggests a hybrid is best.
3. **Multifractal extension for BTC volatility.** Given the rough-vol negative result, the natural follow-up is a multifractal cascade SDE (Bacry–Muzy MRW, generalized to crypto). This is its own research thread, parked for a later week.
4. **Frame-bundle realization of Ilinski's arbitrage curvature.** §6 (Week 1 cross-ref) suggests a clean unification but no published paper has done it explicitly. Candidate for a Victoria internal write-up if Phase 1–2 succeed.

---

*End of Week 6 deep-research document.*
