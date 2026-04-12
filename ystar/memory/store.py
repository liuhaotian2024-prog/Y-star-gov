"""
Memory store implementations (SQLite + in-memory).

Board-mandated schema changes:
- `relevance_score` → `initial_score` (immutable)
- Decay computed at query time, never stored
- decay_scan only deletes, never UPDATEs scores
"""

from __future__ import annotations
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from .models import Memory, Agent, MemoryType, BUILT_IN_MEMORY_TYPES
from .decay import compute_relevance, decay_scan as decay_scan_fn


# Database schema (Board-corrected)
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    memory_id         TEXT PRIMARY KEY,
    agent_id          TEXT NOT NULL,
    memory_type       TEXT NOT NULL,
    content           TEXT NOT NULL,
    initial_score     REAL DEFAULT 1.0,  -- BOARD FIX: was relevance_score
    context_tags      TEXT DEFAULT '[]',

    created_at        REAL NOT NULL,
    last_accessed_at  REAL,
    access_count      INTEGER DEFAULT 0,

    half_life_days    REAL DEFAULT 30.0,
    min_score         REAL DEFAULT 0.1,

    reinforced_by     TEXT,
    parent_memory_id  TEXT,

    source_cieu_ref   TEXT,
    metadata_json     TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS agents (
    agent_id          TEXT PRIMARY KEY,
    display_name      TEXT,
    memory_quota_mb   REAL DEFAULT 10.0,
    retention_policy  TEXT DEFAULT 'standard',
    created_at        REAL NOT NULL,
    last_session_at   REAL,
    session_count     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS memory_types (
    memory_type       TEXT PRIMARY KEY,
    default_half_life REAL NOT NULL,
    description       TEXT,
    schema_json       TEXT
);

CREATE TABLE IF NOT EXISTS access_log (
    access_id         TEXT PRIMARY KEY,
    agent_id          TEXT NOT NULL,
    memory_id         TEXT NOT NULL,
    access_type       TEXT NOT NULL,  -- 'read', 'write', 'reinforce', 'forget'
    ts                REAL NOT NULL,
    cieu_ref          TEXT,
    context           TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_mem_agent       ON memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_mem_type        ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_mem_score       ON memories(initial_score);
CREATE INDEX IF NOT EXISTS idx_mem_created     ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_access_agent    ON access_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_access_memory   ON access_log(memory_id);
"""


class MemoryStore:
    """SQLite-backed memory store with Board-approved decay logic."""

    def __init__(self, db_path: str = ".ystar_memory.db"):
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self):
        """Initialize database schema and seed built-in memory types."""
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)
            # Enable WAL mode for better concurrency
            conn.execute("PRAGMA journal_mode=WAL")
            self._seed_memory_types(conn)

    def _conn(self):
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _seed_memory_types(self, conn):
        """Insert built-in memory types if not exists."""
        for mt in BUILT_IN_MEMORY_TYPES:
            conn.execute("""
                INSERT OR IGNORE INTO memory_types (memory_type, default_half_life, description)
                VALUES (?, ?, ?)
            """, (mt.memory_type, mt.default_half_life, mt.description))

    def remember(self, mem: Memory, cieu_ref: Optional[str] = None) -> str:
        """
        Store a memory.

        Args:
            mem: Memory object to store
            cieu_ref: Optional CIEU audit reference

        Returns:
            memory_id
        """
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO memories (
                    memory_id, agent_id, memory_type, content,
                    initial_score, context_tags, created_at,
                    half_life_days, min_score, source_cieu_ref, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                mem.memory_id, mem.agent_id, mem.memory_type, mem.content,
                mem.initial_score, json.dumps(mem.context_tags), mem.created_at,
                mem.half_life_days, mem.min_score, cieu_ref, json.dumps(mem.metadata)
            ))
            self._log_access(conn, mem.agent_id, mem.memory_id, "write", cieu_ref=cieu_ref)
            conn.commit()
        return mem.memory_id

    def recall(
        self,
        agent_id: str,
        memory_types: Optional[List[str]] = None,
        context_tags: Optional[List[str]] = None,
        min_relevance: float = 0.3,
        limit: int = 10,
        sort_by: str = "relevance_desc"
    ) -> List[Memory]:
        """
        Retrieve memories with filtering.

        Board mandate: Relevance is computed dynamically at query time.

        Args:
            agent_id: Filter by agent
            memory_types: Filter by types (e.g., ['decision', 'lesson'])
            context_tags: Filter by tags (e.g., ['deployment'])
            min_relevance: Exclude memories with current relevance < this
            limit: Max results
            sort_by: 'relevance_desc', 'created_desc', 'accessed_desc'

        Returns:
            List of Memory objects sorted and filtered
        """
        now = time.time()
        filters = ["agent_id = ?"]
        params = [agent_id]

        if memory_types:
            placeholders = ','.join('?' * len(memory_types))
            filters.append(f"memory_type IN ({placeholders})")
            params.extend(memory_types)

        if context_tags:
            # Simple JSON LIKE matching (not optimal, but works for SQLite)
            for tag in context_tags:
                filters.append("context_tags LIKE ?")
                params.append(f'%"{tag}"%')

        query = f"SELECT * FROM memories WHERE {' AND '.join(filters)}"

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            memories = [self._row_to_memory(r) for r in rows]

            # Compute current relevance and filter
            memories = [
                m for m in memories
                if m.compute_relevance(now) >= min_relevance
            ]

            # Sort
            if sort_by == "relevance_desc":
                memories.sort(key=lambda m: m.compute_relevance(now), reverse=True)
            elif sort_by == "created_desc":
                memories.sort(key=lambda m: m.created_at, reverse=True)
            elif sort_by == "accessed_desc":
                memories.sort(key=lambda m: m.last_accessed_at or 0, reverse=True)

            # Update access stats for returned memories
            result = memories[:limit]
            current_time = time.time()
            for mem in result:
                self._update_access(conn, mem.memory_id)
                self._log_access(conn, agent_id, mem.memory_id, "read")
                # Update the Memory object to reflect DB changes
                mem.access_count += 1
                mem.last_accessed_at = current_time

            conn.commit()
            return result

    def forget(self, memory_id: str, reason: str = "", cieu_ref: Optional[str] = None) -> bool:
        """
        Delete a memory.

        Args:
            memory_id: Memory to delete
            reason: Audit reason for deletion
            cieu_ref: Optional CIEU reference

        Returns:
            True if deleted, False if not found
        """
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
            if cursor.rowcount > 0:
                self._log_access(
                    conn, "system", memory_id, "forget",
                    context={"reason": reason}, cieu_ref=cieu_ref
                )
                conn.commit()
                return True
        return False

    def decay_scan(self, prune_threshold: float = 0.1) -> Tuple[int, int]:
        """
        Scan all memories and prune those with relevance below threshold.

        Board mandate: This method ONLY deletes memories. It does NOT update
        initial_score or any other field. Decay is computed dynamically.

        Args:
            prune_threshold: Delete memories with current relevance < this

        Returns:
            Tuple of (scanned_count, pruned_count)
        """
        now = time.time()
        pruned_count = 0

        with self._conn() as conn:
            rows = conn.execute("""
                SELECT memory_id, initial_score, created_at, half_life_days, min_score
                FROM memories
            """).fetchall()

            scanned_count = len(rows)

            for row in rows:
                current_relevance = compute_relevance(
                    initial_score=row["initial_score"],
                    created_at=row["created_at"],
                    half_life_days=row["half_life_days"],
                    min_score=row["min_score"],
                    now=now
                )

                if current_relevance < prune_threshold:
                    conn.execute("DELETE FROM memories WHERE memory_id = ?", (row["memory_id"],))
                    self._log_access(
                        conn, "system", row["memory_id"], "prune",
                        context={"relevance": current_relevance, "threshold": prune_threshold}
                    )
                    pruned_count += 1

            conn.commit()

        return scanned_count, pruned_count

    def reinforce(self, memory_id: str, boost_factor: float = 1.2) -> bool:
        """
        Reinforce a memory by boosting its initial_score.

        Args:
            memory_id: Memory to reinforce
            boost_factor: Multiply initial_score by this (e.g., 1.2 = 20% boost)

        Returns:
            True if reinforced, False if not found
        """
        with self._conn() as conn:
            # Read current initial_score
            row = conn.execute(
                "SELECT initial_score FROM memories WHERE memory_id = ?",
                (memory_id,)
            ).fetchone()

            if not row:
                return False

            new_score = min(1.0, row["initial_score"] * boost_factor)  # Cap at 1.0
            conn.execute(
                "UPDATE memories SET initial_score = ? WHERE memory_id = ?",
                (new_score, memory_id)
            )
            self._log_access(conn, "system", memory_id, "reinforce", context={"boost_factor": boost_factor})
            conn.commit()
            return True

    def get_agent_summary(self, agent_id: str) -> Dict:
        """
        Get memory health report for an agent.

        Returns:
            Dict with keys: total_memories, active_memories, usage_mb,
            oldest_memory, most_accessed, fading_memories
        """
        now = time.time()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE agent_id = ?",
                (agent_id,)
            ).fetchall()

            memories = [self._row_to_memory(r) for r in rows]
            active_memories = [m for m in memories if m.compute_relevance(now) >= 0.3]
            fading_memories = [
                m for m in memories
                if 0.1 < m.compute_relevance(now) < 0.4
            ]

            # Estimate storage usage (rough)
            usage_mb = sum(len(m.content.encode('utf-8')) for m in memories) / (1024 * 1024)

            # Most accessed
            most_accessed = sorted(memories, key=lambda m: m.access_count, reverse=True)[:5]

            return {
                "agent_id": agent_id,
                "total_memories": len(memories),
                "active_memories": len(active_memories),
                "usage_mb": round(usage_mb, 2),
                "oldest_memory": min((m.created_at for m in memories), default=None),
                "most_accessed": [
                    {"memory_id": m.memory_id, "content": m.content[:100], "access_count": m.access_count}
                    for m in most_accessed
                ],
                "fading_memories": [
                    {"memory_id": m.memory_id, "content": m.content[:100], "relevance": round(m.compute_relevance(now), 2)}
                    for m in fading_memories
                ]
            }

    def register_agent(self, agent: Agent) -> str:
        """Register or update agent metadata."""
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO agents (
                    agent_id, display_name, memory_quota_mb, retention_policy,
                    created_at, last_session_at, session_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                agent.agent_id, agent.display_name, agent.memory_quota_mb,
                agent.retention_policy, agent.created_at, agent.last_session_at,
                agent.session_count
            ))
            conn.commit()
        return agent.agent_id

    def _log_access(
        self,
        conn,
        agent_id: str,
        memory_id: str,
        access_type: str,
        context: Optional[Dict] = None,
        cieu_ref: Optional[str] = None
    ):
        """Log memory access to access_log table."""
        conn.execute("""
            INSERT INTO access_log (access_id, agent_id, memory_id, access_type, ts, cieu_ref, context)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            f"acc_{uuid.uuid4().hex[:8]}",
            agent_id,
            memory_id,
            access_type,
            time.time(),
            cieu_ref,
            json.dumps(context or {})
        ))

    def _update_access(self, conn, memory_id: str):
        """Update access count and timestamp."""
        conn.execute("""
            UPDATE memories
            SET access_count = access_count + 1, last_accessed_at = ?
            WHERE memory_id = ?
        """, (time.time(), memory_id))

    def _row_to_memory(self, row) -> Memory:
        """Convert SQLite row to Memory object."""
        return Memory(
            memory_id=row["memory_id"],
            agent_id=row["agent_id"],
            memory_type=row["memory_type"],
            content=row["content"],
            initial_score=row["initial_score"],
            context_tags=json.loads(row["context_tags"]) if row["context_tags"] else [],
            created_at=row["created_at"],
            last_accessed_at=row["last_accessed_at"],
            access_count=row["access_count"],
            half_life_days=row["half_life_days"],
            min_score=row["min_score"],
            reinforced_by=row["reinforced_by"],
            parent_memory_id=row["parent_memory_id"],
            source_cieu_ref=row["source_cieu_ref"],
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        )


class InMemoryMemoryStore:
    """
    In-memory memory store for testing.

    Implements same interface as MemoryStore but stores data in dicts.
    """

    def __init__(self):
        self.memories: Dict[str, Memory] = {}
        self.agents: Dict[str, Agent] = {}
        self.access_log: List[Dict] = []

    def remember(self, mem: Memory, cieu_ref: Optional[str] = None) -> str:
        self.memories[mem.memory_id] = mem
        self._log_access(mem.agent_id, mem.memory_id, "write", cieu_ref=cieu_ref)
        return mem.memory_id

    def recall(
        self,
        agent_id: str,
        memory_types: Optional[List[str]] = None,
        context_tags: Optional[List[str]] = None,
        min_relevance: float = 0.3,
        limit: int = 10,
        sort_by: str = "relevance_desc"
    ) -> List[Memory]:
        now = time.time()
        results = [
            m for m in self.memories.values()
            if m.agent_id == agent_id
        ]

        if memory_types:
            results = [m for m in results if m.memory_type in memory_types]

        if context_tags:
            results = [
                m for m in results
                if any(tag in m.context_tags for tag in context_tags)
            ]

        results = [m for m in results if m.compute_relevance(now) >= min_relevance]

        if sort_by == "relevance_desc":
            results.sort(key=lambda m: m.compute_relevance(now), reverse=True)
        elif sort_by == "created_desc":
            results.sort(key=lambda m: m.created_at, reverse=True)

        for mem in results[:limit]:
            mem.access_count += 1
            mem.last_accessed_at = now
            self._log_access(agent_id, mem.memory_id, "read")

        return results[:limit]

    def forget(self, memory_id: str, reason: str = "", cieu_ref: Optional[str] = None) -> bool:
        if memory_id in self.memories:
            del self.memories[memory_id]
            self._log_access("system", memory_id, "forget", context={"reason": reason}, cieu_ref=cieu_ref)
            return True
        return False

    def decay_scan(self, prune_threshold: float = 0.1) -> Tuple[int, int]:
        now = time.time()
        memories_list = list(self.memories.values())
        scanned = len(memories_list)

        to_prune = [
            m.memory_id for m in memories_list
            if m.compute_relevance(now) < prune_threshold
        ]

        for mem_id in to_prune:
            del self.memories[mem_id]
            self._log_access("system", mem_id, "prune")

        return scanned, len(to_prune)

    def reinforce(self, memory_id: str, boost_factor: float = 1.2) -> bool:
        if memory_id in self.memories:
            mem = self.memories[memory_id]
            mem.initial_score = min(1.0, mem.initial_score * boost_factor)
            self._log_access("system", memory_id, "reinforce", context={"boost_factor": boost_factor})
            return True
        return False

    def get_agent_summary(self, agent_id: str) -> Dict:
        now = time.time()
        agent_memories = [m for m in self.memories.values() if m.agent_id == agent_id]
        active = [m for m in agent_memories if m.compute_relevance(now) >= 0.3]
        fading = [m for m in agent_memories if 0.1 < m.compute_relevance(now) < 0.4]

        usage_mb = sum(len(m.content.encode('utf-8')) for m in agent_memories) / (1024 * 1024)

        most_accessed = sorted(agent_memories, key=lambda m: m.access_count, reverse=True)[:5]

        return {
            "agent_id": agent_id,
            "total_memories": len(agent_memories),
            "active_memories": len(active),
            "usage_mb": round(usage_mb, 2),
            "oldest_memory": min((m.created_at for m in agent_memories), default=None),
            "most_accessed": [
                {"memory_id": m.memory_id, "content": m.content[:100], "access_count": m.access_count}
                for m in most_accessed
            ],
            "fading_memories": [
                {"memory_id": m.memory_id, "content": m.content[:100], "relevance": round(m.compute_relevance(now), 2)}
                for m in fading
            ]
        }

    def register_agent(self, agent: Agent) -> str:
        self.agents[agent.agent_id] = agent
        return agent.agent_id

    def _log_access(
        self,
        agent_id: str,
        memory_id: str,
        access_type: str,
        context: Optional[Dict] = None,
        cieu_ref: str | None = None
    ):
        self.access_log.append({
            "access_id": f"acc_{uuid.uuid4().hex[:8]}",
            "agent_id": agent_id,
            "memory_id": memory_id,
            "access_type": access_type,
            "ts": time.time(),
            "cieu_ref": cieu_ref,
            "context": context or {}
        })
