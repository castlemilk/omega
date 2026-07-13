# V243 Candidate A — universe-blacklist extension {ADA, NEAR, ARB}: VERDICT

**Verdict: KEEP FLAG-GATED.** Ship `universe_blacklist_extended` as infra,
default **OFF**; the standing V240 selective baseline **does not move**.

- **Date:** 2026-07-13
- **Branch:** `v243a-blacklist-grid` (off `origin/main @ ab85789`)
- **Pre-registration:** `V243_PORTFOLIO_CANDIDATES.md` → Candidate A
- **Auto-generated grid tables:** `V243_A_CONFIRM_RESULTS.md`
- **Grid:** `scripts/v243a_wf_grid.sh` + `scripts/v243a_wf_aggregate.py`
- **Raw distribution:** `$OMEGA_AUDIT_OUTPUT_DIR/v243a_wf/distribution.json`

---

## 1. What ran

32-window walk-forward confirm grid, **both arms run fresh on this branch**
(same code, flag-only A/B — NOT the V240 selective cells reused as baseline, so
baseline and treatment differ *only* by `universe_blacklist_extended`):

- `universe_selective` — flag OFF: effective blacklist `{BTC, DOT, LINK}`,
  10-name universe (V240 standing baseline).
- `universe_selective_ext` — flag ON: blacklist `{BTC, DOT, LINK, ADA, NEAR,
  ARB}`, 7-name universe.

64 cells (32 windows × 2 arms), N=2 sentinels per regime
(`snap_wf_20230912` trend, `snap_wf_20240310` crisis, `snap_wf_20250305`
recent). sleep=0, per-window cycle caps (min_bars−31), frozen cache, seed 42.

**Determinism: 64/64 PASS, 0 FAIL.** All six N=2 sentinel cells spread **$0.00**.
Infra verdict: **SHIP**.

**Baseline-arm validation.** The fresh `universe_selective` arm reproduces the
V240 canonical standing baseline **to the cent** (crisis +$598.53, trend
+$2,996.92, recent +$29.64 vs canonical +$599 / +$2,997 / +$30) — confirming
(a) no code drift between the V240-era and `ab85789`, and (b) the flag-OFF path
is byte-equivalent to V240 selective. The Δ below is therefore a clean,
same-code causal contrast.

**Wiring confirmation.** Across all 32 ext cells, **zero** trades in ADA / NEAR
/ ARB (the flag fired everywhere); the 32 baseline cells traded those three
names **101 times**. The A/B is substantive, not a no-op.

---

## 2. Result — Δ(ext − selective) distribution

| regime | n | base mean | ext mean | **mean-Δ** | p25-Δ | median-Δ | min-Δ |
|---|---:|---:|---:|---:|---:|---:|---:|
| crisis | 12 | +$598.53 | +$1,924.78 | **+$1,326.25** | −$464.45 | — | −$1,140.59 |
| trend  | 10 | +$2,996.92 | +$5,004.01 | **+$2,007.10** | −$631.99 | — | −$2,150.23 |
| recent | 10 | +$29.64 | +$262.08 | **+$232.44** | −$235.79 | — | −$1,673.63 |
| **pooled** | 32 | — | — | **+$1,197.20** | −$528.62 | +$93.88 | −$2,150.23 |

Every regime mean is **positive**. Determinism clean. But the distribution is
**wide and right-skewed**: pooled median Δ is only **+$93.88** against a mean of
+$1,197 (a handful of windows — pooled max-Δ +$20,441 — carry the mean), and
**p25-Δ is negative in every regime** (≥25% of windows regress under the flag).

---

## 3. Verdict logic (pre-registered three-tier)

| tier | bar | measured | met? |
|---|---|---|---|
| **REVERT** | any regime mean-Δ < −$300 | worst = recent +$232 | no |
| **ADOPT** | recent Δ ≥ +$300 **AND** pooled Δ ≥ +$400 **AND** no regime < −$100 | recent **+$232** (<$300) | **no** |
| **KEEP FLAG-GATED** | recent Δ ∈ [+$100, +$300) **AND** positive every regime | recent +$232 ∈ band; all + | **YES** |

**recent — the binding gate — clears the +$100 KEEP floor but misses the +$300
ADOPT bar by $68.** ADOPT is therefore not met; REVERT is not triggered; the
outcome is **KEEP FLAG-GATED**.

---

## 4. Interpretation

- **The drop-only paper UNDER-predicted crisis/trend and OVER-predicted recent.**
  Paper (in-sample, drop-only, linear-no-impact): crisis +$838 / trend +$163 /
  recent +$374. Real grid: crisis **+$1,326** / trend **+$2,007** / recent
  **+$232**. The gap is `budget/N` reallocation: dropping 3 names concentrates
  freed capital into the surviving winners (SOL/XRP/MATIC), which the drop-only
  reconstruction (fixes returns, ignores resizing) could not see — a large real
  tailwind in trend/crisis where the survivors carry edge. In **recent** the
  freed capital reallocates into names that are *themselves* edge-decayed (the
  separator's "6/10 recent names negative-edge" finding), so concentration buys
  less — recent lands *below* even its own drop-only paper number.

- **recent is the weakest and noisiest cell.** +$232 mean sits at ~1/10th of
  the recent 2·SE ≈ $2,400 noise band (REFLECTION_V237); its p25 is −$236 and
  min −$1,674. This is a *directional* nudge, not a significant one — exactly
  the regime the ADOPT bar is meant to protect.

- **The pooled "+$1,197" is skew-inflated,** not a broad shift (median +$94).

- **In-sample name-selection caveat stands.** ADA/NEAR/ARB were chosen from
  these same 32 windows' Kelly signs. This grid tests the *static* all-window
  set, not the doc's causal prior-half→test-half selection. Even setting the
  recent-bar miss aside, ADOPT would over-claim generality without that causal
  split.

**Net:** a clean, cheap, causally-honest (static universe selection, no sizing,
no lookahead-in-mechanism) infra lever that is **directionally positive in every
regime with perfect determinism**, but whose binding-gate (recent) improvement
is within noise and below the ADOPT bar. Ship the flag; keep it OFF; do not move
the baseline.

---

## 5. Actions taken

- **SHIP** `universe_blacklist_extended` (default OFF) + grid + aggregator.
- **Standing baseline UNCHANGED** (V240 selective). README gets a flag-gated
  note only (no baseline-table edit — that is ADOPT-only).
- **No memory/baseline promotion** (ADOPT-gated; not met).

## 6. Next steps (for V243.B / successor)

1. **Causal name selection** — prior-half (windows < 2023) → test-half split, as
   the pre-reg falsifier specified, to retire the in-sample objection. Only a
   causal-selection pass can legitimately ADOPT.
2. **Ablate the set** — `{ADA}`-only and `{ADA, ARB}` arms (ADA is the single
   all-regime negative-edge name, persistence 0.83). A smaller set may lift
   recent above +$300 with less of the reallocation noise the full set injects.
3. **Portfolio-family-closed guidance** still applies (V240.B/V242/V244): entry-
   side info feeds and portfolio-corr sizing are saturated. If (1)/(2) don't
   clear recent, the exit-side adaptivity track (V246) is the higher-EV move.

## 7. Falsifier status

Pre-reg falsifier (Candidate A): *"pooled Δ ≤ 0 or recent Δ ≤ 0, OR any regime
< −$300."* **Not triggered** — pooled +$1,197 > 0, recent +$232 > 0, worst
regime +$232 > −$300. The candidate is **not refuted**; it simply falls short of
the ADOPT bar and stays flag-gated pending a causal-selection confirmation.
