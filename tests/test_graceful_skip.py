"""
tests.test_graceful_skip — Test GracefulSkip mechanism for unregistered obligation types
=========================================================================================

Validates that triggers/rules referencing unregistered obligation types:
  - Do NOT create violations
  - Write warning to CIEU
  - Continue processing other valid triggers/rules
  - System remains stable

P0 fix to prevent violation cascades from typos or missing obligation type registrations.
"""
import time
import pytest

from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_rules import RuleRegistry, OmissionRule
from ystar.governance.omission_models import (
    GovernanceEvent, TrackedEntity, EntityStatus, Severity,
)
from ystar.governance.cieu_store import CIEUStore
from ystar.governance.obligation_triggers import (
    ObligationTrigger, TriggerRegistry, get_trigger_registry, reset_trigger_registry,
)


class MockCIEUStore:
    """Simple in-memory CIEU store for testing."""

    def __init__(self):
        self.records = []

    def write_dict(self, record: dict) -> bool:
        self.records.append(record)
        return True

    def query(self, event_type: str = None, **kwargs) -> list:
        if event_type:
            return [r for r in self.records if r.get("event_type") == event_type]
        return self.records


class TestGracefulSkip:
    """Test GracefulSkip mechanism prevents violation cascades."""

    def test_trigger_with_unregistered_obligation_type_graceful_skip(self):
        """
        Trigger references a non-existent obligation_type.
        Should:
          - Not create obligation
          - Write warning to CIEU
          - Not crash
        """
        # Setup
        store = InMemoryOmissionStore()
        cieu_store = MockCIEUStore()
        trigger_registry = reset_trigger_registry()

        # Register trigger with INVALID obligation_type
        trigger = ObligationTrigger(
            trigger_id="test_invalid_type",
            trigger_tool_pattern=r"Write",
            obligation_type="security_incident_response",  # NOT REGISTERED
            description="This should be gracefully skipped",
            target_agent="caller",
            deadline_seconds=300,
            severity="SOFT",
        )
        trigger_registry.register(trigger)

        engine = OmissionEngine(
            store=store,
            registry=RuleRegistry(),  # Empty rule registry
            cieu_store=cieu_store,
            trigger_registry=trigger_registry,
        )

        # Create entity
        entity = TrackedEntity(
            entity_id="session_1",
            entity_type="session",
            initiator_id="agent_1",
            current_owner_id="agent_1",
            status=EntityStatus.ACTIVE,
        )
        store.upsert_entity(entity)

        # Trigger event (Write tool call)
        ev = GovernanceEvent(
            event_id="ev_1",
            event_type="tool_call",
            entity_id="session_1",
            actor_id="agent_1",
            ts=time.time(),
            payload={
                "tool_name": "Write",
                "tool_input": {"file_path": "/tmp/test.txt"},
                "decision": "ALLOW",
            },
        )

        # Ingest event
        result = engine.ingest_event(ev)

        # Assert: No obligation created
        assert len(result.new_obligations) == 0, \
            "GracefulSkip should prevent obligation creation for unregistered types"

        # Assert: No violations
        assert len(result.violations) == 0, \
            "GracefulSkip should not create violations"

        # Assert: CIEU warning written
        cieu_records = cieu_store.query(event_type="obligation_trigger_skipped")
        assert len(cieu_records) == 1, \
            "Should write exactly one GracefulSkip warning to CIEU"

        skip_record = cieu_records[0]
        assert skip_record["passed"] is True, \
            "GracefulSkip is not a failure"
        assert skip_record["metadata"]["obligation_type"] == "security_incident_response"
        assert skip_record["metadata"]["reason"] == "obligation_type_not_registered"
        assert skip_record["metadata"]["trigger_id"] == "test_invalid_type"

    def test_rule_with_unregistered_obligation_type_graceful_skip(self):
        """
        OmissionRule references a non-existent obligation_type.
        Should:
          - Not create obligation
          - Write warning to CIEU
          - Not crash
        """
        # Setup
        store = InMemoryOmissionStore()
        cieu_store = MockCIEUStore()
        rule_registry = RuleRegistry()

        # Register rule with INVALID obligation_type
        rule = OmissionRule(
            rule_id="test_invalid_rule",
            name="Invalid Rule",
            description="This should be gracefully skipped",
            trigger_event_types=["task_created"],
            obligation_type="cieu_liveness_check",  # NOT REGISTERED
            required_event_types=["file_write"],
            due_within_secs=300,
            severity=Severity.MEDIUM,
        )
        rule_registry.register(rule)

        engine = OmissionEngine(
            store=store,
            registry=rule_registry,
            cieu_store=cieu_store,
            trigger_registry=None,
        )

        # Create entity
        entity = TrackedEntity(
            entity_id="task_1",
            entity_type="task",
            initiator_id="agent_1",
            current_owner_id="agent_1",
            status=EntityStatus.ACTIVE,
        )
        store.upsert_entity(entity)

        # Trigger event
        ev = GovernanceEvent(
            event_id="ev_1",
            event_type="task_created",
            entity_id="task_1",
            actor_id="agent_1",
            ts=time.time(),
            payload={},
        )

        # Ingest event
        result = engine.ingest_event(ev)

        # Assert: No obligation created
        assert len(result.new_obligations) == 0, \
            "GracefulSkip should prevent obligation creation for unregistered types"

        # Assert: CIEU warning written
        cieu_records = cieu_store.query(event_type="obligation_trigger_skipped")
        assert len(cieu_records) == 1, \
            "Should write exactly one GracefulSkip warning to CIEU"

        skip_record = cieu_records[0]
        assert skip_record["metadata"]["obligation_type"] == "cieu_liveness_check"
        assert skip_record["metadata"]["trigger_id"] == "test_invalid_rule"

    def test_mixed_valid_and_invalid_triggers(self):
        """
        Mix of valid and invalid triggers.
        Should:
          - Create obligations for valid triggers
          - Skip invalid triggers with warning
          - System continues normally
        """
        # Setup
        store = InMemoryOmissionStore()
        cieu_store = MockCIEUStore()
        trigger_registry = reset_trigger_registry()
        rule_registry = RuleRegistry()

        # Register VALID rule (uses built-in OmissionType)
        from ystar.governance.omission_models import OmissionType
        valid_rule = OmissionRule(
            rule_id="valid_rule",
            name="Valid Rule",
            description="This should work",
            trigger_event_types=["task_created"],
            obligation_type=OmissionType.REQUIRED_DELEGATION,
            required_event_types=["delegation_sent"],
            due_within_secs=300,
            severity=Severity.MEDIUM,
        )
        rule_registry.register(valid_rule)

        # Register INVALID trigger
        invalid_trigger = ObligationTrigger(
            trigger_id="invalid_trigger",
            trigger_tool_pattern=r"Write",
            obligation_type="nonexistent_type",  # NOT REGISTERED
            description="Should be skipped",
            target_agent="caller",
            deadline_seconds=300,
            severity="SOFT",
        )
        trigger_registry.register(invalid_trigger)

        engine = OmissionEngine(
            store=store,
            registry=rule_registry,
            cieu_store=cieu_store,
            trigger_registry=trigger_registry,
        )

        # Create entity
        entity = TrackedEntity(
            entity_id="task_1",
            entity_type="task",
            initiator_id="agent_1",
            current_owner_id="agent_1",
            status=EntityStatus.ACTIVE,
        )
        store.upsert_entity(entity)

        # Event 1: Trigger valid rule
        ev1 = GovernanceEvent(
            event_id="ev_1",
            event_type="task_created",
            entity_id="task_1",
            actor_id="agent_1",
            ts=time.time(),
            payload={},
        )
        result1 = engine.ingest_event(ev1)

        # Assert: Valid obligation created
        assert len(result1.new_obligations) == 1, \
            "Valid rule should create obligation"
        assert result1.new_obligations[0].obligation_type == OmissionType.REQUIRED_DELEGATION

        # Event 2: Trigger invalid trigger
        ev2 = GovernanceEvent(
            event_id="ev_2",
            event_type="tool_call",
            entity_id="task_1",
            actor_id="agent_1",
            ts=time.time(),
            payload={
                "tool_name": "Write",
                "tool_input": {"file_path": "/tmp/test.txt"},
                "decision": "ALLOW",
            },
        )
        result2 = engine.ingest_event(ev2)

        # Assert: Invalid trigger skipped
        assert len(result2.new_obligations) == 0, \
            "Invalid trigger should be skipped"

        # Assert: CIEU warning for invalid trigger
        skip_records = cieu_store.query(event_type="obligation_trigger_skipped")
        assert len(skip_records) == 1, \
            "Should have exactly one skip warning"
        assert skip_records[0]["metadata"]["trigger_id"] == "invalid_trigger"

    def test_no_violation_cascade_from_unregistered_type(self):
        """
        Ensure unregistered obligation types don't cause violation cascade.
        Before GracefulSkip: would create obligations that immediately violate.
        After GracefulSkip: no obligations created, no violations.
        """
        # Setup
        store = InMemoryOmissionStore()
        cieu_store = MockCIEUStore()
        trigger_registry = reset_trigger_registry()

        # Register 100 triggers with invalid types (simulate typo storm)
        for i in range(100):
            trigger = ObligationTrigger(
                trigger_id=f"invalid_trigger_{i}",
                trigger_tool_pattern=r"Write",
                obligation_type=f"invalid_type_{i}",
                description="Should all be skipped",
                target_agent="caller",
                deadline_seconds=1,  # Very short deadline
                severity="HARD",
            )
            trigger_registry.register(trigger)

        engine = OmissionEngine(
            store=store,
            registry=RuleRegistry(),
            cieu_store=cieu_store,
            trigger_registry=trigger_registry,
        )

        # Create entity
        entity = TrackedEntity(
            entity_id="session_1",
            entity_type="session",
            initiator_id="agent_1",
            current_owner_id="agent_1",
            status=EntityStatus.ACTIVE,
        )
        store.upsert_entity(entity)

        # Trigger all 100 invalid triggers
        ev = GovernanceEvent(
            event_id="ev_1",
            event_type="tool_call",
            entity_id="session_1",
            actor_id="agent_1",
            ts=time.time(),
            payload={
                "tool_name": "Write",
                "tool_input": {"file_path": "/tmp/test.txt"},
                "decision": "ALLOW",
            },
        )
        result = engine.ingest_event(ev)

        # Assert: No obligations created
        assert len(result.new_obligations) == 0, \
            "All invalid triggers should be gracefully skipped"

        # Wait for "deadline" to pass
        time.sleep(0.1)

        # Scan for violations
        scan_result = engine.scan()

        # Assert: No violations
        assert len(scan_result.violations) == 0, \
            "GracefulSkip prevents violation cascade"
        assert len(scan_result.expired) == 0, \
            "No expired obligations because none were created"

        # Assert: 100 skip warnings in CIEU
        skip_records = cieu_store.query(event_type="obligation_trigger_skipped")
        assert len(skip_records) == 100, \
            "Should have 100 skip warnings, one per invalid trigger"
