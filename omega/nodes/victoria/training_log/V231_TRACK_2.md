# V231 Track 2 — Distributional Eval Harness (design, instrument-only)

**Status:** DESIGN. No diffs applied. Read-only task; proposes exact diffs to land in V231.
**Scope:** Extend the single-window determinism gate into a per-gate **distribution across ≥3 snapshot windows**, while keeping the existing **$0.00 byte-identical within-window** determinism check unchanged and mandatory.
**Bias:** minimal diff. The lower instrument (`check_determinism.sh`) is **already capable** of running any window via `SNAP_OVERRIDE` (line 52-55). The new code is one orchestrator + one aggregator. `check_determinism.sh` itself needs **zero functional change** (one optional cosmetic line).

---

## 1. What exists today (verified)

### The "cell" today
A **cell** = one `(gate, features)` pair run through `check_determinism.sh GATE N FEATURES VPREFIX FLOOR SLEEP`:
- Spawns `N` replicates as **separate processes** (`check_determinism.sh:84-123`), same `PYTHONHASHSEED=42 --seed 42 --frozen-cache`, restoring frozen disk state (`signal_ic_history.json` + 3 DBs) before each (`restore_state`, lines 75-79, 85).
- Snapshot is chosen by `snap_for()` (lines 44-51): `recent→snap_20260414.json`, `trend→snap_trending_2023q4.json`, `crisis→snap_crisis_2022h1.json`. **`SNAP_OVERRIDE` env overrides it (line 55)** — this is the seam Track 2 uses.
- Preflights: `check_no_wallclock.py` (line 62), `check_frozen_http_fence.py` (line 68).
- Optional identity assertion via `EXPECT_SKEW`/`EXPECT_IC`/`EXPECT_GATE` → `assert_cell_identity.py` (lines 114-121).
- Writes `data/{VPREFIX}_{GATE}_determinism/summary.json` with `{gate, features, n, pnls, trades, pnl_spread, trade_range, floor, verdict}` and a `DETERMINISM: PASS|FAIL` line (lines 126-138). **`verdict=PASS` iff `pnl_spread < FLOOR`** (canonically FLOOR=200; true determinism is $0.00).

### The grid orchestrators (`scripts/v2*_run_grid.sh`)
A flat list of `run_cell` calls, each invoking `check_determinism.sh` once and `grep`-ing the `DETERMINISM:` / `CELL-IDENTITY:` lines into a progress log (e.g. `v225_run_grid.sh:28-48`). **No cross-cell aggregation; no windows.** Each cell is one gate × one snapshot × N replicates.

### Snapshots available today
```
data/snapshots/snap_20260414.json        (recent)
data/snapshots/snap_trending_2023q4.json (trend)
data/snapshots/snap_crisis_2022h1.json   (crisis)
data/snapshots/snap_crisis_2020q1.json   (2nd crisis window — already used by V218.E via SNAP_OVERRIDE)
```
**Only 1–2 windows per regime exist.** Reaching ≥3 windows/gate requires **freezing 5–7 more snapshots** (`scripts/freeze_snapshot.py`) — a data prerequisite for Track 2, called out in §6. The harness is window-count-agnostic, so this is decoupled from the code diff.

### SESSION_STATE.json
Flat object `{version, step, next_action, notes[]}` (`data/SESSION_STATE.json`). No per-run PID/resume structure today — Track 2 adds an optional `v231_dist` block (§5).

---

## 2. Cell model under the distributional extension

```
gate ∈ {trend, crisis, recent}
  └─ window w ∈ {w1, w2, w3, ...}   (≥3 snapshots per gate)
       └─ arm ∈ {ON (skew-gated), OFF (all-OFF equal-weight)}
            └─ replicate r ∈ {1, 2}   ← N=2, handled INSIDE check_determinism.sh
```
- **One `check_determinism.sh` invocation == one (gate, window, arm) cell**, producing N=2 replicates and its own `$0.00` verdict. This is the atomic unit and is **unchanged**.
- Cells per (gate, window) = 2 arms × N=2 = **4 runs**. ✅ matches spec.
- The new layers (window, arm, gate-aggregation) live **entirely in the orchestrator + aggregator**, not in `check_determinism.sh`.

---

## 3. Diffs

### 3a. `check_determinism.sh` — ONE cosmetic line (functionally a no-op)

`SNAP_OVERRIDE` already does all the work. The only nicety: record the effective snapshot + a caller-supplied window label into `summary.json` so the aggregator can key on it without re-deriving paths.

**Before** (lines 133-135):
```python
out={"gate":gate,"features":feats,"n":len(pnls),"pnls":pnls,"trades":trades,
     "pnl_spread":round(spread,2),"trade_range":trange,"floor":floor,"verdict":verdict}
json.dump(out,open(summary,"w"),indent=2)
```
**After** — pass `$SNAP` and `${WINDOW_LABEL:-}` through to the summary writer. Add to the heredoc args (line 126) `"$SNAP" "${WINDOW_LABEL:-default}"` and read them:
```python
out={"gate":gate,"features":feats,"n":len(pnls),"pnls":pnls,"trades":trades,
     "pnl_spread":round(spread,2),"trade_range":trange,"floor":floor,"verdict":verdict,
     "snapshot":sys.argv[<k>],"window":sys.argv[<k+1>]}   # NEW: provenance for the aggregator
json.dump(out,open(summary,"w"),indent=2)
```
Concretely: change line 126 from
```bash
python3 - "$FLOOR" "$SUMMARY" "$GATE" "$FEATURES" "${PNLS[@]}" "::" "${TRADES[@]}" <<'PY'
```
to prepend the two provenance args **before** `"$FLOOR"` (so the `::`-split logic at lines 129-130 is untouched):
```bash
python3 - "$SNAP" "${WINDOW_LABEL:-default}" "$FLOOR" "$SUMMARY" "$GATE" "$FEATURES" "${PNLS[@]}" "::" "${TRADES[@]}" <<'PY'
```
and inside the heredoc shift the existing `sys.argv` indices by 2 (`floor=float(sys.argv[3])`, `summary=sys.argv[4]`, `gate=sys.argv[5]`, `feats=sys.argv[6]`, `rest=sys.argv[7:]`), adding `snap=sys.argv[1]; window=sys.argv[2]` and the two new `out` keys.

> If we want **truly zero** diff to `check_determinism.sh`, skip this entirely: the aggregator can re-derive `snapshot` from `SNAP_OVERRIDE`/`snap_for` and take `window` from its own loop variable. The cosmetic diff just makes each `summary.json` self-describing. **Recommend the cosmetic diff** — provenance-in-artifact is cheap and matches the V225 "self-describing cell" ethos.

**No other change to `check_determinism.sh`.** The within-window $0.00 check, state isolation, preflights, identity assertion, and auto-trade-diff all carry over per cell, unchanged.

### 3b. NEW orchestrator: `scripts/v231_dist_grid.sh`

Wraps `check_determinism.sh`, looping windows × arms, with `SNAP_OVERRIDE` + `WINDOW_LABEL` + a bounded parallel fan-out. Models on `v225_run_grid.sh` (arms = skew-ON / all-OFF, with `EXPECT_SKEW`/`EXPECT_GATE`).

```bash
#!/bin/bash
# V231 — distributional eval grid (≥3 windows/gate × 2 arms × N=2). Run harness; not committed as data.
# Atomic cell = check_determinism.sh (gate, window, arm) → N=2 replicates → own $0.00 verdict.
set -u
cd "$(dirname "$0")/.."
export PATH=/opt/homebrew/bin:$PATH
export DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable

MAXP="${MAXP:-4}"                 # max concurrent cells (memory pressure cap — see §4)
N="${N:-2}"; SLEEP="${SLEEP:-10}"; FLOOR="${FLOOR:-200}"
OUT=data/v231_dist; mkdir -p "$OUT"
STATE="$OUT/grid_state.json"      # resumable manifest (see §5)
SUM="$OUT/grid_progress.log"; : > "$SUM"

# Arms: ON = skew-gated; OFF = all-OFF equal-weight (the within-grid control).
ON='{"crisis_skew_enabled": true,  "crisis_skew_regime_gate_enabled": true, "ic_seed_weighting": false}'
OFF='{"crisis_skew_enabled": false, "ic_seed_weighting": false}'

# Per-gate window snapshot lists (≥3 each). Edit as snapshots are frozen (§6).
windows_for() {
  case "$1" in
    trend)  echo "data/snapshots/snap_trending_2023q4.json data/snapshots/snap_trending_2021h1.json data/snapshots/snap_trending_2020h2.json" ;;
    crisis) echo "data/snapshots/snap_crisis_2022h1.json data/snapshots/snap_crisis_2020q1.json data/snapshots/snap_crisis_2018q4.json" ;;
    recent) echo "data/snapshots/snap_20260414.json data/snapshots/snap_20251201.json data/snapshots/snap_20250901.json" ;;
  esac
}

run_cell() {  # gate window_idx snap arm_label features expect_skew expect_gate
  local gate="$1" wi="$2" snap="$3" arm="$4" feats="$5" eskew="$6" egate="$7"
  local wlabel; wlabel="$(basename "$snap" .json)"
  local vprefix="v231_${gate}_${wlabel}_${arm}"
  echo "--- CELL $vprefix start $(date -u +%FT%TZ) ---" | tee -a "$SUM"
  SNAP_OVERRIDE="$snap" WINDOW_LABEL="$wlabel" \
  EXPECT_SKEW="$eskew" EXPECT_IC=off EXPECT_GATE="$egate" \
    bash scripts/check_determinism.sh "$gate" "$N" "$feats" "$vprefix" "$FLOOR" "$SLEEP" \
    > "$OUT/${vprefix}.log" 2>&1
  echo "$vprefix rc=$? $(date -u +%FT%TZ)" | tee -a "$SUM"
}

# ---- enqueue every (gate,window,arm) cell, fan out MAXP-wide ----
running=0
for gate in trend crisis recent; do
  wi=0
  for snap in $(windows_for "$gate"); do
    wi=$((wi+1))
    run_cell "$gate" "$wi" "$snap" on  "$ON"  on  on  & running=$((running+1))
    [ "$running" -ge "$MAXP" ] && { wait -n; running=$((running-1)); }
    run_cell "$gate" "$wi" "$snap" off "$OFF" off off & running=$((running+1))
    [ "$running" -ge "$MAXP" ] && { wait -n; running=$((running-1)); }
  done
done
wait

echo "=== V231 dist grid complete $(date -u +%FT%TZ) — aggregating ===" | tee -a "$SUM"
python3 scripts/v231_dist_aggregate.py --root "$OUT" --out-json "$OUT/distribution.json" \
        --out-md "omega/nodes/victoria/training_log/V231_dist_results.md" | tee -a "$SUM"
```

> **Concurrency safety note (load-bearing):** `check_determinism.sh`'s `restore_state` rewrites shared `data/*.db` + `signal_ic_history.json` (lines 70-79). Two cells running concurrently would clobber each other's frozen state. The standing-grid pattern (`v219_run_grid.sh` header) ran cells **sequentially for exactly this reason.** Track 2 MUST give each concurrent cell an isolated working copy of those four files. Two options:
> - **(A) per-cell `TMPDIR`/`OMEGA_DATA_DIR`** if `run_training.py` honors a data-root env (preferred, no diff to `check_determinism.sh`); OR
> - **(B)** add a `WORKDIR` override to `check_determinism.sh` so `ISO`/`OUT` and the restored `data/*.db` paths are per-cell.
> This is the **one real risk** in the parallel design. If neither isolation path is cheap, fall back to **`MAXP` parallelism ACROSS GATES only** (different gates already use different snapshots but STILL share the DBs — so even cross-gate needs isolation). **Verify the isolation seam before running parallel; otherwise run `MAXP=1` (sequential, ~40h).** This is the single open question for Track 2 implementation.

### 3c. NEW aggregator: `scripts/v231_dist_aggregate.py`

Reads every `data/v231_*/summary.json`, enforces the gate (every cell must be PASS), and emits the per-gate distribution + per-window detail.

```python
#!/usr/bin/env python3
"""V231 distributional aggregator. Reads per-cell summary.json from check_determinism.sh,
groups by (gate, window, arm), enforces the within-window $0.00 determinism gate on EVERY
cell, then emits per-gate mean±spread for absolute PnL and the ON-OFF delta."""
from __future__ import annotations
import argparse, glob, json, os, statistics, sys

def load_cells(root):
    cells = []
    for sm in glob.glob(os.path.join(root, "v231_*", "*_determinism", "summary.json")):
        d = json.load(open(sm))
        # vprefix encodes gate + window + arm: v231_{gate}_{window}_{arm}
        d["_path"] = sm
        cells.append(d)
    return cells

def cell_pnl(c):  # representative PnL = mean of the N replicates (they are byte-identical on PASS)
    return statistics.fmean(c["pnls"]) if c["pnls"] else float("nan")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    args = ap.parse_args()

    cells = load_cells(args.root)
    # 1) DETERMINISM GATE: every (window, cell, arm) must PASS independently.
    failed = [c for c in cells if c.get("verdict") != "PASS"]
    det_ok = not failed

    # 2) group by gate -> window -> arm
    gates = {}
    for c in cells:
        gate = c["gate"]; window = c.get("window", "?")
        arm = "on" if "_on" in c["_path"].split("/")[-3] else "off"  # from vprefix
        gates.setdefault(gate, {}).setdefault(window, {})[arm] = cell_pnl(c)

    report = {"determinism_gate": "PASS" if det_ok else "FAIL",
              "failed_cells": [c["_path"] for c in failed], "gates": {}}
    for gate, wins in gates.items():
        per_window = []
        for w, arms in sorted(wins.items()):
            on = arms.get("on"); off = arms.get("off")
            per_window.append({"window": w, "pnl_off": off, "pnl_on": on,
                               "delta": (on - off) if (on is not None and off is not None) else None})
        offs = [w["pnl_off"] for w in per_window if w["pnl_off"] is not None]
        ons  = [w["pnl_on"]  for w in per_window if w["pnl_on"]  is not None]
        deltas = [w["delta"] for w in per_window if w["delta"] is not None]
        def stats(xs):
            return {"mean": statistics.fmean(xs), "spread": (max(xs)-min(xs)),
                    "min": min(xs), "max": max(xs)} if xs else None
        report["gates"][gate] = {
            "n_windows": len(per_window),
            "pnl_off": stats(offs), "pnl_on": stats(ons), "delta": stats(deltas),
            "per_window": per_window}

    json.dump(report, open(args.out_json, "w"), indent=2)
    _write_md(report, args.out_md)
    print("DIST-VERDICT:", report["determinism_gate"],
          "— per-gate Δ means:", {g: (v["delta"] or {}).get("mean") for g, v in report["gates"].items()})
    sys.exit(0 if det_ok else 5)   # non-zero blocks the distributional verdict

def _write_md(report, path):
    L = [f"# V231 distributional eval — determinism gate: **{report['determinism_gate']}**", ""]
    if report["failed_cells"]:
        L += ["## FAILED determinism cells (verdict blocked)", ""]
        L += [f"- `{p}`" for p in report["failed_cells"]] + [""]
    for gate, v in report["gates"].items():
        L += [f"## {gate}  (n_windows={v['n_windows']})", "",
              "| metric | mean | spread | min | max |", "|---|---|---|---|---|"]
        for key, lbl in (("pnl_off","PnL OFF"),("pnl_on","PnL ON"),("delta","Δ (ON−OFF)")):
            s = v[key]
            if s: L.append(f"| {lbl} | ${s['mean']:,.2f} | ${s['spread']:,.2f} | ${s['min']:,.2f} | ${s['max']:,.2f} |")
        L += ["", "### per-window detail", "",
              "| window | PnL OFF | PnL ON | Δ |", "|---|---|---|---|"]
        for w in v["per_window"]:
            d = f"${w['delta']:,.2f}" if w["delta"] is not None else "—"
            L.append(f"| {w['window']} | ${w['pnl_off']:,.2f} | ${w['pnl_on']:,.2f} | {d} |")
        L.append("")
    open(path, "w").write("\n".join(L))

if __name__ == "__main__":
    main()
```

---

## 4. Parallel fan-out strategy — **recommend MAXP=4**

Budget: 9 windows × 4 runs/window = 36 cells-as-runs... but the atomic `check_determinism.sh` call bundles N=2, so **36 atomic cells / 2 = 18 `check_determinism.sh` invocations**? No — re-counting against the spec: 3 gates × 3 windows × 2 arms = **18 cells**, each cell = N=2 replicates ⇒ **72 runs**. At sleep=10, ~33 min/run ⇒ **~40h sequential**.

| Fan-out | Concurrent cells | Wall-clock | Memory | Verdict |
|---|---|---|---|---|
| 1-up (sequential) | 1 | ~40h | safe (today's pattern) | baseline / fallback |
| 3-up (per-gate) | 3 | ~13h | moderate | acceptable |
| **4-up** | **4** | **~10h** | **moderate, capped** | **RECOMMENDED** |
| 9-up (per-window) | 9 | ~5h | high — OOM risk (numpy×9 + DBs) | rejected |

**Recommendation: `MAXP=4`** via `wait -n` throttling (shown in 3b). Stays under memory pressure (the spec's stated cap) while cutting wall-clock ~4×. Replicates *within* a cell stay sequential (that is the gold-standard separate-process determinism check — do NOT parallelize r1/r2). Launch under `nohup` with a harness-tracked waiter (per the MEMORY.md op-gotcha: `pgrep -P` down to python before declaring a phase dead).

**Hard prerequisite (see 3b note):** parallel cells must NOT share `data/*.db` + `signal_ic_history.json`. Resolve the per-cell data isolation seam first; if unavailable, `MAXP=1`.

---

## 5. Recovery / resumability

The 18-cell grid is long enough that a mid-run failure must not force a full restart.

**Resumable manifest `data/v231_dist/grid_state.json`:**
```json
{
  "version": "v231",
  "started": "2026-06-22T...Z",
  "max_parallel": 4,
  "cells": {
    "v231_trend_snap_trending_2023q4_on":  {"status": "done",    "pid": null,  "verdict": "PASS", "pnls": [1234.5, 1234.5]},
    "v231_trend_snap_trending_2023q4_off": {"status": "running", "pid": 81234, "verdict": null},
    "v231_crisis_snap_crisis_2020q1_on":   {"status": "pending", "pid": null,  "verdict": null}
  }
}
```
- **`run_cell` writes `status=running`+`pid` before launch, `status=done|failed`+`verdict` on exit.** On restart, the orchestrator skips any cell already `done` (its `summary.json` exists and is PASS) and re-enqueues `pending`/`failed`/orphaned-`running` cells. This makes the grid **idempotent + resumable** — re-running `v231_dist_grid.sh` resumes from the manifest.
- **PID tracking:** `check_determinism.sh` already writes a per-cell `PIDFILE` (line 40) of replicate PIDs and cleans up survivors (lines 162-164). The orchestrator additionally records the **cell-level** PID in the manifest so a killed session can `kill -0` orphans and reap them before resuming.
- **Per-window failure containment:** a single `(window, cell)` determinism FAIL is captured in that cell's `summary.json` (`verdict=FAIL`) and surfaced by the aggregator's gate check (`failed_cells`), which **exits non-zero (5)** → the distributional verdict is **blocked** but all *other* windows' artifacts survive. Fix the offending window (or its snapshot), re-run only that cell (resume), re-aggregate. No re-run of passing windows.
- **SESSION_STATE.json:** add a `v231_dist` block mirroring the manifest's roll-up so the standing session tracker reflects grid progress:
```json
"v231_dist": {"phase": "running", "cells_done": 11, "cells_total": 18,
              "max_parallel": 4, "manifest": "data/v231_dist/grid_state.json",
              "blocking_fails": []}
```
Update `next_action` to point at re-aggregation on resume. This is additive to the existing flat `SESSION_STATE.json` shape — no migration.

---

## 6. Prerequisite & open items (incomplete / needs follow-up)

1. **DATA PREREQ (blocking):** only 4 snapshots exist (2 crisis, 1 trend, 1 recent). ≥3-windows/gate needs **5+ new frozen snapshots** via `scripts/freeze_snapshot.py`. The harness is window-agnostic, so this is parallelizable with the code, but the grid **cannot deliver a real distribution until they exist.** The window lists in `windows_for()` (3b) are **placeholders** — replace with the actual frozen filenames.
2. **OPEN QUESTION (the one real risk):** the per-cell data-isolation seam for concurrent runs (§3b note). Verify whether `run_training.py` honors a data-root env (`OMEGA_DATA_DIR`-style) before committing to `MAXP>1`. If not, either add a `WORKDIR` override to `check_determinism.sh` (small diff) or run `MAXP=1`. **This must be resolved before any parallel launch** — otherwise concurrent cells corrupt each other's frozen state and silently fail the $0.00 check (or worse, pass on corrupted state).
3. Arm features assume the **V227-default gate-ON skew** recipe for the ON arm (`crisis_skew_regime_gate_enabled:true`); confirm the V231 ON-arm definition matches the standing-main config before running, and set `EXPECT_GATE` accordingly so `assert_cell_identity.py` validates it.

---

## 7. Diff summary (what lands)

| File | Change | Size |
|---|---|---|
| `scripts/check_determinism.sh` | Add `snapshot`+`window` provenance to `summary.json` (shift 2 heredoc argv indices). Functionally a no-op; `SNAP_OVERRIDE` already enables windows. | ~6 lines |
| `scripts/v231_dist_grid.sh` | **NEW** orchestrator: windows × arms loop, `SNAP_OVERRIDE`/`WINDOW_LABEL`/`EXPECT_*`, `MAXP=4` `wait -n` throttle, resumable manifest, calls aggregator. | ~55 lines |
| `scripts/v231_dist_aggregate.py` | **NEW** aggregator: group by gate→window→arm, enforce per-cell PASS (exit 5 on any FAIL), emit per-gate mean±spread (abs PnL OFF/ON + ON−OFF Δ) + per-window detail (JSON + MD). | ~80 lines |
| `data/SESSION_STATE.json` | Additive `v231_dist` progress block. | ~4 lines |

**No change to** `run_training.py`, `assert_cell_identity.py`, `check_no_wallclock.py`, `check_frozen_http_fence.py`, or any strategy/signal code. Instrument-only, as mandated.
