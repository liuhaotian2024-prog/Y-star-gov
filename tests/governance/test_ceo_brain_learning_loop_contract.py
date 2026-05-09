from __future__ import annotations

import sqlite3

from ystar.governance.ceo_brain_learning_loop_contract import (
    CEO_BRAIN_LEARNING_LOOP_CIEU_EVENT_TYPE,
    validate_and_write_ceo_brain_learning_packet,
    validate_ceo_brain_learning_packet,
)


def _valid_packet() -> dict:
    return {
        "learning_loop_id": "e112_learning_loop_test",
        "source_runtime": "E111_Aiden_Host_Runtime",
        "source_strategy_session_id": "e112_test_session",
        "freshness_policy": {
            "current_date": "2026-05-09",
            "market_current_max_age_days": 365,
            "competitive_current_max_age_days": 240,
        },
        "evidence_freshness_report": {
            "freshness_filter_applied": True,
            "accepted_count": 2,
            "rejected_count": 1,
            "stale_evidence_used_for_brain_candidate": False,
        },
        "accepted_evidence_items": [
            {
                "evidence_id": "fresh_market_1",
                "source_url": "https://example.com/current-market",
                "source_date": "2026-05-01",
                "observed_at": "2026-05-09T00:00:00Z",
                "freshness_status": "accepted_current",
                "claim_summary": "Current buyer pain evidence.",
            },
            {
                "evidence_id": "fresh_competitor_1",
                "source_url": "https://example.com/current-competitor",
                "source_date": "2026-04-20",
                "observed_at": "2026-05-09T00:00:00Z",
                "freshness_status": "accepted_current",
                "claim_summary": "Current competitor evidence.",
            },
        ],
        "rejected_evidence_items": [
            {
                "evidence_id": "stale_market_1",
                "source_url": "https://example.com/old",
                "source_date": "2023-01-01",
                "freshness_status": "rejected_stale",
            }
        ],
        "brain_mutation_candidates": [
            {
                "candidate_id": "brain_fact_current_market",
                "candidate_type": "market_fact_node",
                "source_evidence_ids": ["fresh_market_1"],
                "summary": "Persist current market pain as candidate memory.",
                "write_mode": "CIEU_backed_candidate_only",
                "production_brain_write_performed": False,
            },
            {
                "candidate_id": "brain_fact_current_competitor",
                "candidate_type": "competitor_fact_node",
                "source_evidence_ids": ["fresh_competitor_1"],
                "summary": "Persist current competitor as candidate memory.",
                "write_mode": "CIEU_backed_candidate_only",
                "production_brain_write_performed": False,
            },
        ],
        "failure_residual_candidates": [
            {
                "residual_id": "residual_competitor_gap",
                "learning_update": "Aiden must refresh competitor saturation before strategic claims.",
                "source_evidence_ids": ["fresh_competitor_1"],
                "residual_loop_engine_path": "ystar/governance/residual_loop_engine.py",
                "CZL_residual_tuple": {
                    "X_t": {"claim": "competitor map stale"},
                    "U": ["refresh current competitor evidence"],
                    "Y_star": {"fresh_competitor_map": True},
                    "Y_t_plus_1": {"fresh_competitor_map": False},
                    "R_t_plus_1": 0.5,
                },
            }
        ],
        "CZL_residual_loop_linkage": {
            "residual_loop_engine_path": "ystar/governance/residual_loop_engine.py",
            "czl_tuple_schema": ["X_t", "U", "Y_star", "Y_t_plus_1", "R_t_plus_1"],
            "uses_existing_czl_mechanism": True,
        },
        "brain_write_policy": {
            "automatic_direct_writeback": False,
            "production_brain_write_requested": False,
            "production_brain_write_performed": False,
            "default_write_mode": "CIEU_backed_candidate_only",
        },
        "CIEU_linkage": {
            "source_CIEU_event_ids": ["event_strategy", "event_host_runtime"],
            "target_event_type": CEO_BRAIN_LEARNING_LOOP_CIEU_EVENT_TYPE,
        },
        "truth_constraints": {
            "customer_validation_claim": False,
            "pricing_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "L4_feedback_executed": False,
            "L5_revenue_loop_complete": False,
            "K9Audit_integration_claim": False,
            "live_provider_execution_claim": False,
        },
    }


def test_valid_brain_learning_packet_allows_and_writes_cieustore(tmp_path):
    packet = _valid_packet()
    decision = validate_ceo_brain_learning_packet(packet)
    assert decision.to_dict()["decision"] == "ALLOW"

    db = tmp_path / "cieu.db"
    result = validate_and_write_ceo_brain_learning_packet(packet, cieu_db=str(db), session_id="e112_test_session")
    assert result["formal_CIEU_log_written"] is True
    assert result["governance_decision"]["decision"] == "ALLOW"
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT event_type, decision FROM cieu_events").fetchone()
    assert row == (CEO_BRAIN_LEARNING_LOOP_CIEU_EVENT_TYPE, "ALLOW")


def test_stale_evidence_cannot_feed_brain_candidate():
    packet = _valid_packet()
    packet["brain_mutation_candidates"][0]["source_evidence_ids"] = ["stale_market_1"]
    decision = validate_ceo_brain_learning_packet(packet)
    assert decision.to_dict()["decision"] == "REQUIRE_REVISION"
    assert "fresh" in " ".join(decision.to_dict()["correct_path"]).lower()


def test_automatic_direct_brain_writeback_is_denied():
    packet = _valid_packet()
    packet["brain_write_policy"]["automatic_direct_writeback"] = True
    decision = validate_ceo_brain_learning_packet(packet)
    assert decision.to_dict()["decision"] == "DENY"


def test_production_brain_write_request_escalates():
    packet = _valid_packet()
    packet["brain_write_policy"]["production_brain_write_requested"] = True
    decision = validate_ceo_brain_learning_packet(packet)
    assert decision.to_dict()["decision"] == "ESCALATE"
    assert decision.to_dict()["requires_owner_decision"] is True


def test_false_revenue_or_k9_claim_is_denied():
    packet = _valid_packet()
    packet["truth_constraints"]["revenue_claim"] = True
    decision = validate_ceo_brain_learning_packet(packet)
    assert decision.to_dict()["decision"] == "DENY"


def test_no_accepted_fresh_evidence_requires_revision():
    packet = _valid_packet()
    packet["accepted_evidence_items"] = []
    packet["brain_mutation_candidates"] = []
    decision = validate_ceo_brain_learning_packet(packet)
    assert decision.to_dict()["decision"] == "REQUIRE_REVISION"
    assert "refresh public-read scan" in " ".join(decision.to_dict()["correct_path"])


def test_missing_czl_residual_tuple_requires_revision():
    packet = _valid_packet()
    del packet["failure_residual_candidates"][0]["CZL_residual_tuple"]
    decision = validate_ceo_brain_learning_packet(packet)
    assert decision.to_dict()["decision"] == "REQUIRE_REVISION"
    assert "CZL_residual_tuple" in " ".join(decision.to_dict()["correct_path"])
