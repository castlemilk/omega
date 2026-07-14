"""
omega.live_paper.runner
~~~~~~~~~~~~~~~~~~~~~~~~~
V252 — the thin daily cycle loop that composes scheduler + checkpoint + a
pluggable *cycle function*. Pure runner-layer; imports NO strategy module.

The runner is deliberately ignorant of *what* a cycle computes. It owns only:

  boot   → load latest checkpoint (or clean-start defaults)
  loop   → wait for the scheduler tick
         → build a CycleContext from the prior checkpoint state
         → call the injected cycle_fn(ctx) -> CycleResult
         → persist a new checkpoint (atomic)
         → append one strictly-monotonic PnL log line
  stop   → gracefully after the current cycle when SIGTERM arrives

Three cycle functions plug into this same loop (none touch strategy code):

- ``make_fixture_cycle`` — deterministic pure function of (prior state, date);
  used by the V252 smoke tests to isolate scheduler-timing (Test A) and
  crash-recovery byte-identity (Test B) from any network/strategy variance.
- ``make_retrospective_cycle`` — replays a frozen walk-forward *window* through
  the **unchanged** ``run_training.py --backtest-snapshot`` eval and returns its
  per-window PnL; used by Test C to prove the runner preserves V251's bit-exact
  reconciliation (the runner adds nothing to the eval computation).
- The production **forward** cycle (live V250 feeds → signals → StrategyNode →
  PaperTradingEngine) is wired by ``scripts/live_paper_daemon.sh`` for the V253
  soak; it is non-deterministic by design (real clock + network) and is NOT
  exercised by the V252 smoke (which must be deterministic).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from omega.live_paper.checkpoint import Checkpoint, CheckpointState
from omega.live_paper.scheduler import DailyScheduler, TickInfo

logger = logging.getLogger("omega.live_paper.runner")

# V253 forward-cycle deterministic hold window. PaperTradingEngine randomizes exit
# age in [_EXIT_CYCLES_MIN, _EXIT_CYCLES_MAX]; the backtest pins both to a fixed
# hold (backtest.py `_BT_HOLD_CYCLES`) so results are reproducible. The forward
# entry wire pins the same way so a cycle is idempotent: identical feeds + prior
# state ⇒ identical positions / realised PnL (only cosmetic trade_id/ts differ).
_FORWARD_HOLD_CYCLES = 5


@dataclass
class CycleContext:
    """Everything a cycle function needs: prior state + the tick that fired it."""

    cycle_date: date
    cycle_ts: str  # ISO-8601 UTC instant the tick fired (from TickInfo)
    prior: CheckpointState | None  # None on the very first (clean-start) cycle
    initial_capital: float


@dataclass
class CycleResult:
    """What a cycle function returns — folded into the next checkpoint + PnL line."""

    equity: float
    realised_pnl: float
    open_positions: list[dict[str, Any]] = field(default_factory=list)
    closed_trades: list[dict[str, Any]] = field(default_factory=list)
    signals_state: dict[str, Any] = field(default_factory=dict)
    seed_state: dict[str, Any] = field(default_factory=dict)
    unrealised_pnl: float = 0.0
    extra_log: dict[str, Any] = field(default_factory=dict)


CycleFn = Callable[[CycleContext], CycleResult]


class LivePaperRunner:
    """Composes DailyScheduler + Checkpoint + a cycle function into a daemon loop."""

    def __init__(
        self,
        scheduler: DailyScheduler,
        checkpoint: Checkpoint,
        cycle_fn: CycleFn,
        *,
        initial_capital: float = 100_000.0,
        pnl_log_path: Path,
        install_signals: bool = True,
    ) -> None:
        self.scheduler = scheduler
        self.checkpoint = checkpoint
        self.cycle_fn = cycle_fn
        self.initial_capital = initial_capital
        self.pnl_log_path = Path(pnl_log_path)
        if install_signals:
            self.scheduler.install_signal_handlers()
        self._last_logged_ts: str | None = None

    # ── boot ─────────────────────────────────────────────────────────────────────

    def _boot(self) -> CheckpointState | None:
        """Load the latest checkpoint (crash-recovery), or None for a clean start.

        A corrupt checkpoint raises :class:`CheckpointCorruption` out of here — the
        daemon must not silently continue on corrupt state.
        """
        state = self.checkpoint.load()
        if state is None:
            logger.info(json.dumps({"event": "runner_clean_start", "capital": self.initial_capital}))
        else:
            logger.info(
                json.dumps(
                    {
                        "event": "runner_resumed",
                        "from_date": state.last_completed_date,
                        "equity": state.equity,
                        "open_positions": len(state.open_positions),
                    }
                )
            )
        # Seed monotonic PnL-log guard from the last logged line, if any.
        self._last_logged_ts = self._tail_pnl_ts()
        # Crash-atomicity reconciliation: the checkpoint is authoritative and is
        # written BEFORE the PnL line is appended. If we crashed in that window,
        # the latest checkpoint carries a `pnl_record` newer than the log's tail —
        # replay it now so the log has no gap AND no duplicate (the monotonic
        # guard blocks a re-append if it already landed).
        if state is not None and state.pnl_record:
            rec_ts = state.pnl_record.get("cycle_ts")
            if rec_ts and (self._last_logged_ts is None or rec_ts > self._last_logged_ts):
                self._write_pnl_line(state.pnl_record)
                logger.info(json.dumps({"event": "pnl_log_reconciled", "cycle_ts": rec_ts}))
        return state

    def _tail_pnl_ts(self) -> str | None:
        if not self.pnl_log_path.is_file():
            return None
        last = None
        for line in self.pnl_log_path.read_text().splitlines():
            line = line.strip()
            if line:
                last = line
        if last is None:
            return None
        try:
            return json.loads(last)["cycle_ts"]
        except (json.JSONDecodeError, KeyError):
            return None

    # ── one cycle ─────────────────────────────────────────────────────────────────

    def _run_one(self, tick: TickInfo, prior: CheckpointState | None) -> CheckpointState:
        ctx = CycleContext(
            cycle_date=tick.cycle_date,
            cycle_ts=tick.fired_utc.isoformat(),
            prior=prior,
            initial_capital=self.initial_capital,
        )
        result = self.cycle_fn(ctx)
        pnl_record = {
            "cycle_ts": ctx.cycle_ts,
            "cycle_date": tick.cycle_date.isoformat(),
            "equity": result.equity,
            "realised_pnl": result.realised_pnl,
            "unrealised_pnl": result.unrealised_pnl,
            "open_n": len(result.open_positions),
            "drift_seconds": round(tick.drift_seconds, 3),
            **result.extra_log,
        }
        state = CheckpointState(
            cycle_ts=ctx.cycle_ts,
            cycle_date=tick.cycle_date.isoformat(),
            last_completed_date=tick.cycle_date.isoformat(),
            equity=result.equity,
            realised_pnl=result.realised_pnl,
            open_positions=result.open_positions,
            closed_trades=result.closed_trades,
            signals_state=result.signals_state,
            seed_state=result.seed_state,
            pnl_record=pnl_record,
        )
        # Persist the checkpoint (AUTHORITATIVE) BEFORE appending the PnL line. A
        # crash in between is recovered on boot from the checkpoint's `pnl_record`
        # (see _boot) — no missing and no duplicate line either way.
        self.checkpoint.save(state)
        self._write_pnl_line(pnl_record)
        return state

    def _write_pnl_line(self, record: dict[str, Any]) -> None:
        cycle_ts = record["cycle_ts"]
        # Strict monotonicity guard (falsifier: PnL log must be monotonic on cycle_ts).
        if self._last_logged_ts is not None and cycle_ts <= self._last_logged_ts:
            raise RuntimeError(
                f"non-monotonic PnL log: cycle_ts {cycle_ts} <= last {self._last_logged_ts}"
            )
        self.pnl_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.pnl_log_path, "a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        self._last_logged_ts = cycle_ts

    # ── loop ─────────────────────────────────────────────────────────────────────

    def run(self, *, max_cycles: int | None = None) -> int:
        """Run the daemon loop. Returns the number of cycles completed.

        ``max_cycles`` bounds the loop (tests / burn-in); ``None`` = run until a
        shutdown signal. Idempotency + crash-recovery are driven purely by the
        checkpoint's ``last_completed_date`` — nothing else carries state.
        """
        state = self._boot()
        completed = 0
        while max_cycles is None or completed < max_cycles:
            last_done = state.completed_date if state is not None else None
            tick = self.scheduler.wait_next(last_done)
            if tick is None:  # graceful shutdown before a tick fired
                logger.info(json.dumps({"event": "runner_shutdown", "cycles": completed}))
                break
            state = self._run_one(tick, state)
            completed += 1
            if self.scheduler.shutdown_requested:
                logger.info(json.dumps({"event": "runner_shutdown", "cycles": completed}))
                break
        return completed


# ── cycle functions ────────────────────────────────────────────────────────────


def make_fixture_cycle(*, step: float = 100.0) -> CycleFn:
    """A deterministic cycle: equity evolves as a pure function of (prior, date).

    Used to isolate the scheduler + checkpoint infra in the V252 smoke tests. The
    per-cycle PnL is a stable hash of the cycle date so that a clean run and a
    crash-then-resume run over the same dates are byte-identical — exactly the
    property Test B asserts. No network, no strategy, no wall-clock dependence.
    """
    import hashlib

    def _cycle(ctx: CycleContext) -> CycleResult:
        prior_equity = ctx.prior.equity if ctx.prior is not None else ctx.initial_capital
        prior_realised = ctx.prior.realised_pnl if ctx.prior is not None else 0.0
        # Deterministic signed daily PnL in [-step, +step) from the date hash.
        h = int(hashlib.sha256(ctx.cycle_date.isoformat().encode()).hexdigest(), 16)
        daily = ((h % 20001) - 10000) / 10000.0 * step  # [-step, +step)
        equity = round(prior_equity + daily, 2)
        realised = round(prior_realised + daily, 2)
        # A single deterministic "position" so open_positions round-trips through
        # the checkpoint and the crash-recovery byte-match covers non-empty state.
        pos = [{"symbol": "ETHUSDT", "side": "long" if daily >= 0 else "short",
                "size": round(abs(daily) * 10, 2), "entry": round(3000 + daily, 2)}]
        return CycleResult(
            equity=equity,
            realised_pnl=realised,
            open_positions=pos,
            signals_state={"last_date": ctx.cycle_date.isoformat()},
            seed_state={"h": h % 1_000_000},
            unrealised_pnl=0.0,
            extra_log={"daily_pnl": round(daily, 2)},
        )

    return _cycle


def make_retrospective_cycle(
    *,
    window_snapshot: Path,
    cycles: int,
    features_json: str,
    repo_root: Path,
    python: str | None = None,
) -> CycleFn:
    """Replay ONE frozen window through the unchanged ``run_training.py`` eval.

    Byte-exact by construction: the runner shells out to the same backtest entry
    V251 used, so the per-window PnL is identical to V251's recorded number. The
    runner contributes only orchestration (when + persist + log), never a single
    line of the strategy computation. Used by Test C.
    """
    py = python or sys.executable

    def _cycle(ctx: CycleContext) -> CycleResult:
        version = f"v252_replay_{ctx.cycle_date.isoformat()}"
        results_path = _run_backtest_eval(
            py, repo_root, version, window_snapshot, cycles, features_json
        )
        results = json.loads(results_path.read_text())
        trades = results.get("trades", {})  # PnL lives under results["trades"] (V251 parity)
        pnl = float(trades.get("total_pnl_usd", 0.0))
        n_closed = int(trades.get("total_closed", 0))
        prior_equity = ctx.prior.equity if ctx.prior is not None else ctx.initial_capital
        return CycleResult(
            equity=round(prior_equity + pnl, 2),
            realised_pnl=round(pnl, 2),
            closed_trades=[{"n_closed": n_closed}],
            seed_state={"window": window_snapshot.name},
            extra_log={"window_pnl": round(pnl, 2), "n_closed": n_closed, "snapshot": window_snapshot.name},
        )

    return _cycle


def make_forward_cycle(cfg: Any) -> CycleFn:
    """Production live-paper cycle: real V250 feeds → SignalGeneration → StrategyNode
    → PaperTradingEngine → equity. This is the V253 **entry wire**.

    Each daily tick:

      1. Rehydrate a :class:`PaperTradingEngine` from the prior checkpoint's open
         positions / realised PnL / closed-trade ledger.
      2. Fetch the trailing daily-close **window** per universe symbol through the
         V250 live pollers (every fetch passes the ``assert_live_source``
         frozen-path guard). The signal pipeline needs history, so we pass the
         full trailing series ``<= as_of`` — NOT a single close.
      3. Run the SAME per-cycle sequence the backtest loop uses
         (``backtest.py`` L217-268) VERBATIM: ``SignalGenerationNode.execute`` →
         ``StrategyNode.execute`` → build proposals → ``execute_proposals``. The
         nodes read their feature flags from ``VICTORIA_FEATURES`` (identical env
         contract to ``run_training.py``), so live-paper runs whatever standing
         baseline the launch env pins (V240-selective for V253).
      4. Mark-to-market and return updated equity / positions.

    Faithfulness contract (V251): the engine + strategy + signal modules are
    **called, never modified** — this function is the only new code, and it drives
    the same objects the backtest drives. Determinism: exit timing is pinned to
    ``_FORWARD_HOLD_CYCLES`` (mirroring the backtest pin) so a cycle is idempotent
    on ``(feeds, prior state)``. The strategy step reads no wall-clock for sizing
    (V216 bar-time fence); only ``execute_proposals`` stamps cosmetic ``ts``/
    ``trade_id`` from the clock — those don't affect positions or PnL.

    Non-deterministic across days by design (real network) — NOT exercised by the
    deterministic V252 smoke; it drives the V253 live-paper soak. The V251
    reconciliation (backtest byte-identity) is preserved: that path is the
    UNCHANGED ``make_retrospective_cycle`` shell-out, untouched by this wire.
    """
    from omega.core.paper_trading import PaperTradingEngine
    from omega.live_paper import feeds

    def _cycle(ctx: CycleContext) -> CycleResult:
        # Pin exit timing for idempotency (same technique as backtest.py L195-200).
        # Runtime module-constant set — paper_trading.py itself is untouched.
        import omega.core.paper_trading as _pt

        _pt._EXIT_CYCLES_MIN = _FORWARD_HOLD_CYCLES
        _pt._EXIT_CYCLES_MAX = _FORWARD_HOLD_CYCLES

        engine = PaperTradingEngine(initial_capital=ctx.initial_capital)
        prior_positions = ctx.prior.open_positions if ctx.prior is not None else []
        engine._positions = {p["symbol"]: dict(p) for p in prior_positions if p.get("symbol")}
        if ctx.prior is not None:
            engine._realised_pnl = ctx.prior.realised_pnl
            engine._closed_trades = list(ctx.prior.closed_trades)
        cycle_n = int(ctx.prior.seed_state.get("cycle_n", 0) if ctx.prior else 0) + 1
        cid = f"lp_{ctx.cycle_date.isoformat()}"

        # ── (2) Fetch the trailing daily-close WINDOW per symbol ────────────────
        # Pass the full series up to as_of (retrospective correctness) so signal
        # indicators see history. close[-1] is the current mark price for the
        # engine; the earlier bars feed the signal window.
        market_data: dict[str, Any] = {}
        blocked: list[str] = []
        for symbol in cfg.universe:
            res = feeds.fetch_ohlcv(cfg, symbol, ctx.cycle_date)
            series = res.doc["series"] if (res.reachable and res.doc) else None
            if series:
                closes = [series[d] for d in sorted(series) if date.fromisoformat(d) <= ctx.cycle_date]
                if closes:
                    market_data[symbol] = {"close": closes}
                    continue
            blocked.append(symbol)

        # ── (3) Entry path: signals → strategy → proposals (backtest-faithful) ──
        # Strategy modules are imported LAZILY here so the runner module itself
        # stays strategy-free (fixture/retrospective paths never import them).
        proposals: list[dict[str, Any]] = []
        regime = "unknown"
        sig_ok = strat_ok = False
        try:
            from omega.core.actions import NodeAction
            from omega.core.node import NodeInput
            from omega.nodes.victoria.signal_generation import SignalGenerationNode
            from omega.nodes.victoria.strategy import StrategyNode

            sig_out = SignalGenerationNode().execute(
                NodeInput(
                    action=NodeAction.COMPUTE_SIGNALS.value,
                    parameters={"market_data": market_data},
                )
            )
            sig_ok = bool(sig_out.success and sig_out.result)
            if sig_ok:
                signals: dict[str, Any] = sig_out.result
                regime = str(signals.get("_regime", "unknown"))
                strat_out = StrategyNode().execute(
                    NodeInput(
                        action=NodeAction.CONSTRUCT_PORTFOLIO.value,
                        parameters={"signals": signals, "market_data": market_data},
                    )
                )
                strat_ok = bool(strat_out.success and strat_out.result)
                if strat_ok:
                    weights: dict[str, float] = strat_out.result.get("weights", {})
                    conviction: dict[str, float] = strat_out.result.get("conviction_scores", {})
                    proposals = [
                        {"symbol": s, "weight": float(w), "conviction": conviction.get(s, 0.30)}
                        for s, w in weights.items()
                    ]
        except Exception as exc:  # never crash the daemon on a strategy error
            logger.warning(json.dumps({"event": "forward_entry_error", "error": str(exc)}))

        # ── (4) Execute + mark-to-market (either/or, exactly as the backtest) ───
        before_closed = len(engine.closed_trades)
        executed: list[dict[str, Any]] = []
        if proposals:
            executed = engine.execute_proposals(
                proposals, market_data=market_data, cycle_id=cid, current_cycle=cycle_n
            )
        else:
            engine.mark_to_market(market_data, current_cycle=cycle_n, cycle_id=cid)
        closed_this_cycle = len(engine.closed_trades) - before_closed

        unrealised = float(sum(p.get("unrealized_pnl", 0.0) for p in engine.positions.values()))
        equity = round(ctx.initial_capital + engine.realised_pnl + unrealised, 2)
        open_positions = [{"symbol": s, **p} for s, p in engine.positions.items()]
        return CycleResult(
            equity=equity,
            realised_pnl=round(engine.realised_pnl, 2),
            open_positions=open_positions,
            closed_trades=list(engine.closed_trades),
            seed_state={"cycle_n": cycle_n},
            unrealised_pnl=round(unrealised, 2),
            extra_log={
                "proposals_n": len(proposals),
                "fills_opened": len(executed),
                "closed_this_cycle": closed_this_cycle,
                "open_symbols": [p["symbol"] for p in open_positions],
                "trade_symbols": sorted({t.get("symbol", t.get("sym", "")) for t in executed}),
                "regime": regime,
                "signals_ok": sig_ok,
                "strategy_ok": strat_ok,
                "feeds_blocked": blocked,
            },
        )

    return _cycle


def _restore_committed_frozen_state(repo_root: Path) -> None:
    """Restore the committed frozen inputs before a replay (V251 grid discipline).

    Matches ``check_determinism.sh``'s ``restore_state``: re-checkout the committed
    ``macro_cache.db`` + ``signal_ic_history.json`` + ``training_version.txt`` and
    drop the sqlite WAL/SHM sidecars, so a prior run's mutation can't perturb this
    replay's byte-exact output.
    """
    subprocess.run(
        ["git", "checkout", "-q", "--",
         "data/macro_cache.db", "data/signal_ic_history.json", "data/training_version.txt"],
        cwd=str(repo_root), check=False, capture_output=True, text=True,
    )
    for sidecar in ("data/macro_cache.db-wal", "data/macro_cache.db-shm"):
        (repo_root / sidecar).unlink(missing_ok=True)


def _run_backtest_eval(
    python: str,
    repo_root: Path,
    version: str,
    snapshot: Path,
    cycles: int,
    features_json: str,
) -> Path:
    """Invoke ``run_training.py --backtest-snapshot`` and return the results path.

    Byte-for-byte the SAME command V251's reconciliation used (via
    ``check_determinism.sh``): ``PYTHONHASHSEED=42``, ``--seed 42``,
    ``--frozen-cache``, sleep 0, committed frozen state restored first. So its
    output is identical to the frozen arm — the runner adds nothing to the eval.
    """
    import os

    _restore_committed_frozen_state(repo_root)
    audit_dir = Path(os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", str(repo_root / "data")))
    results_path = audit_dir / f"{version}_results.json"
    env = dict(os.environ)
    env.setdefault("PYTHONHASHSEED", "42")
    env.setdefault("DATABASE_URL", "postgres://omega:omega@localhost:5432/omega?sslmode=disable")
    cmd = [
        python,
        str(repo_root / "scripts" / "run_training.py"),
        "--version", version,
        "--cycles", str(cycles),
        "--sleep", "0",
        "--seed", "42",
        "--backtest-snapshot", str(snapshot),
        "--frozen-cache",
        "--features", features_json,
    ]
    logger.info(json.dumps({"event": "retrospective_eval", "cmd": " ".join(cmd[3:])}))
    subprocess.run(cmd, cwd=str(repo_root), check=True, capture_output=True, text=True, env=env)
    return results_path
