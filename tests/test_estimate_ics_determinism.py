"""V224: empirical IC estimation must be byte-reproducible across runs.

The estimator feeds the IC table the trading path consumes; if it isn't
deterministic, the whole determinism arc (V211→V221) is undermined. This builds a
tiny synthetic corpus (a snapshot + a decisions JSONL), runs scripts/estimate_ics.py
twice, and asserts the two output JSONs are byte-identical. Also asserts the LOSO
structure (each target fit on the other snapshots, no self-leak).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "estimate_ics.py"
SIGNALS = ["sma_crossover", "rsi_signal", "zscore_signal"]


def _make_snapshot(path: Path, sym: str, n_bars: int, seed: int) -> None:
    # Deterministic pseudo-random-ish close path (no RNG — pinned arithmetic).
    closes = []
    px = 100.0 + seed
    for i in range(n_bars):
        px *= 1.0 + ((i * 7 + seed * 13) % 11 - 5) / 1000.0
        closes.append(round(px, 4))
    data = {
        "_snapshot_id": path.stem,
        "_symbols": [sym],
        sym: {"close": closes, "timestamps": list(range(n_bars))},
    }
    path.write_text(json.dumps(data))


def _make_decisions(path: Path, sym: str, n_cycles: int, seed: int) -> None:
    lines = []
    for c in range(1, n_cycles + 1):
        regime = REGIMES[(c + seed) % len(REGIMES)]
        traces = []
        for j, sname in enumerate(SIGNALS):
            # Pinned deterministic raw_value in [-1, 1].
            rv = round((((c * (j + 1) * 17 + seed * 3) % 200) - 100) / 100.0, 4)
            traces.append({"signal_name": sname, "raw_value": rv, "weight_applied": 1.0})
        rec = {
            "cycle": c,
            "regime": regime,
            "per_ticker": {sym: {"ticker": sym, "signal_traces": traces}},
        }
        lines.append(json.dumps(rec))
    path.write_text("\n".join(lines) + "\n")


REGIMES = ["normal", "crisis", "high_vol"]


def _run(tmp: Path, out: Path) -> None:
    corpora = []
    for name, seed in (("trend", 1), ("crisis", 2), ("recent", 3)):
        snap = tmp / f"snap_{name}.json"
        dec = tmp / f"dec_{name}.jsonl"
        _make_snapshot(snap, "ETHUSDT", 120, seed)
        _make_decisions(dec, "ETHUSDT", 200, seed)
        corpora += ["--corpus", f"{name}:{dec}:{snap}"]
    seed_file = tmp / "seed.json"
    seed_file.write_text(json.dumps({"seeded_regime_ics": {}, "seeded_pooled_ics": {}}))
    subprocess.run(
        [sys.executable, str(SCRIPT), *corpora,
         "--seed", str(seed_file), "--out", str(out), "--n-min", "5"],
        check=True, cwd=str(REPO), capture_output=True,
    )


def test_estimate_ics_byte_reproducible(tmp_path: Path) -> None:
    out1 = tmp_path / "ics1.json"
    out2 = tmp_path / "ics2.json"
    _run(tmp_path, out1)
    _run(tmp_path, out2)
    assert out1.read_bytes() == out2.read_bytes(), "estimate_ics.py output is non-deterministic"


def test_loso_no_self_leak(tmp_path: Path) -> None:
    out = tmp_path / "ics.json"
    _run(tmp_path, out)
    data = json.loads(out.read_text())
    for target in ("trend", "crisis", "recent"):
        assert target in data, f"missing target block {target}"
        fit_on = data[target]["fit_on"]
        assert target not in fit_on, f"LOSO leak: {target} fit on itself"
        assert sorted(fit_on) == sorted(t for t in ("trend", "crisis", "recent") if t != target)
        # Empirical ICs present and in [-1, 1].
        for sig, regmap in data[target]["empirical_regime_ics"].items():
            for reg, ic in regmap.items():
                assert -1.0 <= ic <= 1.0, f"{target}/{sig}/{reg} IC out of range: {ic}"
