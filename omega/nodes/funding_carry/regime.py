"""Funding-regime classifier — the key differentiator from spot regimes.

Funding regimes are driven by market *structure* (leverage demand, basis-trade
positioning, deleveraging events) — NOT by spot direction (crisis/trend/recent).
A date's funding regime is derived from a market-wide funding index and its
recent volatility, using **pre-registered fixed boundaries** (anti-Goodhart:
the classifier is defined independent of, and before, any strategy outcome).

Regimes:
  * POSITIVE_CARRY — crowded longs, funding structurally elevated
  * NEGATIVE_CARRY — crowded shorts, funding structurally depressed
  * NEAR_ZERO      — balanced book, little carry to harvest
  * HIGH_VOL       — funding turbulence (deleveraging / squeeze) dominates

The market funding index on date ``t`` is the cross-sectional mean of each
present symbol's daily funding. Its 30d trailing average (level) and 30d
trailing std (turbulence) are standardized over the full span, then binned.
Full-span standardization is a *descriptive* classification for window
counting — it is never fed to the trading signal (which uses only trailing
per-symbol z-scores). Boundaries are fixed a priori, not tuned to PnL.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class FundingRegime(str, Enum):
    POSITIVE_CARRY = "positive_carry"
    NEGATIVE_CARRY = "negative_carry"
    NEAR_ZERO = "near_zero"
    HIGH_VOL = "high_vol"


# Pre-registered fixed boundaries (in std units of the full-span index).
_LEVEL_HI = 0.5
_LEVEL_LO = -0.5
_VOL_HI = 1.0
_AVG_LOOKBACK = 30


@dataclass
class FundingRegimeClassifier:
    """Assigns a FundingRegime to every date in the aligned span."""

    avg_lookback: int = _AVG_LOOKBACK

    def classify_span(
        self, dates: list[str], market_index: list[float]
    ) -> dict[str, FundingRegime]:
        """Return {date: FundingRegime} for the full span.

        ``market_index[i]`` is the cross-sectional mean funding on ``dates[i]``.
        Days before the lookback is available fall back to NEAR_ZERO.

        **Full-span standardization** — every date's label depends on the mean
        and std of the ENTIRE series, including that date's future. Legitimate
        for descriptive window counting inside a scorer; NOT computable
        forward. Use :meth:`classify_span_causal` for anything online.
        """
        return self._classify(dates, market_index, causal=False)

    def classify_span_causal(
        self, dates: list[str], market_index: list[float]
    ) -> dict[str, FundingRegime]:
        """Causal twin of :meth:`classify_span` (V272).

        Identical in every respect except that the two standardizations use an
        **expanding window** (prefix only): date ``i``'s z-scores are computed
        from ``x[0..i]``, never from later dates. The 30d trailing avg/vol were
        already causal; the ``i < avg_lookback -> NEAR_ZERO`` burn-in and the
        fixed a-priori boundaries are unchanged. No extra burn-in parameter is
        introduced (that would be a tuned free parameter).
        """
        return self._classify(dates, market_index, causal=True)

    def _classify(
        self, dates: list[str], market_index: list[float], causal: bool
    ) -> dict[str, FundingRegime]:
        n = len(dates)
        avg = [0.0] * n
        vol = [0.0] * n
        for i in range(n):
            lo = max(0, i - self.avg_lookback + 1)
            window = market_index[lo : i + 1]
            m = math.fsum(window) / len(window)
            avg[i] = m
            if len(window) > 1 and max(window) != min(window):
                var = math.fsum((x - m) ** 2 for x in window) / len(window)
                vol[i] = math.sqrt(var)
            else:
                vol[i] = 0.0

        std_fn = _standardize_causal if causal else _standardize
        za = std_fn(avg)
        zv = std_fn(vol)

        out: dict[str, FundingRegime] = {}
        for i, d in enumerate(dates):
            if i < self.avg_lookback:
                out[d] = FundingRegime.NEAR_ZERO
                continue
            if zv[i] > _VOL_HI:
                out[d] = FundingRegime.HIGH_VOL
            elif za[i] > _LEVEL_HI:
                out[d] = FundingRegime.POSITIVE_CARRY
            elif za[i] < _LEVEL_LO:
                out[d] = FundingRegime.NEGATIVE_CARRY
            else:
                out[d] = FundingRegime.NEAR_ZERO
        return out


def build_market_index(
    universe: dict[str, "object"],  # dict[str, SymbolSeries]
) -> tuple[list[str], list[float]]:
    """Cross-sectional daily mean funding across all symbols present each day.

    Returns (dates, index) over the UNION of all symbol dates, canonical sorted.
    """
    per_date: dict[str, list[float]] = {}
    for s in universe.values():
        for d, f in zip(s.dates, s.funding):
            per_date.setdefault(d, []).append(f)
    dates = sorted(per_date)
    index = [math.fsum(per_date[d]) / len(per_date[d]) for d in dates]
    return dates, index


def _standardize(xs: list[float]) -> list[float]:
    n = len(xs)
    if n == 0:
        return []
    mean = math.fsum(xs) / n
    if n == 1:
        return [0.0]
    var = math.fsum((x - mean) ** 2 for x in xs) / n
    std = math.sqrt(var)
    if std == 0.0:
        return [0.0] * n
    return [(x - mean) / std for x in xs]


def _standardize_causal(xs: list[float]) -> list[float]:
    """Expanding-window standardization (V272): z[i] uses only ``xs[0..i]``.

    Population std over the prefix, ``math.fsum`` reductions (permutation
    invariant). ``z[0] = 0.0`` and any degenerate (constant) prefix yields
    ``0.0`` — a semantic degeneracy fence, never a small epsilon (V221).
    """
    out: list[float] = []
    for i in range(len(xs)):
        prefix = xs[: i + 1]
        m = len(prefix)
        if m == 1 or max(prefix) == min(prefix):
            out.append(0.0)
            continue
        mean = math.fsum(prefix) / m
        var = math.fsum((x - mean) ** 2 for x in prefix) / m
        std = math.sqrt(var)
        out.append(0.0 if std == 0.0 else (prefix[-1] - mean) / std)
    return out
