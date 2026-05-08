from __future__ import annotations

import json

from ystar.governance.ceo_intelligence_loop_contract import (
    CEO_INTELLIGENCE_LOOP_CIEU_EVENT_TYPE,
    CEOIntelligenceLoopDecisionValue,
    REQUIRED_INTELLIGENCE_STAGE_IDS,
    build_ceo_intelligence_operation_registry,
    validate_and_write_ceo_intelligence_loop_packet,
    validate_ceo_intelligence_loop_packet,
)
from ystar.governance.cieu_store import CIEUStore


def _stage(stage_id: str) -> dict:
    return {
        "stage_id": stage_id,
        "input_summary": f"Input evidence for {stage_id}",
        "evidence_refs": [
            "bridge-labs:operations/baseline/e87r_full_repo_baseline/baseline_summary.json",
            "Y-star-gov:ystar/governance/ceo_intelligence_loop_contract.py",
        ],
        "output_summary": f"Structured governed cognition output for {stage_id}",
        "confidence_boundary": "bounded to repository evidence and E87R baseline",
        "missing_evidence": [],
        "runtime_governance_required": True,
        "CIEU_recording_required": True,
    }


def _candidate(candidate_id: str, route_type: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "description": f"{candidate_id} closes a runtime CEO intelligence loop segment",
        "expected_value": "high internal runtime learning value",
        "speed_to_cash": "indirect, improves shortest credible cash-path selection",
        "implementation_cost": "bounded deterministic code/test/report work",
        "owner_burden": "low unless owner approval boundary is crossed",
        "execution_risk": "no external execution in test",
        "governance_risk": "governed through Y-star-gov",
        "evidence_strength": "repository-backed",
        "why_it_might_fail": "could remain artifact-only if not routed into E88 session",
        "required_next_evidence": "CIEUStore write and runtime session result",
        "route_type": route_type,
    }


def _valid_packet(**overrides) -> dict:
    packet = {
        "intelligence_loop_id": "e89_intelligence_loop",
        "session_id": "e89-session",
        "owner_intent": "turn CEO structured thinking into governed runtime behavior",
        "current_problem": "L5-B is partial until intelligence loop is compiled and recorded",
        "bypass_attempt": False,
        "stages": [_stage(stage_id) for stage_id in REQUIRED_INTELLIGENCE_STAGE_IDS],
        "candidate_actions": [
            _candidate("candidate_internal_runtime", "internal_runtime"),
            _candidate("candidate_provider_dry_run", "provider_tool_dry_run"),
            _candidate("candidate_owner_l4", "owner_decision_required"),
        ],
        "counterfactual_comparison": [
            {"candidate_id": "candidate_internal_runtime", "score": 7, "tradeoff": "less provider-bound proof"},
            {"candidate_id": "candidate_provider_dry_run", "score": 9, "tradeoff": "proves gov-mcp dry-run metadata"},
            {"candidate_id": "candidate_owner_l4", "score": 4, "tradeoff": "requires owner approval"},
        ],
        "commercial_sharpness_gate": {
            "buyer_pain_clarity": 7,
            "urgency": 6,
            "willingness_to_pay_proxy": 5,
            "shortest_cash_path_fit": 7,
            "differentiation": 6,
            "proof_needed": "real L4 feedback remains needed later",
            "owner_execution_burden": 3,
            "risk_of_wasting_time": 4,
        },
        "speed_to_cash_evaluation": {"selected": "candidate_provider_dry_run", "reason": "improves governed path to feedback"},
        "risk_owner_burden_evaluation": {"owner_burden": "low", "risk": "no external execution"},
        "no_new_wheel_gate": {
            "reused": [
                "bridge-labs behavior center",
                "E88 runtime session",
                "Y-star-gov runtime hook",
                "E86 CIEU writer",
                "gov-mcp dry-run",
                "E87R baseline",
            ]
        },
        "adversarial_critique": "This could still be too internal unless followed by owner-approved L4 feedback.",
        "what_not_to_do": ["do not execute L4", "do not claim revenue loop complete"],
        "pre_action_CIEU_residual_prediction": {
            "X_t": "L5-B partial",
            "U_t": "compile governed intelligence packet",
            "Y_star_t": "structured CEO cognition becomes auditable behavior",
            "expected_Y_t_plus_1": "intelligence loop CIEUStore record written",
            "predicted_R_t_plus_1": "live feedback remains pending",
        },
        "selected_action": {"candidate_id": "candidate_provider_dry_run", "route_type": "provider_tool_dry_run"},
        "why_this_action": "It proves intelligence output flows into governed runtime and dry-run boundary.",
        "why_not_other_actions": "Owner L4 is premature; internal-only proof misses gov-mcp alignment.",
        "runtime_governance_plan": {
            "Y-star-gov runtime hook": "validate E88 pre-action envelope",
            "E86 CIEUStore writer": "write intelligence and runtime records",
            "gov-mcp dry-run": "only after Y-star-gov ALLOW for provider/tool boundary",
        },
        "post_action_learning_plan": "Record residual and recommend owner-approved L4 only after runtime proof.",
        "next_action_recommendation": "E90 owner-approved controlled external-action preflight or L4 packet",
        "overclaim_boundary": {
            "L4_execution_claim": False,
            "L5_revenue_loop_complete": False,
            "customer_validation_claim": False,
            "paid_signal_claim": False,
            "pricing_validation_claim": False,
            "payment_loop_complete": False,
            "production_deployment_claim": False,
            "K9Audit_integration_claim": False,
        },
        "owner_approval_state": "not_required",
        "Y_star_contract_hash_input": "sha256:e89-intelligence-loop",
    }
    packet.update(overrides)
    return packet


def test_valid_intelligence_loop_allows_and_registry_registers_thinking_operations():
    registry = build_ceo_intelligence_operation_registry()
    result = validate_ceo_intelligence_loop_packet(_valid_packet())

    assert result.decision == CEOIntelligenceLoopDecisionValue.ALLOW
    assert len(registry["operations"]) == len(REQUIRED_INTELLIGENCE_STAGE_IDS)
    assert registry["private_chain_of_thought_policy"] == "do_not_request_or_store_hidden_chain_of_thought"


def test_missing_stage_requires_revision_with_correct_path():
    packet = _valid_packet()
    packet["stages"] = packet["stages"][:-1]

    result = validate_ceo_intelligence_loop_packet(packet)

    assert result.decision == CEOIntelligenceLoopDecisionValue.REQUIRE_REVISION
    assert result.correct_path
    assert "complete missing intelligence stages" in " ".join(result.correct_path)


def test_missing_evidence_requires_revision():
    packet = _valid_packet()
    packet["stages"][0]["evidence_refs"] = []

    result = validate_ceo_intelligence_loop_packet(packet)

    assert result.decision == CEOIntelligenceLoopDecisionValue.REQUIRE_REVISION
    assert result.failed_stage == "mission_and_owner_constraint_recall"


def test_fewer_than_three_candidates_requires_revision_without_justification():
    packet = _valid_packet(candidate_actions=[_candidate("one", "internal_runtime"), _candidate("two", "provider_tool_dry_run")])

    result = validate_ceo_intelligence_loop_packet(packet)

    assert result.decision == CEOIntelligenceLoopDecisionValue.REQUIRE_REVISION
    assert result.failed_stage == "candidate_action_generation"


def test_missing_counterfactual_or_shallow_commercial_gate_requires_revision():
    packet = _valid_packet(counterfactual_comparison=[{"candidate_id": "candidate_provider_dry_run"}])
    assert validate_ceo_intelligence_loop_packet(packet).decision == CEOIntelligenceLoopDecisionValue.REQUIRE_REVISION

    shallow = _valid_packet()
    shallow["commercial_sharpness_gate"].pop("urgency")
    result = validate_ceo_intelligence_loop_packet(shallow)
    assert result.decision == CEOIntelligenceLoopDecisionValue.REQUIRE_REVISION
    assert result.failed_stage == "commercial_sharpness_gate"


def test_false_l5_revenue_customer_payment_claim_denies():
    packet = _valid_packet()
    packet["overclaim_boundary"]["customer_validation_claim"] = True

    result = validate_ceo_intelligence_loop_packet(packet)

    assert result.decision == CEOIntelligenceLoopDecisionValue.DENY
    assert result.failed_stage == "overclaim_boundary"


def test_private_chain_of_thought_is_not_stored_or_allowed():
    packet = _valid_packet(chain_of_thought="hidden reasoning should never be persisted")

    result = validate_ceo_intelligence_loop_packet(packet)

    assert result.decision == CEOIntelligenceLoopDecisionValue.DENY
    assert "private chain-of-thought" in result.reason


def test_owner_bound_external_action_escalates_with_owner_path():
    packet = _valid_packet(
        selected_action={"candidate_id": "candidate_owner_l4", "route_type": "external_feedback_candidate"},
        owner_approval_state="pending_owner_decision",
    )

    result = validate_ceo_intelligence_loop_packet(packet)

    assert result.decision == CEOIntelligenceLoopDecisionValue.ESCALATE
    assert result.requires_owner_decision is True
    assert result.correct_path


def test_intelligence_loop_writes_formal_cieustore_record(tmp_path):
    db_path = tmp_path / "e89_intelligence.db"
    packet = _valid_packet()

    combined = validate_and_write_ceo_intelligence_loop_packet(packet, cieu_db=str(db_path), seal_session=True)

    assert combined["formal_CIEU_log_written"] is True
    assert combined["CIEU_write_result"]["verify_result"]["valid"] is True
    records = CIEUStore(str(db_path)).query(
        session_id="e89-session",
        event_type=CEO_INTELLIGENCE_LOOP_CIEU_EVENT_TYPE,
        limit=5,
    )
    assert len(records) == 1
    result_payload = json.loads(records[0].result_json)
    assert result_payload["decision"] == "ALLOW"
    assert result_payload["selected_action"]["candidate_id"] == "candidate_provider_dry_run"
    assert result_payload["formal_CIEU_log_path"] == "ystar.governance.cieu_store.CIEUStore.write_dict"
