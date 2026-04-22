"""
Tests for ARCH-18 Phase 3: dim-centroid drift + embedding refinement.

All tests use in-memory SQLite with synthetic data — no external DB needed.
"""

import json
import sqlite3
import time
import uuid

import pytest

from ystar.governance.cieu_brain_learning import (
    apply_drift_to_all_nodes,
    compute_event_type_coord_centroids,
    compute_node_centroid_drift,
    refined_project_event_to_6d,
    run_learning_cycle,
    LEARNING_RATE,
    MIN_SAMPLES_FOR_LEARNED,
)
from ystar.governance.cieu_brain_bridge import project_event_to_6d


# ── Fixtures ────────────────────────────────────────────────────────────

def _create_brain_schema(conn: sqlite3.Connection):
    """Create the brain DB schema (nodes, edges, activation_log)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            file_path   TEXT,
            node_type   TEXT,
            depth_label TEXT,
            content_hash TEXT,
            dim_y       REAL DEFAULT 0.5,
            dim_x       REAL DEFAULT 0.5,
            dim_z       REAL DEFAULT 0.5,
            dim_t       REAL DEFAULT 0.5,
            dim_phi     REAL DEFAULT 0.5,
            dim_c       REAL DEFAULT 0.5,
            base_activation REAL DEFAULT 0.0,
            last_accessed   REAL DEFAULT 0.0,
            access_count    INTEGER DEFAULT 0,
            created_at      REAL DEFAULT 0.0,
            updated_at      REAL DEFAULT 0.0,
            principles  TEXT,
            triggers    TEXT,
            summary     TEXT,
            embedding   BLOB
        );
        CREATE TABLE IF NOT EXISTS edges (
            source_id   TEXT NOT NULL,
            target_id   TEXT NOT NULL,
            edge_type   TEXT DEFAULT 'explicit',
            weight      REAL DEFAULT 0.5,
            created_at  REAL DEFAULT 0.0,
            updated_at  REAL DEFAULT 0.0,
            co_activations INTEGER DEFAULT 0,
            PRIMARY KEY (source_id, target_id)
        );
        CREATE TABLE IF NOT EXISTS activation_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            query       TEXT,
            activated_nodes TEXT,
            session_id  TEXT,
            timestamp   REAL
        );
    """)


def _create_cieu_schema(conn: sqlite3.Connection):
    """Create a minimal cieu_events table for testing."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cieu_events (
            rowid        INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id     TEXT NOT NULL UNIQUE,
            seq_global   INTEGER NOT NULL,
            created_at   REAL NOT NULL,
            session_id   TEXT NOT NULL,
            agent_id     TEXT NOT NULL,
            event_type   TEXT NOT NULL,
            decision     TEXT NOT NULL,
            passed       INTEGER NOT NULL DEFAULT 0,
            violations   TEXT,
            drift_detected INTEGER NOT NULL DEFAULT 0,
            drift_details TEXT,
            drift_category TEXT,
            file_path    TEXT,
            command      TEXT,
            url          TEXT,
            skill_name   TEXT,
            skill_source TEXT,
            task_description TEXT,
            contract_hash TEXT,
            chain_depth   INTEGER DEFAULT 0,
            params_json   TEXT,
            result_json   TEXT,
            human_initiator TEXT,
            lineage_path  TEXT,
            sealed       INTEGER NOT NULL DEFAULT 0,
            evidence_grade TEXT DEFAULT 'decision'
        )
    """)


def _insert_node(conn, node_id, name="test_node", coords=(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)):
    conn.execute(
        "INSERT INTO nodes (id, name, dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (node_id, name, *coords),
    )
    conn.commit()


def _insert_activation(conn, event_id, node_id, ts=None):
    """Insert one activation_log row linking an event to a node."""
    if ts is None:
        ts = time.time()
    activated = json.dumps([{"node_id": node_id, "activation_level": 0.8}])
    conn.execute(
        "INSERT INTO activation_log (query, activated_nodes, session_id, timestamp) "
        "VALUES (?, ?, ?, ?)",
        (f"cieu_event:{event_id}", activated, "test_session", ts),
    )
    conn.commit()


def _insert_cieu_event(conn, event_id, event_type="file_write", decision="allow"):
    now = time.time()
    conn.execute(
        """INSERT INTO cieu_events
           (event_id, seq_global, created_at, session_id, agent_id,
            event_type, decision, passed)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, int(now * 1e6), now, "test", "test", event_type, decision, 1),
    )
    conn.commit()


# ── Test 1: Drift moves centroid toward firing mean ─────────────────────

def test_drift_moves_centroid_toward_firing_mean():
    brain = sqlite3.connect(":memory:")
    cieu = sqlite3.connect(":memory:")
    _create_brain_schema(brain)
    _create_cieu_schema(cieu)

    # Node starts at (0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
    _insert_node(brain, "N1", "Test Node", (0.5, 0.5, 0.5, 0.5, 0.5, 0.5))

    # Create 5 events of type "file_write" → project_event_to_6d returns (0.3, 0.5, 0.4, 0.5, 0.3, 0.7)
    for i in range(5):
        eid = str(uuid.uuid4())
        _insert_cieu_event(cieu, eid, event_type="file_write", decision="allow")
        _insert_activation(brain, eid, "N1")

    # Run drift
    result = compute_node_centroid_drift(
        "N1", window_sec=86400, brain_conn=brain, cieu_conn=cieu
    )
    assert result is not None
    old_coords, new_coords = result

    # file_write projects to (0.3, 0.5, 0.4, 0.5, 0.3, 0.7)
    # EMA: new = 0.9 * 0.5 + 0.1 * fire_mean
    expected_fire_mean = (0.3, 0.5, 0.4, 0.5, 0.3, 0.7)
    for i in range(6):
        expected = (1 - LEARNING_RATE) * 0.5 + LEARNING_RATE * expected_fire_mean[i]
        assert abs(new_coords[i] - expected) < 1e-9, \
            f"dim[{i}]: expected {expected}, got {new_coords[i]}"

    # Key assertion: dim_y moved from 0.5 toward 0.3
    assert new_coords[0] < old_coords[0], "dim_y should decrease toward fire mean 0.3"

    # Now apply to DB and verify persistence
    apply_drift_to_all_nodes(brain_conn=brain, cieu_conn=cieu, window_sec=86400)
    row = brain.execute("SELECT dim_y FROM nodes WHERE id = 'N1'").fetchone()
    assert abs(row[0] - new_coords[0]) < 1e-9

    brain.close()
    cieu.close()


# ── Test 2: Centroid table created and populated ────────────────────────

def test_centroid_table_created_and_populated():
    brain = sqlite3.connect(":memory:")
    cieu = sqlite3.connect(":memory:")
    _create_brain_schema(brain)
    _create_cieu_schema(cieu)

    # Create node
    _insert_node(brain, "N1", "Node1", (0.5, 0.5, 0.5, 0.5, 0.5, 0.5))

    # Create events of two types
    for _ in range(3):
        eid = str(uuid.uuid4())
        _insert_cieu_event(cieu, eid, event_type="file_write")
        _insert_activation(brain, eid, "N1")

    for _ in range(2):
        eid = str(uuid.uuid4())
        _insert_cieu_event(cieu, eid, event_type="cmd_exec")
        _insert_activation(brain, eid, "N1")

    count = compute_event_type_coord_centroids(
        window_sec=86400, brain_conn=brain, cieu_conn=cieu
    )
    assert count >= 2, f"Expected >= 2 event types, got {count}"

    # Verify table exists and has rows
    rows = brain.execute("SELECT event_type, samples FROM event_type_coords").fetchall()
    types = {r[0]: r[1] for r in rows}
    assert "file_write" in types
    assert "cmd_exec" in types
    assert types["file_write"] >= 1

    brain.close()
    cieu.close()


# ── Test 3: Refined projection uses learned when available ──────────────

def test_refined_projection_uses_learned_when_available():
    brain = sqlite3.connect(":memory:")
    _create_brain_schema(brain)

    # Pre-seed event_type_coords with enough samples
    brain.execute("""
        CREATE TABLE IF NOT EXISTS event_type_coords (
            event_type TEXT PRIMARY KEY,
            dim_y REAL, dim_x REAL, dim_z REAL,
            dim_t REAL, dim_phi REAL, dim_c REAL,
            samples INTEGER, last_update REAL
        )
    """)
    brain.execute(
        """INSERT INTO event_type_coords VALUES
           ('test_event', 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 50, ?)""",
        (time.time(),),
    )
    brain.commit()

    event_row = {"event_type": "test_event", "event_id": "abc123"}
    result = refined_project_event_to_6d(event_row, brain_conn=brain)

    # Should be close to (0.9, 0.8, 0.7, 0.6, 0.5, 0.4) + small noise
    # The hand-rule for "test_event" would give default (0.3, 0.3, 0.3, 0.5, 0.3, 0.3)
    # so if learned path works, dim_y should be much closer to 0.9
    assert result[0] > 0.85, f"dim_y should be near 0.9 (learned), got {result[0]}"
    assert result[1] > 0.75, f"dim_x should be near 0.8 (learned), got {result[1]}"

    brain.close()


# ── Test 4: Refined projection falls back when undertrained ─────────────

def test_refined_projection_falls_back_when_undertrained():
    brain = sqlite3.connect(":memory:")
    _create_brain_schema(brain)

    # Pre-seed with samples < MIN_SAMPLES_FOR_LEARNED
    brain.execute("""
        CREATE TABLE IF NOT EXISTS event_type_coords (
            event_type TEXT PRIMARY KEY,
            dim_y REAL, dim_x REAL, dim_z REAL,
            dim_t REAL, dim_phi REAL, dim_c REAL,
            samples INTEGER, last_update REAL
        )
    """)
    brain.execute(
        """INSERT INTO event_type_coords VALUES
           ('file_write', 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 5, ?)""",
        (time.time(),),
    )
    brain.commit()

    event_row = {"event_type": "file_write", "event_id": "xyz"}
    result = refined_project_event_to_6d(event_row, brain_conn=brain)

    # Should fall back to hand-rule for file_write: (0.3, 0.5, 0.4, 0.5, 0.3, 0.7)
    hand_rule = project_event_to_6d(event_row)
    assert result == hand_rule, \
        f"Expected hand-rule fallback {hand_rule}, got {result}"

    brain.close()


# ── Test 5: Learning cycle emits CIEU event ─────────────────────────────

def test_learning_cycle_emits_cieu_event():
    brain = sqlite3.connect(":memory:")
    cieu = sqlite3.connect(":memory:")
    _create_brain_schema(brain)
    _create_cieu_schema(cieu)

    # Seed minimal data
    _insert_node(brain, "N1", "Node1", (0.5, 0.5, 0.5, 0.5, 0.5, 0.5))
    eid = str(uuid.uuid4())
    _insert_cieu_event(cieu, eid, event_type="file_write")
    _insert_activation(brain, eid, "N1")

    result = run_learning_cycle(
        brain_conn=brain, cieu_conn=cieu, window_sec=86400
    )

    assert "event_id" in result
    assert result["event_id"]  # non-empty

    # Verify CIEU event was written
    row = cieu.execute(
        "SELECT event_type FROM cieu_events WHERE event_id = ?",
        (result["event_id"],),
    ).fetchone()
    assert row is not None
    assert row[0] == "CIEU_BRAIN_LEARNING_CYCLE"

    # Verify drift ran
    assert "drift_summary" in result
    assert result["drift_summary"]["total"] >= 1

    # Verify centroid computation ran
    assert result["centroid_count"] >= 0

    brain.close()
    cieu.close()
