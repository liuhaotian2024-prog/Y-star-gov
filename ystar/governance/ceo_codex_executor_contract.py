"""Deterministic governance for the CEO-principal / Codex-executor boundary.

CEO strategy belongs to the bridge-labs CEO behavior center. Codex is an
engineering executor and may only work from a CEOImplementationOrder that has
passed Y-star-gov validation. This module validates the order, validates the
CodexExecutionReceipt returned after work, and writes each decision through the
existing CIEUStore path. It does not execute tools, call providers, or create a
parallel ledger.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


CEO_IMPLEMENTATION_ORDER_EVENT_TYPE = "CEO_IMPLEMENTATION_ORDER_DECISION"
CODEX_EXECUTION_RECEIPT_EVENT_TYPE = "CODEX_EXECUTION_RECEIPT_DECISION"
CEO_POST_CODEX_RESIDUAL_EVENT_TYPE = "CEO_POST_CODEX_RESIDUAL_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"


class CEOCodexExecutorDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOCodexExecutorDecision:
    decision: CEOCodexExecutorDecisionValue
    reason: str
    failed_field: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_codex_executor_governance_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOCodexExecutorDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_field": self.failed_field,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


ORDER_REQUIRED_FIELDS: tuple[str, ...] = (
    "order_id",
    "source_owner_intent",
    "CEO_decision_actor",
    "executor_actor",
    "selected_strategy",
    "selected_action",
    "why_this_action",
    "why_not_alternatives",
    "evidence_refs",
    "YstarGov_validation_required",
    "CIEU_prediction",
    "allowed_repos",
    "allowed_paths",
    "forbidden_actions",
    "owner_approval_boundary",
    "L_level_boundary",
    "tests_required",
    "completion_criteria",
    "required_codex_receipt_fields",
    "deviation_policy",
    "escalation_policy",
    "post_action_residual_required",
    "no_overclaim_policy",
    "no_hidden_chain_of_thought_policy",
)

RECEIPT_REQUIRED_FIELDS: tuple[str, ...] = (
    "receipt_id",
    "linked_order_id",
    "executor_actor",
    "execution_status",
    "repos_read",
    "repos_modified",
    "files_changed",
    "tests_run",
    "test_results",
    "commits",
    "remote_push_status",
    "deviations_from_order",
    "strategy_changed_by_codex",
    "scope_expanded_by_codex",
    "external_action_executed",
    "provider_action_executed",
    "customer_or_payment_claim_made",
    "overclaim_detected",
    "CIEU_write_status",
    "recommended_next_action",
    "residual_observations",
)

POST_CODEX_RESIDUAL_REQUIRED_FIELDS: tuple[str, ...] = (
    "residual_id",
    "linked_order_id",
    "linked_receipt_id",
    "CEO_decision_actor",
    "executor_actor",
    "expected_outcome",
    "actual_outcome",
    "deviation_analysis",
    "learning_update",
    "next_ceo_recommendation",
    "CIEU_record",
    "no_external_action_executed",
    "no_customer_revenue_payment_claim",
)

FORBIDDEN_CLAIM_KEYS: tuple[str, ...] = (
    "customer_validation_claim",
    "revenue_claim",
    "payment_claim",
    "paid_signal_claim",
    "pricing_validation_claim",
    "L4_feedback_executed",
    "L5_revenue_loop_complete",
    "production_deployment_claim",
    "K9Audit_integration_claim",
)


def build_ceo_codex_executor_contract() -> dict[str, Any]:
    return {
        "contract_id": "ceo_principal_codex_executor_boundary_v1",
        "decision_values": ["ALLOW", "REQUIRE_REVISION", "DENY", "ESCALATE"],
        "principal_actor": "bridge_labs_ceo",
        "executor_actor": "Codex",
        "event_types": [
            CEO_IMPLEMENTATION_ORDER_EVENT_TYPE,
            CODEX_EXECUTION_RECEIPT_EVENT_TYPE,
            CEO_POST_CODEX_RESIDUAL_EVENT_TYPE,
        ],
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "private_chain_of_thought_policy": "structured_outputs_only_no_hidden_chain_of_thought",
    }


def validate_ceo_implementation_order(order: Mapping[str, Any]) -> CEOCodexExecutorDecision:
    if not isinstance(order, Mapping):
        return _decision("DENY", "CEOImplementationOrder must be a mapping", {}, "order_schema")
    missing = [field for field in ORDER_REQUIRED_FIELDS if not _present(order.get(field))]
    if missing:
        return _revision(
            "CEOImplementationOrder is missing required fields",
            order,
            missing[0],
            [f"fill required order fields: {', '.join(missing[:12])}"],
        )
    if str(order.get("executor_actor")) != "Codex":
        return _decision("DENY", "executor_actor must be Codex", order, "executor_actor", ["executor_not_codex"])
    if str(order.get("CEO_decision_actor")).lower() in {"codex", "executor"}:
        return _decision("DENY", "Codex may not be the CEO decision actor", order, "CEO_decision_actor", ["codex_as_ceo"])
    if _forbidden_claim(order):
        return _decision("DENY", f"forbidden completion claim present: {_forbidden_claim(order)}", order, "overclaim", [_forbidden_claim(order)])
    if order.get("YstarGov_validation_required") is not True:
        return _revision("YstarGov_validation_required must be true", order, "YstarGov_validation_required", ["set YstarGov_validation_required=true"])
    if order.get("post_action_residual_required") is not True:
        return _revision("post_action_residual_required must be true", order, "post_action_residual_required", ["set post_action_residual_required=true"])
    if order.get("no_hidden_chain_of_thought_policy") is not True:
        return _decision("DENY", "hidden chain-of-thought storage is forbidden", order, "no_hidden_chain_of_thought_policy", ["hidden_chain_of_thought_policy_missing"])
    if order.get("no_overclaim_policy") is not True:
        return _revision("no_overclaim_policy must be true", order, "no_overclaim_policy", ["set no_overclaim_policy=true"])
    if order.get("external_action_allowed") is True and order.get("owner_approval_state") != "approved":
        return _decision("DENY", "external action cannot be allowed without explicit owner approval", order, "external_action_allowed", ["external_action_without_owner_approval"])
    if not _as_list(order.get("allowed_repos")) or not _as_list(order.get("allowed_paths")):
        return _revision("allowed repos and paths are required", order, "allowed_scope", ["declare allowed_repos and allowed_paths"])
    if not _as_list(order.get("tests_required")):
        return _revision("tests_required cannot be empty", order, "tests_required", ["declare tests required for Codex executor"])
    return _decision("ALLOW", "CEOImplementationOrder satisfies CEO-principal/Codex-executor contract", order)


def validate_codex_execution_receipt(receipt: Mapping[str, Any]) -> CEOCodexExecutorDecision:
    if not isinstance(receipt, Mapping):
        return _decision("DENY", "CodexExecutionReceipt must be a mapping", {}, "receipt_schema")
    if not _present(receipt.get("linked_order_id")):
        return _decision("DENY", "CodexExecutionReceipt must link to CEOImplementationOrder", receipt, "linked_order_id", ["linked_order_id_missing"])
    missing = [field for field in RECEIPT_REQUIRED_FIELDS if field not in receipt]
    if missing:
        return _revision("CodexExecutionReceipt is missing required fields", receipt, missing[0], [f"fill receipt fields: {', '.join(missing[:12])}"])
    if str(receipt.get("executor_actor")) != "Codex":
        return _decision("DENY", "receipt executor_actor must be Codex", receipt, "executor_actor", ["executor_not_codex"])
    if receipt.get("strategy_changed_by_codex") is True:
        return _escalate("Codex changed strategy and must return to CEO principal", receipt, "strategy_changed_by_codex")
    if receipt.get("scope_expanded_by_codex") is True:
        return _escalate("Codex expanded scope and must return to CEO principal", receipt, "scope_expanded_by_codex")
    if receipt.get("external_action_executed") is True and receipt.get("external_action_approved_by_order") is not True:
        return _decision("DENY", "Codex executed external action without order approval", receipt, "external_action_executed", ["external_action_without_approval"])
    if receipt.get("provider_action_executed") is True and receipt.get("gov_mcp_approval") is not True:
        return _decision("DENY", "Codex/provider action executed without gov-mcp approval", receipt, "provider_action_executed", ["provider_action_without_gov_mcp_approval"])
    if receipt.get("customer_or_payment_claim_made") is True or receipt.get("overclaim_detected") is True or _forbidden_claim(receipt):
        return _decision("DENY", "receipt contains forbidden customer/revenue/payment/L5 claim", receipt, "overclaim", ["forbidden_claim"])
    if not _as_list(receipt.get("tests_run")) or not _present(receipt.get("test_results")):
        return _revision("Codex receipt must include tests_run and test_results", receipt, "tests_run", ["run required tests or return blocked/require_revision"])
    if receipt.get("execution_status") == "completed" and not _as_list(receipt.get("commits")):
        return _revision("completed Codex receipt requires commit evidence", receipt, "commits", ["commit canonical repo changes or mark status blocked/partial"])
    return _decision("ALLOW", "CodexExecutionReceipt satisfies executor boundary contract", receipt)


def validate_ceo_post_codex_residual(residual: Mapping[str, Any]) -> CEOCodexExecutorDecision:
    if not isinstance(residual, Mapping):
        return _decision("DENY", "CEO post-Codex residual must be a mapping", {}, "residual_schema")
    missing = [field for field in POST_CODEX_RESIDUAL_REQUIRED_FIELDS if not _present(residual.get(field))]
    if missing:
        return _revision("CEO post-Codex residual is missing required fields", residual, missing[0], [f"fill residual fields: {', '.join(missing[:12])}"])
    if str(residual.get("CEO_decision_actor")).lower() in {"codex", "executor"}:
        return _decision("DENY", "Codex may not author CEO residual learning", residual, "CEO_decision_actor", ["codex_as_ceo_residual"])
    if residual.get("executor_actor") != "Codex":
        return _revision("post-Codex residual must identify Codex as executor", residual, "executor_actor", ["set executor_actor=Codex"])
    if residual.get("no_external_action_executed") is not True:
        return _decision("DENY", "post-Codex residual indicates external action occurred", residual, "no_external_action_executed", ["external_action_forbidden"])
    if residual.get("no_customer_revenue_payment_claim") is not True or _forbidden_claim(residual):
        return _decision("DENY", "post-Codex residual contains forbidden customer/revenue/payment claim", residual, "overclaim", ["forbidden_claim"])
    return _decision("ALLOW", "CEO post-Codex residual satisfies executor-boundary learning contract", residual)


def build_ceo_codex_executor_cieu_record(
    payload: Mapping[str, Any],
    decision: CEOCodexExecutorDecision | Mapping[str, Any],
    *,
    event_type: str,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, CEOCodexExecutorDecision) else dict(decision)
    decision_value = str(decision_data.get("decision") or "DENY")
    payload_id = str(payload.get("order_id") or payload.get("receipt_id") or payload.get("residual_id") or "unknown")
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(payload.get("session_id") or "ceo_codex_executor_boundary"),
        "agent_id": str(payload.get("CEO_decision_actor") or payload.get("executor_actor") or "bridge_labs_ceo"),
        "event_type": event_type,
        "decision": _decision_to_cieu_decision(decision_value),
        "passed": decision_value == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_value != "ALLOW",
        "drift_details": None if decision_value == "ALLOW" else decision_data.get("reason"),
        "task_description": f"CEO-Codex executor boundary decision for {payload_id}",
        "contract_hash": "ceo-principal-codex-executor-boundary-v1",
        "params": {
            "payload_id": payload_id,
            "payload_artifact_id": payload.get("artifact_id"),
            "linked_order_id": payload.get("linked_order_id") or payload.get("order_id"),
            "executor_actor": payload.get("executor_actor"),
            "CEO_decision_actor": payload.get("CEO_decision_actor"),
        },
        "result": {
            "decision": decision_value,
            "reason": decision_data.get("reason"),
            "failed_field": decision_data.get("failed_field"),
            "correct_path": list(decision_data.get("correct_path") or [])[:10],
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": payload.get("human_initiator") or "owner",
        "lineage_path": ["owner", "bridge-labs CEO", "Y-star-gov", "Codex", "bridge-labs CEO", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_value == "ALLOW",
    }


def write_ceo_codex_executor_cieu_record(
    payload: Mapping[str, Any],
    decision: CEOCodexExecutorDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    event_type: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    if not cieu_db:
        raise ValueError("cieu_db is required")
    record = build_ceo_codex_executor_cieu_record(payload, decision, event_type=event_type, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_codex_executor_formal_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "formal_CIEU_log_module": "ystar.governance.ceo_codex_executor_contract",
        "formal_CIEU_log_function": "write_ceo_codex_executor_cieu_record",
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_implementation_order(
    order: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_implementation_order(order)
    write_result = write_ceo_codex_executor_cieu_record(
        order,
        decision,
        cieu_db=cieu_db,
        event_type=CEO_IMPLEMENTATION_ORDER_EVENT_TYPE,
        session_id=session_id,
        seal_session=seal_session,
    )
    return _validate_write_result("ceo_implementation_order_validate_and_write_result", decision, write_result)


def validate_and_write_codex_execution_receipt(
    receipt: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_codex_execution_receipt(receipt)
    write_result = write_ceo_codex_executor_cieu_record(
        receipt,
        decision,
        cieu_db=cieu_db,
        event_type=CODEX_EXECUTION_RECEIPT_EVENT_TYPE,
        session_id=session_id,
        seal_session=seal_session,
    )
    return _validate_write_result("codex_execution_receipt_validate_and_write_result", decision, write_result)


def validate_and_write_ceo_post_codex_residual(
    residual: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_post_codex_residual(residual)
    write_result = write_ceo_codex_executor_cieu_record(
        residual,
        decision,
        cieu_db=cieu_db,
        event_type=CEO_POST_CODEX_RESIDUAL_EVENT_TYPE,
        session_id=session_id,
        seal_session=seal_session,
    )
    return _validate_write_result("ceo_post_codex_residual_validate_and_write_result", decision, write_result)


def _validate_write_result(artifact_id: str, decision: CEOCodexExecutorDecision, write_result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": dict(write_result),
        "formal_CIEU_log_written": bool(write_result.get("formal_CIEU_log_written")),
        "formal_CIEU_log_status": write_result.get("formal_CIEU_log_status"),
        "validator_output_status": write_result.get("validator_output_status"),
        "formal_CIEU_log_path": write_result.get("formal_CIEU_log_path"),
    }


def _decision(
    value: str,
    reason: str,
    payload: Mapping[str, Any],
    failed_field: str | None = None,
    violations: list[str] | None = None,
    *,
    guidance: dict[str, Any] | None = None,
    correct_path: list[str] | None = None,
    requires_owner_decision: bool = False,
) -> CEOCodexExecutorDecision:
    decision_value = CEOCodexExecutorDecisionValue(value)
    provisional = CEOCodexExecutorDecision(
        decision=decision_value,
        reason=reason,
        failed_field=failed_field,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
    )
    return CEOCodexExecutorDecision(
        decision=decision_value,
        reason=reason,
        failed_field=failed_field,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
        cieu_validation_record={
            "payload_artifact_id": payload.get("artifact_id"),
            "decision": provisional.to_dict(),
            "validator": "ystar.governance.ceo_codex_executor_contract",
            "validator_output_status": "CIEU_validation_record_candidate",
        },
    )


def _revision(reason: str, payload: Mapping[str, Any], failed_field: str, correct_path: list[str]) -> CEOCodexExecutorDecision:
    return _decision(
        "REQUIRE_REVISION",
        reason,
        payload,
        failed_field,
        [failed_field],
        guidance={"guidance_type": "correct_path", "required_changes": correct_path},
        correct_path=correct_path,
    )


def _escalate(reason: str, payload: Mapping[str, Any], failed_field: str) -> CEOCodexExecutorDecision:
    return _decision(
        "ESCALATE",
        reason,
        payload,
        failed_field,
        [failed_field],
        guidance={"owner_decision_path": "return to CEO principal; do not continue execution"},
        correct_path=["stop Codex execution", "return receipt to CEO principal", "generate revised CEOImplementationOrder if strategy/scope changes"],
        requires_owner_decision=True,
    )


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _forbidden_claim(payload: Mapping[str, Any]) -> str:
    for field in FORBIDDEN_CLAIM_KEYS:
        if payload.get(field) is True:
            return field
    for nested_key in ("overclaim_boundary", "truth_constraints", "claims", "safety_statement"):
        nested = payload.get(nested_key)
        if isinstance(nested, Mapping):
            for field in FORBIDDEN_CLAIM_KEYS:
                if nested.get(field) is True:
                    return field
    text = _text(payload)
    for phrase in (
        "customer validation complete",
        "customer validation achieved",
        "revenue achieved",
        "payment complete",
        "paid signal achieved",
        "pricing validation complete",
        "l5-d complete",
        "l5 revenue loop complete",
    ):
        if phrase in text:
            return phrase
    return ""


def _decision_to_cieu_decision(value: str) -> str:
    return {
        "ALLOW": "allow",
        "REQUIRE_REVISION": "rewrite",
        "DENY": "deny",
        "ESCALATE": "escalate",
    }.get(value, "unknown")


def _text(value: Any) -> str:
    try:
        return str(value).lower()
    except Exception:
        return ""


__all__ = [
    "CEO_IMPLEMENTATION_ORDER_EVENT_TYPE",
    "CODEX_EXECUTION_RECEIPT_EVENT_TYPE",
    "CEO_POST_CODEX_RESIDUAL_EVENT_TYPE",
    "CEOCodexExecutorDecision",
    "CEOCodexExecutorDecisionValue",
    "build_ceo_codex_executor_cieu_record",
    "build_ceo_codex_executor_contract",
    "validate_and_write_ceo_implementation_order",
    "validate_and_write_ceo_post_codex_residual",
    "validate_and_write_codex_execution_receipt",
    "validate_ceo_implementation_order",
    "validate_ceo_post_codex_residual",
    "validate_codex_execution_receipt",
    "write_ceo_codex_executor_cieu_record",
]
