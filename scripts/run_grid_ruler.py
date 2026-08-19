#!/usr/bin/env python3
"""Run the grid-level campaign ruler over a finished walk-forward grid.

    python3 scripts/run_grid_ruler.py --run v246_wf
    python3 scripts/run_grid_ruler.py --run v246_wf --coupling low --out /tmp/x.json

WHEN TO RUN THIS
----------------

**After a whole grid finishes, once — not per cell.** The two layers answer
different questions and the split is deliberate:

  - `omega/eval/standing_gates.py` runs at the END OF EVERY CELL, from
    `scripts/run_training.py`, and asks the per-cell question: did this 90-day
    window lose money.
  - this ruler runs ONCE PER GRID and asks the campaign question: did the
    standing baseline move, on the paired 32-window instrument
    (`training_log/V247_RULER.md`).

Running it per cell would be meaningless — one window is n=1 against an MDE
calibrated at n=10/12/32 — and running it mid-grid produces INSUFFICIENT_GRID by
construction. So it is NOT wired into the training loop.

**Future wiring, deliberately not done here:** the grid shell scripts
(`scripts/v2*_wf_grid.sh`, `scripts/walk_forward_grid.sh`) are the natural
end-of-grid hook — they are the only thing that knows a grid is complete.
`run_training.py` never does: it is invoked once per cell and has no concept of
the set. Adding a final `python3 scripts/run_grid_ruler.py --run "$RUN"` line to
a grid script is a one-line change to a runner, but it is a change to the
training path, so it is left for the pre-registration that first wants a
mechanical grid verdict.

HOW A RUN'S CELLS ARE FOUND
---------------------------

`--run <prefix>` globs `<data-dir>/<prefix>*_results.json`, reads each cell's
`provenance.snapshot`, and keeps the ones whose snapshot basename is a
`data/walk_forward_manifest.json` window id. Anything else — a snapshot cell, a
smoke cell, a differently-shaped label — is reported as unpairable rather than
silently dropped or, worse, counted as a zero.

READ-ONLY except for the one file it writes (`--out`, default
`<data-dir>/<run>_grid_verdict.json`). It touches no strategy code, no training
state, and no other artefact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from omega.eval.grid_ruler import (  # noqa: E402
    GRID_VERDICT_FILE_SUFFIX,
    VERDICT_PASS,
    GridCell,
    check_grid_ruler,
    error_payload,
    load_manifest,
)
from omega.eval.standing_gates import load_baseline_config  # noqa: E402

RESULTS_SUFFIX = "_results.json"


def collect_cells(
    run_prefix: str,
    data_dir: Path,
    manifest: dict,
) -> tuple[list[GridCell], list[dict]]:
    """Resolve `<data-dir>/<prefix>*_results.json` into pairable grid cells.

    Returns `(cells, skipped)`. A cell is pairable iff its
    `provenance.snapshot` basename is a manifest window id — the manifest is the
    authoritative regime label for walk-forward cells, whose LABELS carry a date
    rather than a regime (`v252_replay_2023-09-12`).
    """
    windows = {str(w.get("id")): str(w.get("regime")) for w in manifest.get("windows") or []}
    cells: list[GridCell] = []
    skipped: list[dict] = []

    for path in sorted(data_dir.glob(f"{run_prefix}*{RESULTS_SUFFIX}")):
        label = path.name[: -len(RESULTS_SUFFIX)]
        try:
            payload = json.loads(path.read_text())
        except Exception as exc:  # a corrupt file is reported, never skipped silently
            skipped.append({"label": label, "why": f"unreadable results file: {exc}"})
            continue
        prov = payload.get("provenance") or {}
        snapshot = prov.get("snapshot")
        window = Path(str(snapshot)).name.removesuffix(".json") if snapshot else ""
        if window not in windows:
            skipped.append(
                {
                    "label": label,
                    "why": (
                        f"snapshot {window or '(none)'!r} is not a walk_forward_manifest window id"
                        " — not a walk-forward cell"
                    ),
                }
            )
            continue
        trades = payload.get("trades") or {}
        if "total_pnl_usd" not in trades:
            skipped.append({"label": label, "why": "results carry no trades.total_pnl_usd"})
            continue
        cells.append(
            GridCell(
                label=label,
                window=window,
                family=windows[window],
                pnl_usd=float(trades["total_pnl_usd"]),
                trades=int(trades.get("total_closed", 0)) if "total_closed" in trades else None,
                snapshot=str(snapshot),
            )
        )
    return cells, skipped


def _fmt(value: float | None, plus: bool = True) -> str:
    if value is None:
        return "—"
    return f"{value:+,.2f}" if plus else f"{value:,.2f}"


def render(verdict, skipped: list[dict]) -> str:
    """The stdout report. Everything an operator needs without opening the JSON."""
    lines: list[str] = []
    lines.append(f"grid ruler — {verdict.run_label}")
    lines.append(f"VERDICT: {verdict.verdict}")
    lines.append("")
    cov = verdict.coverage
    lines.append(
        f"coverage: {cov.get('covered_windows')}/{cov.get('expected_windows')} manifest windows "
        f"({cov.get('pairing')})"
    )
    for fam, spec in (cov.get("per_family") or {}).items():
        miss = spec.get("missing") or []
        lines.append(
            f"  {fam:<8} {spec.get('covered')}/{spec.get('expected')}"
            + (f"   missing: {', '.join(miss)}" if miss else "")
        )
    lines.append("")
    lines.append(
        f"{'family':<8} {'n':>3} {'mean-Δ':>12} {'−MDE (bar)':>12} {'margin':>12}  {'bootstrap CI95':>26}  status"
    )
    for fam, ruling in verdict.families.items():
        ci = ruling.bootstrap_ci95_usd
        ci_txt = f"[{ci[0]:+,.0f}, {ci[1]:+,.0f}]" if ci else "—"
        bar = f"{-ruling.mde_usd:+,.2f}" if ruling.mde_usd is not None else "—"
        lines.append(
            f"{fam:<8} {ruling.n:>3} {_fmt(ruling.mean_delta_usd):>12} {bar:>12} "
            f"{_fmt(ruling.margin_usd):>12}  {ci_txt:>26}  {ruling.status}"
            + (f"  [{', '.join(ruling.advisories)}]" if ruling.advisories else "")
        )
    if verdict.failures:
        lines.append("")
        lines.append("failures:")
        lines.extend(f"  - {f}" for f in verdict.failures)
    if skipped:
        lines.append("")
        lines.append(f"cells skipped ({len(skipped)}):")
        lines.extend(f"  - {s['label']}: {s['why']}" for s in skipped[:20])
        if len(skipped) > 20:
            lines.append(f"  … and {len(skipped) - 20} more")
    if verdict.ruler_notes:
        lines.append("")
        lines.append("ruler notes:")
        lines.extend(f"  - {n}" for n in verdict.ruler_notes)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--run",
        required=True,
        help="version prefix, e.g. v246_wf — matches <prefix>*_results.json",
    )
    ap.add_argument(
        "--data-dir", default=str(ROOT / "data"), help="where the *_results.json cells live"
    )
    ap.add_argument(
        "--out",
        default=None,
        help=f"verdict path (default <data-dir>/<run>{GRID_VERDICT_FILE_SUFFIX})",
    )
    ap.add_argument("--no-write", action="store_true", help="print the verdict, write nothing")
    ap.add_argument(
        "--coupling",
        default=None,
        choices=["median", "inert", "low", "heavy"],
        help="the mechanism's coupling class, as declared in its pre-registration "
        "(V247_RULER.md §7). Omitted = the mechanism-agnostic 'median' row.",
    )
    ap.add_argument("--baseline", default=None, help="path to standing_baseline.json")
    ap.add_argument("--manifest", default=None, help="path to walk_forward_manifest.json")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir)
    out_path = (
        None
        if args.no_write
        else Path(args.out)
        if args.out
        else data_dir / f"{args.run}{GRID_VERDICT_FILE_SUFFIX}"
    )

    try:
        manifest = load_manifest(args.manifest)
        config = load_baseline_config(args.baseline)
        cells, skipped = collect_cells(args.run, data_dir, manifest)
        verdict = check_grid_ruler(
            cells,
            config,
            manifest,
            run_label=args.run,
            coupling_class=args.coupling,
            out_path=out_path,
        )
    except Exception as exc:
        payload = error_payload(args.run, exc, out_path=out_path)
        print(json.dumps(payload, indent=2))
        return 2

    if skipped:
        verdict.coverage.setdefault("skipped_cells", skipped)
        if out_path is not None:
            out_path.write_text(json.dumps(verdict.to_dict(), indent=2))

    print(render(verdict, skipped))
    if out_path is not None:
        print(f"\nwrote {out_path}")

    # 0 = PASS, 1 = FAIL or INSUFFICIENT_GRID, 2 = ERROR (returned above).
    # INSUFFICIENT_GRID is non-zero on purpose: it is never a pass.
    return 0 if verdict.verdict == VERDICT_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
