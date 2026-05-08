from __future__ import annotations

import json

from ystar.governance.ceo_competitive_intelligence_contract import (
    CEO_COMPETITIVE_INTELLIGENCE_CIEU_EVENT_TYPE,
    CEOCompetitiveIntelligenceDecisionValue,
    validate_and_write_ceo_competitive_intelligence,
    validate_ceo_competitive_intelligence,
)
from ystar.governance.cieu_store import CIEUStore


def _competitor(idx: int) -> dict:
    return {
        "competitor_name": f"competitor_{idx}",
        "source_url": f"https://example.com/competitor/{idx}",
        "source_date": "2026-05-08",
        "freshness_tier": "current_2026",
        "how_they_solve": "automates part of the same buyer workflow",
        "threat_level": "medium",
        "why_us_gap": "we must prove better evidence, governance, or speed",
    }


def _valid_strategy(**overrides) -> dict:
    selected = "ai_security_compliance_first_cash_pack"
    intel = {
        "competitor_scan_mode": "owner_supplied_live_public_read",
        "latest_source_policy_enforced": True,
        "current_source_refs": [f"https://example.com/source/{idx}" for idx in range(1, 7)],
        "substitute_analysis_present": True,
        "why_us_vs_alternatives_present": True,
        "selected_route_competition": {
            "route_id": selected,
            "competitors": [_competitor(idx) for idx in range(1, 6)],
            "winner_risk_level": "medium",
            "why_we_can_win": "we can produce a concrete evidence pack quickly",
            "why_we_might_lose": "incumbents already own buyer trust and distribution",
        },
        "top_route_competition": [
            {"route_id": f"route_{idx}", "competitors": [_competitor(j) for j in range(1, 4)]}
            for idx in range(1, 4)
        ],
    }
    strategy = {
        "strategy_run_id": "e109_competitive_intel",
        "session_id": "e109_competitive_intel",
        "selected_strategy": {"selected_route_id": selected},
        "competitive_intelligence": intel,
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


def test_valid_competitive_intelligence_allows():
    result = validate_ceo_competitive_intelligence(_valid_strategy())

    assert result.decision == CEOCompetitiveIntelligenceDecisionValue.ALLOW


def test_missing_competitive_intelligence_requires_revision():
    strategy = _valid_strategy()
    strategy.pop("competitive_intelligence")

    result = validate_ceo_competitive_intelligence(strategy)

    assert result.decision == CEOCompetitiveIntelligenceDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "competitive_intelligence"


def test_not_enough_selected_competitors_requires_revision():
    strategy = _valid_strategy()
    strategy["competitive_intelligence"]["selected_route_competition"]["competitors"] = [_competitor(1)]

    result = validate_ceo_competitive_intelligence(strategy)

    assert result.decision == CEOCompetitiveIntelligenceDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "selected_route_competition"


def test_stale_competitor_source_requires_revision():
    strategy = _valid_strategy()
    strategy["competitive_intelligence"]["selected_route_competition"]["competitors"][0]["freshness_tier"] = "stale"

    result = validate_ceo_competitive_intelligence(strategy)

    assert result.decision == CEOCompetitiveIntelligenceDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "selected_route_competition"


def test_false_revenue_claim_denies():
    strategy = _valid_strategy()
    strategy["overclaim_boundary"]["revenue_claim"] = True

    result = validate_ceo_competitive_intelligence(strategy)

    assert result.decision == CEOCompetitiveIntelligenceDecisionValue.DENY
    assert result.failed_section == "overclaim_boundary"


def test_owner_bound_l4_execution_escalates():
    result = validate_ceo_competitive_intelligence(_valid_strategy(execute_L4_now=True))

    assert result.decision == CEOCompetitiveIntelligenceDecisionValue.ESCALATE
    assert result.requires_owner_decision is True


def test_competitive_intelligence_writes_formal_cieustore_record(tmp_path):
    db_path = tmp_path / "e109_competitive.db"

    result = validate_and_write_ceo_competitive_intelligence(
        _valid_strategy(),
        cieu_db=str(db_path),
        seal_session=True,
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["verify_result"]["valid"] is True
    records = CIEUStore(str(db_path)).query(
        session_id="e109_competitive_intel",
        event_type=CEO_COMPETITIVE_INTELLIGENCE_CIEU_EVENT_TYPE,
        limit=5,
    )
    assert len(records) == 1
    payload = json.loads(records[0].result_json)
    assert payload["competitive_intelligence_required"] is True
    assert payload["latest_source_policy_enforced"] is True
