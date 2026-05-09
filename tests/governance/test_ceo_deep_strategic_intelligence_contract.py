from __future__ import annotations

from ystar.governance.ceo_deep_strategic_intelligence_contract import (
    CEODeepStrategicDecisionValue,
    validate_and_write_ceo_deep_strategic_intelligence_dossier,
    validate_ceo_deep_strategic_intelligence_dossier,
)


def _dimension(dimension_id: str) -> dict:
    return {
        "dimension_id": dimension_id,
        "conclusion": f"{dimension_id} conclusion",
        "evidence_refs": ["public://evidence-1"],
        "uncertainty": "buyer feedback pending",
    }


def _valid_dossier() -> dict:
    dimensions = [
        "strategic_question_reframe",
        "jobs_to_be_done",
        "buyer_pain_and_trigger_events",
        "budget_owner_and_procurement",
        "competitive_landscape",
        "substitute_and_status_quo",
        "founder_market_fit_and_right_to_win",
        "product_shape_and_delivery_model",
        "pricing_and_value_capture",
        "distribution_and_first_10_buyers",
        "risk_regulatory_trust",
        "causal_zero_loop_residual_model",
        "experiment_and_kill_criteria",
        "memory_and_learning_update",
    ]
    return {
        "dossier_id": "e115_test_deep_strategy",
        "generation_mode": "brain_grounded_public_evidence_capability_utilized_deep_strategy",
        "source_runtime": "E114",
        "strategic_question_reframe": {
            "question": "What is the easiest credible first-cash path?",
            "not_the_question": ["do not chase vague SaaS", "do not claim customer validation"],
        },
        "deep_reasoning_dimensions": [_dimension(item) for item in dimensions],
        "market_map": {
            "domains_analyzed": [{"domain_id": f"domain_{idx}"} for idx in range(1, 6)],
            "source_date_coverage": {"dated_count": 12, "undated_count": 0},
        },
        "selected_route_thesis": {
            "selected_route_id": "ai_security_compliance_first_cash_pack",
            "thesis": "Buyer urgency exists around agent governance evidence.",
            "evidence_refs": ["public://evidence-1", "public://evidence-2", "public://evidence-3"],
        },
        "customer_and_buyer_model": {
            "ideal_customer_profile": "small AI-enabled team with agent governance exposure",
            "budget_owner": "founder, CTO, security lead, or compliance owner",
            "trigger_events": ["agent rollout", "security questionnaire", "customer audit"],
        },
        "competitive_landscape": {
            "competitors_and_substitutes": [
                {"name": f"Competitor {idx}", "source_url": f"https://vendor{idx}.com", "observed_at": "2026-05-09"}
                for idx in range(1, 6)
            ]
        },
        "right_to_win_and_right_to_lose": {
            "right_to_win_assets": [f"asset_{idx}" for idx in range(1, 6)],
            "right_to_lose_risks": [f"risk_{idx}" for idx in range(1, 4)],
        },
        "product_shape": {
            "product_name": "AI Agent Governance Evidence & Control Pack",
            "buyer_visible_deliverables": [f"deliverable_{idx}" for idx in range(1, 6)],
        },
        "pricing_and_value_capture": {"price_hypothesis_usd": "500-2000", "validation_status": "hypothesis_only"},
        "distribution_and_first_10_buyers": {"channels": ["founder communities"], "first_10_buyer_profiles": [f"profile_{idx}" for idx in range(1, 11)]},
        "causal_zero_loop_model": {"R_t_plus_1": 0.0, "residual_closed_by": "assumption registry and next experiment"},
        "assumption_registry": [
            {"assumption_id": f"a{idx}", "test_method": "owner-approved no-send feedback", "falsification_condition": "buyer rejects pain"}
            for idx in range(1, 6)
        ],
        "experiment_design": {
            "experiment_id": "no_send_validation_packet",
            "owner_decision_required": True,
            "no_send_default": True,
            "external_action_executed": False,
            "provider_action_executed": False,
        },
        "post_action_residual_learning_plan": {"learning_update": "compare buyer feedback against predictions"},
        "CIEU_predictions": [{"X_t": "strategy", "predicted_R_t_plus_1": 0, "falsification_condition": "no buyer urgency"}],
        "no_overclaim_boundary": {
            "customer_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "live_provider_execution_claim": False,
        },
    }


def test_valid_deep_strategy_allows():
    decision = validate_ceo_deep_strategic_intelligence_dossier(_valid_dossier())

    assert decision.decision == CEODeepStrategicDecisionValue.ALLOW


def test_missing_dimension_requires_revision():
    dossier = _valid_dossier()
    dossier["deep_reasoning_dimensions"] = dossier["deep_reasoning_dimensions"][:-1]

    decision = validate_ceo_deep_strategic_intelligence_dossier(dossier)

    assert decision.decision == CEODeepStrategicDecisionValue.REQUIRE_REVISION
    assert decision.failed_section == "deep_reasoning_dimensions"


def test_placeholder_competitor_source_requires_revision():
    dossier = _valid_dossier()
    dossier["competitive_landscape"]["competitors_and_substitutes"][0]["source_url"] = "https://example.com/placeholder"

    decision = validate_ceo_deep_strategic_intelligence_dossier(dossier)

    assert decision.decision == CEODeepStrategicDecisionValue.REQUIRE_REVISION
    assert decision.failed_section == "competitive_landscape"


def test_external_action_executed_denies():
    dossier = _valid_dossier()
    dossier["experiment_design"]["external_action_executed"] = True

    decision = validate_ceo_deep_strategic_intelligence_dossier(dossier)

    assert decision.decision == CEODeepStrategicDecisionValue.DENY


def test_write_deep_strategy_cieustore_record(tmp_path):
    result = validate_and_write_ceo_deep_strategic_intelligence_dossier(
        _valid_dossier(),
        cieu_db=str(tmp_path / "deep_strategy.db"),
        session_id="test_deep_strategy",
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["event_type"] == "CEO_DEEP_STRATEGIC_INTELLIGENCE_DECISION"
