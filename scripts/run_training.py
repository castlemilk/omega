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
  2. Structured cycle metrics  — one-line JSON per cycle → {TMP_SINK_DIR}/{version}_metrics.jsonl
                                 (TMP_SINK_DIR = $OMEGA_AUDIT_OUTPUT_DIR/tmp when set, else /tmp)
  3. Startup preflight         — validates DB, exchange, deps before loop starts
  4. Sit-out circuit breaker   — lowers vol_low threshold after 30 consecutive sit-outs

Usage:
    python scripts/run_training.py
    python scripts/run_training.py --version v27 --cycles 500 --sleep 30
    python scripts/run_training.py --cycles 100 --sleep 5 --log-interval 10

Default version is auto-incremented from data/training_version.txt (or "v1").
"""
from __future__ import annotations

import os
import sys

# V207a + V217: pin determinism-critical env BEFORE any further import.
# Two env vars must be present at *process start*, before numpy / its BLAS
# backend load, or they have no effect:
#   • PYTHONHASHSEED (V207a) — CPython reads it at start; if unset it is
#     randomized per-process, permuting set/dict iteration order (~1e-4 FP
#     drift in composite scoring; V206b located this channel).
#   • BLAS thread count (V217) — Apple Accelerate (vecLib), OpenBLAS, and MKL
#     read their *_NUM_THREADS / VECLIB_MAXIMUM_THREADS vars when the BLAS
#     dylib first loads. Multi-threaded BLAS reduces in a non-deterministic
#     parallel order, drifting the low-order bits of np.corrcoef / eigvalsh /
#     matmul — the V216 third determinism channel (rmt_signal, basic_signals,
#     and the derived consensus/divergence fields). Pinning to 1 thread makes
#     the signal layer byte-identical across replicates (proven cheap A/B).
# Because these must precede numpy import, we set them here and — if we did
# not already inherit them — re-exec ourselves so the values are in place at
# the true process start (execvpe keeps the same PID; fires at most once).
_need_reexec = False
if os.environ.get("PYTHONHASHSEED") != "42":
    os.environ["PYTHONHASHSEED"] = "42"
    _need_reexec = True
# Pin BLAS to a single thread only in frozen-backtest mode (live trading uses
# a different entry point; gate on the frozen-cache flags so the eval — and
# only the eval — is forced deterministic).
if "--frozen-cache" in sys.argv or "--backtest-snapshot" in sys.argv:
    for _blas_var in (
        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
    ):
        if os.environ.get(_blas_var) != "1":
            os.environ[_blas_var] = "1"
            _need_reexec = True
if _need_reexec:
    os.execvpe(sys.executable, [sys.executable] + sys.argv, os.environ)

import argparse
import csv
import hashlib
import json
import logging
import math
import struct
import subprocess
import time
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from omega.eval.v49_gates import check_v49_gates


# ---------------------------------------------------------------------------
# V228 resiliency #5: run-artifact provenance manifest
# ---------------------------------------------------------------------------

def _run_provenance(version: str, snapshot: str | None, active_flags) -> dict:
    """Record the exact substrate a result was produced from, embedded in
    results.json under "provenance": git SHA (+ dirty flag), frozen-cache md5s
    (V219 manifest), resolved feature flags, snapshot, and the cell label.

    This closes the V218-class failure: V217 claimed a hermetic baseline that
    silently depended on an *uncommitted* macro cache, so the number could not
    be reproduced from a clean checkout. With provenance embedded, every
    results.json self-certifies "this PnL came from commit X + cache md5s Y at
    cell Z" — a later reader can detect a dirty tree or drifted cache without
    re-deriving it by hand.

    All lookups are best-effort and never raise: provenance is metadata, not
    compute, and must not crash a 200-cycle run. It is NOT compared by
    check_determinism.sh (which reads only total_pnl_usd/total_closed), so the
    varying git/timestamp fields do not affect the determinism verdict.
    """
    prov: dict = {"cell_label": version}
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=5,
        )
        prov["git_sha"] = sha.stdout.strip() or None
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=5,
        )
        prov["git_dirty"] = bool(dirty.stdout.strip())
    except Exception:
        prov["git_sha"] = None
        prov["git_dirty"] = None
    try:
        man = ROOT / "data" / ".cache_manifest.json"
        if man.exists():
            prov["cache_manifest"] = json.loads(man.read_text()).get("files", {})
            prov["cache_manifest_md5"] = hashlib.md5(man.read_bytes()).hexdigest()
        else:
            prov["cache_manifest"] = None
    except Exception:
        prov["cache_manifest"] = None
    try:
        prov["features"] = active_flags
    except Exception:
        prov["features"] = None
    prov["snapshot"] = snapshot
    prov["frozen_cache"] = os.environ.get("OMEGA_FROZEN_CACHE") == "1"
    prov["r3_ics"] = os.environ.get("OMEGA_R3_ICS") == "1"
    return prov


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

# OMEGA_AUDIT_OUTPUT_DIR — redirect large per-run WRITE artifacts (results, trades,
# progress, JSONL traces/fingerprints, attribution, gate reports, trace-writer output)
# off the host disk onto an external mount (e.g. gamma-systems-2) to avoid the ENOSPC
# class that paused V232/V233. Defaults to DATA_DIR when unset.
#
# Only WRITE artifacts move. STABLE/COMMITTED INPUTS stay anchored to DATA_DIR so
# frozen-cache determinism is untouched: training_version.txt, .cache_manifest.json,
# macro_cache.db, signal_ic_history.json, empirical_ic_history.json, the state/memory
# DBs, and data/snapshots/. Never point AUDIT_DIR at those.
AUDIT_DIR = Path(os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", "").strip() or str(DATA_DIR))
AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# TMP_SINK_DIR — home for the "fast local" per-run sinks (metrics.jsonl,
# trade_details.jsonl, decisions.jsonl, training.log). Historically hardcoded to
# /tmp, which bypassed OMEGA_AUDIT_OUTPUT_DIR and filled the HOST disk during the
# V235 walk-forward grid (64 cells × ~1.5MB of JSONL each, plus every prior grid's
# residue — /tmp never gets cleaned between runs). When OMEGA_AUDIT_OUTPUT_DIR is
# set these now land in $OMEGA_AUDIT_OUTPUT_DIR/tmp/; unset keeps the /tmp default.
_AUDIT_ENV = os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", "").strip()
TMP_SINK_DIR = (Path(_AUDIT_ENV) / "tmp") if _AUDIT_ENV else Path("/tmp")
TMP_SINK_DIR.mkdir(parents=True, exist_ok=True)

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
        results = AUDIT_DIR / f"{label}_results.json"
        trades = AUDIT_DIR / f"{label}_trades.csv"
        if results.exists() and trades.exists():
            return label
    return None


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(version: str) -> logging.Logger:
    log_file = str(TMP_SINK_DIR / f"{version}_training.log")
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
            "mae", "mfe",  # Max Adverse / Favourable Excursion — for disposition metric
            "win_capture", "loss_capture", "exit_score",  # V128 exit telemetry
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


def _v219_substrate_preflight(log: logging.Logger) -> None:
    """V219 — verify the frozen eval substrate is committed, intact, and usable.

    Runs ONLY in frozen-backtest mode (OMEGA_FROZEN_CACHE=1) so the live trading
    path is unaffected. Three checks, each fatal (exit 1) — a backtest must never
    silently run on a corrupt/stale/inert substrate and call the result a baseline:

      1. **Manifest md5** — hash every file in data/.cache_manifest.json and abort
         on any drift from the committed hash. Catches an uncommitted/edited/
         truncated cache (the exact V218 defect: V217's "hermetic" numbers rode an
         uncommitted macro_cache.db). Runs BEFORE MacroDataCache is instantiated so
         the bytes hashed are the committed bytes (a read-only WAL open does not
         mutate the main .db — verified — but order it first regardless).
      2. **Macro health** — call the REAL read path (MacroDataCache.get_values) for
         every MACRO_SERIES and count how many return data. Counting DB rows would
         report "usable" while the wall-clock/anchor read returns empty; exercising
         the read path covers __failed__, 0.0, AND any window/anchor regression in
         one check. 0 usable => "MACRO INERT: 0 series usable" + exit 1.
      3. **Funding health** — funding_rate_cache (inside macro_cache.db) must be
         non-empty. Empty => "FUNDING INERT" + exit 1. (Funding has no date filter,
         so it never expires — the only failure mode is empty/missing.)
    """
    if os.environ.get("OMEGA_FROZEN_CACHE") != "1":
        return

    import hashlib
    import sqlite3

    log.info("[startup] V219 substrate preflight (frozen cache):")

    # ── 1. Manifest md5 verification ─────────────────────────────────────────
    manifest_path = DATA_DIR / ".cache_manifest.json"
    if not manifest_path.exists():
        log.error(
            "[startup]   CACHE MANIFEST MISSING: %s — run "
            "scripts/build_cache_manifest.py and commit. Aborting (frozen eval "
            "must be reproducible from committed state).", manifest_path,
        )
        sys.exit(1)
    try:
        manifest = json.loads(manifest_path.read_text())
        expected = manifest["files"]
    except Exception as exc:
        log.error("[startup]   CACHE MANIFEST UNREADABLE: %s — aborting.", exc)
        sys.exit(1)

    mismatches: list[str] = []
    for rel, want_md5 in sorted(expected.items()):
        p = ROOT / rel
        if not p.exists():
            mismatches.append(f"{rel}: MISSING")
            continue
        h = hashlib.md5()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        got = h.hexdigest()
        if got != want_md5:
            mismatches.append(f"{rel}: {got} != {want_md5}")
        else:
            log.info("[startup]   manifest OK: %s  %s", want_md5, rel)
    if mismatches:
        log.error(
            "[startup]   CACHE MANIFEST MISMATCH (%d file(s)) — frozen substrate "
            "drifted from committed state; refusing to produce a baseline on it:",
            len(mismatches),
        )
        for m in mismatches:
            log.error("[startup]     %s", m)
        log.error(
            "[startup]   If this change is intentional, rerun "
            "scripts/build_cache_manifest.py and commit. Aborting.")
        sys.exit(1)

    # ── 2. Macro health (via the real read path) ─────────────────────────────
    from omega.nodes.victoria.data_cache import MACRO_SERIES, MacroDataCache

    cache = MacroDataCache()
    usable: list[str] = []
    inert: list[str] = []
    for series_id in MACRO_SERIES:
        # 90d covers the widest consumer (yield_curve); dxy uses window+10 (~40d).
        vals = cache.get_values(series_id, lookback_days=90)
        if vals and any(v != 0.0 for v in vals):
            usable.append(series_id)
        else:
            inert.append(series_id)
    log.info(
        "[startup]   MACRO HEALTH: %d/%d series usable via read path (usable=%s)",
        len(usable), len(MACRO_SERIES), ",".join(usable) or "none",
    )
    if inert:
        log.warning("[startup]   macro series with NO usable data: %s", ",".join(inert))
    if not usable:
        log.error(
            "[startup]   MACRO INERT: 0 series usable — every macro signal would "
            "compute on zeros (the V218 defect). Repair with "
            "scripts/repair_macro_cache.py + rebuild manifest. Aborting.")
        sys.exit(1)

    # ── 3. Funding health ────────────────────────────────────────────────────
    db_path = DATA_DIR / "macro_cache.db"
    try:
        conn = sqlite3.connect(str(db_path))
        n_funding = conn.execute("SELECT COUNT(*) FROM funding_rate_cache").fetchone()[0]
        conn.close()
    except Exception as exc:
        log.error("[startup]   FUNDING INERT: cannot read funding_rate_cache (%s). Aborting.", exc)
        sys.exit(1)
    if n_funding == 0:
        log.error(
            "[startup]   FUNDING INERT: funding_rate_cache is empty — carry/funding "
            "signals would see no data. Repair + rebuild manifest. Aborting.")
        sys.exit(1)
    log.info("[startup]   FUNDING HEALTH: %d symbols cached", n_funding)
    log.info("[startup]   V219 substrate preflight PASS")


def run(
    version: str,
    n_cycles: int = 100,
    sleep_seconds: float = 30.0,
    log_interval: int = 5,
    meta_harness: bool = False,
    features: str | None = None,
    backtest_snapshot: str | None = None,
    seed: int | None = None,
) -> dict:
    log = logging.getLogger(f"training.{version}")

    # ── File paths ────────────────────────────────────────────────────────
    metrics_jsonl = TMP_SINK_DIR / f"{version}_metrics.jsonl"
    trades_csv = AUDIT_DIR / f"{version}_trades.csv"
    progress_file = AUDIT_DIR / f"{version}_progress.json"
    results_file = AUDIT_DIR / f"{version}_results.json"
    signal_contribs_jsonl = AUDIT_DIR / f"{version}_signal_contribs.jsonl"
    trade_details_jsonl = TMP_SINK_DIR / f"{version}_trade_details.jsonl"
    # ── V214 observability deltas #3 + #4 (always-on determinism bisect tools) ──
    # #3 mode-switch trace: one line per regime/selector-mode transition.
    # #4 signal-values fingerprint: one line per cycle (sha1 of sorted full-precision
    #    signal scalars + the raw values). Diffing two same-seed runs' fingerprints
    #    yields the FIRST cycle where signals diverge and the exact signal that moved
    #    — the discriminator the V207–V213 determinism hunt lacked. See V214.md §3.
    mode_transitions_jsonl = AUDIT_DIR / f"{version}_mode_transitions.jsonl"
    signal_fingerprint_jsonl = AUDIT_DIR / f"{version}_signal_fingerprint.jsonl"
    # ── V217 obs-delta #1: per-field full-precision fingerprint ──────────────
    # One line per (cycle, signal_name) with the IEEE-754 double bit-exact hex of
    # the field's value. The V216 third channel proved the whole-dict `fp` hash
    # diverges while the rounded-to-12 `values` dump looks identical — so the
    # combined hash cannot NAME the field. This artifact does: one per-field diff
    # = one (cycle, signal_name) channel. Entries are sorted by (cycle, name) so
    # the JSONL is line-comparable via `cmp`. See V217.md §step-1.
    per_field_fingerprint_jsonl = AUDIT_DIR / f"{version}_per_field_fingerprint.jsonl"
    per_field_fingerprint_jsonl.unlink(missing_ok=True)  # fresh per run (cmp-able)

    db_url = os.environ.get("DATABASE_URL", "")
    cg_key = os.environ.get("CG_API_KEY") or os.environ.get("COINGEKO_API_KEY") or ""

    # ── Deterministic seed (required for reproducible backtest comparisons) ──
    if seed is not None:
        import random as _random
        import numpy as _np
        _random.seed(seed)
        _np.random.seed(seed)
        log.info("RNG seed set to %d (deterministic mode)", seed)

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
    log.info("Audit/trace dir: %s%s", AUDIT_DIR,
             " (OMEGA_AUDIT_OUTPUT_DIR)" if AUDIT_DIR != DATA_DIR else " (default)")
    log.info("Tmp sinks      : %s%s", TMP_SINK_DIR,
             " (redirected off host /tmp via OMEGA_AUDIT_OUTPUT_DIR)"
             if str(TMP_SINK_DIR) != "/tmp" else " (host /tmp default)")
    # Runtime assertion: when the audit dir is redirected, the tmp sinks MUST be
    # too — a hardcoded /tmp here is exactly the gap that filled the host disk
    # during the V235 grid. Fail loudly rather than silently regress.
    if AUDIT_DIR != DATA_DIR:
        assert str(metrics_jsonl).startswith(str(TMP_SINK_DIR)), metrics_jsonl
        assert TMP_SINK_DIR != Path("/tmp"), (
            "OMEGA_AUDIT_OUTPUT_DIR is set but tmp sinks still target host /tmp"
        )
    log.info("Log file       : %s", TMP_SINK_DIR / f"{version}_training.log")
    _active_flags = _active_features.active_flags()
    if _active_flags:
        log.info("Features ON    : %s", ", ".join(_active_flags))
    else:
        log.info("Features       : v93_baseline (all OFF)")
    log.info("=" * 70)

    # ── V215 observability delta: frozen-backtest HTTP guard ─────────────
    # V214 localized the determinism break to a hole in --frozen-cache: direct
    # urllib fetches in signals_advanced.py (+ ~25 sibling signal modules)
    # bypassed OMEGA_FROZEN_CACHE, so each replicate process fetched live data at
    # its own startup wall-clock and the "sleep channel" was really wall-clock
    # separation between replicates. This guard makes the freeze airtight AND
    # loud: in frozen-cache mode ALL outbound urllib HTTP is blocked (raises
    # URLError → caught by every signal's broad except → deterministic fallback)
    # and logged. With network provably blocked, any residual determinism spread
    # is definitionally NON-network. It would have prevented the entire V207–V214
    # determinism hunt — grep data/{ver}_http_during_backtest.jsonl for leakers.
    #
    # Patch OpenerDirector.open (NOT urlopen): it is import-style-agnostic — every
    # urlopen(), however imported (incl. `from urllib.request import urlopen` in
    # whale_flow.py), routes through the global opener's .open() at call time, so a
    # class-method patch catches all callers. urllib is the only HTTP mechanism in
    # the Victoria layer (no requests/httpx/aiohttp), so this one patch is airtight.
    # Socket-level blocking was rejected — it would kill the Postgres connection.
    _http_guard_state = {"blocked": 0}
    if os.environ.get("OMEGA_FROZEN_CACHE") == "1":
        import urllib.error as _uerr
        import urllib.request as _ureq

        _http_log_path = AUDIT_DIR / f"{version}_http_during_backtest.jsonl"
        try:
            _http_log_path.unlink()  # fresh per run
        except FileNotFoundError:
            pass
        _orig_opener_open = _ureq.OpenerDirector.open

        def _frozen_blocked_open(_self, fullurl, *args, **kwargs):
            _url = getattr(fullurl, "full_url", fullurl)
            _http_guard_state["blocked"] += 1
            try:
                with open(_http_log_path, "a") as _hf:
                    _hf.write(json.dumps({"url": str(_url)[:300]}) + "\n")
            except Exception:
                pass
            raise _uerr.URLError(
                f"OMEGA_FROZEN_CACHE: live HTTP blocked in backtest: {str(_url)[:120]}"
            )

        _ureq.OpenerDirector.open = _frozen_blocked_open
        log.info(
            "V215: frozen-cache HTTP guard ARMED — all outbound urllib blocked + "
            "logged to %s", _http_log_path,
        )

    # ── V213 observability delta #1: subsystem wiring banner ──────────────
    # Historically (V148–V202) subsystems ran flag-ON but code-INERT — the flag
    # was undeclared on the dataclass (getattr→False no-op) or the module's
    # ImportError was silently caught (V212: strategy_selector was inert for the
    # whole V199–V211 arc). Four versions were spent tuning code that never ran.
    # This banner makes "is this code path ACTUALLY running?" a one-grep answer:
    # for each audited subsystem it prints the flag's declared/value state plus a
    # live wiring probe (is the flag a real dataclass field? does the module
    # import?). Grep a run log for "SILENTLY INERT" or "UNDECLARED" to catch the
    # whole class of bug at cycle 0 instead of after a wasted version.
    from dataclasses import asdict as _asdict
    import importlib as _importlib

    _SUBSYSTEM_PROBES = [
        # (label, flag_name, module_to_import_or_None)
        ("strategy_selector", "strategy_selector_enabled", "omega.nodes.victoria.strategy_selector"),
        ("regime_signal_weighting", "regime_signal_weighting", None),
        ("mode_transition_blend", "mode_transition_blend", None),
        ("bayesian_regime", "bayesian_regime", "omega.nodes.victoria.bayesian_regime"),
        ("hmm_regime", "hmm_regime", "omega.nodes.victoria.hmm_regime"),
        # V218.B preflight: per-regime IC weighting. Undeclared on main → banner
        # prints "UNDECLARED — silent no-op", documenting the latent inertness.
        # NB: even when declared+ON the path is unreachable unless _signal_ics is
        # populated (see the post-build IC-WEIGHTING probe below).
        ("per_regime_ic_weighting", "per_regime_ic_weighting", None),
        # V225: additive crisis-skew signal. Module must import + flag declared.
        ("crisis_skew", "crisis_skew_enabled", "omega.nodes.victoria.signals.crisis_skew"),
        # V232: additive RV-term-structure inversion brake. Module + flag declared.
        ("rv_term_brake", "rv_term_brake_enabled", "omega.nodes.victoria.signals.rv_term_structure"),
    ]
    _declared_fields = set(_asdict(_active_features).keys())
    log.info("[startup] subsystem wiring (flag → wired?):")
    for _label, _flag, _mod in _SUBSYSTEM_PROBES:
        if _flag not in _declared_fields:
            _state = "UNDECLARED — getattr→False, flag is a silent no-op"
        elif not bool(getattr(_active_features, _flag, False)):
            _state = "off"
        elif _mod is None:
            _state = "ON → ACTIVE"
        else:
            try:
                _importlib.import_module(_mod)
                _state = "ON · module importable → ACTIVE"
            except Exception as _imp_exc:
                _state = f"ON · IMPORT FAILED ({type(_imp_exc).__name__}) → SILENTLY INERT"
        log.info("[startup]   %-26s %s", _label + ":", _state)
    # V225: explicit crisis-skew status line (Step-6 banner check). Mirrors the
    # requested `<signal>: ENABLED, frozen=N` format — one-grep confirmation that
    # the additive term is live and reading frozen (not live) inputs.
    _skew_on = bool(getattr(_active_features, "crisis_skew_enabled", False))
    _skew_gated = bool(getattr(_active_features, "crisis_skew_regime_gate_enabled", False))
    _frozen = 1 if os.environ.get("OMEGA_FROZEN_CACHE") == "1" else 0
    # V226: banner shows the regime-gate state + the effective W (0.2 gated / 0.5
    # always-on V225 path) — one-grep confirmation that the gated retry is live.
    log.info(
        "[startup]   crisis_skew: %s (regime_gated=%d, W=%s), frozen=%d "
        "(additive post-demean, source=OHLCV)",
        "ON" if _skew_on else "off",
        1 if _skew_gated else 0,
        "0.2" if _skew_gated else "0.5",
        _frozen,
    )
    # V232: explicit RV-term-structure brake status line (mirrors the crisis_skew
    # banner). One-grep confirmation the brake is live, gated, and OHLCV-fed.
    _rv_on = bool(getattr(_active_features, "rv_term_brake_enabled", False))
    _rv_gated = bool(getattr(_active_features, "rv_term_brake_regime_gate_enabled", False))
    log.info(
        "[startup]   rv_term_brake: %s (regime_gated=%d, W=0.2, X=%s, short=%s/long=%s), "
        "frozen=%d (additive post-demean, source=OHLCV)",
        "ON" if _rv_on else "off",
        1 if _rv_gated else 0,
        getattr(_active_features, "rv_inversion_threshold", 1.5),
        getattr(_active_features, "rv_short_window", 3),
        getattr(_active_features, "rv_long_window", 14),
        _frozen,
    )
    # V238: frozen-series status — per-series presence + coverage so "which of
    # the six info signals actually have data this run?" is a one-grep answer.
    # ABSENT is an honest state (the signal returns NaN → skipped), not an error.
    _fs_on = bool(getattr(_active_features, "frozen_series_enabled", False))
    if "frozen_series_enabled" not in _declared_fields:
        log.info("[startup]   frozen_series: UNDECLARED — silent no-op")
    elif not _fs_on:
        log.info("[startup]   frozen_series: off (six info signals inert under frozen cache)")
    else:
        try:
            from omega.nodes.victoria.series_provider import get_series_provider as _gsp

            _sp = _gsp()
            _fs_series = [
                ("fear_greed", ["fng"]),
                ("vix", ["fred_vixcls"]),
                ("dxy", ["fred_dtwexbgs"]),
                ("yield_curve", ["fred_dgs10", "fred_dgs2"]),
                ("whale_flow.oi", ["binance_oi_ethusdt"]),  # per-symbol; probe one
                ("whale_flow.stables", ["stablecoin_total_usd"]),
                ("gdelt", ["gdelt_tone"]),
                ("dvol(unwired V238)", ["dvol_btc"]),
            ]
            for _fs_label, _fs_names in _fs_series:
                _covs = []
                for _n in _fs_names:
                    _c = _sp.coverage(_n) if _sp.available(_n) else None
                    _covs.append(f"{_n}[{_c[0]}..{_c[1]}]" if _c else f"{_n}=ABSENT")
                log.info("[startup]   frozen_series %-22s %s", _fs_label + ":", " ".join(_covs))
            log.info("[startup]   frozen_series: ON → ACTIVE (provider wired, bar-aligned)")
        except Exception as _fs_exc:
            log.info(
                "[startup]   frozen_series: ON · PROVIDER FAILED (%s) → SILENTLY INERT",
                type(_fs_exc).__name__,
            )
    log.info("=" * 70)

    # ── V219 substrate preflight (frozen cache: manifest md5 + macro/funding
    #    health). Runs BEFORE MacroDataCache is instantiated below so the bytes
    #    hashed are the committed bytes. No-op in live mode. ─────────────────
    _v219_substrate_preflight(log)

    # ── Startup preflight ─────────────────────────────────────────────────
    from omega.core.training_preflight import StartupPreflight
    preflight = StartupPreflight.run()

    # ── Macro cache warm-up ───────────────────────────────────────────────
    # Refresh all stale FRED series once at startup so training cycles read
    # from local SQLite (zero FRED API calls during the training loop).
    try:
        from omega.nodes.victoria.data_cache import MacroDataCache
        _macro_cache = MacroDataCache()
        if os.environ.get("OMEGA_FROZEN_CACHE") == "1":
            log.info("V207a: OMEGA_FROZEN_CACHE=1 — skipping macro warm_up (no live FRED/funding fetches)")
        else:
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
    # ── Exit controller (V128+): ATR-based disposition fix ─────────────────
    _exit_ctrl = None
    if _active_features.disposition_exit_controller:
        from omega.nodes.victoria.exit_controller import ExitController, ExitConfig
        _exit_cfg = ExitConfig(
            enabled=True,
            mfe_trail_k=float(_active_features.mfe_trail_k),
            mfe_retracement_cap=float(_active_features.mfe_retracement_cap),
            mae_stop_k=float(_active_features.mae_stop_k),
            early_loss_time_stop=bool(_active_features.early_loss_time_stop),
            early_loss_cycles=int(_active_features.early_loss_cycles),
            early_loss_k_atr=float(_active_features.early_loss_k_atr),
            trailing_stop_min_age=int(_active_features.trailing_stop_min_age),
            stop_loss_min_age=int(_active_features.stop_loss_min_age),
            # V135: skip legacy fixed-% stop when ATR stop is the guard
            skip_legacy_stop_loss=bool(getattr(_active_features, "atr_stop_enabled", False)),
            # V141: side-specific trail multipliers + zero_mfe early exit
            long_trail_multiplier=float(getattr(_active_features, "long_trail_multiplier", 1.0)),
            short_trail_multiplier=float(getattr(_active_features, "short_trail_multiplier", 1.0)),
            zero_mfe_early_exit_cycles=int(getattr(_active_features, "zero_mfe_early_exit_cycles", 0)),
        )
        _exit_ctrl = ExitController(_exit_cfg)
        log.info(
            "ExitController: enabled (mfe_trail_k=%.2f, retracement_cap=%.2f, mae_stop_k=%.2f"
            ", early_loss=%s N=%d K=%.2f, trail_min_age=%d, sl_min_age=%d"
            ", long_trail_mult=%.2f, short_trail_mult=%.2f, zero_mfe_cycles=%d)",
            _exit_cfg.mfe_trail_k, _exit_cfg.mfe_retracement_cap, _exit_cfg.mae_stop_k,
            _exit_cfg.early_loss_time_stop, _exit_cfg.early_loss_cycles, _exit_cfg.early_loss_k_atr,
            _exit_cfg.trailing_stop_min_age, _exit_cfg.stop_loss_min_age,
            _exit_cfg.long_trail_multiplier, _exit_cfg.short_trail_multiplier,
            _exit_cfg.zero_mfe_early_exit_cycles,
        )

    # V246: exit adaptivity — parametrized legacy exits (flag-gated; defaults
    # reproduce the pre-V246 literals byte-identically when OFF).
    _exit_kw = {}
    if bool(getattr(_active_features, "exit_adaptivity_enabled", False)):
        _exit_kw = {
            "trail_keep_frac": float(getattr(_active_features, "exit_trail_keep_frac", 0.5)),
            "max_hold_win": int(getattr(_active_features, "exit_max_hold_win", 10)),
            "max_hold_lose": int(getattr(_active_features, "exit_max_hold_lose", 6)),
        }
        log.info("V246 exit_adaptivity ACTIVE: %s", _exit_kw)

    # V248: regime-conditional exit params (flag-gated; when OFF the engine
    # receives regime_exit_params=None and behavior is byte-identical).
    _regime_exit_adaptive = bool(
        getattr(_active_features, "exit_regime_adaptivity_enabled", False)
    )
    if _regime_exit_adaptive:
        _exit_kw["regime_exit_params"] = {
            _reg: {
                "trail_keep_frac": float(
                    getattr(_active_features, f"exit_trail_keep_frac_{_reg}", 0.5)
                ),
                "max_hold_win": int(
                    getattr(_active_features, f"exit_max_hold_win_{_reg}", 10)
                ),
                "max_hold_lose": int(
                    getattr(_active_features, f"exit_max_hold_lose_{_reg}", 6)
                ),
            }
            for _reg in ("normal", "high_vol", "crisis")
        }
        log.info(
            "V248 exit_regime_adaptivity ACTIVE: %s", _exit_kw["regime_exit_params"]
        )

    engine = PaperTradingEngine(
        initial_capital=100_000.0,
        db_url=db_url or None,
        max_position_per_symbol=1.0,
        max_portfolio_exposure=1.0,
        exit_controller=_exit_ctrl,
        **_exit_kw,
    )
    orch.set_paper_trading(engine)

    # V133: inject engine reference into strategy for four-factor AND-gate
    _strat = getattr(victoria, "_strategy", None)
    if _strat is not None:
        _strat._paper_engine = engine

    # ── V222: seed pooled + per-regime ICs from committed state ──────────
    # The IC-weighted conviction path was inert for the entire V199–V221 arc
    # because update_signal_ics had zero callers here (the V218.B probe below
    # documented it every startup). Load the committed seed tables from
    # data/signal_ic_history.json BEFORE the probe so the probe line flips to
    # "IC-weighting ACTIVE" — flag ic_seed_weighting=false is the IC-off control.
    if _strat is not None and bool(getattr(_active_features, "ic_seed_weighting", False)):
        try:
            import json as _ic_json
            import os as _ic_os
            # V224: under OMEGA_R3_ICS=1, load empirical OOS-holdout ICs from
            # data/empirical_ic_history.json instead of the hand-seeded table.
            # One committed file holds a per-target (leave-one-snapshot-out)
            # block; select the block by snapshot name so the ICs used while
            # trading X were fit on the OTHER snapshots only (zero look-ahead).
            # Default (env unset) keeps the V222/V223 seed path bit-for-bit.
            if _ic_os.environ.get("OMEGA_R3_ICS") == "1":
                _emp = _ic_json.loads((DATA_DIR / "empirical_ic_history.json").read_text())
                _snap_stem = str(backtest_snapshot or "")
                if "trending" in _snap_stem:
                    _r3_target = "trend"
                elif "crisis" in _snap_stem:
                    _r3_target = "crisis"
                else:
                    _r3_target = "recent"
                _r3_blk = _emp.get(_r3_target) or {}
                _seed_pooled = {
                    str(k): float(v)
                    for k, v in (_r3_blk.get("empirical_pooled_ics") or {}).items()
                }
                _seed_regime = {
                    str(k): {str(r): float(x) for r, x in d.items()}
                    for k, d in (_r3_blk.get("empirical_regime_ics") or {}).items()
                    if isinstance(d, dict)
                }
                _strat._ic_source = "R3"
                log.info(
                    "[startup]   V224 R3 empirical ICs: target=%s fit_on=%s",
                    _r3_target, _r3_blk.get("fit_on"),
                )
            else:
                _ic_raw = _ic_json.loads((DATA_DIR / "signal_ic_history.json").read_text())
                _seed_pooled = {
                    str(k): float(v)
                    for k, v in (_ic_raw.get("seeded_pooled_ics") or {}).items()
                }
                _seed_regime = {
                    str(k): {str(r): float(x) for r, x in d.items()}
                    for k, d in (_ic_raw.get("seeded_regime_ics") or {}).items()
                    if isinstance(d, dict)
                }
                _strat._ic_source = "seed"
            if _seed_pooled:
                _strat.update_signal_ics(_seed_pooled)
            if _seed_regime:
                _strat.update_regime_ics(_seed_regime)
            log.info(
                "[startup]   IC seeds loaded (%s): pooled=%d signals, per-regime=%d signals",
                getattr(_strat, "_ic_source", "seed"), len(_seed_pooled), len(_seed_regime),
            )
            log.info(
                "[startup]   IC weights applied: %s",
                {k: round(v, 2) for k, v in sorted(_seed_pooled.items())},
            )
        except Exception as _ic_exc:
            log.warning(
                "[startup]   IC seed load FAILED (%s: %s) — conviction filter "
                "falls back to raw composite (IC-WEIGHTING INERT)",
                type(_ic_exc).__name__, _ic_exc,
            )

    # V218.B preflight obs-delta: IC-weighting wiring probe. The whole IC-weighted
    # conviction path (pooled AND per-regime) is a no-op whenever _signal_ics is
    # empty — _compute_weighted_conviction returns the raw composite before the
    # weighting loop. update_signal_ics has historically had zero callers in the
    # training path, so this silently held for the entire V199–V218 arc and a
    # per-regime-IC bet (V218.B) was unrunnable. Surface it at cycle 0 instead of
    # after a wasted version. Grep a run log for "IC-WEIGHTING INERT".
    if _strat is not None:
        _n_ics = len(getattr(_strat, "_signal_ics", {}) or {})
        _n_regime_ics = len(getattr(_strat, "_regime_ics", {}) or {})
        if _n_ics == 0:
            log.warning(
                "[startup]   IC-WEIGHTING INERT: _signal_ics empty (0 signals) — "
                "conviction filter uses raw composite; pooled + per-regime IC "
                "weighting are both no-ops (update_signal_ics never called)"
            )
        else:
            log.info(
                "[startup]   IC-weighting ACTIVE: _signal_ics=%d signals, _regime_ics=%d signals",
                _n_ics, _n_regime_ics,
            )

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
        strat.init_trace_writer(version, str(AUDIT_DIR))

    # ── Metrics JSONL file (opened once, flushed each cycle) ──────────────
    metrics_jsonl.parent.mkdir(parents=True, exist_ok=True)
    metrics_fh = open(metrics_jsonl, "w")  # noqa: WPS515
    trade_details_fh = open(trade_details_jsonl, "w")  # noqa: WPS515

    # ── Decision snapshot writer ──────────────────────────────────────────
    from omega.core.decision_snapshot import DecisionSnapshot, DecisionWriter
    decision_writer = DecisionWriter(
        version=version, db_url=db_url or None, output_dir=str(TMP_SINK_DIR)
    )
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

    # ── V138: warm-start hooks (run before trading loop) ─────────────────
    _sig_node = getattr(victoria, "_signals", None)  # SignalGenerationNode
    _replay_node = victoria._ingestion if backtest_snapshot else None

    if _sig_node is not None:
        if _replay_node is not None:
            # Backtest mode: disable signals that would inject current-day data into
            # historical replays, causing regime contamination.
            if getattr(_active_features, "geopolitical_signals", False):
                try:
                    _sig_node.disable_geo_in_backtest()
                except Exception:
                    pass
            # signal_memory_warm_start and geometry_warm_start are disabled in backtest:
            # pre-bars come from before the trading window (different regime) and contaminate
            # conviction_trend / Ricci with wrong-era bias. Both features are live-mode only.
            if getattr(_active_features, "signal_memory_warm_start", False):
                log.info("signal_memory_warm_start skipped in backtest (regime mismatch risk)")
            if getattr(_active_features, "geometry_warm_start", False):
                log.info("geometry_warm_start skipped in backtest (regime mismatch risk)")

        else:
            # Live mode: pre-seed from recent history — same regime, safe to warm-start.
            if getattr(_active_features, "signal_memory_warm_start", False):
                log.info("signal_memory_warm_start: live mode — warm-start on first cycle history")
            if getattr(_active_features, "geometry_warm_start", False):
                log.info("geometry_warm_start: live mode — warm-start on recent bars")

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

    # V214 #3: track the prior cycle's mode so we only log transitions.
    import hashlib as _hashlib
    _prev_mode_v214: str | None = None

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

            # V248: push runtime regime into the engine for the NEXT cycle's
            # marks (1-cycle lag, causal). No-op unless the flag wired
            # regime_exit_params at engine construction.
            if _regime_exit_adaptive:
                engine.set_current_regime(regime)

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
                            round(float(t.get("mae", 0.0)), 4),  # Max Adverse Excursion
                            round(float(t.get("mfe", 0.0)), 4),  # Max Favourable Excursion
                            t.get("win_capture", ""),   # fraction of MFE captured (winners)
                            t.get("loss_capture", ""),  # fraction of MAE realised (losers)
                            t.get("exit_score", ""),    # win_capture - loss_capture
                        ])
                last_closed_count = len(closed)

                # ── V144: meta-learner trade callback ─────────────────
                if strat is not None:
                    _ml = getattr(strat, "_meta_learner", None)
                    if _ml is not None:
                        for _t in new_closed:
                            _ml.record_trade(
                                pnl=float(_t.get("pnl", 0.0)),
                                side=_t.get("side", "long"),
                                regime=regime,
                                entry_confidence=float(_t.get("conviction") or 0.5)
                                    if isinstance(_t.get("conviction"), float) else 0.5,
                                entry_value=float(
                                    getattr(strat, "_last_signals", {}).get(
                                        "_regime_w_bear_prob",
                                        getattr(strat, "_last_signals", {}).get(
                                            "_regime_w_bear", 0.3
                                        )
                                    )
                                ) if regime in ("crisis", "high_vol")
                                else abs(float(_t.get("conviction") or 0.0)),
                            )
                        if cycle_num % 50 == 0:
                            _ml.save_state()

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

            # ── V214 #4: per-cycle signal-values fingerprint ──────────────
            # Flatten every scalar signal (float, or dict-with-"value") into a
            # sorted name→value map, hash the full-precision canonical form, and
            # persist both. Two same-seed runs whose fingerprints first differ at
            # cycle C have their determinism channel active by cycle C; the value
            # map shows exactly which signal moved. Guarded — never breaks a run.
            try:
                _fp_vals: dict[str, float] = {}
                for _k, _v in last_signals.items():
                    if isinstance(_v, bool):
                        continue
                    if isinstance(_v, (int, float)):
                        _fp_vals[_k] = float(_v)
                    elif isinstance(_v, dict):
                        _vv = _v.get("value")
                        if isinstance(_vv, (int, float)) and not isinstance(_vv, bool):
                            _fp_vals[f"{_k}.value"] = float(_vv)
                _canon = ";".join(f"{_k}={_fp_vals[_k]!r}" for _k in sorted(_fp_vals))
                _fp = _hashlib.sha1(_canon.encode()).hexdigest()[:16]
                with open(signal_fingerprint_jsonl, "a") as _fpf:
                    _fpf.write(json.dumps({
                        "cycle": cycle_num,
                        "regime": regime,
                        "fp": _fp,
                        "n": len(_fp_vals),
                        "values": {_k: round(_fp_vals[_k], 12) for _k in sorted(_fp_vals)},
                    }) + "\n")
                # ── V217 #1: per-field IEEE-754-bit-exact fingerprint ─────────
                # One line per (cycle, signal_name). value_hex is the 16-char
                # big-endian IEEE double of the field — bit-exact, so two runs
                # that differ in the sub-12th decimal (the V216 dead-end) now
                # differ in value_hex and `per_field_diff.py` NAMES the field.
                # Sorted by name within the cycle; cycles emit in order, so the
                # whole file is sorted by (cycle, name) and `cmp`-comparable.
                with open(per_field_fingerprint_jsonl, "a") as _pff:
                    for _k in sorted(_fp_vals):
                        _pff.write(json.dumps({
                            "cycle": cycle_num,
                            "signal_name": _k,
                            "value_hex": struct.pack("!d", _fp_vals[_k]).hex(),
                        }) + "\n")
            except Exception as _fp_exc:
                log.debug("V214 fingerprint write failed: %s", _fp_exc)

            # ── V214 #3: mode-switch trace ────────────────────────────────
            # Log only transitions of the active mode (selector mode if the
            # selector is wired, else the regime label). Aligns two runs' mode
            # timelines to the cycle where they first disagree.
            try:
                _sel = getattr(strat, "_strategy_selector", None)
                if _sel is not None and hasattr(_sel, "mode"):
                    _mode_now = getattr(_sel.mode, "value", str(_sel.mode))
                else:
                    _mode_now = regime
                if _mode_now != _prev_mode_v214:
                    with open(mode_transitions_jsonl, "a") as _mtf:
                        _mtf.write(json.dumps({
                            "cycle": cycle_num,
                            "prev": _prev_mode_v214,
                            "new": _mode_now,
                            "regime": regime,
                            "bull_prob": round(float(last_signals.get("_bull_prob", last_signals.get("_regime_w_bull_prob", -1.0))), 6),
                            "bear_prob": round(float(last_signals.get("_bear_prob", last_signals.get("_regime_w_bear_prob", -1.0))), 6),
                            "bull_above": getattr(_sel, "_bull_prob_above", None) if _sel is not None else None,
                            "bear_above": getattr(_sel, "_bear_prob_above", None) if _sel is not None else None,
                        }) + "\n")
                    _prev_mode_v214 = _mode_now
            except Exception as _mt_exc:
                log.debug("V214 mode-trace write failed: %s", _mt_exc)

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
                            if _td is not None and hasattr(_td, "raw_composite"):
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

            # ── Per-trade signal waterfall → {TMP_SINK_DIR}/{version}_trade_details.jsonl ──
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
                        "conviction": str(_td2.conviction) if _td2 and hasattr(_td2, "conviction") else str(_trade.get("conviction", "")),
                        "conviction_score": round(float(_td2.conviction_score), 6) if _td2 and hasattr(_td2, "conviction_score") else None,
                        "filters_applied": list(_td2.filters_applied) if _td2 and hasattr(_td2, "filters_applied") else [],
                        "signal_traces": [
                            {"name": st.signal_name, "value": round(float(st.raw_value), 4), "weight": round(float(st.weight_applied), 4)}
                            for st in _td2.signal_traces
                        ] if _td2 and hasattr(_td2, "signal_traces") else [],
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

    # V225: pull the run-scoped crisis-skew fire counter (module-global on the
    # signal-generation module, mirroring _http_guard_state) for observability.
    try:
        from omega.nodes.victoria.signal_generation import _CRISIS_SKEW_STATE as _crisis_skew_state_ref
    except Exception:
        _crisis_skew_state_ref = {}

    # V232: run-scoped RV-term-structure brake counter (same module-global pattern
    # as the crisis-skew state). Read by assert_cell_identity (--expect-brake).
    try:
        from omega.nodes.victoria.signal_generation import _RV_BRAKE_STATE as _rv_brake_state_ref
    except Exception:
        _rv_brake_state_ref = {}

    results = {
        "version": version,
        # V228 resiliency #5: provenance manifest — git SHA + cache md5s +
        # resolved flags + snapshot + cell label, so this result self-certifies
        # its substrate (closes the V218 uncommitted-cache hermetic-claim class).
        "provenance": _run_provenance(version, backtest_snapshot, _active_flags),
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
            # V215: outbound HTTP attempts blocked by the frozen-cache guard. In a
            # frozen backtest this should be >0 (Deribit/carry/etc. leakers, now
            # deterministically neutralized) and is forensic only — the two
            # localized signals_advanced feeders are snapshot-fed before this. A
            # non-zero count with a deterministic spread = leaks closed; any
            # residual spread with the guard armed is definitionally non-network.
            "http_blocked_count": _http_guard_state["blocked"],
            # V223: regime-conditional IC gate tally. With regime_conditional_ic_
            # weighting ON, ic_off_cycles counts cycles whose runtime regime was
            # crisis/high_vol (IC bypassed → equal-weight composite); ic_on_cycles
            # counts the rest (IC weights applied). Confirms the gate fired as
            # designed per snapshot without a hand bisect (crisis snapshot →
            # mostly off; trend snapshot → mostly on). Integer-only, no det impact.
            "ic_on_cycles": getattr(strat, "_ic_on_cycles", 0),
            "ic_off_cycles": getattr(strat, "_ic_off_cycles", 0),
            # V229: per-ticker IC drawdown-gate bypasses. With ic_drawdown_gate_enabled
            # ON, counts conviction calls that bypassed IC to equal-weight because the
            # per-ticker realized drawdown exceeded ic_drawdown_threshold (independent of
            # the V223 categorical label). High on the crisis snapshot (the normal-labeled
            # high-drawdown cycles V223 misses), low on trend/recent. 0 when the gate is OFF.
            "ic_dd_skips": getattr(strat, "_ic_skip_cycles", 0),
            # V224: which IC table fed the weighted composite — "seed"
            # (hand-seeded pooled/per-regime) or "R3" (empirical OOS-holdout ICs
            # loaded under OMEGA_R3_ICS=1). Confirms the re-estimation path fired.
            "ic_source": getattr(strat, "_ic_source", "seed"),
            # V225: additive crisis-skew term. crisis_skew_enabled reflects the
            # parsed feature flag (NOT the env), skew_on_cycles counts node-cycles
            # where >=1 ticker got a non-zero skew term applied (proves the term
            # actually FIRED, not flag-on-but-inert). Read by assert_cell_identity.
            "crisis_skew_enabled": bool(
                getattr(getattr(strat, "features", None), "crisis_skew_enabled", False)
            ),
            "skew_on_cycles": _crisis_skew_state_ref.get("skew_on_cycles", 0),
            "skew_ticker_terms": _crisis_skew_state_ref.get("ticker_terms", 0),
            # V226: regime-gate state. crisis_skew_regime_gate_enabled reflects the
            # parsed flag; gate_accept/skip_cycles is the per-snapshot accept/skip
            # distribution (read by the gate-aware cell-identity assertion). On a
            # crisis snapshot accept dominates; on trend/recent skip dominates — that
            # asymmetry IS the no-harm proof the V225 always-on term failed.
            "crisis_skew_regime_gate_enabled": bool(
                getattr(getattr(strat, "features", None), "crisis_skew_regime_gate_enabled", False)
            ),
            "skew_gate_accept_cycles": _crisis_skew_state_ref.get("gate_accept_cycles", 0),
            "skew_gate_skip_cycles": _crisis_skew_state_ref.get("gate_skip_cycles", 0),
            # V232: additive RV-term-structure inversion brake. rv_brake_enabled
            # reflects the parsed flag; rv_brake_on_cycles counts node-cycles where
            # >=1 ticker got a non-zero brake term applied (proves it FIRED, not
            # flag-on-but-inert). Like the gated skew, a brake-ON cell may
            # legitimately fire 0 cycles when the V227 drawdown-AND-gate suppresses
            # it (the documented 2024aug behaviour) — assert_cell_identity does NOT
            # require >0 on brake-ON. Read by assert_cell_identity (--expect-brake).
            "rv_brake_enabled": bool(
                getattr(getattr(strat, "features", None), "rv_term_brake_enabled", False)
            ),
            "rv_brake_regime_gate_enabled": bool(
                getattr(getattr(strat, "features", None), "rv_term_brake_regime_gate_enabled", False)
            ),
            "rv_brake_on_cycles": _rv_brake_state_ref.get("brake_on_cycles", 0),
            "rv_brake_ticker_terms": _rv_brake_state_ref.get("ticker_terms", 0),
            "rv_brake_gate_accept_cycles": _rv_brake_state_ref.get("gate_accept_cycles", 0),
            "rv_brake_gate_skip_cycles": _rv_brake_state_ref.get("gate_skip_cycles", 0),
            # V233: crisis-term application-SITE experiment. These reflect the parsed
            # flags so assert_cell_identity (--expect-predemean) can verify each cell
            # ran the site/weight its label claims (the V224 mislabeled-control class).
            # The site reuses the crisis_skew counters above (skew_on_cycles etc.), so
            # a pre_demean cell still proves the term FIRED via skew_on_cycles>0.
            "crisis_term_predemean_enabled": bool(
                getattr(getattr(strat, "features", None), "crisis_term_predemean_enabled", False)
            ),
            "crisis_term_predemean_mode": str(
                getattr(getattr(strat, "features", None), "crisis_term_predemean_mode", "post_demean")
            ),
            "crisis_term_gated_weight": float(
                getattr(getattr(strat, "features", None), "crisis_term_gated_weight", 0.2) or 0.2
            ),
            # V234: crisis SIZING-LAYER throttle identity. Surfaces the parsed flags so
            # assert_cell_identity (--expect-throttle) can verify each cell ran the
            # throttle/factor its label claims (the V224 mislabeled-control class). The
            # throttle reuses the V227 drawdown gate; like the gated skew it may legitimately
            # fire 0 cycles on a benign window, so cell-identity checks the flag value not a
            # fired>0 count.
            "crisis_size_throttle_enabled": bool(
                getattr(getattr(strat, "features", None), "crisis_size_throttle_enabled", False)
            ),
            "crisis_size_throttle": float(
                getattr(getattr(strat, "features", None), "crisis_size_throttle", 1.0) or 1.0
            ),
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

    # V223: visible run-end IC-gate summary. The per-cycle strategy-logger trace
    # is at INFO (suppressed when the run logs at WARNING), so surface the tally
    # here on the training.* logger (visible) — confirms the regime gate fired as
    # designed without parsing JSON: a crisis snapshot should show a meaningful
    # BYPASS count, a trend/normal snapshot mostly IC-ON.
    _ic_on = getattr(strat, "_ic_on_cycles", 0)
    _ic_off = getattr(strat, "_ic_off_cycles", 0)
    _gate_on = bool(getattr(getattr(strat, "features", None), "regime_conditional_ic_weighting", False))
    log.info(
        "[V223] IC-gate summary: regime_conditional=%s → IC-ON %d cycles, "
        "BYPASS(crisis/high_vol) %d cycles (of %d)",
        _gate_on, _ic_on, _ic_off, _ic_on + _ic_off,
    )

    # V49 hard gates — compare this run against the previous version.
    baseline_label = _find_baseline_version(version)
    if baseline_label is not None:
        baseline_results = AUDIT_DIR / f"{baseline_label}_results.json"
        baseline_trades = AUDIT_DIR / f"{baseline_label}_trades.csv"
        gate_out = AUDIT_DIR / f"{version}_gate_result.json"
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
            attr_path = AUDIT_DIR / f"{version}_attribution.json"
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
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help=(
            "RNG seed for fully deterministic backtest runs. Seeds Python random, "
            "numpy, and any sklearn components. Required for reproducible "
            "version-to-version comparisons. Recommended: --seed 42"
        ),
    )
    parser.add_argument(
        "--frozen-cache",
        action="store_true",
        default=False,
        help=(
            "V207a: freeze data/macro_cache.db reads. Suppresses MacroDataCache "
            "warm_up() and disables _refresh_macro/_refresh_funding live fetches; "
            "callers read whatever rows already exist in the cache (or get None). "
            "Auto-enabled when --backtest-snapshot is set. Sets env var "
            "OMEGA_FROZEN_CACHE=1 so data_cache.py respects the freeze."
        ),
    )
    args = parser.parse_args()
    if args.backtest_snapshot and not args.frozen_cache:
        args.frozen_cache = True
    if args.frozen_cache:
        os.environ["OMEGA_FROZEN_CACHE"] = "1"

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
        seed=args.seed,
    )
