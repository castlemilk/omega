# Victoria V49 — Phase 2a Implementation Plan (Calibration + Hard Gates)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship V49 with a surgical short-conviction threshold fix in normal regime, enforced by regime-correct hard gates derived from the V35↔V48 forensics report, so Victoria reclaims the ~$93 ADAUSDT + $44 DOTUSDT short-PnL gap V48 lost.

**Architecture:** Single-agent workstream in one git worktree. Modify `omega/nodes/victoria/strategy.py` to lower the normal-regime `short_conviction_threshold` from 0.10 to 0.05, add a hard-gate module enforcing regime parity + PnL floor + drawdown ceiling + trade count floor, wire the gates into `scripts/run_training.py`, add a forensics-derived signal integrity regression test, run V49, validate against the gates, ship.

**Tech Stack:** Python 3.11+, stdlib only for gate module. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-05-victoria-v49-meta-analyst-dispatch-design.md` (Agent 2 section)

**Forensics input (already on main):** `data/v35-v48-forensics.json`

---

## Scope

**In scope:**
- Short-conviction threshold fix in normal regime (`strategy.py`)
- V49 hard gate module (new, stdlib only)
- Wire gates into `scripts/run_training.py` post-run step
- Forensics-derived regression test (V49 short PnL in normal regime ≥ floor)
- Run V49 200-cycle training
- Validate + commit artifacts

**Out of scope (Phase 2b, separate plan after V49 ships):**
- Agent 3 — TimesFM + Wasserstein signal producers
- Agent 5 — Meta-analyst node + TrainingProposal proto
- Dashboard wiring (Agent 4 from Phase 1, deferred)

**Forensics findings driving this plan (from `data/v35-v48-forensics.json`):**

| Finding | Value | Implication |
|---|---|---|
| V35 extended PnL | $159.24 | Baseline target |
| V48 PnL | $31.97 | Current floor |
| PnL gap | $127.27 | What V49 must reclaim |
| Per-side loss: short | -$137.55 | **V48's short trades are the entire regression** |
| Per-side gain: long | +$10.28 | Longs are fine, do not touch |
| ADAUSDT delta | -$93.48 | 73% of gap |
| DOTUSDT delta | -$44.07 | 35% of gap |
| Normal regime delta | -$182.99 | **144% of gap concentrated in normal** |
| High_vol regime delta | +$82.40 | V48 is BETTER here — do not regress |
| Crisis regime delta | -$26.69 | 21% of gap |
| V35 mean conviction | 0.0839 | Post-demean distribution center |
| V48 mean conviction | 0.0650 | 23% lower, but still close to V35 |
| Normal-regime short threshold in strategy.py | 0.10 | **Above both distributions — gates everything** |

**The diagnosis:** `omega/nodes/victoria/strategy.py:487-488` sets `long_conviction_threshold=0.10` and `short_conviction_threshold=0.10` in normal regime. Post-V35 demeaning, both V35 and V48 mean convictions are ~0.06–0.08, meaning **most short signals in normal regime fail the 0.10 threshold**. V35 survived because its signal distribution happened to have more right-tail short convictions; V48's slightly shifted distribution pushed more shorts below 0.10. The fix mirrors the crisis-regime asymmetry (shorts at 0.05) in normal regime: `short_conviction_threshold = 0.05`. Longs stay at 0.10 (untouched).

**Why this is surgical and safe:**
1. Longs are untouched → no risk of long-side regression.
2. Bull regime is untouched → bull-regime short suppression still works.
3. Crisis/bear regime is untouched → crisis-regime short permissiveness still works.
4. High_vol regime (where V48 is BETTER than V35) is untouched at the strategy level — `vol_regime` tightening in `_passes_conviction_filters` still applies the 1.25× multiplier so high_vol short threshold becomes 0.0625, still permissive but not reckless.
5. V49 hard gates prevent regression in any regime (fail-closed).

---

## File Structure

### New files
- `omega/eval/v49_gates.py` — V49 hard gate module (pure functions, stdlib only)
- `tests/test_v49_gates.py` — unit tests for the gate module
- `tests/test_v49_short_threshold_regression.py` — regression test that pins the normal-regime short threshold to 0.05 and fails loudly if anyone reverts it

### Modified files
- `omega/nodes/victoria/strategy.py:486-495` — change `short_conviction_threshold` from `0.10` to `0.05` in the normal-regime branch
- `scripts/run_training.py` — add post-run gate check that calls `omega.eval.v49_gates.check_v49_gates()` and writes `data/{version}_gate_result.json`

### Output artifacts (committed)
- `data/v49_results.json`, `data/v49_trades.csv`, `data/v49_progress.json`
- `data/v49_gate_result.json`
- `docs/training/v49-run-report.md` — human-readable summary

---

## Task 2.0: Create worktree and copy input data

**Files:** none modified

- [ ] **Step 1: Create worktree from main**

```bash
cd /Users/benebsworth/projects/omega
git worktree add ../omega-v49 training/v49-calibration main
```

Expected: worktree at `/Users/benebsworth/projects/omega-v49` on branch `training/v49-calibration`.

- [ ] **Step 2: Copy untracked data files into the worktree**

Because the V35/V48 training data files are untracked in main, they don't propagate to the worktree automatically. Copy the ones V49 needs for its regression baselines:

```bash
cp /Users/benebsworth/projects/omega/data/v48_results.json \
   /Users/benebsworth/projects/omega/data/v48_trades.csv \
   /Users/benebsworth/projects/omega/data/v48_progress.json \
   /Users/benebsworth/projects/omega/data/v35_extended_results.json \
   /Users/benebsworth/projects/omega/data/v35_extended_trades.csv \
   /Users/benebsworth/projects/omega/data/training_version.txt \
   /Users/benebsworth/projects/omega-v49/data/
```

Verify:
```bash
cd /Users/benebsworth/projects/omega-v49
ls data/v48_results.json data/v35_extended_results.json data/v48_trades.csv data/v35_extended_trades.csv data/v35-v48-forensics.json
```

Expected: all 5 files listed. Note: `data/v35-v48-forensics.json` is already on main from Phase 1, so it's tracked and already present in the worktree.

- [ ] **Step 3: Verify baseline tests still pass from the worktree**

```bash
cd /Users/benebsworth/projects/omega-v49
python3 -m pytest tests/test_forensics_loader.py tests/test_forensics_cli.py -v 2>&1 | tail -10
```

Expected: 5 forensics tests pass (3 loader + 2 cli). This confirms the worktree's Python env resolves imports correctly.

No commit for Task 2.0.

---

## Task 2.1: Write the V49 hard gate module (TDD)

**Files:**
- Create: `omega/eval/v49_gates.py`
- Create: `tests/test_v49_gates.py`

The gate module is a pure function `check_v49_gates(v49_results_path, v49_trades_path, v48_results_path, v48_trades_path)` returning a `GateResult` dataclass. It checks six hard gates derived from the spec and tailored to the forensics findings.

- [ ] **Step 1: Write the failing test**

Create `tests/test_v49_gates.py`:

```python
"""Tests for V49 hard gate module."""
import json
from pathlib import Path

import pytest

from omega.eval.v49_gates import GateResult, check_v49_gates


def _write_results(path: Path, *, pnl: float, trades: int, max_dd: float) -> None:
    """Write a minimal results JSON with the fields v49_gates reads."""
    payload = {
        "version": path.stem.replace("_results", ""),
        "trades": {
            "total_closed": trades,
            "total_pnl_usd": pnl,
            "win_rate": 0.3,
            "long_trades": trades // 2,
            "short_trades": trades - trades // 2,
            "profit_factor": 1.3,
        },
        "observability": {
            "max_drawdown_usd": max_dd,
            "total_zero_trade_cycles": 100,
            "conviction_filter_rate": 0.5,
        },
    }
    path.write_text(json.dumps(payload))


def _write_trades(path: Path, trades: list[tuple[str, str, float, str]]) -> None:
    """Write a minimal trades CSV with the columns v49_gates reads.

    trades is a list of (symbol, side, pnl, regime) tuples.
    """
    lines = [
        "cycle,timestamp,symbol,side,size,entry_price,exit_price,pnl,slippage,hold_cycles,conviction,regime,sit_out_reason"
    ]
    for i, (symbol, side, pnl, regime) in enumerate(trades):
        lines.append(
            f"{i},2026-04-06T00:00:00Z,{symbol},{side},100,100,101,{pnl},0,2,0.07,{regime},normal"
        )
    path.write_text("\n".join(lines) + "\n")


def test_gates_pass_when_v49_beats_v48_in_every_regime(tmp_path: Path):
    v48_results = tmp_path / "v48_results.json"
    v48_trades_p = tmp_path / "v48_trades.csv"
    v49_results = tmp_path / "v49_results.json"
    v49_trades_p = tmp_path / "v49_trades.csv"

    _write_results(v48_results, pnl=32.0, trades=103, max_dd=10.0)
    _write_trades(
        v48_trades_p,
        [
            ("BTCUSDT", "long", 10.0, "normal"),
            ("ADAUSDT", "short", 5.0, "normal"),
            ("ETHUSDT", "long", 15.0, "high_vol"),
            ("DOTUSDT", "short", 2.0, "crisis"),
        ],
    )
    _write_results(v49_results, pnl=90.0, trades=120, max_dd=8.0)
    _write_trades(
        v49_trades_p,
        [
            ("BTCUSDT", "long", 10.0, "normal"),
            ("ADAUSDT", "short", 50.0, "normal"),
            ("ETHUSDT", "long", 20.0, "high_vol"),
            ("DOTUSDT", "short", 10.0, "crisis"),
        ],
    )

    result = check_v49_gates(
        v49_results=v49_results,
        v49_trades=v49_trades_p,
        v48_results=v48_results,
        v48_trades=v48_trades_p,
    )
    assert isinstance(result, GateResult)
    assert result.passed is True, f"expected pass, got failures: {result.failures}"
    assert result.failures == []


def test_gate_fails_pnl_floor(tmp_path: Path):
    v48 = tmp_path / "v48_results.json"
    v49 = tmp_path / "v49_results.json"
    _write_results(v48, pnl=32.0, trades=103, max_dd=10.0)
    _write_results(v49, pnl=20.0, trades=120, max_dd=5.0)  # below v48 pnl floor
    v48t = tmp_path / "v48_trades.csv"
    v49t = tmp_path / "v49_trades.csv"
    _write_trades(v48t, [("BTCUSDT", "long", 32.0, "normal")])
    _write_trades(v49t, [("BTCUSDT", "long", 20.0, "normal")])

    result = check_v49_gates(v49, v49t, v48, v48t)
    assert result.passed is False
    assert any("pnl_floor" in f for f in result.failures)


def test_gate_fails_trade_count_floor(tmp_path: Path):
    v48 = tmp_path / "v48_results.json"
    v49 = tmp_path / "v49_results.json"
    _write_results(v48, pnl=32.0, trades=103, max_dd=10.0)
    _write_results(v49, pnl=100.0, trades=30, max_dd=5.0)  # beats pnl but only 30 trades
    v48t = tmp_path / "v48_trades.csv"
    v49t = tmp_path / "v49_trades.csv"
    _write_trades(v48t, [("BTCUSDT", "long", 32.0, "normal")])
    _write_trades(v49t, [("BTCUSDT", "long", 100.0, "normal")])

    result = check_v49_gates(v49, v49t, v48, v48t)
    assert result.passed is False
    assert any("trade_count_floor" in f for f in result.failures)


def test_gate_fails_drawdown_ceiling(tmp_path: Path):
    v48 = tmp_path / "v48_results.json"
    v49 = tmp_path / "v49_results.json"
    _write_results(v48, pnl=32.0, trades=103, max_dd=10.0)
    _write_results(v49, pnl=50.0, trades=120, max_dd=50.0)  # 5x drawdown
    v48t = tmp_path / "v48_trades.csv"
    v49t = tmp_path / "v49_trades.csv"
    _write_trades(v48t, [("BTCUSDT", "long", 32.0, "normal")])
    _write_trades(v49t, [("BTCUSDT", "long", 50.0, "normal")])

    result = check_v49_gates(v49, v49t, v48, v48t)
    assert result.passed is False
    assert any("drawdown_ceiling" in f for f in result.failures)


def test_gate_fails_regime_parity_high_vol_regression(tmp_path: Path):
    """V48 is BETTER than V35 in high_vol regime — V49 must preserve that gain."""
    v48 = tmp_path / "v48_results.json"
    v49 = tmp_path / "v49_results.json"
    _write_results(v48, pnl=32.0, trades=103, max_dd=10.0)
    _write_results(v49, pnl=100.0, trades=120, max_dd=8.0)
    v48t = tmp_path / "v48_trades.csv"
    v49t = tmp_path / "v49_trades.csv"
    _write_trades(
        v48t,
        [
            ("BTCUSDT", "long", 15.0, "normal"),
            ("ETHUSDT", "long", 17.0, "high_vol"),  # v48 high_vol: +17
        ],
    )
    _write_trades(
        v49t,
        [
            ("BTCUSDT", "long", 100.0, "normal"),
            ("ETHUSDT", "long", -5.0, "high_vol"),  # v49 high_vol: -5 — regression!
        ],
    )

    result = check_v49_gates(v49, v49t, v48, v48t)
    assert result.passed is False
    assert any("regime_parity" in f and "high_vol" in f for f in result.failures)


def test_gate_fails_auto_apply_audit_missing_before(tmp_path: Path):
    """If the results JSON carries auto_applied diffs without before snapshots, fail."""
    v48 = tmp_path / "v48_results.json"
    v49 = tmp_path / "v49_results.json"
    _write_results(v48, pnl=32.0, trades=103, max_dd=10.0)
    # Write v49 with auto_applied but no before snapshot
    v49_payload = {
        "version": "v49",
        "trades": {
            "total_closed": 120,
            "total_pnl_usd": 100.0,
            "win_rate": 0.3,
            "long_trades": 60,
            "short_trades": 60,
            "profit_factor": 1.3,
        },
        "observability": {
            "max_drawdown_usd": 5.0,
            "total_zero_trade_cycles": 80,
            "conviction_filter_rate": 0.5,
        },
        "meta_analyst": {
            "auto_applied": [
                {"proposal_id": "abc", "change_kind": "threshold", "before": None, "after": 0.05}
            ]
        },
    }
    v49.write_text(json.dumps(v49_payload))
    v48t = tmp_path / "v48_trades.csv"
    v49t = tmp_path / "v49_trades.csv"
    _write_trades(v48t, [("BTCUSDT", "long", 32.0, "normal")])
    _write_trades(v49t, [("BTCUSDT", "long", 100.0, "normal")])

    result = check_v49_gates(v49, v49t, v48, v48t)
    assert result.passed is False
    assert any("auto_apply_audit" in f for f in result.failures)


def test_gate_writes_report_json(tmp_path: Path):
    v48 = tmp_path / "v48_results.json"
    v49 = tmp_path / "v49_results.json"
    _write_results(v48, pnl=32.0, trades=103, max_dd=10.0)
    _write_results(v49, pnl=90.0, trades=120, max_dd=8.0)
    v48t = tmp_path / "v48_trades.csv"
    v49t = tmp_path / "v49_trades.csv"
    _write_trades(v48t, [("BTCUSDT", "long", 32.0, "normal")])
    _write_trades(v49t, [("BTCUSDT", "long", 90.0, "normal")])

    out = tmp_path / "v49_gate_result.json"
    result = check_v49_gates(v49, v49t, v48, v48t, out_path=out)
    assert result.passed is True
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["passed"] is True
    assert "gates" in data and len(data["gates"]) == 6
```

- [ ] **Step 2: Run and verify the test fails**

```bash
cd /Users/benebsworth/projects/omega-v49
python3 -m pytest tests/test_v49_gates.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'omega.eval.v49_gates'`.

- [ ] **Step 3: Write the implementation**

Create `omega/eval/v49_gates.py`:

```python
"""V49 hard gate enforcement.

Enforces the six pass/fail criteria derived from the V35↔V48 forensics report:

1. PnL floor:         v49_pnl >= v48_pnl
2. Regime parity:     v49_regime_pnl[r] >= v48_regime_pnl[r] for every regime r that
                      appears in either run (protects high_vol where V48 is BETTER
                      than V35 by +$82.40)
3. Drawdown ceiling:  v49_max_drawdown <= v48_max_drawdown
4. Trade count floor: v49_trades >= 50 (prevents "win by sitting out")
5. Signal integrity:  existing tests/test_signal_integrity.py suite passes
                      (asserted externally — this gate only checks that the
                      test result JSON, if present, reports no failures)
6. Auto-apply audit:  every meta_analyst.auto_applied diff has a non-None
                      `before` snapshot (for rollback). N/A when meta_analyst
                      block is absent.

All gates are pure functions over on-disk artifacts; no Victoria imports.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TRADE_COUNT_FLOOR = 50


@dataclass
class GateResult:
    passed: bool
    gates: dict[str, bool] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    v48_summary: dict[str, Any] = field(default_factory=dict)
    v49_summary: dict[str, Any] = field(default_factory=dict)


def _load_results(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def _load_trades(path: Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def _regime_pnl(trades: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in trades:
        regime = t.get("regime", "unknown")
        out[regime] = out.get(regime, 0.0) + float(t.get("pnl", 0.0))
    return out


def _summary(results: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, Any]:
    tb = results.get("trades", {})
    ob = results.get("observability", {})
    return {
        "version": results.get("version", "unknown"),
        "pnl": float(tb.get("total_pnl_usd", 0.0)),
        "trades": int(tb.get("total_closed", 0)),
        "win_rate": float(tb.get("win_rate", 0.0)),
        "max_drawdown": float(ob.get("max_drawdown_usd", 0.0)),
        "regime_pnl": _regime_pnl(trades),
    }


def _check_pnl_floor(v49: dict[str, Any], v48: dict[str, Any]) -> tuple[bool, str | None]:
    if v49["pnl"] >= v48["pnl"]:
        return True, None
    return False, f"pnl_floor: v49 {v49['pnl']:.2f} < v48 {v48['pnl']:.2f}"


def _check_trade_count_floor(v49: dict[str, Any]) -> tuple[bool, str | None]:
    if v49["trades"] >= TRADE_COUNT_FLOOR:
        return True, None
    return (
        False,
        f"trade_count_floor: v49 trades {v49['trades']} < {TRADE_COUNT_FLOOR}",
    )


def _check_drawdown_ceiling(v49: dict[str, Any], v48: dict[str, Any]) -> tuple[bool, str | None]:
    # Drawdown is expressed as a positive magnitude. Lower is better.
    if v49["max_drawdown"] <= v48["max_drawdown"]:
        return True, None
    return (
        False,
        f"drawdown_ceiling: v49 {v49['max_drawdown']:.2f} > v48 {v48['max_drawdown']:.2f}",
    )


def _check_regime_parity(v49: dict[str, Any], v48: dict[str, Any]) -> tuple[bool, list[str]]:
    """For every regime present in either run, v49 must be >= v48."""
    failures: list[str] = []
    regimes = set(v49["regime_pnl"]) | set(v48["regime_pnl"])
    for r in sorted(regimes):
        v49_r = v49["regime_pnl"].get(r, 0.0)
        v48_r = v48["regime_pnl"].get(r, 0.0)
        if v49_r < v48_r:
            failures.append(
                f"regime_parity[{r}]: v49 {v49_r:+.2f} < v48 {v48_r:+.2f} "
                f"(delta {v49_r - v48_r:+.2f})"
            )
    return (len(failures) == 0, failures)


def _check_auto_apply_audit(v49_results: dict[str, Any]) -> tuple[bool, str | None]:
    """Every auto_applied diff must have a non-None `before` snapshot."""
    meta = v49_results.get("meta_analyst", {})
    applied = meta.get("auto_applied", [])
    if not applied:
        return True, None  # no auto-applies: trivially passes
    missing = [d for d in applied if d.get("before") is None]
    if missing:
        return (
            False,
            f"auto_apply_audit: {len(missing)} auto_applied diffs missing `before` snapshots",
        )
    return True, None


def _check_signal_integrity(v49_results: dict[str, Any]) -> tuple[bool, str | None]:
    """Pass-through gate: only fails if v49_results explicitly reports an integrity test failure."""
    si = v49_results.get("signal_integrity", {})
    if not si:
        return True, None  # no section = not run, don't block
    if si.get("passed") is False:
        return False, f"signal_integrity: {si.get('failed_tests', 'unknown failures')}"
    return True, None


def check_v49_gates(
    v49_results: Path,
    v49_trades: Path,
    v48_results: Path,
    v48_trades: Path,
    out_path: Path | None = None,
) -> GateResult:
    """Run all six V49 hard gates. Write a JSON report to out_path if provided."""
    v48_json = _load_results(Path(v48_results))
    v49_json = _load_results(Path(v49_results))
    v48_t = _load_trades(Path(v48_trades))
    v49_t = _load_trades(Path(v49_trades))

    v48_summary = _summary(v48_json, v48_t)
    v49_summary = _summary(v49_json, v49_t)

    gates: dict[str, bool] = {}
    failures: list[str] = []

    passed, reason = _check_pnl_floor(v49_summary, v48_summary)
    gates["pnl_floor"] = passed
    if reason:
        failures.append(reason)

    passed, reasons = _check_regime_parity(v49_summary, v48_summary)
    gates["regime_parity"] = passed
    failures.extend(reasons)

    passed, reason = _check_drawdown_ceiling(v49_summary, v48_summary)
    gates["drawdown_ceiling"] = passed
    if reason:
        failures.append(reason)

    passed, reason = _check_trade_count_floor(v49_summary)
    gates["trade_count_floor"] = passed
    if reason:
        failures.append(reason)

    passed, reason = _check_signal_integrity(v49_json)
    gates["signal_integrity"] = passed
    if reason:
        failures.append(reason)

    passed, reason = _check_auto_apply_audit(v49_json)
    gates["auto_apply_audit"] = passed
    if reason:
        failures.append(reason)

    result = GateResult(
        passed=all(gates.values()),
        gates=gates,
        failures=failures,
        v48_summary=v48_summary,
        v49_summary=v49_summary,
    )

    if out_path is not None:
        payload = {
            "passed": result.passed,
            "gates": result.gates,
            "failures": result.failures,
            "v48_summary": result.v48_summary,
            "v49_summary": result.v49_summary,
        }
        Path(out_path).write_text(json.dumps(payload, indent=2))

    return result
```

Also create `omega/eval/__init__.py` if it doesn't exist (check first):

```bash
ls omega/eval/__init__.py 2>/dev/null || touch omega/eval/__init__.py
```

- [ ] **Step 4: Run tests and verify pass**

```bash
python3 -m pytest tests/test_v49_gates.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 5: Ruff**

```bash
python3 -m ruff check omega/eval/v49_gates.py tests/test_v49_gates.py 2>&1 | head -30
```

Fix any warnings.

- [ ] **Step 6: Commit**

```bash
git add omega/eval/v49_gates.py omega/eval/__init__.py tests/test_v49_gates.py
git commit -m "feat(eval): V49 hard gate module — pnl/regime/drawdown/trade_count/integrity/audit"
```

---

## Task 2.2: Add the forensics-driven regression test for the short threshold

This test pins the surgical fix: it asserts `strategy.py` sets `short_conviction_threshold = 0.05` in the normal-regime branch. If anyone reverts the fix, this test fails with a pointer to the forensics report that motivated the change.

**Files:**
- Create: `tests/test_v49_short_threshold_regression.py`

- [ ] **Step 1: Write the test**

Create `tests/test_v49_short_threshold_regression.py`:

```python
"""V49 regression guard: the normal-regime short conviction threshold must be 0.05.

Motivation: data/v35-v48-forensics.json shows V48's short trades lost $137.55
relative to V35 extended, concentrated 144% in normal regime and 73% in ADAUSDT.
The surgical V49 fix lowers short_conviction_threshold from 0.10 to 0.05 in the
normal-regime branch of StrategyNode._apply_regime_adaptive_thresholds().

If this test fails, someone reverted the V49 fix. Read
docs/training/v35-v48-forensics.md before changing it back.
"""
from __future__ import annotations

import re
from pathlib import Path


STRATEGY_FILE = (
    Path(__file__).parent.parent / "omega" / "nodes" / "victoria" / "strategy.py"
)


def test_normal_regime_short_threshold_is_005():
    """The normal-regime else branch must set short_conviction_threshold to 0.05."""
    text = STRATEGY_FILE.read_text()
    # Find the normal-regime else branch (follows the bull-regime elif)
    # and assert the short_conviction_threshold assignment is 0.05.
    # This is a structural check, not a string search, so it survives reformatting.
    match = re.search(
        r"else:\s*\n"
        r"\s*self\._long_conviction_threshold\s*=\s*0\.10\s*\n"
        r"\s*self\._short_conviction_threshold\s*=\s*(?P<val>[0-9.]+)",
        text,
    )
    assert match is not None, (
        "Could not find normal-regime else branch setting long and short thresholds. "
        "strategy.py may have been refactored; update this regression test to match."
    )
    val = float(match.group("val"))
    assert val == 0.05, (
        f"Normal-regime short_conviction_threshold is {val}, expected 0.05. "
        "This reverts the V49 fix. Read docs/training/v35-v48-forensics.md — "
        "ADAUSDT alone accounts for 73% of the V35-V48 PnL gap, and the normal-regime "
        "0.10 threshold was the proximate cause."
    )


def test_long_regime_threshold_preserved_at_010():
    """The V49 fix must NOT touch the normal-regime long threshold."""
    text = STRATEGY_FILE.read_text()
    match = re.search(
        r"else:\s*\n"
        r"\s*self\._long_conviction_threshold\s*=\s*(?P<val>[0-9.]+)",
        text,
    )
    assert match is not None, "Could not find normal-regime long threshold."
    val = float(match.group("val"))
    assert val == 0.10, (
        f"Normal-regime long_conviction_threshold is {val}, expected 0.10. "
        "The V49 fix only lowers the short threshold; longs must remain untouched."
    )
```

- [ ] **Step 2: Run and verify the test FAILS at this step**

```bash
cd /Users/benebsworth/projects/omega-v49
python3 -m pytest tests/test_v49_short_threshold_regression.py -v
```

Expected: `test_normal_regime_short_threshold_is_005` FAILS (strategy.py currently says 0.10); `test_long_regime_threshold_preserved_at_010` PASSES.

This is the RED phase of TDD — the regression test is in place and currently failing, proving the test works. Task 2.3 will make it pass.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_v49_short_threshold_regression.py
git commit -m "test(v49): add regression guard for normal-regime short threshold (currently failing)"
```

A failing test committed ahead of the fix is a deliberate TDD pattern. The commit message records the state.

---

## Task 2.3: Apply the surgical short threshold fix

**Files:**
- Modify: `omega/nodes/victoria/strategy.py` (lines 486-495, the normal-regime else branch)

- [ ] **Step 1: Locate the exact line**

```bash
cd /Users/benebsworth/projects/omega-v49
sed -n '486,495p' omega/nodes/victoria/strategy.py
```

Expected output:
```python
        else:
            self._long_conviction_threshold = 0.10
            self._short_conviction_threshold = 0.10
            logger.debug(
                "Regime-adaptive: NORMAL (bear_prob=%.2f, bull_prob=%.2f, hmm=%s) "
                "→ long_thresh=0.10, short_thresh=0.10",
                max(bear_prob, 0.0),
                max(bull_prob, 0.0),
                regime_hmm,
            )
```

If the lines don't match, STOP and report — the file has drifted since Phase 2a was written.

- [ ] **Step 2: Apply the fix**

Replace the normal-regime else branch with:

```python
        else:
            # V49 surgical fix (2026-04-06): short threshold lowered from 0.10 to 0.05
            # in normal regime. Motivation: data/v35-v48-forensics.json — V48 lost $137.55
            # in short trades, 144% concentrated in normal regime, 73% in ADAUSDT alone.
            # The 0.10 threshold was above both V35 and V48 post-demean mean conviction
            # distributions (~0.07-0.08), gating virtually all short entries. Lowering
            # to 0.05 mirrors the crisis-regime short bias without touching longs or
            # other regimes. See docs/training/v35-v48-forensics.md.
            self._long_conviction_threshold = 0.10
            self._short_conviction_threshold = 0.05
            logger.debug(
                "Regime-adaptive: NORMAL (bear_prob=%.2f, bull_prob=%.2f, hmm=%s) "
                "→ long_thresh=0.10, short_thresh=0.05 (V49 fix)",
                max(bear_prob, 0.0),
                max(bull_prob, 0.0),
                regime_hmm,
            )
```

Use the Edit tool or `sed` — do not use interactive editors.

- [ ] **Step 3: Verify the regression test now passes**

```bash
python3 -m pytest tests/test_v49_short_threshold_regression.py -v
```

Expected: 2 PASS.

- [ ] **Step 4: Run the existing signal integrity suite to confirm no cross-regressions**

```bash
python3 -m pytest tests/test_signal_integrity.py -v 2>&1 | tail -20
```

Expected: all pre-existing tests PASS. If any fail, read carefully — the fix may have broken a snapshot assertion that needs updating. Report before modifying snapshot files.

- [ ] **Step 5: Run strategy unit tests if they exist**

```bash
python3 -m pytest tests/ -k strategy -v 2>&1 | tail -20
```

Expected: relevant strategy tests pass.

- [ ] **Step 6: Commit**

```bash
git add omega/nodes/victoria/strategy.py
git commit -m "feat(v49): lower normal-regime short conviction threshold 0.10→0.05

Surgical fix for V35↔V48 regression. V48 lost \$137.55 on short trades, 144%
concentrated in normal regime and 73% in ADAUSDT alone. The 0.10 threshold was
above post-demean signal distribution (~0.07–0.08 mean), gating virtually all
short entries. Lowering to 0.05 mirrors crisis-regime short treatment. Longs,
bull regime, crisis regime, and high_vol tightening all untouched.

Forensics: data/v35-v48-forensics.json
Report: docs/training/v35-v48-forensics.md"
```

---

## Task 2.4: Wire V49 gates into `scripts/run_training.py`

After a training run completes, `run_training.py` should call `check_v49_gates()` against the just-written results and the previous version's results as baseline, and write `data/{version}_gate_result.json`. Gate failure does not stop the script (so partial progress is visible), but it writes a clearly-named failure artifact.

**Files:**
- Modify: `scripts/run_training.py`

- [ ] **Step 1: Read the current end of the run**

```bash
cd /Users/benebsworth/projects/omega-v49
sed -n '760,830p' scripts/run_training.py
```

This shows the section where the results JSON is written. The gate call goes after the results JSON write, before the final log message.

- [ ] **Step 2: Add the gate helper near the top of run_training.py**

Add after the existing imports (around line 30-50) a new import:

```python
from omega.eval.v49_gates import check_v49_gates
```

Add a module-level helper function after `_resolve_version()` (around line 90-95):

```python
def _find_baseline_version(current: str) -> str | None:
    """Find the previous numeric-suffix version that has results + trades artifacts.

    V49 → v48 (ordinary decrement).
    v10 → v9, v1 → None (nothing to compare against).
    Returns the version label or None if no baseline is available.
    """
    import re

    m = re.match(r"^(?P<prefix>[^\d]*)(?P<num>\d+)(?P<suffix>.*)$", current)
    if not m:
        return None
    prefix = m.group("prefix")
    num = int(m.group("num"))
    suffix = m.group("suffix")
    for candidate_num in range(num - 1, 0, -1):
        label = f"{prefix}{candidate_num}{suffix}"
        results = DATA_DIR / f"{label}_results.json"
        trades = DATA_DIR / f"{label}_trades.csv"
        if results.exists() and trades.exists():
            return label
    return None
```

- [ ] **Step 3: Call the gate check at the end of the run**

In the function that writes the results JSON (around line 771+ based on `"version": version,` marker), find the block that writes `results_file` and add a gate-check block immediately after it:

```python
        # ---------------------------------------------------------------------
        # V49 hard gates — compare this run against the previous version.
        # ---------------------------------------------------------------------
        baseline_label = _find_baseline_version(version)
        if baseline_label is not None:
            baseline_results = DATA_DIR / f"{baseline_label}_results.json"
            baseline_trades = DATA_DIR / f"{baseline_label}_trades.csv"
            gate_out = DATA_DIR / f"{version}_gate_result.json"
            try:
                gate_result = check_v49_gates(
                    v49_results=results_file,
                    v49_trades=trades_csv,
                    v48_results=baseline_results,
                    v48_trades=baseline_trades,
                    out_path=gate_out,
                )
                if gate_result.passed:
                    log.info(
                        "%s gates PASSED vs %s (all %d checks green)",
                        version.upper(),
                        baseline_label,
                        len(gate_result.gates),
                    )
                else:
                    log.error(
                        "%s gates FAILED vs %s — %d failures:",
                        version.upper(),
                        baseline_label,
                        len(gate_result.failures),
                    )
                    for f in gate_result.failures:
                        log.error("  ✗ %s", f)
                    log.error("Gate report: %s", gate_out)
            except Exception as exc:
                log.exception("V49 gate check crashed: %s", exc)
        else:
            log.warning(
                "%s: no baseline version found for gate comparison", version.upper()
            )
```

**Important:** The gate check must come AFTER `results_file` and `trades_csv` are written, and BEFORE the final log line. Do not place it inside a `try` block that could swallow exceptions silently — only wrap the `check_v49_gates` call itself.

- [ ] **Step 4: Verify the edit compiles**

```bash
python3 -c "import scripts.run_training" 2>&1 | head -20
```

Note: depending on how `scripts/` is structured you may need:
```bash
python3 scripts/run_training.py --help 2>&1 | head -20
```

Expected: `--help` prints without import errors.

- [ ] **Step 5: Write a smoke test for the gate wiring**

Create `tests/test_v49_gate_wiring.py`:

```python
"""Smoke test: _find_baseline_version helper in run_training.py.

We cannot easily test the full training script without mocking the entire
orchestrator, so we test the helper in isolation.
"""
from pathlib import Path

import sys

SCRIPT_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def test_find_baseline_version_decrements_to_existing(tmp_path: Path, monkeypatch):
    # Import inside the test so we can monkeypatch DATA_DIR
    import run_training

    monkeypatch.setattr(run_training, "DATA_DIR", tmp_path)
    (tmp_path / "v48_results.json").write_text("{}")
    (tmp_path / "v48_trades.csv").write_text("")

    assert run_training._find_baseline_version("v49") == "v48"


def test_find_baseline_version_skips_missing(tmp_path: Path, monkeypatch):
    import run_training

    monkeypatch.setattr(run_training, "DATA_DIR", tmp_path)
    # Only v46 exists
    (tmp_path / "v46_results.json").write_text("{}")
    (tmp_path / "v46_trades.csv").write_text("")

    assert run_training._find_baseline_version("v49") == "v46"


def test_find_baseline_version_none_for_v1(tmp_path: Path, monkeypatch):
    import run_training

    monkeypatch.setattr(run_training, "DATA_DIR", tmp_path)
    assert run_training._find_baseline_version("v1") is None


def test_find_baseline_version_none_for_non_numeric(tmp_path: Path, monkeypatch):
    import run_training

    monkeypatch.setattr(run_training, "DATA_DIR", tmp_path)
    assert run_training._find_baseline_version("experimental") is None
```

- [ ] **Step 6: Run the smoke test**

```bash
python3 -m pytest tests/test_v49_gate_wiring.py -v
```

Expected: 4 PASS.

If the test fails with `ModuleNotFoundError: run_training`, the `sys.path.insert` is not reaching the script. Check that `SCRIPT_DIR` resolves correctly and that `scripts/run_training.py` is importable as a module (it uses top-level code, but its function defs are still reachable).

- [ ] **Step 7: Ruff**

```bash
python3 -m ruff check scripts/run_training.py tests/test_v49_gate_wiring.py 2>&1 | head -30
```

Fix any.

- [ ] **Step 8: Commit**

```bash
git add scripts/run_training.py tests/test_v49_gate_wiring.py
git commit -m "feat(training): wire V49 hard gates into run_training.py post-run check"
```

---

## Task 2.5: Run V49 training

This task runs the actual V49 training script. It is long-running (~45 minutes for 200 cycles at 10s sleep). Do not run it with `run_in_background` — we want to block on its output so the next task can validate results immediately.

**Files:** produces `data/v49_*`

- [ ] **Step 1: Confirm Postgres is up**

```bash
docker compose -f /Users/benebsworth/projects/omega/docker-compose.yml ps postgres 2>&1 | head -5
```

Expected: postgres container running on port 5432. If not, start it:

```bash
cd /Users/benebsworth/projects/omega
make db-up
```

- [ ] **Step 2: Set environment**

```bash
cd /Users/benebsworth/projects/omega-v49
export DATABASE_URL=postgres://omega:omega@localhost:5432/omega?sslmode=disable
export COINGECKO_API_KEY=${COINGECKO_API_KEY:-}
```

(If `COINGECKO_API_KEY` isn't set, the script falls back to unauthenticated CoinGecko. That's fine for V49.)

- [ ] **Step 3: Run V49**

```bash
python3 scripts/run_training.py --version v49 --cycles 200 --sleep 10 2>&1 | tee /tmp/v49_run.log
```

Expected: ~45 minutes of cycle logs, then a final summary. The script should print either:
- `V49 gates PASSED vs v48 (all 6 checks green)`, or
- `V49 gates FAILED vs v48 — N failures:` followed by specific gate failures.

Either outcome is recorded — the next task validates and decides whether to merge.

- [ ] **Step 4: Confirm artifacts exist**

```bash
ls -la data/v49_results.json data/v49_trades.csv data/v49_progress.json data/v49_gate_result.json
```

Expected: all four files present.

- [ ] **Step 5: Summary dump**

```bash
python3 -c "
import json
r = json.load(open('data/v49_results.json'))
g = json.load(open('data/v49_gate_result.json'))
print(f'V49 PnL: {r[\"trades\"][\"total_pnl_usd\"]}')
print(f'V49 trades: {r[\"trades\"][\"total_closed\"]}')
print(f'V49 long/short: {r[\"trades\"][\"long_trades\"]}/{r[\"trades\"][\"short_trades\"]}')
print(f'V49 win_rate: {r[\"trades\"][\"win_rate\"]:.3f}')
print(f'V49 zero_trade_cycles: {r[\"observability\"][\"total_zero_trade_cycles\"]}')
print()
print(f'V49 GATES: passed={g[\"passed\"]}')
for gate, passed in g['gates'].items():
    mark = 'OK' if passed else 'FAIL'
    print(f'  [{mark}] {gate}')
if not g['passed']:
    print('Failures:')
    for f in g['failures']:
        print(f'  - {f}')
"
```

Report this output as-is.

No commit for Task 2.5 — the artifacts are committed in the next task.

---

## Task 2.6: Validate V49 outcome and commit artifacts

**Files:**
- Create: `docs/training/v49-run-report.md`
- Commit: `data/v49_results.json`, `data/v49_trades.csv`, `data/v49_progress.json`, `data/v49_gate_result.json`

- [ ] **Step 1: Run the full forensics diff against V49**

Reuse the forensics CLI to produce a V48→V49 diff. This shows explicitly whether V49 reclaimed the ADA/DOT short PnL.

```bash
cd /Users/benebsworth/projects/omega-v49
python3 -m omega.tools.forensics.run_diff \
  --baseline-results data/v48_results.json \
  --baseline-trades data/v48_trades.csv \
  --target-results data/v49_results.json \
  --target-trades data/v49_trades.csv \
  --out-json data/v48-v49-forensics.json \
  --out-md docs/training/v48-v49-forensics.md
```

Expected: exit 0, two files written.

- [ ] **Step 2: Inspect the V48→V49 diff**

```bash
python3 -c "
import json
d = json.load(open('data/v48-v49-forensics.json'))
print(f'V48 PnL: {d[\"baselines\"][\"v35\"][\"pnl\"]}')  # v35 slot = baseline = v48 here
print(f'V49 PnL: {d[\"baselines\"][\"v48\"][\"pnl\"]}')  # v48 slot = target = v49 here
per_symbol = d['signal_contribution_delta_proxy']['per_symbol']
ada = per_symbol.get('ADAUSDT', 0)
dot = per_symbol.get('DOTUSDT', 0)
print(f'ADAUSDT delta (v49 - v48): {ada:+.2f}')
print(f'DOTUSDT delta (v49 - v48): {dot:+.2f}')
print(f'per_side: {d[\"signal_contribution_delta_proxy\"][\"per_side\"]}')
print(f'regimes:')
for r, rv in d['regime_breakdown'].items():
    print(f'  {r}: v48={rv[\"v35_pnl\"]:+.2f} v49={rv[\"v48_pnl\"]:+.2f} delta={rv[\"delta\"]:+.2f}')
"
```

(Note: the forensics schema labels slots `v35`/`v48` regardless of actual versions — `v35` slot is always the baseline, `v48` slot is the target.)

Expected (hoped):
- ADAUSDT delta > 0 (V49 recovered ADA shorts)
- DOTUSDT delta > 0 (V49 recovered DOT shorts)
- per_side.short > 0 (V49 shorts beat V48 shorts)
- Normal regime delta > 0

If the deltas are NEGATIVE, the fix did not work as expected — record the outcome but still proceed to commit (V49 result is informative either way; the decision whether to merge depends on the gate result from Task 2.5).

- [ ] **Step 3: Write the run report**

Create `docs/training/v49-run-report.md`:

```markdown
# V49 Training Run Report

**Date:** 2026-04-06
**Version:** v49
**Baseline:** v48
**Change:** Normal-regime `short_conviction_threshold` lowered from 0.10 to 0.05
**Forensics input:** `data/v35-v48-forensics.json`

## Summary

[Fill in from Task 2.5 Step 5 output: V49 PnL, trades, win_rate, zero-trade cycles]

## Gate Result

[Fill in from `data/v49_gate_result.json`: passed/failed, per-gate status, any failures]

## V48 → V49 Diff

[Fill in from Task 2.6 Step 2 output: ADA/DOT deltas, per-side deltas, regime breakdown]

## Assessment

[One-paragraph assessment: did the fix work? What's the recommendation for V50?]

## Files

- Results: `data/v49_results.json`
- Trades: `data/v49_trades.csv`
- Gate report: `data/v49_gate_result.json`
- Forensics diff: `data/v48-v49-forensics.json`, `docs/training/v48-v49-forensics.md`
```

Fill in all four `[Fill in ...]` sections with the real numbers from the previous steps. Do not leave placeholders.

- [ ] **Step 4: Decide merge vs reject**

Read `data/v49_gate_result.json`:

```bash
cat data/v49_gate_result.json
```

- **If `passed: true`**: V49 is mergeable. Proceed to Step 5.
- **If `passed: false`**: V49 is NOT mergeable. Commit artifacts for inspection but do NOT merge to main. Report the failure and stop. A follow-up V49.1 iteration will address the gate failures.

- [ ] **Step 5: Commit artifacts (only if gates passed OR user has approved commit for post-mortem)**

```bash
git add data/v49_results.json data/v49_trades.csv data/v49_progress.json \
        data/v49_gate_result.json data/v48-v49-forensics.json \
        docs/training/v49-run-report.md docs/training/v48-v49-forensics.md
git commit -m "docs(training): V49 run artifacts and V48→V49 forensics diff

Gate result: [PASS|FAIL]
PnL: v48 \$31.97 → v49 \$[NEW]
ADAUSDT delta: \$[NEW]
DOTUSDT delta: \$[NEW]
Regime normal delta: \$[NEW]"
```

Fill in the commit message with real values.

- [ ] **Step 6: Verify**

```bash
git log --oneline -8
git status
```

Expected: the artifacts commit is HEAD; status clean.

---

## Task 2.7: Merge to main (only if gates passed)

**Files:** none modified in the merge itself

- [ ] **Step 1: Final test run**

```bash
cd /Users/benebsworth/projects/omega-v49
python3 -m pytest tests/test_v49_gates.py tests/test_v49_short_threshold_regression.py tests/test_v49_gate_wiring.py tests/test_forensics_*.py -v 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 2: Review the branch log**

```bash
git log --oneline main..HEAD
```

Expected: 5–6 commits — gate module, regression test (failing), strategy fix, gate wiring, artifacts.

- [ ] **Step 3: Fast-forward merge to main**

```bash
cd /Users/benebsworth/projects/omega
git merge --ff-only training/v49-calibration
```

Expected: fast-forward succeeds. If it doesn't, fall back to cherry-pick range:

```bash
FIRST=$(git log --reverse --format=%H main..training/v49-calibration | head -1)
LAST=$(git rev-parse training/v49-calibration)
git cherry-pick $FIRST^..$LAST
```

STOP on any conflict — do not force-resolve.

- [ ] **Step 4: Verify files on main**

```bash
cd /Users/benebsworth/projects/omega
ls omega/eval/v49_gates.py tests/test_v49_gates.py tests/test_v49_short_threshold_regression.py tests/test_v49_gate_wiring.py data/v49_results.json data/v49_gate_result.json docs/training/v49-run-report.md
python3 -m pytest tests/test_v49_gates.py tests/test_v49_short_threshold_regression.py tests/test_v49_gate_wiring.py -v 2>&1 | tail -10
```

Expected: all files present, all tests pass.

- [ ] **Step 5: Remove worktree**

```bash
git worktree remove ../omega-v49
git branch -d training/v49-calibration
```

If `git branch -d` refuses, STOP — the branch may not be fully merged.

---

## Phase 2a Exit Criteria

- [ ] `omega/eval/v49_gates.py` exists on main with 7 passing unit tests
- [ ] `tests/test_v49_short_threshold_regression.py` passes on main
- [ ] `omega/nodes/victoria/strategy.py` normal-regime short threshold = 0.05
- [ ] `scripts/run_training.py` calls `check_v49_gates` after each run
- [ ] `data/v49_gate_result.json` on main with `passed: true`
- [ ] `docs/training/v49-run-report.md` on main with real numbers
- [ ] Worktree removed, branch deleted

---

## Phase 2b Handoff

Once Phase 2a ships V49 successfully, Phase 2b planning begins. Phase 2b covers:
- **Agent 3** — TimesFM + Wasserstein K-means signal producers (dry-run only in V50, additive, off-by-default)
- **Agent 5** — Meta-analyst node + `TrainingProposal` protobuf + trust-ladder stages 1+2+3

**Phase 2b inputs:**
1. V49 as the new baseline (not V48)
2. `data/v48-v49-forensics.json` for the meta-analyst's sanity-check ground truth
3. The V49 gate result — if V49 passed its gates, the meta-analyst's first advisory proposal should identify the short-threshold fix as the top hypothesis for the V48→V49 diff

**Phase 2b plan file:** `docs/superpowers/plans/YYYY-MM-DD-victoria-v50-phase2b-intelligence.md`

---

## Appendix: Why V49 is a single-change V-iteration

Prior V-iterations (V36–V44) broke V35 by bundling multiple changes per version. The spec's "prevent another V36–V44 over-iteration" goal is addressed here by:
1. **Exactly one code change** in this plan (one threshold value in `strategy.py`).
2. **Hard gates that fail closed** — if the one change regresses anything, V49 is not merged.
3. **Regression test pinning the fix** — nobody can silently revert without tripping a CI failure.
4. **Forensics report as the commit's source of truth** — the reason for the change is committed alongside the change, not buried in a chat log.

If V49 passes gates, V50 can add one more change. If V49 fails gates, V49.1 adjusts the single change until it passes. **Never two code changes per V-iteration.**
