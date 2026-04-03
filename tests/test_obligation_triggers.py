"""
Tests for ObligationTrigger framework (Directive #015).

Tests cover:
  - TriggerRegistry correctly matches web_search tool calls to trigger #1
  - TriggerRegistry correctly matches content/ writes to trigger #9
  - Unmatched tool calls produce no triggers
  - Created obligations have correct deadlines and severity
  - Multiple triggers can fire from a single tool call
  - Trigger #7 fires on DENY results
  - Integration with OmissionEngine
"""
from __future__ import annotations

import time
import pytest
from ystar.governance.obligation_triggers import (
    ObligationTrigger,
    TriggerRegistry,
    match_triggers,
    create_obligation_from_trigger,
    register_default_triggers,
    reset_trigger_registry,
)
from ystar.governance.omission_models import (
    GovernanceEvent,
    ObligationStatus,
    OmissionType,
    Severity,
)
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_rules import RuleRegistry
from ystar.adapters.omission_adapter import OmissionAdapter


# ── Test Trigger Registry ──────────────────────────────────────────────────


def test_trigger_registry_register_and_get():
    """Test basic registry operations."""
    registry = TriggerRegistry()

    trigger = ObligationTrigger(
        trigger_id="test_trigger",
        trigger_tool_pattern=r"TestTool",
        obligation_type=OmissionType.TEST_OBLIGATION,
        description="Test description",
        target_agent="caller",
        deadline_seconds=300,
    )

    registry.register(trigger)

    assert registry.get("test_trigger") == trigger
    assert len(registry.all_enabled()) == 1


def test_trigger_registry_disabled_triggers_excluded():
    """Test that disabled triggers are not returned by all_enabled()."""
    registry = TriggerRegistry()

    trigger1 = ObligationTrigger(
        trigger_id="enabled",
        trigger_tool_pattern=r"Tool1",
        obligation_type=OmissionType.OBLIGATION1,
        description="Enabled",
        target_agent="caller",
        deadline_seconds=300,
        enabled=True,
    )

    trigger2 = ObligationTrigger(
        trigger_id="disabled",
        trigger_tool_pattern=r"Tool2",
        obligation_type=OmissionType.OBLIGATION2,
        description="Disabled",
        target_agent="caller",
        deadline_seconds=300,
        enabled=False,
    )

    registry.register(trigger1)
    registry.register(trigger2)

    enabled = registry.all_enabled()
    assert len(enabled) == 1
    assert enabled[0].trigger_id == "enabled"


# ── Test Trigger Matching ──────────────────────────────────────────────────


def test_match_triggers_web_search():
    """Test that web_search tool calls match trigger #1 (research knowledge update)."""
    registry = TriggerRegistry()
    register_default_triggers(registry)

    # Test various web search tool names
    for tool_name in ["web_search", "WebSearch", "WebFetch"]:
        matches = match_triggers(registry, tool_name, {"query": "test"}, "CMO")
        assert len(matches) >= 1
        assert any(m.trigger_id == "research_knowledge_update" for m in matches)


def test_match_triggers_content_write():
    """Test that content/ writes match trigger #9 (content accuracy review)."""
    registry = TriggerRegistry()
    register_default_triggers(registry)

    # Test Write to content/
    matches = match_triggers(
        registry, "Write",
        {"file_path": "content/article.md", "content": "test"},
        "CMO"
    )
    assert len(matches) >= 1
    assert any(m.trigger_id == "content_accuracy_review" for m in matches)

    # Test Edit to marketing/
    matches = match_triggers(
        registry, "Edit",
        {"file_path": "marketing/campaign.md", "old_string": "x", "new_string": "y"},
        "CMO"
    )
    assert len(matches) >= 1
    assert any(m.trigger_id == "content_accuracy_review" for m in matches)


def test_match_triggers_unmatched_tool():
    """Test that unmatched tool calls produce no triggers."""
    registry = TriggerRegistry()
    register_default_triggers(registry)

    # Test tool that should not match any default triggers
    matches = match_triggers(registry, "Read", {"file_path": "test.txt"}, "CTO")
    # Read should not trigger any of the 4 priority triggers
    assert len(matches) == 0


def test_match_triggers_deny_result():
    """Test that trigger #7 fires on DENY results."""
    registry = TriggerRegistry()
    register_default_triggers(registry)

    # Mock PolicyResult with DENY
    class MockPolicyResult:
        allowed = False

    matches = match_triggers(
        registry, "Write",
        {"file_path": "forbidden.txt"},
        "CMO",
        check_result=MockPolicyResult()
    )

    # Should match failure case documentation trigger
    assert any(m.trigger_id == "failure_case_documentation" for m in matches)


def test_match_triggers_allow_result_no_deny_trigger():
    """Test that trigger #7 does NOT fire on ALLOW results."""
    registry = TriggerRegistry()
    register_default_triggers(registry)

    # Mock PolicyResult with ALLOW
    class MockPolicyResult:
        allowed = True

    matches = match_triggers(
        registry, "Write",
        {"file_path": "allowed.txt"},
        "CMO",
        check_result=MockPolicyResult()
    )

    # Should NOT match failure case documentation trigger
    assert not any(m.trigger_id == "failure_case_documentation" for m in matches)


def test_multiple_triggers_can_fire():
    """Test that multiple triggers can fire from a single tool call."""
    registry = TriggerRegistry()

    # Register two triggers that match the same tool
    trigger1 = ObligationTrigger(
        trigger_id="trigger1",
        trigger_tool_pattern=r"Write",
        obligation_type=OmissionType.OBLIGATION1,
        description="First trigger",
        target_agent="caller",
        deadline_seconds=300,
    )

    trigger2 = ObligationTrigger(
        trigger_id="trigger2",
        trigger_tool_pattern=r"Write",
        obligation_type=OmissionType.OBLIGATION2,
        description="Second trigger",
        target_agent="caller",
        deadline_seconds=600,
    )

    registry.register(trigger1)
    registry.register(trigger2)

    matches = match_triggers(registry, "Write", {"file_path": "test.txt"}, "CTO")
    assert len(matches) == 2
    assert set(m.trigger_id for m in matches) == {"trigger1", "trigger2"}


# ── Test Obligation Creation ───────────────────────────────────────────────


def test_create_obligation_from_trigger():
    """Test that obligations are created with correct deadlines and severity."""
    # Setup
    store = InMemoryOmissionStore()
    rule_registry = RuleRegistry()
    engine = OmissionEngine(store=store, registry=rule_registry)
    adapter = OmissionAdapter(engine=engine)

    trigger = ObligationTrigger(
        trigger_id="test_trigger",
        trigger_tool_pattern=r"TestTool",
        obligation_type=OmissionType.TEST_OBLIGATION,
        description="Test obligation",
        target_agent="caller",
        deadline_seconds=1800,  # 30 minutes
        severity="SOFT",
        grace_period_secs=180,
        hard_overdue_secs=3600,
    )

    now = time.time()

    # Register entity first
    from ystar.governance.omission_models import TrackedEntity, EntityStatus
    entity = TrackedEntity(
        entity_id="test_session",
        entity_type="session",
        initiator_id="system",
        current_owner_id="TestAgent",
        status=EntityStatus.ACTIVE,
    )
    store.upsert_entity(entity)

    # Create obligation
    obligation = create_obligation_from_trigger(
        trigger=trigger,
        agent_id="TestAgent",
        session_id="test_session",
        omission_adapter=adapter,
        tool_name="TestTool",
        tool_input={"param": "value"},
    )

    assert obligation is not None
    assert obligation.obligation_type == "test_obligation"
    assert obligation.actor_id == "TestAgent"
    assert obligation.entity_id == "test_session"
    assert obligation.status == ObligationStatus.PENDING

    # Check deadline
    assert obligation.due_at is not None
    assert obligation.due_at >= now + 1700  # Should be ~1800 seconds from now
    assert obligation.due_at <= now + 1900

    # Check severity
    assert obligation.severity == Severity.MEDIUM  # SOFT maps to MEDIUM


def test_create_obligation_target_agent_resolution():
    """Test that target_agent 'caller' is resolved correctly."""
    store = InMemoryOmissionStore()
    rule_registry = RuleRegistry()
    engine = OmissionEngine(store=store, registry=rule_registry)
    adapter = OmissionAdapter(engine=engine)

    # Register entity
    from ystar.governance.omission_models import TrackedEntity, EntityStatus
    entity = TrackedEntity(
        entity_id="test_session",
        entity_type="session",
        initiator_id="system",
        current_owner_id="TestAgent",
        status=EntityStatus.ACTIVE,
    )
    store.upsert_entity(entity)

    # Test 'caller' resolution
    trigger1 = ObligationTrigger(
        trigger_id="trigger1",
        trigger_tool_pattern=r"TestTool",
        obligation_type=OmissionType.OBLIGATION1,
        description="Test",
        target_agent="caller",
        deadline_seconds=300,
    )

    obligation1 = create_obligation_from_trigger(
        trigger=trigger1,
        agent_id="CMO",
        session_id="test_session",
        omission_adapter=adapter,
    )

    assert obligation1.actor_id == "CMO"

    # Test specific agent
    trigger2 = ObligationTrigger(
        trigger_id="trigger2",
        trigger_tool_pattern=r"TestTool",
        obligation_type=OmissionType.OBLIGATION2,
        description="Test",
        target_agent="CTO",
        deadline_seconds=300,
    )

    obligation2 = create_obligation_from_trigger(
        trigger=trigger2,
        agent_id="CMO",
        session_id="test_session",
        omission_adapter=adapter,
    )

    assert obligation2.actor_id == "CTO"


def test_create_obligation_deduplicate():
    """Test that deduplicate prevents creating duplicate obligations."""
    store = InMemoryOmissionStore()
    rule_registry = RuleRegistry()
    engine = OmissionEngine(store=store, registry=rule_registry)
    adapter = OmissionAdapter(engine=engine)

    # Register entity
    from ystar.governance.omission_models import TrackedEntity, EntityStatus
    entity = TrackedEntity(
        entity_id="test_session",
        entity_type="session",
        initiator_id="system",
        current_owner_id="TestAgent",
        status=EntityStatus.ACTIVE,
    )
    store.upsert_entity(entity)

    trigger = ObligationTrigger(
        trigger_id="test_trigger",
        trigger_tool_pattern=r"TestTool",
        obligation_type=OmissionType.TEST_OBLIGATION,
        description="Test",
        target_agent="caller",
        deadline_seconds=300,
        deduplicate=True,
    )

    # Create first obligation
    ob1 = create_obligation_from_trigger(
        trigger=trigger,
        agent_id="TestAgent",
        session_id="test_session",
        omission_adapter=adapter,
    )

    assert ob1 is not None

    # Try to create duplicate
    ob2 = create_obligation_from_trigger(
        trigger=trigger,
        agent_id="TestAgent",
        session_id="test_session",
        omission_adapter=adapter,
    )

    # Should be None due to deduplication
    assert ob2 is None


def test_create_obligation_no_deduplicate():
    """Test that deduplicate=False allows duplicate obligations."""
    store = InMemoryOmissionStore()
    rule_registry = RuleRegistry()
    engine = OmissionEngine(store=store, registry=rule_registry)
    adapter = OmissionAdapter(engine=engine)

    # Register entity
    from ystar.governance.omission_models import TrackedEntity, EntityStatus
    entity = TrackedEntity(
        entity_id="test_session",
        entity_type="session",
        initiator_id="system",
        current_owner_id="TestAgent",
        status=EntityStatus.ACTIVE,
    )
    store.upsert_entity(entity)

    trigger = ObligationTrigger(
        trigger_id="test_trigger",
        trigger_tool_pattern=r"TestTool",
        obligation_type=OmissionType.TEST_OBLIGATION,
        description="Test",
        target_agent="caller",
        deadline_seconds=300,
        deduplicate=False,
    )

    # Create first obligation
    ob1 = create_obligation_from_trigger(
        trigger=trigger,
        agent_id="TestAgent",
        session_id="test_session",
        omission_adapter=adapter,
    )

    assert ob1 is not None

    # Create second obligation (should succeed)
    ob2 = create_obligation_from_trigger(
        trigger=trigger,
        agent_id="TestAgent",
        session_id="test_session",
        omission_adapter=adapter,
    )

    assert ob2 is not None
    assert ob1.obligation_id != ob2.obligation_id


# ── Test Default Triggers ──────────────────────────────────────────────────


def test_default_triggers_registered():
    """Test that register_default_triggers creates all 4 priority triggers."""
    registry = TriggerRegistry()
    register_default_triggers(registry)

    triggers = registry.all_enabled()
    trigger_ids = {t.trigger_id for t in triggers}

    # Check that all 4 priority triggers are present
    assert "research_knowledge_update" in trigger_ids
    assert "session_token_recording" in trigger_ids
    assert "failure_case_documentation" in trigger_ids
    assert "content_accuracy_review" in trigger_ids


def test_trigger_serialization():
    """Test that triggers can be serialized and deserialized."""
    trigger = ObligationTrigger(
        trigger_id="test_trigger",
        trigger_tool_pattern=r"TestTool",
        obligation_type=OmissionType.TEST_OBLIGATION,
        description="Test description",
        target_agent="caller",
        deadline_seconds=1800,
        severity="SOFT",
        verification_hint="test hint",
    )

    # Serialize
    data = trigger.to_dict()

    # Deserialize
    trigger2 = ObligationTrigger.from_dict(data)

    assert trigger2.trigger_id == trigger.trigger_id
    assert trigger2.trigger_tool_pattern == trigger.trigger_tool_pattern
    assert trigger2.obligation_type == trigger.obligation_type
    assert trigger2.deadline_seconds == trigger.deadline_seconds
    assert trigger2.severity == trigger.severity


def test_registry_serialization():
    """Test that registry can be serialized and deserialized."""
    registry = TriggerRegistry()
    register_default_triggers(registry)

    # Serialize
    data = registry.to_dict()

    # Deserialize
    registry2 = TriggerRegistry.from_dict(data)

    assert len(registry2.all_enabled()) == len(registry.all_enabled())

    # Check one trigger as sample
    trigger1 = registry.get("research_knowledge_update")
    trigger2 = registry2.get("research_knowledge_update")

    assert trigger1 is not None
    assert trigger2 is not None
    assert trigger1.trigger_id == trigger2.trigger_id
    assert trigger1.obligation_type == trigger2.obligation_type


# ── Integration Tests ──────────────────────────────────────────────────────


def test_integration_trigger_creates_obligation_in_engine():
    """Test full integration: trigger -> event -> obligation in engine."""
    # Setup
    store = InMemoryOmissionStore()
    rule_registry = RuleRegistry()
    engine = OmissionEngine(store=store, registry=rule_registry)
    adapter = OmissionAdapter(engine=engine)

    # Register entity
    from ystar.governance.omission_models import TrackedEntity, EntityStatus
    entity = TrackedEntity(
        entity_id="test_session",
        entity_type="session",
        initiator_id="system",
        current_owner_id="TestAgent",
        status=EntityStatus.ACTIVE,
    )
    store.upsert_entity(entity)

    # Register trigger
    trigger = ObligationTrigger(
        trigger_id="integration_test",
        trigger_tool_pattern=r"TestTool",
        obligation_type=OmissionType.INTEGRATION_OBLIGATION,
        description="Integration test",
        target_agent="caller",
        deadline_seconds=300,
    )

    # Create obligation via trigger
    obligation = create_obligation_from_trigger(
        trigger=trigger,
        agent_id="TestAgent",
        session_id="test_session",
        omission_adapter=adapter,
    )

    assert obligation is not None

    # Verify obligation exists in store
    obligations = store.list_obligations(entity_id="test_session")
    assert len(obligations) == 1
    assert obligations[0].obligation_type == OmissionType.INTEGRATION_OBLIGATION
    assert obligations[0].status == ObligationStatus.PENDING


def test_integration_obligation_expires_and_creates_violation():
    """Test that triggered obligation expires and creates violation."""
    # Setup with fake time
    now = time.time()
    store = InMemoryOmissionStore()
    rule_registry = RuleRegistry()
    engine = OmissionEngine(store=store, registry=rule_registry, now_fn=lambda: now)
    adapter = OmissionAdapter(engine=engine)

    # Register entity
    from ystar.governance.omission_models import TrackedEntity, EntityStatus
    entity = TrackedEntity(
        entity_id="test_session",
        entity_type="session",
        initiator_id="system",
        current_owner_id="TestAgent",
        status=EntityStatus.ACTIVE,
    )
    store.upsert_entity(entity)

    # Register trigger with short deadline
    trigger = ObligationTrigger(
        trigger_id="expiry_test",
        trigger_tool_pattern=r"TestTool",
        obligation_type=OmissionType.EXPIRY_OBLIGATION,
        description="Expiry test",
        target_agent="caller",
        deadline_seconds=10,  # 10 seconds
        severity="SOFT",
    )

    # Create obligation
    obligation = create_obligation_from_trigger(
        trigger=trigger,
        agent_id="TestAgent",
        session_id="test_session",
        omission_adapter=adapter,
    )

    assert obligation is not None

    # Advance time past deadline
    fake_now = now + 15  # 15 seconds later
    engine._now = lambda: fake_now

    # Scan for violations
    result = engine.scan(now=fake_now)

    # Should have a violation
    assert len(result.violations) > 0
    assert result.violations[0].obligation_id == obligation.obligation_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
