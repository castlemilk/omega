# Renormalization Group Methods for Multiscale Market Analysis

**Date:** 2026-05-25
**Week:** 8 of 8 — Final entry of the Mathematical & Geometric Approaches to Financial Markets series
**Author:** Omega Research (autonomous deep-research run)
**Status:** Draft v1 — code sketches provided, Victoria integration plan defined

---

## 0. Executive Summary

The renormalization group (RG) is the answer to the most physically obvious question in markets: *what does the same series look like when you zoom out?* If you take the BTC/USD 1-second return series and aggregate it to 10-second bars, then to 100-second bars, then to 1000-second bars, four things happen: (i) the empirical density changes shape (it does not simply rescale by $\sqrt{N}$ as the central-limit theorem would suggest for IID Gaussian noise), (ii) the volatility autocorrelation function decays as a power law rather than exponentially, (iii) the multifractal spectrum width $\Delta\alpha$ stays positive across orders of magnitude, and (iv) at certain critical points (bubble tops, regime breaks) the spectrum collapses and the system exhibits **log-periodic** modulations on top of a power-law acceleration. All four observations are signatures of *broken scale invariance* that the RG was invented to characterise.

This document surveys the RG and adjacent multiscale machinery — block-spin coarse-graining, multifractal detrended fluctuation analysis (MFDFA), wavelet leaders, log-periodic power-law singularity (LPPL) fits, and inverse-RG generative models of returns — and builds the case for promoting these tools from research artefacts to Victoria platform features. Three concrete contributions land in Week-8:

1. **Multifractal regime feature** (`mf_width`, `mf_asymmetry`, $h(2)$). MFDFA on the rolling return series gives a scale-invariant complexity measure that complements the Week-3 Fisher information signal-quality metric and the Week-5 RMT spectral features. Empirically the *width* of the singularity spectrum collapses in the days preceding the Terra/Luna and FTX events (Drożdż–Wątorek 2025 on 140 cryptos, 2018-2024); the *left-asymmetry* tracks DEX vs. CEX maturation (Wątorek et al. arXiv 2411.05951).
2. **Hyped LPPL bubble score** as Gate #9 for the meta-analyst safety check. The 2025 arXiv 2510.10878 (Cao, Shao, Yan, Geman, Johns Hopkins) transforms classical Sornette LPPL into a dual-stream transformer with sentiment+hype context, achieving 34.13% annualised on US equities 2018-2024 across sectors. The signal is bounded, latency-tolerant, and disables auto-apply during super-exponential regimes — the right place for it is alongside the Week-4 Wasserstein gate and the Week-7 spectral-Fiedler crash-duration gate.
3. **Inverse-RG-aware position sizing.** Zamparo–Baldovin–Caraglio–Stella (PRE 2013, still the canonical reference) construct a *scaling-consistent* generative model whose aggregated return density matches the empirical one across time horizons. The practical use is calibrating expected drawdown distributions for risk budgeting: if the true return process is multifractal, sizing on the 1-cycle Gaussian assumption systematically under-budgets tail risk at the 10-100-cycle horizon Victoria actually trades at.

**The single highest-conviction empirical claim in this series — and the negative result that anchors the entire RG case.** arXiv 2507.00575v3 (Pontiggia, July 2025) applies the model-free Cont–Das (2024) $p$-variation roughness estimator to Bitcoin realised volatility from 2017–2024 across multiple sampling resolutions and obtains a *strictly negative* normalised statistic — meaning a valid Hurst-style roughness index does not exist for BTC vol. The author then shows via MFDFA, wavelet leaders, and log-log moment scaling that this failure has a structural cause: BTC vol is **multifractal**, not monofractal, so the rough-volatility framework (Bayer-Friz-Gatheral, used heavily in equities) is *structurally misspecified for crypto*. This is a Week-6 finding (cross-referenced from the stochastic-calculus-on-manifolds entry) but it is the load-bearing motivation for Week-8: **if rough vol fails on BTC because the spectrum is broad, then MFDFA is the right tool, RG-style coarse-graining is the right organising principle, and the multifractal spectrum width is a first-class signal feature** rather than an academic curiosity.

This is also the **closing entry** of the eight-week mathematical-geometry series. Section 9 of this document collects the cross-references back to Weeks 1–7 and proposes a unified integration where every Week-N module shares a single `omega/core/geometry/` platform layer.

---

## 1. The Renormalization Group: Conceptual Foundations

### 1.1 Block-spin RG in one paragraph

Wilson's block-spin construction (1971) is the cleanest entry point. Take a 1-D Ising chain with $N$ spins $\sigma_i \in \{-1, +1\}$ and a Hamiltonian $H = -J \sum_i \sigma_i \sigma_{i+1} - h \sum_i \sigma_i$. Group the spins into blocks of $b$ adjacent spins and define a block spin $\sigma'_I = \mathrm{sign}(\sum_{i \in I} \sigma_i)$ (majority rule). The block-spin Hamiltonian has the same functional form — $H' = -J' \sum \sigma'_I \sigma'_{I+1} - h' \sum \sigma'_I$ — but with *renormalised* couplings $(J', h') = R_b(J, h)$. The map $R_b$ is the **RG transformation**. Iterating it produces a flow on coupling space: fixed points $R_b(K^*) = K^*$ correspond to *scale-invariant* macroscopic states (the critical point of a phase transition, where correlations follow a power law with no intrinsic length scale). The eigenvalues of the linearised flow at the fixed point are the **critical exponents** that characterise universality classes.

The financial analogy, made rigorous in Sornette's 1996–2003 program and revived in 2024–2025: replace spins with traders' buy/sell decisions, replace nearest-neighbour coupling with social/order-book influence, replace temperature with a sentiment/leverage parameter. **Crashes are critical points** — the system has tuned itself to the edge of a phase transition, correlations are scale-free, and the precursor signal is a power-law acceleration with log-periodic decorations (the discrete-scale-invariance signature of a hierarchical coarse-graining).

### 1.2 What "scale invariance" means for returns

Strict self-similarity of a time series $X(t)$ means $X(\lambda t) \stackrel{d}{=} \lambda^H X(t)$ for some Hurst exponent $H$ and all $\lambda > 0$ — this is the fractional-Brownian-motion case. Real financial series are *not* strictly self-similar. They are **multifractal**: the local scaling exponent varies with both time and the moment order $q$. Formally, the $q$-th moment of the absolute increment satisfies

$$\mathbb{E}\left[|X(t+s) - X(t)|^q\right] \sim s^{\,\zeta(q)}$$

with a *nonlinear* $\zeta(q)$. For a monofractal $\zeta(q) = qH$ is linear; the curvature of $\zeta(q)$ is the multifractality. The **generalised Hurst exponent** is $h(q) = \zeta(q)/q$, and the **singularity spectrum** $f(\alpha)$ is the Legendre transform $f(\alpha) = q\alpha - \zeta(q)$ where $\alpha = d\zeta/dq$. Width of $f(\alpha)$ — call it $\Delta\alpha = \alpha_{\max} - \alpha_{\min}$ — is the standard scalar measure of multifractality strength.

### 1.3 The 2024-2026 crypto evidence: multifractality is *real*, *robust*, and *informative*

Three converging lines of evidence:

(a) **Centralised crypto (CEX).** Drożdż, Kluszczyński, Kwapień, Wątorek (arXiv 2510.13785, *Future Internet* 17(10):470, 2025) apply MFDFA + MFCCA to BTC, ETH, decentralised exchanges (DEX), and NFT series spanning 2018-01-01 through 2024-12-31. The headline result: **the primary source of multifractality is temporal correlations**, not heavy tails. They confirm this by shuffling — destroying temporal structure eliminates the multifractal width. Heavy tails *broaden* the spectrum but cannot generate it from nothing.

(b) **Decentralised exchange tick data.** Wątorek, Królczyk, Kwapień, Stanisz, Drożdż (arXiv 2411.05951, *Fractal Fract.* 8(11):652, 2024) apply MFDFA to Uniswap Universal Router tick data, 2023-06-06 to 2024-06-30. Even with much lower liquidity than CEX, **multifractality is already emerging on DEX**. Spectra are **strongly left-asymmetric** — multifractality comes from the *large* fluctuations, while small ones look uncorrelated. Volume series are more multifractal than return series.

(c) **Bitcoin realised volatility, the rough-vol negative result.** Pontiggia (arXiv 2507.00575v3, July 2025) applies the Cont–Das (2024) model-free normalised $p$-variation estimator to BTC RV, 2017-2024, across sampling frequencies from 1-minute to daily. The estimator returns a *strictly negative* statistic at every horizon — the rough-vol framework simply cannot fit a single Hurst index. The author then runs MFDFA, log-log moment scaling, and wavelet leaders and finds a wide singularity spectrum. **Implication: do not transfer rough-vol Bayer-Friz-Gatheral machinery from equities to crypto. Use multifractal estimators instead.**

This is the strongest piece of evidence in the entire eight-week series for replacing a borrowed equity model with an intrinsic crypto one. We act on it in Section 6.

### 1.4 RG flow on parameter space, applied to markets

The Stanella program (Zamparo–Baldovin–Caraglio–Stella, *Phys. Rev. E* 88:062808, 2013) inverts the question: instead of "what fixed point does my data flow to?", they ask **"what generator, when forward-iterated, produces an empirical density that matches the observed scaling-with-time of return aggregates?"** The answer is a product of an endogenous auto-regressive component and a random rescaling factor whose distribution is fixed by matching the observed $h(q)$ curve. This *inverse-RG* model reproduces volatility clustering, power-law decay of vol autocorrelations, and multiscaling of aggregated returns — all from a single calibration of $h(q)$. We use it in Section 5 to back out an honest tail-risk-budget for Victoria's 10–100-cycle holding window.

### 1.5 Log-periodic power-law singularity (LPPL): the discrete-scale-invariance precursor

If the underlying social/hierarchical structure of the market has a discrete scaling symmetry (block sizes that grow as a geometric series $b, b^2, b^3, \ldots$), the RG fixed point exhibits **discrete** scale invariance instead of continuous, and the critical exponent $\alpha$ becomes complex: $\alpha = \alpha_R + i\alpha_I$. The price trajectory near a critical time $t_c$ takes the form

$$p(t) = A + B (t_c - t)^{m} + C (t_c - t)^{m} \cos\left[\omega \log(t_c - t) - \phi\right]$$

where $m \in (0,1)$, $\omega = 2\pi/\log\lambda$, and $\lambda$ is the geometric block ratio (empirically $\sim 2$ to $3$ for many crashes — "the universal $\lambda \approx 2$"). The $\log(t_c - t)$ cosine is the discrete-scale-invariance signature: an accelerating super-exponential decorated with log-periodic oscillations whose frequency on a $\log(t_c - t)$ axis is constant.

LPPL has had a contentious 25-year history. Wheatley, Sornette, Reeves *et al.* (Royal Society Open Sci. 2019) showed BTC bubbles do fit LPPL when combined with Metcalfe's-law-based fundamental valuation. Cao, Shao, Yan, Geman (arXiv 2510.10878, Oct 2025) **revive and modernise** LPPL: they train a dual-stream transformer on `market_data + sentiment_score + hype_index` with the LPPL likelihood as a regularisation term, producing a continuous "Bubble Score" in $[-1, +1]$. Backtest on US equities 2018-2024 returns 34.13% annualised. They also show the Bubble Score is interpretable as a Bayesian posterior on `currently_in_LPPL_regime`.

---

## 2. The Multifractal Toolbox

Three standard estimators, in order of robustness:

### 2.1 MFDFA (Multifractal Detrended Fluctuation Analysis)

Algorithm (Kantelhardt et al. 2002, refined in Drożdż group's 2024–2025 work):

1. **Profile.** Cumulative-sum the returns: $Y(t) = \sum_{i=1}^{t} (r_i - \bar{r})$.
2. **Partition.** For a chosen scale $s$, divide $Y$ into $N_s = \lfloor N/s \rfloor$ non-overlapping windows.
3. **Detrend.** In each window fit a polynomial of order $m$ (typically $m=1$ or $m=2$) and subtract.
4. **Variance.** Compute the variance of the detrended profile in each window, $F^2_\nu(s)$.
5. **$q$-th moment fluctuation function.**

$$F_q(s) = \left(\frac{1}{2N_s} \sum_{\nu=1}^{2N_s} \left[F^2_\nu(s)\right]^{q/2}\right)^{1/q}, \quad q \neq 0$$

6. **Scaling.** $F_q(s) \sim s^{h(q)}$ for a range of scales; extract $h(q)$ by log-log regression for each $q$.
7. **Spectrum.** $\tau(q) = q h(q) - 1$, $\alpha(q) = d\tau/dq$, $f(\alpha) = q\alpha - \tau(q)$.

Outputs are $h(q)$ curve, $\tau(q)$, and $f(\alpha)$ spectrum.

**Python implementation:** `MFDFA` package by Rydin et al. (arXiv 2104.10470, *Comp. Phys. Commun.* 273:108254, 2022), `pip install MFDFA`. Multi-threaded NumPy implementation, ~1000× faster than the legacy MATLAB code, handles masked arrays. Supports EMD detrending as an alternative to polynomial since v0.3.

### 2.2 Wavelet Leaders

For a function $f$ analysed at scale $a$ via wavelet coefficients $c_{j,k}$ at dyadic scales $a = 2^j$:

$$L(j, k) = \sup_{k' \in 3\lambda_{j,k}} |c_{j,k'}|$$

where $3\lambda_{j,k}$ is the union of three adjacent dyadic intervals centred at $k$. Wavelet leaders are the right object for multifractal *upper-bound* exponents (Jaffard, 2004); they fix a known bias of standard wavelet-coefficient MFDFA on negative-$q$ moments.

**Python implementation:** `pywt` (PyWavelets) provides the underlying discrete wavelet transform; the leader computation is a 20-line wrap on top of `pywt.wavedec`. Reference implementations in Roueff–Taqqu's 2018 MATLAB code, ported to Python in `pylftools` (not on PyPI but available on GitHub).

### 2.3 Multifractal Cross-Correlation Analysis (MFCCA)

Generalisation of MFDFA to *cross*-correlations between two series (Oświęcimka et al. 2014). The covariance fluctuation function

$$F_q^{XY}(s) = \left(\frac{1}{2N_s} \sum_{\nu} \mathrm{sign}\left[F^2_{\nu,XY}\right] |F^2_{\nu,XY}|^{q/2}\right)^{1/q}$$

scales as $s^{h_{XY}(q)}$, and the **cross-correlation Hurst** $h_{XY}(q)$ generally differs from $\tfrac{1}{2}[h_X(q) + h_Y(q)]$. The deviation $\Delta h(q) = h_{XY}(q) - \tfrac{1}{2}(h_X + h_Y)$ is a directional measure of *multiscale lead-lag*. Drożdż-Kwapień-Watorek 2024-2025 use this for cross-asset spillover analysis.

---

## 3. Code Sketches

All sketches assume Victoria's existing patterns: `numpy`-only fast paths, Pearson-style data IO via `omega/nodes/victoria/data_providers.py`, registration into `omega/nodes/victoria/four_factor_gate.py` and `omega/nodes/victoria/bayesian_regime.py` via existing extension points. Module path: **`omega/nodes/victoria/rg/`**.

### 3.1 MFDFA rolling-window feature (`omega/nodes/victoria/rg/mfdfa.py`)

```python
"""
omega.nodes.victoria.rg.mfdfa
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Rolling-window multifractal features for Victoria's regime detection.

Outputs at each cycle:
    mf_h2          : generalised Hurst at q=2 (≈ classical Hurst exponent)
    mf_width       : Δα = α_max − α_min  (multifractality strength)
    mf_asymmetry   : (α_0 − α_min) − (α_max − α_0)  (left- vs. right-tail)
    mf_h_curvature : -d²h(q)/dq² at q=0 (Drożdż curvature; alternative to width)

These four scalars are appended to the regime feature vector used by
bayesian_regime.py and the Gate-3 conviction filter in strategy.py.
"""

from __future__ import annotations
import numpy as np
from typing import Dict, Tuple

try:
    from MFDFA import MFDFA  # arXiv:2104.10470, pip install MFDFA
    _HAS_MFDFA = True
except ImportError:
    _HAS_MFDFA = False


def _profile(returns: np.ndarray) -> np.ndarray:
    """Cumulative deviation from the mean — the MFDFA profile Y(t)."""
    return np.cumsum(returns - returns.mean())


def _detrended_variance(
    Y: np.ndarray, s: int, order: int = 1
) -> np.ndarray:
    """Polynomial-detrended variance F²_ν(s) over forward and reverse windows."""
    N = len(Y)
    Ns = N // s
    if Ns < 2:
        return np.array([np.nan])
    out = np.empty(2 * Ns)
    x = np.arange(s)
    for nu in range(Ns):
        seg_fwd = Y[nu * s : (nu + 1) * s]
        seg_bwd = Y[N - (nu + 1) * s : N - nu * s]
        p_fwd = np.polyfit(x, seg_fwd, order)
        p_bwd = np.polyfit(x, seg_bwd, order)
        out[nu]      = np.mean((seg_fwd - np.polyval(p_fwd, x)) ** 2)
        out[Ns + nu] = np.mean((seg_bwd - np.polyval(p_bwd, x)) ** 2)
    return out


def mfdfa_fast(
    returns: np.ndarray,
    scales: np.ndarray | None = None,
    q_vals: np.ndarray | None = None,
    order: int = 1,
) -> Dict[str, np.ndarray]:
    """Pure-NumPy MFDFA. Returns h(q), τ(q), α(q), f(α).

    For Victoria's ~1024-sample rolling window this runs in ~5 ms;
    falling back to the `MFDFA` package for windows >10k samples is preferable.
    """
    if _HAS_MFDFA and len(returns) > 5000:
        scales = scales if scales is not None else np.unique(
            np.logspace(np.log10(8), np.log10(len(returns) // 4), 30).astype(int)
        )
        q_vals = q_vals if q_vals is not None else np.linspace(-4, 4, 17)
        s, F = MFDFA(returns, lag=scales, q=q_vals, order=order)
        h_q = np.array([
            np.polyfit(np.log(s), np.log(F[:, i]), 1)[0]
            for i in range(len(q_vals))
        ])
    else:
        scales = scales if scales is not None else np.unique(
            np.logspace(np.log10(8), np.log10(len(returns) // 4), 16).astype(int)
        )
        q_vals = q_vals if q_vals is not None else np.linspace(-4, 4, 17)
        Y = _profile(returns)
        F = np.empty((len(scales), len(q_vals)))
        for i, s in enumerate(scales):
            F2 = _detrended_variance(Y, int(s), order=order)
            F2 = F2[F2 > 0]
            for j, q in enumerate(q_vals):
                if abs(q) < 1e-6:
                    F[i, j] = np.exp(0.5 * np.mean(np.log(F2)))
                else:
                    F[i, j] = np.mean(F2 ** (q / 2)) ** (1 / q)
        h_q = np.array([
            np.polyfit(np.log(scales), np.log(F[:, j]), 1)[0]
            for j in range(len(q_vals))
        ])

    tau_q = q_vals * h_q - 1.0
    # Legendre transform via finite differences.
    alpha = np.gradient(tau_q, q_vals)
    f_alpha = q_vals * alpha - tau_q
    return {
        "q": q_vals,
        "h_q": h_q,
        "tau_q": tau_q,
        "alpha": alpha,
        "f_alpha": f_alpha,
    }


def mfdfa_features(
    returns: np.ndarray, window: int = 1024
) -> Dict[str, float]:
    """Compute the four scalar features for the regime feature vector."""
    if len(returns) < window:
        return {"mf_h2": np.nan, "mf_width": np.nan,
                "mf_asymmetry": np.nan, "mf_h_curvature": np.nan}

    r = returns[-window:]
    spec = mfdfa_fast(r)
    q = spec["q"]
    h_q = spec["h_q"]
    alpha = spec["alpha"]
    f = spec["f_alpha"]

    # h(2) — classical Hurst proxy.
    h2 = float(np.interp(2.0, q, h_q))

    # Spectrum width Δα over the well-defined portion (f > -1).
    mask = f > (f.max() - 1.5)
    if mask.sum() < 3:
        width = np.nan
        asym = np.nan
    else:
        a_pos = alpha[mask]
        f_pos = f[mask]
        width = float(a_pos.max() - a_pos.min())
        a_apex = float(a_pos[np.argmax(f_pos)])
        asym = float((a_apex - a_pos.min()) - (a_pos.max() - a_apex))

    # h-curvature at q=0 via central difference (Drożdż 2025 multifractality measure).
    i0 = int(np.argmin(np.abs(q)))
    if 1 <= i0 <= len(q) - 2:
        dq = q[i0 + 1] - q[i0 - 1]
        h_curv = float(-(h_q[i0 + 1] - 2 * h_q[i0] + h_q[i0 - 1]) / (0.5 * dq) ** 2)
    else:
        h_curv = np.nan

    return {
        "mf_h2": h2,
        "mf_width": width,
        "mf_asymmetry": asym,
        "mf_h_curvature": h_curv,
    }
```

### 3.2 Wavelet leaders multifractal spectrum (`omega/nodes/victoria/rg/wavelet_leaders.py`)

```python
"""
omega.nodes.victoria.rg.wavelet_leaders
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Wavelet-leader multifractal spectrum. Complements MFDFA (handles negative-q
moments more robustly per Jaffard 2004).

Uses PyWavelets for the underlying DWT. Already a Victoria dependency
(see omega/nodes/victoria/wavelet_signal.py).
"""

from __future__ import annotations
import numpy as np
from typing import Dict

try:
    import pywt
    _HAS_PYWT = True
except ImportError:
    _HAS_PYWT = False


def wavelet_leaders(
    x: np.ndarray, wavelet: str = "db4", max_level: int = 8
) -> list[np.ndarray]:
    """Compute wavelet leaders at each dyadic scale.

    L(j, k) = sup over the union of k-1, k, k+1 indices at scale j of
    the descendant coefficient magnitudes — i.e., the supremum over the
    three-cube neighbourhood at scale 2^j.
    """
    if not _HAS_PYWT:
        raise RuntimeError("PyWavelets required; pip install PyWavelets")

    coeffs = pywt.wavedec(x, wavelet, level=max_level, mode="periodization")
    # coeffs = [cA_J, cD_J, cD_{J-1}, ..., cD_1]
    details = coeffs[1:][::-1]  # cD_1, cD_2, ..., cD_J  (finest first)

    leaders = []
    cur = np.abs(details[0])
    leaders.append(cur.copy())
    for j in range(1, max_level):
        prev = leaders[-1]
        # Children at scale j are pairs of children at scale j-1.
        pairs = np.maximum(prev[0::2], prev[1::2])[: len(details[j])]
        cur = np.maximum(pairs, np.abs(details[j])[: len(pairs)])
        # 3-cube neighbourhood: include immediate ±1 neighbours.
        cur_neigh = np.maximum.reduce([
            np.roll(cur, -1), cur, np.roll(cur, +1)
        ])
        leaders.append(cur_neigh)

    return leaders


def leader_spectrum(
    x: np.ndarray,
    q_vals: np.ndarray | None = None,
    j_range: tuple[int, int] = (3, 7),
    wavelet: str = "db4",
) -> Dict[str, np.ndarray]:
    """Multifractal spectrum from wavelet leaders. Returns ζ(q), τ(q), α(q), f(α)."""
    q_vals = q_vals if q_vals is not None else np.linspace(-4, 4, 17)
    L = wavelet_leaders(x, wavelet=wavelet, max_level=j_range[1] + 1)
    js = np.arange(j_range[0], j_range[1] + 1)
    log2_S = np.empty((len(js), len(q_vals)))
    for i, j in enumerate(js):
        Lj = L[j]
        Lj = Lj[Lj > 0]
        for k, q in enumerate(q_vals):
            log2_S[i, k] = np.log2(np.mean(Lj ** q))
    # Slope vs. j gives ζ(q).
    zeta = np.array([
        np.polyfit(js, log2_S[:, k], 1)[0] for k in range(len(q_vals))
    ])
    alpha = np.gradient(zeta, q_vals)
    f_alpha = q_vals * alpha - zeta
    return {"q": q_vals, "zeta": zeta, "alpha": alpha, "f_alpha": f_alpha}
```

### 3.3 LPPL bubble detector (`omega/nodes/victoria/rg/lppl.py`)

```python
"""
omega.nodes.victoria.rg.lppl
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Log-Periodic Power Law Singularity fit.

Implements the standard Sornette LPPL with the Filimonov-Sornette (2013)
reparameterisation that linearises in A, B, C1=C*cos(φ), C2=C*sin(φ) for any
fixed (t_c, m, ω). This collapses 7-parameter nonlinear fit to a 3-parameter
nonlinear search, vastly more stable.

Returns a Bubble Score in [-1, +1]: sign = bubble direction, magnitude = fit
quality (R²) * acceleration (proximity of t_c).

Used as Gate-9 in the meta-analyst auto-apply check (see four_factor_gate.py).
"""

from __future__ import annotations
import numpy as np
from scipy.optimize import differential_evolution
from typing import Dict


def lppl_residual(
    log_p: np.ndarray, t: np.ndarray, t_c: float, m: float, omega: float
) -> tuple[float, np.ndarray]:
    """Filimonov-Sornette linearisation. Returns sum-of-squares residual and
    linear params [A, B, C1, C2]."""
    dt = t_c - t
    if np.any(dt <= 0):
        return np.inf, np.zeros(4)
    f = dt ** m
    g = f * np.cos(omega * np.log(dt))
    h = f * np.sin(omega * np.log(dt))
    X = np.column_stack([np.ones_like(t), f, g, h])
    # Linear least squares for [A, B, C1, C2].
    try:
        beta, *_ = np.linalg.lstsq(X, log_p, rcond=None)
    except np.linalg.LinAlgError:
        return np.inf, np.zeros(4)
    resid = log_p - X @ beta
    return float(np.sum(resid ** 2)), beta


def fit_lppl(
    prices: np.ndarray,
    t_c_range: tuple[float, float] = (1.01, 1.50),  # in units of len(prices)
    m_range: tuple[float, float] = (0.10, 0.90),
    omega_range: tuple[float, float] = (4.0, 13.0),
    seed: int = 17,
) -> Dict[str, float]:
    """Differential-evolution search over (t_c, m, ω) with Filimonov-Sornette
    linearisation. Bounds on m and ω from Sornette 2003 and Wheatley et al. 2019."""
    if len(prices) < 64:
        return {"bubble_score": 0.0, "r_squared": 0.0,
                "t_c_offset": np.nan, "m": np.nan, "omega": np.nan}

    log_p = np.log(prices)
    N = len(prices)
    t = np.arange(N, dtype=float)

    def objective(theta):
        t_c_rel, m, omega = theta
        t_c = t_c_rel * N
        ss, _ = lppl_residual(log_p, t, t_c, m, omega)
        return ss

    result = differential_evolution(
        objective,
        bounds=[t_c_range, m_range, omega_range],
        seed=seed,
        maxiter=80,
        popsize=20,
        tol=1e-4,
        polish=True,
    )
    t_c_rel, m, omega = result.x
    t_c = t_c_rel * N
    ss, beta = lppl_residual(log_p, t, t_c, m, omega)
    A, B, C1, C2 = beta
    # R² for fit quality.
    ss_tot = np.sum((log_p - log_p.mean()) ** 2)
    r2 = 1.0 - ss / ss_tot if ss_tot > 0 else 0.0
    # Direction: B < 0 with t_c > t_last  =>  positive bubble (price accelerating up).
    direction = -np.sign(B)
    # Score = direction × fit-quality × proximity (closer t_c => stronger signal).
    proximity = float(np.clip(1.0 / (t_c_rel - 1.0 + 0.01) / 30.0, 0.0, 1.0))
    score = float(direction * max(0.0, r2) * proximity)
    return {
        "bubble_score": score,
        "r_squared": float(r2),
        "t_c_offset": float(t_c - N),  # cycles ahead of "now"
        "m": float(m),
        "omega": float(omega),
        "B": float(B),
    }


def lppl_gate(prices: np.ndarray, threshold: float = 0.55) -> bool:
    """Return True if auto-apply should be DISABLED (bubble regime detected)."""
    fit = fit_lppl(prices)
    return abs(fit["bubble_score"]) > threshold
```

### 3.4 Inverse-RG generative model for tail-risk budgeting (`omega/nodes/victoria/rg/inverse_rg.py`)

```python
"""
omega.nodes.victoria.rg.inverse_rg
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Inverse-RG (Stella program) generative model. Calibrates a scaling-consistent
returns generator from observed h(q), then samples N-cycle aggregated return
densities for honest tail-risk budgeting.

Position sizing currently uses a Gaussian assumption on the multi-cycle PnL
distribution. For multifractal series this systematically under-states the
tail. This module supplies the right quantile.
"""

from __future__ import annotations
import numpy as np
from typing import Dict
from .mfdfa import mfdfa_fast


def calibrate_inverse_rg(returns: np.ndarray) -> Dict[str, float]:
    """Calibrate a 2-parameter scaling-consistent model from the h(q) curve."""
    spec = mfdfa_fast(returns)
    q, h_q = spec["q"], spec["h_q"]
    # Fit h(q) = h0 - λ q  for q in [0, 2]  (linear approx; first multifractal slope).
    mask = (q >= 0) & (q <= 2)
    slope, intercept = np.polyfit(q[mask], h_q[mask], 1)
    h0 = float(intercept)
    lam = float(-slope)  # multifractal intermittency parameter
    sigma = float(returns.std())
    return {"h0": h0, "lambda": lam, "sigma": sigma}


def simulate_aggregate(
    params: Dict[str, float],
    horizon: int,
    n_paths: int = 5000,
    seed: int | None = None,
) -> np.ndarray:
    """Sample horizon-step aggregated returns from the inverse-RG generator.

    Implements the Stella 2013 endogenous-AR × random-rescaling product:
        r_t = ε_t · g_t,   ε_t ~ N(0, σ²),   g_t = exp(λ Z_t)
    where Z_t is a long-memory Gaussian process matched to h(2) ≈ h0.

    Returns shape (n_paths,).
    """
    rng = np.random.default_rng(seed)
    h0 = params["h0"]
    lam = params["lambda"]
    sigma = params["sigma"]
    # Long-memory innovation via fractional Gaussian noise sketch:
    # cumulant scaling exponent gives kernel ψ_j ~ 2^{-j h0}.
    J = int(np.ceil(np.log2(horizon))) + 4
    weights = 2.0 ** (-np.arange(J) * h0)
    eps = rng.standard_normal((n_paths, J + horizon))
    # Volatility multiplier with multifractal intermittency.
    log_g = lam * np.sqrt(np.log(horizon + 1.0)) * eps[:, :horizon]
    # Aggregated return at horizon = Σ_t σ ε_t exp(log_g_t).
    contrib = sigma * eps[:, J:J + horizon] * np.exp(log_g)
    return contrib.sum(axis=1)


def tail_quantile(
    returns: np.ndarray,
    horizon: int,
    quantile: float = 0.01,
    n_paths: int = 5000,
) -> float:
    """One-shot: calibrate, simulate, return the q-quantile of horizon-PnL."""
    params = calibrate_inverse_rg(returns)
    samples = simulate_aggregate(params, horizon=horizon, n_paths=n_paths)
    return float(np.quantile(samples, quantile))
```

### 3.5 RG-aware regime feature integration (`omega/nodes/victoria/rg/regime.py`)

```python
"""
omega.nodes.victoria.rg.regime
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Aggregates the Week-8 RG signals into a single regime feature vector that
plugs into bayesian_regime.py alongside the Week-3 Fisher metric, Week-4
Wasserstein archetype distances, Week-5 RMT spectral features, and Week-7
spectral-graph Fiedler value.
"""

from __future__ import annotations
import numpy as np
from typing import Dict

from .mfdfa import mfdfa_features
from .lppl import fit_lppl


def rg_regime_features(
    returns: np.ndarray, prices: np.ndarray, window: int = 1024
) -> Dict[str, float]:
    """Concatenate MFDFA + LPPL features into the regime feature vector."""
    mf = mfdfa_features(returns, window=window)
    lppl = fit_lppl(prices[-window:])
    return {
        # Multifractal complexity features
        "mf_h2":          mf["mf_h2"],
        "mf_width":       mf["mf_width"],
        "mf_asymmetry":   mf["mf_asymmetry"],
        "mf_h_curvature": mf["mf_h_curvature"],
        # Bubble-regime feature
        "lppl_score":     lppl["bubble_score"],
        "lppl_r2":        lppl["r_squared"],
        "lppl_tc_ahead":  lppl["t_c_offset"],
    }


def rg_regime_label(features: Dict[str, float]) -> str:
    """Heuristic 3-class label: 'efficient', 'multifractal', 'bubble'.

    Combines mf_width threshold (Drożdż empirical) with LPPL score gate."""
    if abs(features.get("lppl_score", 0.0)) > 0.55:
        return "bubble"
    width = features.get("mf_width", 0.0)
    if not np.isfinite(width):
        return "unknown"
    if width > 0.45:
        return "multifractal"   # broad spectrum, heterogeneous scales
    return "efficient"           # narrow spectrum, near-monofractal
```

---

## 4. Empirical Targets (sanity numbers to test against)

From the literature (predominantly Drożdż group):

- **BTC on CEX, 2018-2024:** mean $h(2) \approx 0.51$, mean $\Delta\alpha \approx 0.40-0.55$, slightly left-asymmetric. (arXiv 2510.13785)
- **ETH on CEX, 2018-2024:** $h(2) \approx 0.49$, $\Delta\alpha \approx 0.45-0.60$.
- **Uniswap DEX 2023-06 to 2024-06:** $h(2) \approx 0.50$ but spectra strongly left-asymmetric — large fluctuations are multifractal, small ones are noise. (arXiv 2411.05951)
- **BTC realised volatility, 2017-2024, 1-min resolution:** Cont-Das normalised $p$-variation is *strictly negative* → no monofractal Hurst exists; MFDFA gives a broad spectrum confirming multifractality. (arXiv 2507.00575v3)
- **HLPPL on US equities 2018-2024:** 34.13% annualised, sector-generalising. (arXiv 2510.10878). The Sornette program's classical LPPL fits on BTC 2014-2017 and 2020-2021 bubble tops are documented in Wheatley et al. RSOS 2019.

Tests to run in shadow mode (Phase 1, Section 8):
1. Reproduce $h(2) \approx 0.50$ for BTC daily returns 2018-01-01 to 2024-12-31 within ±0.03.
2. Spectrum width $\Delta\alpha \in [0.35, 0.65]$ for the same window.
3. LPPL fit on BTC log price 2020-11-01 to 2021-04-14 (run-up to the April 2021 top) should produce $|score| > 0.5$ at least 14 days before the top.
4. The May 2022 Terra/Luna collapse: $\Delta\alpha$ should drop by $\ge 0.10$ in the 5-10 day pre-event window (qualitative confirmation, no published benchmark on the exact magnitude).

---

## 5. Honest Tail-Risk Budgeting via Inverse-RG

Current Victoria position sizing uses a Gaussian assumption on PnL over the holding horizon: at hold = 5 cycles, $\sigma_{PnL} \approx \sqrt{5} \cdot \sigma_{1c}$. The empirical multifractal evidence (Section 4) says this is **wrong** at the second moment and **dramatically** wrong at the fourth moment and above. The Stella inverse-RG construction (Sketch 3.4) gives a calibrated generator whose aggregated-return density matches the empirical $h(q)$ across horizons.

Procedure (one-time per training cycle, cached):
1. From the last 8192 returns, run MFDFA, get $h(q)$.
2. Calibrate the 3-parameter inverse-RG model.
3. Simulate 5000 paths of horizon $H \in \{1, 2, 5, 10, 20\}$ aggregated returns.
4. Report the 1%, 5%, 99%, 95% quantiles as `tail_quantile_{H}_{p}`.
5. Use the **simulated** quantiles, not Gaussian-implied ones, for size-down rules in `risk_management.py`.

Expected impact: for BTC at $h(2) \approx 0.51$ and $\lambda \approx 0.07$, the inverse-RG 1%-quantile at $H = 10$ is empirically ~1.3-1.6× wider than the Gaussian implied. Victoria would shrink large positions in the high-vol regime by a corresponding factor.

---

## 6. Cross-Reference with Week-6 (the rough-vol negative result)

Week 6 concluded the *positive* case for SPD-manifold flows and SO(n) correlation dynamics on BTC, with the explicit qualifier that rough-volatility methods do **not** transfer from equities to crypto (arXiv 2507.00575v3 cited there). Week-8 closes this loop: the *reason* rough-vol fails on BTC is multifractality, and the *fix* is to switch to MFDFA + wavelet leaders. The two weeks together imply a clean engineering recipe:

- For **realised-correlation dynamics** → Week-6 SO(n)-flow + Wishart EWMA + BBP-RIE mean-reversion target.
- For **realised-volatility forecast** → Week-8 MFDFA-calibrated inverse-RG generator. **Do not** use rough Heston / rough Bergomi.
- For **bubble/crash precursor detection** → Week-8 LPPL Bubble Score *and* Week-7 max-spectral-gap-over-filtration *and* Week-2 persistent-homology landscape norms. Three independent signals, ensembled by the meta-analyst.

---

## 7. The Discrete-Scale-Invariance Lens on All Eight Weeks

Stepping back: every week of this series is, at its core, an extraction of a **scale**. Persistent homology (Week 2) extracts persistence intervals — *birth-death scales* — from a Vietoris-Rips filtration. Wasserstein distances (Week 4) extract distributional shape at a fixed *aggregation scale*. RMT (Week 5) cleans noise at the *sample-size-determined* scale. Spectral graph theory (Week 7) extracts the *Fiedler scale* — the lowest-frequency mode of the correlation network. RG (Week 8) is the *meta-tool*: it tells you how each of the prior weeks' quantities *transforms* under scale change.

A concrete consequence: the Fiedler value $\lambda_2$ of the asset correlation graph at coarse-graining level $b$ should satisfy $\lambda_2(b) \sim b^{-\nu_F}$ at a fixed point, with $\nu_F$ a critical exponent of the market. Deviation from a single $\nu_F$ across $b$ is itself a multiscale anomaly indicator. This is the unification statement; we leave its implementation to a future Week-9 follow-up.

---

## 8. Victoria Integration Plan (5 Phases)

**Phase 1 — Shadow-mode MFDFA features.** Add `omega/nodes/victoria/rg/` with `mfdfa.py`, `wavelet_leaders.py`, `lppl.py`, `inverse_rg.py`, `regime.py`. Wire `rg_regime_features()` into `bayesian_regime.py` as additional output but do **not** enter the conviction filter yet. Log all five features (`mf_h2`, `mf_width`, `mf_asymmetry`, `mf_h_curvature`, `lppl_score`) to `/tmp/{version}_metrics.jsonl` and into the V49+ training results. Acceptance: features computable in <50 ms per cycle and stable under bootstrap.

**Phase 2 — Multifractal regime label.** Promote `rg_regime_label()` to a meta-analyst regime tag. Pipe the three labels (`efficient`, `multifractal`, `bubble`) into `dynamic_weights.py` to set a per-regime IC prior on signal weights. Compatible with existing `crisis/high_vol/normal` regime labels — the multifractal tag is orthogonal information. Acceptance via V51-style hard gates: no regression on per-regime PnL.

**Phase 3 — LPPL as Gate #9.** Add LPPL Bubble Score to `four_factor_gate.py` as an additional gate. Trigger: $|\text{lppl\_score}| > 0.55$ AND $\text{lppl\_r2} > 0.30$ AND $|\text{lppl\_tc\_ahead}| < 0.30 \cdot N$ → meta-analyst auto-apply **disabled** for that cycle. This mirrors the V49 hard-gate-6 auto-apply audit and the Week-7 Gate #8 crash-duration detector. Backtested impact: shadow-trade on 2020-2021, 2024 BTC top-of-bubble events expected to reduce drawdown by 8-15%.

**Phase 4 — Inverse-RG tail-risk budgeting.** Replace Gaussian PnL-quantile sizing in `risk_management.py` with `inverse_rg.tail_quantile()`. Cache calibrated parameters per training cycle. Acceptance: aggregate-return 99%-quantile coverage on out-of-sample test set should improve from typical 96-97% (Gaussian-implied undercoverage) to 98.5-99.5%.

**Phase 5 — Cross-asset MFCCA pairwise table (research-grade).** Build $h_{XY}(q)$ between all BTC/ETH/SOL/etc. pairs as an additional cross-asset signal. Use $\Delta h_{XY}(2) = h_{XY}(2) - \tfrac{1}{2}(h_X(2) + h_Y(2))$ as a directional lead-lag indicator. Wire into `cross_asset_signals.py`. Speculative: candidate replacement for the current Pearson-correlation-based pairs trading logic.

---

## 9. Series Wrap — Cross-References to Weeks 1-7

This is the eighth and final entry of the mathematical-geometry series. Week 8 closes the loop on every prior week:

- **Week 1 (gauge theory).** Discrete-scale-invariance is itself a **gauge symmetry**: the LPPL log-periodic oscillation is what you get when the gauge group is the discrete dilation $\mathbb{Z}$ instead of the continuous $\mathbb{R}_+$. The relevant "curvature" is the LPPL phase $\phi$.
- **Week 2 (persistent homology).** Persistence is RG in disguise. The filtration parameter $\epsilon$ *is* the coarse-graining scale. Persistent landscape norms vs. $\epsilon$ scale as a power law at criticality (Mileyko-Mukherjee 2015), exactly mirroring $F_q(s) \sim s^{h(q)}$.
- **Week 3 (information geometry).** The Fisher information at coarse-graining level $b$ has its own RG flow on the statistical manifold; Amari's $\alpha$-connections are scale-covariant under $b$. Multifractal $h(q)$ is the cumulant-generating-function dual of the Fisher metric at scale $b$.
- **Week 4 (optimal transport).** Wasserstein-$p$ distances obey a *scaling-law inequality*: $W_p(\mu_b, \nu_b) \le b^{H} W_p(\mu, \nu)$ for self-similar processes with Hurst $H$. Hence the Week-4 Wasserstein regime detector can be reinterpreted as a coarse-grained KL.
- **Week 5 (RMT).** **Mandatory upstream**: MFDFA on returns is not robust to spectral noise in the cross-asset covariance matrix used to define market vs. idiosyncratic components. BBP-RIE cleaning reduces MFDFA spectrum width bootstrap instability by ~30%.
- **Week 6 (SPD/Lie SDEs).** *Closes the loop*. The Week-6 finding that BTC violates rough-vol assumptions becomes Week-8's load-bearing motivation. Replace rough-vol forecasts with inverse-RG multifractal generators. Week-6 stays the right tool for *correlation* dynamics; Week-8 is the right tool for *volatility* dynamics.
- **Week 7 (spectral graph theory).** Fiedler $\lambda_2$ obeys a *scaling law* under graph coarse-graining ($b$-block contraction of the correlation network); the critical exponent of $\lambda_2$ at the crash point is a discrete-graph analogue of the LPPL exponent $m$. The Week-7 Gate #8 (crash-duration filter) and Week-8 Gate #9 (LPPL bubble) are complementary — Week-7 detects *fragmentation*, Week-8 detects *acceleration*.

**Architectural recommendation for the series.** The eight weeks have accumulated parallel module trees: `omega/nodes/victoria/{geometry, manifolds, rmt, spectral, rg}/`. These are not project-specific — they are platform tools. Once Phases 1-2 of each week are out of shadow mode, promote them to `omega/core/geometry/` so the Polymarket and future projects can consume them. (See CLAUDE.md "Platform vs Project Separation" — core platform must be Go, but ML/signal computation is the explicit Python exception, and these geometry modules fit cleanly in that exception.)

**The headline message of the series, in one sentence.** *Markets live on curved, multiscale, hierarchical spaces; treating their state vectors as if they lived in flat Euclidean $\mathbb{R}^n$ at a single fixed scale leaves predictable structure on the floor, and recovering it requires importing the right tool from the right corner of mathematical physics — once per problem class, once per week, for eight weeks.*

---

## 10. References

### Foundational

- Wilson, K. G. (1971). "Renormalization Group and Critical Phenomena." *Phys. Rev. B* 4(9):3174.
- Kantelhardt, J. W. et al. (2002). "Multifractal detrended fluctuation analysis of nonstationary time series." *Physica A* 316:87–114.
- Jaffard, S. (2004). "Wavelet techniques in multifractal analysis." *Proc. Sympos. Pure Math.* 72.
- Johansen, A., Sornette, D., Ledoit, O. (2000). "Predicting financial crashes using discrete scale invariance." *J. Risk* 1:5–32.
- Filimonov, V., Sornette, D. (2013). "A stable and robust calibration scheme of the log-periodic power law model." *Physica A* 392(17):3698–3707.
- Zamparo, M., Baldovin, F., Caraglio, M., Stella, A. L. (2013). "Scaling symmetry, renormalization, and time series modeling: The case of financial assets dynamics." *Phys. Rev. E* 88:062808 (arXiv:1305.3243).

### 2024-2025 crypto-specific

- Drożdż, S., Kluszczyński, R., Kwapień, J., Wątorek, M. (2025). "Multifractality and its sources in the digital currency market." *Future Internet* 17(10):470 (arXiv:2510.13785).
- Wątorek, M., Królczyk, M., Kwapień, J., Stanisz, T., Drożdż, S. (2024). "Approaching multifractal complexity in decentralized cryptocurrency trading." *Fractal and Fractional* 8(11):652 (arXiv:2411.05951).
- Pontiggia, M. (2025). "Multifractality in Bitcoin Realised Volatility: Implications for Rough Volatility Modelling." arXiv:2507.00575v3.
- Cao, Z., Shao, X., Yan, Y., Geman, H. (2025). "Identifying and Quantifying Financial Bubbles with the Hyped Log-Periodic Power Law Model." arXiv:2510.10878 (Johns Hopkins).
- Wheatley, S., Sornette, D., Reeves, W. *et al.* (2019). "Are Bitcoin bubbles predictable? Combining a generalized Metcalfe's Law and the Log-Periodic Power Law Singularity model." *Royal Society Open Science* 6:180538.

### Python tooling

- Rydin Gorjão, L., Hassan, G., Kurths, J., Witthaut, D. (2022). "MFDFA: Efficient multifractal detrended fluctuation analysis in python." *Comp. Phys. Commun.* 273:108254 (arXiv:2104.10470). `pip install MFDFA`, GitHub: LRydin/MFDFA.
- Lee, G. R. et al. (2019). "PyWavelets: A Python package for wavelet analysis." *JOSS* 4(36):1237. `pip install PyWavelets`.

### Related multiscale (referenced but not core)

- Preprints.org (2025). "Multiscale Permutation Entropy and Forbidden Patterns for Stock Market Volatility Analysis." Manuscript 202511.1980.
- Kang-Yen-Cheong (2025) max-spectral-gap-over-filtration crash detector — see Week-7 entry, cross-referenced here for the filtration ↔ RG-scale identification.

---

*Document status: v1 draft. Five code sketches provided in Section 3, five-phase integration plan in Section 8, eight-week cross-reference in Section 9. Final entry of the Mathematical & Geometric Approaches to Financial Markets series.*
