"""V282: scipy is baseline-affecting, and its absence must be loud in frozen runs.

Without scipy, `wasserstein_regime.py` falls back from `scipy.stats.wasserstein_distance`
to a mean-distance approximation. That is a different regime-detection ALGORITHM, not an
approximation of the same number: it changes regime distances, hence labels, hence the
regime-adaptive conviction thresholds, hence the trades. Bisected in V282, it alone moved
crisis by -$66.96 and recent by +$52.83, and it cost V276/V277 two versions to find
because it announced itself only as a `logger.warning`.
"""

from __future__ import annotations

import os
import pathlib
import tomllib
from unittest import mock

import pytest

from omega.nodes.victoria import wasserstein_regime as wr

_REPO = pathlib.Path(__file__).resolve().parents[1]


def test_scipy_is_declared_in_pyproject() -> None:
    """It was declared NOWHERE for the campaign's whole life. Never again silently."""
    data = tomllib.loads((_REPO / "pyproject.toml").read_text())
    extras = data["project"]["optional-dependencies"]
    declared = {
        pkg.split(">=")[0].split("==")[0].strip()
        for group in extras.values()
        for pkg in group
    } | {
        pkg.split(">=")[0].split("==")[0].strip()
        for pkg in data["project"].get("dependencies", [])
    }
    assert "scipy" in declared, (
        "scipy is undeclared again. The standing baseline depends on it "
        "(training_log/V282.md); an undeclared baseline-affecting dependency is how "
        "the V276 off-host deviation happened."
    )


def test_frozen_run_without_scipy_raises() -> None:
    """G2 positive control — the hardening must be able to fire.

    Mirrors the V219 rule ("refuse to produce a baseline on a drifted substrate"),
    applied to the code substrate.
    """
    with (
        mock.patch.object(wr, "_SCIPY_AVAILABLE", False),
        mock.patch.dict(os.environ, {"OMEGA_FROZEN_CACHE": "1"}),
    ):
        with pytest.raises(RuntimeError, match="V282"):
            wr.assert_scipy_for_frozen_runs()
        with pytest.raises(RuntimeError, match="scipy"):
            wr.WassersteinRegimeDetector()


def test_live_run_without_scipy_still_degrades_gracefully() -> None:
    """G3 — degraded live trading beats no live trading.

    A live run is not claiming comparability with a committed number, so the fallback
    is acceptable there. Only a frozen run, whose entire purpose is comparability, must
    refuse.
    """
    env = {k: v for k, v in os.environ.items() if k != "OMEGA_FROZEN_CACHE"}
    with (
        mock.patch.object(wr, "_SCIPY_AVAILABLE", False),
        mock.patch.dict(os.environ, env, clear=True),
    ):
        wr.assert_scipy_for_frozen_runs()  # must not raise
        assert wr.WassersteinRegimeDetector() is not None


def test_frozen_run_with_scipy_is_unaffected() -> None:
    """The assertion must be inert in the configuration everything actually runs in."""
    with (
        mock.patch.object(wr, "_SCIPY_AVAILABLE", True),
        mock.patch.dict(os.environ, {"OMEGA_FROZEN_CACHE": "1"}),
    ):
        wr.assert_scipy_for_frozen_runs()  # must not raise
