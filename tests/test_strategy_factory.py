import pytest

from omega.core.strategy_factory import SignalHotLoader


def test_write_and_load_returns_module(tmp_path):
    loader = SignalHotLoader(generated_dir=str(tmp_path))
    code = """
def compute(data: dict) -> float:
    return data.get("close", 0.0) * 0.01
"""
    mod = loader.write_and_load("test_signal_v1", code)
    assert hasattr(mod, "compute")
    result = mod.compute({"close": 100.0})
    assert result == pytest.approx(1.0)


def test_write_saves_file_to_disk(tmp_path):
    loader = SignalHotLoader(generated_dir=str(tmp_path))
    code = "def compute(data):\n    return 0.5\n"
    loader.write_and_load("saved_signal", code)
    assert (tmp_path / "saved_signal.py").exists()


def test_reload_picks_up_updated_code(tmp_path):
    loader = SignalHotLoader(generated_dir=str(tmp_path))
    code_v1 = "def compute(data):\n    return 1.0\n"
    loader.write_and_load("evolving_signal", code_v1)

    code_v2 = "def compute(data):\n    return 2.0\n"
    (tmp_path / "evolving_signal.py").write_text(code_v2)
    mod = loader.reload("evolving_signal")
    assert mod.compute({}) == pytest.approx(2.0)


def test_list_loaded_returns_signal_names(tmp_path):
    loader = SignalHotLoader(generated_dir=str(tmp_path))
    loader.write_and_load("sig_a", "def compute(data):\n    return 0.1\n")
    loader.write_and_load("sig_b", "def compute(data):\n    return 0.2\n")
    names = loader.list_loaded()
    assert "sig_a" in names
    assert "sig_b" in names


def test_invalid_code_raises_syntax_error(tmp_path):
    loader = SignalHotLoader(generated_dir=str(tmp_path))
    with pytest.raises(SyntaxError):
        loader.write_and_load("bad_signal", "def compute(data:\n    return 0\n")


def test_missing_compute_raises_value_error(tmp_path):
    loader = SignalHotLoader(generated_dir=str(tmp_path))
    code = "CONSTANT = 42\n"
    with pytest.raises(ValueError, match="compute"):
        loader.write_and_load("no_compute_signal", code)


def test_namespace_isolation(tmp_path):
    """Two signals with the same variable name don't bleed into each other."""
    loader = SignalHotLoader(generated_dir=str(tmp_path))
    loader.write_and_load("iso_a", "VALUE = 10\ndef compute(data):\n    return VALUE\n")
    loader.write_and_load("iso_b", "VALUE = 99\ndef compute(data):\n    return VALUE\n")
    assert loader.call("iso_a", {}) == pytest.approx(10.0)
    assert loader.call("iso_b", {}) == pytest.approx(99.0)


def test_call_unknown_signal_raises_key_error(tmp_path):
    loader = SignalHotLoader(generated_dir=str(tmp_path))
    with pytest.raises(KeyError):
        loader.call("nonexistent", {})
