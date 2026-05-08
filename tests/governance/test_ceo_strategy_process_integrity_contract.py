from __future__ import annotations

import json

from ystar.governance.ceo_strategy_process_integrity_contract import (
    CEO_STRATEGY_PROCESS_INTEGRITY_CIEU_EVENT_TYPE,
    CEOStrategyProcessIntegrityDecisionValue,
    REQUIRED_STRATEGY_PHASES,
    validate_and_write_ceo_strategy_process_integrity,
    validate_ceo_strategy_process_integrity,
)
from ystar.governance.cieu_store import CIEUStore


def _valid_strategy(**overrides) -> dict:
    proof = {
        "process_mode": "full_strategy_process_with_anchor_audit",
        "completed_phases": list(REQUIRED_STRATEGY_PHASES),
        "recent_memory_only": False,
        "recent_chat_summary_only": False,
        "opportunity_universe_scan": [
            {"domain_id": f"domain_{idx}", "status": "evaluated"} for idx in range(1, 9)
        ],
        "counterfactual_comparison": [
            {"route_id": f"route_{idx}", "why_not_selected": "lower fit or weaker evidence"}
            for idx in range(1, 6)
        ],
        "customer_segment_and_buyer_map": [
            {"segment_id": "founder_operator", "buyer": "founder", "budget_owner": "founder"},
            {"segment_id": "engineering_lead", "buyer": "engineering lead", "budget_owner": "vp_eng"},
            {"segment_id": "ops_owner", "buyer": "operator", "budget_owner": "owner"},
        ],
        "business_model_options": [
            {"model_id": "service_sprint"},
            {"model_id": "productized_service"},
            {"model_id": "software_after_pull"},
        ],
        "anchor_dependence_audit": {
            "prior_anchors": ["CPA review bottleneck", "AI Agent Control Room"],
            "blank_slate_generation_before_anchor_review": True,
            "anchor_penalty_applied": True,
            "selected_route_supported_without_anchor": True,
        },
        "validation_experiment_design": {
            "owner_decision_required": True,
            "no_send_default": True,
        },
    }
    strategy = {
        "strategy_run_id": "e106_strategy_integrity",
        "session_id": "e106_strategy_integrity",
        "strategy_process_integrity_proof": proof,
        "selected_strategy": {
            "selected_route_id": "agentic_ai_runtime_governance_rescue",
            "current_best_first_cash_path": "AI Agent Control Room Rescue",
        },
        "next_L4_feedback_owner_decision_packet": {
            "owner_decision_required": True,
            "owner_approval_state": "pending_owner_decision",
            "no_send_default": True,
        },
        "overclaim_boundary": {
            "customer_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "paid_signal_claim": False,
            "pricing_validation_claim": False,
            "L4_feedback_executed": False,
            "L5_revenue_loop_complete": False,
            "production_deployment_claim": False,
            "K9Audit_integration_claim": False,
            "live_provider_execution_claim": False,
        },
        "execute_L4_now": False,
        "external_action_executed": False,
        "provider_action_executed": False,
    }
    strategy.update(overrides)
    return strategy


def test_valid_strategy_process_integrity_allows():
    result = validate_ceo_strategy_process_integrity(_valid_strategy())

    assert result.decision == CEOStrategyProcessIntegrityDecisionValue.ALLOW


def test_missing_strategy_phase_requires_revision_with_correct_path():
    strategy = _valid_strategy()
    strategy["strategy_process_integrity_proof"]["completed_phases"].remove("competitor_saturation_by_cluster")

    result = validate_ceo_strategy_process_integrity(strategy)

    assert result.decision == CEOStrategyProcessIntegrityDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "completed_phases"
    assert "competitor_saturation_by_cluster" in " ".join(result.correct_path)


def test_recent_memory_only_requires_revision():
    strategy = _valid_strategy()
    strategy["strategy_process_integrity_proof"]["recent_memory_only"] = True

    result = validate_ceo_strategy_process_integrity(strategy)

    assert result.decision == CEOStrategyProcessIntegrityDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "recent_memory_boundary"


def test_missing_anchor_audit_requires_revision():
    strategy = _valid_strategy()
    strategy["strategy_process_integrity_proof"].pop("anchor_dependence_audit")

    result = validate_ceo_strategy_process_integrity(strategy)

    assert result.decision == CEOStrategyProcessIntegrityDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "anchor_dependence_audit"


def test_anchor_route_without_independent_support_requires_revision():
    strategy = _valid_strategy()
    strategy["strategy_process_integrity_proof"]["anchor_dependence_audit"][
        "selected_route_supported_without_anchor"
    ] = False

    result = validate_ceo_strategy_process_integrity(strategy)

    assert result.decision == CEOStrategyProcessIntegrityDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "anchor_dependence_audit"


def test_false_revenue_claim_denies():
    strategy = _valid_strategy()
    strategy["overclaim_boundary"]["revenue_claim"] = True

    result = validate_ceo_strategy_process_integrity(strategy)

    assert result.decision == CEOStrategyProcessIntegrityDecisionValue.DENY
    assert result.failed_section == "overclaim_boundary"


def test_owner_bound_l4_execution_escalates():
    result = validate_ceo_strategy_process_integrity(_valid_strategy(execute_L4_now=True))

    assert result.decision == CEOStrategyProcessIntegrityDecisionValue.ESCALATE
    assert result.requires_owner_decision is True


def test_strategy_process_integrity_writes_formal_cieustore_record(tmp_path):
    db_path = tmp_path / "e106_strategy_process.db"

    result = validate_and_write_ceo_strategy_process_integrity(
        _valid_strategy(),
        cieu_db=str(db_path),
        seal_session=True,
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["verify_result"]["valid"] is True
    records = CIEUStore(str(db_path)).query(
        session_id="e106_strategy_integrity",
        event_type=CEO_STRATEGY_PROCESS_INTEGRITY_CIEU_EVENT_TYPE,
        limit=5,
    )
    assert len(records) == 1
    payload = json.loads(records[0].result_json)
    assert payload["decision"] == "ALLOW"
    assert payload["strategy_process_integrity_required"] is True
