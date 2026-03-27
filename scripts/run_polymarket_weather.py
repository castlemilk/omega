#!/usr/bin/env python3
"""
Polymarket weather edge detection pipeline — end-to-end runner.

Fetches LIVE Polymarket weather markets (Gamma API) and REAL Open-Meteo GEFS
ensemble forecasts, computes model probabilities, compares against market
prices to surface edges, and saves results to data/polymarket_weather_edges.json.

Observational only — no orders placed.

When Polymarket has no active temperature markets (off-season), a second
"model calibration" phase runs against synthetic reference markets using
REAL Open-Meteo data, to prove the full ensemble→edge pipeline works.

Usage:
    python3 scripts/run_polymarket_weather.py [--cycles N]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omega.core.node import NodeInput
from omega.nodes.polymarket.edge_detection import (
    _AUTO_DETECT_CACHE_PATH,
    EdgeDetectionNode,
)
from omega.nodes.polymarket.pricing import PolymarketPricingNode
from omega.nodes.polymarket.weather_ensemble import CITIES, WeatherEnsembleNode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("polymarket.runner")

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "polymarket_weather_edges.json"

# ---------------------------------------------------------------------------
# Reference markets for model calibration when Polymarket has no live weather
# markets.  Prices are conservative mid-season baselines (not real quotes).
# ---------------------------------------------------------------------------

def _reference_markets() -> list[dict]:
    """Build seasonal reference markets for today's date."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%b %d")
    return [
        {
            "city": "NYC",
            "question": f"Will NYC high temperature exceed 50°F on {tomorrow}?",
            "threshold_f": 50.0,
            "market_price": 0.72,  # baseline — NYC late-March odds for 50°F
            "market_id": "ref-nyc-50f",
            "is_reference": True,
        },
        {
            "city": "CHICAGO",
            "question": f"Will Chicago high temperature exceed 45°F on {tomorrow}?",
            "threshold_f": 45.0,
            "market_price": 0.61,
            "market_id": "ref-chi-45f",
            "is_reference": True,
        },
        {
            "city": "MIAMI",
            "question": f"Will Miami high temperature exceed 75°F on {tomorrow}?",
            "threshold_f": 75.0,
            "market_price": 0.85,
            "market_id": "ref-mia-75f",
            "is_reference": True,
        },
        {
            "city": "DALLAS",
            "question": f"Will Dallas high temperature exceed 65°F on {tomorrow}?",
            "threshold_f": 65.0,
            "market_price": 0.70,
            "market_id": "ref-dal-65f",
            "is_reference": True,
        },
        {
            "city": "SEATTLE",
            "question": f"Will Seattle high temperature exceed 55°F on {tomorrow}?",
            "threshold_f": 55.0,
            "market_price": 0.45,
            "market_id": "ref-sea-55f",
            "is_reference": True,
        },
        {
            "city": "LONDON",
            "question": f"Will London high temperature exceed 12°C on {tomorrow}?",
            "threshold_f": 53.6,  # 12°C
            "market_price": 0.55,
            "market_id": "ref-lon-12c",
            "is_reference": True,
        },
        {
            "city": "TOKYO",
            "question": f"Will Tokyo high temperature exceed 15°C on {tomorrow}?",
            "threshold_f": 59.0,  # 15°C
            "market_price": 0.68,
            "market_id": "ref-tok-15c",
            "is_reference": True,
        },
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def _format_edge_log(cycle: int, result: dict, label: str = "") -> str:
    city = result.get("city", "?")
    question = result.get("question", "")[:75]
    model_pct = result.get("model_prob", 0.5) * 100
    market_pct = result.get("market_price", 0.5) * 100
    edge_pct = result.get("edge", 0.0) * 100
    direction = result.get("direction", "YES")
    opportunity = result.get("opportunity", False)

    tag = f"[{label}] " if label else ""
    line = (
        f"{tag}[cycle {cycle:>2}] {city}: {question!r} "
        f"model={model_pct:.0f}% market={market_pct:.0f}% edge={edge_pct:+.0f}%"
    )
    if opportunity:
        line += f"  *** {direction} EDGE ***"
    return line


# ---------------------------------------------------------------------------
# Live Polymarket pipeline
# ---------------------------------------------------------------------------


def run_live_cycle(
    cycle: int,
    pricing_node: PolymarketPricingNode,
    edge_node: EdgeDetectionNode,
) -> dict | None:
    """One cycle against the live Gamma API."""
    t0 = time.perf_counter()
    pricing_out = pricing_node.execute(NodeInput(action="fetch_weather_markets"))
    if not pricing_out.success:
        logger.error("Cycle %d pricing failed: %s", cycle, pricing_out.errors)
        return None

    markets: list[dict] = pricing_out.result or []
    logger.info("Cycle %d (live): Polymarket returned %d weather markets", cycle, len(markets))
    for m in markets[:5]:
        logger.info(
            "  %s | yes=%.3f no=%.3f vol=%.0f",
            m.get("question", "")[:65],
            m.get("yes_price", 0),
            m.get("no_price", 0),
            m.get("volume", 0),
        )

    # Clear disk cache on first cycle
    if cycle == 1 and os.path.exists(_AUTO_DETECT_CACHE_PATH):
        os.remove(_AUTO_DETECT_CACHE_PATH)

    edge_out = edge_node.execute(
        NodeInput(action="detect", context={"cycle": cycle})
    )
    if not edge_out.success:
        logger.error("Cycle %d edge detection failed: %s", cycle, edge_out.errors)
        return None

    result = {
        **edge_out.result,
        "cycle": cycle,
        "source": "live",
        "markets_polled": len(markets),
        "run_at": datetime.now().isoformat(),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    logger.info(_format_edge_log(cycle, result, "live"))
    if result.get("opportunity"):
        logger.info(
            "  >>> LIVE EDGE: city=%s model=%.0f%% market=%.0f%% edge=%+.0f%% %s",
            result.get("city", "?"),
            result.get("model_prob", 0.5) * 100,
            result.get("market_price", 0.5) * 100,
            result.get("edge", 0.0) * 100,
            result.get("direction", "?"),
        )
    return result


# ---------------------------------------------------------------------------
# Reference / calibration pipeline
# ---------------------------------------------------------------------------


def run_reference_phase(
    weather_node: WeatherEnsembleNode,
    edge_node: EdgeDetectionNode,
) -> list[dict]:
    """
    Run edge detection against seasonal reference markets using REAL Open-Meteo
    GEFS ensemble data.  This proves the full model pipeline works even when
    Polymarket has no active temperature markets.
    """
    logger.info("")
    logger.info("=" * 60)
    logger.info("Model calibration phase — REAL Open-Meteo data + reference markets")
    logger.info("=" * 60)

    markets = _reference_markets()
    results = []

    for ref in markets:
        city = ref["city"]
        threshold_c = _f_to_c(ref["threshold_f"])
        question = ref["question"]
        market_price = ref["market_price"]
        market_id = ref["market_id"]

        # Fetch real GEFS ensemble probability
        w_out = weather_node.execute(
            NodeInput(
                action="probability",
                parameters={"city": city, "threshold_c": threshold_c, "target_hour": 15},
            )
        )
        if not w_out.success:
            logger.warning("Ref %s: weather fetch failed: %s", city, w_out.errors)
            continue

        w = w_out.result
        model_prob = w["probability"]
        edge = model_prob - market_price

        # Log in the requested format
        threshold_f = ref["threshold_f"]
        direction = "YES" if edge > 0 else "NO"
        opportunity = abs(edge) >= edge_node.edge_threshold

        logger.info(
            "  %s high temp > %.0f°F tomorrow: model says %.0f%%, market says %.0f%% = %+.0f%% edge%s",
            city,
            threshold_f,
            model_prob * 100,
            market_price * 100,
            edge * 100,
            f"  *** {direction} EDGE ***" if opportunity else "",
        )
        logger.info(
            "    (GEFS: %d members, %.0f%% exceed %.1f°C, mean_temp=%.1f°C)",
            w["member_count"],
            model_prob * 100,
            threshold_c,
            w.get("mean_temp_c", 0),
        )

        kelly = edge_node.kelly_fraction(abs(edge), model_prob, edge_node.max_kelly_fraction)
        confidence = edge_node.confidence_score(edge, w["member_count"])

        results.append({
            "source": "reference",
            "city": city,
            "question": question,
            "threshold_f": threshold_f,
            "threshold_c": round(threshold_c, 2),
            "model_prob": round(model_prob, 4),
            "market_price": round(market_price, 4),
            "edge": round(edge, 4),
            "direction": direction,
            "kelly_fraction": round(kelly, 4),
            "confidence": round(confidence, 4),
            "opportunity": opportunity,
            "member_count": w["member_count"],
            "mean_temp_c": w.get("mean_temp_c"),
            "market_id": market_id,
            "run_at": datetime.now().isoformat(),
        })

    opportunities = [r for r in results if r["opportunity"]]
    logger.info("")
    logger.info(
        "Reference phase: %d/%d cities produced edges (>%.0f%% threshold)",
        len(opportunities),
        len(results),
        edge_node.edge_threshold * 100,
    )

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(n_cycles: int = 10) -> None:
    logger.info("=" * 70)
    logger.info("Polymarket weather edge detection — %d cycles", n_cycles)
    logger.info("Output: %s", OUTPUT_PATH)
    logger.info("=" * 70)

    pricing_node = PolymarketPricingNode()
    weather_node = WeatherEnsembleNode()
    edge_node = EdgeDetectionNode(edge_threshold=0.08)

    if os.path.exists(_AUTO_DETECT_CACHE_PATH):
        os.remove(_AUTO_DETECT_CACHE_PATH)

    live_cycles: list[dict] = []
    live_opportunities: list[dict] = []

    # --- Phase 1: live Polymarket cycles ---
    for cycle in range(1, n_cycles + 1):
        logger.info("-" * 50)
        result = run_live_cycle(cycle, pricing_node, edge_node)
        if result is not None:
            live_cycles.append(result)
            if result.get("opportunity"):
                live_opportunities.append(result)
        if cycle < n_cycles:
            time.sleep(1)

    live_markets_found = max((r.get("markets_polled", 0) for r in live_cycles), default=0)

    logger.info("")
    logger.info("Live pipeline: %d/%d cycles, %d opportunities, %d weather markets found on Polymarket",
                len(live_cycles), n_cycles, len(live_opportunities), live_markets_found)

    # --- Phase 2: reference / calibration ---
    # Always run this phase to demonstrate real Open-Meteo ensemble data
    reference_results = run_reference_phase(weather_node, edge_node)
    reference_opportunities = [r for r in reference_results if r["opportunity"]]

    # --- Summary ---
    logger.info("")
    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("  Live Polymarket cycles:       %d/%d", len(live_cycles), n_cycles)
    logger.info("  Live weather markets found:   %d", live_markets_found)
    logger.info("  Live edges detected:          %d", len(live_opportunities))
    logger.info("  Reference cities evaluated:   %d", len(reference_results))
    logger.info("  Reference edges detected:     %d", len(reference_opportunities))

    if reference_opportunities:
        logger.info("")
        logger.info("Reference edges (real GEFS data vs baseline market prices):")
        for opp in reference_opportunities:
            logger.info(
                "  %s | %s | model=%.0f%% market=%.0f%% edge=%+.0f%% %s",
                opp["city"],
                opp["question"][:60],
                opp["model_prob"] * 100,
                opp["market_price"] * 100,
                opp["edge"] * 100,
                opp["direction"],
            )

    # --- Save ---
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "generated_at": datetime.now().isoformat(),
        "n_cycles": n_cycles,
        "live": {
            "n_successful": len(live_cycles),
            "n_markets_found": live_markets_found,
            "n_opportunities": len(live_opportunities),
            "cycles": live_cycles,
            "opportunities": live_opportunities,
        },
        "reference": {
            "description": "Real Open-Meteo GEFS ensemble vs seasonal baseline market prices",
            "n_cities": len(reference_results),
            "n_opportunities": len(reference_opportunities),
            "results": reference_results,
            "opportunities": reference_opportunities,
        },
        "node_metrics": {
            "pricing": pricing_node.evaluate(),
            "weather": weather_node.evaluate(),
            "edge": edge_node.evaluate(),
        },
    }
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Results saved → %s", OUTPUT_PATH)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=10)
    args = parser.parse_args()
    main(n_cycles=args.cycles)
