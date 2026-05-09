"""Deterministic governance for Aiden agent-native company messages.

The messenger contract treats communication itself as governed behavior. A
message is not just natural language: it must also carry the CIEU/CZL five
tuple so humans, Aiden, future Labs agents, and external-agent proposals share
the same evidence-and-residual protocol.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


AIDEN_AGENT_NATIVE_MESSAGE_EVENT_TYPE = "AIDEN_AGENT_NATIVE_MESSAGE_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

CIEU_FIVE_TUPLE_FIELDS = ("Y_star_t", "X_t", "U_t", "Y_t_plus_1", "R_t_plus_1")

REQUIRED_PACKET_SECTIONS = (
    "messenger_session_id",
    "thread",
    "participants",
    "message",
    "model_orchestration",
    "delivery_boundary",
    "CIEU_linkage",
    "truth_constraints",
)

REQUIRED_MESSAGE_FIELDS = (
    "message_id",
    "created_at",
    "sender_id",
    "recipient_ids",
    "message_kind",
    "human_readable_text",
    "cieu_five_tuple",
)

SUPPORTED_PARTICIPANT_TYPES = {"human", "agent", "external_agent", "tool_executor", "governance_runtime"}

SUPPORTED_MESSAGE_KINDS = {
    "human_to_agent",
    "agent_to_human",
    "agent_to_agent",
    "group_meeting",
    "task_order",
    "execution_receipt",
    "file_attachment",
    "image_attachment",
    "wallet_proposal",
    "external_agent_proposal",
    "governance_notice",
}

FORBIDDEN_TRUE_CLAIMS = (
    "raw_natural_language_only_message",
    "missing_CIEU_five_tuple_allowed",
    "agent_message_without_model_orchestration",
    "external_delivery_executed",
    "external_agent_live_contact_executed",
    "payment_executed",
    "USDC_transfer_executed",
    "customer_validation_claim",
    "revenue_claim",
    "payment_claim",
    "K9Audit_write_claim",
    "hidden_chain_of_thought_stored",
    "CIEU_recording_bypassed",
)


class AidenAgentNativeMessageDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class AidenAgentNativeMessageDecision:
    decision: AidenAgentNativeMessageDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "aiden_agent_native_message_decision",
            "decision": self.decision.value,
            "passed": self.decision == AidenAgentNativeMessageDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "guidance": dict(self.guidance),
        }


def build_aiden_agent_native_messenger_contract() -> dict[str, Any]:
    return {
        "contract_id": "aiden_agent_native_messenger_contract_v1",
        "event_type": AIDEN_AGENT_NATIVE_MESSAGE_EVENT_TYPE,
        "protocol": "natural_language_plus_CIEU_CZL_five_tuple",
        "five_tuple_fields": list(CIEU_FIVE_TUPLE_FIELDS),
        "supported_participant_types": sorted(SUPPORTED_PARTICIPANT_TYPES),
        "supported_message_kinds": sorted(SUPPORTED_MESSAGE_KINDS),
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "non_goals": [
            "no live external-agent delivery in this milestone",
            "no payment or USDC transfer execution",
            "no hidden chain-of-thought storage",
        ],
    }


def validate_aiden_agent_native_message_packet(packet: Mapping[str, Any]) -> AidenAgentNativeMessageDecision:
    if not isinstance(packet, Mapping):
        return _deny("agent-native message packet must be a mapping", "schema", ["packet_not_mapping"])

    missing = [field for field in REQUIRED_PACKET_SECTIONS if field not in packet]
    if missing:
        return _revision(
            "agent-native message packet is missing required sections",
            "schema",
            [f"add section {field}" for field in missing],
        )

    truth = _mapping(packet.get("truth_constraints"))
    forbidden = [field for field in FORBIDDEN_TRUE_CLAIMS if truth.get(field) is True]
    if forbidden:
        return _deny("message packet contains forbidden bypass or overclaim", "truth_constraints", forbidden)

    participants = _list(packet.get("participants"))
    participant_decision = _validate_participants(participants)
    if participant_decision:
        return participant_decision
    participant_by_id = {str(item.get("participant_id")): item for item in participants if isinstance(item, Mapping)}

    message = _mapping(packet.get("message"))
    message_decision = _validate_message(message, participant_by_id)
    if message_decision:
        return message_decision

    model_decision = _validate_model_orchestration(_mapping(packet.get("model_orchestration")), message, participant_by_id)
    if model_decision:
        return model_decision

    delivery_decision = _validate_delivery_boundary(_mapping(packet.get("delivery_boundary")), message)
    if delivery_decision:
        return delivery_decision

    attachment_decision = _validate_attachment_boundary(_mapping(packet.get("attachment_manifest")), message)
    if attachment_decision:
        return attachment_decision

    cieu_decision = _validate_cieu_linkage(_mapping(packet.get("CIEU_linkage")))
    if cieu_decision:
        return cieu_decision

    return AidenAgentNativeMessageDecision(
        decision=AidenAgentNativeMessageDecisionValue.ALLOW,
        reason="agent-native message is natural-language readable, CIEU/CZL five-tuple complete, boundary-safe, and CIEU-recordable",
        correct_path=["deliver only inside the declared local messenger boundary and record the CIEU event"],
        guidance={
            "message_id": message.get("message_id"),
            "message_kind": message.get("message_kind"),
            "five_tuple_fields": list(CIEU_FIVE_TUPLE_FIELDS),
        },
    )


def build_aiden_agent_native_message_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenAgentNativeMessageDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, AidenAgentNativeMessageDecision) else dict(decision)
    message = _mapping(packet.get("message"))
    thread = _mapping(packet.get("thread"))
    five_tuple = _mapping(message.get("cieu_five_tuple"))
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(packet.get("messenger_session_id") or "aiden_agent_native_messenger"),
        "agent_id": str(message.get("sender_id") or "Aiden"),
        "event_type": AIDEN_AGENT_NATIVE_MESSAGE_EVENT_TYPE,
        "decision": "ALLOW" if decision_data.get("decision") == "ALLOW" else "DENY",
        "passed": decision_data.get("decision") == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_data.get("decision") != "ALLOW",
        "drift_details": None if decision_data.get("decision") == "ALLOW" else decision_data.get("reason"),
        "task_description": "Aiden agent-native messenger message validation",
        "contract_hash": "aiden-agent-native-messenger-v1",
        "params": {
            "message_id": message.get("message_id"),
            "message_kind": message.get("message_kind"),
            "thread_id": thread.get("thread_id"),
            "sender_id": message.get("sender_id"),
            "recipient_ids": list(message.get("recipient_ids") or []),
            "five_tuple_protocol": "CZL/CIEU",
        },
        "result": {
            "decision": decision_data.get("decision"),
            "reason": decision_data.get("reason"),
            "correct_path": list(decision_data.get("correct_path") or []),
            "guidance": dict(decision_data.get("guidance") or {}),
            "human_readable_text": message.get("human_readable_text"),
            "cieu_five_tuple": {field: five_tuple.get(field) for field in CIEU_FIVE_TUPLE_FIELDS},
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "agent-native-messenger", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_data.get("decision") == "ALLOW",
    }


def write_aiden_agent_native_message_cieu_record(record: Mapping[str, Any], *, cieu_db: str) -> bool:
    return bool(CIEUStore(cieu_db).write_dict(dict(record)))


def validate_and_write_aiden_agent_native_message_packet(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_aiden_agent_native_message_packet(packet)
    record = build_aiden_agent_native_message_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "aiden_agent_native_message_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "CIEU_write_result": {"event_type": record["event_type"], "event_id": record["event_id"], "CIEU_record": record},
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def _validate_participants(participants: list[Any]) -> AidenAgentNativeMessageDecision | None:
    if len(participants) < 2:
        return _revision("messenger packet needs at least two participants", "participants", ["add sender and recipient participants"])
    seen: set[str] = set()
    for item in participants:
        if not isinstance(item, Mapping):
            return _revision("participant entries must be mappings", "participants", ["replace malformed participant row"])
        participant_id = str(item.get("participant_id") or "")
        participant_type = str(item.get("participant_type") or "")
        if not participant_id:
            return _revision("participant_id is required", "participants", ["add participant_id"])
        if participant_id in seen:
            return _revision("participant_id must be unique", "participants", [f"deduplicate participant {participant_id}"])
        seen.add(participant_id)
        if participant_type not in SUPPORTED_PARTICIPANT_TYPES:
            return _revision("participant_type is not governed", "participants", [f"classify {participant_id} with a supported participant_type"])
        if participant_type == "external_agent" and item.get("live_external_delivery_allowed") is True:
            return _escalate(
                "external-agent live delivery requires owner approval and a provider boundary",
                "participants",
                ["keep external_agent as no-send/proposal-only until owner approves"],
            )
    return None


def _validate_message(message: Mapping[str, Any], participant_by_id: Mapping[str, Any]) -> AidenAgentNativeMessageDecision | None:
    missing = [field for field in REQUIRED_MESSAGE_FIELDS if field not in message]
    if missing:
        return _revision("message is missing required fields", "message", [f"add message.{field}" for field in missing])
    if str(message.get("message_kind") or "") not in SUPPORTED_MESSAGE_KINDS:
        return _revision("message_kind is not supported by the governed messenger", "message", ["use a supported message_kind"])
    text = str(message.get("human_readable_text") or "").strip()
    if len(text) < 8:
        return _revision("message must contain meaningful human-readable text", "message", ["write a concise natural-language message"])
    sender_id = str(message.get("sender_id") or "")
    recipients = [str(item) for item in _list(message.get("recipient_ids"))]
    if sender_id not in participant_by_id:
        return _revision("sender_id must reference a declared participant", "message", ["add sender participant or fix sender_id"])
    missing_recipients = [item for item in recipients if item not in participant_by_id]
    if not recipients or missing_recipients:
        return _revision("all recipient_ids must reference declared participants", "message", ["add recipient participants or fix recipient_ids"])

    five_tuple = _mapping(message.get("cieu_five_tuple"))
    missing_tuple = [field for field in CIEU_FIVE_TUPLE_FIELDS if _is_empty(five_tuple.get(field))]
    if missing_tuple:
        return _revision(
            "message must include a complete CIEU/CZL five tuple",
            "message.cieu_five_tuple",
            [f"add cieu_five_tuple.{field}" for field in missing_tuple],
        )
    residual_status = str(five_tuple.get("residual_status") or "")
    if residual_status not in {"planning_residual_pending", "planning_residual_closed_real_world_pending", "real_feedback_residual_recorded"}:
        return _revision(
            "five tuple must honestly declare residual status",
            "message.cieu_five_tuple",
            ["set residual_status=planning_residual_pending unless real feedback exists"],
        )
    if residual_status == "real_feedback_residual_recorded" and message.get("real_external_feedback_received") is not True:
        return _deny("message cannot claim real feedback residual without real feedback evidence", "message.cieu_five_tuple", ["false_real_feedback_residual"])
    return None


def _validate_model_orchestration(
    model_plan: Mapping[str, Any],
    message: Mapping[str, Any],
    participant_by_id: Mapping[str, Any],
) -> AidenAgentNativeMessageDecision | None:
    sender_type = str(_mapping(participant_by_id.get(str(message.get("sender_id") or ""))).get("participant_type") or "")
    recipient_types = [
        str(_mapping(participant_by_id.get(str(recipient_id))).get("participant_type") or "")
        for recipient_id in _list(message.get("recipient_ids"))
    ]
    agent_involved = sender_type == "agent" or "agent" in recipient_types or "tool_executor" in recipient_types
    if agent_involved:
        if model_plan.get("model_orchestration_required") is not True:
            return _revision(
                "agent-involved messages require governed model/tool orchestration metadata",
                "model_orchestration",
                ["route the message through E123 model orchestration before generation or execution"],
            )
        if not model_plan.get("selected_model_id"):
            return _revision("model orchestration plan must name selected_model_id", "model_orchestration", ["add selected_model_id"])
        if model_plan.get("raw_prompt_only") is True:
            return _deny("raw prompt-only agent messaging bypasses CEO-governed orchestration", "model_orchestration", ["raw_prompt_only_agent_message"])
    return None


def _validate_delivery_boundary(boundary: Mapping[str, Any], message: Mapping[str, Any]) -> AidenAgentNativeMessageDecision | None:
    if boundary.get("local_messenger_only") is not True:
        return _revision("E124 messenger delivery must stay local-only by default", "delivery_boundary", ["set local_messenger_only=true"])
    if boundary.get("external_delivery_executed") is True or boundary.get("provider_action_executed") is True:
        return _deny("messenger packet executed an external side effect", "delivery_boundary", ["external_side_effect_executed"])
    if str(message.get("message_kind") or "") == "external_agent_proposal" and boundary.get("no_send_default") is not True:
        return _revision("external-agent proposal must remain no-send by default", "delivery_boundary", ["set no_send_default=true"])
    if str(message.get("message_kind") or "") == "wallet_proposal":
        wallet = _mapping(message.get("wallet_proposal"))
        if wallet.get("proposal_only") is not True:
            return _revision("wallet message must be proposal-only", "message.wallet_proposal", ["set proposal_only=true"])
        if wallet.get("payment_executed") is True or wallet.get("USDC_transfer_executed") is True:
            return _deny("wallet proposal cannot execute payment or USDC transfer", "message.wallet_proposal", ["payment_or_USDC_transfer_executed"])
    return None


def _validate_attachment_boundary(attachment_manifest: Mapping[str, Any], message: Mapping[str, Any]) -> AidenAgentNativeMessageDecision | None:
    if str(message.get("message_kind") or "") not in {"file_attachment", "image_attachment"}:
        return None
    if attachment_manifest.get("metadata_only") is not True:
        return _revision("attachment messages must declare metadata-only handling in E124", "attachment_manifest", ["set metadata_only=true"])
    if attachment_manifest.get("external_upload_executed") is True:
        return _deny("attachment upload cannot execute externally in E124", "attachment_manifest", ["external_upload_executed"])
    return None


def _validate_cieu_linkage(cieu: Mapping[str, Any]) -> AidenAgentNativeMessageDecision | None:
    if cieu.get("CIEU_recording_required") is not True:
        return _revision("every governed messenger message must be CIEU recorded", "CIEU_linkage", ["set CIEU_recording_required=true"])
    if str(cieu.get("target_event_type") or "") != AIDEN_AGENT_NATIVE_MESSAGE_EVENT_TYPE:
        return _revision("CIEU target event type must match the messenger contract", "CIEU_linkage", [f"set target_event_type={AIDEN_AGENT_NATIVE_MESSAGE_EVENT_TYPE}"])
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> AidenAgentNativeMessageDecision:
    return AidenAgentNativeMessageDecision(
        decision=AidenAgentNativeMessageDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=failed_section,
        correct_path=correct_path,
    )


def _deny(reason: str, failed_section: str, violations: list[str]) -> AidenAgentNativeMessageDecision:
    return AidenAgentNativeMessageDecision(
        decision=AidenAgentNativeMessageDecisionValue.DENY,
        reason=reason,
        failed_section=failed_section,
        violations=violations,
    )


def _escalate(reason: str, failed_section: str, correct_path: list[str]) -> AidenAgentNativeMessageDecision:
    return AidenAgentNativeMessageDecision(
        decision=AidenAgentNativeMessageDecisionValue.ESCALATE,
        reason=reason,
        failed_section=failed_section,
        correct_path=correct_path,
        guidance={"requires_owner_decision": True},
    )


__all__ = [
    "AIDEN_AGENT_NATIVE_MESSAGE_EVENT_TYPE",
    "CIEU_FIVE_TUPLE_FIELDS",
    "AidenAgentNativeMessageDecision",
    "AidenAgentNativeMessageDecisionValue",
    "build_aiden_agent_native_messenger_contract",
    "build_aiden_agent_native_message_cieu_record",
    "validate_aiden_agent_native_message_packet",
    "validate_and_write_aiden_agent_native_message_packet",
    "write_aiden_agent_native_message_cieu_record",
]
