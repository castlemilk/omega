"""V275/V276: the IC-weighting defaults are code defaults, not a clerical habit.

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
import re

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


def test_per_regime_ic_weighting_defaults_off() -> None:
    """V276: the second half of the V273/H3 defect class, closed in the safe order.

    V275 deliberately left this flag at ``True``. Its Phase 0 audit found that
    ``per_regime_ic_weighting`` was absent from **all 44** feature-JSON arms, and that
    in the 7 arms running ``ic_seed_weighting: true`` it was **live and load-bearing**
    -- including ``scripts/v274_ic_on_grid.sh`` and ``scripts/v274_smoke.sh``, the arms
    behind V274's headline IC-ON result. Flipping the default first would have silently
    redefined what those arms measured.

    V276 pinned ``"per_regime_ic_weighting": true`` into all 7 of them first (a no-op
    edit preserving the inherited value -- see
    ``test_no_arm_inherits_per_regime_ic_weighting``), and only then flipped this
    default. Doing it in the other order rewrites history.

    This assertion FAILS at pre-V276 code. That is the point.
    """
    assert VictoriaFeatures().per_regime_ic_weighting is False


def test_no_arm_inherits_per_regime_ic_weighting() -> None:
    """No IC-ON arm may inherit ``per_regime_ic_weighting`` from the default.

    This is the guard that makes the flip safe *and keeps it safe*. Any arm that
    enables ``ic_seed_weighting`` populates ``_regime_ics`` and thereby makes the
    per-regime flag live (see ``test_regime_ics_only_populated_under_ic_seed_weighting``
    for the mechanism). Such an arm must state the value it wants rather than inherit
    whatever ``features.py`` currently says -- otherwise a future default change
    silently redefines the arm, which is the exact defect V275/V276 exist to close.

    Comment lines are excluded; only real assignments are checked.
    """
    ic_on = re.compile(r'\\?"ic_seed_weighting\\?"\s*:\s*true')
    per_regime = re.compile(r'\\?"per_regime_ic_weighting\\?"\s*:\s*')

    inheriting: list[str] = []
    checked = 0
    for path in sorted((_REPO / "scripts").glob("*.sh")):
        for lineno, line in enumerate(path.read_text(errors="replace").split("\n"), 1):
            if line.lstrip().startswith("#") or not ic_on.search(line):
                continue
            checked += 1
            if not per_regime.search(line):
                inheriting.append(f"{path.relative_to(_REPO)}:{lineno}")

    assert checked > 0, "no IC-ON arms found -- the scanner's regex has rotted."
    assert inheriting == [], (
        "these IC-ON arms inherit per_regime_ic_weighting from the features.py "
        f"default instead of pinning it: {inheriting}. See training_log/V276.md §3."
    )


def test_regime_ics_only_populated_under_ic_seed_weighting() -> None:
    """The mechanism behind V276's safety argument -- asserted, not assumed.

    Unlike its sibling, ``per_regime_ic_weighting`` **does** have strategy-layer
    consumers (``strategy.py:1135``, and the guards at ``:1205``/``:1223``). So the
    flip is not safe "by construction" the way V275's was. It is safe *conditionally*:
    both guards read ``if _per_regime and self._regime_ics``, and ``_regime_ics`` is
    empty unless something populates it.

    ``update_regime_ics`` has exactly one caller in ``scripts/``, and that call sits
    inside the block gated on ``ic_seed_weighting`` at ``run_training.py:1106``. So
    with IC-seeding off, ``_regime_ics`` is ``{}``, the guards short-circuit, and the
    flag cannot be observed at any value.

    If a second populate path is ever added -- or the existing one escapes the gate --
    that argument is void, and this test is what says so.
    """
    runner = _REPO / "scripts" / "run_training.py"
    tree = ast.parse(runner.read_text(encoding="utf-8", errors="replace"), str(runner))

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "update_regime_ics"
    ]
    assert len(calls) == 1, (
        f"expected exactly 1 update_regime_ics call in scripts/run_training.py, "
        f"found {len(calls)} at lines {[c.lineno for c in calls]}. V276 §2's "
        "conditional-inertness argument assumed a single populate path."
    )

    gated = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and "ic_seed_weighting" in _attribute_and_getattr_names_from_node(node.test)
    ]
    assert gated, "no `if ...ic_seed_weighting...` gate found in scripts/run_training.py"

    call_line = calls[0].lineno
    enclosing = [
        node
        for node in gated
        if node.body
        and node.body[0].lineno <= call_line <= max(
            getattr(child, "end_lineno", child.lineno) for child in node.body
        )
    ]
    assert enclosing, (
        f"update_regime_ics (line {call_line}) is NOT inside an ic_seed_weighting-gated "
        "block. _regime_ics can now be populated with IC-seeding off, which voids "
        "V276 §2's safety argument for flipping per_regime_ic_weighting. Re-audit."
    )


def _attribute_and_getattr_names_from_node(root: ast.AST) -> set[str]:
    """Names an AST subtree actually *reads* -- ``x.foo`` and ``getattr(x, "foo", ...)``.

    Parsed via ``ast`` so prose (comments, docstrings) is excluded by construction.
    """
    names: set[str] = set()
    for node in ast.walk(root):
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


def _attribute_and_getattr_names(path: pathlib.Path) -> set[str]:
    """``_attribute_and_getattr_names_from_node`` over a whole module."""
    return _attribute_and_getattr_names_from_node(
        ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
    )


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
