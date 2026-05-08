from __future__ import annotations

import json

from ystar.governance.ceo_live_global_open_world_strategy_contract import (
    CEO_LIVE_GLOBAL_OPEN_WORLD_CIEU_EVENT_TYPE,
    CEOLiveGlobalOpenWorldDecisionValue,
    validate_and_write_ceo_live_global_open_world_strategy,
    validate_ceo_live_global_open_world_strategy,
)
from ystar.governance.cieu_store import CIEUStore


def _evidence(idx: int, domain: str) -> dict:
    return {
        "evidence_id": f"ev_{idx}",
        "source_title": f"{domain} market signal {idx}",
        "source_url": f"https://example.com/{domain}/{idx}",
        "claim_summary": "public-read buyer pain and market alternative signal",
        "observed_at": "2026-05-08T00:00:00Z",
        "domain_id": domain,
    }


def _valid_strategy(**overrides) -> dict:
    domains = [
        {"domain_id": f"domain_{idx}", "adjacent_to_prior_anchor": idx <= 3}
        for idx in range(1, 14)
    ]
    evidence = [_evidence(idx, f"domain_{(idx % 13) + 1}") for idx in range(1, 27)]
    clusters = [
        {
            "cluster_id": f"cluster_{idx}",
            "evidence_refs": [f"ev_{idx}", f"ev_{idx + 1}"],
            "derived_from_fixed_candidate_list": False,
        }
        for idx in range(1, 12)
    ]
    candidates = [
        {
            "route_id": f"route_{idx}",
            "source_cluster_ids": [f"cluster_{idx if idx < 11 else 10}"],
            "evidence_refs": [f"ev_{idx}", f"ev_{idx + 1}"],
            "candidate_source": "live_evidence_cluster",
        }
        for idx in range(1, 12)
    ]
    strategy = {
        "strategy_run_id": "e108_live_global",
        "session_id": "e108_live_global",
        "live_global_open_world_scan": {
            "scan_mode": "codex_live_public_read_web",
            "live_public_read_performed": True,
            "provider_status": "success",
            "scan_domains": domains,
            "query_expansion_rounds": [
                {"round_id": f"round_{idx}", "queries": [f"query {idx}"]}
                for idx in range(4)
            ],
            "evidence_items": evidence,
            "opportunity_clusters": clusters,
            "anchor_proximity_audit": {
                "globally_ranked_against_non_adjacent_domains": True,
                "selected_route_is_prior_anchor_clone": False,
            },
        },
        "route_candidates": candidates,
        "selected_strategy": {"selected_route_id": "route_1"},
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


def test_valid_live_global_open_world_strategy_allows():
    result = validate_ceo_live_global_open_world_strategy(_valid_strategy())

    assert result.decision == CEOLiveGlobalOpenWorldDecisionValue.ALLOW


def test_snapshot_scan_requires_revision_with_correct_path():
    strategy = _valid_strategy()
    strategy["live_global_open_world_scan"]["scan_mode"] = "codex_public_read_research_snapshot"

    result = validate_ceo_live_global_open_world_strategy(strategy)

    assert result.decision == CEOLiveGlobalOpenWorldDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "scan_mode"
    assert "live_public_read_network" in " ".join(result.correct_path)


def test_missing_non_adjacent_domains_requires_revision():
    strategy = _valid_strategy()
    for domain in strategy["live_global_open_world_scan"]["scan_domains"]:
        domain["adjacent_to_prior_anchor"] = True

    result = validate_ceo_live_global_open_world_strategy(strategy)

    assert result.decision == CEOLiveGlobalOpenWorldDecisionValue.REQUIRE_REVISION
    assert result.failed_section == "scan_domains"


def test_fixed_candidate_list_denies():
    strategy = _valid_strategy()
    strategy["route_candidates"][0]["candidate_source"] = "fixed_preset"

    result = validate_ceo_live_global_open_world_strategy(strategy)

    assert result.decision == CEOLiveGlobalOpenWorldDecisionValue.DENY
    assert result.failed_section == "route_candidates"


def test_prior_anchor_clone_denies():
    strategy = _valid_strategy()
    strategy["live_global_open_world_scan"]["anchor_proximity_audit"]["selected_route_is_prior_anchor_clone"] = True

    result = validate_ceo_live_global_open_world_strategy(strategy)

    assert result.decision == CEOLiveGlobalOpenWorldDecisionValue.DENY
    assert result.failed_section == "anchor_proximity_audit"


def test_false_revenue_claim_denies():
    strategy = _valid_strategy()
    strategy["overclaim_boundary"]["revenue_claim"] = True

    result = validate_ceo_live_global_open_world_strategy(strategy)

    assert result.decision == CEOLiveGlobalOpenWorldDecisionValue.DENY
    assert result.failed_section == "overclaim_boundary"


def test_owner_bound_l4_execution_escalates():
    result = validate_ceo_live_global_open_world_strategy(_valid_strategy(execute_L4_now=True))

    assert result.decision == CEOLiveGlobalOpenWorldDecisionValue.ESCALATE
    assert result.requires_owner_decision is True


def test_live_global_open_world_writes_formal_cieustore_record(tmp_path):
    db_path = tmp_path / "e108_live_global.db"

    result = validate_and_write_ceo_live_global_open_world_strategy(
        _valid_strategy(),
        cieu_db=str(db_path),
        seal_session=True,
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["verify_result"]["valid"] is True
    records = CIEUStore(str(db_path)).query(
        session_id="e108_live_global",
        event_type=CEO_LIVE_GLOBAL_OPEN_WORLD_CIEU_EVENT_TYPE,
        limit=5,
    )
    assert len(records) == 1
    payload = json.loads(records[0].result_json)
    assert payload["live_global_public_read_required"] is True
    assert payload["snapshot_evidence_sufficient"] is False
