"""Governance contract for CEO intelligence-loop packets.

The CEO's structured thinking is runtime behavior. This module validates and
persists the auditable outputs of that behavior without requesting or storing
private model chain-of-thought.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class CEOIntelligenceLoopDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOIntelligenceLoopDecision:
    decision: CEOIntelligenceLoopDecisionValue
    reason: str
    failed_stage: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_intelligence_loop_governance_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOIntelligenceLoopDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_stage": self.failed_stage,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


CEO_INTELLIGENCE_LOOP_CIEU_EVENT_TYPE = "CEO_INTELLIGENCE_LOOP_RUNTIME_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_INTELLIGENCE_STAGE_IDS: tuple[str, ...] = (
    "mission_and_owner_constraint_recall",
    "full_repo_capability_recall",
    "historical_asset_retrieval",
    "current_problem_classification",
    "opportunity_framing",
    "candidate_action_generation",
    "counterfactual_action_comparison",
    "commercial_sharpness_gate",
    "speed_to_cash_evaluation",
    "risk_owner_burden_evaluation",
    "no_new_wheel_gate",
    "adversarial_critique",
    "what_not_to_do",
    "pre_action_CIEU_residual_prediction",
    "selected_action_decision",
    "why_this_action",
    "why_not_other_actions",
    "runtime_governance_plan",
    "post_action_learning_plan",
    "next_action_recommendation",
)

REQUIRED_STAGE_FIELDS: tuple[str, ...] = (
    "stage_id",
    "input_summary",
    "evidence_refs",
    "output_summary",
    "confidence_boundary",
    "missing_evidence",
    "runtime_governance_required",
    "CIEU_recording_required",
)

REQUIRED_COMMERCIAL_DIMENSIONS: tuple[str, ...] = (
    "buyer_pain_clarity",
    "urgency",
    "willingness_to_pay_proxy",
    "shortest_cash_path_fit",
    "differentiation",
    "proof_needed",
    "owner_execution_burden",
    "risk_of_wasting_time",
)

REQUIRED_RUNTIME_GOVERNANCE_REFS: tuple[str, ...] = (
    "Y-star-gov runtime hook",
    "E86 CIEUStore writer",
    "gov-mcp dry-run",
)

REQUIRED_NO_NEW_WHEEL_REFS: tuple[str, ...] = (
    "bridge-labs behavior center",
    "E88 runtime session",
    "Y-star-gov runtime hook",
    "E86 CIEU writer",
    "gov-mcp dry-run",
    "E87R baseline",
)

FORBIDDEN_COMPLETION_CLAIMS: tuple[str, ...] = (
    "L4_execution_claim",
    "L5_revenue_loop_complete",
    "customer_validation_claim",
    "paid_signal_claim",
    "pricing_validation_claim",
    "payment_loop_complete",
    "production_deployment_claim",
    "K9Audit_integration_claim",
)

FORBIDDEN_PRIVATE_REASONING_KEYS: tuple[str, ...] = (
    "chain_of_thought",
    "hidden_chain_of_thought",
    "private_chain_of_thought",
    "private_reasoning",
    "raw_model_reasoning",
)


def build_ceo_intelligence_operation_registry() -> dict[str, Any]:
    """Return the governance registry for structured CEO cognition stages."""

    operations: list[dict[str, Any]] = []
    for stage_id in REQUIRED_INTELLIGENCE_STAGE_IDS:
        operations.append(
            {
                "operation_id": stage_id,
                "owner_repo": "bridge-labs",
                "governance_owner_repo": "Y-star-gov",
                "required_inputs": ["input_summary", "evidence_refs"],
                "required_outputs": ["output_summary", "confidence_boundary"],
                "evidence_required": True,
                "runtime_decision_required": True,
                "CIEU_recording_required": True,
                "forbidden_claims": list(FORBIDDEN_COMPLETION_CLAIMS),
                "escalation_boundary": "owner authority required for external/L4/L5 actions",
            }
        )
    return {
        "registry_id": "ceo_intelligence_loop_runtime_operation_registry_v1",
        "operations": operations,
        "private_chain_of_thought_policy": "do_not_request_or_store_hidden_chain_of_thought",
    }


def validate_ceo_cognitive_operation_stage(stage: Mapping[str, Any]) -> CEOIntelligenceLoopDecision:
    if not isinstance(stage, Mapping):
        return _decision("DENY", "cognitive operation stage must be a mapping", {}, "stage_schema")
    missing = [field for field in REQUIRED_STAGE_FIELDS if field not in stage]
    if missing:
        return _revision_decision(
            "stage is missing required fields",
            stage,
            "stage_schema",
            missing_fields=missing,
        )
    if not _present(stage.get("evidence_refs")):
        return _revision_decision(
            "stage requires repository or historical evidence references",
            stage,
            str(stage.get("stage_id") or "stage_evidence"),
            required_packet_changes=["add evidence_refs for this cognitive operation stage"],
        )
    if _shallow(stage.get("output_summary")):
        return _revision_decision(
            "stage output is too shallow for governed CEO cognition",
            stage,
            str(stage.get("stage_id") or "stage_output"),
            required_packet_changes=["replace filler output with concrete structured decision evidence"],
        )
    return _decision("ALLOW", "cognitive operation stage is valid", stage)


def validate_ceo_intelligence_loop_packet(packet: Mapping[str, Any]) -> CEOIntelligenceLoopDecision:
    """Validate a structured CEO intelligence-loop packet."""

    if not isinstance(packet, Mapping):
        return _decision("DENY", "CEO intelligence loop packet must be a mapping", {}, "packet_schema")

    if any(key in packet for key in FORBIDDEN_PRIVATE_REASONING_KEYS):
        return _decision(
            "DENY",
            "private chain-of-thought fields must not be stored",
            packet,
            "private_reasoning_boundary",
            ["private_chain_of_thought_storage_forbidden"],
        )
    if packet.get("bypass_attempt") is True:
        return _decision("DENY", "bypass_attempt is forbidden", packet, "bypass_policy", ["bypass_attempt"])

    forbidden_claim = _forbidden_claim(packet)
    if forbidden_claim:
        return _decision(
            "DENY",
            f"forbidden completion claim present: {forbidden_claim}",
            packet,
            "overclaim_boundary",
            [forbidden_claim],
        )

    stages = packet.get("stages")
    if not isinstance(stages, list):
        return _revision_decision(
            "stages must be a list",
            packet,
            "intelligence_stage_registry",
            required_packet_changes=["attach structured intelligence stages"],
        )
    stage_by_id = {str(stage.get("stage_id")): stage for stage in stages if isinstance(stage, Mapping)}
    missing_stages = [stage_id for stage_id in REQUIRED_INTELLIGENCE_STAGE_IDS if stage_id not in stage_by_id]
    if missing_stages:
        return _revision_decision(
            "missing required intelligence stages",
            packet,
            "intelligence_stage_registry",
            missing_loop_stages=missing_stages,
        )
    for stage_id in REQUIRED_INTELLIGENCE_STAGE_IDS:
        stage_result = validate_ceo_cognitive_operation_stage(stage_by_id[stage_id])
        if stage_result.decision != CEOIntelligenceLoopDecisionValue.ALLOW:
            return _revision_decision(
                f"stage {stage_id} failed validation: {stage_result.reason}",
                packet,
                stage_id,
                required_packet_changes=stage_result.correct_path,
            )

    candidates = _as_list(packet.get("candidate_actions"))
    if len(candidates) < 3 and not _present(packet.get("justification_for_fewer_candidates")):
        return _revision_decision(
            "at least three candidate actions are required unless explicitly justified",
            packet,
            "candidate_action_generation",
            required_packet_changes=["add at least three candidate actions or justify why fewer are possible"],
        )
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            return _revision_decision(
                "candidate actions must be structured mappings",
                packet,
                "candidate_action_generation",
                required_packet_changes=["replace string candidates with structured candidate mappings"],
            )

    comparison = _as_list(packet.get("counterfactual_comparison"))
    if len(comparison) < 2:
        return _revision_decision(
            "counterfactual comparison must compare at least two candidates",
            packet,
            "counterfactual_action_comparison",
            required_packet_changes=["compare at least two candidates before selection"],
        )
    selected = packet.get("selected_action")
    selected_id = selected.get("candidate_id") if isinstance(selected, Mapping) else packet.get("selected_candidate_id")
    candidate_ids = {str(candidate.get("candidate_id")) for candidate in candidates if isinstance(candidate, Mapping)}
    if not selected_id or str(selected_id) not in candidate_ids:
        return _revision_decision(
            "selected action must reference a generated candidate",
            packet,
            "selected_action_decision",
            required_packet_changes=["set selected_action.candidate_id to one of the generated candidates"],
        )

    commercial = packet.get("commercial_sharpness_gate")
    if not isinstance(commercial, Mapping):
        return _revision_decision(
            "commercial sharpness gate is required",
            packet,
            "commercial_sharpness_gate",
            required_packet_changes=["add commercial_sharpness_gate scores"],
        )
    missing_dimensions = [
        dimension for dimension in REQUIRED_COMMERCIAL_DIMENSIONS if dimension not in commercial
    ]
    if missing_dimensions:
        return _revision_decision(
            "commercial sharpness gate is missing dimensions",
            packet,
            "commercial_sharpness_gate",
            missing_fields=missing_dimensions,
        )

    for key in (
        "speed_to_cash_evaluation",
        "risk_owner_burden_evaluation",
        "adversarial_critique",
        "what_not_to_do",
        "pre_action_CIEU_residual_prediction",
        "why_this_action",
        "why_not_other_actions",
        "post_action_learning_plan",
        "next_action_recommendation",
    ):
        if not _present(packet.get(key)):
            return _revision_decision(
                f"{key} is required",
                packet,
                key,
                missing_fields=[key],
            )

    no_new_wheel_text = _text(packet.get("no_new_wheel_gate"))
    missing_reuse = [ref for ref in REQUIRED_NO_NEW_WHEEL_REFS if ref.lower() not in no_new_wheel_text]
    if missing_reuse:
        return _revision_decision(
            "no-new-wheel gate must reference canonical reused systems",
            packet,
            "no_new_wheel_gate",
            required_packet_changes=["reference reused systems: " + ", ".join(missing_reuse)],
        )

    runtime_text = _text(packet.get("runtime_governance_plan"))
    missing_runtime_refs = [ref for ref in REQUIRED_RUNTIME_GOVERNANCE_REFS if ref.lower() not in runtime_text]
    if missing_runtime_refs:
        return _revision_decision(
            "runtime governance plan is missing required runtime owners",
            packet,
            "runtime_governance_plan",
            required_packet_changes=["map selected action to: " + ", ".join(missing_runtime_refs)],
        )

    if _selected_action_requires_owner(packet) and str(packet.get("owner_approval_state")) != "approved":
        return _decision(
            "ESCALATE",
            "selected action crosses owner/L4/L5/external authority boundary",
            packet,
            "owner_approval_gate",
            ["owner_decision_required"],
            guidance={
                "guidance_type": "owner_decision_required",
                "owner_decision_path": packet.get("owner_decision_path")
                or "prepare scoped owner decision packet before execution",
                "execution_allowed_before_owner_decision": False,
            },
            correct_path=[
                "generate owner decision packet for the selected action",
                "do not execute external/L4/L5 action before explicit owner approval",
                "rerun intelligence-loop validation after approval is recorded",
            ],
            requires_owner_decision=True,
        )

    return _decision("ALLOW", "CEO intelligence loop packet satisfies runtime governance contract", packet)


def build_ceo_intelligence_loop_cieu_record(
    packet: Mapping[str, Any],
    decision: CEOIntelligenceLoopDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, CEOIntelligenceLoopDecision) else dict(decision)
    decision_value = str(decision_data.get("decision") or "DENY")
    resolved_session_id = session_id or str(packet.get("session_id") or packet.get("intelligence_loop_id") or "ceo_intelligence_loop")
    selected = packet.get("selected_action") if isinstance(packet.get("selected_action"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": resolved_session_id,
        "agent_id": str(packet.get("agent_id") or "bridge_labs_ceo"),
        "event_type": CEO_INTELLIGENCE_LOOP_CIEU_EVENT_TYPE,
        "decision": _decision_to_cieu_decision(decision_value),
        "passed": decision_value == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_value != "ALLOW",
        "drift_details": None if decision_value == "ALLOW" else decision_data.get("reason"),
        "task_description": "CEO intelligence loop structured cognition runtime decision",
        "contract_hash": str(packet.get("Y_star_contract_hash_input") or "ceo-intelligence-loop-v1"),
        "params": {
            "intelligence_loop_id": packet.get("intelligence_loop_id"),
            "owner_intent": packet.get("owner_intent"),
            "stage_count": len(_as_list(packet.get("stages"))),
            "candidate_count": len(_as_list(packet.get("candidate_actions"))),
            "selected_candidate_id": selected.get("candidate_id") or packet.get("selected_candidate_id"),
            "structured_stage_outputs_only": True,
            "private_chain_of_thought_stored": False,
        },
        "result": {
            "decision": decision_value,
            "reason": decision_data.get("reason"),
            "failed_stage": decision_data.get("failed_stage"),
            "correct_path": list(decision_data.get("correct_path") or [])[:8],
            "selected_action": dict(selected),
            "commercial_sharpness_gate": dict(packet.get("commercial_sharpness_gate") or {}),
            "counterfactual_comparison_summary": list(_as_list(packet.get("counterfactual_comparison")))[:5],
            "runtime_governance_plan": packet.get("runtime_governance_plan"),
            "post_action_learning_plan": packet.get("post_action_learning_plan"),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": packet.get("human_initiator") or packet.get("owner_id"),
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_value == "ALLOW",
    }


def write_ceo_intelligence_loop_cieu_record(
    packet: Mapping[str, Any],
    decision: CEOIntelligenceLoopDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    if not cieu_db:
        raise ValueError("cieu_db is required")
    record = build_ceo_intelligence_loop_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_intelligence_loop_formal_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "formal_CIEU_log_module": "ystar.governance.ceo_intelligence_loop_contract",
        "formal_CIEU_log_function": "write_ceo_intelligence_loop_cieu_record",
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_intelligence_loop_packet(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_intelligence_loop_packet(packet)
    write_result = write_ceo_intelligence_loop_cieu_record(
        packet,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_intelligence_loop_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _decision(
    value: str,
    reason: str,
    packet: Mapping[str, Any],
    failed_stage: str | None = None,
    violations: list[str] | None = None,
    *,
    guidance: dict[str, Any] | None = None,
    correct_path: list[str] | None = None,
    requires_owner_decision: bool = False,
) -> CEOIntelligenceLoopDecision:
    decision_value = CEOIntelligenceLoopDecisionValue(value)
    provisional = CEOIntelligenceLoopDecision(
        decision=decision_value,
        reason=reason,
        failed_stage=failed_stage,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
    )
    return CEOIntelligenceLoopDecision(
        decision=decision_value,
        reason=reason,
        failed_stage=failed_stage,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
        cieu_validation_record=_build_validation_candidate(packet, provisional),
    )


def _revision_decision(
    reason: str,
    packet: Mapping[str, Any],
    failed_stage: str,
    *,
    missing_fields: list[str] | None = None,
    missing_loop_stages: list[str] | None = None,
    required_packet_changes: list[str] | None = None,
) -> CEOIntelligenceLoopDecision:
    missing_fields = missing_fields or []
    missing_loop_stages = missing_loop_stages or []
    required_packet_changes = required_packet_changes or []
    correct_path = [
        "repair the structured CEO intelligence loop packet before runtime acceptance",
        "do not execute selected action while decision is REQUIRE_REVISION",
        "rerun validate_ceo_intelligence_loop_packet after repair",
    ]
    if missing_fields:
        correct_path.append("fill missing fields: " + ", ".join(missing_fields))
    if missing_loop_stages:
        correct_path.append("complete missing intelligence stages: " + ", ".join(missing_loop_stages[:8]))
    correct_path.extend(required_packet_changes)
    guidance = {
        "guidance_type": "require_revision",
        "failed_stage": failed_stage,
        "missing_fields": missing_fields,
        "missing_loop_stages": missing_loop_stages,
        "required_packet_changes": required_packet_changes,
        "correct_path": correct_path,
        "execution_allowed_before_revision": False,
        "revalidate_after_revision": True,
    }
    return _decision(
        "REQUIRE_REVISION",
        reason,
        packet,
        failed_stage,
        list(missing_fields or missing_loop_stages or required_packet_changes),
        guidance=guidance,
        correct_path=correct_path,
    )


def _build_validation_candidate(packet: Mapping[str, Any], decision: CEOIntelligenceLoopDecision) -> dict[str, Any]:
    return {
        "X_t": {
            "contract_id": "ceo_intelligence_loop_runtime_contract_v1",
            "intelligence_loop_id": packet.get("intelligence_loop_id"),
        },
        "U_t": "Y-star-gov structured CEO intelligence-loop governance validation",
        "Y_star_t": "CEO thinking-as-behavior must be evidence-backed, governed, and recordable",
        "Y_t_plus_1": {
            "decision": decision.decision.value,
            "reason": decision.reason,
            "failed_stage": decision.failed_stage,
            "correct_path": list(decision.correct_path),
        },
        "R_t_plus_1": "none" if decision.decision == CEOIntelligenceLoopDecisionValue.ALLOW else decision.reason,
    }


def _decision_to_cieu_decision(value: str) -> str:
    return {
        "ALLOW": "allow",
        "REQUIRE_REVISION": "rewrite",
        "DENY": "deny",
        "ESCALATE": "escalate",
    }.get(value, "unknown")


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}):
        return []
    return [value]


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


def _shallow(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if len(text) < 18:
        return True
    return text in {"todo", "tbd", "n/a", "generic output", "good", "pass", "done"}


def _forbidden_claim(packet: Mapping[str, Any]) -> str:
    checks = packet.get("overclaim_boundary") or packet.get("truth_constraints") or {}
    if isinstance(checks, Mapping):
        for field in FORBIDDEN_COMPLETION_CLAIMS:
            if checks.get(field) is True:
                return field
    text = _text(packet)
    for phrase in (
        "l5 revenue loop complete",
        "customer validation complete",
        "paid signal achieved",
        "payment loop complete",
        "production deployment complete",
        "k9audit integration complete",
    ):
        if phrase in text:
            return phrase
    return ""


def _selected_action_requires_owner(packet: Mapping[str, Any]) -> bool:
    selected_text = _text(packet.get("selected_action"))
    route_type = ""
    selected = packet.get("selected_action")
    if isinstance(selected, Mapping):
        route_type = str(selected.get("route_type") or "").lower()
    if route_type in {"internal_runtime", "provider_tool_dry_run"}:
        return False
    if route_type in {
        "owner_decision_required",
        "external_feedback_candidate",
        "revenue_path_candidate",
    }:
        return True
    return any(term in selected_text for term in ("external execution", "l4 execution", "l5", "revenue_path_candidate"))


__all__ = [
    "CEO_INTELLIGENCE_LOOP_CIEU_EVENT_TYPE",
    "FORMAL_CIEU_LOG_PATH",
    "CEOIntelligenceLoopDecision",
    "CEOIntelligenceLoopDecisionValue",
    "REQUIRED_INTELLIGENCE_STAGE_IDS",
    "build_ceo_intelligence_operation_registry",
    "build_ceo_intelligence_loop_cieu_record",
    "validate_ceo_cognitive_operation_stage",
    "validate_ceo_intelligence_loop_packet",
    "validate_and_write_ceo_intelligence_loop_packet",
    "write_ceo_intelligence_loop_cieu_record",
]
