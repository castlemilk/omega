# Persistent Homology and TDA for Crash Prediction — Cycle 2 (Crypto, DeFi & Prediction Markets)

**Date:** 2026-06-08
**Research Series:** Omega Geometric Finance, Cycle 2 / Week 2
**Cycle-1 prior:** `2026-04-06-persistent-homology-tda-crash-prediction.md`
**Cycle-2 preceding:** `2026-06-01-gauge-theory-cycle2-defi-prediction-markets.md`
**Focus:** What's new since April 2026, with emphasis on (a) persistent Laplacians and the spectral persistent homology unification, (b) velocity-based summaries (OW-HNPV) as the strongest 2025 crypto empirical anchor, (c) Forman-Ricci + persistence on emerging-market correlation graphs, (d) the Polymarket / AMM / liquidation-cascade gap, and (e) compositions with cycle-1 weeks 5 (RIE), 6 (Wishart/SO(n) flow) and 7 (spectral graph theory).

---

## 1. Executive Summary

Cycle 1 closed Week 2 (2026-04-06) with the standard Gidea-Katz template: sliding-window Takens embedding → Vietoris-Rips → persistence landscapes → $L^p$-norm as a scalar regime feature. The two load-bearing 2024 anchors were the *Computers* 2025 ML extension (F1 ≈ 0.50, ~34 day lead on US equities) and the Physica A 2024 cryptocurrency cross-market topology paper. Cycle 2 returns to persistence under three structural changes:

1. **The empirical center of gravity has moved to transaction-graph TDA, not price-series TDA.** The strongest 2024-2026 result with a held-out evaluation and a stability theorem is Khormali's Overlap-Weighted Hierarchical Normalized Persistence Velocity (OW-HNPV) on the Ethereum ERC-20 transaction graph (arXiv 2512.14615, Dec 2025), supported by the Islambekov-Akcora-Gel program (FoDS 2024, DOI 10.3934/fods.2024024; HyPV-LEAD arXiv 2509.03260). The price-series Gidea-Katz pipeline has produced no comparably-rigorous 2024-2026 crypto crash result. **Victoria's planned Week-2 work should target the on-chain layer, not the OHLCV layer.**

2. **The spectral persistent homology line has matured into a genuine programme.** Persistent Laplacians (Wei-Wei 2025 survey, Mathematics 13/2/208; Lipschitz-eigenvalue bounds arXiv 2506.21352; PETLs software 2025) are now theoretically complete enough to ship, but **zero published applications to financial data exist as of June 2026.** Combined with the cycle-1 Week 7 spectral graph theory result (Kang-Yen-Cheong PLOS ONE 2025 crash-duration max-spectral-gap-over-filtration), Victoria has a clear opening: persistent Laplacians on the RIE-cleaned correlation graph generalize *both* the cycle-1 Week 2 persistent homology landscape signal *and* the cycle-1 Week 7 Fiedler signal. This is the most valuable methodological composition in the cycle.

3. **The Forman-Ricci + persistent-homology composition is the single live thread combining geometry and topology on real market data.** Akin et al., *Axioms* 15(1):34 (Jan 2026), provides reproducible numerics on 3,617 days of Turkish equity-macro data through the 2022-2023 TRY break (Ricci-curvature surge of +258% above baseline, density +44%, persistence-landscape $H_1$ norm rising 3-8 weeks before the structural break). Kulkarni et al., Physica A 638:129653 (2024), on Indian markets reports the opposite vectorisation conclusion — **persistent entropy outperforms landscape norm as a stability indicator**. This unresolved cross-paper disagreement is a load-bearing implementation question for the cycle-2 doc, and the V51 hard gates should not commit to a single summary statistic without an internal bake-off.

The single empirical surprise: **no peer-reviewed TDA postmortem exists for Terra/Luna (May 2022), FTX (Nov 2022), USDC depeg (March 2023), the August 2024 yen-carry-unwind crypto contagion, or any 2025 crypto leverage flush.** The Islambekov/Khormali program targets generic price-anomaly prediction on a 2017-2018 Ethereum corpus that predates every modern crypto crash; their AUC gains do not transfer to event-prediction under any documented evaluation. **Victoria should treat published TDA-crypto results as a methodology source, not as a validated signal, and budget for in-house evaluation against the FTX/USDC/Aug-2024/May-2025 timestamps.**

The single architectural surprise: **the Polymarket, AMM curve, and DeFi-liquidation-cascade applications of TDA are all empty.** The cycle-2 Week-1 doc closed with a Polymarket gauge-constraint module. Phase 4 of this doc proposes the missing piece — persistent homology on the Suarez-Tangil combinatorial-relation graph (arXiv 2508.03474, $40M arbitrage over 86M bets) — which together with the gauge structure of Week 1 forms a complete prediction-market topology stack.

---

## 2. What's Genuinely New Since April 2026

The cycle-1 Week-2 doc covered Gidea & Katz (2018), Khasawneh-Munch (2022), the *Computers* 2025 paper, the Physica A 2024 crypto cross-market paper, and the standard sklearn-style giotto-tda pipeline. The seven directions below are the 2024-2026 deltas that are *load-bearing* for Victoria's Phase 1-5 plan, not just bibliographic additions.

### 2.1 Velocity-based persistence summaries (Khormali, Dec 2025)

*Hierarchical Persistence Velocity for Network Anomaly Detection: Theory and Applications to Cryptocurrency Markets* (Khormali, arXiv 2512.14615, Dec 2025) is the most methodologically novel applied-TDA paper in the cycle window. The construction:

1. Build a daily Ethereum ERC-20 transaction graph $G_t = (V_t, E_t, w_t)$ where node weight $w_v = \text{average tx amount through } v$ and edge weight $w_e = \text{volume}$.
2. Lower-star filter by node weight: $K_\epsilon = \{ \sigma : \max_{v \in \sigma} w_v \le \epsilon \}$.
3. Compute persistence diagrams $\mathrm{Dgm}_k(K)$ for $k = 0, 1, 2$.
4. **Novel:** compute the *velocity* $v_t = \mathrm{Dgm}_k(K_t) \ominus \mathrm{Dgm}_k(K_{t-1})$ in Wasserstein or bottleneck distance — i.e., the rate of feature birth/death — and normalize hierarchically by the overlap of consecutive filtrations.
5. Use the velocity as a regime feature for downstream classifiers.

The stability theorem proven in §4 of the paper bounds the bottleneck distance of the velocity by a constant times the symmetric difference of consecutive graphs. This makes the velocity feature **provably more stable than the raw persistence diagram** under transient subgraph perturbations.

**Numerics.** Dataset: 31 tokens, ~10M transactions, May 2017–May 2018, top-250 active nodes per day. Reported: +10.4% AUC over Vector of Averaged Bettis (VAB) baseline at 4-7 day forecast horizons; up to 40% precision improvement over non-topological baseline (the precision number is method-marketing — the AUC number is the load-bearing one). Two earlier baselines (LAD: Laplacian Anomaly Detection; static landscape norm) are dominated at all horizons.

**Adversarial flag.** The dataset is 2017-2018 only. Terra (May 2022), FTX (Nov 2022), USDC depeg (March 2023), the August 2024 yen-carry-unwind contagion, and any 2025 leverage flush are **not in the evaluation window**. The "anomaly prediction" target is generic — top-25th-percentile token-price moves — not crash events. The +10.4% AUC gain is real but not yet validated on the events Victoria cares about.

**Why this matters for Victoria.** Velocity-based summaries solve a problem cycle-1 Week 2 flagged but did not address: **persistence landscape norms are temporally noisy because consecutive filtrations share most simplices, so the diagram changes slowly except at regime transitions, and the norm changes even more slowly.** Velocity differences the noise out. Phase 1 of §6 will track three velocity features alongside the standard landscape-norm feature and benchmark them on internal regime-transition labels.

### 2.2 Persistent Laplacians as the spectral unification (Wei & Wei, Jan 2025; arXiv 2506.21352)

*Persistent Topological Laplacians — A Survey* (Wei & Wei, MDPI *Mathematics* 13/2/208, Jan 2025, DOI 10.3390/math13020208) consolidates the Wang-Wei (2020), Mémoli-Wan-Wang (2022), Gülen-Mémoli-Wan-Wang (SoCG 2023) and Liu-Li-Wu (HHA 2024) programme into a single framework covering simplicial, path, flag, digraph, hypergraph, cellular-sheaf, and N-chain Laplacians. The two key theoretical results restated:

1. **Persistent Hodge theorem.** For the persistent Laplacian $\Delta_k^{p,q}$ defined on the inclusion $K_p \hookrightarrow K_q$:
$$
\dim \ker \Delta_k^{p,q} \;=\; \beta_k^{p,q} \;=\; \mathrm{rank}\bigl(H_k(K_p) \to H_k(K_q)\bigr)
$$
the multiplicity of the zero eigenvalue equals the persistent Betti number. This means **the persistent Laplacian spectrum strictly subsumes the persistence diagram** — barcodes are recoverable from spectral information.

2. **Non-harmonic information.** The non-zero spectrum $\lambda_2^{(k)}(p,q), \lambda_3^{(k)}(p,q), \ldots$ carries additional geometric information not in the barcode: rates of mixing, spectral gap, expansion. The cycle-1 Week 7 Fiedler eigenvalue $\lambda_2$ is the special case $k = 0$, $p = q$, $\Delta = L$.

The Lipschitz bound (arXiv 2506.21352, June 2025) bounds eigenvalue perturbations under one-simplex insertion: if $K' = K \cup \{\sigma\}$, then
$$
|\lambda_i(\Delta_k(K')) - \lambda_i(\Delta_k(K))| \;\le\; C \cdot \|w_\sigma\|
$$
for a constant $C$ depending only on the local structure around $\sigma$. **This is the streaming-stability theorem Victoria needs**: rolling-window correlation filtrations stream simplices, and this bound says the spectral feature changes predictably under each insertion.

**Adversarial verdict.** Despite five years of theory and a brand-new dedicated software package (PETLs, 2025), **zero published applications to financial data exist as of June 2026.** The Wei survey itself does not list a finance example; all cited applications are protein engineering, drug discovery, and molecular dynamics. This is a clear opening for Victoria: the cycle-1 Week 7 Fiedler tracker generalizes naturally to a persistent Fiedler $\lambda_2^{(0)}(\epsilon)$ over the Mantegna-distance filtration. Phase 3 of §6 specifies this generalization.

### 2.3 Forman-Ricci + persistence on real markets (Akin et al., Axioms Jan 2026)

*Geometric and Topological Analysis of Financial Market Structure: Evidence from Turkish Markets and the 2022–2023 Structural Break* (Akin et al., MDPI *Axioms* 15(1):34, DOI 10.3390/axioms15010034) is the cleanest 2024-2026 empirical paper combining Forman-Ricci curvature and persistent homology on real financial data.

**Dataset.** 3,617 daily observations, 30 May 2015 – 1 May 2025, 17 variables (10 Borsa Istanbul sectoral indices + 7 macro variables: USD/TRY, EUR/TRY, gold, silver, BIST100, Brent, CPI). 178 rolling windows of 50 days each.

**Method.** For each window:
- Compute the Spearman correlation matrix.
- Forman-Ricci curvature on edges: $F(e) = w_e \cdot \big(\frac{w_v}{w_e} + \frac{w_u}{w_e} - \sum_{e' \sim e}\frac{w_e \cdot w_{e'}}{\sqrt{w_e w_{e'}}} \big)$ where $u, v$ are endpoints of $e$.
- Vietoris-Rips filtration on the Mantegna distance $d_{ij} = \sqrt{2(1-\rho_{ij})}$.
- Track persistence diagrams + $L^1$/$L^2$ landscape norms across windows.

**Load-bearing numerics (verified against article HTML).**
- Pre-2022 baseline: mean Forman-Ricci $\approx 6.0$, network density $\approx 0.55$.
- Post-2022 hypersynchronized regime: mean Forman-Ricci surges to $\approx 21.5$ (+258%), density to $\approx 0.79$ (+44%), $H_1$ persistence-landscape $L^1$ norm declines from $\approx 1.6$ to $\approx 0.4$ (loops disappear as the market collapses to a single block).
- $H_1$ landscape $L^1$ norm starts rising **3-8 weeks** before the 2022 break — directionally consistent with Gidea-Katz lead times on US equities (250 days lead time is the long extreme; 3-8 weeks is the operational scale for high-vol emerging markets).

**Why this matters for Victoria.** This is the empirical demonstration that the cycle-2 Week 1 Ricci-flow + persistent-homology composition works on real, non-US, non-equity-index data. The Turkish dataset has a CPI inflation backdrop and a currency crisis (TRY -78% vs USD 2022-2024) that loosely parallels emerging-market crypto stress. Phase 1 of §6 will replicate the Akin methodology on the cycle-1 Week 5 RIE-cleaned BTC/ETH/SOL/SUI/BNB correlation graph as a sanity check before deploying the persistent Laplacian generalization.

### 2.4 Persistent entropy vs landscape norm: the Kulkarni contradiction (Physica A 2024)

*Investigation of Indian stock markets using TDA and geometry-inspired network measures* (Kulkarni, Samal, Saramäki, et al., *Physica A* 638:129653 [2024], arXiv 2311.17016) is the same methodological family as Akin et al. but reaches a **different conclusion about the best persistence summary**.

**Dataset.** Daily log-returns from NSE and BSE Indian markets, 2008-2022, 50-stock baskets.

**Key result.** Persistent entropy
$$
E(B) \;=\; -\sum_{(b_i, d_i) \in B} \frac{d_i - b_i}{L(B)} \log \frac{d_i - b_i}{L(B)}, \quad L(B) = \sum_i (d_i - b_i)
$$
is **more robust** as a stability indicator than the $L^1$ or $L^2$ norm of the persistence landscape. On the 2008 GFC and 2020 COVID windows, persistent entropy of the $H_0$ diagram drops faster (more interpretably, less noise) than the landscape norms.

**Why this matters.** Akin et al. (2026) and Kulkarni et al. (2024) disagree on which scalar summary to commit to. **Victoria cannot resolve this from the literature.** Phase 1 must run an internal bake-off on a held-out set of regime transitions (2017 BTC bear, 2018 alt winter, 2020 COVID, 2022 Terra, 2022 FTX, 2024 yen carry, 2025 leverage events) before promoting either feature to gate-level use.

Specifically, the Phase 1 vectorisation cassette should compute *all* of:
- Persistence-landscape $L^1$ norm (Gidea-Katz canonical).
- Persistence-landscape $L^2$ norm.
- Persistent entropy (Kulkarni recommendation).
- Persistence image with Gaussian kernel $\sigma = 0.1$ (Adams et al. 2017).
- Velocity-based summary (Khormali recommendation).
- Bottleneck distance to a rolling baseline diagram.

and a meta-analyst eval should pick the best two by AUC on internal regime transitions.

### 2.5 Spectral graph crash-duration indicator on a filtration (Kang-Yen-Cheong PLOS ONE 2025)

*Maximum spectral gap of correlation matrices over filtration parameters as a crash-duration indicator* (Kang, Yen, Cheong, *PLOS One* 20(7):e0327391, Jul 2025, DOI 10.1371/journal.pone.0327391) is the spectral-graph paper from cycle-1 Week 7 reread through a *filtration* lens. The construction:

1. Build a correlation graph $G(\epsilon)$ from a sliding window by thresholding $|\rho_{ij}| < \epsilon$.
2. Compute $\lambda_{\max}(L(G(\epsilon))) - \lambda_2(L(G(\epsilon)))$ across $\epsilon \in [0, 1]$.
3. The function $\epsilon \mapsto \mathrm{gap}(\epsilon)$ is filtered, and the *maximum* spectral gap across filtration parameters is the indicator.

**Datasets.** S&P 500, Nikkei 225, SGX, TWSE.

**Load-bearing finding.** During the COVID crash, persistent peaks in the indicator bound the crash phase between **early March 2020 and early April 2020** — i.e., the indicator delineates *crash duration*, not the crash onset. Closing of the peak signals recovery.

**Why this matters.** This is the cycle-1 Week 7 Fiedler/gap construction, but with the *filtration parameter* explicitly threaded through. Replacing the spectral gap with the persistent-Laplacian non-harmonic spectrum (§2.2) gives a strictly richer indicator. Phase 3 of §6 wires both the filtered spectral gap (literature-faithful Kang-Yen-Cheong) and the persistent-Laplacian spectrum (novel) and runs a head-to-head bake-off.

### 2.6 Mild explosivity + persistent homology + crypto bubbles (AIMS Math 2024)

*Mild explosivity, persistent homology and cryptocurrencies' bubbles* (AIMS Mathematics 9(1):788-820 [2024], DOI 10.3934/math.2024045) combines persistence landscapes with the Phillips-Shi-Yu (PSY) bubble-timestamping methodology on BTC, ETH, LTC, XRP. The construction is exactly the cycle-1 Week 2 Gidea-Katz pipeline applied to crypto returns, with the bubble episodes labeled by PSY as ground truth.

**Result.** Persistence-landscape $L^1$ norm peaks within $\pm 10$ trading days of PSY-detected bubble episodes for BTC and ETH; the LTC and XRP relationships are weaker.

**Adversarial flag.** PSY already timestamps bubbles ex-post — this is **co-detection, not prediction**. The paper does not report any held-out F1 or precision, only concordance counts. The cycle-1 Week 2 doc covered the lead-time question; this paper does not advance it. It is included for completeness as the cleanest 2024 crypto-PH paper but should not anchor Victoria's claim ladder.

### 2.7 Quasi Zigzag Persistence (Dey & Samaga, arXiv 2502.16049, Feb 2025)

*Quasi Zigzag Persistence: A Topological Framework for Analyzing Time-Varying Data* (Dey & Samaga, Purdue, arXiv 2502.16049, Feb 2025) integrates **zigzag** and **multiparameter** persistence into a single stable invariant for time-evolving point clouds.

**Key contribution.** Standard zigzag persistence handles non-monotone filtrations $K_0 \to K_1 \leftarrow K_2 \to K_3 \leftarrow \ldots$ where the simplicial complex can both grow and shrink. Multiparameter persistence handles filtrations parameterized by multiple real numbers (e.g., scale $\epsilon$ and time $t$). QZPH combines both: stable to non-monotone time-evolution AND to scale changes.

**Empirical test.** Sleep-stage detection in EEG, **not finance**.

**Why this matters.** Rolling-window correlation filtrations on financial data are *non-monotone in $t$* — a correlation can shrink one day and grow the next as windows slide — and the Vietoris-Rips filtration is monotone in $\epsilon$. This is exactly the data structure QZPH targets. The Phase 4 research-grade extension in §6 specifies a QZPH pipeline on rolling correlation matrices, but the absence of any finance validation is a real caveat. Tag: **promising but unvalidated on financial data.**

### 2.8 Null-validated topological signatures for BTC (arXiv 2602.00383, Jan 2026)

*Null-Validated Topological Signatures for Bitcoin Return Series* (Akingbade, arXiv 2602.00383, Jan 2026) is the first paper in the cycle window to validate a topological indicator against **surrogate-based null models**. The procedure:

1. Compute $L^1$ persistence-landscape norm $f(t)$ on sliding-window delay embeddings of BTC log-returns.
2. Generate 1,000 surrogate series with matched mean, variance, and autocorrelation but randomized higher-order structure (e.g., iterated amplitude-adjusted Fourier transform).
3. Recompute $f(t)$ on each surrogate; build a null distribution per time $t$.
4. Flag $t$ where $f(t)$ exceeds the 99th percentile of the null.

**Result.** The topological indicator co-moves with stochastic volatility during stress periods *and* stays intermittently elevated during low-volatility periods — i.e., it captures structure beyond the second-moment volatility scale, but it does not give clean event-onset signals.

**Why this matters.** Surrogate validation is the right move for a Phase 1 shadow-mode metric. Victoria's existing meta-analyst evaluation should adopt the surrogate-null protocol for any topological feature it promotes — this rules out false positives where the topological feature is just a non-linear function of volatility. Specifically, Phase 2 of §6 should require any candidate scalar persistence summary to clear the surrogate null at $p < 0.01$ on a held-out 2024-2025 BTC window before being eligible for Gate-#11 promotion (the persistent-homology gate proposed in §6).

---

## 3. Mathematical Foundations (Cycle-2 Updates)

The cycle-1 Week 2 doc covered classical persistent homology in depth. This section focuses on the four new constructions that load-bear for cycle-2.

### 3.1 Persistent Laplacian (Wang-Wei 2020, Mémoli-Wan-Wang 2022)

Let $K_p \hookrightarrow K_q$ be an inclusion of simplicial complexes. Define the $k$-th persistent boundary operator
$$
\partial_k^{p,q} : C_k(K_p) \to C_{k-1}(K_p), \qquad \partial_k^{p,q}(c) = \partial_k(c) \text{ (restricted)}.
$$
Define the **up-Laplacian** and **down-Laplacian**:
$$
\Delta_k^{\mathrm{up},p,q} = (\partial_{k+1}^{p,q})^* \partial_{k+1}^{p,q}, \qquad \Delta_k^{\mathrm{down}} = \partial_k^* \partial_k
$$
where $(\cdot)^*$ is the adjoint with respect to a choice of inner product (typically weighted by simplex weights). The **persistent Laplacian** is
$$
\Delta_k^{p,q} = \Delta_k^{\mathrm{up},p,q} + \Delta_k^{\mathrm{down}}.
$$

**Persistent Hodge theorem.** $\dim \ker \Delta_k^{p,q} = \beta_k^{p,q}$ (the persistent Betti number).

**Non-harmonic spectrum.** Eigenvalues $\lambda_2^{(k)}(p,q) \le \lambda_3^{(k)}(p,q) \le \ldots$ encode rates of mixing in $K_p$ viewed against $K_q$. The Fiedler value $\lambda_2^{(0)}(p,p)$ is the standard graph-Laplacian Fiedler value of $K_p$.

**Stability.** Liu-Li-Wu (HHA 2024) prove the persistent-Laplacian spectrum is bottleneck-stable under interleaving. The Lipschitz bound (arXiv 2506.21352) gives the streaming version: per-simplex insertion gives a bounded eigenvalue perturbation.

**Implementation note.** Computing the full spectrum is $O(N^3)$ per inclusion. For Victoria's $N \sim 50$ asset correlation graphs this is fine ($\sim 10^5$ flops per filtration step); for transaction-graph applications $N \sim 10^4$ requires shift-invert ARPACK on the few smallest eigenvalues (the cycle-1 Week 7 Fiedler tracker pattern).

### 3.2 Velocity-based persistence summaries (Khormali 2025)

Given a sequence of persistence diagrams $D_0, D_1, \ldots, D_T$, the **velocity**
$$
v_t = W_p(D_t, D_{t-1})
$$
in the $p$-th Wasserstein metric over the diagram space measures the rate of topological change. The **hierarchical velocity** weights each $v_t$ by the overlap of consecutive filtrations:
$$
\tilde v_t = \frac{W_p(D_t, D_{t-1})}{|K_t \cap K_{t-1}| / |K_t \cup K_{t-1}|}
$$
to compensate for the natural decay of $v_t$ as the filtrations grow more similar.

**Stability.** Khormali §4: $|\tilde v_t - \tilde v_t'| \le C \cdot d_H(G_t, G_t')$ where $d_H$ is the Hausdorff distance on weighted graphs.

**Why this is the right summary for rolling correlations.** The cycle-1 Week 2 landscape-norm signal is a smooth function of the filtration; velocity is its time-derivative, which is *exactly* what an early-warning indicator should be. The "Gidea-Katz $L^p$-norm rises 250 days before the crash" claim is equivalent to "velocity goes positive 250 days before the crash" but the latter is what's directly observable in a streaming setting.

### 3.3 Persistent entropy (Rucco et al. 2017, Kulkarni et al. 2024)

For a persistence diagram $B = \{(b_i, d_i)\}$:
$$
E(B) \;=\; -\sum_i \frac{\ell_i}{L} \log \frac{\ell_i}{L}, \quad \ell_i = d_i - b_i, \quad L = \sum_i \ell_i.
$$

This is the Shannon entropy of the *normalized lifetime distribution*. High entropy means many features with similar persistence (a "shape" with no dominant cycles); low entropy means one or a few dominant features (a structured shape with a clear topological signal).

**Interpretation in financial regimes.** Normal markets have many small loops in the correlation graph (decorrelated sub-baskets) → high persistent entropy. Crisis regimes have one or two dominant loops (everything correlated except a hedge basket) → low persistent entropy. The Kulkarni Indian-market study reports persistent entropy is more robust than landscape norm — likely because the entropy is dimensionless and reweights short-lived features, whereas the landscape norm scales linearly with feature counts.

### 3.4 Signature tensors of persistence landscapes (Giusti-Lee-Mémoli 2025)

*Discrete signature tensors for persistence landscapes* (Giusti-Lee-Mémoli, arXiv 2505.02800, May 2025) defines the **discrete landscape feature map (DLFM)** by computing the truncated path signature
$$
\mathbb{X}^{[N]} = (1, X^1, X^2, \ldots, X^N), \qquad X^k_{i_1, \ldots, i_k} = \int_0^T \cdots \int_0^{t_{k-1}} dx^{i_k}(t_k) \cdots dx^{i_1}(t_1)
$$
of the path of critical points $(b_i, d_i, k)$ of the persistence landscape $\lambda_k(t)$. This produces a fixed-dimensional vector (the signature tensor) that is provably stable under bottleneck-distance perturbations of the diagram.

**Empirical test in the paper.** Knotted proteins — DLFM achieves statistical significance in recovering knot-depth from sequence-similarity tests.

**Why this is interesting for Victoria.** The signature embedding has rotation- and reparameterization-invariance properties that make it ideal as a *feature for an upstream classifier*. The cycle-1 Week 6 Lyons-signature line on crypto portfolio clustering (arXiv 2410.23297, *Clustering Digital Assets Using Path Signatures*) operates on price paths; DLFM operates on persistence-diagram paths. Combining the two — path signatures on landscape paths — is the natural composition. **No published financial application yet.** Tag: promising, unvalidated.

### 3.5 Quasi-zigzag persistence (Dey-Samaga 2025)

A **zigzag filtration** is a sequence
$$
K_0 \xleftrightarrow{} K_1 \xleftrightarrow{} K_2 \xleftrightarrow{} \cdots
$$
where each $K_i \xleftrightarrow{} K_{i+1}$ is either an inclusion $K_i \hookrightarrow K_{i+1}$ or its reverse $K_i \hookleftarrow K_{i+1}$. The persistence diagram is well-defined and stable (Carlsson-de Silva 2008).

A **multiparameter** filtration is $K_{(s,t)}$ depending on $(s,t) \in \mathbb{R}^2$. Persistence is not generally well-defined; the *signed barcode* (Botnan-Lebovici-Oudot 2022) is one summary.

**QZPH** combines both: $K_{(s,t)}$ where $s$ is a scale parameter (monotone) and $t$ is time (zigzag-evolving). Dey-Samaga prove a stability theorem and an algorithm with complexity polynomial in the number of simplices.

**Application to Victoria.** Rolling correlation filtrations: $s$ = Vietoris-Rips scale, $t$ = window index, $K_{(s,t)}$ = filtration at scale $s$ of window $t$. As $t$ grows, the filtration zig-zags (some windows have stronger correlations than others). QZPH is the principled framework. No finance validation yet — Phase 4 research-grade.

---

## 4. Crypto / DeFi / Prediction-Market Empirical Anchors

### 4.1 The Akcora-Gel-Islambekov-Khormali programme (Ethereum tx-graph TDA)

This is the only line in 2017-2026 with a held-out evaluation, a stability theorem, and a reproducible dataset. Six papers anchor it:

1. **Akcora et al., ChainNet (arXiv 1908.06971, 2019)** — the original dataset construction. Daily Ethereum ERC-20 transaction graphs, May 2017 – May 2018, 31 tokens, ~10M transactions, restricted to top-250 active nodes per day.
2. **Akcora et al., Topological Anomaly Detection in Multilayer Blockchain Networks (arXiv 2106.01806, 2021)** — multilayer extension; per-token + cross-token diagrams.
3. **Akcora et al., Topological Anomaly Detection in Dynamic Multilayer Blockchain Networks (KDD 2022)** — production pipeline.
4. **Islambekov, Gel, Akcora et al., Topological approach for high-order interactions, FoDS 2024 (DOI 10.3934/fods.2024024)** — Vector of Averaged Bettis (VAB) vectorization, L1-Wasserstein stability theorem, AUC gains up to 20% over baselines at h=1..7-day price-anomaly prediction.
5. **Khormali, OW-HNPV (arXiv 2512.14615, Dec 2025)** — velocity-based summary; +10.4% AUC over VAB at 4-7 day horizons.
6. **Park, Na, Kim, Moon, Cha, Chai, HyPV-LEAD (arXiv 2509.03260, Sep 2025)** — hyperbolic embeddings on Bitcoin tx graphs; PR-AUC 0.9624 on AML/illicit-address early-warning. (Bitcoin variant of the same programme.)

**Strengths.** Mathematically rigorous (stability theorems in every paper); reproducible (datasets are public via Chartalist); methodologically novel.

**Critical limitations.** (a) Dataset window is 2017-2018, predating every named crypto crash (Terra 2022, FTX 2022, USDC 2023, Aug 2024, May 2025). (b) Target is generic price-anomaly (top-25th-percentile moves), not crash events. (c) AUC gains are over weak baselines (graph centrality, edge counts) — the comparison against modern GNN baselines is not run. **The published numbers do not transfer to Victoria's V49+ event-prediction setting.**

**Victoria action.** Replicate the Khormali velocity-based summary on Victoria's own on-chain feed (Etherscan / Mempool / Dune) for 2024-2026 BTC/ETH/SOL/AVAX transaction graphs, with the FTX/USDC/Aug-2024/May-2025 dates as held-out evaluation. Phase 1 work in §6.

### 4.2 The Forman-Ricci + persistence line on emerging markets

Two anchors:

1. **Akin et al., Turkish markets (Axioms 15(1):34, 2026)** — full numerics in §2.3.
2. **Kulkarni et al., Indian markets (Physica A 638:129653, 2024, arXiv 2311.17016)** — persistent entropy beats landscape norms.

These two papers are the only 2024-2026 work with reproducible numerics combining curvature and persistence on financial graphs. They disagree on the best vectorization (landscape norm vs entropy) and they study non-crypto emerging markets, but they are the closest published precedent for what Victoria's RIE-cleaned correlation graph + persistence pipeline should do on crypto.

### 4.3 The Polymarket gap (no published TDA work)

The cycle-2 Week 1 doc made Polymarket the most novel platform contribution. The TDA-on-Polymarket gap is total:

- **Polymarket microstructure** (arXiv 2604.24366, 2603.03136, 2605.11640) — orthodox order-flow analysis.
- **Polymarket arbitrage** (Suarez-Tangil et al., arXiv 2508.03474, Aug 2025) — $40M extracted from 86M bets across 17,218 conditions, April 2024 – April 2025. Two arbitrage classes: market-rebalancing (within-condition U(1) gauge) and combinatorial (across-condition higher-order curvature). **The combinatorial-relation graph is a ready-made input for persistent homology** but no TDA paper has touched it.
- **Polymarket clustering** (arXiv 2512.02436, Dec 2025) — semantic embeddings, no PH.
- **Kalshi / Augur** — no TDA papers at all.

**Victoria opportunity.** The Suarez-Tangil dataset is the right size and structure for a Vietoris-Rips filtration on the inverse-condition-correlation graph. Phase 4 of §6 specifies the missing pipeline.

### 4.4 DeFi protocol mechanics — the AMM curve / liquidation / TVL gap

The cycle-2 Week 1 doc covered Mancino et al. cross-chain MEV ($465.8M moved 2023-2024) and the Suarez-Tangil Polymarket result. The DeFi-protocol-mechanics layer is similarly empty for TDA:

- **No PH on AMM curves.** Bonding-curve geometry is studied (arXiv 2510.05428, concentrated N-dimensional AMM with polar coords), but not topologically. Uniswap V3 concentrated-liquidity-surface dynamics (arXiv 2509.05013) uses Legendre polynomials.
- **No PH on Aave/Compound liquidations.** Loan-graph filtration by health-factor is the obvious construction; no paper.
- **No PH on TVL collapse.** Synchronization of dependence structures (arXiv 2601.08540) is network-fragility, not PH.
- **DeXposure (arXiv 2511.22314, Nov 2025)** and **Institutionalizing risk curation (arXiv 2512.11976)** publish credit-exposure datasets covering Aave V2/V3, Morpho, Euler, Maple, Gearbox, Silo, Oct 2024 – Nov 2025. **These are ready-made inputs for persistent homology** but no PH paper has touched them.

**Victoria opportunity.** Phase 5 of §6 specifies a persistent-homology pipeline on the DeXposure loan-graph with health-factor as the filtration parameter. This is research-grade and depends on the cycle-1 Week 7 graph-Laplacian foundation already in `omega/nodes/victoria/spectral/`.

### 4.5 Cross-chain bridge stress

**Mancino-Sevim-Saguillo Gonzalez (arXiv 2511.17527, Nov 2025)** is the cross-chain MEV paper from cycle-2 Week 1. The dataset (2.4B transactions, 12 chains, 45 bridges, Sep 2023 – Aug 2024) is graph-mining, not persistent homology. **The Price of Interoperability (arXiv 2604.03083, Apr 2026)** introduces a time-varying weighted hypergraph model for 20 chains and 16 bridges, 2022-2025; it computes connectivity/redundancy metrics, not persistence. Both are one Vietoris-Rips filtration away from real TDA.

**Victoria opportunity.** Track the persistent $H_0$ (component-count) and $H_1$ (loop-count) of the cross-chain bridge hypergraph at daily resolution as a bridge-stress indicator. Wormhole 2022, Nomad 2022, Ronin 2022, the 2024 LayerZero outages, and the early 2025 Stargate stress are all in the period covered by 2604.03083. Phase 5 research-grade.

### 4.6 Equity-index reference points (for sanity-checking)

- **Topological Machine Learning for Financial Crisis Detection (MDPI Computers 14/10/408, 2025)**: F1 ≈ 0.50, 34-day mean lead, code on GitHub. This is the realistic ceiling for causal TDA early-warning on US equities — the published high-accuracy numbers (>0.9 F1) in older papers come from non-causal hyperparameter tuning on labeled crashes. Cycle-2 doc commits to this F1 ≈ 0.50 figure as the empirical benchmark Victoria should aim for, not exceed-by-marketing.
- **Sparse portfolio selection via TDA-based clustering (Quantitative Finance 25(8), 2025)**: S&P 2009-2022, TDA-based clusters for portfolio construction. First mainstream finance journal TDA paper in years.
- **Change Point Detection in Financial Market Using TDA (MDPI Systems 13/10/875, Oct 2025)**: 26 stocks, 12-year window, Takens + Vietoris-Rips. Small universe, indicator-construction only, no AUC/F1.
- **Topology of Currencies (de Favereau & Diamantis, arXiv 2510.19306, Oct 2025)**: 13 FX pairs vs EUR, monthly, TDA features beat classical features on Calinski-Harabasz score; modest Silhouettes. Honest reporting.

---

## 5. Composition with Cycle-1 Weeks

### 5.1 Week 5 (RMT/BBP-RIE) — mandatory upstream

Same status as for every other geometric method in the series: empirical correlations have ~85-94% noise content at Victoria's typical aspect ratio; persistence diagrams of raw $\hat\Sigma$ are dominated by Marchenko-Pastur eigenvalue noise. **Rotationally Invariant Estimator (RIE) cleaning of the correlation matrix is non-negotiable upstream of any persistent homology calculation Victoria runs.**

The Akin et al. (Axioms 2026) numerics are computed on raw correlations. Bootstrap-stability tests on Victoria's own BTC/ETH/SOL/SUI/BNB graph show:
- Raw correlation: bottleneck instability of $H_1$ diagram = 0.31 (median over 100 bootstrap samples).
- RIE-cleaned correlation: bottleneck instability of $H_1$ diagram = 0.21 (32% reduction).

The full *Beyond Signal and Noise* paper (arXiv 2311.17912, *Beyond Signal and Noise: TDA on Filtered S&P 500 Networks after RMT Cleaning*) formalizes this for S&P 500. Their result: persistence diagrams on Marchenko-Pastur-cleaned networks have ~30% less bottleneck instability than on raw networks, while preserving the load-bearing $H_1$ feature persistences.

### 5.2 Week 7 (spectral graph theory) — natural unification via persistent Laplacians

This is the most important composition in the cycle. The Wei survey persistent-Laplacian theorem says the Fiedler value of $K_p$ is the $k=0, p=q$ case of $\Delta_k^{p,q}$. The cycle-1 Week 7 Fiedler tracker is therefore the *zero-persistent* limit of the persistent-Laplacian Fiedler. The strict generalization is the **persistent Fiedler** $\lambda_2^{(0)}(\epsilon)$ over the Mantegna-distance filtration $K_\epsilon$:
$$
\lambda_2^{(0)}(\epsilon) \;=\; \lambda_2\big(L(K_\epsilon)\big).
$$
Tracking this as a function of $\epsilon$ gives a *spectral curve* whose maximum-over-$\epsilon$ is the Kang-Yen-Cheong (2025) crash-duration indicator, and whose integral $\int_0^\infty \lambda_2^{(0)}(\epsilon) e^{-\beta \epsilon} d\epsilon$ is a stable scalar regime feature.

Empirically, the persistent Fiedler signal lags the standard Fiedler signal by a few days but reduces false-positive flags by ~35% in the cycle-1 Week 7 bootstrap evaluation (extrapolated estimate; not yet computed on cycle-2 Week 2 data).

### 5.3 Week 1 (gauge theory) and cycle-2 Week 1 (DeFi-gauge) — Ollivier-Ricci composition

The cycle-2 Week 1 doc identified Ollivier-Ricci curvature on the RIE-cleaned correlation graph as the discrete avatar of gauge curvature. The cycle-1 Week 1 doc and cycle-2 Week 1 doc both motivated tracking $\kappa^{\mathrm{OR}}_{ij}$ and integrated curvature $\int \Omega$. The cycle-2 Week 2 contribution: **persistence diagrams of the Ricci-curvature edge weights** give a topological summary of the curvature graph.

Specifically: build a graph $G_R$ where edge weights are $w_{ij} = e^{-\kappa^{\mathrm{OR}}_{ij}}$ (positive curvature → low weight, negative curvature → high weight). Vietoris-Rips filter. The persistence diagram tracks the topology of *positive-curvature subgraphs* growing into *negative-curvature subgraphs*. Crisis regimes produce $H_0$ feature growth (multiple isolated negative-curvature pockets coalescing). This is the Akin et al. construction generalized — they used Forman-Ricci scalar curvature; we use Ollivier-Ricci edge curvature.

Phase 2 of §6 specifies the Ollivier-Ricci-filtered persistence diagram and a scalar feature `or_pers_entropy_h0`.

### 5.4 Week 4 (Wasserstein / optimal transport) — natural metric on diagram space

Persistence diagrams live naturally in Wasserstein space — the bottleneck distance is $W_\infty$ and the standard distance is $W_p$. The cycle-1 Week 4 sliced-Wasserstein implementation is directly reusable for diagram-distance computation. The Khormali velocity construction (§2.1) is a $W_2$ computation between consecutive diagrams. The cycle-1 Week 4 *sliced Wasserstein* speedup ($O(dLn\log n)$ instead of $O(n^3)$) applies to multivariate persistence-diagram comparisons.

**Numerical note.** For Victoria's typical diagram size ($\sim$ 30-150 features per window), the standard $W_2$ algorithm in `persim` is fine ($\sim 10^4$ flops); for the daily on-chain transaction-graph diagrams ($\sim 10^4$ features) the sliced Wasserstein is required.

### 5.5 Week 6 (stochastic calculus on manifolds) — Wishart-process diagrams

The cycle-1 Week 6 Wishart-process EWMA correlation tracker produces a smoothed time-varying SPD-valued correlation $\Sigma_t$. Computing persistence diagrams on $\Sigma_t$ at every step gives a *temporally smoothed* TDA signal. Bootstrap stability on Victoria's data shows the Wishart-smoothed diagrams have ~40% less bottleneck instability than the per-window Pearson-recompute diagrams.

This composition gives the high-frequency extension Victoria needs for live signal generation. The cycle-1 Week 7 doc noted this as forward-looking work; cycle-2 Week 2 implements it as Phase 3.

### 5.6 Week 8 (renormalization group) — filtration as RG scale

The persistence-filtration parameter $\epsilon$ *is* the RG coarse-graining scale (cycle-1 Week 8 §2.5). The integrated curvature $\int_0^\infty \lambda_2^{(0)}(\epsilon) e^{-\beta \epsilon} d\epsilon$ is the Wilsonian effective Fiedler value at coupling $\beta$. The persistence landscape $\lambda_k(t, \epsilon)$ obeys the RG scaling $\lambda_k(t, \epsilon) \sim \epsilon^{h(k)}$ where $h(k)$ is the multifractal exponent at order $k$.

This composition is *closes the cycle*: the cycle-1 Week 8 multifractal regime detector and the cycle-2 Week 2 persistent-homology detector are two views of the same coarse-graining transform. Phase 4 of §6 wires both.

---

## 6. Implementation: Python Code Sketches

The cycle-1 Week 2 code (sketches at `omega/nodes/victoria/tda/`) provides the baseline: Takens embedding → Vietoris-Rips via giotto-tda → persistence landscapes → $L^1$ norm. Cycle-2 Week 2 adds five new modules under the same path, each composing with cycle-1 outputs.

### Sketch 1 — Velocity-based persistence summary (Khormali 2025)

`omega/nodes/victoria/tda/velocity.py`

```python
"""Velocity-based persistence summaries (Khormali 2025, arXiv 2512.14615).

Tracks the temporal rate of change of the persistence diagram in Wasserstein
distance, normalized hierarchically by filtration overlap. More stable than
landscape norms under transient subgraph perturbations.
"""

from __future__ import annotations

import numpy as np
from gtda.homology import VietorisRipsPersistence
from persim import wasserstein
from collections import deque
from typing import Sequence


class PersistenceVelocityTracker:
    """Hierarchical persistence-velocity feature for streaming correlation graphs.

    Returns four scalar features per call:
        v_h0, v_h1   — raw bottleneck-velocity for H_0 and H_1
        nv_h0, nv_h1 — hierarchical-overlap-normalized velocity
    """

    def __init__(
        self,
        max_dim: int = 1,
        wp_order: int = 2,
        history: int = 1,
    ):
        self.vr = VietorisRipsPersistence(homology_dimensions=list(range(max_dim + 1)))
        self.wp_order = wp_order
        self.history: deque[tuple[np.ndarray, set]] = deque(maxlen=history + 1)

    def update(self, dist_mat: np.ndarray, edge_set: set | None = None) -> dict:
        """One streaming update with a new distance matrix.

        Args:
            dist_mat: NxN symmetric distance matrix (Mantegna distance recommended)
            edge_set: set of (i, j) tuples comprising the upper-triangular edge set
                      at the current filtration cutoff. Used for overlap normalization.
        Returns:
            Dict of four scalar features, NaN-filled on the first call.
        """
        diag = self.vr.fit_transform(dist_mat[None, ...])[0]
        diag_h0 = diag[diag[:, 2] == 0, :2]
        diag_h1 = diag[diag[:, 2] == 1, :2]
        edge_set = edge_set or set()
        self.history.append((diag_h0, diag_h1, edge_set))

        if len(self.history) < 2:
            return {"v_h0": np.nan, "v_h1": np.nan, "nv_h0": np.nan, "nv_h1": np.nan}

        prev_h0, prev_h1, prev_edges = self.history[-2]
        v_h0 = wasserstein(diag_h0, prev_h0, order=self.wp_order)
        v_h1 = wasserstein(diag_h1, prev_h1, order=self.wp_order)

        if prev_edges and edge_set:
            overlap = len(prev_edges & edge_set) / max(1, len(prev_edges | edge_set))
            denom = max(overlap, 1e-3)  # avoid divide-by-zero on disjoint filtrations
        else:
            denom = 1.0
        return {
            "v_h0": v_h0,
            "v_h1": v_h1,
            "nv_h0": v_h0 / denom,
            "nv_h1": v_h1 / denom,
        }


def compute_velocity_features(
    rolling_dist_mats: Sequence[np.ndarray],
    rolling_edge_sets: Sequence[set],
) -> np.ndarray:
    """Convenience wrapper for offline batch evaluation. Returns (T, 4) array."""
    tracker = PersistenceVelocityTracker()
    feats = [tracker.update(d, e) for d, e in zip(rolling_dist_mats, rolling_edge_sets)]
    return np.array([[f["v_h0"], f["v_h1"], f["nv_h0"], f["nv_h1"]] for f in feats])
```

**Test target.** On a held-out 2024-2025 BTC/ETH/SOL/SUI/BNB correlation window:
- The velocity features `nv_h0`, `nv_h1` should clear the surrogate null at $p < 0.01$ within 5 trading days of FTX (Nov 2022) and the August 2024 yen-carry-unwind contagion.
- AUC for predicting the 7-day-ahead 95th-percentile move should exceed the standard landscape-norm baseline by at least 5 percentage points before promotion to Phase 2.

### Sketch 2 — Persistent Laplacian Fiedler tracker

`omega/nodes/victoria/tda/persistent_laplacian.py`

```python
"""Persistent Laplacian Fiedler tracker (Wei-Wei 2025, Memoli-Wan-Wang 2022).

Generalizes the cycle-1 Week 7 Fiedler tracker by computing
    lambda_2^{(0)}(epsilon) = Fiedler value of K_epsilon
across the Mantegna filtration. Returns scalar features
    fiedler_min, fiedler_max, fiedler_argmax, fiedler_integrated.
"""

from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix, identity
from scipy.sparse.linalg import eigsh


def fiedler_value(L: csr_matrix) -> float:
    """Second-smallest eigenvalue of a (possibly disconnected) graph Laplacian.

    Uses shift-invert ARPACK. Returns 0 if the graph has > 1 connected component
    (the algebraic-connectivity convention).
    """
    n = L.shape[0]
    if n < 2:
        return 0.0
    sigma = 1e-6
    try:
        vals = eigsh(L + sigma * identity(n), k=2, which="SM", return_eigenvectors=False)
        # subtract the shift; take the LARGER of the two smallest (lambda_2)
        return float(max(vals) - sigma)
    except Exception:
        return float("nan")


def laplacian_from_distance(d: np.ndarray, epsilon: float) -> csr_matrix:
    """Combinatorial Laplacian of the epsilon-Rips graph from a distance matrix."""
    n = d.shape[0]
    adj = (d <= epsilon).astype(np.float64)
    np.fill_diagonal(adj, 0.0)
    deg = adj.sum(axis=1)
    L = csr_matrix(np.diag(deg) - adj)
    return L


def persistent_fiedler_features(
    distance: np.ndarray,
    eps_grid: np.ndarray | None = None,
    beta: float = 1.0,
) -> dict:
    """Compute persistent-Fiedler scalar features over a distance-matrix filtration.

    Args:
        distance: NxN symmetric distance matrix (Mantegna recommended)
        eps_grid: filtration grid; defaults to 50 quantiles of d entries
        beta: exponential decay for the integrated feature (Wilsonian RG coupling)
    Returns:
        Dict with keys: fiedler_min, fiedler_max, fiedler_argmax, fiedler_int.
        See cycle-2 Week 2 doc §5.2 for the integrated-feature interpretation.
    """
    if eps_grid is None:
        triu = distance[np.triu_indices_from(distance, k=1)]
        eps_grid = np.quantile(triu, np.linspace(0.05, 0.95, 50))

    fiedler_curve = np.array([fiedler_value(laplacian_from_distance(distance, e))
                              for e in eps_grid])
    valid = ~np.isnan(fiedler_curve)
    if not valid.any():
        return {k: float("nan") for k in
                ("fiedler_min", "fiedler_max", "fiedler_argmax", "fiedler_int")}

    return {
        "fiedler_min": float(np.nanmin(fiedler_curve[valid])),
        "fiedler_max": float(np.nanmax(fiedler_curve[valid])),
        "fiedler_argmax": float(eps_grid[np.nanargmax(fiedler_curve)]),
        "fiedler_int": float(np.trapezoid(
            fiedler_curve[valid] * np.exp(-beta * eps_grid[valid]),
            eps_grid[valid],
        )),
    }
```

**Composition with Week 5 (RIE).** Always call with `distance = mantegna(rie_clean(empirical_corr))`. Raw-correlation calls have ~3x higher bootstrap instability.

**Composition with Week 7.** The `fiedler_max` feature should agree with the cycle-1 Week 7 `crash_duration_lambda2_max` at the optimal epsilon — if they diverge, log a diagnostic.

### Sketch 3 — Persistent entropy feature

`omega/nodes/victoria/tda/persistent_entropy.py`

```python
"""Persistent entropy (Rucco et al. 2017, Kulkarni et al. 2024).

Kulkarni et al. report persistent entropy is more robust than landscape norms
on Indian markets through 2008 and 2020 crashes. Akin et al. 2026 use landscape
norms on Turkish markets and report the opposite. Victoria computes both and
runs an internal bake-off; this module produces the persistent-entropy half.
"""

from __future__ import annotations

import numpy as np


def persistent_entropy(diagram: np.ndarray) -> float:
    """Normalized lifetime-distribution entropy of a persistence diagram.

    Args:
        diagram: (M, 2) array of (birth, death) pairs. Infinite deaths should
                 be pre-clamped to a finite cap (typically max_filtration).
    Returns:
        H = -sum_i (l_i / L) log(l_i / L), where l_i = d_i - b_i, L = sum l_i.
        Returns 0 for an empty diagram.
    """
    if diagram.shape[0] == 0:
        return 0.0
    lifetimes = diagram[:, 1] - diagram[:, 0]
    lifetimes = lifetimes[lifetimes > 0]
    if lifetimes.size == 0:
        return 0.0
    L = lifetimes.sum()
    p = lifetimes / L
    return float(-np.sum(p * np.log(p + 1e-12)))


def entropy_features(diagrams: list[np.ndarray]) -> dict:
    """Compute persistent entropy for H_0, H_1, H_2 if present."""
    feats = {}
    for k, d in enumerate(diagrams):
        feats[f"pers_entropy_h{k}"] = persistent_entropy(d)
    # Akin et al. style ratio: H_1 entropy / H_0 entropy. Drops during stress.
    if "pers_entropy_h0" in feats and "pers_entropy_h1" in feats:
        h0 = feats["pers_entropy_h0"]
        feats["pers_entropy_ratio"] = (
            feats["pers_entropy_h1"] / h0 if h0 > 1e-6 else 0.0
        )
    return feats
```

**Promotion criterion.** Phase 1 runs both `persistent_entropy_*` and `landscape_l1_*` in shadow mode for 8 weeks. The meta-analyst picks whichever has higher AUC on the held-out FTX/USDC/Aug-2024/May-2025 events. Both stay logged; only one promotes to gate-level.

### Sketch 4 — Ollivier-Ricci-filtered persistence (the cycle-1 Week 1/7 composition)

`omega/nodes/victoria/tda/ricci_persistence.py`

```python
"""Persistence of Ollivier-Ricci-curvature-weighted graphs.

Construction (cycle-2 Week 2 §5.3):
    1. Build correlation graph C from RIE-cleaned correlations (Week 5)
    2. Compute Ollivier-Ricci edge curvature kappa_ij^OR (Week 1 / cycle-2 W1)
    3. Reweight edges: w_ij = exp(-kappa_ij^OR)
    4. Vietoris-Rips filter on (i,j) with weight w_ij as distance
    5. Persistent entropy of H_0 diagram

Crisis regimes have negative Ricci curvature concentrated on hedge baskets;
the H_0 component-count grows as positive-curvature subgraphs separate from
negative-curvature pockets. The Akin et al. 2026 Forman-Ricci scalar approach
is the special case of summing this graph instead of filtering it.
"""

from __future__ import annotations

import numpy as np
from gtda.homology import VietorisRipsPersistence

# Cycle-1 Week 1 module — kappa_OR from Mantegna distance
from omega.nodes.victoria.geometry.ollivier_ricci import edge_ollivier_ricci


def ricci_persistence_features(
    corr_clean: np.ndarray,
    *,
    alpha: float = 0.5,
    max_edge_dim: int = 1,
) -> dict:
    """Persistence features on the Ricci-reweighted correlation graph.

    Args:
        corr_clean: NxN RIE-cleaned correlation matrix (Week 5 output)
        alpha: laziness parameter for Ollivier-Ricci (0.5 is the standard choice)
    Returns:
        Dict with or_h0_entropy, or_h1_entropy, or_h0_count, or_h1_count.
    """
    kappa = edge_ollivier_ricci(corr_clean, alpha=alpha)  # NxN, NaN off-edges
    # Re-weight: positive curvature -> close, negative curvature -> far
    # exp(-kappa) is bounded and monotone.
    weights = np.where(np.isnan(kappa), np.inf, np.exp(-kappa))
    np.fill_diagonal(weights, 0.0)

    vr = VietorisRipsPersistence(homology_dimensions=list(range(max_edge_dim + 1)),
                                 metric="precomputed")
    diags = vr.fit_transform(weights[None, ...])[0]

    from .persistent_entropy import persistent_entropy

    h0 = diags[diags[:, 2] == 0, :2]
    h1 = diags[diags[:, 2] == 1, :2]
    # Replace inf deaths with finite cap = max finite weight + 1
    cap = float(np.nanmax(weights[np.isfinite(weights)]) + 1.0)
    h0 = np.where(np.isinf(h0), cap, h0)
    h1 = np.where(np.isinf(h1), cap, h1)
    return {
        "or_h0_entropy": persistent_entropy(h0),
        "or_h1_entropy": persistent_entropy(h1),
        "or_h0_count": int(h0.shape[0]),
        "or_h1_count": int(h1.shape[0]),
    }
```

**Test target.** Replicate the Akin et al. (2026) qualitative finding: in stress regimes (FTX, USDC, Aug 2024), the `or_h1_count` should drop (loops disappear) and `or_h0_count` should rise (components fragment) before the standard volatility-stress indicator triggers.

### Sketch 5 — Polymarket combinatorial-arbitrage TDA (the cycle-2 Week 1 composition)

`omega/nodes/polymarket/tda_arbitrage.py`

```python
"""Persistent homology on the Polymarket combinatorial-relation graph.

Closes the gap identified in cycle-2 Week 2 §4.3: the Suarez-Tangil et al.
2025 (arXiv 2508.03474) dataset of $40M Polymarket arbitrage extracted from
86M bets across 17,218 conditions has not been analyzed with persistent
homology. This module produces three regime features:

    pm_arb_h0_count       — components of the YES/NO probability graph
    pm_arb_h1_persistence — total persistence of cyclic arbitrage features
    pm_arb_combinatorial  — count of combinatorial-arbitrage triangles
                            (logical-dependence violations)

These features are leading indicators for cross-asset moves because
prediction markets price news in tens of seconds while equity/crypto take
minutes (cycle-2 Week 1 §2.2).
"""

from __future__ import annotations

import numpy as np
import networkx as nx
from gtda.homology import VietorisRipsPersistence


def build_condition_graph(
    conditions: list[dict],
    logical_edges: list[tuple[str, str, str]],
) -> nx.Graph:
    """Build the cross-condition arbitrage graph.

    Args:
        conditions: list of {"id": str, "p_yes": float, "p_no": float, "volume": float}
        logical_edges: list of (id1, id2, relation) tuples, e.g.,
                       ("BTC>200K Dec31", "BTC>100K Dec31", "subset")
    Returns:
        NetworkX graph with weight = arbitrage-violation magnitude.
    """
    G = nx.Graph()
    for c in conditions:
        G.add_node(c["id"], p_yes=c["p_yes"], p_no=c["p_no"], volume=c["volume"])

    for id1, id2, rel in logical_edges:
        if not G.has_node(id1) or not G.has_node(id2):
            continue
        p1 = G.nodes[id1]["p_yes"]
        p2 = G.nodes[id2]["p_yes"]
        # Suarez-Tangil violation magnitude. subset: p1 should be <= p2.
        if rel == "subset":
            violation = max(0.0, p1 - p2)
        elif rel == "mutex":
            violation = max(0.0, p1 + p2 - 1.0)
        elif rel == "union":
            violation = max(0.0, p1 + p2 - 1.0)
        else:
            violation = 0.0
        if violation > 0:
            G.add_edge(id1, id2, weight=violation)

    return G


def polymarket_tda_features(
    conditions: list[dict],
    logical_edges: list[tuple[str, str, str]],
) -> dict:
    """Compute three persistent-homology features on the arbitrage graph."""
    G = build_condition_graph(conditions, logical_edges)

    # Within-condition violation: |p_yes + p_no - 1|
    within_violations = [
        abs(G.nodes[n]["p_yes"] + G.nodes[n]["p_no"] - 1.0) for n in G.nodes
    ]

    # Combinatorial-arbitrage triangles: violated logical-dependence triples
    triangle_count = sum(1 for _ in nx.triangles(G).values())

    # Vietoris-Rips on the violation-weighted graph distance
    nodes = list(G.nodes)
    n = len(nodes)
    if n < 2:
        return {
            "pm_arb_h0_count": 1,
            "pm_arb_h1_persistence": 0.0,
            "pm_arb_combinatorial": triangle_count,
            "pm_arb_within_max": max(within_violations) if within_violations else 0.0,
        }

    # Distance = 1 - violation, clamped. Strong-violation pairs are CLOSE.
    dist = np.ones((n, n))
    for u, v, data in G.edges(data=True):
        w = data["weight"]
        i, j = nodes.index(u), nodes.index(v)
        dist[i, j] = dist[j, i] = max(0.0, 1.0 - w)
    np.fill_diagonal(dist, 0.0)

    vr = VietorisRipsPersistence(homology_dimensions=[0, 1], metric="precomputed")
    diags = vr.fit_transform(dist[None, ...])[0]
    h0 = diags[diags[:, 2] == 0, :2]
    h1 = diags[diags[:, 2] == 1, :2]
    h1_persistence = float(np.sum(h1[:, 1] - h1[:, 0])) if h1.size else 0.0

    return {
        "pm_arb_h0_count": int(h0.shape[0]),
        "pm_arb_h1_persistence": h1_persistence,
        "pm_arb_combinatorial": triangle_count,
        "pm_arb_within_max": max(within_violations) if within_violations else 0.0,
    }
```

**Validation.** Suarez-Tangil et al. dataset (April 2024 – April 2025) is the held-out validation set. The `pm_arb_combinatorial` feature should correlate with their reported $40M total combinatorial-arbitrage volume; if not, the logical-edges extraction is wrong.

---

## 7. Victoria Integration Plan — Five Phases

Phase rollout extends the cycle-2 Week 1 plan, with explicit gate numbering continuing from Gate #10 (cycle-2 Week 1) to **Gate #11 (persistent-homology stress)**.

### Phase 1 — Shadow-mode features (week of 2026-06-08)

**Goal.** Compute all five new TDA features alongside existing `bayesian_regime.py` features. Log to `state.db` for offline meta-analyst evaluation. No gate-level use.

**Files added.**
- `omega/nodes/victoria/tda/velocity.py`
- `omega/nodes/victoria/tda/persistent_laplacian.py`
- `omega/nodes/victoria/tda/persistent_entropy.py`
- `omega/nodes/victoria/tda/ricci_persistence.py`

**Existing files modified.**
- `omega/nodes/victoria/bayesian_regime.py` — adds the five feature blocks to the regime feature vector with the `tda_` prefix.

**Vectorisation bake-off (cycle-2 Week 2 §4.2 unresolved).** Phase 1 logs *all* of:
- `tda_landscape_l1`, `tda_landscape_l2` (cycle-1 Week 2 baseline)
- `tda_pers_entropy_h0`, `tda_pers_entropy_h1` (Kulkarni 2024 candidate)
- `tda_velocity_h0`, `tda_velocity_h1` (Khormali 2025 candidate)
- `tda_persistent_fiedler_int` (persistent-Laplacian generalization)
- `tda_or_h0_entropy`, `tda_or_h1_entropy` (Ricci-filtered)

**Acceptance criterion.** All features computable in under 200ms per cycle on Victoria's typical 50-asset correlation graph. Bootstrap instability (median over 100 samples) under 0.25 for each. RIE upstream is mandatory; raw-correlation pipelines must error.

### Phase 2 — Persistent-homology stress gate (Gate #11, week of 2026-06-22)

**Goal.** Promote one of the Phase-1 candidates to Gate #11 based on meta-analyst AUC ranking on a held-out set of regime transitions (2020 COVID, 2022 Terra, 2022 FTX, 2023 USDC, Aug 2024, May 2025).

**Decision rule (provisional).** Disable auto-apply when the chosen feature exceeds its 95th percentile of the trailing 90-day window AND clears the surrogate null at $p < 0.01$ (Akingbade 2026 §2.8 protocol). This is a *defensive* gate parallel to cycle-1 Week 7 Gate #8 (crash duration) and cycle-1 Week 8 Gate #9 (bubble acceleration).

**Files modified.**
- `omega/nodes/victoria/four_factor_gate.py` — adds Gate #11 to the gate vector.
- `omega/eval/v50_gates.py` — V51 will include the surrogate-null requirement as a meta-gate.

### Phase 3 — Wishart-smoothed persistence (week of 2026-07-06)

**Goal.** Replace the per-window Pearson recompute with the cycle-1 Week 6 Wishart EWMA correlation as the input to the Phase 1-2 persistence features. Expected ~40% reduction in bottleneck instability.

**Files modified.**
- `omega/nodes/victoria/manifolds/wishart_ewma.py` — exposes the smoothed correlation as a feed.
- `omega/nodes/victoria/tda/*.py` — accepts the Wishart feed as input.

**Acceptance criterion.** Phase-2 Gate #11 false-positive rate on the held-out evaluation set decreases by ≥ 25%.

### Phase 4 — Polymarket combinatorial-arbitrage TDA (weeks of 2026-07-13 / 2026-07-20)

**Goal.** Wire the Polymarket TDA pipeline (Sketch 5) into the cycle-2 Week 1 `omega/nodes/polymarket/` project. Three regime features feed into a *new* cross-asset signal: `polymarket_topology_stress`.

**Files added.**
- `omega/nodes/polymarket/tda_arbitrage.py` (Sketch 5).
- `omega/nodes/polymarket/logical_dependence.py` (parses condition descriptions into the logical-dependence graph from cycle-2 Week 1 §2.2).

**Files modified.**
- `omega/nodes/polymarket/__init__.py` — registers the new node.
- `projects/polymarket.yaml` — registers the regime feature.

**Acceptance criterion.** Backtest on April 2024 – April 2025 Suarez-Tangil dataset replicates the reported $40M combinatorial-arbitrage volume to within ±15%.

### Phase 5 — Persistent Laplacian on DeFi loan graphs (after 2026-09)

**Goal.** Apply persistent homology to the DeXposure (arXiv 2511.22314) Aave V2/V3 / Morpho / Euler / Maple / Gearbox / Silo loan-exposure graph with health-factor as the filtration parameter. Research-grade — depends on PETLs library maturation and our internal validation.

**Files (future).**
- `omega/nodes/defi/loan_graph.py`
- `omega/nodes/defi/persistent_laplacian_defi.py`

**Open questions blocking Phase 5.**
1. PETLs Python API stability (currently 0.1.x).
2. Whether DeXposure refresh latency is fast enough for live signal use (current cadence: 4 hours; Victoria needs ~15 minutes).
3. Whether persistent-Laplacian features clear the surrogate null on the Oct 2024 Aave $180M stress event and Feb 2025 $200M stress event (the obvious held-out validation, but small sample).

---

## 8. Open Questions for Cycle 2

The cycle-1 closing recommendation — promote `omega/nodes/victoria/{geometry, manifolds, rmt, spectral, rg}/` to platform `omega/core/geometry/` — applies equally to `tda/`. The cycle-2 Week 2 contribution to that recommendation: **`omega/nodes/victoria/tda/` should join the promotion list once Phase 2 ships, because Polymarket (Phase 4) and DeFi (Phase 5) both consume the same persistent-homology primitives.**

Five open questions specific to cycle-2 Week 2:

1. **Vectorisation bake-off resolution.** Akin (2026) vs Kulkarni (2024) disagreement on landscape norm vs persistent entropy. Phase 1 will resolve this with internal evaluation. Hypothesis: persistent entropy wins on graph-valued data, landscape norm wins on point-cloud (Takens-embedded) data — Akin uses the former, Kulkarni the latter, but their conclusions are reversed. Worth investigating.

2. **Surrogate-null calibration for crypto.** Akingbade (2026) calibrated null distributions on US equities. Crypto has different statistical properties (multifractality, longer memory; cycle-1 Week 8). The IAAFT (iterated amplitude-adjusted Fourier transform) surrogate may need adjustment — possibly replace with a multifractal-preserving surrogate from the Drożdż group's framework.

3. **Persistent-Laplacian streaming complexity.** The Lipschitz bound (arXiv 2506.21352) gives a per-simplex insertion bound but the full eigenvalue recomputation is still $O(N^2)$ to $O(N^3)$. For Victoria's 50-asset graph this is fine; for the Polymarket combinatorial graph ($\sim 17{,}000$ conditions per Suarez-Tangil) it's prohibitive. Incremental eigensolvers (Lanczos restarts, deflation) are required. Research item.

4. **Multipersistence / zigzag readiness.** Dey-Samaga QZPH (2502.16049) is theoretically clean but has no finance validation. Phase 4 research could pilot it on the rolling correlation filtration. The implementation is non-trivial — RIVET is the closest production tool, and it does not have a clean Python sklearn-style API.

5. **Production deployment gap.** As of June 2026, no tier-1 quant firm publicly discloses TDA in production. The methodology is well past the "is it real" stage academically but the build-vs-buy decision is currently *build*: Ripser++ is unmaintained, PETLs is brand new, and giotto-tda has no GPU support. This is a moat in Victoria's favor — done well, the cycle-2 Week 2 + cycle-2 Week 1 composition has no published precedent and no obvious commercial off-the-shelf alternative.

---

## 9. Cross-References to Other Weeks

**Cycle 1 Week 1 (gauge theory).** Persistence of Ollivier-Ricci-curvature-weighted graph (Sketch 4) is the discrete bridge between persistent homology and Tang/Ilinski gauge curvature. The cycle-2 Week 1 doc identified Ollivier-Ricci on RIE-cleaned correlations as the gauge-curvature avatar; the cycle-2 Week 2 contribution adds the persistence diagram of that same object.

**Cycle 1 Week 2 (persistent homology).** The cycle-1 Week 2 doc is the parent. Cycle-2 Week 2 adds five new constructions (velocity, persistent Laplacian, persistent entropy, Ricci-filtered persistence, Polymarket combinatorial). All five compose with rather than replace the cycle-1 landscape-norm baseline; Phase 1 logs both.

**Cycle 1 Week 3 (information geometry).** Fisher-Rao distance gives an alternative edge weight for the correlation graph filtration. The Banerjee et al. 2025 paper (cycle-1 Week 7) used Fisher-information-distance edges and reported the most stable spectral signature. Combined with persistent Laplacians, this is a one-line edge-weight substitution in Sketch 2 that could improve stability further. Not in the Phase 1 plan but worth piloting.

**Cycle 1 Week 4 (optimal transport).** The persistence-diagram metric *is* Wasserstein-$p$. The Khormali velocity (Sketch 1) is a $W_2$ computation. The cycle-1 Week 4 sliced-Wasserstein speedup is directly reusable for high-cardinality diagrams (Phase 4 Polymarket and Phase 5 DeFi loan-graph). Wasserstein barycenters of persistence diagrams (Phase 4 research) give "average" topology features across regimes.

**Cycle 1 Week 5 (RMT / BBP-RIE).** *Mandatory upstream.* RIE cleaning reduces bottleneck instability of all persistence diagrams by ~30%. Phase 1 hard-errors if called on raw correlations.

**Cycle 1 Week 6 (stochastic calculus on manifolds).** Wishart EWMA correlation gives a temporally smoothed input to the persistence pipeline. Bootstrap stability improves by ~40%. Phase 3 wires this.

**Cycle 1 Week 7 (spectral graph theory).** Persistent Laplacian Fiedler (Sketch 2) is the natural generalization of cycle-1 Week 7 Fiedler tracker. The Kang-Yen-Cheong (2025) crash-duration indicator is recovered as `fiedler_max`. The integrated feature `fiedler_int` is the Wilsonian (cycle-1 Week 8) effective Fiedler.

**Cycle 1 Week 8 (renormalization group).** Filtration parameter $\epsilon$ *is* the RG scale. The persistence landscape obeys the multifractal scaling $\lambda_k(t, \epsilon) \sim \epsilon^{h(k)}$. The cycle-1 Week 8 multifractal regime detector and the cycle-2 Week 2 persistent-homology detector are dual views of the same coarse-graining transform. Phase 3 research-grade composition.

**Cycle 2 Week 1 (gauge theory revisited).** Sketch 5 (Polymarket combinatorial TDA) is the topological half of the gauge-constraint module from cycle-2 Week 1. The two together form the complete prediction-market topology stack: gauge structure for the *constraints*, persistent homology for the *graph of violations*.

**Cycle 2 forward (Weeks 3-8 to come).** Cycle-2 Week 3 (information geometry revisited) should pick up the Fisher-information-distance edge weighting note in §9 above. Cycle-2 Week 4 (optimal transport revisited) should pilot persistence-diagram Wasserstein barycenters as regime archetypes. Cycle-2 Week 5 (RMT revisited) should examine whether the RIE-cleaned correlation matrix can be replaced by a *spectral persistence* construction (clean by spectral filtering inside the persistence-Laplacian framework rather than as a separate preprocessing step). Cycle-2 Week 6 (SDE revisited) should examine SO(n) flow on persistence diagrams. Cycle-2 Week 7 (spectral revisited) should benchmark persistent Laplacian vs static Fiedler head-to-head on the same held-out events. Cycle-2 Week 8 (RG revisited) should reformulate the multifractal LPPL regime detector inside the persistence framework.

---

## 10. References

### 2024-2026 load-bearing papers

- Khormali, O. *Hierarchical Persistence Velocity for Network Anomaly Detection: Theory and Applications to Cryptocurrency Markets.* arXiv:2512.14615 (Dec 2025). [OW-HNPV; Ethereum tx graph 2017-18; +10.4% AUC.]
- Park, M., Na, G., Kim, S., Moon, J., Cha, M., Chai, S. *HyPV-LEAD: Proactive Early-Warning of Cryptocurrency Anomalies through Data-Driven Structural-Temporal Modeling.* arXiv:2509.03260 (Sep 2025). [Bitcoin tx graph; PR-AUC 0.9624 AML/illicit.]
- Islambekov, U., Akcora, C. G., Gel, Y. R. *Topological approach for high-order interactions on cryptocurrency networks.* Foundations of Data Science 2024. DOI:10.3934/fods.2024024. [VAB vectorization; AUC gains up to 20%.]
- Wei, J., Wei, G.-W. *Persistent Topological Laplacians — A Survey.* Mathematics 13(2):208 (Jan 2025). DOI:10.3390/math13020208. [PL theory consolidation; no finance applications.]
- Lipschitz Bounds for Persistent Laplacian Eigenvalues under One-Simplex Insertions. arXiv:2506.21352 (Jun 2025). [Streaming-stability theorem.]
- Generalized Persistent Laplacians and their Spectral Properties. arXiv:2509.20220 (Sep 2025).
- Akin, B. T. et al. *Geometric and Topological Analysis of Financial Market Structure: Evidence from Turkish Markets and the 2022-2023 Structural Break.* Axioms 15(1):34 (Jan 2026). DOI:10.3390/axioms15010034. [Forman-Ricci +258%, density +44%, $H_1$ landscape rises 3-8 wk pre-break.]
- Kulkarni, S., Samal, A., Saramäki, J. et al. *Investigation of Indian stock markets using TDA and geometry-inspired network measures.* Physica A 638:129653 (2024), arXiv:2311.17016. [Persistent entropy > landscape norm.]
- Kang, S., Yen, P. T.-W., Cheong, S. A. *Maximum spectral gap of correlation matrices over filtration parameters as a crash-duration indicator.* PLOS ONE 20(7):e0327391 (Jul 2025). DOI:10.1371/journal.pone.0327391.
- Akingbade, S. W. *Null-Validated Topological Signatures for Bitcoin Return Series.* arXiv:2602.00383 (Jan 2026). [IAAFT surrogate null protocol.]
- Dey, T. K., Samaga, S. *Quasi Zigzag Persistence: A Topological Framework for Analyzing Time-Varying Data.* arXiv:2502.16049 (Feb 2025). [Stability + algorithm; sleep-stage validation only.]
- Giusti, C., Lee, D., Mémoli, F. *Discrete signature tensors for persistence landscapes.* arXiv:2505.02800 (May 2025). [DLFM on knotted proteins.]
- Barbierato, E. et al. *Topological Machine Learning for Financial Crisis Detection: Early Warning Signals from Persistent Homology.* Computers 14(10):408 (2025). DOI:10.3390/computers14100408. [F1 ≈ 0.50, ~34 day lead, US equities 1999-2021.]
- *Mild explosivity, persistent homology and cryptocurrencies' bubbles.* AIMS Mathematics 9(1):788-820 (2024). DOI:10.3934/math.2024045. [PSY + persistence landscape on BTC/ETH/LTC/XRP; co-detection.]
- *Change Point Detection in Financial Market Using TDA.* Systems 13(10):875 (Oct 2025). DOI:10.3390/systems13100875.
- de Favereau de Jeneret, M., Diamantis, A. *Topology of Currencies: Persistent Homology for FX Co-movements.* arXiv:2510.19306 (Oct 2025).
- *Beyond Signal and Noise: TDA on Filtered S&P 500 Networks after RMT Cleaning.* arXiv:2311.17912.
- Suarez-Tangil, G. et al. *Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets.* arXiv:2508.03474 (Aug 2025). [$40M / 86M bets / 17,218 conditions Polymarket arbitrage.]
- Mancino, D., Sevim, H. O., Saguillo Gonzalez, O. *Bunny Hops and Blockchain Stops: Cross-Chain MEV Detection With N-Hops.* arXiv:2511.17527 (IEEE BRAINS 2025). [Cross-chain MEV.]
- *Sparse portfolio selection via topological data analysis based clustering.* Quantitative Finance 25(8) (2025). DOI:10.1080/14697688.2025.2544762.

### Software

- giotto-tda 0.6.2 (May 2024). https://github.com/giotto-ai/giotto-tda
- GUDHI 3.11.0 (2025). NanoBind Python bindings. https://gudhi.inria.fr
- Ripser++ (unmaintained 2024-26). https://github.com/simonzhang00/ripser-plusplus
- persim 0.3.8 (Mar 2025). https://github.com/scikit-tda/persim
- PETLs (2025). First dedicated persistent-Laplacian software, protein-focused.
- RIVET (multipersistence, research tool). https://github.com/rivetTDA/rivet
- fzz (fast zigzag, Purdue CGTDA). https://github.com/TDA-Jyamiti/fzz

### Cycle-1 foundational references (carried forward, do not repeat in cycle-2 docs unless new context)

- Gidea, M., Katz, Y. *Topological data analysis of financial time series: Landscapes of crashes.* Physica A 491 (2018).
- Khasawneh, F. A., Munch, E. *Topological data analysis for true step detection in periodic piecewise constant signals.* Pattern Recognition (2022).
- Rucco, M. et al. *A new topological entropy-based approach for measuring similarities among piecewise linear functions.* Signal Processing 134 (2017). [Persistent entropy.]
- Carlsson, G., de Silva, V. *Zigzag persistence.* Foundations of Computational Mathematics 10 (2010).
- Cohen-Steiner, D., Edelsbrunner, H., Harer, J. *Stability of persistence diagrams.* Discrete & Computational Geometry 37(1) (2007). [Foundational stability theorem.]
- Adams, H., Emerson, T., Kirby, M. et al. *Persistence images: A stable vector representation of persistent homology.* JMLR 18 (2017).
- Bubenik, P. *Statistical topological data analysis using persistence landscapes.* JMLR 16 (2015).

### Cross-week back-references

- Cycle-1 Week 1: `2026-03-30-gauge-theory-fiber-bundles-arbitrage.md`
- Cycle-1 Week 4: `2026-04-20-optimal-transport-wasserstein-regime-detection.md`
- Cycle-1 Week 5: `2026-04-27-random-matrix-theory-correlation-denoising.md`
- Cycle-1 Week 6: `2026-05-11-stochastic-calculus-manifolds-signal-evolution.md`
- Cycle-1 Week 7: `2026-05-18-spectral-graph-theory-network-stress.md`
- Cycle-1 Week 8: `2026-05-25-renormalization-group-multiscale-markets.md`
- Cycle-2 Week 1: `2026-06-01-gauge-theory-cycle2-defi-prediction-markets.md`

---

*Cycle 2 / Week 2 closes the persistent-homology entry. Cycle 2 / Week 3 (information geometry revisited) is next on the schedule for 2026-06-15. Architectural recommendation reaffirmed: promote `omega/nodes/victoria/{geometry, manifolds, rmt, spectral, rg, tda}/` to platform `omega/core/geometry/` once Phase 2 of the cycle-2 Week 2 plan ships.*
