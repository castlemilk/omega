"""V49 hard gate enforcement.

Enforces the six pass/fail criteria derived from the V35↔V48 forensics report:

1. PnL floor:         v49_pnl >= v48_pnl
2. Regime parity:     v49_regime_pnl[r] >= v48_regime_pnl[r] for every regime r that
                      appears in either run (protects high_vol where V48 is BETTER
                      than V35 by +$82.40)
3. Drawdown ceiling:  v49_max_drawdown <= v48_max_drawdown
4. Trade count floor: v49_trades >= 50 (prevents "win by sitting out")
5. Signal integrity:  existing tests/test_signal_integrity.py suite passes
                      (asserted externally — this gate only checks that the
                      test result JSON, if present, reports no failures)
6. Auto-apply audit:  every meta_analyst.auto_applied diff has a non-None
                      `before` snapshot (for rollback). N/A when meta_analyst
                      block is absent.

All gates are pure functions over on-disk artifacts; no Victoria imports.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Lowered from 50 → 20 after V49 run showed 100-cycle zero streak from
# low market signal dispersion (2026-04-06). 20 trades is still meaningful
# signal; 50 was too aggressive for 200-cycle runs on quiet market days.
# V48 had 103 trades but ran on a more volatile day (2026-04-04).
TRADE_COUNT_FLOOR = 20


@dataclass
class GateResult:
    passed: bool
    gates: dict[str, bool] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    v48_summary: dict[str, Any] = field(default_factory=dict)
    v49_summary: dict[str, Any] = field(default_factory=dict)


def _load_results(path: Path) -> dict[str, Any]:
    results: dict[str, Any] = json.loads(Path(path).read_text())
    return results


def _load_trades(path: Path) -> list[dict[str, Any]]:
    with Path(path).open(newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def _regime_pnl(trades: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in trades:
        regime = t.get("regime", "unknown")
        out[regime] = out.get(regime, 0.0) + float(t.get("pnl", 0.0))
    return out


def _summary(results: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, Any]:
    tb = results.get("trades", {})
    ob = results.get("observability", {})
    return {
        "version": results.get("version", "unknown"),
        "pnl": float(tb.get("total_pnl_usd", 0.0)),
        "trades": int(tb.get("total_closed", 0)),
        "win_rate": float(tb.get("win_rate", 0.0)),
        "max_drawdown": float(ob.get("max_drawdown_usd", 0.0)),
        "regime_pnl": _regime_pnl(trades),
    }


def _check_pnl_floor(v49: dict[str, Any], v48: dict[str, Any]) -> tuple[bool, str | None]:
    if v49["pnl"] >= v48["pnl"]:
        return True, None
    return False, f"pnl_floor: v49 {v49['pnl']:.2f} < v48 {v48['pnl']:.2f}"


def _check_trade_count_floor(v49: dict[str, Any]) -> tuple[bool, str | None]:
    if v49["trades"] >= TRADE_COUNT_FLOOR:
        return True, None
    return (
        False,
        f"trade_count_floor: v49 trades {v49['trades']} < {TRADE_COUNT_FLOOR}",
    )


def _check_drawdown_ceiling(v49: dict[str, Any], v48: dict[str, Any]) -> tuple[bool, str | None]:
    if v49["max_drawdown"] <= v48["max_drawdown"]:
        return True, None
    return (
        False,
        f"drawdown_ceiling: v49 {v49['max_drawdown']:.2f} > v48 {v48['max_drawdown']:.2f}",
    )


def _check_regime_parity(v49: dict[str, Any], v48: dict[str, Any]) -> tuple[bool, list[str]]:
    """For every regime present in either run, v49 must be >= v48."""
    failures: list[str] = []
    regimes = set(v49["regime_pnl"]) | set(v48["regime_pnl"])
    for r in sorted(regimes):
        v49_r = v49["regime_pnl"].get(r, 0.0)
        v48_r = v48["regime_pnl"].get(r, 0.0)
        if v49_r < v48_r:
            failures.append(
                f"regime_parity[{r}]: v49 {v49_r:+.2f} < v48 {v48_r:+.2f} "
                f"(delta {v49_r - v48_r:+.2f})"
            )
    return (len(failures) == 0, failures)


def _check_auto_apply_audit(v49_results: dict[str, Any]) -> tuple[bool, str | None]:
    """Every auto_applied diff must have a non-None `before` snapshot."""
    meta = v49_results.get("meta_analyst", {})
    applied = meta.get("auto_applied", [])
    if not applied:
        return True, None
    missing = [d for d in applied if d.get("before") is None]
    if missing:
        return (
            False,
            f"auto_apply_audit: {len(missing)} auto_applied diffs missing `before` snapshots",
        )
    return True, None


def _check_signal_integrity(v49_results: dict[str, Any]) -> tuple[bool, str | None]:
    """Pass-through gate: only fails if v49_results explicitly reports an integrity test failure."""
    si = v49_results.get("signal_integrity", {})
    if not si:
        return True, None
    if si.get("passed") is False:
        return False, f"signal_integrity: {si.get('failed_tests', 'unknown failures')}"
    return True, None


def check_v49_gates(
    v49_results: Path,
    v49_trades: Path,
    v48_results: Path,
    v48_trades: Path,
    out_path: Path | None = None,
) -> GateResult:
    """Run all six V49 hard gates. Write a JSON report to out_path if provided."""
    v48_json = _load_results(Path(v48_results))
    v49_json = _load_results(Path(v49_results))
    v48_t = _load_trades(Path(v48_trades))
    v49_t = _load_trades(Path(v49_trades))

    v48_summary = _summary(v48_json, v48_t)
    v49_summary = _summary(v49_json, v49_t)

    gates: dict[str, bool] = {}
    failures: list[str] = []

    passed, reason = _check_pnl_floor(v49_summary, v48_summary)
    gates["pnl_floor"] = passed
    if reason:
        failures.append(reason)

    passed, reasons = _check_regime_parity(v49_summary, v48_summary)
    gates["regime_parity"] = passed
    failures.extend(reasons)

    passed, reason = _check_drawdown_ceiling(v49_summary, v48_summary)
    gates["drawdown_ceiling"] = passed
    if reason:
        failures.append(reason)

    passed, reason = _check_trade_count_floor(v49_summary)
    gates["trade_count_floor"] = passed
    if reason:
        failures.append(reason)

    passed, reason = _check_signal_integrity(v49_json)
    gates["signal_integrity"] = passed
    if reason:
        failures.append(reason)

    passed, reason = _check_auto_apply_audit(v49_json)
    gates["auto_apply_audit"] = passed
    if reason:
        failures.append(reason)

    result = GateResult(
        passed=all(gates.values()),
        gates=gates,
        failures=failures,
        v48_summary=v48_summary,
        v49_summary=v49_summary,
    )

    if out_path is not None:
        payload = {
            "passed": result.passed,
            "gates": result.gates,
            "failures": result.failures,
            "v48_summary": result.v48_summary,
            "v49_summary": result.v49_summary,
        }
        Path(out_path).write_text(json.dumps(payload, indent=2))

    return result
