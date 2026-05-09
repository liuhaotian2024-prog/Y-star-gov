"""Governance for adaptive retrieval and capability invocation planning.

E125 made retrieval mandatory.  This contract makes retrieval *adaptive*: Aiden
must infer what evidence and existing capabilities a task needs, reuse the
governed discovery/no-new-wheel/operating-pattern/unknown-problem mechanisms,
and only then call the retrieval orchestrator.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


AIDEN_ADAPTIVE_RETRIEVAL_PLANNER_EVENT_TYPE = "AIDEN_ADAPTIVE_RETRIEVAL_PLANNER_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_PACKET_SECTIONS = (
    "planner_id",
    "task_context",
    "evidence_need_analysis",
    "governance_obligation_discovery",
    "existing_capability_recall",
    "operating_pattern_selection",
    "unknown_problem_learning_assessment",
    "dynamic_retrieval_plan",
    "capability_invocation_plan",
    "retrieval_orchestration_binding",
    "self_improvement_path",
    "CIEU_linkage",
    "truth_constraints",
)

MANDATORY_MECHANISMS = {
    "E101_adaptive_governance_correct_path",
    "E113_no_new_wheel_runtime_law",
    "E119_operating_pattern_doctrine_registry",
    "E120_unknown_problem_learning_protocol",
    "E125_retrieval_orchestration_runtime",
}

BASE_EVIDENCE_FAMILIES = {
    "repo_capability_evidence",
    "brain_provenance",
    "code_index_or_baseline",
    "CIEU_history",
    "long_term_memory_status",
}

STRATEGY_EVIDENCE_FAMILIES = {
    "current_market_evidence_or_public_read_route",
    "competitor_and_substitute_evidence",
    "buyer_visible_value_evidence",
    "classical_theory_or_case_corpus",
}

IMPLEMENTATION_EVIDENCE_FAMILIES = {
    "existing_code_paths",
    "tests_and_contracts",
    "delivery_boundary",
}

FORBIDDEN_TRUE_CLAIMS = (
    "recent_memory_only",
    "fixed_retrieval_list_only",
    "adaptive_planning_bypassed",
    "no_new_wheel_bypassed",
    "unknown_problem_protocol_bypassed",
    "operating_pattern_registry_bypassed",
    "external_action_executed",
    "provider_action_executed",
    "customer_validation_claim",
    "revenue_claim",
    "payment_claim",
    "live_provider_execution_claim",
    "K9Audit_write_claim",
    "hidden_chain_of_thought_stored",
    "CIEU_recording_bypassed",
)


class AidenAdaptiveRetrievalPlannerDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class AidenAdaptiveRetrievalPlannerDecision:
    decision: AidenAdaptiveRetrievalPlannerDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "aiden_adaptive_retrieval_planner_decision",
            "decision": self.decision.value,
            "passed": self.decision == AidenAdaptiveRetrievalPlannerDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "guidance": dict(self.guidance),
        }


def build_aiden_adaptive_retrieval_planner_contract() -> dict[str, Any]:
    return {
        "contract_id": "aiden_adaptive_retrieval_planner_contract_v1",
        "event_type": AIDEN_ADAPTIVE_RETRIEVAL_PLANNER_EVENT_TYPE,
        "principle": "Aiden must plan evidence needs and existing capability invocation before retrieval.",
        "mandatory_mechanisms": sorted(MANDATORY_MECHANISMS),
        "base_evidence_families": sorted(BASE_EVIDENCE_FAMILIES),
        "strategy_evidence_families": sorted(STRATEGY_EVIDENCE_FAMILIES),
        "implementation_evidence_families": sorted(IMPLEMENTATION_EVIDENCE_FAMILIES),
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
    }


def validate_aiden_adaptive_retrieval_planner_packet(packet: Mapping[str, Any]) -> AidenAdaptiveRetrievalPlannerDecision:
    if not isinstance(packet, Mapping):
        return _deny("adaptive retrieval planner packet must be a mapping", "schema", ["packet_not_mapping"])

    missing = [field for field in REQUIRED_PACKET_SECTIONS if field not in packet]
    if missing:
        return _revision(
            "adaptive retrieval planner packet is missing required sections",
            "schema",
            [f"add section {field}" for field in missing],
        )

    truth = _mapping(packet.get("truth_constraints"))
    forbidden = [field for field in FORBIDDEN_TRUE_CLAIMS if truth.get(field) is True]
    if forbidden:
        return _deny("adaptive retrieval planner contains bypass or overclaim", "truth_constraints", forbidden)

    context = _mapping(packet.get("task_context"))
    if not context.get("owner_message") and not context.get("task_objective"):
        return _revision("task context must contain owner_message or task_objective", "task_context", ["include the concrete owner/task intent"])
    if context.get("planning_mode") != "adaptive_evidence_need_and_capability_invocation":
        return _revision(
            "planner must run in adaptive planning mode",
            "task_context",
            ["set planning_mode=adaptive_evidence_need_and_capability_invocation"],
        )

    evidence_decision = _validate_evidence_need_analysis(_mapping(packet.get("evidence_need_analysis")), context)
    if evidence_decision:
        return evidence_decision

    obligation_decision = _validate_governance_obligation_discovery(_mapping(packet.get("governance_obligation_discovery")))
    if obligation_decision:
        return obligation_decision

    capability_decision = _validate_existing_capability_recall(_mapping(packet.get("existing_capability_recall")))
    if capability_decision:
        return capability_decision

    pattern_decision = _validate_operating_patterns(_mapping(packet.get("operating_pattern_selection")), context)
    if pattern_decision:
        return pattern_decision

    unknown_decision = _validate_unknown_problem_assessment(_mapping(packet.get("unknown_problem_learning_assessment")), context)
    if unknown_decision:
        return unknown_decision

    retrieval_decision = _validate_dynamic_retrieval_plan(_mapping(packet.get("dynamic_retrieval_plan")), context)
    if retrieval_decision:
        return retrieval_decision

    invocation_decision = _validate_invocation_plan(_mapping(packet.get("capability_invocation_plan")))
    if invocation_decision:
        return invocation_decision

    binding_decision = _validate_retrieval_binding(_mapping(packet.get("retrieval_orchestration_binding")))
    if binding_decision:
        return binding_decision

    improvement_decision = _validate_self_improvement_path(_mapping(packet.get("self_improvement_path")))
    if improvement_decision:
        return improvement_decision

    cieu_decision = _validate_cieu_linkage(_mapping(packet.get("CIEU_linkage")))
    if cieu_decision:
        return cieu_decision

    return AidenAdaptiveRetrievalPlannerDecision(
        decision=AidenAdaptiveRetrievalPlannerDecisionValue.ALLOW,
        reason="adaptive retrieval planner selected evidence needs, existing capability invocations, unknown-problem learning checks, and E125 retrieval binding",
        correct_path=["execute E125 retrieval with the validated dynamic plan and bind retrieval context to Aiden's answer/action"],
        guidance={
            "planner_id": packet.get("planner_id"),
            "required_mechanisms": sorted(MANDATORY_MECHANISMS),
            "retrieval_source_count": len(_list(_mapping(packet.get("dynamic_retrieval_plan")).get("planned_source_ids"))),
            "capability_count": len(_list(_mapping(packet.get("capability_invocation_plan")).get("invocations"))),
        },
    )


def build_aiden_adaptive_retrieval_planner_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenAdaptiveRetrievalPlannerDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, AidenAdaptiveRetrievalPlannerDecision) else dict(decision)
    context = _mapping(packet.get("task_context"))
    retrieval_plan = _mapping(packet.get("dynamic_retrieval_plan"))
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(packet.get("planner_id") or "aiden_adaptive_retrieval_planner"),
        "agent_id": str(context.get("agent_id") or "Aiden"),
        "event_type": AIDEN_ADAPTIVE_RETRIEVAL_PLANNER_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "Aiden adaptive retrieval planner validation",
        "contract_hash": "aiden-adaptive-retrieval-planner-v1",
        "params": {
            "planner_id": packet.get("planner_id"),
            "task_type": context.get("task_type"),
            "planned_source_ids": list(retrieval_plan.get("planned_source_ids") or []),
        },
        "result": {
            "decision": data.get("decision"),
            "reason": data.get("reason"),
            "correct_path": list(data.get("correct_path") or []),
            "guidance": dict(data.get("guidance") or {}),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "adaptive-retrieval-planner", "Y-star-gov", "CIEUStore", "E125-retrieval"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": data.get("decision") == "ALLOW",
    }


def validate_and_write_aiden_adaptive_retrieval_planner_packet(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_aiden_adaptive_retrieval_planner_packet(packet)
    record = build_aiden_adaptive_retrieval_planner_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "aiden_adaptive_retrieval_planner_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "CIEU_write_result": {"event_type": record["event_type"], "event_id": record["event_id"], "CIEU_record": record},
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def _validate_evidence_need_analysis(analysis: Mapping[str, Any], context: Mapping[str, Any]) -> AidenAdaptiveRetrievalPlannerDecision | None:
    if analysis.get("adaptive_analysis_performed") is not True:
        return _revision("evidence need analysis must be adaptive", "evidence_need_analysis", ["set adaptive_analysis_performed=true"])
    families = set(_list(analysis.get("required_evidence_families")))
    missing_base = sorted(BASE_EVIDENCE_FAMILIES - families)
    if missing_base:
        return _revision("base evidence families are missing", "evidence_need_analysis", [f"add evidence family {item}" for item in missing_base])
    if context.get("market_strategy_required") is True:
        missing_strategy = sorted(STRATEGY_EVIDENCE_FAMILIES - families)
        if missing_strategy:
            return _revision("strategy task is missing market/competitor/theory evidence families", "evidence_need_analysis", [f"add evidence family {item}" for item in missing_strategy])
    if context.get("implementation_required") is True:
        missing_impl = sorted(IMPLEMENTATION_EVIDENCE_FAMILIES - families)
        if missing_impl:
            return _revision("implementation task is missing code/test/delivery evidence families", "evidence_need_analysis", [f"add evidence family {item}" for item in missing_impl])
    if not _list(analysis.get("unknowns_to_resolve")):
        return _revision("planner must name unknowns to resolve", "evidence_need_analysis", ["include unknowns_to_resolve before retrieval"])
    return None


def _validate_governance_obligation_discovery(discovery: Mapping[str, Any]) -> AidenAdaptiveRetrievalPlannerDecision | None:
    if discovery.get("mechanism_id") != "E101_adaptive_governance_correct_path":
        return _revision("E101 adaptive governance discovery must be used", "governance_obligation_discovery", ["invoke E101 adaptive governance discovery"])
    if discovery.get("discovery_performed") is not True:
        return _revision("governance obligation discovery was not performed", "governance_obligation_discovery", ["set discovery_performed=true with discovered obligations"])
    if not _list(discovery.get("required_obligations")):
        return _revision("required obligations cannot be empty", "governance_obligation_discovery", ["include E101 required_obligations or explicit no-op reason"])
    return None


def _validate_existing_capability_recall(recall: Mapping[str, Any]) -> AidenAdaptiveRetrievalPlannerDecision | None:
    if recall.get("mechanism_id") != "E113_no_new_wheel_runtime_law":
        return _revision("E113 no-new-wheel capability recall must be used", "existing_capability_recall", ["invoke E113 no-new-wheel runtime law"])
    if recall.get("full_system_capability_scan_performed") is not True:
        return _revision("full-system capability scan must be performed", "existing_capability_recall", ["scan bridge-labs, Y-star-gov, and gov-mcp"])
    if recall.get("recent_memory_only") is True:
        return _deny("recent memory cannot satisfy capability recall", "existing_capability_recall", ["recent_memory_only"])
    if int(recall.get("runtime_active_capability_count") or 0) < 5:
        return _revision("too few runtime-active capabilities were surfaced", "existing_capability_recall", ["load E113 capability index and E87R code index"])
    if not _list(recall.get("matched_capability_domains")):
        return _revision("matched capability domains cannot be empty", "existing_capability_recall", ["map action context to existing capabilities"])
    return None


def _validate_operating_patterns(patterns: Mapping[str, Any], context: Mapping[str, Any]) -> AidenAdaptiveRetrievalPlannerDecision | None:
    if patterns.get("mechanism_id") != "E119_operating_pattern_doctrine_registry":
        return _revision("E119 operating pattern registry must be used", "operating_pattern_selection", ["invoke E119 operating pattern registry"])
    selected = set(_list(patterns.get("selected_pattern_ids")))
    base = {"no_new_wheel_preflight", "capability_utilization_sweep", "class_level_extrapolation_gate", "correct_path_navigation"}
    missing = sorted(base - selected)
    if missing:
        return _revision("base operating patterns were not selected", "operating_pattern_selection", [f"select {item}" for item in missing])
    if context.get("unknown_problem_related") is True and "unknown_problem_learning_protocol" not in selected:
        return _revision("unknown tasks must select unknown-problem learning pattern", "operating_pattern_selection", ["select unknown_problem_learning_protocol"])
    return None


def _validate_unknown_problem_assessment(assessment: Mapping[str, Any], context: Mapping[str, Any]) -> AidenAdaptiveRetrievalPlannerDecision | None:
    if assessment.get("mechanism_id") != "E120_unknown_problem_learning_protocol":
        return _revision("E120 unknown-problem protocol must be assessed", "unknown_problem_learning_assessment", ["assess E120 unknown-problem learning protocol"])
    if assessment.get("assessment_performed") is not True:
        return _revision("unknown-problem assessment was not performed", "unknown_problem_learning_assessment", ["set assessment_performed=true"])
    if context.get("unknown_problem_related") is True:
        if assessment.get("protocol_invocation_status") not in {"invoked", "bound"}:
            return _revision("unknown problem requires E120 protocol invocation", "unknown_problem_learning_assessment", ["invoke or bind E120 unknown-problem learning protocol"])
        if not _list(assessment.get("learning_objectives")):
            return _revision("unknown-problem protocol needs learning objectives", "unknown_problem_learning_assessment", ["include learning objectives from E120"])
    return None


def _validate_dynamic_retrieval_plan(plan: Mapping[str, Any], context: Mapping[str, Any]) -> AidenAdaptiveRetrievalPlannerDecision | None:
    if plan.get("plan_mode") != "adaptive_dynamic_source_selection":
        return _revision("dynamic retrieval plan must not be a fixed-only list", "dynamic_retrieval_plan", ["set plan_mode=adaptive_dynamic_source_selection"])
    sources = set(_list(plan.get("planned_source_ids")))
    required = {"repo_evidence_index", "aiden_6d_brain", "code_index_or_capability_map", "cieu_store_history", "local_vector_rag", "e123_memory_asset_discovery"}
    missing = sorted(required - sources)
    if missing:
        return _revision("dynamic retrieval plan omits mandatory local sources", "dynamic_retrieval_plan", [f"add source {item}" for item in missing])
    if context.get("market_strategy_required") is True and "external_public_read_runtime" not in sources and "open_world_strategy_runtime" not in sources:
        return _revision("market strategy requires public-read/open-world route in retrieval plan", "dynamic_retrieval_plan", ["add external_public_read_runtime or open_world_strategy_runtime"])
    if not _list(plan.get("source_selection_rationale")):
        return _revision("dynamic retrieval plan needs source selection rationale", "dynamic_retrieval_plan", ["explain why each source family is selected"])
    return None


def _validate_invocation_plan(plan: Mapping[str, Any]) -> AidenAdaptiveRetrievalPlannerDecision | None:
    invocations = _list(plan.get("invocations"))
    mechanism_ids = {str(item.get("mechanism_id")) for item in invocations if isinstance(item, Mapping)}
    missing = sorted(MANDATORY_MECHANISMS - mechanism_ids)
    if missing:
        return _revision("capability invocation plan is missing mandatory mechanisms", "capability_invocation_plan", [f"invoke or bind {item}" for item in missing])
    for item in invocations:
        if not isinstance(item, Mapping):
            return _revision("each invocation must be a mapping", "capability_invocation_plan", ["complete invocation rows"])
        if item.get("invocation_status") not in {"invoked", "bound", "will_invoke_after_validation"}:
            return _revision("invocation has invalid status", "capability_invocation_plan", [f"fix invocation_status for {item.get('mechanism_id')}"])
        if not item.get("evidence_refs"):
            return _revision("each invocation needs evidence refs", "capability_invocation_plan", [f"add evidence_refs for {item.get('mechanism_id')}"])
    return None


def _validate_retrieval_binding(binding: Mapping[str, Any]) -> AidenAdaptiveRetrievalPlannerDecision | None:
    if binding.get("E125_bound") is not True:
        return _revision("E125 retrieval orchestration must be bound after adaptive planning", "retrieval_orchestration_binding", ["set E125_bound=true"])
    if binding.get("execute_E125_after_planner_allow") is not True:
        return _revision("E125 must execute only after planner ALLOW", "retrieval_orchestration_binding", ["set execute_E125_after_planner_allow=true"])
    if binding.get("raw_answer_before_retrieval_allowed") is True:
        return _deny("raw answer before retrieval is forbidden", "retrieval_orchestration_binding", ["raw_answer_before_retrieval_allowed"])
    return None


def _validate_self_improvement_path(path: Mapping[str, Any]) -> AidenAdaptiveRetrievalPlannerDecision | None:
    if path.get("new_capability_discovery_supported") is not True:
        return _revision("planner must support future new capability discovery", "self_improvement_path", ["set new_capability_discovery_supported=true"])
    if path.get("self_governance_proposal_on_gap") is not True:
        return _revision("planner must propose governance updates for repeatable gaps", "self_improvement_path", ["set self_governance_proposal_on_gap=true"])
    if path.get("direct_contract_mutation_allowed") is True:
        return _deny("Aiden may not directly mutate governance contracts", "self_improvement_path", ["direct_contract_mutation_allowed"])
    return None


def _validate_cieu_linkage(linkage: Mapping[str, Any]) -> AidenAdaptiveRetrievalPlannerDecision | None:
    if linkage.get("CIEU_recording_required") is not True:
        return _revision("adaptive retrieval planner must be CIEU-recorded", "CIEU_linkage", ["set CIEU_recording_required=true"])
    if linkage.get("target_event_type") != AIDEN_ADAPTIVE_RETRIEVAL_PLANNER_EVENT_TYPE:
        return _revision("wrong CIEU event type", "CIEU_linkage", [f"set target_event_type={AIDEN_ADAPTIVE_RETRIEVAL_PLANNER_EVENT_TYPE}"])
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _revision(reason: str, section: str, correct_path: list[str]) -> AidenAdaptiveRetrievalPlannerDecision:
    return AidenAdaptiveRetrievalPlannerDecision(
        decision=AidenAdaptiveRetrievalPlannerDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=section,
        correct_path=correct_path,
        guidance={"navigation": correct_path},
    )


def _deny(reason: str, section: str, violations: list[str]) -> AidenAdaptiveRetrievalPlannerDecision:
    return AidenAdaptiveRetrievalPlannerDecision(
        decision=AidenAdaptiveRetrievalPlannerDecisionValue.DENY,
        reason=reason,
        failed_section=section,
        violations=violations,
        correct_path=["remove bypass/overclaim and rebuild adaptive retrieval planner packet"],
    )
