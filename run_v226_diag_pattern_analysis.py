#!/usr/bin/env python3
"""
Diagnostic runner for V226 crisis regime patterns.
Captures gate decision log and extracts recurring trading patterns.
"""
import logging, sys
lg = logging.getLogger("omega.nodes.victoria.signal_generation")
lg.setLevel(logging.INFO)
h = logging.StreamHandler(sys.stderr)
h.setLevel(logging.INFO)
h.addFilter(lambda r: "gate_decision" in r.getMessage())
lg.addHandler(h)
lg.propagate = False

# Capture all stderr to parse gate decisions
import io
stderr_capture = io.StringIO()
sys.stderr = stderr_capture

sys.argv = ["run_training.py","--version","v226_diag_crisis","--cycles","40","--sleep","0","--seed","42",
            "--backtest-snapshot","data/snapshots/snap_crisis_2022h1.json","--frozen-cache",
            "--features",'{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "ic_seed_weighting": false}']

import runpy
try:
    runpy.run_path("scripts/run_training.py", run_name="__main__")
except SystemExit:
    pass

# Restore stderr and print captured output
sys.stderr = sys.__stderr__
output = stderr_capture.getvalue()
print("=== GATE DECISION LOG ===")
print(output)
