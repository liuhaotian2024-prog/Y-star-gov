from __future__ import annotations

import json

from ystar.governance.ceo_open_world_strategy_contract import (
    CEO_OPEN_WORLD_STRATEGY_CIEU_EVENT_TYPE,
    CEOOpenWorldStrategyDecisionValue,
    validate_and_write_ceo_open_world_strategy,
    validate_ceo_open_world_strategy,
)
from ystar.governance.cieu_store import CIEUStore


def _evidence(idx: int, category: str = "agent_governance") -> dict:
    return {
        "evidence_id": f"evidence_{idx}",
        "source_title": f"Public source {idx}",
        "source_url": f"https://example.org/source-{idx}",
        "category": category,
        "claim_summary": "Public-read evidence supports an opportunity cluster.",
        "evidence_type": "public_read_only",
    }


def _valid_strategy(**overrides) -> dict:
    evidence_items = [_evidence(idx) for idx in range(1, 13)]
    strategy = {
        "strategy_run_id": "e105_open_world_strategy",
        "session_id": "e105_open_world_strategy",
        "generation_mode": "evidence_derived_open_world_strategy",
        "external_market_evidence_map": {
            "freshness_status": "current_public_read_as_of_2026-05-08",
            "evidence_items": evidence_items,
        },
        "open_world_discovery_proof": {
            "evidence_feed_mode": "codex_public_read_research_snapshot",
            "candidate_generation_mode": "dynamic_evidence_cluster_derivation",
            "closed_route_preset_used": False,
            "query_expansion_rounds": [
                {"round_id": "round_0", "queries": ["AI agents governance market"]},
                {"round_id": "round_1", "queries": ["agent observability production gap"]},
                {"round_id": "round_2", "queries": ["small business AI workflow pain"]},
            ],
            "opportunity_clusters": [
                {
                    "cluster_id": "agentic_ai_runtime_governance",
                    "discovered_from_prompt_seed": True,
                    "evidence_refs": ["evidence_1", "evidence_2"],
                },
                {
                    "cluster_id": "ai_observability_gap",
                    "discovered_from_prompt_seed": False,
                    "evidence_refs": ["evidence_3", "evidence_4"],
                },
                {
                    "cluster_id": "smb_ai_workflow_automation",
                    "discovered_from_prompt_seed": True,
                    "evidence_refs": ["evidence_5", "evidence_6"],
                },
                {
                    "cluster_id": "tariff_margin_pressure",
                    "discovered_from_prompt_seed": True,
                    "evidence_refs": ["evidence_7", "evidence_8"],
                },
                {
                    "cluster_id": "cpa_ai_saturation",
                    "discovered_from_prompt_seed": True,
                    "evidence_refs": ["evidence_9", "evidence_10"],
                },
            ],
        },
        "route_candidates": [
            {"route_id": "agentic_ai_runtime_governance_rescue", "source_cluster_ids": ["agentic_ai_runtime_governance"]},
            {"route_id": "ai_observability_gap_rescue", "source_cluster_ids": ["ai_observability_gap"]},
            {"route_id": "smb_ai_workflow_automation_rescue", "source_cluster_ids": ["smb_ai_workflow_automation"]},
            {"route_id": "tariff_margin_pressure_rescue", "source_cluster_ids": ["tariff_margin_pressure"]},
            {"route_id": "cpa_ai_saturation_rescue", "source_cluster_ids": ["cpa_ai_saturation"]},
        ],
        "route_scoring": [
            {"route_id": "agentic_ai_runtime_governance_rescue", "first_cash_score": 22.0},
            {"route_id": "ai_observability_gap_rescue", "first_cash_score": 21.0},
            {"route_id": "smb_ai_workflow_automation_rescue", "first_cash_score": 16.0},
            {"route_id": "tariff_margin_pressure_rescue", "first_cash_score": 12.0},
            {"route_id": "cpa_ai_saturation_rescue", "first_cash_score": 11.0},
        ],
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


def test_valid_open_world_strategy_allows():
    result = validate_ceo_open_world_strategy(_valid_strategy())

    assert result.decision == CEOOpenWorldStrategyDecisionValue.ALLOW


def test_closed_route_preset_requires_revision():
    strategy = _valid_strategy()
    strategy["open_world_discovery_proof"]["closed_route_preset_used"] = True
    strategy["open_world_discovery_proof"]["candidate_generation_mode"] = "hardcoded_route_list"

    result = validate_ceo_open_world_strategy(strategy)

    assert result.decision == CEOOpenWorldStrategyDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "candidate_generation_mode"
    assert "hardcoded" in " ".join(result.correct_path)


def test_missing_unseeded_cluster_requires_revision():
    strategy = _valid_strategy()
    for cluster in strategy["open_world_discovery_proof"]["opportunity_clusters"]:
        cluster["discovered_from_prompt_seed"] = True

    result = validate_ceo_open_world_strategy(strategy)

    assert result.decision == CEOOpenWorldStrategyDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "opportunity_clusters"


def test_candidate_without_cluster_trace_requires_revision():
    strategy = _valid_strategy()
    strategy["route_candidates"][0]["source_cluster_ids"] = ["missing_cluster"]

    result = validate_ceo_open_world_strategy(strategy)

    assert result.decision == CEOOpenWorldStrategyDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "route_candidates"


def test_false_revenue_claim_denies():
    strategy = _valid_strategy()
    strategy["overclaim_boundary"]["revenue_claim"] = True

    result = validate_ceo_open_world_strategy(strategy)

    assert result.decision == CEOOpenWorldStrategyDecisionValue.DENY
    assert result.failed_section == "overclaim_boundary"


def test_owner_bound_l4_execution_escalates():
    result = validate_ceo_open_world_strategy(_valid_strategy(execute_L4_now=True))

    assert result.decision == CEOOpenWorldStrategyDecisionValue.ESCALATE
    assert result.requires_owner_decision is True


def test_open_world_contract_writes_formal_cieustore_record(tmp_path):
    db_path = tmp_path / "e105_open_world.db"

    result = validate_and_write_ceo_open_world_strategy(
        _valid_strategy(),
        cieu_db=str(db_path),
        seal_session=True,
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["verify_result"]["valid"] is True
    records = CIEUStore(str(db_path)).query(
        session_id="e105_open_world_strategy",
        event_type=CEO_OPEN_WORLD_STRATEGY_CIEU_EVENT_TYPE,
        limit=5,
    )
    assert len(records) == 1
    payload = json.loads(records[0].result_json)
    assert payload["decision"] == "ALLOW"
    assert payload["open_world_discovery_required"] is True
