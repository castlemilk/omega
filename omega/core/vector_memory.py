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
    "macro", "fed", "inflation", "gdp", "cpi",
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
"""

# Stable term-to-index mapping — never changes, so stored embeddings remain
# comparable across sessions and as the corpus grows.
_TERM_INDEX: dict[str, int] = {term: idx for idx, term in enumerate(_SEED_VOCAB)}
_VOCAB_DIM = len(_SEED_VOCAB)


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

        # Cache: id -> embedding array (populated on first dedup check)
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

        # Dedup check: skip when threshold <= 0 (disabled)
        if self._dedup_threshold > 0.0:
            self._ensure_cache()
            for existing_emb in self._embedding_cache.values():
                sim = self._cosine(embedding, existing_emb)
                if sim >= self._dedup_threshold:
                    logger.debug(
                        "VectorMemory dedup: similarity=%.3f >= %.3f — rejecting",
                        sim,
                        self._dedup_threshold,
                    )
                    return None

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

        # Update cache so subsequent writes in the same session dedup correctly
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
        Compute a normalised TF bag-of-words vector over the fixed seed vocabulary.

        Dimension is always ``_VOCAB_DIM`` (len(_SEED_VOCAB)) regardless of
        corpus size — this ensures stored embeddings remain comparable as new
        entries are added.  Out-of-vocabulary tokens are silently ignored.
        """
        tokens = _tokenize(text)
        if not tokens:
            return np.zeros(_VOCAB_DIM, dtype=np.float32)

        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        doc_len = len(tokens)

        vec = np.zeros(_VOCAB_DIM, dtype=np.float32)
        for term, count in tf.items():
            idx = _TERM_INDEX.get(term)
            if idx is None:
                continue
            vec[idx] = count / doc_len

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
        return max(-1.0, min(1.0, dot))

    def close(self) -> None:
        self._conn.close()
