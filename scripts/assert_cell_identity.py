#!/usr/bin/env python3
"""V225 observability: control-identity assertion from run artifacts.

The V224 control bug was a cell that *claimed* equal-weight (IC-off) but actually
ran seed-IC on all 200 cycles — because its `features='{}'` inherited
`ic_seed_weighting=True` (features.py default). The grid label said one thing; the
run did another, and nobody checked until after the grid. This is the cheap,
high-leverage fix: read the run's `results.json` and assert its *actual* identity
(what it really ran) matches what the cell label *claims* it ran. Cheap (pure
JSON read), high-leverage (catches the entire class of mislabeled-control bug at
cell time instead of post-grid).

Checks (all from results['observability']):
  - crisis_skew_enabled == expected (--expect-skew on|off)
  - skew_on_cycles > 0  iff  --expect-skew on   (the term actually FIRED — guards
    against flag-on-but-inert, the V148–V202 silent-inertness class)
  - ic_on_cycles == 0   when --expect-ic off     (genuine equal-weight — the exact
    V224 control bug: a cell claiming equal-weight while IC ran 200 cycles)

Exit 0 = identity matches the claimed label. Non-zero = mismatch (the cell did
not run what its label says); the caller must STOP and not trust the cell's PnL.

Usage:
  python3 scripts/assert_cell_identity.py --results data/v225_skew_trend_r1_results.json \
      --expect-skew on --expect-ic off
"""

from __future__ import annotations

import argparse
import json
import sys


def _fail(msg: str) -> None:
    print(f"CELL-IDENTITY: FAIL — {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Assert a run's actual identity matches its cell label.")
    ap.add_argument("--results", required=True, help="path to {version}_results.json")
    ap.add_argument("--expect-skew", choices=("on", "off"), required=True,
                    help="what the cell label CLAIMS for crisis_skew")
    ap.add_argument("--expect-ic", choices=("on", "off"), default="off",
                    help="what the cell label CLAIMS for IC weighting (default off)")
    args = ap.parse_args()

    try:
        with open(args.results) as fh:
            results = json.load(fh)
    except Exception as exc:
        _fail(f"cannot read results {args.results!r}: {exc}")

    obs = results.get("observability")
    if not isinstance(obs, dict):
        _fail(f"results {args.results!r} has no 'observability' block")

    want_skew = args.expect_skew == "on"
    # crisis_skew_enabled defaults to False for runs predating V225; treat missing
    # as False so a skew-OFF assertion passes against old artifacts.
    got_skew = bool(obs.get("crisis_skew_enabled", False))
    if got_skew != want_skew:
        _fail(
            f"crisis_skew_enabled={got_skew} but cell claims skew={args.expect_skew!r} "
            f"(label/run mismatch — the V224 control-bug class)"
        )

    skew_cycles = int(obs.get("skew_on_cycles", 0))
    if want_skew and skew_cycles <= 0:
        _fail(
            f"crisis_skew_enabled=True but skew_on_cycles={skew_cycles} — the term is "
            f"flag-ON but INERT (never fired; silent-inertness class V148–V202)"
        )
    if not want_skew and skew_cycles != 0:
        _fail(
            f"crisis_skew claims OFF but skew_on_cycles={skew_cycles} — the term fired "
            f"in a cell labeled skew-OFF"
        )

    ic_on = int(obs.get("ic_on_cycles", 0))
    want_ic = args.expect_ic == "on"
    if not want_ic and ic_on != 0:
        _fail(
            f"cell claims IC OFF (equal-weight) but ic_on_cycles={ic_on} — the exact "
            f"V224 control bug (claimed equal-weight, ran IC weighting)"
        )
    if want_ic and ic_on <= 0:
        _fail(f"cell claims IC ON but ic_on_cycles={ic_on} (IC never applied)")

    ic_source = obs.get("ic_source", "?")
    print(
        f"CELL-IDENTITY: PASS — skew={args.expect_skew} (enabled={got_skew}, "
        f"on_cycles={skew_cycles}); ic={args.expect_ic} (on_cycles={ic_on}, "
        f"source={ic_source})"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
