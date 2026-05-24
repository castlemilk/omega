# Crypto signal stack — effectiveness review

Written 2026-05-24 while waiting for vol to return. Honest assessment
of which signals are pulling weight and which are dead code with a
feature flag.

## Methodology caveats

* `data/signal_ic_history.json` is currently empty (the IC-tracking
  path resets between presets). This review is **based on which
  signals demonstrably entered profitable trades in v177c (+$132,
  9t, PF 5.53), v185_vpin (+$330, 12t, PF 6.26), and v168_extended
  (composite path, hundreds of trades)** — plus the 2,805-trade gap
  analysis aggregated in `docs/research/live-gap-analysis.md`.
* "Has shown positive live IC" = the signal entered the per-ticker
  composite for trades that produced positive PnL. Not a formal IC
  test, but a strong "has it ever mattered" proxy.

## Signals that have demonstrably contributed live

| Signal | Evidence | Notes |
|---|---|---|
| `breakout_signal` | Top contributor to V177's momentum sub-strategy votes; co-occurred with 80%+ of v177 winners | Most-cited per-ticker positive driver |
| `timeframe_signal` (multi-timeframe alignment) | Momentum sub-strategy input | Stable across regimes |
| `funding_rate_signal` | Macro sub-strategy directional bias | Saw z=0.526 → -0.928 swing in this session; correctly fired carry direction |
| `fear_greed_signal` | Contrarian macro input | Was 0.836-0.896 (high greed) through flat period — correctly suppressed entries |
| `vix_signal` | Macro bearish-tilt input | Currently 17.4 (low) → no risk-off pressure |
| `ollivier_ricci_signal` | Mean-reversion sub-strategy gate | Fade-trigger when sign opposes breakout |
| **VPIN** (V185) | v185_vpin beat v177c baseline 2.5× | Microstructure killer feature when WS data flows |

## Signals built but never measurably contributed live

| Signal | Status | Why |
|---|---|---|
| TDA fragmentation | Tracked in metrics (~0.99) but no trade has been entered on its swing | Used as a regime classifier; correlates with `tda_regime="smooth"` always in flat market |
| Wasserstein regime distance | Three values tracked per cycle (crisis, normal, trend) but no signal-side action ties to them | Feeds regime confidence but doesn't drive direction |
| `dynamic_graph_signal` (V187) | Wired into macro_confidence dampener (>0.7 clustering → ×0.7) | Threshold never triggered in current basket (clustering hovers 0.6) |
| `spectral_crash_signal` (V194) | Built + tested standalone; not in any live preset | Defensive — designed for crashes that haven't happened |
| `geopolitical_signals` | Disabled in all current presets | GDELT integration left untuned; not a current priority |
| `kyles_lambda_signal` (V185) | Computed but never crossed multiplier threshold in live | Needs more cycles of sustained WS flow |
| `lob_features` (V185) | Multi-level OFI + arrival rate + adverse selection | Same as Kyle's — needs WS time to accumulate |
| LLM tie-breaker / risk-scaling (V186) | Adds 160s latency per 200 cycles | Never converted an abstain → trade in live |

## Signal types we don't have but might help in flat markets

1. **Persistent order-flow imbalance** (not z-scored). VPIN spikes
   are episodic; a low-pass-filtered cumulative imbalance over hours
   would surface slow positioning that doesn't trigger 2σ thresholds.
   *Effort: ~50 lines on top of existing ws_feeds tape.*

2. **Cross-exchange basis carry** (Coinbase vs Binance vs Bybit perp
   funding). Persistent basis = predictable carry trade with no
   directional thesis required. We have Coinbase + Binance WS but
   only use them for trade-tape merging — not for basis tracking.
   *Effort: ~80 lines. The infrastructure (`get_latest_price` per
   exchange) exists.*

3. **Funding-rate momentum / acceleration**. Current `funding_rate_signal`
   is point-in-time z-score. Funding RATE OF CHANGE (e.g., funding
   moving from -0.01% to -0.05% over 8h) is a stronger crowded-
   positioning indicator than absolute funding. *Effort: ~30 lines.*

4. **VWAP deviation persistence**. Existing `vwap_deviation` is one
   cycle; trades that fight VWAP repeatedly mean a participant is
   forcing fills. *Effort: ~40 lines; we already compute VWAP.*

## Honest assessment

The current signal stack is heavily weighted toward **directional
momentum + regime classification** — well-suited to trending markets
where momentum sub-strategy + macro sub-strategy align. It does not
have a meaningful answer to **directionless but informationally
asymmetric** markets, which is what we're stuck in:

* VIX 17, TDA smooth, basket_std at floor — directional signals all
  near zero.
* But funding rate IS moving (+0.526 → -0.928 in a few cycles) — a
  real carry opportunity our system can see (`funding_carry_signal`
  built in V191) but the v191 range_vote gated it behind
  `range_bound=1.0` which rarely fires.

**The right next architectural change** when vol stays absent: build a
**carry-only sub-strategy** that votes purely on funding/basis even
when momentum/mean-rev/macro all abstain. Lower size cap (10-20% of
normal) to reflect lower edge per trade, but high frequency in flat
markets compensates.

This is a cleaner answer than "loosen all the gates" (which is what
V194/V195/V196 tried and which all failed because the underlying
signal really was zero).

## Don't-build list

* Don't add more LLM-arbitration layers (V186 tested, no live win).
* Don't add more graph-theoretic regime classifiers without first
  validating the existing ones (TDA, Wasserstein, dynamic_graph)
  have any incremental contribution beyond what `regime_hmm`
  already provides.
* Don't add more entry gates. We have V137 FFG, V178 normal_regime_dampen,
  V181 ensemble_block_normal_shorts, V183 normal-high-conv block,
  V189 symbol_blacklist + min_hold + damp_hours. Adding more is
  diminishing returns; the failure mode of stacked gates is silent
  override (caught in V195→V196 strategy_selector trap).

## Concrete next priority

If forced to pick ONE feature to build before vol returns: **a
funding-carry sub-strategy** (item 2 + 3 from "what's missing")
because it fires in the exact flat-market conditions our current
stack is silent in.
