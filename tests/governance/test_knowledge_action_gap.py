"""
test_knowledge_action_gap.py — Level 4 Knowledge-Action Gap Detection Tests

Board 2026-04-19: "OmissionEngine 也应该是知行合一的重要引擎"
Tests:
  1. test_yaml_registry_loads
  2. test_gap_detected_when_knowledge_no_action
  3. test_no_gap_when_action_follows_knowledge
  4. test_gap_obligation_registered_with_correct_type
"""
import os
import sqlite3
import tempfile
import time
import uuid

import pytest
import yaml

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ystar.governance.omission_engine import (
    _load_knowledge_action_registry,
    detect_knowledge_action_gaps,
)
from ystar.governance.omission_models import OmissionType


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_registry(tmp_path):
    """Create a minimal knowledge-action registry YAML for testing."""
    registry = {
        "rules": [
            {
                "knowledge_id": "test_check_brain",
                "knowledge_source": "test_source.md",
                "knowledge_trigger": "decision_tool_call",
                "required_action": "brain_query",
                "detection_window_sec": 30,
                "severity": "high",
                "description": "Test rule: brain query must follow decision tool call",
            },
            {
                "knowledge_id": "test_verify_before_ship",
                "knowledge_source": "test_verify.md",
                "knowledge_trigger": "ship_event",
                "required_action": "pytest_run",
                "detection_window_sec": 60,
                "severity": "medium",
                "description": "Test rule: pytest must precede ship",
            },
        ]
    }
    path = tmp_path / "test_registry.yaml"
    with open(path, "w") as f:
        yaml.dump(registry, f)
    return str(path)


@pytest.fixture
def cieu_db_with_trigger_only(tmp_path):
    """CIEU DB with a trigger event but NO matching action event."""
    db_path = str(tmp_path / "test_cieu.db")
    now = time.time()

    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cieu_events ("
        "  event_id TEXT PRIMARY KEY,"
        "  seq_global INTEGER,"
        "  created_at REAL,"
        "  session_id TEXT,"
        "  agent_id TEXT,"
        "  event_type TEXT,"
        "  decision TEXT,"
        "  passed INTEGER,"
        "  drift_detected INTEGER,"
        "  task_description TEXT,"
        "  evidence_grade TEXT"
        ")"
    )
    # Insert a trigger event (decision_tool_call) with NO matching brain_query
    conn.execute(
        "INSERT INTO cieu_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            int(now * 1_000_000),
            now - 60,  # 60 seconds ago
            "test_session",
            "test_agent",
            "decision_tool_call",
            "allow",
            1,
            0,
            "Agent made a decision_tool_call without consulting memory",
            "test",
        ),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def cieu_db_with_trigger_and_action(tmp_path):
    """CIEU DB with a trigger event AND a matching action event within the window."""
    db_path = str(tmp_path / "test_cieu_complete.db")
    now = time.time()

    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cieu_events ("
        "  event_id TEXT PRIMARY KEY,"
        "  seq_global INTEGER,"
        "  created_at REAL,"
        "  session_id TEXT,"
        "  agent_id TEXT,"
        "  event_type TEXT,"
        "  decision TEXT,"
        "  passed INTEGER,"
        "  drift_detected INTEGER,"
        "  task_description TEXT,"
        "  evidence_grade TEXT"
        ")"
    )
    trigger_ts = now - 60
    # Insert trigger event
    conn.execute(
        "INSERT INTO cieu_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            int(trigger_ts * 1_000_000),
            trigger_ts,
            "test_session",
            "test_agent",
            "decision_tool_call",
            "allow",
            1,
            0,
            "Agent made decision_tool_call",
            "test",
        ),
    )
    # Insert matching action event 10 seconds after trigger (within 30s window)
    action_ts = trigger_ts + 10
    conn.execute(
        "INSERT INTO cieu_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            int(action_ts * 1_000_000),
            action_ts,
            "test_session",
            "test_agent",
            "brain_query",
            "allow",
            1,
            0,
            "Agent performed brain_query after decision",
            "test",
        ),
    )
    conn.commit()
    conn.close()
    return db_path


# ── Tests ────────────────────────────────────────────────────────────────────

def test_yaml_registry_loads(sample_registry):
    """Test that the YAML registry loads correctly and contains expected rules."""
    rules = _load_knowledge_action_registry(sample_registry)
    assert len(rules) == 2
    assert rules[0]["knowledge_id"] == "test_check_brain"
    assert rules[1]["knowledge_id"] == "test_verify_before_ship"
    assert rules[0]["detection_window_sec"] == 30
    assert rules[0]["severity"] == "high"


def test_gap_detected_when_knowledge_no_action(
    sample_registry, cieu_db_with_trigger_only
):
    """
    When a trigger event exists but NO matching action event follows,
    the detector must report a KNOWLEDGE_ACTION_GAP.
    """
    result = detect_knowledge_action_gaps(
        cieu_db_path=cieu_db_with_trigger_only,
        registry_path=sample_registry,
        cieu_window_sec=300,
    )
    assert result["rules_checked"] == 2
    assert result["total_triggers_found"] >= 1
    assert result["total_gaps"] >= 1

    # Find the specific gap for test_check_brain
    brain_gaps = [g for g in result["gaps"] if g["knowledge_id"] == "test_check_brain"]
    assert len(brain_gaps) >= 1
    assert brain_gaps[0]["required_action"] == "brain_query"
    assert brain_gaps[0]["severity"] == "high"


def test_no_gap_when_action_follows_knowledge(
    sample_registry, cieu_db_with_trigger_and_action
):
    """
    When a trigger event exists AND a matching action event follows
    within the detection window, NO gap should be reported for that rule.
    """
    result = detect_knowledge_action_gaps(
        cieu_db_path=cieu_db_with_trigger_and_action,
        registry_path=sample_registry,
        cieu_window_sec=300,
    )
    # The decision_tool_call trigger has a brain_query action within 10s (< 30s window)
    # So test_check_brain should NOT produce a gap
    brain_gaps = [g for g in result["gaps"] if g["knowledge_id"] == "test_check_brain"]
    assert len(brain_gaps) == 0


def test_gap_obligation_registered_with_correct_type(
    sample_registry, cieu_db_with_trigger_only, tmp_path, monkeypatch
):
    """
    When a gap is detected, the engine must register an ObligationRecord
    with obligation_type == KNOWLEDGE_ACTION_GAP.
    """
    # Monkeypatch the OmissionStore to use a temp DB so we don't pollute
    from ystar.governance import omission_store
    test_db = str(tmp_path / "test_omission.db")
    original_init = omission_store.OmissionStore.__init__

    def patched_init(self, db_path=None, **kwargs):
        original_init(self, db_path=test_db, **kwargs)

    monkeypatch.setattr(omission_store.OmissionStore, "__init__", patched_init)

    result = detect_knowledge_action_gaps(
        cieu_db_path=cieu_db_with_trigger_only,
        registry_path=sample_registry,
        cieu_window_sec=300,
    )

    assert result["obligations_registered"] >= 1

    # Verify the obligation was stored with correct type
    store = omission_store.OmissionStore(db_path=test_db)
    all_obs = store.list_obligations()
    ka_obs = [
        ob for ob in all_obs
        if ob.obligation_type == OmissionType.KNOWLEDGE_ACTION_GAP.value
    ]
    assert len(ka_obs) >= 1
    assert "KNOWLEDGE_ACTION_GAP" in ka_obs[0].notes
    assert ka_obs[0].violation_code == "knowledge_action_gap"
