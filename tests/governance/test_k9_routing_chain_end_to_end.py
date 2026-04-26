#!/usr/bin/env python3
"""
K9 Routing Chain End-to-End Tests
Board 2026-04-16 P0: Test Pattern B event-driven routing chain.

Tests:
1. Subscriber daemon start/stop
2. Handler dispatch correctness (6 handlers)
3. Smoke cascade (emit fake violation → verify handler event emitted)
4. Missing routing_target graceful skip
5. Multiple handlers parallel dispatch
6. State persistence (last_seq tracking)
"""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

# Path setup
REPO_ROOT = Path(__file__).parent.parent.parent
COMPANY_ROOT = REPO_ROOT.parent / "ystar-company"
CIEU_DB = COMPANY_ROOT / ".ystar_cieu.db"
STATE_FILE = COMPANY_ROOT / ".k9_subscriber_state.json"
PID_FILE = Path("/tmp/k9_subscriber.pid")
SUBSCRIBER_SCRIPT = REPO_ROOT / "ystar" / "governance" / "k9_routing_subscriber.py"

# Add company scripts to path for CIEU helpers
sys.path.insert(0, str(COMPANY_ROOT / "scripts"))


# ═══ FIXTURES ═══

@pytest.fixture(scope="function")
def clean_state():
    """Clean up subscriber state before/after each test."""
    # Cleanup before
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text())
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
        except Exception:
            pass
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass

    if STATE_FILE.exists():
        STATE_FILE.unlink()

    yield

    # Cleanup after
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text())
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
        except Exception:
            pass
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass

    if STATE_FILE.exists():
        try:
            STATE_FILE.unlink()
        except FileNotFoundError:
            pass


@pytest.fixture(scope="function")
def cieu_conn():
    """Return CIEU database connection."""
    if not CIEU_DB.exists():
        pytest.skip("CIEU DB not found")

    conn = sqlite3.connect(str(CIEU_DB), timeout=5.0)
    yield conn
    conn.close()


# ═══ HELPER FUNCTIONS ═══

def emit_fake_violation(routing_target: str, action: str, violation_type: str) -> int:
    """
    Emit fake K9_VIOLATION_DETECTED event to CIEU DB.

    Returns:
        int: seq_global of emitted event
    """
    conn = sqlite3.connect(str(CIEU_DB), timeout=5.0)
    cursor = conn.cursor()

    # Get next seq_global
    cursor.execute("SELECT COALESCE(MAX(seq_global), 0) + 1 FROM cieu_events")
    seq_global = cursor.fetchone()[0]

    payload = {
        "routing_target": routing_target,
        "action": action,
        "violation_type": violation_type,
        "agent_id": "test_agent",
        "event_type": "TEST_EVENT",
    }

    cursor.execute(
        """
        INSERT INTO cieu_events (
            event_id, seq_global, created_at, session_id, agent_id,
            event_type, decision, passed, task_description
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            seq_global,
            time.time(),
            "test_session",
            "test_agent",
            "K9_VIOLATION_DETECTED",
            "warn",
            0,
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()

    return seq_global


def get_cieu_events_after_seq(seq_global: int, event_type: str) -> list:
    """
    Fetch CIEU events with event_type after seq_global.

    Returns:
        list: List of event dicts
    """
    conn = sqlite3.connect(str(CIEU_DB), timeout=5.0)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT seq_global, event_id, event_type, agent_id, task_description
        FROM cieu_events
        WHERE event_type = ?
        AND seq_global > ?
        ORDER BY seq_global ASC
        """,
        (event_type, seq_global),
    )

    rows = cursor.fetchall()
    conn.close()

    events = []
    for row in rows:
        seq, event_id, evt_type, agent_id, task_desc = row
        events.append({
            "seq_global": seq,
            "event_id": event_id,
            "event_type": evt_type,
            "agent_id": agent_id,
            "task_description": task_desc,
        })

    return events


def wait_for_cieu_events(seq_global: int, event_type: str, *, min_count: int = 1, timeout: float = 4.0) -> list:
    """Poll until enough matching CIEU events appear or timeout expires."""
    deadline = time.time() + timeout
    events = []
    while time.time() < deadline:
        events = get_cieu_events_after_seq(seq_global, event_type)
        if len(events) >= min_count:
            return events
        time.sleep(0.2)
    return events


def start_subscriber_daemon() -> int:
    """
    Start subscriber daemon in background.

    Returns:
        int: PID of daemon process
    """
    # Seed subscriber state to current DB tail so tests do not replay the
    # historical K9 backlog. Each test emits a fresh violation after startup;
    # the subscriber should process only those new events.
    try:
        conn = sqlite3.connect(str(CIEU_DB), timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(seq_global), 0) FROM cieu_events")
        current_tail = cursor.fetchone()[0]
        conn.close()
        STATE_FILE.write_text(json.dumps({
            "last_seq_global": current_tail,
            "updated_at": time.time(),
            "test_seeded": True,
        }, indent=2))
    except Exception:
        pass

    env = os.environ.copy()
    env["YSTAR_COMPANY_ROOT"] = str(COMPANY_ROOT)
    env["YSTAR_CIEU_DB"] = str(CIEU_DB)

    proc = subprocess.Popen(
        [sys.executable, str(SUBSCRIBER_SCRIPT), "start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    # Wait for PID file to appear
    for _ in range(20):  # 2s timeout
        if PID_FILE.exists():
            pid = int(PID_FILE.read_text())
            return pid
        time.sleep(0.1)

    raise TimeoutError("Subscriber daemon failed to start")


def stop_subscriber_daemon():
    """Stop subscriber daemon."""
    if not PID_FILE.exists():
        return

    try:
        pid = int(PID_FILE.read_text())
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)
    except Exception:
        pass


# ═══ TESTS ═══

def test_subscriber_start_stop(clean_state):
    """Test 1: Subscriber daemon start/stop lifecycle."""
    # Start daemon
    pid = start_subscriber_daemon()
    assert PID_FILE.exists()
    assert pid > 0

    # Verify process is running
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pytest.fail("Daemon process not running")

    # Stop daemon
    stop_subscriber_daemon()
    time.sleep(0.5)

    # Verify PID file removed
    assert not PID_FILE.exists()


def test_handler_dispatch_forget_guard(clean_state, cieu_conn):
    """Test 2a: ForgetGuard warn handler dispatched correctly."""
    # Get baseline seq
    cursor = cieu_conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(seq_global), 0) FROM cieu_events")
    baseline_seq = cursor.fetchone()[0]

    # Start subscriber
    pid = start_subscriber_daemon()
    time.sleep(0.5)  # Let subscriber settle

    # Emit fake violation targeting forget_guard
    emit_fake_violation("forget_guard", "warn", "ceo_engineering_boundary")

    # Wait for handler to process (2s max)
    time.sleep(2.0)

    # Check for FORGET_GUARD_K9_WARN event
    events = get_cieu_events_after_seq(baseline_seq, "FORGET_GUARD_K9_WARN")
    assert len(events) >= 1, "ForgetGuard handler did not emit FORGET_GUARD_K9_WARN event"

    # Cleanup
    stop_subscriber_daemon()


def test_handler_dispatch_stop_hook(clean_state, cieu_conn):
    """Test 2b: StopHook deny handler dispatched correctly."""
    cursor = cieu_conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(seq_global), 0) FROM cieu_events")
    baseline_seq = cursor.fetchone()[0]

    pid = start_subscriber_daemon()
    time.sleep(0.5)

    emit_fake_violation("stop_hook_inject", "deny", "subagent_unauthorized_git_op")

    time.sleep(2.0)

    events = get_cieu_events_after_seq(baseline_seq, "STOP_HOOK_K9_DENY")
    assert len(events) >= 1, "StopHook handler did not emit STOP_HOOK_K9_DENY event"

    stop_subscriber_daemon()


def test_handler_dispatch_czl(clean_state, cieu_conn):
    """Test 2c: CZL protocol handler dispatched correctly."""
    cursor = cieu_conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(seq_global), 0) FROM cieu_events")
    baseline_seq = cursor.fetchone()[0]

    pid = start_subscriber_daemon()
    time.sleep(0.5)

    emit_fake_violation("czl_protocol", "warn", "dispatch_missing_5tuple")

    time.sleep(2.0)

    events = get_cieu_events_after_seq(baseline_seq, "CZL_K9_WARN")
    assert len(events) >= 1, "CZL handler did not emit CZL_K9_WARN event"

    stop_subscriber_daemon()


def test_handler_dispatch_agent_registry(clean_state, cieu_conn):
    """Test 2d: Agent Registry handler dispatched correctly."""
    cursor = cieu_conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(seq_global), 0) FROM cieu_events")
    baseline_seq = cursor.fetchone()[0]

    pid = start_subscriber_daemon()
    time.sleep(0.5)

    emit_fake_violation("agent_registry", "warn", "agent_id_unidentified")

    time.sleep(2.0)

    events = get_cieu_events_after_seq(baseline_seq, "AGENT_REGISTRY_K9_WARN")
    assert len(events) >= 1, "Agent Registry handler did not emit AGENT_REGISTRY_K9_WARN event"

    stop_subscriber_daemon()


def test_handler_dispatch_hook_health(clean_state, cieu_conn):
    """Test 2e: Hook Health handler dispatched correctly."""
    cursor = cieu_conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(seq_global), 0) FROM cieu_events")
    baseline_seq = cursor.fetchone()[0]

    pid = start_subscriber_daemon()
    time.sleep(0.5)

    emit_fake_violation("hook_health", "escalate", "hook_chain_missing")

    time.sleep(2.0)

    events = get_cieu_events_after_seq(baseline_seq, "HOOK_HEALTH_K9_ESCALATE")
    assert len(events) >= 1, "Hook Health handler did not emit HOOK_HEALTH_K9_ESCALATE event"

    stop_subscriber_daemon()


def test_missing_routing_target_graceful(clean_state, cieu_conn):
    """Test 4: Missing routing_target gracefully skipped."""
    cursor = cieu_conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(seq_global), 0) FROM cieu_events")
    baseline_seq = cursor.fetchone()[0]

    pid = start_subscriber_daemon()
    time.sleep(0.5)

    # Emit violation with unknown routing_target
    emit_fake_violation("unknown_module", "warn", "unknown_violation")

    time.sleep(2.0)

    # Check for K9_ROUTING_UNKNOWN_TARGET event
    events = get_cieu_events_after_seq(baseline_seq, "K9_ROUTING_UNKNOWN_TARGET")
    assert len(events) >= 1, "Subscriber did not emit K9_ROUTING_UNKNOWN_TARGET for unknown handler"

    stop_subscriber_daemon()


def test_multiple_handlers_parallel(clean_state, cieu_conn):
    """Test 5: Multiple handlers dispatched in parallel."""
    cursor = cieu_conn.cursor()
    cursor.execute("SELECT COALESCE(MAX(seq_global), 0) FROM cieu_events")
    baseline_seq = cursor.fetchone()[0]

    pid = start_subscriber_daemon()
    time.sleep(0.5)

    # Emit 3 violations targeting different handlers
    emit_fake_violation("forget_guard", "warn", "ceo_engineering_boundary")
    emit_fake_violation("czl_protocol", "warn", "dispatch_missing_5tuple")
    emit_fake_violation("agent_registry", "warn", "agent_id_unidentified")

    # Check all 3 handler events emitted
    forget_guard_events = wait_for_cieu_events(baseline_seq, "FORGET_GUARD_K9_WARN")
    czl_events = wait_for_cieu_events(baseline_seq, "CZL_K9_WARN")
    registry_events = wait_for_cieu_events(baseline_seq, "AGENT_REGISTRY_K9_WARN")

    assert len(forget_guard_events) >= 1, "ForgetGuard handler not dispatched"
    assert len(czl_events) >= 1, "CZL handler not dispatched"
    assert len(registry_events) >= 1, "Agent Registry handler not dispatched"

    stop_subscriber_daemon()


def test_state_persistence(clean_state, cieu_conn):
    """Test 6: State persistence (last_seq tracking)."""
    # Start subscriber
    pid = start_subscriber_daemon()
    time.sleep(0.5)

    # Emit violation
    seq = emit_fake_violation("forget_guard", "warn", "test_violation")
    time.sleep(2.0)

    # Stop subscriber
    stop_subscriber_daemon()
    time.sleep(0.5)

    # Check state file
    assert STATE_FILE.exists(), "State file not created"

    state = json.loads(STATE_FILE.read_text())
    assert "last_seq_global" in state
    assert state["last_seq_global"] >= seq, "State file does not track last processed seq correctly"


# ═══ SMOKE TEST (Manual Verification) ═══

def test_smoke_cascade_manual(clean_state):
    """
    Smoke test: start subscriber, emit fake violation, verify cascade within 2s.

    This used to assume an external subscriber was already running, which made
    the automated test flaky. Keep the manual smoke semantics but make it
    hermetic like the other E2E routing tests.
    """
    if not CIEU_DB.exists():
        pytest.skip("CIEU DB not found")

    conn = sqlite3.connect(str(CIEU_DB), timeout=5.0)
    cursor = conn.cursor()

    # Get baseline seq
    cursor.execute("SELECT COALESCE(MAX(seq_global), 0) FROM cieu_events")
    baseline_seq = cursor.fetchone()[0]
    conn.close()

    try:
        start_subscriber_daemon()
        time.sleep(0.5)

        # Emit fake violation
        emit_fake_violation("forget_guard", "warn", "smoke_test_violation")

        print(f"\n[SMOKE] Emitted fake K9_VIOLATION_DETECTED event")
        print(f"[SMOKE] Baseline seq_global: {baseline_seq}")
        print(f"[SMOKE] Waiting 2s for subscriber to process...")

        # Wait 2s
        time.sleep(2.0)

        # Check for FORGET_GUARD_K9_WARN event
        events = get_cieu_events_after_seq(baseline_seq, "FORGET_GUARD_K9_WARN")

        print(f"[SMOKE] Found {len(events)} FORGET_GUARD_K9_WARN events after baseline")

        if len(events) >= 1:
            print(f"[SMOKE] ✅ SMOKE CASCADE SUCCESS — handler responded within 2s")
        else:
            print(f"[SMOKE] ❌ SMOKE CASCADE FAIL — no handler event detected")

        assert len(events) >= 1, "Smoke cascade failed — no handler event within 2s"
    finally:
        stop_subscriber_daemon()
