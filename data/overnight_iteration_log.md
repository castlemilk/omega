# Victoria Overnight Iteration Log

Autonomous loop: wait → postmortem → adjust → launch → repeat.

Started: 2026-04-13 13:17 UTC  start=v117  features=v115_full_vectors

---

## v117 → v118  [2026-04-13 13:42 UTC]

**Result:** PnL=0.00  WR=50.0%  trades=0  PF=1.281

**Regime breakdown:**
  - high_vol: 1 trades, 0.0% WR, PnL=-12.64
  - normal: 13 trades, 46.2% WR, PnL=-16.74

**Signal scorecard (key signals):**
  - momentum_derivative: 21.4% (n=14) ← FLIP NEEDED
  - volume_profile: 26.7% (n=15) ← FLIP NEEDED
  - ollivier_ricci_signal: 63.2% (n=19) ← ALPHA
  - return_1d: 65.0% (n=20) ← ALPHA
  - liquidation_proximity: 69.2% (n=13) ← ALPHA
  - whale_print: 70.0% (n=20) ← ALPHA

**Signals flipped in v118:** momentum_derivative, volume_profile

**Commit:** `8ebb0da7`  **Next:** v118 PID=64121

---

## v118 → v119  [2026-04-13 14:36 UTC]

**Result:** PnL=0.00  WR=30.8%  trades=0  PF=0.631

**Regime breakdown:**
  - crisis: 12 trades, 41.7% WR, PnL=-188.75
  - normal: 14 trades, 21.4% WR, PnL=-74.99

**Signal scorecard (key signals):**
  - funding_derivative: 25.0% (n=24) ← FLIP NEEDED
  - momentum_persistence: 30.8% (n=26) ← FLIP NEEDED
  - liquidation_proximity: 61.5% (n=13) ← ALPHA
  - order_book_imbalance: 65.4% (n=26) ← ALPHA
  - book_depth_velocity: 69.2% (n=26) ← ALPHA
  - fear_greed_signal: 69.2% (n=26) ← ALPHA
  - price: 69.2% (n=26) ← ALPHA
  - sma_crossover: 69.2% (n=26) ← ALPHA
  - sma_long: 69.2% (n=26) ← ALPHA
  - sma_short: 69.2% (n=26) ← ALPHA
  - vpin: 69.2% (n=26) ← ALPHA
  - momentum_derivative: 75.0% (n=12) ← ALPHA
  - return_1d: 76.9% (n=26) ← ALPHA

**Signals flipped in v119:** funding_derivative, momentum_persistence
**Short-suppressed in v119:** ETHUSDT

**Commit:** `1017f5ce`  **Next:** v119 PID=69566

---

## v120 → v121  [2026-04-13 23:45 UTC]

**Result:** PnL=0.00  WR=31.8%  trades=0  PF=0.493

**Regime breakdown:**
  - normal: 14 trades, 28.6% WR, PnL=-249.88

**Signal scorecard (key signals):**
**Short-suppressed in v121:** ETHUSDT

**Commit:** `7bc63627`  **Next:** v121 PID=93134

---

## v122 → v123  [2026-04-14 05:31 UTC]

**Result:** PnL=0.00  WR=33.3%  trades=0  PF=0.534

**Regime breakdown:**
  - crisis: 15 trades, 40.0% WR, PnL=-27.93
  - normal: 24 trades, 29.2% WR, PnL=-84.39

**Signal scorecard (key signals):**

**No changes** — all signals within bounds, no new suppression needed

**Commit:** `?`  **Next:** v123 PID=31941

---

## v123 → v124  [2026-04-14 06:27 UTC]

**Result:** PnL=0.00  WR=44.7%  trades=0  PF=1.220

**Regime breakdown:**
  - crisis: 6 trades, 33.3% WR, PnL=-21.26
  - high_vol: 2 trades, 50.0% WR, PnL=-18.46

**Signal scorecard (key signals):**

**No changes** — all signals within bounds, no new suppression needed

**Commit:** `?`  **Next:** v124 PID=16933

---

## v124 → v125  [2026-04-14 07:23 UTC]

**Result:** PnL=0.00  WR=43.9%  trades=0  PF=1.045

**Regime breakdown:**
  - high_vol: 3 trades, 33.3% WR, PnL=-5.07
  - normal: 15 trades, 40.0% WR, PnL=-21.68

**Signal scorecard (key signals):**

**No changes** — all signals within bounds, no new suppression needed

**Commit:** `?`  **Next:** v125 PID=58769

---

## v125 → v126  [2026-04-14 08:18 UTC]

**Result:** PnL=0.00  WR=27.3%  trades=0  PF=0.706

**Regime breakdown:**
  - high_vol: 3 trades, 0.0% WR, PnL=-33.10
  - normal: 34 trades, 26.5% WR, PnL=-62.53

**Signal scorecard (key signals):**
**Long-suppressed in v126:** ADAUSDT

**Commit:** `?`  **Next:** v126 PID=95064

---

## v126 → v127  [2026-04-14 09:12 UTC]

**Result:** PnL=0.00  WR=39.0%  trades=0  PF=0.862

**Regime breakdown:**
  - crisis: 14 trades, 21.4% WR, PnL=-56.04
  - high_vol: 2 trades, 50.0% WR, PnL=-6.33

**Signal scorecard (key signals):**
**Short-suppressed in v127:** ETHUSDT

**Commit:** `a810de59`  **Next:** v127 PID=80238

---

## Loop ended

Final version: v127  Iterations: 5  Time: 2026-04-14 09:12 UTC

