"""
Test omission violation activity gating.

Verify fix for Circuit Breaker noise root cause (480/480/480/480 timer-fired violations).
Violations should only fire when entity is active but failed to produce expected artifact.

Fix spec:
- Dormant entity (no events in last 10min) → no violation emission
- Active entity (events in last 10min) + overdue obligation → violation fires

Coverage:
- intent_declaration
- directive_acknowledgement
- progress_update
- task_completion_report
"""
import time
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_models import (
    TrackedEntity,
    ObligationRecord,
    GovernanceEvent,
    EntityStatus,
    ObligationStatus,
    Severity,
    EscalationPolicy,
)


def test_dormant_entity_no_violation():
    """
    Dormant entity (no recent events) should NOT trigger violation.
    """
    fake_time = [1000.0]
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, now_fn=lambda: fake_time[0])

    # Create entity
    entity = TrackedEntity(
        entity_id="task_001",
        entity_type="task",
        initiator_id="ceo",
        current_owner_id="cto",
        status=EntityStatus.ACTIVE,
        last_event_at=300.0,  # Last event 700s ago (dormant - outside 600s window)
    )
    engine.register_entity(entity)

    # Create obligation that is overdue
    ob = ObligationRecord(
        obligation_id="ob_001",
        entity_id="task_001",
        actor_id="cto",
        obligation_type="intent_declaration",
        required_event_types=["intent_declared"],
        status=ObligationStatus.PENDING,
        severity=Severity.MEDIUM,
        due_at=900.0,  # Due 100s ago
        escalation_policy=EscalationPolicy(),
    )
    store.add_obligation(ob)

    # Advance time to trigger overdue check
    fake_time[0] = 1000.0

    # Scan for violations
    result = engine.scan(now=fake_time[0])

    # Expectation: NO violation because entity is dormant (last_event_at = 300, now = 1000, delta = 700s > 600s window)
    assert len(result.violations) == 0, f"Expected 0 violations for dormant entity, got {len(result.violations)}"
    # Obligation may transition to SOFT_OVERDUE internally (tracked in expired list), but no violation should fire
    # The key test: violations list is empty


def test_active_entity_fires_violation():
    """
    Active entity (recent events) should trigger violation when overdue.
    """
    fake_time = [1000.0]
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, now_fn=lambda: fake_time[0])

    # Create entity with recent activity
    entity = TrackedEntity(
        entity_id="task_002",
        entity_type="task",
        initiator_id="ceo",
        current_owner_id="cto",
        status=EntityStatus.ACTIVE,
        last_event_at=950.0,  # Last event 50s ago (active)
    )
    engine.register_entity(entity)

    # Create obligation that is overdue
    ob = ObligationRecord(
        obligation_id="ob_002",
        entity_id="task_002",
        actor_id="cto",
        obligation_type="directive_acknowledgement",
        required_event_types=["directive_ack"],
        status=ObligationStatus.PENDING,
        severity=Severity.MEDIUM,
        due_at=900.0,  # Due 100s ago
        escalation_policy=EscalationPolicy(),
    )
    store.add_obligation(ob)

    # Scan for violations
    result = engine.scan(now=fake_time[0])

    # Expectation: 1 violation because entity is active (last_event_at = 950, now = 1000, delta = 50s < 600s window)
    assert len(result.violations) == 1, f"Expected 1 violation for active entity, got {len(result.violations)}"
    assert result.violations[0].entity_id == "task_002"
    assert result.violations[0].omission_type == "directive_acknowledgement"


def test_hard_overdue_activity_gate():
    """
    HARD_OVERDUE should also respect activity gate.
    """
    fake_time = [1000.0]
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, now_fn=lambda: fake_time[0])

    # Dormant entity
    entity = TrackedEntity(
        entity_id="task_003",
        entity_type="task",
        initiator_id="ceo",
        current_owner_id="cto",
        status=EntityStatus.ACTIVE,
        last_event_at=200.0,  # Last event 800s ago (dormant)
    )
    engine.register_entity(entity)

    # Create SOFT_OVERDUE obligation (simulate soft violation already created)
    ob = ObligationRecord(
        obligation_id="ob_003",
        entity_id="task_003",
        actor_id="cto",
        obligation_type="progress_update",
        required_event_types=["progress_reported"],
        status=ObligationStatus.SOFT_OVERDUE,
        severity=Severity.MEDIUM,
        due_at=500.0,  # Due 500s ago
        soft_violation_at=600.0,
        hard_overdue_secs=300,  # Hard overdue threshold = 500 + 300 = 800
        escalation_policy=EscalationPolicy(),
    )
    store.add_obligation(ob)

    # Manually add soft violation to satisfy幂等 check
    from ystar.governance.omission_models import OmissionViolation
    soft_v = OmissionViolation(
        violation_id="v_soft",
        entity_id="task_003",
        obligation_id="ob_003",
        actor_id="cto",
        omission_type="progress_update",
        severity=Severity.MEDIUM,
        overdue_secs=100.0,
        detected_at=600.0,
    )
    store.add_violation(soft_v)

    # Advance time past hard threshold
    fake_time[0] = 1000.0  # Hard threshold = 800, now = 1000

    # Scan
    result = engine.scan(now=fake_time[0])

    # Expectation: NO hard violation because entity is dormant
    hard_violations = [v for v in result.violations if v.details.get("stage") == "hard_overdue"]
    assert len(hard_violations) == 0, f"Expected 0 hard violations for dormant entity, got {len(hard_violations)}"


def test_activity_window_boundary():
    """
    Entity with last_event_at exactly at window boundary (600s) should still trigger.
    """
    fake_time = [1000.0]
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, now_fn=lambda: fake_time[0])

    # Entity at exact boundary
    entity = TrackedEntity(
        entity_id="task_004",
        entity_type="task",
        initiator_id="ceo",
        current_owner_id="cto",
        status=EntityStatus.ACTIVE,
        last_event_at=400.0,  # Exactly 600s ago (1000 - 400 = 600)
    )
    engine.register_entity(entity)

    # Overdue obligation
    ob = ObligationRecord(
        obligation_id="ob_004",
        entity_id="task_004",
        actor_id="cto",
        obligation_type="task_completion_report",
        required_event_types=["task_completed"],
        status=ObligationStatus.PENDING,
        severity=Severity.HIGH,
        due_at=900.0,
        escalation_policy=EscalationPolicy(),
    )
    store.add_obligation(ob)

    # Scan
    result = engine.scan(now=fake_time[0])

    # Expectation: 1 violation (boundary is inclusive: now - last_event_at <= 600)
    assert len(result.violations) == 1, f"Expected 1 violation at exact boundary, got {len(result.violations)}"


def test_legacy_pending_path_activity_gate():
    """
    Legacy PENDING → EXPIRED path should also respect activity gate.
    """
    fake_time = [1000.0]
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, now_fn=lambda: fake_time[0])

    # Dormant entity
    entity = TrackedEntity(
        entity_id="task_005",
        entity_type="task",
        initiator_id="ceo",
        current_owner_id="cto",
        status=EntityStatus.ACTIVE,
        last_event_at=100.0,  # Last event 900s ago (dormant)
    )
    engine.register_entity(entity)

    # Old-style PENDING obligation (no soft/hard staging)
    ob = ObligationRecord(
        obligation_id="ob_005",
        entity_id="task_005",
        actor_id="cto",
        obligation_type="required_acknowledgement_omission",
        required_event_types=["ack"],
        status=ObligationStatus.PENDING,
        severity=Severity.MEDIUM,
        due_at=900.0,  # Overdue
        escalation_policy=EscalationPolicy(),
    )
    store.add_obligation(ob)

    # Scan
    result = engine.scan(now=fake_time[0])

    # Expectation: NO violation (dormant entity)
    assert len(result.violations) == 0, f"Expected 0 violations for dormant entity (legacy path), got {len(result.violations)}"
    # Status may transition to SOFT_OVERDUE (internal bookkeeping) but no violation should fire
    updated_ob = store.get_obligation(ob.obligation_id)
    # The key test: no violation was emitted despite overdue status
    assert updated_ob.status in [ObligationStatus.PENDING, ObligationStatus.SOFT_OVERDUE], "Obligation can transition internally but no violation should fire"
