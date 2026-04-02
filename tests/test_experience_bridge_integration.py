"""
tests.test_experience_bridge_integration — Experience Bridge + GovernanceLoop Integration Tests

P1-4: Experience Bridge Integration

Test coverage:
1. GovernanceLoop with experience_bridge parameter
2. Bridge metrics merged into observation.raw_kpis
3. Bridge suggestion candidates merged into governance_suggestions
4. GovernanceLoop without bridge remains unchanged
5. Bridge failure does not block observation
6. Bridge suggestion conversion to GovernanceSuggestion

Run with: python -m pytest tests/test_experience_bridge_integration.py -v
"""
import pytest
from unittest.mock import Mock
from ystar.governance.governance_loop import GovernanceLoop, GovernanceObservation, GovernanceSuggestion
from ystar.governance.experience_bridge import (
    ExperienceBridge, BridgeInput, BridgeOutput, BridgeSuggestionCandidate,
    ExternalGovernancePattern, InternalGovernanceGap
)
from ystar.governance.reporting import ReportEngine
from ystar.governance.omission_store import OmissionStore


# ── Test 1: GovernanceLoop accepts experience_bridge parameter ───────────────

def test_governance_loop_with_bridge():
    """Test that GovernanceLoop accepts experience_bridge parameter."""
    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)
    bridge = ExperienceBridge()

    gloop = GovernanceLoop(
        report_engine=report_engine,
        experience_bridge=bridge,
    )

    assert gloop._experience_bridge is bridge
    assert gloop.report_engine is report_engine


def test_governance_loop_without_bridge():
    """Test that GovernanceLoop works without experience_bridge (backward compatible)."""
    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)

    gloop = GovernanceLoop(report_engine=report_engine)

    assert gloop._experience_bridge is None
    assert gloop.report_engine is report_engine


# ── Test 2: Bridge metrics merged into observation ───────────────────────────

def test_bridge_feeds_governance_loop():
    """Test that bridge metrics are merged into GovernanceObservation.raw_kpis."""
    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)
    bridge = ExperienceBridge()

    # Ingest some Path B CIEU records into bridge
    cieu_records = [
        {
            "func_name": "path_b.constraint_applied",
            "path_b_event": "CONSTRAINT_APPLIED",
            "params": {"agent_id": "agent_001", "cycle_id": "c001"},
            "violations": [],
            "source": "path_b_agent",
        },
        {
            "func_name": "path_b.compliance_result",
            "path_b_event": "COMPLIANCE_RESULT",
            "params": {"agent_id": "agent_001", "cycle_id": "c002"},
            "violations": [],
            "source": "path_b_agent",
        },
    ]
    bridge.ingest_path_b_cieu(cieu_records)
    bridge.aggregate_patterns()
    bridge.attribute_gaps()

    # Create GovernanceLoop with bridge
    gloop = GovernanceLoop(
        report_engine=report_engine,
        experience_bridge=bridge,
    )

    # Observe from report engine (should merge bridge metrics)
    obs = gloop.observe_from_report_engine()

    # Check that bridge metrics are in raw_kpis
    assert "external_constraint_effectiveness_rate" in obs.raw_kpis
    assert "external_budget_exhaustion_rate" in obs.raw_kpis
    assert "external_disconnect_pressure" in obs.raw_kpis
    assert isinstance(obs.raw_kpis["external_constraint_effectiveness_rate"], float)


def test_governance_loop_without_bridge_unchanged():
    """Test that GovernanceLoop without bridge produces same observation structure."""
    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)

    gloop = GovernanceLoop(report_engine=report_engine)

    obs = gloop.observe_from_report_engine()

    # Should still have raw_kpis dict, just without bridge metrics
    assert isinstance(obs.raw_kpis, dict)
    assert "external_constraint_effectiveness_rate" not in obs.raw_kpis
    assert "external_budget_exhaustion_rate" not in obs.raw_kpis


# ── Test 3: Bridge suggestions merged into tighten result ────────────────────

def test_bridge_suggestions_merged_into_tighten():
    """Test that bridge suggestion candidates are converted to GovernanceSuggestion."""
    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)
    bridge = ExperienceBridge()

    # Create a pattern that produces a gap
    cieu_records = [
        {
            "func_name": "path_b.constraint_applied",
            "path_b_event": "CONSTRAINT_APPLIED",
            "params": {"agent_id": "agent_001", "cycle_id": f"c{i:03d}"},
            "violations": [{"type": "test_violation"}],
            "source": "path_b_agent",
        }
        for i in range(5)  # 5 violations to trigger high confidence pattern
    ]
    bridge.ingest_path_b_cieu(cieu_records)
    bridge.aggregate_patterns()
    bridge.attribute_gaps()

    gloop = GovernanceLoop(
        report_engine=report_engine,
        experience_bridge=bridge,
    )

    # Observe first
    gloop.observe_from_report_engine()

    # Tighten
    result = gloop.tighten()

    # Should have suggestions from bridge
    assert len(result.governance_suggestions) > 0

    # At least one suggestion should come from Path B gap
    bridge_suggestions = [
        s for s in result.governance_suggestions
        if "[Path B Gap:" in s.rationale
    ]
    assert len(bridge_suggestions) > 0

    # Verify suggestion structure
    bridge_sugg = bridge_suggestions[0]
    assert isinstance(bridge_sugg, GovernanceSuggestion)
    assert bridge_sugg.suggestion_type in {"wire", "tighten", "rewire", "review"}
    assert bridge_sugg.confidence > 0.0
    assert "gap_" in bridge_sugg.observation_ref


# ── Test 4: Bridge failure does not block observation ─────────────────────────

def test_bridge_failure_does_not_block_observation():
    """Test that if bridge.generate_observation_metrics() fails, observation still works."""
    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)

    # Create a mock bridge that raises an exception
    mock_bridge = Mock()
    mock_bridge.generate_observation_metrics.side_effect = RuntimeError("Bridge failure")

    gloop = GovernanceLoop(
        report_engine=report_engine,
        experience_bridge=mock_bridge,
    )

    # Should not raise, fail-soft
    obs = gloop.observe_from_report_engine()

    assert obs is not None
    assert isinstance(obs, GovernanceObservation)
    # raw_kpis should exist but not have bridge metrics
    assert isinstance(obs.raw_kpis, dict)


def test_bridge_failure_does_not_block_tighten():
    """Test that if bridge.generate_output() fails, tighten still works."""
    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)

    # Create a mock bridge that raises an exception
    mock_bridge = Mock()
    mock_bridge.generate_observation_metrics.return_value = {}
    mock_bridge.generate_output.side_effect = RuntimeError("Bridge output failure")

    gloop = GovernanceLoop(
        report_engine=report_engine,
        experience_bridge=mock_bridge,
    )

    gloop.observe_from_report_engine()

    # Should not raise, fail-soft
    result = gloop.tighten()

    assert result is not None
    # governance_suggestions should exist, just without bridge candidates
    assert isinstance(result.governance_suggestions, list)


# ── Test 5: Bridge suggestion conversion ──────────────────────────────────────

def test_bridge_suggestion_candidate_conversion():
    """Test that BridgeSuggestionCandidate is correctly converted to GovernanceSuggestion."""
    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)
    bridge = ExperienceBridge()

    # Manually inject a gap to ensure suggestion generation
    gap = InternalGovernanceGap(
        gap_id="gap_test",
        inferred_module_targets=["constraint_derivation"],
        inferred_gap_type="constraint_missing",
        supporting_patterns=[],
        confidence=0.8,
        rationale="Test gap for suggestion conversion",
    )
    bridge._gaps.append(gap)

    gloop = GovernanceLoop(
        report_engine=report_engine,
        experience_bridge=bridge,
    )

    gloop.observe_from_report_engine()
    result = gloop.tighten()

    # Find the bridge-generated suggestion
    bridge_sugg = [s for s in result.governance_suggestions if "[Path B Gap:" in s.rationale]
    assert len(bridge_sugg) > 0

    sugg = bridge_sugg[0]
    assert sugg.suggestion_type == "wire"  # constraint_missing maps to wire
    assert sugg.target_rule_id == "constraint_derivation"
    assert sugg.confidence == 0.8
    assert "gap_test" in sugg.rationale


# ── Test 6: Multiple bridge sources ───────────────────────────────────────────

def test_bridge_ingest_multiple_sources():
    """Test that bridge can ingest compliance results, budget snapshots, etc."""
    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)
    bridge = ExperienceBridge()

    bridge_input = BridgeInput(
        cieu_records=[
            {
                "func_name": "path_b.test",
                "path_b_event": "TEST_EVENT",
                "params": {"agent_id": "agent_001"},
                "violations": [],
                "source": "path_b_agent",
            }
        ],
        compliance_results=[
            {"agent_id": "agent_002", "compliant": True}
        ],
        budget_snapshots=[
            {"agent_id": "agent_003", "budget_remaining": 0.5}
        ],
        disconnect_events=[
            {"agent_id": "agent_004", "reason": "constraint_exhaustion"}
        ],
    )

    bridge.ingest(bridge_input)

    # Should have ingested all sources
    assert len(bridge._raw_records) == 4

    gloop = GovernanceLoop(
        report_engine=report_engine,
        experience_bridge=bridge,
    )

    obs = gloop.observe_from_report_engine()
    assert "external_constraint_effectiveness_rate" in obs.raw_kpis
