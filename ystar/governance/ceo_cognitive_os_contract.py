"""CEO Cognitive OS contract validator.

This module is the Y-star-gov-side deterministic validator for bridge-labs
CEO Cognitive OS packets. It validates packet shape and governance boundaries;
it does not generate CEO thoughts, execute actions, call hooks, write CIEU
records, read bridge-labs artifacts at runtime, or perform external work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class CEOCognitiveOSDecisionValue(str, Enum):
    """Governance decisions for CEO Cognitive OS packets."""

    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOCognitiveOSContract:
    """Deterministic CEO Cognitive OS contract synced from bridge-labs E81."""

    contract_id: str
    version: str
    required_loop_stage_ids: tuple[str, ...]
    required_pre_action_fields: tuple[str, ...]
    required_prediction_fields: tuple[str, ...]
    required_post_action_fields: tuple[str, ...]
    required_post_cieu_fields: tuple[str, ...]
    forbidden_claim_fields: tuple[str, ...]
    allowed_owner_approval_states: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "version": self.version,
            "required_loop_stage_ids": list(self.required_loop_stage_ids),
            "required_pre_action_fields": list(self.required_pre_action_fields),
            "required_prediction_fields": list(self.required_prediction_fields),
            "required_post_action_fields": list(self.required_post_action_fields),
            "required_post_cieu_fields": list(self.required_post_cieu_fields),
            "forbidden_claim_fields": list(self.forbidden_claim_fields),
            "allowed_owner_approval_states": list(self.allowed_owner_approval_states),
        }


@dataclass(frozen=True)
class CEOCognitiveOSDecision:
    """Result of deterministic CEO Cognitive OS validation."""

    decision: CEOCognitiveOSDecisionValue
    reason: str
    failed_stage: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.decision == CEOCognitiveOSDecisionValue.ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "passed": self.passed,
            "reason": self.reason,
            "failed_stage": self.failed_stage,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


MANDATORY_LOOP_STAGE_IDS: tuple[str, ...] = (
    "mission_and_owner_constraint_recall",
    "full_capability_inventory_recall",
    "relevant_historical_asset_retrieval",
    "current_problem_classification",
    "canonical_owner_selection",
    "existing_module_reuse_extend_wrap_create_new_decision",
    "long_memory_KG_brain_recall_if_evidence_supported",
    "field_dimensional_reasoning_if_evidence_supported",
    "thesis_generation",
    "counterfactual_action_comparison",
    "pre_action_CIEU_residual_prediction",
    "adversarial_critique",
    "commercial_sharpness_gate",
    "no_new_wheel_gate",
    "decision",
    "post_action_CIEU_residual_and_learning_update",
)

REQUIRED_PRE_ACTION_FIELDS: tuple[str, ...] = (
    "packet_id",
    "job_id",
    "proposed_action",
    "action_class",
    "owner_intent",
    "current_mission_context",
    "discovered_capabilities_consulted",
    "historical_assets_consulted",
    "canonical_owner_map",
    "no_new_wheel_decision",
    "candidate_actions",
    "counterfactual_comparison",
    "predicted_CIEU_records",
    "adversarial_critique",
    "what_not_to_do",
    "selected_action",
    "why_this_action",
    "why_not_other_actions",
    "safety_boundary",
    "overclaim_boundary",
    "Y_star_contract_hash_input",
    "required_YstarGov_check",
    "approval_required",
    "owner_approval_state",
    "bypass_attempt",
    "loop_stage_results",
)

REQUIRED_PREDICTION_FIELDS: tuple[str, ...] = (
    "X_t",
    "U_t",
    "Y_star_t",
    "expected_Y_t_plus_1",
    "predicted_R_t_plus_1",
    "residual_severity",
)

REQUIRED_POST_ACTION_FIELDS: tuple[str, ...] = (
    "packet_id",
    "linked_pre_action_packet_id",
    "action_taken",
    "expected_outcome",
    "actual_output",
    "CIEU_record",
    "residuals",
    "unexpected_failures",
    "overclaim_check",
    "no_new_wheel_check",
    "owner_usefulness_check",
    "intelligence_gate_result",
    "capability_state_updates",
    "learning_candidates",
    "YstarGov_sync_status",
    "next_action_recommendation",
    "what_not_to_do_next",
)

REQUIRED_POST_CIEU_FIELDS: tuple[str, ...] = (
    "X_t",
    "U_t",
    "Y_star_t",
    "Y_t_plus_1",
    "R_t_plus_1",
)

FORBIDDEN_CLAIM_FIELDS: tuple[str, ...] = (
    "customer_validation_claim",
    "expert_validation_claim",
    "paid_signal_claim",
    "pricing_validation_claim",
    "compliance_legal_claim",
    "production_deployment_claim",
    "live_ledger_claim",
    "L4_execution_claim",
    "L5_readiness_claim",
)

ALLOWED_OWNER_APPROVAL_STATES: tuple[str, ...] = (
    "not_required",
    "pending_owner_decision",
    "approved",
    "rejected",
)


def build_ceo_cognitive_os_contract() -> CEOCognitiveOSContract:
    """Return the deterministic E81 CEO Cognitive OS contract v1."""

    return CEOCognitiveOSContract(
        contract_id="ceo_cognitive_os_loop_contract_v1",
        version="1.0.0",
        required_loop_stage_ids=MANDATORY_LOOP_STAGE_IDS,
        required_pre_action_fields=REQUIRED_PRE_ACTION_FIELDS,
        required_prediction_fields=REQUIRED_PREDICTION_FIELDS,
        required_post_action_fields=REQUIRED_POST_ACTION_FIELDS,
        required_post_cieu_fields=REQUIRED_POST_CIEU_FIELDS,
        forbidden_claim_fields=FORBIDDEN_CLAIM_FIELDS,
        allowed_owner_approval_states=ALLOWED_OWNER_APPROVAL_STATES,
    )


def validate_ceo_pre_action_packet(
    packet: Mapping[str, Any],
    contract: CEOCognitiveOSContract | None = None,
) -> CEOCognitiveOSDecision:
    """Validate a CEO major-action pre-action packet."""

    contract = contract or build_ceo_cognitive_os_contract()
    if not isinstance(packet, Mapping):
        return _decision("DENY", "pre-action packet must be a mapping", packet, "schema")

    missing = [field for field in contract.required_pre_action_fields if field not in packet]
    if missing:
        return _revision_decision(
            f"missing required fields: {', '.join(missing)}",
            packet,
            "schema",
            missing,
            missing_fields=missing,
        )

    if packet.get("bypass_attempt") is not False:
        return _decision("DENY", "bypass_attempt must be false", packet, "bypass_policy", ["bypass_attempt"])

    missing_stages = _missing_loop_stages(packet, contract)
    if missing_stages:
        return _revision_decision(
            f"missing mandatory loop stages: {', '.join(missing_stages[:6])}",
            packet,
            "cognitive_os_loop",
            missing_stages,
            missing_loop_stages=missing_stages,
        )

    cap_violation = _capability_evidence_violation(packet)
    if cap_violation:
        if "unverified runtime-active capability claim" in cap_violation:
            return _decision("DENY", cap_violation, packet, "repository_evidence", [cap_violation])
        return _revision_decision(
            cap_violation,
            packet,
            "repository_evidence",
            [cap_violation],
            required_evidence=["add repository evidence paths for every claimed capability"],
        )

    if packet.get("current_mission_context", {}).get("reasoning_scope") == "recent_memory_only":
        return _revision_decision(
            "recent-memory-only reasoning is not accepted",
            packet,
            "full_capability_inventory_recall",
            ["recent_memory_only"],
            required_packet_changes=[
                "rerun full repository-evidenced capability recall before selecting the action",
                "replace recent-memory-only context with discovered capability and historical asset evidence",
            ],
        )

    if len(_as_list(packet.get("candidate_actions"))) < 2:
        return _revision_decision(
            "at least two candidate actions are required",
            packet,
            "counterfactual_action_comparison",
            ["candidate_actions"],
            required_packet_changes=["add at least two plausible candidate actions"],
        )
    if len(_as_list(packet.get("counterfactual_comparison"))) < 2:
        return _revision_decision(
            "at least two counterfactual comparisons are required",
            packet,
            "counterfactual_action_comparison",
            ["counterfactual_comparison"],
            required_packet_changes=["compare at least two candidate actions before selecting one"],
        )

    prediction_violation = _prediction_violation(packet, contract)
    if prediction_violation:
        return _revision_decision(
            prediction_violation,
            packet,
            "pre_action_CIEU_residual_prediction",
            [prediction_violation],
            required_packet_changes=["complete pre-action CIEU prediction fields before revalidation"],
        )

    if not _present(packet.get("adversarial_critique")):
        return _revision_decision(
            "adversarial critique is required",
            packet,
            "adversarial_critique",
            ["adversarial_critique"],
            required_packet_changes=["add an adversarial critique of why the selected action could be wrong"],
        )
    if not _present(packet.get("what_not_to_do")):
        return _revision_decision(
            "what-not-to-do declaration is required",
            packet,
            "what_not_to_do",
            ["what_not_to_do"],
            required_packet_changes=["add explicit what-not-to-do constraints"],
        )

    if _is_construction_action(packet) and not _non_duplication_proven(packet.get("no_new_wheel_decision")):
        if _explicit_duplicate_core_mechanism(packet):
            return _decision(
                "DENY",
                "construction action proposes a duplicate core governance/audit/provider mechanism",
                packet,
                "no_new_wheel_gate",
                ["duplicate_core_mechanism"],
            )
        return _revision_decision(
            "construction action lacks no-new-wheel proof",
            packet,
            "no_new_wheel_gate",
            ["no_new_wheel_decision"],
            required_packet_changes=[
                "prove the action reuses, wraps, or extends the canonical owner instead of duplicating it"
            ],
        )

    owner_approval_state = packet.get("owner_approval_state")
    if owner_approval_state not in contract.allowed_owner_approval_states:
        return _revision_decision(
            "owner approval state is invalid",
            packet,
            "owner_approval_gate",
            ["owner_approval_state"],
            required_packet_changes=[
                "set owner_approval_state to one of: "
                + ", ".join(contract.allowed_owner_approval_states)
            ],
        )

    forbidden = _forbidden_claim_violation(packet.get("overclaim_boundary"), contract)
    if forbidden:
        return _decision("DENY", f"forbidden claim present: {forbidden}", packet, "overclaim_boundary", [forbidden])

    if _is_external_or_l4_execution(packet) and owner_approval_state != "approved":
        return _decision(
            "ESCALATE",
            "L4/external execution requires explicit owner approval",
            packet,
            "owner_approval_gate",
            ["owner_approval_required"],
            guidance=_owner_decision_guidance(packet),
            correct_path=[
                "prepare or present an owner decision packet for the scoped L4/external action",
                "do not execute until owner_approval_state is approved",
                "rerun CEO Cognitive OS validation after approval is recorded",
            ],
            requires_owner_decision=True,
        )

    return _decision("ALLOW", "CEO pre-action packet satisfies CEO Cognitive OS contract", packet)


def validate_ceo_post_action_residual(
    residual: Mapping[str, Any],
    contract: CEOCognitiveOSContract | None = None,
) -> CEOCognitiveOSDecision:
    """Validate a CEO post-action residual packet."""

    contract = contract or build_ceo_cognitive_os_contract()
    if not isinstance(residual, Mapping):
        return _decision("DENY", "post-action residual must be a mapping", residual, "post_action_schema")

    missing = [field for field in contract.required_post_action_fields if field not in residual]
    if missing:
        return _revision_decision(
            f"missing post-action fields: {', '.join(missing)}",
            residual,
            "post_action_schema",
            missing,
            missing_fields=missing,
        )

    cieu = residual.get("CIEU_record")
    if not isinstance(cieu, Mapping):
        return _revision_decision(
            "CIEU_record must be a mapping",
            residual,
            "post_action_CIEU_residual",
            ["CIEU_record"],
            required_packet_changes=["add a post-action CIEU_record mapping"],
        )
    missing_cieu = [field for field in contract.required_post_cieu_fields if not _present(cieu.get(field))]
    if missing_cieu:
        return _revision_decision(
            f"missing CIEU fields: {', '.join(missing_cieu)}",
            residual,
            "post_action_CIEU_residual",
            missing_cieu,
            missing_fields=missing_cieu,
        )

    forbidden = _forbidden_claim_violation(residual.get("overclaim_check"), contract)
    if forbidden:
        return _decision("DENY", f"forbidden post-action claim present: {forbidden}", residual, "post_action_overclaim_check", [forbidden])
    if residual.get("no_new_wheel_check", {}).get("passed") is not True:
        return _revision_decision(
            "no-new-wheel check failed",
            residual,
            "post_action_no_new_wheel_check",
            ["no_new_wheel_check"],
            required_packet_changes=["repair the residual with no-new-wheel evidence or record the violation"],
        )
    if residual.get("intelligence_gate_result", {}).get("passed") is not True:
        return _revision_decision(
            "intelligence gate failed",
            residual,
            "post_action_intelligence_gate",
            ["intelligence_gate_result"],
            required_packet_changes=["revise the output or route back to internal strategy before acceptance"],
        )

    return _decision("ALLOW", "CEO post-action residual satisfies CEO Cognitive OS contract", residual)


def build_ceo_cognitive_os_cieu_record(
    packet_or_residual: Mapping[str, Any],
    decision: CEOCognitiveOSDecision | Mapping[str, Any],
) -> dict[str, Any]:
    """Build a CIEU-style validation record without writing it anywhere."""

    decision_value = decision.decision.value if isinstance(decision, CEOCognitiveOSDecision) else str(decision.get("decision"))
    reason = decision.reason if isinstance(decision, CEOCognitiveOSDecision) else str(decision.get("reason", ""))
    guidance = decision.guidance if isinstance(decision, CEOCognitiveOSDecision) else dict(decision.get("guidance", {}))
    correct_path = (
        decision.correct_path
        if isinstance(decision, CEOCognitiveOSDecision)
        else list(decision.get("correct_path", []))
    )
    packet_id = packet_or_residual.get("packet_id") if isinstance(packet_or_residual, Mapping) else None
    return {
        "X_t": {
            "contract_id": "ceo_cognitive_os_loop_contract_v1",
            "packet_id": packet_id,
            "action_class": packet_or_residual.get("action_class") if isinstance(packet_or_residual, Mapping) else None,
        },
        "U_t": "Y-star-gov CEO Cognitive OS validation",
        "Y_star_t": "CEO major action must pass mandatory cognitive loop before acceptance",
        "Y_t_plus_1": {
            "decision": decision_value,
            "reason": reason,
            "guidance": guidance,
            "correct_path": correct_path,
        },
        "R_t_plus_1": (
            "none"
            if decision_value == "ALLOW"
            else {
                "residual": reason,
                "guidance_path": correct_path,
                "requires_owner_decision": (
                    decision.requires_owner_decision
                    if isinstance(decision, CEOCognitiveOSDecision)
                    else bool(decision.get("requires_owner_decision", False))
                ),
            }
        ),
    }


def _decision(
    value: str,
    reason: str,
    packet_or_residual: Mapping[str, Any],
    failed_stage: str | None = None,
    violations: list[str] | None = None,
    guidance: dict[str, Any] | None = None,
    correct_path: list[str] | None = None,
    requires_owner_decision: bool = False,
) -> CEOCognitiveOSDecision:
    decision_value = CEOCognitiveOSDecisionValue(value)
    provisional = CEOCognitiveOSDecision(
        decision=decision_value,
        reason=reason,
        failed_stage=failed_stage,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
    )
    return CEOCognitiveOSDecision(
        decision=decision_value,
        reason=reason,
        failed_stage=failed_stage,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
        cieu_validation_record=build_ceo_cognitive_os_cieu_record(packet_or_residual, provisional),
    )


def _revision_decision(
    reason: str,
    packet_or_residual: Mapping[str, Any],
    failed_stage: str,
    violations: list[str] | None = None,
    *,
    missing_fields: list[str] | None = None,
    missing_loop_stages: list[str] | None = None,
    required_evidence: list[str] | None = None,
    required_packet_changes: list[str] | None = None,
) -> CEOCognitiveOSDecision:
    guidance = _revision_guidance(
        failed_stage=failed_stage,
        missing_fields=missing_fields,
        missing_loop_stages=missing_loop_stages,
        required_evidence=required_evidence,
        required_packet_changes=required_packet_changes,
    )
    return _decision(
        "REQUIRE_REVISION",
        reason,
        packet_or_residual,
        failed_stage,
        violations,
        guidance=guidance,
        correct_path=guidance["correct_path"],
    )


def _revision_guidance(
    *,
    failed_stage: str,
    missing_fields: list[str] | None = None,
    missing_loop_stages: list[str] | None = None,
    required_evidence: list[str] | None = None,
    required_packet_changes: list[str] | None = None,
) -> dict[str, Any]:
    missing_fields = missing_fields or []
    missing_loop_stages = missing_loop_stages or []
    required_evidence = required_evidence or []
    required_packet_changes = required_packet_changes or []
    correct_path = [
        "repair the CEO Cognitive OS packet before execution",
        "do not execute the proposed action while decision is REQUIRE_REVISION",
        "rerun validate_ceo_pre_action_packet or validate_ceo_post_action_residual after repair",
    ]
    if missing_fields:
        correct_path.append("fill missing fields: " + ", ".join(missing_fields))
    if missing_loop_stages:
        correct_path.append("complete missing loop stages: " + ", ".join(missing_loop_stages[:8]))
    if required_evidence:
        correct_path.extend(required_evidence)
    if required_packet_changes:
        correct_path.extend(required_packet_changes)
    return {
        "guidance_type": "require_revision",
        "failed_stage": failed_stage,
        "missing_fields": list(missing_fields),
        "missing_loop_stages": list(missing_loop_stages),
        "required_evidence": list(required_evidence),
        "required_packet_changes": list(required_packet_changes),
        "revalidate_after_revision": True,
        "execution_allowed_before_revision": False,
        "correct_path": correct_path,
    }


def _owner_decision_guidance(packet: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "guidance_type": "owner_decision_required",
        "approval_required": True,
        "owner_approval_state": packet.get("owner_approval_state"),
        "required_packet_changes": [
            "record explicit owner approval before any L4/external execution",
            "keep outreach/publication/payment/login/mass-action boundaries denied unless separately approved",
        ],
        "revalidate_after_owner_decision": True,
        "execution_allowed_before_owner_decision": False,
    }


def _missing_loop_stages(packet: Mapping[str, Any], contract: CEOCognitiveOSContract) -> list[str]:
    results = packet.get("loop_stage_results")
    if not isinstance(results, list):
        return list(contract.required_loop_stage_ids)
    present = {
        str(item.get("stage_id"))
        for item in results
        if isinstance(item, Mapping) and item.get("stage_id") and item.get("status", "passed") != "failed"
    }
    return [stage_id for stage_id in contract.required_loop_stage_ids if stage_id not in present]


def _capability_evidence_violation(packet: Mapping[str, Any]) -> str:
    capabilities = packet.get("discovered_capabilities_consulted")
    if not isinstance(capabilities, list) or not capabilities:
        return "discovered capabilities with repository evidence are required"
    for index, capability in enumerate(capabilities):
        if not isinstance(capability, Mapping):
            return f"capability entry {index} must be a mapping"
        cap_id = capability.get("capability_id") or f"capability[{index}]"
        if not _present(capability.get("evidence_paths")):
            return f"capability lacks repository evidence paths: {cap_id}"
        if capability.get("claimed_runtime_active") is True and not _runtime_claim_verified(capability):
            return f"unverified runtime-active capability claim: {cap_id}"
    return ""


def _runtime_claim_verified(capability: Mapping[str, Any]) -> bool:
    if capability.get("runtime_evidence_status") in {"repository_verified", "runtime_active_verified"}:
        return True
    return capability.get("activation_state") in {
        "active_in_current_CEO_loop",
        "active_but_shallow",
        "readback_only",
        "legacy_promoted",
    }


def _prediction_violation(packet: Mapping[str, Any], contract: CEOCognitiveOSContract) -> str:
    predictions = packet.get("predicted_CIEU_records")
    if not isinstance(predictions, list) or not predictions:
        return "pre-action CIEU prediction is required"
    required = set(contract.required_prediction_fields)
    for index, prediction in enumerate(predictions):
        if not isinstance(prediction, Mapping):
            return f"predicted_CIEU_records[{index}] must be a mapping"
        missing = [field for field in required if not _present(prediction.get(field))]
        if missing:
            return f"predicted_CIEU_records[{index}] missing fields: {', '.join(missing)}"
    return ""


def _forbidden_claim_violation(claims: Any, contract: CEOCognitiveOSContract) -> str:
    if not isinstance(claims, Mapping):
        return ""
    for claim in contract.forbidden_claim_fields:
        if claims.get(claim) is True:
            return claim
    return ""


def _is_construction_action(packet: Mapping[str, Any]) -> bool:
    action_class = str(packet.get("action_class", "")).lower()
    proposed = str(packet.get("proposed_action", "")).lower()
    return "construction" in action_class or "new_module" in action_class or "construction" in proposed


def _is_external_or_l4_execution(packet: Mapping[str, Any]) -> bool:
    action_class = str(packet.get("action_class", "")).lower()
    selected = str(packet.get("selected_action", "")).lower()
    proposed = str(packet.get("proposed_action", "")).lower()
    if "owner_decision" in action_class or "packet_preparation" in action_class:
        return False
    return (
        "external_action" in action_class
        or "external_feedback_execution" in action_class
        or "l4_execution" in action_class
        or "execute_minimal_l4_feedback" in selected
        or "execute minimal l4 feedback" in proposed
    )


def _non_duplication_proven(value: Any) -> bool:
    return isinstance(value, Mapping) and _present(value.get("non_duplication_proof"))


def _explicit_duplicate_core_mechanism(packet: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(packet.get(field, ""))
        for field in (
            "proposed_action",
            "selected_action",
            "why_this_action",
            "why_not_other_actions",
        )
    ).lower()
    no_new_wheel = str(packet.get("no_new_wheel_decision", "")).lower()
    duplicate_terms = ("duplicate", "reimplement", "parallel", "clone")
    owner_terms = (
        "y-star-gov",
        "ystar-gov",
        "governance engine",
        "k9audit",
        "ledger",
        "verifier",
        "gov-mcp",
        "provider executor",
    )
    combined = f"{text} {no_new_wheel}"
    return any(term in combined for term in duplicate_terms) and any(term in combined for term in owner_terms)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


__all__ = [
    "CEOCognitiveOSContract",
    "CEOCognitiveOSDecision",
    "CEOCognitiveOSDecisionValue",
    "build_ceo_cognitive_os_cieu_record",
    "build_ceo_cognitive_os_contract",
    "validate_ceo_post_action_residual",
    "validate_ceo_pre_action_packet",
]
