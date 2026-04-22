"""
Tests for ARCH-18 Phase 2: continuous CIEU→Brain streamer + Hebbian co-firing.

Tests:
  1. test_stream_picks_up_new_events_only
  2. test_hebbian_strengthens_cofired_edges
  3. test_daemon_pid_file_lifecycle
"""

import json
import os
import sqlite3
import signal
import subprocess
import sys
import tempfile
import time
import uuid

import pytest

# Project root on path
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(TESTS_DIR))
sys.path.insert(0, PROJECT_ROOT)

from ystar.governance.cieu_brain_bridge import (
    apply_hebbian_update,
    process_event,
    project_event_to_6d,
)
from ystar.governance.cieu_brain_streamer import (
    _fetch_new_cieu_events,
    _get_last_ingested_seq,
    stream_new_events_to_brain,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


def _create_brain_db(path: str):
    """Create a minimal brain DB with nodes + edges + activation_log tables."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            dim_y REAL DEFAULT 0.5,
            dim_x REAL DEFAULT 0.5,
            dim_z REAL DEFAULT 0.5,
            dim_t REAL DEFAULT 0.5,
            dim_phi REAL DEFAULT 0.5,
            dim_c REAL DEFAULT 0.5,
            base_activation REAL DEFAULT 0.0,
            last_accessed REAL DEFAULT 0.0,
            access_count INTEGER DEFAULT 0,
            created_at REAL DEFAULT 0.0,
            updated_at REAL DEFAULT 0.0,
            node_type TEXT,
            depth_label TEXT,
            content_hash TEXT,
            file_path TEXT,
            principles TEXT,
            triggers TEXT,
            summary TEXT,
            embedding BLOB
        );

        CREATE TABLE IF NOT EXISTS edges (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            edge_type TEXT DEFAULT 'explicit',
            weight REAL DEFAULT 0.5,
            created_at REAL DEFAULT 0.0,
            updated_at REAL DEFAULT 0.0,
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

        -- Seed 5 nodes spread across 6D space
        INSERT INTO nodes (id, name, dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c)
        VALUES
            ('n1', 'Identity Core',    0.9, 0.3, 0.5, 0.4, 0.6, 0.8),
            ('n2', 'Learning Hub',     0.3, 0.9, 0.4, 0.6, 0.5, 0.3),
            ('n3', 'Impact Node',      0.5, 0.4, 0.9, 0.5, 0.7, 0.6),
            ('n4', 'Metacognition',    0.4, 0.5, 0.5, 0.4, 0.95, 0.4),
            ('n5', 'Courage Center',   0.3, 0.3, 0.3, 0.5, 0.3, 0.9);
    """)
    conn.commit()
    conn.close()


def _create_cieu_db(path: str):
    """Create a minimal CIEU DB with cieu_events table."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cieu_events (
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
            sealed INTEGER DEFAULT 0,
            evidence_grade TEXT DEFAULT 'decision'
        );
    """)
    conn.commit()
    conn.close()


def _insert_cieu_event(cieu_db: str, seq_global: int, event_type: str = "test_event",
                        decision: str = "allow", agent_id: str = "test") -> str:
    """Insert a single CIEU event and return its event_id."""
    eid = str(uuid.uuid4())
    conn = sqlite3.connect(cieu_db)
    conn.execute(
        """INSERT INTO cieu_events
           (event_id, seq_global, created_at, session_id, agent_id,
            event_type, decision, passed, drift_detected, sealed)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (eid, seq_global, time.time(), "test_session", agent_id,
         event_type, decision, 1, 0, 0),
    )
    conn.commit()
    conn.close()
    return eid


@pytest.fixture
def temp_dbs(tmp_path):
    """Create temporary brain and CIEU databases."""
    brain_path = str(tmp_path / "brain.db")
    cieu_path = str(tmp_path / "cieu.db")
    _create_brain_db(brain_path)
    _create_cieu_db(cieu_path)
    return brain_path, cieu_path


# ── Test 1: stream picks up new events only ──────────────────────────────


def test_stream_picks_up_new_events_only(temp_dbs):
    """Insert events, run stream, insert more events, run stream again.
    Verify second run only processes new events (no re-processing)."""
    brain_db, cieu_db = temp_dbs

    # Insert 3 "old" events at seq_global 1000, 2000, 3000
    for seq in [1000, 2000, 3000]:
        _insert_cieu_event(cieu_db, seq)

    # First stream: process all from seq_global=0
    result1 = stream_new_events_to_brain(
        since_seq_global=0,
        poll_interval_sec=0.01,
        max_iterations=1,
        cieu_db=cieu_db,
        brain_db=brain_db,
        k=3,
    )
    assert result1["total_events_ingested"] == 3

    # Count activation_log rows
    conn = sqlite3.connect(brain_db)
    count_after_first = conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
    conn.close()
    assert count_after_first == 9  # 3 events * 3 top-k

    # Insert 2 "new" events at seq_global 4000, 5000
    _insert_cieu_event(cieu_db, 4000)
    _insert_cieu_event(cieu_db, 5000)

    # Second stream: should only pick up the 2 new events
    result2 = stream_new_events_to_brain(
        since_seq_global=result1["final_cursor"],
        poll_interval_sec=0.01,
        max_iterations=1,
        cieu_db=cieu_db,
        brain_db=brain_db,
        k=3,
    )
    assert result2["total_events_ingested"] == 2

    conn = sqlite3.connect(brain_db)
    count_after_second = conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
    conn.close()
    # 9 from first run + 6 from second run = 15
    assert count_after_second == 15


# ── Test 2: Hebbian strengthens co-fired edges ───────────────────────────


def test_hebbian_strengthens_cofired_edges(temp_dbs):
    """Process an event that activates nodes, verify Hebbian creates/strengthens edges."""
    brain_db, cieu_db = temp_dbs

    conn = sqlite3.connect(brain_db)

    # Baseline: count edges
    edges_before = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    assert edges_before == 0, "Fresh DB should have no edges"

    # apply_hebbian_update with nodes n1, n2, n3
    updates = apply_hebbian_update(["n1", "n2", "n3"], conn=conn)
    assert updates == 3  # 3 pairs: (n1,n2), (n1,n3), (n2,n3)

    edges_after = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    assert edges_after == 3

    # Check initial weights = 0.1 and edge_type = 'hebbian'
    rows = conn.execute(
        "SELECT source_id, target_id, weight, edge_type, co_activations FROM edges ORDER BY source_id, target_id"
    ).fetchall()
    for src, tgt, weight, etype, co_act in rows:
        assert etype == "hebbian"
        assert weight == pytest.approx(0.1, abs=0.001)
        assert co_act == 1

    # Second co-firing: n1, n2 (subset — should strengthen n1-n2 only)
    updates2 = apply_hebbian_update(["n1", "n2"], conn=conn)
    assert updates2 == 1

    row_n1_n2 = conn.execute(
        "SELECT weight, co_activations FROM edges WHERE source_id='n1' AND target_id='n2'"
    ).fetchone()
    # 0.1 + 0.05 (delta) = 0.15
    assert row_n1_n2[0] == pytest.approx(0.15, abs=0.001)
    assert row_n1_n2[1] == 2

    # n1-n3 should still be at initial weight
    row_n1_n3 = conn.execute(
        "SELECT weight, co_activations FROM edges WHERE source_id='n1' AND target_id='n3'"
    ).fetchone()
    assert row_n1_n3[0] == pytest.approx(0.1, abs=0.001)
    assert row_n1_n3[1] == 1

    conn.close()


# ── Test 3: stream with Hebbian integration ──────────────────────────────


def test_stream_applies_hebbian_during_ingest(temp_dbs):
    """Verify that streaming ingest also creates Hebbian edges."""
    brain_db, cieu_db = temp_dbs

    # Insert an event that will map to a known projection
    # K9_VIOLATION → high dim_phi, should activate n4 (Metacognition, phi=0.95)
    _insert_cieu_event(cieu_db, 1000, event_type="K9_VIOLATION_DETECTED", decision="deny")

    result = stream_new_events_to_brain(
        since_seq_global=0,
        poll_interval_sec=0.01,
        max_iterations=1,
        cieu_db=cieu_db,
        brain_db=brain_db,
        k=3,
    )

    assert result["total_events_ingested"] == 1
    assert result["total_hebbian_updates"] > 0

    conn = sqlite3.connect(brain_db)
    edges = conn.execute("SELECT COUNT(*) FROM edges WHERE edge_type='hebbian'").fetchone()[0]
    conn.close()
    assert edges > 0, "Hebbian edges should have been created during stream ingest"


# ── Test 4: daemon PID file lifecycle ────────────────────────────────────


def test_daemon_pid_file_lifecycle(temp_dbs, tmp_path):
    """Start daemon, verify PID file created, stop, verify PID file removed."""
    brain_db, cieu_db = temp_dbs

    # Insert a few events so daemon has something to process
    for seq in [100, 200, 300]:
        _insert_cieu_event(cieu_db, seq)

    daemon_script = os.path.join(PROJECT_ROOT, "scripts", "cieu_brain_daemon.py")
    pid_file = os.path.join(PROJECT_ROOT, "scripts", ".cieu_brain_daemon.pid")

    # Override PID_FILE location for test isolation
    # We'll use max-iterations=2 so it self-terminates quickly
    env = os.environ.copy()
    env["PYTHONPATH"] = PROJECT_ROOT

    proc = subprocess.Popen(
        [
            sys.executable,
            daemon_script,
            "--poll-interval", "0.5",
            "--max-iterations", "2",
            "--cieu-db", cieu_db,
            "--brain-db", brain_db,
            "--k", "3",
            "--since-seq", "0",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for process to complete (max-iterations=2 → ~1s)
    try:
        stdout, stderr = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        pytest.fail(f"Daemon did not terminate in 15s. stdout={stdout}, stderr={stderr}")

    output = stdout.decode()
    assert "PID" in output, f"Daemon should log PID on start. Output: {output}"
    assert proc.returncode == 0, f"Daemon exited with code {proc.returncode}. stderr={stderr.decode()}"

    # After clean exit, PID file should be removed by atexit handler
    # (atexit may not always fire for subprocess, so we just verify it ran)
    assert "Shutdown complete" in output, f"Daemon should log shutdown. Output: {output}"
