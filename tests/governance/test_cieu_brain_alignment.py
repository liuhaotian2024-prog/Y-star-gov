"""
Tests for ystar.governance.cieu_brain_alignment module.

Uses in-memory SQLite databases to avoid touching production data.
"""

import json
import sqlite3
import tempfile
import time
import os

import pytest

from ystar.governance.cieu_brain_alignment import (
    ensure_table,
    populate_links_from_activation_history,
    compute_functional_completeness,
    align_weakest_link_audit,
)


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def brain_db(tmp_path):
    """Create a temporary brain database with nodes + activation_log."""
    db_path = str(tmp_path / "brain.db")
    conn = sqlite3.connect(db_path)
    # Create nodes table (simplified)
    conn.execute("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            node_type TEXT
        )
    """)
    # Insert test nodes
    conn.executemany(
        "INSERT INTO nodes (id, name, node_type) VALUES (?, ?, ?)",
        [
            ("team/ceo", "CEO Node", "ecosystem_team"),
            ("team/cto", "CTO Node", "ecosystem_team"),
            ("strategic/vision", "Vision Node", "strategic"),
            ("meta/learning", "Learning Node", "meta"),
        ],
    )
    # Create activation_log table
    conn.execute("""
        CREATE TABLE activation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT,
            activated_nodes TEXT,
            session_id TEXT,
            timestamp REAL
        )
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def cieu_db(tmp_path):
    """Create a temporary CIEU database with cieu_events."""
    db_path = str(tmp_path / "cieu.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE cieu_events (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            seq_global INTEGER NOT NULL,
            created_at REAL NOT NULL,
            session_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            decision TEXT NOT NULL,
            passed INTEGER NOT NULL DEFAULT 0,
            violations TEXT,
            drift_detected INTEGER NOT NULL DEFAULT 0,
            drift_details TEXT,
            drift_category TEXT,
            file_path TEXT,
            command TEXT,
            url TEXT,
            skill_name TEXT,
            skill_source TEXT,
            task_description TEXT,
            contract_hash TEXT,
            chain_depth INTEGER DEFAULT 0,
            params_json TEXT,
            result_json TEXT,
            human_initiator TEXT,
            lineage_path TEXT,
            sealed INTEGER NOT NULL DEFAULT 0,
            evidence_grade TEXT DEFAULT 'decision'
        )
    """)
    conn.commit()
    conn.close()
    return db_path


def _insert_cieu_event(db_path, event_id, event_type, created_at=None):
    """Helper: insert a CIEU event."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO cieu_events (event_id, seq_global, created_at, session_id, "
        "agent_id, event_type, decision, passed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id,
            int((created_at or time.time()) * 1e6),
            created_at or time.time(),
            "test-session",
            "test-agent",
            event_type,
            "allow",
            1,
        ),
    )
    conn.commit()
    conn.close()


def _insert_activation(db_path, event_id, node_id, activation_level=0.75, timestamp=None):
    """Helper: insert an activation_log entry."""
    conn = sqlite3.connect(db_path)
    activated = json.dumps([{"node_id": node_id, "activation_level": activation_level}])
    conn.execute(
        "INSERT INTO activation_log (query, activated_nodes, session_id, timestamp) "
        "VALUES (?, ?, ?, ?)",
        (f"cieu_event:{event_id}", activated, "test-session", timestamp or time.time()),
    )
    conn.commit()
    conn.close()


# ── Tests ──────────────────────────────────────────────────────────────

def test_table_created(brain_db):
    """ensure_table is idempotent and creates if missing."""
    conn = sqlite3.connect(brain_db)
    # Table should not exist yet
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='mission_behavior_links'"
    ).fetchall()
    assert len(tables) == 0

    # First call: creates
    ensure_table(conn)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='mission_behavior_links'"
    ).fetchall()
    assert len(tables) == 1

    # Second call: idempotent, no error
    ensure_table(conn)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='mission_behavior_links'"
    ).fetchall()
    assert len(tables) == 1

    conn.close()


def test_populate_from_activation_log(brain_db, cieu_db):
    """Verify that activation_log entries produce expected links."""
    now = time.time()

    # Insert CIEU events
    _insert_cieu_event(cieu_db, "evt-001", "file_write", created_at=now - 100)
    _insert_cieu_event(cieu_db, "evt-002", "K9_VIOLATION_DETECTED", created_at=now - 200)
    _insert_cieu_event(cieu_db, "evt-003", "file_write", created_at=now - 300)

    # Insert activations: evt-001 activated team/ceo, evt-002 activated team/ceo + team/cto
    _insert_activation(brain_db, "evt-001", "team/ceo", timestamp=now - 100)
    _insert_activation(brain_db, "evt-002", "team/ceo", timestamp=now - 200)
    _insert_activation(brain_db, "evt-002", "team/cto", timestamp=now - 200)
    _insert_activation(brain_db, "evt-003", "team/ceo", timestamp=now - 300)

    count = populate_links_from_activation_history(brain_db, cieu_db, window_sec=0)
    assert count == 3  # (ceo, file_write), (ceo, K9_VIOLATION_DETECTED), (cto, K9_VIOLATION_DETECTED)

    conn = sqlite3.connect(brain_db)
    rows = conn.execute(
        "SELECT mission_node_id, cieu_event_type, sample_count "
        "FROM mission_behavior_links ORDER BY mission_node_id, cieu_event_type"
    ).fetchall()
    conn.close()

    assert len(rows) == 3
    # team/ceo + K9_VIOLATION_DETECTED: 1 activation
    assert rows[0] == ("team/ceo", "K9_VIOLATION_DETECTED", 1)
    # team/ceo + file_write: 2 activations (evt-001 + evt-003)
    assert rows[1] == ("team/ceo", "file_write", 2)
    # team/cto + K9_VIOLATION_DETECTED: 1 activation
    assert rows[2] == ("team/cto", "K9_VIOLATION_DETECTED", 1)


def test_functional_completeness_all_fired(brain_db, cieu_db):
    """fit_score = 1.0 when all required event types fired recently."""
    now = time.time()

    # Manually insert links
    conn = sqlite3.connect(brain_db)
    ensure_table(conn)
    conn.execute(
        "INSERT INTO mission_behavior_links (mission_node_id, cieu_event_type, alignment_weight, sample_count) "
        "VALUES ('team/ceo', 'file_write', 0.5, 10)"
    )
    conn.execute(
        "INSERT INTO mission_behavior_links (mission_node_id, cieu_event_type, alignment_weight, sample_count) "
        "VALUES ('team/ceo', 'cmd_exec', 0.5, 5)"
    )
    conn.commit()
    conn.close()

    # Insert CIEU events for both types within the window
    _insert_cieu_event(cieu_db, "e1", "file_write", created_at=now - 100)
    _insert_cieu_event(cieu_db, "e2", "cmd_exec", created_at=now - 200)

    fit = compute_functional_completeness(brain_db, cieu_db, "team/ceo", window_sec=86400)
    assert fit == 1.0


def test_functional_completeness_some_missing(brain_db, cieu_db):
    """fit_score < 1.0 when some required event types did not fire."""
    now = time.time()

    # Insert 3 required links
    conn = sqlite3.connect(brain_db)
    ensure_table(conn)
    conn.execute(
        "INSERT INTO mission_behavior_links (mission_node_id, cieu_event_type, alignment_weight, sample_count) "
        "VALUES ('team/ceo', 'file_write', 0.5, 10)"
    )
    conn.execute(
        "INSERT INTO mission_behavior_links (mission_node_id, cieu_event_type, alignment_weight, sample_count) "
        "VALUES ('team/ceo', 'cmd_exec', 0.5, 5)"
    )
    conn.execute(
        "INSERT INTO mission_behavior_links (mission_node_id, cieu_event_type, alignment_weight, sample_count) "
        "VALUES ('team/ceo', 'K9_VIOLATION_DETECTED', 0.5, 3)"
    )
    conn.commit()
    conn.close()

    # Only file_write fired recently
    _insert_cieu_event(cieu_db, "e1", "file_write", created_at=now - 100)

    fit = compute_functional_completeness(brain_db, cieu_db, "team/ceo", window_sec=86400)
    assert fit == pytest.approx(1.0 / 3.0)


def test_weakest_link_returns_min_firing_type(brain_db, cieu_db):
    """align_weakest_link_audit returns the event type with lowest firing count."""
    now = time.time()

    # Insert links
    conn = sqlite3.connect(brain_db)
    ensure_table(conn)
    conn.execute(
        "INSERT INTO mission_behavior_links (mission_node_id, cieu_event_type, alignment_weight, sample_count, last_fired) "
        "VALUES ('team/ceo', 'file_write', 0.5, 10, ?)", (now - 100,)
    )
    conn.execute(
        "INSERT INTO mission_behavior_links (mission_node_id, cieu_event_type, alignment_weight, sample_count, last_fired) "
        "VALUES ('team/ceo', 'cmd_exec', 0.5, 5, ?)", (now - 200,)
    )
    conn.execute(
        "INSERT INTO mission_behavior_links (mission_node_id, cieu_event_type, alignment_weight, sample_count, last_fired) "
        "VALUES ('team/ceo', 'K9_VIOLATION_DETECTED', 0.5, 3, ?)", (now - 300,)
    )
    conn.commit()
    conn.close()

    # file_write: 3 events, cmd_exec: 1 event, K9_VIOLATION: 0 events
    _insert_cieu_event(cieu_db, "e1", "file_write", created_at=now - 10)
    _insert_cieu_event(cieu_db, "e2", "file_write", created_at=now - 20)
    _insert_cieu_event(cieu_db, "e3", "file_write", created_at=now - 30)
    _insert_cieu_event(cieu_db, "e4", "cmd_exec", created_at=now - 50)

    result = align_weakest_link_audit(brain_db, cieu_db, "team/ceo", window_sec=86400)
    assert result is not None
    assert result["event_type"] == "K9_VIOLATION_DETECTED"
    assert result["firing_count"] == 0
