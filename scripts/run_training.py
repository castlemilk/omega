#!/usr/bin/env python3
"""
scripts/run_training.py
~~~~~~~~~~~~~~~~~~~~~~~
Canonical Victoria training script — replaces all versioned run_vN.py scripts.

Incorporates all fixes from V14:
  - Meta-model regularization (n_estimators=50, min_samples_leaf=10, max_features='sqrt')
  - Semantic memory SQLite fallback
  - IMPROVEMENT_INTERVAL=10 + auto-register scheduler
  - conviction_distribution included in all _construct_portfolio return paths

Plus four observability/resilience improvements:
  1. Training health watchdog  — escalates after 20/50 zero-trade cycles with
                                 detailed gate-blocking diagnostics
  2. Structured cycle metrics  — one-line JSON per cycle → /tmp/{version}_metrics.jsonl
  3. Startup preflight         — validates DB, exchange, deps before loop starts
  4. Sit-out circuit breaker   — lowers vol_low threshold after 30 consecutive sit-outs

Usage:
    python scripts/run_training.py
    python scripts/run_training.py --version v27 --cycles 500 --sleep 30
    python scripts/run_training.py --cycles 100 --sleep 5 --log-interval 10

Default version is auto-incremented from data/training_version.txt (or "v1").
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from omega.eval.v49_gates import check_v49_gates  # noqa: E402, I001


# ---------------------------------------------------------------------------
# .env loader (must run before any omega imports)
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
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


_load_env()


# ---------------------------------------------------------------------------
# Version management
# ---------------------------------------------------------------------------

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_VERSION_FILE = DATA_DIR / "training_version.txt"


def _resolve_version(requested: str | None) -> str:
    """Return the training version to use, auto-incrementing if not specified."""
    if requested:
        _VERSION_FILE.write_text(requested.strip())
        return requested.strip()
    if _VERSION_FILE.exists():
        prev = _VERSION_FILE.read_text().strip()
        if prev.startswith("v") and prev[1:].isdigit():
            next_v = f"v{int(prev[1:]) + 1}"
            _VERSION_FILE.write_text(next_v)
            return next_v
        return prev
    _VERSION_FILE.write_text("v1")
    return "v1"


def _find_baseline_version(current: str) -> str | None:
    """Find the previous numeric-suffix version with results + trades artifacts."""
    import re as _re

    m = _re.match(r"^(?P<prefix>[^\d]*)(?P<num>\d+)(?P<suffix>.*)$", current)
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


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(version: str) -> logging.Logger:
    log_file = f"/tmp/{version}_training.log"
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    fhandler = logging.FileHandler(log_file, mode="w")
    fhandler.setLevel(logging.INFO)
    fhandler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", "%H:%M:%S")
    )

    log = logging.getLogger(f"training.{version}")
    log.addHandler(handler)
    log.addHandler(fhandler)
    log.setLevel(logging.INFO)
    log.propagate = False
    return log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MAX_STALE_MINUTES = 5.0


def _win_rate(trades: list[dict]) -> float:
    wins = [t for t in trades if float(t.get("pnl", 0.0)) > 0]
    return len(wins) / len(trades) if trades else 0.0


def _total_pnl(trades: list[dict]) -> float:
    return sum(float(t.get("pnl", 0.0)) for t in trades)


def _init_trades_csv(path: Path) -> None:
    with open(path, "w", newline="") as f:
        csv.writer(f).writerow([
            "cycle", "timestamp", "symbol", "side", "size",
            "entry_price", "exit_price", "pnl", "slippage",
            "hold_cycles", "conviction", "regime", "sit_out_reason",
        ])


def _get_data_freshness(victoria) -> float:
    try:
        return victoria._data_ingestion._data_freshness_minutes()
    except Exception:
        return 0.0


def _get_regime(victoria) -> str:
    # Primary: read from last computed signals (set by WassersteinRegimeDetector)
    try:
        regime = (victoria._last_signals or {}).get("_regime")
        if regime and regime not in ("", "unknown"):
            return str(regime)
    except Exception:
        pass
    # Fallback: legacy regime_detector attribute (not present in VictoriaNode)
    try:
        return victoria._regime_detector.current_regime
    except Exception:
        return "unknown"


def _query_semantic_count(data_dir: Path) -> int:
    import sqlite3
    db_path = str(data_dir / "omega_victoria_memory.db")
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT COUNT(*) FROM semantic_memories").fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return -1


def _count_active_signals(signals: dict) -> int:
    """Count non-metadata signal keys that have a dict value with a 'value' field."""
    return sum(
        1 for k, v in signals.items()
        if not k.startswith("_") and isinstance(v, dict) and "value" in v
    )


def _extract_cycle_conviction(signals: dict) -> str:
    """Return the most common conviction level across all signals, or 'n/a'."""
    try:
        from omega.nodes.victoria.strategy import score_to_conviction
        levels: list[str] = []
        for k, v in signals.items():
            if k.startswith("_") or not isinstance(v, dict):
                continue
            score = v.get("composite") if "composite" in v else v.get("value")
            if score is not None:
                levels.append(score_to_conviction(float(score)).name)
        if not levels:
            return "n/a"
        return max(set(levels), key=levels.count)
    except Exception:
        return "n/a"


def _get_composite_score(signals: dict) -> float | None:
    """Mean value across all non-metadata signals."""
    scores = [
        float(v.get("composite", v["value"]))
        for k, v in signals.items()
        if not k.startswith("_") and isinstance(v, dict) and ("composite" in v or "value" in v)
    ]
    return sum(scores) / len(scores) if scores else None


def _get_proposals_stats(strat) -> tuple[int, int]:
    """(proposals_generated, proposals_filtered) from the strategy node."""
    if strat is None:
        return 0, 0
    try:
        return (
            getattr(strat, "_proposals_generated", 0),
            getattr(strat, "_proposals_filtered", 0),
        )
    except Exception:
        return 0, 0


def _get_basket_stats(signals: dict) -> tuple[float, float]:
    """Return (basket_std, basket_mean) excluding adv_* synthetic aggregates (mirrors strategy.py logic)."""
    composites = [
        float(sig["composite"])
        for t, sig in signals.items()
        if not t.startswith("_") and not t.startswith("adv_")
           and isinstance(sig, dict) and "composite" in sig
    ]
    if len(composites) >= 2:
        mean = sum(composites) / len(composites)
        std = math.sqrt(sum((v - mean) ** 2 for v in composites) / len(composites))
        return max(std, 0.010), mean
    return 0.20, 0.0


def _get_active_filters(sit_out_reason: str, proposals_gen: int, proposals_filt: int) -> list[str]:
    """Return list of filter names that fired this cycle."""
    filters: list[str] = []
    if sit_out_reason != "normal":
        filters.append(sit_out_reason)
    if proposals_gen > 0 and proposals_filt > 0:
        filters.append(f"conviction_filter({proposals_filt}/{proposals_gen})")
    elif proposals_gen == 0 and proposals_filt == 0:
        filters.append("no_proposals")
    return filters


# ANSI colour helpers (no external deps)
_R = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOX_W = 54


def _diag_line(label: str, value: str) -> str:
    return f"  {_BOLD}{label:<14}{_R} {value}"


def print_training_diagnostics(victoria, strategy, cycle: int, engine) -> None:
    """Print a colorized diagnostics block — shows regime, data, signals, blockers."""
    sep = "═" * _BOX_W

    print(f"\n{_CYAN}{sep}{_R}")
    print(f"{_CYAN}══ TRAINING DIAGNOSTICS (cycle {cycle}) {'═' * max(0, _BOX_W - 30 - len(str(cycle)))}{_R}")
    print(f"{_CYAN}{sep}{_R}")

    # ── Regime ────────────────────────────────────────────────────────────
    signals_cache: dict = {}
    try:
        signals_cache = getattr(victoria, "_last_signals", {}) or {}
    except Exception:
        pass

    regime_raw = signals_cache.get("_regime") or _get_regime(victoria)
    regime_upper = str(regime_raw).upper()
    if regime_upper in ("UNKNOWN", "UNKN", ""):
        regime_str = f"{_RED}UNKN ⚠️{_R}"
    else:
        conf = 0.0
        try:
            # Wasserstein confidence is stored in _last_signals after each compute cycle
            conf = float(signals_cache.get("_regime_w_confidence", 0.0))
        except Exception:
            pass
        label_colour = _GREEN if regime_upper == "BULL" else (_RED if regime_upper == "BEAR" else _YELLOW)
        regime_str = f"{label_colour}{regime_upper}{_R} (conf: {conf:.2f})"
    print(_diag_line("REGIME:", regime_str))

    # ── Data freshness ────────────────────────────────────────────────────
    freshness = _get_data_freshness(victoria)
    if freshness > MAX_STALE_MINUTES:
        fresh_str = f"{_RED}❌ STALE ({freshness:.1f}min >5min){_R}"
    else:
        fresh_str = f"{_GREEN}✅ {freshness:.1f}min ago{_R}"
    print(_diag_line("DATA FRESH:", fresh_str))

    # ── Active signals ────────────────────────────────────────────────────
    # _last_signals has signal-type keys (basic_signals, order_flow, etc.) each
    # with a "value" field — count those with non-zero value as "active".
    signal_type_dicts = {
        k: v for k, v in signals_cache.items()
        if not k.startswith("_") and isinstance(v, dict) and "value" in v
    }
    active = sum(1 for v in signal_type_dicts.values() if v.get("value") != 0.0)
    total = len(signal_type_dicts)
    sig_str = f"{active}/{total} active" if total > 0 else f"{_YELLOW}none yet{_R}"
    print(_diag_line("SIGNALS:", sig_str))

    # ── Sit-out status ────────────────────────────────────────────────────
    if strategy is not None:
        vol_low = getattr(strategy, "_sit_out_vol_low_count", 0)
        vol_high = getattr(strategy, "_sit_out_vol_high_count", 0)
        regime_out = getattr(strategy, "_sit_out_regime_count", 0)
        if vol_low > 0:
            sit_str = f"{_YELLOW}YES: vol_low (streak: {vol_low}){_R}"
        elif vol_high > 0:
            sit_str = f"{_YELLOW}YES: vol_high (streak: {vol_high}){_R}"
        elif regime_out > 0:
            sit_str = f"{_YELLOW}YES: regime_uncertain (count: {regime_out}){_R}"
        else:
            sit_str = f"{_GREEN}NO{_R}"
    else:
        sit_str = "strategy n/a"
    print(_diag_line("SIT-OUT:", sit_str))

    # ── Per-ticker conviction — read from basic_signals sub-dicts ─────────
    conv_parts: list[str] = []
    basic = signals_cache.get("basic_signals") or {}
    for sym, data in basic.items():
        if not isinstance(data, dict):
            continue
        composite = data.get("composite")
        if composite is None:
            continue
        composite = float(composite)
        ticker = sym.replace("USDT", "").replace("/USDT", "")
        if composite > 0.05:
            direction = f"{_GREEN}BUY{_R}"
        elif composite < -0.05:
            direction = f"{_RED}SELL{_R}"
        else:
            direction = "HOLD"
        conv_parts.append(f"{ticker}: {composite:+.2f} ({direction})")
    conv_str = " | ".join(conv_parts) if conv_parts else f"{_YELLOW}n/a{_R}"
    print(_diag_line("CONVICTION:", conv_str))

    # ── Trade stats ───────────────────────────────────────────────────────
    closed = engine.closed_trades
    open_pos = engine.open_trades
    pnl = _total_pnl(closed)
    wr = _win_rate(closed)
    trade_str = (
        f"open={len(open_pos)} closed={len(closed)} | "
        f"PnL=${pnl:+.2f} | WR={wr * 100:.0f}%"
    )
    print(_diag_line("TRADES:", trade_str))

    # ── Long/short breakdown ──────────────────────────────────────────────
    all_trades = list(closed) + list(open_pos)
    n_longs = sum(1 for t in all_trades if t.get("side") == "long")
    n_shorts = sum(1 for t in all_trades if t.get("side") == "short")
    ls_str = f"longs={n_longs} shorts={n_shorts}"
    if n_longs == 0 and n_shorts >= 3:
        ls_str += f"  {_RED}⚠️  short-only bias{_R}"
    elif n_shorts == 0 and n_longs >= 3:
        ls_str += f"  {_YELLOW}⚠️  long-only — short side suppressed?{_R}"
    print(_diag_line("LONG/SHORT:", ls_str))

    # ── Blockers ──────────────────────────────────────────────────────────
    blockers: list[str] = []
    if regime_upper in ("UNKNOWN", "UNKN", ""):
        blockers.append("Regime detector not firing")
    if strategy is not None and getattr(strategy, "_sit_out_vol_low_count", 0) > 0:
        blockers.append(f"vol_low sit-out (streak {strategy._sit_out_vol_low_count})")
    if freshness > MAX_STALE_MINUTES:
        blockers.append(f"Data freshness >{freshness:.1f}min")
    composites = [
        float(data.get("composite", 0.0))
        for data in basic.values()
        if isinstance(data, dict) and data.get("composite") is not None
    ]
    if composites and all(abs(c) < 0.05 for c in composites):
        blockers.append("No conviction above threshold (all HOLD)")
    if n_longs == 0 and n_shorts >= 3:
        blockers.append("Short-only bias detected — check short_bias fix")
    if total == 0:
        blockers.append("No signal data yet (first cycle?)")

    if blockers:
        blocker_str = f"{_RED}" + " | ".join(blockers) + _R
    else:
        blocker_str = f"{_GREEN}NONE{_R}"
    print(_diag_line("BLOCKERS:", blocker_str))

    print(f"{_CYAN}{sep}{_R}\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Main training loop
# ---------------------------------------------------------------------------

_META_HARNESS_INTERVAL = 50  # run meta-harness every N training cycles


def run_meta_harness_iteration(log: logging.Logger, n_eval_cycles: int = 30) -> None:
    """Run one meta-harness Propose → Evaluate → Store iteration."""
    try:
        from omega.core.meta_harness import MetaHarness
        use_llm = os.environ.get("OMEGA_META_LLM", "0") == "1"
        harness = MetaHarness(n_eval_cycles=n_eval_cycles, live=False, use_llm=use_llm)
        iteration = harness.run_iteration()
        log.info(
            "Meta-harness iter %d complete: score=%.4f  %s",
            iteration.iteration_id,
            iteration.score,
            iteration.metrics_summary(),
        )
    except Exception as exc:
        log.warning("Meta-harness iteration failed: %s", exc)


def run(
    version: str,
    n_cycles: int = 100,
    sleep_seconds: float = 30.0,
    log_interval: int = 5,
    meta_harness: bool = False,
    features: str | None = None,
    backtest_snapshot: str | None = None,
) -> dict:
    log = logging.getLogger(f"training.{version}")

    # ── File paths ────────────────────────────────────────────────────────
    metrics_jsonl = Path(f"/tmp/{version}_metrics.jsonl")
    trades_csv = DATA_DIR / f"{version}_trades.csv"
    progress_file = DATA_DIR / f"{version}_progress.json"
    results_file = DATA_DIR / f"{version}_results.json"
    signal_contribs_jsonl = DATA_DIR / f"{version}_signal_contribs.jsonl"
    trade_details_jsonl = Path(f"/tmp/{version}_trade_details.jsonl")

    db_url = os.environ.get("DATABASE_URL", "")
    cg_key = os.environ.get("CG_API_KEY") or os.environ.get("COINGEKO_API_KEY") or ""

    # ── Feature flags ─────────────────────────────────────────────────────
    from omega.nodes.victoria.features import VictoriaFeatures
    if backtest_snapshot:
        # In backtest mode, WS-dependent features can't run — stub them out.
        # The ReplayIngestionNode serves OHLCV; WS signals degrade to 0.0.
        _WS_FLAGS = {"ws_microstructure", "whale_prints"}
        _bt_features = features or ""
        import json as _json
        try:
            _flag_dict = _json.loads(_bt_features) if _bt_features.startswith("{") else {}
        except Exception:
            _flag_dict = {}
        if isinstance(_flag_dict, dict):
            for _wf in _WS_FLAGS:
                _flag_dict.pop(_wf, None)
            if _flag_dict:
                features = _json.dumps(_flag_dict)
        log.info("BACKTEST MODE: WS signals disabled (%s)", ", ".join(sorted(_WS_FLAGS)))
    if features:
        os.environ["VICTORIA_FEATURES"] = features
    _active_features = VictoriaFeatures.from_env()

    log.info("=" * 70)
    log.info("Training Run %s — %d cycles  sleep=%.0fs", version, n_cycles, sleep_seconds)
    log.info("CoinGecko key  : %s", cg_key[:12] + "..." if cg_key else "MISSING")
    log.info("Database URL   : %s", db_url[:40] + "..." if db_url else "NOT SET — SQLite fallback")
    log.info("Metrics JSONL  : %s", metrics_jsonl)
    log.info("Log file       : /tmp/%s_training.log", version)
    _active_flags = _active_features.active_flags()
    if _active_flags:
        log.info("Features ON    : %s", ", ".join(_active_flags))
    else:
        log.info("Features       : v93_baseline (all OFF)")
    log.info("=" * 70)

    # ── Startup preflight ─────────────────────────────────────────────────
    from omega.core.training_preflight import StartupPreflight
    preflight = StartupPreflight.run()

    # ── Macro cache warm-up ───────────────────────────────────────────────
    # Refresh all stale FRED series once at startup so training cycles read
    # from local SQLite (zero FRED API calls during the training loop).
    try:
        from omega.nodes.victoria.data_cache import MacroDataCache
        _macro_cache = MacroDataCache()
        _macro_cache.warm_up()
    except Exception as _cache_exc:
        log.warning("Macro cache warm-up failed (non-fatal): %s", _cache_exc)

    # ── Node / engine setup ───────────────────────────────────────────────
    from omega.core.orchestrator_v2 import OmegaOrchestrator
    from omega.core.paper_trading import PaperTradingEngine
    from omega.nodes.victoria.victoria_node import VictoriaNode
    from omega.nodes.shared.semantic_memory import SemanticMemoryNode
    from omega.core.improvement_engine import SyntheticEvaluator
    from omega.core.adversarial_v2 import AdversarialPressureV2

    victoria = VictoriaNode()
    victoria._version = version  # V107: propagates to tracer file path + orchestrator attribution log

    # ── Backtest mode: inject ReplayIngestionNode ─────────────────────────
    if backtest_snapshot:
        from omega.nodes.victoria.providers.replay import ReplayIngestionNode, load_snapshot
        _snap = load_snapshot(backtest_snapshot)
        victoria._ingestion = ReplayIngestionNode(_snap, window=30)
        log.info(
            "BACKTEST MODE: ingestion replaced by ReplayIngestionNode (%s, %d steps)",
            _snap.get("_snapshot_id"), victoria._ingestion._total_steps,
        )
    # V86: raise Ring 1 block threshold from 1.0 → 2.0 for training.
    # V85 post-mortem: Ring 1 was blocking ALL trades in normal/recovery regime because
    # max_disagreement (1.0–1.5) exceeded learned_threshold (1.030). In post-crash recovery,
    # signal disagreement is EXPECTED (momentum BUY vs macro/fear SELL) — this is not noise
    # but a genuine market phase divergence. The strategy's own conviction filters
    # (threshold, abs_min, multi-cycle) are the quality gate.
    # Setting ring1_threshold=2.0 means only extreme disagreement (>2x pairwise distance)
    # blocks trades; the typical post-crash 1.0–1.5 range passes through.
    _training_adversarial = AdversarialPressureV2(ring1_threshold=2.0)
    orch = OmegaOrchestrator(name=f"{version}_training", adversarial=_training_adversarial)
    orch.register_node(victoria)
    orch._improvement_engine.set_evaluator(SyntheticEvaluator())
    log.info("ImprovementEngine: SyntheticEvaluator injected")

    sem_node = SemanticMemoryNode(review_interval=10)
    orch.register_node(sem_node, activate=False)

    # V94: strategy normalises weights to sum=1.0, so a single ticker gets weight=1.0.
    # Default per-symbol cap (0.15) and portfolio cap (0.80) block every trade since
    # strategy weight 0.25 (after fiedler) * $100k = $25k > 0.15 * $100k = $15k.
    # Remove paper-trading caps — the strategy's own fiedler/kelly/sit-out risk
    # controls are the quality gate; don't double-cap here.
    engine = PaperTradingEngine(
        initial_capital=100_000.0,
        db_url=db_url or None,
        max_position_per_symbol=1.0,
        max_portfolio_exposure=1.0,
    )
    orch.set_paper_trading(engine)

    _init_trades_csv(trades_csv)

    # ── Watchdog + circuit breaker ────────────────────────────────────────
    from omega.core.training_watchdog import WatchdogState
    from omega.core.sit_out_breaker import SitOutCircuitBreaker

    watchdog = WatchdogState()
    strat = getattr(victoria, "_strategy", None)
    breaker = SitOutCircuitBreaker(strat) if strat is not None else None
    if breaker is None:
        log.warning("Strategy node not found on VictoriaNode — circuit breaker disabled")

    # ── Observability init (gated by feature flags) ───────────────────────
    if strat is not None:
        strat.init_trace_writer(version, str(DATA_DIR))

    # ── Metrics JSONL file (opened once, flushed each cycle) ──────────────
    metrics_jsonl.parent.mkdir(parents=True, exist_ok=True)
    metrics_fh = open(metrics_jsonl, "w")  # noqa: WPS515
    trade_details_fh = open(trade_details_jsonl, "w")  # noqa: WPS515

    # ── Decision snapshot writer ──────────────────────────────────────────
    from omega.core.decision_snapshot import DecisionSnapshot, DecisionWriter
    decision_writer = DecisionWriter(version=version, db_url=db_url or None)
    log.info("Decision snapshots → %s (+ Postgres if configured)", decision_writer.path)

    # ── Heartbeat client ──────────────────────────────────────────────────
    from omega.core.heartbeat_client import HeartbeatClient
    hb_client = HeartbeatClient()
    _hb_node_id = f"victoria_{version}"
    hb_client.report_lifecycle(_hb_node_id, "STARTING", "RUNNING", "training loop started")

    # ── Signal IC decay detector ──────────────────────────────────────────
    try:
        from omega.nodes.victoria.signal_decay import SignalDecayDetector
        _decay_detector: "SignalDecayDetector | None" = SignalDecayDetector()
        _decay_detector.load()
        log.info("SignalDecayDetector: loaded from %s", _decay_detector._path)
    except Exception as _sd_exc:
        log.debug("SignalDecayDetector unavailable (non-fatal): %s", _sd_exc)
        _decay_detector = None

    # ── Loop state ────────────────────────────────────────────────────────
    progress: list[dict] = []
    sit_out_counts: dict[str, int] = {
        "stale_data": 0, "vol_low": 0, "vol_high": 0,
        "regime_uncertain": 0, "normal": 0,
    }
    last_closed_count = 0
    improve_calls = 0
    total_start = time.perf_counter()

    # Pre-loop diagnostic (cycle 0 — before any trades)
    print_training_diagnostics(victoria, strat, 0, engine)

    try:
        for i in range(n_cycles):
            cycle_num = i + 1
            cycle_start = time.perf_counter()
            result = orch.run_one_cycle()
            cycle_elapsed = time.perf_counter() - cycle_start

            if result.improvement_proposed:
                improve_calls += 1

            # Diagnostics every 10 cycles
            if cycle_num % 10 == 0:
                print_training_diagnostics(victoria, strat, cycle_num, engine)

            # Semantic memory consolidation every 10 cycles
            if cycle_num % 10 == 0:
                try:
                    from omega.core.node import NodeInput
                    sem_out = sem_node.execute(NodeInput(
                        action="build_semantic",
                        context={"cycle": cycle_num},
                        parameters={"cycle": cycle_num, "force": False},
                    ))
                    if sem_out.success and sem_out.result:
                        stored = sem_out.result.get("patterns_extracted", 0)
                        if stored > 0:
                            log.info("Cycle %d: SemanticMemoryNode stored %d patterns", cycle_num, stored)
                except Exception as exc:
                    log.warning("SemanticMemoryNode error: %s", exc)

            regime = _get_regime(victoria)
            freshness_min = _get_data_freshness(victoria)

            # ── Determine sit_out_reason via strategy counter deltas ───────
            sit_out_reason = "normal"
            if freshness_min > MAX_STALE_MINUTES:
                sit_out_reason = "stale_data"
                sit_out_counts["stale_data"] += 1
            elif strat is not None:
                vol_low_snap = sit_out_counts.get("_vol_low_snap", 0)
                vol_high_snap = sit_out_counts.get("_vol_high_snap", 0)
                regime_snap = sit_out_counts.get("_regime_snap", 0)

                if strat._sit_out_vol_low_count > vol_low_snap:
                    sit_out_reason = "vol_low"
                elif getattr(strat, "_sit_out_vol_high_count", 0) > vol_high_snap:
                    sit_out_reason = "vol_high"
                elif getattr(strat, "_sit_out_regime_count", 0) > regime_snap:
                    sit_out_reason = "regime_uncertain"

                sit_out_counts["_vol_low_snap"] = strat._sit_out_vol_low_count
                sit_out_counts["_vol_high_snap"] = getattr(strat, "_sit_out_vol_high_count", 0)
                sit_out_counts["_regime_snap"] = getattr(strat, "_sit_out_regime_count", 0)
                sit_out_counts[sit_out_reason] = sit_out_counts.get(sit_out_reason, 0) + 1
            else:
                sit_out_counts["normal"] += 1

            # ── Circuit breaker ───────────────────────────────────────────
            if breaker is not None:
                breaker.record(sit_out_reason)

            # ── Closed trade flush ────────────────────────────────────────
            closed = engine.closed_trades
            new_closed = closed[last_closed_count:]
            if new_closed:
                with open(trades_csv, "a", newline="") as f:
                    w = csv.writer(f)
                    for t in new_closed:
                        w.writerow([
                            cycle_num,
                            datetime.now(UTC).isoformat(),
                            t.get("sym", t.get("symbol", "")),
                            t.get("side", ""),
                            round(float(t.get("size", 0.0)), 4),
                            round(float(t.get("entry", t.get("entry_price", 0.0))), 4),
                            round(float(t.get("exit_price") or 0.0), 4),
                            round(float(t.get("pnl", 0.0)), 4),
                            round(float(t.get("slippage", 0.0)), 6),
                            t.get("hold_cycles", t.get("age_cycles", 0)),
                            t.get("conviction", ""),
                            regime,
                            sit_out_reason,
                        ])
                last_closed_count = len(closed)

            # ── Signal metrics ────────────────────────────────────────────
            last_signals: dict = {}
            try:
                last_signals = getattr(victoria, "_last_signals", {}) or {}
            except Exception:
                pass

            active_signals = _count_active_signals(last_signals)
            composite_score = _get_composite_score(last_signals)
            conviction_str = _extract_cycle_conviction(last_signals)
            proposals_gen, proposals_filt = _get_proposals_stats(strat)

            # ring1_pass: true if any symbol cleared conviction filters
            ring1_pass = proposals_gen > proposals_filt or proposals_gen == 0

            trade_action = (
                "SIT_OUT" if sit_out_reason != "normal"
                else ("TRADE" if new_closed else "HOLD")
            )

            # ── Basket stats (computed once; reused in JSONL + signal contribs) ──
            _basket_std, _basket_mean = _get_basket_stats(last_signals)

            # ── Signal contribution capture ───────────────────────────────
            _ticker_decs: dict = {}
            if new_closed and strat is not None:
                _ticker_decs = getattr(strat, "_last_ticker_decisions", {})
                if _ticker_decs:
                    with open(signal_contribs_jsonl, "a") as _scf:
                        for _trade in new_closed:
                            _sym = _trade.get("sym", _trade.get("symbol", ""))
                            _td = _ticker_decs.get(_sym)
                            if _td is not None:
                                _scf.write(json.dumps({
                                    "cycle": cycle_num,
                                    "ts": datetime.now(UTC).isoformat(),
                                    "symbol": _sym,
                                    "side": _trade.get("side", ""),
                                    "pnl": round(float(_trade.get("pnl", 0.0)), 4),
                                    "basket_std": round(_basket_std, 6),
                                    "basket_mean": round(_basket_mean, 6),
                                    "raw_composite": round(float(_td.raw_composite), 6),
                                    "demeaned_composite": round(float(_td.demeaned_composite), 6),
                                    "conviction": str(_td.conviction),
                                    "conviction_score": round(float(_td.conviction_score), 6),
                                    "filters_applied": list(_td.filters_applied),
                                    "signal_traces": [
                                        {
                                            "name": st.signal_name,
                                            "value": round(float(st.raw_value), 4),
                                            "weight": round(float(st.weight_applied), 4),
                                        }
                                        for st in _td.signal_traces
                                    ],
                                }) + "\n")

            # ── Per-trade signal waterfall → /tmp/{version}_trade_details.jsonl ──
            # Full sub-signal values, ML weights, Kelly scale, filters per closed trade.
            if new_closed:
                _kelly_scale_cur = 1.0
                _ml_weights_snap: dict | None = None
                if strat is not None:
                    try:
                        _kelly_scale_cur = strat._kelly_fraction()
                    except Exception:
                        pass
                    _combiner_obj = getattr(strat, "_combiner", None)
                    if _combiner_obj is not None and getattr(_combiner_obj, "_weights", None) is not None:
                        try:
                            from omega.nodes.victoria.ml_combiner import SIGNAL_KEYS as _SK
                            _ml_weights_snap = {k: round(float(w), 6) for k, w in zip(_SK, _combiner_obj._weights)}
                        except Exception:
                            pass

                for _trade in new_closed:
                    _sym = _trade.get("sym", _trade.get("symbol", ""))
                    _sym_sig: dict = last_signals.get(_sym) or {}
                    _td2 = _ticker_decs.get(_sym)

                    def _sf(key: str) -> "float | None":
                        v = _sym_sig.get(key)
                        return round(float(v), 6) if v is not None else None

                    trade_details_fh.write(json.dumps({
                        "cycle": cycle_num,
                        "ts": datetime.now(UTC).isoformat(),
                        "version": version,
                        "symbol": _sym,
                        "side": _trade.get("side", ""),
                        "pnl": round(float(_trade.get("pnl", 0.0)), 4),
                        "size": round(float(_trade.get("size", 0.0)), 4),
                        "hold_cycles": _trade.get("hold_cycles", _trade.get("age_cycles")),
                        "regime": regime,
                        "signals": {
                            "rsi": _sf("rsi"),
                            "rsi_signal": _sf("rsi_signal"),
                            "macd_crossover": _sf("macd_crossover"),
                            "sma_crossover": _sf("sma_crossover"),
                            "zscore_signal": _sf("zscore_signal"),
                            "volume_signal": _sf("volume_signal"),
                            "bb_signal": _sf("bb_signal"),
                            "vol_regime_signal": _sf("vol_regime_signal"),
                            "btc_beta_signal": _sf("btc_beta_signal"),
                            "funding_rate_signal": _sf("funding_rate_signal"),
                            "fear_greed_signal": _sf("fear_greed_signal"),
                            "dxy_signal": _sf("dxy_signal"),
                        },
                        "composite": _sf("composite"),
                        "raw_composite": _sf("_raw_composite"),
                        "composite_method": _sym_sig.get("composite_method", "equal_weight"),
                        "basket_std": round(_basket_std, 6),
                        "basket_mean": round(_basket_mean, 6),
                        "conviction": str(_td2.conviction) if _td2 else str(_trade.get("conviction", "")),
                        "conviction_score": round(float(_td2.conviction_score), 6) if _td2 else None,
                        "filters_applied": list(_td2.filters_applied) if _td2 else [],
                        "signal_traces": [
                            {"name": st.signal_name, "value": round(float(st.raw_value), 4), "weight": round(float(st.weight_applied), 4)}
                            for st in _td2.signal_traces
                        ] if _td2 else [],
                        "kelly_scale": round(_kelly_scale_cur, 4),
                        "fiedler_scale": round(getattr(strat, "_last_fiedler_scale", 1.0), 4) if strat else None,
                        "ml_weights": _ml_weights_snap,
                    }) + "\n")
                trade_details_fh.flush()

            # ── Signal IC decay detection ─────────────────────────────────
            if new_closed and _decay_detector is not None:
                try:
                    for _td_trade in new_closed:
                        _td_sym = _td_trade.get("sym", _td_trade.get("symbol", ""))
                        _td_side = _td_trade.get("side", "long")
                        _td_entry = float(_td_trade.get("entry_price", 0.0))
                        _td_exit = float(_td_trade.get("exit_price", 0.0))
                        if _td_entry > 0 and _td_exit > 0:
                            if _td_side == "long":
                                _fwd_return = (_td_exit - _td_entry) / _td_entry
                            else:
                                _fwd_return = (_td_entry - _td_exit) / _td_entry
                        else:
                            _td_pnl = float(_td_trade.get("pnl", 0.0))
                            _td_size = float(_td_trade.get("size", 1.0)) or 1.0
                            _fwd_return = _td_pnl / _td_size
                        _td_sig_dict = last_signals.get(_td_sym) or {}
                        _decay_detector.update(
                            _td_sig_dict, _fwd_return,
                            symbol=_td_sym, side=_td_side,
                        )
                    _decay_warnings = _decay_detector.log_warnings()
                    if _decay_warnings:
                        log.warning(
                            "IC decay alerts cycle=%d: %s",
                            cycle_num,
                            json.dumps(_decay_warnings),
                        )
                    _decay_detector.persist()
                except Exception as _dc_exc:
                    log.debug("SignalDecayDetector update error (non-fatal): %s", _dc_exc)

            # ── Structured JSONL metric line ──────────────────────────────
            metric_row: dict = {
                "cycle": cycle_num,
                "ts": datetime.now(UTC).isoformat(),
                "version": version,
                "regime": regime,
                "composite_score": round(composite_score, 4) if composite_score is not None else None,
                "trade_action": trade_action,
                "sit_out_reason": sit_out_reason if sit_out_reason != "normal" else None,
                "active_signals": active_signals,
                "ring1_pass": ring1_pass,
                "vol_rank": None,  # transient inside strategy — not exposed yet
                "conviction": conviction_str,
                "new_trades": len(new_closed),
                "total_closed": len(closed),
                "elapsed_s": round(cycle_elapsed, 3),
                "breaker_tripped": breaker.tripped if breaker else False,
                "vol_low_threshold": getattr(strat, "_vol_low_threshold", None),
                "basket_std": round(_basket_std, 6),
                "basket_mean": round(_basket_mean, 6),
                "zero_streak": watchdog.consecutive_zero_trade_cycles,
                "regime_hmm": str(last_signals.get("_regime_hmm", "")),
                "regime_consolidated": str(last_signals.get("_regime", "")),
                "stale_symbols": ["ALL"] if sit_out_reason == "stale_data" else [],
                "active_filters": _get_active_filters(sit_out_reason, proposals_gen, proposals_filt),
                "fear_greed_signal": next(
                    (v.get("fear_greed_signal") for k, v in last_signals.items()
                     if isinstance(v, dict) and not k.startswith("_") and not k.startswith("adv_")
                     and v.get("fear_greed_signal") is not None),
                    None,
                ),
                "funding_rate_btc": (last_signals.get("BTCUSDT") or {}).get("funding_rate_signal"),
                "dxy_signal": next(
                    (v.get("dxy_signal") for k, v in last_signals.items()
                     if isinstance(v, dict) and not k.startswith("_") and not k.startswith("adv_")
                     and v.get("dxy_signal") is not None),
                    None,
                ),
            }
            metrics_fh.write(json.dumps(metric_row) + "\n")
            metrics_fh.flush()

            # ── Anomaly detector (gated by feature flag) ──────────────────
            if strat is not None:
                _pnl_delta = sum(float(t.get("pnl", 0.0)) for t in new_closed)
                _anomalies = strat.check_anomalies(
                    cycle=cycle_num,
                    pnl_delta=_pnl_delta,
                    n_new_trades=len(new_closed),
                    zero_streak=watchdog.consecutive_zero_trade_cycles,
                    basket_std=_basket_std,
                )
                for _ev in _anomalies:
                    log.warning("Anomaly [%s] %s", _ev.metric, _ev.message)

            # ── ML combiner weight snapshot every 20 cycles ───────────────
            if cycle_num % 20 == 0 and strat is not None:
                _snap_combiner = getattr(strat, "_combiner", None)
                if _snap_combiner is not None and getattr(_snap_combiner, "_weights", None) is not None:
                    try:
                        from omega.nodes.victoria.ml_combiner import SIGNAL_KEYS as _SK2
                        metrics_fh.write(json.dumps({
                            "type": "ml_weights_snapshot",
                            "cycle": cycle_num,
                            "ts": datetime.now(UTC).isoformat(),
                            "version": version,
                            "signal_keys": _SK2,
                            "weights": [round(float(w), 6) for w in _snap_combiner._weights],
                            "intercept": round(float(_snap_combiner._intercept), 6),
                            "n_samples": len(_snap_combiner._buffer),
                        }) + "\n")
                        metrics_fh.flush()
                    except Exception:
                        pass

            # Zero-streak alert: dump basket diagnostics when stuck
            if watchdog.consecutive_zero_trade_cycles > 15:
                _per_sym = {
                    t: round(float(sig.get("composite", 0.0)), 4)
                    for t, sig in last_signals.items()
                    if not t.startswith("_") and not t.startswith("adv_")
                       and isinstance(sig, dict) and "composite" in sig
                }
                log.warning(
                    "ZERO_STREAK_ALERT cycle=%d streak=%d basket_std=%.4f basket_mean=%.4f composites=%s",
                    cycle_num,
                    watchdog.consecutive_zero_trade_cycles,
                    _basket_std,
                    _basket_mean,
                    json.dumps(_per_sym),
                )

            # ── Decision snapshot ─────────────────────────────────────────
            try:
                from omega.core.decision_snapshot import DecisionSnapshot
                _regime_conf = 0.0
                _regime_w_bear = -1.0
                _regime_w_bull = -1.0
                try:
                    _regime_conf = float(last_signals.get("_regime_w_confidence", 0.0))
                    _regime_w_bear = float(last_signals.get("_regime_w_bear_prob", last_signals.get("_regime_w_bear", -1.0)))
                    _regime_w_bull = float(last_signals.get("_regime_w_bull_prob", last_signals.get("_regime_w_bull", -1.0)))
                except Exception:
                    pass
                _ticker_decisions = getattr(strat, "_last_ticker_decisions", {}) if strat else {}
                _fiedler_scale = getattr(strat, "_last_fiedler_scale", 1.0) if strat else 1.0
                _fiedler_tag = getattr(strat, "_last_fiedler_tag", "warmup") if strat else "warmup"
                snap = DecisionSnapshot(
                    cycle=cycle_num,
                    timestamp=datetime.now(UTC).isoformat(),
                    version=version,
                    regime=regime,
                    regime_confidence=_regime_conf,
                    regime_hmm=str(last_signals.get("_regime_hmm", last_signals.get("_regime", "unknown"))),
                    regime_w_bear=_regime_w_bear,
                    regime_w_bull=_regime_w_bull,
                    sit_out_reason=sit_out_reason,
                    sit_out_size_mult=1.0 if sit_out_reason == "normal" else (0.0 if sit_out_reason == "vol_low" else 0.5),
                    fiedler_scale=_fiedler_scale,
                    fiedler_regime=_fiedler_tag,
                    per_ticker=_ticker_decisions,
                    n_trades=len(new_closed),
                    n_filtered=proposals_filt,
                    n_hold=max(0, len(_ticker_decisions) - proposals_gen),
                )
                decision_writer.write(snap)
                # Post decision snapshot to Go control plane (fire-and-forget)
                try:
                    import dataclasses as _dc
                    import json as _json
                    hb_client.post_decision(
                        _hb_node_id,
                        cycle_num,
                        _json.dumps(_dc.asdict(snap)),
                    )
                except Exception:
                    pass
            except Exception as _snap_exc:
                log.debug("Decision snapshot error (non-fatal): %s", _snap_exc)

            # ── Watchdog ──────────────────────────────────────────────────
            watchdog.record_cycle(
                had_trade=bool(new_closed),
                sit_out_reason=sit_out_reason,
                regime=regime,
                conviction_failures=proposals_filt,
                proposals_generated=proposals_gen,
                ring1_pass=ring1_pass,
            )

            # ── Periodic progress log ─────────────────────────────────────
            if cycle_num % log_interval == 0 or cycle_num == 1 or cycle_num == n_cycles:
                pnl = _total_pnl(closed)
                wr = _win_rate(closed)
                open_pos = engine.open_trades
                elapsed = time.perf_counter() - total_start
                avg_cycle_s = elapsed / cycle_num
                eta = avg_cycle_s * (n_cycles - cycle_num)
                sem_db_count = _query_semantic_count(DATA_DIR)

                checkpoint = {
                    "cycle": cycle_num,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "trades_open": len(open_pos),
                    "trades_closed": len(closed),
                    "total_pnl": round(pnl, 2),
                    "win_rate": round(wr, 4),
                    "regime": regime,
                    "improve_calls": improve_calls,
                    "semantic_patterns_db": sem_db_count,
                    "data_freshness_min": round(freshness_min, 2),
                    "sit_out_reason": sit_out_reason,
                    "avg_cycle_time_s": round(avg_cycle_s, 3),
                    "elapsed_s": round(elapsed, 1),
                    "watchdog_zero_streak": watchdog.consecutive_zero_trade_cycles,
                    "breaker_tripped": breaker.tripped if breaker else False,
                    "vol_low_threshold": getattr(strat, "_vol_low_threshold", None),
                }
                progress.append(checkpoint)
                with open(progress_file, "w") as f:
                    json.dump(progress, f, indent=2)

                status_tag = {
                    "stale_data": "STALE   ", "vol_low": "SIT-OUT ",
                    "vol_high": "CAUTION ", "regime_uncertain": "CAUTION ",
                    "normal": "OK      ",
                }.get(sit_out_reason, "OK      ")

                breaker_str = (
                    f" [BREAKER thr={strat._vol_low_threshold:.3f}]"
                    if breaker and breaker.tripped else ""
                )

                log.info(
                    "Cycle %3d/%d [%s] %s | fresh=%.1fmin | "
                    "open=%2d closed=%3d | PnL=$%+.0f wr=%.0f%% | "
                    "improve=%d sem_db=%d | %.1fs/c ETA %.0fs"
                    " | zero_streak=%d%s",
                    cycle_num, n_cycles, regime[:4].upper(), status_tag,
                    freshness_min,
                    len(open_pos), len(closed),
                    pnl, wr * 100,
                    improve_calls, sem_db_count,
                    avg_cycle_s, eta,
                    watchdog.consecutive_zero_trade_cycles,
                    breaker_str,
                )

            # Meta-harness: run after every N cycles if enabled
            if meta_harness and cycle_num % _META_HARNESS_INTERVAL == 0:
                log.info("Triggering meta-harness at cycle %d", cycle_num)
                run_meta_harness_iteration(log)

            if i < n_cycles - 1:
                time.sleep(sleep_seconds)

    finally:
        metrics_fh.close()
        trade_details_fh.close()
        decision_writer.close()
        hb_client.report_lifecycle(_hb_node_id, "RUNNING", "STOPPED", "training loop completed")

    # ── Final results ─────────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - total_start
    closed_final = engine.closed_trades
    open_final = engine.open_trades
    sem_db_final = _query_semantic_count(DATA_DIR)

    longs = [t for t in closed_final if t.get("side") == "long"]
    shorts = [t for t in closed_final if t.get("side") == "short"]
    wins = [t for t in closed_final if float(t.get("pnl", 0.0)) > 0]
    losses = [t for t in closed_final if float(t.get("pnl", 0.0)) < 0]

    gross_profit = sum(float(t.get("pnl", 0.0)) for t in wins)
    gross_loss = abs(sum(float(t.get("pnl", 0.0)) for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    sit_out_clean = {k: v for k, v in sit_out_counts.items() if not k.startswith("_")}

    results = {
        "version": version,
        "run": {
            "date": datetime.now(UTC).isoformat(),
            "cycles": n_cycles,
            "sleep_seconds": sleep_seconds,
            "elapsed_s": round(total_elapsed, 1),
            "avg_cycle_s": round(total_elapsed / n_cycles, 3),
            "cg_key_used": bool(cg_key),
            "db_url_used": bool(db_url),
        },
        "preflight": {
            "ok": preflight.ok,
            "warnings": preflight.warnings,
        },
        "intelligence": {
            "improve_calls": improve_calls,
            "semantic_patterns_db": sem_db_final,
            "semantic_patterns_node": sem_node._patterns_extracted,
        },
        "observability": {
            "metrics_jsonl": str(metrics_jsonl),
            "total_zero_trade_cycles": watchdog.total_zero_trade_cycles,
            "max_zero_streak": watchdog.consecutive_zero_trade_cycles,
            "ring1_pass_rate_final": watchdog.ring1_pass_rate(),
            "conviction_filter_rate": watchdog.conviction_filter_rate(),
            "circuit_breaker_trips": breaker._trip_count if breaker else 0,
            "final_vol_low_threshold": getattr(strat, "_vol_low_threshold", None),
        },
        "filters": sit_out_clean,
        "trades": {
            "total_closed": len(closed_final),
            "long_trades": len(longs),
            "short_trades": len(shorts),
            "open_positions": len(open_final),
            "win_rate": round(_win_rate(closed_final), 4),
            "total_pnl_usd": round(_total_pnl(closed_final), 2),
            "realised_pnl_engine": round(engine.realised_pnl, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else None,
        },
    }

    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    # V49 hard gates — compare this run against the previous version.
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

    # Performance attribution report
    try:
        from omega.nodes.victoria.performance_attribution import PerformanceAttribution
        if trades_csv.exists():
            attr = PerformanceAttribution(trades_csv)
            attr_result = attr.compute()
            attr_path = DATA_DIR / f"{version}_attribution.json"
            attr.save(attr_path)
            log.info(
                "Attribution — alpha: $%+.2f  beta: $%+.2f  timing: $%+.2f  selection: $%+.2f",
                attr_result["components"]["alpha"],
                attr_result["components"]["beta"],
                attr_result["components"]["timing"],
                attr_result["components"]["selection"],
            )
            log.info("Attribution report  : %s", attr_path)
    except Exception as exc:
        log.warning("Performance attribution failed (non-fatal): %s", exc)

    log.info("")
    log.info("=" * 70)
    log.info(
        "%s COMPLETE — %d cycles in %.0fs (%.2fs/cycle)",
        version.upper(), n_cycles, total_elapsed, total_elapsed / n_cycles,
    )
    log.info("=" * 70)
    log.info("improve_calls         : %d", improve_calls)
    log.info("semantic_patterns_db  : %d", sem_db_final)
    log.info("Closed trades         : %d  (long=%d  short=%d)", len(closed_final), len(longs), len(shorts))
    log.info(
        "Total PnL             : $%+.2f  (engine realised: $%+.2f)",
        _total_pnl(closed_final), engine.realised_pnl,
    )
    log.info("Win rate              : %.1f%%  (%d/%d)", _win_rate(closed_final) * 100, len(wins), len(closed_final))
    log.info("Profit factor         : %.2f", profit_factor if profit_factor != float("inf") else 0)
    log.info("--- Observability ---")
    log.info(
        "Zero-trade cycles     : %d / %d  (%.0f%%)",
        watchdog.total_zero_trade_cycles, n_cycles,
        watchdog.total_zero_trade_cycles / n_cycles * 100,
    )
    log.info("Circuit breaker trips : %d", breaker._trip_count if breaker else 0)
    log.info("Final vol threshold   : %.3f", getattr(strat, "_vol_low_threshold", 0.20))
    log.info("Metrics JSONL         : %s", metrics_jsonl)
    log.info("Results               : %s", results_file)
    log.info("=" * 70)

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Canonical Victoria training script with watchdog, circuit breaker, and preflight"
    )
    parser.add_argument(
        "--version", type=str, default=None,
        help="Training version label (default: auto-increment from data/training_version.txt)"
    )
    parser.add_argument("--cycles", type=int, default=100, help="Number of training cycles")
    parser.add_argument("--sleep", type=float, default=30.0, help="Seconds between cycles")
    parser.add_argument("--log-interval", type=int, default=5, help="Log every N cycles")
    parser.add_argument(
        "--meta-harness",
        action="store_true",
        default=False,
        help=(
            "Enable Meta-Harness self-improvement loop. "
            f"Runs strategy optimization every {_META_HARNESS_INTERVAL} cycles. "
            "Set OMEGA_META_LLM=1 to enable LLM-powered proposals."
        ),
    )
    parser.add_argument(
        "--features",
        type=str,
        default=None,
        help=(
            "Feature flags: preset name (v93_baseline, v97_geometry, observability_only, "
            "embeddings_only, v98_full_obs, v99_full) or JSON dict "
            '(e.g. \'{"ricci_sizing":true}\'). Default: v93_baseline (all OFF).'
        ),
    )
    parser.add_argument(
        "--backtest-snapshot",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Path to a frozen OHLCV snapshot (created by scripts/freeze_snapshot.py). "
            "When set, replaces live DataIngestionNode with ReplayIngestionNode for "
            "deterministic version-to-version comparison. WS signals degrade to 0.0. "
            "Example: --backtest-snapshot data/snapshots/snap_20260414.json"
        ),
    )
    args = parser.parse_args()

    version = _resolve_version(args.version)
    _setup_logging(version)

    run(
        version=version,
        n_cycles=args.cycles,
        sleep_seconds=args.sleep,
        log_interval=args.log_interval,
        meta_harness=args.meta_harness,
        features=args.features,
        backtest_snapshot=args.backtest_snapshot,
    )
