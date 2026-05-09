from __future__ import annotations

import sqlite3

from ystar.governance.aiden_adaptive_retrieval_planner_contract import (
    AIDEN_ADAPTIVE_RETRIEVAL_PLANNER_EVENT_TYPE,
    validate_aiden_adaptive_retrieval_planner_packet,
    validate_and_write_aiden_adaptive_retrieval_planner_packet,
)


def _valid_packet(task_type: str = "strategy") -> dict:
    market = task_type == "strategy"
    implementation = task_type == "implementation"
    families = [
        "repo_capability_evidence",
        "brain_provenance",
        "code_index_or_baseline",
        "CIEU_history",
        "long_term_memory_status",
    ]
    if market:
        families.extend(
            [
                "current_market_evidence_or_public_read_route",
                "competitor_and_substitute_evidence",
                "buyer_visible_value_evidence",
                "classical_theory_or_case_corpus",
            ]
        )
    if implementation:
        families.extend(["existing_code_paths", "tests_and_contracts", "delivery_boundary"])
    planned_sources = [
        "repo_evidence_index",
        "aiden_6d_brain",
        "code_index_or_capability_map",
        "cieu_store_history",
        "ystar_memory_store",
        "local_vector_rag",
        "e123_memory_asset_discovery",
    ]
    if market:
        planned_sources.extend(["external_public_read_runtime", "open_world_strategy_runtime"])
    return {
        "planner_id": "e126_test_planner",
        "task_context": {
            "agent_id": "Aiden",
            "owner_message": "Aiden, plan adaptive retrieval for this task.",
            "task_type": task_type,
            "planning_mode": "adaptive_evidence_need_and_capability_invocation",
            "market_strategy_required": market,
            "implementation_required": implementation,
            "unknown_problem_related": True,
        },
        "evidence_need_analysis": {
            "adaptive_analysis_performed": True,
            "required_evidence_families": families,
            "unknowns_to_resolve": ["which sources matter", "which existing capabilities must be reused"],
        },
        "governance_obligation_discovery": {
            "mechanism_id": "E101_adaptive_governance_correct_path",
            "discovery_performed": True,
            "required_obligations": ["external_observation_or_staleness_boundary", "new_governance_obligation_candidate"],
        },
        "existing_capability_recall": {
            "mechanism_id": "E113_no_new_wheel_runtime_law",
            "full_system_capability_scan_performed": True,
            "recent_memory_only": False,
            "runtime_active_capability_count": 12,
            "matched_capability_domains": ["aiden_brain_runtime", "cieu_store_formal_memory", "adaptive_governance_correct_path"],
        },
        "operating_pattern_selection": {
            "mechanism_id": "E119_operating_pattern_doctrine_registry",
            "selected_pattern_ids": [
                "no_new_wheel_preflight",
                "capability_utilization_sweep",
                "class_level_extrapolation_gate",
                "correct_path_navigation",
                "unknown_problem_learning_protocol",
            ],
        },
        "unknown_problem_learning_assessment": {
            "mechanism_id": "E120_unknown_problem_learning_protocol",
            "assessment_performed": True,
            "protocol_invocation_status": "invoked",
            "learning_objectives": ["classical_theory_canon", "peer_experience_corpus", "historical_case_corpus"],
        },
        "dynamic_retrieval_plan": {
            "plan_mode": "adaptive_dynamic_source_selection",
            "planned_source_ids": planned_sources,
            "source_selection_rationale": [
                {"source_id": "repo_evidence_index", "why": "local company doctrine"},
                {"source_id": "aiden_6d_brain", "why": "CEO brain provenance"},
            ],
        },
        "capability_invocation_plan": {
            "invocations": [
                _invocation("E101_adaptive_governance_correct_path"),
                _invocation("E113_no_new_wheel_runtime_law"),
                _invocation("E119_operating_pattern_doctrine_registry"),
                _invocation("E120_unknown_problem_learning_protocol"),
                _invocation("E125_retrieval_orchestration_runtime", status="will_invoke_after_validation"),
            ],
        },
        "retrieval_orchestration_binding": {
            "E125_bound": True,
            "execute_E125_after_planner_allow": True,
            "raw_answer_before_retrieval_allowed": False,
        },
        "self_improvement_path": {
            "new_capability_discovery_supported": True,
            "self_governance_proposal_on_gap": True,
            "direct_contract_mutation_allowed": False,
        },
        "CIEU_linkage": {
            "CIEU_recording_required": True,
            "target_event_type": AIDEN_ADAPTIVE_RETRIEVAL_PLANNER_EVENT_TYPE,
        },
        "truth_constraints": {
            "recent_memory_only": False,
            "fixed_retrieval_list_only": False,
            "adaptive_planning_bypassed": False,
            "no_new_wheel_bypassed": False,
            "unknown_problem_protocol_bypassed": False,
            "operating_pattern_registry_bypassed": False,
            "external_action_executed": False,
            "provider_action_executed": False,
            "customer_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "live_provider_execution_claim": False,
            "K9Audit_write_claim": False,
            "hidden_chain_of_thought_stored": False,
            "CIEU_recording_bypassed": False,
        },
    }


def _invocation(mechanism_id: str, status: str = "invoked") -> dict:
    return {
        "mechanism_id": mechanism_id,
        "invocation_status": status,
        "evidence_refs": [f"runtime://{mechanism_id}"],
        "output_summary": f"{mechanism_id} bound into adaptive retrieval planning.",
    }


def test_valid_adaptive_retrieval_planner_allows():
    decision = validate_aiden_adaptive_retrieval_planner_packet(_valid_packet()).to_dict()
    assert decision["decision"] == "ALLOW"
    assert "E125_retrieval_orchestration_runtime" in decision["guidance"]["required_mechanisms"]


def test_fixed_retrieval_list_only_denies():
    packet = _valid_packet()
    packet["truth_constraints"]["fixed_retrieval_list_only"] = True
    decision = validate_aiden_adaptive_retrieval_planner_packet(packet).to_dict()
    assert decision["decision"] == "DENY"
    assert "fixed_retrieval_list_only" in decision["violations"]


def test_missing_no_new_wheel_requires_revision():
    packet = _valid_packet()
    packet["existing_capability_recall"]["full_system_capability_scan_performed"] = False
    decision = validate_aiden_adaptive_retrieval_planner_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "existing_capability_recall"


def test_strategy_requires_public_read_or_open_world_source():
    packet = _valid_packet("strategy")
    packet["dynamic_retrieval_plan"]["planned_source_ids"] = [
        source for source in packet["dynamic_retrieval_plan"]["planned_source_ids"] if source not in {"external_public_read_runtime", "open_world_strategy_runtime"}
    ]
    decision = validate_aiden_adaptive_retrieval_planner_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "dynamic_retrieval_plan"


def test_unknown_problem_requires_e120_invocation():
    packet = _valid_packet()
    packet["unknown_problem_learning_assessment"]["protocol_invocation_status"] = "not_needed"
    decision = validate_aiden_adaptive_retrieval_planner_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "unknown_problem_learning_assessment"


def test_direct_contract_mutation_denies():
    packet = _valid_packet()
    packet["self_improvement_path"]["direct_contract_mutation_allowed"] = True
    decision = validate_aiden_adaptive_retrieval_planner_packet(packet).to_dict()
    assert decision["decision"] == "DENY"
    assert "direct_contract_mutation_allowed" in decision["violations"]


def test_write_cieustore_record(tmp_path):
    db = tmp_path / "e126_planner.db"
    result = validate_and_write_aiden_adaptive_retrieval_planner_packet(_valid_packet(), cieu_db=str(db))
    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT event_type, passed FROM cieu_events").fetchall()
    assert rows == [(AIDEN_ADAPTIVE_RETRIEVAL_PLANNER_EVENT_TYPE, 1)]
