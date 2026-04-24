#!/usr/bin/env python3
"""
scripts/auto_improve.py
~~~~~~~~~~~~~~~~~~~~~~~
Autonomous self-improving loop for Victoria parameters.

Full loop (no human intervention required):
  Iteration 0 : fresh baseline run — establishes composite reference PnL
  Iteration N : RUN → EVALUATE → REASON → DECIDE → PLAN → IMPLEMENT → LOG → REPEAT

Decisions:
  ACCEPT      — composite_pnl > prev_best × 1.02  (clear improvement)
  INVESTIGATE — marginal change ±2%, try different direction
  REVERT      — composite_pnl < prev_best × 0.98  (regression confirmed)
  HALT        — safety condition triggered
  CONVERGED   — convergence criteria met

Planner strategy:
  N < 5  : axis-aligned perturbations from best known config (structured search)
  N >= 5 : GP-guided via ManifoldGP (penalised EI, λ=0.2)

Safety halts (checked before every iteration):
  - composite_pnl < -30 000
  - any snapshot n_trades < 20
  - 3 consecutive regressions

Convergence (checked after each accepted iteration):
  - <5% improvement over last 3 accepted iterations
  - all 3 snapshots positive and stable

Crash-safe: each iteration appended to data/auto_improve_log.jsonl before loop
continues — process can be killed and resumed with --resume at any time.

Usage:
    python scripts/auto_improve.py                          # full 10 iterations
    python scripts/auto_improve.py --smoke-test             # 50 cycles, 1 iteration
    python scripts/auto_improve.py --max-iterations 10 --cycles 200
    python scripts/auto_improve.py --resume                 # resume from log
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("auto_improve")

DATA_DIR = ROOT / "data"
LOG_FILE = DATA_DIR / "auto_improve_log.jsonl"

# Canonical parameter search bounds (VictoriaFeatures field names)
# Only live params that actually affect trade outcomes in v161_no_llm:
#   - dyn_floor_crisis/normal were LLM modifier floors (no-op when llm_analyst_enabled=False)
#   - crisis_short_thresh_scale: scales short conviction threshold in crisis
#   - strategy_selector thresholds: control TREND/CRISIS mode entry probability gates
#   - bear_prob_long_block_threshold: bear_prob above which longs are blocked
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "trend_dampening_bull_prob_threshold": (0.45, 0.80),
    "crisis_short_thresh_scale": (0.2, 1.0),
    "strategy_selector_trend_bull_threshold": (0.50, 0.75),
    "strategy_selector_crisis_bear_threshold": (0.40, 0.70),
    "bear_prob_long_block_threshold": (0.40, 0.70),
    # V163 expansion: recent-snapshot recovery hinges on normal/high_vol regimes.
    # dyn_floor_* gates how much the LLM can override the strategy in each regime.
    "dyn_floor_normal": (0.50, 0.95),
    "dyn_floor_high_vol": (0.40, 0.90),
}

SNAPSHOT_ALIASES: dict[str, str] = {
    "recent": str(DATA_DIR / "snapshots" / "snap_20260414.json"),
    "crisis": str(DATA_DIR / "snapshots" / "snap_crisis_2022h1.json"),
    "trend": str(DATA_DIR / "snapshots" / "snap_trending_2023q4.json"),
}

# Safety thresholds
HALT_PNL_FLOOR = -30_000.0
HALT_MIN_TRADES = 20
HALT_CONSECUTIVE_REGRESSIONS = 3

# Decision thresholds
ACCEPT_IMPROVEMENT_PCT = 0.02   # >= 2% improvement → ACCEPT
REVERT_REGRESSION_PCT = -0.02   # <= -2% → REVERT (else INVESTIGATE)

# Convergence
CONVERGE_MIN_IMPROVEMENT_PCT = 0.05   # <5% over CONVERGE_WINDOW iterations
CONVERGE_WINDOW = 3

# GP activation
GP_MIN_OBSERVATIONS = 5


# ---------------------------------------------------------------------------
# Environment loader
# ---------------------------------------------------------------------------

def _load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SnapshotResult:
    snapshot: str
    pnl: float
    profit_factor: float
    win_rate: float
    n_trades: int
    version: str


@dataclass
class Iteration:
    iteration: int
    version: str
    params: dict[str, float]
    per_snapshot: list[SnapshotResult]
    composite_pnl: float
    decision: str       # ACCEPT | INVESTIGATE | REVERT | HALT | CONVERGED
    reasoning: str
    next_experiment: dict[str, float] | None
    timestamp: str
    elapsed_s: float = 0.0

    def to_json(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Crash-safe JSONL log
# ---------------------------------------------------------------------------

def _append_log(record: Iteration) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record.to_json()) + "\n")
        f.flush()


def _load_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    records: list[dict] = []
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


# ---------------------------------------------------------------------------
# Backtest runner
# ---------------------------------------------------------------------------

async def _run_one_backtest(
    sem: asyncio.Semaphore,
    version: str,
    features_json: str,
    snapshot_key: str,
    snapshot_path: str,
    cycles: int,
    seed: int,
) -> SnapshotResult:
    """Run one backtest (version × snapshot) and return SnapshotResult."""
    async with sem:
        log.info("  RUN  %s × %s", version, snapshot_key)
        t0 = time.monotonic()
        cmd = [
            sys.executable, str(ROOT / "scripts" / "run_training.py"),
            "--version", version,
            "--cycles", str(cycles),
            "--sleep", "0",
            "--features", features_json,
            "--backtest-snapshot", snapshot_path,
            "--seed", str(seed),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await proc.wait()
        elapsed = time.monotonic() - t0

        results_path = DATA_DIR / f"{version}_results.json"
        if not results_path.exists():
            log.warning("  FAIL %s × %s  rc=%d  %.0fs  (no results file)", version, snapshot_key, rc, elapsed)
            return SnapshotResult(
                snapshot=snapshot_key, pnl=-99_999.0, profit_factor=0.0,
                win_rate=0.0, n_trades=0, version=version,
            )
        if rc != 0:
            # Process exited non-zero but results file exists — prefer partial data
            # over a synthetic -99,999 that would spuriously halt the loop.
            log.warning("  PARTIAL %s × %s  rc=%d  %.0fs  (using results file)", version, snapshot_key, rc, elapsed)

        with open(results_path) as fh:
            data = json.load(fh)
        t = data.get("trades", data)
        pnl = float(t.get("total_pnl_usd", t.get("total_pnl", 0.0)))
        pf = float(t.get("profit_factor", 0.0))
        wr = float(t.get("win_rate", 0.0))
        nt = int(t.get("total_closed", t.get("n_trades", t.get("total_trades", 0))))
        log.info(
            "  DONE %s × %s  pnl=%s  pf=%.2f  wr=%.1f%%  trades=%d  %.0fs",
            version, snapshot_key, f"{pnl:+,.0f}", pf, wr * 100, nt, elapsed,
        )
        return SnapshotResult(
            snapshot=snapshot_key, pnl=pnl, profit_factor=pf,
            win_rate=wr, n_trades=nt, version=version,
        )


class BacktestRunner:
    def __init__(
        self,
        cycles: int,
        max_parallel: int = 3,
        seed: int = 42,
        snapshots: dict[str, str] | None = None,
        snapshot_cycles: dict[str, int] | None = None,
    ):
        self.cycles = cycles
        self.max_parallel = max_parallel
        self.seed = seed
        self.snapshots = snapshots or SNAPSHOT_ALIASES
        # Per-snapshot cycle overrides; falls back to self.cycles if key absent
        self.snapshot_cycles: dict[str, int] = snapshot_cycles or {}

    async def run(
        self,
        iteration: int,
        params: dict[str, float],
        base_preset: str,
    ) -> tuple[list[SnapshotResult], float]:
        """Run configured snapshots concurrently. Returns (results, composite_pnl)."""
        from omega.nodes.victoria.features import VictoriaFeatures

        base = asdict(VictoriaFeatures.preset(base_preset))
        base.update(params)
        features_json = json.dumps(base)

        sem = asyncio.Semaphore(self.max_parallel)
        tasks = []
        for snap_key, snap_path in self.snapshots.items():
            snap_cycles = self.snapshot_cycles.get(snap_key, self.cycles)
            version = f"ai_{iteration:03d}_{snap_key}"
            tasks.append(
                _run_one_backtest(
                    sem, version, features_json,
                    snap_key, snap_path, snap_cycles, self.seed,
                )
            )

        results: list[SnapshotResult] = list(await asyncio.gather(*tasks))
        composite_pnl = sum(r.pnl for r in results)
        return results, composite_pnl


# ---------------------------------------------------------------------------
# Rule-based reasoner (deterministic, no LLM)
# ---------------------------------------------------------------------------

class RuleReasoner:
    def reason(
        self,
        iteration: int,
        current_composite: float,
        best_composite: float,
        per_snapshot: list[SnapshotResult],
        consecutive_regressions: int,
    ) -> tuple[str, str]:
        """Return (decision, reasoning). decision ∈ {ACCEPT, INVESTIGATE, REVERT, HALT}."""
        min_trades = min(r.n_trades for r in per_snapshot) if per_snapshot else 0
        snap_summary = "  ".join(
            f"{r.snapshot}={r.pnl:+,.0f}({r.n_trades}t)" for r in per_snapshot
        )

        # ── Safety halts (checked first) ────────────────────────────────────
        if current_composite < HALT_PNL_FLOOR:
            return "HALT", (
                f"composite_pnl={current_composite:+,.0f} below halt floor "
                f"{HALT_PNL_FLOOR:+,.0f}. [{snap_summary}]"
            )
        if per_snapshot and min_trades < HALT_MIN_TRADES:
            bad = [r for r in per_snapshot if r.n_trades < HALT_MIN_TRADES]
            return "HALT", (
                f"min_trades={min_trades} < {HALT_MIN_TRADES} on "
                f"{[r.snapshot for r in bad]}. Too few trades for reliable signal."
            )
        if consecutive_regressions >= HALT_CONSECUTIVE_REGRESSIONS:
            return "HALT", (
                f"{consecutive_regressions} consecutive regressions. "
                "Search is diverging — halting for safety."
            )

        # ── Iteration 0: baseline ───────────────────────────────────────────
        if iteration == 0:
            return "ACCEPT", (
                f"Baseline iteration. composite_pnl={current_composite:+,.0f}. "
                f"[{snap_summary}]"
            )

        # ── Compute improvement ratio ───────────────────────────────────────
        denom = abs(best_composite) + 1.0
        improvement_pct = (current_composite - best_composite) / denom

        if improvement_pct >= ACCEPT_IMPROVEMENT_PCT:
            return "ACCEPT", (
                f"composite={current_composite:+,.0f} vs best={best_composite:+,.0f} "
                f"(+{improvement_pct:.1%}). [{snap_summary}]"
            )

        if improvement_pct >= REVERT_REGRESSION_PCT:
            # Marginal zone: ±2%
            negative_snaps = [r for r in per_snapshot if r.pnl < 0]
            if negative_snaps:
                return "INVESTIGATE", (
                    f"composite={current_composite:+,.0f} marginal ({improvement_pct:+.1%}). "
                    f"Negative snapshot(s): {[r.snapshot for r in negative_snaps]}. "
                    "Trying different direction. [{snap_summary}]"
                )
            return "INVESTIGATE", (
                f"composite={current_composite:+,.0f} marginal ({improvement_pct:+.1%}). "
                f"All snapshots positive — searching for better flat region. [{snap_summary}]"
            )

        # Regression
        return "REVERT", (
            f"composite={current_composite:+,.0f} vs best={best_composite:+,.0f} "
            f"({improvement_pct:+.1%}). Regression — reverting to best known. [{snap_summary}]"
        )


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class Planner:
    """Proposes next parameter config to evaluate."""

    def __init__(self, lambda_curv: float = 0.2):
        self.lambda_curv = lambda_curv
        self._tried: set[str] = set()

    def _key(self, params: dict[str, float]) -> str:
        return json.dumps({k: round(v, 4) for k, v in sorted(params.items())})

    def _structured_candidates(
        self, best_params: dict[str, float], step_frac: float = 0.1
    ) -> list[dict[str, float]]:
        """Axis-aligned perturbations, one param at a time, ±step."""
        candidates: list[dict[str, float]] = []
        for pname, (lo, hi) in PARAM_BOUNDS.items():
            step = (hi - lo) * step_frac
            for delta in [+step, -step]:
                new_val = round(float(max(lo, min(hi, best_params[pname] + delta))), 4)
                if abs(new_val - best_params[pname]) < 1e-6:
                    continue
                candidate = dict(best_params)
                candidate[pname] = new_val
                if self._key(candidate) not in self._tried:
                    candidates.append(candidate)
        return candidates

    def _gp_candidate(
        self, observations: list[tuple[dict[str, float], float]]
    ) -> dict[str, float] | None:
        """GP-guided suggestion via ManifoldGP + penalised EI."""
        try:
            import numpy as np
            # Add scripts/ to path for manifold_optimizer import
            scripts_dir = str(ROOT / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from manifold_optimizer import ManifoldGP  # type: ignore

            mgp = ManifoldGP(PARAM_BOUNDS)
            param_names = mgp.param_names

            X_raw = np.array([[p[pn] for pn in param_names] for p, _ in observations])
            y = np.array([score for _, score in observations])
            mgp.fit(X_raw, y)

            suggestions = mgp.suggest_next(lambda_curv=self.lambda_curv)
            if len(suggestions) == 0:
                return None
            suggestion = suggestions[0]
            return {pname: round(float(suggestion[i]), 4) for i, pname in enumerate(param_names)}
        except Exception as exc:
            log.warning("GP suggestion failed: %s", exc)
            return None

    def propose(
        self,
        observations: list[tuple[dict[str, float], float]],
        best_params: dict[str, float],
        decision: str,
    ) -> dict[str, float]:
        """Return next params to try, updating internal tried-set."""
        self._tried.add(self._key(best_params))
        n = len(observations)

        if n >= GP_MIN_OBSERVATIONS:
            candidate = self._gp_candidate(observations)
            if candidate and self._key(candidate) not in self._tried:
                self._tried.add(self._key(candidate))
                log.info("  PLAN  GP-guided suggestion: %s", candidate)
                return candidate
            log.info("  PLAN  GP suggestion tried or failed — falling back to structured search")

        # Structured search
        step_frac = 0.08 if decision == "REVERT" else 0.12
        candidates = self._structured_candidates(best_params, step_frac)
        if candidates:
            chosen = candidates[0]
            self._tried.add(self._key(chosen))
            log.info("  PLAN  Structured candidate (step=%.0f%%): %s", step_frac * 100, chosen)
            return chosen

        # Last resort: tiny random perturbation
        import random
        rng = random.Random()
        candidate = dict(best_params)
        for pname, (lo, hi) in PARAM_BOUNDS.items():
            delta = rng.uniform(-0.05 * (hi - lo), 0.05 * (hi - lo))
            candidate[pname] = round(float(max(lo, min(hi, candidate[pname] + delta))), 4)
        log.info("  PLAN  Fallback random perturbation: %s", candidate)
        return candidate


# ---------------------------------------------------------------------------
# Convergence checker
# ---------------------------------------------------------------------------

def _check_convergence(
    accepted_pnls: list[float],
    accepted_snap_results: list[list[SnapshotResult]],
) -> tuple[bool, str]:
    """Return (converged, reason_string)."""
    if len(accepted_pnls) < CONVERGE_WINDOW + 1:
        return False, ""

    recent = accepted_pnls[-CONVERGE_WINDOW:]
    baseline = accepted_pnls[-(CONVERGE_WINDOW + 1)]
    denom = abs(baseline) + 1.0
    max_improvement = max(abs(p - baseline) / denom for p in recent)

    if max_improvement < CONVERGE_MIN_IMPROVEMENT_PCT:
        return True, (
            f"<{CONVERGE_MIN_IMPROVEMENT_PCT:.0%} improvement over last "
            f"{CONVERGE_WINDOW} accepted iterations "
            f"(baseline={baseline:+,.0f}, recent={[f'{p:+,.0f}' for p in recent]})."
        )

    # All snapshots positive and marginal improvement
    if len(accepted_snap_results) >= CONVERGE_WINDOW:
        recent_results = accepted_snap_results[-CONVERGE_WINDOW:]
        all_positive = all(
            all(r.pnl > 0 for r in snap_results)
            for snap_results in recent_results
        )
        if all_positive and max_improvement < CONVERGE_MIN_IMPROVEMENT_PCT * 2:
            return True, (
                f"All snapshots positive and stable over last {CONVERGE_WINDOW} "
                "accepted iterations — system has converged on robust region."
            )

    return False, ""


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

class AutoImprove:
    def __init__(
        self,
        base_preset: str = "v153_trend_only",
        cycles: int = 200,
        max_iterations: int = 10,
        max_parallel: int = 3,
        seed: int = 42,
        resume: bool = False,
        lambda_curv: float = 0.2,
        snapshots: dict[str, str] | None = None,
        start_params: dict[str, float] | None = None,
        log_file: str | None = None,
        snapshot_cycles: dict[str, int] | None = None,
    ):
        self.base_preset = base_preset
        self.cycles = cycles
        self.max_iterations = max_iterations
        self.max_parallel = max_parallel
        self.seed = seed
        self.resume = resume
        self._snapshots = snapshots or SNAPSHOT_ALIASES
        self._start_params = start_params  # override baseline if provided
        global LOG_FILE
        if log_file:
            LOG_FILE = Path(log_file)

        self.runner = BacktestRunner(
            cycles, max_parallel, seed,
            snapshots=self._snapshots, snapshot_cycles=snapshot_cycles,
        )
        self.reasoner = RuleReasoner()
        self.planner = Planner(lambda_curv=lambda_curv)

        # Mutable state
        self._iterations: list[Iteration] = []
        self._best_composite: float = -float("inf")
        self._best_params: dict[str, float] = {}
        self._consecutive_regressions: int = 0
        self._accepted_pnls: list[float] = []
        self._accepted_snap_results: list[list[SnapshotResult]] = []
        self._observations: list[tuple[dict[str, float], float]] = []

    def _baseline_params(self) -> dict[str, float]:
        if self._start_params:
            # Ensure all PARAM_BOUNDS keys present; fill missing from preset
            from omega.nodes.victoria.features import VictoriaFeatures
            base = asdict(VictoriaFeatures.preset(self.base_preset))
            result = {k: float(base[k]) for k in PARAM_BOUNDS}
            result.update({k: float(v) for k, v in self._start_params.items() if k in PARAM_BOUNDS})
            return result
        from omega.nodes.victoria.features import VictoriaFeatures
        base = asdict(VictoriaFeatures.preset(self.base_preset))
        return {k: float(base[k]) for k in PARAM_BOUNDS}

    def _load_resume_state(self) -> int:
        records = _load_log()
        if not records:
            return 0
        log.info("Resuming from %d prior iterations in %s", len(records), LOG_FILE)
        for rec in records:
            if rec.get("decision") == "CONVERGED":
                continue
            per_snap = [SnapshotResult(**s) for s in rec.get("per_snapshot", [])]
            it = Iteration(
                iteration=rec["iteration"],
                version=rec["version"],
                params=rec["params"],
                per_snapshot=per_snap,
                composite_pnl=rec["composite_pnl"],
                decision=rec["decision"],
                reasoning=rec["reasoning"],
                next_experiment=rec.get("next_experiment"),
                timestamp=rec["timestamp"],
                elapsed_s=rec.get("elapsed_s", 0.0),
            )
            self._iterations.append(it)
            self._observations.append((rec["params"], rec["composite_pnl"]))

            decision = rec["decision"]
            if decision == "ACCEPT":
                if rec["composite_pnl"] > self._best_composite:
                    self._best_composite = rec["composite_pnl"]
                    self._best_params = rec["params"]
                self._accepted_pnls.append(rec["composite_pnl"])
                self._accepted_snap_results.append(per_snap)
                self._consecutive_regressions = 0
            elif decision == "REVERT":
                self._consecutive_regressions += 1
            elif decision == "HALT":
                pass
            else:  # INVESTIGATE
                self._consecutive_regressions = 0

        return len([r for r in records if r.get("decision") != "CONVERGED"])

    async def run(self) -> None:
        start_iteration = 0

        if self.resume:
            start_iteration = self._load_resume_state()
            if start_iteration >= self.max_iterations:
                log.info("Already completed %d iterations. Use --max-iterations to extend.", start_iteration)
                return

        if not self._best_params:
            self._best_params = self._baseline_params()

        _snap_cyc_str = (
            ", ".join(f"{k}={v}" for k, v in self.runner.snapshot_cycles.items())
            if self.runner.snapshot_cycles else f"all={self.cycles}"
        )
        log.info(
            "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "  AUTO-IMPROVE  preset=%s  cycles=%s  max_iter=%d\n"
            "  Log: %s\n"
            "  Starting from iteration %d\n"
            "  Initial params: %s\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            self.base_preset, _snap_cyc_str, self.max_iterations,
            LOG_FILE, start_iteration, self._best_params,
        )

        next_params: dict[str, float] | None = None

        for iteration in range(start_iteration, self.max_iterations):
            # Determine params for this iteration
            if iteration == 0:
                params = self._best_params
            elif next_params is not None:
                params = next_params
            else:
                params = self._best_params

            log.info(
                "\n┌─ ITERATION %d / %d ──────────────────────────────\n"
                "│  Params: %s\n"
                "└──────────────────────────────────────────────────",
                iteration, self.max_iterations - 1, params,
            )

            t0 = time.monotonic()

            # ── RUN ──────────────────────────────────────────────────────────
            per_snapshot, composite_pnl = await self.runner.run(
                iteration, params, self.base_preset,
            )

            # ── EVALUATE + REASON ─────────────────────────────────────────────
            decision, reasoning = self.reasoner.reason(
                iteration=iteration,
                current_composite=composite_pnl,
                best_composite=self._best_composite,
                per_snapshot=per_snapshot,
                consecutive_regressions=self._consecutive_regressions,
            )

            # ── UPDATE STATE ──────────────────────────────────────────────────
            self._observations.append((params, composite_pnl))

            if decision == "ACCEPT":
                prev_best = self._best_composite
                self._best_composite = composite_pnl
                self._best_params = params
                self._consecutive_regressions = 0
                self._accepted_pnls.append(composite_pnl)
                self._accepted_snap_results.append(per_snapshot)
                log.info(
                    "  ✓ ACCEPT  composite=%s  (prev_best=%s)",
                    f"{composite_pnl:+,.0f}", f"{prev_best:+,.0f}",
                )
            elif decision == "REVERT":
                self._consecutive_regressions += 1
                log.info(
                    "  ✗ REVERT  composite=%s  (best=%s  regressions=%d)",
                    f"{composite_pnl:+,.0f}", f"{self._best_composite:+,.0f}",
                    self._consecutive_regressions,
                )
            elif decision == "HALT":
                pass  # handled below
            else:  # INVESTIGATE
                self._consecutive_regressions = 0
                log.info(
                    "  ~ INVEST  composite=%s  (best=%s)",
                    f"{composite_pnl:+,.0f}", f"{self._best_composite:+,.0f}",
                )

            # ── PLAN ──────────────────────────────────────────────────────────
            next_params = None
            if decision not in ("HALT",):
                next_params = self.planner.propose(
                    self._observations,
                    self._best_params,
                    decision,
                )

            # ── LOG ───────────────────────────────────────────────────────────
            elapsed = time.monotonic() - t0
            record = Iteration(
                iteration=iteration,
                version=f"ai_{iteration:03d}",
                params=params,
                per_snapshot=per_snapshot,
                composite_pnl=composite_pnl,
                decision=decision,
                reasoning=reasoning,
                next_experiment=next_params,
                timestamp=datetime.now(timezone.utc).isoformat(),
                elapsed_s=round(elapsed, 1),
            )
            self._iterations.append(record)
            _append_log(record)

            log.info("  REASON: %s", reasoning)
            log.info("  elapsed=%.0fs  next=%s", elapsed, next_params)

            # ── HALT ──────────────────────────────────────────────────────────
            if decision == "HALT":
                log.warning("\n⛔ SAFETY HALT at iteration %d — %s", iteration, reasoning)
                break

            # ── CONVERGENCE CHECK ─────────────────────────────────────────────
            converged, conv_reason = _check_convergence(
                self._accepted_pnls, self._accepted_snap_results,
            )
            if converged:
                log.info("\n✓ CONVERGED at iteration %d — %s", iteration, conv_reason)
                _append_log(Iteration(
                    iteration=iteration + 1,
                    version="converged",
                    params=self._best_params,
                    per_snapshot=[],
                    composite_pnl=self._best_composite,
                    decision="CONVERGED",
                    reasoning=conv_reason,
                    next_experiment=None,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))
                break

            if next_params is None:
                break

        # ── FINAL SUMMARY ─────────────────────────────────────────────────────
        n_run = len(self._iterations)
        decisions = {d: sum(1 for it in self._iterations if it.decision == d)
                     for d in ("ACCEPT", "INVESTIGATE", "REVERT", "HALT")}
        log.info(
            "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "  AUTO-IMPROVE COMPLETE\n"
            "  Best composite PnL : %s\n"
            "  Best params        : %s\n"
            "  Iterations run     : %d\n"
            "  Decisions          : %s\n"
            "  Log                : %s\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"{self._best_composite:+,.0f}",
            self._best_params,
            n_run,
            decisions,
            LOG_FILE,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Autonomous Victoria self-improvement loop",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--base-preset", default="v153_trend_only",
                   help="Base VictoriaFeatures preset")
    p.add_argument("--cycles", type=int, default=200,
                   help="Backtest cycles per snapshot per iteration")
    p.add_argument("--max-iterations", type=int, default=10,
                   help="Maximum improvement iterations")
    p.add_argument("--max-parallel", type=int, default=3,
                   help="Max concurrent backtests")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--lambda-curv", type=float, default=0.2,
                   help="GP curvature penalty λ (0=standard EI, 0.2=moderate ridge bias)")
    p.add_argument("--smoke-test", action="store_true",
                   help="50 cycles, 1 iteration — fast sanity check")
    p.add_argument("--resume", action="store_true",
                   help="Resume from log file")
    p.add_argument("--snapshots", nargs="+", default=None,
                   metavar="SNAP",
                   help="Snapshot keys to use (default: recent crisis trend). "
                        "E.g. --snapshots recent crisis")
    p.add_argument("--start-params", default=None,
                   help='JSON dict of starting params, e.g. \'{"dyn_floor_crisis":0.0,"trend_dampening_bull_prob_threshold":0.55,"dyn_floor_normal":0.8}\'')
    p.add_argument("--log-file", default=None,
                   help="Override log file path (default: data/auto_improve_log.jsonl)")
    p.add_argument("--snapshot-cycles", default=None,
                   help="Per-snapshot cycle overrides in key=value format, comma-separated. "
                        "E.g. --snapshot-cycles recent=300,crisis=150,trend=300. "
                        "Unspecified snapshots use --cycles.")
    return p.parse_args()


def main() -> None:
    _load_env()
    args = _parse_args()

    if args.smoke_test:
        log.info("SMOKE TEST — 50 cycles, 1 iteration, min_trades=5")
        args.cycles = 50
        args.max_iterations = 1
        global HALT_MIN_TRADES
        HALT_MIN_TRADES = 5

    # Resolve snapshots
    snap_dict: dict[str, str] | None = None
    if args.snapshots:
        snap_dict = {k: SNAPSHOT_ALIASES[k] for k in args.snapshots if k in SNAPSHOT_ALIASES}
        if len(snap_dict) != len(args.snapshots):
            unknown = [k for k in args.snapshots if k not in SNAPSHOT_ALIASES]
            log.error("Unknown snapshot keys: %s  (valid: %s)", unknown, list(SNAPSHOT_ALIASES))
            sys.exit(1)

    start_params: dict[str, float] | None = None
    if args.start_params:
        start_params = json.loads(args.start_params)

    snapshot_cycles: dict[str, int] | None = None
    if args.snapshot_cycles:
        snapshot_cycles = {}
        for part in args.snapshot_cycles.split(","):
            k, _, v = part.strip().partition("=")
            if k and v:
                snapshot_cycles[k.strip()] = int(v.strip())
        if not snapshot_cycles:
            log.error("Invalid --snapshot-cycles format. Expected: recent=300,crisis=150,trend=300")
            sys.exit(1)

    loop = AutoImprove(
        base_preset=args.base_preset,
        cycles=args.cycles,
        max_iterations=args.max_iterations,
        max_parallel=args.max_parallel,
        seed=args.seed,
        resume=args.resume,
        lambda_curv=args.lambda_curv,
        snapshots=snap_dict,
        start_params=start_params,
        log_file=args.log_file,
        snapshot_cycles=snapshot_cycles,
    )
    asyncio.run(loop.run())


if __name__ == "__main__":
    main()
