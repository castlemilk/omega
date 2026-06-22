# V232 — brief skeleton (branch-conditional on V231 falsifier)

**Status:** SKELETON — filled verbatim once the V231 grid completes and the
distributional table is in `V231_dist_results.md`. Two pre-written branches; the V231
crisis result (B0) selects which one ships. Pre-registered here to prevent
retrospective hypothesis-shaping (the exact failure mode the V222→V229 arc kept hitting).

---

## The fork (V230 pre-registered falsifier, evaluated on the crisis gate)

Read `data/v231_dist/distribution.json` → `gates.crisis`:
- **`pnl_off.spread`** = standing-main crisis cross-window spread (B0).
- **`delta.mean`, `delta.min`, `delta_all_windows_positive`** = V227 skew Δ generalization (B1).

### Branch A — INSTRUMENT WAS INADEQUATE (V231 hypothesis CONFIRMED)
Fires if **crisis `pnl_off.spread` ≥ ~$2k** (the V218.E ±$16k pattern reproduces — the
3 single-window gates were Goodharting one window each).

> **V232 = ship Track B #1 (realized-vol term-structure inversion additive brake),
> measured on the V231 distribution.** Accept the V231 distributional eval as the new
> yardstick. The brake's verdict is its **per-gate mean-Δ AND min-Δ across the 3 crisis
> windows** (B1-style bar), NOT a single-window number. A brake that helps one crisis
> window but not the mean/min does NOT ship.

### Branch B — INSTRUMENT WAS ADEQUATE (V231 hypothesis FALSIFIED)
Fires if **crisis `pnl_off.spread` < ~$2k AND** V227's +$630 (B1: mean-Δ>0 AND min-Δ>0)
**AND** (if measured) V229's +$1,428 reproduce within spread on **every** window.

> **V232 = ship Track B #1 (RV-term-structure additive brake) DIRECTLY on the existing
> 3 gates** — no distributional-eval overhead; the single-window numbers were
> representative all along. The V231 harness stays as belt-and-suspenders but isn't
> load-bearing.

---

## V232 implementation (identical in BOTH branches — only the YARDSTICK differs)

Track B #1 — **realized-vol term-structure inversion brake**. Mirrors `crisis_skew.py`
exactly (the proven V227 additive-brake shape):
- **NEW** `omega/nodes/victoria/signals/rv_term_structure.py`: stateless, per-ticker.
  Short-window realized vol (3d) / long-window realized vol (14d). When the ratio
  **inverts** (short RV ≫ long RV — vol spiking on the near timescale), emit a one-sided
  `[-1, 0]` brake. `math.fsum` discipline on every reduction.
- Applied in the **post-demean additive block** (`signal_generation.py:1336–1409`),
  exactly where `crisis_skew` is added — NOT a selection re-weight (re-weight is closed,
  5× refuted; the drawdown gate works ONLY as an additive brake — V227→V229 lesson).
- Gated by the **proven V227 drawdown-AND-gate** (`crisis_skew_regime_gate_enabled`
  pattern): brake fires only inside crisis/high_vol AND drawdown-magnitude condition.
- **Default-inert flags** reproducing main byte-for-byte (V227 recipe): new
  `rv_term_brake_enabled: bool = False` (+ threshold params) so the OFF arm is the exact
  standing-main equal-weight control; the determinism gate must read $0.00 on every cell.

### Falsifier for V232
The brake is **orthogonal** to V227's drawdown-magnitude skew (vol-of-vol on a shorter
timescale). It ships iff, on the V231 crisis distribution: **mean-Δ (brake-ON − main) > 0
AND min-Δ > 0** across the ≥3 crisis windows, WITHOUT regressing trend OR recent mean-Δ
below −$200. If it helps only one window (mean or min ≤ 0), it's window-luck — do NOT
ship; park and reassess.

### Determinism pre-reqs (carry from the arc)
`check_no_wallclock.py` + `check_frozen_http_fence.py` + `assert_cell_identity.py` PASS
per cell. New signal must carry the `OMEGA_FROZEN_CACHE` fence if it touches any feed
(it's OHLCV-only → snapshot-fed, so no HTTP). Grep its producer for unsorted FP
reductions before trusting the $0.00 check (V211/V217/V220/V221 channel-peel pattern);
prefer `math.fsum` over `sorted()+sum`.

---

## Deferred (→ V233+)
- **B2 V229 trend-IC re-measure** on a ≥3-window trend distribution (needs a 3rd trend
  window — widen 2024 post-halving or accept 2020-Q4 11/13).
- **Recent 2025 distribution** (MATIC→POL basket-identity fork must be resolved first).
- **Track A free DVOL options-skew MVP** (Deribit public `get_volatility_index_data`,
  $0, 2-of-3 windows) — only if appetite remains after V232.
