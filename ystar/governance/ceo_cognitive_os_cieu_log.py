"""Formal CIEU record writer for CEO Cognitive OS runtime decisions.

The CEO Cognitive OS runtime hook is intentionally side-effect-free by
default. This module provides the explicit insertion path for callers that
need to persist the runtime decision into the existing Y-star-gov CIEU store.
It uses ``CIEUStore.write_dict`` and does not create a parallel ledger.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Mapping, Optional

from ystar.governance.ceo_cognitive_os_runtime_hook import (
    CEOCognitiveOSRuntimeResult,
    validate_ceo_runtime_envelope,
)
from ystar.governance.cieu_store import CIEUStore

CEO_COGNITIVE_OS_CIEU_EVENT_TYPE = "CEO_COGNITIVE_OS_RUNTIME_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

_RUNTIME_DECISION_TO_CIEU_DECISION = {
    "ALLOW": "allow",
    "REQUIRE_REVISION": "rewrite",
    "DENY": "deny",
    "ESCALATE": "escalate",
    "STATUS_ONLY": "info",
}


def build_ceo_cognitive_os_cieu_log_record(
    envelope: Mapping[str, Any],
    runtime_result: CEOCognitiveOSRuntimeResult | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    """Build a CIEU record that fits the existing ``CIEUStore`` schema."""

    if not isinstance(envelope, Mapping):
        raise TypeError("CEO runtime envelope must be a mapping")

    result_data = _runtime_result_to_dict(runtime_result)
    runtime_decision = str(result_data.get("decision") or "STATUS_ONLY")
    cieu_decision = _RUNTIME_DECISION_TO_CIEU_DECISION.get(runtime_decision, "unknown")
    resolved_session_id = (
        session_id
        or _first_present(envelope, "session_id", "runtime_session_id", "job_id")
        or "ceo_cognitive_os_runtime"
    )
    resolved_agent_id = agent_id or str(envelope.get("actor") or envelope.get("role") or "ceo")
    action_id = _first_present(envelope, "action_id", "packet_id") or "unknown_action"

    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": resolved_session_id,
        "agent_id": resolved_agent_id,
        "event_type": CEO_COGNITIVE_OS_CIEU_EVENT_TYPE,
        "decision": cieu_decision,
        "passed": runtime_decision in {"ALLOW", "STATUS_ONLY"},
        "violations": _violations_from_runtime_result(result_data),
        "drift_detected": runtime_decision not in {"ALLOW", "STATUS_ONLY"},
        "drift_details": None if runtime_decision in {"ALLOW", "STATUS_ONLY"} else result_data.get("reason"),
        "task_description": f"CEO Cognitive OS runtime decision for {action_id}",
        "contract_hash": _contract_hash_from_envelope(envelope),
        "params": {
            "runtime_envelope": dict(envelope),
            "cieu_validation_record_candidate": result_data.get("cieu_validation_record_candidate", {}),
        },
        "result": {
            "runtime_decision": runtime_decision,
            "runtime_route": result_data.get("route"),
            "reason": result_data.get("reason"),
            "guidance": _compact_guidance(result_data.get("guidance", {})),
            "correct_path": list(result_data.get("correct_path") or [])[:8],
            "validator_result": _compact_validator_result(result_data.get("validator_result", {})),
            "post_action_residual_validation": _compact_validator_result(
                result_data.get("post_action_residual_validation", {})
            ),
            "hook_decision_envelope": _compact_hook_decision_envelope(
                result_data.get("hook_decision_envelope", {})
            ),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": envelope.get("human_initiator") or envelope.get("owner_id"),
        "lineage_path": envelope.get("lineage_path") or ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": runtime_decision in {"ALLOW", "STATUS_ONLY"},
    }


def write_ceo_cognitive_os_cieu_log_record(
    envelope: Mapping[str, Any],
    runtime_result: CEOCognitiveOSRuntimeResult | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    """Persist a CEO Cognitive OS runtime decision through ``CIEUStore``."""

    if not cieu_db:
        raise ValueError("cieu_db is required for formal CIEU record writing")

    record = build_ceo_cognitive_os_cieu_log_record(
        envelope,
        runtime_result,
        session_id=session_id,
        agent_id=agent_id,
    )
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])

    return {
        "artifact_id": "ceo_cognitive_os_formal_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": (
            "formal_CIEU_record_written"
            if written
            else "formal_CIEU_record_duplicate_existing"
        ),
        "validator_output_status": (
            "formal_CIEU_record_written"
            if written
            else "formal_CIEU_record_duplicate_existing"
        ),
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "formal_CIEU_log_module": "ystar.governance.ceo_cognitive_os_cieu_log",
        "formal_CIEU_log_function": "write_ceo_cognitive_os_cieu_log_record",
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "runtime_decision": _runtime_result_to_dict(runtime_result).get("decision"),
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_runtime_envelope(
    envelope: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    """Validate a runtime envelope and persist the resulting CIEU record."""

    runtime_result = validate_ceo_runtime_envelope(envelope)
    write_result = write_ceo_cognitive_os_cieu_log_record(
        envelope,
        runtime_result,
        cieu_db=cieu_db,
        session_id=session_id,
        agent_id=agent_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_cognitive_os_validate_and_write_result",
        "runtime_result": runtime_result.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _runtime_result_to_dict(runtime_result: CEOCognitiveOSRuntimeResult | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(runtime_result, CEOCognitiveOSRuntimeResult):
        return runtime_result.to_dict()
    if isinstance(runtime_result, Mapping):
        return dict(runtime_result)
    if hasattr(runtime_result, "to_dict"):
        return runtime_result.to_dict()
    raise TypeError("runtime_result must be a CEOCognitiveOSRuntimeResult or mapping")


def _violations_from_runtime_result(result_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    runtime_decision = str(result_data.get("decision") or "STATUS_ONLY")
    if runtime_decision in {"ALLOW", "STATUS_ONLY"}:
        return []
    validator_result = result_data.get("validator_result")
    raw_violations = []
    if isinstance(validator_result, Mapping):
        raw_violations = list(validator_result.get("violations") or [])
    if not raw_violations and result_data.get("reason"):
        raw_violations = [str(result_data["reason"])]

    normalized: list[dict[str, Any]] = []
    for violation in raw_violations:
        if isinstance(violation, Mapping):
            normalized.append(dict(violation))
        else:
            normalized.append(
                {
                    "dimension": str(result_data.get("route") or runtime_decision).lower(),
                    "message": str(violation),
                }
            )
    return normalized


def _compact_guidance(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        "guidance_type": value.get("guidance_type"),
        "failed_stage": value.get("failed_stage"),
        "missing_fields": list(value.get("missing_fields") or [])[:12],
        "missing_loop_stages": list(value.get("missing_loop_stages") or [])[:12],
        "required_packet_changes": list(value.get("required_packet_changes") or [])[:8],
        "revalidate_after_revision": value.get("revalidate_after_revision"),
        "execution_allowed_before_revision": value.get("execution_allowed_before_revision"),
    }


def _compact_validator_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        "validator": value.get("validator"),
        "decision": value.get("decision"),
        "passed": value.get("passed"),
        "reason": value.get("reason"),
        "failed_stage": value.get("failed_stage"),
        "violations": list(value.get("violations") or [])[:8],
        "requires_owner_decision": value.get("requires_owner_decision"),
    }


def _compact_hook_decision_envelope(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        "decision": value.get("decision"),
        "route": value.get("route"),
        "allow_execution": value.get("allow_execution"),
        "allow_approved_next_step": value.get("allow_approved_next_step"),
        "allow_external_execution": value.get("allow_external_execution"),
        "require_revision": value.get("require_revision"),
        "deny": value.get("deny"),
        "escalate": value.get("escalate"),
        "owner_decision_path_required": value.get("owner_decision_path_required"),
    }


def _contract_hash_from_envelope(envelope: Mapping[str, Any]) -> Optional[str]:
    packet = envelope.get("pre_action_packet") or envelope.get("ceo_pre_action_packet")
    if isinstance(packet, Mapping):
        value = packet.get("Y_star_contract_hash_input")
        if value:
            return str(value)
    value = envelope.get("contract_hash")
    return str(value) if value else None


def _first_present(envelope: Mapping[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = envelope.get(key)
        if value:
            return str(value)
    return None


__all__ = [
    "CEO_COGNITIVE_OS_CIEU_EVENT_TYPE",
    "FORMAL_CIEU_LOG_PATH",
    "build_ceo_cognitive_os_cieu_log_record",
    "validate_and_write_ceo_runtime_envelope",
    "write_ceo_cognitive_os_cieu_log_record",
]
