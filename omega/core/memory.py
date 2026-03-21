"""
omega.core.memory
~~~~~~~~~~~~~~~~~~
MemoryKernel — a human-mind-inspired memory system for the Omega framework.

Architecture
------------
  WorkingMemory   : ephemeral key-value store for the current heartbeat cycle
  EpisodicStore   : timestamped event records that decay over time
  SemanticStore   : learned patterns/rules; reinforced by episodes or decay
  Consolidator    : extracts patterns from episodic → semantic every N cycles
  Pruner          : removes memories that fall below importance threshold
  Retriever       : tag/keyword-based recall for node queries

Storage: all persistence in SQLite (zero external dependencies).

Design philosophy
-----------------
Each heartbeat cycle is an "episode". Nodes can:
  - Write to working memory (current cycle state)
  - Read episodic memories ("what happened last time X?")
  - Read semantic memories ("what do I know about X in general?")
  - Receive consolidated insights from the Consolidator

Human-mind analogues:
  WorkingMemory  ≈ prefrontal cortex / active attention
  EpisodicStore  ≈ hippocampus / autobiographical memory
  SemanticStore  ≈ neocortex / general knowledge
  Consolidation  ≈ sleep memory consolidation
  Pruning        ≈ forgetting curve / synaptic pruning
"""

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("omega.core.memory")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Episode:
    """A timestamped record of something that happened."""
    episode_id: str
    timestamp: float
    event_type: str          # e.g. "signal_generated", "portfolio_built", "feedback"
    content: dict[str, Any]  # structured data about the event
    tags: list[str]          # searchable labels
    importance: float        # 0.0-1.0; decays over time
    cycle: int               # heartbeat cycle number


@dataclass
class SemanticMemory:
    """A learned generalisation extracted from episodes."""
    memory_id: str
    concept: str             # e.g. "btc_momentum_signal", "high_vol_regime"
    content: str             # human-readable description of the pattern
    confidence: float        # 0.0-1.0; reinforced by new matching episodes
    evidence_count: int      # how many episodes support this
    last_reinforced: float   # unix timestamp of last reinforcement
    tags: list[str]


# ---------------------------------------------------------------------------
# Memory Kernel
# ---------------------------------------------------------------------------

class MemoryKernel:
    """
    Central memory system for the Omega Vectora domain.

    Usage::
        mem = MemoryKernel(db_path="vectora_memory.db")

        # Working memory (current cycle, ephemeral)
        mem.set_working("current_signals", {...})
        signals = mem.get_working("current_signals")

        # Store an episode
        mem.store_episode(
            event_type="signal_generated",
            content={"ticker": "BTCUSDT", "composite": 0.8, "outcome": 0.03},
            tags=["btc", "buy_signal", "momentum"],
            importance=0.8,
        )

        # Query episodic memory
        past_btc = mem.retrieve_episodes(tags=["btc", "buy_signal"], limit=5)

        # Semantic knowledge
        mem.store_semantic("btc_momentum", "BTC momentum signals tend to persist 3-5 days", 0.7)
        knowledge = mem.retrieve_semantic(concept="btc_momentum")
    """

    DECAY_RATE = 0.05          # per cycle; episodic importance decays by this factor
    SEMANTIC_DECAY_RATE = 0.02 # per cycle for unreinforced semantics
    MIN_IMPORTANCE = 0.05      # prune below this
    MAX_EPISODES = 500         # cap on total episodes
    MAX_SEMANTIC = 200         # cap on semantic memories
    CONSOLIDATION_INTERVAL = 5 # consolidate every N cycles

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._working: dict[str, Any] = {}
        self._current_cycle = 0
        self._create_schema()
        logger.info("MemoryKernel initialised (db=%s)", db_path)

    # ------------------------------------------------------------------ Schema

    def _create_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                episode_id   TEXT    PRIMARY KEY,
                timestamp    REAL    NOT NULL,
                cycle        INTEGER NOT NULL,
                event_type   TEXT    NOT NULL,
                content_json TEXT    NOT NULL,
                tags_json    TEXT    NOT NULL,
                importance   REAL    NOT NULL DEFAULT 1.0,
                namespace    TEXT    NOT NULL DEFAULT 'global'
            );

            CREATE TABLE IF NOT EXISTS semantic_memories (
                memory_id       TEXT    PRIMARY KEY,
                concept         TEXT    NOT NULL,
                content         TEXT    NOT NULL,
                confidence      REAL    NOT NULL DEFAULT 1.0,
                evidence_count  INTEGER NOT NULL DEFAULT 1,
                last_reinforced REAL    NOT NULL,
                tags_json       TEXT    NOT NULL DEFAULT '[]',
                namespace       TEXT    NOT NULL DEFAULT 'global'
            );

            CREATE TABLE IF NOT EXISTS memory_ratings (
                rating_id   TEXT PRIMARY KEY,
                memory_id   TEXT NOT NULL,
                namespace   TEXT NOT NULL DEFAULT 'global',
                quality     REAL NOT NULL,
                rated_at    REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_episodes_event_type ON episodes(event_type);
            CREATE INDEX IF NOT EXISTS idx_episodes_cycle ON episodes(cycle);
            CREATE INDEX IF NOT EXISTS idx_semantic_concept ON semantic_memories(concept);
        """)
        self._conn.commit()
        # Migration: add namespace column if missing (existing DBs), then create namespace indexes
        self._migrate_add_namespace()

    def _migrate_add_namespace(self) -> None:
        for table in ("episodes", "semantic_memories"):
            cols = [r[1] for r in self._conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "namespace" not in cols:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN namespace TEXT NOT NULL DEFAULT 'global'"
                )
        self._conn.commit()
        # Create namespace indexes now that the columns are guaranteed to exist
        self._conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_episodes_namespace ON episodes(namespace);
            CREATE INDEX IF NOT EXISTS idx_semantic_namespace ON semantic_memories(namespace);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------ Working Memory

    def set_working(self, key: str, value: Any) -> None:
        """Store a value in working memory (current cycle only, not persisted)."""
        self._working[key] = value

    def get_working(self, key: str, default: Any = None) -> Any:
        """Retrieve a value from working memory."""
        return self._working.get(key, default)

    def clear_working(self) -> None:
        """Clear all working memory at the start of a new cycle."""
        self._working.clear()

    def working_snapshot(self) -> dict[str, Any]:
        """Return a copy of all working memory."""
        return dict(self._working)

    # ------------------------------------------------------------------ Episodic Memory

    def store_episode(
        self,
        event_type: str,
        content: dict[str, Any],
        tags: list[str] | None = None,
        importance: float = 1.0,
        cycle: int | None = None,
        namespace: str = "global",
    ) -> str:
        """Store a new episode. Returns the episode_id."""
        episode_id = str(uuid.uuid4())
        ts = time.time()
        cyc = cycle if cycle is not None else self._current_cycle
        tags = tags or []

        self._conn.execute(
            """
            INSERT INTO episodes
            (episode_id, timestamp, cycle, event_type, content_json, tags_json, importance, namespace)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                episode_id, ts, cyc, event_type,
                json.dumps(content, default=str),
                json.dumps(tags),
                min(1.0, max(0.0, importance)),
                namespace,
            ),
        )
        self._conn.commit()
        return episode_id

    def retrieve_episodes(
        self,
        event_type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
        since_cycle: int | None = None,
        namespace: str | None = None,
    ) -> list[Episode]:
        """Retrieve episodes matching filters, ordered by importance desc."""
        query = "SELECT * FROM episodes WHERE importance >= ?"
        params: list[Any] = [min_importance]

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if since_cycle is not None:
            query += " AND cycle >= ?"
            params.append(since_cycle)
        if namespace is not None:
            query += " AND namespace = ?"
            params.append(namespace)

        query += " ORDER BY importance DESC, timestamp DESC LIMIT ?"
        params.append(limit * 3)  # fetch extra for tag filtering

        rows = self._conn.execute(query, params).fetchall()
        episodes = []

        for row in rows:
            content = json.loads(row["content_json"])
            row_tags = json.loads(row["tags_json"])

            # Tag filtering
            if tags and not any(t in row_tags for t in tags):
                continue

            episodes.append(Episode(
                episode_id=row["episode_id"],
                timestamp=row["timestamp"],
                event_type=row["event_type"],
                content=content,
                tags=row_tags,
                importance=row["importance"],
                cycle=row["cycle"],
            ))
            if len(episodes) >= limit:
                break

        return episodes

    def get_episode_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as n FROM episodes").fetchone()
        return row["n"] if row else 0

    # ------------------------------------------------------------------ Semantic Memory

    def store_semantic(
        self,
        concept: str,
        content: str,
        confidence: float = 1.0,
        tags: list[str] | None = None,
        namespace: str = "global",
    ) -> str:
        """Store or update a semantic memory. Returns memory_id."""
        tags = tags or []

        # Check if concept already exists within this namespace
        existing = self._conn.execute(
            "SELECT memory_id, evidence_count, confidence FROM semantic_memories WHERE concept = ? AND namespace = ?",
            (concept, namespace),
        ).fetchone()

        if existing:
            # Reinforce existing memory
            new_confidence = min(1.0, existing["confidence"] + confidence * 0.1)
            new_count = existing["evidence_count"] + 1
            self._conn.execute(
                """
                UPDATE semantic_memories
                SET content = ?, confidence = ?, evidence_count = ?, last_reinforced = ?, tags_json = ?
                WHERE concept = ? AND namespace = ?
                """,
                (content, new_confidence, new_count, time.time(), json.dumps(tags), concept, namespace),
            )
            self._conn.commit()
            return existing["memory_id"]  # type: ignore[no-any-return]
        else:
            memory_id = str(uuid.uuid4())
            self._conn.execute(
                """
                INSERT INTO semantic_memories
                (memory_id, concept, content, confidence, evidence_count, last_reinforced, tags_json, namespace)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (memory_id, concept, content, confidence, time.time(), json.dumps(tags), namespace),
            )
            self._conn.commit()
            return memory_id

    def retrieve_semantic(
        self,
        concept: str | None = None,
        tags: list[str] | None = None,
        query_text: str | None = None,
        limit: int = 5,
        min_confidence: float = 0.1,
        namespace: str | None = None,
    ) -> list[SemanticMemory]:
        """Retrieve semantic memories by concept, tags, or keyword search."""
        sql = "SELECT * FROM semantic_memories WHERE confidence >= ?"
        params: list[Any] = [min_confidence]

        if namespace is not None:
            sql += " AND namespace = ?"
            params.append(namespace)

        sql += " ORDER BY confidence DESC LIMIT ?"
        params.append(limit * 3)

        rows = self._conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            row_tags = json.loads(row["tags_json"])

            if concept and concept.lower() not in row["concept"].lower():
                continue
            if tags and not any(t in row_tags for t in tags):
                continue
            if query_text:
                text_lower = query_text.lower()
                if (
                    text_lower not in row["concept"].lower()
                    and text_lower not in row["content"].lower()
                    and not any(text_lower in t.lower() for t in row_tags)
                ):
                    continue

            results.append(SemanticMemory(
                memory_id=row["memory_id"],
                concept=row["concept"],
                content=row["content"],
                confidence=row["confidence"],
                evidence_count=row["evidence_count"],
                last_reinforced=row["last_reinforced"],
                tags=row_tags,
            ))
            if len(results) >= limit:
                break

        return results

    def reinforce_semantic(self, concept: str, delta: float = 0.05) -> bool:
        """Strengthen confidence for an existing semantic memory. Returns True if found."""
        row = self._conn.execute(
            "SELECT confidence FROM semantic_memories WHERE concept = ?", (concept,)
        ).fetchone()
        if not row:
            return False
        new_conf = min(1.0, row["confidence"] + delta)
        self._conn.execute(
            "UPDATE semantic_memories SET confidence = ?, last_reinforced = ?, evidence_count = evidence_count + 1 WHERE concept = ?",
            (new_conf, time.time(), concept),
        )
        self._conn.commit()
        return True

    # ------------------------------------------------------------------ Ratings

    def rate_memory(self, memory_id: str, quality: float, namespace: str = "global") -> None:
        """Record a quality rating for a memory entry."""
        self._conn.execute(
            "INSERT INTO memory_ratings (rating_id, memory_id, namespace, quality, rated_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), memory_id, namespace, min(1.0, max(0.0, quality)), time.time()),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ NodeMemory factory

    def get_node_memory(self, node_name: str) -> "NodeMemory":
        """Return a NodeMemory facade scoped to this node's namespace."""
        return NodeMemory(kernel=self, namespace=node_name)

    # ------------------------------------------------------------------ Consolidation

    def consolidate(self, namespace: str | None = None) -> list[str]:
        """
        Extract patterns from recent episodes and store as semantic memories.
        Returns list of new/updated concepts.

        Consolidation rules:
          - If a signal type appears N times with positive outcome → store "X works"
          - If a ticker appears frequently in top signals → store "X is trending"
          - If high volatility correlates with poor signals → store "vol regime warning"
        """
        concepts_updated: list[str] = []
        recent = self.retrieve_episodes(
            event_type="signal_outcome",
            limit=50,
            min_importance=0.1,
            since_cycle=max(0, self._current_cycle - 20),
            namespace=namespace,
        )

        if not recent:
            return concepts_updated

        # Pattern: signal type success rate
        signal_outcomes: dict[str, list[float]] = {}
        ticker_appearances: dict[str, int] = {}

        for ep in recent:
            content = ep.content
            ticker = content.get("ticker", "")
            signal_type = content.get("signal_type", "composite")
            outcome = content.get("outcome", 0.0)

            if ticker:
                ticker_appearances[ticker] = ticker_appearances.get(ticker, 0) + 1

            key = f"{ticker}:{signal_type}" if ticker else signal_type
            if key not in signal_outcomes:
                signal_outcomes[key] = []
            signal_outcomes[key].append(outcome)

        # Generate semantic memories from patterns
        store_ns = namespace or "global"
        for key, outcomes in signal_outcomes.items():
            if len(outcomes) < 3:
                continue
            hit_rate = sum(1 for o in outcomes if o > 0) / len(outcomes)
            avg_outcome = sum(outcomes) / len(outcomes)

            if ":" in key:
                ticker, sig_type = key.split(":", 1)
                concept = f"{ticker.lower()}_{sig_type}_pattern"
                tags = [ticker.lower(), sig_type]
            else:
                concept = f"{key}_pattern"
                tags = [key]

            if hit_rate > 0.6:
                content_str = (
                    f"{key} signal has {hit_rate:.0%} hit rate over {len(outcomes)} samples "
                    f"(avg return {avg_outcome:+.3%}). Momentum persists."
                )
                self.store_semantic(concept, content_str, confidence=hit_rate, tags=tags, namespace=store_ns)
                concepts_updated.append(concept)
            elif hit_rate < 0.4:
                content_str = (
                    f"{key} signal has poor hit rate {hit_rate:.0%} over {len(outcomes)} samples. "
                    f"Consider reducing weight."
                )
                self.store_semantic(concept, content_str, confidence=0.3, tags=tags, namespace=store_ns)
                concepts_updated.append(concept)

        # Top appearing tickers
        for ticker, count in sorted(ticker_appearances.items(), key=lambda x: -x[1])[:3]:
            if count >= 3:
                concept = f"{ticker.lower()}_trending"
                content_str = f"{ticker} appeared in {count} recent signal episodes — strong interest."
                self.store_semantic(concept, content_str, confidence=0.6, tags=[ticker.lower()], namespace=store_ns)
                concepts_updated.append(concept)

        if concepts_updated:
            logger.info(
                "Memory consolidation: updated %d semantic concepts", len(concepts_updated)
            )

        return concepts_updated

    # ------------------------------------------------------------------ Pruning & Decay

    def decay_and_prune(self) -> tuple[int, int]:
        """
        Apply importance decay to all episodes and remove those below threshold.
        Returns (episodes_decayed, episodes_pruned, semantics_pruned).
        """
        # Decay episodic importance
        self._conn.execute(
            "UPDATE episodes SET importance = importance * ?",
            (1.0 - self.DECAY_RATE,),
        )
        self._conn.commit()

        # Prune low-importance episodes
        pruned = self._conn.execute(
            "DELETE FROM episodes WHERE importance < ?",
            (self.MIN_IMPORTANCE,),
        ).rowcount
        self._conn.commit()

        # Cap total episodes
        total = self.get_episode_count()
        if total > self.MAX_EPISODES:
            # Delete the oldest low-importance episodes
            excess = total - self.MAX_EPISODES
            self._conn.execute(
                """
                DELETE FROM episodes WHERE episode_id IN (
                    SELECT episode_id FROM episodes ORDER BY importance ASC, timestamp ASC LIMIT ?
                )
                """,
                (excess,),
            )
            self._conn.commit()
            pruned += excess

        # Decay semantic confidence for unreinforced memories
        age_threshold = time.time() - (self._current_cycle * 30 + 60)  # approx cycle time
        self._conn.execute(
            "UPDATE semantic_memories SET confidence = confidence * ? WHERE last_reinforced < ?",
            (1.0 - self.SEMANTIC_DECAY_RATE, age_threshold),
        )
        self._conn.commit()

        # Prune weak semantic memories (keep at least 10)
        sem_count = self._conn.execute(
            "SELECT COUNT(*) as n FROM semantic_memories"
        ).fetchone()["n"]
        sem_pruned = 0
        if sem_count > 10:
            sem_pruned = self._conn.execute(
                "DELETE FROM semantic_memories WHERE confidence < ? AND evidence_count < 3",
                (self.MIN_IMPORTANCE,),
            ).rowcount
            self._conn.commit()

        if pruned > 0 or sem_pruned > 0:
            logger.debug(
                "Memory pruned: %d episodes, %d semantic memories", pruned, sem_pruned
            )

        return (pruned, sem_pruned)

    # ------------------------------------------------------------------ Lifecycle

    def begin_cycle(self, cycle: int) -> None:
        """Called at the start of each heartbeat cycle."""
        self._current_cycle = cycle
        self.clear_working()

        # Run decay every cycle
        self.decay_and_prune()

        # Consolidate every N cycles
        if cycle > 0 and cycle % self.CONSOLIDATION_INTERVAL == 0:
            concepts = self.consolidate()
            if concepts:
                logger.info("Cycle %d consolidation: %d patterns learned", cycle, len(concepts))

    def end_cycle(self, cycle: int, summary: dict[str, Any]) -> str:
        """Store a cycle summary episode at the end of each heartbeat."""
        return self.store_episode(
            event_type="cycle_summary",
            content=summary,
            tags=["cycle_end", f"cycle_{cycle}"],
            importance=0.8,
            cycle=cycle,
            namespace="global",
        )

    # ------------------------------------------------------------------ Query interface

    def query(self, question: str, limit: int = 5, namespace: str | None = None) -> dict[str, Any]:
        """
        Natural-language-ish query against all memory stores.
        Returns matching episodes and semantic memories.
        """
        words = [w.lower() for w in question.split() if len(w) > 2]

        # Search semantic memories
        semantic_results = []
        for word in words[:3]:  # use first 3 significant words
            sem = self.retrieve_semantic(query_text=word, limit=3, namespace=namespace)
            semantic_results.extend(sem)

        # Deduplicate semantic results
        seen_ids = set()
        unique_semantic = []
        for s in semantic_results:
            if s.memory_id not in seen_ids:
                seen_ids.add(s.memory_id)
                unique_semantic.append(s)

        # Search episodic memories using tags derived from the question
        tag_candidates = [w for w in words if len(w) > 3]
        episodes = self.retrieve_episodes(tags=tag_candidates[:3], limit=limit, namespace=namespace)

        return {
            "question": question,
            "semantic": [
                {"concept": s.concept, "content": s.content, "confidence": s.confidence}
                for s in unique_semantic[:limit]
            ],
            "episodes": [
                {
                    "event_type": e.event_type,
                    "content": e.content,
                    "importance": e.importance,
                    "cycle": e.cycle,
                }
                for e in episodes
            ],
        }

    def summary(self) -> dict[str, Any]:
        """Return a status summary of the memory kernel."""
        episode_count = self.get_episode_count()
        sem_count = self._conn.execute(
            "SELECT COUNT(*) as n FROM semantic_memories"
        ).fetchone()["n"]
        working_keys = list(self._working.keys())

        top_semantic = self._conn.execute(
            "SELECT concept, confidence FROM semantic_memories ORDER BY confidence DESC LIMIT 5"
        ).fetchall()

        return {
            "current_cycle": self._current_cycle,
            "working_memory_keys": working_keys,
            "episodic_count": episode_count,
            "semantic_count": sem_count,
            "top_semantic_concepts": [
                {"concept": r["concept"], "confidence": r["confidence"]}
                for r in top_semantic
            ],
        }


# ---------------------------------------------------------------------------
# NodeMemory — per-node namespaced memory facade
# ---------------------------------------------------------------------------

class NodeMemory:
    """
    Per-node memory facade with namespace isolation.

    Each node gets its own NodeMemory, scoped to its namespace.
    Reads/writes never bleed into other nodes' memories.

    Tiers:
      working  : key-value dict with per-entry TTL (in-memory, ephemeral)
      episodic : timestamped events stored in SQLite (namespaced)
      semantic : learned patterns stored in SQLite (namespaced)
      feedback : quality ratings on memory entries

    Usage::
        node_mem = memory_kernel.get_node_memory("DataIngestionNode")

        # Working memory (ephemeral, TTL-aware)
        node_mem.remember("last_fetch_stats", {...}, ttl_seconds=300)
        stats = node_mem.recall("last_fetch_stats")

        # Episodic
        eid = node_mem.store_episode("data_fetched", {"pairs": 15}, importance=0.7)
        node_mem.rate(eid, 0.9)  # this was a good fetch

        # Semantic
        node_mem.store_semantic("btc_volatility", "BTC volatility spikes Fridays", 0.6)

        # Search across all tiers
        results = node_mem.search("BTC volatility")
    """

    def __init__(self, kernel: MemoryKernel, namespace: str) -> None:
        self._kernel = kernel
        self._namespace = namespace
        # working: key → (value, set_at_unix, ttl_seconds)
        self._working: dict[str, tuple[Any, float, float]] = {}

    @property
    def namespace(self) -> str:
        return self._namespace

    # ------------------------------------------------------------------ working

    def remember(self, key: str, value: Any, ttl_seconds: float = 600.0) -> None:
        """Store in working memory with TTL. Overwrites existing."""
        self._working[key] = (value, time.time(), ttl_seconds)

    def recall(self, key: str, default: Any = None) -> Any:
        """Retrieve from working memory. Returns default if missing or expired."""
        entry = self._working.get(key)
        if entry is None:
            return default
        value, set_at, ttl = entry
        if time.time() - set_at > ttl:
            del self._working[key]
            return default
        return value

    def forget_working(self, key: str) -> None:
        """Remove a specific working memory entry."""
        self._working.pop(key, None)

    def flush_expired(self) -> int:
        """Evict all expired working memory entries. Returns count evicted."""
        now = time.time()
        expired = [k for k, (_, set_at, ttl) in self._working.items() if now - set_at > ttl]
        for k in expired:
            del self._working[k]
        return len(expired)

    def working_keys(self) -> list[str]:
        self.flush_expired()
        return list(self._working.keys())

    # ------------------------------------------------------------------ episodic

    def store_episode(
        self,
        event_type: str,
        content: dict[str, Any],
        tags: list[str] | None = None,
        importance: float = 1.0,
        cycle: int | None = None,
    ) -> str:
        """Store a namespaced episode. Returns episode_id."""
        return self._kernel.store_episode(
            event_type=event_type,
            content=content,
            tags=tags,
            importance=importance,
            cycle=cycle,
            namespace=self._namespace,
        )

    def retrieve_episodes(
        self,
        event_type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
        since_cycle: int | None = None,
    ) -> list[Episode]:
        return self._kernel.retrieve_episodes(
            event_type=event_type,
            tags=tags,
            limit=limit,
            min_importance=min_importance,
            since_cycle=since_cycle,
            namespace=self._namespace,
        )

    # ------------------------------------------------------------------ semantic

    def store_semantic(
        self,
        concept: str,
        content: str,
        confidence: float = 1.0,
        tags: list[str] | None = None,
    ) -> str:
        """Store or reinforce a namespaced semantic memory. Returns memory_id."""
        return self._kernel.store_semantic(
            concept=concept,
            content=content,
            confidence=confidence,
            tags=tags,
            namespace=self._namespace,
        )

    def retrieve_semantic(
        self,
        concept: str | None = None,
        tags: list[str] | None = None,
        query_text: str | None = None,
        limit: int = 5,
        min_confidence: float = 0.1,
    ) -> list[SemanticMemory]:
        return self._kernel.retrieve_semantic(
            concept=concept,
            tags=tags,
            query_text=query_text,
            limit=limit,
            min_confidence=min_confidence,
            namespace=self._namespace,
        )

    # ------------------------------------------------------------------ feedback / rating

    def rate(self, memory_id: str, quality: float) -> None:
        """Rate a memory entry (0.0 = poor, 1.0 = excellent). Affects future importance."""
        self._kernel.rate_memory(memory_id, quality, self._namespace)

    # ------------------------------------------------------------------ search

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        """Keyword search across episodic + semantic tiers (namespaced)."""
        return self._kernel.query(query, limit, namespace=self._namespace)

    # ------------------------------------------------------------------ summary

    def summary(self) -> dict[str, Any]:
        episode_count = len(self.retrieve_episodes(limit=9999, min_importance=0.0))
        semantic_list = self.retrieve_semantic(limit=9999, min_confidence=0.0)
        working_keys = self.working_keys()
        return {
            "namespace": self._namespace,
            "working_keys": working_keys,
            "episodic_count": episode_count,
            "semantic_count": len(semantic_list),
        }
