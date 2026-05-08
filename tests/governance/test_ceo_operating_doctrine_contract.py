from __future__ import annotations

from ystar.governance.ceo_operating_doctrine_contract import (
    required_doctrines_for_action_context,
    validate_and_write_ceo_doctrine_invocation_proof,
    validate_ceo_doctrine_invocation_plan,
    validate_ceo_doctrine_invocation_proof,
)


def _context(**overrides):
    data = {
        "action_id": "e91_doctrine_test_action",
        "actor": "bridge_labs_ceo",
        "action_type": "market_strategy",
        "mission_type": "market_strategy",
        "route_type": "external_feedback_candidate",
        "L_level": "L5-B",
        "externality_level": "internal_no_send",
        "repo_scope": ["bridge-labs", "Y-star-gov", "gov-mcp"],
        "provider_tool_boundary": True,
        "market_strategy_required": True,
        "external_observation_required": True,
        "owner_decision_required": False,
        "revenue_or_payment_related": False,
        "K9Audit_related": False,
        "generation_mode": "runtime_generated_structured_output",
        "test_mode": False,
        "evidence_need": "public_read_and_repo_history",
    }
    data.update(overrides)
    return data


def _invocation(doctrine_id: str, **overrides):
    data = {
        "doctrine_id": doctrine_id,
        "canonical_owner": "bridge-labs",
        "source_paths": [f"bridge-labs:doctrine/{doctrine_id}.json"],
        "runtime_status": "runtime_active",
        "invocation_status": "completed",
        "output_summary": f"{doctrine_id} was invoked with structured outputs",
        "evidence_refs": [f"operations/external_validation/{doctrine_id}.json"],
        "gaps": [],
        "CIEU_recording_status": "candidate_for_CIEUStore_write",
    }
    data.update(overrides)
    return data


def _valid_plan(**context_overrides):
    context = _context(**context_overrides)
    required = required_doctrines_for_action_context(context)
    invocations = [_invocation(doctrine_id) for doctrine_id in required]
    for item in invocations:
        if item["doctrine_id"] == "external_observation_public_read_model":
            item["runtime_status"] = "callable_but_not_live"
            item["invocation_status"] = "historical_public_read_wrapper_invoked"
        if item["doctrine_id"] == "gov_mcp_dry_run_preflight":
            item.update(
                {
                    "invocation_status": "dry_run_invoked",
                    "provider_action_executed": False,
                    "external_side_effect": False,
                    "no_send_invariant": True,
                }
            )
        if item["doctrine_id"] == "owner_decision_packet":
            item["invocation_status"] = "owner_packet_prepared"
    return {
        "artifact_id": "ceo_doctrine_invocation_plan",
        "registry_id": "ceo_operating_doctrine_registry_v1",
        "doctrine_invocation_plan_id": "plan_e91_test",
        "action_context": context,
        "required_doctrines": required,
        "planned_invocations": invocations,
        "overclaim_boundary": {
            "customer_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "K9Audit_integration_claim": False,
        },
    }


def _proof_from_plan(plan):
    proof = dict(plan)
    proof["artifact_id"] = "ceo_doctrine_invocation_proof"
    proof["doctrine_invocation_proof_id"] = "proof_e91_test"
    proof["doctrine_invocations"] = list(plan["planned_invocations"])
    proof.pop("planned_invocations", None)
    return proof


def test_valid_plan_allows():
    decision = validate_ceo_doctrine_invocation_plan(_valid_plan())

    assert decision.decision.value == "ALLOW"


def test_missing_mandatory_doctrine_requires_revision():
    plan = _valid_plan()
    plan["planned_invocations"] = [
        item for item in plan["planned_invocations"] if item["doctrine_id"] != "counterfactual_comparison"
    ]

    decision = validate_ceo_doctrine_invocation_plan(plan)

    assert decision.decision.value == "REQUIRE_REVISION"
    assert decision.failed_doctrine == "counterfactual_comparison"


def test_stale_deprecated_doctrine_cannot_satisfy_mandatory_requirement():
    plan = _valid_plan()
    for item in plan["planned_invocations"]:
        if item["doctrine_id"] == "commercial_sharpness_gate":
            item["runtime_status"] = "stale_or_deprecated"

    decision = validate_ceo_doctrine_invocation_plan(plan)

    assert decision.decision.value == "REQUIRE_REVISION"
    assert decision.failed_doctrine == "commercial_sharpness_gate"


def test_missing_external_observation_for_market_strategy_requires_revision():
    plan = _valid_plan()
    for item in plan["planned_invocations"]:
        if item["doctrine_id"] == "external_observation_public_read_model":
            item["invocation_status"] = "static_evidence_map_only"

    decision = validate_ceo_doctrine_invocation_plan(plan)

    assert decision.decision.value == "REQUIRE_REVISION"
    assert decision.failed_doctrine == "external_observation_public_read_model"


def test_static_template_non_test_market_strategy_requires_revision():
    plan = _valid_plan(generation_mode="static_template", test_mode=False)

    decision = validate_ceo_doctrine_invocation_plan(plan)

    assert decision.decision.value == "REQUIRE_REVISION"
    assert decision.failed_doctrine == "generation_mode"


def test_false_revenue_customer_payment_or_k9_claim_denies():
    plan = _valid_plan()
    plan["overclaim_boundary"]["revenue_claim"] = True

    decision = validate_ceo_doctrine_invocation_plan(plan)

    assert decision.decision.value == "DENY"


def test_owner_bound_l4_execution_escalates():
    plan = _valid_plan(
        L_level="L4",
        owner_decision_required=True,
        execution_requested=True,
        owner_approval_state="pending_owner_decision",
    )

    decision = validate_ceo_doctrine_invocation_plan(plan)

    assert decision.decision.value == "ESCALATE"
    assert decision.requires_owner_decision is True


def test_valid_proof_writes_cieustore_record(tmp_path):
    proof = _proof_from_plan(_valid_plan())

    result = validate_and_write_ceo_doctrine_invocation_proof(
        proof,
        cieu_db=str(tmp_path / "doctrine.db"),
        seal_session=True,
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["verify_result"]["valid"] is True


def test_bypass_attempt_denies():
    plan = _valid_plan()
    plan["bypass_attempt"] = True

    decision = validate_ceo_doctrine_invocation_proof(_proof_from_plan(plan))

    assert decision.decision.value == "DENY"
