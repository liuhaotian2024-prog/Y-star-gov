"""Deterministic governance for Aiden model/tool orchestration.

This contract does not execute models. It validates that Aiden selected a
model/tool through a governed routing packet, with memory reuse, privacy/cost
boundaries, quality comparison, and CIEU recording before execution.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class AidenModelOrchestrationDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class AidenModelOrchestrationDecision:
    decision: AidenModelOrchestrationDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "aiden_model_orchestration_decision",
            "decision": self.decision.value,
            "passed": self.decision == AidenModelOrchestrationDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "guidance": dict(self.guidance),
        }


AIDEN_MODEL_ORCHESTRATION_EVENT_TYPE = "AIDEN_MODEL_ORCHESTRATION_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

SUPPORTED_MODEL_IDS = {
    "deterministic_validator",
    "local_gemma4_e4b",
    "local_ystar_gemma",
    "codex_executor",
    "external_gpt",
    "external_claude",
}

LOCAL_MODEL_IDS = {"local_gemma4_e4b", "local_ystar_gemma"}
EXTERNAL_MODEL_IDS = {"external_gpt", "external_claude"}

REQUIRED_SECTIONS = (
    "orchestration_id",
    "task_context",
    "routing_factors",
    "candidate_models",
    "selected_model",
    "execution_boundary",
    "memory_context_plan",
    "quality_comparison_plan",
    "routing_policy_update",
    "CIEU_linkage",
    "truth_constraints",
)

REQUIRED_ROUTING_FACTORS = {
    "task_type",
    "risk_tier",
    "privacy_tier",
    "context_size",
    "cost_sensitivity",
    "required_wisdom_level",
}

REQUIRED_MEMORY_ASSETS = {
    "CIEUStore_formal_memory",
    "Aiden_6D_brain",
    "YstarGov_memory_store",
}

REQUIRED_QUALITY_METRICS = {
    "task_fit",
    "privacy_preservation",
    "evidence_grounding",
}

FORBIDDEN_TRUE_CLAIMS = (
    "model_choice_recent_memory_only",
    "raw_prompt_to_codex_without_CEOImplementationOrder",
    "external_model_called_without_owner_approval",
    "private_data_sent_to_external_model",
    "arbitrary_shell_allowed",
    "external_business_action_executed",
    "customer_validation_claim",
    "revenue_claim",
    "payment_claim",
    "direct_brain_write_without_owner_gate",
    "direct_policy_mutation",
    "K9Audit_write_claim",
)


def build_aiden_model_orchestration_contract() -> dict[str, Any]:
    return {
        "contract_id": "aiden_model_orchestration_contract_v1",
        "event_type": AIDEN_MODEL_ORCHESTRATION_EVENT_TYPE,
        "supported_model_ids": sorted(SUPPORTED_MODEL_IDS),
        "local_model_ids": sorted(LOCAL_MODEL_IDS),
        "external_model_ids": sorted(EXTERNAL_MODEL_IDS),
        "required_routing_factors": sorted(REQUIRED_ROUTING_FACTORS),
        "required_memory_assets": sorted(REQUIRED_MEMORY_ASSETS),
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
    }


def validate_aiden_model_orchestration_packet(packet: Mapping[str, Any]) -> AidenModelOrchestrationDecision:
    if not isinstance(packet, Mapping):
        return _deny("model orchestration packet must be a mapping", "schema", ["packet_not_mapping"])

    missing = [field for field in REQUIRED_SECTIONS if field not in packet]
    if missing:
        return _revision("model orchestration packet is missing required sections", "schema", [f"add {field}" for field in missing])

    truth = _mapping(packet.get("truth_constraints"))
    forbidden = [key for key in FORBIDDEN_TRUE_CLAIMS if truth.get(key) is True]
    if forbidden:
        return _deny("model orchestration packet contains forbidden bypass or overclaim", "truth_constraints", forbidden)

    task = _mapping(packet.get("task_context"))
    routing = _mapping(packet.get("routing_factors"))
    missing_routing = sorted(REQUIRED_ROUTING_FACTORS - set(routing))
    if missing_routing:
        return _revision("routing factors are incomplete", "routing_factors", [f"add routing factor {field}" for field in missing_routing])
    if not task.get("task_id") or not task.get("owner_intent"):
        return _revision("task context must include task_id and owner_intent", "task_context", ["add task_id", "add owner_intent"])

    candidates = _list(packet.get("candidate_models"))
    candidate_ids = {str(item.get("model_id")) for item in candidates if isinstance(item, Mapping)}
    if len(candidate_ids) < 3:
        return _revision("Aiden must compare at least three model/tool candidates", "candidate_models", ["include local, deterministic, and executor/frontier candidates"])
    unknown_candidates = sorted(candidate_ids - SUPPORTED_MODEL_IDS)
    if unknown_candidates:
        return _revision("candidate model is not in the governed model catalog", "candidate_models", [f"register or remove {model_id}" for model_id in unknown_candidates])

    selected = _mapping(packet.get("selected_model"))
    selected_id = str(selected.get("model_id") or "")
    if selected_id not in candidate_ids:
        return _revision("selected model must come from candidate_models", "selected_model", ["select one governed candidate_model"])

    boundary = _mapping(packet.get("execution_boundary"))
    decision = _validate_selected_model(selected_id, selected, boundary, task, packet)
    if decision:
        return decision

    memory_decision = _validate_memory_context_plan(_mapping(packet.get("memory_context_plan")))
    if memory_decision:
        return memory_decision

    quality_decision = _validate_quality_comparison_plan(_mapping(packet.get("quality_comparison_plan")))
    if quality_decision:
        return quality_decision

    policy = _mapping(packet.get("routing_policy_update"))
    if policy.get("direct_policy_mutation") is True:
        return _deny("routing policy may not be mutated directly by Aiden", "routing_policy_update", ["direct_policy_mutation"])
    if str(policy.get("update_mode") or "") not in {"proposal_only", "CIEU_backed_candidate"}:
        return _revision("routing policy update must be proposal-only or CIEU-backed candidate", "routing_policy_update", ["set update_mode=proposal_only"])

    cieu = _mapping(packet.get("CIEU_linkage"))
    if cieu.get("CIEU_recording_required") is not True:
        return _revision("model orchestration decision must be CIEU recorded before execution", "CIEU_linkage", ["set CIEU_recording_required=true"])

    return AidenModelOrchestrationDecision(
        decision=AidenModelOrchestrationDecisionValue.ALLOW,
        reason="model/tool selection is governed, memory-aware, privacy-bounded, and quality-comparable",
        correct_path=["execute selected model/tool through its declared boundary and record result quality"],
        guidance={"selected_model_id": selected_id, "candidate_model_ids": sorted(candidate_ids)},
    )


def build_aiden_model_orchestration_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenModelOrchestrationDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, AidenModelOrchestrationDecision) else dict(decision)
    task = _mapping(packet.get("task_context"))
    selected = _mapping(packet.get("selected_model"))
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(packet.get("orchestration_id") or "aiden_model_orchestration"),
        "agent_id": "Aiden",
        "event_type": AIDEN_MODEL_ORCHESTRATION_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "Aiden model/tool orchestration validation",
        "contract_hash": "aiden-model-orchestration-v1",
        "params": {"task_id": task.get("task_id"), "selected_model_id": selected.get("model_id")},
        "result": {
            "decision": data.get("decision"),
            "reason": data.get("reason"),
            "correct_path": list(data.get("correct_path") or []),
            "guidance": dict(data.get("guidance") or {}),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "model-orchestration-boundary", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": data.get("decision") == "ALLOW",
    }


def write_aiden_model_orchestration_cieu_record(record: Mapping[str, Any], *, cieu_db: str) -> bool:
    return bool(CIEUStore(cieu_db).write_dict(dict(record)))


def validate_and_write_aiden_model_orchestration_packet(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_aiden_model_orchestration_packet(packet)
    record = build_aiden_model_orchestration_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "aiden_model_orchestration_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "CIEU_write_result": {"event_type": record["event_type"], "event_id": record["event_id"], "CIEU_record": record},
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def _validate_selected_model(
    selected_id: str,
    selected: Mapping[str, Any],
    boundary: Mapping[str, Any],
    task: Mapping[str, Any],
    packet: Mapping[str, Any],
) -> AidenModelOrchestrationDecision | None:
    if selected_id in LOCAL_MODEL_IDS:
        if boundary.get("host_runtime_service_bridge_required") is not True:
            return _revision("local Gemma selection requires host runtime service bridge", "execution_boundary", ["route through E122 host runtime service bridge"])
        if boundary.get("local_only") is not True or boundary.get("external_provider_call_allowed") is True:
            return _deny("local model route must remain local-only with no external provider call", "execution_boundary", ["local_model_external_boundary_violation"])
        proof = _mapping(boundary.get("host_service_controller_proof"))
        if str(proof.get("status") or "") not in {"available", "ALLOW", "already_running", "service_bridge_running"}:
            return _revision("local model route needs host service controller proof", "execution_boundary", ["probe or start Ollama through E122 before local execution"])
    elif selected_id == "codex_executor":
        if boundary.get("CEOImplementationOrder_required") is not True or boundary.get("Codex_executor_boundary_required") is not True:
            return _revision("Codex execution requires CEOImplementationOrder boundary", "execution_boundary", ["build CEOImplementationOrder before Codex prompt"])
    elif selected_id == "deterministic_validator":
        if str(selected.get("role") or "") not in {"validator", "governance_judge", "rule_engine"}:
            return _revision("deterministic validator candidate must be used as validator/rule engine", "selected_model", ["set selected_model.role=validator"])
    elif selected_id in EXTERNAL_MODEL_IDS:
        approval = _mapping(packet.get("owner_approval"))
        if approval.get("owner_approved_external_model_use") is not True:
            return _escalate("external frontier model use requires owner approval", "owner_approval", ["owner must approve external GPT/Claude use and data boundary"])
        privacy = str(task.get("privacy_tier") or "").lower()
        if privacy in {"private", "secret", "sensitive", "high"} and boundary.get("redacted_context_only") is not True:
            return _deny("private or sensitive context cannot be sent to an external model unredacted", "execution_boundary", ["raw_private_context_external_model"])
        if boundary.get("external_provider_call_allowed") is not True:
            return _revision("external model route must explicitly declare external provider boundary", "execution_boundary", ["set external_provider_call_allowed=true only after approval"])
    else:
        return _revision("selected model is unsupported", "selected_model", ["choose a supported model/tool candidate"])
    return None


def _validate_memory_context_plan(plan: Mapping[str, Any]) -> AidenModelOrchestrationDecision | None:
    if plan.get("local_long_term_memory_required") is not True:
        return _revision("Aiden model choice must include local long-term memory plan", "memory_context_plan", ["set local_long_term_memory_required=true"])
    assets = _list(plan.get("discovered_memory_assets"))
    asset_ids = {str(item.get("asset_id")) for item in assets if isinstance(item, Mapping)}
    missing = sorted(REQUIRED_MEMORY_ASSETS - asset_ids)
    if missing:
        return _revision("memory context plan does not reuse the mandatory memory spine", "memory_context_plan", [f"include {asset_id}" for asset_id in missing])
    for item in assets:
        if not isinstance(item, Mapping):
            return _revision("memory asset rows must be mappings", "memory_context_plan", ["complete memory asset row"])
        if str(item.get("reuse_status") or "") in {"unknown", "ignored", "bypassed"}:
            return _revision("memory assets must be classified for reuse, not ignored", "memory_context_plan", [f"classify {item.get('asset_id') or 'unknown_asset'}"])
    if plan.get("recent_memory_only") is True:
        return _deny("recent memory cannot substitute for local long-term memory", "memory_context_plan", ["recent_memory_only"])
    return None


def _validate_quality_comparison_plan(plan: Mapping[str, Any]) -> AidenModelOrchestrationDecision | None:
    if plan.get("comparison_required") is not True:
        return _revision("model orchestration needs result-quality comparison", "quality_comparison_plan", ["set comparison_required=true"])
    metrics = set(_as_str_list(plan.get("metrics")))
    missing = sorted(REQUIRED_QUALITY_METRICS - metrics)
    if missing:
        return _revision("quality comparison metrics are incomplete", "quality_comparison_plan", [f"add metric {metric}" for metric in missing])
    if plan.get("CIEU_recording_required") is not True:
        return _revision("quality comparison must be CIEU-recorded", "quality_comparison_plan", ["set CIEU_recording_required=true"])
    if plan.get("raw_private_prompt_shadowing_allowed") is True:
        return _deny("raw private prompts may not be shadowed across models", "quality_comparison_plan", ["raw_private_prompt_shadowing_allowed"])
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_str_list(value: Any) -> list[str]:
    return [str(item) for item in _list(value)]


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> AidenModelOrchestrationDecision:
    return AidenModelOrchestrationDecision(
        decision=AidenModelOrchestrationDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=failed_section,
        correct_path=correct_path,
    )


def _deny(reason: str, failed_section: str, violations: list[str]) -> AidenModelOrchestrationDecision:
    return AidenModelOrchestrationDecision(
        decision=AidenModelOrchestrationDecisionValue.DENY,
        reason=reason,
        failed_section=failed_section,
        violations=violations,
    )


def _escalate(reason: str, failed_section: str, correct_path: list[str]) -> AidenModelOrchestrationDecision:
    return AidenModelOrchestrationDecision(
        decision=AidenModelOrchestrationDecisionValue.ESCALATE,
        reason=reason,
        failed_section=failed_section,
        correct_path=correct_path,
        guidance={"requires_owner_decision": True},
    )


__all__ = [
    "AIDEN_MODEL_ORCHESTRATION_EVENT_TYPE",
    "AidenModelOrchestrationDecision",
    "AidenModelOrchestrationDecisionValue",
    "build_aiden_model_orchestration_contract",
    "build_aiden_model_orchestration_cieu_record",
    "validate_aiden_model_orchestration_packet",
    "validate_and_write_aiden_model_orchestration_packet",
    "write_aiden_model_orchestration_cieu_record",
]
