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
    ap.add_argument("--expect-gate", choices=("on", "off"), default="off",
                    help="V226: what the cell label CLAIMS for the crisis_skew regime "
                         "gate. When 'on', a skew-ON cell may legitimately fire 0 cycles "
                         "(the gate suppresses the term outside crisis/high_vol), so the "
                         "skew_on_cycles>0 inertness check is relaxed to 'gate was "
                         "evaluated' (accept+skip cycles > 0).")
    ap.add_argument("--expect-brake", choices=("on", "off"), default="off",
                    help="V232: what the cell label CLAIMS for the rv_term_structure "
                         "brake. Like the gated skew, a brake-ON cell may legitimately "
                         "fire 0 cycles when the V227 drawdown-AND-gate suppresses it "
                         "(the documented 2024aug inertness the brake inherits) — so the "
                         "inertness guard is RELAXED to 'flag set as claimed' + "
                         "'fired count bounded by gate-accepted cycles', NOT 'fired > 0'.")
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

    # V226: gate-aware identity. crisis_skew_regime_gate_enabled must match the
    # cell's claimed --expect-gate (a skew-ON cell that claims gate-ON but ran the
    # always-on V225 path — or vice versa — is mislabeled, the V224 bug class).
    # V229: only meaningful when skew is ON. The regime gate is consulted ONLY inside
    # the crisis_skew_enabled block (signal_generation), so when skew is OFF the gate
    # flag is inert (skew_on_cycles=0 regardless). Since V227 flipped its default to
    # True, an equal-weight control (skew OFF) carries gate=True-but-inert and would
    # spuriously FAIL this check — the cosmetic OFF-cell FAIL seen in the V228/V229
    # grids. Skip the gate-identity check when the cell is skew-OFF.
    want_gate = args.expect_gate == "on"
    got_gate = bool(obs.get("crisis_skew_regime_gate_enabled", False))
    if want_skew and got_gate != want_gate:
        _fail(
            f"crisis_skew_regime_gate_enabled={got_gate} but cell claims gate="
            f"{args.expect_gate!r} (label/run mismatch — the V224 control-bug class)"
        )

    skew_cycles = int(obs.get("skew_on_cycles", 0))
    gate_accept = int(obs.get("skew_gate_accept_cycles", 0))
    gate_skip = int(obs.get("skew_gate_skip_cycles", 0))
    if want_skew and want_gate:
        # Gated skew-ON: the term may legitimately fire 0 cycles (gate suppresses it
        # outside crisis/high_vol — exactly the no-harm goal on trend/recent). The
        # inertness guard becomes "the gate was actually EVALUATED" — accept+skip
        # must cover the run; otherwise the gate code path never ran (silent
        # inertness). skew_on_cycles must not exceed gate_accept (a fired cycle is
        # by definition an accepted cycle).
        if gate_accept + gate_skip <= 0:
            _fail(
                "crisis_skew gate ON but accept+skip cycles=0 — the gate code path "
                "never ran (silent-inertness class V148–V202)"
            )
        if skew_cycles > gate_accept:
            _fail(
                f"skew_on_cycles={skew_cycles} > gate_accept_cycles={gate_accept} — a "
                f"fired cycle must be a gate-accepted cycle (gate accounting broken)"
            )
    elif want_skew and skew_cycles <= 0:
        _fail(
            f"crisis_skew_enabled=True but skew_on_cycles={skew_cycles} — the term is "
            f"flag-ON but INERT (never fired; silent-inertness class V148–V202)"
        )
    if not want_skew and skew_cycles != 0:
        _fail(
            f"crisis_skew claims OFF but skew_on_cycles={skew_cycles} — the term fired "
            f"in a cell labeled skew-OFF"
        )

    # V232: brake identity. rv_brake_enabled must match --expect-brake. Because the
    # brake reuses the V227 drawdown-AND-gate (inert on 2024aug, by design), a
    # brake-ON cell may legitimately fire 0 cycles — so we do NOT require
    # rv_brake_on_cycles>0. We require (a) the flag matches the claim and (b) a fired
    # cycle is a gate-accepted cycle. A brake-OFF cell that fired is the V224 bug.
    want_brake = args.expect_brake == "on"
    got_brake = bool(obs.get("rv_brake_enabled", False))
    if got_brake != want_brake:
        _fail(
            f"rv_brake_enabled={got_brake} but cell claims brake={args.expect_brake!r} "
            f"(label/run mismatch — the V224 control-bug class)"
        )
    brake_cycles = int(obs.get("rv_brake_on_cycles", 0))
    rv_gate_accept = int(obs.get("rv_brake_gate_accept_cycles", 0))
    if want_brake and brake_cycles > rv_gate_accept:
        _fail(
            f"rv_brake_on_cycles={brake_cycles} > rv_brake_gate_accept_cycles="
            f"{rv_gate_accept} — a braked cycle must be a gate-accepted cycle "
            f"(brake/gate accounting broken)"
        )
    if not want_brake and brake_cycles != 0:
        _fail(
            f"brake claims OFF but rv_brake_on_cycles={brake_cycles} — the brake fired "
            f"in a cell labeled brake-OFF"
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
        f"on_cycles={skew_cycles}); gate={args.expect_gate} (enabled={got_gate}, "
        f"accept={gate_accept}, skip={gate_skip}); brake={args.expect_brake} "
        f"(enabled={got_brake}, on_cycles={brake_cycles}, accept={rv_gate_accept}); "
        f"ic={args.expect_ic} (on_cycles={ic_on}, source={ic_source})"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
