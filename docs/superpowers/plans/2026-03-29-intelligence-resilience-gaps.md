# Intelligence & Resilience Gap Fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill four capability gaps vs 724 Office: vector memory with cosine dedup, runtime signal hot-loading, self-repair loop, and cron-based task scheduler.

**Architecture:** Four new standalone modules in `omega/core/`, each with clear interfaces and SQLite/file-backed persistence. No new pip dependencies — stdlib + numpy only. Each integrates with the existing overnight_runner and improvement_engine as optional extensions.

**Tech Stack:** Python 3.11+, numpy (already present), sqlite3 (stdlib), importlib (stdlib), zoneinfo (stdlib 3.9+)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `omega/core/vector_memory.py` | Create | TF-IDF embedding, cosine dedup @ 0.92, SQLite storage, retrieve-before-decision |
| `omega/core/strategy_factory.py` | Create | Write generated signals to disk, hot-load via importlib without restart |
| `omega/core/self_repair.py` | Create | Log error parsing, component restart, webhook notification |
| `omega/core/task_scheduler.py` | Create | Cron + one-shot scheduling, JSON persistence, timezone-aware |
| `omega/nodes/victoria/generated/__init__.py` | Create | Package marker for hot-loaded signals |
| `tests/test_vector_memory.py` | Create | Tests for embedding, dedup, retrieval |
| `tests/test_strategy_factory.py` | Create | Tests for hot-load, reload, namespace isolation |
| `tests/test_self_repair.py` | Create | Tests for log parsing, repair actions, notification |
| `tests/test_task_scheduler.py` | Create | Tests for cron parsing, tick, persistence |

---

## Task 1: Vector Memory Layer

**Files:**
- Create: `omega/core/vector_memory.py`
- Create: `tests/test_vector_memory.py`

- [ ] **Step 1.1: Write failing tests**

```python
# tests/test_vector_memory.py
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
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /Users/benebsworth/projects/omega
python -m pytest tests/test_vector_memory.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'omega.core.vector_memory'`

- [ ] **Step 1.3: Implement `omega/core/vector_memory.py`**

```python
"""
omega.core.vector_memory
~~~~~~~~~~~~~~~~~~~~~~~~
Vector memory layer with TF-IDF bag-of-words embeddings and cosine dedup.

Architecture
------------
Embeddings are computed as L2-normalised TF-IDF vectors over a financial
vocabulary built from the stored corpus plus a small seed vocabulary.
Before each insert, cosine similarity is checked against all stored
embeddings; if max similarity >= dedup_threshold (default 0.92) the
entry is rejected as a near-duplicate.

Retrieval ranks stored entries by cosine similarity to the query vector
and returns top_k results with their text, metadata, and score.

Storage: SQLite (data/vector_memory.db by default).

Usage::

    vm = VectorMemoryLayer()
    vm.write("BTC funding rate spike — reduce leverage", {"source": "victoria"})
    results = vm.retrieve("funding rate leverage risk", top_k=5)
    for r in results:
        print(r["score"], r["text"])
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("omega.core.vector_memory")

# ── Seed financial vocabulary ──────────────────────────────────────────────────
# Ensures common trading terms are always in the vocabulary even before
# enough corpus entries exist to build a good IDF.
_SEED_VOCAB = [
    "btc", "eth", "sol", "bitcoin", "ethereum", "solana", "crypto",
    "momentum", "signal", "regime", "funding", "rate", "liquidation",
    "volatility", "sentiment", "whale", "onchain", "stablecoin",
    "leverage", "long", "short", "buy", "sell", "entry", "exit",
    "sharpe", "drawdown", "pnl", "profit", "loss", "win", "trade",
    "risk", "reward", "position", "portfolio", "equity", "margin",
    "bull", "bear", "neutral", "trend", "reversal", "breakout",
    "support", "resistance", "volume", "open", "close", "high", "low",
    "rsi", "macd", "ema", "sma", "atr", "bollinger", "correlation",
    "alpha", "beta", "gamma", "delta", "vega", "theta", "options",
    "futures", "spot", "perpetual", "basis", "carry", "roll",
    "regime", "macro", "fed", "inflation", "rate", "gdp", "cpi",
    "market", "exchange", "liquidity", "spread", "slippage", "fee",
    "node", "cycle", "improvement", "evaluation", "score", "metric",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS vector_memories (
    id          TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    metadata    TEXT NOT NULL,
    embedding   TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS vm_vocab (
    term        TEXT PRIMARY KEY,
    df          INTEGER NOT NULL DEFAULT 1
);
"""


def _tokenize(text: str) -> list[str]:
    """Lower-case, split on non-alphanumeric."""
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1]


class VectorMemoryLayer:
    """
    Vector memory with TF-IDF embeddings and cosine dedup.

    Parameters
    ----------
    db_path:
        SQLite file path.  Default: ``data/vector_memory.db``.
    dedup_threshold:
        Cosine similarity above which a new entry is treated as a
        duplicate and rejected (default 0.92).
    vocab_size:
        Maximum vocabulary size.  Oldest/rarest terms are dropped when
        this is exceeded (default 4096).
    """

    DEFAULT_DB = "data/vector_memory.db"

    def __init__(
        self,
        db_path: str | None = None,
        dedup_threshold: float = 0.92,
        vocab_size: int = 4096,
    ) -> None:
        self._db_path = db_path or self.DEFAULT_DB
        self._dedup_threshold = dedup_threshold
        self._vocab_size = vocab_size

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

        # Seed vocabulary
        for term in _SEED_VOCAB:
            self._conn.execute(
                "INSERT OR IGNORE INTO vm_vocab (term, df) VALUES (?, 1)", (term,)
            )
        self._conn.commit()

        # Cache: id -> embedding array (loaded lazily)
        self._embedding_cache: dict[str, np.ndarray] = {}
        self._cache_loaded = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def write(self, text: str, metadata: dict[str, Any]) -> str | None:
        """
        Write a memory.

        Returns the new memory ID if stored, or ``None`` if rejected as a
        near-duplicate (cosine similarity >= dedup_threshold).
        """
        embedding = self._embed(text)

        # Load all embeddings for dedup check
        self._ensure_cache()
        for existing_id, existing_emb in self._embedding_cache.items():
            sim = self._cosine(embedding, existing_emb)
            if sim >= self._dedup_threshold:
                logger.debug(
                    "VectorMemory dedup: similarity=%.3f >= %.3f — rejecting",
                    sim,
                    self._dedup_threshold,
                )
                return None

        # Update document frequency for vocabulary
        tokens = set(_tokenize(text))
        for token in tokens:
            self._conn.execute(
                "INSERT INTO vm_vocab (term, df) VALUES (?, 1) "
                "ON CONFLICT(term) DO UPDATE SET df = df + 1",
                (token,),
            )
        self._conn.commit()

        mid = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO vector_memories (id, text, metadata, embedding, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                mid,
                text,
                json.dumps(metadata),
                json.dumps(embedding.tolist()),
                time.time(),
            ),
        )
        self._conn.commit()

        # Invalidate cache so next operation reloads
        self._embedding_cache[mid] = embedding

        logger.debug("VectorMemory.write: stored id=%s", mid)
        return mid

    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """
        Retrieve top_k most similar memories.

        Returns list of dicts with keys: ``id``, ``text``, ``metadata``, ``score``.
        """
        rows = self._conn.execute(
            "SELECT id, text, metadata, embedding FROM vector_memories"
        ).fetchall()
        if not rows:
            return []

        q_emb = self._embed(query)
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            emb = np.array(json.loads(row["embedding"]), dtype=np.float32)
            sim = self._cosine(q_emb, emb)
            scored.append((sim, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for sim, row in scored[:top_k]:
            results.append(
                {
                    "id": row["id"],
                    "text": row["text"],
                    "metadata": json.loads(row["metadata"]),
                    "score": float(sim),
                }
            )
        return results

    def count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) as n FROM vector_memories"
        ).fetchone()
        return row["n"] if row else 0

    def prune_oldest(self, keep: int = 10_000) -> int:
        """Remove the oldest entries beyond ``keep``. Returns count deleted."""
        total = self.count()
        if total <= keep:
            return 0
        excess = total - keep
        deleted = self._conn.execute(
            "DELETE FROM vector_memories WHERE id IN "
            "(SELECT id FROM vector_memories ORDER BY created_at ASC LIMIT ?)",
            (excess,),
        ).rowcount
        self._conn.commit()
        self._cache_loaded = False
        self._embedding_cache.clear()
        return deleted or 0

    # ── Internals ──────────────────────────────────────────────────────────────

    def _ensure_cache(self) -> None:
        if self._cache_loaded:
            return
        rows = self._conn.execute(
            "SELECT id, embedding FROM vector_memories"
        ).fetchall()
        self._embedding_cache = {
            row["id"]: np.array(json.loads(row["embedding"]), dtype=np.float32)
            for row in rows
        }
        self._cache_loaded = True

    def _embed(self, text: str) -> np.ndarray:
        """
        Compute a normalised TF-IDF bag-of-words vector.

        Vocabulary is the top-``vocab_size`` terms by document frequency
        from the SQLite vocab table plus the seed vocabulary.
        """
        vocab_rows = self._conn.execute(
            "SELECT term, df FROM vm_vocab ORDER BY df DESC LIMIT ?",
            (self._vocab_size,),
        ).fetchall()

        if not vocab_rows:
            # No vocabulary yet — return a zero vector of fixed size
            return np.zeros(len(_SEED_VOCAB), dtype=np.float32)

        # Build term -> index mapping
        terms = [r["term"] for r in vocab_rows]
        dfs = [r["df"] for r in vocab_rows]
        term_to_idx = {t: i for i, t in enumerate(terms)}
        n_docs = max(self.count(), 1)

        tokens = _tokenize(text)
        if not tokens:
            return np.zeros(len(terms), dtype=np.float32)

        # TF (term frequency in document)
        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        doc_len = len(tokens)

        vec = np.zeros(len(terms), dtype=np.float32)
        for term, count in tf.items():
            idx = term_to_idx.get(term)
            if idx is None:
                continue
            tf_val = count / doc_len
            idf_val = math.log((n_docs + 1) / (dfs[idx] + 1)) + 1.0
            vec[idx] = tf_val * idf_val

        # L2 normalise
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two L2-normalised vectors."""
        if a.shape != b.shape:
            # Pad shorter vector with zeros
            size = max(a.shape[0], b.shape[0])
            a = np.pad(a, (0, size - a.shape[0]))
            b = np.pad(b, (0, size - b.shape[0]))
        dot = float(np.dot(a, b))
        # Clamp to [-1, 1] to handle float imprecision
        return max(-1.0, min(1.0, dot))

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 1.4: Create generated package marker**

```python
# omega/nodes/victoria/generated/__init__.py
"""
omega.nodes.victoria.generated
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Package for hot-loaded signal functions generated at runtime by the
improvement engine. Files in this directory are written and loaded by
omega.core.strategy_factory.SignalHotLoader.

Do not edit files here manually — they are machine-generated.
"""
```

- [ ] **Step 1.5: Run tests to verify they pass**

```bash
cd /Users/benebsworth/projects/omega
python -m pytest tests/test_vector_memory.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 1.6: Commit**

```bash
git add omega/core/vector_memory.py omega/nodes/victoria/generated/__init__.py tests/test_vector_memory.py
git commit -m "feat: vector memory layer with TF-IDF cosine dedup at 0.92 threshold"
```

---

## Task 2: Runtime Signal Hot-Loading

**Files:**
- Create: `omega/core/strategy_factory.py`
- Create: `tests/test_strategy_factory.py`

- [ ] **Step 2.1: Write failing tests**

```python
# tests/test_strategy_factory.py
import importlib
import sys
import pytest
from pathlib import Path
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
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
cd /Users/benebsworth/projects/omega
python -m pytest tests/test_strategy_factory.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'omega.core.strategy_factory'`

- [ ] **Step 2.3: Implement `omega/core/strategy_factory.py`**

```python
"""
omega.core.strategy_factory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runtime signal hot-loading — writes Python signal functions to disk and
loads them into the running process via importlib without restart.

Design
------
Generated signals live in a ``generated_dir`` (default:
``omega/nodes/victoria/generated/``).  Each file must expose:

    def compute(data: dict) -> float: ...

``SignalHotLoader`` compiles the source, validates the ``compute``
callable is present, writes to disk, then imports the module under a
unique package path (``omega_generated.<name>``).

Namespace isolation: each signal gets its own module object so module-
level constants in signal A never bleed into signal B.

Usage::

    loader = SignalHotLoader()
    mod = loader.write_and_load("whale_pressure_v2", code_string)
    score = mod.compute(market_data)

    # Later — update signal in place without restart
    new_code = generate_improved_signal(...)
    loader.write_and_load("whale_pressure_v2", new_code)
    score = loader.call("whale_pressure_v2", market_data)
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
import types
from pathlib import Path

logger = logging.getLogger("omega.core.strategy_factory")

_DEFAULT_GENERATED_DIR = str(
    Path(__file__).parent.parent / "nodes" / "victoria" / "generated"
)


class SignalHotLoader:
    """
    Writes Python signal code to disk and hot-loads it via importlib.

    Parameters
    ----------
    generated_dir:
        Directory where generated ``.py`` files are written.
        Default: ``omega/nodes/victoria/generated/``.
    """

    def __init__(self, generated_dir: str | None = None) -> None:
        self._dir = Path(generated_dir or _DEFAULT_GENERATED_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        # Ensure the directory is a Python package
        init = self._dir / "__init__.py"
        if not init.exists():
            init.write_text(
                '"""Auto-generated signal functions — do not edit manually."""\n'
            )
        # name -> module
        self._modules: dict[str, types.ModuleType] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def write_and_load(self, name: str, code: str) -> types.ModuleType:
        """
        Compile ``code``, write to ``<generated_dir>/<name>.py``, and load.

        Raises
        ------
        SyntaxError  : if ``code`` has a syntax error.
        ValueError   : if ``code`` does not define a ``compute`` callable.

        Returns the loaded module.
        """
        # Compile first to catch syntax errors before touching disk
        compile(code, f"<{name}>", "exec")

        path = self._dir / f"{name}.py"
        path.write_text(code, encoding="utf-8")
        logger.info("SignalHotLoader: wrote %s (%d bytes)", path, len(code))

        mod = self._load_from_file(name, path)

        if not callable(getattr(mod, "compute", None)):
            raise ValueError(
                f"Generated signal '{name}' must define a callable `compute(data: dict) -> float`. "
                f"Found module attributes: {[a for a in dir(mod) if not a.startswith('_')]}"
            )

        self._modules[name] = mod
        logger.info("SignalHotLoader: loaded signal '%s'", name)
        return mod

    def reload(self, name: str) -> types.ModuleType:
        """
        Re-read ``<name>.py`` from disk and reload the module in-place.

        Use this after externally updating the file (e.g. after the LLM
        writes an improved version directly to disk).

        Raises KeyError if ``name`` has never been loaded.
        """
        if name not in self._modules:
            raise KeyError(f"Signal '{name}' not loaded — call write_and_load() first.")
        path = self._dir / f"{name}.py"
        mod = self._load_from_file(name, path)
        self._modules[name] = mod
        logger.info("SignalHotLoader: reloaded signal '%s'", name)
        return mod

    def call(self, name: str, data: dict) -> float:
        """
        Call ``compute(data)`` on a loaded signal.

        Raises KeyError if signal not loaded.
        """
        mod = self._modules.get(name)
        if mod is None:
            raise KeyError(f"Signal '{name}' not loaded.")
        return float(mod.compute(data))

    def list_loaded(self) -> list[str]:
        """Return names of all currently loaded signals."""
        return list(self._modules.keys())

    def get_module(self, name: str) -> types.ModuleType | None:
        return self._modules.get(name)

    # ── Internals ──────────────────────────────────────────────────────────────

    def _load_from_file(self, name: str, path: Path) -> types.ModuleType:
        """Load (or reload) a module from an absolute file path."""
        module_name = f"omega_generated.{name}"

        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {path}")

        mod = importlib.util.module_from_spec(spec)
        # Register in sys.modules so relative imports within the signal work
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
cd /Users/benebsworth/projects/omega
python -m pytest tests/test_strategy_factory.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 2.5: Commit**

```bash
git add omega/core/strategy_factory.py tests/test_strategy_factory.py
git commit -m "feat: runtime signal hot-loading via importlib without restart"
```

---

## Task 3: Self-Repair Loop

**Files:**
- Create: `omega/core/self_repair.py`
- Create: `tests/test_self_repair.py`

- [ ] **Step 3.1: Write failing tests**

```python
# tests/test_self_repair.py
import importlib
import json
import logging
import os
import pytest
from pathlib import Path
from omega.core.self_repair import SelfRepairLoop, RepairReport, LogError


def test_repair_report_defaults():
    r = RepairReport()
    assert r.healthy is True
    assert r.errors_found == 0
    assert r.repairs_attempted == 0
    assert r.repairs_succeeded == 0


def test_parse_errors_finds_critical_lines(tmp_path):
    log_file = tmp_path / "omega.log"
    log_file.write_text(
        "2026-03-29 01:00:00 INFO  Starting\n"
        "2026-03-29 01:00:01 ERROR Failed to connect to database: timeout\n"
        "2026-03-29 01:00:02 INFO  Retrying\n"
        "2026-03-29 01:00:03 CRITICAL Signal import failed: momentum_factor\n"
    )
    loop = SelfRepairLoop(skip_db=True, skip_signals=True)
    errors = loop._parse_log_errors(str(log_file), last_n_lines=100)
    assert len(errors) == 2
    assert any("database" in e.message.lower() for e in errors)
    assert any("signal" in e.message.lower() for e in errors)


def test_parse_errors_empty_log(tmp_path):
    log_file = tmp_path / "empty.log"
    log_file.write_text("")
    loop = SelfRepairLoop(skip_db=True, skip_signals=True)
    errors = loop._parse_log_errors(str(log_file))
    assert errors == []


def test_parse_errors_missing_log():
    loop = SelfRepairLoop(skip_db=True, skip_signals=True)
    errors = loop._parse_log_errors("/nonexistent/path.log")
    assert errors == []


def test_check_and_repair_returns_report():
    loop = SelfRepairLoop(skip_db=True, skip_signals=True)
    report = loop.check_and_repair()
    assert isinstance(report, RepairReport)
    assert isinstance(report.healthy, bool)
    assert isinstance(report.errors_found, int)


def test_notification_uses_logger(caplog):
    loop = SelfRepairLoop(skip_db=True, skip_signals=True)
    report = RepairReport(
        healthy=False,
        errors_found=3,
        repairs_attempted=2,
        repairs_succeeded=1,
        details=["DB timeout", "Signal import failed"],
    )
    with caplog.at_level(logging.CRITICAL, logger="omega.core.self_repair"):
        loop._notify(report)
    assert any("errors_found" in rec.message or "unhealthy" in rec.message.lower()
               for rec in caplog.records)


def test_to_dict_serializable():
    report = RepairReport(
        healthy=False,
        errors_found=2,
        repairs_attempted=1,
        repairs_succeeded=1,
        details=["detail1"],
    )
    d = report.to_dict()
    # Must be JSON-serializable
    assert json.dumps(d)
    assert d["healthy"] is False
    assert d["errors_found"] == 2
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
cd /Users/benebsworth/projects/omega
python -m pytest tests/test_self_repair.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'omega.core.self_repair'`

- [ ] **Step 3.3: Implement `omega/core/self_repair.py`**

```python
"""
omega.core.self_repair
~~~~~~~~~~~~~~~~~~~~~~
Daily self-repair loop — checks system health, analyzes error logs, and
attempts to auto-repair failed components.

Repair actions
--------------
- DB_TIMEOUT    : re-test DATABASE_URL connection (warns, does not reconnect
                  running psycopg connections — those reconnect on next call)
- SIGNAL_IMPORT : re-import failed signal modules via importlib
- LOG_FLOOD     : detected error spike → logs a CRITICAL alert

Notification
------------
1. Always logs at CRITICAL level.
2. If env var ``OMEGA_WEBHOOK_URL`` is set, POSTs a JSON payload there
   (best-effort, silently ignored on failure).

Usage::

    loop = SelfRepairLoop()
    report = loop.check_and_repair(log_file="/var/log/omega/omega.log")
    if not report.healthy:
        print(report.to_dict())
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("omega.core.self_repair")

# Error patterns that trigger repair actions
_ERROR_PATTERNS = [
    (re.compile(r"(database|psycopg|postgres|db)", re.IGNORECASE), "DB_TIMEOUT"),
    (re.compile(r"(signal.*(import|failed)|importerror)", re.IGNORECASE), "SIGNAL_IMPORT"),
    (re.compile(r"(critical|fatal|panic)", re.IGNORECASE), "CRITICAL_EVENT"),
]

# Signal modules we know how to re-import
_REPAIRABLE_SIGNAL_MODULES = [
    "omega.nodes.victoria.alt_data_signals",
    "omega.nodes.victoria.carry_signals",
    "omega.nodes.victoria.momentum_factor",
    "omega.nodes.victoria.market_data_signals",
    "omega.nodes.victoria.regime_detector",
    "omega.nodes.victoria.signal_generation",
]


@dataclass
class LogError:
    """A single error parsed from the log file."""
    line_number: int
    severity: str
    message: str
    error_type: str  # DB_TIMEOUT | SIGNAL_IMPORT | CRITICAL_EVENT


@dataclass
class RepairReport:
    """Result of a check_and_repair() run."""
    healthy: bool = True
    errors_found: int = 0
    repairs_attempted: int = 0
    repairs_succeeded: int = 0
    details: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "errors_found": self.errors_found,
            "repairs_attempted": self.repairs_attempted,
            "repairs_succeeded": self.repairs_succeeded,
            "details": self.details,
            "timestamp": self.timestamp,
        }


class SelfRepairLoop:
    """
    Self-monitoring and repair loop.

    Parameters
    ----------
    skip_db:
        Skip database connectivity checks (useful in test environments).
    skip_signals:
        Skip signal module re-import checks.
    webhook_url:
        Optional URL to POST repair reports to.  Defaults to
        ``OMEGA_WEBHOOK_URL`` env var.
    """

    def __init__(
        self,
        skip_db: bool = False,
        skip_signals: bool = False,
        webhook_url: str | None = None,
    ) -> None:
        self._skip_db = skip_db
        self._skip_signals = skip_signals
        self._webhook_url = webhook_url or os.environ.get("OMEGA_WEBHOOK_URL", "")

    # ── Public API ─────────────────────────────────────────────────────────────

    def check_and_repair(
        self,
        log_file: str | None = None,
        last_n_lines: int = 1000,
    ) -> RepairReport:
        """
        Run a full check cycle and attempt repairs.

        Steps:
        1. Run StartupValidator (skip slow checks if configured).
        2. Parse ``log_file`` for recent errors.
        3. For each detected error type, attempt a repair.
        4. Notify if unhealthy.

        Returns a RepairReport summarising findings and outcomes.
        """
        report = RepairReport()

        # ── 1. StartupValidator ────────────────────────────────────────────────
        try:
            from omega.core.startup_validator import StartupValidator
            validator = StartupValidator(
                skip_docker=True,
                skip_db=self._skip_db,
                skip_signals=self._skip_signals,
            )
            val_report = validator.run()
            if val_report.has_errors:
                report.healthy = False
                report.errors_found += val_report.error_count
                for c in val_report.checks:
                    if c.status == "error":
                        report.details.append(f"[startup] {c.label}: {c.detail}")
            for c in val_report.checks:
                if c.status == "warn":
                    report.details.append(f"[startup_warn] {c.label}: {c.detail}")
        except Exception as exc:
            logger.warning("SelfRepairLoop: StartupValidator failed: %s", exc)

        # ── 2. Log analysis ────────────────────────────────────────────────────
        log_errors: list[LogError] = []
        if log_file:
            log_errors = self._parse_log_errors(log_file, last_n_lines)
            if log_errors:
                report.healthy = False
                report.errors_found += len(log_errors)
                error_types = set(e.error_type for e in log_errors)
                report.details.append(
                    f"[log] {len(log_errors)} errors found, types: {sorted(error_types)}"
                )

        # ── 3. Repair actions ──────────────────────────────────────────────────
        error_types_found = {e.error_type for e in log_errors}

        if "DB_TIMEOUT" in error_types_found and not self._skip_db:
            report.repairs_attempted += 1
            if self._repair_db():
                report.repairs_succeeded += 1
                report.details.append("[repair] DB connectivity restored")
            else:
                report.details.append("[repair] DB connectivity check failed")

        if "SIGNAL_IMPORT" in error_types_found and not self._skip_signals:
            report.repairs_attempted += 1
            n_fixed = self._repair_signals()
            report.repairs_succeeded += 1
            report.details.append(f"[repair] Re-imported {n_fixed} signal module(s)")

        # ── 4. Notify ──────────────────────────────────────────────────────────
        if not report.healthy:
            self._notify(report)

        return report

    # ── Log parsing ────────────────────────────────────────────────────────────

    def _parse_log_errors(
        self, log_file: str, last_n_lines: int = 1000
    ) -> list[LogError]:
        """
        Parse the last ``last_n_lines`` lines of ``log_file`` for errors.
        Returns a list of LogError objects.
        """
        path = Path(log_file)
        if not path.exists():
            return []

        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            logger.warning("SelfRepairLoop: cannot read log %s: %s", log_file, exc)
            return []

        recent = lines[-last_n_lines:] if len(lines) > last_n_lines else lines
        errors: list[LogError] = []

        for i, line in enumerate(recent):
            upper = line.upper()
            severity = ""
            if " ERROR " in upper or upper.startswith("ERROR"):
                severity = "ERROR"
            elif " CRITICAL " in upper or upper.startswith("CRITICAL"):
                severity = "CRITICAL"
            else:
                continue

            error_type = "CRITICAL_EVENT"
            for pattern, etype in _ERROR_PATTERNS:
                if pattern.search(line):
                    error_type = etype
                    break

            errors.append(
                LogError(
                    line_number=len(lines) - len(recent) + i + 1,
                    severity=severity,
                    message=line.strip(),
                    error_type=error_type,
                )
            )

        return errors

    # ── Repair actions ─────────────────────────────────────────────────────────

    def _repair_db(self) -> bool:
        """
        Attempt to reconnect to the database and verify connectivity.
        Returns True if connection succeeds.
        """
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            logger.warning("SelfRepairLoop._repair_db: DATABASE_URL not set")
            return False
        try:
            import psycopg
            conn = psycopg.connect(db_url, connect_timeout=5)
            conn.close()
            logger.info("SelfRepairLoop._repair_db: DB connection OK")
            return True
        except Exception as exc:
            logger.error("SelfRepairLoop._repair_db: DB still unreachable: %s", exc)
            return False

    def _repair_signals(self) -> int:
        """
        Re-import all known signal modules to recover from import errors.
        Returns count of successfully (re-)imported modules.
        """
        fixed = 0
        for mod_path in _REPAIRABLE_SIGNAL_MODULES:
            try:
                if mod_path in __import__("sys").modules:
                    importlib.reload(__import__("sys").modules[mod_path])
                else:
                    importlib.import_module(mod_path)
                fixed += 1
            except Exception as exc:
                logger.warning(
                    "SelfRepairLoop._repair_signals: failed to re-import %s: %s",
                    mod_path,
                    exc,
                )
        logger.info("SelfRepairLoop._repair_signals: fixed %d/%d modules", fixed, len(_REPAIRABLE_SIGNAL_MODULES))
        return fixed

    # ── Notification ───────────────────────────────────────────────────────────

    def _notify(self, report: RepairReport) -> None:
        """
        Emit CRITICAL log and optionally POST to webhook.
        """
        payload = report.to_dict()
        logger.critical(
            "SelfRepairLoop: system unhealthy — errors_found=%d repairs=%d/%d details=%s",
            report.errors_found,
            report.repairs_succeeded,
            report.repairs_attempted,
            report.details[:3],
        )

        webhook = self._webhook_url
        if webhook:
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    webhook,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5):
                    pass
                logger.info("SelfRepairLoop: webhook notified at %s", webhook)
            except Exception as exc:
                logger.warning("SelfRepairLoop: webhook failed: %s", exc)
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
cd /Users/benebsworth/projects/omega
python -m pytest tests/test_self_repair.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 3.5: Commit**

```bash
git add omega/core/self_repair.py tests/test_self_repair.py
git commit -m "feat: self-repair loop with log error parsing and component auto-restart"
```

---

## Task 4: Task Scheduler

**Files:**
- Create: `omega/core/task_scheduler.py`
- Create: `tests/test_task_scheduler.py`

- [ ] **Step 4.1: Write failing tests**

```python
# tests/test_task_scheduler.py
import json
import time
import pytest
from datetime import datetime, timezone, timedelta
from omega.core.task_scheduler import TaskScheduler, CronExpression


# ── CronExpression parsing ─────────────────────────────────────────────────────

def test_cron_wildcard_always_matches():
    cron = CronExpression("* * * * *")
    dt = datetime(2026, 3, 29, 14, 30, tzinfo=timezone.utc)
    assert cron.matches(dt)


def test_cron_specific_minute_matches():
    cron = CronExpression("30 * * * *")
    assert cron.matches(datetime(2026, 3, 29, 14, 30, tzinfo=timezone.utc))
    assert not cron.matches(datetime(2026, 3, 29, 14, 31, tzinfo=timezone.utc))


def test_cron_daily_at_2am():
    cron = CronExpression("0 2 * * *")
    assert cron.matches(datetime(2026, 3, 29, 2, 0, tzinfo=timezone.utc))
    assert not cron.matches(datetime(2026, 3, 29, 2, 1, tzinfo=timezone.utc))
    assert not cron.matches(datetime(2026, 3, 29, 3, 0, tzinfo=timezone.utc))


def test_cron_invalid_expression_raises():
    with pytest.raises(ValueError):
        CronExpression("* * *")  # only 3 fields


# ── TaskScheduler ─────────────────────────────────────────────────────────────

def test_add_cron_and_tick_runs_task():
    scheduler = TaskScheduler()
    ran = []
    scheduler.add_cron("test_job", "* * * * *", lambda: ran.append(1))
    scheduler.tick(datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc))
    assert ran == [1]


def test_tick_does_not_run_task_twice_in_same_minute():
    scheduler = TaskScheduler()
    ran = []
    scheduler.add_cron("dedup_job", "* * * * *", lambda: ran.append(1))
    dt = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
    scheduler.tick(dt)
    scheduler.tick(dt)  # same minute — should not re-run
    assert len(ran) == 1


def test_tick_runs_task_in_next_minute():
    scheduler = TaskScheduler()
    ran = []
    scheduler.add_cron("next_min", "* * * * *", lambda: ran.append(1))
    dt1 = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
    dt2 = datetime(2026, 3, 29, 10, 1, tzinfo=timezone.utc)
    scheduler.tick(dt1)
    scheduler.tick(dt2)
    assert len(ran) == 2


def test_add_one_shot_runs_once():
    scheduler = TaskScheduler()
    ran = []
    run_at = datetime(2026, 3, 29, 15, 0, tzinfo=timezone.utc)
    scheduler.add_one_shot("snapshot", run_at, lambda: ran.append(1))
    scheduler.tick(datetime(2026, 3, 29, 14, 59, tzinfo=timezone.utc))
    assert ran == []
    scheduler.tick(run_at)
    assert ran == [1]
    scheduler.tick(datetime(2026, 3, 29, 15, 1, tzinfo=timezone.utc))
    assert ran == [1]  # did not re-run


def test_save_and_load_preserves_tasks(tmp_path):
    state_file = str(tmp_path / "state.json")
    scheduler = TaskScheduler(state_file=state_file)
    ran = []
    scheduler.add_cron("persistent_job", "0 6 * * *", lambda: ran.append(1))
    scheduler.save()

    # Reload into a new scheduler with a fresh callable registry
    scheduler2 = TaskScheduler(state_file=state_file)
    scheduler2.load()
    tasks = scheduler2.list_tasks()
    assert any(t["name"] == "persistent_job" for t in tasks)


def test_list_tasks_returns_metadata():
    scheduler = TaskScheduler()
    scheduler.add_cron("my_task", "0 2 * * *", lambda: None, tz="UTC")
    tasks = scheduler.list_tasks()
    assert len(tasks) == 1
    assert tasks[0]["name"] == "my_task"
    assert tasks[0]["cron"] == "0 2 * * *"
    assert tasks[0]["tz"] == "UTC"


def test_remove_task():
    scheduler = TaskScheduler()
    scheduler.add_cron("removable", "* * * * *", lambda: None)
    scheduler.remove("removable")
    assert scheduler.list_tasks() == []


def test_task_exception_does_not_crash_scheduler():
    scheduler = TaskScheduler()
    def bad_fn():
        raise RuntimeError("task failure")
    scheduler.add_cron("bad_task", "* * * * *", bad_fn)
    dt = datetime(2026, 3, 29, 10, 0, tzinfo=timezone.utc)
    # Should not raise — logs the error and continues
    ran = scheduler.tick(dt)
    assert "bad_task" in ran  # it was attempted
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
cd /Users/benebsworth/projects/omega
python -m pytest tests/test_task_scheduler.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'omega.core.task_scheduler'`

- [ ] **Step 4.3: Implement `omega/core/task_scheduler.py`**

```python
"""
omega.core.task_scheduler
~~~~~~~~~~~~~~~~~~~~~~~~~~
Cron-based task scheduler with persistent state and timezone awareness.

Features
--------
- Cron expressions (5-field: minute hour day month weekday)
- One-shot tasks (run once at a specific UTC datetime)
- Deduplication: a cron task runs at most once per minute window
- JSON-backed persistence for task metadata (callables are NOT persisted
  and must be re-registered after a process restart)
- Timezone-aware scheduling via ``zoneinfo``
- Graceful error handling: a failing task logs the exception but does
  not stop the scheduler

Usage::

    from omega.core.task_scheduler import TaskScheduler

    scheduler = TaskScheduler(state_file="data/scheduler_state.json")

    # Daily self-repair at 03:00 UTC
    scheduler.add_cron(
        "daily_self_repair",
        "0 3 * * *",
        lambda: SelfRepairLoop().check_and_repair(),
    )

    # One-shot snapshot
    from datetime import datetime, timezone
    scheduler.add_one_shot(
        "end_of_month_snapshot",
        datetime(2026, 3, 31, 23, 59, tzinfo=timezone.utc),
        take_snapshot,
    )

    # Call scheduler.tick() from your main loop (or a background thread)
    scheduler.tick()
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("omega.core.task_scheduler")

_DEFAULT_STATE_FILE = "data/scheduler_state.json"


# ── Cron expression parsing ────────────────────────────────────────────────────


class CronExpression:
    """
    Minimal 5-field cron parser: ``minute hour day month weekday``.

    Supports:
    - ``*``          : any value
    - ``5``          : exact value
    - ``*/5``        : every 5 (step)
    - ``0-30``       : range (inclusive)

    Raises ValueError for malformed expressions.
    """

    def __init__(self, expr: str) -> None:
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"Cron expression must have 5 fields (got {len(parts)}): {expr!r}"
            )
        self._expr = expr
        self._minute = _parse_field(parts[0], 0, 59)
        self._hour = _parse_field(parts[1], 0, 23)
        self._day = _parse_field(parts[2], 1, 31)
        self._month = _parse_field(parts[3], 1, 12)
        self._weekday = _parse_field(parts[4], 0, 6)  # 0=Sunday

    def matches(self, dt: datetime) -> bool:
        """Return True if ``dt`` matches this cron expression."""
        wd = dt.weekday()  # Monday=0 in Python
        # Convert to Sunday=0
        sunday_based = (wd + 1) % 7
        return (
            dt.minute in self._minute
            and dt.hour in self._hour
            and dt.day in self._day
            and dt.month in self._month
            and sunday_based in self._weekday
        )

    def __str__(self) -> str:
        return self._expr


def _parse_field(field: str, low: int, high: int) -> set[int]:
    """Parse a single cron field into a set of matching integers."""
    if field == "*":
        return set(range(low, high + 1))
    if "/" in field:
        base, step_str = field.split("/", 1)
        step = int(step_str)
        start = low if base == "*" else int(base)
        return set(range(start, high + 1, step))
    if "-" in field:
        a, b = field.split("-", 1)
        return set(range(int(a), int(b) + 1))
    return {int(field)}


# ── Task data structures ───────────────────────────────────────────────────────


@dataclass
class ScheduledTask:
    """Internal representation of a scheduled task."""
    name: str
    task_type: str          # "cron" | "one_shot"
    cron: str               # cron expression (empty for one_shot)
    run_at_iso: str         # ISO-8601 UTC datetime (empty for cron)
    tz: str                 # timezone name (e.g. "UTC", "US/Eastern")
    last_run_iso: str = ""  # ISO-8601 of last successful run
    run_count: int = 0


# ── Scheduler ─────────────────────────────────────────────────────────────────


class TaskScheduler:
    """
    Cron-based task scheduler.

    Callables are registered in memory; metadata (name, cron, last_run)
    is persisted to ``state_file`` as JSON.

    After a process restart, call ``load()`` to restore task metadata, then
    re-register callables via ``add_cron()`` / ``add_one_shot()`` — the
    load merges metadata so ``last_run_iso`` and ``run_count`` are preserved.
    """

    def __init__(self, state_file: str = _DEFAULT_STATE_FILE) -> None:
        self._state_file = state_file
        self._tasks: dict[str, ScheduledTask] = {}
        self._fns: dict[str, Callable] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def add_cron(
        self,
        name: str,
        cron_expr: str,
        fn: Callable,
        tz: str = "UTC",
    ) -> str:
        """
        Register a cron task.  Validates the cron expression immediately.
        Returns the task name.
        """
        CronExpression(cron_expr)  # validate
        existing = self._tasks.get(name)
        self._tasks[name] = ScheduledTask(
            name=name,
            task_type="cron",
            cron=cron_expr,
            run_at_iso="",
            tz=tz,
            last_run_iso=existing.last_run_iso if existing else "",
            run_count=existing.run_count if existing else 0,
        )
        self._fns[name] = fn
        logger.debug("TaskScheduler: registered cron task '%s' (%s %s)", name, cron_expr, tz)
        return name

    def add_one_shot(
        self,
        name: str,
        run_at: datetime,
        fn: Callable,
    ) -> str:
        """
        Register a one-shot task that runs once at ``run_at`` (UTC).
        Returns the task name.
        """
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=timezone.utc)
        self._tasks[name] = ScheduledTask(
            name=name,
            task_type="one_shot",
            cron="",
            run_at_iso=run_at.isoformat(),
            tz="UTC",
        )
        self._fns[name] = fn
        logger.debug(
            "TaskScheduler: registered one-shot task '%s' at %s",
            name,
            run_at.isoformat(),
        )
        return name

    def remove(self, name: str) -> None:
        """Remove a task by name. No-op if not found."""
        self._tasks.pop(name, None)
        self._fns.pop(name, None)

    # ── Tick ──────────────────────────────────────────────────────────────────

    def tick(self, now: datetime | None = None) -> list[str]:
        """
        Check all tasks against ``now`` and run any that are due.

        ``now`` defaults to the current UTC time.  Pass an explicit value
        for deterministic testing.

        Returns list of task names that were attempted (including failed ones).
        """
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        attempted: list[str] = []

        for name, task in list(self._tasks.items()):
            fn = self._fns.get(name)
            if fn is None:
                continue

            should_run = False

            if task.task_type == "cron":
                # Convert now to the task's timezone for matching
                dt_in_tz = _to_tz(now, task.tz)
                cron = CronExpression(task.cron)
                if cron.matches(dt_in_tz):
                    # Dedup: only run once per minute window
                    last_run = _parse_iso(task.last_run_iso)
                    if last_run is None or _minute_bucket(now) != _minute_bucket(last_run):
                        should_run = True

            elif task.task_type == "one_shot":
                if not task.last_run_iso:  # not yet run
                    run_at = _parse_iso(task.run_at_iso)
                    if run_at and now >= run_at:
                        should_run = True

            if should_run:
                attempted.append(name)
                try:
                    fn()
                    task.last_run_iso = now.isoformat()
                    task.run_count += 1
                    logger.info("TaskScheduler: ran task '%s' (count=%d)", name, task.run_count)
                except Exception as exc:
                    task.last_run_iso = now.isoformat()  # mark as attempted
                    task.run_count += 1
                    logger.error(
                        "TaskScheduler: task '%s' raised %s: %s",
                        name,
                        type(exc).__name__,
                        exc,
                    )

        return attempted

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str | None = None) -> None:
        """Persist task metadata (not callables) to JSON."""
        fpath = Path(path or self._state_file)
        fpath.parent.mkdir(parents=True, exist_ok=True)
        data = {name: asdict(task) for name, task in self._tasks.items()}
        fpath.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.debug("TaskScheduler: saved state to %s", fpath)

    def load(self, path: str | None = None) -> None:
        """
        Load task metadata from JSON.  Merges into existing tasks
        (preserves last_run_iso and run_count for already-registered tasks).
        """
        fpath = Path(path or self._state_file)
        if not fpath.exists():
            return
        try:
            data: dict[str, Any] = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("TaskScheduler: could not load state from %s: %s", fpath, exc)
            return
        for name, task_dict in data.items():
            if name not in self._tasks:
                # Restore metadata without a callable (fn will be missing until re-registered)
                self._tasks[name] = ScheduledTask(**task_dict)
            else:
                # Merge persisted counters into existing task
                self._tasks[name].last_run_iso = task_dict.get("last_run_iso", "")
                self._tasks[name].run_count = task_dict.get("run_count", 0)
        logger.debug("TaskScheduler: loaded state from %s (%d tasks)", fpath, len(data))

    # ── Introspection ─────────────────────────────────────────────────────────

    def list_tasks(self) -> list[dict[str, Any]]:
        """Return a list of task metadata dicts."""
        return [asdict(t) for t in self._tasks.values()]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _to_tz(dt: datetime, tz_name: str) -> datetime:
    """Convert ``dt`` to the named timezone. Falls back to UTC on error."""
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo(tz_name))
    except Exception:
        return dt.astimezone(timezone.utc)


def _parse_iso(iso: str) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def _minute_bucket(dt: datetime) -> str:
    """Return a string key representing the UTC minute bucket."""
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%Y%m%d%H%M")
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
cd /Users/benebsworth/projects/omega
python -m pytest tests/test_task_scheduler.py -v
```

Expected: all 10 tests PASS.

- [ ] **Step 4.5: Commit**

```bash
git add omega/core/task_scheduler.py tests/test_task_scheduler.py
git commit -m "feat: cron task scheduler with one-shot tasks and JSON persistence"
```

---

## Task 5: Run Full Test Suite and Final Commit

- [ ] **Step 5.1: Run all new tests together**

```bash
cd /Users/benebsworth/projects/omega
python -m pytest tests/test_vector_memory.py tests/test_strategy_factory.py tests/test_self_repair.py tests/test_task_scheduler.py -v
```

Expected: all tests PASS. Acceptable failure: any test that requires psycopg (DB) should be skipped or xfail.

- [ ] **Step 5.2: Verify no regressions in existing tests**

```bash
cd /Users/benebsworth/projects/omega
python -m pytest tests/ -x -q --ignore=tests/integration --ignore=tests/bridge 2>&1 | tail -20
```

Expected: existing test suite still passes (no regressions).

- [ ] **Step 5.3: Save design doc**

The design doc was saved to `docs/superpowers/specs/2026-03-29-intelligence-resilience-gaps-design.md` during brainstorming. Commit if not already committed:

```bash
git add docs/superpowers/specs/2026-03-29-intelligence-resilience-gaps-design.md \
        docs/superpowers/plans/2026-03-29-intelligence-resilience-gaps.md
git commit -m "docs: intelligence and resilience gap analysis spec and implementation plan"
```

- [ ] **Step 5.4: Merge to main**

```bash
git checkout main
git merge --no-ff claude/romantic-ptolemy -m "feat: vector memory, signal hot-loading, self-repair loop, task scheduler"
git push origin main
```

---

## Self-Review

**Spec coverage:**
- ✅ Vector memory with cosine dedup @ 0.92 → Task 1
- ✅ TF-IDF bag-of-words, no new deps → Task 1
- ✅ Retrieval before decision → `retrieve()` API in Task 1
- ✅ Runtime signal hot-loading → Task 2
- ✅ Write Python, save to disk, hot-load → `write_and_load()` in Task 2
- ✅ Self-repair: log parsing + auto-restart → Task 3
- ✅ Notification: CRITICAL log + optional webhook → Task 3
- ✅ Task scheduler: cron + one-shot → Task 4
- ✅ Persistent across restarts → `save()`/`load()` in Task 4
- ✅ Timezone-aware → `zoneinfo` in Task 4

**Placeholder scan:** None found.

**Type consistency:** All method signatures consistent across tasks. `VectorMemoryLayer.write()` returns `str | None`. `SignalHotLoader.write_and_load()` returns `types.ModuleType`. `RepairReport` used consistently in Task 3.
