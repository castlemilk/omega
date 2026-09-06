"""Funding-carry — a parallel Victoria-independent alpha strategy (V255+).

Perpetual-futures funding-rate carry / mean-reversion. This package is a
FULLY SEPARATE strategy from ``omega/nodes/victoria``: its own data loader,
regime classifier, PnL accounting, and eval. It shares NO runtime state with
the spot Victoria book — the only overlap is that both read from the same
frozen data directory (read-only).

Rationale (V254 alt-data scoping, option B, ranked #1): funding regimes cycle
on a different clock than spot regimes, so a funding strategy manufactures
*genuinely independent* recent-regime windows rather than resampling the same
four that bound the spot book. See ``training_log/V255.md``.

Determinism contract (same as Victoria): PYTHONHASHSEED=42, ``math.fsum`` for
float reductions, canonical ``sorted`` iteration order everywhere.
"""

from .data import FundingDataLoader, SymbolSeries
from .regime import FundingRegime, FundingRegimeClassifier

__all__ = [
    "FundingDataLoader",
    "FundingRegime",
    "FundingRegimeClassifier",
    "SymbolSeries",
]
