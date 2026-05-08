"""Governance contract for the bridge-labs CEO behavior-center runtime gateway.

The behavior center is allowed to execute low-risk internal/read-only/dry-run
work autonomously. It must not push safe work back to the owner just because an
action is "external" in the broad sense. High-risk external side effects remain
owner-bound or denied.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


CEO_BEHAVIOR_CENTER_RUNTIME_EVENT_TYPE = "CEO_BEHAVIOR_CENTER_RUNTIME_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"


class CEOBehaviorCenterDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOBehaviorCenterDecision:
    decision: CEOBehaviorCenterDecisionValue
    reason: str
    failed_field: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_behavior_center_runtime_governance_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOBehaviorCenterDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_field": self.failed_field,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


REQUIRED_PACKET_FIELDS: tuple[str, ...] = (
    "packet_id",
    "source_owner_message",
    "behavior_center_source",
    "behavior_center_response",
    "intent",
    "brain_provenance",
    "brain_activations",
    "action_classification",
    "autonomous_execution_policy",
    "truth_constraints",
    "post_action_residual_required",
)

LOW_RISK_TIERS: set[str] = {
    "TIER_0_INTERNAL",
    "TIER_1_PUBLIC_READ_ONLY",
    "TIER_2_TRANSPARENT_LOW_RISK_EXTERNAL_VALIDATION",
}

HIGH_RISK_MARKERS: tuple[str, ...] = (
    "payment",
    "contract",
    "legal",
    "financial_commitment",
    "account_creation",
    "login",
    "credential",
    "regulated_form",
    "government_form",
    "tax_form",
    "identity_form",
    "production_deployment",
    "core_brain_cieu_memory_writeback",
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
    "live_provider_execution_claim",
)

FORBIDDEN_PRIVATE_REASONING_KEYS: tuple[str, ...] = (
    "chain_of_thought",
    "hidden_chain_of_thought",
    "private_chain_of_thought",
    "private_reasoning",
    "raw_model_reasoning",
)


def validate_ceo_behavior_center_runtime_packet(
    packet: Mapping[str, Any],
) -> CEOBehaviorCenterDecision:
    """Validate a behavior-center runtime packet before/after routing."""

    if not isinstance(packet, Mapping):
        return _decision("DENY", "behavior-center runtime packet must be a mapping", {}, "packet_schema")

    for key in FORBIDDEN_PRIVATE_REASONING_KEYS:
        if key in packet:
            return _decision("DENY", "private chain-of-thought must not be stored", packet, key, [key])

    if packet.get("bypass_attempt") is True:
        return _decision("DENY", "behavior-center runtime bypass attempt is forbidden", packet, "bypass_attempt", ["bypass_attempt"])

    forbidden = _forbidden_claim(packet)
    if forbidden:
        return _decision("DENY", f"forbidden completion claim present: {forbidden}", packet, "overclaim", [forbidden])

    missing = [field for field in REQUIRED_PACKET_FIELDS if field not in packet]
    if missing:
        return _revision("behavior-center runtime packet is missing required fields", packet, missing[0], [f"fill missing fields: {', '.join(missing[:12])}"])

    brain = packet.get("brain_provenance")
    if not isinstance(brain, Mapping):
        return _revision("brain_provenance must be present before behavior-center runtime acceptance", packet, "brain_provenance", ["query aiden_brain and attach brain_provenance"])
    if int(brain.get("total_activations") or 0) < 1 or int(brain.get("unique_nodes") or 0) < 1:
        return _revision("behavior-center runtime requires at least one real brain activation", packet, "brain_provenance", ["call aiden_brain.activate before routing behavior-center output"])
    activations = packet.get("brain_activations")
    if not isinstance(activations, list) or not activations:
        return _revision("brain_activations must be non-empty", packet, "brain_activations", ["attach non-empty brain_activations with brain:// evidence"])

    classification = packet.get("action_classification")
    policy = packet.get("autonomous_execution_policy")
    if not isinstance(classification, Mapping):
        return _revision("action_classification must be a mapping", packet, "action_classification", ["classify behavior-center route"])
    if not isinstance(policy, Mapping):
        return _revision("autonomous_execution_policy must be a mapping", packet, "autonomous_execution_policy", ["attach autonomous execution policy"])

    risk_tier = str(classification.get("risk_tier") or policy.get("risk_tier") or "")
    route_type = str(classification.get("route_type") or "")
    is_high_risk = bool(policy.get("high_risk_external_side_effect")) or _high_risk_text(packet)
    owner_required = bool(policy.get("owner_decision_required"))
    can_autonomous = bool(policy.get("can_autonomously_execute"))

    if policy.get("real_external_action_executed") is True:
        return _decision("DENY", "behavior-center gateway may not claim real external execution in this milestone", packet, "real_external_action_executed", ["real_external_action_forbidden_in_E94"])
    if policy.get("provider_action_executed") is True:
        return _decision("DENY", "provider action execution must remain false unless a later live provider gate is approved", packet, "provider_action_executed", ["provider_action_execution_forbidden"])

    if is_high_risk and can_autonomous:
        return _decision("DENY", "high-risk external side effects cannot be autonomously executed", packet, "autonomous_execution_policy", ["high_risk_autonomous_execution_attempt"])
    if is_high_risk and owner_required:
        return _escalate("high-risk external side effect requires owner decision packet", packet, "owner_decision_required")

    if risk_tier in LOW_RISK_TIERS and owner_required:
        return _revision(
            "low-risk internal/read-only/dry-run work should route autonomously instead of defaulting to owner",
            packet,
            "owner_decision_required",
            [
                "set owner_decision_required=false for low-risk autonomous route",
                "route through internal runtime, public-read adapter, gov-mcp dry-run, or E92 CEOImplementationOrder as appropriate",
            ],
        )

    if route_type in {"provider_tool_dry_run", "low_risk_external_validation_dry_run"}:
        if policy.get("gov_mcp_dry_run_required") is not True:
            return _revision("provider/tool boundary requires gov-mcp dry-run proof", packet, "gov_mcp_dry_run_required", ["set gov_mcp_dry_run_required=true and attach dry-run receipt after routing"])
        if policy.get("no_send_invariant") is not True:
            return _revision("provider/tool dry-run requires no_send_invariant", packet, "no_send_invariant", ["set no_send_invariant=true"])

    if not can_autonomous and not owner_required:
        return _revision(
            "runtime packet must either execute autonomously within safe bounds or explicitly require owner decision",
            packet,
            "autonomous_execution_policy",
            ["set can_autonomously_execute=true for safe routes or owner_decision_required=true for high-risk routes"],
        )

    return _decision("ALLOW", "behavior-center runtime packet satisfies brain-grounded autonomous governance contract", packet)


def build_ceo_behavior_center_runtime_cieu_record(
    packet: Mapping[str, Any],
    decision: CEOBehaviorCenterDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, CEOBehaviorCenterDecision) else dict(decision)
    decision_value = str(decision_data.get("decision") or "DENY")
    brain = packet.get("brain_provenance") if isinstance(packet.get("brain_provenance"), Mapping) else {}
    classification = packet.get("action_classification") if isinstance(packet.get("action_classification"), Mapping) else {}
    policy = packet.get("autonomous_execution_policy") if isinstance(packet.get("autonomous_execution_policy"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(packet.get("session_id") or packet.get("packet_id") or "ceo_behavior_center_session"),
        "agent_id": str(packet.get("agent_id") or "bridge_labs_ceo"),
        "event_type": CEO_BEHAVIOR_CENTER_RUNTIME_EVENT_TYPE,
        "decision": _decision_to_cieu_decision(decision_value),
        "passed": decision_value == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_value != "ALLOW",
        "drift_details": None if decision_value == "ALLOW" else decision_data.get("reason"),
        "task_description": "CEO behavior-center brain-grounded runtime gateway decision",
        "contract_hash": "ceo-behavior-center-runtime-v1",
        "params": {
            "packet_id": packet.get("packet_id"),
            "intent": packet.get("intent"),
            "risk_tier": classification.get("risk_tier") or policy.get("risk_tier"),
            "route_type": classification.get("route_type"),
            "brain_db": brain.get("brain_db"),
            "total_brain_activations": brain.get("total_activations"),
            "unique_brain_nodes": brain.get("unique_nodes"),
            "can_autonomously_execute": policy.get("can_autonomously_execute"),
            "owner_decision_required": policy.get("owner_decision_required"),
            "gov_mcp_dry_run_required": policy.get("gov_mcp_dry_run_required"),
            "no_send_invariant": policy.get("no_send_invariant"),
        },
        "result": {
            "decision": decision_value,
            "reason": decision_data.get("reason"),
            "failed_field": decision_data.get("failed_field"),
            "correct_path": list(decision_data.get("correct_path") or [])[:10],
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": packet.get("human_initiator") or packet.get("owner_id"),
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_value == "ALLOW",
    }


def write_ceo_behavior_center_runtime_cieu_record(
    packet: Mapping[str, Any],
    decision: CEOBehaviorCenterDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    if not cieu_db:
        raise ValueError("cieu_db is required")
    record = build_ceo_behavior_center_runtime_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_behavior_center_runtime_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "formal_CIEU_log_module": "ystar.governance.ceo_behavior_center_runtime_contract",
        "formal_CIEU_log_function": "write_ceo_behavior_center_runtime_cieu_record",
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_behavior_center_runtime_packet(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_behavior_center_runtime_packet(packet)
    write_result = write_ceo_behavior_center_runtime_cieu_record(packet, decision, cieu_db=cieu_db, session_id=session_id, seal_session=seal_session)
    return {
        "artifact_id": "ceo_behavior_center_runtime_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": bool(write_result.get("formal_CIEU_log_written")),
        "formal_CIEU_log_status": write_result.get("formal_CIEU_log_status"),
        "validator_output_status": write_result.get("validator_output_status"),
    }


def _revision(reason: str, packet: Mapping[str, Any], failed_field: str, correct_path: list[str]) -> CEOBehaviorCenterDecision:
    return _decision("REQUIRE_REVISION", reason, packet, failed_field, [], guidance={"guidance_type": "repair_behavior_center_runtime_packet"}, correct_path=correct_path)


def _escalate(reason: str, packet: Mapping[str, Any], failed_field: str) -> CEOBehaviorCenterDecision:
    return _decision(
        "ESCALATE",
        reason,
        packet,
        failed_field,
        ["owner_decision_required"],
        guidance={
            "guidance_type": "owner_decision_packet_required",
            "execution_allowed_before_owner_decision": False,
            "owner_decision_path": "build scoped owner decision packet for high-risk external side effect",
        },
        correct_path=["stop before high-risk external side effect", "prepare owner decision packet", "resume only after explicit approval"],
        requires_owner_decision=True,
    )


def _decision(
    value: str,
    reason: str,
    packet: Mapping[str, Any],
    failed_field: str | None = None,
    violations: list[str] | None = None,
    *,
    guidance: dict[str, Any] | None = None,
    correct_path: list[str] | None = None,
    requires_owner_decision: bool = False,
) -> CEOBehaviorCenterDecision:
    decision_value = CEOBehaviorCenterDecisionValue(value)
    return CEOBehaviorCenterDecision(
        decision=decision_value,
        reason=reason,
        failed_field=failed_field,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
        cieu_validation_record={
            "record_type": "CIEU_validation_record",
            "event_type": CEO_BEHAVIOR_CENTER_RUNTIME_EVENT_TYPE,
            "decision": decision_value.value,
            "reason": reason,
            "packet_id": packet.get("packet_id"),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
            "private_chain_of_thought_stored": False,
        },
    )


def _forbidden_claim(packet: Mapping[str, Any]) -> str:
    candidates: list[Any] = [
        packet,
        packet.get("truth_constraints") if isinstance(packet.get("truth_constraints"), Mapping) else {},
        packet.get("overclaim_boundary") if isinstance(packet.get("overclaim_boundary"), Mapping) else {},
        packet.get("autonomous_execution_policy") if isinstance(packet.get("autonomous_execution_policy"), Mapping) else {},
    ]
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            for field in FORBIDDEN_CLAIM_KEYS:
                if candidate.get(field) is True:
                    return field
    text = _text(packet).lower()
    for phrase in (
        "customer validation complete",
        "revenue achieved",
        "payment complete",
        "paid signal achieved",
        "pricing validation complete",
        "l5-d complete",
        "k9audit integration complete",
        "live provider execution complete",
    ):
        if phrase in text:
            return phrase
    return ""


def _high_risk_text(packet: Mapping[str, Any]) -> bool:
    classification = packet.get("action_classification") if isinstance(packet.get("action_classification"), Mapping) else {}
    policy = packet.get("autonomous_execution_policy") if isinstance(packet.get("autonomous_execution_policy"), Mapping) else {}
    text = " ".join(
        [
            str(packet.get("source_owner_message") or ""),
            str(classification.get("action_type") or ""),
            str(classification.get("route_type") or ""),
            str(classification.get("externality_level") or ""),
            str(policy.get("risk_tier") or ""),
        ]
    ).lower()
    return any(marker in text for marker in HIGH_RISK_MARKERS)


def _decision_to_cieu_decision(value: str) -> str:
    if value == "ALLOW":
        return "allow"
    if value == "ESCALATE":
        return "escalate"
    return "deny"


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(f"{k} {_text(v)}" for k, v in value.items())
    if isinstance(value, list):
        return " ".join(_text(v) for v in value)
    return str(value)


__all__ = [
    "CEO_BEHAVIOR_CENTER_RUNTIME_EVENT_TYPE",
    "CEOBehaviorCenterDecision",
    "CEOBehaviorCenterDecisionValue",
    "build_ceo_behavior_center_runtime_cieu_record",
    "validate_and_write_ceo_behavior_center_runtime_packet",
    "validate_ceo_behavior_center_runtime_packet",
    "write_ceo_behavior_center_runtime_cieu_record",
]
