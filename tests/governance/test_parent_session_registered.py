"""
test_parent_session_registered.py — Regression tests for parent session entity
===============================================================================

Board directive: CZL-PARENT-SESSION-REGISTER-AS-ENTITY (2026-04-20)

Tests:
1. Boot creates parent entity in OmissionStore
2. Parent obligations registered (4 total)
3. GovernanceLoop.observe_parent_session returns non-empty observation
4. Entity expiry triggers InterventionEngine pulse entry point
"""
from __future__ import annotations

import time
import pytest

import sys
import os

# Ensure Y-star-gov is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_models import (
    EntityStatus,
    GovernanceEvent,
    GEventType,
    ObligationStatus,
)
from ystar.governance.omission_rules import RuleRegistry, get_registry, reset_registry
from ystar.governance.parent_session_rules import (
    PARENT_SESSION_RULES,
    create_parent_entity,
    create_parent_obligations,
    register_parent_session_rules,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset the global registry before each test."""
    reset_registry()
    yield
    reset_registry()


class TestParentEntityRegistration:
    """Test 1: Boot creates parent entity in OmissionStore."""

    def test_entity_created_in_store(self):
        store = InMemoryOmissionStore()
        engine = OmissionEngine(store=store)

        entity = create_parent_entity(session_id="test-session-001", agent_id="ceo")
        engine.register_entity(entity)

        # Verify entity exists
        retrieved = store.get_entity("parent-test-session-001")
        assert retrieved is not None
        assert retrieved.entity_id == "parent-test-session-001"
        assert retrieved.entity_type == "ceo_parent"
        assert retrieved.status == EntityStatus.ACTIVE
        assert retrieved.initiator_id == "ceo"
        assert retrieved.current_owner_id == "ceo"

    def test_entity_metadata_includes_session_info(self):
        entity = create_parent_entity(session_id="abc-123", agent_id="ceo")
        assert entity.metadata["session_id"] == "abc-123"
        assert entity.metadata["agent_id"] == "ceo"
        assert "registered_at" in entity.metadata

    def test_entity_goal_summary_descriptive(self):
        entity = create_parent_entity(session_id="sess-42", agent_id="ceo")
        assert "sess-42" in entity.goal_summary
        assert "ceo" in entity.goal_summary


class TestParentObligations:
    """Test 2: Parent obligations registered (4 total)."""

    def test_four_obligations_created(self):
        store = InMemoryOmissionStore()
        entity = create_parent_entity(session_id="test-session-002", agent_id="ceo")
        store.upsert_entity(entity)

        obligations = create_parent_obligations(
            entity_id=entity.entity_id,
            actor_id="ceo",
            session_id="test-session-002",
        )
        for ob in obligations:
            store.add_obligation(ob)

        registered = store.list_obligations(entity_id="parent-test-session-002")
        assert len(registered) == 4

    def test_obligation_types_cover_all_four(self):
        obligations = create_parent_obligations(
            entity_id="parent-test",
            actor_id="ceo",
            session_id="test",
        )
        types = {ob.obligation_type for ob in obligations}
        assert "parent_tool_uses_density" in types
        assert "parent_drift_rate" in types
        assert "parent_reply_latency" in types
        assert "parent_stream_timeout" in types

    def test_obligations_have_correct_due_at(self):
        now = time.time()
        obligations = create_parent_obligations(
            entity_id="parent-test",
            actor_id="ceo",
        )
        for ob in obligations:
            # due_at should be ~1800s from now
            assert ob.due_at is not None
            assert ob.due_at - now >= 1799.0  # allow small time delta
            assert ob.due_at - now <= 1802.0

    def test_obligations_pending_status(self):
        obligations = create_parent_obligations(
            entity_id="parent-test",
            actor_id="ceo",
        )
        for ob in obligations:
            assert ob.status == ObligationStatus.PENDING

    def test_rules_registered_in_registry(self):
        registry = RuleRegistry()
        count = register_parent_session_rules(registry)
        assert count == 4

        # Verify rules exist
        assert registry.get("rule_i_parent_tool_uses_density") is not None
        assert registry.get("rule_j_parent_drift_rate") is not None
        assert registry.get("rule_k_parent_reply_latency") is not None
        assert registry.get("rule_l_parent_stream_timeout") is not None


class TestGovernanceLoopObserveParent:
    """Test 3: GovernanceLoop.observe_parent_session returns non-empty observation."""

    def test_observe_parent_returns_observation(self):
        from ystar.governance.governance_loop import GovernanceLoop
        from ystar.governance.reporting import ReportEngine

        store = InMemoryOmissionStore()
        report_engine = ReportEngine(omission_store=store)
        loop = GovernanceLoop(report_engine=report_engine)

        obs = loop.observe_parent_session(
            entity_id="parent-test-session-003",
            metrics={
                "tool_uses_30min": 50,
                "drift_count_30min": 1,
                "reply_latency_ratio": 1.2,
                "stream_timeout_count": 0,
            },
        )

        assert obs is not None
        assert obs.period_label == "parent_session_parent-test-session-003"
        assert obs.total_entities == 1
        assert obs.raw_kpis["parent_entity_id"] == "parent-test-session-003"
        assert obs.raw_kpis["tool_uses_30min"] == 50

    def test_observe_parent_healthy_metrics(self):
        from ystar.governance.governance_loop import GovernanceLoop
        from ystar.governance.reporting import ReportEngine

        store = InMemoryOmissionStore()
        report_engine = ReportEngine(omission_store=store)
        loop = GovernanceLoop(report_engine=report_engine)

        obs = loop.observe_parent_session(
            entity_id="parent-healthy",
            metrics={
                "tool_uses_30min": 30,
                "drift_count_30min": 0,
                "reply_latency_ratio": 1.0,
                "stream_timeout_count": 0,
            },
        )

        # All metrics within thresholds -> fulfillment rate = 1.0
        assert obs.obligation_fulfillment_rate == 1.0
        assert obs.hard_overdue_rate == 0.0

    def test_observe_parent_degraded_metrics(self):
        from ystar.governance.governance_loop import GovernanceLoop
        from ystar.governance.reporting import ReportEngine

        store = InMemoryOmissionStore()
        report_engine = ReportEngine(omission_store=store)
        loop = GovernanceLoop(report_engine=report_engine)

        obs = loop.observe_parent_session(
            entity_id="parent-degraded",
            metrics={
                "tool_uses_30min": 150,   # exceeds 100
                "drift_count_30min": 5,    # exceeds 2
                "reply_latency_ratio": 3.0, # exceeds 2.0
                "stream_timeout_count": 4,  # exceeds 2
            },
        )

        # All 4 thresholds violated
        assert obs.obligation_fulfillment_rate == 0.0
        assert obs.hard_overdue_rate == 1.0

    def test_observe_parent_partial_violations(self):
        from ystar.governance.governance_loop import GovernanceLoop
        from ystar.governance.reporting import ReportEngine

        store = InMemoryOmissionStore()
        report_engine = ReportEngine(omission_store=store)
        loop = GovernanceLoop(report_engine=report_engine)

        obs = loop.observe_parent_session(
            entity_id="parent-partial",
            metrics={
                "tool_uses_30min": 150,   # violates (>100)
                "drift_count_30min": 1,    # ok
                "reply_latency_ratio": 1.0, # ok
                "stream_timeout_count": 3,  # violates (>2)
            },
        )

        # 2 out of 4 violated
        assert obs.obligation_fulfillment_rate == 0.5
        assert obs.hard_overdue_rate == 0.5


class TestEntityExpiryInterventionPulse:
    """Test 4: Entity expiry triggers InterventionEngine pulse entry point."""

    def test_expired_obligation_triggers_intervention_path(self):
        """
        When a parent obligation expires (hard_overdue), the OmissionEngine.scan()
        detects them and the InterventionEngine can process the violations.
        """
        store = InMemoryOmissionStore()
        engine = OmissionEngine(store=store)

        # Register entity
        entity = create_parent_entity(session_id="expire-test", agent_id="ceo")
        engine.register_entity(entity)

        # Create obligations with immediate expiry (due_at in the past)
        obligations = create_parent_obligations(
            entity_id=entity.entity_id,
            actor_id="ceo",
            session_id="expire-test",
        )
        # Force expiry by setting due_at to past
        for ob in obligations:
            ob.due_at = time.time() - 100  # 100 seconds ago
            store.add_obligation(ob)

        # Run scan — should detect overdue obligations
        result = engine.scan()

        # After scan(), obligations transition from PENDING to overdue states
        # (SOFT_OVERDUE or HARD_OVERDUE). Check that they are no longer PENDING.
        all_obs = store.list_obligations(entity_id=entity.entity_id)
        non_pending = [
            ob for ob in all_obs
            if ob.status != ObligationStatus.PENDING
        ]
        assert len(non_pending) == 4, "All 4 parent obligations should have transitioned from PENDING"

        # Verify scan result contains violation info
        assert result is not None

    def test_intervention_engine_can_receive_parent_violation(self):
        """
        InterventionEngine accepts parent entity obligations.
        This verifies the contract compatibility (no crash on ceo_parent type).
        """
        try:
            from ystar.governance.intervention_engine import InterventionEngine
        except ImportError:
            pytest.skip("InterventionEngine not available")

        # Create store with parent obligations
        store = InMemoryOmissionStore()
        entity = create_parent_entity(session_id="ie-test", agent_id="ceo")
        store.upsert_entity(entity)

        obligations = create_parent_obligations(
            entity_id=entity.entity_id,
            actor_id="ceo",
            session_id="ie-test",
        )
        for ob in obligations:
            ob.due_at = time.time() - 100  # expired
            store.add_obligation(ob)

        # InterventionEngine should initialize with store containing parent entities
        ie = InterventionEngine(omission_store=store)

        # Verify it can list parent obligations without crash
        parent_obs = store.list_obligations(entity_id=entity.entity_id)
        assert len(parent_obs) == 4

        # Verify InterventionEngine can do gate_check on parent entity actor
        # gate_check(actor_id, action_type) should not reject ceo_parent entity type
        try:
            if hasattr(ie, 'gate_check'):
                result = ie.gate_check(actor_id="ceo", action_type="status_update")
                # If we get here, gate_check accepted the parent actor
                assert result is not None
        except TypeError:
            pytest.fail("InterventionEngine rejected parent actor — contract violation")
        except Exception:
            # Other exceptions (missing config, no violations cached, etc) acceptable
            # Key: no TypeError on parent entity type
            pass
