"""Smoke test: _find_baseline_version helper in run_training.py."""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def test_find_baseline_version_decrements_to_existing(tmp_path: Path, monkeypatch):
    import run_training

    monkeypatch.setattr(run_training, "DATA_DIR", tmp_path)
    (tmp_path / "v48_results.json").write_text("{}")
    (tmp_path / "v48_trades.csv").write_text("")

    assert run_training._find_baseline_version("v49") == "v48"


def test_find_baseline_version_skips_missing(tmp_path: Path, monkeypatch):
    import run_training

    monkeypatch.setattr(run_training, "DATA_DIR", tmp_path)
    (tmp_path / "v46_results.json").write_text("{}")
    (tmp_path / "v46_trades.csv").write_text("")

    assert run_training._find_baseline_version("v49") == "v46"


def test_find_baseline_version_none_for_v1(tmp_path: Path, monkeypatch):
    import run_training

    monkeypatch.setattr(run_training, "DATA_DIR", tmp_path)
    assert run_training._find_baseline_version("v1") is None


def test_find_baseline_version_none_for_non_numeric(tmp_path: Path, monkeypatch):
    import run_training

    monkeypatch.setattr(run_training, "DATA_DIR", tmp_path)
    assert run_training._find_baseline_version("experimental") is None
