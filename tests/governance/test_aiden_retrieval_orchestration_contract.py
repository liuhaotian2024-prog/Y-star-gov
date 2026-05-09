from __future__ import annotations

import sqlite3

from ystar.governance.aiden_retrieval_orchestration_contract import (
    AIDEN_RETRIEVAL_ORCHESTRATION_EVENT_TYPE,
    validate_aiden_retrieval_orchestration_packet,
    validate_and_write_aiden_retrieval_orchestration_packet,
)


def _source(source_id: str, *, count: int = 1, status: str = "queried") -> dict:
    return {
        "source_id": source_id,
        "retrieval_status": status,
        "evidence_count": count,
        "evidence_refs": [f"{source_id}:ref"] if count else [],
        "correct_path": [] if status == "queried" else [f"configure {source_id}"],
        "unavailable_reason": "" if status == "queried" else f"{source_id} unavailable in test",
    }


def _valid_packet() -> dict:
    sources = [
        _source("repo_evidence_index", count=2),
        _source("aiden_6d_brain", count=2),
        _source("code_index_or_capability_map", count=1),
        _source("cieu_store_history", count=1),
        _source("ystar_memory_store", count=0, status="unavailable_declared"),
        _source("local_vector_rag", count=0, status="not_configured"),
    ]
    evidence = [
        {"source_id": "repo_evidence_index", "evidence_ref": "repo:AGENTS.md", "summary": "Company mission and M-triangle.", "runtime_status": "retrieved"},
        {"source_id": "aiden_6d_brain", "evidence_ref": "brain:node1", "summary": "Aiden brain activation on governance.", "runtime_status": "retrieved"},
        {"source_id": "code_index_or_capability_map", "evidence_ref": "baseline:code_index", "summary": "E87R baseline code/capability map.", "runtime_status": "retrieved"},
        {"source_id": "cieu_store_history", "evidence_ref": "cieu:recent", "summary": "Recent CIEU history for Aiden answers.", "runtime_status": "retrieved"},
        {"source_id": "repo_evidence_index", "evidence_ref": "repo:WORK_METHODOLOGY.md", "summary": "Search before build/no-new-wheel method.", "runtime_status": "retrieved"},
    ]
    return {
        "retrieval_id": "e125_test_retrieval",
        "task_context": {
            "agent_id": "Aiden",
            "owner_message": "Aiden, answer with retrieved context.",
            "task_type": "ceo_meeting_answer",
            "major_action": True,
            "high_wisdom_required": True,
            "generation_mode": "retrieval_orchestrated_structured_output",
        },
        "retrieval_plan": {
            "retrieval_required_before_answer": True,
            "mandatory_source_ids": [
                "repo_evidence_index",
                "aiden_6d_brain",
                "code_index_or_capability_map",
                "cieu_store_history",
                "ystar_memory_store",
                "local_vector_rag",
            ],
            "recent_memory_only_allowed": False,
        },
        "retrieval_sources": sources,
        "retrieved_evidence_pack": {
            "evidence_items": evidence,
            "human_summary": "Retrieved repo, brain, baseline, and CIEU context before answer.",
        },
        "source_coverage": {
            "queried_source_ids": [source["source_id"] for source in sources],
            "satisfied_source_family_count": 4,
            "unavailable_source_ids": ["ystar_memory_store", "local_vector_rag"],
        },
        "sufficiency_assessment": {
            "sufficient_for_answer": True,
            "recent_memory_only": False,
            "minimum_evidence_items_required": 5,
            "actual_evidence_items": len(evidence),
            "correct_path": [],
        },
        "downstream_binding": {
            "retrieval_required_before_aiden_answer": True,
            "retrieved_context_bound_to_answer": True,
            "raw_prompt_to_codex_allowed": False,
        },
        "CIEU_linkage": {
            "CIEU_recording_required": True,
            "target_event_type": AIDEN_RETRIEVAL_ORCHESTRATION_EVENT_TYPE,
        },
        "truth_constraints": {
            "recent_memory_only": False,
            "raw_natural_language_only_answer": False,
            "retrieval_bypassed": False,
            "static_template_only": False,
            "external_web_research_claim_without_provider": False,
            "customer_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "live_provider_execution_claim": False,
            "K9Audit_write_claim": False,
            "hidden_chain_of_thought_stored": False,
            "CIEU_recording_bypassed": False,
        },
    }


def test_valid_retrieval_orchestration_allows():
    decision = validate_aiden_retrieval_orchestration_packet(_valid_packet()).to_dict()
    assert decision["decision"] == "ALLOW"
    assert decision["guidance"]["evidence_count"] == 5


def test_missing_mandatory_source_requires_revision():
    packet = _valid_packet()
    packet["retrieval_sources"] = [source for source in packet["retrieval_sources"] if source["source_id"] != "aiden_6d_brain"]
    decision = validate_aiden_retrieval_orchestration_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "retrieval_sources"
    assert any("aiden_6d_brain" in step for step in decision["correct_path"])


def test_recent_memory_only_denies():
    packet = _valid_packet()
    packet["truth_constraints"]["recent_memory_only"] = True
    decision = validate_aiden_retrieval_orchestration_packet(packet).to_dict()
    assert decision["decision"] == "DENY"
    assert "recent_memory_only" in decision["violations"]


def test_sparse_evidence_requires_revision():
    packet = _valid_packet()
    packet["retrieved_evidence_pack"]["evidence_items"] = packet["retrieved_evidence_pack"]["evidence_items"][:2]
    decision = validate_aiden_retrieval_orchestration_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "retrieved_evidence_pack"


def test_false_customer_revenue_payment_claim_denies():
    packet = _valid_packet()
    packet["truth_constraints"]["revenue_claim"] = True
    decision = validate_aiden_retrieval_orchestration_packet(packet).to_dict()
    assert decision["decision"] == "DENY"
    assert "revenue_claim" in decision["violations"]


def test_unavailable_source_must_have_navigation():
    packet = _valid_packet()
    for source in packet["retrieval_sources"]:
        if source["source_id"] == "local_vector_rag":
            source["correct_path"] = []
            source["unavailable_reason"] = ""
    decision = validate_aiden_retrieval_orchestration_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "retrieval_sources"


def test_write_cieustore_record(tmp_path):
    db = tmp_path / "e125_retrieval.db"
    result = validate_and_write_aiden_retrieval_orchestration_packet(_valid_packet(), cieu_db=str(db))
    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT event_type, passed FROM cieu_events").fetchall()
    assert rows == [(AIDEN_RETRIEVAL_ORCHESTRATION_EVENT_TYPE, 1)]
