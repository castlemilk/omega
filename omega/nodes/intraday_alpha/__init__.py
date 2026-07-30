"""V262-2 — intraday (1h) alpha offline scorer.

A self-contained offline scorer for the V262 intraday thesis, built on the
V255.C / V261 pattern: read the frozen series directly, compute the
pre-registered falsifier statistics, no node DAG, no cycle loop, no sleep.

**This package imports nothing from ``omega.nodes.victoria``** and contains no
strategy code. It reuses only the audited pure-statistics helpers from
``funding_carry.phase0_separator`` (MWU, median, stats) — the same reuse V261
made.

Parameters are LOCKED to ``victoria/training_log/V262-2.md``. See that document
for the provenance of every constant; nothing here may be tuned after a result
is seen.
"""

from .loader import IntradayLoader
from .signals import COMPOSITE_SIGNS, MEMBER_KEYS, composite_z_series
from .sim import IntradayParams, IntradayTrade, simulate_symbol

__all__ = [
    "COMPOSITE_SIGNS",
    "MEMBER_KEYS",
    "IntradayLoader",
    "IntradayParams",
    "IntradayTrade",
    "composite_z_series",
    "simulate_symbol",
]
