from __future__ import annotations

import json
from pathlib import Path

from ystar.governance.ceo_strategic_intelligence_benchmark import (
    CEO_STRATEGIC_BENCHMARK_CIEU_EVENT_TYPE,
    CEOStrategicBenchmarkDecisionValue,
    validate_and_write_ceo_strategic_intelligence_strategy,
    validate_ceo_strategic_intelligence_strategy,
)
from ystar.governance.cieu_store import CIEUStore


def _evidence(idx: int) -> dict:
    return {
        "evidence_id": f"public_read_{idx}",
        "source_title": f"Public source {idx}",
        "source_url": f"https://example.org/source-{idx}",
        "category": "cash pain",
        "claim_summary": "Public read-only evidence supports buyer pain.",
        "evidence_type": "public_read_only",
    }


def _brain_stage(idx: int) -> dict:
    return {
        "dimension_id": f"D{idx}_strategy_dimension",
        "brain_stage_id": f"brain_stage_{idx}",
        "evidence_refs": [f"brain://node-{idx}: node {idx}"],
        "output_summary": f"brain-grounded strategic output {idx}",
        "brain_activation_count": 1,
        "runtime_governance_required": True,
        "CIEU_recording_required": True,
    }


def _route(idx: int) -> dict:
    return {
        "route_id": f"route_{idx}",
        "name": f"Route {idx}",
        "description": "Commercial route candidate.",
        "route_type": "cash_service",
    }


def _score(idx: int) -> dict:
    return {
        "route_id": f"route_{idx}",
        "speed_to_first_cash": 4,
        "buyer_pain_intensity": 4,
        "proof_needed": 3,
        "implementation_readiness": 4,
        "sales_friction": 3,
        "differentiation": 4,
        "trust_compliance_value": 5,
        "owner_burden": 2,
        "external_validation_next_step": "owner-gated L4 feedback packet, no-send default",
        "kill_criteria": "no pain signal after owner-approved feedback",
    }


def _valid_brain_grounded_strategy(**overrides) -> dict:
    strategy = {
        "strategy_run_id": "e100_brain_locked_strategy",
        "session_id": "e100-session",
        "generation_mode": "six_d_brain_grounded_full_strategy_dossier",
        "brain_provenance": {
            "brain_db": "/tmp/aiden_brain_copy.db",
            "total_activations": 12,
            "unique_nodes": 6,
        },
        "six_d_brain_review": [_brain_stage(idx) for idx in range(1, 7)],
        "internal_capability_map": {
            "bridge-labs": "CEO/company behavior center and brain runtime",
            "Y-star-gov": "governance reflex center and CIEUStore writer",
            "gov-mcp": "dry-run provider/tool boundary",
            "K9Audit": "separate stronger evidence ledger, not integrated",
        },
        "external_market_evidence_map": {
            "freshness_status": "public_read_current_as_of_2026-05-08",
            "evidence_items": [_evidence(idx) for idx in range(1, 9)],
        },
        "route_candidates": [_route(idx) for idx in range(1, 6)],
        "route_scoring": [_score(idx) for idx in range(1, 6)],
        "selected_strategy": {
            "current_best_first_cash_path": "brain-grounded first-cash route",
            "second_best_path": "second route",
            "why_this_path_now": "chosen after 6D brain-grounded review",
            "why_not_others": "others have weaker cash urgency",
            "what_evidence_could_falsify_it": "owner-approved feedback rejects the pain statement",
            "next_48h_action": "prepare no-send demo",
            "next_7d_action": "prepare owner-approved L4 feedback packet",
            "next_owner_decision_needed": "approve or reject no-send L4 feedback packet",
        },
        "do_not_pursue_list": ["mass outreach", "live provider execution", "payment/revenue loop"],
        "next_L4_feedback_owner_decision_packet": {
            "target_profile": "buyer profile",
            "owner_decision_required": True,
            "owner_approval_state": "pending_owner_decision",
            "no_send_default": True,
            "external_action_executed": False,
            "provider_action_executed": False,
            "ai_transparency": True,
            "opt_out_language": "If this is not relevant, no reply is needed.",
        },
        "CIEU_predictions": [
            {
                "X_t": "prior strategy lacked permanent brain lock",
                "U_t": "require 6D brain provenance before strategy acceptance",
                "Y_star_t": "strategy is accepted only after brain-grounded review",
                "expected_Y_t_plus_1": "future CEO strategy cannot bypass brain runtime",
                "predicted_R_t_plus_1": "external proof remains pending",
                "residual_severity": "medium",
                "falsification_condition": "a strategy without brain provenance is allowed",
            }
        ],
        "post_strategy_residual_plan": {
            "evaluate_strategy_quality_by": "future owner-approved feedback response content",
            "pivot_trigger": "no recognized buyer pain or urgency",
        },
        "benchmark_result": {
            "strategic_intelligence_score": 4.8,
            "pass": True,
            "failed_dimensions": [],
            "required_revisions": [],
            "benchmark_decision": "ALLOW",
        },
        "truth_constraints": {
            "brain_grounded": True,
            "private_chain_of_thought_stored": False,
            "no_customer_validation_claim": True,
            "no_revenue_payment_pricing_loop_claim": True,
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
        },
        "execute_L4_now": False,
    }
    strategy.update(overrides)
    return strategy


def test_brain_grounded_strategy_allows():
    result = validate_ceo_strategic_intelligence_strategy(_valid_brain_grounded_strategy())

    assert result.decision == CEOStrategicBenchmarkDecisionValue.ALLOW
    assert result.to_dict()["passed"] is True


def test_strategy_without_brain_provenance_requires_revision():
    strategy = _valid_brain_grounded_strategy()
    strategy.pop("brain_provenance")

    result = validate_ceo_strategic_intelligence_strategy(strategy)

    assert result.decision == CEOStrategicBenchmarkDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "strategy_schema"
    assert "brain_provenance" in result.correct_path[-1] or "brain_provenance" in str(result.to_dict())


def test_strategy_with_static_generation_mode_requires_revision():
    strategy = _valid_brain_grounded_strategy(generation_mode="static_template")

    result = validate_ceo_strategic_intelligence_strategy(strategy)

    assert result.decision == CEOStrategicBenchmarkDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "generation_mode"
    assert "brain runtime" in " ".join(result.correct_path).lower()


def test_strategy_without_six_d_review_requires_revision():
    strategy = _valid_brain_grounded_strategy(six_d_brain_review=[])

    result = validate_ceo_strategic_intelligence_strategy(strategy)

    assert result.decision == CEOStrategicBenchmarkDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "six_d_brain_review"


def test_strategy_with_weak_brain_activation_requires_revision():
    strategy = _valid_brain_grounded_strategy(
        brain_provenance={"brain_db": "/tmp/aiden.db", "total_activations": 2, "unique_nodes": 1}
    )

    result = validate_ceo_strategic_intelligence_strategy(strategy)

    assert result.decision == CEOStrategicBenchmarkDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "brain_provenance"


def test_brain_lock_metadata_is_written_to_cieustore(tmp_path):
    db_path = tmp_path / "e100_strategy.db"

    result = validate_and_write_ceo_strategic_intelligence_strategy(
        _valid_brain_grounded_strategy(),
        cieu_db=str(db_path),
        seal_session=True,
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    records = CIEUStore(str(db_path)).query(
        session_id="e100-session",
        event_type=CEO_STRATEGIC_BENCHMARK_CIEU_EVENT_TYPE,
        limit=5,
    )
    assert len(records) == 1
    params = json.loads(records[0].params_json)
    payload = json.loads(records[0].result_json)
    assert params["brain_unique_nodes"] == 6
    assert params["six_d_brain_review_count"] == 6
    assert payload["brain_required_for_strategy"] is True
