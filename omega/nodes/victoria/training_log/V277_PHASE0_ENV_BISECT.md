# V277 Phase 0 — bisecting the off-host baseline deviation (R5 from V276 §6)

**Date:** 2026-08-27
**Author:** claude
**Status:** PHASE 0 ONLY — no version pre-registered, no code changed, no flag added
**Parent:** [`V276.md`](V276.md) §6 R5 / §8 item 1
**Standing baseline (MUST NOT MOVE):** crisis +$599 / trend +$2,997 / recent +$30 — untouched here

---

## §0 — What this is

V276's paired control found that the three sentinel windows do **not** reproduce their
committed values on a second machine. Per V276 §1's STOP rule that version did not
chase it. This document is the separator probe the loop requires *before* a version is
pre-registered against a cause — it narrows the hypothesis space and nothing else.

**The deviation** (identical at every commit and configuration tested below):

| Family | Window | Committed | This host | Δ | Trades |
|---|---|---:|---:|---:|---:|
| crisis | `snap_wf_20240310` | $1,149.76 | $1,082.80 | −$66.96 | 9 = 9 |
| trend | `snap_wf_20230912` | $4,679.67 | $4,679.67 | $0.00 | 6 = 6 |
| recent | `snap_wf_20250305` | $771.98 | $824.81 | +$52.83 | 13 = 13 |

Trade counts match the record exactly on all three while PnL moves in **opposite
directions** on two — a magnitude channel, not a selection one (V220 pattern), and not
a global scale factor.

---

## §1 — Eliminated (each measured, not argued)

| # | Hypothesis | Test | Result |
|---|---|---|---|
| 1 | **V276's own change** | paired control worktree at `d93f7340` (pre-V276) | **Not it.** Δ = $0.00 on all 6 cells (3 windows × 2 arms). Deviation present before any V276 line. |
| 2 | **Post-V274 code regression** — the V275 seam (`2acda30`), the §7 build-out (`5b9df6c`), the metrics work (`c135ee2`) all landed after V274 certified these numbers | worktree at **`2200134f`** — the V274 RESULTS commit itself | **Not it.** Same $1,082.80 / $4,679.67 / $824.81. **The deviation reproduces at the exact commit that claims 0.000000 drift against these values.** |
| 3 | **numpy version** — the V217 precedent is a BLAS/numpy reduction-order channel | numpy **2.3.5** vs **2.5.2**, same everything else | **Not it.** Byte-identical results. |
| 4 | **`omega_victoria_memory.db`** — mutated by `cfb4a43d "add all"`, the same commit that broke `macro_cache.db`, and **not** manifest-pinned. Its 1.4 MB WAL (also new in that commit) would be replayed by SQLite | restored `memory.db@0f4dd2d3` + removed the WAL/SHM that did not exist pre-`cfb4a43d` | **Not it.** Same results. |
| 5 | **Manifest-pinned frozen caches** | md5 of all 3 manifest entries, before and after every run | **Not it.** All three match throughout. |

---

## §2 — NOT eliminated (stated as untested, not rounded up to a pass)

**Optional signal dependencies.** `yfinance`, `websockets`, `scikit-learn`, `scipy` and
`pandas` are all absent on this host. None is declared in `pyproject.toml` (not even as
an extra), and the startup log reports `VIXSignal` / `SPYSignal` / all microstructure
signals returning `0.0` and `DecisionEmbedder` as a no-op.

Indirect evidence says they are probably **not** the cause: an AST scan of the crisis
cell's `signal_contribs.jsonl` finds **no** `vix` / `spy` / `ws_` / microstructure keys
among the 14 composite keys, i.e. those signals do not reach the composite in a frozen
backtest at all.

**But the direct test was not run.** Installing the five packages to a probe target
timed out after 10 minutes against the same registry that had already stalled the
Docker pull on this host. This is a **gap in the evidence, not a negative result**, and
it is the first thing V277 should close if the network allows.

**Python interpreter version.** This host runs Homebrew CPython **3.14.7**. What the
committed values were produced on is **unrecorded anywhere in the repo** — which is
itself the finding. Untested.

---

## §3 — The structural finding (independent of which hypothesis wins)

`scripts/check_determinism.sh` snapshots **four** files as the run's state:

| File | In `data/.cache_manifest.json`? |
|---|---|
| `data/macro_cache.db` | **PINNED** |
| `data/omega_victoria_memory.db` | **not pinned** |
| `data/omega_victoria_state.db` | **not pinned** |
| `data/signal_ic_history.json` | **not pinned** |

One of four. The V219 manifest and its startup abort — the mechanism that caught the
`cfb4a43d` `macro_cache.db` drift and refused to produce a baseline on it — is blind to
the other three. `cfb4a43d` mutated `omega_victoria_memory.db` too, and **nothing
anywhere would have said so**; it took a hand bisect (row 4 above) to even check.

And no manifest of any kind covers the **code environment**: interpreter version, numpy
version, or which optional signal deps are importable. V274 certified the baseline's
*data* provenance and V275 restored its *substrate*; both were measured on one host, and
row 2 shows that host-dependence is invisible to both.

---

## §4 — Recommendation for V277

Two separable pieces. They are listed in dependency order, not bundled:

1. **Widen the manifest to the other three state files** (`omega_victoria_memory.db`,
   `omega_victoria_state.db`, `signal_ic_history.json`) — the same mechanism, the same
   abort, three more files. Cheap, mechanical, and closes §3's blind spot regardless of
   what causes the deviation.
2. **Add a code-environment manifest** (`data/.env_manifest.json`): interpreter version,
   numpy version, and the importable/absent status of every optional signal dep,
   asserted at startup under `OMEGA_FROZEN_CACHE=1` the way the cache manifest is.
   Recording it is useful immediately; **asserting** it needs a decision about how
   strict to be, since it would abort runs on any host that does not match.

**Until one of these lands, no number measured on a different machine should be compared
to the committed baseline.** V276's own G2 is the worked example: it failed as written,
and the only reason that was not read as a V276 regression is that a paired control
happened to be run.

**Not recommended:** editing `data/standing_baseline.json`. Nothing here shows the
baseline is wrong — it shows it is *unverified off-host*. Those are different claims and
only the second is evidenced.
