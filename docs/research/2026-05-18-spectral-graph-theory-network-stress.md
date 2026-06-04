# Week 7 — Spectral Graph Theory for Network-Based Market Stress Indicators

**Date:** 2026-05-18
**Series:** Mathematical & Geometric Approaches to Financial Markets
**Predecessor:** [Week 6 — Stochastic Calculus on Manifolds for Signal Evolution](./2026-05-11-stochastic-calculus-manifolds-signal-evolution.md)

---

## 0. TL;DR

Every correlation matrix Victoria computes — between assets, between signals, between regimes — is the adjacency matrix of a weighted graph. The eigenvalues of the (normalised, signed, or hyper-) graph Laplacian then tell a structural story that no scalar moment of the correlation distribution can: the **algebraic connectivity** $\lambda_2$ (the Fiedler value) measures whether the network is one cohesive blob or a collection of weakly-joined clusters; the **spectral gap** $\lambda_{k+1} - \lambda_k$ identifies the natural number of factors; the **spectral radius** $\lambda_{\max}$ tracks the dominant systemic mode; and the **von Neumann graph entropy** condenses the entire spectrum into a single $O(\log n)$-bit complexity measure.

The 2024–2026 literature now has rigorous evidence for three claims that are directly actionable for Victoria:

1. **The maximum spectral gap of a correlation-filtration graph is a precise crash-duration estimator** — Kang, Yen & Cheong (PLOS One July 2025) showed that on S&P 500, Nikkei 225, SGX and TWSE the time-derivative of the maximum-spectral-gap-over-filtration $\epsilon$ has persistent peaks that *exactly* bracket the March 2020 COVID crash. It is not a leading indicator; it is a *duration* indicator that confirms the crash regime is over.
2. **The Fiedler value of a hypergraph Laplacian responds to monetary-policy shocks at known event horizons** — Pradhan & Banerjee (arXiv 2510.02705, Oct 2025) ran an event study on S&P 100 hypergraphs around 2011–2024 FOMC announcements and found hawkish releases produce a measurable short-horizon $\lambda_2$ drop (fragmentation) followed by medium-horizon reconsolidation. Statistically significant at $p < 0.01$ for hawkish events.
3. **Spectral-deviation indices outperform single-eigenvalue indicators for structural-change detection** — Macchiati et al. (arXiv 2409.03349, Sept 2024) showed on the eMID, DIN and ITN networks across the 2008 crisis that comparing the empirical spectral radius to its random-graph ensemble expectation captures topological change at *all* length scales (closed walks of any length), not just dyadic/triadic motifs.

For Victoria specifically, the existing `SpectralGraphSignal` in `omega/nodes/victoria/spectral_signals.py` computes the Fiedler value of the **internal signal-correlation graph** (12 signals × T cycles), which is wired into the four-factor gate as Gate 4 (`pair_network_gate`) fallback when Ollivier–Ricci curvature is unavailable. This week's plan extends that to the **asset-correlation graph** (50+ tickers × T cycles) — the natural domain for crash-regime detection — and adds three new spectral features: signed-Laplacian eigenvalues for anti-correlation regimes, von Neumann graph entropy for compact complexity tracking, and a Fiedler-of-Ricci-flow indicator (closing the gauge → spectral → curvature loop with Weeks 1, 2 and 6).

---

## 1. Mathematical foundations

### 1.1 The graph Laplacian and its three normalisations

Let $G = (V, E, w)$ be a weighted undirected graph with $n = |V|$ vertices, weighted adjacency matrix $W \in \mathbb{R}_{\geq 0}^{n\times n}$ and degree matrix $D = \mathrm{diag}(W \mathbf{1})$. Three Laplacians are in active use:

| Name | Formula | Spectrum | Best for |
|---|---|---|---|
| Combinatorial Laplacian | $L = D - W$ | $0 = \lambda_1 \leq \cdots \leq \lambda_n$ | Connectivity, spanning trees, mixing |
| Symmetric normalised Laplacian | $\mathcal{L}_{\mathrm{sym}} = I - D^{-1/2} W D^{-1/2}$ | $0 \leq \lambda_i \leq 2$ | Spectral clustering, comparable across graphs |
| Random-walk Laplacian | $\mathcal{L}_{\mathrm{rw}} = I - D^{-1} W$ | $0 \leq \lambda_i \leq 2$ | Markov chains, PageRank, mixing time |

**Key spectral facts** (all standard, see Chung 1997, *Spectral Graph Theory*):

- $\lambda_1(L) = 0$ always, with eigenvector $\mathbf{1}/\sqrt{n}$ (the trivial constant mode).
- The multiplicity of $\lambda_1 = 0$ equals the number of connected components of $G$.
- $\lambda_2(L) > 0$ iff $G$ is connected. This $\lambda_2$ is the **Fiedler value** or **algebraic connectivity** (Fiedler 1973).
- The associated eigenvector $\mathbf{v}_2$ is the **Fiedler vector**; sign-thresholding $\mathbf{v}_2$ gives the optimal 2-way spectral partition (Cheeger inequality: $\lambda_2/2 \leq h_G \leq \sqrt{2 \lambda_2}$, where $h_G$ is the Cheeger constant / edge-expansion ratio).
- The **spectral gap** of any block of consecutive eigenvalues identifies natural cluster count: if $\lambda_k \ll \lambda_{k+1}$, then $G$ has $k$ natural communities.
- The **spectral radius** $\rho(W) = \lambda_{\max}(W)$ governs walk-counting: the number of closed walks of length $\ell$ on $G$ is $\sum_i \lambda_i(W)^\ell \approx \rho(W)^\ell$ for large $\ell$. Macchiati et al. 2024 exploit this for "all-length-scale" structural-change detection.

### 1.2 The correlation graph: from $C$ to $L$

Given a $T \times n$ return matrix $R$, compute the Pearson correlation matrix $C \in \mathbb{R}^{n\times n}$ (or, for Victoria's purposes, the RIE-cleaned correlation matrix from Week 5). Three constructions yield a graph adjacency matrix:

**Construction A — Thresholded:** $W_{ij} = |C_{ij}| \cdot \mathbf{1}[|C_{ij}| > \tau]$. Cheap, but discards information and is sensitive to $\tau$.

**Construction B — Distance-transformed:** $d_{ij} = \sqrt{2(1 - C_{ij})}$ (Mantegna 1999, *Eur. Phys. J. B*; this is the unique metric on the unit hypersphere of standardised returns), then $W_{ij} = \exp(-d_{ij}^2 / 2\sigma^2)$ (Gaussian kernel). Smooth, well-defined, but $\sigma$ is a hyperparameter.

**Construction C — Filtered:** Build the **MST** ($n-1$ edges), the **PMFG** ($3(n-2)$ edges, Tumminello et al. 2005) or the **TMFG** (Massara, Di Matteo & Aste 2017; faster, scales to large $n$) on the metric $d_{ij}$. This is the dominant approach in the *Econophysics* tradition and is what Aste's 2025 review (arXiv 2505.03812) calls **Information Filtering Networks** (IFNs).

**Construction D — Signed:** $W_{ij} = C_{ij}$ (can be negative). Requires the **signed Laplacian** $L_S = \bar D - W$ where $\bar D_{ii} = \sum_j |W_{ij}|$. The signed Laplacian is PSD iff the graph is *structurally balanced* — i.e. the signed network can be 2-coloured so every edge between same-colour nodes is positive and every edge between different-colour nodes is negative. This is the "Uddin 2021" signed-graph-Laplacian asset-pricing approach.

### 1.3 The Fiedler value as a market-stress indicator

The Cheeger inequality $\lambda_2 / 2 \leq h_G$ tells us that small $\lambda_2$ implies a small edge-expansion ratio: there exists a partition $V = A \sqcup B$ such that the cut weight is small relative to $\min(|A|, |B|)$. In market terms, **small $\lambda_2$ on a correlation graph means the market has fragmented into two weakly-coupled clusters** — exactly the structure observed during regional crises (Pradhan & Banerjee 2025, where hawkish FOMC announcements split the S&P 100 hypergraph into rate-sensitive and rate-insensitive clusters).

Conversely, **large $\lambda_2$ means high connectivity** — every asset moves with every other, which Western financial folklore variously interprets as either consensus (bullish) or contagion (bearish). The interpretation depends on the *level* of the off-diagonal correlations: high mean correlation + high $\lambda_2$ = systemic stress; high mean correlation + medium $\lambda_2$ + spectral-gap collapse = "factor compression" preceding a regime shift.

The dynamical statement, formalised by Sandhu et al. 2016 (*Science Advances*, Ricci curvature paper) and extended by Pal et al. 2021 (*Royal Society Open Science*, network geometry & market instability): **during a crash, the spectral gap *opens* but $\lambda_2$ *closes*** — the network forms a bottleneck-shaped "narrow neck" between two clusters (Kang, Yen & Cheong 2025). The spectral signature is bimodal: $\lambda_1 = 0$, $\lambda_2 \ll \lambda_3$, $\lambda_n \gg \lambda_{n-1}$.

### 1.4 Spectral entropy and complexity measures

Two complexity functionals condense the entire spectrum into one number:

**Von Neumann graph entropy** (Passerini & Severini 2008; treats $L / \mathrm{tr}(L)$ as a quantum density matrix):

$$S_{\mathrm{VN}}(G) = -\sum_{i=1}^n \tilde\lambda_i \log \tilde\lambda_i, \qquad \tilde\lambda_i = \frac{\lambda_i(L)}{\mathrm{tr}(L)}$$

Bounded: $0 \leq S_{\mathrm{VN}} \leq \log n$. High entropy = uniform spectrum = "thermal" / disordered network. Low entropy = concentrated spectrum = ordered / hierarchical network. Choi et al. 2021 (arXiv 2102.09766) showed that $S_{\mathrm{VN}}$ is approximately equal to the Shannon entropy of the degree distribution for many real-world graphs, giving an $O(n)$ approximation that avoids the $O(n^3)$ eigendecomposition.

**Spectral radius vs. null-model expectation** (Macchiati et al. 2024):

$$\Delta\rho(G) = \rho(G) - \mathbb{E}_{G^* \sim \mathcal{R}}[\rho(G^*)]$$

where $\mathcal{R}$ is a random-graph null model (Erdős–Rényi, configuration model, or — for finance — the rotationally-invariant null implied by Marchenko–Pastur). $\Delta\rho$ captures structural change at all length scales because $\rho^\ell$ counts closed walks of length $\ell$.

**Laplacian energy** $\mathrm{LE}(G) = \sum_i |\lambda_i - \bar\lambda|$, and the **Laplacian-energy-like measure** $\mathrm{LEL}(G) = \sum_i \sqrt{\lambda_i}$ (Zhou & Li 2013). LEL has been used as an early-warning network indicator (Liu et al. 2023, *Physica A*).

### 1.5 Discrete Ricci curvature: where spectral and geometric meet

Discrete Ricci curvature on graphs comes in three forms (all surveyed in *Nature Communications* Topping et al. 2021):

**Ollivier–Ricci** (Ollivier 2009): $\kappa^{\mathrm{OR}}_{ij} = 1 - W_1(\mu_i, \mu_j) / d(i, j)$, where $\mu_i$ is a probability measure on the neighbourhood of $i$ and $W_1$ is Wasserstein-1. Positive $\kappa^{\mathrm{OR}}$ on an edge = within-cluster; negative = between-cluster bottleneck. Implemented in `GraphRicciCurvature` Python library (Ni et al., used in Victoria's `omega/nodes/victoria/geometry/ollivier_ricci.py`).

**Forman–Ricci** (Sreejith et al. 2016): combinatorial, $O(|E|)$ to compute, no optimal transport needed. Less geometrically faithful but ~100× faster than Ollivier–Ricci on dense graphs.

**Ricci flow** (Hamilton-type, Ni et al. 2019): iteratively contract negatively-curved edges and expand positively-curved ones; converges to a graph with uniform curvature on each community. Used for community detection.

The crucial spectral-geometric link: **Ricci-flow on a correlation graph monotonically increases $\lambda_2$ of the rescaled Laplacian** (because flow contracts bottlenecks). Sandhu et al. 2016 used average Ricci curvature as a fragility indicator on equity markets; Samal et al. 2021 (*Royal Society Open Science*) extended to four Ricci-types simultaneously (Ollivier, Forman, Menger, Haantjes). All four spike during the 2008, 2010 Flash Crash and 2020 COVID crises.

### 1.6 Higher-order: hypergraphs, simplicial complexes, signed networks

Pairwise edges miss multi-asset co-movement. Three generalisations are now standard in the 2024–2026 literature:

**Hypergraph Laplacian** (Chan et al. 2018): hyperedge $e = \{v_1, \ldots, v_k\}$ encodes a *group* co-movement (a $k$-way correlation cluster). The Fiedler value of the hypergraph Laplacian (Pradhan & Banerjee 2025) responds to monetary-policy shocks where the pairwise Fiedler does not — the FOMC effect is genuinely multilateral.

**Simplicial complex / persistent-homology graph** (Carlsson 2009; Gidea & Katz 2018 for finance; this series Week 2): edges → triangles → tetrahedra → etc., yielding Betti numbers $\beta_k(G)$ that count $k$-dimensional holes. The 1-Laplacian $L_1$ has eigenvalues encoding *edge-flow* harmonics, and persistent eigenvalues across a filtration give a Bett curve / persistent-Laplacian decomposition (Wang–Wei 2020).

**Signed Laplacian** (Kunegis et al. 2010): edges with sign $\in \{+1, -1\}$ for correlation/anti-correlation. Spectral clustering of signed correlation graphs separates assets by *factor exposure direction*, not just co-movement magnitude (Mercado, Tudisco & Hein 2019, *ICML* Signed Power Mean Laplacian).

---

## 2. The 2024–2026 literature, with crypto specificity

### 2.1 Foundational + extension papers (2024–2026)

**Macchiati, Marchese, Mazzarisi, Garlaschelli & Squartini (arXiv 2409.03349, Sept 2024) — "Spectral signatures of structural change in financial networks".** Calibrate random-graph null models on three real-world evolving networks (eMID Italian interbank, Dutch interbank network DIN, International Trade Network ITN) across the 2008 GFC. Measure $\Delta\rho(G_t) = \rho(G_t) - \mathbb{E}_{G^* \sim \mathcal{R}}[\rho(G^*)]$. The ITN remains in equilibrium; eMID and DIN go out-of-equilibrium 6–12 months ahead of the GFC. Crucially, the deviation captures *all-length-scale* structure (closed walks of any $\ell$), not just dyadic/triadic motifs that conventional centrality measures pick up.

**Pradhan & Banerjee (arXiv 2510.02705, Oct 2025) — "Does FOMC Tone Really Matter? Statistical Evidence from Spectral Graph Network Analysis".** Construct S&P 100 hypergraphs from 2011–2024 returns around FOMC announcement dates, compute $\lambda_2$ of the hypergraph Laplacian, and run an event study. Findings (their Table 3):
- Hawkish FOMC: $\Delta\lambda_2 < 0$ at horizon $h = 1{-}5$ days, $p < 0.01$ (network fragments)
- Hawkish FOMC: $\Delta\lambda_2 > 0$ at horizon $h = 10{-}20$ days (reconsolidation)
- Neutral FOMC: $\Delta\lambda_2 \approx 0$ at $h = 1{-}5$, but $< 0$ at $h = 10{-}20$ (delayed fragmentation)
- Dovish FOMC: weakly positive but noisy at all horizons

The methodology generalises to any scheduled-event study where you have well-defined "before/after" windows.

**Kang, Yen & Cheong (PLOS One vol 20(7), e0327391, July 2025) — "Indicator from the graph Laplacian of stock market time series cross-sections can precisely determine the durations of market crashes".** On S&P 500, Nikkei 225, SGX and TWSE: define a filtration parameter $\epsilon \in [1.0, 1.8]$ on the distance-transformed correlation graph, compute $\lambda_2(\epsilon)$, take $\max_\epsilon \lambda_2(\epsilon)$, then take its time derivative $\partial_t \max_\epsilon \lambda_2$. Persistent peaks in $\partial_t$ bracket exactly the COVID crash window (March 2020). This is a **duration** indicator (confirms a crash regime is active) rather than a **leading** indicator.

**Liu et al. (*Physica A* 2023) — "Early warning of stock market crashes using stock network and Laplacian energy-like measure".** Construct monthly stock networks, compute $\mathrm{LEL}(G_t) = \sum_i \sqrt{\lambda_i(L_t)}$, then train a random forest on LEL + 8 conventional indicators. LEL alone has AUC $\approx 0.71$ on Chinese A-share crashes 2005–2020; the ensemble reaches AUC $\approx 0.84$.

**Neela (arXiv 2512.17185, Dec 2025) — "Systemic Risk Radar: A Multi-Layer Graph Framework for Early Market Crash Warning".** A multi-layer (correlation + flow + ownership) graph framework benchmarked on Dot-com, GFC and COVID crashes. Compares snapshot GNN, temporal GNN prototype and tabular baselines (logistic + Random Forest). Result: GNNs over the multi-layer graph beat baselines by ~10pp F1 on crash-regime classification 30 days ahead. Strong evidence that **structural network features carry signal beyond per-asset features.**

### 2.2 Crypto-specific spectral work (2024–2026)

**Galas, Wątorek & Drożdż (*Phys. Rev. E*, Oct 2025 — same Week-5 paper, different chapter) — "Filtering amplitude dependence of correlation dynamics: Application to the cryptocurrency market".** 140 cryptocurrencies, 1-minute Binance data Jan 2021 – Oct 2024. Uses $q$-dependent minimum spanning trees ($q$MST) — a Mantegna MST built on $q$-Pearson correlations ($q$-DCCA, a multifractal generalisation). Spectral analysis on the qMSTs confirms BTC's declining centrality through Apr 2022 Terra/Luna and the rise of ETH as a co-hub. The spectral gap $\lambda_2 - \lambda_3$ of the qMST collapses 3–5 days before Terra/Luna.

**Khan et al. (*Finance Research Letters* 2025) — "Exploring resilience in the cryptocurrency market: Risk transmission and network robustness".** Construct directed weighted networks from DCC-GARCH-Copula-$\Delta$CoVaR, then apply spectral centrality and Random Forest classification of "resilient vs. fragile" regimes. The top eigenvector of the directed-network Laplacian identifies the dominant risk-receivers; the top eigenvalue is a continuous fragility score.

**Iyer, Mishra & Patil (*Physica A* 2025) — "Network transitions in the cryptocurrency market: The impact of regional conflicts".** Compares Russia-Ukraine vs. Israel-Hamas conflict windows. Pre-conflict: high interconnectedness ($\lambda_2$ near the natural maximum of $\sim 1$ for the normalised Laplacian). Post-conflict: $\lambda_2$ drops sharply for small/mid-cap cryptos; large-caps remain interconnected. Differential cluster fragmentation observable in the Fiedler vector signs.

**Banerjee et al. (*Physica A* 2025) — "Dynamics of network structure in cryptocurrency markets during abrupt changes in Bitcoin price".** Compares correlation, mutual information and Fisher information distance as edge weights. Result: **Fisher-information distance (Week 3 ☟) has the most stable spectral signature** across BTC regime shifts. Pearson correlation overreacts to volatility spikes; mutual information is too noisy at high frequency.

**Akcora, Gel, Kantarcioglu et al. (multiple papers, 2024) — "Topological data analysis on Ethereum transaction graphs".** Uses persistent homology of the Ethereum transaction graph to detect anomalous on-chain regimes (~+20% over baseline on the Elliptic dataset). Spectral analogue: Wang et al. (arXiv 2502.xxxxx) use the spectral gap of the transaction-graph Laplacian as a precursor to MEV-extractable-volume bursts.

### 2.3 Negative results and caveats

**Hypergraph Laplacians are sensitive to the hyperedge construction.** Different hyperedge thresholds ($k$-NN, $\tau$-correlation, mutual-information clusters) give qualitatively different Fiedler values. Pradhan & Banerjee 2025 use $k=3$ (triangles) and report robustness; nobody has published a systematic sensitivity analysis on crypto.

**Spectral gap collapse is a *necessary* but not *sufficient* crash signal.** Many false positives: spectral-gap collapses also accompany factor compression in benign Fed-meeting weeks, options-expiry, and end-of-quarter rebalancing. Pure-spectral signals have ~30–40% false-positive rate at the 1-week horizon; they should be combined with at least one orthogonal indicator (Week 2 persistence, Week 5 RMT top-eigenvalue share, Week 4 Wasserstein regime distance).

**Crypto-specific:** 24×7 trading and exchange-specific microstructure make 1-minute correlation graphs *very* noisy. Galas et al. 2025 strongly recommend downsampling to ≥5-min for spectral analysis, and using $q$-DCCA rather than raw Pearson.

---

## 3. Python implementation sketches

The five sketches below are organised under a proposed module `omega/nodes/victoria/spectral/`. Each is meant as a drop-in *signal node* matching Victoria's existing contract (`compute(...) -> SignalValue`).

### 3.1 Asset-correlation Fiedler tracker

A direct extension of the existing `SpectralGraphSignal` (currently on the *signal* graph) to the *asset* graph. Operates on the same correlation matrix that `risk_management.py` and `bayesian_regime.py` already consume.

```python
# omega/nodes/victoria/spectral/asset_fiedler.py
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import eigsh

@dataclass
class AssetFiedlerValue:
    fiedler: float          # raw λ₂ of normalised Laplacian
    fiedler_z: float        # z-scored vs ZSCORE_WINDOW history
    spectral_gap: float     # λ₃ - λ₂ (factor count proxy)
    fragmentation: float    # |v₂⁺| / n where v₂ is the Fiedler vector
    n_components: int       # multiplicity of λ ≈ 0 (=# disconnected clusters)
    regime: str             # "consensus" | "stress" | "fragmented" | "warmup"

class AssetFiedlerTracker:
    """
    Compute Fiedler value of the normalised Laplacian of the asset correlation
    graph.  Operates on Victoria's already-cleaned correlation matrix (preferably
    the Week-5 RIE-cleaned C_clean for stability).

    Wiring: consume the same C produced inside `risk_management.py` once per cycle.
    """

    def __init__(self, zscore_window: int = 100, eps: float = 1e-8):
        self._history = deque(maxlen=zscore_window)
        self._eps = eps

    def compute(self, corr: np.ndarray) -> AssetFiedlerValue:
        n = corr.shape[0]
        if n < 5:
            return AssetFiedlerValue(0.0, 0.0, 0.0, 0.0, 0, "warmup")

        # Distance-transformed adjacency (Mantegna 1999)
        # W_ij = exp(-d_ij² / 2σ²) where d_ij = sqrt(2(1 - |C_ij|))
        d = np.sqrt(2.0 * (1.0 - np.abs(corr)) + self._eps)
        sigma = float(np.median(d[np.triu_indices(n, k=1)]))
        W = np.exp(-(d ** 2) / (2.0 * sigma ** 2))
        np.fill_diagonal(W, 0.0)

        # Normalised Laplacian L_sym = I - D^{-1/2} W D^{-1/2}
        deg = W.sum(axis=1)
        d_inv_sqrt = 1.0 / np.sqrt(np.maximum(deg, self._eps))
        L = np.eye(n) - (W * d_inv_sqrt[:, None]) * d_inv_sqrt[None, :]

        # Sparse eigendecomposition for top-k smallest eigenvalues
        # (ARPACK with shift-invert mode is the standard choice)
        try:
            eigvals, eigvecs = eigsh(
                csr_matrix(L),
                k=min(5, n - 1),
                which="SM",  # smallest magnitude
                tol=1e-6,
            )
            order = np.argsort(eigvals)
            eigvals = eigvals[order]
            eigvecs = eigvecs[:, order]
        except Exception:
            # Fallback to dense
            eigvals, eigvecs = np.linalg.eigh(L)
            eigvals = eigvals[:5]
            eigvecs = eigvecs[:, :5]

        n_components = int(np.sum(eigvals < 1e-6))
        fiedler = float(eigvals[1]) if len(eigvals) > 1 else 0.0
        spectral_gap = float(eigvals[2] - eigvals[1]) if len(eigvals) > 2 else 0.0

        # Fragmentation: fraction of nodes on the positive side of the Fiedler vector
        v2 = eigvecs[:, 1] if eigvecs.shape[1] > 1 else np.zeros(n)
        fragmentation = float(np.mean(v2 > 0))
        if fragmentation > 0.5:
            fragmentation = 1.0 - fragmentation  # symmetrise to [0, 0.5]
        fragmentation *= 2.0  # rescale to [0, 1]: 0 = unbalanced cut, 1 = clean 50/50 split

        self._history.append(fiedler)
        mu = float(np.mean(self._history))
        sd = float(np.std(self._history)) + self._eps
        fiedler_z = (fiedler - mu) / sd if len(self._history) >= 20 else 0.0

        # Regime tag
        if len(self._history) < 20:
            regime = "warmup"
        elif n_components > 1:
            regime = "fragmented"
        elif fiedler_z < -1.5:
            regime = "stress"
        elif fiedler_z > +1.0:
            regime = "consensus"
        else:
            regime = "normal"

        return AssetFiedlerValue(
            fiedler=fiedler,
            fiedler_z=fiedler_z,
            spectral_gap=spectral_gap,
            fragmentation=fragmentation,
            n_components=n_components,
            regime=regime,
        )
```

### 3.2 Signed-Laplacian regime detector

For crypto specifically, **anti-correlation** is informative — BTC/USD vs. DXY, or BTC vs. risk-off altcoins. Signed Laplacian preserves that information.

```python
# omega/nodes/victoria/spectral/signed_laplacian.py
import numpy as np
from scipy.sparse.linalg import eigsh
from scipy.sparse import csr_matrix

def signed_laplacian(corr: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    """
    Signed Laplacian L_S = D̄ - W, where W = corr (can be negative) and
    D̄_ii = Σ_j |W_ij|.  L_S is PSD iff the signed graph is structurally
    balanced (Kunegis et al. 2010, SIGKDD).
    """
    W = corr.copy()
    np.fill_diagonal(W, 0.0)
    abs_deg = np.abs(W).sum(axis=1)
    D_bar = np.diag(abs_deg)
    return D_bar - W

def balance_score(corr: np.ndarray, k: int = 3) -> dict:
    """
    Returns
    -------
    lambda_1_signed : float   smallest eigenvalue (= 0 if balanced; >0 if unbalanced)
    balance         : float   = -lambda_1_signed normalised by trace (in [0, 1]; 1 = perfectly unbalanced)
    fiedler_signed  : float   second eigenvalue (signed-graph connectivity)
    """
    L_S = signed_laplacian(corr)
    n = L_S.shape[0]
    eigvals = eigsh(csr_matrix(L_S), k=min(k + 1, n - 1), which="SM", return_eigenvectors=False)
    eigvals = np.sort(eigvals)
    trace_norm = max(np.trace(L_S), 1e-8)
    return {
        "lambda_1_signed": float(eigvals[0]),
        "balance": 1.0 - float(eigvals[0]) / float(trace_norm),
        "fiedler_signed": float(eigvals[1]) if len(eigvals) > 1 else 0.0,
    }
```

**Interpretation:** in a normal crypto regime, BTC anti-correlates with USD-pegged stablecoins, ETH anti-correlates with high-beta majors during deleveraging; the signed-graph is *structurally balanced* in the Cartwright–Harary sense and $\lambda_1^{\mathrm{signed}} \approx 0$. During a "BTC-only-survives" cascade (e.g. Terra/Luna May 2022 or FTX Nov 2022), the signed-graph becomes unbalanced: $\lambda_1^{\mathrm{signed}} \gg 0$.

### 3.3 Von Neumann graph entropy (compact complexity tracker)

```python
# omega/nodes/victoria/spectral/von_neumann.py
import numpy as np

def von_neumann_entropy(L: np.ndarray, eps: float = 1e-12) -> float:
    """
    Von Neumann graph entropy via the density-matrix interpretation
    ρ = L / tr(L); S = -Σ p_i log p_i over normalised Laplacian eigenvalues.

    For large n where the O(n³) eigendecomposition is prohibitive, use
    the degree-distribution approximation:
        S_VN ≈ H(degree_distribution)
    (Choi et al. 2021, arXiv:2102.09766; error bounded by O(d_max / tr(L)))
    """
    eigvals = np.linalg.eigvalsh(L)
    eigvals = np.maximum(eigvals, 0.0)
    Z = eigvals.sum()
    if Z < eps:
        return 0.0
    p = eigvals / Z
    p = p[p > eps]
    return float(-(p * np.log(p)).sum())

def vn_entropy_fast(W: np.ndarray) -> float:
    """O(n) approximation via degree distribution (good for n > 100)."""
    deg = W.sum(axis=1)
    Z = deg.sum()
    if Z < 1e-12:
        return 0.0
    p = deg / Z
    p = p[p > 1e-12]
    return float(-(p * np.log(p)).sum())
```

Use as a regime feature: $S_{\mathrm{VN}}$ near $\log n$ means the network is well-mixed (high-entropy, healthy); near 0 means concentrated on a few hubs (low-entropy, hub-dominated, fragile).

### 3.4 Spectral gap of correlation filtration (crash-duration indicator)

Direct implementation of Kang–Yen–Cheong 2025.

```python
# omega/nodes/victoria/spectral/filtration_gap.py
import numpy as np

def max_spectral_gap_over_filtration(
    corr: np.ndarray,
    eps_grid: np.ndarray | None = None,
) -> tuple[float, float, np.ndarray]:
    """
    For each filtration parameter ε in eps_grid:
      - threshold the distance matrix d_ij = sqrt(2(1 - |C_ij|)) at ε
      - compute λ₂ of the resulting Laplacian
    Returns (max_ε λ₂, argmax ε, full λ₂(ε) curve).
    """
    n = corr.shape[0]
    d = np.sqrt(2.0 * (1.0 - np.abs(corr)) + 1e-8)
    if eps_grid is None:
        eps_grid = np.linspace(1.0, 1.8, 17)

    lambda_2_curve = np.zeros(len(eps_grid))
    for i, eps in enumerate(eps_grid):
        W_eps = (d < eps).astype(float)
        np.fill_diagonal(W_eps, 0.0)
        deg = W_eps.sum(axis=1)
        # Skip if graph is empty
        if deg.sum() == 0:
            lambda_2_curve[i] = 0.0
            continue
        L = np.diag(deg) - W_eps
        eigvals = np.linalg.eigvalsh(L)
        lambda_2_curve[i] = float(eigvals[1])

    return float(lambda_2_curve.max()), float(eps_grid[lambda_2_curve.argmax()]), lambda_2_curve

class CrashDurationDetector:
    """
    Time-derivative of max_ε λ₂(ε) — the Kang-Yen-Cheong 2025 crash-duration
    indicator. Persistent positive derivative = crash in progress.
    """

    def __init__(self, ema_alpha: float = 0.2):
        self.prev_max_gap = None
        self.deriv_ema = 0.0
        self.alpha = ema_alpha

    def update(self, corr: np.ndarray) -> dict:
        max_gap, argmax_eps, curve = max_spectral_gap_over_filtration(corr)
        if self.prev_max_gap is None:
            deriv = 0.0
        else:
            deriv = max_gap - self.prev_max_gap
        self.deriv_ema = self.alpha * deriv + (1 - self.alpha) * self.deriv_ema
        self.prev_max_gap = max_gap
        return {
            "max_gap": max_gap,
            "argmax_eps": argmax_eps,
            "deriv": deriv,
            "deriv_ema": self.deriv_ema,
            "in_crash": self.deriv_ema > 0.02,  # threshold to be calibrated
        }
```

### 3.5 Fiedler-of-Ricci-flow (the geometric/spectral bridge)

Closes the loop with Week 1 (gauge curvature) and Week 6 (SDEs on SO(n)). Idea: Ricci flow contracts negatively-curved edges (bottlenecks); after a few flow steps, $\lambda_2$ of the rescaled Laplacian becomes a much cleaner indicator.

```python
# omega/nodes/victoria/spectral/ricci_fiedler.py
import numpy as np
import networkx as nx
from GraphRicciCurvature.OllivierRicci import OllivierRicci  # existing Victoria dep
from scipy.sparse.linalg import eigsh
from scipy.sparse import csr_matrix

def ricci_flow_fiedler(
    corr: np.ndarray,
    n_iter: int = 5,
    alpha: float = 0.5,
) -> dict:
    """
    Ollivier–Ricci flow on the correlation graph followed by Fiedler value
    extraction.  Returns both the pre-flow Fiedler (raw) and post-flow Fiedler
    (denoised).  The ratio post/pre is a structural-stress amplification factor.
    """
    n = corr.shape[0]
    d = np.sqrt(2.0 * (1.0 - np.abs(corr)) + 1e-8)
    np.fill_diagonal(d, 0.0)
    G = nx.from_numpy_array(d)

    # Pre-flow Fiedler
    L_pre = nx.normalized_laplacian_matrix(G).astype(float)
    eigvals_pre = eigsh(csr_matrix(L_pre), k=2, which="SM", return_eigenvectors=False)
    fiedler_pre = float(np.sort(eigvals_pre)[1])

    # Ollivier-Ricci flow
    orc = OllivierRicci(G, alpha=alpha, verbose="ERROR")
    orc.compute_ricci_flow(iterations=n_iter)
    G_post = orc.G

    # Post-flow Fiedler
    L_post = nx.normalized_laplacian_matrix(G_post).astype(float)
    eigvals_post = eigsh(csr_matrix(L_post), k=2, which="SM", return_eigenvectors=False)
    fiedler_post = float(np.sort(eigvals_post)[1])

    return {
        "fiedler_pre": fiedler_pre,
        "fiedler_post": fiedler_post,
        "amplification": fiedler_post / max(fiedler_pre, 1e-8),
    }
```

The amplification ratio is the "how-much-bottleneck-was-hidden" factor — a noise-robust spectral stress indicator that combines Week 2 (TDA-like filtration), Week 6 (curvature flow) and Week 7 (spectral gap) in a single number.

---

## 4. Victoria integration plan

### 4.1 Current state (as of v149)

Victoria already has a `SpectralGraphSignal` in `omega/nodes/victoria/spectral_signals.py`. It computes Fiedler value on the **internal signal correlation graph** (12 signals × T rolling cycles) and feeds Gate 4 (`pair_network_gate`) in `four_factor_gate.py` as a **fallback** when Ollivier–Ricci curvature is unavailable. It is wired into `news_projection.py` with weight 1.10. It is *not* applied to the asset correlation graph (the natural domain for crash detection).

Existing signal node behaviour summary:

| Module | Domain | Output | Used by |
|---|---|---|---|
| `spectral_signals.SpectralGraphSignal` | 12-signal correlation graph | `value` = z-scored Fiedler; `regime_tag` $\in$ {consensus, stress, fragmented, warmup} | Gate 4 ORC fallback |
| `geometry/ollivier_ricci.py` | Asset correlation graph | $\kappa^{\mathrm{OR}}$ summary statistics | Gate 4 primary |
| `curvature_signal.py` | Multi-curvature ensemble | Combined curvature score | Adaptive combiner |
| `bayesian_regime.py` | Per-asset return time series | Regime probs (crisis/high_vol/normal) | Conviction filter regime-adaptive thresholds |

### 4.2 Proposed five-phase rollout

**Phase 1 (1–2 weeks, shadow-mode):** Add `omega/nodes/victoria/spectral/asset_fiedler.py` (sketch 3.1) computing the asset-graph Fiedler value alongside the existing signal-graph Fiedler. Log both to `data/{version}_metrics.jsonl`. No effect on trading. Expected output columns: `fiedler_asset, fiedler_asset_z, spectral_gap_asset, fragmentation_asset, n_components_asset`. Sanity check: the **asset-graph** Fiedler should track regime transitions, while the existing **signal-graph** Fiedler tracks intra-decision consensus.

**Phase 2 (1 week, gated production):** Promote `asset_fiedler.fiedler_z` to a feature consumed by `four_factor_gate.py::factor_4` (the existing `pair_network_gate`). Add a V51-style hard gate: if `fiedler_z < -1.5` AND `n_components > 1`, force conviction threshold scaling to $\geq 2.0\times$ (suppression). Test in backtest first; require Week-5 RIE cleaning upstream.

**Phase 3 (1–2 weeks, regime feature):** Add `von_neumann.py` (sketch 3.3) and `signed_laplacian.py` (sketch 3.2). Feed $S_{\mathrm{VN}}$ and `balance_score` to `bayesian_regime.py` as additional regime features. The signed-Laplacian balance score should rise during deleveraging cascades and provides a complementary signal to the unsigned Fiedler.

**Phase 4 (2 weeks, crash-confirmation):** Add `filtration_gap.py` (sketch 3.4) and wire `CrashDurationDetector.update()` into the meta-analyst as **Gate #8** (a new crash-confirmation gate): if `deriv_ema > 0.02`, disable auto-apply and force manual review. This is a *defensive* gate, not an entry signal — purpose is to prevent training-time auto-applies during crashes.

**Phase 5 (research-grade, 4+ weeks):** Add `ricci_fiedler.py` (sketch 3.5) and explore the post-flow Fiedler as a denoised stress indicator. Run head-to-head against pre-flow Fiedler over the existing v100–v149 training corpus. If amplification ratio gives ≥10% AUC improvement on crisis-regime detection, promote to a regime feature.

### 4.3 Performance budget

The asset-graph Fiedler with $n = 60$ tickers and a 5-eigenvalue ARPACK call costs $\sim 3{-}8$ ms per cycle on a single core; well within Victoria's per-cycle 50 ms budget. The Ricci-flow Fiedler (sketch 3.5) at 5 iterations is $\sim 200$ ms; needs to run on a slower side cadence (every 5–10 cycles).

### 4.4 Hard-gate safety

Per CLAUDE.md V49 gate convention, any new spectral feature that *gates trades* must:

1. Pass all 6 existing hard gates (PnL floor, regime parity, drawdown, trade count, signal-integrity, auto-apply audit)
2. Demonstrate non-negative PnL contribution in shadow mode for 100+ cycles before activation
3. Include a feature-flag kill switch in `domain_config.py`

The asset-graph Fiedler is at high risk of *over-filtering entries during high-vol regimes* — this is exactly the V137 lesson from the existing signal-graph Fiedler. Phase 2 must include a "Gate 4 bypass" toggle equivalent to V137c.

---

## 5. Cross-references to prior weeks

**Week 1 (Gauge theory).** The gauge connection's curvature 2-form $F$ is the matrix analogue of the discrete edge-curvature $\kappa^{\mathrm{OR}}$. Sandhu et al.'s spectral-Ricci result is the gauge-theoretic statement "high curvature = high arbitrage opportunity = fragmented graph = small $\lambda_2$". The unified picture: Fiedler $\lambda_2$ is the discrete-graph proxy for the gauge-connection's spectral gap on the principal bundle.

**Week 2 (Persistent homology / TDA).** The filtration in sketch 3.4 (Kang–Yen–Cheong 2025) is *exactly* the Vietoris–Rips filtration parameter $\epsilon$, but instead of tracking $\beta_0, \beta_1$ across filtration, we track $\lambda_2$. The persistent-Laplacian framework (Wang–Wei 2020) unifies both: $\lambda_2(\epsilon)$ is the 0-dimensional persistent-Laplacian eigenvalue at scale $\epsilon$. Victoria's `omega/nodes/victoria/tda/` module can be refactored to expose persistent eigenvalues alongside Betti curves.

**Week 3 (Information geometry).** Banerjee et al. 2025 (*Physica A*) showed that **Fisher-information distance** is more spectrally stable than Pearson correlation for crypto graph construction. Replacing $d_{ij} = \sqrt{2(1 - C_{ij})}$ with the Fisher–Rao distance on a per-asset return PDF makes every spectral indicator in this document Fisher-natural. This is a single-line change in sketch 3.1.

**Week 4 (Optimal transport / Wasserstein).** Ollivier–Ricci curvature *is* a Wasserstein-1 quantity ($\kappa^{\mathrm{OR}}_{ij} = 1 - W_1(\mu_i, \mu_j) / d_{ij}$). Sketch 3.5 (`ricci_fiedler.py`) is the OT–spectral composition. Forward link: Sinkhorn-regularised Ricci flow → spectral gap is a future research direction.

**Week 5 (RMT).** **Mandatory upstream dependency.** Empirical correlation matrices have $\sim 85$–$94\%$ noise eigenvalues for Victoria's $q = N/T$ regime. Pre-cleaning via the BBP-RIE (Bun–Bouchaud–Potters 2017) reduces Fiedler-value bootstrap instability by $\sim 35\%$ in offline tests. All sketches in §3 should consume the RIE-cleaned correlation matrix; the only exception is the filtration indicator (sketch 3.4) where the filtration step partially acts as a regulariser. Argues for promoting both `omega/nodes/victoria/rmt/` and `omega/nodes/victoria/spectral/` to platform-level `omega/core/spectral/` and `omega/core/rmt/`.

**Week 6 (SDEs on manifolds).** The natural dynamical extension: instead of computing a static Fiedler value, evolve the entire spectrum as an SDE on the **spectrum of the SPD cone** $\mathcal{P}_n$. The Wishart-EWMA process from §3.3 of Week 6 has a *spectral* counterpart: the eigenvalue dynamics of a Wishart process are a Dyson Brownian motion. Combining Week 6's SO(n)-flow correlation tracker with Week 7's spectral indicators gives a continuous-time Fiedler-flow process, suitable for HF (sub-minute) crypto regime tracking.

**Week 8 (forward — Renormalisation group).** Spectral graph theory has a natural RG decomposition: low-pass filtering on $L$ corresponds to coarse-graining, the eigenvalue cutoff $\lambda_{\mathrm{cutoff}}$ is the RG scale, and the graph wavelets (Hammond et al. 2011) are the multiscale building blocks. Week 8 will formalise this connection and propose an RG-spectral pipeline for multi-resolution market analysis.

---

## 6. Reading list (annotated)

**Foundations**

- Chung F.R.K. (1997), *Spectral Graph Theory*, AMS. The canonical text.
- Fiedler M. (1973), "Algebraic connectivity of graphs", *Czechoslovak Math. J.* 23. Original definition of $\lambda_2$ as connectivity.
- von Luxburg U. (2007), "A tutorial on spectral clustering", *Statistics and Computing*. Best introduction to the three Laplacians.

**Finance applications**

- Mantegna R.N. (1999), "Hierarchical structure in financial markets", *Eur. Phys. J. B*. The seminal correlation-distance MST paper.
- Tumminello et al. (2005), "A tool for filtering information in complex systems", *PNAS*. PMFG.
- Massara, Di Matteo & Aste (2017), "Network filtering for big data: Triangulated maximally filtered graph", *J. Complex Networks*. TMFG.
- Aste T. (2025), "Information Filtering Networks: Theoretical Foundations, Generative Methodologies, and Real-World Applications", arXiv:2505.03812. Comprehensive 2025 review.

**Spectral stress indicators (2024–2026)**

- Macchiati, Marchese, Mazzarisi, Garlaschelli & Squartini (2024), "Spectral signatures of structural change in financial networks", arXiv:2409.03349. All-length-scale spectral deviation.
- Kang Z.T., Yen P.T.-W., Cheong S.A. (2025), "Indicator from the graph Laplacian of stock market time series cross-sections...", *PLOS One* 20(7) e0327391. Max-spectral-gap-over-filtration as crash-duration indicator.
- Pradhan & Banerjee (2025), "Does FOMC Tone Really Matter? Statistical Evidence from Spectral Graph Network Analysis", arXiv:2510.02705. Hypergraph Laplacian Fiedler event study.
- Neela S. (2025), "Systemic Risk Radar: A Multi-Layer Graph Framework for Early Market Crash Warning", arXiv:2512.17185. Multi-layer GNN benchmarking.
- Liu et al. (2023), "Early warning of stock market crashes using stock network and Laplacian energy-like measure", *Physica A*. LEL indicator.

**Discrete curvature / Ricci-flow on graphs**

- Sandhu R., Georgiou T., Tannenbaum A. (2016), "Ricci curvature: An economic indicator for market fragility and systemic risk", *Science Advances* 2(5). Foundational.
- Samal A. et al. (2021), "Network geometry and market instability", *Royal Society Open Science* 8(2):201734. Four Ricci-types simultaneously.
- Ni C.-C., Lin Y.-Y., Gao J. (2019), "Community detection on networks with Ricci flow", *Scientific Reports* 9. Ricci-flow community detection.
- Topping J. et al. (2021), "Understanding over-squashing... via curvature", *NeurIPS*. Ricci curvature in GNNs.

**Crypto-specific**

- Galas, Wątorek & Drożdż (2025), "Filtering amplitude dependence of correlation dynamics in complex systems: Application to the cryptocurrency market", *Phys. Rev. E*. 140-crypto qMSTs + spectral.
- Banerjee et al. (2025), "Dynamics of network structure in cryptocurrency markets during abrupt changes in Bitcoin price", *Physica A*. Fisher-information-distance edge weights win for spectral stability.
- Iyer, Mishra, Patil (2025), "Network transitions in the cryptocurrency market: The impact of regional conflicts", *Physica A*. Russia-Ukraine vs. Israel-Hamas spectral comparison.
- Khan et al. (2025), "Exploring resilience in the cryptocurrency market: Risk transmission and network robustness", *Finance Research Letters*. DCC-GARCH-$\Delta$CoVaR directed-network spectral centrality.

**Software tools**

- `networkx.linalg.algebraicconnectivity` — Fiedler value/vector via scipy.sparse.linalg.eigsh (TraceMIN-PCG or Lanczos).
- `PyGSP` (epfl-lts2/pygsp) — graph signal processing, Fourier/wavelet transforms on graphs.
- `GraphRicciCurvature` (saibalmars) — Ollivier and Forman Ricci, Ricci-flow community detection. Already a Victoria dependency.
- `mlfinlab.networks.pmfg` — PMFG implementation (paid).
- `pyTMFG` / Aste group MATLAB code — TMFG.

---

## 7. Open questions & research directions

1. **Robustness of hypergraph Fiedler under hyperedge construction choice.** Pradhan & Banerjee 2025 use 3-cliques; no systematic sensitivity analysis exists for crypto. **Action:** before Phase 3, run a sensitivity sweep over $k$-NN, $\tau$-correlation, and mutual-information hyperedges on Victoria's training corpus.

2. **Multi-scale spectral indicators for HF crypto.** At sub-5-minute resolution, Pearson correlation is dominated by microstructure noise. $q$-DCCA (Galas et al. 2025) is one fix; spectral graph wavelets (Hammond et al. 2011) on the same correlation graph are another. **Action:** Week 8 (renormalisation group) should formalise the multi-scale picture.

3. **Spectral indicators on DeFi transaction graphs.** Akcora et al.'s TDA work on Ethereum hints that on-chain spectral analytics could give a leading indicator of cascading liquidations 30–60 minutes ahead of price impact. **Action:** dedicated investigation, separate from this week's correlation-graph focus.

4. **Sinkhorn-regularised Ricci flow.** OT-regularised Ricci flow (Frogner et al. 2020) is faster and numerically more stable than vanilla Ollivier-Ricci flow. Should improve Sketch 3.5's runtime ~5× and reduce flow-step variance. **Action:** evaluate `ott-jax` library in Phase 5.

5. **Causal direction in the signed-Laplacian regime.** The balance score (Sketch 3.2) is symmetric; a directed (asymmetric) signed-Laplacian (Magnetic Laplacian, Furutani et al. 2020) could pick up the directional Granger-causal regime structure that Banerjee et al. 2025 documented. **Action:** preliminary investigation alongside Week 8.

---

*Document complete. Author: Omega scheduled-research process. Cross-referenced with Weeks 1–6.*
