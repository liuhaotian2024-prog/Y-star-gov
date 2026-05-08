from __future__ import annotations

from ystar.governance.ceo_adaptive_governance_contract import (
    CEOAdaptiveGovernanceDecisionValue,
    validate_ceo_adaptive_governance_result,
)


def _valid_result(**overrides):
    obligations = [
        {"obligation_id": "six_d_brain_review"},
        {"obligation_id": "pricing_hypothesis_source_audit"},
        {"obligation_id": "right_to_win_analysis"},
        {"obligation_id": "strongest_validation_question"},
        {"obligation_id": "competitor_differentiation_map"},
        {"obligation_id": "external_observation_or_staleness_boundary"},
        {"obligation_id": "post_action_residual"},
    ]
    result = {
        "discovery_id": "adaptive_governance::strategy",
        "action_context": {
            "action_id": "strategy",
            "action_type": "market_strategy",
            "market_strategy_required": True,
            "external_observation_required": True,
        },
        "discovered_obligations": obligations,
        "required_obligations": obligations,
        "obligation_invocation_proof": {
            "satisfied_obligations": [item["obligation_id"] for item in obligations],
            "missing_obligations": [],
        },
        "correct_path_navigator": {"steps": []},
        "bypass_prevention": {"runtime_gate_required": True},
        "truth_constraints": {
            "customer_validation_claim": False,
            "pricing_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
        },
    }
    result.update(overrides)
    return result


def test_valid_adaptive_governance_result_allows():
    decision = validate_ceo_adaptive_governance_result(_valid_result())

    assert decision.decision == CEOAdaptiveGovernanceDecisionValue.ALLOW


def test_missing_required_obligation_requires_revision_with_navigation():
    result = _valid_result()
    result["obligation_invocation_proof"]["satisfied_obligations"].remove("six_d_brain_review")

    decision = validate_ceo_adaptive_governance_result(result)

    assert decision.decision == CEOAdaptiveGovernanceDecisionValue.REQUIRE_REVISION
    assert "6D brain review" in " ".join(decision.correct_path)
    assert decision.navigation["next_allowed_action"] == "repair_packet_only"


def test_false_customer_validation_claim_denies():
    result = _valid_result(truth_constraints={"customer_validation_claim": True})

    decision = validate_ceo_adaptive_governance_result(result)

    assert decision.decision == CEOAdaptiveGovernanceDecisionValue.DENY


def test_owner_bound_external_action_escalates():
    result = _valid_result(
        action_context={
            "action_id": "strategy",
            "action_type": "market_strategy",
            "market_strategy_required": True,
            "owner_bound_external_action_requested": True,
        }
    )

    decision = validate_ceo_adaptive_governance_result(result)

    assert decision.decision == CEOAdaptiveGovernanceDecisionValue.ESCALATE
    assert decision.requires_owner_decision is True
