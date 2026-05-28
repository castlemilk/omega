# V### — <short phase name>

**Date:** YYYY-MM-DD
**Author:** <you / claude>
**Parent:** V### (previous version)
**Status:** planned | running | complete | reverted

## Hypothesis

One paragraph: what's the bet? What signal/gate/sizing change do we
believe will move which metric, and why?

## Changes

- Files touched: `path/to/file.py`, …
- Configs / preset name:
- Feature flags toggled:
- Anything reverted vs parent:

## Gate results

| Gate    | PnL | Trades | WR | PF | Max DD | Notes |
|---------|----:|-------:|---:|---:|-------:|-------|
| recent  |     |        |    |    |        |       |
| trend   |     |        |    |    |        |       |
| crisis  |     |        |    |    |        |       |

Result files: `data/v###_<gate>_results.json`, `data/v###_<gate>_trades.csv`.
Gate-pass report: `data/v###_<gate>_gate_result.json`.

## Conclusion

- What held up?
- What regressed?
- Was the hypothesis confirmed, refuted, or inconclusive?
- High-water mark broken? (update `README.md`)

## Next steps

→ **V###+1**: <one-sentence brief for the next version>.

Open questions / parking lot:
- …
