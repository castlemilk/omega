"""V262-2 — intraday composite z (LOCKED per V262-2.md §3/§4).

The composite is the **mean of signed z-scores** of its members, on the z-score
scale — the V261 construction (``on_chain_flow/signals.py``), rebased to the 1h grid.

### Native-cadence z, then forward-fill (V262-2.md §4)

Every member is z-scored over **30 of its OWN observations**, and only the resulting
z is forward-filled onto the 1h grid. Z-scoring after the fill would be degenerate:
a forward-filled daily series is piecewise-constant, so a 30-*bar* window spans ~1.25
days, is very often perfectly flat, trips the ``std == 0`` fence, and the
all-or-nothing composite fence would then drop nearly every bar.

### Fences (never epsilons — the V221 lesson)

- ``std == 0`` ⇒ the member yields **no** z for that observation (semantic fence).
  An epsilon here is exactly the V221 epsilon-guard amplifier that turned rounding
  residue into an O(1) signal.
- A bar carries a composite only when **every** member has a valid z at that bar
  (all-or-nothing), so a partially-covered bar is skipped rather than silently
  down-weighted.

Determinism: ``math.fsum`` for every reduction; no numpy, no wall clock.
"""

from __future__ import annotations

import math

from .loader import IntradayLoader

WINDOW = 30  # observations, at each member's native cadence (V262-2.md §4)

# member -> declared sign (V262-2.md §3a). `hourly_return_z` is the arm-dependent
# one (+1 momentum / -1 reversion) and is supplied by the caller, not fixed here.
COMPOSITE_SIGNS: dict[str, float] = {
    "funding": -1.0,  # positive funding = crowded longs => short (V255.C direction)
    "open_interest": -1.0,  # rising OI into a move = crowding (V240.B read)
    "fear_greed": -1.0,  # contrarian sentiment (features.py:1827 crisis-poison note)
    "vix": -1.0,  # risk-off => crypto bearish
    "dxy": -1.0,  # strong dollar => crypto bearish
    "yield_curve": +1.0,  # steepening => risk-on
    "gdelt": +1.0,  # positive news tone => risk-on
}

# Full member set of the primary composite (return sign applied separately).
MEMBER_KEYS = ("hourly_return_z", *COMPOSITE_SIGNS.keys())

# The genuinely-new-information subset (V262.md §5) — diagnostic arm only.
NATIVE_MEMBER_KEYS = ("hourly_return_z",)

_GDELT_TONE = (
    "gdelt_tone_central_bank",
    "gdelt_tone_crypto_regulation",
    "gdelt_tone_financial_crisis",
    "gdelt_tone_geopolitical",
    "gdelt_tone_sanctions",
)


def _sample_std(window: list[float], mean: float) -> float:
    """Sample std (ddof=1) via fsum."""
    ss = math.fsum((x - mean) ** 2 for x in window)
    return math.sqrt(ss / (len(window) - 1))


def rolling_z(series: list[float | None], window: int = WINDOW) -> list[float | None]:
    """Trailing z of each observation vs its previous ``window`` obs (inclusive).

    ``None`` where the window is incomplete, contains a hole, or is degenerate
    (``std == 0``). Causal by construction: index ``i`` uses only ``[i-window+1, i]``.
    """
    out: list[float | None] = [None] * len(series)
    for i in range(window - 1, len(series)):
        w = series[i - window + 1 : i + 1]
        if any(v is None for v in w):
            continue
        vals = [float(v) for v in w]  # type: ignore[arg-type]
        mean = math.fsum(vals) / len(vals)
        std = _sample_std(vals, mean)
        if std == 0.0:
            continue  # semantic degeneracy fence, never an epsilon (V221)
        out[i] = (vals[-1] - mean) / std
    return out


def _daily_z_ffilled(
    loader: IntradayLoader, values: dict[str, float], bar_times: list[int]
) -> list[float | None]:
    """z-score a daily ``{date: value}`` feed on its own grid, then forward-fill to bars."""
    dates = sorted(values)
    zs = rolling_z([values[d] for d in dates])
    z_by_date = {d: z for d, z in zip(dates, zs, strict=True) if z is not None}
    return loader.ffill_onto(z_by_date, bar_times)


def _combine_daily(parts: list[dict[str, float]], op: str) -> dict[str, float]:
    """Combine daily feeds on their common dates. ``op`` is 'sub' (a-b) or 'mean'."""
    common = set(parts[0])
    for p in parts[1:]:
        common &= set(p)
    if op == "sub":
        return {d: parts[0][d] - parts[1][d] for d in sorted(common)}
    return {d: math.fsum(p[d] for p in parts) / len(parts) for d in sorted(common)}


def build_members(
    loader: IntradayLoader,
    symbol: str,
    bar_times: list[int],
    close: list[float],
    volume: list[float],
) -> dict[str, list[float | None]]:
    """Per-bar z for every composite member, plus the ``hourly_volume_z`` filter series.

    Returns ``{member_key: [z or None per bar]}``. Signs are NOT applied here.
    """
    # ---- intraday-native (30-bar windows on the 1h grid) ----
    log_ret: list[float | None] = [None]
    for i in range(1, len(close)):
        prev, cur = close[i - 1], close[i]
        log_ret.append(math.log(cur / prev) if prev > 0.0 and cur > 0.0 else None)
    members: dict[str, list[float | None]] = {
        "hourly_return_z": rolling_z(log_ret),
        "hourly_volume_z": rolling_z([float(v) for v in volume]),
    }

    # ---- daily feeds (30-day windows on their own grids, then forward-filled) ----
    sym_lc = symbol.lower()
    members["funding"] = _daily_z_ffilled(
        loader, loader.load_feed(f"binance_funding_{sym_lc}"), bar_times
    )
    members["open_interest"] = _daily_z_ffilled(
        loader, loader.load_feed(f"binance_oi_{sym_lc}"), bar_times
    )
    members["fear_greed"] = _daily_z_ffilled(loader, loader.load_feed("fng"), bar_times)
    members["vix"] = _daily_z_ffilled(loader, loader.load_feed("fred_vixcls"), bar_times)
    members["dxy"] = _daily_z_ffilled(loader, loader.load_feed("fred_dtwexbgs"), bar_times)
    members["yield_curve"] = _daily_z_ffilled(
        loader,
        _combine_daily([loader.load_feed("fred_dgs10"), loader.load_feed("fred_dgs2")], "sub"),
        bar_times,
    )
    # gdelt: mean of the five tone series' daily z-scores (V262-2.md §4)
    tone_dailies = [loader.load_feed(n) for n in _GDELT_TONE]
    tone_zs = []
    for feed in tone_dailies:
        dates = sorted(feed)
        zs = rolling_z([feed[d] for d in dates])
        tone_zs.append({d: z for d, z in zip(dates, zs, strict=True) if z is not None})
    common = set(tone_zs[0])
    for t in tone_zs[1:]:
        common &= set(t)
    gdelt_z = {d: math.fsum(t[d] for t in tone_zs) / len(tone_zs) for d in sorted(common)}
    members["gdelt"] = loader.ffill_onto(gdelt_z, bar_times)
    return members


def composite_z_series(
    members: dict[str, list[float | None]],
    include: tuple[str, ...],
    return_sign: float,
) -> list[float | None]:
    """Mean of signed member z's per bar; ``None`` unless EVERY included member is valid.

    ``return_sign`` is the arm's ``hourly_return_z`` sign (+1 momentum / −1 reversion,
    V262-2.md §3b). ``hourly_volume_z`` is never a composite member — it is the entry
    filter, applied in ``sim.py``.
    """
    n = len(next(iter(members.values())))
    out: list[float | None] = [None] * n
    for i in range(n):
        signed: list[float] = []
        ok = True
        for key in include:
            z = members[key][i]
            if z is None:
                ok = False
                break
            sign = return_sign if key == "hourly_return_z" else COMPOSITE_SIGNS[key]
            signed.append(sign * z)
        if ok and signed:
            out[i] = math.fsum(signed) / len(signed)
    return out
