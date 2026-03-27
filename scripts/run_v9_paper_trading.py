#!/usr/bin/env python3
"""Run 50 V9 paper trading cycles.

V9 improvements over V8:
  1. Regime uncertainty sit-out: if no regime has >50% confidence → 75% size reduction
  2. Volatility percentile sit-out:
       - vol < 20th pct of last 100 candles → full sit-out (0% size)
       - vol > 80th pct of last 100 candles → 50% size reduction
       - sweet spot (20th-80th pct) -> normal sizing
"""

import logging
import sys
import time

from omega.core.orchestrator_v2 import OmegaOrchestrator
from omega.nodes.victoria.victoria_node import VictoriaNode

sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/tmp/v9_training.log", mode="w"),
    ],
)
logger = logging.getLogger("v9_run")

logger.info("Initialising V9 training run — sit-out filters (regime uncertainty + vol percentile)")

node = VictoriaNode()
orch = OmegaOrchestrator()
orch.register_node(node)

cycle_times: list[float] = []
sit_out_counts: dict[str, int] = {
    "vol_low": 0,
    "vol_high": 0,
    "regime_uncertain": 0,
    "normal": 0,
}

for i in range(50):
    start = time.time()
    result = orch.run_one_cycle()
    elapsed = time.time() - start
    cycle_times.append(elapsed)

    sit_out_reason = "normal"

    # CycleResult exposes .proposals as list of trade dicts
    # Each dict may contain sit_out from the portfolio result
    proposals = getattr(result, "proposals", []) or []
    for prop in proposals:
        if isinstance(prop, dict) and "sit_out" in prop:
            sit_out_reason = prop["sit_out"]
            break

    # Also check strategy node's own counters as ground truth
    strat = node._strategy
    total_so_far = (
        strat._sit_out_vol_low_count
        + strat._sit_out_vol_high_count
        + strat._sit_out_regime_count
        + strat._normal_trade_count
    )
    if total_so_far == i + 1:
        # counters are current — derive from latest delta
        if strat._sit_out_vol_low_count > sit_out_counts.get("vol_low", 0):
            sit_out_reason = "vol_low"
        elif strat._sit_out_vol_high_count > sit_out_counts.get("vol_high", 0):
            sit_out_reason = "vol_high"
        elif strat._sit_out_regime_count > sit_out_counts.get("regime_uncertain", 0):
            sit_out_reason = "regime_uncertain"
        else:
            sit_out_reason = "normal"

    sit_out_counts[sit_out_reason] = sit_out_counts.get(sit_out_reason, 0) + 1

    cycle_num = getattr(result, "cycle_number", i + 1)
    if sit_out_reason == "vol_low":
        logger.info(
            "Cycle %3d (%.1fs) — SIT-OUT (dead-calm vol < 20th pct) — no trades",
            cycle_num,
            elapsed,
        )
    elif sit_out_reason == "vol_high":
        logger.info(
            "Cycle %3d (%.1fs) — CAUTION (chaotic vol > 80th pct) — 50%% size",
            cycle_num,
            elapsed,
        )
    elif sit_out_reason == "regime_uncertain":
        logger.info(
            "Cycle %3d (%.1fs) — CAUTION (uncertain regime) — 25%% size",
            cycle_num,
            elapsed,
        )
    else:
        n_actions = getattr(result, "actions_executed", 0)
        logger.info("Cycle %3d (%.1fs) — normal, actions=%d", cycle_num, elapsed, n_actions)

    if i < 49:
        time.sleep(30)

avg_cycle = sum(cycle_times) / len(cycle_times) if cycle_times else 0
total_sit = (
    sit_out_counts["vol_low"] + sit_out_counts["vol_high"] + sit_out_counts["regime_uncertain"]
)

# Print final counters directly from strategy node for accuracy
s = node._strategy
logger.info("\n=== V9 SUMMARY (50 cycles) ===")
logger.info("Avg cycle latency: %.2fs", avg_cycle)
logger.info("─── Sit-out breakdown (from strategy counters) ───")
logger.info("  FULL sit-out (dead-calm vol):  %2d cycles", s._sit_out_vol_low_count)
logger.info("  50%% size (chaotic vol):        %2d cycles", s._sit_out_vol_high_count)
logger.info("  25%% size (uncertain regime):   %2d cycles", s._sit_out_regime_count)
logger.info("  Normal full-size trading:       %2d cycles", s._normal_trade_count)
real_total = s._sit_out_vol_low_count + s._sit_out_vol_high_count + s._sit_out_regime_count
logger.info(
    "  Total sit-out/reduced:          %2d / 50 (%.0f%%)",
    real_total,
    real_total / 50 * 100,
)
logger.info("Log: /tmp/v9_training.log")

print("\nDone. 50 cycles complete.")
print(f"Avg cycle time: {avg_cycle:.2f}s")
print("Sit-out breakdown (strategy counters):")
print(f"  Full sit-out (vol_low):    {s._sit_out_vol_low_count}")
print(f"  50% size  (vol_high):      {s._sit_out_vol_high_count}")
print(f"  25% size  (regime uncert): {s._sit_out_regime_count}")
print(f"  Normal:                    {s._normal_trade_count}")
print(f"  Total reduced/sat-out:     {real_total}/50 ({real_total / 50 * 100:.0f}%)")
