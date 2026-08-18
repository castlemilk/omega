"""Standing-baseline gates — the post-run ship/no-ship record for a Victoria cell.

Why this module exists (and why `v49_gates.py` is retired in place)
-------------------------------------------------------------------

`omega/eval/v49_gates.py` compared a run against its **N-1 sibling cell** — the
same label with the numeric component decremented. Three things went wrong with
that, all confirmed against the real corpus in `data/` on 2026-08-18:

1. **It silently resolved nothing.** `_find_baseline_version` requires an exact
   suffix match, so as soon as cells were renamed (from 2026-06-24 on) 39 of the
   51 most recent labels resolved to `None`. `run_training.py` then logged a
   warning and wrote **no gate file at all** — a skip that looked like silence,
   not like a failure.
2. **When it did resolve, it compared a run to itself.** Deterministic replay
   cells produce byte-identical numbers under two labels; 18 gate files in
   `data/` carry identical baseline and candidate summaries, i.e. a vacuous
   all-green board.
3. **Three of its "six hard gates" could not fail.** `signal_integrity` and
   `auto_apply_audit` return True when their input block is absent (it always
   is), and `max_drawdown` defaults to 0.0, so `drawdown_ceiling` compared
   `0.0 <= 0.0` forever. Only `pnl_floor` and `trade_count_floor` were real.

The discipline that *was* actually being enforced lives in the training journal:
every pre-registration since V240 carries a **standing baseline** line — e.g.
`training_log/V271.md:6`, "Standing baseline (MUST NOT MOVE): crisis +$599 /
trend +$2,997 / recent +$30". Those are per-regime-family PnL levels for the
whole campaign, not a sibling diff. This module gates against **those**, read
from `data/standing_baseline.json` (config, committed, provenanced).

Verdict vocabulary (a first-class field, not inferred from `passed`)
--------------------------------------------------------------------

``PASS``          every evaluated gate passed.
``FAIL``          at least one evaluated gate failed.
``NO_BASELINE``   the cell's regime family could not be resolved, so the family
                  PnL floor is *not evaluated*. Loud, and the file is still
                  written — this is the case the old code turned into silence.
``NO_OP``         the run reproduced a prior run rather than measuring anything
                  new (frozen cache + an N-1 sibling with an identical trade
                  fingerprint, or identical trade count and PnL). This is the
                  18-vacuous-file case, named instead of rendered green.
``ERROR``         written by the caller when gate evaluation itself raised.

Precedence: ``FAIL`` > ``NO_BASELINE`` > ``NO_OP`` > ``PASS``. A real gate
failure is never masked by a no-op; a no-op is never dressed up as a pass.

Per-gate status is ``pass`` / ``fail`` / ``not_evaluated``. **A gate whose input
block is absent reports `not_evaluated` and NEVER `pass`.** That single rule is
what makes this board honest where the v49 board was not.

All functions here are pure over on-disk artifacts. No Victoria imports, no
strategy code, no side effects other than the optional report write.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_BASELINE_PATH",
    "TRADE_COUNT_FLOOR",
    "VERDICT_ERROR",
    "VERDICT_FAIL",
    "VERDICT_NO_BASELINE",
    "VERDICT_NO_OP",
    "VERDICT_PASS",
    "GateCheck",
    "StandingGateResult",
    "check_standing_gates",
    "error_payload",
    "load_baseline_config",
    "resolve_family",
    "trades_fingerprint",
]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE_PATH = ROOT / "data" / "standing_baseline.json"

# Carried over verbatim from v49_gates.TRADE_COUNT_FLOOR (lowered 50 -> 20 on
# 2026-04-06). Overridable from the config file.
TRADE_COUNT_FLOOR = 20

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_NO_OP = "NO_OP"
VERDICT_NO_BASELINE = "NO_BASELINE"
VERDICT_ERROR = "ERROR"

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_NOT_EVALUATED = "not_evaluated"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class GateCheck:
    """One gate's verdict plus the numbers it was computed from.

    `status` is deliberately a string, not a bool: `not_evaluated` is a third
    state and collapsing it into False (a failure) or True (a pass) is exactly
    the bug this module replaces.
    """

    status: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, **self.detail}


@dataclass
class StandingGateResult:
    version: str
    family: str | None
    verdict: str
    gates: dict[str, GateCheck] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    standing_baseline_used: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    sibling_comparison: dict[str, Any] | None = None
    candidate_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Legacy compatibility: only a clean PASS is a pass.

        NO_OP / NO_BASELINE / ERROR are explicitly NOT passes — a caller that
        only knows about the old boolean must not treat them as ship-ready.
        """
        return self.verdict == VERDICT_PASS

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.version,
            "family": self.family,
            "verdict": self.verdict,
            # `passed` and `failures` are kept for the pre-existing Go handler
            # and Foreman board, which predate the verdict vocabulary.
            "passed": self.passed,
            "gates": {name: check.to_dict() for name, check in self.gates.items()},
            "failures": list(self.failures),
            "notes": list(self.notes),
            "standing_baseline_used": self.standing_baseline_used,
            "provenance": self.provenance,
            "candidate_summary": self.candidate_summary,
            "gate_module": "omega/eval/standing_gates.py",
        }
        if self.sibling_comparison is not None:
            payload["sibling_comparison"] = self.sibling_comparison
        return payload


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_baseline_config(path: Path | str | None = None) -> dict[str, Any]:
    """Read `data/standing_baseline.json` (or an explicit path)."""
    p = Path(path) if path is not None else DEFAULT_BASELINE_PATH
    return json.loads(p.read_text())


def _as_results(results: Path | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(results, dict):
        return results
    return json.loads(Path(results).read_text())


def _load_trades(path: Path | str) -> list[dict[str, Any]]:
    with Path(path).open(newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _summary(results: dict[str, Any]) -> dict[str, Any]:
    """Pull the candidate's headline numbers, preserving absence as None.

    `max_drawdown_usd` is NOT defaulted to 0.0 — its absence is the signal that
    drawdown cannot be gated, and defaulting it is what made the v49 drawdown
    ceiling permanently green.
    """
    tb = results.get("trades") or {}
    ob = results.get("observability") or {}
    dd = ob.get("max_drawdown_usd")
    return {
        "version": results.get("version"),
        # Key names deliberately match the legacy GateSummary the Foreman board
        # and the Go handler already understand (`pnl`, `trades`, `win_rate`,
        # `max_drawdown`) so the candidate column renders without a shim.
        "pnl": float(tb.get("total_pnl_usd", 0.0)) if "total_pnl_usd" in tb else None,
        "trades": int(tb.get("total_closed", 0)) if "total_closed" in tb else None,
        "win_rate": tb.get("win_rate"),
        "max_drawdown": float(dd) if isinstance(dd, (int, float)) else None,
    }


# ---------------------------------------------------------------------------
# Family resolution
# ---------------------------------------------------------------------------


def _manifest_regime(snapshot_basename: str, config: dict[str, Any]) -> str | None:
    """Look a walk-forward snapshot id up in `data/walk_forward_manifest.json`.

    Walk-forward cells are labelled by DATE (`v252_replay_2023-09-12`), so the
    label carries no regime token at all; the manifest is the only mechanical
    source of truth for them.
    """
    spec = config.get("snapshot_regime_manifest") or {}
    rel = spec.get("path")
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = ROOT / rel
    if not p.exists():
        return None
    try:
        manifest = json.loads(p.read_text())
    except Exception:
        return None
    stem = snapshot_basename.removesuffix(".json")
    for window in manifest.get("windows") or []:
        if window.get("id") == stem:
            regime = window.get("regime")
            return str(regime) if regime else None
    return None


def _pattern_family(text: str, config: dict[str, Any]) -> str | None:
    for entry in config.get("family_patterns") or []:
        pattern = entry.get("pattern")
        family = entry.get("family")
        if pattern and family and re.search(pattern, text):
            return str(family)
    return None


def resolve_family(
    label: str,
    results: dict[str, Any] | None,
    config: dict[str, Any],
) -> tuple[str | None, str, list[str]]:
    """Map a cell to one of the standing baseline's regime families.

    Returns `(family, source, notes)`. `source` is one of
    `manifest` / `snapshot_pattern` / `label_pattern` / `unresolved`.

    Resolution order puts the SUBSTRATE ahead of the NAME: a cell's snapshot is
    what it actually ran on, whereas its label is what someone typed. When both
    resolve and disagree, the snapshot wins and the conflict is recorded in
    `notes` rather than quietly dropped.
    """
    notes: list[str] = []
    snapshot = None
    if results:
        snapshot = ((results.get("provenance") or {}).get("snapshot")) or None

    snap_family: str | None = None
    snap_source = ""
    if snapshot:
        basename = Path(str(snapshot)).name
        snap_family = _manifest_regime(basename, config)
        if snap_family:
            snap_source = "manifest"
        else:
            snap_family = _pattern_family(basename, config)
            if snap_family:
                snap_source = "snapshot_pattern"

    label_family = _pattern_family(label, config)

    if snap_family and label_family and snap_family != label_family:
        notes.append(
            f"family conflict: snapshot {Path(str(snapshot)).name} says "
            f"{snap_family!r} but the cell label says {label_family!r}; "
            f"using the snapshot (the substrate the run actually used)"
        )
    if snap_family:
        return snap_family, snap_source, notes
    if label_family:
        return label_family, "label_pattern", notes
    notes.append(
        f"no family pattern matched cell label {label!r}"
        + (f" or snapshot {Path(str(snapshot)).name!r}" if snapshot else "")
    )
    return None, "unresolved", notes


# ---------------------------------------------------------------------------
# Trade fingerprint (no-op detection)
# ---------------------------------------------------------------------------


def trades_fingerprint(path: Path | str) -> str | None:
    """sha256 over a trades CSV with the `timestamp` column dropped.

    Timestamps move with wall-clock even for a bit-identical replay, so they are
    the one column that must not participate. Everything else — symbol, side,
    size, prices, pnl, regime — is the run's actual content. Returns None when
    the file is missing or unreadable; a fingerprint that cannot be computed
    must not be allowed to look like a match.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        rows = _load_trades(p)
    except Exception:
        return None
    digest = hashlib.sha256()
    for row in rows:
        content = {k: v for k, v in sorted(row.items()) if k != "timestamp"}
        digest.update(json.dumps(content, sort_keys=True).encode())
        digest.update(b"\n")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def _gate_family_pnl_floor(
    summary: dict[str, Any],
    family: str | None,
    families: dict[str, Any],
) -> tuple[GateCheck, str | None]:
    if family is None:
        return (
            GateCheck(
                STATUS_NOT_EVALUATED,
                {"reason": "cell family unresolved — no standing floor applies"},
            ),
            None,
        )
    spec = families.get(family)
    if not spec or spec.get("pnl_floor_usd") is None:
        return (
            GateCheck(
                STATUS_NOT_EVALUATED,
                {
                    "family": family,
                    "reason": f"standing baseline config carries no pnl_floor_usd for family {family!r}",
                },
            ),
            None,
        )
    floor = float(spec["pnl_floor_usd"])
    pnl = summary.get("pnl")
    if pnl is None:
        return (
            GateCheck(
                STATUS_NOT_EVALUATED,
                {
                    "family": family,
                    "floor_usd": floor,
                    "reason": "candidate results carry no trades.total_pnl_usd",
                },
            ),
            None,
        )
    detail = {
        "family": family,
        "candidate_pnl_usd": pnl,
        "floor_usd": floor,
        "margin_usd": round(pnl - floor, 4),
        "journal_cite": spec.get("journal_cite"),
    }
    if pnl >= floor:
        return GateCheck(STATUS_PASS, detail), None
    return (
        GateCheck(STATUS_FAIL, detail),
        f"family_pnl_floor[{family}]: candidate {pnl:+.2f} < standing floor {floor:+.2f} "
        f"(margin {pnl - floor:+.2f})",
    )


def _gate_trade_count_floor(summary: dict[str, Any], floor: int) -> tuple[GateCheck, str | None]:
    trades = summary.get("trades")
    if trades is None:
        return (
            GateCheck(
                STATUS_NOT_EVALUATED,
                {"floor": floor, "reason": "candidate results carry no trades.total_closed"},
            ),
            None,
        )
    detail = {"trades": trades, "floor": floor}
    if trades >= floor:
        return GateCheck(STATUS_PASS, detail), None
    return (
        GateCheck(STATUS_FAIL, detail),
        f"trade_count_floor: candidate trades {trades} < {floor}",
    )


def _gate_drawdown_ceiling(
    summary: dict[str, Any],
    ceiling: float | None,
) -> tuple[GateCheck, str | None]:
    """Only evaluated when the run actually emitted a drawdown number.

    `scripts/run_training.py` does not currently write
    `observability.max_drawdown_usd`, so in practice this reports
    `not_evaluated` — which is the truth, and is the point.
    """
    dd = summary.get("max_drawdown")
    if dd is None:
        return (
            GateCheck(
                STATUS_NOT_EVALUATED,
                {
                    "reason": "observability.max_drawdown_usd absent from candidate results — "
                    "nothing to gate (this is why the v49 drawdown_ceiling was vacuously green)"
                },
            ),
            None,
        )
    if ceiling is None:
        return (
            GateCheck(
                STATUS_NOT_EVALUATED,
                {
                    "candidate_max_drawdown_usd": dd,
                    "reason": "standing baseline config carries no max_drawdown_ceiling_usd",
                },
            ),
            None,
        )
    detail = {"candidate_max_drawdown_usd": dd, "ceiling_usd": float(ceiling)}
    if dd <= float(ceiling):
        return GateCheck(STATUS_PASS, detail), None
    return (
        GateCheck(STATUS_FAIL, detail),
        f"drawdown_ceiling: candidate {dd:.2f} > ceiling {float(ceiling):.2f}",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def check_standing_gates(
    candidate_results: Path | str | dict[str, Any],
    candidate_trades_path: Path | str | None,
    baseline_config: dict[str, Any] | Path | str | None = None,
    *,
    version: str | None = None,
    sibling_label: str | None = None,
    sibling_results: Path | str | dict[str, Any] | None = None,
    sibling_trades_path: Path | str | None = None,
    out_path: Path | str | None = None,
) -> StandingGateResult:
    """Evaluate a candidate cell against the standing campaign baseline.

    The PRIMARY comparison is the candidate's PnL against its regime family's
    standing floor. The N-1 sibling (`sibling_*`, optional) is a SECONDARY,
    purely informational signal used for no-op detection; it never decides a
    pass or a fail on its own.
    """
    config = (
        baseline_config
        if isinstance(baseline_config, dict)
        else load_baseline_config(baseline_config)
    )
    results = _as_results(candidate_results)
    label = version or results.get("version") or (results.get("provenance") or {}).get("cell_label") or "unknown"
    summary = _summary(results)

    family, family_source, notes = resolve_family(str(label), results, config)

    families = config.get("families") or {}
    trade_floor = int(config.get("trade_count_floor", TRADE_COUNT_FLOOR))

    gates: dict[str, GateCheck] = {}
    failures: list[str] = []

    check, failure = _gate_family_pnl_floor(summary, family, families)
    gates["family_pnl_floor"] = check
    if failure:
        failures.append(failure)

    check, failure = _gate_trade_count_floor(summary, trade_floor)
    gates["trade_count_floor"] = check
    if failure:
        failures.append(failure)

    check, failure = _gate_drawdown_ceiling(summary, config.get("max_drawdown_ceiling_usd"))
    gates["drawdown_ceiling"] = check
    if failure:
        failures.append(failure)

    # ── sibling comparison (informational only) ─────────────────────────────
    prov = results.get("provenance") or {}
    frozen_cache = bool(prov.get("frozen_cache"))
    candidate_fp = trades_fingerprint(candidate_trades_path) if candidate_trades_path else None

    sibling_comparison: dict[str, Any] | None = None
    is_no_op = False
    if sibling_label or sibling_results is not None:
        sib = _as_results(sibling_results) if sibling_results is not None else {}
        sib_summary = _summary(sib)
        sib_fp = trades_fingerprint(sibling_trades_path) if sibling_trades_path else None
        same_numbers = (
            sib_summary.get("pnl") is not None
            and sib_summary.get("pnl") == summary.get("pnl")
            and sib_summary.get("trades") is not None
            and sib_summary.get("trades") == summary.get("trades")
        )
        same_fingerprint = bool(candidate_fp) and candidate_fp == sib_fp
        sibling_comparison = {
            "status": "informational",
            "note": "the N-1 sibling is NOT the gate — it exists to detect a run that "
            "reproduced a prior run instead of measuring something new",
            "sibling_label": sibling_label,
            "sibling_pnl_usd": sib_summary.get("pnl"),
            "sibling_trades": sib_summary.get("trades"),
            "candidate_pnl_usd": summary.get("pnl"),
            "candidate_trades": summary.get("trades"),
            "delta_pnl_usd": (
                round(summary["pnl"] - sib_summary["pnl"], 4)
                if summary.get("pnl") is not None and sib_summary.get("pnl") is not None
                else None
            ),
            "identical_numbers": same_numbers,
            "identical_trade_fingerprint": same_fingerprint,
            "candidate_frozen_cache": frozen_cache,
        }
        is_no_op = frozen_cache and (same_fingerprint or same_numbers)
        if is_no_op:
            notes.append(
                f"NO_OP: this run used a frozen cache and reproduced {sibling_label or 'its N-1 sibling'} "
                f"exactly ({'trade fingerprint' if same_fingerprint else 'trade count and PnL'} identical). "
                f"It measured nothing new; a green board here would be vacuous."
            )
    if candidate_fp:
        notes.append(f"candidate trade fingerprint (timestamp column dropped): {candidate_fp[:16]}…")

    # ── verdict ─────────────────────────────────────────────────────────────
    if any(c.status == STATUS_FAIL for c in gates.values()):
        verdict = VERDICT_FAIL
    elif family is None:
        verdict = VERDICT_NO_BASELINE
    elif is_no_op:
        verdict = VERDICT_NO_OP
    else:
        verdict = VERDICT_PASS

    standing_used: dict[str, Any] = {
        "source": config.get("source"),
        "updated": config.get("updated"),
        "family": family,
        "family_source": family_source,
        "trade_count_floor": trade_floor,
    }
    if family and family in families:
        standing_used["pnl_floor_usd"] = families[family].get("pnl_floor_usd")
        standing_used["journal_cite"] = families[family].get("journal_cite")

    result = StandingGateResult(
        version=str(label),
        family=family,
        verdict=verdict,
        gates=gates,
        failures=failures,
        notes=notes,
        standing_baseline_used=standing_used,
        provenance={
            "git_sha": prov.get("git_sha"),
            "git_dirty": prov.get("git_dirty"),
            "features": prov.get("features"),
            "snapshot": prov.get("snapshot"),
            "frozen_cache": frozen_cache,
            "cache_manifest_md5": prov.get("cache_manifest_md5"),
            "trades_fingerprint": candidate_fp,
        },
        sibling_comparison=sibling_comparison,
        candidate_summary=summary,
    )

    if out_path is not None:
        Path(out_path).write_text(json.dumps(result.to_dict(), indent=2))

    return result


def error_payload(version: str, error: BaseException | str, *, out_path: Path | str | None = None) -> dict[str, Any]:
    """The gate file written when gate evaluation itself blew up.

    The old code swallowed the exception and wrote nothing, so a crashed gate
    was indistinguishable from a gate that never ran. An ERROR file is the
    record; the caller still must not let it kill the training run.
    """
    payload = {
        "version": version,
        "family": None,
        "verdict": VERDICT_ERROR,
        "passed": False,
        "gates": {},
        "failures": [f"gate evaluation raised: {error}"],
        "error": str(error),
        "error_type": type(error).__name__ if isinstance(error, BaseException) else "str",
        "notes": [
            "Standing gates could not be evaluated. This file exists so the failure "
            "is a record rather than a silence — see the training log for the traceback."
        ],
        "gate_module": "omega/eval/standing_gates.py",
    }
    if out_path is not None:
        Path(out_path).write_text(json.dumps(payload, indent=2))
    return payload
