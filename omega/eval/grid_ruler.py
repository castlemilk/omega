"""Grid-level campaign ruler — the instrument that actually gates the standing baseline.

Why this module exists
----------------------

`omega/eval/standing_gates.py` judges ONE CELL: did this 90-day window lose
money (`per_cell_floor_usd`, $0). It deliberately refuses to use the journal's
campaign means (+$599 crisis / +$2,997 trend / +$30 recent) as a per-cell bar,
because those are means of heavily right-skewed per-regime distributions —
crisis's own median window is +$65 — so a per-cell bar at the mean would fail
most legitimate cells. Its own docstring names the consequence:

    "The campaign mean is a GRID-level ruler; comparing a whole grid against it
     is future work, and `training_log/V247_RULER.md` is that instrument's spec."

This module is that instrument. Until it existed, the standing baseline was
defended by the journal and an advisory string and nothing else.

The rule, from the journal
--------------------------

`training_log/V247_RULER.md` §1 fixes what a verdict IS:

    "A verdict is a **paired per-window Δ (ON − OFF)** aggregated per regime.
     Two distributions matter and they are NOT the same ruler:
       - OFF-arm levels — how heterogeneous the windows themselves are. This is
         the $27k-spread problem; **it can never be the gate**.
       - Paired Δ — the actual verdict instrument."

So the ruler pairs each candidate cell against the standing baseline's value
FOR THE SAME WINDOW and aggregates the differences — per regime family and
pooled over all 32. It never compares a candidate mean against a baseline mean
as two independent samples; §3 finding 3 ("Pooling works") and the $4,216 pooled
LEVEL sd against the $1,278–$4,404 paired-Δ sd are the whole reason pairing is
not optional. (A summary-stats fallback exists for a config that has lost its
per-window values; it is loud, and it is not the intended path — see
`PAIRING_UNPAIRED`.)

§4/§7 fix the BAR. MDE = (1.96 + 0.84)·sd/√n at α=0.05, 80% power, and §7 states
the standing thresholds:

    "Recent mean-Δ claims below **$1,043** at n=10: unfalsifiable, may not be
     used as an acceptance bar or reported as signal.
     Trend mean-Δ claims below **$4,118** (median-sd basis) at n=10: same.
     Crisis mean-Δ claims below **$1,565** at n=12: same.
     Pooled mean-Δ: resolvable down to ~**$875** (low-coupling mechanisms only)."

The direction this module gates in comes from §6, which is also where the
campaign chose to point the instrument (candidate β, `V247_RULER_CANDIDATES.md`,
"β verdict: PRIMARY", "Adopt β now"):

    "the pooled instrument already resolves $875-class effects for low-coupling
     mechanisms (candidate β reframes the gate onto it, **with recent as a
     one-sided no-regression floor — a floor does not need to DETECT small
     effects, only to reject large regressions**)."

Hence: **a family FAILS iff its mean-Δ is more negative than that family's MDE.**
A regression the instrument cannot resolve is not a failure — asserting one
would be exactly the unfalsifiable claim §7 forbids — but it is not silence
either: it rides as the `regression_within_noise` advisory, the same idiom the
cell layer uses for `below_campaign_mean`.

What this module deliberately does NOT do
-----------------------------------------

Candidate β's PRIMARY ACCEPTANCE gate ("pooled mean-Δ ≥ a bar set at/above the
mechanism-class 2·SE … pre-registered as a fixed $ number, AND seeded-bootstrap
95% CI on pooled mean-Δ excludes 0") is not implemented as a gate, because β
says in the same breath that "Exact $ bars are fixed in the pre-reg BEFORE any
run, per REFLECTION_V246". A standing scorer that invented an adoption bar would
be setting a bar after seeing results — the precise thing the campaign's
anti-Goodhart discipline exists to prevent. Every number that gate needs (pooled
mean-Δ, SE, 2·SE, seeded bootstrap CI) is computed and reported so a
pre-registration can adjudicate against it; the same holds for β's −1·SE recent
floor (`advisory_recent_floor_usd`) and its dual-tail Δ-p25 / level-p25 clause.
`gate_advisory_recent_floor` in the config turns the recent floor into a real
failure when a pre-reg adopts it.

Verdict vocabulary (mirrors `standing_gates.py`, which is the sibling layer)
---------------------------------------------------------------------------

``PASS``               no family regressed beyond its MDE. May carry advisories.
``FAIL``               at least one family's mean-Δ is below −MDE.
``INSUFFICIENT_GRID``  the grid does not cover the manifest's windows. LOUD, and
                       never a pass: the missing window ids are named per family.
``ERROR``              ruler evaluation itself raised (see `error_payload`).

Precedence: ``ERROR`` > ``FAIL`` > ``INSUFFICIENT_GRID`` > ``PASS``.

FAIL outranking INSUFFICIENT_GRID is only defensible because the MDE is
recomputed at the grid's ACTUAL n rather than read off §4's table. A short grid
therefore gets a correspondingly WIDER bar (MDE ∝ 1/√n), so a FAIL on a partial
grid is a regression large enough to clear the bar the partial grid can support
— not the n=32 bar misapplied to n=5. The coverage shortfall is still reported
in full alongside it.

All functions here are pure over on-disk artifacts. No Victoria imports, no
strategy code, no side effects other than the optional report write.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "ADVISORY_BELOW_RECENT_FLOOR",
    "ADVISORY_REGRESSION_WITHIN_NOISE",
    "DEFAULT_MANIFEST_PATH",
    "GRID_VERDICT_FILE_SUFFIX",
    "PAIRING_PAIRED",
    "PAIRING_UNPAIRED",
    "POOLED",
    "VERDICT_ERROR",
    "VERDICT_FAIL",
    "VERDICT_INSUFFICIENT_GRID",
    "VERDICT_PASS",
    "Z_ALPHA",
    "Z_POWER",
    "FamilyRuling",
    "GridCell",
    "GridVerdict",
    "check_grid_ruler",
    "error_payload",
    "load_manifest",
    "mde",
    "percentile",
]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = ROOT / "data" / "walk_forward_manifest.json"

#: The file this module writes, and the one the Go handler serves.
GRID_VERDICT_FILE_SUFFIX = "_grid_verdict.json"

# Identical to scripts/v247_ruler.py, so a ruler number is comparable with the
# published V247_RULER.md tables rather than merely similar to them.
Z_ALPHA = 1.959964  # two-sided alpha = 0.05
Z_POWER = 0.841621  # 80% power

POOLED = "pooled"

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_INSUFFICIENT_GRID = "INSUFFICIENT_GRID"
VERDICT_ERROR = "ERROR"

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_NOT_EVALUATED = "not_evaluated"

#: mean-Δ is negative but inside the family's MDE. Per V247_RULER.md §7 this is
#: exactly the region where a claim "may not be used as an acceptance bar or
#: reported as signal" — so it is neither a failure nor a silence.
ADVISORY_REGRESSION_WITHIN_NOISE = "regression_within_noise"

#: recent mean-Δ is below candidate β's −1·SE floor. Reported, not gated, unless
#: a pre-registration sets `gate_advisory_recent_floor`.
ADVISORY_BELOW_RECENT_FLOOR = "below_recent_no_regression_floor"

#: How the candidate was compared with the standing baseline.
PAIRING_PAIRED = "paired_per_window"
PAIRING_UNPAIRED = "unpaired_summary_stats"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GridCell:
    """One candidate cell: a version label, the window it ran, its family, its PnL.

    `window` is a `data/walk_forward_manifest.json` `windows[].id`
    (e.g. `snap_wf_20230912`). It is the pairing key, and a cell whose window is
    not in the manifest cannot be paired with anything — such cells are excluded
    from the arithmetic and named in `ruler_notes` rather than dropped silently.
    """

    label: str
    window: str
    family: str
    pnl_usd: float
    trades: int | None = None
    snapshot: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "window": self.window,
            "family": self.family,
            "pnl_usd": self.pnl_usd,
            "trades": self.trades,
        }


# ---------------------------------------------------------------------------
# Statistics — deliberately the same estimators as scripts/v247_ruler.py
# ---------------------------------------------------------------------------


def percentile(xs: list[float], q: float) -> float:
    """Linear-interpolated percentile (matches numpy's default and v247_ruler.py)."""
    if not xs:
        raise ValueError("percentile of an empty sample")
    s = sorted(xs)
    n = len(s)
    if n == 1:
        return s[0]
    pos = q / 100.0 * (n - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def mde(sd: float, n: int) -> float:
    """Minimum detectable mean effect: (z_{1-α/2} + z_power)·sd/√n.

    Two-sided α=0.05 at 80% power. Normal approximation — V247_RULER.md §4 says
    it is "slightly optimistic below n≈15", which is true of the published
    recent/trend/crisis rows themselves (n=10, 10, 12) and is a property of the
    campaign's own bars, not something this module chose.
    """
    if n <= 0:
        raise ValueError("mde requires n >= 1")
    return (Z_ALPHA + Z_POWER) * sd / math.sqrt(n)


def _bootstrap_ci(xs: list[float], resamples: int, seed: int) -> list[float] | None:
    """Seeded percentile bootstrap CI95 on the mean.

    A FRESH `random.Random(seed)` per call, unlike `scripts/v247_ruler.py`, which
    threads one stream through every table row. That makes a family's CI depend
    only on that family's numbers rather than on how many families were scored
    before it — the same run must not produce a different CI because the caller
    passed the crisis cells first. The estimator (percentile bootstrap of the
    mean, 20,000 resamples, seed 42) is otherwise identical.
    """
    if len(xs) < 2:
        return None
    rng = random.Random(seed)
    n = len(xs)
    means = [math.fsum(rng.choice(xs) for _ in range(n)) / n for _ in range(resamples)]
    return [percentile(means, 2.5), percentile(means, 97.5)]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class FamilyRuling:
    """One regime family's (or `pooled`'s) paired-Δ ruling."""

    family: str
    status: str
    n: int
    expected_n: int
    mean_delta_usd: float | None = None
    sd_usd: float | None = None
    se_usd: float | None = None
    two_se_usd: float | None = None
    delta_p25_usd: float | None = None
    candidate_level_p25_usd: float | None = None
    baseline_level_p25_usd: float | None = None
    candidate_mean_usd: float | None = None
    baseline_mean_usd: float | None = None
    bootstrap_ci95_usd: list[float] | None = None
    #: The bar: −`mde_usd` is the failure line.
    mde_usd: float | None = None
    delta_sd_assumed_usd: float | None = None
    published_mde_usd: float | None = None
    #: mean-Δ − (−MDE). Negative means the family failed.
    margin_usd: float | None = None
    advisories: list[str] = field(default_factory=list)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "family": self.family,
            "status": self.status,
            "n": self.n,
            "expected_n": self.expected_n,
        }
        for key in (
            "mean_delta_usd",
            "sd_usd",
            "se_usd",
            "two_se_usd",
            "delta_p25_usd",
            "candidate_level_p25_usd",
            "baseline_level_p25_usd",
            "candidate_mean_usd",
            "baseline_mean_usd",
            "bootstrap_ci95_usd",
            "mde_usd",
            "delta_sd_assumed_usd",
            "published_mde_usd",
            "margin_usd",
        ):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        if self.advisories:
            out["advisories"] = list(self.advisories)
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass
class GridVerdict:
    run_label: str
    verdict: str
    families: dict[str, FamilyRuling] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    #: Every judgement call the ruler made, in words. Ambiguities in the spec are
    #: resolved conservatively and confessed here rather than buried in code.
    ruler_notes: list[str] = field(default_factory=list)
    standing_distribution_used: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    cells: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Only a clean PASS is a pass. INSUFFICIENT_GRID and ERROR are not."""
        return self.verdict == VERDICT_PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_label": self.run_label,
            "verdict": self.verdict,
            "passed": self.passed,
            "families": {name: ruling.to_dict() for name, ruling in self.families.items()},
            "coverage": self.coverage,
            "failures": list(self.failures),
            "ruler_notes": list(self.ruler_notes),
            "standing_distribution_used": self.standing_distribution_used,
            "provenance": self.provenance,
            "cells": list(self.cells),
            "ruler_module": "omega/eval/grid_ruler.py",
        }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_manifest(path: Path | str | None = None) -> dict[str, Any]:
    """Read `data/walk_forward_manifest.json` (or an explicit path)."""
    p = Path(path) if path is not None else DEFAULT_MANIFEST_PATH
    manifest: dict[str, Any] = json.loads(p.read_text())
    return manifest


def _manifest_families(manifest: dict[str, Any]) -> dict[str, str]:
    """window id -> regime, in manifest order."""
    out: dict[str, str] = {}
    for window in manifest.get("windows") or []:
        wid = window.get("id")
        regime = window.get("regime")
        if wid and regime:
            out[str(wid)] = str(regime)
    return out


def _baseline_windows(config: dict[str, Any]) -> tuple[dict[str, float], dict[str, str]]:
    """window id -> baseline PnL, and window id -> family, from `distributions`."""
    levels: dict[str, float] = {}
    fams: dict[str, str] = {}
    per_family = ((config.get("distributions") or {}).get("per_family")) or {}
    for family, spec in per_family.items():
        for row in spec.get("windows") or []:
            wid = row.get("window")
            pnl = row.get("pnl_usd")
            if wid is None or pnl is None:
                continue
            levels[str(wid)] = float(pnl)
            fams[str(wid)] = str(family)
    return levels, fams


def _delta_sd_table(
    config: dict[str, Any], coupling: str
) -> tuple[dict[str, float], str, list[str]]:
    """The Δ-sd row for `coupling`, falling back to the config default then `median`."""
    notes: list[str] = []
    ruler_cfg = config.get("grid_ruler") or {}
    table = ruler_cfg.get("delta_sd_usd") or {}
    chosen = coupling
    if chosen not in table:
        fallback = str(ruler_cfg.get("default_coupling_class") or "median")
        if coupling:
            notes.append(
                f"coupling class {coupling!r} is not in the config's delta_sd_usd table "
                f"({sorted(k for k in table if not k.startswith('_'))}); using {fallback!r}"
            )
        chosen = fallback
    row = table.get(chosen) or {}
    sds = {k: float(v) for k, v in row.items() if not k.startswith("_")}
    return sds, chosen, notes


# ---------------------------------------------------------------------------
# The ruler
# ---------------------------------------------------------------------------


def _rule_family(
    family: str,
    deltas: list[float],
    candidate_levels: list[float],
    baseline_levels: list[float],
    expected_n: int,
    delta_sd: float | None,
    published_mde: float | None,
    published_n: int | None,
    boot: dict[str, Any],
) -> tuple[FamilyRuling, str | None]:
    """Rule one family. Returns `(ruling, failure_line)`."""
    n = len(deltas)
    if n == 0:
        return (
            FamilyRuling(
                family=family,
                status=STATUS_NOT_EVALUATED,
                n=0,
                expected_n=expected_n,
                reason=f"no candidate cell resolved to a {family} window — nothing to pair",
            ),
            None,
        )

    mean_delta = math.fsum(deltas) / n
    sd = statistics.stdev(deltas) if n > 1 else None
    se = (sd / math.sqrt(n)) if sd is not None else None

    ruling = FamilyRuling(
        family=family,
        status=STATUS_NOT_EVALUATED,
        n=n,
        expected_n=expected_n,
        mean_delta_usd=round(mean_delta, 4),
        sd_usd=round(sd, 4) if sd is not None else None,
        se_usd=round(se, 4) if se is not None else None,
        two_se_usd=round(2 * se, 4) if se is not None else None,
        delta_p25_usd=round(percentile(deltas, 25), 4),
        candidate_level_p25_usd=round(percentile(candidate_levels, 25), 4),
        baseline_level_p25_usd=round(percentile(baseline_levels, 25), 4),
        candidate_mean_usd=round(math.fsum(candidate_levels) / n, 4),
        baseline_mean_usd=round(math.fsum(baseline_levels) / n, 4),
        bootstrap_ci95_usd=[
            round(v, 4)
            for v in (
                _bootstrap_ci(deltas, int(boot.get("resamples", 20000)), int(boot.get("seed", 42)))
                or []
            )
        ]
        or None,
        published_mde_usd=published_mde,
    )

    if delta_sd is None:
        ruling.reason = (
            f"the standing baseline config carries no Δ-sd for family {family!r}, so no MDE bar "
            f"can be computed — V247_RULER.md §4 is the only source for one and it must not be "
            f"guessed at"
        )
        return ruling, None

    bar = mde(delta_sd, n)
    ruling.delta_sd_assumed_usd = delta_sd
    ruling.mde_usd = round(bar, 4)
    ruling.margin_usd = round(mean_delta + bar, 4)

    if published_mde is not None and published_n is not None and n != published_n:
        ruling.reason = (
            f"MDE recomputed at the grid's actual n={n} (published bar ${published_mde:,.0f} "
            f"assumes n={published_n}); MDE scales as 1/√n so a short grid gets a wider bar"
        )

    if mean_delta < -bar:
        ruling.status = STATUS_FAIL
        return (
            ruling,
            f"grid_regression[{family}]: mean-Δ {mean_delta:+,.2f} is below −MDE "
            f"{-bar:+,.2f} (n={n}, Δ-sd assumed ${delta_sd:,.0f}); the standing baseline "
            f"regressed by more than this instrument's resolution",
        )

    ruling.status = STATUS_PASS
    if mean_delta < 0:
        ruling.advisories.append(ADVISORY_REGRESSION_WITHIN_NOISE)
    return ruling, None


def check_grid_ruler(
    candidate_cells: list[GridCell] | list[dict[str, Any]],
    baseline_config: dict[str, Any] | Path | str | None = None,
    manifest: dict[str, Any] | Path | str | None = None,
    *,
    run_label: str = "unknown",
    coupling_class: str | None = None,
    out_path: Path | str | None = None,
) -> GridVerdict:
    """Rule a whole candidate grid against the standing baseline distribution.

    `candidate_cells` is the run's per-window results — `GridCell`s, or dicts
    with the same keys. The comparison is a paired per-window Δ against
    `distributions.per_family[*].windows[*].pnl_usd` in
    `data/standing_baseline.json`; the bar is `−MDE` per family, recomputed at
    the grid's actual n. See the module docstring for the journal citations.
    """
    # Local import keeps `standing_gates` the owner of the config loader; there
    # is exactly one reader of data/standing_baseline.json and it is that module.
    from omega.eval.standing_gates import load_baseline_config

    config = (
        baseline_config
        if isinstance(baseline_config, dict)
        else load_baseline_config(baseline_config)
    )
    man = manifest if isinstance(manifest, dict) else load_manifest(manifest)
    ruler_cfg = config.get("grid_ruler") or {}
    boot = ruler_cfg.get("bootstrap") or {}

    notes: list[str] = []
    failures: list[str] = []

    cells: list[GridCell] = [
        c if isinstance(c, GridCell) else GridCell(**c) for c in candidate_cells
    ]

    manifest_families = _manifest_families(man)
    baseline_levels, baseline_families = _baseline_windows(config)

    pairing = PAIRING_PAIRED if baseline_levels else PAIRING_UNPAIRED
    if pairing == PAIRING_UNPAIRED:
        notes.append(
            "LIMITATION — the standing baseline config carries NO per-window values "
            "(distributions.per_family[*].windows is empty or absent), so the paired instrument "
            "V247_RULER.md §1 specifies CANNOT be formed. No verdict is issued: an unpaired "
            "candidate-mean-vs-campaign-mean comparison would be the OFF-arm LEVEL ruler, of "
            "which the doc says 'it can never be the gate' (pooled level sd $4,216 against a "
            "paired-Δ sd of $1,278–$4,404). Restore the per-window values and re-run."
        )

    # ── window resolution + coverage ────────────────────────────────────────
    paired: dict[str, list[tuple[str, float, float]]] = {}  # family -> [(window, cand, base)]
    seen: dict[str, GridCell] = {}
    unpairable: list[dict[str, Any]] = []
    # Windows two cells disagreed about. Once a window is here it stays out, so a
    # third cell cannot quietly become the winner by arriving after the conflict.
    conflicted: set[str] = set()

    for cell in cells:
        if cell.window in conflicted:
            continue
        if cell.window not in manifest_families:
            unpairable.append(
                {
                    "label": cell.label,
                    "window": cell.window,
                    "why": "not a walk_forward_manifest window id",
                }
            )
            continue
        prior = seen.get(cell.window)
        if prior is not None:
            if abs(prior.pnl_usd - cell.pnl_usd) <= 0.005:
                notes.append(
                    f"duplicate cells on window {cell.window} ({prior.label!r} and {cell.label!r}) "
                    f"carry the same PnL to the cent; kept one"
                )
                continue
            failures.append(
                f"ambiguous_window[{cell.window}]: {prior.label!r} says {prior.pnl_usd:+,.2f} and "
                f"{cell.label!r} says {cell.pnl_usd:+,.2f}; a paired Δ needs one candidate value "
                f"per window and the ruler will not pick"
            )
            notes.append(
                f"window {cell.window} excluded from the arithmetic: two candidate cells disagree "
                f"on its PnL. This is a coverage hole, not a tie to be broken."
            )
            conflicted.add(cell.window)
            seen.pop(cell.window, None)
            for fam_cells in paired.values():
                fam_cells[:] = [row for row in fam_cells if row[0] != cell.window]
            continue

        manifest_family = manifest_families[cell.window]
        if cell.family and cell.family != manifest_family:
            notes.append(
                f"family conflict on {cell.window}: cell {cell.label!r} says {cell.family!r} but "
                f"the manifest says {manifest_family!r}; using the manifest (it is the "
                f"authoritative ex-post label — see snapshot_regime_manifest)"
            )
        if cell.window not in baseline_levels:
            unpairable.append(
                {
                    "label": cell.label,
                    "window": cell.window,
                    "why": "the standing baseline distribution carries no value for this window",
                }
            )
            continue
        if baseline_families.get(cell.window) not in (None, manifest_family):
            notes.append(
                f"the standing distribution files {cell.window} under "
                f"{baseline_families[cell.window]!r} but the manifest says {manifest_family!r}; "
                f"using the manifest"
            )
        seen[cell.window] = cell
        paired.setdefault(manifest_family, []).append(
            (cell.window, cell.pnl_usd, baseline_levels[cell.window])
        )

    expected_by_family: dict[str, list[str]] = {}
    for wid, fam in manifest_families.items():
        expected_by_family.setdefault(fam, []).append(wid)

    covered = set(seen)
    missing_by_family = {
        fam: [w for w in wids if w not in covered] for fam, wids in expected_by_family.items()
    }
    n_missing = sum(len(v) for v in missing_by_family.values())

    coverage: dict[str, Any] = {
        "manifest_built_by": man.get("_built_by"),
        "expected_windows": len(manifest_families),
        "covered_windows": len(covered),
        "complete": n_missing == 0,
        "pairing": pairing,
        "per_family": {
            fam: {
                "expected": len(wids),
                "covered": len(wids) - len(missing_by_family[fam]),
                "missing": sorted(missing_by_family[fam]),
            }
            for fam, wids in sorted(expected_by_family.items())
        },
        "unpairable_cells": unpairable,
    }
    if unpairable:
        notes.append(
            f"{len(unpairable)} candidate cell(s) could not be paired and were EXCLUDED from the "
            f"arithmetic (not treated as zero): "
            + ", ".join(f"{u['label']} ({u['why']})" for u in unpairable[:8])
            + (" …" if len(unpairable) > 8 else "")
        )

    # ── the rulings ─────────────────────────────────────────────────────────
    sds, coupling_used, coupling_notes = _delta_sd_table(config, coupling_class or "")
    notes.extend(coupling_notes)
    if coupling_class is None:
        notes.append(
            f"no coupling class was declared, so the mechanism-agnostic {coupling_used!r} Δ-sd row "
            f"is used. V247_RULER.md §7: 'Any pre-reg must declare its expected coupling class "
            f"(exit-only / sizing-only / selection-changing) — it determines which MDE row "
            f"applies.' The ruler will not infer one from results. This is the CONSERVATIVE "
            f"direction for a no-regression gate: the median Δ-sd is the widest of the "
            f"low-coupling rows, so the bar is harder to breach than a class-specific bar."
        )
    published = ruler_cfg.get("published_mde_usd_at_current_n") or {}
    published_n = ruler_cfg.get("n_at_publication") or {}

    families: dict[str, FamilyRuling] = {}
    if pairing == PAIRING_PAIRED:
        for fam in sorted(expected_by_family):
            rows = sorted(paired.get(fam, []))
            ruling, failure = _rule_family(
                fam,
                [c - b for _, c, b in rows],
                [c for _, c, _ in rows],
                [b for _, _, b in rows],
                len(expected_by_family[fam]),
                sds.get(fam),
                published.get(fam),
                published_n.get(fam),
                boot,
            )
            families[fam] = ruling
            if failure:
                failures.append(failure)

        pooled_rows = sorted(row for rows in paired.values() for row in rows)
        ruling, failure = _rule_family(
            POOLED,
            [c - b for _, c, b in pooled_rows],
            [c for _, c, _ in pooled_rows],
            [b for _, _, b in pooled_rows],
            len(manifest_families),
            sds.get(POOLED),
            published.get(POOLED),
            published_n.get(POOLED),
            boot,
        )
        families[POOLED] = ruling
        if failure:
            failures.append(failure)

        recent = families.get("recent")
        floor = ruler_cfg.get("advisory_recent_floor_usd")
        if (
            recent is not None
            and recent.mean_delta_usd is not None
            and floor is not None
            and recent.mean_delta_usd < float(floor)
        ):
            recent.advisories.append(ADVISORY_BELOW_RECENT_FLOOR)
            line = (
                f"recent mean-Δ {recent.mean_delta_usd:+,.2f} is below candidate β's one-sided "
                f"no-regression floor {float(floor):+,.2f}"
            )
            if bool(ruler_cfg.get("gate_advisory_recent_floor")):
                recent.status = STATUS_FAIL
                failures.append(f"recent_no_regression_floor: {line} (gated by pre-registration)")
            else:
                notes.append(
                    f"ADVISORY {ADVISORY_BELOW_RECENT_FLOOR}: {line}. NOT a failure here — "
                    f"V247_RULER_CANDIDATES.md fixes exact $ bars in a pre-registration BEFORE "
                    f"a run, so a standing scorer may not impose one. Set "
                    f"grid_ruler.gate_advisory_recent_floor to gate on it."
                )

    # ── verdict ─────────────────────────────────────────────────────────────
    if pairing == PAIRING_UNPAIRED:
        verdict = VERDICT_INSUFFICIENT_GRID
        failures.append(
            "no_standing_distribution: the config carries no per-window standing values, so the "
            "paired instrument cannot be formed"
        )
    elif failures:
        verdict = VERDICT_FAIL
    elif n_missing > 0:
        verdict = VERDICT_INSUFFICIENT_GRID
    else:
        verdict = VERDICT_PASS

    if n_missing > 0 and verdict != VERDICT_PASS:
        detail = "; ".join(
            f"{fam}: {len(missing_by_family[fam])}/{len(wids)} missing "
            f"({', '.join(sorted(missing_by_family[fam])[:4])}"
            f"{' …' if len(missing_by_family[fam]) > 4 else ''})"
            for fam, wids in sorted(expected_by_family.items())
            if missing_by_family[fam]
        )
        notes.append(
            f"INSUFFICIENT_GRID: {n_missing} of {len(manifest_families)} manifest windows are not "
            f"covered by this run — {detail}. The campaign ruler is a whole-grid instrument; a "
            f"partial grid is not a pass, and the MDE bars above have been widened to the actual "
            f"n rather than the published n so that any FAIL reported alongside is one the partial "
            f"grid can actually support."
        )

    dist_cfg = config.get("distributions") or {}
    result = GridVerdict(
        run_label=run_label,
        verdict=verdict,
        families=families,
        coverage=coverage,
        failures=failures,
        ruler_notes=notes,
        standing_distribution_used={
            "source": dist_cfg.get("source"),
            "config": dist_cfg.get("config"),
            "corroboration": dist_cfg.get("corroboration"),
            "updated": config.get("updated"),
            "per_family": {
                fam: {
                    "n": spec.get("n"),
                    "mean_usd": spec.get("mean_usd"),
                    "sd_usd": spec.get("sd_usd"),
                }
                for fam, spec in sorted((dist_cfg.get("per_family") or {}).items())
            },
            "campaign_means_usd": {
                fam: (spec or {}).get("campaign_mean_usd")
                for fam, spec in sorted((config.get("families") or {}).items())
            },
        },
        provenance={
            "spec": ruler_cfg.get("spec"),
            "instrument": ruler_cfg.get("instrument"),
            "bar": ruler_cfg.get("bar"),
            "mde_formula": ruler_cfg.get("mde_formula"),
            "coupling_class": coupling_used,
            "coupling_class_declared": coupling_class,
            "delta_sd_usd": {k: v for k, v in sorted(sds.items())},
            "bootstrap": {
                "resamples": int(boot.get("resamples", 20000)),
                "seed": int(boot.get("seed", 42)),
            },
            "gate_advisory_recent_floor": bool(ruler_cfg.get("gate_advisory_recent_floor")),
            "advisory_recent_floor_usd": ruler_cfg.get("advisory_recent_floor_usd"),
        },
        cells=[
            {
                "window": w,
                "family": manifest_families[w],
                "label": seen[w].label,
                "candidate_pnl_usd": c,
                "baseline_pnl_usd": b,
                "delta_usd": round(c - b, 4),
            }
            for fam in sorted(paired)
            for w, c, b in sorted(paired[fam])
        ],
    )

    if out_path is not None:
        Path(out_path).write_text(json.dumps(result.to_dict(), indent=2))
    return result


def error_payload(
    run_label: str,
    error: BaseException | str,
    *,
    out_path: Path | str | None = None,
) -> dict[str, Any]:
    """The grid-verdict file written when ruler evaluation itself blew up.

    Same contract as `standing_gates.error_payload`: an ERROR file is a record,
    and a crashed ruler must never be indistinguishable from a ruler that never
    ran.
    """
    payload = {
        "run_label": run_label,
        "verdict": VERDICT_ERROR,
        "passed": False,
        "families": {},
        "coverage": {},
        "failures": [f"grid ruler evaluation raised: {error}"],
        "ruler_notes": [
            "The campaign ruler could not be evaluated. This file exists so the failure is a "
            "record rather than a silence."
        ],
        "error": str(error),
        "error_type": type(error).__name__ if isinstance(error, BaseException) else "str",
        "ruler_module": "omega/eval/grid_ruler.py",
    }
    if out_path is not None:
        Path(out_path).write_text(json.dumps(payload, indent=2))
    return payload
