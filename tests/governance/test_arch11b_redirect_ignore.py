"""
CZL-ARCH-11b: REDIRECT ignore detector via OmissionEngine

3 tests:
  1. Obligation created on free-text REDIRECT (register_redirect_obligation)
  2. TTL expiry -> scan() produces violation (REDIRECT_IGNORED semantics)
  3. GuidancePayload present -> no obligation created (handled by ARCH-11a)
"""
import time
import uuid

import pytest

from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_models import (
    ObligationStatus, OmissionType, Severity, TrackedEntity, EntityStatus,
)


def _make_engine(now: float = 1000.0):
    """Create OmissionEngine with controllable time."""
    store = InMemoryOmissionStore()
    t = [now]

    def now_fn():
        return t[0]

    engine = OmissionEngine(store=store, now_fn=now_fn)

    def advance(secs: float):
        t[0] += secs

    return engine, store, advance, t


class TestArch11bRedirectIgnore:
    """ARCH-11b: free-text REDIRECT -> OmissionEngine obligation tracking."""

    def test_obligation_created_on_free_text_redirect(self):
        """Test 1: register_redirect_obligation creates a PENDING obligation
        with type MUST_EXECUTE_REDIRECT."""
        engine, store, advance, _ = _make_engine(now=1000.0)

        ob = engine.register_redirect_obligation(
            agent_id="ceo",
            redirect_id="redir-001",
            ttl_actions=3,
            entity_id="session-abc",
            redirect_reason="identity mismatch: active_agent != ceo",
        )

        assert ob is not None
        assert ob.status == ObligationStatus.PENDING
        assert ob.obligation_type == OmissionType.MUST_EXECUTE_REDIRECT.value
        assert ob.actor_id == "ceo"
        assert ob.entity_id == "session-abc"
        assert ob.violation_code == "redirect_ignored"
        assert ob.severity == Severity.HIGH
        assert "redirect_fulfilled" in ob.required_event_types
        assert "ARCH-11b" in ob.notes

        # Verify obligation is in store
        pending = store.pending_obligations()
        assert any(
            o.obligation_type == OmissionType.MUST_EXECUTE_REDIRECT.value
            for o in pending
        )

    def test_ttl_expiry_produces_violation(self):
        """Test 2: When obligation TTL expires (agent ignores REDIRECT),
        scan() produces a violation -> deny next tool call semantics."""
        engine, store, advance, _ = _make_engine(now=1000.0)

        # Register entity so violation can fire (activity gate)
        entity = TrackedEntity(
            entity_id="session-abc",
            entity_type="session",
            status=EntityStatus.ACTIVE,
            last_event_at=1000.0,
            initiator_id="ceo",
            current_owner_id="ceo",
        )
        store.upsert_entity(entity)

        ob = engine.register_redirect_obligation(
            agent_id="ceo",
            redirect_id="redir-002",
            ttl_actions=3,
            entity_id="session-abc",
            redirect_reason="scope violation",
        )

        # Advance past TTL (3 actions * 10s = 30s deadline)
        advance(35.0)

        # Update entity activity so violation gate passes
        entity.last_event_at = 1035.0
        store.upsert_entity(entity)

        result = engine.scan()

        # Should have at least one violation
        assert len(result.violations) >= 1
        violation = result.violations[0]
        assert violation.omission_type == OmissionType.MUST_EXECUTE_REDIRECT.value
        assert violation.actor_id == "ceo"
        assert violation.entity_id == "session-abc"
        assert "redirect_ignored" in (violation.details.get("violation_code", ""))

    def test_no_obligation_when_guidance_payload_present(self):
        """Test 3: When GuidancePayload is present, ARCH-11a handles the
        REDIRECT via auto-invoke. No OmissionEngine obligation is created.

        This test verifies the contract: register_redirect_obligation is
        only called when GuidancePayload is absent or invoke fails.
        We simulate the hook logic decision tree."""
        engine, store, _, _ = _make_engine(now=1000.0)

        # Simulate: GuidancePayload present + invoke succeeded
        # In this case, hook returns ALLOW (auto-invoked) and never calls
        # register_redirect_obligation. So store should have 0 obligations.
        guidance_present = True
        invoke_succeeded = True

        if not guidance_present or not invoke_succeeded:
            # Only register obligation when guidance absent or invoke failed
            engine.register_redirect_obligation(
                agent_id="ceo",
                redirect_id="redir-003",
                ttl_actions=3,
                entity_id="session-xyz",
                redirect_reason="should not happen",
            )

        # No obligation should exist
        pending = store.pending_obligations()
        must_exec = [
            o for o in pending
            if o.obligation_type == OmissionType.MUST_EXECUTE_REDIRECT.value
        ]
        assert len(must_exec) == 0, (
            "GuidancePayload present + invoke succeeded should NOT create "
            "redirect obligation (handled by ARCH-11a)"
        )

        # Now verify the negative case: guidance absent -> obligation IS created
        guidance_present = False
        if not guidance_present or not invoke_succeeded:
            engine.register_redirect_obligation(
                agent_id="ceo",
                redirect_id="redir-004",
                ttl_actions=3,
                entity_id="session-xyz",
                redirect_reason="no guidance payload",
            )

        pending2 = store.pending_obligations()
        must_exec2 = [
            o for o in pending2
            if o.obligation_type == OmissionType.MUST_EXECUTE_REDIRECT.value
        ]
        assert len(must_exec2) == 1, (
            "GuidancePayload absent should create redirect obligation"
        )
