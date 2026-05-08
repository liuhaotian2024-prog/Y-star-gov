from __future__ import annotations

import json

from ystar.governance.ceo_strategy_math_model_contract import (
    CEO_STRATEGY_MATH_MODEL_CIEU_EVENT_TYPE,
    CEOStrategyMathModelDecisionValue,
    REQUIRED_PARAMETER_KEYS,
    REQUIRED_SOURCE_KEYS,
    validate_and_write_ceo_strategy_math_model,
    validate_ceo_strategy_math_model,
)
from ystar.governance.cieu_store import CIEUStore


def _source_map() -> dict:
    return {
        key: {
            "source_url": f"https://example.com/{key}",
            "source_name": key.replace("_", " "),
            "model_role": "required model family",
        }
        for key in REQUIRED_SOURCE_KEYS
    }


def _parameter_registry() -> dict:
    return {
        key: {
            "definition": f"definition for {key}",
            "source_family": "decision_analysis",
            "calibration_status": "prior_estimate_requires_validation",
            "allowed_range": [0, 1] if key.endswith("probability") or key.endswith("penalty") else [0, 10000],
        }
        for key in REQUIRED_PARAMETER_KEYS
    }


def _route(route_id: str, score: float, *, evidence_ref: str = "evidence:1") -> dict:
    return {
        "route_id": route_id,
        "expected_first_cash_value_usd": 325.0 + score,
        "market_pull_probability": 0.5,
        "willingness_to_pay_probability": 0.3,
        "distribution_access_probability": 0.4,
        "trust_access_probability": 0.4,
        "delivery_success_probability": 0.7,
        "time_to_first_signal_days": 7,
        "validation_cost_usd": 250.0,
        "competition_penalty": 0.25,
        "regulatory_penalty": 0.05,
        "uncertainty_penalty": 0.35,
        "internal_capability_feasibility": 0.85,
        "market_first_score": score,
        "evsi_usd": 420.0,
        "evidence_refs": [evidence_ref],
        "math_model_decision_basis": "expected utility adjusted by uncertainty and market structure",
    }


def _valid_strategy(**overrides) -> dict:
    strategy = {
        "strategy_run_id": "e107_strategy_math",
        "session_id": "e107_strategy_math",
        "strategy_math_model": {
            "model_id": "market_first_expected_utility_model_v1",
            "model_version": "1.0",
            "generation_mode": "runtime_generated_structured_output",
            "primary_selector": "market_first_expected_utility",
            "internal_capability_role": "feasibility_multiplier_not_primary_selector",
            "mathematical_source_map": _source_map(),
            "parameter_registry": _parameter_registry(),
            "validation_experiment_design": {
                "owner_decision_required": True,
                "no_send_default": True,
                "expected_value_of_sample_information_usd": 420.0,
            },
        },
        "mathematical_source_map": _source_map(),
        "parameter_registry": _parameter_registry(),
        "route_math_scores": [
            _route("ai_agent_control_room_rescue", 810.0),
            _route("ai_observability_readiness_sprint", 700.0),
            _route("agent_production_gap_rescue", 660.0),
            _route("cpa_review_bottleneck_rescue", 130.0),
            _route("tariff_margin_rescue", 95.0),
        ],
        "selected_strategy": {
            "selected_route_id": "ai_agent_control_room_rescue",
            "current_best_first_cash_path": "AI Agent Control Room Rescue",
        },
        "validation_experiment_design": {
            "owner_decision_required": True,
            "no_send_default": True,
            "expected_value_of_sample_information_usd": 420.0,
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
        "external_action_executed": False,
        "provider_action_executed": False,
        "execute_L4_now": False,
    }
    strategy.update(overrides)
    return strategy


def test_valid_market_first_math_model_allows():
    result = validate_ceo_strategy_math_model(_valid_strategy())

    assert result.decision == CEOStrategyMathModelDecisionValue.ALLOW


def test_missing_source_family_requires_revision_with_correct_path():
    strategy = _valid_strategy()
    strategy["mathematical_source_map"].pop("value_of_information")

    result = validate_ceo_strategy_math_model(strategy)

    assert result.decision == CEOStrategyMathModelDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "mathematical_source_map"
    assert "value_of_information" in " ".join(result.correct_path)


def test_internal_capability_primary_selector_denies():
    strategy = _valid_strategy()
    strategy["strategy_math_model"]["primary_selector"] = "internal_capability_fit"

    result = validate_ceo_strategy_math_model(strategy)

    assert result.decision == CEOStrategyMathModelDecisionValue.DENY
    assert result.failed_section == "primary_selector"


def test_arbitrary_weight_mode_requires_revision():
    strategy = _valid_strategy()
    strategy["strategy_math_model"]["generation_mode"] = "arbitrary_weights"

    result = validate_ceo_strategy_math_model(strategy)

    assert result.decision == CEOStrategyMathModelDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "generation_mode"


def test_selected_route_must_match_top_score_or_justify():
    strategy = _valid_strategy()
    strategy["selected_strategy"]["selected_route_id"] = "tariff_margin_rescue"

    result = validate_ceo_strategy_math_model(strategy)

    assert result.decision == CEOStrategyMathModelDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "selected_strategy"
    assert "ai_agent_control_room_rescue" in " ".join(result.correct_path)


def test_validation_experiment_must_include_evsi():
    strategy = _valid_strategy()
    strategy["validation_experiment_design"].pop("expected_value_of_sample_information_usd")

    result = validate_ceo_strategy_math_model(strategy)

    assert result.decision == CEOStrategyMathModelDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "validation_experiment_design"


def test_false_revenue_claim_denies():
    strategy = _valid_strategy()
    strategy["overclaim_boundary"]["revenue_claim"] = True

    result = validate_ceo_strategy_math_model(strategy)

    assert result.decision == CEOStrategyMathModelDecisionValue.DENY
    assert result.failed_section == "overclaim_boundary"


def test_owner_bound_l4_execution_escalates():
    result = validate_ceo_strategy_math_model(_valid_strategy(execute_L4_now=True))

    assert result.decision == CEOStrategyMathModelDecisionValue.ESCALATE
    assert result.requires_owner_decision is True


def test_strategy_math_model_writes_formal_cieustore_record(tmp_path):
    db_path = tmp_path / "e107_strategy_math.db"

    result = validate_and_write_ceo_strategy_math_model(
        _valid_strategy(),
        cieu_db=str(db_path),
        seal_session=True,
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["verify_result"]["valid"] is True
    records = CIEUStore(str(db_path)).query(
        session_id="e107_strategy_math",
        event_type=CEO_STRATEGY_MATH_MODEL_CIEU_EVENT_TYPE,
        limit=5,
    )
    assert len(records) == 1
    payload = json.loads(records[0].result_json)
    assert payload["market_first_math_model_required"] is True
    assert payload["internal_capability_not_primary_selector"] is True
