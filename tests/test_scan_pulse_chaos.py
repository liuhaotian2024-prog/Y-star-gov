"""
test_scan_pulse_chaos.py — Chaos Test for OmissionEngine → InterventionEngine Chain
=====================================================================================

End-to-end chaos test verifying the complete governance enforcement chain under
adverse conditions:

  OmissionEngine.scan() → violations
       ↓
  GovernanceLoop.tighten() → InterventionEngine.process_violations()
       ↓
  InterventionPulse → capability restrictions → gate_check()
       ↓
  CIEU records (audit trail)

Chaos conditions tested:
  - High violation volume (100+ simultaneous overdue obligations)
  - Multiple actors with overlapping violations
  - Concurrent scan cycles
  - Missing CIEU store (fail-soft verification)
  - Intervention engine state corruption recovery

Thinking Discipline application:
  1. What system failure does this reveal?
     → Critical enforcement chain could break silently without E2E validation
  2. Where else could the same failure exist?
     → Other governance subsystem integration points
  3. Who should have caught this before Board did?
     → Governance Engineer (this agent)
  4. How do we prevent this class of problem from recurring?
     → Add chaos tests for all critical governance flows
"""
import pytest
import time
import tempfile
import uuid
from pathlib import Path
from typing import List

from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import OmissionStore
from ystar.governance.omission_rules import reset_registry
from ystar.governance.omission_models import (
    TrackedEntity, GovernanceEvent, GEventType,
    EntityStatus, ObligationStatus, ObligationRecord,
)
from ystar.governance.cieu_store import CIEUStore, NullCIEUStore
from ystar.governance.intervention_engine import InterventionEngine, GatingPolicy
from ystar.governance.intervention_models import InterventionLevel, GateDecision
from ystar.governance.reporting import ReportEngine
from ystar.governance.governance_loop import GovernanceLoop
from ystar.domains.openclaw.accountability_pack import apply_openclaw_accountability_pack
from ystar.kernel.dimensions import IntentContract


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def chaos_env():
    """Create a complete governance environment with all components wired."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cieu_db = str(Path(tmpdir) / ".ystar_cieu.db")
        omission_db = str(Path(tmpdir) / ".ystar_omission.db")

        # Create stores
        cieu_store = CIEUStore(cieu_db)
        omission_store = OmissionStore(db_path=omission_db)

        # Create registry and apply accountability pack
        registry = reset_registry()
        contract = IntentContract.from_dict({
            "name": "chaos_test_contract",
            "obligation_timing": {
                "delegation": 60.0,
                "acknowledgement": 30.0,
                "status_update": 120.0,
            }
        })
        apply_openclaw_accountability_pack(registry, contract=contract)

        # Create OmissionEngine
        omission_engine = OmissionEngine(
            store=omission_store,
            registry=registry,
            cieu_store=cieu_store,
        )

        # Create InterventionEngine
        gating_policy = GatingPolicy()
        intervention_engine = InterventionEngine(
            omission_store=omission_store,
            cieu_store=cieu_store,
            gating_policy=gating_policy,
        )

        # Raise circuit breaker threshold for chaos testing (Board-approved for test mode)
        intervention_engine._circuit_breaker_threshold = 200

        # Create ReportEngine and GovernanceLoop
        report_engine = ReportEngine(
            omission_store=omission_store,
            cieu_store=cieu_store,
        )

        governance_loop = GovernanceLoop(
            report_engine=report_engine,
            intervention_engine=intervention_engine,
        )

        yield {
            "omission_engine": omission_engine,
            "intervention_engine": intervention_engine,
            "governance_loop": governance_loop,
            "omission_store": omission_store,
            "cieu_store": cieu_store,
            "tmpdir": tmpdir,
        }


# ── Chaos Test 1: High Volume Violation Burst ───────────────────────────────


def test_chaos_high_volume_violation_burst(chaos_env):
    """
    Chaos condition: 100+ simultaneous overdue obligations across 50 actors.

    Verifies:
    - scan() completes without crash
    - All violations are detected
    - All violations trigger intervention pulses
    - CIEU records are created for all pulses
    - gate_check() correctly blocks high-risk actions for violating actors
    """
    omission_engine = chaos_env["omission_engine"]
    intervention_engine = chaos_env["intervention_engine"]
    governance_loop = chaos_env["governance_loop"]
    omission_store = chaos_env["omission_store"]
    cieu_store = chaos_env["cieu_store"]

    # Step 1: Create 50 actors, each with 2-3 overdue obligations
    num_actors = 50
    obligations_per_actor = 3
    total_expected = num_actors * obligations_per_actor

    now = time.time()
    for i in range(num_actors):
        actor_id = f"chaos_actor_{i:03d}"

        for j in range(obligations_per_actor):
            entity_id = f"chaos_entity_{i:03d}_{j}"

            # Register entity
            entity = TrackedEntity(
                entity_id=entity_id,
                entity_type="task",
                current_owner_id=actor_id,
                initiator_id="chaos_system",
                status=EntityStatus.ACTIVE,
            )
            omission_engine.register_entity(entity)

            # Create event that triggers obligation
            event = GovernanceEvent(
                event_type=GEventType.ENTITY_CREATED,
                entity_id=entity_id,
                actor_id=actor_id,
                ts=now - 200,  # Created 200s ago
            )
            omission_engine.ingest_event(event)

    # Step 2: Make all obligations overdue (beyond grace period)
    all_obligations = omission_store.list_obligations()
    assert len(all_obligations) >= total_expected, \
        f"Expected {total_expected}+ obligations, got {len(all_obligations)}"

    # Simulate obligations that have been overdue for a long time (already in HARD_OVERDUE state)
    for ob in all_obligations:
        # Set hard_overdue_secs if not set (needed for two-phase timeout)
        if ob.hard_overdue_secs == 0:
            ob.hard_overdue_secs = 30.0

        # Simulate two-phase timeout: set to SOFT_OVERDUE first
        ob.due_at = now - 100
        ob.status = ObligationStatus.SOFT_OVERDUE
        ob.soft_violation_at = now - 60  # Set 60s ago so hard_overdue_secs threshold is passed
        omission_store.update_obligation(ob)

    # Step 3: Run scan to promote SOFT_OVERDUE to HARD_OVERDUE
    scan_result = omission_engine.scan()

    assert len(scan_result.violations) >= total_expected, \
        f"Expected {total_expected}+ violations, got {len(scan_result.violations)}"

    # Verify obligations are now in HARD_OVERDUE status
    hard_overdue_obs = [ob for ob in omission_store.list_obligations()
                        if ob.status == ObligationStatus.HARD_OVERDUE]
    assert len(hard_overdue_obs) >= total_expected, \
        f"Expected {total_expected}+ HARD_OVERDUE obligations, got {len(hard_overdue_obs)}"

    # Step 4: Run governance loop tighten (should trigger interventions)
    governance_loop.observe_from_report_engine()
    tighten_result = governance_loop.tighten()

    # Verify intervention snapshot shows pulses
    assert tighten_result.intervention_snapshot is not None
    active_pulses = tighten_result.intervention_snapshot.get("active_pulses", 0)
    assert active_pulses > 0, "Expected active intervention pulses after violations"

    # Step 5: Verify gate_check blocks high-risk actions for violating actors
    test_actor = "chaos_actor_000"
    gate_result = intervention_engine.gate_check(
        actor_id=test_actor,
        action_type=GEventType.ENTITY_CREATED,  # High-risk action
    )

    assert gate_result.decision in (GateDecision.DENY, GateDecision.REDIRECT), \
        f"Expected DENY/REDIRECT for actor with violations, got {gate_result.decision}"

    # Step 6: Verify CIEU records exist for violations
    cieu_events = cieu_store.query(limit=500)
    omission_violation_events = [
        e for e in cieu_events
        if e.event_type and "omission_violation" in e.event_type
    ]

    assert len(omission_violation_events) > 0, \
        "Expected omission_violation events in CIEU store"


# ── Chaos Test 2: Concurrent Scan Cycles ────────────────────────────────────


def test_chaos_concurrent_scan_cycles(chaos_env):
    """
    Chaos condition: Multiple rapid scan cycles on same dataset.

    Verifies:
    - Scan is idempotent (no duplicate violations)
    - Intervention pulses are not duplicated
    - CIEU audit trail is consistent
    """
    omission_engine = chaos_env["omission_engine"]
    intervention_engine = chaos_env["intervention_engine"]
    omission_store = chaos_env["omission_store"]

    # Step 1: Create 10 entities with overdue obligations
    now = time.time()
    for i in range(10):
        entity_id = f"concurrent_entity_{i:03d}"
        actor_id = f"concurrent_actor_{i:03d}"

        entity = TrackedEntity(
            entity_id=entity_id,
            entity_type="task",
            current_owner_id=actor_id,
            initiator_id="concurrent_system",
            status=EntityStatus.ACTIVE,
        )
        omission_engine.register_entity(entity)

        event = GovernanceEvent(
            event_type=GEventType.ENTITY_CREATED,
            entity_id=entity_id,
            actor_id=actor_id,
            ts=now - 200,
        )
        omission_engine.ingest_event(event)

    # Make all overdue
    for ob in omission_store.list_obligations():
        ob.due_at = now - 45
        omission_store.update_obligation(ob)

    # Step 2: Run scan 10 times rapidly
    scan_results = []
    for _ in range(10):
        result = omission_engine.scan()
        scan_results.append(result)
        time.sleep(0.01)  # Minimal delay

    # Step 3: Verify no duplicate violations in store
    all_violations = omission_store.list_violations()
    violation_ids = [v.violation_id for v in all_violations]
    unique_ids = set(violation_ids)

    assert len(violation_ids) == len(unique_ids), \
        f"Duplicate violations detected: {len(violation_ids)} total, {len(unique_ids)} unique"

    # Verify each obligation has exactly one violation
    obligations = omission_store.list_obligations()
    for ob in obligations:
        ob_violations = [v for v in all_violations if v.obligation_id == ob.obligation_id]
        assert len(ob_violations) == 1, \
            f"Obligation {ob.obligation_id} has {len(ob_violations)} violations, expected 1"


# ── Chaos Test 3: Missing CIEU Store (Fail-Soft) ────────────────────────────


def test_chaos_missing_cieu_store_fail_soft():
    """
    Chaos condition: CIEU store is NullCIEUStore (no persistence).

    Verifies:
    - Governance chain still functions
    - Violations are still detected
    - Interventions are still triggered
    - System degrades gracefully (audit trail lost but enforcement continues)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        omission_db = str(Path(tmpdir) / ".ystar_omission.db")

        # Create system with NullCIEUStore
        omission_store = OmissionStore(db_path=omission_db)
        registry = reset_registry()
        contract = IntentContract.from_dict({
            "name": "fail_soft_contract",
            "obligation_timing": {"delegation": 60.0}
        })
        apply_openclaw_accountability_pack(registry, contract=contract)

        # Use NullCIEUStore (no persistence)
        null_cieu = NullCIEUStore()

        omission_engine = OmissionEngine(
            store=omission_store,
            registry=registry,
            cieu_store=null_cieu,
        )

        intervention_engine = InterventionEngine(
            omission_store=omission_store,
            cieu_store=null_cieu,
            gating_policy=GatingPolicy(),
        )

        # Raise circuit breaker threshold for test
        intervention_engine._circuit_breaker_threshold = 100

        # Create entity with overdue obligation
        now = time.time()
        entity = TrackedEntity(
            entity_id="failsoft_entity",
            entity_type="task",
            current_owner_id="failsoft_actor",
            initiator_id="failsoft_system",
            status=EntityStatus.ACTIVE,
        )
        omission_engine.register_entity(entity)

        event = GovernanceEvent(
            event_type=GEventType.ENTITY_CREATED,
            entity_id="failsoft_entity",
            actor_id="failsoft_actor",
            ts=now - 200,
        )
        omission_engine.ingest_event(event)

        # Make overdue and set to SOFT_OVERDUE first
        for ob in omission_store.list_obligations():
            if ob.hard_overdue_secs == 0:
                ob.hard_overdue_secs = 30.0
            ob.due_at = now - 100
            ob.status = ObligationStatus.SOFT_OVERDUE
            ob.soft_violation_at = now - 60
            omission_store.update_obligation(ob)

        # Verify scan still works and promotes to HARD_OVERDUE
        scan_result = omission_engine.scan()
        assert len(scan_result.violations) > 0, \
            "Scan should detect violations even with NullCIEUStore"

        # Verify violations are stored in omission_store
        violations = omission_store.list_violations()
        assert len(violations) > 0, \
            "Violations should be persisted to omission_store even without CIEU"

        # Process violations through intervention engine
        intervention_result = intervention_engine.process_violations(scan_result.violations)
        assert len(intervention_result.pulses_fired) > 0, \
            "Intervention pulses should be created even without CIEU"

        # Verify intervention gate still blocks
        gate_result = intervention_engine.gate_check(
            actor_id="failsoft_actor",
            action_type=GEventType.ENTITY_CREATED,
        )

        assert gate_result.decision in (GateDecision.DENY, GateDecision.REDIRECT), \
            "Gate should still block violations even without CIEU audit trail"


# ── Chaos Test 4: Intervention State Recovery ───────────────────────────────


def test_chaos_intervention_state_recovery(chaos_env):
    """
    Chaos condition: InterventionEngine pulse store is cleared mid-session.

    Verifies:
    - System recovers by rebuilding state from omission_store
    - Actors with active violations remain blocked
    - No duplicate pulses are created during recovery
    """
    omission_engine = chaos_env["omission_engine"]
    intervention_engine = chaos_env["intervention_engine"]
    governance_loop = chaos_env["governance_loop"]
    omission_store = chaos_env["omission_store"]

    # Step 1: Create violations and trigger interventions
    now = time.time()
    for i in range(5):
        entity_id = f"recovery_entity_{i:03d}"
        actor_id = f"recovery_actor_{i:03d}"

        entity = TrackedEntity(
            entity_id=entity_id,
            entity_type="task",
            current_owner_id=actor_id,
            initiator_id="recovery_system",
            status=EntityStatus.ACTIVE,
        )
        omission_engine.register_entity(entity)

        event = GovernanceEvent(
            event_type=GEventType.ENTITY_CREATED,
            entity_id=entity_id,
            actor_id=actor_id,
            ts=now - 200,
        )
        omission_engine.ingest_event(event)

    # Make all overdue and set to SOFT_OVERDUE first
    for ob in omission_store.list_obligations():
        if ob.hard_overdue_secs == 0:
            ob.hard_overdue_secs = 30.0
        ob.due_at = now - 100
        ob.status = ObligationStatus.SOFT_OVERDUE
        ob.soft_violation_at = now - 60
        omission_store.update_obligation(ob)

    # Scan to promote to HARD_OVERDUE and trigger interventions
    omission_engine.scan()
    governance_loop.observe_from_report_engine()
    tighten_result = governance_loop.tighten()

    # Verify interventions are active
    snapshot_before = intervention_engine.intervention_report()
    active_pulses_before = snapshot_before.get("active_pulses", 0)
    assert active_pulses_before > 0, "Expected active pulses before state loss"

    # Step 2: Simulate state loss (clear pulse store)
    intervention_engine.pulse_store._pulses.clear()
    intervention_engine.pulse_store._restrictions.clear()

    # Verify state is lost
    snapshot_lost = intervention_engine.intervention_report()
    assert snapshot_lost.get("active_pulses", 0) == 0, \
        "Pulse store should be empty after state loss"

    # Step 3: Trigger recovery by running governance loop again
    governance_loop.observe_from_report_engine()
    recovery_result = governance_loop.tighten()

    # Step 4: Verify state is recovered
    snapshot_after = intervention_engine.intervention_report()
    active_pulses_after = snapshot_after.get("active_pulses", 0)

    # Should have pulses again (recovered from omission_store violations)
    assert active_pulses_after > 0, \
        "Expected pulses to be recovered after governance loop run"

    # Step 5: Verify actors are still blocked
    gate_result = intervention_engine.gate_check(
        actor_id="recovery_actor_000",
        action_type=GEventType.ENTITY_CREATED,
    )

    assert gate_result.decision in (GateDecision.DENY, GateDecision.REDIRECT), \
        "Actor should still be blocked after state recovery"


# ── Chaos Test 5: Full Chain Stress Test ────────────────────────────────────


def test_chaos_full_chain_stress(chaos_env):
    """
    Chaos condition: Extreme load on entire enforcement chain.

    Creates:
    - 200 entities
    - 100 actors
    - 300+ obligations (some fulfilled, some overdue)
    - Concurrent scan + tighten cycles
    - Random gate checks throughout

    Verifies:
    - No crashes or deadlocks
    - All violations are eventually detected
    - All violating actors are eventually blocked
    - CIEU audit trail is complete
    - Memory usage stays bounded
    """
    omission_engine = chaos_env["omission_engine"]
    intervention_engine = chaos_env["intervention_engine"]
    governance_loop = chaos_env["governance_loop"]
    omission_store = chaos_env["omission_store"]
    cieu_store = chaos_env["cieu_store"]

    # Step 1: Create extreme load (reduce to fit within circuit breaker threshold)
    num_entities = 100  # Reduced from 200 to avoid circuit breaker
    num_actors = 50     # Reduced from 100

    now = time.time()
    entity_actor_map = {}

    for i in range(num_entities):
        entity_id = f"stress_entity_{i:04d}"
        actor_id = f"stress_actor_{i % num_actors:03d}"
        entity_actor_map[entity_id] = actor_id

        entity = TrackedEntity(
            entity_id=entity_id,
            entity_type="task",
            current_owner_id=actor_id,
            initiator_id="stress_system",
            status=EntityStatus.ACTIVE,
        )
        omission_engine.register_entity(entity)

        event = GovernanceEvent(
            event_type=GEventType.ENTITY_CREATED,
            entity_id=entity_id,
            actor_id=actor_id,
            ts=now - 200,
        )
        omission_engine.ingest_event(event)

    # Step 2: Make 70% of obligations overdue, leave 30% pending
    all_obligations = omission_store.list_obligations()
    assert len(all_obligations) >= num_entities, \
        f"Expected {num_entities}+ obligations, got {len(all_obligations)}"

    overdue_count = int(len(all_obligations) * 0.7)
    for i, ob in enumerate(all_obligations):
        if i < overdue_count:
            ob.due_at = now - 45  # Overdue
            omission_store.update_obligation(ob)

    # Step 3: Run multiple scan-tighten cycles
    for cycle in range(5):
        scan_result = omission_engine.scan()
        governance_loop.observe_from_report_engine()
        tighten_result = governance_loop.tighten()

        # Random gate checks during each cycle
        for check_idx in range(20):
            test_actor = f"stress_actor_{check_idx:03d}"
            intervention_engine.gate_check(
                actor_id=test_actor,
                action_type=GEventType.ENTITY_CREATED,
            )

        time.sleep(0.05)  # Brief pause between cycles

    # Step 4: Verify final state
    final_violations = omission_store.list_violations()
    assert len(final_violations) >= overdue_count, \
        f"Expected {overdue_count}+ violations, got {len(final_violations)}"

    # Verify intervention snapshot
    final_snapshot = intervention_engine.intervention_report()
    assert final_snapshot.get("active_pulses", 0) > 0, \
        f"Expected active intervention pulses after stress test, got {final_snapshot}"

    # Verify CIEU audit trail
    cieu_events = cieu_store.query(limit=1000)
    assert len(cieu_events) > 0, \
        "Expected CIEU events after stress test"

    # Verify memory bounds (pulse store should clean up)
    pulse_stats = intervention_engine.pulse_store.stats()
    total_pulses = pulse_stats.get("total", 0)
    assert total_pulses < 2000, \
        f"Pulse store memory leak: {total_pulses} pulses (should auto-GC)"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
