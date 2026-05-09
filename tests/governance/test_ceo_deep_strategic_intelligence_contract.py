from __future__ import annotations

from ystar.governance.ceo_deep_strategic_intelligence_contract import (
    CEODeepStrategicDecisionValue,
    validate_and_write_ceo_deep_strategic_intelligence_dossier,
    validate_ceo_deep_strategic_intelligence_dossier,
)


def _dimension(dimension_id: str, idx: int) -> dict:
    return {
        "dimension_id": dimension_id,
        "conclusion": f"{dimension_id} conclusion",
        "evidence_refs": [
            f"public://dimension-specific-{idx}",
            f"public://shared-cluster-{idx % 4}",
            f"public://supporting-{idx + 20}",
        ],
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
        "deep_reasoning_dimensions": [_dimension(item, idx) for idx, item in enumerate(dimensions)],
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
                {
                    "name": f"Competitor {idx}",
                    "source_url": f"https://vendor{idx}.com/research/current-signal",
                    "source_date": "2026-05-09",
                    "observed_at": "2026-05-09",
                    "public_signal_date": "2026-05-09",
                    "public_signal_date_basis": "source_dated_public_evidence",
                    "public_signal_evidence_refs": [f"public://competitor-signal-{idx}"],
                }
                for idx in range(1, 6)
            ]
        },
        "right_to_win_and_right_to_lose": {
            "right_to_win_assets": [f"asset_{idx}" for idx in range(1, 6)],
            "market_visible_right_to_win_assets": [
                {
                    "asset": f"market_visible_asset_{idx}",
                    "buyer_visible_proof": f"buyer can inspect proof artifact {idx}",
                    "why_buyer_cares": "reduces trust, audit, or implementation risk",
                    "evidence_refs": [f"public://dimension-specific-{idx}"],
                }
                for idx in range(1, 5)
            ],
            "right_to_lose_risks": [f"risk_{idx}" for idx in range(1, 4)],
        },
        "product_shape": {
            "product_name": "AI Agent Governance Evidence & Control Pack",
            "buyer_visible_deliverables": [f"deliverable_{idx}" for idx in range(1, 6)],
        },
        "pricing_and_value_capture": {"price_hypothesis_usd": "500-2000", "validation_status": "hypothesis_only"},
        "distribution_and_first_10_buyers": {"channels": ["founder communities"], "first_10_buyer_profiles": [f"profile_{idx}" for idx in range(1, 11)]},
        "causal_zero_loop_model": {
            "R_t_plus_1": 0.0,
            "residual_closed_by": "assumption registry and next experiment",
            "residual_truth_status": {
                "closure_scope": "planning_residual_closed_real_market_residual_pending",
                "real_market_residual_closed": False,
            },
        },
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
        "extrapolation_gate": {
            "class_of_issue": {
                "issue_class_id": "strategy_point_fix_without_generalization",
                "description": "single audit findings can be patched without preventing the class of failure",
                "generalization_boundary": "applies to strategic reasoning, evidence, competitor, right-to-win, and CZL truth gates",
            },
            "extrapolation_to_other_cases": [
                {
                    "case_id": "repeated_evidence_bundle",
                    "why_same_class": "schema can be satisfied while semantic diversity is absent",
                    "preventive_rule": "require dimension-specific evidence diversity",
                },
                {
                    "case_id": "homepage_current_signal",
                    "why_same_class": "a field can be present without proving source-dated reality",
                    "preventive_rule": "require source-dated current-signal basis",
                },
                {
                    "case_id": "internal_only_right_to_win",
                    "why_same_class": "internal assets can masquerade as market differentiation",
                    "preventive_rule": "require buyer-visible proof",
                },
            ],
            "proposed_class_level_fix": {
                "rule": "every deep strategy must name the issue class and at least three same-class future variants",
                "affected_runtime_paths": ["E115_deep_strategy", "E116_idle_learning"],
                "correct_path_navigation": "generalize the point failure before accepting the strategy",
            },
            "evidence_refs": ["tests/governance/test_ceo_deep_strategic_intelligence_contract.py"],
            "point_fix_only": False,
        },
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


def test_reused_identical_dimension_evidence_requires_revision():
    dossier = _valid_dossier()
    for item in dossier["deep_reasoning_dimensions"]:
        item["evidence_refs"] = ["public://same-1", "public://same-2"]

    decision = validate_ceo_deep_strategic_intelligence_dossier(dossier)

    assert decision.decision == CEODeepStrategicDecisionValue.REQUIRE_REVISION
    assert decision.failed_section == "deep_reasoning_dimensions"


def test_competitor_without_current_signal_requires_revision():
    dossier = _valid_dossier()
    competitor = dossier["competitive_landscape"]["competitors_and_substitutes"][0]
    competitor["source_url"] = "https://vendor1.com/"
    competitor.pop("public_signal_date")
    competitor.pop("observed_at")

    decision = validate_ceo_deep_strategic_intelligence_dossier(dossier)

    assert decision.decision == CEODeepStrategicDecisionValue.REQUIRE_REVISION
    assert decision.failed_section == "competitive_landscape"


def test_competitor_homepage_with_self_assigned_current_date_requires_revision():
    dossier = _valid_dossier()
    competitor = dossier["competitive_landscape"]["competitors_and_substitutes"][0]
    competitor["source_url"] = "https://vendor1.com/"
    competitor["public_signal_date"] = "2026-05-09"
    competitor["public_signal_date_basis"] = "public competitor presence observed during strategy run"
    competitor["public_signal_evidence_refs"] = []
    competitor.pop("source_date")

    decision = validate_ceo_deep_strategic_intelligence_dossier(dossier)

    assert decision.decision == CEODeepStrategicDecisionValue.REQUIRE_REVISION
    assert decision.failed_section == "competitive_landscape"


def test_internal_only_right_to_win_requires_revision():
    dossier = _valid_dossier()
    dossier["right_to_win_and_right_to_lose"].pop("market_visible_right_to_win_assets")

    decision = validate_ceo_deep_strategic_intelligence_dossier(dossier)

    assert decision.decision == CEODeepStrategicDecisionValue.REQUIRE_REVISION
    assert decision.failed_section == "right_to_win_and_right_to_lose"


def test_false_real_market_residual_closure_denies():
    dossier = _valid_dossier()
    dossier["causal_zero_loop_model"]["residual_truth_status"]["real_market_residual_closed"] = True

    decision = validate_ceo_deep_strategic_intelligence_dossier(dossier)

    assert decision.decision == CEODeepStrategicDecisionValue.DENY
    assert decision.failed_section == "causal_zero_loop_model"


def test_missing_extrapolation_gate_requires_revision():
    dossier = _valid_dossier()
    dossier.pop("extrapolation_gate")

    decision = validate_ceo_deep_strategic_intelligence_dossier(dossier)

    assert decision.decision == CEODeepStrategicDecisionValue.REQUIRE_REVISION
    assert decision.failed_section == "dossier_schema"


def test_point_fix_only_extrapolation_gate_requires_revision():
    dossier = _valid_dossier()
    dossier["extrapolation_gate"]["point_fix_only"] = True

    decision = validate_ceo_deep_strategic_intelligence_dossier(dossier)

    assert decision.decision == CEODeepStrategicDecisionValue.REQUIRE_REVISION
    assert decision.failed_section == "extrapolation_gate"


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
