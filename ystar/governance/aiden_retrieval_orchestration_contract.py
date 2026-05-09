"""Governed retrieval orchestration contract for Aiden.

This contract makes retrieval a first-class governed behavior.  Aiden must not
answer from recent chat memory alone when a serious owner/CEO task is active.
Instead it must build a retrieval packet that proves which memory and evidence
systems were queried, which were unavailable, what evidence was retrieved, and
how the retrieved context is bound to the downstream answer or action.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


AIDEN_RETRIEVAL_ORCHESTRATION_EVENT_TYPE = "AIDEN_RETRIEVAL_ORCHESTRATION_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_PACKET_SECTIONS = (
    "retrieval_id",
    "task_context",
    "retrieval_plan",
    "retrieval_sources",
    "retrieved_evidence_pack",
    "source_coverage",
    "sufficiency_assessment",
    "downstream_binding",
    "CIEU_linkage",
    "truth_constraints",
)

MANDATORY_SOURCE_IDS = (
    "repo_evidence_index",
    "aiden_6d_brain",
    "code_index_or_capability_map",
    "cieu_store_history",
    "ystar_memory_store",
    "local_vector_rag",
)

OPTIONAL_SOURCE_IDS = (
    "e123_memory_asset_discovery",
    "external_public_read_runtime",
)

VALID_SOURCE_STATUSES = {
    "queried",
    "available",
    "empty",
    "unavailable_declared",
    "not_configured",
    "dependency_unavailable",
    "blocked_by_policy",
}

FORBIDDEN_TRUE_CLAIMS = (
    "recent_memory_only",
    "raw_natural_language_only_answer",
    "retrieval_bypassed",
    "static_template_only",
    "external_web_research_claim_without_provider",
    "customer_validation_claim",
    "revenue_claim",
    "payment_claim",
    "live_provider_execution_claim",
    "K9Audit_write_claim",
    "hidden_chain_of_thought_stored",
    "CIEU_recording_bypassed",
)


class AidenRetrievalOrchestrationDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class AidenRetrievalOrchestrationDecision:
    decision: AidenRetrievalOrchestrationDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "aiden_retrieval_orchestration_decision",
            "decision": self.decision.value,
            "passed": self.decision == AidenRetrievalOrchestrationDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "guidance": dict(self.guidance),
        }


def build_aiden_retrieval_orchestration_contract() -> dict[str, Any]:
    return {
        "contract_id": "aiden_retrieval_orchestration_contract_v1",
        "event_type": AIDEN_RETRIEVAL_ORCHESTRATION_EVENT_TYPE,
        "principle": "Aiden must retrieve from governed local memory and evidence systems before substantive answers or actions.",
        "mandatory_source_ids": list(MANDATORY_SOURCE_IDS),
        "optional_source_ids": list(OPTIONAL_SOURCE_IDS),
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "non_goals": [
            "no external side effect",
            "no live provider execution",
            "no hidden chain-of-thought storage",
            "no customer, revenue, or payment validation claim",
        ],
    }


def validate_aiden_retrieval_orchestration_packet(packet: Mapping[str, Any]) -> AidenRetrievalOrchestrationDecision:
    if not isinstance(packet, Mapping):
        return _deny("retrieval orchestration packet must be a mapping", "schema", ["packet_not_mapping"])

    missing = [field for field in REQUIRED_PACKET_SECTIONS if field not in packet]
    if missing:
        return _revision(
            "retrieval packet is missing required sections",
            "schema",
            [f"add section {field}" for field in missing],
        )

    truth = _mapping(packet.get("truth_constraints"))
    forbidden = [field for field in FORBIDDEN_TRUE_CLAIMS if truth.get(field) is True]
    if forbidden:
        return _deny("retrieval packet contains bypass or overclaim", "truth_constraints", forbidden)

    context = _mapping(packet.get("task_context"))
    if not context.get("owner_message") and not context.get("task_objective"):
        return _revision(
            "retrieval task context must contain owner_message or task_objective",
            "task_context",
            ["include the concrete owner intent or runtime task objective before retrieval"],
        )
    if context.get("generation_mode") in {"recent_memory_only", "static_template_only"}:
        return _revision(
            "retrieval cannot be satisfied by recent memory or static templates",
            "task_context",
            ["set generation_mode to retrieval_orchestrated_structured_output and query governed sources"],
        )

    plan_decision = _validate_retrieval_plan(_mapping(packet.get("retrieval_plan")))
    if plan_decision:
        return plan_decision

    sources_decision = _validate_retrieval_sources(_list(packet.get("retrieval_sources")), context)
    if sources_decision:
        return sources_decision

    evidence_decision = _validate_retrieved_evidence_pack(_mapping(packet.get("retrieved_evidence_pack")), context)
    if evidence_decision:
        return evidence_decision

    coverage_decision = _validate_source_coverage(_mapping(packet.get("source_coverage")))
    if coverage_decision:
        return coverage_decision

    sufficiency_decision = _validate_sufficiency(_mapping(packet.get("sufficiency_assessment")), context)
    if sufficiency_decision:
        return sufficiency_decision

    downstream_decision = _validate_downstream_binding(_mapping(packet.get("downstream_binding")))
    if downstream_decision:
        return downstream_decision

    cieu_decision = _validate_cieu_linkage(_mapping(packet.get("CIEU_linkage")))
    if cieu_decision:
        return cieu_decision

    guidance = {
        "retrieval_id": packet.get("retrieval_id"),
        "queried_source_count": len(_list(packet.get("retrieval_sources"))),
        "evidence_count": len(_list(_mapping(packet.get("retrieved_evidence_pack")).get("evidence_items"))),
        "mandatory_source_ids": list(MANDATORY_SOURCE_IDS),
        "correct_next_step": "use the retrieved evidence pack as context for Aiden's answer or action packet",
    }
    return AidenRetrievalOrchestrationDecision(
        decision=AidenRetrievalOrchestrationDecisionValue.ALLOW,
        reason="retrieval orchestration queried mandatory local evidence systems, declared unavailable systems honestly, and is safe for downstream Aiden use",
        correct_path=["bind retrieved_evidence_pack into the downstream Aiden answer/action and record the CIEU decision"],
        guidance=guidance,
    )


def build_aiden_retrieval_orchestration_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenRetrievalOrchestrationDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, AidenRetrievalOrchestrationDecision) else dict(decision)
    evidence_pack = _mapping(packet.get("retrieved_evidence_pack"))
    coverage = _mapping(packet.get("source_coverage"))
    context = _mapping(packet.get("task_context"))
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(packet.get("retrieval_id") or "aiden_retrieval_orchestration"),
        "agent_id": str(context.get("agent_id") or "Aiden"),
        "event_type": AIDEN_RETRIEVAL_ORCHESTRATION_EVENT_TYPE,
        "decision": "ALLOW" if decision_data.get("decision") == "ALLOW" else "DENY",
        "passed": decision_data.get("decision") == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_data.get("decision") != "ALLOW",
        "drift_details": None if decision_data.get("decision") == "ALLOW" else decision_data.get("reason"),
        "task_description": "Aiden governed retrieval orchestration validation",
        "contract_hash": "aiden-retrieval-orchestration-v1",
        "params": {
            "retrieval_id": packet.get("retrieval_id"),
            "task_type": context.get("task_type"),
            "source_count": len(_list(packet.get("retrieval_sources"))),
            "evidence_count": len(_list(evidence_pack.get("evidence_items"))),
            "mandatory_source_ids": list(MANDATORY_SOURCE_IDS),
        },
        "result": {
            "decision": decision_data.get("decision"),
            "reason": decision_data.get("reason"),
            "correct_path": list(decision_data.get("correct_path") or []),
            "guidance": dict(decision_data.get("guidance") or {}),
            "source_coverage": dict(coverage),
            "evidence_refs": [item.get("evidence_ref") for item in _list(evidence_pack.get("evidence_items"))[:20]],
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "retrieval-orchestration", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_data.get("decision") == "ALLOW",
    }


def write_aiden_retrieval_orchestration_cieu_record(record: Mapping[str, Any], *, cieu_db: str) -> bool:
    return bool(CIEUStore(cieu_db).write_dict(dict(record)))


def validate_and_write_aiden_retrieval_orchestration_packet(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_aiden_retrieval_orchestration_packet(packet)
    record = build_aiden_retrieval_orchestration_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "aiden_retrieval_orchestration_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "CIEU_write_result": {"event_type": record["event_type"], "event_id": record["event_id"], "CIEU_record": record},
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def _validate_retrieval_plan(plan: Mapping[str, Any]) -> AidenRetrievalOrchestrationDecision | None:
    if plan.get("retrieval_required_before_answer") is not True:
        return _revision(
            "retrieval plan must require retrieval before Aiden answers",
            "retrieval_plan",
            ["set retrieval_required_before_answer=true and run retrieval orchestration first"],
        )
    mandatory = set(_list(plan.get("mandatory_source_ids")))
    missing = [source_id for source_id in MANDATORY_SOURCE_IDS if source_id not in mandatory]
    if missing:
        return _revision(
            "retrieval plan is missing mandatory source ids",
            "retrieval_plan",
            [f"add mandatory source {source_id}" for source_id in missing],
        )
    if plan.get("recent_memory_only_allowed") is True:
        return _deny("recent-memory-only retrieval is forbidden", "retrieval_plan", ["recent_memory_only_allowed"])
    return None


def _validate_retrieval_sources(
    sources: list[Any],
    context: Mapping[str, Any],
) -> AidenRetrievalOrchestrationDecision | None:
    if not sources:
        return _revision(
            "retrieval_sources cannot be empty",
            "retrieval_sources",
            ["query repo, brain, code/capability, CIEU, Y-star memory, and vector RAG status"],
        )
    by_id = {str(_mapping(source).get("source_id")): _mapping(source) for source in sources}
    missing = [source_id for source_id in MANDATORY_SOURCE_IDS if source_id not in by_id]
    if missing:
        return _revision(
            "mandatory retrieval sources were not queried or declared",
            "retrieval_sources",
            [f"query or declare unavailable source {source_id}" for source_id in missing],
        )

    for source_id, source in by_id.items():
        status = source.get("retrieval_status")
        if status not in VALID_SOURCE_STATUSES:
            return _revision(
                f"retrieval source {source_id} has invalid status",
                "retrieval_sources",
                [f"use one of {sorted(VALID_SOURCE_STATUSES)}"],
            )
        if status in {"unavailable_declared", "not_configured", "dependency_unavailable", "blocked_by_policy"}:
            if not source.get("unavailable_reason") or not source.get("correct_path"):
                return _revision(
                    f"unavailable source {source_id} must include reason and correct path",
                    "retrieval_sources",
                    [f"add unavailable_reason and correct_path for {source_id}"],
                )

    if context.get("external_public_read_required") is True:
        external = by_id.get("external_public_read_runtime")
        if not external or external.get("retrieval_status") in {"unavailable_declared", "not_configured", "blocked_by_policy"}:
            return _revision(
                "external public-read was required but not proven",
                "retrieval_sources",
                ["run the governed public-read provider or mark the downstream action as not fully market-grounded"],
            )
    return None


def _validate_retrieved_evidence_pack(
    pack: Mapping[str, Any],
    context: Mapping[str, Any],
) -> AidenRetrievalOrchestrationDecision | None:
    items = _list(pack.get("evidence_items"))
    if len(items) < 3:
        return _revision(
            "retrieved evidence pack is too sparse",
            "retrieved_evidence_pack",
            ["retrieve at least three structured evidence items before answering"],
        )
    families = {str(_mapping(item).get("source_id")) for item in items if _mapping(item).get("source_id")}
    required_family_count = 4 if _task_is_major(context) else 3
    if len(families) < required_family_count:
        return _revision(
            "retrieved evidence pack lacks source-family diversity",
            "retrieved_evidence_pack",
            [f"retrieve evidence from at least {required_family_count} source families"],
        )
    for item in items:
        item_map = _mapping(item)
        for field in ("source_id", "evidence_ref", "summary", "runtime_status"):
            if not item_map.get(field):
                return _revision(
                    "each evidence item must include source_id, evidence_ref, summary, and runtime_status",
                    "retrieved_evidence_pack",
                    [f"add field {field} to all evidence items"],
                )
    return None


def _validate_source_coverage(coverage: Mapping[str, Any]) -> AidenRetrievalOrchestrationDecision | None:
    queried = set(_list(coverage.get("queried_source_ids")))
    missing = [source_id for source_id in MANDATORY_SOURCE_IDS if source_id not in queried]
    if missing:
        return _revision(
            "source coverage omits mandatory queried source ids",
            "source_coverage",
            [f"include {source_id} in queried_source_ids" for source_id in missing],
        )
    if int(coverage.get("satisfied_source_family_count") or 0) < 3:
        return _revision(
            "source coverage has too few satisfied source families",
            "source_coverage",
            ["increase satisfied_source_family_count by retrieving repo, brain, and baseline/CIEU evidence"],
        )
    return None


def _validate_sufficiency(
    assessment: Mapping[str, Any],
    context: Mapping[str, Any],
) -> AidenRetrievalOrchestrationDecision | None:
    if assessment.get("recent_memory_only") is True:
        return _deny("recent memory cannot satisfy retrieval", "sufficiency_assessment", ["recent_memory_only"])
    if assessment.get("sufficient_for_answer") is not True:
        return _revision(
            "retrieval assessment says context is insufficient",
            "sufficiency_assessment",
            list(assessment.get("correct_path") or ["query more governed sources before answering"]),
        )
    if _task_is_major(context) and int(assessment.get("minimum_evidence_items_required") or 0) < 5:
        return _revision(
            "major tasks require a higher evidence minimum",
            "sufficiency_assessment",
            ["set minimum_evidence_items_required >= 5 for strategy, governance, runtime, or major CEO tasks"],
        )
    return None


def _validate_downstream_binding(binding: Mapping[str, Any]) -> AidenRetrievalOrchestrationDecision | None:
    if binding.get("retrieval_required_before_aiden_answer") is not True:
        return _revision(
            "downstream binding must require retrieval before Aiden answers",
            "downstream_binding",
            ["set retrieval_required_before_aiden_answer=true"],
        )
    if binding.get("retrieved_context_bound_to_answer") is not True:
        return _revision(
            "retrieved context must be bound to the downstream answer/action",
            "downstream_binding",
            ["bind retrieved_evidence_pack into the Aiden answer context"],
        )
    if binding.get("raw_prompt_to_codex_allowed") is True:
        return _deny("raw prompt handoff is forbidden without governed order/retrieval", "downstream_binding", ["raw_prompt_to_codex_allowed"])
    return None


def _validate_cieu_linkage(linkage: Mapping[str, Any]) -> AidenRetrievalOrchestrationDecision | None:
    if linkage.get("CIEU_recording_required") is not True:
        return _revision(
            "retrieval orchestration must be CIEU-recorded",
            "CIEU_linkage",
            ["set CIEU_recording_required=true and write the retrieval decision to CIEUStore"],
        )
    if linkage.get("target_event_type") != AIDEN_RETRIEVAL_ORCHESTRATION_EVENT_TYPE:
        return _revision(
            "retrieval CIEU linkage targets the wrong event type",
            "CIEU_linkage",
            [f"set target_event_type={AIDEN_RETRIEVAL_ORCHESTRATION_EVENT_TYPE}"],
        )
    return None


def _task_is_major(context: Mapping[str, Any]) -> bool:
    task_type = str(context.get("task_type") or "").lower()
    return bool(
        context.get("major_action")
        or context.get("high_wisdom_required")
        or any(term in task_type for term in ("strategy", "governance", "runtime", "implementation", "market", "ceo"))
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _revision(reason: str, section: str, correct_path: list[str]) -> AidenRetrievalOrchestrationDecision:
    return AidenRetrievalOrchestrationDecision(
        decision=AidenRetrievalOrchestrationDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=section,
        correct_path=correct_path,
        guidance={"navigation": correct_path},
    )


def _deny(reason: str, section: str, violations: list[str]) -> AidenRetrievalOrchestrationDecision:
    return AidenRetrievalOrchestrationDecision(
        decision=AidenRetrievalOrchestrationDecisionValue.DENY,
        reason=reason,
        failed_section=section,
        violations=violations,
        correct_path=["remove the bypass/overclaim and rebuild the retrieval packet through governed sources"],
    )
