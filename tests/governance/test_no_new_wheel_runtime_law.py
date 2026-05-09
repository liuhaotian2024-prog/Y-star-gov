from __future__ import annotations

import sqlite3

from ystar.governance.no_new_wheel_runtime_law import (
    NO_NEW_WHEEL_RUNTIME_LAW_EVENT_TYPE,
    validate_and_write_no_new_wheel_runtime_law_packet,
    validate_no_new_wheel_runtime_law_packet,
)


def _valid_packet() -> dict:
    domains = [
        "cieu_store_formal_memory",
        "adaptive_governance_correct_path",
        "czl_residual_loop_engine",
        "czl_message_protocol",
        "cieu_prediction_delta",
        "goal_tree_and_y_star_field",
        "ceo_implementation_order",
        "aiden_brain_runtime",
        "open_world_strategy_runtime",
    ]
    matches = [
        {
            "domain_id": domain,
            "runtime_status": "runtime_active",
            "source_paths": [f"canonical/{domain}.py"],
            "satisfies_mandatory_domain": True,
        }
        for domain in domains
    ]
    return {
        "runtime_law_id": "e113_no_new_wheel_runtime_law",
        "action_context": {
            "action_id": "e113_test_action",
            "owner_intent": "implement residual, goal, brain learning, market strategy without rebuilding existing CZL systems",
            "operation_type": "runtime_implementation",
            "major_action": True,
        },
        "repository_discovery": {
            "full_system_scan_performed": True,
            "repos_scanned": ["bridge-labs", "Y-star-gov", "gov-mcp"],
            "tracked_file_counts": {"bridge-labs": 1, "Y-star-gov": 1, "gov-mcp": 1},
            "recent_memory_only": False,
            "prompt_summary_only": False,
        },
        "capability_index_summary": {
            "total_capability_domains": len(domains),
            "source": "git_ls_files_plus_runtime_capability_map",
        },
        "capability_utilization_matrix": {
            "code_index_loaded": True,
            "indexed_capability_counts": {
                "total_tracked_files": 34677,
                "total_python_files": 3085,
                "total_functions": 11495,
                "total_classes": 1660,
            },
            "action_relevant_capability_groups": [
                {
                    "domain_id": domain,
                    "utilization_status": "runtime_bound",
                    "invocation_requirement": "mandatory",
                    "source_paths": [f"canonical/{domain}.py"],
                }
                for domain in domains
            ],
            "available_for_future_activation": [],
            "unreviewed_runtime_active_capability_count": 0,
        },
        "mandatory_capability_domains": domains,
        "semantic_capability_matches": matches,
        "reuse_plan": [
            {
                "domain_id": domain,
                "will_reuse_existing_capability": True,
                "reuse_mode": "reuse_or_extend_existing",
                "source_paths": [f"canonical/{domain}.py"],
            }
            for domain in domains
        ],
        "no_new_wheel_proof": {
            "existing_capability_recall_completed": True,
            "all_mandatory_domains_satisfied": True,
            "parallel_rebuild_detected": False,
            "recent_memory_sufficient": False,
            "prompt_summary_sufficient": False,
            "parallel_rebuild_allowed": False,
        },
        "CZL_closure": {
            "X_t": {"problem": "human reminder was previously needed to reuse CZL"},
            "U": ["scan repos", "match capabilities", "build reuse plan", "validate runtime law"],
            "Y_star": {"all_mandatory_domains_satisfied": True, "parallel_rebuild_detected": False},
            "Y_t_plus_1": {"all_mandatory_domains_satisfied": True, "parallel_rebuild_detected": False},
            "R_t_plus_1": 0,
            "residual_loop_engine_path": "ystar/governance/residual_loop_engine.py",
        },
        "truth_constraints": {
            "recent_memory_sufficient": False,
            "prompt_summary_sufficient": False,
            "parallel_rebuild_allowed": False,
            "customer_validation_claim": False,
            "pricing_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "L5_revenue_loop_complete": False,
            "K9Audit_integration_claim": False,
            "live_provider_execution_claim": False,
        },
    }


def test_valid_no_new_wheel_packet_allows_and_writes_cieu(tmp_path):
    packet = _valid_packet()
    decision = validate_no_new_wheel_runtime_law_packet(packet)
    assert decision.to_dict()["decision"] == "ALLOW"

    db = tmp_path / "cieu.db"
    result = validate_and_write_no_new_wheel_runtime_law_packet(packet, cieu_db=str(db), session_id="e113_test")
    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT event_type, decision FROM cieu_events").fetchone()
    assert row == (NO_NEW_WHEEL_RUNTIME_LAW_EVENT_TYPE, "ALLOW")


def test_missing_czl_for_residual_task_requires_revision():
    packet = _valid_packet()
    packet["mandatory_capability_domains"].remove("czl_residual_loop_engine")
    decision = validate_no_new_wheel_runtime_law_packet(packet)
    assert decision.to_dict()["decision"] == "REQUIRE_REVISION"
    assert "residual_loop_engine" in " ".join(decision.to_dict()["correct_path"])


def test_recent_memory_only_is_denied():
    packet = _valid_packet()
    packet["repository_discovery"]["recent_memory_only"] = True
    decision = validate_no_new_wheel_runtime_law_packet(packet)
    assert decision.to_dict()["decision"] == "DENY"


def test_parallel_rebuild_is_denied():
    packet = _valid_packet()
    packet["reuse_plan"][0]["reuse_mode"] = "new_parallel_system"
    decision = validate_no_new_wheel_runtime_law_packet(packet)
    assert decision.to_dict()["decision"] == "DENY"


def test_nonzero_rt_requires_revision():
    packet = _valid_packet()
    packet["CZL_closure"]["R_t_plus_1"] = 0.25
    decision = validate_no_new_wheel_runtime_law_packet(packet)
    assert decision.to_dict()["decision"] == "REQUIRE_REVISION"
    assert "R_t_plus_1 is 0" in " ".join(decision.to_dict()["correct_path"])


def test_missing_repo_scan_requires_revision():
    packet = _valid_packet()
    packet["repository_discovery"]["repos_scanned"] = ["bridge-labs", "Y-star-gov"]
    decision = validate_no_new_wheel_runtime_law_packet(packet)
    assert decision.to_dict()["decision"] == "REQUIRE_REVISION"
    assert "gov-mcp" in " ".join(decision.to_dict()["correct_path"])


def test_missing_capability_utilization_matrix_requires_revision():
    packet = _valid_packet()
    packet.pop("capability_utilization_matrix")
    decision = validate_no_new_wheel_runtime_law_packet(packet)
    assert decision.to_dict()["decision"] == "REQUIRE_REVISION"
    assert "capability_utilization_matrix" in " ".join(decision.to_dict()["correct_path"])


def test_mandatory_domain_missing_from_utilization_matrix_requires_revision():
    packet = _valid_packet()
    packet["capability_utilization_matrix"]["action_relevant_capability_groups"] = [
        row
        for row in packet["capability_utilization_matrix"]["action_relevant_capability_groups"]
        if row["domain_id"] != "czl_residual_loop_engine"
    ]
    decision = validate_no_new_wheel_runtime_law_packet(packet)
    assert decision.to_dict()["decision"] == "REQUIRE_REVISION"
    assert "residual_loop_engine" in " ".join(decision.to_dict()["correct_path"])
