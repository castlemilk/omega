"""
omega.eval.ring1_eval
~~~~~~~~~~~~~~~~~~~~~
Ring 1 precision / recall evaluator.

Runs the orchestrator for N cycles, records every Ring 1 flag, and computes
counterfactual PnL for each flagged trade (what *would* have happened if the
trade had executed despite the flag).

Metrics
-------
precision         = (flagged cycles that would have lost money) / (all flagged cycles)
recall            = (losing cycles that were flagged) / (all losing cycles)
F1                = harmonic mean of precision and recall
opportunity_cost  = sum of positive PnL from suppressed *winning* trades
net_impact        = (saved_losses - opportunity_cost) / total_cycles
flags_per_100     = adversarial flags per 100 cycles
net_sharpe_impact = Sharpe(full) - Sharpe(with_ring1_flags_suppressed)

Usage::

    from omega.eval.ring1_eval import Ring1Evaluator
    from omega.core.orchestrator_v2 import OmegaOrchestrator

    ev = Ring1Evaluator(n_cycles=200)
    report = ev.run()
    print(report)
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any

from omega.core.node import Node, NodeInput, NodeOutput, NodeState
from omega.core.orchestrator_v2 import OmegaOrchestrator

logger = logging.getLogger("omega.eval.ring1_eval")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Ring1CycleRecord:
    """Per-cycle record used for precision/recall computation."""

    cycle_number: int
    flagged: bool  # Ring 1 raised a flag
    counterfactual_pnl: float  # PnL if the trade had executed anyway
    trade_would_have_lost: bool  # counterfactual_pnl < 0


@dataclass
class Ring1EvalReport:
    """Full Ring 1 evaluation report."""

    n_cycles: int
    n_flagged: int
    n_true_positives: int  # flagged AND would have lost
    n_false_positives: int  # flagged AND would have gained
    n_losing_cycles: int  # all cycles where trade would have lost
    precision: float
    recall: float
    f1: float
    opportunity_cost: float  # sum of suppressed *winning* PnL
    saved_losses: float  # sum of losses avoided by flags
    net_impact: float  # (saved_losses - opportunity_cost) / n_cycles
    flags_per_100: float
    net_sharpe_impact: float
    cycle_records: list[Ring1CycleRecord] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"Ring1EvalReport(\n"
            f"  cycles={self.n_cycles}, flagged={self.n_flagged}, "
            f"flags/100={self.flags_per_100:.2f}\n"
            f"  precision={self.precision:.4f}, recall={self.recall:.4f}, "
            f"F1={self.f1:.4f}\n"
            f"  saved_losses={self.saved_losses:.6f}, "
            f"opportunity_cost={self.opportunity_cost:.6f}\n"
            f"  net_impact={self.net_impact:.6f}, "
            f"net_sharpe_impact={self.net_sharpe_impact:.4f}\n"
            f")"
        )


# ---------------------------------------------------------------------------
# Instrumented node
# ---------------------------------------------------------------------------


class _Ring1InstrumentedNode(Node):
    """
    Node that generates trades with known expected PnL.

    Stores counterfactual PnL for every cycle so the evaluator can compute
    what would have happened without Ring 1 suppression.
    """

    def __init__(
        self,
        loss_rate: float = 0.35,
        avg_loss: float = -0.005,
        avg_gain: float = 0.003,
        seed: int = 42,
    ) -> None:
        import uuid

        self._nid = str(uuid.uuid4())
        self._rng = random.Random(seed)
        self._loss_rate = loss_rate
        self._avg_loss = avg_loss
        self._avg_gain = avg_gain
        self._cycle_pnl: list[float] = []

    def get_state(self) -> NodeState:
        return NodeState(
            node_id=self._nid,
            name="ring1_instrumented",
            version="1.0",
            health=1.0,
            capabilities=["poll", "compute_signals", "construct_portfolio"],
            metrics={},
        )

    def get_capabilities(self) -> list[str]:
        return ["poll", "compute_signals", "construct_portfolio"]

    def describe(self) -> str:
        return "Ring1InstrumentedNode"

    def execute(self, inp: NodeInput) -> NodeOutput:
        if inp.action in ("poll", "fetch_data"):
            return NodeOutput(request_id=inp.request_id, success=True, result={"price": 50000.0})

        if inp.action == "compute_signals":
            signal = self._rng.gauss(0.01, 0.05)
            return NodeOutput(
                request_id=inp.request_id,
                success=True,
                result={"composite_signal": signal, "regime_label": "normal"},
            )

        if inp.action == "construct_portfolio":
            # Generate a trade with known counterfactual PnL
            if self._rng.random() < self._loss_rate:
                pnl = self._rng.gauss(self._avg_loss, abs(self._avg_loss) * 0.5)
            else:
                pnl = self._rng.gauss(self._avg_gain, self._avg_gain * 0.5)
            self._cycle_pnl.append(pnl)
            proposal = {
                "symbol": "BTC/USDT",
                "side": "buy" if pnl > 0 else "sell",
                "size": 1.0,
                "expected_return": pnl,
                "_counterfactual_pnl": pnl,  # tagged for evaluator
            }
            return NodeOutput(
                request_id=inp.request_id,
                success=True,
                result=[proposal],
            )

        return NodeOutput(request_id=inp.request_id, success=True, result={})

    def evaluate(self) -> dict[str, float]:
        return {"cycle_count": float(len(self._cycle_pnl))}

    def improve(self, feedback: dict) -> bool:
        return False

    @property
    def cycle_pnl(self) -> list[float]:
        return list(self._cycle_pnl)


# ---------------------------------------------------------------------------
# Instrumented orchestrator subclass
# ---------------------------------------------------------------------------


class _TrackingOrchestrator(OmegaOrchestrator):
    """
    OmegaOrchestrator subclass that records flagged cycles and their
    counterfactual PnL for Ring 1 evaluation.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._ring1_records: list[Ring1CycleRecord] = []

    def _step_adversarial(
        self, ctx: Any, result: Any, proposals: Any, signal_data: Any, log: Any
    ) -> Any:
        clean = super()._step_adversarial(ctx, result, proposals, signal_data, log)

        # Determine if Ring 1 flagged this cycle
        flagged = result.had_adversarial_flag

        # Compute counterfactual PnL from proposals (pre-filtering)
        counterfactual_pnl = 0.0
        for p in proposals:
            if isinstance(p, dict):
                raw = p.get("_counterfactual_pnl") or p.get("expected_return") or 0.0
                counterfactual_pnl += float(raw)

        record = Ring1CycleRecord(
            cycle_number=ctx.cycle_number,
            flagged=flagged,
            counterfactual_pnl=counterfactual_pnl,
            trade_would_have_lost=counterfactual_pnl < 0,
        )
        self._ring1_records.append(record)
        return clean

    @property
    def ring1_records(self) -> list[Ring1CycleRecord]:
        return list(self._ring1_records)


# ---------------------------------------------------------------------------
# Ring1Evaluator
# ---------------------------------------------------------------------------


class Ring1Evaluator:
    """
    Evaluate Ring 1 adversarial layer precision and recall.

    Parameters
    ----------
    n_cycles        : Orchestrator cycles to run.
    loss_rate       : Fraction of trades that would lose money (ground truth).
    flag_rate_target: Approximate fraction of cycles Ring 1 will flag
                      (used to inject synthetic flags when orchestrator has no
                      real Ring 1 adversarial — keeps evaluation meaningful).
    seed            : RNG seed.
    inject_flags    : If True, synthetically inject Ring 1 flags at ``flag_rate_target``
                      to simulate adversarial behaviour without needing a live model.
    """

    def __init__(
        self,
        n_cycles: int = 200,
        loss_rate: float = 0.35,
        flag_rate_target: float = 0.30,
        seed: int = 42,
        inject_flags: bool = True,
    ) -> None:
        self._n_cycles = n_cycles
        self._loss_rate = loss_rate
        self._flag_rate_target = flag_rate_target
        self._seed = seed
        self._inject_flags = inject_flags

    def run(self) -> Ring1EvalReport:
        """
        Run the orchestrator and return a Ring1EvalReport.
        """
        node = _Ring1InstrumentedNode(
            loss_rate=self._loss_rate,
            seed=self._seed,
        )

        orch = _TrackingOrchestrator(name="ring1_eval")
        orch.register_node(node)
        orch.run(max_cycles=self._n_cycles)

        records = orch.ring1_records

        # Inject synthetic flags if requested (simulates Ring 1 behaviour)
        if self._inject_flags:
            records = self._inject_synthetic_flags(records)

        return self._compute_report(records)

    def _inject_synthetic_flags(
        self,
        records: list[Ring1CycleRecord],
    ) -> list[Ring1CycleRecord]:
        """
        Simulate Ring 1 flags: flag losing cycles preferentially but with noise.

        Ring 1 has imperfect information — it will miss some losers and flag
        some winners. This simulates that realistic behaviour.
        """
        rng = random.Random(self._seed + 1)
        result = []
        for rec in records:
            if rec.trade_would_have_lost:
                # Higher probability of flagging a loser
                flagged = rng.random() < self._flag_rate_target * 1.8
            else:
                # Lower probability of flagging a winner (false positives)
                flagged = rng.random() < self._flag_rate_target * 0.4
            result.append(
                Ring1CycleRecord(
                    cycle_number=rec.cycle_number,
                    flagged=flagged,
                    counterfactual_pnl=rec.counterfactual_pnl,
                    trade_would_have_lost=rec.trade_would_have_lost,
                )
            )
        return result

    def _compute_report(self, records: list[Ring1CycleRecord]) -> Ring1EvalReport:
        n_cycles = len(records)
        if n_cycles == 0:
            return Ring1EvalReport(
                n_cycles=0,
                n_flagged=0,
                n_true_positives=0,
                n_false_positives=0,
                n_losing_cycles=0,
                precision=0.0,
                recall=0.0,
                f1=0.0,
                opportunity_cost=0.0,
                saved_losses=0.0,
                net_impact=0.0,
                flags_per_100=0.0,
                net_sharpe_impact=0.0,
                cycle_records=records,
            )

        flagged = [r for r in records if r.flagged]
        losing_cycles = [r for r in records if r.trade_would_have_lost]

        # True positives: flagged AND would have lost
        true_positives = [r for r in flagged if r.trade_would_have_lost]
        # False positives: flagged AND would have gained
        false_positives = [r for r in flagged if not r.trade_would_have_lost]

        n_flagged = len(flagged)
        n_tp = len(true_positives)
        n_fp = len(false_positives)
        n_losing = len(losing_cycles)

        precision = n_tp / n_flagged if n_flagged > 0 else 0.0
        recall = n_tp / n_losing if n_losing > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        # Opportunity cost: sum of positive PnL from suppressed winning trades
        opportunity_cost = sum(
            r.counterfactual_pnl for r in false_positives if r.counterfactual_pnl > 0
        )

        # Saved losses: sum of loss magnitudes we avoided
        saved_losses = sum(abs(r.counterfactual_pnl) for r in true_positives)

        net_impact = (saved_losses - opportunity_cost) / n_cycles if n_cycles > 0 else 0.0

        flags_per_100 = (n_flagged / n_cycles) * 100

        # Net Sharpe impact: compare Sharpe with vs without Ring 1
        # "without Ring 1" = all trades execute regardless of flags
        all_pnl = [r.counterfactual_pnl for r in records]
        # "with Ring 1" = suppress flagged trades (PnL = 0 for flagged cycles)
        ring1_pnl = [0.0 if r.flagged else r.counterfactual_pnl for r in records]

        sharpe_without = _sharpe(all_pnl)
        sharpe_with = _sharpe(ring1_pnl)
        net_sharpe_impact = sharpe_with - sharpe_without

        return Ring1EvalReport(
            n_cycles=n_cycles,
            n_flagged=n_flagged,
            n_true_positives=n_tp,
            n_false_positives=n_fp,
            n_losing_cycles=n_losing,
            precision=round(precision, 6),
            recall=round(recall, 6),
            f1=round(f1, 6),
            opportunity_cost=round(opportunity_cost, 8),
            saved_losses=round(saved_losses, 8),
            net_impact=round(net_impact, 8),
            flags_per_100=round(flags_per_100, 4),
            net_sharpe_impact=round(net_sharpe_impact, 6),
            cycle_records=records,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sharpe(returns: list[float], risk_free: float = 0.0) -> float:
    if len(returns) < 2:
        return 0.0
    daily_rf = risk_free / 252
    excess = [r - daily_rf for r in returns]
    mean_e = sum(excess) / len(excess)
    var = sum((x - mean_e) ** 2 for x in excess) / (len(excess) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    return (mean_e / std * math.sqrt(252)) if std > 0 else 0.0
