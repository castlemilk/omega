"""
omega.core.meta_harness
~~~~~~~~~~~~~~~~~~~~~~~
Meta-Harness — strategy-optimization loop sitting above the trading strategy.

Architecture inspired by Yoonho Lee's Stanford research on self-improvement
loops (Meta-Harness). Implements the 3-step Propose → Evaluate → Store loop
at the strategy configuration level (NOT the trading decision level).

The key insight from the research: textual feedback (rationale) is a richer
gradient signal than scalar metrics alone. Each proposal carries a "why"
that feeds back into subsequent proposals — Feedback Descent.

Flow::
    MetaHarness.run_iteration()
        → MetaProposer.propose()
            → heuristic shortlist of candidate changes (numpy)
            → LLM writes rationale + ranks (if OMEGA_META_LLM=1)
        → MetaEvaluator.evaluate()
            → runs N paper-trading cycles
            → computes composite score
        → StrategyFileSystem.save()
            → persists snapshot, trades, metrics, rationale
        → MetaHarness._apply_or_revert()
            → if improved: apply change live
            → if 3 consecutive regressions: revert to best known

Environment:
    OMEGA_META_LLM=1    — enable LLM-powered rationale (default: off)
    OMEGA_META_LLM_PROVIDER — brain provider (default: "anthropic")
"""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("omega.core.meta_harness")

_BASE_DIR = Path("data/meta_harness")

# ---------------------------------------------------------------------------
# Composite score weights (must sum to 1.0)
# ---------------------------------------------------------------------------
_W_SHARPE = 0.30
_W_DRAWDOWN = 0.20       # scored as (1 - abs(max_drawdown))
_W_HIT_RATE = 0.20
_W_PROFIT_FACTOR = 0.15
_W_LONG_RATIO = 0.15     # penalises all-short / all-long bias


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass
class StrategyIteration:
    """Represents one iteration of the meta-harness loop."""

    iteration_id: int
    parent_id: Optional[int]                      # None for seed iteration
    changes_description: str                       # textual WHY
    code_diff: str                                 # what changed (param diff)
    metrics: dict[str, float]                      # sharpe, drawdown, hit_rate, …
    trade_log_path: str                            # path to full trades.csv
    score: float                                   # composite score
    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StrategyIteration":
        return cls(
            iteration_id=int(d["iteration_id"]),
            parent_id=d.get("parent_id"),
            changes_description=str(d.get("changes_description", "")),
            code_diff=str(d.get("code_diff", "")),
            metrics={k: float(v) for k, v in d.get("metrics", {}).items()},
            trade_log_path=str(d.get("trade_log_path", "")),
            score=float(d.get("score", 0.0)),
            timestamp=str(d.get("timestamp", datetime.now(UTC).isoformat())),
        )

    def metrics_summary(self) -> str:
        m = self.metrics
        return (
            f"sharpe={m.get('sharpe', 0):.3f}  "
            f"dd={m.get('drawdown', 0):.3f}  "
            f"hit={m.get('hit_rate', 0):.2%}  "
            f"pf={m.get('profit_factor', 0):.2f}  "
            f"score={self.score:.4f}"
        )


@dataclass
class StrategyProposal:
    """A proposed change to the strategy configuration."""

    category: str     # "signal_weight" | "conviction" | "risk" | "signal_toggle" | "regime"
    param_path: str   # dotted param key e.g. "dynamic_weights.ema_alpha"
    old_value: Any
    new_value: Any
    rationale: str    # textual WHY (from heuristic or LLM)
    confidence: float  # 0–1


def compute_score(metrics: dict[str, float]) -> float:
    """
    Compute composite score from a metrics dict.

    Components:
        - sharpe: higher is better (normalised to ~[0,1] assuming max sharpe ~3)
        - drawdown: lower magnitude is better (score = 1 - abs(dd))
        - hit_rate: already in [0,1]
        - profit_factor: bounded at 3 then normalised
        - long_ratio: penalises extreme bias (want ~0.4–0.6 longs)
    """
    sharpe = float(metrics.get("sharpe", 0.0))
    drawdown = float(metrics.get("drawdown", 0.0))
    hit_rate = float(metrics.get("hit_rate", 0.0))
    profit_factor = float(metrics.get("profit_factor", 1.0))
    long_ratio = float(metrics.get("long_ratio", 0.5))
    trade_count = int(metrics.get("trade_count", 0))

    # Normalise sharpe to ~[0,1]; cap at 3 before normalising
    sharpe_norm = min(max(sharpe, 0.0), 3.0) / 3.0

    # Drawdown score: perfect=1 (no drawdown), worst=0 (100% drawdown)
    dd_score = max(0.0, 1.0 - abs(drawdown))

    # Profit factor: cap at 3, normalise
    pf_norm = min(max(profit_factor, 0.0), 3.0) / 3.0

    # Long ratio penalty: want 0.4–0.6 ratio; score=1 at 0.5, drops toward 0 at 0 or 1
    # Using a tent function centred at 0.5
    long_score = max(0.0, 1.0 - abs(long_ratio - 0.5) * 4.0)

    # Zero-trade penalty: very low score if no trades
    if trade_count == 0:
        return 0.0

    score = (
        _W_SHARPE * sharpe_norm
        + _W_DRAWDOWN * dd_score
        + _W_HIT_RATE * hit_rate
        + _W_PROFIT_FACTOR * pf_norm
        + _W_LONG_RATIO * long_score
    )
    return round(float(score), 6)


# ---------------------------------------------------------------------------
# StrategyFileSystem
# ---------------------------------------------------------------------------


class StrategyFileSystem:
    """
    Manages persistent iteration history on disk.

    Layout::
        data/meta_harness/
            index.json           ← list of all iterations (light metadata)
            iter_001/
                strategy_snapshot.json   ← frozen param snapshot
                trades.csv               ← trade log
                metrics.json             ← computed metrics
                rationale.md             ← textual rationale
            iter_002/
                ...
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = base_dir or _BASE_DIR
        self._base.mkdir(parents=True, exist_ok=True)
        self._index_path = self._base / "index.json"
        self._index: list[dict[str, Any]] = []
        self._load_index()

    # ------------------------------------------------------------------ I/O

    def _load_index(self) -> None:
        if self._index_path.exists():
            try:
                self._index = json.loads(self._index_path.read_text())
            except Exception as exc:
                logger.warning("Failed to load meta-harness index: %s", exc)
                self._index = []

    def _save_index(self) -> None:
        self._index_path.write_text(json.dumps(self._index, indent=2))

    def _iter_dir(self, iteration_id: int) -> Path:
        return self._base / f"iter_{iteration_id:03d}"

    # ------------------------------------------------------------------ Public API

    def save(
        self,
        iteration: StrategyIteration,
        strategy_snapshot: dict[str, Any],
        trades: list[dict[str, Any]],
    ) -> Path:
        """
        Persist an iteration to disk.

        Returns the iteration directory path.
        """
        d = self._iter_dir(iteration.iteration_id)
        d.mkdir(parents=True, exist_ok=True)

        # Strategy snapshot (frozen param copy)
        (d / "strategy_snapshot.json").write_text(
            json.dumps(strategy_snapshot, indent=2, default=str)
        )

        # Trades CSV
        trades_path = d / "trades.csv"
        if trades:
            fieldnames = list(trades[0].keys())
            with open(trades_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(trades)
        else:
            trades_path.write_text("no_trades\n")

        # Metrics JSON
        (d / "metrics.json").write_text(
            json.dumps(iteration.metrics, indent=2)
        )

        # Rationale markdown
        rationale_md = f"# Iteration {iteration.iteration_id} Rationale\n\n"
        rationale_md += f"**Score:** {iteration.score:.4f}\n\n"
        rationale_md += f"**Parent:** {iteration.parent_id}\n\n"
        rationale_md += f"**Timestamp:** {iteration.timestamp}\n\n"
        rationale_md += f"## Why This Change\n\n{iteration.changes_description}\n\n"
        rationale_md += f"## What Changed\n\n```\n{iteration.code_diff}\n```\n\n"
        rationale_md += f"## Metrics\n\n{iteration.metrics_summary()}\n"
        (d / "rationale.md").write_text(rationale_md)

        # Update index
        entry = {
            "iteration_id": iteration.iteration_id,
            "parent_id": iteration.parent_id,
            "score": iteration.score,
            "timestamp": iteration.timestamp,
            "metrics": iteration.metrics,
        }
        # Replace or append
        existing_ids = [e["iteration_id"] for e in self._index]
        if iteration.iteration_id in existing_ids:
            idx = existing_ids.index(iteration.iteration_id)
            self._index[idx] = entry
        else:
            self._index.append(entry)
        self._save_index()

        # Update the canonical trade_log_path on the iteration
        iteration.trade_log_path = str(trades_path)

        logger.info(
            "Saved iteration %d → %s  (score=%.4f)",
            iteration.iteration_id, d, iteration.score,
        )
        return d

    def get_full_history(self) -> list[StrategyIteration]:
        """
        Return ALL iterations in chronological order (not summarised).

        Raw history is critical per the research — never return a summary here.
        """
        iterations = []
        for entry in sorted(self._index, key=lambda e: e["iteration_id"]):
            iter_dir = self._iter_dir(entry["iteration_id"])
            rationale_path = iter_dir / "rationale.md"
            diff_text = ""
            description = ""
            if rationale_path.exists():
                text = rationale_path.read_text()
                # Extract sections
                for line in text.splitlines():
                    if line.startswith("## Why"):
                        pass  # marker found, next non-header lines are description
                if "## Why This Change\n\n" in text:
                    description = text.split("## Why This Change\n\n")[1].split("\n\n")[0]
                if "## What Changed\n\n```\n" in text:
                    diff_text = text.split("## What Changed\n\n```\n")[1].split("\n```")[0]

            trades_path = iter_dir / "trades.csv"
            iterations.append(
                StrategyIteration(
                    iteration_id=entry["iteration_id"],
                    parent_id=entry.get("parent_id"),
                    changes_description=description,
                    code_diff=diff_text,
                    metrics=entry.get("metrics", {}),
                    trade_log_path=str(trades_path),
                    score=float(entry.get("score", 0.0)),
                    timestamp=str(entry.get("timestamp", "")),
                )
            )
        return iterations

    def get_best_iteration(self) -> Optional[StrategyIteration]:
        """Return the iteration with the highest composite score."""
        if not self._index:
            return None
        best_entry = max(self._index, key=lambda e: float(e.get("score", 0.0)))
        history = self.get_full_history()
        for it in history:
            if it.iteration_id == best_entry["iteration_id"]:
                return it
        return None

    def get_recent_regressions(self, n: int = 5) -> list[StrategyIteration]:
        """
        Find the N most recent iterations where score dropped vs parent.
        Returns them with their rationale describing why the regression happened.
        """
        history = self.get_full_history()
        score_map = {it.iteration_id: it.score for it in history}
        regressions = []
        for it in reversed(history):
            if it.parent_id is not None:
                parent_score = score_map.get(it.parent_id, 0.0)
                if it.score < parent_score:
                    regressions.append(it)
            if len(regressions) >= n:
                break
        return regressions

    def load_snapshot(self, iteration_id: int) -> dict[str, Any]:
        """Load the strategy_snapshot.json for a given iteration."""
        path = self._iter_dir(iteration_id) / "strategy_snapshot.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def next_iteration_id(self) -> int:
        """Return the next available iteration ID (1-based)."""
        if not self._index:
            return 1
        return max(e["iteration_id"] for e in self._index) + 1


# ---------------------------------------------------------------------------
# MetaProposer — hybrid heuristic + optional LLM
# ---------------------------------------------------------------------------

# Candidate change types
_CATEGORIES = [
    "signal_weight",
    "conviction",
    "risk",
    "signal_toggle",
    "regime",
]

# Known tunable params and their bounds/options
_PARAM_SPACE: dict[str, dict[str, Any]] = {
    "dynamic_weights.ema_alpha": {"min": 0.1, "max": 0.6, "step": 0.05},
    "dynamic_weights.max_single_weight": {"min": 0.25, "max": 0.55, "step": 0.05},
    "strategy.conviction_threshold_buy": {"min": 0.1, "max": 0.5, "step": 0.05},
    "strategy.conviction_threshold_strong_buy": {"min": 0.4, "max": 0.8, "step": 0.05},
    "strategy.base_position_size": {"min": 0.02, "max": 0.10, "step": 0.01},
    "strategy.vol_low_threshold": {"min": 0.05, "max": 0.35, "step": 0.02},
    "strategy.vol_high_threshold": {"min": 0.4, "max": 0.9, "step": 0.05},
    "risk.stop_loss_pct": {"min": 0.01, "max": 0.05, "step": 0.005},
    "risk.take_profit_pct": {"min": 0.02, "max": 0.10, "step": 0.01},
}


class MetaProposer:
    """
    Proposes the next strategy variant.

    Hybrid approach:
    1. Heuristics shortlist candidate changes (numpy, free, fast)
    2. LLM writes rationale + ranks candidates (if OMEGA_META_LLM=1)

    The proposal isolates ONE change at a time per the isolation principle.
    """

    def __init__(
        self,
        fs: StrategyFileSystem,
        feedback_descent: Any | None = None,  # FeedbackDescent instance
        use_llm: bool | None = None,
    ) -> None:
        self._fs = fs
        self._fd = feedback_descent
        if use_llm is None:
            use_llm = os.environ.get("OMEGA_META_LLM", "0") == "1"
        self._use_llm = use_llm
        self._brain: Any | None = None
        if self._use_llm:
            self._brain = self._init_brain()

    def _init_brain(self) -> Any:
        """Initialise the LLM brain adapter."""
        try:
            from omega.core.brain import AnthropicBrain, BrainConfig, NoBrain
            provider = os.environ.get("OMEGA_META_LLM_PROVIDER", "anthropic")
            if provider == "anthropic":
                cfg = BrainConfig(provider="anthropic", max_tokens=2048, temperature=0.3)
                brain = AnthropicBrain(cfg)
                if brain.is_available():
                    logger.info("MetaProposer: LLM enabled (Anthropic)")
                    return brain
                logger.warning("MetaProposer: Anthropic not available, falling back to heuristic")
            return NoBrain()
        except Exception as exc:
            logger.warning("MetaProposer: brain init failed (%s), heuristic only", exc)
            return None

    def propose(
        self,
        current_snapshot: dict[str, Any],
    ) -> StrategyProposal:
        """
        Propose ONE change to the strategy configuration.

        Returns a StrategyProposal with rationale.
        """
        history = self._fs.get_full_history()
        candidates = self._heuristic_shortlist(history, current_snapshot)

        if not candidates:
            candidates = [self._random_candidate(current_snapshot)]

        if self._use_llm and self._brain is not None:
            return self._llm_rank_and_rationale(candidates, history, current_snapshot)

        # Heuristic-only: pick highest-confidence candidate, generate template rationale
        best = max(candidates, key=lambda c: c.confidence)
        best.rationale = self._heuristic_rationale(best, history)
        return best

    # ------------------------------------------------------------------ Heuristic

    def _heuristic_shortlist(
        self,
        history: list[StrategyIteration],
        snapshot: dict[str, Any],
    ) -> list[StrategyProposal]:
        """
        Use numpy to identify candidate changes.

        Strategies:
        - If recent regressions: propose reverting the last change
        - If low hit_rate: nudge conviction threshold down (be less selective)
        - If low sharpe: adjust signal weights toward higher-IC signals
        - If long/short imbalance: tune conviction direction bias
        - If no data: explore randomly
        """
        if len(history) < 2:
            return [self._explore_candidate(snapshot)]

        recent = history[-5:]
        scores = np.array([it.score for it in recent])
        trend = np.polyfit(range(len(scores)), scores, 1)[0] if len(scores) > 1 else 0.0

        candidates: list[StrategyProposal] = []

        # Pattern 1: Declining trend → propose reverting conviction threshold
        if trend < -0.01 and len(history) >= 3:
            last = history[-1]
            hit_rate = last.metrics.get("hit_rate", 0.5)
            if hit_rate < 0.45:
                candidates.append(StrategyProposal(
                    category="conviction",
                    param_path="strategy.conviction_threshold_buy",
                    old_value=snapshot.get("strategy", {}).get("conviction_threshold_buy", 0.2),
                    new_value=round(
                        float(snapshot.get("strategy", {}).get("conviction_threshold_buy", 0.2))
                        - 0.05,
                        3,
                    ),
                    rationale="",  # filled by LLM or heuristic_rationale
                    confidence=0.7,
                ))

        # Pattern 2: Long/short imbalance
        long_ratios = [it.metrics.get("long_ratio", 0.5) for it in recent]
        avg_long_ratio = float(np.mean(long_ratios)) if long_ratios else 0.5
        if avg_long_ratio < 0.3:
            candidates.append(StrategyProposal(
                category="conviction",
                param_path="strategy.conviction_threshold_buy",
                old_value=snapshot.get("strategy", {}).get("conviction_threshold_buy", 0.2),
                new_value=round(
                    float(snapshot.get("strategy", {}).get("conviction_threshold_buy", 0.2))
                    - 0.03,
                    3,
                ),
                rationale="",
                confidence=0.65,
            ))

        # Pattern 3: High drawdown → tighten stop loss
        drawdowns = [abs(it.metrics.get("drawdown", 0.0)) for it in recent]
        avg_dd = float(np.mean(drawdowns)) if drawdowns else 0.0
        if avg_dd > 0.05:
            current_sl = float(snapshot.get("risk", {}).get("stop_loss_pct", 0.02))
            tighter = round(max(current_sl - 0.005, 0.01), 3)
            candidates.append(StrategyProposal(
                category="risk",
                param_path="risk.stop_loss_pct",
                old_value=current_sl,
                new_value=tighter,
                rationale="",
                confidence=0.60,
            ))

        # Pattern 4: Low profit factor → widen signal weight range
        pfs = [it.metrics.get("profit_factor", 1.0) for it in recent]
        avg_pf = float(np.mean(pfs)) if pfs else 1.0
        if avg_pf < 1.2:
            current_alpha = float(snapshot.get("dynamic_weights", {}).get("ema_alpha", 0.3))
            candidates.append(StrategyProposal(
                category="signal_weight",
                param_path="dynamic_weights.ema_alpha",
                old_value=current_alpha,
                new_value=round(min(current_alpha + 0.05, 0.6), 2),
                rationale="",
                confidence=0.55,
            ))

        # Pattern 5: Positive trend → amplify by nudging current best param
        if trend > 0.005:
            candidates.append(self._amplify_candidate(history, snapshot))

        return [c for c in candidates if c is not None]

    def _explore_candidate(self, snapshot: dict[str, Any]) -> StrategyProposal:
        """Generate a random exploratory proposal (used when history is sparse)."""
        rng = np.random.default_rng()
        param = rng.choice(list(_PARAM_SPACE.keys()))
        bounds = _PARAM_SPACE[param]
        new_val = round(
            float(rng.uniform(bounds["min"], bounds["max"])),
            3,
        )
        parts = param.split(".")
        section, key = parts[0], parts[1]
        old_val = snapshot.get(section, {}).get(key, (bounds["min"] + bounds["max"]) / 2)
        return StrategyProposal(
            category=self._param_to_category(param),
            param_path=param,
            old_value=old_val,
            new_value=new_val,
            rationale="",
            confidence=0.3,
        )

    def _random_candidate(self, snapshot: dict[str, Any]) -> StrategyProposal:
        return self._explore_candidate(snapshot)

    def _amplify_candidate(
        self,
        history: list[StrategyIteration],
        snapshot: dict[str, Any],
    ) -> StrategyProposal:
        """If score is improving, push the most recent change further."""
        last = history[-1]
        code_diff = last.code_diff
        # Try to detect which param was last changed from the diff
        for param in _PARAM_SPACE:
            if param.split(".")[-1] in code_diff:
                bounds = _PARAM_SPACE[param]
                parts = param.split(".")
                section, key = parts[0], parts[1]
                current = float(snapshot.get(section, {}).get(key, bounds["min"]))
                new_val = round(min(current + bounds["step"], bounds["max"]), 3)
                return StrategyProposal(
                    category=self._param_to_category(param),
                    param_path=param,
                    old_value=current,
                    new_value=new_val,
                    rationale="",
                    confidence=0.6,
                )
        return self._explore_candidate(snapshot)

    def _param_to_category(self, param_path: str) -> str:
        section = param_path.split(".")[0]
        return {
            "dynamic_weights": "signal_weight",
            "strategy": "conviction",
            "risk": "risk",
        }.get(section, "signal_weight")

    def _heuristic_rationale(
        self,
        proposal: StrategyProposal,
        history: list[StrategyIteration],
    ) -> str:
        recent_regressions = self._fs.get_recent_regressions(n=3)
        regression_context = ""
        if recent_regressions:
            regression_context = (
                f"Recent regressions detected in iterations "
                f"{[r.iteration_id for r in recent_regressions]}. "
            )

        trend_context = ""
        if len(history) >= 3:
            recent_scores = [it.score for it in history[-3:]]
            trend = "improving" if recent_scores[-1] > recent_scores[0] else "declining"
            trend_context = f"Score trend over last 3 iterations: {trend}. "

        return (
            f"[Heuristic] {regression_context}{trend_context}"
            f"Proposing to adjust {proposal.param_path} from {proposal.old_value} "
            f"to {proposal.new_value} based on pattern analysis. "
            f"Category: {proposal.category}. Confidence: {proposal.confidence:.2f}."
        )

    # ------------------------------------------------------------------ LLM

    def _llm_rank_and_rationale(
        self,
        candidates: list[StrategyProposal],
        history: list[StrategyIteration],
        snapshot: dict[str, Any],
    ) -> StrategyProposal:
        """Send candidates to LLM for ranking and rationale generation."""
        from omega.core.brain import ModelTier

        feedback_summary = ""
        if self._fd is not None:
            feedback_summary = self._fd.summarize_for_llm(recent_n=10)

        history_summary = self._format_history_for_llm(history[-10:])

        candidates_text = "\n".join(
            f"{i+1}. [{c.category}] {c.param_path}: {c.old_value} → {c.new_value} "
            f"(heuristic conf={c.confidence:.2f})"
            for i, c in enumerate(candidates)
        )

        prompt = f"""You are the MetaProposer for a cryptocurrency trading system (Victoria).
Your role: analyze strategy iteration history and select the BEST single parameter change.

## Current Strategy Snapshot
{json.dumps(snapshot, indent=2, default=str)}

## Iteration History (most recent last)
{history_summary}

## Feedback Descent Summary
{feedback_summary}

## Candidate Changes (heuristic shortlist)
{candidates_text}

## Instructions
1. Select the candidate most likely to improve the composite score.
2. Write a clear 2-3 sentence rationale explaining WHY this change will help,
   grounded in the historical evidence above.
3. If none of the candidates look promising, propose a different change.

Respond with ONLY valid JSON (no markdown fences):
{{
  "selected_index": <1-based index or 0 for new proposal>,
  "category": "<category>",
  "param_path": "<param_path>",
  "old_value": <old>,
  "new_value": <new>,
  "rationale": "<2-3 sentence rationale>",
  "confidence": <0.0-1.0>
}}"""

        try:
            response_text = self._brain.consult(prompt, tier=ModelTier.DEEP)
            if not response_text:
                raise ValueError("Empty LLM response")

            # Strip markdown fences if present
            text = response_text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            parsed = json.loads(text.strip())

            idx = int(parsed.get("selected_index", 1)) - 1
            if 0 <= idx < len(candidates):
                candidate = candidates[idx]
                candidate.rationale = str(parsed.get("rationale", ""))
                candidate.confidence = float(parsed.get("confidence", candidate.confidence))
                return candidate

            # LLM proposed a new change
            return StrategyProposal(
                category=str(parsed.get("category", "signal_weight")),
                param_path=str(parsed.get("param_path", "")),
                old_value=parsed.get("old_value"),
                new_value=parsed.get("new_value"),
                rationale=str(parsed.get("rationale", "")),
                confidence=float(parsed.get("confidence", 0.5)),
            )

        except Exception as exc:
            logger.warning("LLM ranking failed (%s), using heuristic best", exc)
            best = max(candidates, key=lambda c: c.confidence)
            best.rationale = self._heuristic_rationale(best, history)
            return best

    def _format_history_for_llm(self, history: list[StrategyIteration]) -> str:
        lines = []
        for it in history:
            lines.append(
                f"Iter {it.iteration_id} (parent={it.parent_id}): "
                f"score={it.score:.4f}  {it.metrics_summary()}\n"
                f"  Change: {it.changes_description[:200]}"
            )
        return "\n".join(lines) if lines else "No history yet."


# ---------------------------------------------------------------------------
# MetaEvaluator
# ---------------------------------------------------------------------------


class MetaEvaluator:
    """
    Scores a proposed strategy by running N paper-trading cycles and
    computing the composite metric.

    In test/simulation mode (no live VictoriaNode), generates synthetic
    metrics based on the proposal parameters.
    """

    def __init__(self, n_eval_cycles: int = 50, live: bool = True) -> None:
        self._n_eval_cycles = n_eval_cycles
        self._live = live

    def evaluate(
        self,
        proposal: StrategyProposal,
        parent_iteration: Optional[StrategyIteration],
        current_snapshot: dict[str, Any],
        iteration_id: int,
    ) -> tuple[StrategyIteration, list[dict[str, Any]]]:
        """
        Apply the proposal, run evaluation cycles, compute metrics.

        Returns:
            (StrategyIteration, trades_list)
        """
        new_snapshot = self._apply_proposal_to_snapshot(proposal, current_snapshot)

        if self._live:
            metrics, trades = self._run_live_evaluation(new_snapshot, proposal)
        else:
            metrics, trades = self._synthetic_evaluation(proposal, parent_iteration)

        score = compute_score(metrics)

        diff_text = (
            f"{proposal.param_path}: {proposal.old_value!r} → {proposal.new_value!r}"
        )

        iteration = StrategyIteration(
            iteration_id=iteration_id,
            parent_id=parent_iteration.iteration_id if parent_iteration else None,
            changes_description=proposal.rationale,
            code_diff=diff_text,
            metrics=metrics,
            trade_log_path="",  # filled by StrategyFileSystem.save()
            score=score,
        )
        return iteration, trades

    def _apply_proposal_to_snapshot(
        self,
        proposal: StrategyProposal,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Return a new snapshot with the proposal applied."""
        import copy
        new = copy.deepcopy(snapshot)
        parts = proposal.param_path.split(".")
        if len(parts) == 2:
            section, key = parts
            if section not in new:
                new[section] = {}
            new[section][key] = proposal.new_value
        return new

    def _run_live_evaluation(
        self,
        snapshot: dict[str, Any],
        proposal: StrategyProposal,
    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
        """
        Run actual paper trading with the proposed configuration.

        Imports VictoriaNode and PaperTradingEngine lazily to avoid
        circular imports in test environments.
        """
        try:
            from omega.core.orchestrator_v2 import OmegaOrchestrator
            from omega.core.paper_trading import PaperTradingEngine
            from omega.nodes.victoria.victoria_node import VictoriaNode

            victoria = VictoriaNode()
            # Apply snapshot params to the node where possible
            self._apply_snapshot_to_node(victoria, snapshot)

            engine = PaperTradingEngine(initial_capital=100_000.0)
            orch = OmegaOrchestrator(name="meta_eval")
            orch.register_node(victoria)
            orch.set_paper_trading(engine)

            for _ in range(self._n_eval_cycles):
                orch.run_one_cycle()
                time.sleep(0.1)  # minimal sleep in eval mode

            return self._compute_metrics_from_engine(engine), list(engine.closed_trades)

        except Exception as exc:
            logger.warning("Live evaluation failed (%s), using synthetic metrics", exc)
            return self._synthetic_evaluation(proposal, None)

    def _apply_snapshot_to_node(self, victoria: Any, snapshot: dict[str, Any]) -> None:
        """Best-effort application of snapshot params to a live VictoriaNode."""
        try:
            strat = getattr(victoria, "_strategy", None)
            if strat is not None:
                strat_params = snapshot.get("strategy", {})
                for k, v in strat_params.items():
                    if hasattr(strat, f"_{k}"):
                        setattr(strat, f"_{k}", v)

            dw = getattr(victoria, "_dynamic_weights", None)
            if dw is not None:
                dw_params = snapshot.get("dynamic_weights", {})
                for k, v in dw_params.items():
                    if hasattr(dw, f"_{k}"):
                        setattr(dw, f"_{k}", v)
        except Exception as exc:
            logger.debug("Could not apply snapshot to node: %s", exc)

    def _compute_metrics_from_engine(
        self, engine: Any
    ) -> dict[str, float]:
        """Extract standardised metrics from a PaperTradingEngine."""
        trades = list(engine.closed_trades)
        if not trades:
            return {
                "sharpe": 0.0, "drawdown": 0.0, "hit_rate": 0.0,
                "pnl": 0.0, "profit_factor": 0.0, "trade_count": 0,
                "long_ratio": 0.5,
            }

        pnls = [float(t.get("pnl", 0.0)) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))

        pnl_arr = np.array(pnls)
        sharpe = (
            float(np.mean(pnl_arr) / (np.std(pnl_arr) + 1e-8) * np.sqrt(252))
            if len(pnl_arr) > 1 else 0.0
        )

        # Drawdown: peak-to-trough on cumulative PnL
        cum = np.cumsum(pnl_arr)
        peak = np.maximum.accumulate(cum)
        dd_series = (cum - peak) / (np.abs(peak) + 1e-8)
        max_dd = float(np.min(dd_series))

        longs = sum(1 for t in trades if t.get("side") == "long")
        long_ratio = longs / len(trades) if trades else 0.5

        return {
            "sharpe": round(sharpe, 4),
            "drawdown": round(max_dd, 4),
            "hit_rate": round(len(wins) / len(trades), 4),
            "pnl": round(sum(pnls), 4),
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else 0.0,
            "trade_count": len(trades),
            "long_ratio": round(long_ratio, 4),
        }

    def _synthetic_evaluation(
        self,
        proposal: StrategyProposal,
        parent: Optional[StrategyIteration],
    ) -> tuple[dict[str, float], list[dict[str, Any]]]:
        """
        Synthetic evaluation for testing/CI — generates plausible metrics
        based on the proposal without running live trading.
        """
        rng = np.random.default_rng(
            hash(f"{proposal.param_path}{proposal.new_value}") % (2**32)
        )

        # Base metrics from parent, or defaults
        if parent is not None:
            base_sharpe = parent.metrics.get("sharpe", 1.0)
            base_hit = parent.metrics.get("hit_rate", 0.5)
        else:
            base_sharpe = 1.0
            base_hit = 0.50

        # Small random delta centred on slight improvement
        delta = float(rng.normal(0.02, 0.15))
        metrics = {
            "sharpe": round(max(0.0, base_sharpe + delta), 4),
            "drawdown": round(float(-rng.uniform(0.01, 0.08)), 4),
            "hit_rate": round(float(np.clip(base_hit + rng.normal(0.01, 0.05), 0.2, 0.8)), 4),
            "pnl": round(float(rng.normal(500, 2000)), 2),
            "profit_factor": round(float(max(0.5, rng.normal(1.4, 0.4))), 4),
            "trade_count": int(rng.integers(10, 60)),
            "long_ratio": round(float(np.clip(rng.normal(0.5, 0.15), 0.1, 0.9)), 4),
        }
        return metrics, []


# ---------------------------------------------------------------------------
# MetaHarness — orchestrates the loop
# ---------------------------------------------------------------------------


class MetaHarness:
    """
    Orchestrates the Propose → Evaluate → Store self-improvement loop.

    After each iteration:
    - If score improved: apply change to live strategy
    - If 3 consecutive regressions: revert to best known iteration

    All activity logged to data/meta_harness/harness.log.
    """

    _MAX_CONSECUTIVE_REGRESSIONS = 3

    def __init__(
        self,
        n_eval_cycles: int = 50,
        live: bool = False,
        use_llm: bool | None = None,
        base_dir: Path | None = None,
    ) -> None:
        from omega.core.feedback_descent import FeedbackDescent

        self._base = base_dir or _BASE_DIR
        self._base.mkdir(parents=True, exist_ok=True)
        self._fs = StrategyFileSystem(self._base)
        self._fd = FeedbackDescent(self._base)
        self._proposer = MetaProposer(self._fs, self._fd, use_llm=use_llm)
        self._evaluator = MetaEvaluator(n_eval_cycles=n_eval_cycles, live=live)

        self._consecutive_regressions = 0
        self._current_snapshot: dict[str, Any] = self._load_or_init_snapshot()

        # Set up file logger
        log_path = self._base / "harness.log"
        fh = logging.FileHandler(log_path, mode="a")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)

    def _load_or_init_snapshot(self) -> dict[str, Any]:
        """Load best known snapshot or return a default."""
        best = self._fs.get_best_iteration()
        if best is not None:
            snapshot = self._fs.load_snapshot(best.iteration_id)
            if snapshot:
                logger.info("Loaded snapshot from best iteration %d", best.iteration_id)
                return snapshot
        return self._default_snapshot()

    @staticmethod
    def _default_snapshot() -> dict[str, Any]:
        return {
            "dynamic_weights": {
                "ema_alpha": 0.3,
                "max_single_weight": 0.40,
            },
            "strategy": {
                "conviction_threshold_buy": 0.20,
                "conviction_threshold_strong_buy": 0.60,
                "base_position_size": 0.05,
                "vol_low_threshold": 0.15,
                "vol_high_threshold": 0.70,
            },
            "risk": {
                "stop_loss_pct": 0.02,
                "take_profit_pct": 0.05,
            },
        }

    def run_iteration(self) -> StrategyIteration:
        """
        Run one full Propose → Evaluate → Store cycle.

        Returns the resulting StrategyIteration.
        """
        iteration_id = self._fs.next_iteration_id()
        parent = self._fs.get_best_iteration() if self._fs._index else None
        parent_score = parent.score if parent else 0.0

        logger.info("=== Meta-Harness Iteration %d ===", iteration_id)

        # PROPOSE
        proposal = self._proposer.propose(self._current_snapshot)
        logger.info(
            "Proposal: [%s] %s: %s → %s  (conf=%.2f)",
            proposal.category, proposal.param_path,
            proposal.old_value, proposal.new_value, proposal.confidence,
        )

        # EVALUATE
        iteration, trades = self._evaluator.evaluate(
            proposal, parent, self._current_snapshot, iteration_id
        )
        logger.info("Evaluated iter %d: %s", iteration_id, iteration.metrics_summary())

        # STORE
        new_snapshot = self._evaluator._apply_proposal_to_snapshot(
            proposal, self._current_snapshot
        )
        self._fs.save(iteration, new_snapshot, trades)

        # Record feedback
        metrics_delta = {
            k: iteration.metrics.get(k, 0.0) - (parent.metrics.get(k, 0.0) if parent else 0.0)
            for k in iteration.metrics
        }
        metrics_delta["score"] = iteration.score - parent_score
        self._fd.record_feedback(
            iteration_id=iteration_id,
            feedback_text=proposal.rationale,
            metrics_delta=metrics_delta,
            tags=[proposal.category],
        )

        # APPLY OR REVERT
        improved = iteration.score > parent_score
        if improved:
            self._current_snapshot = new_snapshot
            self._consecutive_regressions = 0
            logger.info(
                "Iteration %d IMPROVED score %.4f → %.4f. Applying change.",
                iteration_id, parent_score, iteration.score,
            )
        else:
            self._consecutive_regressions += 1
            logger.info(
                "Iteration %d REGRESSED score %.4f → %.4f (consecutive=%d).",
                iteration_id, parent_score, iteration.score,
                self._consecutive_regressions,
            )
            if self._consecutive_regressions >= self._MAX_CONSECUTIVE_REGRESSIONS:
                self._revert_to_best()

        return iteration

    def run_loop(self, n_iterations: int) -> list[StrategyIteration]:
        """
        Run N full iterations of the meta-harness loop.

        Returns list of all StrategyIterations produced.
        """
        results = []
        for i in range(n_iterations):
            logger.info("Loop %d/%d", i + 1, n_iterations)
            try:
                iteration = self.run_iteration()
                results.append(iteration)
            except Exception as exc:
                logger.error("Iteration %d failed: %s", i + 1, exc, exc_info=True)
        return results

    def _revert_to_best(self) -> None:
        """Revert current snapshot to the best known iteration."""
        best = self._fs.get_best_iteration()
        if best is None:
            logger.warning("Cannot revert — no best iteration found")
            return
        snapshot = self._fs.load_snapshot(best.iteration_id)
        if snapshot:
            self._current_snapshot = snapshot
            self._consecutive_regressions = 0
            logger.info(
                "REVERTED to best iteration %d (score=%.4f)",
                best.iteration_id, best.score,
            )
        else:
            logger.warning("Could not load snapshot for iteration %d", best.iteration_id)

    def get_status(self) -> dict[str, Any]:
        """Return a status dict for logging/monitoring."""
        best = self._fs.get_best_iteration()
        history = self._fs.get_full_history()
        return {
            "total_iterations": len(history),
            "best_iteration_id": best.iteration_id if best else None,
            "best_score": best.score if best else 0.0,
            "consecutive_regressions": self._consecutive_regressions,
            "llm_enabled": self._proposer._use_llm,
            "current_snapshot": self._current_snapshot,
        }
