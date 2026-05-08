"""Deterministic governance for CEO operating-doctrine invocation.

The CEO behavior center lives in bridge-labs, but major CEO actions must prove
that the relevant operating doctrines were invoked before action selection. This
module validates that proof and writes the decision through the existing
``CIEUStore.write_dict`` path. It does not create a parallel ledger.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


CEO_OPERATING_DOCTRINE_CIEU_EVENT_TYPE = "CEO_OPERATING_DOCTRINE_INVOCATION_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"


class CEODoctrineDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEODoctrineDecision:
    decision: CEODoctrineDecisionValue
    reason: str
    failed_doctrine: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_operating_doctrine_governance_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEODoctrineDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_doctrine": self.failed_doctrine,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


BASE_REQUIRED_DOCTRINES: tuple[str, ...] = (
    "mission_owner_intent_understanding",
    "full_repo_capability_recall",
    "no_new_wheel_gate",
    "Y_star_gov_runtime_governance",
    "CIEU_prediction",
    "post_action_residual_learning",
)

MARKET_STRATEGY_REQUIRED_DOCTRINES: tuple[str, ...] = (
    "historical_asset_retrieval",
    "external_observation_public_read_model",
    "evidence_trust_scoring",
    "route_candidate_generation",
    "counterfactual_comparison",
    "commercial_sharpness_gate",
    "first_cash_path_selection",
    "what_not_to_do",
)

ENGINEERING_REQUIRED_DOCTRINES: tuple[str, ...] = (
    "owner_repo_boundary_check",
    "tests_required",
)

PROVIDER_REQUIRED_DOCTRINES: tuple[str, ...] = (
    "gov_mcp_dry_run_preflight",
    "owner_approval_boundary",
    "no_send_invariant",
)

L4_REQUIRED_DOCTRINES: tuple[str, ...] = (
    "target_profile_evidence",
    "owner_decision_packet",
    "AI_transparency_opt_out_no_send",
)

REVENUE_REQUIRED_DOCTRINES: tuple[str, ...] = (
    "legal_compliance_boundary",
    "pricing_hypothesis_evidence",
    "payment_execution_boundary",
)

K9_REQUIRED_DOCTRINES: tuple[str, ...] = ("K9Audit_evidence_chain_boundary",)

UNSATISFACTORY_STATUSES: set[str] = {
    "missing",
    "report_only",
    "artifact_only",
    "stale_or_deprecated",
    "quarantined",
    "unsafe_contact_sensitive",
    "static_evidence_map_only",
}

REPAIRABLE_EXTERNAL_OBSERVATION_STATUSES: set[str] = {
    "historical_public_read_wrapper_invoked",
    "runtime_invoked",
    "live_public_read_invoked",
}

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


def build_ceo_operating_doctrine_contract() -> dict[str, Any]:
    return {
        "contract_id": "ceo_operating_doctrine_invocation_contract_v1",
        "event_type": CEO_OPERATING_DOCTRINE_CIEU_EVENT_TYPE,
        "decision_values": ["ALLOW", "REQUIRE_REVISION", "DENY", "ESCALATE"],
        "base_required_doctrines": list(BASE_REQUIRED_DOCTRINES),
        "market_strategy_required_doctrines": list(MARKET_STRATEGY_REQUIRED_DOCTRINES),
        "provider_required_doctrines": list(PROVIDER_REQUIRED_DOCTRINES),
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "private_chain_of_thought_policy": "structured_outputs_only_no_hidden_chain_of_thought",
    }


def required_doctrines_for_action_context(action_context: Mapping[str, Any]) -> list[str]:
    required = list(BASE_REQUIRED_DOCTRINES)
    action_type = str(action_context.get("action_type") or "").lower()
    mission_type = str(action_context.get("mission_type") or "").lower()

    if action_context.get("market_strategy_required") is True or "market" in mission_type:
        required.extend(MARKET_STRATEGY_REQUIRED_DOCTRINES)
    if action_context.get("external_observation_required") is True:
        required.extend(("external_observation_public_read_model", "evidence_trust_scoring"))
    if action_context.get("provider_tool_boundary") is True or "provider" in action_type:
        required.extend(PROVIDER_REQUIRED_DOCTRINES)
    if action_context.get("owner_decision_required") is True or str(action_context.get("L_level")) == "L4":
        required.extend(L4_REQUIRED_DOCTRINES)
    if action_context.get("revenue_or_payment_related") is True:
        required.extend(REVENUE_REQUIRED_DOCTRINES)
    if action_context.get("K9Audit_related") is True:
        required.extend(K9_REQUIRED_DOCTRINES)
    if action_type in {"engineering_runtime_implementation", "canonical_governance_mutation"}:
        required.extend(ENGINEERING_REQUIRED_DOCTRINES)
    return list(dict.fromkeys(required))


def validate_ceo_doctrine_invocation_plan(plan: Mapping[str, Any]) -> CEODoctrineDecision:
    return _validate_plan_or_proof(plan, proof_mode=False)


def validate_ceo_doctrine_invocation_proof(proof: Mapping[str, Any]) -> CEODoctrineDecision:
    return _validate_plan_or_proof(proof, proof_mode=True)


def build_ceo_doctrine_cieu_record(
    payload: Mapping[str, Any],
    decision: CEODoctrineDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, CEODoctrineDecision) else dict(decision)
    decision_value = str(decision_data.get("decision") or "DENY")
    context = payload.get("action_context") if isinstance(payload.get("action_context"), Mapping) else {}
    invocations = _invocations(payload)
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(payload.get("session_id") or context.get("action_id") or "ceo_doctrine_session"),
        "agent_id": str(payload.get("agent_id") or context.get("actor") or "bridge_labs_ceo"),
        "event_type": CEO_OPERATING_DOCTRINE_CIEU_EVENT_TYPE,
        "decision": _decision_to_cieu_decision(decision_value),
        "passed": decision_value == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_value != "ALLOW",
        "drift_details": None if decision_value == "ALLOW" else decision_data.get("reason"),
        "task_description": "CEO operating doctrine invocation governance decision",
        "contract_hash": "ceo-operating-doctrine-contract-v1",
        "params": {
            "registry_id": payload.get("registry_id"),
            "plan_id": payload.get("doctrine_invocation_plan_id"),
            "proof_id": payload.get("doctrine_invocation_proof_id"),
            "action_id": context.get("action_id"),
            "action_type": context.get("action_type"),
            "mission_type": context.get("mission_type"),
            "market_strategy_required": context.get("market_strategy_required"),
            "external_observation_required": context.get("external_observation_required"),
            "provider_tool_boundary": context.get("provider_tool_boundary"),
            "generation_mode": context.get("generation_mode"),
            "required_doctrine_count": len(_required_from_payload(payload, context)),
            "invocation_count": len(invocations),
        },
        "result": {
            "decision": decision_value,
            "reason": decision_data.get("reason"),
            "failed_doctrine": decision_data.get("failed_doctrine"),
            "correct_path": list(decision_data.get("correct_path") or [])[:10],
            "required_doctrines": _required_from_payload(payload, context),
            "satisfied_doctrines": [
                str(item.get("doctrine_id"))
                for item in invocations
                if _invocation_satisfies(item, context)
            ],
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": payload.get("human_initiator") or context.get("owner_id"),
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_value == "ALLOW",
    }


def write_ceo_doctrine_cieu_record(
    payload: Mapping[str, Any],
    decision: CEODoctrineDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    if not cieu_db:
        raise ValueError("cieu_db is required")
    record = build_ceo_doctrine_cieu_record(payload, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_operating_doctrine_formal_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "formal_CIEU_log_module": "ystar.governance.ceo_operating_doctrine_contract",
        "formal_CIEU_log_function": "write_ceo_doctrine_cieu_record",
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_doctrine_invocation_plan(
    plan: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_doctrine_invocation_plan(plan)
    write_result = write_ceo_doctrine_cieu_record(
        plan,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return _validate_write_result("ceo_doctrine_plan_validate_and_write_result", decision, write_result)


def validate_and_write_ceo_doctrine_invocation_proof(
    proof: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_doctrine_invocation_proof(proof)
    write_result = write_ceo_doctrine_cieu_record(
        proof,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return _validate_write_result("ceo_doctrine_proof_validate_and_write_result", decision, write_result)


def _validate_write_result(artifact_id: str, decision: CEODoctrineDecision, write_result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": dict(write_result),
        "formal_CIEU_log_written": bool(write_result.get("formal_CIEU_log_written")),
        "formal_CIEU_log_status": write_result.get("formal_CIEU_log_status"),
        "validator_output_status": write_result.get("validator_output_status"),
    }


def _validate_plan_or_proof(payload: Mapping[str, Any], *, proof_mode: bool) -> CEODoctrineDecision:
    if not isinstance(payload, Mapping):
        return _decision("DENY", "doctrine payload must be a mapping", {}, "payload_schema")
    context = payload.get("action_context")
    if not isinstance(context, Mapping):
        return _revision("action_context is required", payload, "action_context", ["attach action_context"])
    if payload.get("bypass_attempt") is True or context.get("bypass_attempt") is True:
        return _decision("DENY", "doctrine invocation bypass attempt is forbidden", payload, "bypass", ["bypass_attempt"])

    forbidden = _forbidden_claim(payload)
    if forbidden:
        return _decision("DENY", f"false or forbidden claim present: {forbidden}", payload, "overclaim", [forbidden])
    if context.get("K9Audit_related") is True and context.get("K9Audit_integration_claim") is True and context.get("K9Audit_bridge_exists") is not True:
        return _decision("DENY", "K9Audit integration claim is unsupported by bridge code", payload, "K9Audit_evidence_chain_boundary", ["false_K9Audit_integration_claim"])
    if context.get("revenue_or_payment_related") is True and not (
        context.get("owner_approval_state") == "approved"
        and context.get("payment_boundary_configured") is True
        and context.get("legal_compliance_boundary_present") is True
    ):
        return _decision("DENY", "revenue/payment action lacks owner/legal/payment boundary proof", payload, "payment_execution_boundary", ["revenue_payment_boundary_missing"])

    if (
        context.get("market_strategy_required") is True
        and context.get("test_mode") is not True
        and str(context.get("generation_mode") or "").lower() in {"static_template", "deterministic_fixture"}
    ):
        return _revision(
            "static templates cannot satisfy non-test market strategy doctrine",
            payload,
            "generation_mode",
            ["use runtime_generated_structured_output or mark test_mode=true"],
        )

    required = _required_from_payload(payload, context)
    invocations = _invocations(payload)
    by_id = {str(item.get("doctrine_id")): item for item in invocations if isinstance(item, Mapping)}
    missing = [doctrine_id for doctrine_id in required if doctrine_id not in by_id]
    if missing:
        return _revision(
            "mandatory doctrine invocation is missing",
            payload,
            missing[0],
            ["invoke missing doctrines: " + ", ".join(missing[:12])],
        )
    for doctrine_id in required:
        invocation = by_id[doctrine_id]
        if not _invocation_satisfies(invocation, context):
            return _revision(
                "mandatory doctrine invocation does not satisfy runtime contract",
                payload,
                doctrine_id,
                [f"replace {doctrine_id} invocation_status={invocation.get('invocation_status')} with runtime/callable proof"],
            )
        if proof_mode and not _present(invocation.get("output_summary")):
            return _revision(
                "doctrine proof requires output_summary",
                payload,
                doctrine_id,
                [f"attach output_summary for {doctrine_id}"],
            )
        if not _present(invocation.get("evidence_refs")):
            return _revision(
                "doctrine invocation requires evidence_refs",
                payload,
                doctrine_id,
                [f"attach evidence_refs for {doctrine_id}"],
            )
        if _is_gov_mcp_doctrine(doctrine_id) and context.get("provider_tool_boundary") is True:
            if invocation.get("provider_action_executed") is True or invocation.get("external_side_effect") is True:
                return _decision("DENY", "gov-mcp doctrine proof may not execute provider action", payload, doctrine_id, ["provider_execution_forbidden"])
            if invocation.get("no_send_invariant") is not True:
                return _revision("gov-mcp doctrine proof requires no_send_invariant", payload, doctrine_id, ["set no_send_invariant=true"])

    if context.get("owner_decision_required") is True and context.get("execution_requested") is True and context.get("owner_approval_state") != "approved":
        return _decision(
            "ESCALATE",
            "complete doctrine proof reaches owner-bound authority without approval",
            payload,
            "owner_decision_packet",
            ["owner_decision_required"],
            guidance={
                "guidance_type": "owner_decision_required",
                "owner_decision_path": context.get("owner_decision_path") or "generate scoped owner decision packet; no execution",
                "execution_allowed_before_owner_decision": False,
            },
            correct_path=[
                "stop before owner-bound execution",
                "present owner decision packet",
                "rerun doctrine validation after explicit approval",
            ],
            requires_owner_decision=True,
        )
    return _decision("ALLOW", "CEO doctrine invocation payload satisfies governance contract", payload)


def _required_from_payload(payload: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    explicit = payload.get("required_doctrines")
    if isinstance(explicit, list) and explicit:
        return [str(item) for item in explicit]
    return required_doctrines_for_action_context(context)


def _invocations(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("doctrine_invocations", "planned_invocations", "invocations"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _invocation_satisfies(invocation: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
    if invocation.get("deprecated") is True or invocation.get("quarantined") is True:
        return False
    runtime_status = str(invocation.get("runtime_status") or invocation.get("source_runtime_status") or "").lower()
    invocation_status = str(invocation.get("invocation_status") or "").lower()
    if runtime_status in UNSATISFACTORY_STATUSES or invocation_status in UNSATISFACTORY_STATUSES:
        return False
    doctrine_id = str(invocation.get("doctrine_id") or "")
    if _is_external_observation_doctrine(doctrine_id):
        if context.get("live_external_observation_required") is True:
            return invocation_status in {"runtime_invoked", "live_public_read_invoked"}
        return invocation_status in REPAIRABLE_EXTERNAL_OBSERVATION_STATUSES
    return invocation_status in {
        "planned",
        "runtime_invoked",
        "validated",
        "completed",
        "satisfied",
        "historical_public_read_wrapper_invoked",
        "dry_run_invoked",
        "owner_packet_prepared",
        "cieustore_recorded",
    }


def _is_external_observation_doctrine(doctrine_id: str) -> bool:
    return "external_observation" in doctrine_id or "public_read" in doctrine_id or "public-read" in doctrine_id


def _is_gov_mcp_doctrine(doctrine_id: str) -> bool:
    return "gov_mcp" in doctrine_id or "gov-mcp" in doctrine_id


def _forbidden_claim(payload: Mapping[str, Any]) -> str:
    candidates: list[Any] = [payload, payload.get("action_context") if isinstance(payload.get("action_context"), Mapping) else {}]
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            for field in FORBIDDEN_CLAIM_KEYS:
                if candidate.get(field) is True:
                    return field
            for nested_key in ("overclaim_boundary", "truth_constraints", "claims"):
                nested = candidate.get(nested_key)
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
        "k9audit integration complete",
    ):
        if phrase in text:
            return phrase
    return ""


def _decision(
    value: str,
    reason: str,
    payload: Mapping[str, Any],
    failed_doctrine: str | None = None,
    violations: list[str] | None = None,
    *,
    guidance: dict[str, Any] | None = None,
    correct_path: list[str] | None = None,
    requires_owner_decision: bool = False,
) -> CEODoctrineDecision:
    decision_value = CEODoctrineDecisionValue(value)
    provisional = CEODoctrineDecision(
        decision=decision_value,
        reason=reason,
        failed_doctrine=failed_doctrine,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
    )
    return CEODoctrineDecision(
        decision=decision_value,
        reason=reason,
        failed_doctrine=failed_doctrine,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
        cieu_validation_record=_validation_candidate(payload, provisional),
    )


def _revision(reason: str, payload: Mapping[str, Any], failed_doctrine: str, required_changes: list[str]) -> CEODoctrineDecision:
    correct_path = [
        "repair the CEO doctrine invocation plan/proof before runtime continuation",
        "do not proceed to CEO major action while decision is REQUIRE_REVISION",
        "rerun validate_ceo_doctrine_invocation_plan/proof after repair",
        *required_changes,
    ]
    return _decision(
        "REQUIRE_REVISION",
        reason,
        payload,
        failed_doctrine,
        required_changes,
        guidance={
            "guidance_type": "require_revision",
            "failed_doctrine": failed_doctrine,
            "required_changes": required_changes,
            "correct_path": correct_path,
            "execution_allowed_before_revision": False,
            "revalidate_after_revision": True,
        },
        correct_path=correct_path,
    )


def _validation_candidate(payload: Mapping[str, Any], decision: CEODoctrineDecision) -> dict[str, Any]:
    context = payload.get("action_context") if isinstance(payload.get("action_context"), Mapping) else {}
    return {
        "X_t": {
            "contract_id": "ceo_operating_doctrine_invocation_contract_v1",
            "action_id": context.get("action_id"),
            "registry_id": payload.get("registry_id"),
        },
        "U_t": "Y-star-gov deterministic CEO operating doctrine invocation validation",
        "Y_star_t": "CEO major actions must prove mandatory operating-doctrine invocation before runtime continuation",
        "Y_t_plus_1": {
            "decision": decision.decision.value,
            "reason": decision.reason,
            "failed_doctrine": decision.failed_doctrine,
            "correct_path": list(decision.correct_path),
        },
        "R_t_plus_1": "none" if decision.decision == CEODoctrineDecisionValue.ALLOW else decision.reason,
    }


def _decision_to_cieu_decision(value: str) -> str:
    return {
        "ALLOW": "allow",
        "REQUIRE_REVISION": "rewrite",
        "DENY": "deny",
        "ESCALATE": "escalate",
    }.get(value, "unknown")


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_text(item)}" for key, item in value.items()).lower()
    if isinstance(value, list):
        return " ".join(_text(item) for item in value).lower()
    return str(value or "").lower()


__all__ = [
    "CEO_OPERATING_DOCTRINE_CIEU_EVENT_TYPE",
    "FORMAL_CIEU_LOG_PATH",
    "CEODoctrineDecision",
    "CEODoctrineDecisionValue",
    "build_ceo_doctrine_cieu_record",
    "build_ceo_operating_doctrine_contract",
    "required_doctrines_for_action_context",
    "validate_and_write_ceo_doctrine_invocation_plan",
    "validate_and_write_ceo_doctrine_invocation_proof",
    "validate_ceo_doctrine_invocation_plan",
    "validate_ceo_doctrine_invocation_proof",
    "write_ceo_doctrine_cieu_record",
]
