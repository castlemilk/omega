"""
omega.nodes.victoria.llm_trade_review
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Post-trade LLM analysis for Victoria.

Loads a training run's trades CSV and (optionally) decision JSONL snapshots,
then calls the `claude` CLI via llm_shell to generate a natural-language
post-mortem written to data/decision_traces/{version}_llm_review.md.

No API key required — auth is handled by the existing Claude Code login session.

Usage:
    python -m omega.nodes.victoria.llm_trade_review \\
        --version v98 \\
        --trades data/v98_trades.csv \\
        [--decisions /tmp/v98_decisions.jsonl] \\
        [--out data/decision_traces/v98_llm_review.md]

Falls back to a deterministic rule-based summary when no CLI is available.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from omega.core.llm_shell import invoke as llm_invoke
from omega.core.llm_shell import is_available as llm_available

logger = logging.getLogger("omega.nodes.victoria.llm_trade_review")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TradeRecord:
    cycle: int
    timestamp: str
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    slippage: float
    hold_cycles: int
    conviction: float
    regime: str
    sit_out_reason: str


@dataclass
class SymbolSummary:
    symbol: str
    side: str
    trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    avg_conviction: float = 0.0
    regimes: dict[str, int] = field(default_factory=dict)

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_trades(path: Path) -> list[TradeRecord]:
    trades: list[TradeRecord] = []
    if not path.exists():
        logger.warning("Trades file not found: %s", path)
        return trades
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            try:
                trades.append(
                    TradeRecord(
                        cycle=int(row["cycle"]),
                        timestamp=row.get("timestamp", ""),
                        symbol=row["symbol"],
                        side=row["side"],
                        size=float(row["size"]),
                        entry_price=float(row["entry_price"]),
                        exit_price=float(row["exit_price"]),
                        pnl=float(row["pnl"]),
                        slippage=float(row.get("slippage", 0)),
                        hold_cycles=int(row.get("hold_cycles", 0)),
                        conviction=float(row.get("conviction", 0)),
                        regime=row.get("regime", "unknown"),
                        sit_out_reason=row.get("sit_out_reason", "normal"),
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.debug("Skipping malformed row: %s — %s", row, exc)
    return trades


def _find_decisions_jsonl(version: str, hints: list[str] | None = None) -> Path | None:
    """Search common locations for the decision JSONL file."""
    _audit = os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", "").strip()
    candidates = [
        # run_training.py writes here when OMEGA_AUDIT_OUTPUT_DIR is set (V235)
        *([Path(_audit) / "tmp" / f"{version}_decisions.jsonl"] if _audit else []),
        Path(f"/tmp/{version}_decisions.jsonl"),
        Path(f"data/decision_traces/{version}.jsonl"),
        Path(f"data/decision_traces/{version}_decisions.jsonl"),
        Path(f"data/{version}_decisions.jsonl"),
    ]
    if hints:
        candidates = [Path(h) for h in hints] + candidates
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_decisions(path: Path) -> dict[int, dict]:
    """Load JSONL → dict keyed by cycle (first occurrence wins)."""
    result: dict[int, dict] = {}
    if not path.exists():
        return result
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                cycle = int(d.get("cycle", -1))
                if cycle >= 0 and cycle not in result:
                    result[cycle] = d
            except Exception:
                pass
    return result


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------


def _aggregate_by_symbol(trades: list[TradeRecord]) -> dict[str, SymbolSummary]:
    summaries: dict[str, SymbolSummary] = {}
    for t in trades:
        key = f"{t.symbol}:{t.side}"
        if key not in summaries:
            summaries[key] = SymbolSummary(symbol=t.symbol, side=t.side)
        s = summaries[key]
        s.trades += 1
        s.total_pnl += t.pnl
        if t.pnl > 0:
            s.wins += 1
        s.avg_conviction = (s.avg_conviction * (s.trades - 1) + t.conviction) / s.trades
        s.regimes[t.regime] = s.regimes.get(t.regime, 0) + 1
    return summaries


def _worst_trades(trades: list[TradeRecord], n: int = 5) -> list[TradeRecord]:
    return sorted(trades, key=lambda t: t.pnl)[:n]


def _build_review_prompt(
    version: str,
    trades: list[TradeRecord],
    summaries: dict[str, SymbolSummary],
    decisions: dict[int, dict],
) -> str:
    total_pnl = sum(t.pnl for t in trades)
    wins = sum(1 for t in trades if t.pnl > 0)
    wr = wins / len(trades) if trades else 0.0

    # Per-regime PnL
    regime_pnl: dict[str, float] = {}
    for t in trades:
        regime_pnl[t.regime] = regime_pnl.get(t.regime, 0.0) + t.pnl

    worst = _worst_trades(trades, n=5)

    # Enrich worst trades with signal data when available
    worst_details: list[str] = []
    for t in worst:
        dec = decisions.get(t.cycle, {})
        ticker_dec = dec.get("per_ticker", {}).get(t.symbol, {})
        signals_str = ""
        if ticker_dec:
            traces = ticker_dec.get("signal_traces", [])[:6]
            signals_str = "; ".join(
                f"{tr['signal_name']}={tr['raw_value']:.3f}"
                for tr in traces
                if isinstance(tr, dict)
            )
        worst_details.append(
            f"  • Cycle {t.cycle} | {t.symbol} {t.side} | PnL ${t.pnl:.2f} | "
            f"conviction={t.conviction:.3f} | regime={t.regime} | hold={t.hold_cycles}"
            + (f"\n    signals: {signals_str}" if signals_str else "")
        )

    # Per-symbol summary table
    sym_lines: list[str] = []
    for s in sorted(summaries.values(), key=lambda x: x.total_pnl):
        sym_lines.append(
            f"  {s.symbol} {s.side}: {s.trades}T {s.wins}W "
            f"{s.win_rate:.0%} WR ${s.total_pnl:+.2f} "
            f"avg_conv={s.avg_conviction:.3f} regimes={dict(s.regimes)}"
        )

    prompt = f"""You are a quantitative trading analyst reviewing a live crypto momentum strategy.

Training run: {version}
Total trades: {len(trades)}
Win rate: {wr:.1%}
Total PnL: ${total_pnl:+.2f}

Per-regime PnL:
{chr(10).join(f"  {r}: ${p:+.2f}" for r, p in sorted(regime_pnl.items()))}

Per-symbol performance (sorted worst to best):
{chr(10).join(sym_lines)}

5 worst individual trades:
{chr(10).join(worst_details)}

Write a concise post-mortem covering:
1. **Root cause of losses** — which symbols/regimes/signals failed and why
2. **What worked** — top 2-3 winning patterns worth preserving
3. **Signal diagnosis** — which signals appear to be misfiring based on the worst trades
4. **Actionable fixes** — 3 specific changes to strategy parameters or blacklists with exact values
5. **One-line verdict** — should {version} be deployed or iterated on?

Write in markdown. Be specific about cycles, symbols, and conviction values where relevant.
Respond in 400-600 words."""

    return prompt


# ---------------------------------------------------------------------------
# Main review entry point
# ---------------------------------------------------------------------------


def run_review(
    version: str,
    trades_path: Path,
    decisions_path: Path | None = None,
    out_path: Path | None = None,
) -> Path:
    """
    Run LLM post-mortem for one training version.
    Returns the path to the written markdown file.
    """
    trades = _load_trades(trades_path)
    if not trades:
        raise ValueError(f"No trades found at {trades_path}")

    decisions: dict[int, dict] = {}
    if decisions_path and decisions_path.exists():
        decisions = _load_decisions(decisions_path)
    else:
        auto_path = _find_decisions_jsonl(version)
        if auto_path:
            decisions = _load_decisions(auto_path)
            logger.info("Auto-detected decisions at %s (%d cycles)", auto_path, len(decisions))

    summaries = _aggregate_by_symbol(trades)

    prompt = _build_review_prompt(version, trades, summaries, decisions)

    if llm_available():
        logger.info("Calling Claude CLI (deep) for %s post-mortem…", version)
        review_text = llm_invoke(prompt, model="deep")
        if not review_text:
            logger.warning("LLM CLI returned empty — falling back to rule-based summary")
            review_text = _rule_based_summary(version, trades, summaries)
            review_text += "\n\n> ⚠️ LLM call failed — showing rule-based fallback."
    else:
        logger.warning("No LLM CLI available — producing rule-based summary")
        review_text = _rule_based_summary(version, trades, summaries)

    # Determine output path
    if out_path is None:
        out_dir = Path("data/decision_traces")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{version}_llm_review.md"

    _write_report(out_path, version, trades, review_text)
    logger.info("LLM review written to %s", out_path)
    return out_path


def _rule_based_summary(
    version: str,
    trades: list[TradeRecord],
    summaries: dict[str, SymbolSummary],
) -> str:
    """Fallback when no LLM key — deterministic stats summary."""
    total_pnl = sum(t.pnl for t in trades)
    wins = sum(1 for t in trades if t.pnl > 0)
    wr = wins / len(trades) if trades else 0.0

    regime_pnl: dict[str, float] = {}
    for t in trades:
        regime_pnl[t.regime] = regime_pnl.get(t.regime, 0.0) + t.pnl

    worst = _worst_trades(trades, n=3)
    best = sorted(trades, key=lambda t: t.pnl, reverse=True)[:3]

    lines = [
        "## Summary",
        "",
        f"**Total trades:** {len(trades)} | **Win rate:** {wr:.1%} | **Total PnL:** ${total_pnl:+.2f}",
        "",
        "## Per-regime PnL",
        *[f"- {r}: ${p:+.2f}" for r, p in sorted(regime_pnl.items(), key=lambda x: x[1])],
        "",
        "## Worst 3 Trades",
        *[
            f"- Cycle {t.cycle} | {t.symbol} {t.side} | PnL ${t.pnl:.2f} | "
            f"conviction={t.conviction:.3f} | regime={t.regime} | hold={t.hold_cycles}"
            for t in worst
        ],
        "",
        "## Best 3 Trades",
        *[
            f"- Cycle {t.cycle} | {t.symbol} {t.side} | PnL ${t.pnl:.2f} | "
            f"conviction={t.conviction:.3f} | regime={t.regime} | hold={t.hold_cycles}"
            for t in best
        ],
        "",
        "## Per-Symbol Summary",
        *[
            f"- {s.symbol} {s.side}: {s.trades}T {s.wins}W {s.win_rate:.0%} WR ${s.total_pnl:+.2f}"
            for s in sorted(summaries.values(), key=lambda x: x.total_pnl)
        ],
        "",
        "_Rule-based summary (set ANTHROPIC_API_KEY for LLM analysis)._",
    ]
    return "\n".join(lines)


def _write_report(out_path: Path, version: str, trades: list[TradeRecord], body: str) -> None:
    total_pnl = sum(t.pnl for t in trades)
    wins = sum(1 for t in trades if t.pnl > 0)
    wr = wins / len(trades) if trades else 0.0

    header = (
        f"# LLM Trade Review — {version}\n\n"
        f"_Generated: {datetime.now(UTC).isoformat()}_\n\n"
        f"**Summary:** {len(trades)} trades | {wr:.1%} WR | ${total_pnl:+.2f} PnL\n\n"
        "---\n\n"
    )
    out_path.write_text(header + body + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="LLM post-trade review for Victoria")
    parser.add_argument("--version", required=True, help="Training version e.g. v98")
    parser.add_argument("--trades", help="Path to trades CSV (default: data/{version}_trades.csv)")
    parser.add_argument("--decisions", help="Path to decisions JSONL (optional)")
    parser.add_argument("--out", help="Output markdown path")
    args = parser.parse_args()

    version = args.version
    trades_path = Path(args.trades) if args.trades else Path(f"data/{version}_trades.csv")
    decisions_path = Path(args.decisions) if args.decisions else None
    out_path = Path(args.out) if args.out else None

    out = run_review(version, trades_path, decisions_path, out_path)
    print(f"Review written to: {out}")


if __name__ == "__main__":
    main()
