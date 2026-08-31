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

    # Placeholder for #551 (no ADV/market-cap in the API). When liquidity lands this
    # becomes a real filter; today it is declared and inert, and `explain()` says so
    # rather than letting a reader assume the universe is liquidity-screened.
    min_adv_aud: float | None = None


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

    scores = {c: v["short"] for c, v in day.items()}
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
        weights = {c: v / total for c, v in weights.items()}   # re-normalise to fully invested

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
        f"adv filter: {'ACTIVE' if spec.min_adv_aud else 'INERT — no liquidity data upstream (#551)'}"
    )
    return lines
