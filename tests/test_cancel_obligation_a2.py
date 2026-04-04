"""
Test cancel_obligation() implementation [tech-debt A2]

Validates:
- InMemoryOmissionStore.cancel_obligation()
- OmissionStore.cancel_obligation()
- Status updates to CANCELLED
- CIEU event recording
- Handling of non-existent obligations
"""
import time
from pathlib import Path

import pytest

from ystar.governance.omission_store import InMemoryOmissionStore, OmissionStore
from ystar.governance.omission_models import (
    ObligationRecord,
    ObligationStatus,
    Severity,
    EscalationPolicy,
)


def test_cancel_obligation_memory():
    """Test cancel_obligation in InMemoryOmissionStore."""
    store = InMemoryOmissionStore()

    # Create an obligation
    ob = ObligationRecord(
        obligation_id="ob_001",
        entity_id="ent_001",
        actor_id="agent_a",
        obligation_type="test_obligation",
        trigger_event_id="evt_trigger",
        required_event_types=["completion"],
        due_at=time.time() + 3600,
        status=ObligationStatus.PENDING,
        severity=Severity.MEDIUM,
        escalation_policy=EscalationPolicy.default(),
    )

    store.add_obligation(ob)

    # Verify initial state
    retrieved = store.get_obligation("ob_001")
    assert retrieved is not None
    assert retrieved.status == ObligationStatus.PENDING

    # Cancel the obligation
    result = store.cancel_obligation("ob_001")
    assert result is True, "Should successfully cancel obligation"

    # Verify status changed to CANCELLED
    cancelled = store.get_obligation("ob_001")
    assert cancelled is not None
    assert cancelled.status == ObligationStatus.CANCELLED

    # Try to cancel non-existent obligation
    result = store.cancel_obligation("ob_nonexistent")
    assert result is False, "Should return False for non-existent obligation"


def test_cancel_obligation_sqlite(tmp_path):
    """Test cancel_obligation in SQLite-backed OmissionStore."""
    db_path = tmp_path / "test_omission.db"
    store = OmissionStore(str(db_path))

    # Create an obligation
    ob = ObligationRecord(
        obligation_id="ob_002",
        entity_id="ent_002",
        actor_id="agent_b",
        obligation_type="test_obligation",
        trigger_event_id="evt_trigger",
        required_event_types=["status_update"],
        due_at=time.time() + 3600,
        status=ObligationStatus.PENDING,
        severity=Severity.HIGH,
        escalation_policy=EscalationPolicy.default(),
    )

    store.add_obligation(ob)

    # Verify initial state
    retrieved = store.get_obligation("ob_002")
    assert retrieved is not None
    assert retrieved.status == ObligationStatus.PENDING

    # Cancel the obligation with reason
    result = store.cancel_obligation("ob_002", reason="Session ended")
    assert result is True, "Should successfully cancel obligation"

    # Verify status changed to CANCELLED
    cancelled = store.get_obligation("ob_002")
    assert cancelled is not None
    assert cancelled.status == ObligationStatus.CANCELLED

    # Try to cancel non-existent obligation
    result = store.cancel_obligation("ob_nonexistent")
    assert result is False, "Should return False for non-existent obligation"


def test_cancel_obligation_cieu_recording(tmp_path):
    """Test that cancel_obligation writes to CIEU."""
    db_path = tmp_path / "test_omission.db"
    cieu_path = tmp_path / "test.db"

    # Create CIEU database
    from ystar.governance.cieu_store import CIEUStore
    cieu_store = CIEUStore(str(cieu_path))

    # Create omission store
    store = OmissionStore(str(db_path))

    # Create and cancel an obligation
    ob = ObligationRecord(
        obligation_id="ob_003",
        entity_id="ent_003",
        actor_id="agent_c",
        obligation_type="test_obligation",
        trigger_event_id="evt_trigger",
        required_event_types=["completion"],
        due_at=time.time() + 3600,
        status=ObligationStatus.PENDING,
        severity=Severity.MEDIUM,
        escalation_policy=EscalationPolicy.default(),
    )

    store.add_obligation(ob)
    store.cancel_obligation("ob_003", reason="Test cancellation", write_cieu=True)

    # Verify CIEU event was written
    events = cieu_store.query(event_type="obligation_cancelled", limit=10)
    assert len(events) > 0, "Should have recorded cancellation in CIEU"

    # Check event details
    import json
    cancellation_events = []
    for e in events:
        if e.params_json:
            params = json.loads(e.params_json)
            if params.get('obligation_id') == 'ob_003':
                cancellation_events.append(e)

    assert len(cancellation_events) > 0, "Should find cancellation event for ob_003"

    event = cancellation_events[0]
    params = json.loads(event.params_json)
    assert params['reason'] == 'Test cancellation'
    assert event.decision == 'allow'


def test_cancel_obligation_no_cieu(tmp_path):
    """Test that cancel_obligation works even without CIEU database."""
    db_path = tmp_path / "test_omission.db"
    store = OmissionStore(str(db_path))

    # Create an obligation
    ob = ObligationRecord(
        obligation_id="ob_004",
        entity_id="ent_004",
        actor_id="agent_d",
        obligation_type="test_obligation",
        trigger_event_id="evt_trigger",
        required_event_types=["completion"],
        due_at=time.time() + 3600,
        status=ObligationStatus.PENDING,
        severity=Severity.LOW,
        escalation_policy=EscalationPolicy.default(),
    )

    store.add_obligation(ob)

    # Cancel without CIEU (CIEU path doesn't exist)
    result = store.cancel_obligation("ob_004", write_cieu=True)
    assert result is True, "Should succeed even if CIEU write fails"

    # Verify obligation was still cancelled
    cancelled = store.get_obligation("ob_004")
    assert cancelled.status == ObligationStatus.CANCELLED


def test_cancel_obligation_pending_check(tmp_path):
    """Test that cancelled obligations are not reported as pending."""
    store = InMemoryOmissionStore()

    # Create two obligations
    ob1 = ObligationRecord(
        obligation_id="ob_pending",
        entity_id="ent_005",
        actor_id="agent_e",
        obligation_type="test_obligation",
        trigger_event_id="evt_trigger",
        required_event_types=["completion"],
        due_at=time.time() + 3600,
        status=ObligationStatus.PENDING,
        severity=Severity.MEDIUM,
        escalation_policy=EscalationPolicy.default(),
    )

    ob2 = ObligationRecord(
        obligation_id="ob_to_cancel",
        entity_id="ent_005",
        actor_id="agent_e",
        obligation_type="test_obligation",
        trigger_event_id="evt_trigger",
        required_event_types=["completion"],
        due_at=time.time() + 3600,
        status=ObligationStatus.PENDING,
        severity=Severity.MEDIUM,
        escalation_policy=EscalationPolicy.default(),
    )

    store.add_obligation(ob1)
    store.add_obligation(ob2)

    # Verify both are pending
    pending = store.pending_obligations()
    assert len(pending) == 2

    # Cancel one obligation
    store.cancel_obligation("ob_to_cancel")

    # Verify only one is now pending
    pending_after = store.pending_obligations()
    assert len(pending_after) == 1
    assert pending_after[0].obligation_id == "ob_pending"
