#!/usr/bin/env python3
"""
test_auto_fulfillment_9types.py — Auto-Fulfillment Pattern Matching for 9 Obligation Types

Tests the v0.50 auto-fulfillment logic added to OmissionEngine._try_fulfill and
_matches_fulfiller_pattern methods.

Post-mortem trigger:
  ystar-company/knowledge/ceo/lessons/governance_self_deadlock_20260413.md

Author: Maya Patel (eng-governance)
Date: 2026-04-13
"""

import pytest
import time
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_models import (
    ObligationRecord, ObligationStatus, GovernanceEvent, Severity
)
from ystar.governance.omission_rules import get_registry


# ── Test 1: directive_acknowledgement auto-fulfill ───────────────────────────

def test_directive_acknowledgement_auto_fulfill():
    """
    Test that assistant_response event auto-fulfills directive_acknowledgement obligation.
    This is the exact failure mode that hard-locked CEO for 35 minutes.
    """
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, registry=get_registry())

    # Create directive_acknowledgement obligation manually
    ob = ObligationRecord(
        obligation_id="ob1",
        entity_id="board_message_123",
        actor_id="ceo",
        obligation_type="directive_acknowledgement",
        required_event_types=["DIRECTIVE_ACKNOWLEDGED"],  # Original required event
        status=ObligationStatus.PENDING,
        due_at=time.time() + 120,  # 120s deadline
        created_at=time.time(),
    )
    store.add_obligation(ob)

    # Emit assistant_response event (agent responds to Board)
    ev = GovernanceEvent(
        event_id="ev1",
        event_type="assistant_response",
        entity_id="board_message_123",
        actor_id="ceo",
        ts=time.time(),
    )
    result = engine.ingest_event(ev)

    # Verify obligation auto-fulfilled
    assert len(result.fulfilled) == 1
    assert result.fulfilled[0].obligation_id == "ob1"
    assert result.fulfilled[0].status == ObligationStatus.FULFILLED
    assert result.fulfilled[0].fulfilled_by_event_id == "ev1"


# ── Test 2: intent_declaration auto-fulfill ──────────────────────────────────

def test_intent_declaration_auto_fulfill():
    """Test INTENT_DECLARED event auto-fulfills intent_declaration obligation."""
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, registry=get_registry())

    ob = ObligationRecord(
        obligation_id="ob2",
        entity_id="governance_change_456",
        actor_id="eng-governance",
        obligation_type="intent_declaration",
        required_event_types=["INTENT_DECLARED"],
        status=ObligationStatus.PENDING,
        due_at=time.time() + 300,
    )
    store.add_obligation(ob)

    ev = GovernanceEvent(
        event_id="ev2",
        event_type="INTENT_DECLARED",
        entity_id="governance_change_456",
        actor_id="eng-governance",
        ts=time.time(),
        payload={"scope": "governance", "summary": "Add auto-fulfillment"},
    )
    result = engine.ingest_event(ev)

    assert len(result.fulfilled) == 1
    assert result.fulfilled[0].obligation_type == "intent_declaration"


# ── Test 3: progress_update with git_commit ──────────────────────────────────

def test_progress_update_git_commit_auto_fulfill():
    """Test git_commit event auto-fulfills progress_update obligation."""
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, registry=get_registry())

    ob = ObligationRecord(
        obligation_id="ob3",
        entity_id="task_789",
        actor_id="eng-kernel",
        obligation_type="progress_update",
        required_event_types=["PROGRESS_UPDATE", "git_commit"],
        status=ObligationStatus.PENDING,
        due_at=time.time() + 1800,  # 30min
    )
    store.add_obligation(ob)

    # Emit git_commit event
    ev = GovernanceEvent(
        event_id="ev3",
        event_type="git_commit",
        entity_id="task_789",
        actor_id="eng-kernel",
        ts=time.time(),
        payload={"commit_sha": "abc123", "message": "wip: kernel refactor"},
    )
    result = engine.ingest_event(ev)

    assert len(result.fulfilled) == 1
    assert result.fulfilled[0].obligation_type == "progress_update"


# ── Test 4: task_completion_report with git_commit ───────────────────────────

def test_task_completion_git_commit_auto_fulfill():
    """Test git_commit with feat/fix prefix auto-fulfills task_completion_report."""
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, registry=get_registry())

    ob = ObligationRecord(
        obligation_id="ob4",
        entity_id="task_001",
        actor_id="eng-platform",
        obligation_type="task_completion_report",
        required_event_types=["TASK_COMPLETED", "git_commit"],
        status=ObligationStatus.PENDING,
        due_at=time.time() + 3600,  # 1h
    )
    store.add_obligation(ob)

    ev = GovernanceEvent(
        event_id="ev4",
        event_type="git_commit",
        entity_id="task_001",
        actor_id="eng-platform",
        ts=time.time(),
        payload={"commit_sha": "def456", "message": "feat: add MCP server"},
    )
    result = engine.ingest_event(ev)

    assert len(result.fulfilled) == 1


# ── Test 5: knowledge_update with git_commit (path filter) ───────────────────

def test_knowledge_update_git_commit_auto_fulfill():
    """Test git_commit touching knowledge/ auto-fulfills knowledge_update."""
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, registry=get_registry())

    ob = ObligationRecord(
        obligation_id="ob5",
        entity_id="knowledge_sync_002",
        actor_id="eng-domains",
        obligation_type="knowledge_update",
        required_event_types=["KNOWLEDGE_UPDATED", "git_commit"],
        status=ObligationStatus.PENDING,
        due_at=time.time() + 21600,  # 6h
    )
    store.add_obligation(ob)

    ev = GovernanceEvent(
        event_id="ev5",
        event_type="git_commit",
        entity_id="knowledge_sync_002",
        actor_id="eng-domains",
        ts=time.time(),
        payload={
            "commit_sha": "ghi789",
            "message": "docs: update domains lessons",
            "files_changed": ["knowledge/eng-domains/lessons/gap_analysis.md"],
        },
    )
    result = engine.ingest_event(ev)

    assert len(result.fulfilled) == 1
    assert result.fulfilled[0].obligation_type == "knowledge_update"


# ── Test 6: autonomous_daily_report ───────────────────────────────────────────

def test_autonomous_daily_report_auto_fulfill():
    """Test DAILY_REPORT_SUBMITTED event auto-fulfills autonomous_daily_report."""
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, registry=get_registry())

    ob = ObligationRecord(
        obligation_id="ob6",
        entity_id="daily_report_20260413",
        actor_id="cto",
        obligation_type="autonomous_daily_report",
        required_event_types=["DAILY_REPORT_SUBMITTED"],
        status=ObligationStatus.PENDING,
        due_at=time.time() + 86400,  # 24h
    )
    store.add_obligation(ob)

    ev = GovernanceEvent(
        event_id="ev6",
        event_type="DAILY_REPORT_SUBMITTED",
        entity_id="daily_report_20260413",
        actor_id="cto",
        ts=time.time(),
        payload={"report_path": "reports/autonomous/cto_20260413.md"},
    )
    result = engine.ingest_event(ev)

    assert len(result.fulfilled) == 1


# ── Test 7: Actor mismatch does NOT fulfill ──────────────────────────────────

def test_actor_mismatch_no_fulfill():
    """
    Test that event with wrong actor_id does NOT fulfill obligation.
    Pattern has $OBLIGATION_ACTOR_ID template — must match exactly.
    """
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, registry=get_registry())

    ob = ObligationRecord(
        obligation_id="ob7",
        entity_id="msg_999",
        actor_id="ceo",  # Obligation for CEO
        obligation_type="directive_acknowledgement",
        required_event_types=["DIRECTIVE_ACKNOWLEDGED"],
        status=ObligationStatus.PENDING,
        due_at=time.time() + 120,
    )
    store.add_obligation(ob)

    # Event from different actor (CTO instead of CEO)
    ev = GovernanceEvent(
        event_id="ev7",
        event_type="assistant_response",
        entity_id="msg_999",
        actor_id="cto",  # WRONG ACTOR
        ts=time.time(),
    )
    result = engine.ingest_event(ev)

    # Should NOT fulfill (actor mismatch)
    assert len(result.fulfilled) == 0

    # Obligation should still be PENDING
    ob_after = store.get_obligation("ob7")
    assert ob_after.status == ObligationStatus.PENDING


# ── Test 8: SOFT_OVERDUE obligation can still be auto-fulfilled ──────────────

def test_soft_overdue_auto_fulfill():
    """
    Test that SOFT_OVERDUE obligation can still be fulfilled via auto-fulfillment.
    This is the restoration path after soft timeout.
    """
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, registry=get_registry())

    ob = ObligationRecord(
        obligation_id="ob8",
        entity_id="late_task_111",
        actor_id="eng-governance",
        obligation_type="progress_update",
        required_event_types=["PROGRESS_UPDATE", "git_commit"],
        status=ObligationStatus.SOFT_OVERDUE,  # Already soft overdue
        due_at=time.time() - 100,  # Past deadline
        soft_violation_at=time.time() - 50,
    )
    store.add_obligation(ob)

    # Agent commits late (after soft violation)
    ev = GovernanceEvent(
        event_id="ev8",
        event_type="git_commit",
        entity_id="late_task_111",
        actor_id="eng-governance",
        ts=time.time(),
    )
    result = engine.ingest_event(ev)

    # Should fulfill despite being SOFT_OVERDUE
    assert len(result.fulfilled) == 1
    assert result.fulfilled[0].status == ObligationStatus.FULFILLED


# ── Test 9: Multiple event types in pattern ──────────────────────────────────

def test_multiple_event_types_in_pattern():
    """
    Test fulfiller pattern with list of event_types (e.g., ["git_commit", "PROGRESS_UPDATE"]).
    Either event type should fulfill the obligation.
    """
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, registry=get_registry())

    ob = ObligationRecord(
        obligation_id="ob9",
        entity_id="task_multi",
        actor_id="eng-kernel",
        obligation_type="progress_update",
        required_event_types=["PROGRESS_UPDATE", "git_commit"],
        status=ObligationStatus.PENDING,
        due_at=time.time() + 1800,
    )
    store.add_obligation(ob)

    # First try: PROGRESS_UPDATE event
    ev1 = GovernanceEvent(
        event_id="ev9a",
        event_type="PROGRESS_UPDATE",
        entity_id="task_multi",
        actor_id="eng-kernel",
        ts=time.time(),
    )
    result1 = engine.ingest_event(ev1)
    assert len(result1.fulfilled) == 1

    # Reset obligation to PENDING for second test
    ob.status = ObligationStatus.PENDING
    ob.fulfilled_by_event_id = None
    store.update_obligation(ob)

    # Second try: git_commit event
    ev2 = GovernanceEvent(
        event_id="ev9b",
        event_type="git_commit",
        entity_id="task_multi",
        actor_id="eng-kernel",
        ts=time.time(),
    )
    result2 = engine.ingest_event(ev2)
    assert len(result2.fulfilled) == 1


# ── Test 10: No fulfiller registered = no auto-fulfill ───────────────────────

def test_no_fulfiller_no_auto_fulfill():
    """
    Test that obligation type without registered fulfiller does NOT auto-fulfill.
    Only uses original required_event_types matching.
    """
    store = InMemoryOmissionStore()
    engine = OmissionEngine(store=store, registry=get_registry())

    # Create obligation with unknown type (no fulfiller)
    ob = ObligationRecord(
        obligation_id="ob10",
        entity_id="task_unknown",
        actor_id="eng-test",
        obligation_type="unknown_obligation_type",  # NOT in 9 types
        required_event_types=["EXACT_EVENT_MATCH"],
        status=ObligationStatus.PENDING,
        due_at=time.time() + 3600,
    )
    store.add_obligation(ob)

    # Emit random event that would match if fulfiller existed
    ev = GovernanceEvent(
        event_id="ev10",
        event_type="random_event",
        entity_id="task_unknown",
        actor_id="eng-test",
        ts=time.time(),
    )
    result = engine.ingest_event(ev)

    # Should NOT fulfill (no fulfiller, no exact match)
    assert len(result.fulfilled) == 0

    # But exact match should still work
    ev2 = GovernanceEvent(
        event_id="ev10b",
        event_type="EXACT_EVENT_MATCH",
        entity_id="task_unknown",
        actor_id="eng-test",
        ts=time.time(),
    )
    result2 = engine.ingest_event(ev2)
    assert len(result2.fulfilled) == 1  # Exact match works


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
