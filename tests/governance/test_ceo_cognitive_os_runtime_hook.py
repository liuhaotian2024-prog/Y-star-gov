from __future__ import annotations

from ystar.governance.ceo_cognitive_os_contract import build_ceo_cognitive_os_contract
from ystar.governance.ceo_cognitive_os_runtime_hook import (
    CEOCognitiveOSRuntimeDecisionValue,
    classify_ceo_major_action,
    validate_ceo_runtime_envelope,
)


def _valid_pre_action_packet(action_class: str = "internal_strategy_runtime_action") -> dict:
    contract = build_ceo_cognitive_os_contract()
    return {
        "packet_id": "e85_pre_action_packet",
        "job_id": "E85_CEO_Nervous_System_L5_Runtime_Foundation_R1",
        "proposed_action": "route CEO major action through Y-star-gov runtime hook",
        "action_class": action_class,
        "owner_intent": "make CEO major actions pass deterministic runtime validation",
        "current_mission_context": {"reasoning_scope": "repository_evidence_backed"},
        "discovered_capabilities_consulted": [
            {
                "capability_id": "ceo_cognitive_os_validator",
                "evidence_paths": ["ystar/governance/ceo_cognitive_os_contract.py"],
                "claimed_runtime_active": True,
                "runtime_evidence_status": "runtime_active_verified",
            },
            {
                "capability_id": "ceo_cognitive_os_runtime_hook",
                "evidence_paths": ["ystar/governance/ceo_cognitive_os_runtime_hook.py"],
                "claimed_runtime_active": True,
                "runtime_evidence_status": "runtime_active_verified",
            },
        ],
        "historical_assets_consulted": ["E81 contract", "E83 guided-revision semantics", "E84 runtime audit"],
        "canonical_owner_map": {"Y-star-gov": "governance validation", "bridge-labs": "CEO packet producer"},
        "no_new_wheel_decision": {"decision": "wrap_existing_validator", "non_duplication_proof": "no new governance engine"},
        "candidate_actions": ["runtime hook wrapper", "bridge-only adapter"],
        "counterfactual_comparison": [
            {"candidate": "runtime hook wrapper", "expected_gain": "runtime decision semantics"},
            {"candidate": "bridge-only adapter", "expected_gain": "compatibility but weaker runtime binding"},
        ],
        "predicted_CIEU_records": [
            {
                "X_t": "CEO major action proposed",
                "U_t": "validate through Y-star-gov runtime hook",
                "Y_star_t": "major action cannot bypass CEO Cognitive OS",
                "expected_Y_t_plus_1": "runtime decision returned without external execution",
                "predicted_R_t_plus_1": "formal CIEU log write remains deferred",
                "residual_severity": "medium",
            }
        ],
        "adversarial_critique": "The wrapper could still be bypassed unless bridge-labs routes major actions through it.",
        "what_not_to_do": ["do not execute external work", "do not claim L5 completion"],
        "selected_action": "runtime hook wrapper",
        "why_this_action": "It binds existing deterministic validation to a runtime envelope.",
        "why_not_other_actions": "Direct provider execution is premature before owner-approved L4 feedback.",
        "safety_boundary": {"external_action_allowed": False},
        "overclaim_boundary": {
            "customer_validation_claim": False,
            "expert_validation_claim": False,
            "paid_signal_claim": False,
            "pricing_validation_claim": False,
            "compliance_legal_claim": False,
            "production_deployment_claim": False,
            "live_ledger_claim": False,
            "L4_execution_claim": False,
            "L5_readiness_claim": False,
        },
        "Y_star_contract_hash_input": "sha256:e85-runtime-hook",
        "required_YstarGov_check": "validate_ceo_pre_action_packet",
        "approval_required": False,
        "owner_approval_state": "not_required",
        "bypass_attempt": False,
        "loop_stage_results": [
            {"stage_id": stage_id, "status": "passed", "evidence_paths": ["repo://E85/runtime-hook"]}
            for stage_id in contract.required_loop_stage_ids
        ],
    }


def _valid_envelope(**overrides) -> dict:
    packet = overrides.pop("pre_action_packet", _valid_pre_action_packet())
    envelope = {
        "action_id": "e85_runtime_action",
        "actor": "ceo",
        "role": "ceo",
        "action_type": "major_action",
        "mission": "CEO nervous system runtime foundation",
        "objective": "strategy mutation through governance runtime",
        "declared_intent": "validate CEO major action before acceptance",
        "context": "repository evidence backed runtime hook test",
        "proposed_execution_boundary": "internal approved next step only",
        "externality_level": "internal",
        "owner_approval_status": "not_required",
        "counterfactual_alternatives": ["runtime hook wrapper", "bridge-only direct validator"],
        "evidence_basis": ["ystar/governance/ceo_cognitive_os_runtime_hook.py"],
        "rollback_containment_plan": "block execution and return correct_path if validation fails",
        "pre_action_packet": packet,
        "formal_CIEU_log_written": False,
    }
    envelope.update(overrides)
    return envelope


def _valid_post_action_residual() -> dict:
    return {
        "packet_id": "e85_post_action_residual",
        "linked_pre_action_packet_id": "e85_pre_action_packet",
        "action_taken": "runtime hook validation",
        "expected_outcome": "runtime decision returned",
        "actual_output": "ALLOW without external execution",
        "CIEU_record": {
            "X_t": "pre-action packet accepted",
            "U_t": "runtime hook wrapper called validator",
            "Y_star_t": "major action remains governance-gated",
            "Y_t_plus_1": "post-action residual validated",
            "R_t_plus_1": "formal CIEU log write still deferred",
        },
        "residuals": ["formal CIEU log write deferred"],
        "unexpected_failures": [],
        "overclaim_check": {
            "customer_validation_claim": False,
            "expert_validation_claim": False,
            "paid_signal_claim": False,
            "pricing_validation_claim": False,
            "compliance_legal_claim": False,
            "production_deployment_claim": False,
            "live_ledger_claim": False,
            "L4_execution_claim": False,
            "L5_readiness_claim": False,
        },
        "no_new_wheel_check": {"passed": True},
        "owner_usefulness_check": {"passed": True},
        "intelligence_gate_result": {"passed": True},
        "capability_state_updates": ["runtime hook foundation wired"],
        "learning_candidates": ["formal CIEU log insertion needs E86"],
        "YstarGov_sync_status": "runtime_hook_foundation_active",
        "next_action_recommendation": "E86 formal CIEU log insertion narrowing",
        "what_not_to_do_next": ["do not claim L5 completion"],
    }


def test_major_action_classifier_covers_required_categories():
    envelope = _valid_envelope(
        action_type="L4 provider tool execution and pricing strategy mutation",
        declared_intent="prepare customer contact, payment, publication, CIEU log write, brain memory write",
        proposed_execution_boundary="cross-repo governance mutation with owner approval boundary",
    )

    classification = classify_ceo_major_action(envelope)

    assert classification.requires_ceo_cognitive_os is True
    for category in {
        "customer_contact_action",
        "payment_revenue_pricing_action",
        "public_publication",
        "provider_tool_execution",
        "strategy_mutation",
        "CIEU_log_write_claim",
        "brain_memory_write",
        "cross_repo_governance_mutation",
        "owner_approval_boundary_crossing",
        "L4_L5_escalation_attempt",
    }:
        assert category in classification.categories


def test_ceo_major_action_hook_calls_validator_and_allows_internal_next_step():
    result = validate_ceo_runtime_envelope(_valid_envelope())
    data = result.to_dict()

    assert result.decision == CEOCognitiveOSRuntimeDecisionValue.ALLOW
    assert data["validator_result"]["validator"] == "validate_ceo_pre_action_packet"
    assert data["route"] == "continue_to_approved_next_step_without_external_execution"
    assert data["allow_approved_next_step"] is True
    assert data["allow_external_execution"] is False
    assert data["external_action_executed"] is False


def test_missing_repairable_cognition_fields_return_require_revision():
    packet = _valid_pre_action_packet()
    packet["counterfactual_comparison"] = []

    result = validate_ceo_runtime_envelope(_valid_envelope(pre_action_packet=packet))
    data = result.to_dict()

    assert result.decision == CEOCognitiveOSRuntimeDecisionValue.REQUIRE_REVISION
    assert data["route"] == "return_correct_path_guidance_to_ceo"
    assert data["correct_path"]
    assert data["guidance"]["guidance_type"] == "require_revision"


def test_missing_pre_action_packet_is_require_revision_not_escalate():
    envelope = _valid_envelope()
    envelope.pop("pre_action_packet")

    result = validate_ceo_runtime_envelope(envelope)

    assert result.decision == CEOCognitiveOSRuntimeDecisionValue.REQUIRE_REVISION
    assert result.route == "return_correct_path_guidance_to_ceo"


def test_hard_boundary_violation_returns_deny():
    envelope = _valid_envelope(bypass_attempt=True)

    result = validate_ceo_runtime_envelope(envelope)

    assert result.decision == CEOCognitiveOSRuntimeDecisionValue.DENY
    assert result.route == "block_execution_and_record_residual"
    assert result.cieu_validation_record_candidate


def test_recent_memory_only_reasoning_is_runtime_deny():
    packet = _valid_pre_action_packet()
    packet["current_mission_context"] = {"reasoning_scope": "recent_memory_only"}

    result = validate_ceo_runtime_envelope(_valid_envelope(pre_action_packet=packet))

    assert result.decision == CEOCognitiveOSRuntimeDecisionValue.DENY
    assert "recent-memory-only" in result.reason


def test_l4_without_owner_approval_escalates_not_allows():
    packet = _valid_pre_action_packet(action_class="L4_external_feedback_execution")
    packet["approval_required"] = True
    packet["owner_approval_state"] = "pending_owner_decision"

    result = validate_ceo_runtime_envelope(
        _valid_envelope(
            pre_action_packet=packet,
            action_type="L4 external feedback execution",
            externality_level="external_feedback",
            owner_approval_status="pending_owner_decision",
        )
    )

    assert result.decision == CEOCognitiveOSRuntimeDecisionValue.ESCALATE
    assert result.route == "generate_owner_decision_packet_no_execution"
    assert result.requires_owner_decision is True
    assert result.allow_external_execution is False


def test_post_action_residual_is_required_and_validated():
    missing = validate_ceo_runtime_envelope(_valid_envelope(action_phase="completed"))
    assert missing.decision == CEOCognitiveOSRuntimeDecisionValue.REQUIRE_REVISION
    assert missing.post_action_residual_required is True

    result = validate_ceo_runtime_envelope(
        _valid_envelope(action_phase="completed", post_action_residual=_valid_post_action_residual())
    )

    assert result.decision == CEOCognitiveOSRuntimeDecisionValue.ALLOW
    assert result.post_action_residual_validation["decision"] == "ALLOW"
    assert result.post_action_residual_required is True


def test_cieu_log_write_is_deferred_candidate_only():
    result = validate_ceo_runtime_envelope(_valid_envelope())
    data = result.to_dict()

    assert data["cieu_validation_record_candidate"]
    assert data["formal_CIEU_log_written"] is False
    assert data["formal_CIEU_log_status"] == "CIEU_log_write_deferred"


def test_unsupported_formal_cieu_log_claim_is_deny():
    result = validate_ceo_runtime_envelope(_valid_envelope(formal_CIEU_log_written=True))

    assert result.decision == CEOCognitiveOSRuntimeDecisionValue.DENY
    assert "formal CIEU log write claim" in result.reason
