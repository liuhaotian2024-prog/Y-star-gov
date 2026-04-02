"""
tests/test_trigger_activation.py — Automatic Obligation Trigger Activation
===========================================================================

Test that OmissionEngine automatically matches and activates ObligationTriggers
when tool call events are ingested, without requiring hook layer intervention.

Test cases:
  1. test_ingest_event_auto_triggers_obligation
     - When a tool_call event is ingested that matches a trigger
     - Then obligation should be automatically created

  2. test_duplicate_trigger_deduplication
     - When multiple tool_call events match the same trigger
     - Then only one obligation should be created (deduplicate=True)

  3. test_no_trigger_match_no_obligation
     - When a tool_call event doesn't match any trigger
     - Then no obligation should be created
"""

import time
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_models import (
    TrackedEntity, GovernanceEvent, EntityStatus, ObligationStatus
)
from ystar.governance.obligation_triggers import (
    ObligationTrigger, TriggerRegistry, reset_trigger_registry
)


def test_ingest_event_auto_triggers_obligation():
    """
    When a tool_call event matching a trigger is ingested,
    OmissionEngine should automatically create the obligation.
    """
    # Setup
    store = InMemoryOmissionStore()
    registry = reset_trigger_registry()

    # Register a trigger for WebSearch
    trigger = ObligationTrigger(
        trigger_id="test_web_search_trigger",
        trigger_tool_pattern=r"WebSearch",
        obligation_type="knowledge_update_required",
        description="After web search, update knowledge",
        target_agent="caller",
        deadline_seconds=1800,
        severity="SOFT",
        deduplicate=True,
    )
    registry.register(trigger)

    # Create engine with trigger registry
    now = time.time()
    engine = OmissionEngine(
        store=store,
        registry=None,  # Use default registry (for rules)
        now_fn=lambda: now,
        trigger_registry=registry,  # Pass trigger registry
    )

    # Register entity
    entity = TrackedEntity(
        entity_id="session_1",
        entity_type="session",
        initiator_id="agent_researcher",
        current_owner_id="agent_researcher",
        status=EntityStatus.ACTIVE,
    )
    engine.register_entity(entity)

    # Create a tool_call event for WebSearch
    event = GovernanceEvent(
        event_id="evt_1",
        event_type="tool_call",
        entity_id="session_1",
        actor_id="agent_researcher",
        ts=now,
        payload={
            "tool_name": "WebSearch",
            "tool_input": {"query": "Y*gov governance frameworks"},
            "decision": "ALLOW",
        },
    )

    # Ingest event - should automatically match trigger and create obligation
    result = engine.ingest_event(event)

    # Verify obligation was created
    assert len(result.new_obligations) == 1
    ob = result.new_obligations[0]
    assert ob.obligation_type == "knowledge_update_required"
    assert ob.actor_id == "agent_researcher"  # target_agent="caller"
    assert ob.status == ObligationStatus.PENDING

    # Verify obligation is in store
    pending = store.pending_obligations()
    assert len(pending) == 1
    assert pending[0].obligation_id == ob.obligation_id


def test_duplicate_trigger_deduplication():
    """
    When the same trigger fires multiple times with deduplicate=True,
    only one obligation should be created.
    """
    # Setup
    store = InMemoryOmissionStore()
    registry = reset_trigger_registry()

    # Register trigger with deduplicate=True
    trigger = ObligationTrigger(
        trigger_id="test_dedup_trigger",
        trigger_tool_pattern=r"WebSearch",
        obligation_type="knowledge_update_required",
        description="After web search, update knowledge",
        target_agent="caller",
        deadline_seconds=1800,
        severity="SOFT",
        deduplicate=True,  # Key: deduplicate enabled
    )
    registry.register(trigger)

    now = time.time()
    engine = OmissionEngine(store=store, now_fn=lambda: now, trigger_registry=registry)

    # Register entity
    entity = TrackedEntity(
        entity_id="session_1",
        entity_type="session",
        initiator_id="agent_researcher",
        current_owner_id="agent_researcher",
        status=EntityStatus.ACTIVE,
    )
    engine.register_entity(entity)

    # First tool call
    event1 = GovernanceEvent(
        event_id="evt_1",
        event_type="tool_call",
        entity_id="session_1",
        actor_id="agent_researcher",
        ts=now,
        payload={
            "tool_name": "WebSearch",
            "tool_input": {"query": "first query"},
            "decision": "ALLOW",
        },
    )
    result1 = engine.ingest_event(event1)
    assert len(result1.new_obligations) == 1

    # Second tool call (same trigger, same agent, same entity)
    event2 = GovernanceEvent(
        event_id="evt_2",
        event_type="tool_call",
        entity_id="session_1",
        actor_id="agent_researcher",
        ts=now + 10,
        payload={
            "tool_name": "WebSearch",
            "tool_input": {"query": "second query"},
            "decision": "ALLOW",
        },
    )
    result2 = engine.ingest_event(event2)

    # Should NOT create second obligation (deduplication)
    assert len(result2.new_obligations) == 0

    # Verify only one obligation in store
    pending = store.pending_obligations()
    assert len(pending) == 1


def test_no_trigger_match_no_obligation():
    """
    When a tool_call event doesn't match any trigger,
    no obligation should be created.
    """
    # Setup
    store = InMemoryOmissionStore()
    registry = reset_trigger_registry()

    # Register trigger for WebSearch only
    trigger = ObligationTrigger(
        trigger_id="test_web_only",
        trigger_tool_pattern=r"WebSearch",
        obligation_type="knowledge_update_required",
        description="After web search, update knowledge",
        target_agent="caller",
        deadline_seconds=1800,
        severity="SOFT",
    )
    registry.register(trigger)

    now = time.time()
    engine = OmissionEngine(store=store, now_fn=lambda: now, trigger_registry=registry)

    # Register entity
    entity = TrackedEntity(
        entity_id="session_1",
        entity_type="session",
        initiator_id="agent_researcher",
        current_owner_id="agent_researcher",
        status=EntityStatus.ACTIVE,
    )
    engine.register_entity(entity)

    # Create tool_call event for different tool (Read)
    event = GovernanceEvent(
        event_id="evt_1",
        event_type="tool_call",
        entity_id="session_1",
        actor_id="agent_dev",
        ts=now,
        payload={
            "tool_name": "Read",
            "tool_input": {"file_path": "/some/file.py"},
            "decision": "ALLOW",
        },
    )

    # Ingest event
    result = engine.ingest_event(event)

    # Should NOT create any obligation
    assert len(result.new_obligations) == 0

    # Verify no obligations in store
    pending = store.pending_obligations()
    assert len(pending) == 0


def test_trigger_with_param_filter():
    """
    When a trigger has param filters, only matching params should trigger.
    """
    # Setup
    store = InMemoryOmissionStore()
    registry = reset_trigger_registry()

    # Register trigger that only fires for content/ writes
    trigger = ObligationTrigger(
        trigger_id="test_content_write",
        trigger_tool_pattern=r"Write|Edit",
        trigger_param_filter={"file_path": ["content/", "marketing/"]},
        obligation_type="technical_review_required",
        description="Content writes require review",
        target_agent="technical_reviewer",
        deadline_seconds=7200,
        severity="SOFT",
    )
    registry.register(trigger)

    now = time.time()
    engine = OmissionEngine(store=store, now_fn=lambda: now, trigger_registry=registry)

    # Register entity
    entity = TrackedEntity(
        entity_id="session_1",
        entity_type="session",
        initiator_id="agent_researcher",
        current_owner_id="agent_researcher",
        status=EntityStatus.ACTIVE,
    )
    engine.register_entity(entity)

    # Test 1: Write to content/ should trigger
    event1 = GovernanceEvent(
        event_id="evt_1",
        event_type="tool_call",
        entity_id="session_1",
        actor_id="agent_writer",
        ts=now,
        payload={
            "tool_name": "Write",
            "tool_input": {"file_path": "content/blog/post.md"},
            "decision": "ALLOW",
        },
    )
    result1 = engine.ingest_event(event1)
    assert len(result1.new_obligations) == 1

    # Test 2: Write to code/ should NOT trigger
    event2 = GovernanceEvent(
        event_id="evt_2",
        event_type="tool_call",
        entity_id="session_1",
        actor_id="agent_writer",
        ts=now + 10,
        payload={
            "tool_name": "Write",
            "tool_input": {"file_path": "src/code.py"},
            "decision": "ALLOW",
        },
    )
    result2 = engine.ingest_event(event2)
    assert len(result2.new_obligations) == 0


def test_trigger_only_fires_on_allow():
    """
    Triggers should only fire when tool decision is ALLOW.
    """
    # Setup
    store = InMemoryOmissionStore()
    registry = reset_trigger_registry()

    trigger = ObligationTrigger(
        trigger_id="test_allow_only",
        trigger_tool_pattern=r"WebSearch",
        obligation_type="knowledge_update_required",
        description="After web search, update knowledge",
        target_agent="caller",
        deadline_seconds=1800,
        severity="SOFT",
    )
    registry.register(trigger)

    now = time.time()
    engine = OmissionEngine(store=store, now_fn=lambda: now, trigger_registry=registry)

    # Register entity
    entity = TrackedEntity(
        entity_id="session_1",
        entity_type="session",
        initiator_id="agent_researcher",
        current_owner_id="agent_researcher",
        status=EntityStatus.ACTIVE,
    )
    engine.register_entity(entity)

    # Create tool_call event with DENY decision
    event = GovernanceEvent(
        event_id="evt_1",
        event_type="tool_call",
        entity_id="session_1",
        actor_id="agent_researcher",
        ts=now,
        payload={
            "tool_name": "WebSearch",
            "tool_input": {"query": "test"},
            "decision": "DENY",
        },
    )

    # Ingest event
    result = engine.ingest_event(event)

    # Should NOT create obligation (tool was denied)
    assert len(result.new_obligations) == 0
