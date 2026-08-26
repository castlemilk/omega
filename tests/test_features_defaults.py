"""V275: the IC-weighting defaults are a code default, not a clerical habit.

Background (V273 H3 -> V274 -> V275):

V273's full-span-lookahead audit flagged ``ic_seed_weighting`` and
``per_regime_ic_weighting`` (``omega/nodes/victoria/features.py``) as **defaults-ON**
while every grid arm that produced the standing baseline (crisis +$599 / trend
+$2,997 / recent +$30) types ``"ic_seed_weighting": false`` into its feature JSON by
hand. V274 audited all 32 cells behind that baseline and cleared it -- every cell
recorded the flag explicitly ``false``, and the re-run drifted 0.000000. The
measuring stick is causal.

But it was clean by **convention**, not by **construction**. Correctness rested on
each grid author remembering to type ``false``. These tests remove that dependency:
the defaults are now asserted, so the defect class cannot return silently.

These are pure default-value assertions -- no fixtures, no I/O, no strategy state.
"""

from __future__ import annotations

import ast
import pathlib

from omega.nodes.victoria.features import VictoriaFeatures

_REPO = pathlib.Path(__file__).resolve().parents[1]


def test_ic_seed_weighting_defaults_off() -> None:
    """The regression test for the V273/H3 defect class.

    ``ic_seed_weighting`` ON loads the seeded pooled + per-regime ICs from
    ``data/signal_ic_history.json`` -- values derived from completed training runs
    over the same corpus every walk-forward window is drawn from -- and feeds them to
    the conviction filter. On the default it did that *silently*: an arm that simply
    omitted the key inherited the overlay.

    V275 audited all 44 feature-JSON arms in ``scripts/*.sh``: **zero** of them
    inherit this default (every one sets the key explicitly), so flipping it to
    ``False`` is a no-op for every existing arm and a guard for every future one.

    This assertion FAILS on pre-V275 code. That is the point.
    """
    assert VictoriaFeatures().ic_seed_weighting is False


def test_per_regime_ic_weighting_default_is_pinned_true() -> None:
    """Deliberately pinned ``True`` -- do NOT "fix" this to match its sibling.

    V275's Phase 0 audit found the premise SPLITS. ``per_regime_ic_weighting`` is
    absent from **all 44** arms. In the 37 arms running ``ic_seed_weighting: false``
    it is doubly inert (``_regime_ics`` has no populate path outside the
    ``ic_seed_weighting``-gated block at ``scripts/run_training.py:1105-1155``). But
    in **7 arms it is live and load-bearing**::

        scripts/v224_run_grid.sh:37       R3F
        scripts/v228_run_grid.sh:15       ON
        scripts/v229_run_grid.sh:18       ON
        scripts/v229_xsweep.sh:11         (function-local `feats`)
        scripts/walk_forward_grid.sh:51   TRENDIC
        scripts/v274_ic_on_grid.sh:38     ARM_ON      <-- V274's own IC-ON arm
        scripts/v274_smoke.sh:32          ARM_ON      <-- V274's own IC-ON arm

    ``v274_ic_on_grid.sh:36`` says so in a comment: *"per_regime_ic_weighting is left
    at its features.py default"*. V274's headline result -- IC-ON moves all 32 cells,
    8 sign flips, nets inside every MDE -- was measured with per-regime weighting ON.
    Flipping this default would silently redefine that arm: a re-run would measure
    something different and report the same label. That is the very reproducibility
    defect V275 exists to close, pointed the other way.

    **The correct sequence** (queued as V276-hygiene): first pin
    ``"per_regime_ic_weighting": true`` explicitly into those 7 arms -- a no-op edit
    that preserves what they measured -- and only then flip this default and update
    this test. Doing it in the other order rewrites history.
    """
    assert VictoriaFeatures().per_regime_ic_weighting is True


def _attribute_and_getattr_names(path: pathlib.Path) -> set[str]:
    """Names a module actually *reads* -- ``x.foo`` and ``getattr(x, "foo", ...)``.

    Parsed via ``ast`` so prose (comments, docstrings) is excluded by construction.
    """
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            names.add(node.args[1].value)
    return names


def test_ic_seed_weighting_has_no_strategy_layer_consumer() -> None:
    """The flip provably cannot change strategy behaviour.

    ``ic_seed_weighting`` is a **runner**-level flag with exactly one consumer:
    ``scripts/run_training.py``, which gates whether the seeded ICs are pushed into
    ``StrategyNode.update_signal_ics`` / ``update_regime_ics``.

    ``strategy.py`` never reads it -- ``_compute_weighted_conviction`` branches on
    ``_signal_ics`` being non-empty, not on the flag. That is what makes V275's G2
    (every representative cell reproduces its committed PnL to the cent) a
    structural claim rather than an empirical hope. If a strategy-layer consumer is
    ever added, this test fails and G2's reasoning has to be redone.
    """
    victoria = _REPO / "omega" / "nodes" / "victoria"
    offenders = sorted(
        str(p.relative_to(_REPO))
        for p in victoria.rglob("*.py")
        if p.name != "features.py" and "ic_seed_weighting" in _attribute_and_getattr_names(p)
    )
    assert offenders == [], (
        "ic_seed_weighting gained a strategy-layer consumer: "
        f"{offenders}. V275's G2 argument (see training_log/V275.md §2) assumed "
        "the flag is read only by scripts/run_training.py."
    )

    runner = _REPO / "scripts" / "run_training.py"
    assert "ic_seed_weighting" in _attribute_and_getattr_names(runner), (
        "scripts/run_training.py no longer reads ic_seed_weighting -- the IC-off "
        "control has moved or been removed; re-audit before trusting this suite."
    )
