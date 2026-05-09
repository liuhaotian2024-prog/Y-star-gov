"""Governance contract for Aiden's host-level CEO operating runtime.

This contract treats the host runtime loop as a governed company behavior. It
does not let Aiden become "free-running" by skipping the already-built systems:
E110 universal control, E89/E90/E108 strategy/intelligence, E92 CEO-to-Codex
orders, Y-star-gov validation, CIEUStore memory, and gov-mcp no-send boundaries.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class AidenHostRuntimeDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class AidenHostRuntimeDecision:
    decision: AidenHostRuntimeDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    navigation: dict[str, Any] = field(default_factory=dict)
    requires_owner_decision: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "aiden_host_runtime_governance_decision",
            "decision": self.decision.value,
            "passed": self.decision == AidenHostRuntimeDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "navigation": dict(self.navigation),
            "requires_owner_decision": self.requires_owner_decision,
        }


AIDEN_HOST_RUNTIME_CIEU_EVENT_TYPE = "AIDEN_HOST_RUNTIME_CYCLE_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_PACKET_FIELDS = (
    "host_runtime_id",
    "mission_anchor",
    "first_principles_operating_model",
    "existing_capability_orchestration_map",
    "autonomy_policy",
    "universal_control_gate",
    "value_discovery_cycle",
    "CEO_implementation_order",
    "next_action_recommendation",
    "truth_constraints",
)

REQUIRED_CAPABILITY_IDS = (
    "E110_labs_universal_operating_control_plane",
    "E89_ceo_intelligence_loop_runtime_compiler",
    "E90_ceo_strategic_intelligence_benchmark",
    "E108_live_global_open_world_strategy_runtime",
    "E92_CEOImplementationOrder",
    "E101_adaptive_governance_correct_path_navigator",
    "E94_behavior_center_brain_binding",
    "Y_star_gov_deterministic_governance",
    "CIEUStore_formal_memory",
    "gov_mcp_dry_run_no_send_boundary",
)

REQUIRED_AUTONOMY_TIERS = (
    "autonomous_internal_low_risk",
    "codex_executor_order_required",
    "gov_mcp_dry_run_only",
    "owner_decision_required",
    "hard_deny",
)

FORBIDDEN_TRUE_CLAIMS = (
    "external_action_executed",
    "provider_action_executed",
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


def build_aiden_host_runtime_contract() -> dict[str, Any]:
    return {
        "contract_id": "aiden_host_runtime_contract_v1",
        "event_type": AIDEN_HOST_RUNTIME_CIEU_EVENT_TYPE,
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "required_packet_fields": list(REQUIRED_PACKET_FIELDS),
        "required_capability_ids": list(REQUIRED_CAPABILITY_IDS),
        "required_autonomy_tiers": list(REQUIRED_AUTONOMY_TIERS),
        "governance_style": "autonomy_with_correct_path_navigation",
    }


def validate_aiden_host_runtime_cycle(packet: Mapping[str, Any]) -> AidenHostRuntimeDecision:
    if not isinstance(packet, Mapping):
        return _deny("host runtime packet must be a mapping", "schema", ["packet_not_mapping"])

    missing_fields = [field for field in REQUIRED_PACKET_FIELDS if not _present(packet.get(field))]
    if missing_fields:
        return _revision(
            "Aiden host runtime packet is missing required sections",
            "schema",
            [f"add {field}" for field in missing_fields],
        )

    forbidden = _forbidden_claim(packet)
    if forbidden:
        return _deny(f"forbidden runtime claim present: {forbidden}", "truth_constraints", [forbidden])

    mission = packet.get("mission_anchor") if isinstance(packet.get("mission_anchor"), Mapping) else {}
    mission_terms = set(str(item) for item in mission.get("must_optimize_for", []) or [])
    if not {"autonomous_value_discovery", "governed_value_creation", "residual_learning"}.issubset(mission_terms):
        return _revision(
            "mission anchor must optimize for autonomous value discovery, governed value creation, and residual learning",
            "mission_anchor",
            [
                "rebuild mission_anchor from the Y*Bridge Labs final mission",
                "include autonomous_value_discovery, governed_value_creation, and residual_learning",
            ],
        )

    capability_map = packet.get("existing_capability_orchestration_map")
    found_caps = _capability_ids(capability_map)
    missing_caps = [capability for capability in REQUIRED_CAPABILITY_IDS if capability not in found_caps]
    if missing_caps:
        return _revision(
            "host runtime did not orchestrate all mandatory existing systems",
            "existing_capability_orchestration_map",
            [_correct_path_for(capability) for capability in missing_caps],
        )

    policy = packet.get("autonomy_policy") if isinstance(packet.get("autonomy_policy"), Mapping) else {}
    tiers = set(str(item.get("tier_id")) for item in policy.get("tiers", []) if isinstance(item, Mapping))
    missing_tiers = [tier for tier in REQUIRED_AUTONOMY_TIERS if tier not in tiers]
    if missing_tiers:
        return _revision(
            "autonomy policy is missing required safety tiers",
            "autonomy_policy",
            [f"add autonomy tier {tier}" for tier in missing_tiers],
        )

    control_gate = packet.get("universal_control_gate") if isinstance(packet.get("universal_control_gate"), Mapping) else {}
    control_decision = (
        control_gate.get("Y_star_gov_universal_control_decision")
        or control_gate.get("governance_decision")
        or control_gate.get("decision")
    )
    if control_decision != "ALLOW" or control_gate.get("runtime_may_continue") is not True:
        return _revision(
            "E110 universal control gate must ALLOW before host runtime continues",
            "universal_control_gate",
            ["run E110 labs universal operating control plane and follow its correct_path navigator"],
        )

    value_cycle = packet.get("value_discovery_cycle") if isinstance(packet.get("value_discovery_cycle"), Mapping) else {}
    if value_cycle.get("market_strategy_decision") != "ALLOW" or value_cycle.get("open_world_scan_performed") is not True:
        return _revision(
            "host runtime must perform governed open-world value discovery before selecting work",
            "value_discovery_cycle",
            ["run E108/E110 live global open-world strategy with brain provenance and current evidence"],
        )

    next_action = packet.get("next_action_recommendation") if isinstance(packet.get("next_action_recommendation"), Mapping) else {}
    if _truthy(next_action, "payment_related") or _truthy(next_action, "live_provider_execution_requested"):
        return _deny(
            "payment or live provider execution cannot be authorized by host runtime",
            "next_action_recommendation",
            ["payment_or_live_provider_execution_requested"],
        )
    if _truthy(next_action, "external_action_candidate") and next_action.get("autonomy_tier") != "owner_decision_required":
        return _escalate(
            "external/L4 action must become an owner decision packet before execution",
            "next_action_recommendation",
            ["prepare owner decision packet", "do not execute outreach/publication/customer action"],
        )

    order = packet.get("CEO_implementation_order") if isinstance(packet.get("CEO_implementation_order"), Mapping) else {}
    if next_action.get("route_type") in {"codex_executor_order", "internal_engineering"}:
        if order.get("artifact_id") != "CEOImplementationOrder" or order.get("executor_actor") != "Codex":
            return _revision(
                "Codex-executable host actions require a CEOImplementationOrder",
                "CEO_implementation_order",
                ["build CEOImplementationOrder and validate it through Y-star-gov before Codex prompt generation"],
            )

    return AidenHostRuntimeDecision(
        decision=AidenHostRuntimeDecisionValue.ALLOW,
        reason="Aiden host runtime cycle satisfies mission, orchestration, autonomy, E110, value-discovery, and executor-boundary gates",
        navigation={
            "decision_mode": "continue_with_low_risk_autonomous_internal_work_or_owner_gated_external_packet",
            "next_allowed_action": next_action.get("action_id") or next_action.get("title"),
            "external_action_allowed": False,
            "codex_requires_CEOImplementationOrder": True,
        },
    )


def build_aiden_host_runtime_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenHostRuntimeDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, AidenHostRuntimeDecision) else dict(decision)
    next_action = packet.get("next_action_recommendation") if isinstance(packet.get("next_action_recommendation"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(packet.get("session_id") or "aiden_host_runtime_cycle"),
        "agent_id": "Aiden",
        "event_type": AIDEN_HOST_RUNTIME_CIEU_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "Aiden host-level CEO operating runtime cycle decision",
        "contract_hash": "aiden-host-runtime-contract-v1",
        "params": {
            "host_runtime_id": packet.get("host_runtime_id"),
            "selected_next_action": next_action.get("action_id") or next_action.get("title"),
            "autonomy_tier": next_action.get("autonomy_tier"),
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


def write_aiden_host_runtime_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenHostRuntimeDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    record = build_aiden_host_runtime_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "aiden_host_runtime_cieu_write_result",
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


def validate_and_write_aiden_host_runtime_cycle(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_aiden_host_runtime_cycle(packet)
    write_result = write_aiden_host_runtime_cieu_record(
        packet,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "aiden_host_runtime_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> AidenHostRuntimeDecision:
    path = [
        "repair Aiden host runtime packet before autonomous company behavior continues",
        "do not execute external/provider/customer/revenue/payment action while decision is REQUIRE_REVISION",
        *correct_path,
    ]
    return AidenHostRuntimeDecision(
        decision=AidenHostRuntimeDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=failed_section,
        correct_path=path,
        navigation={
            "decision_mode": "correct_path_navigation",
            "next_allowed_action": "repair_host_runtime_packet_only",
            "blocked_actions": ["external_execution", "provider_execution", "customer_or_revenue_claim"],
            "correct_path": path,
        },
    )


def _deny(reason: str, failed_section: str, violations: list[str]) -> AidenHostRuntimeDecision:
    return AidenHostRuntimeDecision(
        decision=AidenHostRuntimeDecisionValue.DENY,
        reason=reason,
        failed_section=failed_section,
        violations=violations,
        correct_path=["remove forbidden claim or unsafe action", "return to governed host runtime planner"],
        navigation={"decision_mode": "hard_stop", "next_allowed_action": "none_until_violation_removed"},
    )


def _escalate(reason: str, failed_section: str, correct_path: list[str]) -> AidenHostRuntimeDecision:
    return AidenHostRuntimeDecision(
        decision=AidenHostRuntimeDecisionValue.ESCALATE,
        reason=reason,
        failed_section=failed_section,
        correct_path=correct_path,
        requires_owner_decision=True,
        navigation={"decision_mode": "owner_decision_required", "owner_decision_path": correct_path},
    )


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, tuple, dict, set)):
        return bool(value)
    return True


def _truthy(mapping: Mapping[str, Any], key: str) -> bool:
    return mapping.get(key) is True


def _capability_ids(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        items = value.get("capabilities") or value.get("systems") or value.get("items") or []
    else:
        items = value or []
    ids: list[str] = []
    for item in items:
        if isinstance(item, Mapping):
            capability_id = item.get("capability_id") or item.get("system_id") or item.get("id")
        else:
            capability_id = item
        if capability_id:
            ids.append(str(capability_id))
    return list(dict.fromkeys(ids))


def _forbidden_claim(packet: Mapping[str, Any]) -> str:
    truth = packet.get("truth_constraints") if isinstance(packet.get("truth_constraints"), Mapping) else {}
    for field in FORBIDDEN_TRUE_CLAIMS:
        if truth.get(field) is True:
            return field
    next_action = packet.get("next_action_recommendation") if isinstance(packet.get("next_action_recommendation"), Mapping) else {}
    for field in FORBIDDEN_TRUE_CLAIMS:
        if next_action.get(field) is True:
            return field
    return ""


def _correct_path_for(capability_id: str) -> str:
    paths = {
        "E110_labs_universal_operating_control_plane": "route all Labs behavior through E110 universal operating control first",
        "E89_ceo_intelligence_loop_runtime_compiler": "run structured governed CEO intelligence before action selection",
        "E90_ceo_strategic_intelligence_benchmark": "score strategy quality before selecting market/action route",
        "E108_live_global_open_world_strategy_runtime": "run live/open-world public-read value discovery where strategy is required",
        "E92_CEOImplementationOrder": "convert executable engineering work into CEOImplementationOrder before Codex prompt",
        "E101_adaptive_governance_correct_path_navigator": "return correct_path guidance for missing obligations instead of blunt denial",
        "E94_behavior_center_brain_binding": "bind owner-facing behavior center to brain provenance and governance",
        "Y_star_gov_deterministic_governance": "validate through Y-star-gov deterministic contract",
        "CIEUStore_formal_memory": "write decision/residual evidence to CIEUStore",
        "gov_mcp_dry_run_no_send_boundary": "route provider/tool boundary through gov-mcp dry-run/no-send receipt",
    }
    return paths.get(capability_id, f"wire {capability_id} into host runtime before continuing")


__all__ = [
    "AIDEN_HOST_RUNTIME_CIEU_EVENT_TYPE",
    "AidenHostRuntimeDecision",
    "AidenHostRuntimeDecisionValue",
    "FORMAL_CIEU_LOG_PATH",
    "REQUIRED_AUTONOMY_TIERS",
    "REQUIRED_CAPABILITY_IDS",
    "build_aiden_host_runtime_cieu_record",
    "build_aiden_host_runtime_contract",
    "validate_aiden_host_runtime_cycle",
    "validate_and_write_aiden_host_runtime_cycle",
    "write_aiden_host_runtime_cieu_record",
]
