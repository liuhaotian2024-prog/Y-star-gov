from copy import deepcopy

from ystar.governance.ceo_cognitive_os_contract import (
    CEOCognitiveOSDecisionValue,
    build_ceo_cognitive_os_cieu_record,
    build_ceo_cognitive_os_contract,
    validate_ceo_post_action_residual,
    validate_ceo_pre_action_packet,
)


def valid_pre_action_packet():
    contract = build_ceo_cognitive_os_contract()
    return {
        "packet_id": "ceo-pre-1",
        "job_id": "job-1",
        "proposed_action": "prepare owner decision for narrow L4 feedback",
        "action_class": "owner_decision_preparation",
        "owner_intent": "force CEO work through repository-evidenced cognition",
        "current_mission_context": {"reasoning_scope": "discovery_first_full_ecosystem"},
        "discovered_capabilities_consulted": [
            {
                "capability_id": "cap_bridge_labs_e80_inventory",
                "evidence_paths": ["operations/external_validation/e80_whole_ecosystem_capability_inventory.json"],
                "claimed_runtime_active": False,
            }
        ],
        "historical_assets_consulted": ["E24 legacy commercial assets", "E80 raw inventory"],
        "canonical_owner_map": {"Y-star-gov": "canonical governance", "bridge-labs": "packet producer"},
        "no_new_wheel_decision": {"decision": "wrap_existing", "non_duplication_proof": "no governance clone"},
        "candidate_actions": ["sync Y-star-gov", "narrow L4 message"],
        "counterfactual_comparison": [
            {"candidate": "sync Y-star-gov", "expected_gain": "canonical enforcement"},
            {"candidate": "narrow L4 message", "expected_gain": "better feedback quality"},
        ],
        "predicted_CIEU_records": [
            {
                "X_t": "bridge-labs pre-sync validator exists",
                "U_t": "validate through Y-star-gov",
                "Y_star_t": "CEO work cannot bypass cognitive OS",
                "expected_Y_t_plus_1": "deterministic ALLOW/REQUIRE_REVISION/DENY/ESCALATE",
                "predicted_R_t_plus_1": "hook wiring remains future work",
                "residual_severity": "medium",
            }
        ],
        "adversarial_critique": "This could become governance theater if not tied to L4 feedback.",
        "what_not_to_do": ["do not execute L4", "do not claim customer validation"],
        "selected_action": "sync Y-star-gov",
        "why_this_action": "canonical governance should judge the packet",
        "why_not_other_actions": "direct L4 execution is not approved",
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
        "Y_star_contract_hash_input": "sha256:test",
        "required_YstarGov_check": "validate_ceo_pre_action_packet",
        "approval_required": True,
        "owner_approval_state": "pending_owner_decision",
        "bypass_attempt": False,
        "loop_stage_results": [
            {"stage_id": stage_id, "status": "passed", "evidence_paths": ["repo://evidence"]}
            for stage_id in contract.required_loop_stage_ids
        ],
    }


def valid_post_action_residual():
    return {
        "packet_id": "ceo-post-1",
        "linked_pre_action_packet_id": "ceo-pre-1",
        "action_taken": "sync Y-star-gov",
        "expected_outcome": "validator exists",
        "actual_output": "validator added and tests pass",
        "CIEU_record": {
            "X_t": "pre-sync validator exists",
            "U_t": "add Y-star-gov validator",
            "Y_star_t": "canonical cognitive OS sync",
            "Y_t_plus_1": "Y-star-gov validates packets",
            "R_t_plus_1": "hook wiring still pending",
        },
        "residuals": ["hook runtime wiring pending"],
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
        "capability_state_updates": ["Y-star-gov validator synced"],
        "learning_candidates": ["wire hook later"],
        "YstarGov_sync_status": "YstarGov_synced",
        "next_action_recommendation": "record owner L4 decision",
        "what_not_to_do_next": ["do not execute L4 without owner approval"],
    }


def assert_denied(packet, expected_stage):
    result = validate_ceo_pre_action_packet(packet)
    assert result.decision == CEOCognitiveOSDecisionValue.DENY
    assert result.failed_stage == expected_stage
    assert result.passed is False


def assert_requires_revision(packet, expected_stage):
    result = validate_ceo_pre_action_packet(packet)
    assert result.decision == CEOCognitiveOSDecisionValue.REQUIRE_REVISION
    assert result.failed_stage == expected_stage
    assert result.passed is False
    assert result.guidance["guidance_type"] == "require_revision"
    assert result.correct_path
    assert result.cieu_validation_record["Y_t_plus_1"]["decision"] == "REQUIRE_REVISION"


def test_valid_pre_action_packet_allows():
    result = validate_ceo_pre_action_packet(valid_pre_action_packet())

    assert result.decision == CEOCognitiveOSDecisionValue.ALLOW
    assert result.passed is True
    assert result.cieu_validation_record["X_t"]["contract_id"] == "ceo_cognitive_os_loop_contract_v1"


def test_missing_required_field_requires_revision_with_guidance():
    packet = valid_pre_action_packet()
    packet.pop("owner_intent")

    result = validate_ceo_pre_action_packet(packet)

    assert result.decision == CEOCognitiveOSDecisionValue.REQUIRE_REVISION
    assert result.failed_stage == "schema"
    assert "owner_intent" in result.guidance["missing_fields"]
    assert "fill missing fields: owner_intent" in result.correct_path


def test_bypass_attempt_denies():
    packet = valid_pre_action_packet()
    packet["bypass_attempt"] = True

    assert_denied(packet, "bypass_policy")


def test_missing_loop_stage_requires_revision_with_stage_guidance():
    packet = valid_pre_action_packet()
    packet["loop_stage_results"] = packet["loop_stage_results"][:-1]

    result = validate_ceo_pre_action_packet(packet)

    assert result.decision == CEOCognitiveOSDecisionValue.REQUIRE_REVISION
    assert result.failed_stage == "cognitive_os_loop"
    assert "post_action_CIEU_residual_and_learning_update" in result.guidance["missing_loop_stages"]


def test_recent_memory_only_requires_revision():
    packet = valid_pre_action_packet()
    packet["current_mission_context"]["reasoning_scope"] = "recent_memory_only"

    assert_requires_revision(packet, "full_capability_inventory_recall")


def test_no_counterfactual_comparison_requires_revision():
    packet = valid_pre_action_packet()
    packet["counterfactual_comparison"] = []

    assert_requires_revision(packet, "counterfactual_action_comparison")


def test_missing_pre_action_cieu_prediction_requires_revision():
    packet = valid_pre_action_packet()
    packet["predicted_CIEU_records"] = []

    assert_requires_revision(packet, "pre_action_CIEU_residual_prediction")


def test_malformed_pre_action_cieu_prediction_requires_revision():
    packet = valid_pre_action_packet()
    packet["predicted_CIEU_records"][0].pop("predicted_R_t_plus_1")

    assert_requires_revision(packet, "pre_action_CIEU_residual_prediction")


def test_missing_adversarial_critique_requires_revision():
    packet = valid_pre_action_packet()
    packet["adversarial_critique"] = ""

    assert_requires_revision(packet, "adversarial_critique")


def test_missing_what_not_to_do_requires_revision():
    packet = valid_pre_action_packet()
    packet["what_not_to_do"] = []

    assert_requires_revision(packet, "what_not_to_do")


def test_construction_without_no_new_wheel_proof_requires_revision():
    packet = valid_pre_action_packet()
    packet["action_class"] = "new_module_construction"
    packet["no_new_wheel_decision"] = {"decision": "create_new"}

    assert_requires_revision(packet, "no_new_wheel_gate")


def test_explicit_duplicate_core_mechanism_denies():
    packet = valid_pre_action_packet()
    packet["action_class"] = "new_module_construction"
    packet["proposed_action"] = "duplicate the Y-star-gov governance engine inside bridge-labs"
    packet["no_new_wheel_decision"] = {"decision": "create_new"}

    assert_denied(packet, "no_new_wheel_gate")


def test_l4_external_action_without_owner_approval_escalates_with_owner_path():
    packet = valid_pre_action_packet()
    packet["action_class"] = "L4_external_feedback_execution"
    packet["owner_approval_state"] = "pending_owner_decision"

    result = validate_ceo_pre_action_packet(packet)

    assert result.decision == CEOCognitiveOSDecisionValue.ESCALATE
    assert result.failed_stage == "owner_approval_gate"
    assert result.requires_owner_decision is True
    assert result.guidance["guidance_type"] == "owner_decision_required"
    assert "do not execute until owner_approval_state is approved" in result.correct_path


def test_forbidden_claim_takes_precedence_over_owner_escalation():
    packet = valid_pre_action_packet()
    packet["action_class"] = "L4_external_feedback_execution"
    packet["owner_approval_state"] = "pending_owner_decision"
    packet["overclaim_boundary"]["customer_validation_claim"] = True

    result = validate_ceo_pre_action_packet(packet)

    assert result.decision == CEOCognitiveOSDecisionValue.DENY
    assert result.failed_stage == "overclaim_boundary"


def test_forbidden_customer_paid_compliance_production_l5_claims_deny():
    for claim in [
        "customer_validation_claim",
        "paid_signal_claim",
        "compliance_legal_claim",
        "production_deployment_claim",
        "L5_readiness_claim",
    ]:
        packet = valid_pre_action_packet()
        packet["overclaim_boundary"][claim] = True

        result = validate_ceo_pre_action_packet(packet)

        assert result.decision == CEOCognitiveOSDecisionValue.DENY
        assert result.failed_stage == "overclaim_boundary"


def test_unverified_runtime_active_capability_claim_denies():
    packet = valid_pre_action_packet()
    packet["discovered_capabilities_consulted"][0] = {
        "capability_id": "unverified_runtime_capability",
        "evidence_paths": ["repo://some-file"],
        "claimed_runtime_active": True,
        "activation_state": "dormant",
    }

    assert_denied(packet, "repository_evidence")


def test_missing_repository_evidence_requires_revision():
    packet = valid_pre_action_packet()
    packet["discovered_capabilities_consulted"][0] = {
        "capability_id": "missing_evidence_paths",
        "claimed_runtime_active": False,
    }

    assert_requires_revision(packet, "repository_evidence")


def test_valid_post_action_residual_allows():
    result = validate_ceo_post_action_residual(valid_post_action_residual())

    assert result.decision == CEOCognitiveOSDecisionValue.ALLOW
    assert result.cieu_validation_record["Y_t_plus_1"]["decision"] == "ALLOW"


def test_post_action_residual_missing_cieu_fields_requires_revision():
    residual = valid_post_action_residual()
    residual["CIEU_record"].pop("R_t_plus_1")

    result = validate_ceo_post_action_residual(residual)

    assert result.decision == CEOCognitiveOSDecisionValue.REQUIRE_REVISION
    assert result.failed_stage == "post_action_CIEU_residual"
    assert result.guidance["guidance_type"] == "require_revision"


def test_post_action_residual_forbidden_claim_denies():
    residual = valid_post_action_residual()
    residual["overclaim_check"]["customer_validation_claim"] = True

    result = validate_ceo_post_action_residual(residual)

    assert result.decision == CEOCognitiveOSDecisionValue.DENY
    assert result.failed_stage == "post_action_overclaim_check"


def test_generated_cieu_validation_record_has_five_tuple():
    result = validate_ceo_pre_action_packet(valid_pre_action_packet())
    record = build_ceo_cognitive_os_cieu_record(valid_pre_action_packet(), result)

    assert {"X_t", "U_t", "Y_star_t", "Y_t_plus_1", "R_t_plus_1"}.issubset(record)


def test_cieu_validation_record_includes_guidance_path_when_revision_required():
    packet = valid_pre_action_packet()
    packet["counterfactual_comparison"] = []

    result = validate_ceo_pre_action_packet(packet)

    assert result.cieu_validation_record["Y_t_plus_1"]["guidance"]["guidance_type"] == "require_revision"
    assert result.cieu_validation_record["Y_t_plus_1"]["correct_path"]


def test_module_uses_standard_library_only():
    import ystar.governance.ceo_cognitive_os_contract as module

    assert "jsonschema" not in getattr(module, "__dict__", {})


def test_validators_do_not_mutate_input_packet():
    packet = valid_pre_action_packet()
    original = deepcopy(packet)

    validate_ceo_pre_action_packet(packet)

    assert packet == original
