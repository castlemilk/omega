"""
omega.core.challenge_registry
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Persistent store of challenges raised by the Devil's Advocate node.

Each challenge targets a subsystem, has a severity, evidence, and lifecycle
status. Unresolved CRITICAL challenges block deployments via has_blocking_challenges().
Resolution rate is tracked as a system health metric.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import Enum


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

# Seeded challenges — covering both current architecture and planned subsystems.
# 18 substantive challenges: 8 against existing code, 10 against planned architecture.
_SEED_CHALLENGES = [
    # ── Current architecture ──────────────────────────────────────────────────
    dict(
        target_subsystem="orchestrator.convergence_loop",
        severity=ChallengeSeverity.HIGH,
        description=(
            "Convergence detection uses a single metric delta threshold — the system "
            "can stop improving a metric because it oscillates just below the threshold, "
            "appearing converged while actually thrashing."
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
            "improve_system() sends identical feedback to every node regardless of "
            "whether that node contributed to the failing metric. A slow "
            "DataIngestionNode triggers improve() on SignalGenerationNode and "
            "RiskManagementNode."
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
            "EpisodicStore importance decay is time-based, not outcome-based. A signal "
            "that predicted a 40% crash correctly decays at the same rate as a noise "
            "signal. High-importance rare events will be pruned before the system can "
            "learn from them."
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
            "by at least one consolidation window, issuing stale guidance to nodes."
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
            "SignalGenerationNode self-improvement unlocks new indicator types each "
            "cycle. No check that adding a new indicator doesn't re-introduce a "
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
            "VerificationNode uses a fixed 30% regression threshold — arbitrary. "
            "A 29% regression in Sharpe during high-volatility may be noise; "
            "a 5% regression in max drawdown may be catastrophic. Thresholds should "
            "be metric-specific and regime-aware."
        ),
        evidence=(
            "verification.py:REGRESSION_THRESHOLD = 0.3 — single constant applied "
            "to all metrics regardless of scale or business impact."
        ),
    ),
    dict(
        target_subsystem="vectora.data_ingestion",
        severity=ChallengeSeverity.HIGH,
        description=(
            "DataIngestionNode falls back to cached data on failure without staleness "
            "bounds. If Binance and CoinGecko both fail for 24+ hours, the pipeline "
            "continues on day-old data producing 'valid' signals with no staleness "
            "warning in the output."
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
            "If the heartbeat loop gains async or threading support, concurrent writes "
            "will corrupt the database silently."
        ),
        evidence=(
            "state_store.py:__init__ — sqlite3.connect(db_path, check_same_thread=False); "
            "no write serialisation."
        ),
    ),
    dict(
        target_subsystem="orchestrator.node_selection",
        severity=ChallengeSeverity.MEDIUM,
        description=(
            "Node selection always picks the highest-health node — greedy, no "
            "exploration. A new improved node version starting at health=0.5 will "
            "never be selected over a stale node at health=0.9, permanently blocking "
            "the system from discovering that the new version is better."
        ),
        evidence=(
            "orchestrator.py:_select_node — max(candidates, key=health). "
            "No epsilon-greedy or UCB exploration. New nodes are starved of execution data."
        ),
    ),
    dict(
        target_subsystem="vectora.strategy",
        severity=ChallengeSeverity.HIGH,
        description=(
            "StrategyNode backtest uses the same data window for both signal training "
            "and portfolio evaluation — look-ahead bias. Reported Sharpe ratios are "
            "optimistic by an unknown but likely significant factor."
        ),
        evidence=(
            "strategy.py — signals and backtest share the same OHLCV window; "
            "no walk-forward or out-of-sample holdout separation."
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
            "separable with stable Fisher information estimates. Crypto regime "
            "transitions are gradual and overlapping, not discrete. EWC importance "
            "weights computed during one regime will incorrectly protect parameters "
            "that should adapt during a transition, resisting beneficial updates."
        ),
        evidence=(
            "EWC design assumes clear task boundaries. Crypto markets exhibit "
            "non-stationary overlapping regimes (bull/bear/sideways/high-vol) with "
            "no ground-truth change point. BOCPD or HMM-based regime detection would "
            "be needed to gate EWC application correctly."
        ),
    ),
    dict(
        target_subsystem="alignment.nash_welfare",
        severity=ChallengeSeverity.CRITICAL,
        description=(
            "Nash welfare aggregation requires knowing all objectives upfront. "
            "If a new objective emerges mid-operation (e.g. 'minimise drawdown during "
            "regulatory crackdown'), adding it retroactively changes welfare scores "
            "of all prior decisions, potentially invalidating the improvement history."
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
            "The IterDRAG research skill has no grounding mechanism. Retrieval from "
            "a vector store followed by LLM generation can produce hallucinated "
            "justifications for plausible-but-wrong documents. Hallucinated research "
            "findings stored back into SemanticMemory propagate permanently to all "
            "downstream nodes."
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
            "not rational — they are stochastic functions that may 'misreport' their "
            "true valuation due to prompt framing, temperature, or context window "
            "effects. The VCG mechanism's incentive-compatibility guarantee breaks down."
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
            "will OOM within days unless a truncation scheme is implemented, and the "
            "truncation point must be chosen carefully to not miss long-horizon regimes."
        ),
        evidence=(
            "BOCPD: P(r_t | x_{1:t}) computed over all r_t ∈ {0, 1, …, t}. "
            "At 1000 heartbeats/day × 180 days = 180,000 hypotheses untruncated. "
            "Hazard function truncation at window W loses detection of regimes > W."
        ),
    ),
    dict(
        target_subsystem="alignment.constitutional_constraints",
        severity=ChallengeSeverity.HIGH,
        description=(
            "Constitutional constraints are described as 'nodes cannot override' but "
            "the enforcement mechanism is trust-based, not structural. Any node that "
            "calls improve() on itself can change its own behaviour. There is no "
            "sandboxing, no capability revocation, and no cryptographic proof that "
            "constitutional rules were actually checked."
        ),
        evidence=(
            "node.py:improve() is abstract — implementations are free to do anything. "
            "The orchestrator calls improve() and trusts the return value. "
            "No post-improvement audit of node behaviour against constitutional rules."
        ),
    ),
    dict(
        target_subsystem="skills.skill_system",
        severity=ChallengeSeverity.MEDIUM,
        description=(
            "The skill system has no versioning or compatibility contract. If a skill "
            "is updated while a long-running heartbeat loop is active, mid-loop "
            "behaviour changes unpredictably. Skills loaded at startup may differ from "
            "skills loaded on the next restart, making debugging intermittent failures "
            "extremely difficult."
        ),
        evidence=(
            "omega/skills/ — no skill version pinning, no schema validation, "
            "no compatibility matrix between skill versions and node versions."
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
        challenge_id: str | None = None,
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

    def get(self, challenge_id: str) -> Challenge | None:
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

    def all_challenges(self, subsystem: str | None = None) -> list[Challenge]:
        query = "SELECT * FROM challenges"
        params: list = []
        if subsystem:
            query += " WHERE target_subsystem LIKE ?"
            params.append(f"%{subsystem}%")
        query += " ORDER BY created_at"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_challenge(r) for r in rows]

    def open_challenges(self, severity: ChallengeSeverity | None = None) -> list[Challenge]:
        query = "SELECT * FROM challenges WHERE status = 'open'"
        params: list = []
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
            for row in self._conn.execute("SELECT description FROM challenges").fetchall()
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
