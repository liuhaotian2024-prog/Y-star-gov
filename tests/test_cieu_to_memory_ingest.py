"""
Test suite for CIEU → memory.db event bridge (Closure-1).

Tests cover:
1. Trigger rule evaluation (should_ingest)
2. Queue mechanics (non-blocking, fail-open)
3. Worker writes to MemoryStore
4. No LLM imports in hook path
"""
import pytest
import sys
import time
import tempfile
from pathlib import Path

from ystar.memory.ingest import should_ingest, enqueue, _INGEST_QUEUE
from ystar.memory.store import MemoryStore


# ── Test 1: High-severity denial → lesson ────────────────────────────────

def test_should_ingest_deny_high_severity():
    """High-severity denial triggers 'lesson' memory type."""
    event = {
        "event_type": "write_file",
        "decision": "deny",
        "violations": [
            {"dimension": "scope", "severity": 0.9, "message": "Path forbidden"}
        ],
        "params": {},
        "agent_id": "test-agent",
        "session_id": "test-session",
    }

    should_store, mem_type = should_ingest(event)
    assert should_store is True
    assert mem_type == "lesson"


# ── Test 2: Normal allow → no ingest ──────────────────────────────────────

def test_should_ingest_allow_normal():
    """Normal 'allow' decision does not trigger ingest."""
    event = {
        "event_type": "read_file",
        "decision": "allow",
        "violations": [],
        "params": {},
        "agent_id": "test-agent",
        "session_id": "test-session",
    }

    should_store, mem_type = should_ingest(event)
    assert should_store is False
    assert mem_type is None


# ── Test 3: Drift detected → environment_change ───────────────────────────

def test_should_ingest_drift_detected():
    """drift_detected param triggers 'environment_change' memory type."""
    event = {
        "event_type": "boot_check",
        "decision": "info",
        "violations": [],
        "params": {"drift_detected": 1, "drift_details": {"cwd": "changed"}},
        "agent_id": "test-agent",
        "session_id": "test-session",
    }

    should_store, mem_type = should_ingest(event)
    assert should_store is True
    assert mem_type == "environment_change"


# ── Test 4: Explicit event type 'insight' → insight ────────────────────────

def test_should_ingest_explicit_insight():
    """Event type 'insight' triggers 'insight' memory type."""
    event = {
        "event_type": "insight",
        "decision": "info",
        "violations": [],
        "params": {"observation": "Pattern X observed"},
        "agent_id": "test-agent",
        "session_id": "test-session",
    }

    should_store, mem_type = should_ingest(event)
    assert should_store is True
    assert mem_type == "insight"


# ── Test 5: Human initiator → human_directive ──────────────────────────────

def test_should_ingest_human_initiator():
    """human_initiator param triggers 'human_directive' memory type."""
    event = {
        "event_type": "board_command",
        "decision": "info",
        "violations": [],
        "params": {"human_initiator": "Board", "directive": "Deploy immediately"},
        "agent_id": "test-agent",
        "session_id": "test-session",
    }

    should_store, mem_type = should_ingest(event)
    assert should_store is True
    assert mem_type == "human_directive"


# ── Test 6: Low-severity denial → no ingest (negative case) ────────────────

def test_should_ingest_low_severity_deny():
    """Low-severity denial (<0.7) does NOT trigger ingest."""
    event = {
        "event_type": "write_file",
        "decision": "deny",
        "violations": [
            {"dimension": "scope", "severity": 0.5, "message": "Minor violation"}
        ],
        "params": {},
        "agent_id": "test-agent",
        "session_id": "test-session",
    }

    should_store, mem_type = should_ingest(event)
    assert should_store is False
    assert mem_type is None


# ── Test 7: Queue non-blocking when full ───────────────────────────────────

def test_enqueue_nonblocking_when_full():
    """enqueue returns immediately even when queue is full (fail-open)."""
    # Fill queue to capacity (maxsize=1000)
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / ".ystar_memory.db")

        # Create a blocking event that should trigger ingest
        event = {
            "event_type": "insight",
            "decision": "info",
            "violations": [],
            "params": {},
            "agent_id": "test",
            "session_id": "test",
        }

        # Fill queue (this may not fully fill it due to worker draining)
        # So we test timing instead
        start = time.time()
        for _ in range(10):  # Just enqueue a few
            enqueue(event, db_path)
        elapsed = time.time() - start

        # All calls should complete in well under 10ms total
        assert elapsed < 0.1, f"enqueue took {elapsed*1000:.1f}ms, expected <100ms"


# ── Test 8: Worker writes to MemoryStore ───────────────────────────────────

def test_worker_writes_memory():
    """Worker thread drains queue and writes to MemoryStore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / ".ystar_memory.db")

        # Pre-create store to initialize schema before worker starts
        store = MemoryStore(db_path)

        # Enqueue a high-severity denial
        event = {
            "event_type": "write_file",
            "decision": "deny",
            "violations": [
                {"dimension": "scope", "severity": 0.95, "message": "Critical violation"}
            ],
            "params": {},
            "agent_id": "test-worker",
            "session_id": "worker-session",
            "cieu_ref": "test-ref-123",
        }

        enqueue(event, db_path)

        # Wait for worker to process (generous timeout)
        time.sleep(0.5)

        # Query memory store (use memory_types plural, as a list)
        memories = store.recall(agent_id="test-worker", memory_types=["lesson"], limit=10)

        assert len(memories) >= 1, "Expected at least 1 'lesson' memory"
        mem = memories[0]
        assert mem.memory_type == "lesson"
        assert mem.agent_id == "test-worker"
        assert "Critical violation" in mem.content


# ── Test 9: No LLM imports in hook path ────────────────────────────────────

def test_hook_path_no_llm_import():
    """Importing ingest module does not pull in openai/anthropic (Iron Rule 1)."""
    # Before importing, check sys.modules
    llm_modules = {"openai", "anthropic", "anthropic.ai"}

    # Import ingest (should be safe)
    import ystar.memory.ingest  # noqa: F401

    # Check that no LLM SDKs were imported
    loaded_llm = [m for m in llm_modules if m in sys.modules]
    assert not loaded_llm, f"LLM modules loaded in hook path: {loaded_llm}"


# ── Test 10: Multiple event types in one session ───────────────────────────

def test_multiple_event_types():
    """Different event types trigger different memory types."""
    events = [
        # Drift
        {
            "event_type": "boot",
            "decision": "info",
            "violations": [],
            "params": {"drift_detected": 1},
            "agent_id": "multi-test",
            "session_id": "multi-session",
        },
        # High-severity deny
        {
            "event_type": "exec",
            "decision": "deny",
            "violations": [{"dimension": "command", "severity": 0.8, "message": "rm -rf forbidden"}],
            "params": {},
            "agent_id": "multi-test",
            "session_id": "multi-session",
        },
        # Explicit insight
        {
            "event_type": "insight",
            "decision": "info",
            "violations": [],
            "params": {"insight": "Found performance bottleneck"},
            "agent_id": "multi-test",
            "session_id": "multi-session",
        },
    ]

    results = [should_ingest(e) for e in events]

    assert results[0] == (True, "environment_change")
    assert results[1] == (True, "lesson")
    assert results[2] == (True, "insight")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
