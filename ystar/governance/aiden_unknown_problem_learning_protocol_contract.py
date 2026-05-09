"""Governance for Aiden's unknown-problem learning protocol."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class AidenUnknownProblemLearningDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"


@dataclass(frozen=True)
class AidenUnknownProblemLearningDecision:
    decision: AidenUnknownProblemLearningDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "aiden_unknown_problem_learning_protocol_decision",
            "decision": self.decision.value,
            "passed": self.decision == AidenUnknownProblemLearningDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "guidance": dict(self.guidance),
        }


AIDEN_UNKNOWN_PROBLEM_LEARNING_EVENT_TYPE = "AIDEN_UNKNOWN_PROBLEM_LEARNING_PROTOCOL_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_SECTIONS = (
    "problem_context",
    "knowledge_gap_diagnosis",
    "learning_objectives",
    "sensemaking_modes",
    "thinking_modes",
    "source_discovery_plan",
    "tool_selection",
    "knowledge_graph_methodology",
    "governance_plan",
    "output_obligations",
    "truth_constraints",
)

REQUIRED_THINKING_MODES = {
    "first_principles",
    "systems_thinking",
    "decision_theory",
    "adversarial_critique",
    "causal_zero_loop",
    "customer_empathy",
}

REQUIRED_SOURCE_TYPES = {
    "brain_recall",
    "repo_capability_recall",
    "public_read_research",
    "classical_theory",
    "peer_experience",
    "historical_case",
    "owner_or_L4_feedback_when_approved",
}

FORBIDDEN_TRUE_CLAIMS = (
    "recent_memory_only",
    "external_action_executed",
    "customer_validation_claim",
    "revenue_claim",
    "payment_claim",
    "direct_brain_write_without_owner_gate",
    "direct_contract_mutation",
)


def validate_aiden_unknown_problem_learning_protocol(packet: Mapping[str, Any]) -> AidenUnknownProblemLearningDecision:
    if not isinstance(packet, Mapping):
        return _deny("unknown-problem learning protocol must be a mapping", "schema", ["packet_not_mapping"])

    missing = [field for field in REQUIRED_SECTIONS if field not in packet]
    if missing:
        return _revision("unknown-problem learning protocol is missing required sections", "schema", [f"add {field}" for field in missing])

    truth = packet.get("truth_constraints") if isinstance(packet.get("truth_constraints"), Mapping) else {}
    forbidden = [key for key in FORBIDDEN_TRUE_CLAIMS if truth.get(key) is True]
    if forbidden:
        return _deny("unknown-problem learning protocol contains forbidden bypass or overclaim", "truth_constraints", forbidden)

    problem = packet.get("problem_context") if isinstance(packet.get("problem_context"), Mapping) else {}
    if not problem.get("unknown_problem_statement") or not problem.get("action_boundary"):
        return _revision("problem context must name the unknown and action boundary", "problem_context", ["add unknown_problem_statement and action_boundary"])

    objectives = packet.get("learning_objectives") if isinstance(packet.get("learning_objectives"), list) else []
    objective_domains = {str(item.get("domain_id")) for item in objectives if isinstance(item, Mapping)}
    required_domains = {
        "classical_theory_canon",
        "peer_experience_corpus",
        "historical_case_corpus",
        "current_market_evidence",
        "internal_capability_recall",
        "customer_contact_residuals",
    }
    missing_domains = sorted(required_domains - objective_domains)
    if missing_domains:
        return _revision("learning objectives do not cover the full CEO knowledge stack", "learning_objectives", [f"add domain {domain}" for domain in missing_domains])

    thinking_modes = set(_as_list(packet.get("thinking_modes")))
    missing_modes = sorted(REQUIRED_THINKING_MODES - thinking_modes)
    if missing_modes:
        return _revision("unknown problems require explicit thinking-mode selection", "thinking_modes", [f"add thinking mode {mode}" for mode in missing_modes])

    sources = packet.get("source_discovery_plan") if isinstance(packet.get("source_discovery_plan"), list) else []
    source_types = {str(item.get("source_type")) for item in sources if isinstance(item, Mapping)}
    missing_sources = sorted(REQUIRED_SOURCE_TYPES - source_types)
    if missing_sources:
        return _revision("source discovery plan is too narrow", "source_discovery_plan", [f"add source_type {source}" for source in missing_sources])

    tools = packet.get("tool_selection") if isinstance(packet.get("tool_selection"), list) else []
    tool_ids = {str(item.get("tool_id")) for item in tools if isinstance(item, Mapping)}
    for required_tool in {"brain_activation", "repo_search", "public_read_provider", "Y_star_gov_validator", "CIEUStore", "CZL_residual_engine"}:
        if required_tool not in tool_ids:
            return _revision("tool selection is missing required learning tool", "tool_selection", [f"add tool {required_tool}"])

    graph = packet.get("knowledge_graph_methodology") if isinstance(packet.get("knowledge_graph_methodology"), Mapping) else {}
    if len(_as_list(graph.get("node_types"))) < 6 or len(_as_list(graph.get("edge_types"))) < 6:
        return _revision("knowledge graph methodology needs rich node and edge schemas", "knowledge_graph_methodology", ["add typed nodes and typed edges for theory, cases, tools, assumptions, residuals"])
    if graph.get("content_type_freshness_policy_required") is not True:
        return _revision("knowledge graph learning must use content-type freshness policy", "knowledge_graph_methodology", ["set content_type_freshness_policy_required=true"])
    if graph.get("production_brain_write_requires_owner_gate") is not True:
        return _revision("brain graph writes require owner-gated production boundary", "knowledge_graph_methodology", ["set production_brain_write_requires_owner_gate=true"])

    governance = packet.get("governance_plan") if isinstance(packet.get("governance_plan"), Mapping) else {}
    if governance.get("operating_pattern_doctrine_required") is not True or governance.get("CIEU_recording_required") is not True:
        return _revision("unknown-problem learning must be governed and recorded", "governance_plan", ["require operating pattern doctrine and CIEU recording"])

    return AidenUnknownProblemLearningDecision(
        decision=AidenUnknownProblemLearningDecisionValue.ALLOW,
        reason="unknown-problem learning protocol is complete and governed",
        correct_path=["run protocol before strategy/action when Aiden faces unfamiliar terrain"],
        guidance={"required_thinking_modes": sorted(REQUIRED_THINKING_MODES), "required_source_types": sorted(REQUIRED_SOURCE_TYPES)},
    )


def build_aiden_unknown_problem_learning_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenUnknownProblemLearningDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, AidenUnknownProblemLearningDecision) else dict(decision)
    problem = packet.get("problem_context") if isinstance(packet.get("problem_context"), Mapping) else {}
    return {
        "event_id": str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(problem.get("problem_id") or "aiden_unknown_problem_learning_protocol"),
        "agent_id": "Aiden",
        "event_type": AIDEN_UNKNOWN_PROBLEM_LEARNING_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "Aiden unknown-problem learning protocol validation",
        "contract_hash": "aiden-unknown-problem-learning-protocol-v1",
        "params": {"problem_id": problem.get("problem_id")},
        "result": {"decision": data.get("decision"), "reason": data.get("reason"), "correct_path": list(data.get("correct_path") or [])},
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore", "Aiden-brain"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": data.get("decision") == "ALLOW",
    }


def validate_and_write_aiden_unknown_problem_learning_protocol(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_aiden_unknown_problem_learning_protocol(packet)
    record = build_aiden_unknown_problem_learning_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "aiden_unknown_problem_learning_protocol_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "CIEU_write_result": {"event_type": record["event_type"], "event_id": record["event_id"], "CIEU_record": record},
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> AidenUnknownProblemLearningDecision:
    return AidenUnknownProblemLearningDecision(
        decision=AidenUnknownProblemLearningDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=failed_section,
        correct_path=["repair unknown-problem learning protocol", *correct_path],
        guidance={"decision_mode": "correct_path_navigation"},
    )


def _deny(reason: str, failed_section: str, violations: list[str]) -> AidenUnknownProblemLearningDecision:
    return AidenUnknownProblemLearningDecision(
        decision=AidenUnknownProblemLearningDecisionValue.DENY,
        reason=reason,
        failed_section=failed_section,
        violations=violations,
        correct_path=["block learning protocol", "remove bypass or false claim", "resubmit as governed learning plan"],
        guidance={"decision_mode": "hard_stop"},
    )


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


__all__ = [
    "AIDEN_UNKNOWN_PROBLEM_LEARNING_EVENT_TYPE",
    "AidenUnknownProblemLearningDecision",
    "AidenUnknownProblemLearningDecisionValue",
    "validate_aiden_unknown_problem_learning_protocol",
    "validate_and_write_aiden_unknown_problem_learning_protocol",
    "build_aiden_unknown_problem_learning_cieu_record",
]
