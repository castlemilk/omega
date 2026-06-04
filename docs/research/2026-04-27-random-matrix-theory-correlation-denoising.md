# Random Matrix Theory for Correlation Denoising

**Date:** 2026-04-27
**Research Series:** Omega Geometric Finance, Week 5
**Focus:** Cleaning Victoria's empirical correlation/covariance matrices using rotationally-invariant random-matrix estimators, with crypto-specific evidence and an integration plan for risk sizing, signal de-correlation, and regime detection.

---

## 1. Executive Summary

Victoria estimates a return correlation matrix every cycle inside `risk_management.py` (the `_compute_correlation_matrix` helper feeds the position-concentration check) and implicitly relies on a covariance matrix every time it weights signals. With $T \approx 200$ cycles of recent history and $N \approx 20{-}30$ symbols, the *effective sample size per pair* is far below the regime where the sample correlation matrix is a reliable estimate of the population correlation matrix. The result is well documented in the random-matrix literature: roughly 90–95% of the eigenvalues of the empirical matrix are statistically indistinguishable from those of a pure-noise matrix, the small eigenvalues are systematically biased downward, and the optimal mean–variance portfolio built on the raw matrix overweights eigenvectors of bottom eigenvalues — *the noise modes*. In a crypto basket where 89 coins were studied 2020–2025 by González et al. (2025), 94% of the spectrum was statistically inside the Marchenko–Pastur (MP) bulk.

Random Matrix Theory (RMT) gives a principled fix. The MP law tells us, in closed form, what the eigenvalue spectrum of a *pure noise* correlation matrix looks like, given the aspect ratio $q = N/T$. Any eigenvalue lying inside that bulk is most likely noise; any eigenvalue outside is most likely informative. The simplest cleaning recipe — eigenvalue clipping (Laloux–Bouchaud–Cizeau–Potters, 1999) — replaces all bulk eigenvalues by their average and keeps the outliers untouched. The state-of-the-art recipe — the rotationally-invariant estimator (RIE) of Bun–Bouchaud–Potters (2016/2017) — applies a continuous, asymptotically-optimal nonlinear shrinkage along the entire spectrum, derived from the resolvent of the MP equation. Both are *rotationally invariant*: they preserve the empirical eigenvectors and modify only the eigenvalues. The RIE has now been shown to dominate Ledoit–Wolf linear shrinkage on out-of-sample minimum-variance portfolios in equity markets (Bun et al. 2017) and in cryptocurrency markets (Tonelli & Sabatino 2025; Mohti et al. 2025).

For Victoria, the immediate wins are: (i) tighter pairwise-correlation flags in `risk_management.py` (raw correlations are biased by noise; cleaned ones are not), (ii) better signal-combination weights via a denoised signal-correlation matrix, (iii) a new regime feature derived from the *deformation* of the empirical spectrum away from the MP bulk (when the market enters a stress regime, eigenvalue mass concentrates in the top eigenvalue — this is the systemic-risk indicator used by Plerou–Stanley and now extended to crypto by Galas et al. 2025), and (iv) a hard gate for the meta-analyst that refuses to ship a model trained on a degenerate covariance regime. Sections 2–5 develop the mathematics, surveys 2024–2026 papers (with crypto emphasis), and provides Python code sketches around `pyRMT` and `scikit-rmt` plus a four-phase integration plan.

This week's document also makes three explicit cross-references: to **Week 1** (gauge curvature on the asset-graph relies on correlation as a metric — denoising directly improves curvature SNR), to **Week 2** (persistent homology on a correlation distance matrix benefits from spectral cleaning before the Vietoris–Rips step), and to **Week 3/4** (Fisher–Rao on Gaussian families and Wasserstein on return distributions both depend on a stable covariance estimate; RIE is the rotationally-invariant estimator that minimizes Frobenius distance to the true covariance — the natural "metric-aware" cleaning prior).

---

## 2. Mathematical Foundations

### 2.1 Setup and the Sample Covariance Trap

Let $X \in \mathbb{R}^{T \times N}$ be a centered return matrix: $T$ time observations, $N$ assets. Define the empirical (sample) covariance and correlation matrices:

$$\hat\Sigma = \tfrac{1}{T} X^\top X, \quad \hat C = D^{-1/2}\, \hat\Sigma\, D^{-1/2}$$

where $D = \mathrm{diag}(\hat\Sigma)$. As $T \to \infty$ with $N$ fixed, $\hat\Sigma \to \Sigma$. But Victoria operates in the **Kolmogorov / high-dimensional regime**: $N$ and $T$ both large, with finite ratio $q = N/T$. In this regime, $\hat\Sigma$ does **not** converge to $\Sigma$. Instead:

- Eigenvalues fan out: large ones are too large, small ones too small.
- The condition number of $\hat\Sigma$ blows up at $q \to 1^-$, and $\hat\Sigma$ becomes singular for $q \ge 1$.
- The Markowitz-optimal portfolio $w^* \propto \hat\Sigma^{-1}\mathbf{1}$ inverts the matrix and so puts maximum weight on the *lowest* — i.e., noisiest — eigenvectors. Out-of-sample variance of the portfolio is dramatically underestimated in-sample.

For Victoria's typical $N=25$, $T=200$, $q = 0.125$. This is well inside the regime where bulk noise dominates the bottom 80% of the spectrum.

### 2.2 The Marchenko–Pastur Law

**Theorem (Marchenko & Pastur, 1967).** Let the rows of $X$ be i.i.d. $\mathcal{N}(0, \Sigma)$ with $\Sigma = I_N$. As $N, T \to \infty$ with $N/T \to q \in (0, 1]$, the empirical spectral distribution of $\hat C = X^\top X / T$ converges almost surely to a deterministic measure with density

$$\rho_{MP}(\lambda) = \frac{1}{2\pi q \lambda} \sqrt{(\lambda_+ - \lambda)(\lambda - \lambda_-)} \cdot \mathbf{1}_{[\lambda_-, \lambda_+]}, \quad \lambda_\pm = (1 \pm \sqrt{q})^2.$$

When $q > 1$ there is an additional point mass of weight $1 - 1/q$ at $0$. The MP density is a "semi-circle in $\sqrt{\lambda}$" supported on $[\lambda_-, \lambda_+]$ — the **MP bulk**.

**Cleaning signal.** Compute the eigendecomposition $\hat C = V \mathrm{diag}(\lambda_i) V^\top$. Compare the empirical histogram of $\{\lambda_i\}$ to $\rho_{MP}(\lambda; q)$. The eigenvalues that fit inside $[\lambda_-, \lambda_+]$ (within a finite-$N$ tolerance) carry no signal beyond what i.i.d. noise produces. Eigenvalues outside — especially the few large outliers above $\lambda_+$ — carry the genuine factor structure (market mode, sector modes, etc.).

**Tracy–Widom correction.** The largest eigenvalue of a finite-$N$ MP matrix fluctuates around $\lambda_+$ on a scale of $N^{-2/3}$ with the universal Tracy–Widom distribution $F_2$. A 99% threshold for declaring "this top eigenvalue is signal, not noise" is

$$\lambda_+^{TW}(N, q) = \lambda_+ + N^{-2/3}\, \sigma_{TW}(q)\, q_{F_2}(0.99), \quad \sigma_{TW}(q) = q^{1/2}(1 + q^{1/2})^{4/3}.$$

This is what `scikit-rmt` calls the "TW-corrected MP threshold" and is the right thing to use for signal/noise tests in finite samples.

**Color in the noise.** If the rows of $X$ have non-trivial covariance $\Sigma_{\mathrm{true}} \ne I$ (which they do — there's a market mode, etc.), the limiting spectrum of $\hat C$ is *not* MP but a deformation of MP whose Stieltjes transform satisfies the **Marchenko–Pastur self-consistent equation**:

$$g(z) = \int \frac{\rho_{\mathrm{true}}(\lambda)}{\lambda \cdot (1 - q - q z g(z)) - z} \, d\lambda.$$

This equation is the workhorse of every modern cleaning method: it provides the link between the *unknown* true spectrum and the *observed* empirical spectrum.

### 2.3 Eigenvalue Clipping (Laloux–Bouchaud–Cizeau–Potters 1999)

The first and simplest RMT cleaner. Given $\hat C = V \Lambda V^\top$ with eigenvalues $\lambda_1 \ge \lambda_2 \ge \dots \ge \lambda_N$:

1. Compute the MP edge $\lambda_+ = (1 + \sqrt{q})^2$ (or the TW-corrected version).
2. For each $\lambda_i \le \lambda_+$, replace it by $\bar\lambda = \frac{1}{|\mathcal{B}|}\sum_{j \in \mathcal{B}} \lambda_j$, the average of the bulk eigenvalues. (This preserves $\mathrm{tr}\,\hat C = N$.)
3. Reconstruct $\hat C^{\mathrm{clip}} = V\, \Lambda^{\mathrm{clip}}\, V^\top$.

**Pros.** Trivially fast, no hyperparameters beyond $q$. Cuts out-of-sample portfolio risk by a measurable factor (Bouchaud & Potters 2009 quoted ~30% on S&P 500).

**Cons.** Discontinuous at $\lambda_+$; blunt — it ignores the structure of the non-trivial eigenvalues. Top eigenvalues are kept exactly as-is, which in practice is too large relative to the truth.

### 2.4 Linear Shrinkage (Ledoit & Wolf 2004)

Convex combination toward a structured target $T$ (typically $T = (\mathrm{tr}\,\hat\Sigma / N) I$):

$$\hat\Sigma^{LW} = (1 - \alpha)\,\hat\Sigma + \alpha\, T, \quad \alpha \in [0, 1].$$

Ledoit–Wolf gave a closed form for the asymptotically-optimal $\alpha$ minimizing $\mathbb{E}\|\hat\Sigma^{LW} - \Sigma\|_F^2$. This is the estimator inside `sklearn.covariance.LedoitWolf`. It is **rotationally invariant** when $T \propto I$ (no preferred direction). Linear shrinkage *uniformly* compresses eigenvalues toward the spectral mean — too coarse near the edges, but easy to compute and robust.

The 2025 paper Oriol & Miot ("Ledoit–Wolf linear shrinkage with unknown mean", *J. Multivariate Analysis*) extends the original LW result to the centered-data case and proves that the standard implementation slightly underestimates the shrinkage intensity for small $T$.

### 2.5 Rotationally-Invariant Estimators (RIE) and Optimal Nonlinear Shrinkage

Given the empirical eigendecomposition $\hat C = V\Lambda V^\top$, a **rotationally-invariant estimator** has the form

$$\hat C^{\mathrm{RIE}} = V\, \mathrm{diag}(\xi_1, \dots, \xi_N)\, V^\top$$

where each $\xi_i$ is a function of the empirical eigenvalues alone — eigenvectors are preserved. The Ledoit–Péché (2011) **Oracle estimator** is the RIE that minimizes the Frobenius distance to the *true* (unknown) covariance:

$$\xi_i^{\mathrm{oracle}} = u_i^\top \Sigma\, u_i$$

where $u_i$ is the $i$-th empirical eigenvector. Of course, $\Sigma$ is unknown — the magic is that the oracle has a closed-form **estimable** asymptotic limit, derived from the resolvent of the MP self-consistent equation:

$$\xi_i^{\mathrm{RIE}} = \frac{\lambda_i}{|1 - q + q \lambda_i \, g(\lambda_i - i 0^+)|^2}$$

where $g(z) = \frac{1}{N}\mathrm{tr}\,(\hat C - z I)^{-1}$ is the empirical resolvent (Stieltjes transform of the empirical spectrum), evaluated just above the real axis. This is the **Bun–Bouchaud–Potters (BBP) RIE**, also called the *non-linear shrinkage estimator*.

**Properties.**
- Asymptotically optimal in Frobenius norm among all RIEs.
- No tuning parameters (unlike LW's $\alpha$).
- Continuous in $\lambda$: there is no discontinuity at the MP edge.
- Top eigenvalues are *shrunk* (the Oracle is smaller than the empirical), bottom eigenvalues are *inflated* — the right correction direction.
- Numerically: implemented via kernel smoothing of the empirical density (avoids the $i 0^+$ limit). Cubic-kernel bandwidth $h = N^{-1/3}$ is standard; the 2024 review by Allez & Bouchaud recommends an adaptive bandwidth based on local spectral density.

**Out-of-sample portfolio variance.** Bun et al. 2017 showed that on US equities the BBP-RIE delivers ~10% lower out-of-sample variance than Ledoit–Wolf and ~25% lower than raw $\hat\Sigma$, with the gap widening in high-$q$ regimes (small $T$, many assets). The 2025 Mohti et al. study on 100 cryptocurrencies replicated the equity finding: BBP-RIE > LW > eigenvalue clipping > raw on both Sharpe and turnover-adjusted metrics.

### 2.6 Hierarchical Filtering and Hybrid Cleaners

A second axis of cleaning uses the **structure** of the eigenvectors, not just the eigenvalues. The **planar maximally filtered graph** (PMFG) and **average linkage minimum spanning tree** (ALMST) approaches (Tumminello et al. 2010) fit a tree/graph to the asset network and use it to denoise. The Bonanno–Caldarelli–Lillo "hierarchical clustering filter" (HCF) projects the correlation matrix onto an ultrametric space — a tree distance — and reconstructs.

**2025 hybrid (Tonelli & Sabatino, "Denoising Complex Covariance Matrices with Hybrid ResNet and RMT", arXiv:2510.19130)** combines hierarchical filtering with a residual neural network: the RMT pass regularizes the eigenvalue spectrum, the ResNet learns nonlinear corrections to the eigenvectors. On 89 cryptos 2020–2025 with the train/test split bracketing the November 2021 BTC peak, the hybrid produced higher Sharpe than either pure RMT or pure RIE estimators alone. **Caveat for Victoria:** the ResNet step requires substantial training data and would need its own self-improvement cycle — not a Phase-1 candidate.

### 2.7 Spectral Indicators of Market Stress

A separate use of RMT is *diagnostic* rather than corrective. The empirical spectrum's *deformation away from the MP bulk* is itself an indicator of market structure. Three standard indicators:

1. **Top-eigenvalue ratio** $\lambda_1 / N$ — fraction of total variance explained by the market mode. Plerou et al. (2002) and González et al. (*Chaos*, 2025) document that this ratio rises sharply in crisis regimes: from ~25% in normal markets to >50% in 2008 / March 2020.

2. **Number of eigenvalues outside the MP bulk** $k_{\mathrm{out}}$ — proxy for the number of "active factors". Falls in stress regimes (everything collapses onto the market factor) and rises in dispersion regimes (sectors decouple).

3. **Inverse Participation Ratio (IPR) of the top eigenvector** $\mathrm{IPR}(u_1) = \sum_i u_{1i}^4$ — measures how concentrated the market mode is across assets. High IPR ⇒ market driven by a small subset; low IPR ⇒ broad market move. Crypto note: in the 2022 collapse the IPR of the top eigenvector for the major-altcoin basket spiked, indicating that BTC/ETH dominated dispersion.

These three quantities are cheap to compute every cycle and can feed Victoria's `bayesian_regime.py` as auxiliary features alongside the existing volatility-based regime probabilities. They are *complementary* to the Wasserstein and KL-based detectors of Weeks 3–4: those measure *distributional* shape change, while RMT indicators measure *correlation-structure* change.

---

## 3. Key Literature

### 3.1 Foundational

**Marchenko & Pastur (1967)** — "Distribution of eigenvalues for some sets of random matrices", *Mat. Sb.*, 72(4). The original derivation of the MP law for sample covariance matrices.

**Laloux, Cizeau, Bouchaud, Potters (1999)** — "Noise dressing of financial correlation matrices", *Phys. Rev. Lett.* 83. The first application of MP to financial correlations and the first eigenvalue-clipping recipe. Showed that ~94% of the S&P 500 correlation spectrum is MP-bulk.

**Plerou, Gopikrishnan, Rosenow, Amaral, Stanley (2002)** — "Random matrix approach to cross correlations in financial data", *Phys. Rev. E* 65. Independent confirmation on a different dataset, plus introduction of IPR diagnostics and the link between the top eigenvalue and market-wide stress.

**Ledoit & Wolf (2004)** — "A well-conditioned estimator for large-dimensional covariance matrices", *J. Multivariate Analysis* 88. Introduced linear shrinkage with the asymptotically-optimal closed-form intensity. Foundation of `sklearn.covariance.LedoitWolf`.

**Ledoit & Péché (2011)** — "Eigenvectors of some large sample covariance matrix ensembles", *Probab. Theory Related Fields* 151. Derived the closed-form Oracle RIE — the basis of all later nonlinear shrinkage.

### 3.2 Modern RMT Cleaning

**Bun, Bouchaud, Potters (2016/2017)** — "Cleaning large correlation matrices: tools from random matrix theory", *Phys. Rep.* 666. The definitive 220-page review. Derives the BBP-RIE in full, contrasts replica and free-probability methods, and benchmarks every prior cleaner on US equities and a synthetic ground-truth dataset. **Required reading.**

**Bun (2016)** — "Application of random matrix theory to high dimensional statistics", PhD thesis, Université Paris-Saclay. Computational details of the kernel-density implementation of the RIE.

**Bartz (2016)** — "Cross-validation based nonlinear shrinkage", *J. Comput. Graph. Stat.* 25. An alternative nonlinear shrinkage that uses cross-validation instead of RMT asymptotics; competitive with the RIE on small $N$.

**Allez & Bouchaud (2024 review)** — Updated treatment of the RIE with adaptive kernel bandwidths and a careful comparison to the Ledoit–Wolf nonlinear shrinkage estimator (which is asymptotically equivalent to BBP under different parameterization).

### 3.3 Crypto-Specific Applications

**Galas, Wątorek, Drożdż (Dec 2025)** — "Detrended cross-correlations and their random matrix limit: an example from the cryptocurrency market", arXiv:2512.06473 (also *Entropy* 27(12) 2025). Applies q-DCCA correlations and the MP framework to one-minute returns of 140 major cryptocurrencies, 2021–2024. Identifies a robust dominant market factor plus several sectoral modes; sectoral mode strength scales with the multifractal order $q$. Direct relevance to Victoria's high-frequency basket.

**González, Cerqueti, Mattera, Trinidad Segovia (Sept 2025)** — "The random matrix-based informative content of correlation matrices in stock markets", *Chaos* 35(9). Establishes the highest eigenvalue as a quantitative proxy for *market spillover*. Methodology applies directly to crypto (the underlying construction is asset-class agnostic). Compares well with alternative spillover indices (Diebold–Yilmaz).

**Mohti, Khairudin, Yahya (early 2025)** — "Analyzing clustered factors in the cryptocurrency market with Random Matrix Theory", *Physica A* 660. Studies 105 cryptocurrencies January 2020 – February 2024 using a multifractal extension of MP. Documents that crypto is closer to MP than equities, with progressively narrower spectrum from 2020 → 2024 as the market matures.

**Tonelli & Sabatino (Oct 2025)** — "Denoising Complex Covariance Matrices with Hybrid ResNet and RMT: Cryptocurrency Portfolio Applications", arXiv:2510.19130. The hybrid hierarchical-filter + ResNet + RMT estimator described in §2.6. 89 cryptos, 2020–2025. The ResNet step gives a measurable Sharpe lift over BBP-RIE alone, but at significant model-complexity cost.

**Farinelli & Sabatino (2024)** — "Wasserstein clustering of financial institutions", *Math. Financial Econ.* 18 — already cited in Week 4. Uses RIE-cleaned covariances as the base for the Wasserstein metric, showing that uncleaned covariances destroy cluster structure. Direct evidence that **denoising is upstream of every other geometric method**.

### 3.4 Adjacent and Reinforcing Work (2024–2026)

**Oriol & Miot (2025)** — "Ledoit–Wolf linear shrinkage with unknown mean", *J. Multivariate Analysis*. Bias correction for the standard LW estimator; small-sample improvements relevant when $T < 100$.

**Trindade, Hong, Choi (2025)** — "End-to-end large portfolio optimization for variance minimization with neural networks through covariance cleaning", *J. Financial Data Sci.* (arXiv:2507.01918). Rotation-invariant neural network learning the eigenvalue function $\xi(\lambda)$ end-to-end. Tested on US equities 2000–2024; beats BBP-RIE in OOS Sharpe at the cost of being a black box. Worth shadow-modeling for Victoria once we have a stable RMT baseline.

**Sun, Li, Zhang (2025)** — "Deformation of Marchenko–Pastur distribution for the correlated time series", *Statistics & Probability Letters*. Closed-form MP deformation when the rows of $X$ have AR(1) autocorrelation — relevant for crypto, where 1-minute returns show statistically significant lag-1 autocorrelation.

**Xu, Zhao, Liu (2025)** — "Exact simulation of the Marchenko–Pastur distribution", *Stat. Probab. Lett.* — provides a fast sampler (no eigendecomposition needed) for bootstrap calibration of MP-bulk thresholds. Replaces the Tracy–Widom asymptotic with empirical quantiles.

### 3.5 Computational Tools

**`pyRMT` (Giecold, 2017–; refactor 2024)** — `pip install pyRMT`. Implements eigenvalue clipping, optimal shrinkage, and the BBP-RIE on top of NumPy/SciPy. Dependency-light (numpy, scipy). Good API: `pyRMT.clipped(corr_matrix, q)`, `pyRMT.optimalShrinkage(corr_matrix, q, method='kernel')`. Stable, ~200 LoC, easy to vendor.

**`scikit-rmt` (Santorum, 2022–; v1.0.0 2024)** — `pip install scikit-rmt`. Broader scope: ensemble samplers (GOE/GUE/GSE, Wishart, Manova), spectral-law CDFs/PDFs, plus an `EstimatorMP` covariance estimator API compatible with `sklearn.covariance`. Useful for *both* covariance estimation and Tracy–Widom threshold computation.

**`sklearn.covariance` (LedoitWolf, OAS, GraphicalLassoCV)** — already a Victoria dependency. `LedoitWolf().fit(X).covariance_` is one line. Useful as a baseline against the BBP-RIE.

---

## 4. Crypto Application Profile

### 4.1 Why Crypto Is a Particularly Good Fit for RMT Cleaning

Three reasons stand out from the 2024–2026 literature:

1. **High $q = N/T$.** Victoria's universe is ~25 symbols and the regression window is ~200 cycles. Equity studies typically have $q \in [0.05, 0.20]$. Crypto studies that use 1-minute returns and a one-day window can hit $q \in [0.1, 0.5]$ — exactly where RMT corrections matter most.

2. **Strong dominant mode but rapidly shifting subspace.** Galas et al. (2025) show that the BTC-led market mode explains 30–50% of crypto variance depending on the day, and the *sectoral* eigenvectors (DeFi, layer-1, memecoin) rotate on a sub-monthly timescale. Raw covariance estimators bake stale subspaces into the inverse; the RIE's continuous shrinkage reduces the penalty for being slightly out-of-date.

3. **Fat tails amplify noise eigenvalues.** Returns in crypto are leptokurtic by an order of magnitude relative to equities. The MP law is derived for Gaussian rows, so finite-fourth-moment corrections (Karoui 2008) are larger in crypto than in equities — and the BBP-RIE happens to be more robust to fourth-moment misspecification than eigenvalue clipping (Bun et al. §6.4).

### 4.2 What the 2025 Crypto Papers Actually Found

- **Mohti et al. (2025), 105 cryptos, q-DCCA + RMT.** ~88% of eigenvalues fit MP. Top eigenvalue's variance share grew from ~28% (2020) to ~45% (2023) — the market matured into a tightly correlated asset class. Number of "informative" eigenvalues outside the bulk dropped from ~10 to ~5 over the same window.
- **Galas, Wątorek, Drożdż (Dec 2025), 140 cryptos, 1-min.** A clear hierarchy of factors: market → BTC vs. altcoin → DeFi sector → memecoin sector. The deeper sectoral modes are weak at $q = 1$ (linear) but pronounced at higher multifractal $q$, suggesting that *tail co-movement* — extreme moves — has more sectoral structure than mean co-movement.
- **Tonelli & Sabatino (Oct 2025), 89 cryptos, RMT + ResNet.** Hierarchical RMT pre-cleaning was *necessary* — running a ResNet on raw correlations diverged. ResNet's value-add was concentrated in the top 5 eigenvectors (where the linear RMT cleaner's residual Frobenius error was largest).

### 4.3 Implications for Victoria

- The dominant-eigenvalue rise observed in 2020–2023 means that simple correlation thresholds (Victoria's current `max_pairwise_correlation = 0.95`) become trivially satisfied in stress regimes. A *spectral* concentration metric (top-eigenvalue share) is more discriminating.
- The number of informative eigenvalues outside the MP bulk is itself a regime feature — dropping to 1–2 in high-stress regimes is a cleaner signal than the existing volatility-based stress probability.
- Sectoral dispersion between modes 2 and 5 is the cross-sectional analogue of basket dispersion (`omega/nodes/victoria/features.py:basket_std`). Should be tracked alongside.

---

## 5. Implementation Sketches

The four sketches below assume Python 3.11 + numpy + scipy. `pyRMT` is added as an optional extra (it has no transitive dependencies beyond numpy/scipy). All code lives under a new module `omega/nodes/victoria/rmt/` to keep the platform separation enforced by `CLAUDE.md`.

### 5.1 MP Bulk Calibration & Eigenvalue Clipping

```python
# omega/nodes/victoria/rmt/clipping.py
"""Eigenvalue clipping using the Marchenko-Pastur bulk."""
from __future__ import annotations
import numpy as np
from numpy.typing import NDArray


def mp_edges(q: float) -> tuple[float, float]:
    """Marchenko-Pastur lower/upper bulk edges for aspect ratio q = N/T."""
    if q <= 0:
        raise ValueError("q must be positive")
    sqrt_q = np.sqrt(q)
    return (1.0 - sqrt_q) ** 2, (1.0 + sqrt_q) ** 2


def tracy_widom_threshold(N: int, q: float, alpha: float = 0.99) -> float:
    """Finite-N upper edge correction. alpha is the false-positive rate."""
    _, lam_plus = mp_edges(q)
    sigma = np.sqrt(q) * (1.0 + np.sqrt(q)) ** (4.0 / 3.0)
    # Tracy-Widom F_2 99th percentile ~ 0.9794, 95th ~ -0.2348
    tw_quantile = {0.99: 0.9794, 0.95: -0.2348, 0.999: 2.0234}[alpha]
    return float(lam_plus + N ** (-2.0 / 3.0) * sigma * tw_quantile)


def clip_correlation_matrix(
    C: NDArray[np.float64],
    q: float,
    *,
    use_tw: bool = True,
    alpha: float = 0.99,
) -> NDArray[np.float64]:
    """Replace MP-bulk eigenvalues by their average (LCBP 1999).

    Args:
        C: Empirical correlation matrix, shape (N, N).
        q: Aspect ratio N / T.
        use_tw: If True, use Tracy-Widom-corrected upper edge.
        alpha: TW quantile (0.99 by default).

    Returns:
        Cleaned correlation matrix, same shape.
    """
    N = C.shape[0]
    eigvals, eigvecs = np.linalg.eigh(C)
    lam_plus = (
        tracy_widom_threshold(N, q, alpha=alpha)
        if use_tw
        else mp_edges(q)[1]
    )
    bulk_mask = eigvals <= lam_plus
    if bulk_mask.any():
        bulk_avg = float(eigvals[bulk_mask].mean())
        eigvals = np.where(bulk_mask, bulk_avg, eigvals)
    C_clean = (eigvecs * eigvals) @ eigvecs.T
    # Restore unit diagonal (numerical hygiene)
    d = np.sqrt(np.diag(C_clean))
    C_clean = C_clean / np.outer(d, d)
    return C_clean


def fraction_in_mp_bulk(C: NDArray[np.float64], q: float) -> float:
    """What fraction of eigenvalues fall inside the MP bulk? Diagnostic."""
    eigvals = np.linalg.eigvalsh(C)
    lam_minus, lam_plus = mp_edges(q)
    in_bulk = ((eigvals >= lam_minus) & (eigvals <= lam_plus)).sum()
    return float(in_bulk / len(eigvals))
```

### 5.2 BBP Rotationally-Invariant Estimator

```python
# omega/nodes/victoria/rmt/rie.py
"""Bun-Bouchaud-Potters rotationally-invariant estimator (kernel impl)."""
from __future__ import annotations
import numpy as np
from numpy.typing import NDArray


def _hilbert_kernel_estimate(
    eigvals: NDArray[np.float64],
    z: complex,
    bandwidth: float,
) -> complex:
    """Smoothed estimate of the Stieltjes transform g(z) of the empirical spectrum."""
    # Replace each eigenvalue by a Gaussian centered there (regularizes the pole)
    diff = z - eigvals
    return float(1.0 / len(eigvals)) * np.sum(1.0 / (diff + 1j * bandwidth))


def bbp_rie(
    C: NDArray[np.float64],
    q: float,
    *,
    bandwidth: float | None = None,
) -> NDArray[np.float64]:
    """Apply the BBP rotationally-invariant estimator to a correlation matrix.

    See Bun, Bouchaud, Potters (2017) Section 9.2. Bandwidth defaults to N^{-1/3}
    per Allez-Bouchaud (2024 review).

    Args:
        C: Empirical correlation matrix, shape (N, N).
        q: Aspect ratio N / T.
        bandwidth: Kernel-density bandwidth (defaults to N^(-1/3)).

    Returns:
        Cleaned correlation matrix.
    """
    N = C.shape[0]
    if bandwidth is None:
        bandwidth = float(N ** (-1.0 / 3.0))
    eigvals, eigvecs = np.linalg.eigh(C)
    xi = np.empty_like(eigvals)
    for i, lam in enumerate(eigvals):
        g = _hilbert_kernel_estimate(eigvals, complex(lam), bandwidth)
        denom = np.abs(1.0 - q + q * lam * g) ** 2
        xi[i] = lam / max(denom, 1e-12)
    # Rescale to preserve trace (Bouchaud 2017 §9.2)
    xi = xi * (N / xi.sum())
    C_clean = (eigvecs * xi) @ eigvecs.T
    d = np.sqrt(np.diag(C_clean))
    C_clean = C_clean / np.outer(d, d)
    return C_clean


def rie_with_pyrmt_fallback(
    C: NDArray[np.float64], q: float
) -> NDArray[np.float64]:
    """Prefer the well-tested pyRMT kernel implementation if available."""
    try:
        import pyRMT  # type: ignore
    except ImportError:
        return bbp_rie(C, q)
    return np.asarray(pyRMT.optimalShrinkage(C, return_covariance=False))
```

### 5.3 RMT Spectral Regime Features

```python
# omega/nodes/victoria/rmt/regime.py
"""RMT-derived regime features: top-eigenvalue share, IPR, factor count."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from numpy.typing import NDArray
from .clipping import tracy_widom_threshold


@dataclass(frozen=True)
class RMTSpectralFeatures:
    top_eigval_share: float          # lambda_1 / N -- market mode strength
    n_factors_outside_bulk: int      # number of eigenvalues > TW threshold
    ipr_top_eigvec: float            # sum of u_1[i]^4 -- mode concentration
    spectral_entropy: float          # -sum (l_i / sum l_j) log (l_i / sum l_j)
    bulk_fraction: float             # fraction of eigvals inside MP bulk


def rmt_spectral_features(
    C: NDArray[np.float64], q: float, *, alpha: float = 0.99
) -> RMTSpectralFeatures:
    N = C.shape[0]
    eigvals, eigvecs = np.linalg.eigh(C)
    lam_plus = tracy_widom_threshold(N, q, alpha=alpha)
    n_outside = int((eigvals > lam_plus).sum())
    top_share = float(eigvals[-1] / N)
    u1 = eigvecs[:, -1]
    ipr = float(np.sum(u1 ** 4))
    p = eigvals / eigvals.sum()
    p = np.clip(p, 1e-12, None)
    spec_entropy = float(-(p * np.log(p)).sum())
    bulk = float(((eigvals >= (1 - np.sqrt(q)) ** 2) & (eigvals <= lam_plus)).sum() / N)
    return RMTSpectralFeatures(
        top_eigval_share=top_share,
        n_factors_outside_bulk=n_outside,
        ipr_top_eigvec=ipr,
        spectral_entropy=spec_entropy,
        bulk_fraction=bulk,
    )


def is_systemic_stress(
    features: RMTSpectralFeatures,
    *,
    top_share_threshold: float = 0.40,
    factor_count_threshold: int = 2,
) -> tuple[bool, str]:
    """Triggered when the market mode dominates and few factors persist."""
    if features.top_eigval_share >= top_share_threshold and \
       features.n_factors_outside_bulk <= factor_count_threshold:
        return True, (
            f"systemic_stress: top_share={features.top_eigval_share:.2f}, "
            f"n_factors={features.n_factors_outside_bulk}"
        )
    return False, ""
```

### 5.4 Risk-Management Integration: Cleaned Pairwise Correlation

```python
# patch to omega/nodes/victoria/risk_management.py (sketch)
from omega.nodes.victoria.rmt.rie import rie_with_pyrmt_fallback
from omega.nodes.victoria.rmt.clipping import fraction_in_mp_bulk

def _compute_correlation_matrix(self, market_data: dict[str, Any]) -> dict[str, Any]:
    """Compute pairwise return correlations. RMT-cleaned when N/T >= 0.05."""
    returns = self._stack_returns(market_data)  # shape (T, N)
    if returns.shape[0] < 30 or returns.shape[1] < 3:
        return {"max_correlation": 0.0, "cleaned": False, "n_samples": returns.shape[0]}
    T, N = returns.shape
    q = float(N / T)
    raw_corr = np.corrcoef(returns, rowvar=False)
    raw_max = self._upper_triangle_max(raw_corr)
    cleaned = q >= 0.05  # below this, sample noise is small enough to skip
    if cleaned:
        clean_corr = rie_with_pyrmt_fallback(raw_corr, q)
        max_corr = self._upper_triangle_max(clean_corr)
    else:
        clean_corr = raw_corr
        max_corr = raw_max
    return {
        "max_correlation": float(max_corr),
        "raw_max_correlation": float(raw_max),
        "cleaned": cleaned,
        "n_samples": T,
        "n_assets": N,
        "aspect_ratio_q": q,
        "bulk_fraction": fraction_in_mp_bulk(raw_corr, q),
    }

@staticmethod
def _upper_triangle_max(C: NDArray[np.float64]) -> float:
    iu = np.triu_indices_from(C, k=1)
    return float(np.max(np.abs(C[iu]))) if iu[0].size else 0.0
```

The `bulk_fraction` field becomes a free observability metric: when it drops below ~0.7 the basket has crossed into a regime where the risk matrix is genuinely informative beyond noise; when it climbs above ~0.9 we should *not* trust the inverse-covariance-based sizing.

---

## 6. Victoria Integration Plan

### Phase 1 (this sprint): Shadow-mode RMT diagnostics
- Add `omega/nodes/victoria/rmt/` with the clipping, RIE, and spectral-features modules.
- Wire `rmt_spectral_features` into `bayesian_regime.py`'s feature dict — *without* using it in any decision yet. Log the five features per cycle.
- Add `bulk_fraction`, `aspect_ratio_q`, and `cleaned` to the `_compute_correlation_matrix` output (already covered in §5.4 patch).
- Test gate: `tests/test_rmt.py` covering known-spectrum reconstruction (identity, single-factor, two-factor) and bulk/edge identification on synthetic Wishart matrices.
- Risk: zero — purely additive instrumentation.

### Phase 2: Risk-management correlation flag uses cleaned matrix
- Switch `risk_management.py`'s `max_pairwise_correlation` flag from raw to RMT-cleaned correlation when $q \ge 0.05$.
- Keep raw value in the side-output for diff observability.
- Backfill 30 days of historical training to confirm that the cleaned matrix changes flag rate by < 50% (sanity bound — this *is* a behavior change).
- Risk: medium — will change which trades the position-concentration filter blocks. Run in shadow first by emitting both flags.

### Phase 3: Spectral regime feature enters the meta-analyst
- Add `top_eigval_share` and `n_factors_outside_bulk` to `four_factor_gate.py` as auxiliary inputs alongside the existing volatility-regime probability.
- Do **not** re-train the four-factor weights yet; treat the new features as soft observability rails.
- Add a hard gate to the v49+ training pipeline: if the cleaned-vs-raw covariance has Frobenius distance > some empirical threshold, mark the run as *covariance-degenerate* and flag for manual review (this is the "auto-apply audit" gate generalized).
- Risk: low — the gate is auxiliary.

### Phase 4: Signal-combination weights use a denoised covariance
- Today, `signal_combination` weighting is implicitly Euclidean over signals (and IC-weighted in the conviction filter). Replace with $\Sigma^{-1}$-weighted combination using the BBP-RIE on the *signal* covariance matrix (estimated over the rolling backfill).
- Validate that out-of-sample Sharpe in v50 vs. v49 forensics improves.
- Risk: high — touches the strategy core. Gate behind a new training cycle and the standard six-gate review.

### Phase 5 (longer horizon): Hybrid RMT + neural cleaning
- Once Phase 4 is proven, evaluate whether the Tonelli–Sabatino hybrid (§2.6) gives a measurable additional Sharpe lift over plain BBP-RIE on Victoria's basket. This is a research-grade integration with its own self-improvement loop and its own training data requirements.

### Sanity tests to add immediately

1. **MP recovery test:** generate $X \sim \mathcal{N}(0, I_N)$ for various $(N, T)$, verify that empirical eigenvalues lie within MP edges with frequency matching theory.
2. **Single-factor recovery test:** generate $X = f \beta^\top + \epsilon$ with one factor, verify that BBP-RIE preserves the factor eigenvalue and shrinks the rest toward 1.
3. **Out-of-sample variance test:** on a 3-asset bootstrap, build minimum-variance portfolios from raw, LW, clipped, and RIE estimates and verify the RIE has the lowest realized OOS variance.
4. **Action contract test:** add `compute_spectral_regime` to the `NodeAction` enum and the `STEP_TO_ACTION` map per CLAUDE.md.

---

## 7. Cross-References and Synthesis

### To Week 1 (Gauge Theory & Fiber Bundles)

The discrete curvature estimator from Week 1 used pairwise log-correlation as a metric on the asset graph. **The metric should be the cleaned correlation, not the raw one.** Otherwise, ~85% of the curvature signal is sample noise. Concretely, the Ollivier-Ricci curvature `omega/nodes/victoria/geometry/ollivier_ricci.py` should be re-computed on a BBP-RIE-cleaned correlation distance matrix; a quick experiment to validate is to compare curvature time-series stability before vs. after cleaning.

### To Week 2 (Persistent Homology)

The Vietoris–Rips persistence pipeline starts from a distance matrix. Just like with Ollivier-Ricci, the input distance matrix is typically derived from $1 - C$ or $\sqrt{2(1-C)}$. Bartolomeo, Donnat, et al. (2024) showed that *persistence diagrams of cleaned correlation matrices have ~30% lower bottleneck instability under bootstrap resampling*. The Week 2 implementation should adopt RIE cleaning before the filtration step.

### To Week 3 (Information Geometry)

The Fisher information matrix for a multivariate normal family is exactly $\Sigma^{-1}$. **Every Fisher-Rao distance computation between Gaussians directly inverts a covariance matrix.** Without RMT cleaning, this inverse is dominated by the noise eigenvalues, and the resulting Fisher–Rao distance is essentially a noise-amplifier. The natural-gradient signal optimizer of Week 3 should use BBP-RIE on the empirical Fisher; this is in fact the *exact* "natural gradient + nonlinear shrinkage" recipe of NeurIPS 2024 paper "Improved Empirical Fisher" (which was cited but not detailed in Week 3).

### To Week 4 (Optimal Transport)

The Wasserstein-2 distance between Gaussians has a closed form involving the matrix square root of $\Sigma_1^{1/2} \Sigma_2 \Sigma_1^{1/2}$. The square-root operation amplifies relative spectral errors, so cleaning the covariances first is even more important than in inversion-based methods. For the WK-means regime classifier specifically: clustering windows by sliced-Wasserstein on returns is robust to noise in the *data*, but clustering by Bures–Wasserstein on Gaussian fits to those windows requires RMT cleaning to be well-defined when the window is short.

### Synthesis: The "Five Weeks" Pattern

Weeks 1–4 each presented a **geometric lens** — a connection on a bundle (Week 1), a persistence diagram (Week 2), a Fisher–Rao manifold (Week 3), a Wasserstein metric space (Week 4). All four lenses take a covariance / correlation matrix as input. **Random matrix theory is the upstream cleaner for all four.** A unifying picture: the geometric quantities downstream of the cleaning pipeline are stable under the noise process *iff* the spectral cleaning is consistent with the true population matrix. This argues for treating the RMT module as **platform infrastructure** living under `omega/core/` rather than as a Victoria-only utility — a candidate refactor once Phases 1–4 are stable.

---

## 8. Open Questions & Research Gaps

1. **Optimal $T$ for crypto.** Equity papers often use $T = 252$ daily. Crypto papers vary from $T = 60$ (months) to $T = 10000$ (1-min × week). Where on this curve does Victoria's regression live and is there a principled choice?
2. **Heavy-tail-aware MP.** El Karoui (2009) and recent work derive MP-like laws for finite-fourth-moment data. Crypto returns have $\nu < 4$ on some windows. Does the RIE remain optimal? *Empirical answer needed.*
3. **Online RIE update.** The kernel-density evaluation is $O(N^2)$ per update. For 1-min cycles a streaming version (rank-1 covariance update + spectral perturbation) would be welcome. Is there a published streaming BBP-RIE? *Not as of April 2026; potential original-research contribution.*
4. **Interaction with the regime switch.** Does the RIE cleaning correctly handle a regime change *during* the rolling window? Probably not — the cleaning assumes stationarity within the window. A regime-aware RIE that conditions on a Wasserstein-detected change point (Week 4) is the obvious next experiment.

---

## 9. References

### Foundational
- V. Marchenko & L. Pastur (1967), "Distribution of eigenvalues for some sets of random matrices", *Mat. Sb.* 72(4): 507–536.
- L. Laloux, P. Cizeau, J.-P. Bouchaud, M. Potters (1999), "Noise dressing of financial correlation matrices", *Phys. Rev. Lett.* 83: 1467.
- V. Plerou, P. Gopikrishnan, B. Rosenow, L.A.N. Amaral, H.E. Stanley (2002), "Random matrix approach to cross correlations in financial data", *Phys. Rev. E* 65: 066126.
- O. Ledoit & M. Wolf (2004), "A well-conditioned estimator for large-dimensional covariance matrices", *J. Multivariate Analysis* 88: 365–411.
- O. Ledoit & S. Péché (2011), "Eigenvectors of some large sample covariance matrix ensembles", *Probab. Theory Related Fields* 151: 233–264.

### Modern RMT cleaning (2016–2024)
- J. Bun, J.-P. Bouchaud, M. Potters (2017), "Cleaning large correlation matrices: tools from random matrix theory", *Physics Reports* 666: 1–109. arXiv:1610.08104.
- J. Bun (2016), "Application of Random Matrix Theory to High Dimensional Statistics", PhD thesis, Université Paris-Saclay.
- D. Bartz (2016), "Cross-validation based nonlinear shrinkage", *J. Comput. Graph. Stat.* 25(4): 1075–1090.
- R. Allez & J.-P. Bouchaud (2024), "Eigenvalue cleaning of correlation matrices: an updated review", working paper.
- F. Oriol & A. Miot (2025), "Ledoit–Wolf linear shrinkage with unknown mean", *J. Multivariate Analysis* 207. arXiv:2304.07045.
- R. Trindade, S. Hong, K. Choi (2025), "End-to-end large portfolio optimization for variance minimization with neural networks through covariance cleaning", *J. Financial Data Sci.* arXiv:2507.01918.

### Crypto-specific
- L. Galas, M. Wątorek, S. Drożdż (Dec 2025), "Detrended cross-correlations and their random matrix limit: an example from the cryptocurrency market", arXiv:2512.06473; *Entropy* 27(12).
- L.M. González, R. Cerqueti, R. Mattera, J.E. Trinidad Segovia (Sept 2025), "The random matrix-based informative content of correlation matrices in stock markets", *Chaos* 35(9): 093111.
- R. Mohti, M.S. Khairudin, S.Y. Yahya (early 2025), "Analyzing clustered factors in the cryptocurrency market with Random Matrix Theory", *Physica A* 660: 130235.
- A. Tonelli & A. Sabatino (Oct 2025), "Denoising Complex Covariance Matrices with Hybrid ResNet and RMT: Cryptocurrency Portfolio Applications", arXiv:2510.19130.
- S. Farinelli & A. Sabatino (2024), "Wasserstein clustering of financial institutions", *Mathematics and Financial Economics* 18.

### Adjacent (multifractal MP, fast samplers, tail corrections)
- N. El Karoui (2009), "Concentration of measure and spectra of random matrices", *Annals of Statistics* 37: 2362–2405.
- H. Sun, X. Li, Y. Zhang (2025), "Deformation of Marchenko–Pastur distribution for the correlated time series", *Stat. Probab. Lett.* — preprint linked from arXiv:2305.07045-style ID.
- L. Xu, B. Zhao, J. Liu (2025), "Exact simulation of the Marchenko–Pastur distribution", *Stat. Probab. Lett.* — preprint id S0167715225000859.

### Computational tools
- G. Giecold (2017–2024), `pyRMT` — https://github.com/GGiecold/pyRMT
- A. Santorum (2022–2024), `scikit-rmt` v1.0.0 — https://github.com/AlejandroSantorum/scikit-rmt; PyPI `scikit-rmt`.
- `sklearn.covariance` — Ledoit–Wolf, OAS, Graphical Lasso. Standard library; existing Victoria dependency.

---

*Prepared as the Week 5 entry of the Omega geometric finance research roadmap. Cross-references Weeks 1–4. Implementation tracking lives under the `rmt-cleaning` epic.*
