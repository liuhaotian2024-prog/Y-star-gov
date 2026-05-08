from __future__ import annotations

import sqlite3

from ystar.governance.ceo_codex_executor_contract import (
    CODEX_HANDOFF_PROMPT_EVENT_TYPE,
    CEO_IMPLEMENTATION_ORDER_EVENT_TYPE,
    validate_and_write_codex_handoff_prompt_generation,
    validate_and_write_ceo_implementation_order,
    validate_and_write_ceo_post_codex_residual,
    validate_and_write_codex_execution_receipt,
    validate_codex_handoff_prompt_generation,
    validate_ceo_implementation_order,
    validate_codex_execution_receipt,
)


def _valid_order() -> dict:
    return {
        "artifact_id": "CEOImplementationOrder",
        "order_id": "order_e92_test",
        "source_owner_intent": "Implement the scoped executor-boundary feature.",
        "CEO_decision_actor": "bridge_labs_ceo",
        "executor_actor": "Codex",
        "selected_strategy": "close CEO-principal/Codex-executor boundary",
        "selected_action": "add deterministic order and receipt validation",
        "why_this_action": "It prevents Codex from self-authorizing strategy.",
        "why_not_alternatives": ["do not let Codex infer strategy from owner prompt"],
        "evidence_refs": ["bridge-labs:operations/baseline/e87r_full_repo_baseline/baseline_summary.json"],
        "YstarGov_validation_required": True,
        "CIEU_prediction": {"X_t": "gap exists", "U_t": "add boundary", "Y_star_t": "executor constrained"},
        "allowed_repos": ["bridge-labs", "Y-star-gov"],
        "allowed_paths": ["office/mission_command/e92_*.py", "ystar/governance/ceo_codex_executor_contract.py"],
        "likely_files_to_modify": ["office/mission_command/e92_ceo_principal_codex_executor_boundary.py"],
        "forbidden_repos": ["K9Audit", "ystar-company"],
        "forbidden_paths": [".env", "customer_data/"],
        "forbidden_actions": ["external_action", "provider_live_execution", "strategy_change_by_codex"],
        "owner_approval_boundary": {"external_action_allowed": False, "owner_approval_state": "not_approved"},
        "L_level_boundary": {"L5-D": "absent_or_not_executed"},
        "external_action_allowed": False,
        "gov_mcp_required": False,
        "K9Audit_boundary": "read_only_not_integrated",
        "tests_required": ["pytest -q tests/office/test_e92_ceo_principal_codex_executor_boundary.py"],
        "validation_commands": ["python3 -m py_compile touched_files"],
        "completion_criteria": ["order, receipt, residual CIEU records written"],
        "required_report_format": "E92 final response format",
        "required_codex_receipt_fields": ["linked_order_id", "tests_run", "commits"],
        "deviation_policy": "return ESCALATE receipt for strategy/scope change",
        "escalation_policy": "return to CEO principal",
        "post_action_residual_required": True,
        "no_overclaim_policy": True,
        "no_hidden_chain_of_thought_policy": True,
    }


def _valid_receipt() -> dict:
    return {
        "artifact_id": "CodexExecutionReceipt",
        "receipt_id": "receipt_e92_test",
        "linked_order_id": "order_e92_test",
        "executor_actor": "Codex",
        "execution_status": "completed",
        "repos_read": ["bridge-labs", "Y-star-gov"],
        "repos_modified": ["bridge-labs", "Y-star-gov"],
        "files_changed": ["office/mission_command/e92_ceo_principal_codex_executor_boundary.py"],
        "tests_run": ["pytest -q tests/office/test_e92_ceo_principal_codex_executor_boundary.py"],
        "test_results": {"passed": 10, "failed": 0},
        "commits": [{"repo": "bridge-labs", "hash": "abc123"}],
        "remote_push_status": "remote_confirmed",
        "deviations_from_order": [],
        "unexpected_blockers": [],
        "strategy_changed_by_codex": False,
        "scope_expanded_by_codex": False,
        "external_action_executed": False,
        "provider_action_executed": False,
        "customer_or_payment_claim_made": False,
        "overclaim_detected": False,
        "CIEU_write_status": "order_receipt_residual_written",
        "recommended_next_action": "CEO residual learning",
        "residual_observations": ["implementation stayed inside order"],
    }


def _valid_residual() -> dict:
    return {
        "artifact_id": "CEOPostCodexResidual",
        "residual_id": "residual_e92_test",
        "linked_order_id": "order_e92_test",
        "linked_receipt_id": "receipt_e92_test",
        "CEO_decision_actor": "bridge_labs_ceo",
        "executor_actor": "Codex",
        "expected_outcome": "Codex implements only the ordered boundary.",
        "actual_outcome": "Codex returned compliant receipt.",
        "deviation_analysis": {"deviations": []},
        "learning_update": "CEO can now treat implementation work as receipt-backed execution.",
        "next_ceo_recommendation": "Use CEOImplementationOrder before future engineering work.",
        "CIEU_record": {"X_t": "order issued", "U_t": "Codex executed", "Y_t_plus_1": "receipt returned"},
        "no_external_action_executed": True,
        "no_customer_revenue_payment_claim": True,
    }


def _valid_prompt_request(order_write: dict | None = None) -> dict:
    if order_write is None:
        order_write = {
            "governance_decision": {"decision": "ALLOW"},
            "formal_CIEU_log_written": True,
            "CIEU_write_result": {
                "event_type": CEO_IMPLEMENTATION_ORDER_EVENT_TYPE,
                "event_id": "event_order_prompt_test",
            },
        }
    return {
        "artifact_id": "CodexHandoffPromptGenerationRequest",
        "prompt_request_id": "prompt_request_e92_test",
        "linked_order_id": "order_e92_test",
        "source_prompt_type": "CEOImplementationOrder",
        "order_validation_result": order_write,
        "YstarGov_order_validation_required": True,
        "CIEUStore_order_write_required": True,
        "prompt_generation_after_cieu_write_required": True,
        "raw_natural_language_prompt_used": False,
    }


def test_valid_ceo_implementation_order_allow():
    assert validate_ceo_implementation_order(_valid_order()).to_dict()["decision"] == "ALLOW"


def test_missing_selected_action_requires_revision():
    order = _valid_order()
    order.pop("selected_action")
    decision = validate_ceo_implementation_order(order).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_field"] == "selected_action"


def test_missing_evidence_requires_revision():
    order = _valid_order()
    order["evidence_refs"] = []
    decision = validate_ceo_implementation_order(order).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_field"] == "evidence_refs"


def test_codex_changing_strategy_escalates():
    receipt = _valid_receipt()
    receipt["strategy_changed_by_codex"] = True
    decision = validate_codex_execution_receipt(receipt).to_dict()
    assert decision["decision"] == "ESCALATE"


def test_codex_expanding_scope_escalates():
    receipt = _valid_receipt()
    receipt["scope_expanded_by_codex"] = True
    decision = validate_codex_execution_receipt(receipt).to_dict()
    assert decision["decision"] == "ESCALATE"


def test_external_action_without_approval_denies():
    receipt = _valid_receipt()
    receipt["external_action_executed"] = True
    decision = validate_codex_execution_receipt(receipt).to_dict()
    assert decision["decision"] == "DENY"


def test_false_revenue_customer_payment_claim_denies():
    receipt = _valid_receipt()
    receipt["customer_or_payment_claim_made"] = True
    decision = validate_codex_execution_receipt(receipt).to_dict()
    assert decision["decision"] == "DENY"


def test_valid_receipt_allow():
    assert validate_codex_execution_receipt(_valid_receipt()).to_dict()["decision"] == "ALLOW"


def test_valid_codex_prompt_generation_requires_validated_written_order():
    decision = validate_codex_handoff_prompt_generation(_valid_prompt_request()).to_dict()

    assert decision["decision"] == "ALLOW"


def test_raw_natural_language_prompt_without_order_denies():
    request = {
        "artifact_id": "CodexHandoffPromptGenerationRequest",
        "prompt_request_id": "raw_prompt",
        "source_prompt_type": "raw_natural_language",
        "raw_natural_language_prompt_used": True,
    }

    decision = validate_codex_handoff_prompt_generation(request).to_dict()
    assert decision["decision"] == "DENY"
    assert decision["failed_field"] == "raw_natural_language_prompt_used"


def test_prompt_generation_without_cieustore_order_write_requires_revision():
    request = _valid_prompt_request(
        {
            "governance_decision": {"decision": "ALLOW"},
            "formal_CIEU_log_written": False,
            "CIEU_write_result": {"event_type": CEO_IMPLEMENTATION_ORDER_EVENT_TYPE},
        }
    )

    decision = validate_codex_handoff_prompt_generation(request).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_field"] == "formal_CIEU_log_written"


def test_prompt_generation_decision_writes_cieustore_record(tmp_path):
    db = str(tmp_path / "e92_prompt_governance.db")
    order_write = validate_and_write_ceo_implementation_order(_valid_order(), cieu_db=db, session_id="e92_prompt_test")
    prompt_write = validate_and_write_codex_handoff_prompt_generation(
        _valid_prompt_request(order_write),
        cieu_db=db,
        session_id="e92_prompt_test",
    )

    assert prompt_write["governance_decision"]["decision"] == "ALLOW"
    assert prompt_write["formal_CIEU_log_written"] is True
    assert prompt_write["CIEU_write_result"]["event_type"] == CODEX_HANDOFF_PROMPT_EVENT_TYPE


def test_cieustore_writer_works_for_order_receipt_and_residual(tmp_path):
    db = str(tmp_path / "e92_codex_executor.db")
    order_write = validate_and_write_ceo_implementation_order(_valid_order(), cieu_db=db, session_id="e92_test")
    receipt_write = validate_and_write_codex_execution_receipt(_valid_receipt(), cieu_db=db, session_id="e92_test")
    residual_write = validate_and_write_ceo_post_codex_residual(_valid_residual(), cieu_db=db, session_id="e92_test", seal_session=True)

    assert order_write["governance_decision"]["decision"] == "ALLOW"
    assert receipt_write["governance_decision"]["decision"] == "ALLOW"
    assert residual_write["governance_decision"]["decision"] == "ALLOW"
    assert residual_write["CIEU_write_result"]["verify_result"]["valid"] is True

    with sqlite3.connect(db) as conn:
        count = conn.execute("select count(*) from cieu_events where session_id='e92_test'").fetchone()[0]
    assert count == 3
