import logging, sys
lg = logging.getLogger("omega.nodes.victoria.signal_generation")
lg.setLevel(logging.INFO)
h = logging.StreamHandler(sys.stderr)
h.setLevel(logging.INFO)
h.addFilter(lambda r: "gate_decision" in r.getMessage())
lg.addHandler(h)
lg.propagate=False
sys.argv = ["run_training.py","--version","v226_diag_crisis","--cycles","40","--sleep","0","--seed","42",
            "--backtest-snapshot","data/snapshots/snap_crisis_2022h1.json","--frozen-cache",
            "--features",'{"crisis_skew_enabled": true, "crisis_skew_regime_gate_enabled": true, "ic_seed_weighting": false}']
import runpy
runpy.run_path("scripts/run_training.py", run_name="__main__")
