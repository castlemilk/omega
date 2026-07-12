# V243 — Portfolio-level intervention: separator + pre-registration candidates

**Status:** analysis-only (no grid runs, no cache-fills). Pure paper analysis on the
committed **V240 selective-universe confirm-grid trade ledgers** (32 walk-forward
windows, round r1, on `/Volumes/gamma-systems-2/omega-victoria-data/`).
Reproduce with `scripts/v243_portfolio_separator.py`; raw numbers in
`training_log/V243_PORTFOLIO_SEPARATOR.json`.

Branched from `origin/main @ 71fc1c0` (V241 running on main, untouched).

---

## 0. Setup, corrections, and the load-bearing caveat

**Universe correction.** The spawn brief said the selective universe was 6 names
(SOL/BNB/AVAX/XRP/SUI/MATIC). The ledger is authoritative: it is **10 names** =
the full-13 universe minus blacklist `{BTC, DOT, LINK}`:
`ETH SOL BNB AVAX XRP SUI MATIC ADA NEAR ARB`. All analysis uses the 10 actually traded.

**Baseline reproduction (methodology validation).** Summing the ledger per regime
reproduces the canonical V240 standing baseline **exactly**:

| regime | ledger sum | ÷ n windows | V240 canonical mean |
|---|---:|---:|---:|
| crisis | +$7,182 | ÷12 = **+$599** | +$599 ✓ |
| trend | +$29,969 | ÷10 = **+$2,997** | +$2,997 ✓ |
| recent | +$296 | ÷10 = **+$30** | +$30 ✓ |

**THE CAVEAT (load-bearing).** No OHLCV price series is committed — the frozen-cache
manifest (`data/.cache_manifest.json`) freezes only funding / advanced-signals /
macro; crypto klines are fetched live at run time. A literal "60-day price-return
correlation matrix" would require live fetching → **out of scope by guardrail**.
So **every correlation / variance / Kelly figure here is computed on the realized
strategy-P&L streams** (the co-movement of the positions the book actually carried,
aggregated to per-window-per-name granularity), **not raw buy-and-hold price
correlation.** For risk-budgeting the strategy's *own* book this is the
decision-relevant object; it is also the only committed-artifacts path. All paper Δ's
that fix returns while rescaling notional assume **linear, no-market-impact** sizing.

---

## 1. Separator table

### (a) Correlation surface — avg pairwise correlation of realized per-name P&L, by regime

| regime | n windows | avg pairwise corr |
|---|---:|---:|
| **crisis** | 12 | **+0.175** |
| trend | 10 | +0.090 |
| **recent** | 10 | **−0.112** |
| pooled | 32 | +0.033 |

**Read:** crisis windows are systematically the *most* correlated (concentration
risk is real in crisis — the hypothesis that risk-parity would help crisis is
directionally supported). **But recent is mildly *diversifying* (negative corr)** —
so the recent-regime cushion problem is **NOT a concentration problem**, and a
diversification/risk-parity scheme has nothing to harvest there.

### (b) Variance decomposition (equal-weight portfolio, realized P&L)

Two names carry **82% of portfolio variance**: MATIC 0.555 + SOL 0.264. **But these
are the profit engines** (SOL/MATIC/SUI are top-3 P&L in trend & recent). Persistent
*drag* name = **ADA** (worst-P&L name in every regime: crisis −$4,686, trend −$3,249,
recent −$1,859). This is the crux of why risk-parity fails here: **variance and edge
are positively coupled** — demoting the high-variance names demotes the winners.

### (c) Kelly sign matrix (realized edge = mean/var per name × regime)

`NEG` = negative realized mean return (negative Kelly) in that regime.

| name | crisis | trend | recent |
|---|:--:|:--:|:--:|
| **ADA** | **NEG** −2.9 | **NEG** −41 | **NEG** −13 |
| ARB | **NEG** −27 | **NEG** −2.3 | pos +0.1 |
| NEAR | **NEG** −7.1 | pos +1.3 | **NEG** −19 |
| AVAX | pos +3.6 | **NEG** −12 | **NEG** −1.2 |
| BNB | pos +2.5 | **NEG** −0.8 | **NEG** −1.4 |
| ETH | pos +2.8 | pos +1.1 | **NEG** −12 |
| MATIC | pos +0.2 | pos +0.4 | **NEG** −4.6 |
| SUI | **NEG** −1.0 | pos +2.9 | pos +1.0 |
| SOL | pos +3.1 | pos +0.7 | pos +2.3 |
| XRP | pos +1.1 | pos +1.7 | pos +4.4 |

- **ADA is negative-edge in ALL three regimes** — the single most robust drop candidate.
- **ARB** negative in crisis+trend; **NEAR** negative in crisis+recent.
- **SOL, XRP** are positive in all three regimes (never drop).
- **Recent** has the *most* negative-edge names (6/10) — the recent cushion problem is
  a **broad per-name edge-decay problem**, consistent with (a)'s negative correlation.

### (c2) Kelly-sign persistence (fraction of a name's regime-windows whose per-window sign matches the pooled sign)

The recent negative-edge names are **persistently** negative — ADA 0.83, AVAX 0.67,
ETH 0.67, NEAR 0.67 — i.e. detectable without using the scored window. Trend signs
are noisy (~0.33–0.5, MATIC/SOL winners flip window-to-window), which is why any
per-window sizing filter *hurts* trend.

---

## 2. Paper backtest — every scheme vs the executed baseline (Δ$ mean/window)

| scheme | crisis | trend | recent | pooled | verdict |
|---|---:|---:|---:|---:|---|
| **inv-vol risk-parity (≈ERC)** | −37 | −2,280 | −326 | −828 | **REFUTED** |
| **HRP** | −1,192 | −3,294 | −570 | −1,654 | **REFUTED** |
| Kelly-cap (in-sample) | +2,938 | +3,010 | +2,782 | +2,912 | lookahead **ceiling** |
| Kelly-filter WF (redistribute) | −631 | −903 | +613 | −327 | causal — fails |
| Kelly-filter WF **drop-only FLOOR** | 0 | 0 | **−204** | −64 | causal floor **negative** |
| Static blacklist `{ADA,NEAR,ARB}` all-regime, drop-only | +838 | +163 | **+374** | **+482** | **near-miss** |

**Sanity gate (pre-registered):** recent Δ > **+$300** AND pooled Δ > **+$500** AND no
regime worse than **−$300**.

**What survives:**
- **Risk-parity / ERC / HRP: REFUTED.** Negative in every regime. In this book edge
  ∝ variance (SOL/MATIC/SUI carry both); demoting variance demotes profit. This
  refutes the brief's "largest untried axis" framing *as a risk-budgeting play*.
- **Kelly-sizing filter: REFUTED causally.** In-sample it looks spectacular (+$2,912)
  but that is lookahead. The strictly-causal, no-amplification **drop-only floor is
  −$204 in recent** — the apparent +$613 walk-forward gain was **pro-rata
  redistribution amplifying winners** (a linear-no-impact artifact), not real edge.
- **Universe-blacklist extension: the one near-miss.** A *static* blacklist of the
  persistent-negative-edge names, applied like V240's existing `{BTC,DOT,LINK}`,
  lifts **every** regime even at the conservative drop-only floor. `{ADA,NEAR,ARB}`
  all-regime gives recent **+$374** (clears), pooled **+$482** (misses the +$500 bar by
  $18), worst regime +$81. This is a **universe-selection** play, not a sizing play,
  and reuses existing machinery. Its residual weakness is **in-sample name selection**
  (the names were chosen from these same 32 windows' Kelly signs).

**Strict verdict:** under the literal three-part gate, **no admissible (non-lookahead,
causal) scheme clears all three bars.** The portfolio-level *sizing* axis is REFUTED.
The universe-blacklist extension is a genuine near-miss whose only failure is the
pooled bar (mechanically hard for any regime-gated scheme) and whose only impurity is
in-sample name selection — it is the sole candidate worth pre-registering, tested
**walk-forward with causal name selection**.

---

## 3. Pre-registration candidates

### Candidate A — Static universe-blacklist extension (PRIMARY; the survivor)

- **Hypothesis.** A small set of names carry persistent negative realized edge across
  the walk-forward. Excluding them from the tradable universe (extending the existing
  `{BTC,DOT,LINK}` blacklist) raises pooled and per-regime PnL without touching sizing
  logic. Falsifiable target: recent Δ > +$300, pooled Δ > +$500, no regime worse than −$300.
- **Mechanism.** ADA is negative-Kelly in all 3 regimes (persistence 0.83 in recent);
  ARB negative crisis+trend; NEAR negative crisis+recent. Dropping them removes their
  drag; because recent P&L is near-zero, removing a persistent loser is a large
  *relative* gain there.
- **Expected effect size (in-sample paper, drop-only floor).**
  `{ADA}`: crisis +$390 / trend +$325 / recent +$186 / pooled +$306 (every regime up).
  `{ADA,NEAR,ARB}`: crisis +$838 / trend +$163 / recent +$374 / pooled +$482.
  Walk-forward (causal name selection) will be **weaker** than these in-sample numbers.
- **Falsifier.** In a walk-forward grid where the blacklist is chosen from **prior
  windows only**, pooled Δ ≤ 0 or recent Δ ≤ 0, OR any regime regresses below −$300.
  (The causal per-window Kelly filter already floored at −$204 — so causal name
  selection is the live risk; a *static* prior-half → test-half split is the fair test.)
- **Minimal code change (flag).** In `omega/nodes/victoria/strategy.py:221`, add a
  second frozenset and a flag; extend `_universe_blocked`:
  ```python
  _V243_EXTRA_BLACKLIST: frozenset[str] = frozenset({"ADAUSDT", "NEARUSDT", "ARBUSDT"})
  # in _universe_blocked, after the universe_selective_enabled branch:
  if features.universe_selective_v243_enabled:
      return ticker in (_SELECTIVE_UNIVERSE_BLACKLIST | _V243_EXTRA_BLACKLIST)
  ```
  plus `universe_selective_v243_enabled: bool = False` in `features.py` (mirrors the
  existing `universe_selective_enabled` at `features.py:915`). Grid cells set the flag.
- **Grid layout.** Reuse `scripts/v240_wf_grid.sh` + `v240_wf_aggregate.py` over the
  32-window manifest. Arms: `selective` (baseline) vs `selective_v243`. Ablate the
  blacklist set: `{ADA}`, `{ADA,ARB}`, `{ADA,NEAR,ARB}`. Do **causal** selection: pick
  the set from windows before 2023, score on windows after, to defeat the in-sample
  objection. Aggregate = per-regime mean Δ + pooled + p25, same gate as V240.

### Candidate B — Kelly-cap position sizing (SECONDARY; expect REFUTED, run only to confirm)

- **Hypothesis.** Scaling per-name notional by realized Kelly fraction (zeroing
  negative-Kelly names, sizing survivors ∝ Kelly) beats equal/actual notional.
- **Mechanism / why it likely fails.** In-sample ceiling +$2,912, but the causal
  drop-only floor is **−$204 in recent**; the walk-forward gain came from winner
  redistribution under a linear-no-impact assumption that will not survive realistic
  sizing. Trend Kelly signs are non-persistent (0.33–0.5), so a per-window filter
  zeroes winners on noise.
- **Expected effect size.** Causal, realistic: ≈ 0 to negative. Include only as the
  adversarial control that quantifies the redistribution artifact.
- **Falsifier.** Causal walk-forward Kelly-cap pooled Δ ≤ +$500 (near-certain).
- **Minimal code change.** A sizing hook in `strategy.py` position-sizing that
  multiplies per-name notional by `max(kelly_prior, 0)` from an expanding per-name
  IC/return estimate. Larger blast radius than Candidate A — **do not build unless A
  passes and the sizing question is still open.**
- **Grid layout.** Only if pursued: arms = `equal` / `kelly_cap_redistribute` /
  `kelly_cap_droponly`, walk-forward, same manifest. Report the redistribute−droponly
  gap explicitly (it is the amplification artifact).

### Candidate C — ERC / HRP risk-parity weighting (REFUTED — do not run)

- **Hypothesis (refuted).** Equal-risk-contribution or hierarchical-risk-parity
  weights from window-t−1 correlation reduce concentration and lift risk-adjusted PnL.
- **Result.** inv-vol/ERC pooled **−$828**, HRP pooled **−$1,654**, negative in *every*
  regime. Refuted because edge ∝ variance in this book and recent is already
  diversifying (corr −0.11), so there is no concentration to harvest where it matters.
- **Action.** **Do not build a grid.** Documented as a dead axis. Revisit only if the
  traded universe or sizing regime changes enough to decouple edge from variance.

---

## 4. Recommendation to the user (decision fork)

The portfolio **risk-budgeting** axis (ERC/HRP/inv-vol) is **dead** for this book —
edge and variance are the same names. The portfolio **universe-selection** axis
(Candidate A) is the only survivor and it is a **near-miss** (pooled +$482 vs +$500,
in-sample). Two honest options:

1. **Run Candidate A as a walk-forward grid** (causal name selection, ~1 grid, reuses
   V240 machinery, near-zero code risk). Highest-probability positive of the three.
2. **Declare the portfolio-level axis REFUTED** (no scheme clears the causal gate) and
   redirect to the V242 sub-crisis whale_flow separator or another signal-level axis.

Recommend **(1)** — it is cheap, reuses existing flags, and the drop-only floor is
positive in every regime; the only open question (causal name selection) is exactly
what a prior-half→test-half grid resolves. No grid launched here per scope.
