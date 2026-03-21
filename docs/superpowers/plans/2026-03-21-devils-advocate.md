# Devil's Advocate Agent Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Devil's Advocate meta-node that challenges every architectural decision, gates improvements with property/invariant checks, and maintains a persistent challenge registry — wired into the Vectora heartbeat loop.

**Architecture:** Three new `omega/core/` modules (`challenge_registry.py`, `verification_gates.py`) plus one new node (`omega/nodes/devils_advocate.py`), all following the existing Node/StateStore/SQLite patterns. The `DevilsAdvocateNode` implements the `Node` ABC and runs after `improve_system()` in `vectora_main.py`. `ChallengeRegistry` gets its own SQLite table seeded with 16 substantive challenges covering both current and planned architecture.

**Tech Stack:** Python 3.10+, sqlite3 (stdlib), pytest, existing `omega.core.node`, `omega.core.state_store`, `omega.core.orchestrator`.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `omega/core/challenge_registry.py` | Create | SQLite-backed store for challenges; CRUD + health metric |
| `omega/core/verification_gates.py` | Create | Composable gate objects: Property/Invariant/Consistency/Regression/Convergence + And/Or |
| `omega/nodes/devils_advocate.py` | Create | `DevilsAdvocateNode` — 5 operating modes, runs review, produces Challenge reports |
| `omega/skills/devils-advocate/SKILL.md` | Create | Adversarial thinking skill for agents |
| `omega/nodes/__init__.py` | Modify | Export `DevilsAdvocateNode` |
| `omega/examples/vectora_main.py` | Modify | Wire DA node after `improve_system()` in heartbeat |
| `tests/test_challenge_registry.py` | Create | Unit tests for ChallengeRegistry |
| `tests/test_verification_gates.py` | Create | Unit tests for VerificationGateSystem |
| `tests/test_devils_advocate.py` | Create | Unit + integration tests for DevilsAdvocateNode |

---

## Task 1: ChallengeRegistry

**Files:**
- Create: `omega/core/challenge_registry.py`
- Create: `tests/test_challenge_registry.py`

- [ ] **Step 1.1: Write failing tests first**

```python
# tests/test_challenge_registry.py
import pytest
from omega.core.challenge_registry import ChallengeRegistry, Challenge, ChallengeSeverity, ChallengeStatus

class TestChallengeRegistry:
    def setup_method(self):
        self.reg = ChallengeRegistry(db_path=":memory:")

    def test_add_and_get(self):
        cid = self.reg.add(
            target_subsystem="orchestrator",
            severity=ChallengeSeverity.HIGH,
            description="Test challenge",
            evidence="Some evidence",
        )
        ch = self.reg.get(cid)
        assert ch is not None
        assert ch.description == "Test challenge"
        assert ch.status == ChallengeStatus.OPEN
        assert ch.severity == ChallengeSeverity.HIGH

    def test_update_status(self):
        cid = self.reg.add(
            target_subsystem="memory",
            severity=ChallengeSeverity.MEDIUM,
            description="Memory test",
            evidence="Evidence",
        )
        self.reg.update_status(cid, ChallengeStatus.RESOLVED, resolution_notes="Fixed it")
        ch = self.reg.get(cid)
        assert ch.status == ChallengeStatus.RESOLVED
        assert ch.resolution_notes == "Fixed it"

    def test_open_challenges(self):
        self.reg.add("sys", ChallengeSeverity.CRITICAL, "Critical issue", "Evidence")
        self.reg.add("sys", ChallengeSeverity.LOW, "Low issue", "Evidence")
        cid3 = self.reg.add("sys", ChallengeSeverity.HIGH, "High issue", "Evidence")
        self.reg.update_status(cid3, ChallengeStatus.WONTFIX)
        open_chs = self.reg.open_challenges()
        assert len(open_chs) == 2

    def test_resolution_rate_zero_when_all_open(self):
        self.reg.add("sys", ChallengeSeverity.HIGH, "A", "E")
        self.reg.add("sys", ChallengeSeverity.HIGH, "B", "E")
        assert self.reg.resolution_rate() == 0.0

    def test_resolution_rate_partial(self):
        cid1 = self.reg.add("sys", ChallengeSeverity.HIGH, "A", "E")
        self.reg.add("sys", ChallengeSeverity.HIGH, "B", "E")
        self.reg.update_status(cid1, ChallengeStatus.RESOLVED)
        assert self.reg.resolution_rate() == pytest.approx(0.5)

    def test_critical_unresolved_blocks(self):
        self.reg.add("sys", ChallengeSeverity.CRITICAL, "Blocker", "Evidence")
        assert self.reg.has_blocking_challenges() is True

    def test_no_blocking_if_none_critical(self):
        self.reg.add("sys", ChallengeSeverity.HIGH, "High but not critical", "E")
        assert self.reg.has_blocking_challenges() is False

    def test_seed_challenges(self):
        self.reg.seed_initial_challenges()
        all_chs = self.reg.all_challenges()
        assert len(all_chs) >= 16
        severities = {c.severity for c in all_chs}
        assert ChallengeSeverity.CRITICAL in severities
        subsystems = {c.target_subsystem for c in all_chs}
        assert len(subsystems) >= 4  # covers multiple subsystems

    def test_duplicate_seed_is_idempotent(self):
        self.reg.seed_initial_challenges()
        self.reg.seed_initial_challenges()
        assert len(self.reg.all_challenges()) >= 16
        # Should not double-count
        count1 = len(self.reg.all_challenges())
        self.reg.seed_initial_challenges()
        assert len(self.reg.all_challenges()) == count1
```

- [ ] **Step 1.2: Run to confirm FAIL**

```bash
cd /Users/benebsworth/projects/omega/.claude/worktrees/sweet-hugle
python -m pytest tests/test_challenge_registry.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'omega.core.challenge_registry'`

- [ ] **Step 1.3: Implement ChallengeRegistry**

```python
# omega/core/challenge_registry.py
"""
omega.core.challenge_registry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Persistent store of challenges raised by the Devil's Advocate node.

Each challenge targets a subsystem, has a severity, evidence, and lifecycle
status. Unresolved CRITICAL challenges block deployments via has_blocking_challenges().
Resolution rate is tracked as a system health metric.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class ChallengeSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH     = "high"
    MEDIUM   = "medium"
    LOW      = "low"


class ChallengeStatus(str, Enum):
    OPEN         = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED     = "resolved"
    WONTFIX      = "wontfix"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS challenges (
    challenge_id      TEXT PRIMARY KEY,
    target_subsystem  TEXT NOT NULL,
    severity          TEXT NOT NULL,
    description       TEXT NOT NULL,
    evidence          TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'open',
    resolution_notes  TEXT NOT NULL DEFAULT '',
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL
);
"""

# Seeded challenges — covering both current architecture and planned subsystems
_SEED_CHALLENGES = [
    # ── Current architecture ─────────────────────────────────────────────────
    dict(
        target_subsystem="orchestrator.convergence_loop",
        severity=ChallengeSeverity.HIGH,
        description=(
            "Convergence detection uses a single metric delta threshold — "
            "the system can stop improving a metric because it oscillates just below "
            "the threshold, appearing converged while actually thrashing."
        ),
        evidence=(
            "orchestrator.py:run_convergence_loop — has_improved() checks only the last "
            "two iterations; oscillation over a 4-iteration window is invisible to it."
        ),
    ),
    dict(
        target_subsystem="orchestrator.improvement_loop",
        severity=ChallengeSeverity.MEDIUM,
        description=(
            "improve_system() sends identical feedback to every node regardless of whether "
            "that node contributed to the failing metric. A slow DataIngestionNode will "
            "trigger improve() calls on SignalGenerationNode and RiskManagementNode."
        ),
        evidence=(
            "orchestrator.py:improve_system — iterates all_nodes() with system-level "
            "feedback; no per-node attribution of metric causality."
        ),
    ),
    dict(
        target_subsystem="memory.episodic_decay",
        severity=ChallengeSeverity.HIGH,
        description=(
            "EpisodicStore importance decay is time-based, not outcome-based. "
            "A signal that predicted a 40% crash correctly decays at the same rate "
            "as a noise signal that happened at the same time. High-importance rare "
            "events will be pruned before the system can learn from them."
        ),
        evidence=(
            "memory.py — decay formula is exponential by age; no reinforcement signal "
            "from downstream outcome evaluation."
        ),
    ),
    dict(
        target_subsystem="memory.semantic_consolidation",
        severity=ChallengeSeverity.MEDIUM,
        description=(
            "Consolidator extracts patterns from episodic → semantic on a fixed cycle "
            "interval. During rapid regime changes, the semantic store will lag reality "
            "by at least one consolidation window, potentially issuing stale guidance "
            "to nodes consulting it."
        ),
        evidence=(
            "memory.py:Consolidator — consolidates every N cycles; no trigger for "
            "urgent consolidation when high-confidence contradictions appear."
        ),
    ),
    dict(
        target_subsystem="vectora.signal_generation",
        severity=ChallengeSeverity.HIGH,
        description=(
            "SignalGenerationNode self-improvement unlocks new indicator types each cycle. "
            "There is no check that adding a new indicator doesn't re-introduce a "
            "highly-correlated signal already present. Correlated signals inflate "
            "apparent alpha and degrade out-of-sample Sharpe."
        ),
        evidence=(
            "signal_generation.py — improve() appends to _enabled_indicators; no "
            "correlation check against existing set."
        ),
    ),
    dict(
        target_subsystem="vectora.verification",
        severity=ChallengeSeverity.MEDIUM,
        description=(
            "VerificationNode uses a fixed 30% regression threshold. This is arbitrary. "
            "A 29% regression in Sharpe ratio during a high-volatility regime may be "
            "noise; a 5% regression in max drawdown may be catastrophic. "
            "Thresholds should be metric-specific and regime-aware."
        ),
        evidence=(
            "verification.py:REGRESSION_THRESHOLD = 0.3 — single constant applied "
            "to all metrics regardless of their scale or business impact."
        ),
    ),
    dict(
        target_subsystem="vectora.data_ingestion",
        severity=ChallengeSeverity.HIGH,
        description=(
            "DataIngestionNode falls back to cached data on failure without staleness "
            "bounds. If Binance and CoinGecko both fail for 24+ hours, the pipeline "
            "continues running on day-old data and producing 'valid' signals with no "
            "staleness warning in the output."
        ),
        evidence=(
            "data_ingestion.py — fallback path returns self._cache without timestamp "
            "comparison; vectora_main.py logs a warning but does not halt the pipeline."
        ),
    ),
    dict(
        target_subsystem="state_store",
        severity=ChallengeSeverity.LOW,
        description=(
            "StateStore uses a single SQLite connection with check_same_thread=False. "
            "If the heartbeat loop ever gains async or threading support, concurrent "
            "writes will corrupt the database. The 'safe for now' assumption is invisible "
            "and will be violated silently."
        ),
        evidence=(
            "state_store.py:__init__ — sqlite3.connect(db_path, check_same_thread=False); "
            "no write serialisation."
        ),
    ),
    # ── Planned architecture ──────────────────────────────────────────────────
    dict(
        target_subsystem="alignment.layer_architecture",
        severity=ChallengeSeverity.HIGH,
        description=(
            "The planned 5-layer alignment architecture adds O(5n) overhead per "
            "improvement cycle. At high heartbeat frequency or large node count, "
            "the alignment layer itself becomes the bottleneck. What is the empirical "
            "threshold, and is there a fast-path for low-risk improvements?"
        ),
        evidence=(
            "Planned design: each improvement passes through 5 sequential alignment "
            "checks before commit. No profiling baseline established yet."
        ),
    ),
    dict(
        target_subsystem="alignment.ewc_protection",
        severity=ChallengeSeverity.CRITICAL,
        description=(
            "EWC (Elastic Weight Consolidation) protection assumes tasks are cleanly "
            "separable with stable Fisher information estimates. Crypto regime transitions "
            "are gradual and overlapping, not discrete. EWC importance weights computed "
            "during one regime will incorrectly protect parameters that should adapt "
            "during a transition, causing the system to resist beneficial updates."
        ),
        evidence=(
            "EWC design assumes clear task boundaries. Crypto markets exhibit "
            "non-stationary, overlapping regimes (bull/bear/sideways/high-vol) with "
            "no ground-truth change point. BOCPD or HMM-based regime detection would "
            "be needed to gate EWC application."
        ),
    ),
    dict(
        target_subsystem="alignment.nash_welfare",
        severity=ChallengeSeverity.CRITICAL,
        description=(
            "Nash welfare aggregation requires knowing all objectives upfront to "
            "compute the joint welfare function. If a new objective emerges mid-operation "
            "(e.g. 'minimise drawdown during regulatory crackdown'), adding it retroactively "
            "changes the welfare scores of all prior decisions, potentially invalidating "
            "the improvement history."
        ),
        evidence=(
            "Nash welfare: max ∏ u_i(x). Adding a new u_i reweights the product. "
            "No mechanism in the planned design for objective versioning or retroactive "
            "welfare recalculation."
        ),
    ),
    dict(
        target_subsystem="skills.iter_drag",
        severity=ChallengeSeverity.CRITICAL,
        description=(
            "The IterDRAG research skill has no grounding mechanism. It retrieves "
            "from a vector store and generates reasoning chains, but if the initial "
            "retrieval returns a plausible-but-wrong document, the generation step "
            "will hallucinate a confident justification. Hallucinated research findings "
            "stored back into SemanticMemory propagate to all downstream nodes "
            "permanently."
        ),
        evidence=(
            "RAG without verification: retrieval → generation → memory write. "
            "No citation verification, no cross-referencing against live market data, "
            "no confidence threshold before memory storage."
        ),
    ),
    dict(
        target_subsystem="alignment.vcg_pricing",
        severity=ChallengeSeverity.HIGH,
        description=(
            "VCG pricing assumes rational, utility-maximising agents. LLM nodes are "
            "not rational in the game-theoretic sense — they are stochastic functions "
            "that may 'misreport' their true valuation due to prompt framing, "
            "temperature settings, or context window effects. The VCG mechanism's "
            "incentive-compatibility guarantee breaks down entirely."
        ),
        evidence=(
            "VCG correctness requires truthful bidding. LLM inference is "
            "non-deterministic and context-sensitive; the same node may report "
            "different 'valuations' for identical inputs across calls."
        ),
    ),
    dict(
        target_subsystem="memory.bocpd_regime_detection",
        severity=ChallengeSeverity.HIGH,
        description=(
            "BOCPD (Bayesian Online Changepoint Detection) has O(t) memory growth — "
            "the run-length distribution must track all possible changepoint hypotheses "
            "back to t=0. On a long-running system with sub-minute heartbeats, this "
            "will OOM within days unless a truncation scheme is implemented and "
            "the truncation point is chosen carefully to not miss long-horizon regimes."
        ),
        evidence=(
            "BOCPD: P(r_t | x_{1:t}) computed over all r_t ∈ {0, 1, …, t}. "
            "At 1000 heartbeats/day × 180 days = 180,000 hypotheses untruncated. "
            "Hazard function truncation at window W loses detection of regimes longer than W."
        ),
    ),
    dict(
        target_subsystem="orchestrator.node_selection",
        severity=ChallengeSeverity.MEDIUM,
        description=(
            "Node selection always picks the highest-health node for a capability. "
            "This is a greedy policy with no exploration. If a new, improved node "
            "version starts at health=0.5 (no history), it will never be selected "
            "over a stale node at health=0.9, blocking the system from ever "
            "discovering that the new version is better."
        ),
        evidence=(
            "orchestrator.py:_select_node — max(candidates, key=health). "
            "No epsilon-greedy or UCB exploration. New nodes are starved of execution data."
        ),
    ),
    dict(
        target_subsystem="vectora.strategy",
        severity=ChallengeSeverity.MEDIUM,
        description=(
            "StrategyNode backtest uses the same data window for both signal training "
            "and portfolio evaluation. This is look-ahead bias — the strategy is being "
            "evaluated on data it effectively 'saw' during signal generation. "
            "Reported Sharpe ratios are optimistic by an unknown but likely significant factor."
        ),
        evidence=(
            "strategy.py — signals and backtest share the same OHLCV window; "
            "no walk-forward or out-of-sample holdout separation."
        ),
    ),
    dict(
        target_subsystem="alignment.constitutional_constraints",
        severity=ChallengeSeverity.HIGH,
        description=(
            "Constitutional constraints are described as 'nodes cannot override' — "
            "but the constraint enforcement mechanism is trust-based, not structural. "
            "Any node that calls improve() on itself can change its own behaviour. "
            "There is no sandboxing, no capability revocation, and no cryptographic "
            "proof that constitutional rules were actually checked."
        ),
        evidence=(
            "node.py:improve() is abstract — implementations are free to do anything. "
            "The orchestrator calls improve() and trusts the return value. "
            "No post-improvement audit of node behaviour against constitutional rules."
        ),
    ),
]


@dataclass
class Challenge:
    challenge_id: str
    target_subsystem: str
    severity: ChallengeSeverity
    description: str
    evidence: str
    status: ChallengeStatus
    resolution_notes: str
    created_at: float
    updated_at: float


class ChallengeRegistry:
    """
    Persistent store for Devil's Advocate challenges.

    Challenges are raised against specific subsystems, rated by severity,
    and tracked through their lifecycle. Unresolved CRITICAL challenges
    block deployments. Resolution rate is a system health metric.

    Uses SQLite (stdlib only, zero external dependencies).
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add(
        self,
        target_subsystem: str,
        severity: ChallengeSeverity,
        description: str,
        evidence: str = "",
        challenge_id: Optional[str] = None,
    ) -> str:
        cid = challenge_id or str(uuid.uuid4())
        now = time.time()
        self._conn.execute(
            """INSERT INTO challenges
               (challenge_id, target_subsystem, severity, description, evidence,
                status, resolution_notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (cid, target_subsystem, severity.value, description, evidence,
             ChallengeStatus.OPEN.value, "", now, now),
        )
        self._conn.commit()
        return cid

    def get(self, challenge_id: str) -> Optional[Challenge]:
        row = self._conn.execute(
            "SELECT * FROM challenges WHERE challenge_id = ?", (challenge_id,)
        ).fetchone()
        return self._row_to_challenge(row) if row else None

    def update_status(
        self,
        challenge_id: str,
        status: ChallengeStatus,
        resolution_notes: str = "",
    ) -> bool:
        result = self._conn.execute(
            """UPDATE challenges
               SET status=?, resolution_notes=?, updated_at=?
               WHERE challenge_id=?""",
            (status.value, resolution_notes, time.time(), challenge_id),
        )
        self._conn.commit()
        return result.rowcount > 0

    def all_challenges(self, subsystem: Optional[str] = None) -> List[Challenge]:
        query = "SELECT * FROM challenges"
        params: List = []
        if subsystem:
            query += " WHERE target_subsystem LIKE ?"
            params.append(f"%{subsystem}%")
        query += " ORDER BY created_at"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_challenge(r) for r in rows]

    def open_challenges(self, severity: Optional[ChallengeSeverity] = None) -> List[Challenge]:
        query = "SELECT * FROM challenges WHERE status = 'open'"
        params: List = []
        if severity:
            query += " AND severity = ?"
            params.append(severity.value)
        query += " ORDER BY created_at"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_challenge(r) for r in rows]

    # ------------------------------------------------------------------
    # Health metrics
    # ------------------------------------------------------------------

    def resolution_rate(self) -> float:
        """Fraction of challenges that are resolved or wontfix."""
        row = self._conn.execute(
            """SELECT
                 COUNT(*) as total,
                 SUM(CASE WHEN status IN ('resolved','wontfix') THEN 1 ELSE 0 END) as closed
               FROM challenges"""
        ).fetchone()
        total = row["total"] or 0
        closed = row["closed"] or 0
        return closed / total if total > 0 else 1.0

    def has_blocking_challenges(self) -> bool:
        """True if any CRITICAL challenge is still open."""
        row = self._conn.execute(
            "SELECT COUNT(*) as n FROM challenges WHERE severity='critical' AND status='open'"
        ).fetchone()
        return (row["n"] or 0) > 0

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    def seed_initial_challenges(self) -> int:
        """
        Insert the pre-defined challenge set if not already present.
        Idempotent — skips challenges whose description already exists.
        Returns number of challenges newly inserted.
        """
        existing_descriptions = {
            row[0]
            for row in self._conn.execute(
                "SELECT description FROM challenges"
            ).fetchall()
        }
        inserted = 0
        for ch in _SEED_CHALLENGES:
            if ch["description"] in existing_descriptions:
                continue
            self.add(
                target_subsystem=ch["target_subsystem"],
                severity=ch["severity"],
                description=ch["description"],
                evidence=ch["evidence"],
            )
            inserted += 1
        return inserted

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _row_to_challenge(self, row: sqlite3.Row) -> Challenge:
        return Challenge(
            challenge_id=row["challenge_id"],
            target_subsystem=row["target_subsystem"],
            severity=ChallengeSeverity(row["severity"]),
            description=row["description"],
            evidence=row["evidence"],
            status=ChallengeStatus(row["status"]),
            resolution_notes=row["resolution_notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
```

- [ ] **Step 1.4: Run tests — expect PASS**

```bash
python -m pytest tests/test_challenge_registry.py -v
```
Expected: all 9 tests PASS.

- [ ] **Step 1.5: Commit**

```bash
git add omega/core/challenge_registry.py tests/test_challenge_registry.py
git commit -m "feat(devil): add ChallengeRegistry with 18 seeded challenges"
```

---

## Task 2: VerificationGateSystem

**Files:**
- Create: `omega/core/verification_gates.py`
- Create: `tests/test_verification_gates.py`

- [ ] **Step 2.1: Write failing tests**

```python
# tests/test_verification_gates.py
import pytest
from omega.core.verification_gates import (
    GateResult, GateStatus,
    PropertyGate, InvariantGate, ConsistencyGate,
    RegressionGate, ConvergenceGate,
    AndGate, OrGate,
    VerificationGateSystem,
)


class TestGateResult:
    def test_pass_result(self):
        r = GateResult(status=GateStatus.PASS, gate_name="test", evidence="ok")
        assert r.passed is True
        assert r.failed is False

    def test_fail_result(self):
        r = GateResult(status=GateStatus.FAIL, gate_name="test", evidence="bad")
        assert r.failed is True
        assert r.passed is False

    def test_warning_is_not_pass_not_fail(self):
        r = GateResult(status=GateStatus.WARNING, gate_name="test", evidence="marginal")
        assert r.passed is False
        assert r.failed is False


class TestPropertyGate:
    def test_passes_when_predicate_true(self):
        gate = PropertyGate(
            name="bounded_output",
            predicate=lambda ctx: 0.0 <= ctx.get("value", 0) <= 1.0,
            description="Output must be in [0, 1]",
        )
        result = gate.check({"value": 0.5})
        assert result.status == GateStatus.PASS

    def test_fails_when_predicate_false(self):
        gate = PropertyGate(
            name="bounded_output",
            predicate=lambda ctx: 0.0 <= ctx.get("value", 0) <= 1.0,
            description="Output must be in [0, 1]",
        )
        result = gate.check({"value": 1.5})
        assert result.status == GateStatus.FAIL

    def test_exception_in_predicate_is_fail(self):
        gate = PropertyGate(
            name="bad_gate",
            predicate=lambda ctx: 1 / 0,
            description="Always crashes",
        )
        result = gate.check({})
        assert result.status == GateStatus.FAIL
        assert "ZeroDivisionError" in result.evidence


class TestInvariantGate:
    def test_invariant_holds(self):
        gate = InvariantGate(
            name="position_bounded",
            invariant=lambda ctx: ctx.get("total_position", 0) <= ctx.get("max_position", 1),
            description="Total position must not exceed max",
        )
        result = gate.check({"total_position": 0.8, "max_position": 1.0})
        assert result.status == GateStatus.PASS

    def test_invariant_violated(self):
        gate = InvariantGate(
            name="position_bounded",
            invariant=lambda ctx: ctx.get("total_position", 0) <= ctx.get("max_position", 1),
            description="Total position must not exceed max",
        )
        result = gate.check({"total_position": 1.5, "max_position": 1.0})
        assert result.status == GateStatus.FAIL


class TestRegressionGate:
    def test_no_regression(self):
        gate = RegressionGate(name="sharpe_regression", metric="sharpe", direction="maximize", threshold_pct=10.0)
        result = gate.check({"before": {"sharpe": 1.0}, "after": {"sharpe": 1.05}})
        assert result.status == GateStatus.PASS

    def test_regression_detected(self):
        gate = RegressionGate(name="sharpe_regression", metric="sharpe", direction="maximize", threshold_pct=10.0)
        result = gate.check({"before": {"sharpe": 1.0}, "after": {"sharpe": 0.80}})
        assert result.status == GateStatus.FAIL

    def test_missing_metric_is_warning(self):
        gate = RegressionGate(name="sharpe_regression", metric="sharpe", direction="maximize", threshold_pct=10.0)
        result = gate.check({"before": {}, "after": {}})
        assert result.status == GateStatus.WARNING


class TestConvergenceGate:
    def test_converging_series_passes(self):
        gate = ConvergenceGate(name="convergence", metric="accuracy", window=4)
        # Strictly increasing — converging
        result = gate.check({"history": [0.7, 0.75, 0.80, 0.85]})
        assert result.status == GateStatus.PASS

    def test_oscillating_series_fails(self):
        gate = ConvergenceGate(name="convergence", metric="accuracy", window=4)
        result = gate.check({"history": [0.7, 0.9, 0.5, 0.85]})
        assert result.status == GateStatus.FAIL

    def test_insufficient_history_is_warning(self):
        gate = ConvergenceGate(name="convergence", metric="accuracy", window=4)
        result = gate.check({"history": [0.7]})
        assert result.status == GateStatus.WARNING


class TestCompositeGates:
    def _pass_gate(self, name="p"):
        return PropertyGate(name=name, predicate=lambda _: True, description="always pass")

    def _fail_gate(self, name="f"):
        return PropertyGate(name=name, predicate=lambda _: False, description="always fail")

    def test_and_gate_both_pass(self):
        gate = AndGate("both", [self._pass_gate("a"), self._pass_gate("b")])
        assert gate.check({}).status == GateStatus.PASS

    def test_and_gate_one_fails(self):
        gate = AndGate("both", [self._pass_gate("a"), self._fail_gate("b")])
        assert gate.check({}).status == GateStatus.FAIL

    def test_or_gate_one_passes(self):
        gate = OrGate("either", [self._pass_gate("a"), self._fail_gate("b")])
        assert gate.check({}).status == GateStatus.PASS

    def test_or_gate_all_fail(self):
        gate = OrGate("either", [self._fail_gate("a"), self._fail_gate("b")])
        assert gate.check({}).status == GateStatus.FAIL


class TestVerificationGateSystem:
    def test_run_all_passing(self):
        system = VerificationGateSystem()
        system.register(PropertyGate("p1", lambda _: True, "ok"))
        system.register(PropertyGate("p2", lambda _: True, "ok"))
        results = system.run_all({})
        assert all(r.passed for r in results)
        assert system.all_passed(results) is True

    def test_run_with_failure(self):
        system = VerificationGateSystem()
        system.register(PropertyGate("p1", lambda _: True, "ok"))
        system.register(PropertyGate("p2", lambda _: False, "bad"))
        results = system.run_all({})
        assert system.all_passed(results) is False
        assert any(r.failed for r in results)

    def test_summary_dict(self):
        system = VerificationGateSystem()
        system.register(PropertyGate("p1", lambda _: True, "ok"))
        results = system.run_all({})
        summary = system.summary(results)
        assert summary["total"] == 1
        assert summary["passed"] == 1
        assert summary["failed"] == 0
```

- [ ] **Step 2.2: Run to confirm FAIL**

```bash
python -m pytest tests/test_verification_gates.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'omega.core.verification_gates'`

- [ ] **Step 2.3: Implement VerificationGateSystem**

```python
# omega/core/verification_gates.py
"""
omega.core.verification_gates
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Composable gate objects that verify system properties before committing improvements.

Gate types:
  PropertyGate    — arbitrary predicate on a context dict
  InvariantGate   — system invariant that must hold across all states
  ConsistencyGate — cross-subsystem consistency check
  RegressionGate  — before/after metric regression detection
  ConvergenceGate — statistical test that a metric series is converging

Composition:
  AndGate — all children must pass
  OrGate  — at least one child must pass

Usage::
    system = VerificationGateSystem()
    system.register(PropertyGate("bounded", lambda ctx: 0 <= ctx["value"] <= 1, "must be [0,1]"))
    system.register(RegressionGate("sharpe", metric="sharpe", direction="maximize", threshold_pct=10.0))
    results = system.run_all(context)
    if not system.all_passed(results):
        raise RuntimeError("Gates failed: " + str(system.summary(results)))
"""
from __future__ import annotations

import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class GateStatus(str, Enum):
    PASS    = "pass"
    FAIL    = "fail"
    WARNING = "warning"


@dataclass
class GateResult:
    status: GateStatus
    gate_name: str
    evidence: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == GateStatus.PASS

    @property
    def failed(self) -> bool:
        return self.status == GateStatus.FAIL


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class Gate(ABC):
    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def check(self, context: Dict[str, Any]) -> GateResult:
        """Run the gate check and return a GateResult."""


# ---------------------------------------------------------------------------
# Concrete gates
# ---------------------------------------------------------------------------

class PropertyGate(Gate):
    """Passes when predicate(context) is True."""

    def __init__(self, name: str, predicate: Callable[[Dict], bool], description: str) -> None:
        super().__init__(name)
        self._predicate = predicate
        self._description = description

    def check(self, context: Dict[str, Any]) -> GateResult:
        try:
            ok = bool(self._predicate(context))
        except Exception as exc:
            return GateResult(
                status=GateStatus.FAIL,
                gate_name=self.name,
                evidence=f"{type(exc).__name__}: {exc}",
            )
        return GateResult(
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            gate_name=self.name,
            evidence=self._description if ok else f"Property violated: {self._description}",
        )


class InvariantGate(Gate):
    """System invariant — must hold at all times."""

    def __init__(self, name: str, invariant: Callable[[Dict], bool], description: str) -> None:
        super().__init__(name)
        self._invariant = invariant
        self._description = description

    def check(self, context: Dict[str, Any]) -> GateResult:
        try:
            ok = bool(self._invariant(context))
        except Exception as exc:
            return GateResult(
                status=GateStatus.FAIL,
                gate_name=self.name,
                evidence=f"Invariant check raised: {type(exc).__name__}: {exc}",
            )
        return GateResult(
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            gate_name=self.name,
            evidence=self._description if ok else f"Invariant violated: {self._description}",
        )


class ConsistencyGate(Gate):
    """Cross-subsystem consistency — checks that two context values agree."""

    def __init__(
        self,
        name: str,
        check_fn: Callable[[Dict], bool],
        description: str,
    ) -> None:
        super().__init__(name)
        self._check_fn = check_fn
        self._description = description

    def check(self, context: Dict[str, Any]) -> GateResult:
        try:
            ok = bool(self._check_fn(context))
        except Exception as exc:
            return GateResult(
                status=GateStatus.FAIL,
                gate_name=self.name,
                evidence=f"Consistency check raised: {exc}",
            )
        return GateResult(
            status=GateStatus.PASS if ok else GateStatus.FAIL,
            gate_name=self.name,
            evidence=self._description if ok else f"Consistency violated: {self._description}",
        )


class RegressionGate(Gate):
    """
    Detects metric regressions between before/after snapshots.

    Context must have keys: ``before`` and ``after`` — both dicts of metric_name → float.
    direction: "maximize" (regression = drop) or "minimize" (regression = rise).
    threshold_pct: percentage change that constitutes a regression.
    """

    def __init__(
        self,
        name: str,
        metric: str,
        direction: str = "maximize",
        threshold_pct: float = 10.0,
    ) -> None:
        super().__init__(name)
        self._metric = metric
        self._direction = direction
        self._threshold_pct = threshold_pct

    def check(self, context: Dict[str, Any]) -> GateResult:
        before = context.get("before", {})
        after = context.get("after", {})
        bval = before.get(self._metric)
        aval = after.get(self._metric)

        if bval is None or aval is None:
            return GateResult(
                status=GateStatus.WARNING,
                gate_name=self.name,
                evidence=f"Metric '{self._metric}' missing from before/after context",
            )

        if bval == 0:
            pct_change = 0.0
        else:
            pct_change = (aval - bval) / abs(bval) * 100.0

        if self._direction == "maximize":
            regressed = pct_change < -self._threshold_pct
        else:
            regressed = pct_change > self._threshold_pct

        if regressed:
            return GateResult(
                status=GateStatus.FAIL,
                gate_name=self.name,
                evidence=(
                    f"Regression: {self._metric} changed {pct_change:.1f}% "
                    f"(before={bval:.4f}, after={aval:.4f}, threshold={self._threshold_pct}%)"
                ),
                details={"metric": self._metric, "before": bval, "after": aval, "pct_change": pct_change},
            )
        return GateResult(
            status=GateStatus.PASS,
            gate_name=self.name,
            evidence=f"{self._metric} change={pct_change:+.1f}% within threshold",
            details={"metric": self._metric, "before": bval, "after": aval, "pct_change": pct_change},
        )


class ConvergenceGate(Gate):
    """
    Statistical test that a metric history is converging (monotonically improving)
    rather than oscillating or diverging.

    Context must have key ``history``: List[float], values in iteration order.
    Requires at least ``window`` data points; returns WARNING if insufficient.
    Passes if the linear trend over the window is improving (slope > 0 for maximize).
    """

    def __init__(
        self,
        name: str,
        metric: str,
        window: int = 5,
        direction: str = "maximize",
    ) -> None:
        super().__init__(name)
        self._metric = metric
        self._window = window
        self._direction = direction

    def check(self, context: Dict[str, Any]) -> GateResult:
        history = context.get("history", [])
        if len(history) < self._window:
            return GateResult(
                status=GateStatus.WARNING,
                gate_name=self.name,
                evidence=f"Insufficient history: {len(history)} < {self._window} required",
            )

        recent = history[-self._window:]
        n = len(recent)
        mean_x = (n - 1) / 2.0
        mean_y = sum(recent) / n
        slope_num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(recent))
        slope_den = sum((i - mean_x) ** 2 for i in range(n))
        slope = slope_num / slope_den if slope_den != 0 else 0.0

        converging = slope > 0 if self._direction == "maximize" else slope < 0

        # Also check for oscillation: high variance relative to range
        rng = max(recent) - min(recent)
        mean_abs_diff = sum(abs(recent[i] - recent[i-1]) for i in range(1, n)) / (n - 1)
        oscillating = rng > 0 and mean_abs_diff > rng * 0.5

        if oscillating and not converging:
            return GateResult(
                status=GateStatus.FAIL,
                gate_name=self.name,
                evidence=f"{self._metric} is oscillating (slope={slope:.4f}, mean_abs_diff={mean_abs_diff:.4f})",
                details={"slope": slope, "oscillating": True, "history_tail": recent},
            )
        if not converging and not oscillating:
            return GateResult(
                status=GateStatus.WARNING,
                gate_name=self.name,
                evidence=f"{self._metric} trend flat or diverging (slope={slope:.4f})",
                details={"slope": slope, "history_tail": recent},
            )
        return GateResult(
            status=GateStatus.PASS,
            gate_name=self.name,
            evidence=f"{self._metric} converging (slope={slope:+.4f})",
            details={"slope": slope, "history_tail": recent},
        )


# ---------------------------------------------------------------------------
# Composite gates
# ---------------------------------------------------------------------------

class AndGate(Gate):
    """All children must pass."""

    def __init__(self, name: str, children: List[Gate]) -> None:
        super().__init__(name)
        self._children = children

    def check(self, context: Dict[str, Any]) -> GateResult:
        results = [g.check(context) for g in self._children]
        failures = [r for r in results if r.failed]
        if failures:
            evidence = "; ".join(r.evidence for r in failures)
            return GateResult(status=GateStatus.FAIL, gate_name=self.name, evidence=evidence)
        warnings = [r for r in results if r.status == GateStatus.WARNING]
        if warnings:
            return GateResult(
                status=GateStatus.WARNING,
                gate_name=self.name,
                evidence="; ".join(r.evidence for r in warnings),
            )
        return GateResult(status=GateStatus.PASS, gate_name=self.name, evidence="All children passed")


class OrGate(Gate):
    """At least one child must pass."""

    def __init__(self, name: str, children: List[Gate]) -> None:
        super().__init__(name)
        self._children = children

    def check(self, context: Dict[str, Any]) -> GateResult:
        results = [g.check(context) for g in self._children]
        if any(r.passed for r in results):
            return GateResult(status=GateStatus.PASS, gate_name=self.name, evidence="At least one child passed")
        if any(r.status == GateStatus.WARNING for r in results):
            return GateResult(
                status=GateStatus.WARNING,
                gate_name=self.name,
                evidence="No child passed; some warnings",
            )
        evidence = "; ".join(r.evidence for r in results)
        return GateResult(status=GateStatus.FAIL, gate_name=self.name, evidence=evidence)


# ---------------------------------------------------------------------------
# VerificationGateSystem
# ---------------------------------------------------------------------------

class VerificationGateSystem:
    """
    Registry of gates that can be run collectively as a CI check
    or as part of the heartbeat loop.

    Usage::
        system = VerificationGateSystem()
        system.register(PropertyGate(...))
        system.register(RegressionGate(...))
        results = system.run_all(context)
        if not system.all_passed(results):
            # veto the improvement
            ...
    """

    def __init__(self) -> None:
        self._gates: List[Gate] = []

    def register(self, gate: Gate) -> None:
        self._gates.append(gate)

    def run_all(self, context: Dict[str, Any]) -> List[GateResult]:
        return [g.check(context) for g in self._gates]

    def all_passed(self, results: List[GateResult]) -> bool:
        return all(r.passed or r.status == GateStatus.WARNING for r in results)

    def summary(self, results: List[GateResult]) -> Dict[str, Any]:
        return {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if r.failed),
            "warnings": sum(1 for r in results if r.status == GateStatus.WARNING),
            "failures": [{"gate": r.gate_name, "evidence": r.evidence} for r in results if r.failed],
        }
```

- [ ] **Step 2.4: Run tests — expect PASS**

```bash
python -m pytest tests/test_verification_gates.py -v
```

- [ ] **Step 2.5: Commit**

```bash
git add omega/core/verification_gates.py tests/test_verification_gates.py
git commit -m "feat(devil): add VerificationGateSystem with composable gates"
```

---

## Task 3: DevilsAdvocateNode

**Files:**
- Create: `omega/nodes/devils_advocate.py`
- Create: `tests/test_devils_advocate.py`

- [ ] **Step 3.1: Write failing tests**

```python
# tests/test_devils_advocate.py
import pytest
from omega.core.node import NodeInput, NodeOutput
from omega.core.challenge_registry import ChallengeRegistry, ChallengeSeverity, ChallengeStatus
from omega.core.verification_gates import VerificationGateSystem, PropertyGate, RegressionGate, GateStatus
from omega.nodes.devils_advocate import DevilsAdvocateNode, ReviewMode


class TestDevilsAdvocateNodeBasics:
    def setup_method(self):
        self.registry = ChallengeRegistry(db_path=":memory:")
        self.gates = VerificationGateSystem()
        self.node = DevilsAdvocateNode(registry=self.registry, gate_system=self.gates)

    def test_get_state(self):
        state = self.node.get_state()
        assert state.name == "DevilsAdvocateNode"
        assert state.health >= 0.0
        assert state.health <= 1.0

    def test_get_capabilities(self):
        caps = self.node.get_capabilities()
        assert "architectural_review" in caps
        assert "implementation_audit" in caps
        assert "assumption_stress_test" in caps
        assert "regression_hunt" in caps
        assert "complexity_audit" in caps

    def test_describe(self):
        desc = self.node.describe()
        assert "devil" in desc.lower() or "challenge" in desc.lower() or "adversarial" in desc.lower()

    def test_evaluate_returns_metrics(self):
        metrics = self.node.evaluate()
        assert "open_challenges" in metrics
        assert "resolution_rate" in metrics
        assert "blocking_challenges" in metrics

    def test_improve_always_returns_false(self):
        # DA node does not self-improve — it challenges others
        result = self.node.improve({})
        assert result is False


class TestDevilsAdvocateExecute:
    def setup_method(self):
        self.registry = ChallengeRegistry(db_path=":memory:")
        self.gates = VerificationGateSystem()
        self.node = DevilsAdvocateNode(registry=self.registry, gate_system=self.gates)

    def _exec(self, action: str, **params) -> NodeOutput:
        inp = NodeInput(action=action, parameters=params)
        return self.node.execute(inp)

    def test_architectural_review_returns_report(self):
        out = self._exec("architectural_review", subsystem="orchestrator")
        assert out.success
        assert out.result is not None
        report = out.result
        assert "challenges" in report
        assert "gate_results" in report

    def test_implementation_audit_returns_report(self):
        out = self._exec("implementation_audit", subsystem="memory")
        assert out.success
        assert "challenges" in out.result

    def test_assumption_stress_test_returns_report(self):
        out = self._exec("assumption_stress_test")
        assert out.success

    def test_regression_hunt_with_before_after(self):
        out = self._exec(
            "regression_hunt",
            before={"accuracy": 0.90, "sharpe": 1.2},
            after={"accuracy": 0.70, "sharpe": 0.9},  # regression
        )
        assert out.success
        report = out.result
        assert report["gate_results"]["failed"] > 0

    def test_complexity_audit_returns_report(self):
        out = self._exec("complexity_audit")
        assert out.success

    def test_unknown_action_fails_gracefully(self):
        out = self._exec("nonexistent_action")
        assert out.success is False
        assert len(out.errors) > 0

    def test_veto_when_critical_open(self):
        # Seed a critical open challenge
        self.registry.seed_initial_challenges()
        out = self._exec("architectural_review", subsystem="alignment")
        assert "veto" in out.result or out.result.get("veto") is True or "veto" in str(out.result).lower()


class TestDevilsAdvocateGateIntegration:
    """Integration test: DA node catches a real regression."""

    def test_catches_sharpe_regression(self):
        registry = ChallengeRegistry(db_path=":memory:")
        gates = VerificationGateSystem()
        gates.register(RegressionGate("sharpe_regression", metric="sharpe", direction="maximize", threshold_pct=15.0))
        node = DevilsAdvocateNode(registry=registry, gate_system=gates)

        inp = NodeInput(
            action="regression_hunt",
            parameters={
                "before": {"sharpe": 1.5},
                "after":  {"sharpe": 1.0},  # 33% drop — exceeds 15% threshold
            },
        )
        out = node.execute(inp)
        assert out.success
        assert out.result["gate_results"]["failed"] >= 1
        failure_evidence = out.result["gate_results"]["failures"][0]["evidence"]
        assert "sharpe" in failure_evidence.lower()

    def test_passes_when_no_regression(self):
        registry = ChallengeRegistry(db_path=":memory:")
        gates = VerificationGateSystem()
        gates.register(RegressionGate("sharpe_regression", metric="sharpe", direction="maximize", threshold_pct=15.0))
        node = DevilsAdvocateNode(registry=registry, gate_system=gates)

        inp = NodeInput(
            action="regression_hunt",
            parameters={"before": {"sharpe": 1.0}, "after": {"sharpe": 1.1}},
        )
        out = node.execute(inp)
        assert out.success
        assert out.result["gate_results"]["failed"] == 0
```

- [ ] **Step 3.2: Run to confirm FAIL**

```bash
python -m pytest tests/test_devils_advocate.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'omega.nodes.devils_advocate'`

- [ ] **Step 3.3: Implement DevilsAdvocateNode**

```python
# omega/nodes/devils_advocate.py
"""
omega.nodes.devils_advocate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The Devil's Advocate meta-node.

Purpose: challenge, stress-test, and poke holes in every architectural
decision, principle, and primitive in the system.

Operating modes (capabilities):
  architectural_review     — challenge high-level design decisions
  implementation_audit     — review code for gaps between spec and implementation
  assumption_stress_test   — enumerate implicit assumptions and try to break them
  regression_hunt          — detect regressions introduced by improvements
  complexity_audit         — flag over-engineering; suggest simpler alternatives

The node:
  - Runs VerificationGates against the provided before/after context
  - Queries ChallengeRegistry for open challenges against the target subsystem
  - Produces structured Challenge Reports with severity ratings
  - Vetoes improvements when CRITICAL open challenges exist
  - Never self-improves (improve() always returns False — it challenges others)
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.challenge_registry import ChallengeRegistry, ChallengeSeverity, ChallengeStatus
from omega.core.verification_gates import VerificationGateSystem, GateStatus


class ReviewMode(str, Enum):
    ARCHITECTURAL_REVIEW     = "architectural_review"
    IMPLEMENTATION_AUDIT     = "implementation_audit"
    ASSUMPTION_STRESS_TEST   = "assumption_stress_test"
    REGRESSION_HUNT          = "regression_hunt"
    COMPLEXITY_AUDIT         = "complexity_audit"


_CAPABILITIES = [m.value for m in ReviewMode]


class DevilsAdvocateNode(Node):
    """
    Meta-node whose entire purpose is adversarial: challenge every
    assumption, gate every improvement, and surface blind spots.

    The DA node does NOT self-improve. Its job is to make every
    other node prove it deserves to exist and improve.
    """

    def __init__(
        self,
        registry: Optional[ChallengeRegistry] = None,
        gate_system: Optional[VerificationGateSystem] = None,
        db_path: str = ":memory:",
    ) -> None:
        # Do NOT call super().__init__() — we don't want a Brain for this node
        self._node_id = str(uuid.uuid4())
        self._version = "1.0"
        self._registry = registry or ChallengeRegistry(db_path=db_path)
        self._gates = gate_system or VerificationGateSystem()
        self._execution_count = 0
        self._veto_count = 0

    # ------------------------------------------------------------------
    # Node interface
    # ------------------------------------------------------------------

    def get_state(self) -> NodeState:
        metrics = self.evaluate()
        # Health = resolution rate (0 open challenges = perfect health for a DA node)
        health = float(self._registry.resolution_rate())
        return NodeState(
            node_id=self._node_id,
            name="DevilsAdvocateNode",
            version=self._version,
            health=health,
            capabilities=_CAPABILITIES,
            metrics=metrics,
            metadata={
                "veto_count": self._veto_count,
                "execution_count": self._execution_count,
            },
        )

    def get_capabilities(self) -> List[str]:
        return _CAPABILITIES

    def describe(self) -> str:
        return (
            "The Devil's Advocate meta-node. Challenges every architectural decision, "
            "stress-tests assumptions, hunts for regressions, and vetoes improvements "
            "that fail verification gates or have unresolved CRITICAL challenges. "
            "It never self-improves — it challenges others."
        )

    def evaluate(self) -> Dict[str, float]:
        open_chs = self._registry.open_challenges()
        critical_open = sum(1 for c in open_chs if c.severity == ChallengeSeverity.CRITICAL)
        return {
            "open_challenges": float(len(open_chs)),
            "critical_open": float(critical_open),
            "resolution_rate": self._registry.resolution_rate(),
            "blocking_challenges": float(self._registry.has_blocking_challenges()),
            "veto_count": float(self._veto_count),
        }

    def improve(self, feedback: Dict[str, Any]) -> bool:
        """Devil's advocate does not self-improve. It challenges others."""
        return False

    def execute(self, input: NodeInput) -> NodeOutput:
        t0 = time.perf_counter()
        self._execution_count += 1

        action = input.action
        params = input.parameters

        try:
            if action == ReviewMode.ARCHITECTURAL_REVIEW:
                result = self._architectural_review(params)
            elif action == ReviewMode.IMPLEMENTATION_AUDIT:
                result = self._implementation_audit(params)
            elif action == ReviewMode.ASSUMPTION_STRESS_TEST:
                result = self._assumption_stress_test(params)
            elif action == ReviewMode.REGRESSION_HUNT:
                result = self._regression_hunt(params)
            elif action == ReviewMode.COMPLEXITY_AUDIT:
                result = self._complexity_audit(params)
            else:
                return NodeOutput(
                    request_id=input.request_id,
                    success=False,
                    errors=[f"Unknown action '{action}'. Valid: {_CAPABILITIES}"],
                    metrics={"latency_ms": (time.perf_counter() - t0) * 1000},
                )
        except Exception as exc:
            return NodeOutput(
                request_id=input.request_id,
                success=False,
                errors=[f"DevilsAdvocateNode.{action} raised: {type(exc).__name__}: {exc}"],
                metrics={"latency_ms": (time.perf_counter() - t0) * 1000},
            )

        latency_ms = (time.perf_counter() - t0) * 1000
        return NodeOutput(
            request_id=input.request_id,
            success=True,
            result=result,
            metrics={"latency_ms": latency_ms, **self.evaluate()},
        )

    # ------------------------------------------------------------------
    # Operating modes
    # ------------------------------------------------------------------

    def _architectural_review(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Challenge high-level design decisions for a given subsystem.
        Returns open challenges + gate results + veto decision.
        """
        subsystem = params.get("subsystem", "")
        open_chs = self._registry.open_challenges()
        if subsystem:
            relevant = [c for c in open_chs if subsystem.lower() in c.target_subsystem.lower()]
        else:
            relevant = open_chs

        # Run gates against the context
        gate_results = self._gates.run_all(params)
        gate_summary = self._gates.summary(gate_results)

        veto = self._registry.has_blocking_challenges() or gate_summary["failed"] > 0
        if veto:
            self._veto_count += 1

        return {
            "mode": "architectural_review",
            "subsystem": subsystem,
            "challenges": [self._challenge_to_dict(c) for c in relevant],
            "open_count": len(relevant),
            "critical_count": sum(1 for c in relevant if c.severity == ChallengeSeverity.CRITICAL),
            "gate_results": gate_summary,
            "veto": veto,
            "verdict": "VETOED" if veto else "APPROVED",
        }

    def _implementation_audit(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Review code for gaps between spec and implementation.
        Queries challenges tagged to the subsystem.
        """
        subsystem = params.get("subsystem", "")
        all_chs = self._registry.all_challenges(subsystem=subsystem)
        open_chs = [c for c in all_chs if c.status == ChallengeStatus.OPEN]

        gate_results = self._gates.run_all(params)
        gate_summary = self._gates.summary(gate_results)

        return {
            "mode": "implementation_audit",
            "subsystem": subsystem,
            "challenges": [self._challenge_to_dict(c) for c in open_chs],
            "total_challenges": len(all_chs),
            "open_count": len(open_chs),
            "gate_results": gate_summary,
        }

    def _assumption_stress_test(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enumerate implicit assumptions across the system and flag those
        with open critical/high challenges.
        """
        all_chs = self._registry.all_challenges()
        critical = [c for c in all_chs if c.severity == ChallengeSeverity.CRITICAL and c.status == ChallengeStatus.OPEN]
        high = [c for c in all_chs if c.severity == ChallengeSeverity.HIGH and c.status == ChallengeStatus.OPEN]

        gate_results = self._gates.run_all(params)
        gate_summary = self._gates.summary(gate_results)

        assumptions_broken = len(critical) + len(high)
        return {
            "mode": "assumption_stress_test",
            "critical_violations": [self._challenge_to_dict(c) for c in critical],
            "high_violations": [self._challenge_to_dict(c) for c in high],
            "assumptions_broken": assumptions_broken,
            "gate_results": gate_summary,
            "verdict": "BROKEN" if assumptions_broken > 0 else "HOLDING",
        }

    def _regression_hunt(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run all registered RegressionGates against before/after snapshots.
        Raises new challenges for any regressions found.
        """
        gate_results = self._gates.run_all(params)
        gate_summary = self._gates.summary(gate_results)

        # Auto-raise challenges for any failed gates
        new_challenge_ids = []
        for gr in gate_results:
            if gr.failed:
                cid = self._registry.add(
                    target_subsystem="regression",
                    severity=ChallengeSeverity.HIGH,
                    description=f"Regression detected by gate '{gr.gate_name}': {gr.evidence}",
                    evidence=str(gr.details),
                )
                new_challenge_ids.append(cid)

        return {
            "mode": "regression_hunt",
            "gate_results": gate_summary,
            "new_challenges_raised": new_challenge_ids,
            "regressions_found": len(new_challenge_ids),
            "verdict": "REGRESSION_DETECTED" if new_challenge_ids else "CLEAN",
        }

    def _complexity_audit(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Flag over-engineering. Currently queries challenges tagged with
        'complexity' or 'yagni' and surfaces them for review.
        """
        all_open = self._registry.open_challenges()
        complexity_chs = [
            c for c in all_open
            if any(kw in c.description.lower() for kw in ["complex", "overhead", "o(", "yagni", "layer"])
        ]

        gate_results = self._gates.run_all(params)
        gate_summary = self._gates.summary(gate_results)

        return {
            "mode": "complexity_audit",
            "complexity_challenges": [self._challenge_to_dict(c) for c in complexity_chs],
            "complexity_challenge_count": len(complexity_chs),
            "gate_results": gate_summary,
            "recommendation": (
                "Review and simplify" if len(complexity_chs) > 2
                else "Complexity within acceptable bounds"
            ),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _challenge_to_dict(self, c: Any) -> Dict[str, Any]:
        return {
            "id": c.challenge_id,
            "subsystem": c.target_subsystem,
            "severity": c.severity.value,
            "description": c.description,
            "evidence": c.evidence,
            "status": c.status.value,
        }
```

- [ ] **Step 3.4: Run tests — expect PASS**

```bash
python -m pytest tests/test_devils_advocate.py -v
```

- [ ] **Step 3.5: Commit**

```bash
git add omega/nodes/devils_advocate.py tests/test_devils_advocate.py
git commit -m "feat(devil): add DevilsAdvocateNode with 5 operating modes"
```

---

## Task 4: Wire into Exports and Heartbeat

**Files:**
- Modify: `omega/nodes/__init__.py`
- Modify: `omega/examples/vectora_main.py`

- [ ] **Step 4.1: Export DevilsAdvocateNode from nodes package**

In `omega/nodes/__init__.py`, add:
```python
from omega.nodes.devils_advocate import DevilsAdvocateNode
```
And add `"DevilsAdvocateNode"` to `__all__`.

- [ ] **Step 4.2: Wire into vectora_main.py**

In `__init__` of `VectoraSystem`:
```python
from omega.core.challenge_registry import ChallengeRegistry
from omega.core.verification_gates import (
    VerificationGateSystem, PropertyGate, InvariantGate, RegressionGate, ConvergenceGate
)
from omega.nodes.devils_advocate import DevilsAdvocateNode

# After existing node construction:
self.challenge_registry = ChallengeRegistry(db_path=db_path)
self.challenge_registry.seed_initial_challenges()

# Build default gates for the Vectora pipeline
self.gate_system = VerificationGateSystem()
self.gate_system.register(PropertyGate(
    "health_bounded",
    predicate=lambda ctx: all(0.0 <= v <= 1.0 for v in ctx.get("node_healths", [1.0])),
    description="All node health scores must be in [0, 1]",
))
self.gate_system.register(InvariantGate(
    "no_negative_prices",
    invariant=lambda ctx: ctx.get("min_price", 1.0) >= 0,
    description="Market prices must be non-negative",
))
self.gate_system.register(RegressionGate(
    "sharpe_regression", metric="sharpe_ratio", direction="maximize", threshold_pct=20.0
))
self.gate_system.register(ConvergenceGate(
    "system_convergence", metric="score", window=4
))

self.devils_advocate = DevilsAdvocateNode(
    registry=self.challenge_registry,
    gate_system=self.gate_system,
    db_path=db_path,
)
```

In `run_heartbeat()`, after the existing improvement step (step 9), add step 10:

```python
# ── Step 10: Devil's Advocate review ──────────────────────────────────
node_healths = [n.get_state().health for n in [
    self.ingestion, self.signals, self.strategy,
    self.risk, self.reporting,
]]
da_context = {
    "node_healths": node_healths,
    "before": getattr(self, "_last_metrics", {}),
    "after": system_metrics,
    "history": [s.score for s in self.orchestrator._iteration_history[-5:]],
    "subsystem": "vectora",
}
da_out = self.devils_advocate.execute(
    NodeInput(action="architectural_review", parameters=da_context)
)
if da_out.success and da_out.result:
    da_report = da_out.result
    open_count = da_report.get("open_count", 0)
    veto = da_report.get("veto", False)
    logger.info(
        "[DA] %s | open_challenges=%d | veto=%s",
        da_report.get("verdict", "?"),
        open_count,
        veto,
    )
    if veto:
        logger.warning("[DA] Improvement VETOED — unresolved CRITICAL challenges exist")
self._last_metrics = dict(system_metrics)
```

- [ ] **Step 4.3: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```
Expected: all tests pass.

- [ ] **Step 4.4: Commit**

```bash
git add omega/nodes/__init__.py omega/examples/vectora_main.py
git commit -m "feat(devil): wire DevilsAdvocateNode into Vectora heartbeat loop"
```

---

## Task 5: SKILL.md

**Files:**
- Create: `omega/skills/devils-advocate/SKILL.md`

- [ ] **Step 5.1: Create the skill file**

```markdown
# Devil's Advocate Skill

Think adversarially about system design. When invoked, challenge every
assumption, find failure modes, and produce a structured critique.

## How to Think Like a Devil's Advocate

### 1. Invert the Success Assumptions
For every claim "X ensures Y", ask: "Under what conditions does X *not* ensure Y?"
- "EWC protects against catastrophic forgetting" → what if the task boundary is wrong?
- "Nash welfare maximises fairness" → what if one agent has unbounded utility?

### 2. Find the Hidden O(n) / O(t) Growth
Every abstraction has a cost. Ask: "What grows unboundedly as this system runs longer?"
- State accumulation (BOCPD run-length distribution)
- Challenge registry size
- Episodic memory without aggressive pruning

### 3. The Rational Agent Assumption
LLMs are not rational agents. Any mechanism that assumes truthful reporting,
utility maximisation, or stable preferences breaks when applied to LLM nodes.

### 4. The Grounding Problem
Any system that writes LLM-generated content back to persistent memory must
verify it against ground truth. Ungrounded beliefs compound.

### 5. Circular Dependency Hunt
Draw the dependency graph. Look for cycles:
- Does alignment check nodes that implement alignment?
- Does the registry depend on nodes that depend on the registry?

### 6. Regression in Disguise
Improvements that raise one metric often lower another.
Always ask: "What breaks when this gets better?"

### 7. YAGNI Check
For every abstraction layer, ask: "What is the simplest thing that achieves
80% of this benefit?" If the answer is <20 lines of code, the abstraction
is probably premature.

## Usage in Code

```python
from omega.core.challenge_registry import ChallengeRegistry, ChallengeSeverity
from omega.core.verification_gates import VerificationGateSystem, RegressionGate
from omega.nodes.devils_advocate import DevilsAdvocateNode

registry = ChallengeRegistry(db_path="omega.db")
registry.seed_initial_challenges()

gates = VerificationGateSystem()
gates.register(RegressionGate("sharpe", metric="sharpe_ratio", direction="maximize", threshold_pct=15.0))

da = DevilsAdvocateNode(registry=registry, gate_system=gates)
report = da.execute(NodeInput(action="architectural_review", parameters={"subsystem": "alignment"}))
```

## Challenge Severity Guide

| Severity | Meaning | Action |
|----------|---------|--------|
| CRITICAL | Will cause system failure or data corruption | Block deployment |
| HIGH | Will cause silent degradation or incorrect results | Require resolution before next release |
| MEDIUM | Suboptimal behaviour; workarounds exist | Track and schedule fix |
| LOW | Stylistic or future-proofing concern | Log and accept |
```

- [ ] **Step 5.2: Commit**

```bash
mkdir -p omega/skills/devils-advocate
git add omega/skills/devils-advocate/SKILL.md
git commit -m "docs(devil): add devils-advocate skill with adversarial thinking guide"
```

---

## Task 6: Full Test Run and Final Commit

- [ ] **Step 6.1: Run complete test suite**

```bash
python -m pytest tests/ -v
```
Expected: all tests in `test_challenge_registry.py`, `test_verification_gates.py`, `test_devils_advocate.py`, plus existing tests in `test_node.py`, `test_orchestrator.py`, `test_evaluator.py`, `test_dashboard_node.py` — all PASS.

- [ ] **Step 6.2: Verify import chain**

```bash
python -c "
from omega.core.challenge_registry import ChallengeRegistry, ChallengeSeverity
from omega.core.verification_gates import VerificationGateSystem, PropertyGate, RegressionGate
from omega.nodes.devils_advocate import DevilsAdvocateNode
reg = ChallengeRegistry()
reg.seed_initial_challenges()
print(f'Seeded {len(reg.all_challenges())} challenges')
print(f'Blocking: {reg.has_blocking_challenges()}')
print('All imports OK')
"
```
Expected output includes `Seeded 18 challenges` and `All imports OK`.

- [ ] **Step 6.3: Final commit**

```bash
git add -A
git commit -m "feat(devil): complete devil's advocate layer — registry, gates, node, heartbeat wiring"
```
