from __future__ import annotations

from ystar.governance.aiden_model_orchestration_contract import (
    validate_aiden_model_orchestration_packet,
    validate_and_write_aiden_model_orchestration_packet,
)


def valid_packet() -> dict:
    return {
        "orchestration_id": "e123_test_model_orchestration",
        "task_context": {
            "task_id": "task_low_risk_local_reasoning",
            "owner_intent": "Summarize local memory assets for Aiden.",
            "task_type": "local_reasoning",
            "risk_tier": "low_internal",
            "privacy_tier": "local_private",
            "context_size": "medium",
            "required_wisdom_level": "medium",
        },
        "routing_factors": {
            "task_type": "local_reasoning",
            "risk_tier": "low_internal",
            "privacy_tier": "local_private",
            "context_size": "medium",
            "cost_sensitivity": "prefer_local_low_cost",
            "required_wisdom_level": "medium",
        },
        "candidate_models": [
            {"model_id": "local_gemma4_e4b", "role": "local_reasoner"},
            {"model_id": "local_ystar_gemma", "role": "local_reasoner"},
            {"model_id": "deterministic_validator", "role": "validator"},
            {"model_id": "codex_executor", "role": "executor"},
        ],
        "selected_model": {
            "model_id": "local_gemma4_e4b",
            "role": "local_reasoner",
            "selection_reason": "private local reasoning with low cost and sufficient context",
        },
        "execution_boundary": {
            "local_only": True,
            "external_provider_call_allowed": False,
            "host_runtime_service_bridge_required": True,
            "host_service_controller_proof": {"status": "service_bridge_running"},
        },
        "memory_context_plan": {
            "local_long_term_memory_required": True,
            "recent_memory_only": False,
            "discovered_memory_assets": [
                {"asset_id": "CIEUStore_formal_memory", "reuse_status": "mandatory"},
                {"asset_id": "Aiden_6D_brain", "reuse_status": "mandatory"},
                {"asset_id": "YstarGov_memory_store", "reuse_status": "reuse_as_team_memory"},
                {"asset_id": "meeting_room_turn_memory", "reuse_status": "short_context_only"},
            ],
        },
        "quality_comparison_plan": {
            "comparison_required": True,
            "metrics": ["task_fit", "privacy_preservation", "evidence_grounding", "latency", "cost"],
            "CIEU_recording_required": True,
            "raw_private_prompt_shadowing_allowed": False,
        },
        "routing_policy_update": {
            "update_mode": "proposal_only",
            "direct_policy_mutation": False,
            "owner_review_required": True,
        },
        "CIEU_linkage": {"CIEU_recording_required": True},
        "truth_constraints": {
            "model_choice_recent_memory_only": False,
            "raw_prompt_to_codex_without_CEOImplementationOrder": False,
            "external_model_called_without_owner_approval": False,
            "private_data_sent_to_external_model": False,
            "arbitrary_shell_allowed": False,
            "external_business_action_executed": False,
            "customer_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "direct_brain_write_without_owner_gate": False,
            "direct_policy_mutation": False,
            "K9Audit_write_claim": False,
        },
    }


def test_valid_local_gemma_packet_allows() -> None:
    decision = validate_aiden_model_orchestration_packet(valid_packet()).to_dict()
    assert decision["decision"] == "ALLOW"


def test_external_model_without_owner_approval_escalates() -> None:
    packet = valid_packet()
    packet["candidate_models"].append({"model_id": "external_gpt", "role": "frontier_reasoner"})
    packet["selected_model"] = {"model_id": "external_gpt", "role": "frontier_reasoner"}
    packet["execution_boundary"] = {
        "external_provider_call_allowed": True,
        "redacted_context_only": True,
    }
    decision = validate_aiden_model_orchestration_packet(packet).to_dict()
    assert decision["decision"] == "ESCALATE"
    assert decision["guidance"]["requires_owner_decision"] is True


def test_external_model_with_private_unredacted_context_denies() -> None:
    packet = valid_packet()
    packet["candidate_models"].append({"model_id": "external_claude", "role": "frontier_reasoner"})
    packet["selected_model"] = {"model_id": "external_claude", "role": "frontier_reasoner"}
    packet["owner_approval"] = {"owner_approved_external_model_use": True}
    packet["task_context"]["privacy_tier"] = "private"
    packet["execution_boundary"] = {"external_provider_call_allowed": True, "redacted_context_only": False}
    decision = validate_aiden_model_orchestration_packet(packet).to_dict()
    assert decision["decision"] == "DENY"


def test_missing_long_term_memory_requires_revision() -> None:
    packet = valid_packet()
    packet["memory_context_plan"]["discovered_memory_assets"] = [
        {"asset_id": "meeting_room_turn_memory", "reuse_status": "short_context_only"}
    ]
    decision = validate_aiden_model_orchestration_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "memory_context_plan"


def test_direct_routing_policy_mutation_denies() -> None:
    packet = valid_packet()
    packet["routing_policy_update"]["direct_policy_mutation"] = True
    decision = validate_aiden_model_orchestration_packet(packet).to_dict()
    assert decision["decision"] == "DENY"


def test_validate_and_write_model_orchestration_packet(tmp_path) -> None:
    result = validate_and_write_aiden_model_orchestration_packet(
        valid_packet(),
        cieu_db=str(tmp_path / "e123_cieu.db"),
        session_id="e123_model_orchestration_test",
    )
    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["event_type"] == "AIDEN_MODEL_ORCHESTRATION_DECISION"
