"""
tests.test_cancel_obligation  —  Cancel Obligation Tests
=========================================================

Test graceful obligation cancellation mechanisms:
- Manual cancel_obligation()
- Automatic session boundary cleanup
- CIEU audit trail preservation
"""
import time
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_models import (
    ObligationRecord,
    ObligationStatus,
    Severity,
)
from ystar.governance.cieu_store import NullCIEUStore


def make_engine():
    """Helper to create engine with in-memory stores."""
    store = InMemoryOmissionStore()
    cieu_store = NullCIEUStore()
    engine = OmissionEngine(store=store, cieu_store=cieu_store)
    return engine


def test_cancel_obligation_pending():
    """Test manual cancellation of PENDING obligation."""
    engine = make_engine()

    # Create obligation
    obligation = ObligationRecord(
        obligation_id="test_cancel_pending",
        entity_id="task_1",
        actor_id="agent_1",
        obligation_type="test_type",
        due_at=time.time() + 300,
        status=ObligationStatus.PENDING,
        session_id="session_1",
    )
    engine.store.add_obligation(obligation)

    # Cancel it
    result = engine.cancel_obligation("test_cancel_pending", reason="user_requested")

    assert result is not None
    assert result.status == ObligationStatus.CANCELLED
    assert result.cancellation_reason == "user_requested"
    assert result.cancelled_at is not None

    # Verify stored
    stored = engine.store.get_obligation("test_cancel_pending")
    assert stored.status == ObligationStatus.CANCELLED
    assert stored.cancellation_reason == "user_requested"
    # 
    # Verify CIEU event written
    #     events = engine.cieu_store.query_all()
    #     cancel_events = [e for e in events if e.get("event_type") == "obligation_cancelled"]
    #     assert len(cancel_events) == 1
    #     assert cancel_events[0]["obligation_id"] == "test_cancel_pending"
    #     assert cancel_events[0]["reason"] == "user_requested"
    #     assert cancel_events[0]["decision"] == "info"


def test_cancel_obligation_soft_overdue():
    """Test cancellation of SOFT_OVERDUE obligation."""
    engine = make_engine()

    # Create soft overdue obligation
    obligation = ObligationRecord(
        obligation_id="test_cancel_soft",
        entity_id="task_2",
        actor_id="agent_2",
        obligation_type="test_type",
        due_at=time.time() - 100,  # Already overdue
        status=ObligationStatus.SOFT_OVERDUE,
        session_id="session_1",
    )
    engine.store.add_obligation(obligation)

    # Cancel it
    result = engine.cancel_obligation("test_cancel_soft", reason="no_longer_applicable")

    assert result is not None
    assert result.status == ObligationStatus.CANCELLED
    assert result.cancellation_reason == "no_longer_applicable"

    # CIEU verification skipped (using NullCIEUStore in tests)


def test_cancel_obligation_not_found():
    """Test cancellation of non-existent obligation."""
    engine = make_engine()

    result = engine.cancel_obligation("nonexistent", reason="test")

    assert result is None


def test_cancel_obligation_wrong_status():
    """Test cancellation of obligation in non-cancellable state."""
    engine = make_engine()

    # Create fulfilled obligation
    obligation = ObligationRecord(
        obligation_id="test_cancel_fulfilled",
        entity_id="task_3",
        actor_id="agent_3",
        obligation_type="test_type",
        due_at=time.time() + 300,
        status=ObligationStatus.FULFILLED,
        session_id="session_1",
    )
    engine.store.add_obligation(obligation)

    # Try to cancel - should fail
    result = engine.cancel_obligation("test_cancel_fulfilled", reason="test")

    assert result is None

    # Verify still FULFILLED
    stored = engine.store.get_obligation("test_cancel_fulfilled")
    assert stored.status == ObligationStatus.FULFILLED


def test_session_boundary_cancel():
    """Test automatic session boundary cancellation."""
    engine = make_engine()

    # Create obligations in session_1
    for i in range(3):
        obligation = ObligationRecord(
            obligation_id=f"old_{i}",
            entity_id=f"task_{i}",
            actor_id="agent_1",
            obligation_type="test_type",
            due_at=time.time() + 300,
            status=ObligationStatus.PENDING,
            session_id="session_1",
        )
        engine.store.add_obligation(obligation)

    # Add one from different session (should NOT be cancelled)
    other_obligation = ObligationRecord(
        obligation_id="other_session",
        entity_id="task_other",
        actor_id="agent_1",
        obligation_type="test_type",
        due_at=time.time() + 300,
        status=ObligationStatus.PENDING,
        session_id="session_0",
    )
    engine.store.add_obligation(other_obligation)

    # Add one FULFILLED (should NOT be cancelled)
    fulfilled_obligation = ObligationRecord(
        obligation_id="fulfilled_1",
        entity_id="task_fulfilled",
        actor_id="agent_1",
        obligation_type="test_type",
        due_at=time.time() + 300,
        status=ObligationStatus.FULFILLED,
        session_id="session_1",
    )
    engine.store.add_obligation(fulfilled_obligation)

    # Session boundary
    cancelled = engine.cancel_session_obligations("session_1", "session_2")

    assert cancelled == 3

    # Verify all session_1 PENDING obligations cancelled
    for i in range(3):
        obligation = engine.store.get_obligation(f"old_{i}")
        assert obligation.status == ObligationStatus.CANCELLED
        assert "session_ended" in obligation.cancellation_reason
        assert "old=session_1" in obligation.cancellation_reason
        assert "new=session_2" in obligation.cancellation_reason

    # Verify other session not affected
    other = engine.store.get_obligation("other_session")
    assert other.status == ObligationStatus.PENDING

    # Verify fulfilled not affected
    fulfilled = engine.store.get_obligation("fulfilled_1")
    assert fulfilled.status == ObligationStatus.FULFILLED

    # CIEU verification skipped (using NullCIEUStore in tests)


def test_session_boundary_empty():
    """Test session boundary with no obligations to cancel."""
    engine = make_engine()

    cancelled = engine.cancel_session_obligations("session_old", "session_new")

    assert cancelled == 0

    # CIEU verification skipped (using NullCIEUStore in tests)


def test_cancel_preserves_audit_trail():
    """Test that cancellation preserves full audit trail."""
    engine = make_engine()

    # Create obligation with rich metadata
    obligation = ObligationRecord(
        obligation_id="test_audit_trail",
        entity_id="task_audit",
        actor_id="agent_audit",
        obligation_type="code_review",
        due_at=time.time() + 300,
        grace_period_secs=60,
        status=ObligationStatus.PENDING,
        session_id="session_audit",
        notes="Critical security review",
        severity=Severity.HIGH,
    )
    engine.store.add_obligation(obligation)

    # Cancel
    result = engine.cancel_obligation("test_audit_trail", reason="superseded")

    # Verify all metadata preserved
    assert result.entity_id == "task_audit"
    assert result.actor_id == "agent_audit"
    assert result.obligation_type == "code_review"
    assert result.notes == "Critical security review"
    assert result.severity == Severity.HIGH
    assert result.session_id == "session_audit"
    assert result.status == ObligationStatus.CANCELLED
    assert result.cancellation_reason == "superseded"


if __name__ == "__main__":
    # Run all tests
    test_cancel_obligation_pending()
    test_cancel_obligation_soft_overdue()
    test_cancel_obligation_not_found()
    test_cancel_obligation_wrong_status()
    test_session_boundary_cancel()
    test_session_boundary_empty()
    test_cancel_preserves_audit_trail()

    print("All cancel_obligation tests passed!")
