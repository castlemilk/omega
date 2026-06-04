# Gauge Theory and Fiber Bundles in Financial Arbitrage — Cycle 2 (DeFi & Prediction Markets)

**Date:** 2026-06-01
**Research Series:** Omega Geometric Finance, Cycle 2 / Week 1
**Cycle-1 prior:** `2026-03-30-gauge-theory-fiber-bundles-arbitrage.md`, `2026-04-13-gauge-theory-fiber-bundles-arbitrage.md`
**Focus:** What's new since April 2026, with emphasis on (a) cross-chain MEV as gauge holonomy, (b) Polymarket combinatorial arbitrage as a gauge constraint, (c) graph-Ricci/gauge unification in light of cycle-1 weeks 5–7, and (d) a concrete `omega/nodes/victoria/geometry/gauge_bundle.py` spec composing with the existing `market_manifold.py` and `ollivier_ricci.py`.

---

## 1. Executive Summary

Cycle 1 closed with a clear architectural recommendation: promote `omega/nodes/victoria/{geometry, manifolds, rmt, spectral, rg}/` to platform `omega/core/geometry/`. Cycle 2 returns to the foundational topic — gauge theory — but with two structural changes:

1. **Empirical scope shifts from FX to DeFi + prediction markets.** The cycle-1 doc surveyed Ilinski–Farinelli–Tang at the *theoretical* level; cycle 2 anchors the same machinery to (a) cross-chain MEV (Mancino–Sevim–Saguillo Gonzalez 2025, arXiv 2511.17527 *Bunny Hops*), (b) Polymarket combinatorial arbitrage (Suarez-Tangil et al. 2025, arXiv 2508.03474), and (c) the Drożdż/Wątorek tradition of Uniswap-tick multifractality joining the gauge picture via the LPPL scale-symmetry bridge from cycle-1 week 8.
2. **The gauge framework is no longer standalone — it composes with cycle-1 weeks 5–7.** The Oct 2025 *Intrinsic Geometry of the Stock Market from Graph Ricci Flow* paper (arXiv 2510.15942) on NASDAQ-100 makes the discrete-curvature/gauge-curvature identification empirically tractable. Together with the cycle-1 week-7 spectral results and the cycle-1 week-5 RIE-cleaned correlation matrix, Victoria now has the full upstream stack to compute a *signal-grade* gauge curvature feed, not just a research-grade one.

The load-bearing claim of cycle 2: **NFLVR-curvature is the same object as Ollivier-Ricci curvature on the RIE-cleaned correlation graph, up to a sign convention and a numeraire choice.** This is not a new theorem (the Sandhu–Georgiou–Tannenbaum 2016 / Samal et al. 2021 program already pointed at it for equity markets), but cycle-1 weeks 5 and 7 make it *measurable* in a way the cycle-1 week-1 doc could only sketch. The concrete deliverable is a small (~250 LOC) `gauge_bundle.py` module that takes the existing Victoria correlation feed and emits three time-series: integrated curvature `int_Omega`, prediction-market holonomy excess `pm_hol`, and cross-chain triangle gap `xc_tri`.

The single empirical surprise from the 2024–2025 literature: **the most lucrative gauge holonomies are no longer in CEX FX.** Suarez-Tangil et al. document $40M of Polymarket arbitrage on 86M bets across 17,218 conditions over April 2024–April 2025; Mancino et al. document 260,808 cross-chain arbitrages moving $465.8M over 12 chains and 45 bridges in 2023–2024. Single-chain DEX cyclic arbitrage and CEX triangular arbitrage have been competed down to the Belavkin–Pawitan noise floor. Victoria should track all three holonomy classes but allocate research effort proportionally — that means promoting prediction-market gauge structure into the platform layer.

---

## 2. What's Genuinely New Since April 2026

The cycle-1 documents covered Ilinski 1997, Farinelli 2009/2022, Vazquez–Farinelli 2009, Tang et al. 2023, the Farinelli–Takada 2021/2022 series, and the recent extension to frictional markets. Cycle 2 surveys five 2024–2026 directions that are *load-bearing* for Victoria, not just literature additions.

### 2.1 Cross-chain MEV as N-step holonomy (Mancino et al., Nov 2025)

*Bunny Hops and Blockchain Stops: Cross-Chain MEV Detection With N-Hops* (Mancino–Sevim–Saguillo Gonzalez, arXiv 2511.17527, IEEE BRAINS 2025) is the first paper to treat multi-hop cross-chain arbitrage as a graph-theoretic problem at the scale of 2.4 billion transactions across 12 chains and 45 bridges (Sep 2023 – Aug 2024). The published headline number — 260,808 N-step arbitrages, $465.8M moved, ≥$9.5M profit, year-long study — is much less interesting than the structural finding: **$A \to B \to C$ via an intermediate chain is more profitable than direct $A \to C$ in 17.4% of opportunities**. This is exactly Ilinski's holonomy: parallel transport along a triangular loop has non-zero excess because the connection (here, the bridge fee structure plus chain-local gas-cost curvature) is non-flat.

The gauge-theoretic restatement: each blockchain is a fiber, each bridge is a connection coefficient $\omega^i_j$ on a discrete principal bundle whose base manifold is the bridge graph $G_{\text{br}}$. Three-cycle excess is the trace of the curvature 2-form pulled back along the cycle:

$$
\rho_{\text{xc-tri}}(A \to B \to C \to A)
\;=\;
\operatorname{tr}\!\left[\,\Omega(A,B) + \Omega(B,C) + \Omega(C,A)\,\right]
\;-\;
\sum_{\text{bridges}} \text{fee}.
$$

When this exceeds zero plus expected slippage, an arbitrage exists; the rare ($p \approx 0$) multihop cases are exactly the cases where curvature *accumulates* along the path rather than cancelling. The empirical rarity of N≥3 arbitrage in the Mancino dataset is consistent with the curvature being approximately additive *and* small at any single edge — most edge-curvatures are sub-fee, but a few rare paths have constructive accumulation.

**Why this matters for Victoria.** The cross-chain triangle gap `xc_tri` is a directly tradeable signal *and* a leading indicator of bridge stress. Phase 1 of the Victoria integration (§5) will track it as a regime feature in shadow mode.

### 2.2 Polymarket combinatorial arbitrage as a holonomy constraint (Suarez-Tangil et al., Aug 2025)

*Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets* (Suarez-Tangil et al., arXiv 2508.03474, AFT 2025) is the first large-scale empirical study of arbitrage on Polymarket. The numbers — $40M in arbitrage over 86M bets across 17,218 conditions, April 2024–April 2025 — qualify it as one of the most empirically dense gauge-theoretic datasets ever published. Two classes of arbitrage are distinguished:

1. **Market rebalancing arbitrage** — within a single condition $C$, the prices of YES and NO must sum to $1$. When $p(\text{YES}) + p(\text{NO}) < 1$, there is arbitrage. Geometrically, this is *first-order* curvature: the fiber over $C$ has structure group $U(1)$ (the price phase) and the rebalancing constraint is the flatness of the trivial connection on the YES/NO fiber.
2. **Combinatorial arbitrage** — when conditions $C_1, \ldots, C_k$ are logically dependent (mutually exclusive, subset, etc.), there is a system of inequalities $p_i$ must satisfy. When the empirical prices violate them, arbitrage exists. Geometrically, this is *higher-order* curvature: the connection on the multi-condition fiber bundle has non-zero curvature in directions that correspond to logical dependence between conditions.

The latter is a textbook gauge constraint. If $C_1 \subset C_2$ (e.g., "Bitcoin > 200K on Dec 31" $\subset$ "Bitcoin > 100K on Dec 31"), then $p(C_1) \le p(C_2)$ is required by probability; violation IS arbitrage and IS curvature on a 2-condition fiber. The combinatorial arbitrage results in Polymarket are exactly the failures of this connection to be flat across logical-dependence directions.

**Why this matters for Victoria.** The Omega Victoria architecture is project-agnostic and the CLAUDE.md docs explicitly mention `omega/nodes/polymarket/` as a planned project. The gauge structure of prediction markets is *richer* than FX (because the structure group changes per-condition and the logical-dependence graph is non-trivial), but the computational machinery — discrete curvature on a graph — is *cheaper* than continuous FX curvature. Phase 2 of the Victoria integration recommends a Polymarket-specific `gauge_constraint.py` based directly on the Suarez-Tangil combinatorial-relation graph.

### 2.3 Intrinsic geometry from Graph Ricci flow (Oct 2025, arXiv 2510.15942)

*Intrinsic Geometry of the Stock Market from Graph Ricci Flow* (arXiv 2510.15942, Oct 2025) applies discrete Ollivier–Ricci curvature with Ricci flow to the NASDAQ-100 empirical-correlation graph. The headline result — Ricci flow on the correlation graph reveals hidden hierarchies and clustering structure not visible to standard MST/PMFG analyses — is methodological. The load-bearing observation for cycle-2 is the construction itself:

- Build asset correlation graph $G$ with edge weights $w_{ij} = \sqrt{2(1-\rho_{ij})}$ (the Mantegna distance, cycle-1 week 7).
- Compute Ollivier–Ricci curvature $\kappa_{ij} = 1 - W_1(\mu_i, \mu_j) / d(i,j)$ where $\mu_i$ is the lazy-walk distribution at $i$ and $W_1$ is the 1-Wasserstein distance (cycle-1 week 4).
- Flow the graph: $w_{ij}(t+1) = w_{ij}(t)(1 - \epsilon \kappa_{ij}(t))$.
- Edges with persistently negative curvature collapse; edges with positive curvature expand. The fixed points are intrinsic clusters.

The bridge to gauge theory is the **Sandhu–Georgiou–Tannenbaum (2016) identity**: under the lazy-walk Markov chain, the Ollivier–Ricci curvature on a graph $G$ matches the scalar Ricci curvature of the discrete-spectrum Laplacian of $G$, and the discrete-spectrum Laplacian *is* the discretization of the gauge-bundle curvature 2-form $\Omega$ when the graph is given the natural fiber-bundle structure (assets as fibers, correlation edges as parallel-transport coefficients). In short: **Ollivier–Ricci curvature on the correlation graph is the discrete avatar of the Ilinski/Farinelli gauge curvature**, with the sign convention $\kappa < 0 \Leftrightarrow \Omega \ne 0 \Leftrightarrow$ arbitrage.

Cycle-1 week 5 (RIE cleaning) reduces the bootstrap instability of correlation-graph Ricci by ~85% (as documented in the week-5 cross-references). Cycle-1 week 7 (spectral graph theory) gives algebraic-connectivity $\lambda_2$ as a complementary stress indicator. Combining them: $(\kappa_{\text{Ollivier}}, \lambda_2, \Omega_{\text{path}})$ on the RIE-cleaned correlation graph is a *complete* discrete gauge-curvature feature vector that subsumes the cycle-1 week-1 Phase-1 sketch.

### 2.4 GNN-based triangular arbitrage detection (Feb 2025, arXiv 2502.03194)

*Efficient Triangular Arbitrage Detection via Graph Neural Networks* (arXiv 2502.03194, Feb 2025) and the follow-up Atlantis Press paper (*Arbitrage Detection in Crypto Markets Using Graph Neural Networks*, ICISD-25) use GraphSAGE with custom edge fusion on snapshots from KuCoin, Gate.io, Huobi, Bitget, and MEXC across BTC/ETH/SOL/XRP/LTC/ADA. Edge features include log exchange rate, inverse rate, volume, volatility, trading fee, and one-hot exchange identifiers. The reported balance of "performance, interpretability, and deployment readiness" is what makes this load-bearing: it is the first GNN arbitrage system credibly deployable at production latency on commodity hardware.

The gauge interpretation: GraphSAGE learns a per-node embedding $h_i$ such that $h_i - h_j \approx \omega_{ij}$ along the empirical connection. The classifier head predicts cyclic arbitrage on triangles. This is, structurally, a *learned* discrete connection — a neural parameterization of the gauge field. The classifier's positive predictions correspond to triangles where the learned connection has non-trivial holonomy.

**Why this matters for Victoria.** The GraphSAGE-on-edge-features architecture is the natural plug for the existing Victoria adaptive_combiner: the same 12-signal correlation graph that feeds `spectral_signals.py` and `geometry/ollivier_ricci.py` can feed a small GNN whose output is a binary "non-trivial holonomy detected" flag. Phase 4 of the integration plan (§5) is exactly this — the most research-grade phase, but with a concrete prior art baseline.

### 2.5 φ⁴ quantum field theory of S&P 500 returns (Dec 2025, arXiv 2512.17225)

The Dec 2025 paper *Modelling financial time series with φ⁴ quantum field theory* (arXiv 2512.17225) is the first credible φ⁴-on-S&P-500 fit since the 2011 GARCH-lattice paper. The continuum φ⁴ field theory with inhomogeneous couplings and explicit symmetry-breaking reproduces market kurtosis as a function of the symmetry-breaking parameter, and the authors explicitly identify the symmetry-broken phase with high-kurtosis regimes that precede crash events.

This is not directly tradeable but it closes a theoretical loop. In Ilinski's 1997 framework, gauge symmetry breaking corresponds to NFLVR violation; the φ⁴ paper provides the *dynamics* — a Ginzburg–Landau picture in which the symmetry-breaking parameter is a slow-varying field whose value determines whether the curvature is identically zero. The slow-varying parameter generalizes the Vazquez–Farinelli "drift of the connection" and the Tang frictional-market curvature into a single Higgs-like field.

**Why this matters for Victoria.** The φ⁴ paper is research-grade — not for production — but it suggests a regime label space (`unbroken-symmetry-efficient`, `pre-crash-broken-symmetry`, `crashed`) that connects cycle-1 week 2 (TDA crash prediction) and cycle-1 week 8 (LPPL bubble fitting) to the gauge-theoretic framework via a single thermodynamic quantity (the symmetry-breaking parameter). This is the angle for the cycle-2 week-8 doc when we get there.

### 2.6 Other notable additions

- **The Tang et al. 2023 frictional-market gauge extension** continues to be the standard reference; no major successor in 2024–2025.
- **CFMM curvature** has its own literature trajectory after Angeris–Chitra–Evans 2022 "When Does the Tail Wag the Dog?". The 2023 Angeris–Chitra–Diamandis–Evans–Kulkarni paper (arXiv 2308.08066) establishes that every CFMM has a canonical homogeneous trading function; subsequent 2024 work (Medium "Arbitrage Routing as a Multi-Surface Liquidity Optimization") treats Uniswap V4 hooks as programmable curvature surfaces. The fiber bundle is now per-pool, not per-asset, and the gauge group is the structure of permissible swap parameter changes induced by hooks. This is a substantial generalization but does not yet have a load-bearing crypto-market empirical anchor outside the Angeris–Chitra–Diamandis arbitrage-routing experiments.
- **Quantum finance / Higgs in markets** (Gauge symmetries and the Higgs mechanism in Quantum Finance, arXiv 2306.03237, with the Dec 2025 φ⁴ follow-up arXiv 2512.17225) provides the GL theoretical scaffold but no implementable signal yet.

---

## 3. The Unified Gauge–Ricci Picture

Cycle-1 week 4 (optimal transport), week 5 (RMT), and week 7 (spectral graph theory) provide the upstream components. The unified picture for cycle 2:

### 3.1 Construction

Given an N-asset correlation matrix $C$ over a rolling window $T$, the cycle-2 gauge construction is:

**Step 1 — Clean.** Apply BBP-RIE (cycle-1 week 5, `omega/nodes/victoria/rmt_denoiser.py`) to get $\tilde C$. The aspect ratio $q = N/T \approx 0.1{-}0.3$ for Victoria's typical 60-day window means ~85–94% of $C$'s eigenvalues are noise without cleaning.

**Step 2 — Embed.** Construct the Mantegna distance graph $G$ with $w_{ij} = \sqrt{2(1 - \tilde C_{ij})}$. This is the natural metric on the asset manifold induced by correlation; Mantegna 1999 is the standard reference.

**Step 3 — Compute discrete gauge curvature.** Two equivalent objects (up to sign and normalization) are available:

- **Ollivier–Ricci edge curvature** $\kappa_{ij}^{\text{OR}} = 1 - W_1(\mu_i, \mu_j) / w_{ij}$ where $\mu_i$ is the lazy-walk distribution at $i$. Computed by GraphRicciCurvature (PyPI, NetworkX-compatible).
- **Discrete gauge holonomy** along a triangle $(i,j,k)$: $\rho_{ijk} = \log(\tilde C_{ij}) + \log(\tilde C_{jk}) + \log(\tilde C_{ki})$. This is the discrete analogue of $\oint_{\partial\Delta} \omega$ where $\omega$ is the connection 1-form with components $\omega_{ij} = \log \tilde C_{ij}$ (the *information geometry* connection — cycle-1 week 3 — when $\tilde C$ is interpreted as a transition kernel).

The two are related by the discrete Stokes' theorem on the graph: $\sum_{\text{triangles}} \rho_{ijk}$ over a region equals $\sum_{\text{edges in interior}} \kappa^{\text{OR}}_{ij}$ up to boundary terms. For Victoria's purposes, the holonomy version is cheaper (no Wasserstein computation) and the Ollivier–Ricci version is more informative (captures higher-order structure).

**Step 4 — Integrate.** Define the scalar gauge-curvature stress index
$$
\Omega_{\text{int}}(t) = \frac{1}{|E|} \sum_{(i,j) \in E} \kappa^{\text{OR}}_{ij}(t).
$$
This is a single scalar per time step. Cycle-1 week 7 documents that this scalar tracks the algebraic connectivity $\lambda_2$ of the Laplacian closely but is more sensitive to local edge-level stress.

### 3.2 The four propositions

Stated informally:

**P1 (NFLVR–Ricci equivalence).** A market is locally arbitrage-free along a path $\gamma$ in state space iff the integrated Ricci curvature $\int_\gamma \kappa^{\text{OR}}$ vanishes. (Discretized Ilinski; folklore in the Sandhu–Georgiou–Tannenbaum line.)

**P2 (Stress = negative curvature).** Empirical observations (Samal et al. 2021, arXiv 2510.15942 NASDAQ-100, plus cycle-1 week 7 crypto results) consistently find $\kappa^{\text{OR}} < 0$ during crisis periods and $\kappa^{\text{OR}} \approx 0$ during normal regimes. The sign convention is that *negative* Ollivier–Ricci curvature corresponds to *non-zero* gauge curvature, i.e., arbitrage opportunity.

**P3 (Cleaning is mandatory).** Without cycle-1 week-5 RIE cleaning, $\kappa^{\text{OR}}$ on raw correlation graphs has bootstrap standard deviation ~7–10x larger than on cleaned graphs. The week-5 cross-reference table quotes ~85% noise reduction; the practical implication is that pre-RIE $\kappa^{\text{OR}}$ is not signal-grade.

**P4 (Holonomy holds across asset classes).** The triangular-arbitrage holonomy on FX (Ilinski's original application), the cross-chain holonomy on bridge graphs (Mancino et al. 2025), and the combinatorial-condition holonomy on Polymarket (Suarez-Tangil et al. 2025) are all instances of the same discrete-gauge construction with different choices of fiber and structure group. Victoria can compute all three with the same `gauge_bundle.py` infrastructure.

---

## 4. Code Sketches

These are Python sketches structured to slot into `omega/nodes/victoria/geometry/gauge_bundle.py`. They are intentionally minimal — production-grade versions will need the standard Victoria observability hooks, but the algorithmic core is here.

### 4.1 Sketch: discrete gauge holonomy on the cleaned correlation graph

```python
# omega/nodes/victoria/geometry/gauge_bundle.py
"""Discrete gauge curvature on the RIE-cleaned correlation graph.

Composes Week-5 RIE cleaning (rmt_denoiser) with Week-1 gauge curvature.
Outputs three scalar signals: int_omega, max_abs_holonomy, triangle_excess_frac.
"""
from __future__ import annotations

import numpy as np
import networkx as nx
from itertools import combinations
from dataclasses import dataclass


@dataclass
class GaugeCurvatureFeatures:
    """Scalar gauge-curvature features for the regime feature vector."""
    int_omega: float          # mean Ollivier-Ricci over edges (Eq. 3.1)
    max_abs_holonomy: float   # max |sum log C| over all triangles
    triangle_excess_frac: float  # fraction of triangles with |holonomy| > tau
    lambda_2: float           # Fiedler value for cross-reference (Week 7)


def mantegna_distance(C_clean: np.ndarray) -> np.ndarray:
    """Mantegna 1999: distance from correlation, isotone & ultrametric-friendly."""
    # Clip to avoid sqrt(negative) on numerical-noise diagonal terms.
    return np.sqrt(2.0 * np.clip(1.0 - C_clean, 0.0, 2.0))


def correlation_graph(C_clean: np.ndarray, names: list[str]) -> nx.Graph:
    """Mantegna-distance weighted graph on N assets."""
    D = mantegna_distance(C_clean)
    G = nx.Graph()
    G.add_nodes_from(names)
    for i, j in combinations(range(len(names)), 2):
        G.add_edge(names[i], names[j], weight=float(D[i, j]))
    return G


def triangle_holonomy(C_clean: np.ndarray) -> np.ndarray:
    """Discrete gauge holonomy on every 3-cycle.

    H_ijk = log C_ij + log C_jk + log C_ki
    Returns flat array of length C(N,3).
    """
    N = C_clean.shape[0]
    # Use clip to keep log defined on numerical-zero entries.
    logC = np.log(np.clip(np.abs(C_clean), 1e-10, None)) * np.sign(C_clean)
    out = []
    for i, j, k in combinations(range(N), 3):
        out.append(logC[i, j] + logC[j, k] + logC[k, i])
    return np.asarray(out)


def compute_features(
    C_clean: np.ndarray,
    names: list[str],
    holonomy_threshold: float = 0.05,
) -> GaugeCurvatureFeatures:
    """Compute the scalar gauge-curvature feature bundle.

    C_clean MUST be the RIE-cleaned correlation matrix; raw Pearson is too noisy.
    """
    # Ollivier-Ricci via GraphRicciCurvature (composes Week 4 OT + Week 7 graph).
    from GraphRicciCurvature.OllivierRicci import OllivierRicci

    G = correlation_graph(C_clean, names)
    orc = OllivierRicci(G, alpha=0.5, verbose="ERROR")
    orc.compute_ricci_curvature()
    kappas = [data["ricciCurvature"] for _, _, data in orc.G.edges(data=True)]
    int_omega = float(np.mean(kappas))

    # Triangle holonomy.
    H = triangle_holonomy(C_clean)
    max_abs_holonomy = float(np.max(np.abs(H)))
    triangle_excess_frac = float(np.mean(np.abs(H) > holonomy_threshold))

    # Cross-check: Fiedler value (Week 7).
    L = nx.laplacian_matrix(G).astype(float).toarray()
    eigvals = np.linalg.eigvalsh(L)
    lambda_2 = float(eigvals[1])  # second-smallest is algebraic connectivity

    return GaugeCurvatureFeatures(
        int_omega=int_omega,
        max_abs_holonomy=max_abs_holonomy,
        triangle_excess_frac=triangle_excess_frac,
        lambda_2=lambda_2,
    )
```

**Calling pattern from `bayesian_regime.py`:**

```python
# In omega/nodes/victoria/bayesian_regime.py
from omega.nodes.victoria.rmt_denoiser import clean_correlation
from omega.nodes.victoria.geometry.gauge_bundle import compute_features

def regime_features_with_gauge(returns_window: np.ndarray, names: list[str]):
    C_raw = np.corrcoef(returns_window.T)
    C_clean = clean_correlation(C_raw, q=len(names) / returns_window.shape[0])
    gauge = compute_features(C_clean, names)
    return {
        "gauge_int_omega": gauge.int_omega,
        "gauge_max_holonomy": gauge.max_abs_holonomy,
        "gauge_triangle_excess": gauge.triangle_excess_frac,
        "gauge_lambda_2": gauge.lambda_2,
    }
```

### 4.2 Sketch: Polymarket combinatorial-arbitrage detector

```python
# omega/nodes/victoria/geometry/pm_gauge_constraint.py
"""Polymarket combinatorial arbitrage as gauge-constraint violation.

Each Polymarket condition is a fiber with U(1) phase = price.
Logical dependence between conditions induces a gauge constraint on prices.
Violations are arbitrage opportunities = non-flat connection along
logical-dependence edges.

Follows Suarez-Tangil et al. (arXiv:2508.03474, AFT 2025).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class Relation(Enum):
    SUBSET = "subset"          # C1 implies C2 (e.g., "BTC>200K" => "BTC>100K")
    DISJOINT = "disjoint"      # mutually exclusive
    COMPLEMENT = "complement"  # exhaustive partition of two


@dataclass
class ConditionPrice:
    cond_id: str
    p_yes: float
    p_no: float
    liquidity: float


@dataclass
class CombinatorialArbitrage:
    relation: Relation
    conditions: list[str]
    excess: float           # gauge holonomy along the constraint edge
    direction: str          # which side to buy / sell


def detect(
    prices: dict[str, ConditionPrice],
    relations: Iterable[tuple[Relation, tuple[str, ...]]],
    fee_bps: float = 20.0,
    min_liquidity: float = 100.0,
) -> list[CombinatorialArbitrage]:
    """Return list of detected combinatorial arbitrages.

    Each Relation defines a gauge constraint:
      SUBSET: p(C1) - p(C2) <= 0      => excess = p(C1) - p(C2)
      DISJOINT: p(C1) + p(C2) - 1 <= 0 => excess = p(C1) + p(C2) - 1
      COMPLEMENT: p(C1) + p(C2) = 1    => |excess| = |p(C1) + p(C2) - 1|

    Excess > fee + slippage_bps/10000 is a real arbitrage.
    """
    threshold = fee_bps / 10000.0
    out: list[CombinatorialArbitrage] = []

    for rel, conds in relations:
        # Liquidity gate — Suarez-Tangil show most paper arbitrages are too thin.
        liq = min(prices[c].liquidity for c in conds if c in prices)
        if liq < min_liquidity:
            continue

        if rel == Relation.SUBSET:
            c1, c2 = conds
            ex = prices[c1].p_yes - prices[c2].p_yes
            if ex > threshold:
                out.append(CombinatorialArbitrage(
                    rel, list(conds), ex, f"sell YES {c1}, buy YES {c2}"))

        elif rel == Relation.DISJOINT:
            c1, c2 = conds
            ex = prices[c1].p_yes + prices[c2].p_yes - 1.0
            if ex > threshold:
                out.append(CombinatorialArbitrage(
                    rel, list(conds), ex, f"sell YES {c1} and YES {c2}"))

        elif rel == Relation.COMPLEMENT:
            c1, c2 = conds
            ex = prices[c1].p_yes + prices[c2].p_yes - 1.0
            if abs(ex) > threshold:
                direction = (f"sell YES {c1}+{c2}" if ex > 0
                             else f"buy YES {c1}+{c2}")
                out.append(CombinatorialArbitrage(
                    rel, list(conds), abs(ex), direction))

    return out
```

**Note on the Suarez-Tangil dataset.** Their $40M figure is *paper* arbitrage (gross of bridging costs, slippage, and resolution risk). In the cycle-2 Polymarket integration, the `fee_bps` and `min_liquidity` parameters should be tuned from a 30-day live-shadow comparison before this is allowed to influence sizing.

### 4.3 Sketch: cross-chain triangle holonomy detector

```python
# omega/nodes/victoria/geometry/xc_gauge.py
"""Cross-chain triangle holonomy: gauge curvature on the bridge graph.

Follows Mancino-Sevim-Saguillo Gonzalez (arXiv:2511.17527, BRAINS 2025).
The bridge graph G has chains as nodes and bridges as edges; each edge has a
quoted rate and fee. Three-cycle holonomy is gauge curvature on the bundle
whose fiber over chain X is the asset value on X.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations


@dataclass
class BridgeEdge:
    src: str
    dst: str
    rate: float       # rate per 1 unit src to dst (after gas)
    fee: float        # additive fee, normalized to dst units
    latency_s: float  # bridge confirmation latency


@dataclass
class TriangleArbitrage:
    cycle: tuple[str, ...]
    excess: float        # net log-return after fees
    worst_latency_s: float


def compute(
    bridges: list[BridgeEdge],
    chains: list[str],
    excess_threshold: float = 0.002,
) -> list[TriangleArbitrage]:
    """Detect three-chain cycles with positive holonomy net of fees."""
    import math
    edge_map = {(b.src, b.dst): b for b in bridges}
    out: list[TriangleArbitrage] = []

    for c1, c2, c3 in combinations(chains, 3):
        for cycle in [(c1, c2, c3, c1), (c1, c3, c2, c1)]:
            edges = [edge_map.get((cycle[i], cycle[i+1])) for i in range(3)]
            if any(e is None for e in edges):
                continue
            log_return = sum(math.log(e.rate) for e in edges)
            fee_cost = sum(e.fee / e.rate for e in edges)
            net = log_return - fee_cost
            if net > excess_threshold:
                out.append(TriangleArbitrage(
                    cycle=cycle,
                    excess=net,
                    worst_latency_s=max(e.latency_s for e in edges),
                ))

    return out
```

The latency field is necessary because the cross-chain holonomy is a *delayed* observation — the bridge confirmation takes 30s–10min, during which the curvature may move. Mancino et al. document that this is the primary reason the 17.4% N=3 advantage rarely converts to executed profit.

### 4.4 Sketch: GNN gauge-curvature classifier (research-grade)

```python
# omega/nodes/victoria/geometry/gnn_gauge.py
"""GraphSAGE-based learned gauge connection.

Follows Yang et al. arXiv:2502.03194 architecture. Edge features include
log rate, inverse rate, volume, volatility, fee. Output: per-triangle
binary 'non-trivial holonomy' probability.

This is Phase 4 in the integration plan — research-grade, not for production
sizing without 30+ days of live-shadow validation.
"""
from __future__ import annotations

try:
    import torch
    from torch_geometric.nn import SAGEConv
    from torch_geometric.data import Data
except ImportError:  # Heavy deps are optional per CLAUDE.md
    torch = None
    SAGEConv = None


class GaugeSAGE(torch.nn.Module if torch is not None else object):
    """Two-layer GraphSAGE with edge-feature fusion."""

    def __init__(self, in_node: int, in_edge: int, hidden: int = 64):
        super().__init__()
        # Edge MLP -> per-edge feature embedding.
        self.edge_mlp = torch.nn.Sequential(
            torch.nn.Linear(in_edge, hidden), torch.nn.ReLU(),
            torch.nn.Linear(hidden, hidden),
        )
        # Node embedding via SAGEConv on the augmented graph.
        self.conv1 = SAGEConv(in_node + hidden, hidden)
        self.conv2 = SAGEConv(hidden, hidden)
        # Triangle classifier: concat three node embeds + three edge embeds.
        self.triangle_head = torch.nn.Sequential(
            torch.nn.Linear(3 * hidden + 3 * hidden, hidden), torch.nn.ReLU(),
            torch.nn.Linear(hidden, 1),
        )

    def forward(self, data: "Data", triangle_idx: torch.Tensor) -> torch.Tensor:
        # Fold edge features into node features by averaging per node.
        edge_emb = self.edge_mlp(data.edge_attr)
        # Scatter mean edge_emb to its endpoints, concat to node features.
        # ... (omitted: standard scatter_mean pattern) ...
        h = self.conv1(data.x, data.edge_index)
        h = torch.relu(h)
        h = self.conv2(h, data.edge_index)
        # triangle_idx: (T, 3) node-index triples; (T, 3) edge-index triples.
        n_idx, e_idx = triangle_idx[:, :3], triangle_idx[:, 3:]
        node_feats = h[n_idx].reshape(-1, 3 * h.shape[1])
        edge_feats = edge_emb[e_idx].reshape(-1, 3 * edge_emb.shape[1])
        return torch.sigmoid(self.triangle_head(
            torch.cat([node_feats, edge_feats], dim=1)).squeeze(-1))
```

The training labels come from the discrete holonomy check from §4.1 (triangle log-sum exceeds threshold). The GNN is therefore a *learned approximation* of the analytic gauge holonomy — its value is amortized inference at production latency, not new discovery. Phase 4 (§5) treats this as an opt-in research module.

### 4.5 Sketch: live ccxt wrapper

```python
# omega/nodes/victoria/geometry/live_gauge.py
"""Live gauge-curvature monitor for a basket of crypto pairs.

Subscribes to ccxt order books for a fixed set of triangles
(e.g., BTC/USDT, ETH/USDT, ETH/BTC) and emits triangular holonomy events.
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass

try:
    import ccxt.async_support as ccxta  # async ccxt
except ImportError:
    ccxta = None

log = logging.getLogger(__name__)


@dataclass
class TriangleQuote:
    exchange: str
    base: str
    quote: str
    third: str         # the bridging asset
    rate_bq: float     # base -> quote
    rate_qt: float     # quote -> third
    rate_tb: float     # third -> base
    fee_bps: float


def holonomy(q: TriangleQuote) -> float:
    """Signed log-holonomy net of fees."""
    raw = math.log(q.rate_bq) + math.log(q.rate_qt) + math.log(q.rate_tb)
    fee_log = 3 * math.log(1 - q.fee_bps / 10000)
    return raw + fee_log


async def monitor(
    exchange_id: str,
    triangles: list[tuple[str, str, str]],
    threshold: float = 0.001,
    poll_s: float = 1.0,
):
    if ccxta is None:
        raise RuntimeError("ccxt async not installed")
    ex = getattr(ccxta, exchange_id)()
    try:
        while True:
            for base, quote, third in triangles:
                pair_bq = f"{base}/{quote}"
                pair_qt = f"{quote}/{third}"
                pair_tb = f"{third}/{base}"
                try:
                    obs = await asyncio.gather(
                        ex.fetch_ticker(pair_bq),
                        ex.fetch_ticker(pair_qt),
                        ex.fetch_ticker(pair_tb),
                    )
                    q = TriangleQuote(
                        exchange=exchange_id,
                        base=base, quote=quote, third=third,
                        rate_bq=obs[0]["last"],
                        rate_qt=obs[1]["last"],
                        rate_tb=obs[2]["last"],
                        fee_bps=10.0,  # placeholder; pull from ex.fees
                    )
                    h = holonomy(q)
                    if abs(h) > threshold:
                        log.info(
                            "gauge_holonomy",
                            extra={"exchange": exchange_id,
                                   "triangle": (base, quote, third),
                                   "holonomy": h},
                        )
                except Exception as e:
                    log.warning("triangle fetch failed: %s", e)
            await asyncio.sleep(poll_s)
    finally:
        await ex.close()
```

The CLAUDE.md constraint that Binance/Bybit are geo-blocked from the US implies the live monitor should default to Coinbase + Kraken; both are present in ccxt with sufficient pair coverage for the canonical BTC/ETH/USDT triangle.

---

## 5. Victoria Integration Plan

Five phases, mapped to the existing Victoria architecture. Each phase ends with a hard-gate check (V49-style) against the previous training cycle.

**Phase 1 — Shadow-mode gauge features in `bayesian_regime.py`** *(week of 2026-06-08)*

Add `gauge_int_omega`, `gauge_max_holonomy`, `gauge_triangle_excess`, `gauge_lambda_2` to the regime feature vector. Composes with the existing `rmt_denoiser.py` and `spectral_signals.py`. No effect on sizing. Metric logging via `/tmp/{version}_metrics.jsonl`. Hard-gate check: the four new features must not destabilize the regime classifier (regime parity across `crisis`/`high_vol`/`normal` per CLAUDE.md regime labels).

**Phase 2 — Promote `gauge_int_omega` to Gate #10 in `four_factor_gate.py`** *(week of 2026-06-22)*

Hard rule: when `gauge_int_omega < -0.10` (Ollivier–Ricci stress floor empirically calibrated on cycle-1 NASDAQ-100 reference and cycle-1 week-7 crypto results), suppress auto-apply. This is the gauge-theoretic analogue of the cycle-1 week-7 Gate #8 (crash-duration filter) and week-8 Gate #9 (LPPL bubble score). Bayesian conjugacy: the three gates form a defensive trinity at distinct stress timescales (Gate #8 multi-day, Gate #9 multi-week, Gate #10 intraday-multi-day).

**Phase 3 — Polymarket combinatorial arbitrage detector** *(weeks of 2026-07-06 / 2026-07-13)*

Wire `pm_gauge_constraint.py` (§4.2) into a new `omega/nodes/polymarket/` project. This is project-grade, not platform-grade (per CLAUDE.md), but the underlying gauge machinery is shared. The integration provides Victoria a *cross-asset* gauge signal: prediction-market combinatorial excess is a leading indicator of regime-information arrival (Polymarket reacts to news in tens of seconds, equity/crypto in minutes). Hard-gate check: paper-tradeable excess must exceed a 30-day rolling 95th-percentile fee-and-slippage estimate before promotion.

**Phase 4 — GNN-learned gauge classifier (research)** *(month of 2026-08)*

Train `GaugeSAGE` (§4.4) on the 12-signal Victoria correlation graph plus a 6-CEX asset graph. Use the analytic gauge holonomy as the label. Validate by held-out triangles. The deliverable is a single inference-cost number: the GNN should match the analytic holonomy detector at <10x inference cost per cycle (otherwise the analytic detector is preferable). Note: heavy ML deps (torch, torch_geometric) are optional extras per CLAUDE.md — must remain optional.

**Phase 5 — Promote to platform** *(after 2026-09)*

Per the cycle-1 closing recommendation, promote `omega/nodes/victoria/geometry/` (with cycle-2 additions) to `omega/core/geometry/`. Move only the project-agnostic parts: `gauge_bundle.py` (§4.1) and the discrete-curvature/holonomy primitives. Leave `pm_gauge_constraint.py` and `xc_gauge.py` in their respective project trees. This unblocks Polymarket and any future projects from re-implementing the same machinery.

---

## 6. Cross-References to Cycle 1

Cycle 2 is consciously a *recomposition* rather than a new direction. The cross-references that matter:

- **Week 1 (cycle 1) → this doc.** Cycle 1 established the curvature-arbitrage correspondence at the continuous-Farinelli level. Cycle 2 makes it computable: Ollivier–Ricci on the RIE-cleaned correlation graph IS the discrete avatar of Farinelli's $\Omega$, up to sign and numeraire. The cycle-1 doc's Phase-1 sketch — discrete curvature on the asset graph — is the same algorithm; the cycle-2 doc's improvement is using cycle-1 weeks 5 and 7 as upstream and downstream.
- **Week 2 (persistent homology) → §3.1.** The Vietoris–Rips filtration on the Mantegna-distance graph is exactly the construction the cycle-1 week-2 TDA detector uses; the gauge features `int_omega` and `triangle_excess_frac` are 0-dim and 1-dim persistence summaries respectively. Composing: the *bottleneck distance* between successive triangle-holonomy distributions is a richer crash precursor than either signal alone.
- **Week 3 (information geometry) → §3.1.** The $\log \tilde C_{ij}$ connection on the correlation graph is the Fisher-Rao information-geometry connection when $\tilde C$ is read as a transition kernel. The cycle-1 week-3 natural-gradient update of signal weights is the same parallel-transport machinery as the cycle-2 §3.1 holonomy. They are dual: signals flow on the Fisher manifold, prices flow on the gauge manifold, both via the same connection coefficients (up to sign).
- **Week 4 (optimal transport) → §3.1, §4.1.** The 1-Wasserstein distance in $\kappa^{\text{OR}}$ is the same $W_1$ as the cycle-1 week-4 regime detector. The Ollivier–Ricci computation is internally an OT problem solved by linear programming (POT or GraphRicciCurvature). The cycle-1 week-4 sliced-Wasserstein speedup ($O(dLn\log n)$) carries over.
- **Week 5 (RMT) → §3.1, §3.2 P3.** *Mandatory upstream.* The BBP-RIE clean is the single biggest factor in making cycle-2's gauge features signal-grade. The week-5 doc quantified ~85% bootstrap-variance reduction for Ollivier–Ricci on cleaned graphs; this is what makes Phase 2 (Gate #10) viable.
- **Week 6 (stochastic calculus on manifolds) → §3.1, §4.1.** The Wishart EWMA correlation flow (week 6, §4.3) is the natural dynamical version of the static $\tilde C$ that §3.1 uses. Composing: feed the Week-6 Wishart EWMA correlation directly into `compute_features` — this is approximately Phase 1+6, scheduled for cycle-2 week 6.
- **Week 7 (spectral graph theory) → §3.1, §4.1.** $\lambda_2$ (Fiedler) is computed alongside `int_omega` in `compute_features` as a *cross-check*: empirically they correlate at $\rho \approx 0.7$ on the cycle-1 week-7 crypto datasets but the residual is the high-information signal. Diverging $\lambda_2$ and `int_omega` indicates spectral-vs-curvature mismatch — typically associated with thin-tailed fragmentation rather than crisis.
- **Week 8 (renormalization group) → §2.5.** The φ⁴ quantum-field-theory regime label space (`unbroken-symmetry`, `pre-crash`, `crashed`) bridges directly to the week-8 LPPL bubble regime. Cycle 2 week 8 will operationalize this bridge.

---

## 7. Open Questions for Cycle 2

Five questions that cycle 2 should answer before cycle 3 starts:

1. **Sign convention.** The cycle-2 doc adopts $\kappa^{\text{OR}} < 0 \Leftrightarrow$ arbitrage, following Samal et al. 2021 and arXiv 2510.15942. Some papers in the gauge-theoretic tradition use the opposite convention. Phase 1 should verify the sign empirically against ground-truth Polymarket arbitrages.
2. **Threshold calibration.** The `holonomy_threshold=0.05` in §4.1 is a placeholder. The Mancino et al. and Suarez-Tangil datasets provide direct empirical-distribution anchors that should replace this.
3. **The Higgs-like field.** The φ⁴ paper (arXiv 2512.17225) proposes a slow-varying symmetry-breaking parameter. Is it estimable from Victoria's existing regime classifier output? This is a research question for cycle-2 week 8.
4. **The Stiefel/Grassmannian extension.** Cycle-1 weeks 3, 6, and 7 all touch on the Stiefel manifold (orthonormal frames on the asset bundle). Is there a natural Stiefel-gauge theory that unifies the discrete graph constructions with the continuous principal-bundle picture? The 2024 *Stiefel optimization is NP-hard* result (Lekheng Lim) is cautionary — the Stiefel side is computationally expensive — but the continuous-discrete bridge is worth surveying in cycle-2 week 6.
5. **CFMM hooks as curvature programming.** Uniswap V4 hooks (active since early 2025) make AMM curvature programmable per-pool. The natural gauge interpretation is that the bundle's structure group is now per-pool variable — the connection is no longer canonical. This is a major theoretical opening; the Angeris–Chitra–Diamandis 2023 (arXiv 2308.08066) canonical-trading-function result needs to be revisited under hook composition.

---

## 8. Conclusion

Cycle 2 returns to gauge theory with two structural deliverables: (a) the unified gauge–Ricci picture of §3, which makes Ilinski's continuous curvature computable via Ollivier–Ricci on the RIE-cleaned correlation graph, and (b) a five-phase Victoria integration plan that delivers four signal-grade scalar features (`gauge_int_omega`, `gauge_max_holonomy`, `gauge_triangle_excess`, `gauge_lambda_2`), one defensive gate (Gate #10), one project-specific Polymarket detector, and a research-grade GNN extension. The single load-bearing 2024–2025 result is the Mancino et al. *Bunny Hops* paper documenting cross-chain MEV as N-step holonomy at $465.8M/year scale; the single load-bearing theoretical result is the φ⁴ field-theory of S&P 500 returns identifying gauge symmetry breaking with the high-kurtosis pre-crash regime.

The architectural recommendation from cycle 1 — promote `omega/nodes/victoria/geometry/` to `omega/core/geometry/` — is reinforced by cycle 2. The `gauge_bundle.py` module of §4.1 is project-agnostic by construction and is the most natural anchor for the future platform-level geometry module.

---

## Sources

- [Mancino, Sevim, Saguillo Gonzalez. *Bunny Hops and Blockchain Stops: Cross-Chain MEV Detection With N-Hops.* arXiv:2511.17527 (IEEE BRAINS 2025).](https://arxiv.org/abs/2511.17527)
- [Suarez-Tangil et al. *Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets.* arXiv:2508.03474 (AFT 2025).](https://arxiv.org/abs/2508.03474)
- [Intrinsic Geometry of the Stock Market from Graph Ricci Flow. arXiv:2510.15942 (Oct 2025).](https://arxiv.org/html/2510.15942)
- [Yang et al. *Efficient Triangular Arbitrage Detection via Graph Neural Networks.* arXiv:2502.03194 (Feb 2025).](https://arxiv.org/abs/2502.03194)
- [Modelling financial time series with φ⁴ quantum field theory. arXiv:2512.17225 (Dec 2025).](https://arxiv.org/abs/2512.17225)
- [Cross-Chain Arbitrage: The Next Frontier of MEV in Decentralized Finance. arXiv:2501.17335 (2025), ACM POMACS.](https://dl.acm.org/doi/10.1145/3771566)
- [Gauge symmetries and the Higgs mechanism in Quantum Finance. arXiv:2306.03237.](https://arxiv.org/abs/2306.03237)
- [Farinelli & Takada. *Can You Hear the Shape of a Market? Geometric Arbitrage and Spectral Theory.* MDPI Axioms 10(4):242.](https://www.mdpi.com/2075-1680/10/4/242)
- [Farinelli. *Geometric Arbitrage Theory and Market Dynamics Reloaded.* arXiv:0910.1671.](https://arxiv.org/abs/0910.1671)
- [Farinelli & Takada (foundational two-paper synthesis). scientia.global feature.](https://www.scientia.global/dr-simone-farinelli-dr-hideyuki-takada-geometric-arbitrage-theory-a-new-conceptual-structure-in-financial-mathematics/)
- [Angeris, Chitra, Diamandis, Evans, Kulkarni. *The Geometry of Constant Function Market Makers.* arXiv:2308.08066.](https://arxiv.org/abs/2308.08066)
- [Angeris et al. *Optimal Routing for Constant Function Market Makers.* arXiv:2204.05238.](https://arxiv.org/abs/2204.05238)
- [GraphRicciCurvature Python library.](https://github.com/saibalmars/GraphRicciCurvature)
- [CCXT cryptocurrency exchange trading library.](https://github.com/ccxt/ccxt)
- [Drakkar Triangular Arbitrage open-source detector.](https://github.com/Drakkar-Software/Triangular-Arbitrage)
- [Hands-On Mathematical Optimization with AMPL: Cryptocurrency arbitrage search.](https://ampl.com/mo-book/notebooks/04/cryptocurrency-arbitrage.html)
- [Neural Arbitrage: Cross-Chain MEV in 2025.](https://www.neuralarb.com/2025/10/27/cross-chain-mev-arbitrage-opportunities-in-2025/)
- [Uniswap V4 hooks 2025 review (DWF Labs).](https://www.dwf-labs.com/research/457-what-s-new-in-uniswap-v4-three-key-changes-and-two-new-protocols)
- [Arbitrage Routing as Multi-Surface Liquidity Optimization (Medium / MEV-X).](https://medium.com/@MEV-X/arbitrage-routing-as-a-multi-surface-liquidity-optimization-20a0b74e64aa)
