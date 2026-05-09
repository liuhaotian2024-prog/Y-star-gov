"""Deterministic governance for Aiden operating pattern doctrines.

This contract turns reusable success patterns into runtime obligations. The
goal is not to make Aiden memorize slogans; it must prove that the relevant
operating patterns were selected and invoked for the current action class.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class AidenOperatingPatternDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class AidenOperatingPatternDecision:
    decision: AidenOperatingPatternDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "aiden_operating_pattern_doctrine_decision",
            "decision": self.decision.value,
            "passed": self.decision == AidenOperatingPatternDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "guidance": dict(self.guidance),
        }


AIDEN_OPERATING_PATTERN_DOCTRINE_EVENT_TYPE = "AIDEN_OPERATING_PATTERN_DOCTRINE_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

BASE_MANDATORY_PATTERNS = {
    "full_repo_and_baseline_first",
    "no_new_wheel_preflight",
    "capability_utilization_sweep",
    "class_level_extrapolation_gate",
    "downstream_impact_scan",
    "correct_path_navigation",
    "evidence_quality_and_freshness_gate",
    "regression_test_and_cieu_closure",
}

CONDITIONAL_PATTERN_RULES = {
    "market_strategy_required": {
        "brain_provenance_required",
        "competitive_landscape_current_signal",
        "buyer_visible_value_translation",
        "residual_truth_scope_split",
    },
    "codex_execution_required": {
        "CEOImplementationOrder_before_Codex_prompt",
        "CodexExecutionReceipt_return_path",
    },
    "brain_write_related": {
        "production_brain_write_owner_backup_gate",
        "learning_quality_scoring_v2",
    },
    "external_action_related": {
        "gov_mcp_no_send_preflight",
        "owner_boundary_minimization_and_escalation",
    },
    "self_governance_related": {
        "proposal_only_no_direct_contract_mutation",
        "owner_review_before_contract_patch",
    },
    "unknown_problem_related": {
        "unknown_problem_learning_protocol",
        "knowledge_graph_methodology_selection",
        "source_discovery_tool_selection",
        "thinking_mode_selection",
    },
    "durable_learning_related": {
        "content_type_freshness_policy",
        "theory_case_peer_curriculum_coverage",
    },
    "autonomous_web_observation_related": {
        "host_autonomous_public_read_observer",
        "autonomous_query_frontier_expansion",
        "public_read_no_side_effect_boundary",
    },
    "local_llm_related": {
        "local_gemma_runtime_boundary",
        "local_llm_no_external_provider",
    },
}

FORBIDDEN_TRUE_CLAIMS = (
    "recent_memory_only",
    "skipped_no_new_wheel",
    "raw_codex_prompt_without_order",
    "static_template_used_for_live_strategy",
    "direct_contract_mutation",
    "external_action_executed_without_owner_approval",
    "customer_validation_claim",
    "revenue_claim",
    "payment_claim",
    "K9Audit_integration_claim",
)


def build_aiden_operating_pattern_doctrine_contract() -> dict[str, Any]:
    return {
        "contract_id": "aiden_operating_pattern_doctrine_contract_v1",
        "event_type": AIDEN_OPERATING_PATTERN_DOCTRINE_EVENT_TYPE,
        "base_mandatory_patterns": sorted(BASE_MANDATORY_PATTERNS),
        "conditional_pattern_rules": {key: sorted(value) for key, value in CONDITIONAL_PATTERN_RULES.items()},
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
    }


def expected_patterns_for_action_context(action_context: Mapping[str, Any]) -> set[str]:
    expected = set(BASE_MANDATORY_PATTERNS)
    for flag, patterns in CONDITIONAL_PATTERN_RULES.items():
        if action_context.get(flag) is True:
            expected.update(patterns)
    return expected


def validate_aiden_operating_pattern_invocation(packet: Mapping[str, Any]) -> AidenOperatingPatternDecision:
    if not isinstance(packet, Mapping):
        return _deny("operating pattern packet must be a mapping", "schema", ["packet_not_mapping"])

    action_context = packet.get("action_context") if isinstance(packet.get("action_context"), Mapping) else {}
    invocations = packet.get("pattern_invocations") if isinstance(packet.get("pattern_invocations"), list) else []
    truth = packet.get("truth_constraints") if isinstance(packet.get("truth_constraints"), Mapping) else {}

    if not action_context:
        return _revision("action_context is required", "action_context", ["build action_context before selecting operating patterns"])
    if not invocations:
        return _revision("pattern_invocations are required", "pattern_invocations", ["invoke the operating pattern registry before proceeding"])

    forbidden = [key for key in FORBIDDEN_TRUE_CLAIMS if truth.get(key) is True]
    if forbidden:
        return _deny("operating pattern packet contains forbidden overclaim or bypass", "truth_constraints", forbidden)

    expected = expected_patterns_for_action_context(action_context)
    invoked = {item.get("pattern_id") for item in invocations if isinstance(item, Mapping)}
    missing = sorted(expected - invoked)
    if missing:
        return _revision(
            "required operating patterns were not invoked",
            "pattern_invocations",
            [f"invoke {pattern_id}" for pattern_id in missing],
        )

    for item in invocations:
        if not isinstance(item, Mapping):
            return _revision("each pattern invocation must be a mapping", "pattern_invocations", ["complete invocation rows"])
        if item.get("invocation_status") != "invoked":
            return _revision(
                "mandatory operating patterns must be invoked, not merely mentioned",
                "pattern_invocations",
                [f"invoke {item.get('pattern_id') or 'missing_pattern_id'}"],
            )
        if not item.get("evidence_refs"):
            return _revision(
                "each operating pattern invocation needs evidence_refs",
                "pattern_invocations",
                [f"add evidence_refs for {item.get('pattern_id') or 'unknown_pattern'}"],
            )
        if not item.get("output_summary"):
            return _revision(
                "each operating pattern invocation needs output_summary",
                "pattern_invocations",
                [f"add output_summary for {item.get('pattern_id') or 'unknown_pattern'}"],
            )
        if item.get("runtime_governance_required") is not True:
            return _revision(
                "operating pattern invocations must declare runtime governance",
                "pattern_invocations",
                [f"set runtime_governance_required=true for {item.get('pattern_id') or 'unknown_pattern'}"],
            )

    return AidenOperatingPatternDecision(
        decision=AidenOperatingPatternDecisionValue.ALLOW,
        reason="required Aiden operating patterns were selected and invoked",
        correct_path=["proceed to the governed runtime action with CIEU-backed pattern proof"],
        guidance={"expected_patterns": sorted(expected), "invoked_patterns": sorted(invoked)},
    )


def build_aiden_operating_pattern_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenOperatingPatternDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, AidenOperatingPatternDecision) else dict(decision)
    context = packet.get("action_context") if isinstance(packet.get("action_context"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(context.get("action_id") or "aiden_operating_pattern_doctrine"),
        "agent_id": "Aiden",
        "event_type": AIDEN_OPERATING_PATTERN_DOCTRINE_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "Aiden operating pattern doctrine validation",
        "contract_hash": "aiden-operating-pattern-doctrine-v1",
        "params": {"action_id": context.get("action_id"), "action_type": context.get("action_type")},
        "result": {
            "decision": data.get("decision"),
            "reason": data.get("reason"),
            "correct_path": list(data.get("correct_path") or []),
            "guidance": dict(data.get("guidance") or {}),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": data.get("decision") == "ALLOW",
    }


def write_aiden_operating_pattern_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenOperatingPatternDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    record = build_aiden_operating_pattern_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "aiden_operating_pattern_doctrine_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_aiden_operating_pattern_invocation(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_aiden_operating_pattern_invocation(packet)
    write_result = write_aiden_operating_pattern_cieu_record(
        packet,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "aiden_operating_pattern_doctrine_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> AidenOperatingPatternDecision:
    return AidenOperatingPatternDecision(
        decision=AidenOperatingPatternDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=failed_section,
        correct_path=["repair operating pattern invocation before proceeding", *correct_path],
        guidance={"decision_mode": "correct_path_navigation"},
    )


def _deny(reason: str, failed_section: str, violations: list[str]) -> AidenOperatingPatternDecision:
    return AidenOperatingPatternDecision(
        decision=AidenOperatingPatternDecisionValue.DENY,
        reason=reason,
        failed_section=failed_section,
        violations=violations,
        correct_path=["block action", "remove bypass or false claim", "resubmit with governed pattern proof"],
        guidance={"decision_mode": "hard_stop"},
    )


__all__ = [
    "AIDEN_OPERATING_PATTERN_DOCTRINE_EVENT_TYPE",
    "AidenOperatingPatternDecision",
    "AidenOperatingPatternDecisionValue",
    "build_aiden_operating_pattern_doctrine_contract",
    "build_aiden_operating_pattern_cieu_record",
    "expected_patterns_for_action_context",
    "validate_aiden_operating_pattern_invocation",
    "validate_and_write_aiden_operating_pattern_invocation",
    "write_aiden_operating_pattern_cieu_record",
]
