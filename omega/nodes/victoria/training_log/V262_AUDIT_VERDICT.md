# V262 — Intraday resolution audit VERDICT

**Task:** audit + freeze only. No strategy code, no scorer, no grid, no flag.
**Pre-registration:** [`V262.md`](V262.md) (committed `f8713f2`, **before** the freeze).
**Date:** 2026-07-25. **Parent:** V261 (REFUTED, MWU p=0.942).

---

## Verdict in one line

**GREEN for the V262-2 Phase-0 separator proof (falsifier F4); CAVEATED for the
full PnL grid** — the data is complete, clean and byte-identical, but the *existing
walk-forward simulation runner is the wrong tool at 1h* and V262-2 must be built as
an offline scorer (V255.C / V261 pattern), not as a `run_training.py` grid.

---

## Phase 0 — coverage matrix

Source: `data.binance.vision` spot klines, `1h`, window **2020-01 → 2026-07**.
Monthly archives for complete months; per-day archives for the partial current month
(reaching **2026-07-24**, i.e. yesterday).

| Symbol | Role | First month | Months | Bars | Outage gaps | Frozen size |
|---|---|---|---:|---:|---:|---:|
| BTCUSDT | regime ref | 2020-01 | 79 | 57,497 | 31 | 1.39 MB |
| ETHUSDT | regime ref | 2020-01 | 79 | 57,497 | 31 | 1.26 MB |
| BNBUSDT | tradable | 2020-01 | 79 | 57,497 | 31 | 1.07 MB |
| XRPUSDT | tradable | 2020-01 | 79 | 57,497 | 31 | 1.05 MB |
| ADAUSDT | tradable | 2020-01 | 79 | 57,497 | 31 | 1.03 MB |
| LINKUSDT | blacklisted | 2020-01 | 79 | 57,497 | 31 | 1.03 MB |
| SOLUSDT | tradable | 2020-08 | 72 | 52,151 | 19 | 0.97 MB |
| DOTUSDT | blacklisted | 2020-08 | 72 | 51,966 | 19 | 0.91 MB |
| AVAXUSDT | tradable | 2020-09 | 71 | 51,143 | 19 | 0.87 MB |
| NEARUSDT | tradable | 2020-10 | 70 | 50,616 | 19 | 0.87 MB |
| ARBUSDT | tradable | 2023-03 | 41 | 29,264 | 0 | 0.52 MB |
| SUIUSDT | tradable | 2023-05 | 39 | 28,284 | 0 | 0.53 MB |
| POLUSDT | tradable | 2024-09 | 23 | 16,310 | 0 | 0.27 MB |
| MATICUSDT | pre-migration | 2020-01 | 57 | 41,108 | 31 | 0.74 MB |
| **TOTAL** | | | **919** | **665,824** | **293** | **12.5 MB** |

**13/13 universe names have full 1h coverage. Zero blocking gaps.**

### Data integrity — the gap structure is fully explained

Raw "missing" was 3,200 bars, but that number is misleading; decomposed:

- **2,907 bars (91%) are listing/delisting month artifacts** — the symbol simply
  wasn't trading yet (ARB 2023-03: 544; AVAX 2020-09: 510; MATIC 2024-09 delisting:
  501; DOT 2020-08: 431; NEAR 2020-10: 317; POL 2024-09: 298; SOL 2020-08: 246;
  SUI 2023-05: 60). Not data loss.
- **293 bars (0.044%) are genuine exchange outages.** These appear at *byte-identical
  months and counts across every symbol listed at the time* — 2020-02:6, 2020-03:1,
  2020-04:2, 2020-06:3, 2020-11:1, 2020-12:4, 2021-02:1, 2021-03:1, 2021-04:5,
  2021-08:4, 2021-09:2, 2023-03:1. Cross-symbol identity is the proof these are
  exchange-wide downtime, not per-symbol corruption.
- **Zero gaps from 2023-04 onward.** The entire `recent`-regime era — the exact era
  V262 is trying to reopen — is 100% complete.

### MATIC→POL: an 80-hour hole, NOT a clean splice

Measured, and it **corrects the assumption written into the V262 pre-registration**
(which was fixed before commit):

- MATICUSDT last 1h bar opens **2024-09-10T02:00Z**
- POLUSDT first 1h bar opens **2024-09-13T10:00Z**
- **Gap: 80 hours (3.3 days).**

Narrower than the daily case (V255.D-EXT: all 86 MATIC trades exited before the POL
archive began, making the splice untestable) — but still a real discontinuity.
**V262-2 must pre-declare a splice policy**; the defensible default is two separate
name-histories with the 80h window excluded. A silent splice injects a fabricated
3.3-day price jump into every trailing-window z-score straddling the boundary.

---

## Phase 2 — freeze actuals

| Metric | Value |
|---|---|
| Path | `data/frozen_series/binance_intraday/{SYMBOL}/1h/{YYYY-MM}.json.gz` |
| Files | 919 cells + `MANIFEST.json` |
| **Committed size** | **14 MB** (12.5 MB gz + 156 KB manifest) |
| Raw zip mirror (gamma volume) | 34 MB, `frozen_series/binance_intraday_raw` |
| Integrity | every archive sha256-verified against its `.CHECKSUM` sidecar |
| **Byte-identity gate** | **PASS — 919 identical, 0 differing, 0 missing** |
| Full-corpus load time | **0.5 s** (1.47M bars/s) |

Determinism is achieved by (a) clock-free file content — provenance only, no
`fetched_at_utc` — and (b) `gzip(mtime=0)`, since the default gzip header stamps
wall-clock and would break byte-identity on every re-freeze. `--now-ms` is pinned
into the manifest so a `--verify` run months later recomputes the same
`expected_bars` for the partial month rather than drifting against the wall clock.

Deviation from the V255.D pattern, deliberately: **no per-file `.md5` sidecars.**
At 919 cells they would double the committed file count while carrying nothing
`MANIFEST.json` doesn't already hold, and `--verify` reads the manifest, never the
sidecars. (V255.D froze ~24 files, where sidecars were cheap.)

### Storage estimate correction — the task brief was off by ~150×

| Scope | Brief's estimate | **Measured** | Ratio |
|---|---|---|---|
| 1h × 14 names × 6.5 yr | 4–6 GB | **14 MB frozen** (33 MB raw zip) | ~**150× smaller** |
| 5m × 14 names, full history | 50–70 GB | **~0.6 GB raw zip** (BTC 49 MB + ETH 46 MB measured) | ~**100× smaller** |

**Consequence:** the premise behind "5m is a big commitment, hold it for a user
decision" does not survive measurement. 5m is ~0.6 GB raw / plausibly ~0.2 GB
frozen — trivial against 239 GB free. It was still **not frozen**, per the explicit
guardrail; but the decision should now be made on *scientific* grounds
(overfit risk, microstructure noise, F3 cost erosion), not storage. The freeze script
already supports `--interval 5m` and needs no changes.

---

## V262-2 build/run readiness

| Component | Status | Note |
|---|---|---|
| 1h OHLCV corpus | 🟢 **GREEN** | complete, clean, byte-identical, 0.5 s load |
| F4 regime-independence separator proof | 🟢 **GREEN** | pure statistics on frozen data; needs only an intraday regime labeller |
| Intraday regime labeller | 🟡 **CAVEATED** | **does not exist.** `walk_forward_freeze.py:regime_label` is defined on daily bars. This is new code and V262-2's first deliverable, with its own correctness risk |
| F1/F2 offline scorer | 🟡 **CAVEATED** | buildable (V255.C/V261 pattern) but see compute below |
| `hourly_basis_z` signal | 🔴 **BLOCKED** | needs a **1h** mark/index basis freeze. V255.D froze basis at **1d** only. Either extend `v255d_freeze_basis.py` to 1h or drop this one signal from V262-2 |
| Full `run_training.py` walk-forward at 1h | 🔴 **NOT VIABLE** | see below |
| 5m corpus | ⚪ not frozen | user's call; cheap, see correction above |

### Compute estimate — and why the simulation path is the wrong tool

A 90-day walk-forward window holds **90 bars at 1d but 2,160 bars at 1h — 24×**.
The existing `run_training.py` grid costs roughly ~8 h per cell at daily resolution;
scaling linearly with bar count puts a naive 1h re-run at **~8 days per cell**, times
26 windows times the grid. **That is infeasible and should not be attempted.**

The viable path is the one V255.C and V261 already established: an **offline scorer**
that reads the frozen series directly and computes the falsifier statistics, with no
node DAG, no cycle loop, no sleep. Grounded estimate:

| Job | Estimated compute |
|---|---|
| F4 regime-independence proof (label + correlate, 665k bars) | **< 1 minute** |
| F2 MWU on entry-composite z split | **minutes** |
| F1/F3 offline PnL + fee model over the full corpus | **minutes to ~1 hour** |
| Naive `run_training.py` walk-forward at 1h | ~8 days/cell — **do not** |

The whole corpus loads in 0.5 s, so the binding cost in V262-2 is *signal
computation*, not I/O. This is a strong argument for the offline-scorer architecture
independent of the timeframe question.

---

## Recommendation: **proceed to V262-2, but F4 first and alone**

1. **Build the intraday regime labeller + run F4 as a standalone Phase-0 separator
   proof. Ship nothing else until F4 returns.** This follows the V234 standing rule
   ("no grid until an env-gated probe shows the gate variable actually discriminates")
   — the rule that would have saved V234's entire burn. F4 costs under a minute of
   compute against a corpus that already exists.
2. **F4 is the gate on the whole thesis, not a formality.** Per `V262.md` §2a: 24×
   more *bars* is not 24× more *independent windows*. The V249 constraint is about
   independent 90-day regime windows (26, fully tiled). Intraday only manufactures
   new independent N if per-name hourly regime structure is genuinely orthogonal to
   the macro-daily regime. **If corr > 0.7, V262 is REFUTED at Phase 0** and reduces
   to "the same saturated composite measured with a finer ruler on the same 26
   draws" — and we stop, cheaply, having spent 14 MB and one afternoon.
3. **Only if F4 passes**, build the offline scorer for F1/F2/F3, with window lengths,
   thresholds and fee model pre-declared before the first grid.
4. **Expect F3 to be the likeliest killer.** V255.B is the precedent: gross 36.4%
   annualized was *real, confirmed* alpha and still died at −$5.95 median net once
   2-leg 20 bps friction met a 3-day hold. At 1h the trade count rises by
   construction while edge does not, so friction scales against us. Pre-declare the
   fee model honestly, and do not tune the hold to rescue it.
5. **Decide 5m on science, not storage.** Storage is a non-issue. The real arguments
   against 5m are overfit surface (288× the bars = 288× the noise-fitting
   opportunity) and microstructure contamination. Recommend holding 5m until 1h
   clears F4 *and* F3 — exactly the tier order pre-declared in `V262.md` §4.

**Do NOT** reopen the daily-bar entry-side composite, re-run parked V241–V261 flags,
or touch the standing baseline on the strength of this freeze. All flags stay **OFF**.
The standing baseline (V240-selective: crisis +$599 / trend +$2,997 / recent +$30)
is untouched and remains the shippable answer.

---

## Side observation (not part of this task, surfaced because the brief assumed otherwise)

The task brief states "Live daemon PID 53422 running headless with 2 open paper
positions." **PID 53422 is not running.** No live-paper process is alive, and the
configured checkpoint directory
(`/Volumes/gamma-systems-2/omega-victoria-data/live_paper/checkpoint`) **does not
exist** — though the gamma volume itself is mounted and healthy (the freeze mirrored
34 MB of raw zips to it with zero skips). This is consistent with V253 shipping with
`SCHEDULER_ENABLED=0` pending the 8-item host provisioning checklist, i.e. the daemon
was an ad-hoc foreground run rather than a scheduled service.

**Consequence:** the live-paper `recent`-N accrual toward the ≥20 resume gate is
**not currently running**, so resume path (1) is not advancing on the calendar. That
raises the value of V262 (resume path 2) but is a separate matter to fix. I did not
touch it — no daemon was restarted, no flag flipped.

---

## Artifacts

| Artifact | Path |
|---|---|
| Pre-registration | `omega/nodes/victoria/training_log/V262.md` |
| This verdict | `omega/nodes/victoria/training_log/V262_AUDIT_VERDICT.md` |
| Freeze pipeline | `scripts/v262_freeze_intraday.py` |
| Frozen corpus | `data/frozen_series/binance_intraday/` (919 cells + MANIFEST) |
| Raw zip mirror | `/Volumes/gamma-systems-2/.../frozen_series/binance_intraday_raw` (34 MB) |
| Scoping update | `V254_ALT_DATA_SCOPING.md` — intraday added as rank-1 follow-on |

Re-verify at any time:

```bash
python3 scripts/v262_freeze_intraday.py --verify --interval 1h
# expect: identical=919  differing=0  missing=0 / BYTE-IDENTITY: PASS
```
