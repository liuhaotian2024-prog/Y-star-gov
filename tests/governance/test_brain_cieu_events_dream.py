"""
Tests for CZL-BRAIN-CIEU-EVENTS-DREAM:
  - 8 BRAIN event types registered and emit-receivable
  - Dream runs on mock activation_log with 4 patterns injected -> 4 proposal types emitted
  - Idempotency: concurrent dream call within 30min -> skips
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import warnings
from pathlib import Path

import pytest

# Suppress NullCIEUStore warnings during test imports
warnings.filterwarnings("ignore", message="NullCIEUStore is active")

from ystar.governance.cieu_store import (
    CIEUStore,
    BRAIN_AUTO_INGEST_START,
    BRAIN_AUTO_INGEST_COMPLETE,
    BRAIN_AUTO_INGEST_FAILED,
    BRAIN_QUERY_SUCCESS,
    BRAIN_QUERY_FAILED,
    BRAIN_WRITEBACK_QUEUED,
    BRAIN_DREAM_CYCLE_START,
    BRAIN_DREAM_CYCLE_COMPLETE,
    BRAIN_EVENT_TYPES,
    BRAIN_DREAM_PROPOSAL_TYPES,
    BRAIN_NODE_PROPOSED,
    BRAIN_EDGE_PROPOSED,
    BRAIN_ARCHIVE_PROPOSED,
    BRAIN_ENTANGLEMENT_PROPOSED,
)
from ystar.governance.brain_dream_scheduler import (
    consolidate,
    check_lockout,
    set_sentinel,
    pattern_a_coactivation_edges,
    pattern_b_cluster_entanglement,
    pattern_c_archive_candidates,
    pattern_d_blind_spots,
    LOCKOUT_SECONDS,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def cieu_store():
    """In-memory CIEU store for event verification."""
    return CIEUStore(":memory:")


@pytest.fixture
def brain_db(tmp_path):
    """
    Create a mock aiden_brain.db with nodes, edges, and activation_log
    seeded for all 4 patterns.
    """
    db_path = str(tmp_path / "test_brain.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            name TEXT,
            file_path TEXT DEFAULT '',
            node_type TEXT DEFAULT '',
            depth_label TEXT DEFAULT '',
            dim_y REAL DEFAULT 0.5,
            dim_x REAL DEFAULT 0.5,
            dim_z REAL DEFAULT 0.5,
            dim_t REAL DEFAULT 0.5,
            dim_phi REAL DEFAULT 0.5,
            dim_c REAL DEFAULT 0.5,
            summary TEXT DEFAULT '',
            principles TEXT DEFAULT '[]',
            access_count INTEGER DEFAULT 0,
            last_accessed REAL,
            created_at REAL,
            updated_at REAL,
            base_activation REAL DEFAULT 0.0,
            content_hash TEXT
        );

        CREATE TABLE IF NOT EXISTS edges (
            source_id TEXT,
            target_id TEXT,
            weight REAL DEFAULT 0.5,
            edge_type TEXT DEFAULT 'semantic',
            co_activations INTEGER DEFAULT 0,
            PRIMARY KEY (source_id, target_id)
        );

        CREATE TABLE IF NOT EXISTS activation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT,
            activated_nodes TEXT,
            session_id TEXT,
            timestamp REAL
        );

        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
    """)

    now = time.time()

    # Insert nodes across different categories
    nodes = [
        # Pattern C candidates: low access, old last_accessed
        ("governance/rule_x", "Rule X", "governance", 0, now - 40 * 86400),
        ("governance/rule_y", "Rule Y", "governance", 1, now - 10 * 86400),
        # Normal nodes (different categories for Pattern B)
        ("kernel/core", "Kernel Core", "kernel", 10, now),
        ("platform/hooks", "Platform Hooks", "platform", 8, now),
        ("governance/loop", "Governance Loop", "governance", 5, now),
        ("ceo/strategy", "CEO Strategy", "ceo", 3, now),
        # Pattern A targets: frequently co-activated but no edge
        ("reports/spec_alpha", "Spec Alpha", "reports", 4, now),
        ("reports/spec_beta", "Spec Beta", "reports", 4, now),
    ]
    for nid, name, ntype, ac, la in nodes:
        conn.execute(
            "INSERT INTO nodes (id, name, node_type, access_count, last_accessed, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (nid, name, ntype, ac, la, now - 90 * 86400)
        )

    # Insert an existing edge (so Pattern A skips this pair)
    conn.execute(
        "INSERT INTO edges (source_id, target_id, weight, edge_type) "
        "VALUES (?, ?, ?, ?)",
        ("kernel/core", "platform/hooks", 0.7, "semantic")
    )

    # === Seed activation_log for all 4 patterns ===

    # Pattern A: reports/spec_alpha + reports/spec_beta co-activated 5 times (no edge)
    for i in range(5):
        conn.execute(
            "INSERT INTO activation_log (query, activated_nodes, session_id, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (
                f"query_pattern_a_{i}",
                json.dumps([
                    {"node_id": "reports/spec_alpha", "activation_level": 0.8},
                    {"node_id": "reports/spec_beta", "activation_level": 0.7},
                ]),
                "test-session",
                now - i * 60,
            )
        )

    # Pattern B: kernel/core + platform/hooks + governance/loop always co-activate (4x)
    # (these cross 3 categories: kernel, platform, governance)
    for i in range(4):
        conn.execute(
            "INSERT INTO activation_log (query, activated_nodes, session_id, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (
                f"query_pattern_b_{i}",
                json.dumps([
                    {"node_id": "kernel/core", "activation_level": 0.9},
                    {"node_id": "platform/hooks", "activation_level": 0.8},
                    {"node_id": "governance/loop", "activation_level": 0.7},
                ]),
                "test-session",
                now - i * 120,
            )
        )

    # Pattern D: recurring query with NO high-relevance node (5x)
    for i in range(5):
        conn.execute(
            "INSERT INTO activation_log (query, activated_nodes, session_id, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (
                "how to handle agent deadlock",
                json.dumps([
                    {"node_id": "governance/rule_x", "activation_level": 0.2},
                ]),
                "test-session",
                now - i * 300,
            )
        )

    conn.commit()
    conn.close()

    return db_path


@pytest.fixture
def sentinel_file(tmp_path):
    return tmp_path / ".last_dream_timestamp"


@pytest.fixture
def proposals_file(tmp_path):
    return tmp_path / ".dream_proposals.jsonl"


# ── Test Group 1: CIEU Event Types Registered ─────────────────────────

class TestBrainEventTypesRegistered:
    """Verify all 8 core event types + 4 proposal types are importable and emittable."""

    def test_8_core_event_types_exist(self):
        """All 8 core BRAIN event types are defined as module-level constants."""
        assert len(BRAIN_EVENT_TYPES) == 8
        expected = [
            "BRAIN_AUTO_INGEST_START",
            "BRAIN_AUTO_INGEST_COMPLETE",
            "BRAIN_AUTO_INGEST_FAILED",
            "BRAIN_QUERY_SUCCESS",
            "BRAIN_QUERY_FAILED",
            "BRAIN_WRITEBACK_QUEUED",
            "BRAIN_DREAM_CYCLE_START",
            "BRAIN_DREAM_CYCLE_COMPLETE",
        ]
        for name in expected:
            assert name in BRAIN_EVENT_TYPES, f"{name} missing from BRAIN_EVENT_TYPES"

    def test_4_proposal_types_exist(self):
        """All 4 dream proposal types are defined."""
        assert len(BRAIN_DREAM_PROPOSAL_TYPES) == 4
        expected = [
            "BRAIN_NODE_PROPOSED",
            "BRAIN_EDGE_PROPOSED",
            "BRAIN_ARCHIVE_PROPOSED",
            "BRAIN_ENTANGLEMENT_PROPOSED",
        ]
        for name in expected:
            assert name in BRAIN_DREAM_PROPOSAL_TYPES, f"{name} missing"

    def test_emit_all_8_event_types(self, cieu_store):
        """Each of the 8 core event types can be written and queried back."""
        for evt_type in BRAIN_EVENT_TYPES:
            ok = cieu_store.emit_brain_event(
                event_type=evt_type,
                payload={"test": True, "type": evt_type},
                session_id="test-emit",
            )
            assert ok, f"Failed to emit {evt_type}"

        # Verify all 8 are queryable
        results = cieu_store.query(session_id="test-emit", limit=100)
        types_found = {r.event_type for r in results}
        for evt_type in BRAIN_EVENT_TYPES:
            assert evt_type in types_found, f"{evt_type} not found in query results"

    def test_emit_proposal_event_types(self, cieu_store):
        """Each of the 4 proposal event types can be emitted."""
        for evt_type in BRAIN_DREAM_PROPOSAL_TYPES:
            ok = cieu_store.emit_brain_event(
                event_type=evt_type,
                payload={"test": True},
                session_id="test-proposals",
            )
            assert ok, f"Failed to emit {evt_type}"

    def test_reject_unknown_event_type(self, cieu_store):
        """Unknown event types are rejected."""
        ok = cieu_store.emit_brain_event(
            event_type="BRAIN_INVALID_TYPE",
            payload={"test": True},
            session_id="test-reject",
        )
        assert not ok


# ── Test Group 2: Dream Consolidation Patterns ────────────────────────

class TestDreamConsolidationPatterns:
    """Verify all 4 patterns produce correct proposals from mock data."""

    def test_pattern_a_coactivation_edges(self, brain_db):
        """Pattern A finds co-activated pairs without existing edge."""
        conn = sqlite3.connect(brain_db)
        conn.row_factory = sqlite3.Row
        proposals = pattern_a_coactivation_edges(conn, window=100)
        conn.close()

        # Should find reports/spec_alpha + reports/spec_beta (5 co-activations, no edge)
        assert len(proposals) >= 1
        edge_pairs = [(p["source_id"], p["target_id"]) for p in proposals]
        # sorted pair
        found = any(
            (s, t) in [("reports/spec_alpha", "reports/spec_beta"),
                       ("reports/spec_beta", "reports/spec_alpha")]
            for s, t in edge_pairs
        )
        assert found, f"Expected spec_alpha/spec_beta pair, got {edge_pairs}"
        # Verify it does NOT propose kernel/core + platform/hooks (edge exists)
        for s, t in edge_pairs:
            assert not (
                {s, t} == {"kernel/core", "platform/hooks"}
            ), "Should not propose edge for existing pair"

    def test_pattern_b_cluster_entanglement(self, brain_db):
        """Pattern B finds 3+ node clusters crossing 2+ categories."""
        conn = sqlite3.connect(brain_db)
        conn.row_factory = sqlite3.Row
        proposals = pattern_b_cluster_entanglement(conn, window=100)
        conn.close()

        # Should find kernel/core + platform/hooks + governance/loop cluster
        assert len(proposals) >= 1
        cluster_nodes = proposals[0]["cluster_node_ids"]
        assert len(cluster_nodes) >= 3
        assert proposals[0]["co_activation_count"] >= 4
        assert len(proposals[0]["categories_bridged"]) >= 2

    def test_pattern_c_archive_candidates(self, brain_db):
        """Pattern C finds low-access nodes for archiving."""
        conn = sqlite3.connect(brain_db)
        conn.row_factory = sqlite3.Row
        proposals = pattern_c_archive_candidates(conn)
        conn.close()

        # Should find governance/rule_x (access_count=0, last_accessed 40d ago)
        node_ids = [p["node_id"] for p in proposals]
        assert "governance/rule_x" in node_ids, f"Expected rule_x, got {node_ids}"
        # governance/rule_y has access_count=1 and last_accessed 10d ago -> should NOT be archived
        assert "governance/rule_y" not in node_ids, "rule_y should not be archived (recent access)"

    def test_pattern_d_blind_spots(self, brain_db):
        """Pattern D finds recurring queries with no high-relevance node."""
        conn = sqlite3.connect(brain_db)
        conn.row_factory = sqlite3.Row
        proposals = pattern_d_blind_spots(conn, window=100)
        conn.close()

        # Should find "how to handle agent deadlock" (5x, max activation 0.2 < 0.5)
        assert len(proposals) >= 1
        queries = [p["trigger_query"] for p in proposals]
        assert "how to handle agent deadlock" in queries

    def test_full_consolidation_produces_all_4_types(
        self, brain_db, cieu_store, sentinel_file, proposals_file
    ):
        """Full consolidation produces proposals for all 4 pattern types."""
        result = consolidate(
            scope="session-close",
            activation_window=100,
            sentinel_path=sentinel_file,
            proposals_path=proposals_file,
            cieu_store=cieu_store,
            session_id="test-full",
            force=True,
            db_connector=lambda: _make_conn(brain_db),
        )

        assert result["status"] == "complete"
        assert result["new_edges"] >= 1, "Pattern A should produce >= 1 proposal"
        assert result["entanglements"] >= 1, "Pattern B should produce >= 1 proposal"
        assert result["archives"] >= 1, "Pattern C should produce >= 1 proposal"
        assert result["new_nodes"] >= 1, "Pattern D should produce >= 1 proposal"
        assert result["proposals_total"] == (
            result["new_edges"] + result["entanglements"] +
            result["archives"] + result["new_nodes"]
        )

        # Verify proposals file was written
        assert proposals_file.exists()
        lines = proposals_file.read_text().strip().split("\n")
        assert len(lines) == result["proposals_total"]

        # Verify CIEU events emitted
        events = cieu_store.query(session_id="test-full", limit=200)
        event_types = [e.event_type for e in events]
        assert BRAIN_DREAM_CYCLE_START in event_types
        assert BRAIN_DREAM_CYCLE_COMPLETE in event_types
        assert BRAIN_EDGE_PROPOSED in event_types
        assert BRAIN_ENTANGLEMENT_PROPOSED in event_types
        assert BRAIN_ARCHIVE_PROPOSED in event_types
        assert BRAIN_NODE_PROPOSED in event_types


# ── Test Group 3: Idempotency ─────────────────────────────────────────

class TestDreamIdempotency:
    """Verify lockout sentinel prevents concurrent dreams."""

    def test_fresh_sentinel_not_locked(self, sentinel_file):
        """No sentinel file -> not locked."""
        locked, remaining = check_lockout(sentinel_file)
        assert not locked
        assert remaining == 0.0

    def test_recent_sentinel_is_locked(self, sentinel_file):
        """Sentinel written just now -> locked for ~30min."""
        set_sentinel(sentinel_file)
        locked, remaining = check_lockout(sentinel_file)
        assert locked
        assert remaining > LOCKOUT_SECONDS - 5  # within 5s tolerance

    def test_old_sentinel_not_locked(self, sentinel_file):
        """Sentinel older than 30min -> not locked."""
        sentinel_file.write_text(str(time.time() - LOCKOUT_SECONDS - 10))
        locked, remaining = check_lockout(sentinel_file)
        assert not locked

    def test_concurrent_dream_skips(
        self, brain_db, cieu_store, sentinel_file, proposals_file
    ):
        """Second dream within lockout window returns 'skipped'."""
        # First dream succeeds
        r1 = consolidate(
            scope="session-close",
            activation_window=100,
            sentinel_path=sentinel_file,
            proposals_path=proposals_file,
            cieu_store=cieu_store,
            session_id="test-idempotent",
            force=False,
            db_connector=lambda: _make_conn(brain_db),
        )
        assert r1["status"] == "complete"

        # Second dream (within 30min) should skip
        r2 = consolidate(
            scope="session-close",
            activation_window=100,
            sentinel_path=sentinel_file,
            proposals_path=proposals_file,
            cieu_store=cieu_store,
            session_id="test-idempotent-2",
            force=False,
            db_connector=lambda: _make_conn(brain_db),
        )
        assert r2["status"] == "skipped"
        assert "locked" in r2.get("reason", "").lower()

    def test_force_bypasses_lockout(
        self, brain_db, cieu_store, sentinel_file, proposals_file
    ):
        """force=True bypasses the lockout."""
        set_sentinel(sentinel_file)
        result = consolidate(
            scope="idle",
            activation_window=100,
            sentinel_path=sentinel_file,
            proposals_path=proposals_file,
            cieu_store=cieu_store,
            session_id="test-force",
            force=True,
            db_connector=lambda: _make_conn(brain_db),
        )
        assert result["status"] == "complete"


# ── Helper ────────────────────────────────────────────────────────────

def _make_conn(db_path: str) -> sqlite3.Connection:
    """Create a new SQLite connection to the test brain DB."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
