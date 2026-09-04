import pytest

from omega.core.vector_memory import VectorMemoryLayer


def test_write_and_retrieve(tmp_path):
    vm = VectorMemoryLayer(db_path=str(tmp_path / "vm.db"))
    mid = vm.write("BTC momentum signal shows strong uptrend", {"source": "victoria"})
    assert mid is not None
    results = vm.retrieve("bitcoin momentum uptrend", top_k=3)
    assert len(results) == 1
    assert results[0]["text"] == "BTC momentum signal shows strong uptrend"
    assert results[0]["score"] > 0.0


def test_cosine_dedup_blocks_near_duplicate(tmp_path):
    vm = VectorMemoryLayer(db_path=str(tmp_path / "vm.db"))
    mid1 = vm.write("BTC funding rate is extremely high indicating over-leverage", {})
    mid2 = vm.write("BTC funding rate is extremely high indicating over-leverage", {})
    assert mid1 is not None
    assert mid2 is None  # blocked as duplicate
    assert vm.count() == 1


def test_distinct_entries_both_stored(tmp_path):
    vm = VectorMemoryLayer(db_path=str(tmp_path / "vm.db"))
    vm.write("BTC momentum shows uptrend with strong volume", {})
    vm.write("ETH stablecoin inflows suggest risk-off regime", {})
    assert vm.count() == 2


def test_retrieve_top_k(tmp_path):
    vm = VectorMemoryLayer(db_path=str(tmp_path / "vm.db"))
    vm.write("BTC momentum signal", {"tag": "btc"})
    vm.write("ETH funding rate spike", {"tag": "eth"})
    vm.write("SOL liquidation cascade risk", {"tag": "sol"})
    results = vm.retrieve("BTC momentum", top_k=2)
    assert len(results) <= 2
    # Most relevant result should mention btc or momentum
    assert any("BTC" in r["text"] or "momentum" in r["text"] for r in results)


def test_retrieve_returns_empty_when_no_entries(tmp_path):
    vm = VectorMemoryLayer(db_path=str(tmp_path / "vm.db"))
    results = vm.retrieve("anything", top_k=5)
    assert results == []


def test_metadata_round_trips(tmp_path):
    vm = VectorMemoryLayer(db_path=str(tmp_path / "vm.db"))
    vm.write("regime shift detected", {"cycle": 42, "confidence": 0.87})
    results = vm.retrieve("regime shift", top_k=1)
    assert results[0]["metadata"]["cycle"] == 42
    assert results[0]["metadata"]["confidence"] == pytest.approx(0.87)


def test_dedup_threshold_configurable(tmp_path):
    # With threshold=0.0 even exact duplicates are stored
    vm = VectorMemoryLayer(db_path=str(tmp_path / "vm.db"), dedup_threshold=0.0)
    vm.write("duplicate text here", {})
    vm.write("duplicate text here", {})
    assert vm.count() == 2
