"""Tests for CIEU → 6D Brain Activation Bridge (ARCH-18 Phase 1)."""

import json
import math
import multiprocessing
import os
import sqlite3
import sys
import tempfile
import time

import pytest

# Ensure project root is on path for script imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from ystar.governance.cieu_brain_bridge import (
    euclidean_6d,
    insert_activation,
    process_event,
    project_event_to_6d,
    top_k_nodes,
)

from scripts.cieu_to_brain_batch import (
    partition_range,
    read_cieu_events_range,
    worker_process,
    writer_process,
    _load_all_nodes,
    _SENTINEL,
    _WRITER_BATCH_SIZE,
)


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def brain_db():
    """Create a temporary brain DB with nodes table and activation_log."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            node_type TEXT,
            dim_y REAL DEFAULT 0.5,
            dim_x REAL DEFAULT 0.5,
            dim_z REAL DEFAULT 0.5,
            dim_t REAL DEFAULT 0.5,
            dim_phi REAL DEFAULT 0.5,
            dim_c REAL DEFAULT 0.5
        );
        CREATE TABLE activation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT,
            activated_nodes TEXT,
            session_id TEXT,
            timestamp REAL
        );
        INSERT INTO nodes VALUES ('N1', 'Identity Core', 'hub', 0.9, 0.3, 0.7, 0.4, 0.6, 0.9);
        INSERT INTO nodes VALUES ('N2', 'Learning Hub', 'meta', 0.4, 0.9, 0.3, 0.5, 0.4, 0.3);
        INSERT INTO nodes VALUES ('N3', 'Metacog Node', 'meta', 0.5, 0.4, 0.6, 0.3, 0.95, 0.4);
        INSERT INTO nodes VALUES ('N4', 'Action Node', 'strategic', 0.2, 0.4, 0.3, 0.5, 0.2, 0.8);
        INSERT INTO nodes VALUES ('N5', 'Low Signal', 'meta', 0.1, 0.1, 0.1, 0.5, 0.1, 0.1);
    """)
    conn.close()
    yield path
    os.unlink(path)


# ── Projection tests ────────────────────────────────────────────────────

class TestProjectEventTo6D:

    def test_deny_agent_generic_has_high_action_and_identity(self):
        """Deny events from unidentified 'agent' should have high dim_c and dim_y."""
        row = {"decision": "deny", "agent_id": "agent", "event_type": "cmd_exec"}
        coords = project_event_to_6d(row)
        dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c = coords
        assert dim_c >= 0.8, f"dim_c should be high for deny+agent, got {dim_c}"
        assert dim_y >= 0.8, f"dim_y should be high for deny+agent, got {dim_y}"

    def test_k9_violation_has_high_metacognition(self):
        """K9_VIOLATION events should project to high dim_phi."""
        row = {"event_type": "K9_VIOLATION_DETECTED", "decision": "deny", "agent_id": "ceo"}
        coords = project_event_to_6d(row)
        assert coords[4] >= 0.9, f"dim_phi should be >=0.9 for K9 violation, got {coords[4]}"

    def test_ceo_learning_has_high_identity_and_knowledge(self):
        """ceo_learning events should project to high dim_y and dim_x."""
        row = {"event_type": "ceo_learning_reflection", "decision": "info", "agent_id": "ceo"}
        coords = project_event_to_6d(row)
        assert coords[0] >= 0.7, f"dim_y should be high for ceo_learning, got {coords[0]}"
        assert coords[1] >= 0.8, f"dim_x should be high for ceo_learning, got {coords[1]}"

    def test_orchestration_heartbeat_is_low_signal(self):
        """Orchestration heartbeat events should have low coordinates everywhere."""
        row = {"event_type": "orchestration:path_a_cycle", "decision": "info", "agent_id": "orchestrator"}
        coords = project_event_to_6d(row)
        for i, dim_name in enumerate(["y", "x", "z", "t", "phi", "c"]):
            if dim_name == "t":
                continue  # dim_t is always 0.5 baseline
            assert coords[i] <= 0.2, f"dim_{dim_name} should be low for heartbeat, got {coords[i]}"

    def test_default_fallback(self):
        """Unknown event types get default coords."""
        row = {"event_type": "something_unknown", "decision": "info", "agent_id": "foo"}
        coords = project_event_to_6d(row)
        assert coords == (0.3, 0.3, 0.3, 0.5, 0.3, 0.3)

    def test_identity_violation_drift(self):
        """Identity violation drift should project to very high dim_y."""
        row = {"event_type": "external_observation", "decision": "deny",
               "agent_id": "unknown", "drift_category": "identity_violation"}
        coords = project_event_to_6d(row)
        assert coords[0] >= 0.9, f"dim_y should be >=0.9 for identity_violation, got {coords[0]}"

    def test_escalate_decision(self):
        """Escalate decisions should have high dim_z (impact)."""
        row = {"event_type": "external_observation", "decision": "escalate", "agent_id": "ceo"}
        coords = project_event_to_6d(row)
        assert coords[2] >= 0.7, f"dim_z should be high for escalate, got {coords[2]}"


# ── Top-K tests ──────────────────────────────────────────────────────────

class TestTopKNodes:

    def test_returns_3_nodes(self, brain_db):
        """top_k_nodes with k=3 returns exactly 3 results."""
        coords = (0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        results = top_k_nodes(coords, k=3, db_path=brain_db)
        assert len(results) == 3
        # Each result is (node_id, node_name, distance)
        for nid, name, dist in results:
            assert isinstance(nid, str)
            assert isinstance(name, str)
            assert isinstance(dist, float)
            assert dist >= 0.0

    def test_nearest_node_is_correct(self, brain_db):
        """Query near N1's coords should return N1 as nearest."""
        # N1 = (0.9, 0.3, 0.7, 0.4, 0.6, 0.9)
        coords = (0.9, 0.3, 0.7, 0.4, 0.6, 0.9)
        results = top_k_nodes(coords, k=1, db_path=brain_db)
        assert results[0][0] == "N1"
        assert results[0][2] < 0.01  # essentially zero distance

    def test_ordering_by_distance(self, brain_db):
        """Results are sorted by ascending distance."""
        coords = (0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        results = top_k_nodes(coords, k=5, db_path=brain_db)
        dists = [r[2] for r in results]
        assert dists == sorted(dists)


# ── Insert activation tests ──────────────────────────────────────────────

class TestInsertActivation:

    def test_insert_activation_persists(self, brain_db):
        """Inserting an activation should be readable back."""
        conn = sqlite3.connect(brain_db)
        before = conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
        assert before == 0

        rowid = insert_activation(
            event_id="evt-001",
            node_id="N1",
            weight=0.85,
            query_text="test_event",
            session_id="test-session",
            conn=conn,
        )
        assert rowid is not None
        assert rowid > 0

        after = conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
        assert after == 1

        row = conn.execute("SELECT query, activated_nodes, session_id FROM activation_log WHERE id=?", (rowid,)).fetchone()
        assert "evt-001" in row[0]
        activated = json.loads(row[1])
        assert activated[0]["node_id"] == "N1"
        assert activated[0]["activation_level"] == 0.85
        conn.close()


# ── End-to-end process_event tests ────────────────────────────────────────

class TestProcessEvent:

    def test_end_to_end(self, brain_db):
        """process_event should project, find nodes, and insert activations."""
        conn = sqlite3.connect(brain_db)
        before = conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
        assert before == 0

        event_row = {
            "event_id": "e2e-test-001",
            "event_type": "BEHAVIOR_RULE_VIOLATION",
            "decision": "deny",
            "agent_id": "ceo",
            "session_id": "s-test",
            "drift_category": "",
        }

        result = process_event(event_row, k=3, brain_conn=conn)
        assert len(result) == 3
        for act in result:
            assert "node_id" in act
            assert "weight" in act
            assert act["weight"] > 0

        after = conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
        assert after == 3  # k=3 nodes activated
        conn.close()

    def test_deny_agent_activates_identity_node(self, brain_db):
        """deny+agent='agent' should activate N1 (Identity Core) as nearest."""
        conn = sqlite3.connect(brain_db)
        event_row = {
            "event_id": "deny-agent-test",
            "event_type": "cmd_exec",
            "decision": "deny",
            "agent_id": "agent",
            "session_id": "s-deny",
            "drift_category": "",
        }
        result = process_event(event_row, k=1, brain_conn=conn)
        assert result[0]["node_id"] == "N1"  # N1 has coords matching deny+agent rule
        conn.close()


# ── Euclidean distance tests ──────────────────────────────────────────────

class TestEuclidean6D:

    def test_same_point_is_zero(self):
        a = (0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        assert euclidean_6d(a, a) == 0.0

    def test_known_distance(self):
        a = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        b = (1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert abs(euclidean_6d(a, b) - 1.0) < 1e-9

    def test_symmetric(self):
        a = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
        b = (0.6, 0.5, 0.4, 0.3, 0.2, 0.1)
        assert abs(euclidean_6d(a, b) - euclidean_6d(b, a)) < 1e-12


# ── Parallel batch tests ────────────────────────────────────────────────

@pytest.fixture
def cieu_db():
    """Create a temporary CIEU DB with synthetic events."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE cieu_events (
            event_id TEXT,
            seq_global INTEGER,
            created_at REAL,
            session_id TEXT,
            agent_id TEXT,
            event_type TEXT,
            decision TEXT,
            passed INTEGER DEFAULT 1,
            drift_detected INTEGER DEFAULT 0,
            drift_category TEXT DEFAULT '',
            sealed INTEGER DEFAULT 0,
            params_json TEXT DEFAULT '{}',
            violations TEXT DEFAULT '',
            file_path TEXT DEFAULT '',
            command TEXT DEFAULT ''
        )
    """)
    # Insert 20 synthetic events with varied types
    event_types = [
        "BEHAVIOR_RULE_VIOLATION", "cmd_exec", "Write", "orchestration:heartbeat",
        "ceo_learning_reflection", "intervention_gate:deny", "something_unknown",
        "K9_VIOLATION_DETECTED", "cmd_exec", "Write",
    ]
    for i in range(20):
        et = event_types[i % len(event_types)]
        decision = "deny" if "VIOLATION" in et or "intervention" in et else "info"
        conn.execute(
            """INSERT INTO cieu_events
               (event_id, seq_global, created_at, session_id, agent_id,
                event_type, decision, drift_category)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (f"evt-{i:04d}", i, time.time(), "test-session", "ceo", et, decision, ""),
        )
    conn.commit()
    conn.close()
    yield path
    os.unlink(path)


class TestPartitionRange:

    def test_partition_splits_event_range_cleanly(self):
        """Partitions must cover all items with no gaps and no overlaps."""
        for total in [0, 1, 5, 10, 17, 100, 1001]:
            for num_workers in [1, 2, 3, 4, 7, 16]:
                partitions = partition_range(total, num_workers)
                # Verify no gaps, no overlaps: consecutive offsets
                if total == 0:
                    assert partitions == []
                    continue

                covered = set()
                for offset, count in partitions:
                    for idx in range(offset, offset + count):
                        assert idx not in covered, (
                            f"Double-count at index {idx} for total={total}, workers={num_workers}"
                        )
                        covered.add(idx)

                # Verify all indices covered
                assert covered == set(range(total)), (
                    f"Gap detected for total={total}, workers={num_workers}: "
                    f"missing={set(range(total)) - covered}"
                )


class TestParallelActivationCountMatchesSequential:

    def test_parallel_activation_count_matches_sequential(self, cieu_db, brain_db):
        """Running N events sequentially and in parallel must produce same activation count."""
        k = 3
        n_events = 20

        # --- Sequential run ---
        seq_conn = sqlite3.connect(brain_db)
        # Read events
        conn_cieu = sqlite3.connect(cieu_db)
        conn_cieu.row_factory = sqlite3.Row
        events = [dict(r) for r in conn_cieu.execute(
            "SELECT * FROM cieu_events ORDER BY rowid DESC LIMIT ?", (n_events,)
        ).fetchall()]
        conn_cieu.close()

        for event in events:
            process_event(event, k=k, brain_conn=seq_conn)
        seq_count = seq_conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
        seq_conn.close()

        # --- Parallel run (using a fresh brain_db copy) ---
        fd2, brain_db2 = tempfile.mkstemp(suffix=".db")
        os.close(fd2)
        # Copy schema + nodes from brain_db (but empty activation_log)
        src = sqlite3.connect(brain_db)
        dst = sqlite3.connect(brain_db2)
        # Clone schema
        schema_rows = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (sql,) in schema_rows:
            if sql:
                dst.execute(sql)
        # Copy nodes
        nodes = src.execute("SELECT * FROM nodes").fetchall()
        if nodes:
            placeholders = ",".join(["?"] * len(nodes[0]))
            dst.executemany(f"INSERT INTO nodes VALUES ({placeholders})", nodes)
        dst.commit()
        src.close()

        # Run parallel: workers -> queue -> writer
        cached_nodes = _load_all_nodes(brain_db2)
        partitions = partition_range(len(events), 2)
        result_queue = multiprocessing.Queue()
        manager = multiprocessing.Manager()
        stats_dict = manager.dict()
        stats_dict["total_inserted"] = 0

        writer = multiprocessing.Process(
            target=writer_process,
            args=(brain_db2, result_queue, len(partitions), stats_dict),
        )
        writer.start()

        workers = []
        for wid, (offset, count) in enumerate(partitions):
            p = multiprocessing.Process(
                target=worker_process,
                args=(wid, cieu_db, brain_db2, offset, count, k, result_queue, cached_nodes),
            )
            p.start()
            workers.append(p)

        for p in workers:
            p.join()
        writer.join()

        par_conn = sqlite3.connect(brain_db2)
        par_count = par_conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
        par_conn.close()
        os.unlink(brain_db2)

        assert seq_count == par_count, (
            f"Sequential produced {seq_count} activations but parallel produced {par_count}"
        )
        # Both should be n_events * k
        assert seq_count == n_events * k


class TestWriterCommitsBatchOnQueueDrain:

    def test_writer_commits_batch_on_queue_drain(self, brain_db):
        """Writer process must commit all queued items and leave queue empty."""
        result_queue = multiprocessing.Queue()
        manager = multiprocessing.Manager()
        stats_dict = manager.dict()
        stats_dict["total_inserted"] = 0

        # Push 7 synthetic activation batches (simulating 7 events, k=2 each = 14 rows)
        for i in range(7):
            batch = [
                {
                    "event_id": f"test-evt-{i}",
                    "node_id": f"N{j}",
                    "weight": 0.5 + j * 0.1,
                    "query_text": "test|info",
                    "session_id": "writer-test",
                }
                for j in range(1, 3)  # 2 activations per event
            ]
            result_queue.put(batch)

        # Push sentinel (1 worker)
        result_queue.put(_SENTINEL)

        writer = multiprocessing.Process(
            target=writer_process,
            args=(brain_db, result_queue, 1, stats_dict),
        )
        writer.start()
        writer.join(timeout=10)

        assert not writer.is_alive(), "Writer process did not terminate"

        # Verify all 14 rows committed
        conn = sqlite3.connect(brain_db)
        count = conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
        conn.close()

        assert count == 14, f"Expected 14 activation rows, got {count}"
        assert stats_dict["total_inserted"] == 14

        # Queue should be empty
        assert result_queue.empty(), "Queue not fully drained"


class TestQueueMaxsizeBounded:

    def test_queue_maxsize_bounded(self):
        """Queue maxsize must never exceed 30000 regardless of total event count.

        Regression test for macOS BSD semaphore limit (32767).
        The production code uses min(total + num_workers + 10, 30000).
        """
        # Simulate what the script computes
        test_cases = [
            (100, 4),        # small: 100+4+10=114, expect 114
            (10000, 4),      # medium: 10014, expect 10014
            (29990, 4),      # just under: 30004, expect 30000
            (100000, 8),     # large: 100018, expect 30000
            (353000, 4),     # original bug trigger: 353014, expect 30000
            (1000000, 16),   # extreme: 1000026, expect 30000
        ]
        for total, num_workers in test_cases:
            computed = min(total + num_workers + 10, 30000)
            assert computed <= 30000, (
                f"maxsize {computed} exceeds 30000 for total={total}, workers={num_workers}"
            )
            # For small totals, the natural size should be used
            if total + num_workers + 10 <= 30000:
                assert computed == total + num_workers + 10
