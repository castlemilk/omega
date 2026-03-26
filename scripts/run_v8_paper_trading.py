#!/usr/bin/env python3
"""Run 100 V8 paper trading cycles with 30s sleep between each.

V8 improvements:
  1. Regime-directional filter (block longs in bear, shorts in bull)
  2. CoinGecko cache TTL reduced to 60s (fresher prices)
  3. FRED macro signals merged
  4. DAG parallel pipeline (14 signals concurrently via ThreadPoolExecutor)
"""
import logging
import sys
import time

sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/tmp/v8_training.log", mode="w"),
    ],
)
logger = logging.getLogger("v8_run")

from omega.core.orchestrator_v2 import OmegaOrchestrator
from omega.nodes.victoria.victoria_node import VictoriaNode

logger.info("Initialising V8 training run — regime filter + DAG pipeline + 60s CoinGecko TTL")

node = VictoriaNode()
orch = OmegaOrchestrator()
orch.register_node(node)

cycle_times: list[float] = []
regime_blocks: list[dict] = []

for i in range(100):
    start = time.time()
    result = orch.run_one_cycle()
    elapsed = time.time() - start
    cycle_times.append(elapsed)

    status = result.get("status", "?") if isinstance(result, dict) else str(result)[:80]

    # Extract regime blocking info from portfolio result if available
    if isinstance(result, dict):
        portfolio = result.get("portfolio") or result.get("result", {})
        if isinstance(portfolio, dict):
            blocked_longs = portfolio.get("regime_blocked_longs", 0)
            blocked_shorts = portfolio.get("regime_blocked_shorts", 0)
            regime_info = portfolio.get("regime_filter", {})
            if blocked_longs or blocked_shorts:
                regime_blocks.append({
                    "cycle": i + 1,
                    "blocked_longs": blocked_longs,
                    "blocked_shorts": blocked_shorts,
                    "regime": regime_info.get("regime", "?"),
                    "confidence": regime_info.get("confidence", 0.0),
                })
                logger.info(
                    "Cycle %3d: %s (%.1fs) — Regime filter (%s, conf=%.2f) blocked %d long(s), %d short(s)",
                    i + 1, status, elapsed,
                    regime_info.get("regime", "?"),
                    regime_info.get("confidence", 0.0),
                    blocked_longs, blocked_shorts,
                )
            else:
                logger.info("Cycle %3d: %s (%.1fs)", i + 1, status, elapsed)
        else:
            logger.info("Cycle %3d: %s (%.1fs)", i + 1, status, elapsed)
    else:
        logger.info("Cycle %3d: %s (%.1fs)", i + 1, status, elapsed)

    if i < 99:
        time.sleep(30)

avg_cycle = sum(cycle_times) / len(cycle_times) if cycle_times else 0
total_blocked_longs = sum(r["blocked_longs"] for r in regime_blocks)
total_blocked_shorts = sum(r["blocked_shorts"] for r in regime_blocks)

logger.info("\n=== V8 SUMMARY ===")
logger.info("100 cycles complete.")
logger.info("Avg cycle latency: %.2fs", avg_cycle)
logger.info("Total regime blocks: %d longs, %d shorts (across %d cycles)", total_blocked_longs, total_blocked_shorts, len(regime_blocks))
logger.info("Log file: /tmp/v8_training.log")

print(f"\nDone. 100 cycles complete.")
print(f"Avg cycle time: {avg_cycle:.2f}s")
print(f"Regime-blocked longs: {total_blocked_longs}, shorts: {total_blocked_shorts}")
