from __future__ import annotations

import sqlite3

from ystar.governance.aiden_idle_learning_contract import (
    AIDEN_IDLE_LEARNING_CIEU_EVENT_TYPE,
    AidenIdleLearningDecisionValue,
    validate_aiden_idle_learning_packet,
    validate_and_write_aiden_idle_learning_packet,
)


def _evidence(idx: int, domain_id: str = "ceo_judgment") -> dict:
    return {
        "evidence_id": f"e116_evidence_{idx}",
        "domain_id": domain_id,
        "source_url": f"https://public.example.org/source-{idx}",
        "source_title": f"Source {idx}",
        "source_date": "2026-05-01",
        "observed_at": "2026-05-09T00:00:00Z",
        "freshness_status": "accepted_current",
        "claim_summary": f"Source-dated learning fact {idx}",
    }


def _valid_packet() -> dict:
    domain_ids = [
        "ceo_judgment",
        "market_intelligence",
        "competitive_strategy",
        "product_strategy",
        "sales_and_distribution",
        "governance_and_risk",
        "technology_architecture",
        "failure_residual_learning",
    ]
    evidence = [_evidence(idx + 1, domain_ids[idx % len(domain_ids)]) for idx in range(10)]
    nodes = [
        {
            "node_id": f"ceo_learning/e116_node_{idx}",
            "name": f"E116 Node {idx}",
            "node_type": "ceo_idle_learning",
            "depth_label": "operational",
            "source_evidence_ids": [evidence[idx % len(evidence)]["evidence_id"]],
            "summary": f"Learning node {idx}",
        }
        for idx in range(10)
    ]
    edges = [
        {
            "source_id": nodes[idx]["node_id"],
            "target_id": nodes[(idx + 1) % len(nodes)]["node_id"],
            "edge_type": "idle_learning",
            "weight": 0.55,
        }
        for idx in range(10)
    ]
    return {
        "learning_cycle_id": "e116_test_idle_learning",
        "learning_mode": "idle_continuous_learning",
        "trigger_context": {
            "idle_state_verified": True,
            "explicit_session_task_active": False,
            "active_session_source": "test_fixture",
        },
        "curriculum_domains": [{"domain_id": domain_id, "priority": "mandatory"} for domain_id in domain_ids],
        "source_date_policy": {
            "source_dates_required": True,
            "stale_or_undated_rejected": True,
            "freshness_policy_id": "e112_market_evidence_freshness_policy_v1",
        },
        "evidence_items": evidence,
        "knowledge_graph_delta": {"nodes": nodes, "edges": edges},
        "brain_write_policy": {
            "write_mode": "isolated_test_brain_db_write",
            "automatic_direct_writeback": False,
            "YstarGov_validation_required": True,
            "target_brain_db": "/tmp/e116_test_brain.db",
            "max_nodes_per_cycle": 25,
            "max_edges_per_cycle": 50,
            "production_brain_write_performed": False,
        },
        "CIEU_linkage": {
            "target_event_type": AIDEN_IDLE_LEARNING_CIEU_EVENT_TYPE,
            "formal_CIEU_log_path": "ystar.governance.cieu_store.CIEUStore.write_dict",
        },
        "CZL_closure": {
            "uses_existing_CZL": True,
            "residual_loop_engine_path": "ystar/governance/residual_loop_engine.py",
            "R_t_plus_1": 0.0,
        },
        "truth_constraints": {
            "external_action_executed": False,
            "provider_action_executed": False,
            "customer_validation_claim": False,
            "pricing_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "paid_signal_claim": False,
            "L4_feedback_executed": False,
            "L5_revenue_loop_complete": False,
            "K9Audit_integration_claim": False,
            "live_provider_execution_claim": False,
        },
    }


def test_valid_idle_learning_packet_allows_and_writes_cieustore(tmp_path):
    packet = _valid_packet()

    decision = validate_aiden_idle_learning_packet(packet)
    assert decision.decision == AidenIdleLearningDecisionValue.ALLOW

    db = tmp_path / "idle_learning.db"
    result = validate_and_write_aiden_idle_learning_packet(packet, cieu_db=str(db), session_id="e116_test")
    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT event_type, decision FROM cieu_events").fetchone()
    assert row == (AIDEN_IDLE_LEARNING_CIEU_EVENT_TYPE, "ALLOW")


def test_active_session_task_requires_revision_with_navigation():
    packet = _valid_packet()
    packet["trigger_context"]["explicit_session_task_active"] = True

    decision = validate_aiden_idle_learning_packet(packet).to_dict()

    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "trigger_context"
    assert "finish the active session task first" in " ".join(decision["correct_path"])


def test_undated_or_unaccepted_evidence_requires_revision():
    packet = _valid_packet()
    packet["evidence_items"][0]["freshness_status"] = "rejected_missing_source_date_for_brain_learning"

    decision = validate_aiden_idle_learning_packet(packet).to_dict()

    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "evidence_items"


def test_automatic_direct_writeback_is_denied():
    packet = _valid_packet()
    packet["brain_write_policy"]["automatic_direct_writeback"] = True

    decision = validate_aiden_idle_learning_packet(packet).to_dict()

    assert decision["decision"] == "DENY"
    assert decision["failed_section"] == "brain_write_policy"


def test_external_or_revenue_claim_is_denied():
    packet = _valid_packet()
    packet["truth_constraints"]["revenue_claim"] = True

    decision = validate_aiden_idle_learning_packet(packet).to_dict()

    assert decision["decision"] == "DENY"
    assert decision["failed_section"] == "truth_constraints"

