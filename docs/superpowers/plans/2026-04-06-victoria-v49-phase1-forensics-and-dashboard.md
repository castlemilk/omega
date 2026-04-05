# Victoria V49 — Phase 1 Implementation Plan (Forensics + Dashboard Wiring)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the V35↔V48 forensics artifact that unblocks V49 calibration, and wire three dashboard pages off mock data so the training loop is visually auditable during the V49 run.

**Architecture:** Two independent agent workstreams, each in its own git worktree off `main`. Agent 1 (forensics) produces `data/v35-v48-forensics.json` as a read-only analysis. Agent 4 (dashboard wiring) moves `DecisionTrace.tsx`, `NodeHealth.tsx`, and `VictoriaTrades.tsx` off mock data onto real Connect-RPC endpoints. Neither agent touches Python signal/strategy code. Phase 2 (Agents 2, 3, 5) is deliberately deferred — it will be planned once the forensics artifact exists so parameter choices are concrete, not speculative.

**Tech Stack:**
- Python 3.11+, pandas, stdlib json (no new Python deps)
- Go 1.25+, Connect-RPC (existing `OrchestratorService`)
- React 18, Connect-ES client, shadcn, Vite, Vitest
- Generated proto types in `dashboard/src/gen/omega/v1/`

**Spec:** `docs/superpowers/specs/2026-04-05-victoria-v49-meta-analyst-dispatch-design.md`

---

## Scope & Exclusions

**In scope (Phase 1):**
- Agent 1: Forensics tool, forensics JSON+MD artifacts, regression-safe tests
- Agent 4: Wire DecisionTrace, NodeHealth, VictoriaTrades to real data; contract tests

**Out of scope (Phase 2, written later):**
- Agent 2 (calibration + V49 training run)
- Agent 3 (TimesFM + Wasserstein)
- Agent 5 (meta-analyst node + TrainingProposal proto)

**Assumption validated by file inspection:**
- `data/v35_extended_results.json`, `data/v35_extended_trades.csv`, `data/v35_extended_progress.json` exist (500-cycle V35 run dated 2026-04-01). Agent 1 uses these as the V35 baseline; no re-run needed for Phase 1.
- `data/v48_results.json`, `data/v48_trades.csv`, `data/v48_progress.json` exist.
- Trade CSV columns: `cycle, timestamp, symbol, side, size, entry_price, exit_price, pnl, slippage, hold_cycles, conviction, regime, sit_out_reason`.
- Dashboard pages `DecisionTrace.tsx` (768 lines), `NodeHealth.tsx` (612 lines), `VictoriaTrades.tsx` (650 lines) already exist and render mock data.

---

## File Structure

### Agent 1 creates
- `omega/tools/forensics/__init__.py` — package marker
- `omega/tools/forensics/run_diff.py` — CLI entry: `python -m omega.tools.forensics.run_diff --v35 data/v35_extended --v48 data/v48`
- `omega/tools/forensics/loader.py` — load results JSON + trades CSV into typed dataclasses
- `omega/tools/forensics/signal_delta.py` — per-signal contribution delta computation
- `omega/tools/forensics/conviction_histogram.py` — HOLD vs trade band bucketing
- `omega/tools/forensics/skipped_trades.py` — V35 trades V48 missed, with reason codes
- `omega/tools/forensics/hypothesis_ranker.py` — rank top-3 structural differences
- `omega/tools/forensics/regime_breakdown.py` — per-regime PnL delta
- `omega/tools/forensics/writer.py` — emit JSON + MD reports
- `tests/test_forensics_loader.py`
- `tests/test_forensics_signal_delta.py`
- `tests/test_forensics_conviction_histogram.py`
- `tests/test_forensics_skipped_trades.py`
- `tests/test_forensics_hypothesis_ranker.py`
- `tests/test_forensics_writer.py`
- `tests/test_forensics_cli.py` — integration test of the full CLI
- `tests/fixtures/forensics/` — synthetic mini-V35 and mini-V48 fixtures

### Agent 1 writes (artifacts, not code)
- `data/v35-v48-forensics.json`
- `docs/training/v35-v48-forensics.md`

### Agent 4 creates
- `dashboard/src/api/decisions.ts` — Connect-ES wrapper for decision trace queries
- `dashboard/src/api/node_health.ts` — wrapper for `/health-score` + `/lifecycle`
- `dashboard/src/api/victoria_trades.ts` — wrapper for Victoria trades endpoint
- `dashboard/src/pages/__tests__/DecisionTrace.test.tsx`
- `dashboard/src/pages/__tests__/NodeHealth.test.tsx`
- `dashboard/src/pages/__tests__/VictoriaTrades.test.tsx`

### Agent 4 modifies
- `dashboard/src/pages/DecisionTrace.tsx` — swap mock data source for real API
- `dashboard/src/pages/NodeHealth.tsx` — swap mock data source for real API
- `dashboard/src/pages/VictoriaTrades.tsx` — swap mock data source for real API

### Agent 4 modifies (Go side, only if the needed endpoints don't exist)
- `internal/handler/orchestrator.go` (or wherever `OrchestratorService` / `VictoriaService` is implemented) — add a `ListVictoriaTrades` RPC method if missing
- `proto/omega/v1/victoria_service.proto` — add `ListVictoriaTrades` message + rpc if missing

---

# AGENT 1 — FORENSICS WORKSTREAM

**Branch:** `forensics/v35-v48-diff`
**Owner:** dispatched agent 1
**Blocking dependency for:** Phase 2 Agents 2, 3, 5

### Task 1.0: Create worktree and baseline

**Files:** none modified

- [ ] **Step 1: Create worktree**

Run:
```bash
cd /Users/benebsworth/projects/omega
git worktree add ../omega-forensics forensics/v35-v48-diff main
cd ../omega-forensics
```

Expected: new worktree at `/Users/benebsworth/projects/omega-forensics` on branch `forensics/v35-v48-diff`.

- [ ] **Step 2: Confirm V35 and V48 artifacts are present**

Run:
```bash
ls data/v35_extended_results.json data/v35_extended_trades.csv data/v48_results.json data/v48_trades.csv
```

Expected: all four files listed. If any missing, **stop** and report; this plan's assumption is invalidated and Agent 1 must re-run V35 (out of Phase 1 scope — escalate).

- [ ] **Step 3: Create package directories**

Run:
```bash
mkdir -p omega/tools/forensics tests/fixtures/forensics docs/training
touch omega/tools/__init__.py omega/tools/forensics/__init__.py
```

- [ ] **Step 4: Commit the empty package**

```bash
git add omega/tools/__init__.py omega/tools/forensics/__init__.py
git commit -m "chore(forensics): scaffold tools package for V35-V48 diff"
```

---

### Task 1.1: Create synthetic fixtures for forensics tests

**Files:**
- Create: `tests/fixtures/forensics/mini_v35_results.json`
- Create: `tests/fixtures/forensics/mini_v35_trades.csv`
- Create: `tests/fixtures/forensics/mini_v48_results.json`
- Create: `tests/fixtures/forensics/mini_v48_trades.csv`

- [ ] **Step 1: Write mini V35 results fixture**

Create `tests/fixtures/forensics/mini_v35_results.json`:

```json
{
  "version": "mini_v35",
  "run": {"date": "2026-04-01T00:00:00+00:00", "cycles": 10, "sleep_seconds": 1.0, "elapsed_s": 10, "avg_cycle_s": 1.0, "cg_key_used": false, "db_url_used": false},
  "preflight": {"ok": true, "warnings": []},
  "intelligence": {"improve_calls": 0, "semantic_patterns_db": 0, "semantic_patterns_node": 0},
  "observability": {"metrics_jsonl": "/tmp/mini_v35.jsonl", "total_zero_trade_cycles": 2, "max_zero_streak": 1, "ring1_pass_rate_final": 1.0, "conviction_filter_rate": 0.2, "circuit_breaker_trips": 0, "final_vol_low_threshold": 0.2},
  "filters": {"stale_data": 0, "vol_low": 0, "vol_high": 0, "regime_uncertain": 0, "normal": 10},
  "trades": {"total_closed": 6, "long_trades": 4, "short_trades": 2, "open_positions": 0, "win_rate": 0.5, "total_pnl_usd": 120.0, "realised_pnl_engine": 120.0, "gross_profit": 180.0, "gross_loss": 60.0, "profit_factor": 3.0}
}
```

- [ ] **Step 2: Write mini V35 trades fixture**

Create `tests/fixtures/forensics/mini_v35_trades.csv`:

```csv
cycle,timestamp,symbol,side,size,entry_price,exit_price,pnl,slippage,hold_cycles,conviction,regime,sit_out_reason
1,2026-04-01T00:00:01+00:00,BTCUSDT,long,100,40000,40500,50.0,0,2,0.35,bull,normal
2,2026-04-01T00:00:02+00:00,ETHUSDT,long,100,2000,2030,30.0,0,2,0.28,bull,normal
3,2026-04-01T00:00:03+00:00,BTCUSDT,short,100,40500,40200,30.0,0,2,0.31,chop,normal
4,2026-04-01T00:00:04+00:00,SOLUSDT,long,100,100,101,10.0,0,2,0.22,bull,normal
5,2026-04-01T00:00:05+00:00,ETHUSDT,short,100,2030,2025,-5.0,0,2,0.19,bear,normal
6,2026-04-01T00:00:06+00:00,BTCUSDT,long,100,40200,40260,5.0,0,2,0.18,chop,normal
```

- [ ] **Step 3: Write mini V48 results fixture**

Create `tests/fixtures/forensics/mini_v48_results.json`:

```json
{
  "version": "mini_v48",
  "run": {"date": "2026-04-04T00:00:00+00:00", "cycles": 10, "sleep_seconds": 1.0, "elapsed_s": 10, "avg_cycle_s": 1.0, "cg_key_used": false, "db_url_used": false},
  "preflight": {"ok": true, "warnings": []},
  "intelligence": {"improve_calls": 0, "semantic_patterns_db": 0, "semantic_patterns_node": 0},
  "observability": {"metrics_jsonl": "/tmp/mini_v48.jsonl", "total_zero_trade_cycles": 7, "max_zero_streak": 4, "ring1_pass_rate_final": 1.0, "conviction_filter_rate": 0.58, "circuit_breaker_trips": 0, "final_vol_low_threshold": 0.2},
  "filters": {"stale_data": 0, "vol_low": 0, "vol_high": 0, "regime_uncertain": 0, "normal": 10},
  "trades": {"total_closed": 2, "long_trades": 1, "short_trades": 1, "open_positions": 0, "win_rate": 0.5, "total_pnl_usd": 15.0, "realised_pnl_engine": 15.0, "gross_profit": 20.0, "gross_loss": 5.0, "profit_factor": 4.0}
}
```

- [ ] **Step 4: Write mini V48 trades fixture**

Create `tests/fixtures/forensics/mini_v48_trades.csv`:

```csv
cycle,timestamp,symbol,side,size,entry_price,exit_price,pnl,slippage,hold_cycles,conviction,regime,sit_out_reason
3,2026-04-04T00:00:03+00:00,BTCUSDT,short,100,40500,40300,20.0,0,2,0.07,chop,normal
5,2026-04-04T00:00:05+00:00,ETHUSDT,short,100,2030,2029,-5.0,0,2,0.06,bear,normal
```

Note: V48 fixture has lower conviction values (~0.06–0.07) and fewer trades (2 vs 6) — mirrors the real V48 vs V35 pattern where post-demeaning magnitudes are ~5× smaller.

- [ ] **Step 5: Commit fixtures**

```bash
git add tests/fixtures/forensics/
git commit -m "test(forensics): add mini V35/V48 fixtures for diff tooling"
```

---

### Task 1.2: Loader module — parse results JSON + trades CSV

**Files:**
- Create: `omega/tools/forensics/loader.py`
- Create: `tests/test_forensics_loader.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_forensics_loader.py`:

```python
"""Tests for forensics data loader."""
from pathlib import Path

import pytest

from omega.tools.forensics.loader import RunArtifacts, load_run


FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def test_load_run_reads_results_json_and_trades_csv():
    run = load_run(
        results_path=FIXTURES / "mini_v35_results.json",
        trades_path=FIXTURES / "mini_v35_trades.csv",
    )
    assert isinstance(run, RunArtifacts)
    assert run.version == "mini_v35"
    assert run.total_pnl == 120.0
    assert run.win_rate == 0.5
    assert run.conviction_filter_rate == 0.2
    assert len(run.trades) == 6
    assert run.trades[0]["symbol"] == "BTCUSDT"
    assert run.trades[0]["pnl"] == 50.0


def test_load_run_computes_per_regime_pnl():
    run = load_run(
        results_path=FIXTURES / "mini_v35_results.json",
        trades_path=FIXTURES / "mini_v35_trades.csv",
    )
    # bull: 50 + 30 + 10 = 90; chop: 30 + 5 = 35; bear: -5
    assert run.regime_pnl["bull"] == pytest.approx(90.0)
    assert run.regime_pnl["chop"] == pytest.approx(35.0)
    assert run.regime_pnl["bear"] == pytest.approx(-5.0)


def test_load_run_handles_v48_shape():
    run = load_run(
        results_path=FIXTURES / "mini_v48_results.json",
        trades_path=FIXTURES / "mini_v48_trades.csv",
    )
    assert run.version == "mini_v48"
    assert run.total_pnl == 15.0
    assert len(run.trades) == 2
    assert run.zero_trade_cycles == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_forensics_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'omega.tools.forensics.loader'`.

- [ ] **Step 3: Write minimal implementation**

Create `omega/tools/forensics/loader.py`:

```python
"""Load Victoria training run artifacts (results JSON + trades CSV) into typed records."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunArtifacts:
    """Normalised view of a single training run's results + trades."""

    version: str
    total_pnl: float
    win_rate: float
    total_trades: int
    long_trades: int
    short_trades: int
    profit_factor: float
    zero_trade_cycles: int
    conviction_filter_rate: float
    trades: list[dict[str, Any]]
    regime_pnl: dict[str, float] = field(default_factory=dict)

    @property
    def trade_cycles(self) -> int:
        """Cycles on which at least one trade was opened."""
        return len({t["cycle"] for t in self.trades})


def _parse_trades_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        rows: list[dict[str, Any]] = []
        for row in reader:
            rows.append(
                {
                    "cycle": int(row["cycle"]),
                    "timestamp": row["timestamp"],
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "size": float(row["size"]),
                    "entry_price": float(row["entry_price"]),
                    "exit_price": float(row["exit_price"]),
                    "pnl": float(row["pnl"]),
                    "slippage": float(row["slippage"]),
                    "hold_cycles": int(row["hold_cycles"]),
                    "conviction": float(row["conviction"]),
                    "regime": row["regime"],
                    "sit_out_reason": row["sit_out_reason"],
                }
            )
    return rows


def _compute_regime_pnl(trades: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in trades:
        regime = t.get("regime", "unknown")
        out[regime] = out.get(regime, 0.0) + t["pnl"]
    return out


def load_run(results_path: Path, trades_path: Path) -> RunArtifacts:
    """Load a results JSON and trades CSV into a single RunArtifacts record."""
    with Path(results_path).open() as f:
        results = json.load(f)

    trades_block = results.get("trades", {})
    obs_block = results.get("observability", {})

    trades = _parse_trades_csv(Path(trades_path))
    regime_pnl = _compute_regime_pnl(trades)

    return RunArtifacts(
        version=results.get("version", "unknown"),
        total_pnl=float(trades_block.get("total_pnl_usd", 0.0)),
        win_rate=float(trades_block.get("win_rate", 0.0)),
        total_trades=int(trades_block.get("total_closed", 0)),
        long_trades=int(trades_block.get("long_trades", 0)),
        short_trades=int(trades_block.get("short_trades", 0)),
        profit_factor=float(trades_block.get("profit_factor", 0.0)),
        zero_trade_cycles=int(obs_block.get("total_zero_trade_cycles", 0)),
        conviction_filter_rate=float(obs_block.get("conviction_filter_rate", 0.0)),
        trades=trades,
        regime_pnl=regime_pnl,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_forensics_loader.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add omega/tools/forensics/loader.py tests/test_forensics_loader.py
git commit -m "feat(forensics): add RunArtifacts loader for results JSON + trades CSV"
```

---

### Task 1.3: Conviction histogram module

**Files:**
- Create: `omega/tools/forensics/conviction_histogram.py`
- Create: `tests/test_forensics_conviction_histogram.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_forensics_conviction_histogram.py`:

```python
"""Tests for conviction band histogram."""
from pathlib import Path

import pytest

from omega.tools.forensics.conviction_histogram import (
    ConvictionHistogram,
    compute_histogram,
)
from omega.tools.forensics.loader import load_run

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def test_histogram_reports_trade_and_hold_bands():
    v35 = load_run(
        FIXTURES / "mini_v35_results.json",
        FIXTURES / "mini_v35_trades.csv",
    )
    hist = compute_histogram(v35, hold_threshold=0.20)
    # v35 trades have convictions: 0.35, 0.28, 0.31, 0.22, 0.19, 0.18
    # trade band (>= 0.20): 4 trades; hold band (< 0.20): 2 trades
    assert isinstance(hist, ConvictionHistogram)
    assert hist.trade_band_count == 4
    assert hist.hold_band_count == 2
    assert hist.hold_band_pct == pytest.approx(2 / 6)
    assert hist.trade_band_pct == pytest.approx(4 / 6)


def test_histogram_empty_trades_returns_zero_pcts():
    v48 = load_run(
        FIXTURES / "mini_v48_results.json",
        FIXTURES / "mini_v48_trades.csv",
    )
    # Override trades list to empty
    v48.trades = []
    hist = compute_histogram(v48, hold_threshold=0.20)
    assert hist.trade_band_count == 0
    assert hist.hold_band_count == 0
    assert hist.trade_band_pct == 0.0
    assert hist.hold_band_pct == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_forensics_conviction_histogram.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `omega/tools/forensics/conviction_histogram.py`:

```python
"""Conviction band histogram — how many trades fall above/below a conviction threshold."""

from __future__ import annotations

from dataclasses import dataclass

from omega.tools.forensics.loader import RunArtifacts


@dataclass
class ConvictionHistogram:
    hold_threshold: float
    trade_band_count: int
    hold_band_count: int
    trade_band_pct: float
    hold_band_pct: float
    min_conviction: float
    max_conviction: float
    mean_conviction: float


def compute_histogram(run: RunArtifacts, hold_threshold: float) -> ConvictionHistogram:
    """Compute a conviction-band histogram for a run's trades.

    A trade is in the *trade band* if `abs(conviction) >= hold_threshold`.
    Otherwise it is in the *hold band* (would have been skipped under that threshold).
    """
    convictions = [abs(float(t.get("conviction", 0.0))) for t in run.trades]
    total = len(convictions)

    trade_band = sum(1 for c in convictions if c >= hold_threshold)
    hold_band = total - trade_band

    return ConvictionHistogram(
        hold_threshold=hold_threshold,
        trade_band_count=trade_band,
        hold_band_count=hold_band,
        trade_band_pct=(trade_band / total) if total > 0 else 0.0,
        hold_band_pct=(hold_band / total) if total > 0 else 0.0,
        min_conviction=min(convictions) if convictions else 0.0,
        max_conviction=max(convictions) if convictions else 0.0,
        mean_conviction=(sum(convictions) / total) if total > 0 else 0.0,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_forensics_conviction_histogram.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add omega/tools/forensics/conviction_histogram.py tests/test_forensics_conviction_histogram.py
git commit -m "feat(forensics): add conviction band histogram"
```

---

### Task 1.4: Signal delta module (simplified — trade-level proxy)

**Note**: The forensics spec's "per-signal contribution delta" ideally would read per-signal weights from a signal log. In Phase 1 we don't have that log, so we use a **trade-level proxy**: per-symbol and per-side PnL contributions compared between runs. This is explicitly scoped as a proxy and noted in the output JSON's schema.

**Files:**
- Create: `omega/tools/forensics/signal_delta.py`
- Create: `tests/test_forensics_signal_delta.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_forensics_signal_delta.py`:

```python
"""Tests for signal (trade-level proxy) delta."""
from pathlib import Path

import pytest

from omega.tools.forensics.loader import load_run
from omega.tools.forensics.signal_delta import (
    SignalDeltaProxy,
    compute_signal_delta_proxy,
)

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def test_signal_delta_proxy_computes_per_symbol_pnl_delta():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")

    delta = compute_signal_delta_proxy(v35, v48)
    assert isinstance(delta, SignalDeltaProxy)
    # V35 BTC PnL: 50 + 30 + 5 = 85; V48 BTC PnL: 20. Delta = 20 - 85 = -65
    assert delta.per_symbol_delta["BTCUSDT"] == pytest.approx(-65.0)
    # V35 ETH PnL: 30 + -5 = 25; V48 ETH PnL: -5. Delta = -5 - 25 = -30
    assert delta.per_symbol_delta["ETHUSDT"] == pytest.approx(-30.0)


def test_signal_delta_proxy_totals_match_run_totals():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")
    delta = compute_signal_delta_proxy(v35, v48)
    # Sum of per-symbol deltas should equal (V48 total PnL - V35 total PnL) from trades
    # V35 trades sum: 50+30+30+10-5+5 = 120; V48 trades sum: 20-5 = 15
    assert sum(delta.per_symbol_delta.values()) == pytest.approx(15.0 - 120.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_forensics_signal_delta.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Create `omega/tools/forensics/signal_delta.py`:

```python
"""Signal contribution delta — Phase 1 trade-level proxy.

This module does not read per-signal weights (no signal log available in Phase 1).
Instead it computes per-symbol and per-side PnL contribution deltas between two runs.
The forensics JSON labels this as `signal_contribution_delta_proxy` to make the
limitation explicit. A full per-signal version lands in Phase 2 once the signal log
is wired into training artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from omega.tools.forensics.loader import RunArtifacts


@dataclass
class SignalDeltaProxy:
    per_symbol_delta: dict[str, float] = field(default_factory=dict)
    per_side_delta: dict[str, float] = field(default_factory=dict)
    baseline_version: str = ""
    target_version: str = ""


def _group_pnl(trades: list[dict], key: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in trades:
        k = t.get(key, "unknown")
        out[k] = out.get(k, 0.0) + float(t.get("pnl", 0.0))
    return out


def compute_signal_delta_proxy(baseline: RunArtifacts, target: RunArtifacts) -> SignalDeltaProxy:
    """Delta = target - baseline for per-symbol and per-side PnL sums."""
    baseline_by_symbol = _group_pnl(baseline.trades, "symbol")
    target_by_symbol = _group_pnl(target.trades, "symbol")
    baseline_by_side = _group_pnl(baseline.trades, "side")
    target_by_side = _group_pnl(target.trades, "side")

    all_symbols = set(baseline_by_symbol) | set(target_by_symbol)
    all_sides = set(baseline_by_side) | set(target_by_side)

    return SignalDeltaProxy(
        per_symbol_delta={
            s: target_by_symbol.get(s, 0.0) - baseline_by_symbol.get(s, 0.0)
            for s in all_symbols
        },
        per_side_delta={
            s: target_by_side.get(s, 0.0) - baseline_by_side.get(s, 0.0)
            for s in all_sides
        },
        baseline_version=baseline.version,
        target_version=target.version,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_forensics_signal_delta.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add omega/tools/forensics/signal_delta.py tests/test_forensics_signal_delta.py
git commit -m "feat(forensics): add trade-level signal contribution delta proxy"
```

---

### Task 1.5: Skipped trades detection

**Files:**
- Create: `omega/tools/forensics/skipped_trades.py`
- Create: `tests/test_forensics_skipped_trades.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_forensics_skipped_trades.py`:

```python
"""Tests for skipped-trades detection (V35 trades V48 missed)."""
from pathlib import Path

from omega.tools.forensics.loader import load_run
from omega.tools.forensics.skipped_trades import SkippedTrade, find_skipped_trades

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def test_find_skipped_trades_returns_v35_trades_with_no_v48_match():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")

    skipped = find_skipped_trades(v35, v48)
    # V35 has 6 trades, V48 has 2 (BTC short cycle 3, ETH short cycle 5).
    # V35 matches on (cycle, symbol, side): cycle 3 BTC short, cycle 5 ETH short.
    # So 6 - 2 = 4 skipped.
    assert len(skipped) == 4
    assert all(isinstance(s, SkippedTrade) for s in skipped)

    # Cycle 1 BTC long in V35 was not in V48
    symbols = {(s.cycle, s.symbol, s.side) for s in skipped}
    assert (1, "BTCUSDT", "long") in symbols
    assert (2, "ETHUSDT", "long") in symbols
    assert (4, "SOLUSDT", "long") in symbols
    assert (6, "BTCUSDT", "long") in symbols


def test_skipped_trade_attaches_baseline_conviction():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")
    skipped = find_skipped_trades(v35, v48)
    cycle_1 = next(s for s in skipped if s.cycle == 1)
    assert cycle_1.baseline_conviction == 0.35
    assert cycle_1.baseline_pnl == 50.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_forensics_skipped_trades.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Create `omega/tools/forensics/skipped_trades.py`:

```python
"""Find trades present in the baseline run but missing in the target run.

Matching key: (cycle, symbol, side). This is a necessary compromise: V35 and V48
will not have byte-identical cycle sequences, but using cycle+symbol+side captures
the intent ("same decision, same instrument, same direction") well enough for a
forensics diff. Rank mismatches will show as both a skipped-baseline and an
introduced-target trade, which is acceptable signal for hypothesis ranking.
"""

from __future__ import annotations

from dataclasses import dataclass

from omega.tools.forensics.loader import RunArtifacts


@dataclass
class SkippedTrade:
    cycle: int
    symbol: str
    side: str
    baseline_pnl: float
    baseline_conviction: float
    baseline_regime: str


def find_skipped_trades(baseline: RunArtifacts, target: RunArtifacts) -> list[SkippedTrade]:
    """Return baseline trades with no matching (cycle, symbol, side) in target."""
    target_keys = {(t["cycle"], t["symbol"], t["side"]) for t in target.trades}
    skipped: list[SkippedTrade] = []
    for t in baseline.trades:
        key = (t["cycle"], t["symbol"], t["side"])
        if key not in target_keys:
            skipped.append(
                SkippedTrade(
                    cycle=t["cycle"],
                    symbol=t["symbol"],
                    side=t["side"],
                    baseline_pnl=float(t["pnl"]),
                    baseline_conviction=float(t["conviction"]),
                    baseline_regime=t.get("regime", "unknown"),
                )
            )
    return skipped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_forensics_skipped_trades.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add omega/tools/forensics/skipped_trades.py tests/test_forensics_skipped_trades.py
git commit -m "feat(forensics): detect trades present in baseline but missing in target"
```

---

### Task 1.6: Hypothesis ranker (top-3 structural differences)

**Files:**
- Create: `omega/tools/forensics/hypothesis_ranker.py`
- Create: `tests/test_forensics_hypothesis_ranker.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_forensics_hypothesis_ranker.py`:

```python
"""Tests for hypothesis ranker."""
from pathlib import Path

from omega.tools.forensics.conviction_histogram import compute_histogram
from omega.tools.forensics.hypothesis_ranker import (
    Hypothesis,
    rank_hypotheses,
)
from omega.tools.forensics.loader import load_run
from omega.tools.forensics.signal_delta import compute_signal_delta_proxy
from omega.tools.forensics.skipped_trades import find_skipped_trades

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def test_rank_hypotheses_returns_top3_with_descending_confidence():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")

    histogram_v35 = compute_histogram(v35, hold_threshold=0.20)
    histogram_v48 = compute_histogram(v48, hold_threshold=0.20)
    delta = compute_signal_delta_proxy(v35, v48)
    skipped = find_skipped_trades(v35, v48)

    hypotheses = rank_hypotheses(
        v35=v35,
        v48=v48,
        v35_histogram=histogram_v35,
        v48_histogram=histogram_v48,
        delta=delta,
        skipped=skipped,
    )
    assert len(hypotheses) == 3
    assert all(isinstance(h, Hypothesis) for h in hypotheses)
    # Ranks are 1, 2, 3
    assert [h.rank for h in hypotheses] == [1, 2, 3]
    # Confidence is monotonically non-increasing
    assert hypotheses[0].confidence >= hypotheses[1].confidence
    assert hypotheses[1].confidence >= hypotheses[2].confidence
    # Every hypothesis has non-empty claim and evidence refs
    for h in hypotheses:
        assert h.claim
        assert h.evidence_refs


def test_rank_hypotheses_identifies_conviction_widening_when_present():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")
    histogram_v35 = compute_histogram(v35, hold_threshold=0.20)
    histogram_v48 = compute_histogram(v48, hold_threshold=0.20)
    delta = compute_signal_delta_proxy(v35, v48)
    skipped = find_skipped_trades(v35, v48)

    hypotheses = rank_hypotheses(
        v35=v35, v48=v48,
        v35_histogram=histogram_v35, v48_histogram=histogram_v48,
        delta=delta, skipped=skipped,
    )
    # In fixtures: V48 mean conviction (0.065) is ~5x lower than V35 (0.255).
    # The top hypothesis should mention conviction/HOLD band.
    top_claim_lower = hypotheses[0].claim.lower()
    assert "conviction" in top_claim_lower or "hold" in top_claim_lower
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_forensics_hypothesis_ranker.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Create `omega/tools/forensics/hypothesis_ranker.py`:

```python
"""Rank the top-3 structural differences most likely explaining the baseline→target PnL gap.

Hypotheses are scored heuristically from four inputs:
1. Conviction histogram shift (mean/max conviction ratio, hold-band percentage delta)
2. Signal delta proxy (per-symbol PnL delta concentration)
3. Skipped trades (count and PnL of trades the target missed)
4. Zero-trade cycle ratio shift

Each hypothesis has a confidence in [0, 1] derived from the magnitude of its supporting
signal relative to the total PnL gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from omega.tools.forensics.conviction_histogram import ConvictionHistogram
from omega.tools.forensics.loader import RunArtifacts
from omega.tools.forensics.signal_delta import SignalDeltaProxy
from omega.tools.forensics.skipped_trades import SkippedTrade


@dataclass
class Hypothesis:
    rank: int
    claim: str
    confidence: float
    evidence_refs: list[str] = field(default_factory=list)


def _conviction_hypothesis(
    v35: RunArtifacts,
    v48: RunArtifacts,
    h35: ConvictionHistogram,
    h48: ConvictionHistogram,
) -> tuple[str, float]:
    if h35.mean_conviction <= 0:
        return ("", 0.0)
    ratio = h48.mean_conviction / h35.mean_conviction
    # Ratio < 0.5 is strong evidence; 1.0 is no change
    if ratio < 1.0:
        magnitude = 1.0 - ratio  # 0.0 .. 1.0
    else:
        magnitude = 0.0
    claim = (
        f"Conviction magnitudes collapsed: V48 mean conviction ({h48.mean_conviction:.3f}) "
        f"is {ratio:.2f}x V35 ({h35.mean_conviction:.3f}). The HOLD band is now "
        f"{h48.hold_band_pct:.0%} of trades vs {h35.hold_band_pct:.0%} in V35, "
        "consistent with post-demean thresholds not tracking signal magnitude."
    )
    return (claim, min(0.95, 0.3 + magnitude))


def _skipped_trades_hypothesis(
    skipped: list[SkippedTrade],
    v35: RunArtifacts,
    v48: RunArtifacts,
) -> tuple[str, float]:
    if not skipped:
        return ("", 0.0)
    skipped_pnl = sum(s.baseline_pnl for s in skipped)
    pnl_gap = v35.total_pnl - v48.total_pnl
    if pnl_gap <= 0:
        return ("", 0.0)
    coverage = min(1.0, max(0.0, skipped_pnl / pnl_gap))
    claim = (
        f"{len(skipped)} baseline trades were skipped by V48, representing "
        f"${skipped_pnl:.2f} of the ${pnl_gap:.2f} PnL gap ({coverage:.0%} coverage). "
        "Most were profitable baseline entries below V48's current threshold."
    )
    return (claim, min(0.9, 0.2 + coverage * 0.7))


def _signal_concentration_hypothesis(
    delta: SignalDeltaProxy,
    v35: RunArtifacts,
    v48: RunArtifacts,
) -> tuple[str, float]:
    if not delta.per_symbol_delta:
        return ("", 0.0)
    worst_symbol, worst_delta = min(delta.per_symbol_delta.items(), key=lambda kv: kv[1])
    pnl_gap = v35.total_pnl - v48.total_pnl
    if pnl_gap <= 0 or worst_delta >= 0:
        return ("", 0.0)
    share = min(1.0, abs(worst_delta) / pnl_gap)
    claim = (
        f"Per-symbol PnL loss is concentrated in {worst_symbol}: "
        f"${worst_delta:.2f} delta ({share:.0%} of the total gap). "
        "Targeted signal re-weighting for this symbol is a cheap first fix."
    )
    return (claim, min(0.85, 0.15 + share * 0.6))


def _zero_trade_hypothesis(v35: RunArtifacts, v48: RunArtifacts) -> tuple[str, float]:
    # Ratio of zero-trade cycles normalized to run length
    v35_cycles = max(1, v35.zero_trade_cycles + v35.trade_cycles)
    v48_cycles = max(1, v48.zero_trade_cycles + v48.trade_cycles)
    v35_ratio = v35.zero_trade_cycles / v35_cycles
    v48_ratio = v48.zero_trade_cycles / v48_cycles
    growth = v48_ratio - v35_ratio
    if growth <= 0.1:
        return ("", 0.0)
    claim = (
        f"V48 zero-trade cycle ratio is {v48_ratio:.0%} vs V35 {v35_ratio:.0%} "
        f"(+{growth:.0%}). Filters or HOLD-band are skipping entire cycles; "
        "conviction or stale-data filters are over-gating."
    )
    return (claim, min(0.8, 0.2 + growth * 2.0))


def rank_hypotheses(
    v35: RunArtifacts,
    v48: RunArtifacts,
    v35_histogram: ConvictionHistogram,
    v48_histogram: ConvictionHistogram,
    delta: SignalDeltaProxy,
    skipped: list[SkippedTrade],
) -> list[Hypothesis]:
    """Produce the top-3 ranked hypotheses. Always returns exactly 3 entries."""
    candidates: list[tuple[str, float, list[str]]] = []

    claim, conf = _conviction_hypothesis(v35, v48, v35_histogram, v48_histogram)
    if claim:
        candidates.append((claim, conf, ["conviction_histogram", "observability.conviction_filter_rate"]))

    claim, conf = _skipped_trades_hypothesis(skipped, v35, v48)
    if claim:
        candidates.append((claim, conf, ["skipped_trades", "baselines"]))

    claim, conf = _signal_concentration_hypothesis(delta, v35, v48)
    if claim:
        candidates.append((claim, conf, ["signal_contribution_delta_proxy"]))

    claim, conf = _zero_trade_hypothesis(v35, v48)
    if claim:
        candidates.append((claim, conf, ["observability.total_zero_trade_cycles"]))

    # Always pad to 3 with neutral-confidence fallbacks so downstream agents have a stable shape
    while len(candidates) < 3:
        candidates.append(
            (
                "No additional structural difference detected above heuristic thresholds.",
                0.05,
                [],
            )
        )

    candidates.sort(key=lambda c: c[1], reverse=True)
    top3 = candidates[:3]
    return [
        Hypothesis(rank=i + 1, claim=c[0], confidence=c[1], evidence_refs=c[2])
        for i, c in enumerate(top3)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_forensics_hypothesis_ranker.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add omega/tools/forensics/hypothesis_ranker.py tests/test_forensics_hypothesis_ranker.py
git commit -m "feat(forensics): add heuristic hypothesis ranker for V35-V48 diff"
```

---

### Task 1.7: Writer module — JSON + Markdown output

**Files:**
- Create: `omega/tools/forensics/writer.py`
- Create: `tests/test_forensics_writer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_forensics_writer.py`:

```python
"""Tests for forensics JSON + Markdown writer."""
import json
from pathlib import Path

from omega.tools.forensics.conviction_histogram import compute_histogram
from omega.tools.forensics.hypothesis_ranker import rank_hypotheses
from omega.tools.forensics.loader import load_run
from omega.tools.forensics.signal_delta import compute_signal_delta_proxy
from omega.tools.forensics.skipped_trades import find_skipped_trades
from omega.tools.forensics.writer import write_forensics_json, write_forensics_markdown

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def _build_bundle():
    v35 = load_run(FIXTURES / "mini_v35_results.json", FIXTURES / "mini_v35_trades.csv")
    v48 = load_run(FIXTURES / "mini_v48_results.json", FIXTURES / "mini_v48_trades.csv")
    h35 = compute_histogram(v35, 0.20)
    h48 = compute_histogram(v48, 0.20)
    delta = compute_signal_delta_proxy(v35, v48)
    skipped = find_skipped_trades(v35, v48)
    hypotheses = rank_hypotheses(v35=v35, v48=v48, v35_histogram=h35, v48_histogram=h48, delta=delta, skipped=skipped)
    return v35, v48, h35, h48, delta, skipped, hypotheses


def test_write_forensics_json_produces_valid_schema(tmp_path: Path):
    v35, v48, h35, h48, delta, skipped, hypotheses = _build_bundle()
    out = tmp_path / "forensics.json"
    write_forensics_json(
        out,
        v35=v35, v48=v48,
        v35_histogram=h35, v48_histogram=h48,
        delta=delta, skipped=skipped, hypotheses=hypotheses,
    )
    data = json.loads(out.read_text())
    assert data["schema_version"] == "1.0"
    assert data["status"] == "ok"
    assert data["baselines"]["v35"]["pnl"] == 120.0
    assert data["baselines"]["v48"]["pnl"] == 15.0
    assert "conviction_histogram" in data
    assert "skipped_trades" in data
    assert len(data["hypotheses"]) == 3
    assert data["hypotheses"][0]["rank"] == 1
    assert "regime_breakdown" in data
    assert "signal_contribution_delta_proxy" in data


def test_write_forensics_markdown_contains_top_hypothesis(tmp_path: Path):
    v35, v48, h35, h48, delta, skipped, hypotheses = _build_bundle()
    out = tmp_path / "forensics.md"
    write_forensics_markdown(
        out,
        v35=v35, v48=v48,
        v35_histogram=h35, v48_histogram=h48,
        delta=delta, skipped=skipped, hypotheses=hypotheses,
    )
    text = out.read_text()
    assert "# V35 → V48 Forensics Report" in text
    assert hypotheses[0].claim in text
    assert "| Metric | V35 | V48 |" in text  # summary table
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_forensics_writer.py -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Create `omega/tools/forensics/writer.py`:

```python
"""Emit forensics output as machine-readable JSON and human-readable Markdown."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omega.tools.forensics.conviction_histogram import ConvictionHistogram
from omega.tools.forensics.hypothesis_ranker import Hypothesis
from omega.tools.forensics.loader import RunArtifacts
from omega.tools.forensics.signal_delta import SignalDeltaProxy
from omega.tools.forensics.skipped_trades import SkippedTrade

SCHEMA_VERSION = "1.0"


def _baseline_dict(run: RunArtifacts, source: str) -> dict[str, Any]:
    return {
        "version": run.version,
        "pnl": run.total_pnl,
        "trades": run.total_trades,
        "win_rate": run.win_rate,
        "long_trades": run.long_trades,
        "short_trades": run.short_trades,
        "profit_factor": run.profit_factor,
        "zero_trade_cycles": run.zero_trade_cycles,
        "conviction_filter_rate": run.conviction_filter_rate,
        "source": source,
    }


def _histogram_dict(h: ConvictionHistogram) -> dict[str, Any]:
    return {
        "hold_threshold": h.hold_threshold,
        "trade_band_count": h.trade_band_count,
        "hold_band_count": h.hold_band_count,
        "trade_band_pct": h.trade_band_pct,
        "hold_band_pct": h.hold_band_pct,
        "min_conviction": h.min_conviction,
        "max_conviction": h.max_conviction,
        "mean_conviction": h.mean_conviction,
    }


def _regime_breakdown(v35: RunArtifacts, v48: RunArtifacts) -> dict[str, Any]:
    regimes = set(v35.regime_pnl) | set(v48.regime_pnl)
    return {
        r: {
            "v35_pnl": v35.regime_pnl.get(r, 0.0),
            "v48_pnl": v48.regime_pnl.get(r, 0.0),
            "delta": v48.regime_pnl.get(r, 0.0) - v35.regime_pnl.get(r, 0.0),
        }
        for r in sorted(regimes)
    }


def write_forensics_json(
    path: Path,
    *,
    v35: RunArtifacts,
    v48: RunArtifacts,
    v35_histogram: ConvictionHistogram,
    v48_histogram: ConvictionHistogram,
    delta: SignalDeltaProxy,
    skipped: list[SkippedTrade],
    hypotheses: list[Hypothesis],
    status: str = "ok",
) -> None:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "baselines": {
            "v35": _baseline_dict(v35, source="data/v35_extended_results.json"),
            "v48": _baseline_dict(v48, source="data/v48_results.json"),
        },
        "conviction_histogram": {
            "v35": _histogram_dict(v35_histogram),
            "v48": _histogram_dict(v48_histogram),
        },
        "signal_contribution_delta_proxy": {
            "per_symbol": delta.per_symbol_delta,
            "per_side": delta.per_side_delta,
            "note": "Phase 1 proxy — per-symbol PnL delta, not per-signal weight delta.",
        },
        "skipped_trades": [
            {
                "cycle": s.cycle,
                "symbol": s.symbol,
                "side": s.side,
                "baseline_pnl": s.baseline_pnl,
                "baseline_conviction": s.baseline_conviction,
                "baseline_regime": s.baseline_regime,
                "reason": "present_in_v35_absent_in_v48",
            }
            for s in skipped
        ],
        "hypotheses": [
            {
                "rank": h.rank,
                "claim": h.claim,
                "confidence": h.confidence,
                "evidence_refs": h.evidence_refs,
            }
            for h in hypotheses
        ],
        "regime_breakdown": _regime_breakdown(v35, v48),
    }
    Path(path).write_text(json.dumps(payload, indent=2))


def write_forensics_markdown(
    path: Path,
    *,
    v35: RunArtifacts,
    v48: RunArtifacts,
    v35_histogram: ConvictionHistogram,
    v48_histogram: ConvictionHistogram,
    delta: SignalDeltaProxy,
    skipped: list[SkippedTrade],
    hypotheses: list[Hypothesis],
) -> None:
    lines: list[str] = []
    lines.append("# V35 → V48 Forensics Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | V35 | V48 | Delta |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| Total PnL (USD) | {v35.total_pnl:.2f} | {v48.total_pnl:.2f} | {v48.total_pnl - v35.total_pnl:+.2f} |"
    )
    lines.append(
        f"| Trades | {v35.total_trades} | {v48.total_trades} | {v48.total_trades - v35.total_trades:+d} |"
    )
    lines.append(
        f"| Win rate | {v35.win_rate:.2%} | {v48.win_rate:.2%} | {(v48.win_rate - v35.win_rate):+.2%} |"
    )
    lines.append(
        f"| Profit factor | {v35.profit_factor:.2f} | {v48.profit_factor:.2f} | {v48.profit_factor - v35.profit_factor:+.2f} |"
    )
    lines.append(
        f"| Zero-trade cycles | {v35.zero_trade_cycles} | {v48.zero_trade_cycles} | {v48.zero_trade_cycles - v35.zero_trade_cycles:+d} |"
    )
    lines.append("")
    lines.append("## Conviction Histogram")
    lines.append("")
    lines.append("| Band | V35 | V48 |")
    lines.append("|---|---|---|")
    lines.append(f"| HOLD (< 0.20) | {v35_histogram.hold_band_pct:.0%} | {v48_histogram.hold_band_pct:.0%} |")
    lines.append(f"| Trade (>= 0.20) | {v35_histogram.trade_band_pct:.0%} | {v48_histogram.trade_band_pct:.0%} |")
    lines.append(f"| Mean conviction | {v35_histogram.mean_conviction:.3f} | {v48_histogram.mean_conviction:.3f} |")
    lines.append("")
    lines.append("## Top-3 Hypotheses")
    lines.append("")
    for h in hypotheses:
        lines.append(f"### {h.rank}. (confidence {h.confidence:.2f})")
        lines.append("")
        lines.append(h.claim)
        lines.append("")
        if h.evidence_refs:
            lines.append("**Evidence:** " + ", ".join(h.evidence_refs))
            lines.append("")
    lines.append("## Skipped Trades")
    lines.append("")
    if not skipped:
        lines.append("_None — all baseline trades matched a target entry._")
    else:
        lines.append("| Cycle | Symbol | Side | Baseline PnL | Conviction | Regime |")
        lines.append("|---|---|---|---|---|---|")
        for s in skipped:
            lines.append(
                f"| {s.cycle} | {s.symbol} | {s.side} | {s.baseline_pnl:+.2f} | "
                f"{s.baseline_conviction:.3f} | {s.baseline_regime} |"
            )
    lines.append("")
    lines.append("## Regime Breakdown")
    lines.append("")
    lines.append("| Regime | V35 PnL | V48 PnL | Delta |")
    lines.append("|---|---|---|---|")
    regimes = set(v35.regime_pnl) | set(v48.regime_pnl)
    for r in sorted(regimes):
        v35_p = v35.regime_pnl.get(r, 0.0)
        v48_p = v48.regime_pnl.get(r, 0.0)
        lines.append(f"| {r} | {v35_p:+.2f} | {v48_p:+.2f} | {v48_p - v35_p:+.2f} |")
    lines.append("")
    Path(path).write_text("\n".join(lines))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_forensics_writer.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add omega/tools/forensics/writer.py tests/test_forensics_writer.py
git commit -m "feat(forensics): add JSON + Markdown writer with v1.0 schema"
```

---

### Task 1.8: CLI runner + end-to-end integration test

**Files:**
- Create: `omega/tools/forensics/run_diff.py`
- Create: `tests/test_forensics_cli.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/test_forensics_cli.py`:

```python
"""End-to-end test for the forensics CLI runner."""
import json
from pathlib import Path

from omega.tools.forensics.run_diff import run_diff

FIXTURES = Path(__file__).parent / "fixtures" / "forensics"


def test_run_diff_produces_json_and_markdown(tmp_path: Path):
    out_json = tmp_path / "v35-v48-forensics.json"
    out_md = tmp_path / "v35-v48-forensics.md"
    exit_code = run_diff(
        baseline_results=FIXTURES / "mini_v35_results.json",
        baseline_trades=FIXTURES / "mini_v35_trades.csv",
        target_results=FIXTURES / "mini_v48_results.json",
        target_trades=FIXTURES / "mini_v48_trades.csv",
        out_json=out_json,
        out_md=out_md,
        hold_threshold=0.20,
    )
    assert exit_code == 0
    assert out_json.exists()
    assert out_md.exists()
    data = json.loads(out_json.read_text())
    assert data["schema_version"] == "1.0"
    assert data["status"] == "ok"
    assert len(data["hypotheses"]) == 3
    assert data["baselines"]["v35"]["version"] == "mini_v35"
    assert data["baselines"]["v48"]["version"] == "mini_v48"


def test_run_diff_signal_delta_sums_to_pnl_gap(tmp_path: Path):
    """The sum of per-symbol deltas should equal the PnL gap (integrity invariant)."""
    out_json = tmp_path / "forensics.json"
    out_md = tmp_path / "forensics.md"
    run_diff(
        baseline_results=FIXTURES / "mini_v35_results.json",
        baseline_trades=FIXTURES / "mini_v35_trades.csv",
        target_results=FIXTURES / "mini_v48_results.json",
        target_trades=FIXTURES / "mini_v48_trades.csv",
        out_json=out_json,
        out_md=out_md,
        hold_threshold=0.20,
    )
    data = json.loads(out_json.read_text())
    per_symbol = data["signal_contribution_delta_proxy"]["per_symbol"]
    # Sum of all per-symbol PnL deltas == V48 trade sum - V35 trade sum
    # V35: 50+30+30+10-5+5 = 120; V48: 20-5 = 15; diff = -105
    assert sum(per_symbol.values()) == -105.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_forensics_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write CLI runner**

Create `omega/tools/forensics/run_diff.py`:

```python
"""CLI runner for V35 ↔ V48 (or any baseline/target) forensics diff.

Usage:
    python -m omega.tools.forensics.run_diff \
        --baseline-results data/v35_extended_results.json \
        --baseline-trades data/v35_extended_trades.csv \
        --target-results data/v48_results.json \
        --target-trades data/v48_trades.csv \
        --out-json data/v35-v48-forensics.json \
        --out-md docs/training/v35-v48-forensics.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from omega.tools.forensics.conviction_histogram import compute_histogram
from omega.tools.forensics.hypothesis_ranker import rank_hypotheses
from omega.tools.forensics.loader import load_run
from omega.tools.forensics.signal_delta import compute_signal_delta_proxy
from omega.tools.forensics.skipped_trades import find_skipped_trades
from omega.tools.forensics.writer import write_forensics_json, write_forensics_markdown


def run_diff(
    baseline_results: Path,
    baseline_trades: Path,
    target_results: Path,
    target_trades: Path,
    out_json: Path,
    out_md: Path,
    hold_threshold: float = 0.20,
) -> int:
    """Execute the full diff pipeline. Returns process exit code."""
    baseline = load_run(baseline_results, baseline_trades)
    target = load_run(target_results, target_trades)

    h_baseline = compute_histogram(baseline, hold_threshold)
    h_target = compute_histogram(target, hold_threshold)
    delta = compute_signal_delta_proxy(baseline, target)
    skipped = find_skipped_trades(baseline, target)
    hypotheses = rank_hypotheses(
        v35=baseline,
        v48=target,
        v35_histogram=h_baseline,
        v48_histogram=h_target,
        delta=delta,
        skipped=skipped,
    )

    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_md).parent.mkdir(parents=True, exist_ok=True)

    write_forensics_json(
        Path(out_json),
        v35=baseline,
        v48=target,
        v35_histogram=h_baseline,
        v48_histogram=h_target,
        delta=delta,
        skipped=skipped,
        hypotheses=hypotheses,
    )
    write_forensics_markdown(
        Path(out_md),
        v35=baseline,
        v48=target,
        v35_histogram=h_baseline,
        v48_histogram=h_target,
        delta=delta,
        skipped=skipped,
        hypotheses=hypotheses,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run V35 ↔ V48 forensics diff.")
    parser.add_argument("--baseline-results", type=Path, required=True)
    parser.add_argument("--baseline-trades", type=Path, required=True)
    parser.add_argument("--target-results", type=Path, required=True)
    parser.add_argument("--target-trades", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--hold-threshold", type=float, default=0.20)
    args = parser.parse_args(argv)

    return run_diff(
        baseline_results=args.baseline_results,
        baseline_trades=args.baseline_trades,
        target_results=args.target_results,
        target_trades=args.target_trades,
        out_json=args.out_json,
        out_md=args.out_md,
        hold_threshold=args.hold_threshold,
    )


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_forensics_cli.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Run full forensics test suite**

Run: `python3 -m pytest tests/test_forensics_loader.py tests/test_forensics_conviction_histogram.py tests/test_forensics_signal_delta.py tests/test_forensics_skipped_trades.py tests/test_forensics_hypothesis_ranker.py tests/test_forensics_writer.py tests/test_forensics_cli.py -v`
Expected: all PASS (13 tests total).

- [ ] **Step 6: Commit**

```bash
git add omega/tools/forensics/run_diff.py tests/test_forensics_cli.py
git commit -m "feat(forensics): add CLI runner + end-to-end integration test"
```

---

### Task 1.9: Execute the real V35↔V48 diff and commit artifacts

**Files:**
- Create: `data/v35-v48-forensics.json`
- Create: `docs/training/v35-v48-forensics.md`

- [ ] **Step 1: Run the CLI against real V35 and V48 data**

Run:
```bash
python3 -m omega.tools.forensics.run_diff \
  --baseline-results data/v35_extended_results.json \
  --baseline-trades data/v35_extended_trades.csv \
  --target-results data/v48_results.json \
  --target-trades data/v48_trades.csv \
  --out-json data/v35-v48-forensics.json \
  --out-md docs/training/v35-v48-forensics.md
```

Expected: exit code 0, both files created. If it fails, inspect the stack trace — likely a schema mismatch between the fixtures and real V35 extended schema (e.g., missing field). Add defensive `.get(..., default)` calls in `loader.py`, re-run the unit tests, then re-run the CLI.

- [ ] **Step 2: Inspect the generated Markdown**

Run: `head -60 docs/training/v35-v48-forensics.md`
Expected: summary table with real V35 PnL (~$151) and V48 PnL ($31.97), top hypothesis printed.

- [ ] **Step 3: Validate the JSON integrity invariant**

Run:
```bash
python3 -c "
import json
d = json.load(open('data/v35-v48-forensics.json'))
per_symbol_sum = sum(d['signal_contribution_delta_proxy']['per_symbol'].values())
pnl_gap = d['baselines']['v48']['pnl'] - d['baselines']['v35']['pnl']
# Trade-level sums won't exactly equal reported PnL (open positions, fees) but should be close
print(f'per_symbol_sum={per_symbol_sum:.2f}  pnl_gap={pnl_gap:.2f}  hypotheses={len(d[\"hypotheses\"])}')
assert len(d['hypotheses']) == 3
assert d['status'] == 'ok'
print('OK')
"
```
Expected: prints OK.

- [ ] **Step 4: Commit the artifacts**

```bash
git add data/v35-v48-forensics.json docs/training/v35-v48-forensics.md
git commit -m "docs(training): V35↔V48 forensics report and machine-readable sidecar"
```

---

### Task 1.10: Merge Agent 1 worktree to main

**Files:** none

- [ ] **Step 1: Run the full forensics test suite one more time from the worktree**

Run: `python3 -m pytest tests/test_forensics_*.py -v`
Expected: all PASS.

- [ ] **Step 2: Check branch log**

Run: `git log --oneline main..HEAD`
Expected: 10 commits (one per task 1.1 through 1.10).

- [ ] **Step 3: Return to the main worktree and cherry-pick**

Run:
```bash
cd /Users/benebsworth/projects/omega
git cherry-pick forensics/v35-v48-diff~9..forensics/v35-v48-diff
```

Expected: clean cherry-pick of all commits (or use `git merge --ff-only` if the branch is still a fast-forward).

- [ ] **Step 4: Verify files land on main**

Run: `ls data/v35-v48-forensics.json docs/training/v35-v48-forensics.md omega/tools/forensics/run_diff.py`
Expected: all three files exist on main.

- [ ] **Step 5: Remove the worktree**

Run:
```bash
git worktree remove ../omega-forensics
git branch -d forensics/v35-v48-diff
```

Expected: worktree removed; branch deleted.

**Agent 1 complete. Phase 2 is now unblocked.**

---

# AGENT 4 — DASHBOARD REAL-DATA WIRING

**Branch:** `dashboard/real-data`
**Owner:** dispatched agent 4
**Depends on:** nothing (runs in parallel with Agent 1)

### Task 4.0: Worktree setup and baseline

**Files:** none modified

- [ ] **Step 1: Create worktree**

Run:
```bash
cd /Users/benebsworth/projects/omega
git worktree add ../omega-dashboard dashboard/real-data main
cd ../omega-dashboard/dashboard
```

- [ ] **Step 2: Install dependencies**

Run: `npm install`
Expected: clean install.

- [ ] **Step 3: Baseline run**

Run: `npm run typecheck && npm run lint`
Expected: both succeed. If either fails on main, stop — the baseline is broken and must be fixed before Agent 4 starts.

- [ ] **Step 4: Confirm Vitest is configured**

Run: `npx vitest --version`
Expected: a version string. If Vitest is not installed, add it:

```bash
npm install --save-dev vitest @vitest/ui @testing-library/react @testing-library/jest-dom jsdom
```

Then add `vitest.config.ts` at `dashboard/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

And `dashboard/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

Add to `dashboard/package.json` scripts:
```json
"test": "vitest run",
"test:watch": "vitest"
```

Commit the Vitest scaffolding as its own commit:

```bash
git add dashboard/vitest.config.ts dashboard/src/test/setup.ts dashboard/package.json dashboard/package-lock.json
git commit -m "chore(dashboard): add Vitest + testing-library scaffolding for contract tests"
```

If Vitest already exists, skip this step.

---

### Task 4.1: Explore the existing DecisionTrace, NodeHealth, VictoriaTrades pages

**Files:** read-only

- [ ] **Step 1: Read DecisionTrace.tsx and identify the mock-data call site**

Run: `grep -n "mock\|mockData\|VITE_API_URL\|fetch(" dashboard/src/pages/DecisionTrace.tsx`

Expected output: one or more lines where mock data is imported/called. Note the exact variable name and import path.

- [ ] **Step 2: Read NodeHealth.tsx similarly**

Run: `grep -n "mock\|mockData\|VITE_API_URL\|fetch(" dashboard/src/pages/NodeHealth.tsx`

- [ ] **Step 3: Read VictoriaTrades.tsx similarly**

Run: `grep -n "mock\|mockData\|VITE_API_URL\|fetch(" dashboard/src/pages/VictoriaTrades.tsx`

- [ ] **Step 4: Check what the Go side already exposes for decisions/health/lifecycle/victoria-trades**

Run: `grep -rn "rpc ListVictoriaTrades\|rpc GetDecisions\|rpc ListDecisions\|rpc GetNodeHealth\|rpc GetLifecycle" proto/ internal/`

Expected: list of existing RPC methods. Mark which of the four needed endpoints (decisions, health-score, lifecycle, victoria-trades) already exist vs need to be added. **This determines which subtasks are needed in Tasks 4.2–4.5.**

- [ ] **Step 5: Record findings in a scratch file**

Create `/tmp/agent4_exploration.md` capturing the concrete outputs from Steps 1–4: existing RPC method names from Step 4, exact file paths and line numbers of mock-data imports in each page from Steps 1–3, and any RPC methods that must be added in Phase 1. This file is consulted by Tasks 4.2–4.5. Not committed.

---

### Task 4.2: Add `ListVictoriaTrades` RPC if missing

**Skip this task if Task 4.1 Step 4 showed `ListVictoriaTrades` already exists.**

**Files:**
- Modify: `proto/omega/v1/victoria_service.proto`
- Modify: `internal/handler/` (specific file identified in Task 4.1)
- Regenerate: `gen/go/omega/v1/victoria_service.pb.go` and `dashboard/src/gen/omega/v1/victoria_service_pb.ts` (via `make proto`)

- [ ] **Step 1: Add proto message and RPC method**

Edit `proto/omega/v1/victoria_service.proto` — add inside the existing `VictoriaService` service block and near existing message definitions:

```proto
message ListVictoriaTradesRequest {
  int32 limit = 1;           // Max trades to return; 0 = server default
  string since_cycle = 2;    // Optional cursor
  string regime_filter = 3;  // Optional: "bull", "bear", "chop", ""
}

message VictoriaTrade {
  int32 cycle = 1;
  string timestamp = 2;
  string symbol = 3;
  string side = 4;
  double size = 5;
  double entry_price = 6;
  double exit_price = 7;
  double pnl = 8;
  double slippage = 9;
  int32 hold_cycles = 10;
  double conviction = 11;
  string regime = 12;
  string sit_out_reason = 13;
}

message ListVictoriaTradesResponse {
  repeated VictoriaTrade trades = 1;
  int32 total_count = 2;
}

service VictoriaService {
  // ... existing rpcs ...
  rpc ListVictoriaTrades(ListVictoriaTradesRequest) returns (ListVictoriaTradesResponse);
}
```

- [ ] **Step 2: Regenerate proto bindings**

Run:
```bash
cd /Users/benebsworth/projects/omega-dashboard
make proto
```

Expected: new Go and TS bindings for `VictoriaTrade`, `ListVictoriaTradesRequest`, `ListVictoriaTradesResponse`.

- [ ] **Step 3: Implement the RPC on the Go side**

Identify the file that implements the other VictoriaService methods (from Task 4.1 Step 4). In that file, add:

```go
// ListVictoriaTrades returns the most recent closed trades from the latest Victoria training run.
// Data source: the CSV written by scripts/run_training.py (data/v*_trades.csv).
// Implementation reads the newest matching file by mtime.
func (h *VictoriaHandler) ListVictoriaTrades(
    ctx context.Context,
    req *connect.Request[omegav1.ListVictoriaTradesRequest],
) (*connect.Response[omegav1.ListVictoriaTradesResponse], error) {
    limit := req.Msg.Limit
    if limit <= 0 {
        limit = 200
    }
    trades, err := h.readLatestTradesCSV(ctx, int(limit), req.Msg.RegimeFilter)
    if err != nil {
        return nil, connect.NewError(connect.CodeInternal, err)
    }
    return connect.NewResponse(&omegav1.ListVictoriaTradesResponse{
        Trades:     trades,
        TotalCount: int32(len(trades)),
    }), nil
}

// readLatestTradesCSV finds the newest data/v*_trades.csv and parses it.
// Listed here in full because the engineer reading this may not have familiarity with
// Go csv package or filepath.Glob.
func (h *VictoriaHandler) readLatestTradesCSV(
    ctx context.Context,
    limit int,
    regimeFilter string,
) ([]*omegav1.VictoriaTrade, error) {
    matches, err := filepath.Glob("data/v*_trades.csv")
    if err != nil || len(matches) == 0 {
        return nil, fmt.Errorf("no training trade CSVs found under data/: %w", err)
    }
    // Pick newest by mtime
    sort.Slice(matches, func(i, j int) bool {
        fi, errI := os.Stat(matches[i])
        fj, errJ := os.Stat(matches[j])
        if errI != nil || errJ != nil {
            return matches[i] > matches[j]
        }
        return fi.ModTime().After(fj.ModTime())
    })
    f, err := os.Open(matches[0])
    if err != nil {
        return nil, err
    }
    defer f.Close()
    reader := csv.NewReader(f)
    header, err := reader.Read()
    if err != nil {
        return nil, err
    }
    idx := map[string]int{}
    for i, col := range header {
        idx[col] = i
    }
    var out []*omegav1.VictoriaTrade
    for {
        row, err := reader.Read()
        if err == io.EOF {
            break
        }
        if err != nil {
            return nil, err
        }
        regime := row[idx["regime"]]
        if regimeFilter != "" && regime != regimeFilter {
            continue
        }
        cycle, _ := strconv.Atoi(row[idx["cycle"]])
        size, _ := strconv.ParseFloat(row[idx["size"]], 64)
        entry, _ := strconv.ParseFloat(row[idx["entry_price"]], 64)
        exitP, _ := strconv.ParseFloat(row[idx["exit_price"]], 64)
        pnl, _ := strconv.ParseFloat(row[idx["pnl"]], 64)
        slip, _ := strconv.ParseFloat(row[idx["slippage"]], 64)
        hold, _ := strconv.Atoi(row[idx["hold_cycles"]])
        conviction, _ := strconv.ParseFloat(row[idx["conviction"]], 64)

        out = append(out, &omegav1.VictoriaTrade{
            Cycle:         int32(cycle),
            Timestamp:     row[idx["timestamp"]],
            Symbol:        row[idx["symbol"]],
            Side:          row[idx["side"]],
            Size:          size,
            EntryPrice:    entry,
            ExitPrice:     exitP,
            Pnl:           pnl,
            Slippage:      slip,
            HoldCycles:    int32(hold),
            Conviction:    conviction,
            Regime:        regime,
            SitOutReason:  row[idx["sit_out_reason"]],
        })
        if len(out) >= limit {
            break
        }
    }
    return out, nil
}
```

Required imports in the same file (add if not present):
```go
import (
    "context"
    "encoding/csv"
    "fmt"
    "io"
    "os"
    "path/filepath"
    "sort"
    "strconv"

    "connectrpc.com/connect"
    omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
)
```

- [ ] **Step 4: Write a Go table-driven test**

Create `internal/handler/victoria_list_trades_test.go` next to the handler file:

```go
package handler

import (
    "context"
    "os"
    "path/filepath"
    "testing"

    "connectrpc.com/connect"
    omegav1 "github.com/benebsworth/omega/gen/go/omega/v1"
)

func TestListVictoriaTrades_ReadsNewestCSV(t *testing.T) {
    // Create a temp data dir with two CSVs; the newer one should be picked.
    tmp := t.TempDir()
    old := filepath.Join(tmp, "v01_trades.csv")
    new_ := filepath.Join(tmp, "v99_trades.csv")
    oldContent := "cycle,timestamp,symbol,side,size,entry_price,exit_price,pnl,slippage,hold_cycles,conviction,regime,sit_out_reason\n1,2020-01-01T00:00:00Z,BTCUSDT,long,100,1,2,100,0,1,0.5,bull,normal\n"
    newContent := "cycle,timestamp,symbol,side,size,entry_price,exit_price,pnl,slippage,hold_cycles,conviction,regime,sit_out_reason\n7,2026-04-04T00:00:00Z,ETHUSDT,short,50,2000,1990,500,0,2,0.12,chop,normal\n"
    if err := os.WriteFile(old, []byte(oldContent), 0644); err != nil {
        t.Fatal(err)
    }
    if err := os.WriteFile(new_, []byte(newContent), 0644); err != nil {
        t.Fatal(err)
    }
    // Chdir into tmp so filepath.Glob("data/v*_trades.csv") resolves relative to it.
    t.Setenv("PWD", tmp)
    if err := os.Chdir(tmp); err != nil {
        t.Fatal(err)
    }
    if err := os.Mkdir("data", 0755); err != nil {
        t.Fatal(err)
    }
    if err := os.Rename("v01_trades.csv", "data/v01_trades.csv"); err != nil {
        t.Fatal(err)
    }
    if err := os.Rename("v99_trades.csv", "data/v99_trades.csv"); err != nil {
        t.Fatal(err)
    }

    h := &VictoriaHandler{}
    resp, err := h.ListVictoriaTrades(
        context.Background(),
        connect.NewRequest(&omegav1.ListVictoriaTradesRequest{Limit: 10}),
    )
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
    if got := len(resp.Msg.Trades); got != 1 {
        t.Fatalf("expected 1 trade from newest CSV, got %d", got)
    }
    if got := resp.Msg.Trades[0].Symbol; got != "ETHUSDT" {
        t.Fatalf("expected ETHUSDT from newest CSV, got %s", got)
    }
}
```

- [ ] **Step 5: Run the Go test**

Run: `go test ./internal/handler/... -run TestListVictoriaTrades -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proto/omega/v1/victoria_service.proto gen/ internal/handler/
git commit -m "feat(api): add ListVictoriaTrades RPC reading newest training CSV"
```

---

### Task 4.3: Wire DecisionTrace page to real `/decisions` data

**Files:**
- Create: `dashboard/src/api/decisions.ts`
- Modify: `dashboard/src/pages/DecisionTrace.tsx`
- Create: `dashboard/src/pages/__tests__/DecisionTrace.test.tsx`

- [ ] **Step 1: Read the current DecisionTrace.tsx mock data shape**

Run: `sed -n '1,120p' dashboard/src/pages/DecisionTrace.tsx`

Expected: TypeScript interfaces for `SignalTrace`, etc., and a mock data function or import.

- [ ] **Step 2: Write the API wrapper**

Create `dashboard/src/api/decisions.ts`:

```ts
/**
 * Decision trace API wrapper. Calls the OrchestratorService /decisions endpoint
 * via Connect-RPC, falls back to mock data if the transport errors.
 */
import { client } from "../client";

// The generated Connect-ES client method name depends on the proto. Replace
// `listDecisions` below with the actual method name from
// dashboard/src/gen/omega/v1/omega_service_pb.ts if different.
//
// The expected proto shape is:
//   rpc ListDecisions(ListDecisionsRequest) returns (ListDecisionsResponse)
// with a response containing `decisions: DecisionSnapshot[]`.

export interface DecisionSnapshot {
  cycle: number;
  timestamp: string;
  nodeId: string;
  action: string;
  signals: Array<{ name: string; raw: number; normalized: number; weight: number }>;
  compositeScore: number;
  convictionBand: "hold" | "trade_low" | "trade_mid" | "trade_high";
  filterResults: Array<{ name: string; passed: boolean; reason?: string }>;
  finalAction: string;
  pnlAttribution?: number;
}

export interface ListDecisionsOptions {
  limit?: number;
  sinceCycle?: number;
  nodeId?: string;
}

export async function listDecisions(opts: ListDecisionsOptions = {}): Promise<DecisionSnapshot[]> {
  // @ts-expect-error — method name placeholder; update to match generated Connect-ES client
  const resp = await client.listDecisions({
    limit: opts.limit ?? 100,
    sinceCycle: opts.sinceCycle ?? 0,
    nodeId: opts.nodeId ?? "",
  });
  return resp.decisions.map(mapDecision);
}

function mapDecision(d: any): DecisionSnapshot {
  return {
    cycle: Number(d.cycle ?? 0),
    timestamp: String(d.timestamp ?? ""),
    nodeId: String(d.nodeId ?? ""),
    action: String(d.action ?? ""),
    signals: (d.signals ?? []).map((s: any) => ({
      name: String(s.name ?? ""),
      raw: Number(s.raw ?? 0),
      normalized: Number(s.normalized ?? 0),
      weight: Number(s.weight ?? 0),
    })),
    compositeScore: Number(d.compositeScore ?? 0),
    convictionBand: (d.convictionBand ?? "hold") as DecisionSnapshot["convictionBand"],
    filterResults: (d.filterResults ?? []).map((f: any) => ({
      name: String(f.name ?? ""),
      passed: Boolean(f.passed),
      reason: f.reason ? String(f.reason) : undefined,
    })),
    finalAction: String(d.finalAction ?? ""),
    pnlAttribution: d.pnlAttribution != null ? Number(d.pnlAttribution) : undefined,
  };
}
```

**Note to executing agent:** The `@ts-expect-error` is a temporary marker. Replace both the method name and the `@ts-expect-error` comment with the actual method name from the generated Connect-ES client. If the proto does not yet have a `ListDecisions` RPC, add it exactly as for `ListVictoriaTrades` in Task 4.2, matching the REST endpoint `/decisions` from `internal/heartbeat/decisions.go`.

- [ ] **Step 3: Write the contract test BEFORE modifying the page**

Create `dashboard/src/pages/__tests__/DecisionTrace.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import DecisionTrace from "../DecisionTrace";

vi.mock("../../api/decisions", () => ({
  listDecisions: vi.fn(),
}));

import { listDecisions } from "../../api/decisions";

describe("DecisionTrace page", () => {
  beforeEach(() => {
    vi.mocked(listDecisions).mockReset();
  });

  it("fetches decisions on mount and renders rows", async () => {
    vi.mocked(listDecisions).mockResolvedValueOnce([
      {
        cycle: 42,
        timestamp: "2026-04-04T08:00:00Z",
        nodeId: "victoria",
        action: "trade",
        signals: [{ name: "sma", raw: 0.12, normalized: 0.03, weight: 0.2 }],
        compositeScore: 0.15,
        convictionBand: "trade_mid",
        filterResults: [{ name: "ring1", passed: true }],
        finalAction: "long",
        pnlAttribution: 5.5,
      },
    ]);
    render(<DecisionTrace />);
    await waitFor(() => {
      expect(listDecisions).toHaveBeenCalled();
    });
    expect(await screen.findByText(/cycle 42/i)).toBeInTheDocument();
  });

  it("renders empty state when no decisions returned", async () => {
    vi.mocked(listDecisions).mockResolvedValueOnce([]);
    render(<DecisionTrace />);
    expect(await screen.findByText(/no decisions/i)).toBeInTheDocument();
  });

  it("renders error state when API rejects", async () => {
    vi.mocked(listDecisions).mockRejectedValueOnce(new Error("transport failure"));
    render(<DecisionTrace />);
    expect(await screen.findByText(/unable to load decision trace/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run the test (should fail)**

Run: `cd dashboard && npm run test -- DecisionTrace.test.tsx`
Expected: FAIL (the current `DecisionTrace.tsx` imports mock data, not `listDecisions`, and may not render the exact strings the test expects).

- [ ] **Step 5: Modify DecisionTrace.tsx to use the API wrapper**

Open `dashboard/src/pages/DecisionTrace.tsx`. Find the existing mock data fetch (identified in Task 4.1) and replace with:

```tsx
import { listDecisions, type DecisionSnapshot } from "../api/decisions";
// ... existing imports ...

export default function DecisionTrace() {
  const [decisions, setDecisions] = useState<DecisionSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listDecisions({ limit: 100 });
      setDecisions(rows);
    } catch (e: unknown) {
      setError("Unable to load decision trace");
      setDecisions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (loading) {
    return <div className="p-6 text-gray-400">Loading decision trace…</div>;
  }
  if (error) {
    return <div className="p-6 text-red-400">{error}</div>;
  }
  if (decisions.length === 0) {
    return <div className="p-6 text-gray-400">No decisions recorded yet.</div>;
  }

  // ... keep the existing rendering code but source from `decisions` instead of mock data ...
  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-2">
        <GitBranch className="w-5 h-5" />
        <h1 className="text-xl font-semibold">Decision Trace</h1>
        <button
          onClick={refresh}
          className="ml-auto flex items-center gap-1 text-sm text-gray-400 hover:text-white"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>
      </div>
      <div className="space-y-2">
        {decisions.map((d) => (
          <div key={`${d.cycle}-${d.nodeId}`} className="rounded border border-gray-800 p-3">
            <div className="text-sm text-gray-300">
              Cycle {d.cycle} — {d.nodeId} — <span className="font-mono">{d.finalAction}</span>
            </div>
            <div className="text-xs text-gray-500">
              {new Date(d.timestamp).toLocaleString()} · composite {d.compositeScore.toFixed(3)} ·
              conviction {d.convictionBand}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Executing agent note:** Preserve any existing visualization code (recharts bar/line charts, waterfall, filters) — the above is the *minimum* render needed to make the contract test pass. The richer rendering code from the mock-data version should be retained and simply re-sourced from `decisions` state.

- [ ] **Step 6: Run the test (should pass)**

Run: `npm run test -- DecisionTrace.test.tsx`
Expected: 3 PASS.

- [ ] **Step 7: Run full typecheck and lint**

Run: `npm run typecheck && npm run lint`
Expected: both pass.

- [ ] **Step 8: Commit**

```bash
git add dashboard/src/api/decisions.ts dashboard/src/pages/DecisionTrace.tsx dashboard/src/pages/__tests__/DecisionTrace.test.tsx
git commit -m "feat(dashboard): wire DecisionTrace page to real /decisions RPC with contract tests"
```

---

### Task 4.4: Wire NodeHealth page to real data

**Files:**
- Create: `dashboard/src/api/node_health.ts`
- Modify: `dashboard/src/pages/NodeHealth.tsx`
- Create: `dashboard/src/pages/__tests__/NodeHealth.test.tsx`

- [ ] **Step 1: Write the API wrapper**

Create `dashboard/src/api/node_health.ts`:

```ts
/**
 * Node health API wrapper. Fetches composite health score and lifecycle history
 * from the OrchestratorService.
 */
import { client } from "../client";

export interface NodeHealthRow {
  nodeId: string;
  nodeName: string;
  compositeScore: number; // 0..100
  components: {
    latency: number;
    errorRate: number;
    freshness: number;
    convergence: number;
    alignment: number;
  };
  lastTransition?: {
    fromState: string;
    toState: string;
    at: string;
  };
}

export async function listNodeHealth(): Promise<NodeHealthRow[]> {
  // @ts-expect-error — method name placeholder; update to match generated Connect-ES client
  const resp = await client.listNodeHealth({});
  return (resp.nodes ?? []).map(mapRow);
}

function mapRow(n: any): NodeHealthRow {
  return {
    nodeId: String(n.nodeId ?? ""),
    nodeName: String(n.nodeName ?? n.nodeId ?? ""),
    compositeScore: Number(n.compositeScore ?? 0),
    components: {
      latency: Number(n.components?.latency ?? 0),
      errorRate: Number(n.components?.errorRate ?? 0),
      freshness: Number(n.components?.freshness ?? 0),
      convergence: Number(n.components?.convergence ?? 0),
      alignment: Number(n.components?.alignment ?? 0),
    },
    lastTransition: n.lastTransition
      ? {
          fromState: String(n.lastTransition.fromState ?? ""),
          toState: String(n.lastTransition.toState ?? ""),
          at: String(n.lastTransition.at ?? ""),
        }
      : undefined,
  };
}
```

**Executing agent note:** Same as Task 4.3 — replace the method name with the real one from the generated client; if the RPC doesn't exist, add it following the `ListVictoriaTrades` pattern in Task 4.2. The underlying data already exists in `internal/observability/node_health_scorer.go` and `internal/heartbeat/lifecycle.go`; the RPC just needs to expose it.

- [ ] **Step 2: Write the contract test**

Create `dashboard/src/pages/__tests__/NodeHealth.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import NodeHealth from "../NodeHealth";

vi.mock("../../api/node_health", () => ({
  listNodeHealth: vi.fn(),
}));

import { listNodeHealth } from "../../api/node_health";

describe("NodeHealth page", () => {
  beforeEach(() => {
    vi.mocked(listNodeHealth).mockReset();
  });

  it("fetches node health on mount and renders composite scores", async () => {
    vi.mocked(listNodeHealth).mockResolvedValueOnce([
      {
        nodeId: "victoria-signal",
        nodeName: "Victoria Signal",
        compositeScore: 87,
        components: { latency: 90, errorRate: 95, freshness: 80, convergence: 85, alignment: 85 },
        lastTransition: { fromState: "idle", toState: "active", at: "2026-04-04T08:00:00Z" },
      },
    ]);
    render(<NodeHealth />);
    await waitFor(() => {
      expect(listNodeHealth).toHaveBeenCalled();
    });
    expect(await screen.findByText(/Victoria Signal/)).toBeInTheDocument();
    expect(screen.getByText(/87/)).toBeInTheDocument();
  });

  it("renders empty state when no nodes returned", async () => {
    vi.mocked(listNodeHealth).mockResolvedValueOnce([]);
    render(<NodeHealth />);
    expect(await screen.findByText(/no node health data/i)).toBeInTheDocument();
  });

  it("renders error state when API rejects", async () => {
    vi.mocked(listNodeHealth).mockRejectedValueOnce(new Error("transport failure"));
    render(<NodeHealth />);
    expect(await screen.findByText(/unable to load node health/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run test, expect failure**

Run: `npm run test -- NodeHealth.test.tsx`
Expected: FAIL.

- [ ] **Step 4: Modify NodeHealth.tsx to use the API wrapper**

Apply the same pattern as DecisionTrace (Task 4.3 Step 5): replace the mock data source with `listNodeHealth`, add loading/error/empty states, preserve existing rendering code (component breakdown charts, transition timelines). Key states that the tests require:

```tsx
// At top of component:
const [rows, setRows] = useState<NodeHealthRow[]>([]);
const [loading, setLoading] = useState(true);
const [error, setError] = useState<string | null>(null);

// useEffect + listNodeHealth call identical pattern to Task 4.3

// Render branches:
if (error) return <div className="p-6 text-red-400">Unable to load node health: {error}</div>;
if (rows.length === 0) return <div className="p-6 text-gray-400">No node health data.</div>;
```

- [ ] **Step 5: Run test, expect pass**

Run: `npm run test -- NodeHealth.test.tsx`
Expected: 3 PASS.

- [ ] **Step 6: Typecheck and lint**

Run: `npm run typecheck && npm run lint`
Expected: both pass.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/api/node_health.ts dashboard/src/pages/NodeHealth.tsx dashboard/src/pages/__tests__/NodeHealth.test.tsx
git commit -m "feat(dashboard): wire NodeHealth page to real health scorer + lifecycle"
```

---

### Task 4.5: Wire VictoriaTrades page to real `ListVictoriaTrades` RPC

**Files:**
- Create: `dashboard/src/api/victoria_trades.ts`
- Modify: `dashboard/src/pages/VictoriaTrades.tsx`
- Create: `dashboard/src/pages/__tests__/VictoriaTrades.test.tsx`

- [ ] **Step 1: Write the API wrapper**

Create `dashboard/src/api/victoria_trades.ts`:

```ts
/**
 * Victoria trades API wrapper. Calls ListVictoriaTrades RPC added in Task 4.2.
 */
import { createClient } from "@connectrpc/connect";
import { VictoriaService } from "../gen/omega/v1/victoria_service_pb";
import { transport } from "../client";

export interface VictoriaTradeRow {
  cycle: number;
  timestamp: string;
  symbol: string;
  side: "long" | "short";
  size: number;
  entryPrice: number;
  exitPrice: number;
  pnl: number;
  slippage: number;
  holdCycles: number;
  conviction: number;
  regime: string;
  sitOutReason: string;
}

const victoriaClient = createClient(VictoriaService, transport);

export async function listVictoriaTrades(
  limit = 200,
  regimeFilter = "",
): Promise<VictoriaTradeRow[]> {
  const resp = await victoriaClient.listVictoriaTrades({ limit, sinceCycle: "", regimeFilter });
  return resp.trades.map((t) => ({
    cycle: Number(t.cycle ?? 0),
    timestamp: String(t.timestamp ?? ""),
    symbol: String(t.symbol ?? ""),
    side: (t.side as "long" | "short") ?? "long",
    size: Number(t.size ?? 0),
    entryPrice: Number(t.entryPrice ?? 0),
    exitPrice: Number(t.exitPrice ?? 0),
    pnl: Number(t.pnl ?? 0),
    slippage: Number(t.slippage ?? 0),
    holdCycles: Number(t.holdCycles ?? 0),
    conviction: Number(t.conviction ?? 0),
    regime: String(t.regime ?? ""),
    sitOutReason: String(t.sitOutReason ?? ""),
  }));
}
```

- [ ] **Step 2: Write the contract test**

Create `dashboard/src/pages/__tests__/VictoriaTrades.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import VictoriaTrades from "../VictoriaTrades";

vi.mock("../../api/victoria_trades", () => ({
  listVictoriaTrades: vi.fn(),
}));

import { listVictoriaTrades } from "../../api/victoria_trades";

describe("VictoriaTrades page", () => {
  beforeEach(() => {
    vi.mocked(listVictoriaTrades).mockReset();
  });

  it("fetches trades on mount and renders rows", async () => {
    vi.mocked(listVictoriaTrades).mockResolvedValueOnce([
      {
        cycle: 4, timestamp: "2026-04-04T07:44:27Z", symbol: "ETHUSDT", side: "long",
        size: 6923, entryPrice: 2053.71, exitPrice: 2053.71, pnl: 0,
        slippage: 0, holdCycles: 3, conviction: 0.069, regime: "normal", sitOutReason: "normal",
      },
      {
        cycle: 5, timestamp: "2026-04-04T07:44:45Z", symbol: "LINKUSDT", side: "long",
        size: 6923, entryPrice: 8.66, exitPrice: 8.67, pnl: 7.99,
        slippage: 0, holdCycles: 4, conviction: 0.069, regime: "normal", sitOutReason: "normal",
      },
    ]);
    render(<VictoriaTrades />);
    await waitFor(() => expect(listVictoriaTrades).toHaveBeenCalled());
    expect(await screen.findByText(/LINKUSDT/)).toBeInTheDocument();
    expect(screen.getByText(/ETHUSDT/)).toBeInTheDocument();
  });

  it("renders empty state when no trades returned", async () => {
    vi.mocked(listVictoriaTrades).mockResolvedValueOnce([]);
    render(<VictoriaTrades />);
    expect(await screen.findByText(/no trades/i)).toBeInTheDocument();
  });

  it("renders error state when API rejects", async () => {
    vi.mocked(listVictoriaTrades).mockRejectedValueOnce(new Error("transport failure"));
    render(<VictoriaTrades />);
    expect(await screen.findByText(/unable to load trades/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run test, expect failure**

Run: `npm run test -- VictoriaTrades.test.tsx`
Expected: FAIL.

- [ ] **Step 4: Modify VictoriaTrades.tsx**

Same pattern as DecisionTrace/NodeHealth. Minimum changes required to make the test pass:

```tsx
import { listVictoriaTrades, type VictoriaTradeRow } from "../api/victoria_trades";

export default function VictoriaTrades() {
  const [trades, setTrades] = useState<VictoriaTradeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const rows = await listVictoriaTrades(200);
        setTrades(rows);
      } catch {
        setError("Unable to load trades");
        setTrades([]);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="p-6 text-gray-400">Loading trades…</div>;
  if (error) return <div className="p-6 text-red-400">{error}</div>;
  if (trades.length === 0) return <div className="p-6 text-gray-400">No trades yet.</div>;

  // ... existing rich rendering (PnL chart, filter controls, etc.) re-sourced from `trades` ...
}
```

- [ ] **Step 5: Run test, expect pass**

Run: `npm run test -- VictoriaTrades.test.tsx`
Expected: 3 PASS.

- [ ] **Step 6: Typecheck and lint**

Run: `npm run typecheck && npm run lint`
Expected: both pass.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/api/victoria_trades.ts dashboard/src/pages/VictoriaTrades.tsx dashboard/src/pages/__tests__/VictoriaTrades.test.tsx
git commit -m "feat(dashboard): wire VictoriaTrades page to ListVictoriaTrades RPC"
```

---

### Task 4.6: Full dashboard verification + merge to main

**Files:** none modified

- [ ] **Step 1: Run the full dashboard test suite**

Run: `cd dashboard && npm run test`
Expected: all three new contract test files pass (9 tests total). If other existing tests fail due to unrelated mocks, fix or skip as targeted repairs.

- [ ] **Step 2: Run dashboard typecheck + lint once more**

Run: `npm run typecheck && npm run lint`
Expected: both pass.

- [ ] **Step 3: Run the Go handler tests**

Run: `cd /Users/benebsworth/projects/omega-dashboard && go test ./internal/handler/... -run TestListVictoriaTrades -v`
Expected: PASS.

- [ ] **Step 4: Build the dashboard**

Run: `cd dashboard && npm run build`
Expected: clean build; no warnings about missing exports from the API wrappers.

- [ ] **Step 5: Smoke test locally (optional, recommended)**

Run: `make dev` from the worktree root, wait for the stack to come up, open http://localhost:5173, click through DecisionTrace / NodeHealth / VictoriaTrades pages. Expected: pages render with real data (or empty state if the data hasn't been generated yet — empty state is acceptable).

- [ ] **Step 6: Review branch log**

Run: `git log --oneline main..HEAD`
Expected: one commit per task (4.0 scaffold if Vitest added, 4.2 if RPC added, 4.3, 4.4, 4.5) — 4 to 6 commits total.

- [ ] **Step 7: Return to main and cherry-pick**

Run:
```bash
cd /Users/benebsworth/projects/omega
git cherry-pick dashboard/real-data~5..dashboard/real-data  # adjust range to actual commit count
```

Expected: clean cherry-pick.

- [ ] **Step 8: Verify on main**

Run:
```bash
ls dashboard/src/api/decisions.ts dashboard/src/api/node_health.ts dashboard/src/api/victoria_trades.ts
ls dashboard/src/pages/__tests__/DecisionTrace.test.tsx dashboard/src/pages/__tests__/NodeHealth.test.tsx dashboard/src/pages/__tests__/VictoriaTrades.test.tsx
cd dashboard && npm run test
```
Expected: all files exist; all tests pass on main.

- [ ] **Step 9: Remove the worktree**

Run:
```bash
cd /Users/benebsworth/projects/omega
git worktree remove ../omega-dashboard
git branch -d dashboard/real-data
```

**Agent 4 complete.**

---

# PHASE 1 EXIT CRITERIA

- [ ] `data/v35-v48-forensics.json` exists on `main` with `schema_version: "1.0"`, `status: "ok"`, and 3 hypotheses.
- [ ] `docs/training/v35-v48-forensics.md` exists on `main` and contains the top-1 hypothesis in its body.
- [ ] All 13 forensics unit/integration tests pass (`python3 -m pytest tests/test_forensics_*.py -v`).
- [ ] `DecisionTrace`, `NodeHealth`, `VictoriaTrades` dashboard pages render from real API wrappers (mock imports removed from these three files).
- [ ] 9 new dashboard contract tests pass (`cd dashboard && npm run test`).
- [ ] `go test ./internal/handler/...` passes (including new `TestListVictoriaTrades` if RPC was added).
- [ ] Both Agent 1 and Agent 4 worktrees removed; both branches deleted.

---

# PHASE 2 HANDOFF

Once Phase 1 exit criteria are met, Phase 2 planning begins. Phase 2 covers:
- **Agent 2** — V49 calibration run driven by `data/v35-v48-forensics.json` hypothesis #1; V49 hard gates enforced in `scripts/run_training.py`.
- **Agent 3** — TimesFM + Wasserstein signal producers (dry-run, weight=0) wired into `signal_generation.py`.
- **Agent 5** — Meta-analyst node + `TrainingProposal` protobuf + full trust-ladder stages 1+2+3 active.

**Before writing Phase 2:**
1. Read `data/v35-v48-forensics.json` top hypothesis.
2. If the top hypothesis is "conviction magnitudes collapsed / HOLD band too wide" (expected based on spec), Phase 2 Agent 2 tasks will target `omega/nodes/victoria/strategy.py` conviction threshold computation.
3. If the top hypothesis is something else (skipped trades, signal concentration, zero-trade ratio), Phase 2 Agent 2 scope pivots accordingly.
4. Phase 2 plan file: `docs/superpowers/plans/YYYY-MM-DD-victoria-v49-phase2-calibration-signals-meta-analyst.md`.

Phase 2 is invoked by re-running `superpowers:writing-plans` with this handoff as input.
