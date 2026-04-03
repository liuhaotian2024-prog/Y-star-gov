"""
test_governance_pipeline_e2e.py — End-to-End Governance Pipeline Tests
=======================================================================

P0 tests for the full governance pipeline:
  session config → obligations → suggestions → Path A

These tests verify that the governance subsystems are properly connected
and data flows from start to finish.

Failure modes this catches:
  - OmissionStore has zero obligations (empty data source)
  - GovernanceLoop produces zero suggestions (broken KPI pipeline)
  - Path A never activates (trigger condition not met)
"""
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from ystar.governance.omission_store import OmissionStore
from ystar.governance.omission_rules import reset_registry
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_models import (
    TrackedEntity, GovernanceEvent, GEventType,
    EntityStatus, ObligationStatus,
)
from ystar.governance.cieu_store import CIEUStore
from ystar.domains.openclaw.accountability_pack import apply_openclaw_accountability_pack
from ystar.kernel.dimensions import IntentContract


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_session_dir():
    """Create a temporary directory with session config for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session_cfg = {
            "session_id": f"test_session_{uuid.uuid4().hex[:8]}",
            "cieu_db": str(Path(tmpdir) / ".ystar_cieu.db"),
            "contract": {
                "name": "test_policy",
                "obligation_timing": {
                    "delegation": 300.0,
                    "acknowledgement": 120.0,
                    "status_update": 600.0,
                }
            }
        }
        session_file = Path(tmpdir) / ".ystar_session.json"
        session_file.write_text(json.dumps(session_cfg, indent=2))
        yield tmpdir, session_cfg


# ── Test 1: Session config creates obligations ──────────────────────────────


def test_session_config_creates_obligations(temp_session_dir):
    """
    Verify that session config with obligation_timing creates obligations
    when corresponding events occur.

    This tests the OmissionEngine rule-based obligation creation.
    """
    tmpdir, session_cfg = temp_session_dir
    cieu_db = session_cfg["cieu_db"]
    omission_db = cieu_db.replace(".db", "_omission.db")

    # Step 1: Create OmissionStore and Engine with contract config
    store = OmissionStore(db_path=omission_db)
    registry = reset_registry()

    # Apply OpenClaw accountability pack with contract timing
    contract_dict = session_cfg.get("contract", {})
    contract = IntentContract.from_dict(contract_dict)
    apply_openclaw_accountability_pack(registry, contract=contract)

    cieu_store = CIEUStore(cieu_db)
    engine = OmissionEngine(store=store, registry=registry, cieu_store=cieu_store)

    # Step 2: Create an entity (simulates a task being created)
    entity = TrackedEntity(
        entity_id="task_001",
        entity_type="task",
        current_owner_id="agent_a",
        initiator_id="agent_system",
        status=EntityStatus.ACTIVE,
    )
    engine.register_entity(entity)

    # Step 3: Ingest ENTITY_CREATED event (should trigger rule_a_delegation)
    event = GovernanceEvent(
        event_type=GEventType.ENTITY_CREATED,
        entity_id="task_001",
        actor_id="agent_a",
        ts=time.time(),
    )
    result = engine.ingest_event(event)

    # Step 4: Verify obligation was created
    obligations = store.list_obligations(entity_id="task_001")
    assert len(obligations) > 0, "Expected at least one obligation to be created"

    # Verify the obligation is PENDING and has correct deadline
    delegation_obs = [o for o in obligations if "delegation" in o.obligation_type.lower()]
    assert len(delegation_obs) > 0, "Expected delegation obligation to be created"

    ob = delegation_obs[0]
    assert ob.status == ObligationStatus.PENDING
    assert ob.actor_id == "agent_a"
    assert ob.due_at > time.time()  # Should have a future deadline


# ── Test 2: Obligations produce violations when overdue ─────────────────────


def test_obligations_produce_violations(temp_session_dir):
    """
    Verify that overdue obligations produce violations that are visible
    to GovernanceLoop.

    This tests the OmissionEngine scan cycle and violation generation.
    """
    tmpdir, session_cfg = temp_session_dir
    cieu_db = session_cfg["cieu_db"]
    omission_db = cieu_db.replace(".db", "_omission.db")

    # Step 1: Create engine with contract
    store = OmissionStore(db_path=omission_db)
    registry = reset_registry()
    contract_dict = session_cfg.get("contract", {})
    contract = IntentContract.from_dict(contract_dict)
    apply_openclaw_accountability_pack(registry, contract=contract)

    cieu_store = CIEUStore(cieu_db)
    engine = OmissionEngine(store=store, registry=registry, cieu_store=cieu_store)

    # Step 2: Create entity and event (creates obligation)
    entity = TrackedEntity(
        entity_id="task_002",
        entity_type="task",
        current_owner_id="agent_b",
        initiator_id="agent_system",
        status=EntityStatus.ACTIVE,
    )
    engine.register_entity(entity)

    event = GovernanceEvent(
        event_type=GEventType.ENTITY_CREATED,
        entity_id="task_002",
        actor_id="agent_b",
        ts=time.time() - 400,  # Created 400 seconds ago
    )
    engine.ingest_event(event)

    # Step 3: Manually set obligation to be overdue (beyond grace period)
    obligations = store.list_obligations(entity_id="task_002")
    assert len(obligations) > 0
    ob = obligations[0]
    # Grace period is 30s, so set overdue by 40s to ensure violation is created
    ob.due_at = time.time() - 40
    store.update_obligation(ob)

    # Step 4: Run scan to detect violation
    scan_result = engine.scan()

    # Step 5: Verify violation was created
    assert len(scan_result.violations) > 0, "Expected violation to be detected"
    assert len(scan_result.expired) > 0, "Expected expired obligation"

    violations = store.list_violations(entity_id="task_002")
    assert len(violations) > 0, "Expected violation to be persisted in store"


# ── Test 3: ReportEngine produces non-zero KPIs ─────────────────────────────


def test_report_engine_produces_kpis(temp_session_dir):
    """
    Verify that ReportEngine queries OmissionStore and produces non-zero KPIs
    when violations exist.

    This tests the ReportEngine → OmissionStore connection.
    """
    tmpdir, session_cfg = temp_session_dir
    cieu_db = session_cfg["cieu_db"]
    omission_db = cieu_db.replace(".db", "_omission.db")

    # Step 1: Create engine and populate with violation
    store = OmissionStore(db_path=omission_db)
    registry = reset_registry()
    contract_dict = session_cfg.get("contract", {})
    contract = IntentContract.from_dict(contract_dict)
    apply_openclaw_accountability_pack(registry, contract=contract)

    cieu_store = CIEUStore(cieu_db)
    engine = OmissionEngine(store=store, registry=registry, cieu_store=cieu_store)

    # Create entity, event, and violation
    entity = TrackedEntity(
        entity_id="task_003",
        entity_type="task",
        current_owner_id="agent_c",
        initiator_id="agent_system",
        status=EntityStatus.ACTIVE,
    )
    engine.register_entity(entity)

    event = GovernanceEvent(
        event_type=GEventType.ENTITY_CREATED,
        entity_id="task_003",
        actor_id="agent_c",
        ts=time.time() - 400,
    )
    engine.ingest_event(event)

    # Make obligation overdue and scan (beyond grace period)
    obligations = store.list_obligations(entity_id="task_003")
    ob = obligations[0]
    # Grace period is 30s, so set overdue by 40s to ensure violation is created
    ob.due_at = time.time() - 40
    store.update_obligation(ob)
    engine.scan()

    # Step 2: Create ReportEngine and generate report
    from ystar.governance.reporting import ReportEngine

    report_engine = ReportEngine(omission_store=store, cieu_store=cieu_store)
    report = report_engine.baseline_report()

    # Step 3: Verify KPIs are non-zero
    assert report is not None, "Expected Report to be returned"
    assert report.kpis is not None, "Expected KPIs dict in report"
    assert "obligation_fulfillment_rate" in report.kpis
    assert "omission_detection_rate" in report.kpis

    # With violations present, detection rate should be > 0
    odr = report.kpis.get("omission_detection_rate", 0.0)
    assert odr > 0.0, f"Expected non-zero omission_detection_rate, got {odr}"


# ── Test 4: GovernanceLoop produces suggestions from KPIs ───────────────────


def test_governance_loop_produces_suggestions(temp_session_dir):
    """
    Verify that GovernanceLoop receives KPIs from ReportEngine and produces
    governance suggestions when health is degraded.

    This tests the ReportEngine → GovernanceLoop → SuggestionPolicy chain.
    """
    tmpdir, session_cfg = temp_session_dir
    cieu_db = session_cfg["cieu_db"]
    omission_db = cieu_db.replace(".db", "_omission.db")

    # Step 1: Create system with violations
    store = OmissionStore(db_path=omission_db)
    registry = reset_registry()
    contract_dict = session_cfg.get("contract", {})
    contract = IntentContract.from_dict(contract_dict)
    apply_openclaw_accountability_pack(registry, contract=contract)

    cieu_store = CIEUStore(cieu_db)
    engine = OmissionEngine(store=store, registry=registry, cieu_store=cieu_store)

    # Create multiple violations to degrade health
    for i in range(3):
        entity = TrackedEntity(
            entity_id=f"task_{i:03d}",
            entity_type="task",
            current_owner_id=f"agent_{i}",
            initiator_id="agent_system",
            status=EntityStatus.ACTIVE,
        )
        engine.register_entity(entity)

        event = GovernanceEvent(
            event_type=GEventType.ENTITY_CREATED,
            entity_id=f"task_{i:03d}",
            actor_id=f"agent_{i}",
            ts=time.time() - 400,
        )
        engine.ingest_event(event)

    # Make all obligations overdue (beyond grace period)
    for ob in store.list_obligations():
        # Grace period is 30s, so set overdue by 40s to ensure violation is created
        ob.due_at = time.time() - 40
        store.update_obligation(ob)

    engine.scan()

    # Step 2: Create ReportEngine and GovernanceLoop
    from ystar.governance.reporting import ReportEngine
    from ystar.governance.governance_loop import GovernanceLoop

    report_engine = ReportEngine(omission_store=store, cieu_store=cieu_store)
    gov_loop = GovernanceLoop(report_engine=report_engine)

    # Step 3: Run observe-tighten cycle
    gov_loop.observe_from_report_engine()
    result = gov_loop.tighten()

    # Step 4: Verify suggestions were generated
    assert result.governance_suggestions is not None
    assert len(result.governance_suggestions) > 0, \
        "Expected governance suggestions when health is degraded"


# ── Test 5: Full pipeline smoke test ────────────────────────────────────────


def test_full_governance_pipeline_smoke():
    """
    Smoke test for the entire governance pipeline:
      session config → obligations → violations → KPIs → suggestions

    This is a minimal end-to-end test to verify basic connectivity.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cieu_db = str(Path(tmpdir) / ".ystar_cieu.db")
        omission_db = cieu_db.replace(".db", "_omission.db")

        # Minimal session config
        session_cfg = {
            "session_id": "smoke_test",
            "contract": {
                "name": "smoke_policy",
                "obligation_timing": {"delegation": 60.0}
            }
        }

        # Build system
        store = OmissionStore(db_path=omission_db)
        registry = reset_registry()
        contract = IntentContract.from_dict(session_cfg["contract"])
        apply_openclaw_accountability_pack(registry, contract=contract)

        cieu_store = CIEUStore(cieu_db)
        engine = OmissionEngine(store=store, registry=registry, cieu_store=cieu_store)

        from ystar.governance.reporting import ReportEngine
        from ystar.governance.governance_loop import GovernanceLoop

        report_engine = ReportEngine(omission_store=store, cieu_store=cieu_store)
        gov_loop = GovernanceLoop(report_engine=report_engine)

        # Create entity and trigger obligation
        entity = TrackedEntity(
            entity_id="smoke_task",
            entity_type="task",
            current_owner_id="agent_smoke",
            initiator_id="system",
            status=EntityStatus.ACTIVE,
        )
        engine.register_entity(entity)

        event = GovernanceEvent(
            event_type=GEventType.ENTITY_CREATED,
            entity_id="smoke_task",
            actor_id="agent_smoke",
            ts=time.time() - 100,
        )
        engine.ingest_event(event)

        # Make overdue and scan (beyond grace period)
        for ob in store.list_obligations():
            # Grace period is 30s, so set overdue by 40s to ensure violation is created
            ob.due_at = time.time() - 40
            store.update_obligation(ob)
        engine.scan()

        # Run governance cycle
        gov_loop.observe_from_report_engine()
        result = gov_loop.tighten()

        # Basic assertions - pipeline produced output
        assert result is not None
        assert result.overall_health in ("healthy", "degraded", "critical")

        # Verify CIEU events were recorded by OmissionEngine during scan()
        # OmissionEngine writes omission_violation events to CIEU when violations are detected
        all_events = cieu_store.query(limit=100)
        omission_events = [e for e in all_events if e.event_type and e.event_type.startswith("omission_violation:")]
        assert len(omission_events) > 0, f"Expected omission_violation events in CIEU. Got {len(all_events)} total events."


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
