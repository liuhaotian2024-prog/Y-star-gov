from __future__ import annotations

import json

from ystar.governance.ceo_market_strategy_refresh_contract import (
    CEO_MARKET_STRATEGY_REFRESH_CIEU_EVENT_TYPE,
    CEOMarketStrategyRefreshDecisionValue,
    validate_and_write_ceo_market_strategy_refresh,
    validate_ceo_market_strategy_refresh,
)
from ystar.governance.cieu_store import CIEUStore


def _evidence(idx: int, category: str = "agent_governance") -> dict:
    return {
        "evidence_id": f"evidence_{idx}",
        "source_title": f"Public source {idx}",
        "source_url": f"https://example.org/source-{idx}",
        "category": category,
        "claim_summary": "Current public-read evidence supports the strategy comparison.",
        "evidence_type": "public_read_only",
        "observed_at": "2026-05-08",
    }


def _competitor(competitor_id: str) -> dict:
    return {
        "competitor_id": competitor_id,
        "name": competitor_id.replace("_", " ").title(),
        "source_url": f"https://example.org/{competitor_id}",
        "threat_level": "high",
    }


def _valid_strategy(**overrides) -> dict:
    competitors = [
        "black_ore",
        "basis",
        "juno",
        "cpa_pilot",
        "aiwyn",
        "canopy",
        "karbon",
        "taxdome",
        "madras_accountancy_offshore",
    ]
    strategy = {
        "strategy_run_id": "e104_adaptive_market_strategy",
        "session_id": "e104_adaptive_market_strategy",
        "selected_strategy": {
            "selected_route_id": "agentic_engineering_control_room_rescue",
            "current_best_first_cash_path": "AI Agent Control Room Rescue for founder-led engineering teams",
            "why_this_path_now": "best founder-market fit and visible buyer pain around agent governance",
        },
        "external_market_evidence_map": {
            "freshness_status": "current_public_read_as_of_2026-05-08",
            "evidence_items": [_evidence(idx) for idx in range(1, 11)],
        },
        "adaptive_market_governance_gates": {
            "live_market_evidence_refresh_gate": {
                "gate_passed": True,
                "freshness_status": "current_public_read_as_of_2026-05-08",
                "evidence_count": 10,
            },
            "competitor_saturation_scan": {
                "gate_passed": True,
                "saturation_level": "high",
                "competitors": [_competitor(item) for item in competitors],
                "route_implication": "CPA route is credible but crowded and must be demoted.",
            },
            "founder_market_fit_gate": {
                "gate_passed": True,
                "founder_is_cpa": False,
                "route_fit_scores": {
                    "agentic_engineering_control_room_rescue": 5,
                    "cpa_review_bottleneck_rescue": 2,
                },
            },
            "customer_visible_differentiation_gate": {
                "gate_passed": True,
                "internal_only_claims_disallowed": True,
                "visible_customer_outcomes": [
                    "repo drift is found before it damages delivery",
                    "AI executor scope is constrained before code changes",
                    "a no-force-push delivery path is proven",
                ],
            },
            "price_hypothesis_source_audit": {
                "gate_passed": True,
                "validation_status": "hypothesis_only_not_validated",
                "source_refs": ["public_consulting_rate_analog", "agentic_ai_operations_gap"],
            },
            "strategy_residual_intake": {
                "gate_passed": True,
                "residuals_ingested": [
                    "Claude critique: competitor saturation was missing.",
                    "Claude critique: founder-market fit was weak for CPA route.",
                    "Claude critique: prior brain market data was stale.",
                ],
            },
            "open_world_research_trigger": {
                "gate_passed": True,
                "domains_compared": [
                    {"route_id": "agentic_engineering_control_room_rescue"},
                    {"route_id": "cpa_review_bottleneck_rescue"},
                    {"route_id": "tariff_shock_margin_rescue"},
                    {"route_id": "small_business_ai_workflow_rescue"},
                    {"route_id": "insurance_premium_rescue_brief"},
                ],
            },
        },
        "next_L4_feedback_owner_decision_packet": {
            "owner_decision_required": True,
            "owner_approval_state": "pending_owner_decision",
            "no_send_default": True,
            "external_action_executed": False,
            "provider_action_executed": False,
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


def test_valid_adaptive_market_strategy_allows():
    result = validate_ceo_market_strategy_refresh(_valid_strategy())

    assert result.decision == CEOMarketStrategyRefreshDecisionValue.ALLOW
    assert result.to_dict()["passed"] is True


def test_missing_required_gate_requires_revision_with_correct_path():
    strategy = _valid_strategy()
    strategy["adaptive_market_governance_gates"].pop("founder_market_fit_gate")

    result = validate_ceo_market_strategy_refresh(strategy)

    assert result.decision == CEOMarketStrategyRefreshDecisionValue.REQUIRE_REVISION
    assert result.failed_gate == "adaptive_market_governance_gates"
    assert result.correct_path


def test_missing_competitor_saturation_requires_revision():
    strategy = _valid_strategy()
    strategy["adaptive_market_governance_gates"]["competitor_saturation_scan"]["competitors"] = [
        _competitor("taxdome"),
        _competitor("karbon"),
    ]

    result = validate_ceo_market_strategy_refresh(strategy)

    assert result.decision == CEOMarketStrategyRefreshDecisionValue.REQUIRE_REVISION
    assert result.failed_gate == "competitor_saturation_scan"
    assert "black_ore" in " ".join(result.correct_path)


def test_weak_founder_market_fit_requires_revision():
    strategy = _valid_strategy()
    strategy["adaptive_market_governance_gates"]["founder_market_fit_gate"]["route_fit_scores"][
        "agentic_engineering_control_room_rescue"
    ] = 2

    result = validate_ceo_market_strategy_refresh(strategy)

    assert result.decision == CEOMarketStrategyRefreshDecisionValue.REQUIRE_REVISION
    assert result.failed_gate == "founder_market_fit_gate"


def test_false_customer_or_revenue_claim_denies():
    strategy = _valid_strategy()
    strategy["overclaim_boundary"]["revenue_claim"] = True

    result = validate_ceo_market_strategy_refresh(strategy)

    assert result.decision == CEOMarketStrategyRefreshDecisionValue.DENY
    assert result.failed_gate == "overclaim_boundary"


def test_owner_bound_l4_execution_escalates():
    strategy = _valid_strategy(execute_L4_now=True)

    result = validate_ceo_market_strategy_refresh(strategy)

    assert result.decision == CEOMarketStrategyRefreshDecisionValue.ESCALATE
    assert result.requires_owner_decision is True


def test_refresh_contract_writes_formal_cieustore_record(tmp_path):
    db_path = tmp_path / "e104_market_strategy_refresh.db"

    result = validate_and_write_ceo_market_strategy_refresh(
        _valid_strategy(),
        cieu_db=str(db_path),
        seal_session=True,
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["verify_result"]["valid"] is True
    records = CIEUStore(str(db_path)).query(
        session_id="e104_adaptive_market_strategy",
        event_type=CEO_MARKET_STRATEGY_REFRESH_CIEU_EVENT_TYPE,
        limit=5,
    )
    assert len(records) == 1
    payload = json.loads(records[0].result_json)
    assert payload["decision"] == "ALLOW"
    assert payload["selected_route_id"] == "agentic_engineering_control_room_rescue"
    assert payload["market_refresh_gates_required"] is True
