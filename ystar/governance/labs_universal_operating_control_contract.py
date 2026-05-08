"""Deterministic governance for the Labs universal operating control plane.

The control plane is the non-bypassable front door for bridge-labs CEO/company
runtime behavior. It does not replace specialized contracts; it decides which
specialized capabilities must be invoked before a behavior can continue.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class LabsUniversalControlDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class LabsUniversalControlDecision:
    decision: LabsUniversalControlDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    navigation: dict[str, Any] = field(default_factory=dict)
    requires_owner_decision: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "labs_universal_operating_control_decision",
            "decision": self.decision.value,
            "passed": self.decision == LabsUniversalControlDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "navigation": dict(self.navigation),
            "requires_owner_decision": self.requires_owner_decision,
        }


LABS_UNIVERSAL_OPERATING_CONTROL_CIEU_EVENT_TYPE = "LABS_UNIVERSAL_OPERATING_CONTROL_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_PACKET_FIELDS = (
    "control_plane_id",
    "operation_context",
    "operation_classification",
    "required_capabilities",
    "capability_invocation_plan",
    "correct_path_navigator",
    "bypass_prevention",
    "truth_constraints",
)

BASELINE_CAPABILITIES = (
    "adaptive_governance_discovery",
    "open_world_doctrine_registry",
    "Y_star_gov_runtime_validation",
    "CIEUStore_write_plan",
    "post_action_residual",
)

STRATEGY_CAPABILITIES = (
    "six_d_brain_provenance",
    "live_public_read_open_world_scan",
    "competitive_intelligence_current_sources",
    "substitute_threat_analysis",
    "founder_market_fit_and_right_to_win",
    "strategy_math_model",
    "anti_anchor_counterfactual_search",
    "latest_source_freshness_policy",
)

CODEX_CAPABILITIES = (
    "CEOImplementationOrder",
    "CodexExecutionReceipt",
)

PROVIDER_CAPABILITIES = (
    "gov_mcp_dry_run_no_send_boundary",
)

FORBIDDEN_TRUE_CLAIMS = (
    "customer_validation_claim",
    "pricing_validation_claim",
    "revenue_claim",
    "payment_claim",
    "paid_signal_claim",
    "L4_feedback_executed",
    "L5_revenue_loop_complete",
    "K9Audit_integration_claim",
    "live_provider_execution_claim",
)


def build_labs_universal_operating_control_contract() -> dict[str, Any]:
    return {
        "contract_id": "labs_universal_operating_control_contract_v1",
        "event_type": LABS_UNIVERSAL_OPERATING_CONTROL_CIEU_EVENT_TYPE,
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "baseline_capabilities": list(BASELINE_CAPABILITIES),
        "strategy_capabilities": list(STRATEGY_CAPABILITIES),
        "codex_capabilities": list(CODEX_CAPABILITIES),
        "provider_capabilities": list(PROVIDER_CAPABILITIES),
        "governance_style": "correct_path_navigator_first",
    }


def required_capabilities_for_operation_context(context: Mapping[str, Any]) -> list[str]:
    required = list(BASELINE_CAPABILITIES)
    if _truthy(context, "market_strategy_required") or str(context.get("operation_type")) == "strategic_market_analysis":
        required.extend(STRATEGY_CAPABILITIES)
    if _truthy(context, "codex_executor_boundary") or _truthy(context, "codex_prompt_generation"):
        required.extend(CODEX_CAPABILITIES)
    if _truthy(context, "provider_tool_boundary") or _truthy(context, "external_action_candidate"):
        required.extend(PROVIDER_CAPABILITIES)
    if _truthy(context, "memory_write_requested"):
        required.append("memory_write_residual_learning_boundary")
    if _truthy(context, "report_generation_requested"):
        required.append("report_truth_boundary")
    return list(dict.fromkeys(required))


def validate_labs_universal_control_packet(packet: Mapping[str, Any]) -> LabsUniversalControlDecision:
    if not isinstance(packet, Mapping):
        return _deny("control packet must be a mapping", "schema", ["packet_not_mapping"])

    missing_fields = [field for field in REQUIRED_PACKET_FIELDS if field not in packet]
    if missing_fields:
        return _revision(
            "universal operating control packet is missing required fields",
            "schema",
            [f"add {field}" for field in missing_fields],
        )

    forbidden = _forbidden_claim(packet)
    if forbidden:
        return _deny(f"forbidden completion claim present: {forbidden}", "truth_constraints", [forbidden])

    context = packet.get("operation_context")
    if not isinstance(context, Mapping):
        return _revision("operation_context must be structured", "operation_context", ["attach structured operation_context"])

    if packet.get("bypass_attempt") is True or context.get("bypass_attempt") is True:
        return _deny(
            "Labs operating behavior attempted to bypass the universal control plane",
            "bypass_prevention",
            ["universal_control_bypass_attempt"],
        )

    if _truthy(context, "owner_bound_external_action_requested"):
        return _escalate(
            "owner-bound external action requires owner decision before execution",
            "owner_decision_boundary",
            ["prepare owner decision packet; do not execute external action"],
        )

    if _truthy(context, "external_action_executed") or _truthy(context, "provider_action_executed"):
        return _deny(
            "universal control packet cannot authorize already-executed external/provider action",
            "execution_boundary",
            ["external_or_provider_action_executed"],
        )

    expected = required_capabilities_for_operation_context(context)
    declared_required = _capability_ids(packet.get("required_capabilities"))
    missing_from_required = [capability for capability in expected if capability not in declared_required]
    if missing_from_required:
        return _revision(
            "required capabilities were not resolved by the universal control plane",
            "required_capabilities",
            [_correct_path_for(capability) for capability in missing_from_required],
        )

    planned = _plan_by_id(packet.get("capability_invocation_plan"))
    missing_plan = [capability for capability in declared_required if capability not in planned]
    if missing_plan:
        return _revision(
            "required capabilities do not have invocation plan entries",
            "capability_invocation_plan",
            [_correct_path_for(capability) for capability in missing_plan],
        )

    for capability in declared_required:
        row = planned[capability]
        if str(row.get("runtime_status")) in {"deprecated", "quarantined", "unsafe_contact_sensitive"}:
            return _revision(
                f"{capability} cannot be satisfied by stale/deprecated/quarantined capability",
                "capability_invocation_plan",
                [_correct_path_for(capability)],
            )
        if row.get("satisfied") is not True:
            return _revision(
                f"{capability} is not satisfied",
                "capability_invocation_plan",
                [_correct_path_for(capability)],
            )

    if _truthy(context, "market_strategy_required"):
        for capability in STRATEGY_CAPABILITIES:
            row = planned.get(capability, {})
            if row.get("satisfied") is not True:
                return _revision(
                    f"market strategy requires {capability}",
                    "strategy_capability_gate",
                    [_correct_path_for(capability)],
                )
        if _static_or_memory_only(planned.get("live_public_read_open_world_scan", {})):
            return _revision(
                "static or memory-only evidence cannot satisfy live open-world strategy",
                "live_public_read_open_world_scan",
                [_correct_path_for("live_public_read_open_world_scan")],
            )
        if _static_or_memory_only(planned.get("competitive_intelligence_current_sources", {})):
            return _revision(
                "static or memory-only competitor scan cannot satisfy strategic competition analysis",
                "competitive_intelligence_current_sources",
                [_correct_path_for("competitive_intelligence_current_sources")],
            )

    if _truthy(context, "codex_prompt_generation") and planned.get("CEOImplementationOrder", {}).get("satisfied") is not True:
        return _revision(
            "Codex prompt generation requires a linked CEOImplementationOrder",
            "codex_prompt_generation",
            [_correct_path_for("CEOImplementationOrder")],
        )

    if _truthy(context, "provider_tool_boundary") and planned.get("gov_mcp_dry_run_no_send_boundary", {}).get("satisfied") is not True:
        return _revision(
            "provider/tool boundary requires gov-mcp dry-run/no-send proof",
            "provider_tool_boundary",
            [_correct_path_for("gov_mcp_dry_run_no_send_boundary")],
        )

    return LabsUniversalControlDecision(
        decision=LabsUniversalControlDecisionValue.ALLOW,
        reason="Labs universal operating control packet satisfies all required capability gates",
        navigation={
            "decision_mode": "continue_to_specialized_runtime",
            "next_allowed_action": "continue_only_with_declared_capability_sequence",
            "specialized_contracts_still_required": True,
        },
    )


def build_labs_universal_control_cieu_record(
    packet: Mapping[str, Any],
    decision: LabsUniversalControlDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, LabsUniversalControlDecision) else dict(decision)
    context = packet.get("operation_context") if isinstance(packet.get("operation_context"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(packet.get("session_id") or context.get("operation_id") or "labs_universal_control"),
        "agent_id": "bridge_labs_ceo",
        "event_type": LABS_UNIVERSAL_OPERATING_CONTROL_CIEU_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "Labs universal operating control plane decision",
        "contract_hash": "labs-universal-operating-control-v1",
        "params": {
            "control_plane_id": packet.get("control_plane_id"),
            "operation_id": context.get("operation_id"),
            "operation_type": context.get("operation_type"),
            "required_capability_count": len(_capability_ids(packet.get("required_capabilities"))),
        },
        "result": {
            "decision": data.get("decision"),
            "reason": data.get("reason"),
            "correct_path": list(data.get("correct_path") or []),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": data.get("decision") == "ALLOW",
    }


def write_labs_universal_control_cieu_record(
    packet: Mapping[str, Any],
    decision: LabsUniversalControlDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    record = build_labs_universal_control_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "labs_universal_control_cieu_write_result",
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


def validate_and_write_labs_universal_control_packet(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_labs_universal_control_packet(packet)
    write_result = write_labs_universal_control_cieu_record(
        packet,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "labs_universal_control_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> LabsUniversalControlDecision:
    path = [
        "repair the Labs universal operating control packet before specialized runtime continues",
        "do not execute external/provider/customer/revenue/payment action while decision is REQUIRE_REVISION",
        *correct_path,
    ]
    return LabsUniversalControlDecision(
        decision=LabsUniversalControlDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=failed_section,
        correct_path=path,
        navigation={
            "decision_mode": "correct_path_navigation",
            "next_allowed_action": "repair_packet_only",
            "blocked_actions": ["external_execution", "provider_execution", "customer_or_revenue_claim"],
            "correct_path": path,
        },
    )


def _deny(reason: str, failed_section: str, violations: list[str]) -> LabsUniversalControlDecision:
    return LabsUniversalControlDecision(
        decision=LabsUniversalControlDecisionValue.DENY,
        reason=reason,
        failed_section=failed_section,
        violations=violations,
        correct_path=[
            "remove forbidden claim or bypass attempt",
            "return to the Labs universal operating control plane",
        ],
        navigation={"decision_mode": "hard_stop", "next_allowed_action": "none_until_claim_removed"},
    )


def _escalate(reason: str, failed_section: str, correct_path: list[str]) -> LabsUniversalControlDecision:
    return LabsUniversalControlDecision(
        decision=LabsUniversalControlDecisionValue.ESCALATE,
        reason=reason,
        failed_section=failed_section,
        correct_path=correct_path,
        requires_owner_decision=True,
        navigation={"decision_mode": "owner_decision_required", "owner_decision_path": correct_path},
    )


def _truthy(mapping: Mapping[str, Any], key: str) -> bool:
    return mapping.get(key) is True


def _capability_ids(items: Any) -> list[str]:
    ids = []
    for item in items or []:
        if isinstance(item, Mapping):
            value = item.get("capability_id") or item.get("id")
        else:
            value = item
        if value:
            ids.append(str(value))
    return list(dict.fromkeys(ids))


def _plan_by_id(items: Any) -> dict[str, Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    for item in items or []:
        if isinstance(item, Mapping) and item.get("capability_id"):
            rows[str(item["capability_id"])] = item
    return rows


def _static_or_memory_only(row: Mapping[str, Any]) -> bool:
    mode = str(row.get("invocation_mode") or row.get("satisfied_by") or "")
    return mode in {"static_template", "static_evidence_map", "recent_memory_only", "historical_snapshot_only"}


def _forbidden_claim(packet: Mapping[str, Any]) -> str:
    truth = packet.get("truth_constraints") if isinstance(packet.get("truth_constraints"), Mapping) else {}
    for field in FORBIDDEN_TRUE_CLAIMS:
        if truth.get(field) is True:
            return field
    context = packet.get("operation_context") if isinstance(packet.get("operation_context"), Mapping) else {}
    for field in FORBIDDEN_TRUE_CLAIMS:
        if context.get(field) is True:
            return field
    return ""


def _correct_path_for(capability_id: str) -> str:
    paths = {
        "adaptive_governance_discovery": "run adaptive governance discovery and attach obligation proof",
        "open_world_doctrine_registry": "resolve required doctrines from the open-world doctrine registry",
        "Y_star_gov_runtime_validation": "route packet through Y-star-gov deterministic validation",
        "CIEUStore_write_plan": "attach formal CIEUStore write path and session id",
        "post_action_residual": "declare post-action residual requirement and learning path",
        "six_d_brain_provenance": "run 6D brain grounding and attach brain_provenance",
        "live_public_read_open_world_scan": "run live public-read open-world scan or return REQUIRE_REVISION",
        "competitive_intelligence_current_sources": "collect current competitor/substitute evidence with source urls and dates",
        "substitute_threat_analysis": "compare direct competitors, substitutes, incumbents, and why buyers might choose them",
        "founder_market_fit_and_right_to_win": "state founder-market fit, Y*Bridge Labs advantage, and weaknesses",
        "strategy_math_model": "rank routes with source-backed market-first mathematical model",
        "anti_anchor_counterfactual_search": "compare non-adjacent routes and prove result is not a prior-anchor clone",
        "latest_source_freshness_policy": "tag source freshness and reject stale-only market conclusions",
        "CEOImplementationOrder": "build and validate CEOImplementationOrder before Codex prompt generation",
        "CodexExecutionReceipt": "require CodexExecutionReceipt after execution",
        "gov_mcp_dry_run_no_send_boundary": "route provider/tool boundary through gov-mcp dry-run/no-send receipt",
        "memory_write_residual_learning_boundary": "write memory/residual only through governed CIEUStore path",
        "report_truth_boundary": "report claims must be evidence-bound and carry no-overclaim constraints",
    }
    return paths.get(capability_id, f"satisfy capability {capability_id} with evidence and rerun control plane")


__all__ = [
    "BASELINE_CAPABILITIES",
    "CODEX_CAPABILITIES",
    "FORMAL_CIEU_LOG_PATH",
    "LABS_UNIVERSAL_OPERATING_CONTROL_CIEU_EVENT_TYPE",
    "LabsUniversalControlDecision",
    "LabsUniversalControlDecisionValue",
    "PROVIDER_CAPABILITIES",
    "STRATEGY_CAPABILITIES",
    "build_labs_universal_control_cieu_record",
    "build_labs_universal_operating_control_contract",
    "required_capabilities_for_operation_context",
    "validate_and_write_labs_universal_control_packet",
    "validate_labs_universal_control_packet",
    "write_labs_universal_control_cieu_record",
]
