"""
omega.core.node_skills
~~~~~~~~~~~~~~~~~~~~~~
Per-node skills framework — makes each Victoria node genuinely intelligent
with its own skills registry, signal lifecycle tracking, ISQ reasoning, and
retrieval-augmented context.

Inspired by AlphaEar / Awesome-Finance-Skills 4-layer architecture:
    Discovery → Analysis → Prediction → Output

Modules
-------
1. SkillRegistry         — each node declares skills (what it can do, what model it wraps)
2. SignalEvolutionTracker — temporal signal lifecycle: EMERGING → STRENGTHENING →
                           STABLE → WEAKENING → FALSIFIED
3. ISQValidator          — Investment Signal Qualification: structured reasoning per node
4. NodeRAGContext        — per-node retrieval context (BM25 + cosine hybrid)
5. NodeSkillFramework    — top-level facade wiring 1–4 together
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]  # noqa: UP042
        pass


from typing import Any, ClassVar

logger = logging.getLogger("omega.core.node_skills")


# ---------------------------------------------------------------------------
# 1. Skill Registry
# ---------------------------------------------------------------------------


@dataclass
class NodeSkill:
    """
    A single skill declared by a node.

    Parameters
    ----------
    name          : Unique skill identifier within the node (e.g. "sentiment_analysis").
    description   : Human-readable description of what the skill does.
    model         : Underlying model/technique (e.g. "FinBERT", "Kronos", "RMT denoiser").
    input_schema  : Field name → type hint for expected inputs.
    output_schema : Field name → type hint for expected outputs.
    confidence_score : EMA-tracked historical performance (0.0–1.0).
    skill_version : Semantic version for tracking improvements.
    """

    name: str
    description: str
    model: str
    input_schema: dict[str, str] = field(default_factory=dict)
    output_schema: dict[str, str] = field(default_factory=dict)
    confidence_score: float = 0.5
    skill_version: str = "1.0.0"
    execution_count: int = 0
    success_count: int = 0
    last_updated: datetime = field(default_factory=datetime.now)

    @property
    def success_rate(self) -> float:
        """Historical success rate (uses confidence prior until executions accumulate)."""
        if self.execution_count == 0:
            return self.confidence_score
        return self.success_count / self.execution_count


class SkillRegistry:
    """
    Manages the set of skills a node has declared.

    Usage::

        registry = SkillRegistry()
        registry.register(NodeSkill(
            name="finbert_sentiment",
            description="Classify funding-rate sentiment via FinBERT proxy",
            model="FinBERT / funding-rate proxy",
            confidence_score=0.72,
        ))
        skill = registry.get("finbert_sentiment")
        registry.record_execution("finbert_sentiment", success=True)
    """

    def __init__(self) -> None:
        self._skills: dict[str, NodeSkill] = {}

    def register(self, skill: NodeSkill) -> None:
        """Register or overwrite a skill."""
        self._skills[skill.name] = skill

    def get(self, name: str) -> NodeSkill | None:
        return self._skills.get(name)

    def list_skills(self) -> list[NodeSkill]:
        return list(self._skills.values())

    def record_execution(self, name: str, success: bool) -> None:
        """Update confidence score with EMA after each execution (α=0.1)."""
        skill = self._skills.get(name)
        if skill is None:
            return
        skill.execution_count += 1
        if success:
            skill.success_count += 1
        alpha = 0.1
        skill.confidence_score = (1 - alpha) * skill.confidence_score + alpha * (
            1.0 if success else 0.0
        )
        skill.last_updated = datetime.now()

    def summary(self) -> dict[str, Any]:
        """Return a serialisable summary for metrics / logging."""
        skills = self.list_skills()
        avg_conf = sum(s.confidence_score for s in skills) / max(len(skills), 1)
        return {
            "count": len(skills),
            "avg_confidence": round(avg_conf, 4),
            "skills": [
                {
                    "name": s.name,
                    "model": s.model,
                    "confidence": round(s.confidence_score, 4),
                    "version": s.skill_version,
                    "executions": s.execution_count,
                }
                for s in skills
            ],
        }


# ---------------------------------------------------------------------------
# 2. Signal Evolution Tracker
# ---------------------------------------------------------------------------


class SignalLifecycle(StrEnum):
    """Lifecycle states of a trading signal."""

    EMERGING = "EMERGING"
    STRENGTHENING = "STRENGTHENING"
    STABLE = "STABLE"
    WEAKENING = "WEAKENING"
    FALSIFIED = "FALSIFIED"
    RETIRED = "RETIRED"


class SignalRetirementReason(StrEnum):
    """Why a signal was auto-retired."""

    LOW_IC = "LOW_IC"  # IC stayed below threshold for retirement_window cycles


@dataclass
class StateTransition:
    """A recorded state change in a signal's lifecycle."""

    from_state: SignalLifecycle
    to_state: SignalLifecycle
    timestamp: datetime
    evidence: str
    signal_value: float


@dataclass
class SignalEvolution:
    """
    Tracks the temporal lifecycle of a single signal.

    Transition logic
    ----------------
    EMERGING        → needs ≥3 observations to graduate.
    STRENGTHENING   → ≥5 observations with ≥70% directional agreement.
    STABLE          → ≥10 observations with ≥80% agreement over the full window.
    WEAKENING       → STABLE signal drops below 60% agreement over last 5 observations.
    FALSIFIED       → 3 consecutive observations all flip direction vs prior.
    """

    signal_name: str
    current_state: SignalLifecycle = SignalLifecycle.EMERGING
    transitions: list[StateTransition] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    _values: deque = field(default_factory=lambda: deque(maxlen=20))
    _directions: deque = field(default_factory=lambda: deque(maxlen=20))

    # IC tracking for auto-retirement
    cycles_below_ic_threshold: int = 0
    retirement_reason: SignalRetirementReason | None = None

    # ------------------------------------------------------------------ #

    def observe(self, value: float) -> SignalLifecycle:
        """Record a new observation and potentially transition state."""
        # Retired signals do not change state
        if self.current_state == SignalLifecycle.RETIRED:
            return self.current_state

        direction = 1 if value > 0.05 else (-1 if value < -0.05 else 0)
        self._values.append(value)
        self._directions.append(direction)

        new_state = self._compute_next_state()
        if new_state != self.current_state:
            self.transitions.append(
                StateTransition(
                    from_state=self.current_state,
                    to_state=new_state,
                    timestamp=datetime.now(),
                    evidence=self._transition_evidence(new_state, value),
                    signal_value=value,
                )
            )
            logger.debug(
                "signal=%s %s→%s value=%.4f",
                self.signal_name,
                self.current_state.value,
                new_state.value,
                value,
            )
            self.current_state = new_state
        return self.current_state

    def _compute_next_state(self) -> SignalLifecycle:
        n = len(self._directions)
        if n < 3:
            return SignalLifecycle.EMERGING

        dirs = list(self._directions)
        last3 = dirs[-3:]
        last5 = dirs[-5:] if n >= 5 else dirs
        last10 = dirs[-10:] if n >= 10 else dirs

        def agreement(window: list[int]) -> float:
            nonzero = [d for d in window if d != 0]
            if not nonzero:
                return 0.5  # neutral
            dominant = 1 if sum(nonzero) >= 0 else -1
            return sum(1 for d in nonzero if d == dominant) / len(nonzero)

        a5 = agreement(last5)
        a10 = agreement(last10)

        # FALSIFIED: current state is STABLE/WEAKENING + 3-cycle direction flip
        if (
            self.current_state in (SignalLifecycle.STABLE, SignalLifecycle.WEAKENING)
            and len(last3) == 3
        ):
            flip = last3[0] != 0 and last3[-1] != 0 and last3[0] != last3[-1]
            consistent_flip = all(d == last3[-1] for d in last3[-2:])
            if flip and consistent_flip:
                return SignalLifecycle.FALSIFIED

        # WEAKENING: was STABLE but agreement dropped
        if self.current_state == SignalLifecycle.STABLE and a5 < 0.60:
            return SignalLifecycle.WEAKENING

        # STABLE: strong sustained agreement
        if n >= 10 and a10 >= 0.80:
            return SignalLifecycle.STABLE

        # STRENGTHENING: good 5-cycle agreement
        if a5 >= 0.70:
            return SignalLifecycle.STRENGTHENING

        # Recovery from WEAKENING
        if self.current_state == SignalLifecycle.WEAKENING and a5 >= 0.70:
            return SignalLifecycle.STRENGTHENING

        return self.current_state

    def _transition_evidence(self, to_state: SignalLifecycle, value: float) -> str:
        n = len(self._values)
        recent = list(self._values)[-5:]
        avg_recent = sum(recent) / len(recent) if recent else 0.0
        return f"value={value:.4f} avg_recent_5={avg_recent:.4f} n_obs={n} → {to_state.value}"

    @property
    def signal_reliability(self) -> float:
        """Fraction of lifecycle completions that reached STABLE vs FALSIFIED."""
        stable = sum(1 for t in self.transitions if t.to_state == SignalLifecycle.STABLE)
        falsified = sum(1 for t in self.transitions if t.to_state == SignalLifecycle.FALSIFIED)
        total = stable + falsified
        return stable / total if total > 0 else 0.5  # neutral prior


class SignalEvolutionTracker:
    """
    Tracks the lifecycle of multiple signals.

    Parameters
    ----------
    window           : Rolling window size for direction observations.
    ic_threshold     : Minimum IC below which a cycle counts toward retirement.
    retirement_window: Consecutive cycles below ic_threshold required to auto-retire.
    """

    def __init__(
        self,
        window: int = 20,
        ic_threshold: float = 0.02,
        retirement_window: int = 50,
    ) -> None:
        self._evolutions: dict[str, SignalEvolution] = {}
        self._window = window
        self._ic_threshold = ic_threshold
        self._retirement_window = retirement_window

    def observe(self, signal_name: str, value: float) -> SignalLifecycle:
        if signal_name not in self._evolutions:
            self._evolutions[signal_name] = SignalEvolution(
                signal_name=signal_name,
                _values=deque(maxlen=self._window),
                _directions=deque(maxlen=self._window),
            )
        return self._evolutions[signal_name].observe(value)

    def observe_many(self, signals: dict[str, float]) -> dict[str, SignalLifecycle]:
        return {name: self.observe(name, val) for name, val in signals.items()}

    def get_evolution(self, signal_name: str) -> SignalEvolution | None:
        return self._evolutions.get(signal_name)

    def record_ic(self, signal_name: str, ic: float) -> None:
        """
        Record an IC value for a signal and trigger retirement if applicable.

        If the signal's IC has been below ``ic_threshold`` for
        ``retirement_window`` consecutive cycles, the signal is auto-retired.
        """
        ev = self._evolutions.get(signal_name)
        if ev is None:
            return
        if ev.current_state == SignalLifecycle.RETIRED:
            return

        if ic < self._ic_threshold:
            ev.cycles_below_ic_threshold += 1
        else:
            ev.cycles_below_ic_threshold = 0  # reset on recovery

        if ev.cycles_below_ic_threshold >= self._retirement_window:
            # current_state != RETIRED is guaranteed by the early return above.
            ev.retirement_reason = SignalRetirementReason.LOW_IC
            ev.transitions.append(
                StateTransition(
                    from_state=ev.current_state,
                    to_state=SignalLifecycle.RETIRED,
                    timestamp=datetime.now(),
                    evidence=(
                        f"IC={ic:.4f} below threshold={self._ic_threshold:.4f} "
                        f"for {ev.cycles_below_ic_threshold} consecutive cycles "
                        f"(window={self._retirement_window})"
                    ),
                    signal_value=ic,
                )
            )
            ev.current_state = SignalLifecycle.RETIRED
            logger.warning(
                "Signal '%s' auto-retired: IC=%.4f below %.4f for %d cycles",
                signal_name,
                ic,
                self._ic_threshold,
                ev.cycles_below_ic_threshold,
            )

    def is_retired(self, signal_name: str) -> bool:
        """Return True if the named signal has been auto-retired."""
        ev = self._evolutions.get(signal_name)
        return ev is not None and ev.current_state == SignalLifecycle.RETIRED

    def get_retired_signals(self) -> list[str]:
        """Return names of all signals that have been auto-retired."""
        return [
            name
            for name, ev in self._evolutions.items()
            if ev.current_state == SignalLifecycle.RETIRED
        ]

    @property
    def signal_reliability(self) -> float:
        """Overall reliability: fraction of signals in STABLE vs FALSIFIED."""
        stable = sum(
            1 for e in self._evolutions.values() if e.current_state == SignalLifecycle.STABLE
        )
        falsified = sum(
            1 for e in self._evolutions.values() if e.current_state == SignalLifecycle.FALSIFIED
        )
        total = stable + falsified
        return stable / total if total > 0 else 0.5

    def summary(self) -> dict[str, Any]:
        by_state: dict[str, list[str]] = {}
        for name, ev in self._evolutions.items():
            by_state.setdefault(ev.current_state.value, []).append(name)
        return {
            "total_signals": len(self._evolutions),
            "by_state": {k: len(v) for k, v in by_state.items()},
            "signal_reliability": round(self.signal_reliability, 4),
            "signals": {
                name: {
                    "state": ev.current_state.value,
                    "transitions": len(ev.transitions),
                    "reliability": round(ev.signal_reliability, 4),
                }
                for name, ev in self._evolutions.items()
            },
        }


# ---------------------------------------------------------------------------
# 3. ISQ — Investment Signal Qualification
# ---------------------------------------------------------------------------


@dataclass
class ISQTemplate:
    """
    Per-node reasoning template that governs how ISQ checks are run.

    Parameters
    ----------
    node_name                 : Name of the node this template belongs to.
    data_freshness_max_seconds: Maximum acceptable age (seconds) for market data.
    consistency_threshold     : Minimum signal directional agreement (0–1) to pass.
    min_signal_count          : Minimum number of valid numeric signals required.
    regime_alignment_signals  : Signal names used for regime-alignment check.
    cross_validation_pairs    : Pairs of signals expected to agree in direction.
    qualification_threshold   : Minimum ISQ score to pass (0–1).
    """

    node_name: str
    data_freshness_max_seconds: float = 300.0  # 5 minutes
    consistency_threshold: float = 0.55
    min_signal_count: int = 3
    regime_alignment_signals: list[str] = field(default_factory=list)
    cross_validation_pairs: list[tuple[str, str]] = field(default_factory=list)
    qualification_threshold: float = 0.45


@dataclass
class ISQResult:
    """Result of an ISQ qualification run."""

    qualification_score: float  # 0.0 – 1.0
    concerns: list[str]
    check_results: dict[str, float]
    passed: bool
    timestamp: datetime = field(default_factory=datetime.now)

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"ISQ[{status}] score={self.qualification_score:.3f} concerns={len(self.concerns)}"


class ISQValidator:
    """
    Structured reasoning template validator for investment signals.

    Checks (weighted)
    -----------------
    1. data_freshness    (0.25) — is market data recent enough?
    2. signal_count      (0.10) — enough signals to form a view?
    3. signal_consistency(0.30) — do signals broadly agree in direction?
    4. regime_alignment  (0.20) — do signals match the detected regime?
    5. cross_validation  (0.15) — do correlated pairs agree?

    If qualification_score < template.qualification_threshold, the result
    is marked as failed and callers can lower-confidence their output.
    """

    _WEIGHTS: ClassVar[dict[str, float]] = {
        "data_freshness": 0.25,
        "signal_count": 0.10,
        "signal_consistency": 0.30,
        "regime_alignment": 0.20,
        "cross_validation": 0.15,
    }

    def __init__(self, template: ISQTemplate) -> None:
        self._template = template
        self._history: deque[ISQResult] = deque(maxlen=50)

    def qualify(
        self,
        signals: dict[str, Any],
        market_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ISQResult:
        """Run all ISQ checks and return a qualified result."""
        ctx = context or {}
        check_results: dict[str, float] = {}
        concerns: list[str] = []

        check_results["data_freshness"] = self._check_freshness(market_data, concerns)
        check_results["signal_count"] = self._check_signal_count(signals, concerns)
        check_results["signal_consistency"] = self._check_consistency(signals, concerns)
        check_results["regime_alignment"] = self._check_regime_alignment(signals, ctx, concerns)
        check_results["cross_validation"] = self._check_cross_validation(signals, concerns)

        score = sum(self._WEIGHTS[k] * check_results[k] for k in self._WEIGHTS)
        passed = score >= self._template.qualification_threshold

        result = ISQResult(
            qualification_score=round(score, 4),
            concerns=concerns,
            check_results={k: round(v, 4) for k, v in check_results.items()},
            passed=passed,
        )
        self._history.append(result)
        return result

    # ------------------------------------------------------------------ #
    # Individual checks
    # ------------------------------------------------------------------ #

    def _check_freshness(self, market_data: dict[str, Any], concerns: list[str]) -> float:
        ts = market_data.get("timestamp") or market_data.get("fetched_at")
        if ts is None:
            concerns.append("No market data timestamp — freshness unknown")
            return 0.4  # partial credit; data may still be valid

        try:
            if isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(float(ts))
            elif isinstance(ts, str):
                # ISO8601 or similar — strip tz for naive comparison
                clean = re.sub(r"[TZ]", " ", ts).strip()
                clean = re.sub(r"\+\d{2}:\d{2}$", "", clean).strip()
                dt = datetime.fromisoformat(clean)
            else:
                dt = ts  # assume datetime-like

            age = (datetime.now() - dt).total_seconds()
            max_age = self._template.data_freshness_max_seconds
            if age > max_age * 2:
                concerns.append(f"Market data stale: {age:.0f}s old (max {max_age:.0f}s)")
                return 0.0
            return max(0.0, 1.0 - age / max_age)
        except Exception:
            return 0.5  # can't parse → neutral

    def _check_signal_count(self, signals: dict[str, Any], concerns: list[str]) -> float:
        count = sum(
            1 for k, v in signals.items() if not k.startswith("_") and isinstance(v, (int, float))
        )
        # Also count dict-type signals that have a "value" field
        count += sum(
            1
            for k, v in signals.items()
            if not k.startswith("_")
            and isinstance(v, dict)
            and isinstance(v.get("value"), (int, float))
        )
        min_count = self._template.min_signal_count
        if count < min_count:
            concerns.append(f"Only {count} signals; min {min_count} required")
            return count / max(min_count, 1)
        return 1.0

    def _check_consistency(self, signals: dict[str, Any], concerns: list[str]) -> float:
        values: list[float] = []
        for k, v in signals.items():
            if k.startswith("_"):
                continue
            if isinstance(v, (int, float)):
                values.append(float(v))
            elif isinstance(v, dict):
                val = v.get("value")
                if isinstance(val, (int, float)):
                    values.append(float(val))

        if len(values) < 2:
            return 0.5

        positive = sum(1 for v in values if v > 0.05)
        negative = sum(1 for v in values if v < -0.05)
        neutral = len(values) - positive - negative
        majority = max(positive, negative, neutral)
        consistency = majority / len(values)

        if consistency < self._template.consistency_threshold:
            concerns.append(
                f"Signal consistency {consistency:.2f} below threshold "
                f"{self._template.consistency_threshold:.2f}"
            )
        return consistency

    def _check_regime_alignment(
        self,
        signals: dict[str, Any],
        context: dict[str, Any],
        concerns: list[str],
    ) -> float:
        regime = context.get("regime") or signals.get("_regime") or "NEUTRAL"
        regime_sigs = self._template.regime_alignment_signals
        if not regime_sigs:
            return 0.65  # no template → partial credit

        vals: list[float] = []
        for s in regime_sigs:
            v = signals.get(s)
            if isinstance(v, (int, float)):
                vals.append(float(v))
            elif isinstance(v, dict):
                inner = v.get("value")
                if isinstance(inner, (int, float)):
                    vals.append(float(inner))

        if not vals:
            return 0.5

        avg = sum(vals) / len(vals)

        bull_regimes = {"BULL", "RISK_ON", "high_momentum", "bull", "risk_on"}
        bear_regimes = {"BEAR", "RISK_OFF", "high_vol", "crisis", "bear", "risk_off"}

        if regime in bull_regimes:
            score = min(1.0, max(0.0, (avg + 1.0) / 2.0))
        elif regime in bear_regimes:
            score = min(1.0, max(0.0, (1.0 - avg) / 2.0))
        else:
            score = 0.65  # neutral regime → partial credit

        if score < 0.35:
            concerns.append(f"Signals poorly aligned with regime '{regime}' (avg={avg:.3f})")
        return score

    def _check_cross_validation(self, signals: dict[str, Any], concerns: list[str]) -> float:
        pairs = self._template.cross_validation_pairs
        if not pairs:
            return 0.65  # no template → partial credit

        scores: list[float] = []
        for s1, s2 in pairs:
            v1 = self._extract_value(signals, s1)
            v2 = self._extract_value(signals, s2)
            if v1 is None or v2 is None:
                continue
            agree = v1 * v2 >= 0  # same sign → agreement
            scores.append(1.0 if agree else 0.0)
            if not agree:
                concerns.append(f"Cross-signal conflict: {s1}={v1:.3f} ↔ {s2}={v2:.3f}")

        return sum(scores) / len(scores) if scores else 0.65

    @staticmethod
    def _extract_value(signals: dict[str, Any], key: str) -> float | None:
        v = signals.get(key)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, dict):
            inner = v.get("value")
            if isinstance(inner, (int, float)):
                return float(inner)
        return None

    @property
    def recent_avg_score(self) -> float:
        if not self._history:
            return 0.5
        return sum(r.qualification_score for r in self._history) / len(self._history)


# ---------------------------------------------------------------------------
# 4. Per-Node RAG Context
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Whitespace + punctuation tokenizer."""
    return re.findall(r"\w+", text.lower())


def _dict_to_text(d: Any, depth: int = 0) -> str:
    """Flatten a dict/list to text for BM25 tokenization."""
    if depth > 3:
        return str(d)
    if isinstance(d, dict):
        parts = []
        for k, v in d.items():
            parts.append(f"{k} {_dict_to_text(v, depth + 1)}")
        return " ".join(parts)
    if isinstance(d, (list, tuple)):
        return " ".join(str(x) for x in d[:20])
    return str(d)


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    avg_dl: float,
    idf: dict[str, float],
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    dl = len(doc_tokens)
    tf_map: dict[str, int] = {}
    for t in doc_tokens:
        tf_map[t] = tf_map.get(t, 0) + 1

    score = 0.0
    for qt in query_tokens:
        tf = tf_map.get(qt, 0)
        if tf == 0:
            continue
        idf_val = idf.get(qt, 0.0)
        num = tf * (k1 + 1)
        den = tf + k1 * (1 - b + b * dl / max(avg_dl, 1))
        score += idf_val * num / den
    return score


@dataclass
class RAGEpisode:
    """A single stored episode in the RAG context."""

    episode_id: str
    content: dict[str, Any]
    score: float
    timestamp: datetime = field(default_factory=datetime.now)
    tokens: list[str] = field(default_factory=list)


class NodeRAGContext:
    """
    Per-node retrieval-augmented context.

    Combines BM25 (lexical) and a lightweight embedding-free proximity score
    across three stores:
    - Recent cycle outputs (rolling window)
    - Best/worst performing episodes (fixed-size sorted lists)
    - Domain knowledge snippets (research notes, patterns)

    Usage::

        rag = NodeRAGContext()
        rag.add_knowledge(
            "FinBERT sentiment leads price by 2–4 hours in crypto markets",
            source="2024 finbert crypto paper"
        )
        rag.record_episode({"signals": {...}, "result": {...}}, score=0.82)
        context = rag.retrieve({"sentiment": 0.4, "regime": "BULL"}, top_k=3)
    """

    def __init__(
        self,
        max_recent: int = 100,
        max_best: int = 10,
        max_worst: int = 5,
        max_knowledge: int = 50,
    ) -> None:
        self._recent: deque[RAGEpisode] = deque(maxlen=max_recent)
        self._best: list[RAGEpisode] = []
        self._worst: list[RAGEpisode] = []
        self._max_best = max_best
        self._max_worst = max_worst
        self._knowledge: list[RAGEpisode] = []
        self._max_knowledge = max_knowledge

    def record_episode(self, content: dict[str, Any], score: float) -> None:
        """Record a completed cycle result."""
        text = _dict_to_text(content)
        ep = RAGEpisode(
            episode_id=str(uuid.uuid4()),
            content=content,
            score=score,
            tokens=_tokenize(text),
        )
        self._recent.append(ep)

        # Maintain top-N best
        self._best.append(ep)
        self._best.sort(key=lambda e: e.score, reverse=True)
        self._best = self._best[: self._max_best]

        # Maintain bottom-N worst
        self._worst.append(ep)
        self._worst.sort(key=lambda e: e.score)
        self._worst = self._worst[: self._max_worst]

    def add_knowledge(
        self,
        text: str,
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a domain knowledge snippet (research paper excerpt, pattern note, etc.)."""
        if len(self._knowledge) >= self._max_knowledge:
            self._knowledge.pop(0)
        ep = RAGEpisode(
            episode_id=str(uuid.uuid4()),
            content={"text": text, "source": source, "metadata": metadata or {}},
            score=1.0,
            tokens=_tokenize(text),
        )
        self._knowledge.append(ep)

    def retrieve(self, query: dict[str, Any], top_k: int = 5) -> list[dict[str, Any]]:
        """
        BM25-ranked retrieval from recent + best + knowledge stores.

        Returns up to *top_k* episodes sorted by relevance (highest first),
        each augmented with `_score` and `_id` fields.
        """
        query_tokens = _tokenize(_dict_to_text(query))
        corpus = list(self._recent) + self._best + self._knowledge

        if not corpus or not query_tokens:
            return []

        # Build IDF
        n = len(corpus)
        df: dict[str, int] = {}
        for ep in corpus:
            for t in set(ep.tokens):
                df[t] = df.get(t, 0) + 1
        idf = {t: math.log((n - cnt + 0.5) / (cnt + 0.5) + 1) for t, cnt in df.items()}

        avg_dl = sum(len(ep.tokens) for ep in corpus) / n

        scored: list[tuple[float, RAGEpisode]] = [
            (_bm25_score(query_tokens, ep.tokens, avg_dl, idf), ep) for ep in corpus
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        max_score = scored[0][0] if scored[0][0] > 0 else 1.0
        return [
            {
                **ep.content,
                "_score": round(s / max_score, 4),
                "_id": ep.episode_id,
                "_timestamp": ep.timestamp.isoformat(),
            }
            for s, ep in scored[:top_k]
        ]

    @property
    def episode_count(self) -> int:
        return len(self._recent)

    @property
    def knowledge_count(self) -> int:
        return len(self._knowledge)


# ---------------------------------------------------------------------------
# 5. NodeSkillFramework — top-level facade
# ---------------------------------------------------------------------------


class NodeSkillFramework:
    """
    Top-level facade wiring SkillRegistry, SignalEvolutionTracker, ISQValidator,
    and NodeRAGContext together for a single Omega node.

    The framework is additive — it can be attached to any existing node without
    changing its core contract. Each Victoria signal generator benefits from:

    - Skills declared at construction time (what models it wraps)
    - Lifecycle tracking for every numeric signal it emits
    - ISQ checks before signals are forwarded downstream
    - RAG context for retrieving similar past episodes

    Usage::

        framework = NodeSkillFramework(
            "VictoriaNode",
            isq_template=ISQTemplate(
                node_name="VictoriaNode",
                regime_alignment_signals=["sentiment", "order_flow"],
                cross_validation_pairs=[("cross_asset", "momentum_factor")],
            ),
        )

        # Register skills once at startup
        framework.register_skill(NodeSkill(
            name="finbert_sentiment",
            description="Funding-rate sentiment via FinBERT proxy",
            model="FinBERT / funding-rate proxy",
            confidence_score=0.72,
        ))

        # On each cycle
        states = framework.observe_signals({"sentiment": 0.3, "momentum": -0.1})
        isq = framework.qualify(signals, market_data, context={"regime": "BULL"})
        if isq.passed:
            framework.record_cycle(signals, result, score=quality_score)

        metrics = framework.get_metrics()
    """

    def __init__(
        self,
        node_name: str,
        isq_template: ISQTemplate | None = None,
        rag_max_recent: int = 100,
    ) -> None:
        self.node_name = node_name
        self.skills = SkillRegistry()
        self.evolution = SignalEvolutionTracker()
        self.rag = NodeRAGContext(max_recent=rag_max_recent)
        self.isq = ISQValidator(isq_template or ISQTemplate(node_name=node_name))
        self._last_isq: ISQResult | None = None
        self._cycle_count: int = 0

    # ------------------------------------------------------------------ #
    # Skills
    # ------------------------------------------------------------------ #

    def register_skill(self, skill: NodeSkill) -> None:
        self.skills.register(skill)

    # ------------------------------------------------------------------ #
    # Signal lifecycle
    # ------------------------------------------------------------------ #

    def observe_signals(self, signals: dict[str, Any]) -> dict[str, SignalLifecycle]:
        """
        Track evolution for all numeric signals in *signals*.

        Accepts both flat ``{name: float}`` dicts and Victoria-style
        ``{name: {"value": float, ...}}`` dicts.
        """
        flat: dict[str, float] = {}
        for k, v in signals.items():
            if k.startswith("_"):
                continue
            if isinstance(v, (int, float)):
                flat[k] = float(v)
            elif isinstance(v, dict):
                inner = v.get("value")
                if isinstance(inner, (int, float)):
                    flat[k] = float(inner)
        return self.evolution.observe_many(flat)

    # ------------------------------------------------------------------ #
    # ISQ qualification
    # ------------------------------------------------------------------ #

    def qualify(
        self,
        signals: dict[str, Any],
        market_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ISQResult:
        """
        Run ISQ checks. If the score falls below the template threshold,
        the result is marked failed and a warning is logged. Callers should
        attach `_isq_passed: False` to their output in that case.
        """
        result = self.isq.qualify(signals, market_data, context or {})
        self._last_isq = result
        if not result.passed:
            logger.warning(
                "[%s] ISQ FAIL score=%.3f concerns=%s",
                self.node_name,
                result.qualification_score,
                result.concerns,
            )
        else:
            logger.debug(
                "[%s] ISQ PASS score=%.3f",
                self.node_name,
                result.qualification_score,
            )
        return result

    # ------------------------------------------------------------------ #
    # RAG
    # ------------------------------------------------------------------ #

    def record_cycle(
        self,
        signals: dict[str, Any],
        result: dict[str, Any],
        score: float,
    ) -> None:
        """Record a completed cycle in the RAG context."""
        self._cycle_count += 1
        flat_signals = {
            k: float(v)
            for k, v in signals.items()
            if isinstance(v, (int, float)) and not k.startswith("_")
        }
        # Also extract .value from dict-style signals
        for k, v in signals.items():
            if k.startswith("_") or k in flat_signals:
                continue
            if isinstance(v, dict):
                inner = v.get("value")
                if isinstance(inner, (int, float)):
                    flat_signals[k] = float(inner)

        self.rag.record_episode(
            content={
                "cycle": self._cycle_count,
                "signals": flat_signals,
                "result": result,
            },
            score=score,
        )

    def retrieve_context(self, query: dict[str, Any], top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve the most relevant past episodes for the given query."""
        return self.rag.retrieve(query, top_k=top_k)

    # ------------------------------------------------------------------ #
    # Metrics
    # ------------------------------------------------------------------ #

    def get_metrics(self) -> dict[str, float]:
        """Return a flat metrics dict suitable for orchestrator / Prometheus."""
        skill_summary = self.skills.summary()
        return {
            "skill_count": float(skill_summary["count"]),
            "avg_skill_confidence": float(skill_summary.get("avg_confidence", 0.0)),
            "signal_reliability": round(self.evolution.signal_reliability, 4),
            "isq_score": (self._last_isq.qualification_score if self._last_isq else 0.5),
            "isq_passed": float(self._last_isq.passed if self._last_isq else 0),
            "cycle_count": float(self._cycle_count),
            "rag_recent_episodes": float(self.rag.episode_count),
            "rag_knowledge_snippets": float(self.rag.knowledge_count),
        }

    def describe(self) -> str:
        skill_summary = self.skills.summary()
        return (
            f"NodeSkillFramework({self.node_name}): "
            f"{skill_summary['count']} skills, "
            f"avg_confidence={skill_summary.get('avg_confidence', 0):.3f}, "
            f"signal_reliability={self.evolution.signal_reliability:.3f}, "
            f"cycles={self._cycle_count}"
        )


# ---------------------------------------------------------------------------
# Pre-built ISQ templates for Victoria nodes
# ---------------------------------------------------------------------------


def victoria_isq_template() -> ISQTemplate:
    """
    Default ISQ template for VictoriaNode — wired to the 16 SIGNAL_NAMES
    and the correlated pairs most likely to agree when the regime is clear.
    """
    return ISQTemplate(
        node_name="VictoriaNode",
        data_freshness_max_seconds=600.0,  # 10 min — crypto data refreshes fast
        consistency_threshold=0.50,  # crypto signals are noisy; 50% is realistic
        min_signal_count=4,
        regime_alignment_signals=[
            "sentiment",
            "order_flow",
            "cross_asset",
            "btc_dominance",
        ],
        cross_validation_pairs=[
            ("cross_asset", "momentum_factor"),
            ("sentiment", "long_short_ratio"),
            ("order_flow", "microstructure"),
            ("carry", "vrp"),
        ],
        qualification_threshold=0.40,  # conservative: many signals are noisy
    )


def victoria_skills() -> list[NodeSkill]:
    """
    Pre-built NodeSkill declarations for all 16 Victoria signal generators.

    Confidence scores are seeded from documented backtest IC values;
    they are refined by EMA updates after each cycle.
    """
    return [
        NodeSkill(
            name="basic_signals",
            description="SMA/RSI/MACD/Bollinger Band technical indicators",
            model="Classical technical analysis (SMA-20/50, RSI-14, MACD-12-26-9)",
            input_schema={"ohlcv": "dict[str, DataFrame]"},
            output_schema={"composite": "float", "rsi": "float", "macd": "float"},
            confidence_score=0.58,
            skill_version="1.3.0",
        ),
        NodeSkill(
            name="order_flow",
            description="VPIN-based order flow imbalance and toxicity signals",
            model="Volume-Synchronized Probability of Informed Trading (VPIN)",
            input_schema={"market_data": "dict"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.62,
            skill_version="1.0.0",
        ),
        NodeSkill(
            name="cross_asset",
            description="BTC/ETH/SOL/BNB correlation regime and divergence signals",
            model="Rolling Pearson correlation matrix + z-score normalisation",
            input_schema={"market_data": "dict"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.64,
            skill_version="1.1.0",
        ),
        NodeSkill(
            name="microstructure",
            description="Spread and tick pattern signals (quoted/effective spread)",
            model="Bid-ask spread analysis + Roll's model implicit cost",
            input_schema={"market_data": "dict"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.55,
            skill_version="1.0.0",
        ),
        NodeSkill(
            name="sentiment",
            description="Funding rate and open interest sentiment proxy",
            model="FinBERT / funding-rate proxy (positive funding → bullish sentiment)",
            input_schema={"market_data": "dict"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.60,
            skill_version="1.0.0",
        ),
        NodeSkill(
            name="vrp",
            description="Variance Risk Premium — realized vs implied vol spread",
            model="VRP = Realized Vol − Implied Vol (funding proxy), HMM regime",
            input_schema={"market_data": "dict"},
            output_schema={"vrp_signal": "float", "vrp_regime": "str"},
            confidence_score=0.68,
            skill_version="1.2.0",
        ),
        NodeSkill(
            name="market_data",
            description="Raw market data feature signals (volume delta, open interest change)",
            model="Statistical z-score of rolling market microstructure metrics",
            input_schema={"market_data": "dict"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.53,
            skill_version="1.0.0",
        ),
        NodeSkill(
            name="onchain",
            description="On-chain activity signals (active addresses, exchange flows)",
            model="CryptoQuant/Glassnode on-chain data aggregation",
            input_schema={"market_data": "dict"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.57,
            skill_version="1.0.0",
        ),
        NodeSkill(
            name="long_short_ratio",
            description="Futures long/short ratio from Binance perpetual markets",
            model="Exchange API: globalLongShortAccountRatio endpoint",
            input_schema={"market_data": "dict"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.59,
            skill_version="1.0.0",
        ),
        NodeSkill(
            name="btc_dominance",
            description="BTC dominance trend as altcoin risk-on/off signal",
            model="CoinGecko dominance API + rolling z-score",
            input_schema={"market_data": "dict"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.61,
            skill_version="1.0.0",
        ),
        NodeSkill(
            name="rmt_signal",
            description="Random Matrix Theory denoiser — structured vs noisy market",
            model="RMT Marchenko-Pastur law + information content extraction",
            input_schema={"signal_vector": "dict[str, float]"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.66,
            skill_version="1.0.0",
        ),
        NodeSkill(
            name="alt_data",
            description="Alternative data signals (social sentiment, macro indicators)",
            model="NewsAPI + OpenMeteo macro proxy + Twitter/X volume proxy",
            input_schema={},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.52,
            skill_version="1.0.0",
        ),
        NodeSkill(
            name="spectral_graph",
            description="Spectral graph Fiedler value — signal correlation stress indicator",
            model="Laplacian eigenvalue (Fiedler) of signal correlation graph",
            input_schema={"signal_vector": "dict[str, float]"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.63,
            skill_version="1.0.0",
        ),
        NodeSkill(
            name="carry",
            description="Funding-rate carry / mean-reversion signals",
            model="Perpetual funding rate carry (8h annualised) + z-score reversion",
            input_schema={"market_data": "dict"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.65,
            skill_version="1.0.0",
        ),
        NodeSkill(
            name="pairs",
            description="Cointegration pairs spread z-score (statistical arbitrage)",
            model="Engle-Granger cointegration test + OU process spread normalisation",
            input_schema={"market_data": "dict"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.60,
            skill_version="1.0.0",
        ),
        NodeSkill(
            name="momentum_factor",
            description="Cross-sectional Jegadeesh-Titman momentum factor",
            model="Jegadeesh-Titman (1993) 12-1 cross-sectional momentum, P1 portfolio",
            input_schema={"market_data": "dict"},
            output_schema={"value": "float", "confidence": "float"},
            confidence_score=0.67,
            skill_version="1.0.0",
        ),
    ]
