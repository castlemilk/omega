#!/usr/bin/env python3
"""Run 100 paper trading cycles with 30s sleep between each."""
import sys
import time

sys.path.insert(0, ".")

from omega.core.orchestrator_v2 import OmegaOrchestrator
from omega.nodes.victoria.victoria_node import VictoriaNode

node = VictoriaNode()
orch = OmegaOrchestrator()
orch.register_node(node)

for i in range(100):
    start = time.time()
    result = orch.run_one_cycle()
    elapsed = time.time() - start
    status = result.get("status", "?") if isinstance(result, dict) else str(result)[:80]
    print(f"Cycle {i+1:3d}: {status} ({elapsed:.1f}s)", flush=True)
    if i < 99:
        time.sleep(30)

print("\nDone. 100 cycles complete.")
