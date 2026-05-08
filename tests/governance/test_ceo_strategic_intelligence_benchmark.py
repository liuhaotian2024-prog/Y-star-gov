from __future__ import annotations

import json

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
        "category": "AI agent governance risk",
        "claim_summary": "Public read-only evidence supports agent governance buyer pain.",
        "evidence_type": "public_read_only",
    }


def _route(idx: int) -> dict:
    return {
        "route_id": f"route_{idx}",
        "name": f"Route {idx}",
        "description": "Commercial route candidate for governed agent operations.",
        "route_type": "internal_runtime" if idx == 1 else "external_feedback_candidate",
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


def _valid_strategy(**overrides) -> dict:
    strategy = {
        "strategy_run_id": "e90_strategy_run",
        "session_id": "e90-session",
        "internal_capability_map": {
            "bridge-labs": "CEO/company behavior center and intelligence compiler",
            "Y-star-gov": "governance reflex center and CIEUStore writer",
            "gov-mcp": "dry-run provider/tool boundary",
            "K9Audit": "separate stronger evidence ledger, not integrated",
        },
        "external_market_evidence_map": {
            "freshness_status": "public_read_current_as_of_2026-05-07",
            "evidence_items": [_evidence(idx) for idx in range(1, 9)],
        },
        "route_candidates": [_route(idx) for idx in range(1, 6)],
        "route_scoring": [_score(idx) for idx in range(1, 6)],
        "selected_strategy": {
            "current_best_first_cash_path": "governed business operations blueprint plus CIEU audit module wedge",
            "second_best_path": "CEO runtime governance product",
            "why_this_path_now": "fastest credible no-send path using existing runtime foundation",
            "why_not_others": "other routes need broader productization or owner activation",
            "what_evidence_could_falsify_it": "operators do not recognize audit/control pain in owner-approved feedback",
            "next_48h_action": "prepare owner-gated L4 feedback packet",
            "next_7d_action": "collect owner-approved feedback if authorized",
            "next_owner_decision_needed": "approve or reject scoped no-send L4 feedback pilot",
        },
        "do_not_pursue_list": ["mass outreach", "live provider execution", "payment/revenue loop"],
        "next_L4_feedback_owner_decision_packet": {
            "target_profile": "founder/operator of a small AI-agent team",
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
                "X_t": "E89 structured intelligence exists",
                "U_t": "run strategy benchmark and prepare no-send L4 packet",
                "Y_star_t": "choose first-cash path based on internal and external evidence",
                "expected_Y_t_plus_1": "owner can decide whether to run L4 feedback later",
                "predicted_R_t_plus_1": "external proof still pending",
                "residual_severity": "medium",
                "falsification_condition": "owner-approved feedback rejects the pain statement",
            }
        ],
        "post_strategy_residual_plan": {
            "evaluate_strategy_quality_by": "future owner-approved feedback response content",
            "pivot_trigger": "no recognized buyer pain or urgency",
        },
        "benchmark_result": {
            "strategic_intelligence_score": 4.3,
            "pass": True,
            "failed_dimensions": [],
            "required_revisions": [],
            "benchmark_decision": "ALLOW",
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


def test_valid_strategy_allows():
    result = validate_ceo_strategic_intelligence_strategy(_valid_strategy())

    assert result.decision == CEOStrategicBenchmarkDecisionValue.ALLOW
    assert result.to_dict()["passed"] is True


def test_shallow_or_missing_evidence_requires_revision():
    strategy = _valid_strategy()
    strategy["external_market_evidence_map"]["evidence_items"] = [_evidence(1)]

    result = validate_ceo_strategic_intelligence_strategy(strategy)

    assert result.decision == CEOStrategicBenchmarkDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "external_market_evidence_map"
    assert result.correct_path


def test_false_revenue_or_customer_claim_denies():
    strategy = _valid_strategy()
    strategy["overclaim_boundary"]["customer_validation_claim"] = True

    result = validate_ceo_strategic_intelligence_strategy(strategy)

    assert result.decision == CEOStrategicBenchmarkDecisionValue.DENY
    assert result.failed_section == "overclaim_boundary"


def test_owner_bound_l4_execution_escalates_if_execution_requested():
    strategy = _valid_strategy(execute_L4_now=True)

    result = validate_ceo_strategic_intelligence_strategy(strategy)

    assert result.decision == CEOStrategicBenchmarkDecisionValue.ESCALATE
    assert result.requires_owner_decision is True
    assert "owner decision packet" in " ".join(result.correct_path).lower()


def test_next_l4_packet_must_be_no_send():
    strategy = _valid_strategy()
    strategy["next_L4_feedback_owner_decision_packet"]["no_send_default"] = False

    result = validate_ceo_strategic_intelligence_strategy(strategy)

    assert result.decision == CEOStrategicBenchmarkDecisionValue.DENY
    assert result.failed_section == "next_L4_feedback_owner_decision_packet"


def test_strategic_benchmark_writes_formal_cieustore_record(tmp_path):
    db_path = tmp_path / "e90_strategy.db"

    result = validate_and_write_ceo_strategic_intelligence_strategy(
        _valid_strategy(),
        cieu_db=str(db_path),
        seal_session=True,
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["verify_result"]["valid"] is True
    records = CIEUStore(str(db_path)).query(
        session_id="e90-session",
        event_type=CEO_STRATEGIC_BENCHMARK_CIEU_EVENT_TYPE,
        limit=5,
    )
    assert len(records) == 1
    payload = json.loads(records[0].result_json)
    assert payload["decision"] == "ALLOW"
    assert payload["selected_first_cash_path"]
    assert payload["formal_CIEU_log_path"] == "ystar.governance.cieu_store.CIEUStore.write_dict"
