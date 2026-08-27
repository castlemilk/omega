"""ASX — Australian equities project node.

A PROJECT node (see CLAUDE.md "Platform vs Project Separation"): it may import from
`omega/core` and the node base classes, and platform code must never import from here.

Forked from Victoria's *method*, not its model. V286 Phase 0 measured that Victoria's
one working signal (`sma_crossover`, +0.0399 OOS on crypto) does NOT transfer to the
ASX — it reads -0.0226 all-data and +0.0004 on held-out data. What the ASX data does
show, in all twelve MA-pair x horizon cells tested, is the OPPOSITE sign: MA-crossover
mean-REVERTS on ASX large caps at 1-6 month horizons.

That finding is NOT yet trustworthy — see `training_log/V286_PHASE0_ASX.md` §5. It was
measured on today's large caps, and survivorship bias manufactures exactly a reversion
signal. Resolving that is this project's first job, and nothing here should be treated
as a strategy until it is.
"""

from omega.nodes.asx.loader import (
    ASXUniverse,
    freeze_universe,
    load_frozen_bars,
    verify_frozen_manifest,
)
from omega.nodes.asx.shorted import ShortedClient, freeze_short_positions

__all__ = [
    "ASXUniverse",
    "ShortedClient",
    "freeze_short_positions",
    "freeze_universe",
    "load_frozen_bars",
    "verify_frozen_manifest",
]
