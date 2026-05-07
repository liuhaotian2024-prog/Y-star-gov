from __future__ import annotations

import json

from ystar.governance.ceo_cognitive_os_cieu_log import (
    CEO_COGNITIVE_OS_CIEU_EVENT_TYPE,
    FORMAL_CIEU_LOG_PATH,
    validate_and_write_ceo_runtime_envelope,
    write_ceo_cognitive_os_cieu_log_record,
)
from ystar.governance.ceo_cognitive_os_contract import build_ceo_cognitive_os_contract
from ystar.governance.ceo_cognitive_os_runtime_hook import (
    CEOCognitiveOSRuntimeDecisionValue,
    validate_ceo_runtime_envelope,
)
from ystar.governance.cieu_store import CIEUStore


def _valid_pre_action_packet(action_class: str = "internal_strategy_runtime_action") -> dict:
    contract = build_ceo_cognitive_os_contract()
    return {
        "packet_id": "e86_pre_action_packet",
        "job_id": "E86_YStarGov_CEO_Cognitive_OS_CIEU_Log_Write_Insertion_Point_R1",
        "proposed_action": "persist CEO Cognitive OS runtime decision through existing CIEUStore",
        "action_class": action_class,
        "owner_intent": "prove formal CIEU record insertion without creating a parallel ledger",
        "current_mission_context": {"reasoning_scope": "repository_evidence_backed"},
        "discovered_capabilities_consulted": [
            {
                "capability_id": "ceo_cognitive_os_cieu_log_writer",
                "evidence_paths": ["ystar/governance/ceo_cognitive_os_cieu_log.py"],
                "claimed_runtime_active": True,
                "runtime_evidence_status": "runtime_active_verified",
            },
            {
                "capability_id": "cieu_store",
                "evidence_paths": ["ystar/governance/cieu_store.py"],
                "claimed_runtime_active": True,
                "runtime_evidence_status": "runtime_active_verified",
            },
        ],
        "historical_assets_consulted": ["E85R runtime hook", "Y-star-gov CIEUStore"],
        "canonical_owner_map": {"Y-star-gov": "CIEUStore and governance validation"},
        "no_new_wheel_decision": {"decision": "wrap_existing", "non_duplication_proof": "uses CIEUStore.write_dict"},
        "candidate_actions": ["explicit CIEU writer", "keep validation candidate only"],
        "counterfactual_comparison": [
            {"candidate": "explicit CIEU writer", "expected_gain": "formal record proof"},
            {"candidate": "candidate only", "expected_gain": "safe but incomplete"},
        ],
        "predicted_CIEU_records": [
            {
                "X_t": "CEO runtime decision exists",
                "U_t": "write through CIEUStore",
                "Y_star_t": "formal CIEU record can be queried and sealed",
                "expected_Y_t_plus_1": "record persisted in test DB",
                "predicted_R_t_plus_1": "K9Audit ledger integration remains separate",
                "residual_severity": "low",
            }
        ],
        "adversarial_critique": "A Y-star-gov CIEU record is not the same as K9Audit's separate ledger.",
        "what_not_to_do": ["do not create a parallel ledger", "do not execute external action"],
        "selected_action": "explicit CIEU writer",
        "why_this_action": "It uses existing Y-star-gov persistence.",
        "why_not_other_actions": "Automatic hidden writes would make validation side-effectful.",
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
        "Y_star_contract_hash_input": "sha256:e86-cieu-log",
        "required_YstarGov_check": "validate_ceo_pre_action_packet",
        "approval_required": False,
        "owner_approval_state": "not_required",
        "bypass_attempt": False,
        "loop_stage_results": [
            {"stage_id": stage_id, "status": "passed", "evidence_paths": ["repo://E86/cieu-log"]}
            for stage_id in contract.required_loop_stage_ids
        ],
    }


def _valid_envelope(**overrides) -> dict:
    packet = overrides.pop("pre_action_packet", _valid_pre_action_packet())
    envelope = {
        "action_id": "e86_cieu_log_action",
        "actor": "ceo",
        "role": "ceo",
        "action_type": "major_action",
        "mission": "CEO Cognitive OS CIEU insertion",
        "objective": "governance runtime record persistence",
        "declared_intent": "validate CEO major action and persist formal CIEU record",
        "context": "repository evidence backed test",
        "proposed_execution_boundary": "internal approved next step only",
        "externality_level": "internal",
        "owner_approval_status": "not_required",
        "counterfactual_alternatives": ["explicit CIEU writer", "candidate only"],
        "evidence_basis": ["ystar/governance/cieu_store.py"],
        "rollback_containment_plan": "delete test DB only",
        "pre_action_packet": packet,
        "formal_CIEU_log_written": False,
    }
    envelope.update(overrides)
    return envelope


def _valid_post_action_residual() -> dict:
    return {
        "packet_id": "e86_post_action_residual",
        "linked_pre_action_packet_id": "e86_pre_action_packet",
        "action_taken": "formal CIEU record test write",
        "expected_outcome": "record query succeeds",
        "actual_output": "record persisted in isolated test DB",
        "CIEU_record": {
            "X_t": "runtime result accepted",
            "U_t": "write CIEU record",
            "Y_star_t": "formal record is queryable",
            "Y_t_plus_1": "record written",
            "R_t_plus_1": "K9Audit ledger integration remains separate",
        },
        "residuals": ["K9Audit ledger not mutated"],
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
        "capability_state_updates": ["formal CIEU writer tested"],
        "learning_candidates": ["define optional K9Audit bridge separately if approved"],
        "YstarGov_sync_status": "formal_CIEU_record_path_verified",
        "next_action_recommendation": "E87 owner-approved CIEU/K9 evidence-chain bridge if needed",
        "what_not_to_do_next": ["do not call this K9Audit ledger write"],
    }


def _query_single(db_path, session_id: str):
    results = CIEUStore(str(db_path)).query(
        session_id=session_id,
        event_type=CEO_COGNITIVE_OS_CIEU_EVENT_TYPE,
        limit=10,
    )
    assert len(results) == 1
    return results[0]


def test_allow_runtime_decision_writes_queryable_and_sealable_cieu_record(tmp_path):
    db_path = tmp_path / "e86_cieu.db"
    envelope = _valid_envelope(session_id="e86-allow")
    runtime_result = validate_ceo_runtime_envelope(envelope)
    assert runtime_result.decision == CEOCognitiveOSRuntimeDecisionValue.ALLOW

    write_result = write_ceo_cognitive_os_cieu_log_record(
        envelope,
        runtime_result,
        cieu_db=str(db_path),
        seal_session=True,
    )

    assert write_result["formal_CIEU_log_written"] is True
    assert write_result["formal_CIEU_log_path"] == FORMAL_CIEU_LOG_PATH
    assert write_result["verify_result"]["valid"] is True
    record = _query_single(db_path, "e86-allow")
    assert record.decision == "allow"
    assert record.evidence_grade == "governance"
    result_payload = json.loads(record.result_json)
    assert result_payload["runtime_decision"] == "ALLOW"
    assert result_payload["formal_CIEU_log_path"] == FORMAL_CIEU_LOG_PATH


def test_require_revision_runtime_decision_writes_correct_path_record(tmp_path):
    db_path = tmp_path / "e86_cieu.db"
    packet = _valid_pre_action_packet()
    packet["counterfactual_comparison"] = []
    envelope = _valid_envelope(session_id="e86-revision", pre_action_packet=packet)
    runtime_result = validate_ceo_runtime_envelope(envelope)
    assert runtime_result.decision == CEOCognitiveOSRuntimeDecisionValue.REQUIRE_REVISION

    write_result = write_ceo_cognitive_os_cieu_log_record(
        envelope,
        runtime_result,
        cieu_db=str(db_path),
    )

    assert write_result["formal_CIEU_log_written"] is True
    record = _query_single(db_path, "e86-revision")
    assert record.decision == "rewrite"
    assert record.violations
    result_payload = json.loads(record.result_json)
    assert result_payload["runtime_decision"] == "REQUIRE_REVISION"
    assert result_payload["correct_path"]


def test_deny_runtime_decision_writes_blocked_residual_record(tmp_path):
    db_path = tmp_path / "e86_cieu.db"
    envelope = _valid_envelope(session_id="e86-deny", bypass_attempt=True)
    runtime_result = validate_ceo_runtime_envelope(envelope)
    assert runtime_result.decision == CEOCognitiveOSRuntimeDecisionValue.DENY

    write_ceo_cognitive_os_cieu_log_record(envelope, runtime_result, cieu_db=str(db_path))

    record = _query_single(db_path, "e86-deny")
    assert record.decision == "deny"
    result_payload = json.loads(record.result_json)
    assert result_payload["runtime_decision"] == "DENY"
    assert "block_execution" in result_payload["runtime_route"]


def test_escalate_runtime_decision_writes_owner_decision_record(tmp_path):
    db_path = tmp_path / "e86_cieu.db"
    packet = _valid_pre_action_packet(action_class="L4_external_feedback_execution")
    packet["approval_required"] = True
    packet["owner_approval_state"] = "pending_owner_decision"
    envelope = _valid_envelope(
        session_id="e86-escalate",
        pre_action_packet=packet,
        action_type="L4 external feedback execution",
        externality_level="external_feedback",
        owner_approval_status="pending_owner_decision",
    )
    runtime_result = validate_ceo_runtime_envelope(envelope)
    assert runtime_result.decision == CEOCognitiveOSRuntimeDecisionValue.ESCALATE

    write_ceo_cognitive_os_cieu_log_record(envelope, runtime_result, cieu_db=str(db_path))

    record = _query_single(db_path, "e86-escalate")
    assert record.decision == "escalate"
    result_payload = json.loads(record.result_json)
    assert result_payload["runtime_decision"] == "ESCALATE"
    assert "owner_decision" in result_payload["runtime_route"]


def test_post_action_residual_validation_result_can_be_written(tmp_path):
    db_path = tmp_path / "e86_cieu.db"
    envelope = _valid_envelope(
        session_id="e86-post",
        action_phase="completed",
        post_action_residual=_valid_post_action_residual(),
    )

    combined = validate_and_write_ceo_runtime_envelope(envelope, cieu_db=str(db_path))

    assert combined["formal_CIEU_log_written"] is True
    record = _query_single(db_path, "e86-post")
    result_payload = json.loads(record.result_json)
    assert result_payload["runtime_decision"] == "ALLOW"
    assert result_payload["post_action_residual_validation"]["decision"] == "ALLOW"
