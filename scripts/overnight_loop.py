#!/usr/bin/env python3
"""
scripts/overnight_loop.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Autonomous overnight iteration loop for Victoria training.

Waits for vN to finish, runs postmortem, adjusts DEAD_SIGNALS / suppression
lists based on evidence, commits, launches vN+1. Logs each iteration to
data/overnight_iteration_log.md.

Usage:
    python3 scripts/overnight_loop.py --start v117 --max-versions 10

Logic per iteration:
  1. Wait for current version process to finish
  2. Run postmortem, parse signal scorecard
  3. Check per-symbol PnL from trades CSV
  4. For any signal with acc < 40% and NOT already in DEAD_SIGNALS → add it
  5. For any symbol+direction with total PnL < -$30 across run → add to suppression
  6. Patch signal_generation.py DEAD_SIGNALS and strategy.py SHORT/LONG_SUPPRESSED
  7. Commit, launch next version, log results
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
LOG_FILE = ROOT / "data" / "overnight_iteration_log.md"
SIGNAL_GEN = ROOT / "omega" / "nodes" / "victoria" / "signal_generation.py"
STRATEGY = ROOT / "omega" / "nodes" / "victoria" / "strategy.py"
TRACES_DIR = ROOT / "data" / "activation_traces"
TRAINING_SCRIPT = ROOT / "scripts" / "run_training.py"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("overnight_loop")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FLIP_THRESHOLD = 40.0        # signal accuracy below this → flip
SUPPRESS_THRESHOLD = -30.0   # per-symbol-direction PnL below this → suppress
MIN_SIGNAL_APPEARANCES = 50  # GUARDRAIL: need ≥50 trades before flipping any signal
MIN_SUPPRESS_VERSIONS = 2    # GUARDRAIL: need evidence in ≥2 versions before suppressing
MIN_ACTIVE_PAIRS = 3         # GUARDRAIL: never suppress if it would leave <3 active sym/dir pairs

CYCLES = 200
SLEEP = 10
FEATURES = "v115_full_vectors"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_signal_scorecard(version: str) -> dict[str, dict]:
    """
    Run postmortem and parse signal scorecard.

    Returns: {signal_name: {"right": int, "wrong": int, "acc": float}}
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "postmortem.py"), "--version", version],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    output = result.stdout + result.stderr
    # Strip ANSI colour codes
    output = re.sub(r"\x1b\[[0-9;]*m", "", output)

    scores: dict[str, dict] = {}
    in_scorecard = False
    for line in output.splitlines():
        if "SIGNAL SCORECARD" in line:
            in_scorecard = True
            continue
        if in_scorecard and "REGIME BREAKDOWN" in line:
            break
        if not in_scorecard:
            continue
        # e.g.: "  whale_print        7     6  53.8%    n/a    n/a   n/a"
        m = re.match(r"\s+(\S+)\s+(\d+)\s+(\d+)\s+([\d.]+)%", line)
        if m:
            name, right, wrong, acc = m.groups()
            scores[name] = {
                "right": int(right),
                "wrong": int(wrong),
                "acc": float(acc),
                "n": int(right) + int(wrong),
            }
    return scores


def parse_regime_breakdown(version: str) -> dict[str, dict]:
    """Parse regime breakdown from postmortem output."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "postmortem.py"), "--version", version],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    output = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr)

    regimes: dict[str, dict] = {}
    in_regime = False
    for line in output.splitlines():
        if "REGIME BREAKDOWN" in line:
            in_regime = True
            continue
        if not in_regime:
            continue
        # e.g. "  crisis     14    28.6%     -38.97     -2.78"
        m = re.match(r"\s+(\w+)\s+(\d+)\s+([\d.]+)%\s+([-\d.]+)\s+([-\d.]+)", line)
        if m:
            regime, trades, wr, total_pnl, avg_pnl = m.groups()
            regimes[regime] = {
                "trades": int(trades),
                "wr": float(wr),
                "total_pnl": float(total_pnl),
                "avg_pnl": float(avg_pnl),
            }
    return regimes


def parse_symbol_pnl(version: str) -> dict[tuple[str, str], float]:
    """
    Parse per (symbol, side) total PnL from trades CSV.

    Returns: {(symbol, side): total_pnl}
    """
    trades_file = ROOT / "data" / f"{version}_trades.csv"
    if not trades_file.exists():
        return {}

    pnl: dict[tuple[str, str], float] = defaultdict(float)
    with open(trades_file) as f:
        for row in csv.DictReader(f):
            key = (row["symbol"], row["side"])
            pnl[key] += float(row["pnl"])
    return dict(pnl)


def get_summary(version: str) -> dict:
    """Read final results for a version."""
    results_file = ROOT / "data" / f"{version}_results.json"
    if not results_file.exists():
        return {}
    with open(results_file) as f:
        data = json.load(f)
    # Try both flat and nested schema
    trades = data.get("trades", data)
    return {
        "pnl": trades.get("total_pnl", 0),
        "wr": trades.get("win_rate", 0),
        "n_trades": trades.get("n_trades", 0),
        "pf": trades.get("profit_factor", 0),
    }


# ---------------------------------------------------------------------------
# Code patching
# ---------------------------------------------------------------------------

def read_current_dead_signals() -> set[str]:
    """Parse current _dead_signals from signal_generation.py (linter lowercased it)."""
    src = SIGNAL_GEN.read_text()
    # Match case-insensitively — linter may rename _DEAD_SIGNALS → _dead_signals
    m = re.search(r"_dead_signals\s*=\s*\{([^}]+)\}", src, re.DOTALL | re.IGNORECASE)
    if not m:
        return set()
    block = m.group(1)
    return set(re.findall(r'"(\w+)"', block))


def read_current_suppressed(var_name: str) -> set[str]:
    """Parse current SHORT_SUPPRESSED or LONG_SUPPRESSED from strategy.py."""
    src = STRATEGY.read_text()
    m = re.search(rf"{var_name}\s*=\s*\{{([^}}]+)\}}", src, re.DOTALL)
    if not m:
        return set()
    block = m.group(1)
    return set(re.findall(r'"(\w+)"', block))


def patch_dead_signals(new_signals: dict[str, str]) -> bool:
    """
    Add new_signals to _dead_signals in signal_generation.py.

    new_signals: {signal_name: comment_reason}
    Returns True if file was changed.
    """
    if not new_signals:
        return False

    src = SIGNAL_GEN.read_text()
    m = re.search(r"(_dead_signals\s*=\s*\{)([^}]+)(\})", src, re.DOTALL | re.IGNORECASE)
    if not m:
        logger.error("Could not find _dead_signals block")
        return False

    prefix, block, suffix = m.group(1), m.group(2), m.group(3)
    version_label = f"v{_current_version_num()}_postmortem"

    # Build new lines
    new_lines = [f"                    # {version_label}: accuracy below 40%"]
    for sig, reason in new_signals.items():
        new_lines.append(f'                    "{sig}",  # {reason}')

    new_block = block.rstrip() + "\n" + "\n".join(new_lines) + "\n                "
    new_src = src[: m.start()] + prefix + new_block + suffix + src[m.end():]
    SIGNAL_GEN.write_text(new_src)
    return True


def _current_version_num() -> str:
    """Read current training version from data/training_version.txt."""
    vfile = ROOT / "data" / "training_version.txt"
    if vfile.exists():
        return vfile.read_text().strip().lstrip("v")
    return "?"


def patch_suppressed(var_name: str, new_tickers: dict[str, str]) -> bool:
    """
    Add new_tickers to SHORT_SUPPRESSED or LONG_SUPPRESSED in strategy.py.

    new_tickers: {ticker: comment_reason}
    Returns True if file was changed.
    """
    if not new_tickers:
        return False

    src = STRATEGY.read_text()
    m = re.search(rf"({var_name}\s*=\s*\{{)([^}}]+)(\}})", src, re.DOTALL)
    if not m:
        logger.error("Could not find %s block", var_name)
        return False

    prefix, block, suffix = m.group(1), m.group(2), m.group(3)
    new_lines = []
    for ticker, reason in new_tickers.items():
        new_lines.append(f'                    "{ticker}",  # {reason}')

    new_block = block.rstrip() + "\n" + "\n".join(new_lines) + "\n                "
    new_src = src[: m.start()] + prefix + new_block + suffix + src[m.end():]
    STRATEGY.write_text(new_src)
    return True


def syntax_check() -> bool:
    """Return True if both files parse cleanly."""
    import ast
    for f in [SIGNAL_GEN, STRATEGY]:
        try:
            ast.parse(f.read_text())
        except SyntaxError as e:
            logger.error("Syntax error in %s: %s", f, e)
            return False
    return True


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git_commit(message: str) -> str:
    """Stage modified files, commit, return short SHA."""
    subprocess.run(
        ["git", "add",
         str(SIGNAL_GEN.relative_to(ROOT)),
         str(STRATEGY.relative_to(ROOT))],
        cwd=str(ROOT), check=True,
    )
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Nothing to commit is OK
        if "nothing to commit" in result.stdout + result.stderr:
            logger.info("git: nothing to commit")
            return subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(ROOT), capture_output=True, text=True,
            ).stdout.strip()
        logger.error("git commit failed: %s", result.stderr)
        return "?"
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(ROOT), capture_output=True, text=True,
    ).stdout.strip()
    return sha


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------

def wait_for_version(version: str, poll_interval: int = 30) -> bool:
    """
    Wait until data/{version}_results.json exists OR the training process
    exits.  Returns True when results are available.
    """
    results_file = ROOT / "data" / f"{version}_results.json"
    logger.info("Waiting for %s to finish…", version)
    while True:
        if results_file.exists():
            logger.info("%s results found", version)
            return True
        time.sleep(poll_interval)


def launch_version(version: str) -> int:
    """Launch training for version and return PID."""
    cmd = [
        sys.executable,
        str(TRAINING_SCRIPT),
        "--version", version,
        "--cycles", str(CYCLES),
        "--sleep", str(SLEEP),
    ]
    env = os.environ.copy()
    env["VICTORIA_FEATURES"] = FEATURES
    log_path = Path(f"/tmp/{version}.log")
    with open(log_path, "w") as log_f:
        proc = subprocess.Popen(
            cmd, cwd=str(ROOT), env=env,
            stdout=log_f, stderr=log_f,
        )
    logger.info("Launched %s PID=%d (log: %s)", version, proc.pid, log_path)
    return proc.pid


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def append_log(content: str) -> None:
    """Append a block to the overnight iteration log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(content + "\n")


def log_iteration(
    version: str,
    summary: dict,
    scorecard: dict[str, dict],
    regime: dict[str, dict],
    new_dead: dict[str, str],
    new_short_supp: dict[str, str],
    new_long_supp: dict[str, str],
    commit_sha: str,
    next_version: str,
    next_pid: int,
) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"\n## {version} → {next_version}  [{ts}]",
        f"",
        f"**Result:** PnL={summary.get('pnl', 0):.2f}  "
        f"WR={summary.get('wr', 0):.1%}  "
        f"trades={summary.get('n_trades', 0)}  "
        f"PF={summary.get('pf', 0):.3f}",
        f"",
        f"**Regime breakdown:**",
    ]
    for r, v in regime.items():
        lines.append(
            f"  - {r}: {v['trades']} trades, {v['wr']:.1f}% WR, PnL={v['total_pnl']:.2f}"
        )
    lines += [
        f"",
        f"**Signal scorecard (key signals):**",
    ]
    for name, d in sorted(scorecard.items(), key=lambda x: x[1]["acc"]):
        flag = ""
        if d["acc"] < 40 and d["n"] >= MIN_SIGNAL_APPEARANCES:
            flag = " ← FLIP NEEDED"
        elif d["acc"] > 60 and d["n"] >= MIN_SIGNAL_APPEARANCES:
            flag = " ← ALPHA"
        if flag or name in new_dead:
            lines.append(f"  - {name}: {d['acc']:.1f}% (n={d['n']}){flag}")

    if new_dead:
        lines += ["", f"**Signals flipped in {next_version}:** " + ", ".join(new_dead.keys())]
    if new_short_supp:
        lines += [f"**Short-suppressed in {next_version}:** " + ", ".join(new_short_supp.keys())]
    if new_long_supp:
        lines += [f"**Long-suppressed in {next_version}:** " + ", ".join(new_long_supp.keys())]
    if not new_dead and not new_short_supp and not new_long_supp:
        lines += ["", f"**No changes** — all signals within bounds, no new suppression needed"]

    lines += [
        f"",
        f"**Commit:** `{commit_sha}`  **Next:** {next_version} PID={next_pid}",
        f"",
        f"---",
    ]
    append_log("\n".join(lines))


# ---------------------------------------------------------------------------
# Core decision logic
# ---------------------------------------------------------------------------

def count_active_pairs(current_short: set[str], current_long: set[str]) -> int:
    """Count currently active (symbol, direction) pairs after applying suppression."""
    base_symbols = ["ETHUSDT", "NEARUSDT", "ARBUSDT", "ADAUSDT", "BTCUSDT"]
    active = 0
    for sym in base_symbols:
        if sym not in current_short:
            active += 1
        if sym not in current_long:
            active += 1
    return active


def compute_adjustments(
    version: str,
    scorecard: dict[str, dict],
    symbol_pnl: dict[tuple[str, str], float],
    all_version_pnls: dict[str, dict[tuple[str, str], float]],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """
    Compute what to add to DEAD_SIGNALS, _short_suppressed, _long_suppressed.

    Guardrails:
      - Signal flip: requires ≥50 appearances in this version
      - Symbol suppression: requires bad PnL in ≥2 separate versions
      - Never suppress if it would leave fewer than MIN_ACTIVE_PAIRS active pairs

    Returns:
        new_dead_signals: {name: reason}
        new_short_suppressed: {ticker: reason}
        new_long_suppressed:  {ticker: reason}
    """
    current_dead = read_current_dead_signals()
    current_short = read_current_suppressed("_short_suppressed")
    current_long = read_current_suppressed("_long_suppressed")

    new_dead: dict[str, str] = {}
    for sig, d in scorecard.items():
        if d["n"] < MIN_SIGNAL_APPEARANCES:
            logger.info(
                "GUARDRAIL skip flip %s — %d appearances (need %d)",
                sig, d["n"], MIN_SIGNAL_APPEARANCES,
            )
            continue
        if d["acc"] < FLIP_THRESHOLD and sig not in current_dead:
            new_dead[sig] = f"{d['acc']:.1f}% (n={d['n']}) — {version} postmortem"

    new_short: dict[str, str] = {}
    new_long: dict[str, str] = {}
    for (sym, side), pnl in symbol_pnl.items():
        if pnl >= SUPPRESS_THRESHOLD:
            continue
        # Multi-version evidence check
        bad_versions = [
            v for v, vpnl in all_version_pnls.items()
            if vpnl.get((sym, side), 0) < SUPPRESS_THRESHOLD
        ]
        if len(bad_versions) < MIN_SUPPRESS_VERSIONS:
            logger.info(
                "GUARDRAIL skip suppress %s %s — only %d version(s) of evidence (need %d)",
                sym, side, len(bad_versions), MIN_SUPPRESS_VERSIONS,
            )
            continue
        if side == "short" and sym not in current_short:
            projected = current_short | {sym}
            if count_active_pairs(projected, current_long) >= MIN_ACTIVE_PAIRS:
                new_short[sym] = (
                    f"{version}+prior ({','.join(bad_versions)}): {pnl:.2f} PnL → suppress shorts"
                )
            else:
                logger.info("GUARDRAIL skip %s short — would leave <3 active pairs", sym)
        elif side == "long" and sym not in current_long:
            projected = current_long | {sym}
            if count_active_pairs(current_short, projected) >= MIN_ACTIVE_PAIRS:
                new_long[sym] = (
                    f"{version}+prior ({','.join(bad_versions)}): {pnl:.2f} PnL → suppress longs"
                )
            else:
                logger.info("GUARDRAIL skip %s long — would leave <3 active pairs", sym)

    return new_dead, new_short, new_long


def version_increment(version: str) -> str:
    """v117 → v118"""
    m = re.match(r"v(\d+)", version)
    if not m:
        raise ValueError(f"Can't parse version: {version}")
    return f"v{int(m.group(1)) + 1}"


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_loop(start_version: str, max_iterations: int) -> None:
    current = start_version

    # Write log header if file doesn't exist
    if not LOG_FILE.exists():
        append_log(
            "# Victoria Overnight Iteration Log\n\n"
            "Autonomous loop: wait → postmortem → adjust → launch → repeat.\n\n"
            f"Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  "
            f"start={start_version}  features={FEATURES}\n\n---"
        )

    for i in range(max_iterations):
        logger.info("=== Iteration %d/%d: %s ===", i + 1, max_iterations, current)

        # 1. Wait for current version
        wait_for_version(current)
        time.sleep(5)  # brief settle to ensure CSV is flushed

        # 2. Parse results
        summary = get_summary(current)
        logger.info(
            "%s DONE: PnL=%.2f WR=%.1f%% trades=%d PF=%.3f",
            current,
            summary.get("pnl", 0),
            summary.get("wr", 0) * 100,
            summary.get("n_trades", 0),
            summary.get("pf", 0),
        )

        # 3. Postmortem
        logger.info("Running postmortem for %s…", current)
        scorecard = parse_signal_scorecard(current)
        regime = parse_regime_breakdown(current)
        symbol_pnl = parse_symbol_pnl(current)

        logger.info(
            "Scorecard: %d signals. Regime: %s",
            len(scorecard),
            {r: f"{v['total_pnl']:.0f}" for r, v in regime.items()},
        )

        # Collect multi-version symbol PnL for guardrail checks
        # Look back at the last 3 completed versions (excluding current)
        all_version_pnls: dict[str, dict[tuple[str, str], float]] = {}
        m = re.match(r"v(\d+)", current)
        if m:
            cur_num = int(m.group(1))
            for lookback in range(1, 4):
                prev_v = f"v{cur_num - lookback}"
                prev_pnl = parse_symbol_pnl(prev_v)
                if prev_pnl:
                    all_version_pnls[prev_v] = prev_pnl
        all_version_pnls[current] = symbol_pnl

        # 4. Compute adjustments
        new_dead, new_short, new_long = compute_adjustments(
            current, scorecard, symbol_pnl, all_version_pnls
        )

        logger.info(
            "Adjustments → dead=%s short_supp=%s long_supp=%s",
            list(new_dead), list(new_short), list(new_long),
        )

        # 5. Patch files
        changed = False
        if new_dead:
            if patch_dead_signals(new_dead):
                changed = True
                logger.info("Patched DEAD_SIGNALS: %s", list(new_dead))
        if new_short:
            if patch_suppressed("_short_suppressed", new_short):
                changed = True
                logger.info("Patched _short_suppressed: %s", list(new_short))
        if new_long:
            if patch_suppressed("_long_suppressed", new_long):
                changed = True
                logger.info("Patched _long_suppressed: %s", list(new_long))

        # 6. Syntax check
        if not syntax_check():
            logger.error("Syntax check failed — aborting loop")
            append_log(f"\n## ⚠️ LOOP ABORTED at {current} — syntax check failed\n")
            break

        # 7. Commit (even if no changes — records the iteration)
        next_version = version_increment(current)
        if changed:
            msg = (
                f"feat(victoria): {next_version} evidence-based adjustments from {current} postmortem\n\n"
                + (f"DEAD_SIGNALS added: {', '.join(new_dead)}\n" if new_dead else "")
                + (f"SHORT_SUPPRESSED added: {', '.join(new_short)}\n" if new_short else "")
                + (f"LONG_SUPPRESSED added: {', '.join(new_long)}\n" if new_long else "")
                + f"\n{current}: PnL={summary.get('pnl', 0):.2f} WR={summary.get('wr', 0):.1%} "
                f"trades={summary.get('n_trades', 0)} PF={summary.get('pf', 0):.3f}"
            )
        else:
            msg = (
                f"chore(victoria): {next_version} — no signal changes from {current} postmortem\n\n"
                f"{current}: PnL={summary.get('pnl', 0):.2f} WR={summary.get('wr', 0):.1%} "
                f"trades={summary.get('n_trades', 0)} PF={summary.get('pf', 0):.3f} — all signals within bounds"
            )
        sha = git_commit(msg)
        logger.info("Committed: %s", sha)

        # 8. Launch next version
        next_pid = launch_version(next_version)

        # 9. Log iteration
        log_iteration(
            version=current,
            summary=summary,
            scorecard=scorecard,
            regime=regime,
            new_dead=new_dead,
            new_short_supp=new_short,
            new_long_supp=new_long,
            commit_sha=sha,
            next_version=next_version,
            next_pid=next_pid,
        )

        logger.info("Launched %s (PID %d). Moving to next iteration.", next_version, next_pid)
        current = next_version

    logger.info("Loop complete after %d iterations. Final version: %s", max_iterations, current)
    append_log(
        f"\n## Loop ended\n\nFinal version: {current}  "
        f"Iterations: {max_iterations}  "
        f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous overnight Victoria training loop")
    parser.add_argument("--start", default="v117", help="Version currently running (default: v117)")
    parser.add_argument("--max-versions", type=int, default=10, help="Max iterations (default: 10)")
    args = parser.parse_args()

    run_loop(start_version=args.start, max_iterations=args.max_versions)
