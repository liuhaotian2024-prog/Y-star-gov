from __future__ import annotations

from pathlib import Path

from ystar.governance.aiden_host_autonomous_web_observer_contract import (
    AIDEN_HOST_AUTONOMOUS_WEB_OBSERVER_EVENT_TYPE,
    validate_aiden_host_autonomous_web_observer_packet,
    validate_and_write_aiden_host_autonomous_web_observer_packet,
)


def _evidence(i: int, domain: str) -> dict:
    return {
        "evidence_id": f"ev_{i:03d}",
        "domain_id": domain,
        "title": f"Source-dated public evidence {i}",
        "source_url": f"https://example.org/{domain}/article-{i}",
        "source_date": "2026-05-01",
        "observed_at": "2026-05-09T00:00:00Z",
        "freshness_status": "accepted_current",
        "content_type": "current_market_signal",
        "claim": "Dated public-read evidence for governed autonomous observation.",
    }


def _valid_packet() -> dict:
    domains = [
        "ai_security",
        "healthcare_admin",
        "construction",
        "legal_ops",
        "insurance",
        "manufacturing",
        "local_services",
        "grant_ops",
    ]
    evidence = [_evidence(i, domains[i % len(domains)]) for i in range(16)]
    return {
        "observer_cycle_id": "e121_test_cycle",
        "execution_boundary": {
            "runs_on_owner_host": True,
            "sandbox_restricted": False,
            "host_public_read_bridge": True,
            "external_side_effect_allowed": False,
        },
        "query_frontier": {
            "round_count": 3,
            "recent_memory_anchor_removed": True,
            "domain_hypotheses": domains,
            "rounds": [
                {"round_id": "broad_scan", "queries": ["global AI business opportunities 2026"]},
                {"round_id": "expansion_scan", "queries": ["underrated SMB bottlenecks AI 2026"]},
                {"round_id": "contradiction_scan", "queries": ["funded competitors AI compliance 2026"]},
            ],
        },
        "public_read_policy": {
            "public_read_only": True,
            "allowed_http_methods": ["GET", "HEAD"],
            "login_allowed": False,
            "form_submission_allowed": False,
            "contact_allowed": False,
            "payment_allowed": False,
            "account_creation_allowed": False,
            "private_data_collection_allowed": False,
        },
        "source_date_policy": {"policy_id": "e120_content_type_aware_evidence_freshness_policy_v2"},
        "evidence_items": evidence,
        "learning_quality_summary": {
            "learning_quality_gate_applied": True,
            "average_quality_score": 0.74,
            "minimum_quality_score": 0.66,
            "low_quality_evidence_ids": [],
        },
        "knowledge_graph_update_plan": {
            "production_brain_write_requires_owner_gate": True,
            "candidate_node_types": [
                "market_fact",
                "competitor",
                "buyer_pain",
                "theory",
                "assumption",
                "residual",
            ],
            "candidate_edge_types": ["supports", "contradicts", "competes_with", "updates", "falsifies"],
        },
        "local_gemma_runtime": {
            "requested": True,
            "available": True,
            "status": "available",
            "runtime_host": "127.0.0.1",
            "model_name": "gemma4:latest",
            "external_provider_api_used": False,
            "private_data_exfiltration_allowed": False,
        },
        "governance_chain": {
            "governance_links": [
                "E112_content_type_freshness_filter",
                "E119_operating_pattern_doctrine",
                "E120_unknown_problem_learning_protocol",
                "CIEUStore_formal_recording",
            ]
        },
        "CIEU_linkage": {"CIEU_recording_required": True},
        "truth_constraints": {
            "login_attempted": False,
            "form_submitted": False,
            "message_sent": False,
            "payment_attempted": False,
            "external_action_executed": False,
            "provider_action_executed": False,
            "scraped_private_data": False,
            "customer_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "live_provider_execution_claim": False,
            "K9Audit_integration_claim": False,
            "raw_unvalidated_codex_prompt_used": False,
            "external_llm_provider_used_for_local_gemma": False,
        },
    }


def test_valid_packet_allows() -> None:
    decision = validate_aiden_host_autonomous_web_observer_packet(_valid_packet())
    assert decision.to_dict()["decision"] == "ALLOW"


def test_non_read_http_method_denies() -> None:
    packet = _valid_packet()
    packet["public_read_policy"]["allowed_http_methods"] = ["GET", "POST"]
    decision = validate_aiden_host_autonomous_web_observer_packet(packet)
    assert decision.to_dict()["decision"] == "DENY"
    assert "POST" in decision.to_dict()["violations"]


def test_missing_source_date_requires_revision() -> None:
    packet = _valid_packet()
    packet["evidence_items"][0].pop("source_date")
    decision = validate_aiden_host_autonomous_web_observer_packet(packet)
    assert decision.to_dict()["decision"] == "REQUIRE_REVISION"
    assert decision.to_dict()["failed_section"] == "evidence_items"


def test_local_gemma_missing_requires_correct_path() -> None:
    packet = _valid_packet()
    packet["local_gemma_runtime"]["available"] = False
    packet["local_gemma_runtime"]["status"] = "not_found"
    decision = validate_aiden_host_autonomous_web_observer_packet(packet)
    data = decision.to_dict()
    assert data["decision"] == "REQUIRE_REVISION"
    assert "pull a Gemma4-compatible local model" in " ".join(data["correct_path"])


def test_external_llm_provider_for_local_gemma_denies() -> None:
    packet = _valid_packet()
    packet["local_gemma_runtime"]["external_provider_api_used"] = True
    decision = validate_aiden_host_autonomous_web_observer_packet(packet)
    assert decision.to_dict()["decision"] == "DENY"


def test_cieu_writer_records_decision(tmp_path: Path) -> None:
    db = tmp_path / "e121_ystar.db"
    result = validate_and_write_aiden_host_autonomous_web_observer_packet(
        _valid_packet(),
        cieu_db=str(db),
        session_id="e121_test",
    )
    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["event_type"] == AIDEN_HOST_AUTONOMOUS_WEB_OBSERVER_EVENT_TYPE
