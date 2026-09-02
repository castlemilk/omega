"""Target-portfolio construction for the ASX engine.

Long-only by default, and that is a measured decision rather than caution:
`V289 §7` decomposed the long/short spread and found ~60% of it sits in the long leg,
while the short leg is by construction the hardest-to-borrow names. Dropping the short
leg costs ~40% of a spread whose significance was already under 1, and removes the one
constraint that made the strategy unexecutable for a retail account.

The composition rule is MULTIPLICATIVE, never additive. V280 measured that adding
signals into an equal-weight composite cost $1k–$3.2k per window on the crypto book,
because a mediocre signal at equal weight dilutes a good one. Here the ranking signal
picks the names and every other input can only SCALE a weight that already exists. A
new input can therefore reduce risk or trim a position; it can never dilute the entry
decision, which is the failure mode that has cost this campaign the most.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("omega.nodes.asx.portfolio")


@dataclass(frozen=True)
class PortfolioSpec:
    """Sizing and eligibility rules. All bars are explicit so they can be pre-registered."""

    top_quantile: float = 0.20        # long the least-shorted quintile
    max_names: int = 25
    max_weight: float = 0.08          # concentration cap
    long_only: bool = True            # V289 §7: the long leg carries ~60% of the spread
    min_names_to_trade: int = 10      # refuse to trade a thin cross-section

    # LIVE since 2026-09-01. Upstream GetStockPrices now returns `volume` alongside a
    # split/dividend-adjusted close, so `panel.ApiPriceSource.adv20` computes a
    # point-in-time trailing 20-session dollar volume and this became a real filter.
    #
    # It is not a refinement. Without it the engine ranked sub-cent stocks where one
    # tick is a +20% return: AEU at $0.0140 -> $0.3500 contributed +200% to a single
    # week, 88E turns over $10k/day. Any statistic computed over a book like that
    # describes the tick size, not the signal.
    min_adv_aud: float | None = 500_000.0

    # A price floor does the same job on a different axis and needs no volume data.
    # Knowable at entry, so it introduces no lookahead.
    min_price_aud: float | None = 0.20


@dataclass
class Target:
    date: str
    weights: dict[str, float]
    diagnostics: dict[str, Any]


def _rank_ascending(scores: dict[str, float]) -> list[str]:
    """Least-shorted first. Ties broken by code so the output is deterministic —
    an unstable sort would make two identical runs disagree, which is exactly the
    class of non-determinism the Victoria campaign spent five versions chasing."""
    return [c for c, _ in sorted(scores.items(), key=lambda kv: (kv[1], kv[0]))]


def build_target(
    date: str,
    day: dict[str, dict[str, float]],
    spec: PortfolioSpec,
    scale: dict[str, float] | None = None,
) -> Target:
    """Build the target book for one date.

    `scale` is the multiplicative seam: a mapping of code -> [0,1] multiplier applied
    AFTER selection. Risk overlays, a news/announcement veto (#548), or a liquidity
    haircut (#551) all attach here. Nothing attached this way can introduce a position
    or dilute the ranking — it can only trim one that the signal already chose.
    """
    diagnostics: dict[str, Any] = {"universe": len(day), "reason": None}

    if len(day) < spec.min_names_to_trade:
        diagnostics["reason"] = (
            f"cross-section too thin ({len(day)} < {spec.min_names_to_trade}) — "
            "not trading rather than trading a noisy rank"
        )
        return Target(date, {}, diagnostics)

    # Liquidity and price screens run BEFORE ranking, so an excluded name cannot be
    # selected and cannot alter the quantile boundary either.
    eligible = dict(day)
    dropped: dict[str, int] = {}

    if spec.min_price_aud is not None:
        before = len(eligible)
        eligible = {c: v for c, v in eligible.items() if v["price"] >= spec.min_price_aud}
        dropped["below_min_price"] = before - len(eligible)

    have_adv = any("adv20_aud" in v for v in day.values())
    if spec.min_adv_aud is not None and have_adv:
        before = len(eligible)
        # A name with no ADV reading is EXCLUDED, not waved through: an absent
        # liquidity number is not evidence of liquidity (V279).
        eligible = {
            c: v for c, v in eligible.items()
            if v.get("adv20_aud") is not None and v["adv20_aud"] >= spec.min_adv_aud
        }
        dropped["below_min_adv_or_unknown"] = before - len(eligible)

    diagnostics["dropped"] = {k: v for k, v in dropped.items() if v}
    diagnostics["eligible"] = len(eligible)
    diagnostics["adv_data_present"] = have_adv
    if spec.min_adv_aud is not None and not have_adv:
        diagnostics["adv_filter_inert"] = "no volume in panel — price source lacks adv20"

    if len(eligible) < spec.min_names_to_trade:
        diagnostics["reason"] = (
            f"too few eligible after screens ({len(eligible)} < {spec.min_names_to_trade})"
        )
        return Target(date, {}, diagnostics)

    scores = {c: v["short"] for c, v in eligible.items()}
    ordered = _rank_ascending(scores)
    n = min(spec.max_names, max(1, int(len(ordered) * spec.top_quantile)))
    picked = ordered[:n]

    w = 1.0 / len(picked)
    weights = {c: min(w, spec.max_weight) for c in picked}

    if scale:
        applied = {c: max(0.0, min(1.0, scale.get(c, 1.0))) for c in weights}
        weights = {c: weights[c] * applied[c] for c in weights}
        trimmed = {c: round(m, 3) for c, m in applied.items() if m < 0.999}
        if trimmed:
            diagnostics["scaled"] = trimmed

    weights = {c: v for c, v in weights.items() if v > 0}
    total = sum(weights.values())
    if total > 0:
        # Re-normalise to fully invested, then RE-APPLY the cap and repeat.
        #
        # Normalising alone silently undoes the concentration cap: a 6-name book
        # capped at 8% sums to 0.48, and scaling that back to 1.0 returns every
        # position to 16.7% — the cap did nothing. That is how one corrupted
        # price (AIZ at $224.32, a New Zealand dual-listing) took a 16% position
        # and moved a single week by 66%.
        #
        # Iterating to a fixed point is the standard water-filling fix: cap,
        # redistribute the freed weight over uncapped names, cap again. When
        # every name is at the cap the book is deliberately left UNDER-invested
        # rather than breaching it — a concentration limit that yields whenever
        # it binds is not a limit.
        for _ in range(16):
            weights = {c: v / total for c, v in weights.items()}
            over = {c: v for c, v in weights.items() if v > spec.max_weight + 1e-12}
            if not over:
                break
            weights = {c: min(v, spec.max_weight) for c, v in weights.items()}
            total = sum(weights.values())
            if total <= 0 or len(over) == len(weights):
                break
        capped_total = sum(weights.values())
        if capped_total > 1.0 + 1e-9:
            weights = {c: v / capped_total for c, v in weights.items()}
        diagnostics["invested"] = round(sum(weights.values()), 4)

    diagnostics.update(
        {
            "selected": len(weights),
            "short_pct_range": [
                round(scores[picked[0]], 4),
                round(scores[picked[-1]], 4),
            ] if picked else None,
            "concentration_capped": any(
                abs(v - spec.max_weight) < 1e-9 for v in weights.values()
            ),
            "long_only": spec.long_only,
            "adv_filter_active": spec.min_adv_aud is not None,
        }
    )
    return Target(date, weights, diagnostics)


def turnover(prev: dict[str, float], new: dict[str, float]) -> float:
    """One-way turnover between two books, as a fraction of NAV.

    Drives the cost model. Reported rather than assumed because ASX retail costs
    (~20bp round trip) are an order of magnitude above the crypto friction that already
    killed one lane (V272: a 1.3-1.5bp edge under 1.86bp of cost), so turnover is the
    variable that decides whether an edge survives contact with a broker.
    """
    codes = set(prev) | set(new)
    return sum(abs(new.get(c, 0.0) - prev.get(c, 0.0)) for c in codes) / 2.0


def explain(spec: PortfolioSpec) -> list[str]:
    """Human-readable statement of what is and is not active.

    Exists because of V279: the campaign's dominant defect is a component that is
    correctly wired, imports cleanly, and never does anything. A spec that prints what
    is inert cannot quietly become decorative.
    """
    lines = [
        f"long_only={spec.long_only} (V289 §7: long leg is ~60% of the spread)",
        f"top_quantile={spec.top_quantile} max_names={spec.max_names} max_weight={spec.max_weight}",
        f"min_names_to_trade={spec.min_names_to_trade}",
    ]
    lines.append(
        f"adv filter: {f'ACTIVE >= ${spec.min_adv_aud:,.0f}/day' if spec.min_adv_aud else 'DISABLED'}"
        " (needs a price source with volume, e.g. ApiPriceSource)"
    )
    lines.append(
        f"price floor: {f'ACTIVE >= ${spec.min_price_aud:.2f}' if spec.min_price_aud else 'DISABLED'}"
    )
    return lines
