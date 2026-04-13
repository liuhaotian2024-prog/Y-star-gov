# AMENDMENT-015 Layer 3: Self-Recovery Tests
"""
Tests for Layer 3 self-recovery mechanisms:
- L3.1: Observable action auto-satisfy
- L3.2: Violation escalation WARN→DENY
- L3.3: Circuit breaker auto-reset
- L3.4: Narrative coherence detection
"""
import time
import pytest
from ystar.governance.observable_action_detector import (
    ObservableActionDetector, ObligationSatisfied, ObligationPending
)
from ystar.governance.violation_tracker import ViolationTracker
from ystar.governance.narrative_coherence_detector import (
    NarrativeCoherenceDetector, NarrativeGap
)
from ystar.governance.intervention_engine import InterventionEngine
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_models import ObligationRecord, ObligationStatus
from ystar.governance.cieu_store import CIEUStore


def test_observable_action_auto_satisfy():
    """L3.1: Observable action (git commit) auto-satisfies obligation."""
    cieu = CIEUStore(":memory:")
    detector = ObservableActionDetector(cieu_store=cieu)

    # Create a fake obligation with notes containing file path
    class FakeObligation:
        obligation_id = "ob_test_001"
        obligation_type = "directive_acknowledgement"
        actor_id = "test_agent"
        directive = ""
        notes = "Please write tests to tests/test_feature.py"

    ob = FakeObligation()

    # Simulate test pass event in CIEU (easier to verify than git)
    now = time.time()
    cieu.write_dict({
        "event_id": "evt_test_001",
        "seq_global": int(now * 1_000_000),
        "created_at": now,
        "session_id": "test_session",
        "agent_id": "test_agent",
        "event_type": "test_pass",
        "decision": "allow",
        "passed": True,
        "command": "pytest tests/test_feature.py -v",
        "violations": [],
    })

    # Check if observable action satisfies obligation
    result = detector.check_directive_acknowledgement(ob, "test_agent", window_sec=300)

    assert isinstance(result, ObligationSatisfied), "Test pass should auto-satisfy directive obligation"
    assert result.evidence_type == "test_pass"
    assert "test_pass" in result.evidence.lower()


def test_violation_escalation_warn_to_deny():
    """L3.2: Second violation within window escalates WARN→DENY."""
    tracker = ViolationTracker(window_sec=300)

    agent_id = "test_agent"
    violation_type = "scope_violation"

    # First violation → WARNING
    # Note: check_repeat_violation adds timestamp internally
    decision1, message1 = tracker.check_repeat_violation(agent_id, violation_type)
    assert decision1 == "WARN", "First violation should be WARNING"

    # Second violation within window → DENY
    decision2, message2 = tracker.check_repeat_violation(agent_id, violation_type)
    assert decision2 == "DENY", "Second violation within window should be DENY"
    assert "repeated" in message2.lower() or "second" in message2.lower() or "within" in message2.lower()


def test_narrative_gap_detection():
    """L3.4: Detect claim "file written" without Write tool call."""
    cieu = CIEUStore(":memory:")
    detector = NarrativeCoherenceDetector(cieu_store=cieu)

    agent_id = "test_agent"
    turn_id = "turn_001"

    # Agent claims file written
    agent_text = "I wrote the implementation to src/feature.py and tests pass."

    # No Write tool called (tools list is empty)
    tools_called = []

    gaps = detector.check_turn_coherence(
        agent_id=agent_id,
        turn_text=agent_text,
        turn_tools=tools_called
    )

    assert len(gaps) >= 1, f"Should detect narrative gap, got {len(gaps)} gaps: {[g.claim_type for g in gaps]}"

    # Find the file write gap (there may also be a test pass gap)
    write_gap = next((g for g in gaps if g.claim_type == "file_write"), None)
    # If no write gap, check what we got
    if write_gap is None:
        gap_types = [(g.claim, g.claim_type, g.expected_tool) for g in gaps]
        assert write_gap is not None, f"Should detect file write gap. Got: {gap_types}"
    assert "Write" in write_gap.expected_tool or "Edit" in write_gap.expected_tool, \
        f"Gap should expect Write/Edit, got {write_gap.expected_tool}"
    assert write_gap.severity == "HIGH", "File write claim without tool is HIGH severity"

    gap = write_gap

    # Emit gap to CIEU
    detector.emit_gap_event(agent_id, gap, session_id="test_session")

    # Verify CIEU event written
    recent = cieu.query("narrative_bias_detected", limit=1)
    assert len(recent) == 1, "Should write narrative gap to CIEU"
    assert recent[0]["agent_id"] == agent_id


def test_circuit_breaker_auto_reset():
    """L3.3: Circuit breaker auto-resets when observable action delivered."""
    cieu = CIEUStore(":memory:")
    store = InMemoryOmissionStore()
    engine = InterventionEngine(omission_store=store, cieu_store=cieu)

    agent_id = "test_agent"
    now = time.time()

    # Create obligation
    ob = ObligationRecord(
        obligation_id="ob_auto_reset_001",
        entity_id="entity_001",
        actor_id=agent_id,
        obligation_type="test_write_obligation",
        trigger_event_id="evt_directive",
        required_event_types=["test_pass"],
        due_at=now - 100,  # Overdue
        status=ObligationStatus.PENDING,
    )
    store.add_obligation(ob)

    # Trigger hard block (simulate hard_overdue violation)
    from ystar.governance.omission_models import OmissionViolation, Severity
    violation = OmissionViolation(
        obligation_id=ob.obligation_id,
        entity_id=ob.entity_id,
        actor_id=agent_id,
        omission_type="hard_overdue",
        severity=Severity.CRITICAL,
        overdue_secs=100,
        details={"message": "Test obligation hard overdue"},
        detected_at=now,
    )

    # Process violation → creates intervention pulse + restriction
    result = engine.process_violations([violation])
    assert len(result.pulses_created) > 0, "Should create intervention pulse"

    # Verify restriction exists
    restriction = engine.pulse_store.get_restriction(agent_id)
    assert restriction is not None, "Agent should be restricted"

    # Observable action arrives (git commit)
    evidence = "git commit -m 'feat: add tests' (detected via CIEU)"
    lifted = engine.auto_reset_circuit_breakers(agent_id, evidence, now=now + 10)

    assert lifted > 0, "Should lift at least one restriction"

    # Verify restriction cleared
    restriction_after = engine.pulse_store.get_restriction(agent_id)
    assert restriction_after is None, "Restriction should be cleared after auto-reset"

    # Verify CIEU event
    reset_events = cieu.query("circuit_breaker_auto_reset", limit=1)
    assert len(reset_events) == 1, "Should write auto-reset event to CIEU"
    assert reset_events[0]["agent_id"] == agent_id
    assert reset_events[0]["passed"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
