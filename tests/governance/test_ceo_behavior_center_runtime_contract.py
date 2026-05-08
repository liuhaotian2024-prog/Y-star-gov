from __future__ import annotations

import sqlite3

from ystar.governance import (
    CEO_BEHAVIOR_CENTER_RUNTIME_EVENT_TYPE,
    CEOBehaviorCenterDecisionValue,
    validate_and_write_ceo_behavior_center_runtime_packet,
    validate_ceo_behavior_center_runtime_packet,
)


def _packet(**overrides):
    packet = {
        "packet_id": "e94_behavior_packet_test",
        "session_id": "e94_behavior_session_test",
        "agent_id": "bridge_labs_ceo",
        "source_owner_message": "what should we do next",
        "behavior_center_source": "office/aiden_meeting_room/aiden_response_engine.py::answer_owner",
        "behavior_center_response": "Use the governed behavior runtime gateway.",
        "intent": "general",
        "brain_provenance": {
            "brain_db": "/tmp/aiden_brain.db",
            "total_activations": 5,
            "unique_nodes": 3,
        },
        "brain_activations": [
            {
                "node_id": "WHO_I_AM",
                "node_name": "Who I Am",
                "file_path": "WHO_I_AM.md",
                "activation_level": 1.2,
                "hop_distance": 0,
                "evidence_ref": "brain://WHO_I_AM",
            }
        ],
        "action_classification": {
            "action_type": "status_or_internal_runtime",
            "route_type": "autonomous_internal_runtime",
            "risk_tier": "TIER_0_INTERNAL",
            "externality_level": "internal",
        },
        "autonomous_execution_policy": {
            "risk_tier": "TIER_0_INTERNAL",
            "can_autonomously_execute": True,
            "owner_decision_required": False,
            "high_risk_external_side_effect": False,
            "real_external_action_executed": False,
            "provider_action_executed": False,
            "no_send_invariant": True,
        },
        "truth_constraints": {
            "private_chain_of_thought_stored": False,
            "no_customer_validation_claim": True,
            "no_revenue_payment_claim": True,
            "no_K9Audit_integration_claim": True,
        },
        "post_action_residual_required": True,
    }
    packet.update(overrides)
    return packet


def test_valid_low_risk_behavior_center_packet_allows():
    decision = validate_ceo_behavior_center_runtime_packet(_packet())
    assert decision.decision == CEOBehaviorCenterDecisionValue.ALLOW


def test_missing_brain_provenance_requires_revision():
    packet = _packet()
    del packet["brain_provenance"]
    decision = validate_ceo_behavior_center_runtime_packet(packet)
    assert decision.decision == CEOBehaviorCenterDecisionValue.REQUIRE_REVISION
    assert decision.failed_field == "brain_provenance"


def test_low_risk_owner_default_requires_revision():
    packet = _packet(
        autonomous_execution_policy={
            "risk_tier": "TIER_1_PUBLIC_READ_ONLY",
            "can_autonomously_execute": False,
            "owner_decision_required": True,
            "high_risk_external_side_effect": False,
            "real_external_action_executed": False,
            "provider_action_executed": False,
            "no_send_invariant": True,
        },
        action_classification={
            "action_type": "public_read",
            "route_type": "autonomous_public_read_only",
            "risk_tier": "TIER_1_PUBLIC_READ_ONLY",
            "externality_level": "public_read_only",
        },
    )
    decision = validate_ceo_behavior_center_runtime_packet(packet)
    assert decision.decision == CEOBehaviorCenterDecisionValue.REQUIRE_REVISION
    assert "autonomously" in decision.reason


def test_high_risk_autonomous_payment_denied():
    packet = _packet(
        source_owner_message="send payment now",
        action_classification={
            "action_type": "payment",
            "route_type": "high_risk_owner_decision",
            "risk_tier": "TIER_4_COMMERCIAL_LEGAL_PRODUCTION_HIGH_RISK",
            "externality_level": "external_side_effect",
        },
        autonomous_execution_policy={
            "risk_tier": "TIER_4_COMMERCIAL_LEGAL_PRODUCTION_HIGH_RISK",
            "can_autonomously_execute": True,
            "owner_decision_required": False,
            "high_risk_external_side_effect": True,
            "real_external_action_executed": False,
            "provider_action_executed": False,
            "no_send_invariant": True,
        },
    )
    decision = validate_ceo_behavior_center_runtime_packet(packet)
    assert decision.decision == CEOBehaviorCenterDecisionValue.DENY


def test_high_risk_owner_bound_escalates():
    packet = _packet(
        source_owner_message="legal contract approval",
        action_classification={
            "action_type": "legal_contract",
            "route_type": "high_risk_owner_decision",
            "risk_tier": "TIER_4_COMMERCIAL_LEGAL_PRODUCTION_HIGH_RISK",
            "externality_level": "external_side_effect",
        },
        autonomous_execution_policy={
            "risk_tier": "TIER_4_COMMERCIAL_LEGAL_PRODUCTION_HIGH_RISK",
            "can_autonomously_execute": False,
            "owner_decision_required": True,
            "high_risk_external_side_effect": True,
            "real_external_action_executed": False,
            "provider_action_executed": False,
            "no_send_invariant": True,
        },
    )
    decision = validate_ceo_behavior_center_runtime_packet(packet)
    assert decision.decision == CEOBehaviorCenterDecisionValue.ESCALATE
    assert decision.requires_owner_decision is True


def test_provider_dry_run_without_no_send_requires_revision():
    packet = _packet(
        action_classification={
            "action_type": "external_validation_message",
            "route_type": "low_risk_external_validation_dry_run",
            "risk_tier": "TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION",
            "externality_level": "dry_run_only",
        },
        autonomous_execution_policy={
            "risk_tier": "TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION",
            "can_autonomously_execute": True,
            "owner_decision_required": False,
            "high_risk_external_side_effect": False,
            "gov_mcp_dry_run_required": True,
            "real_external_action_executed": False,
            "provider_action_executed": False,
            "no_send_invariant": False,
        },
    )
    decision = validate_ceo_behavior_center_runtime_packet(packet)
    assert decision.decision == CEOBehaviorCenterDecisionValue.REQUIRE_REVISION
    assert decision.failed_field == "no_send_invariant"


def test_formal_cieu_write_for_behavior_center_packet(tmp_path):
    db = tmp_path / "e94_behavior.db"
    result = validate_and_write_ceo_behavior_center_runtime_packet(
        _packet(),
        cieu_db=str(db),
        session_id="e94_behavior_session",
        seal_session=True,
    )
    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    con = sqlite3.connect(str(db))
    rows = con.execute("select event_type, decision from cieu_events").fetchall()
    assert rows == [(CEO_BEHAVIOR_CENTER_RUNTIME_EVENT_TYPE, "allow")]
    seal = con.execute("select event_count, merkle_root from sealed_sessions").fetchone()
    assert seal[0] == 1
    assert seal[1]
