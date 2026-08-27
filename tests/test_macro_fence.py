"""V278 G1: the H2 macro-lookahead fence is a real arm, not a decorative one.

V273 §6 H2: under ``OMEGA_FROZEN_CACHE=1`` the macro cache anchors its lookback to its
own newest row (``data_cache.py:298``) instead of the replayed bar. The committed cache
spans 2025-12-09 -> 2026-06-10 and every walk-forward window predates its EARLIEST row,
so ``dxy_signal`` and ``yield_curve`` read years of the replayed bar's future.
``vix_signal``/``spy_signal`` fence this class of leak; these two never did.

These tests exist because of the V275 lesson: three of V49's "hard gates" spent months
unable to fail, and nobody noticed. If ``OMEGA_MACRO_BAR_FENCE=1`` did not actually
change what these signals read, V278's measured Δ would be $0 for a reason that has
nothing to do with the finding.
"""

from __future__ import annotations

import os
from unittest import mock

from omega.nodes.victoria.signals.dxy_signal import DXYSignal
from omega.nodes.victoria.signals.yield_curve import YieldCurveSignal


def _env(**kw: str | None) -> mock._patch_dict:
    return mock.patch.dict(os.environ, {k: v for k, v in kw.items() if v is not None},
                           clear=False)


def test_fence_is_inert_unless_both_env_vars_set() -> None:
    """The arm must be OFF by default, or V278 is not byte-identical to pre-V278.

    Frozen-without-the-arm is the standing configuration every committed number was
    produced under; if the fence fired there, this version would silently move the
    baseline instead of measuring it.
    """
    from omega.nodes.victoria.signals import dxy_signal as mod

    with _env(OMEGA_FROZEN_CACHE="1", OMEGA_MACRO_BAR_FENCE=None):
        os.environ.pop("OMEGA_MACRO_BAR_FENCE", None)
        assert mod._macro_fence_active() is False, (
            "fence fired with OMEGA_MACRO_BAR_FENCE unset — V278's arm-OFF is not "
            "byte-identical to pre-V278 and every gate in it is invalid."
        )

    with _env(OMEGA_MACRO_BAR_FENCE="1"):
        os.environ.pop("OMEGA_FROZEN_CACHE", None)
        assert mod._macro_fence_active() is False, (
            "fence fired outside frozen mode — this would alter LIVE trading, which "
            "V278 explicitly does not touch."
        )


def test_dxy_reads_macro_without_the_fence_and_stops_with_it() -> None:
    """G1 positive control for `dxy_signal`.

    Without the arm the loader reaches the cache; with it, the loader short-circuits
    to an empty series and never consults the cache at all. The `assert_not_called`
    is the part that matters: it proves the leak path is closed, not merely that the
    return value changed.
    """
    sig = DXYSignal()
    fake_cache = mock.MagicMock()
    fake_cache.get_values.return_value = [100.0] * 60
    sig._cache = fake_cache

    with _env(OMEGA_FROZEN_CACHE="1"):
        os.environ.pop("OMEGA_MACRO_BAR_FENCE", None)
        assert sig._get_dollar_prices() == [100.0] * 60
        fake_cache.get_values.assert_called()

    fake_cache.reset_mock()
    with _env(OMEGA_FROZEN_CACHE="1", OMEGA_MACRO_BAR_FENCE="1"):
        assert sig._get_dollar_prices() == []
        fake_cache.get_values.assert_not_called()


def test_yield_curve_reads_macro_without_the_fence_and_stops_with_it() -> None:
    """G1 positive control for `yield_curve`, and that its public API degrades cleanly.

    The fence routes through the signal's pre-existing "data unavailable" path, so
    `compute()` returns the neutral 0.0 and `compute_with_meta()` returns the `stub`
    dict rather than raising on `self._rates_10y[-1]`.
    """
    sig = YieldCurveSignal()
    fake_cache = mock.MagicMock()
    fake_cache.get_values.return_value = [4.0] * 90
    sig._cache = fake_cache

    with _env(OMEGA_FROZEN_CACHE="1"):
        os.environ.pop("OMEGA_MACRO_BAR_FENCE", None)
        assert sig._load_rates("DGS10") == [4.0] * 90
        fake_cache.get_values.assert_called()

    fake_cache.reset_mock()
    with _env(OMEGA_FROZEN_CACHE="1", OMEGA_MACRO_BAR_FENCE="1"):
        assert sig._load_rates("DGS10") == []
        fake_cache.get_values.assert_not_called()

        fenced = YieldCurveSignal()
        fenced._cache = fake_cache
        assert fenced.compute() == 0.0
        meta = fenced.compute_with_meta()
        assert meta["mode"] == "stub" and meta["signal"] == 0.0
