"""Runtime hook wrapper for CEO Cognitive OS validation.

This module turns a CEO major-action runtime envelope into a deterministic
Y-star-gov runtime decision. It is intentionally small: bridge-labs still
produces the CEO packets, the CEO Cognitive OS contract module validates them,
and this wrapper only performs classification, routing, and safety boundaries.

It does not execute external actions. It does not call providers. It does not
write a formal CIEU log; validator output remains a CIEU validation record
candidate until a separately verified CIEU log insertion point is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.ceo_cognitive_os_contract import (
    CEOCognitiveOSDecision,
    CEOCognitiveOSDecisionValue,
    build_ceo_cognitive_os_cieu_record,
    validate_ceo_post_action_residual,
    validate_ceo_pre_action_packet,
)


class CEOCognitiveOSRuntimeDecisionValue(str, Enum):
    """Runtime decision values for CEO Cognitive OS hook envelopes."""

    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"
    STATUS_ONLY = "STATUS_ONLY"


@dataclass(frozen=True)
class CEOMajorActionClassification:
    """Deterministic classification for CEO runtime envelopes."""

    requires_ceo_cognitive_os: bool
    categories: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requires_ceo_cognitive_os": self.requires_ceo_cognitive_os,
            "categories": list(self.categories),
            "signals": list(self.signals),
        }


@dataclass(frozen=True)
class CEOCognitiveOSRuntimeResult:
    """Runtime routing result for a CEO major-action envelope."""

    decision: CEOCognitiveOSRuntimeDecisionValue
    route: str
    reason: str
    action_id: Optional[str] = None
    classification: CEOMajorActionClassification = field(
        default_factory=lambda: CEOMajorActionClassification(False)
    )
    validator_result: dict[str, Any] = field(default_factory=dict)
    post_action_residual_validation: dict[str, Any] = field(default_factory=dict)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    cieu_validation_record_candidate: dict[str, Any] = field(default_factory=dict)
    requires_owner_decision: bool = False
    post_action_residual_required: bool = False
    allow_approved_next_step: bool = False
    allow_external_execution: bool = False
    external_action_executed: bool = False
    provider_live_execution: bool = False
    formal_CIEU_log_written: bool = False
    formal_CIEU_log_status: str = "CIEU_log_write_deferred"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_cognitive_os_runtime_hook_result",
            "action_id": self.action_id,
            "decision": self.decision.value,
            "route": self.route,
            "reason": self.reason,
            "classification": self.classification.to_dict(),
            "validator_result": dict(self.validator_result),
            "post_action_residual_validation": dict(self.post_action_residual_validation),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "cieu_validation_record_candidate": dict(self.cieu_validation_record_candidate),
            "hook_decision_envelope": self.hook_decision_envelope(),
            "requires_owner_decision": self.requires_owner_decision,
            "post_action_residual_required": self.post_action_residual_required,
            "allow_approved_next_step": self.allow_approved_next_step,
            "allow_external_execution": self.allow_external_execution,
            "external_action_executed": self.external_action_executed,
            "provider_live_execution": self.provider_live_execution,
            "formal_CIEU_log_written": self.formal_CIEU_log_written,
            "formal_CIEU_log_status": self.formal_CIEU_log_status,
        }

    def hook_decision_envelope(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "decision": self.decision.value,
            "route": self.route,
            "allow_execution": False,
            "allow_approved_next_step": self.allow_approved_next_step,
            "allow_external_execution": False,
            "require_revision": self.decision == CEOCognitiveOSRuntimeDecisionValue.REQUIRE_REVISION,
            "deny": self.decision == CEOCognitiveOSRuntimeDecisionValue.DENY,
            "escalate": self.decision == CEOCognitiveOSRuntimeDecisionValue.ESCALATE,
            "status_only": self.decision == CEOCognitiveOSRuntimeDecisionValue.STATUS_ONLY,
            "correct_path": list(self.correct_path),
            "guidance": dict(self.guidance),
            "owner_decision_path_required": self.requires_owner_decision,
            "external_action_executed": False,
            "provider_live_execution": False,
            "formal_CIEU_log_written": False,
            "formal_CIEU_log_status": self.formal_CIEU_log_status,
        }


MAJOR_ACTION_TERMS: dict[str, tuple[str, ...]] = {
    "external_read_write_action": ("external", "public-read", "public read", "external feedback"),
    "customer_contact_action": ("customer", "contact", "outreach", "email", "message", "expert"),
    "payment_revenue_pricing_action": ("payment", "paid", "revenue", "pricing", "invoice", "checkout"),
    "public_publication": ("publish", "publication", "social post", "blog post", "public launch"),
    "provider_tool_execution": ("provider", "mcp", "tool execution", "live execution", "api call"),
    "strategy_mutation": ("strategy", "thesis", "route", "positioning", "commercial"),
    "canonical_y_star_mutation": ("y-star-gov", "ystar-gov", "canonical governance", "governance mutation"),
    "brain_memory_write": ("brain", "memory", "kg write", "knowledge graph write"),
    "CIEU_log_write_claim": ("cieu log", "cieu store", "cieu ledger", "formal cieu"),
    "cross_repo_governance_mutation": ("cross-repo", "cross repo", "governance sync", "runtime hook"),
    "owner_approval_boundary_crossing": ("owner approval", "owner decision", "approval boundary"),
    "L4_L5_escalation_attempt": ("l4", "l5", "external feedback", "revenue loop"),
}

INTERNAL_EXTERNALITY_VALUES = {"", "none", "internal", "local", "readback_only", "readback-only"}


def classify_ceo_major_action(envelope: Mapping[str, Any]) -> CEOMajorActionClassification:
    """Classify whether a runtime envelope is a CEO major action."""

    if not isinstance(envelope, Mapping):
        return CEOMajorActionClassification(False, [], ["envelope_not_mapping"])

    categories: set[str] = set()
    signals: list[str] = []
    text = _action_request_text(envelope)
    action_type = str(envelope.get("action_type", "")).lower()
    role = str(envelope.get("role") or envelope.get("actor") or "").lower()
    externality_level = str(envelope.get("externality_level", "")).lower()

    if envelope.get("requires_ceo_cognitive_os") is True:
        categories.add("explicit_ceo_cognitive_os_required")
        signals.append("requires_ceo_cognitive_os=true")
    if role == "ceo" and action_type in {"major_action", "runtime_major_action", "owner_decision_boundary"}:
        categories.add("ceo_major_action_declared")
        signals.append(f"role={role}; action_type={action_type}")
    if externality_level not in INTERNAL_EXTERNALITY_VALUES:
        categories.add("external_read_write_action")
        signals.append(f"externality_level={externality_level}")

    for category, terms in MAJOR_ACTION_TERMS.items():
        matched = [term for term in terms if term in text]
        if matched:
            categories.add(category)
            signals.append(f"{category}: {', '.join(matched[:4])}")

    return CEOMajorActionClassification(
        requires_ceo_cognitive_os=bool(categories),
        categories=sorted(categories),
        signals=signals,
    )


def validate_ceo_runtime_envelope(envelope: Mapping[str, Any]) -> CEOCognitiveOSRuntimeResult:
    """Validate a proposed CEO major action through the runtime hook wrapper."""

    if not isinstance(envelope, Mapping):
        return _runtime_result(
            decision="DENY",
            route="block_execution_and_record_residual",
            reason="CEO runtime envelope must be a mapping",
            envelope={},
            classification=CEOMajorActionClassification(False, [], ["envelope_not_mapping"]),
            failed_stage="runtime_envelope_schema",
            violations=["runtime_envelope_schema"],
        )

    classification = classify_ceo_major_action(envelope)
    action_id = _action_id(envelope)
    if not classification.requires_ceo_cognitive_os:
        return CEOCognitiveOSRuntimeResult(
            decision=CEOCognitiveOSRuntimeDecisionValue.STATUS_ONLY,
            route="no_ceo_cognitive_os_required_no_external_execution",
            reason="runtime envelope is not classified as a CEO major action",
            action_id=action_id,
            classification=classification,
        )

    hard_boundary = _hard_boundary_violation(envelope)
    if hard_boundary:
        return _runtime_result(
            decision="DENY",
            route="block_execution_and_record_residual",
            reason=hard_boundary,
            envelope=envelope,
            classification=classification,
            failed_stage="runtime_hard_boundary",
            violations=[hard_boundary],
        )

    packet = envelope.get("pre_action_packet") or envelope.get("ceo_pre_action_packet")
    if not isinstance(packet, Mapping):
        return _revision_runtime_result(
            reason="CEO major action requires a pre-action packet before runtime acceptance",
            envelope=envelope,
            classification=classification,
            failed_stage="pre_action_packet_required",
            required_packet_changes=["attach pre_action_packet generated by bridge-labs CEO Cognitive OS"],
        )

    if _is_post_action_phase(envelope):
        residual = envelope.get("post_action_residual")
        if not isinstance(residual, Mapping):
            return _revision_runtime_result(
                reason="completed CEO major action requires post-action residual validation",
                envelope=envelope,
                classification=classification,
                failed_stage="post_action_residual_required",
                required_packet_changes=["attach post_action_residual and validate it before closure"],
                post_action_residual_required=True,
            )
        residual_decision = validate_ceo_post_action_residual(residual)
        mapped = _from_validator_decision(
            residual_decision,
            envelope=envelope,
            classification=classification,
            validator_name="validate_ceo_post_action_residual",
        )
        return CEOCognitiveOSRuntimeResult(
            **{
                **mapped.__dict__,
                "post_action_residual_validation": residual_decision.to_dict(),
                "post_action_residual_required": True,
            }
        )

    pre_decision = validate_ceo_pre_action_packet(packet)
    result = _from_validator_decision(
        pre_decision,
        envelope=envelope,
        classification=classification,
        validator_name="validate_ceo_pre_action_packet",
    )
    return CEOCognitiveOSRuntimeResult(
        **{
            **result.__dict__,
            "post_action_residual_required": True,
        }
    )


def _from_validator_decision(
    decision: CEOCognitiveOSDecision,
    *,
    envelope: Mapping[str, Any],
    classification: CEOMajorActionClassification,
    validator_name: str,
) -> CEOCognitiveOSRuntimeResult:
    value = decision.decision.value
    route_by_decision = {
        "ALLOW": "continue_to_approved_next_step_without_external_execution",
        "REQUIRE_REVISION": "return_correct_path_guidance_to_ceo",
        "ESCALATE": "generate_owner_decision_packet_no_execution",
        "DENY": "block_execution_and_record_residual",
    }
    return CEOCognitiveOSRuntimeResult(
        decision=CEOCognitiveOSRuntimeDecisionValue(value),
        route=route_by_decision.get(value, "block_execution_and_record_residual"),
        reason=decision.reason,
        action_id=_action_id(envelope),
        classification=classification,
        validator_result={"validator": validator_name, **decision.to_dict()},
        guidance=dict(decision.guidance),
        correct_path=list(decision.correct_path),
        cieu_validation_record_candidate=dict(decision.cieu_validation_record),
        requires_owner_decision=bool(decision.requires_owner_decision),
        post_action_residual_required=True,
        allow_approved_next_step=decision.decision == CEOCognitiveOSDecisionValue.ALLOW,
        allow_external_execution=False,
    )


def _runtime_result(
    *,
    decision: str,
    route: str,
    reason: str,
    envelope: Mapping[str, Any],
    classification: CEOMajorActionClassification,
    failed_stage: str,
    violations: list[str],
) -> CEOCognitiveOSRuntimeResult:
    decision_value = CEOCognitiveOSRuntimeDecisionValue(decision)
    candidate = build_ceo_cognitive_os_cieu_record(
        envelope,
        {
            "decision": decision,
            "reason": reason,
            "failed_stage": failed_stage,
            "violations": violations,
            "guidance": {},
            "correct_path": [],
            "requires_owner_decision": False,
        },
    )
    return CEOCognitiveOSRuntimeResult(
        decision=decision_value,
        route=route,
        reason=reason,
        action_id=_action_id(envelope),
        classification=classification,
        validator_result={
            "validator": "ceo_cognitive_os_runtime_hook_precheck",
            "decision": decision,
            "reason": reason,
            "failed_stage": failed_stage,
            "violations": violations,
        },
        cieu_validation_record_candidate=candidate,
        post_action_residual_required=True,
    )


def _revision_runtime_result(
    *,
    reason: str,
    envelope: Mapping[str, Any],
    classification: CEOMajorActionClassification,
    failed_stage: str,
    required_packet_changes: list[str],
    post_action_residual_required: bool = False,
) -> CEOCognitiveOSRuntimeResult:
    guidance = {
        "guidance_type": "require_revision",
        "failed_stage": failed_stage,
        "required_packet_changes": list(required_packet_changes),
        "revalidate_after_revision": True,
        "execution_allowed_before_revision": False,
        "correct_path": [
            "repair the CEO runtime envelope before execution",
            "do not execute the proposed action while decision is REQUIRE_REVISION",
            *required_packet_changes,
        ],
    }
    candidate = build_ceo_cognitive_os_cieu_record(
        envelope,
        {
            "decision": "REQUIRE_REVISION",
            "reason": reason,
            "guidance": guidance,
            "correct_path": guidance["correct_path"],
            "requires_owner_decision": False,
        },
    )
    return CEOCognitiveOSRuntimeResult(
        decision=CEOCognitiveOSRuntimeDecisionValue.REQUIRE_REVISION,
        route="return_correct_path_guidance_to_ceo",
        reason=reason,
        action_id=_action_id(envelope),
        classification=classification,
        validator_result={
            "validator": "ceo_cognitive_os_runtime_hook_precheck",
            "decision": "REQUIRE_REVISION",
            "reason": reason,
            "failed_stage": failed_stage,
            "guidance": guidance,
            "correct_path": guidance["correct_path"],
        },
        guidance=guidance,
        correct_path=guidance["correct_path"],
        cieu_validation_record_candidate=candidate,
        post_action_residual_required=post_action_residual_required or True,
    )


def _hard_boundary_violation(envelope: Mapping[str, Any]) -> str:
    packet = envelope.get("pre_action_packet") or envelope.get("ceo_pre_action_packet") or {}
    text = _envelope_text(envelope)
    if envelope.get("bypass_attempt") is True or (
        isinstance(packet, Mapping) and packet.get("bypass_attempt") is True
    ):
        return "bypass attempt is a hard runtime boundary violation"
    if envelope.get("formal_CIEU_log_written") is True or envelope.get("claims_formal_CIEU_log_write") is True:
        return "formal CIEU log write claim is denied unless an existing CIEU log path actually wrote it"
    if isinstance(packet, Mapping) and packet.get("current_mission_context", {}).get("reasoning_scope") == "recent_memory_only":
        return "recent-memory-only reasoning is denied at runtime for CEO major actions"
    if not _evidence_basis_present(envelope, packet):
        return "CEO major action lacks repository evidence basis"
    if _proposes_forbidden_external_action(envelope, packet):
        return "forbidden external action is denied at runtime"
    if _claims_duplicate_core_mechanism(envelope, packet):
        return "duplicate or reinvented core mechanism is denied at runtime"
    if "formal cieu log written" in text or ("cieu-style" in text and "trace" in text):
        return "unsupported CIEU terminology claim is denied"
    return ""


def _evidence_basis_present(envelope: Mapping[str, Any], packet: Any) -> bool:
    evidence = envelope.get("evidence_basis")
    if _present(evidence):
        return True
    if isinstance(packet, Mapping):
        capabilities = packet.get("discovered_capabilities_consulted")
        return isinstance(capabilities, list) and any(
            isinstance(capability, Mapping) and _present(capability.get("evidence_paths"))
            for capability in capabilities
        )
    return False


def _proposes_forbidden_external_action(envelope: Mapping[str, Any], packet: Any) -> bool:
    text = _envelope_text(envelope)
    hard_terms = (
        "mass outreach",
        "send email",
        "send message",
        "payment",
        "checkout",
        "publish",
        "publication",
        "login",
        "account creation",
        "form submission",
        "provider live execution",
        "live mcp execution",
    )
    if any(_term_requested(text, term) for term in hard_terms):
        owner_state = str(envelope.get("owner_approval_status") or envelope.get("owner_approval_state") or "").lower()
        if owner_state != "approved":
            return True
    if isinstance(packet, Mapping):
        safety = packet.get("safety_boundary")
        if isinstance(safety, Mapping) and safety.get("external_action_allowed") is True:
            owner_state = str(packet.get("owner_approval_state", "")).lower()
            return owner_state != "approved"
    return False


def _claims_duplicate_core_mechanism(envelope: Mapping[str, Any], packet: Any) -> bool:
    text = _envelope_text(envelope)
    if isinstance(packet, Mapping):
        no_new_wheel = packet.get("no_new_wheel_decision")
        if isinstance(no_new_wheel, Mapping):
            no_new_wheel_text = _mapping_text(no_new_wheel)
            if any(
                marker in no_new_wheel_text
                for marker in (
                    "no bridge-labs governance clone",
                    "no governance clone",
                    "non_duplication_proof",
                    "call_existing",
                    "reuse_existing",
                    "wrap_existing",
                )
            ):
                return False
        text = f"{text} {_mapping_text(packet)}"
    duplicate_terms = ("duplicate", "reimplement", "parallel", "clone")
    core_terms = ("y-star-gov", "governance engine", "k9audit", "ledger", "gov-mcp", "provider executor")
    return any(term in text for term in duplicate_terms) and any(term in text for term in core_terms)


def _is_post_action_phase(envelope: Mapping[str, Any]) -> bool:
    phase = str(envelope.get("action_phase") or envelope.get("runtime_phase") or "").lower()
    return phase in {"post_action", "completed", "closure"} or envelope.get("completed_action") is True


def _action_id(envelope: Mapping[str, Any]) -> Optional[str]:
    value = envelope.get("action_id") or envelope.get("packet_id")
    return str(value) if value else None


def _envelope_text(envelope: Mapping[str, Any]) -> str:
    fields = (
        "action_id",
        "actor",
        "role",
        "action_type",
        "mission",
        "objective",
        "declared_intent",
        "context",
        "proposed_execution_boundary",
        "externality_level",
        "owner_approval_status",
        "selected_action",
        "proposed_action",
        "action_class",
    )
    return " ".join(str(envelope.get(field, "")) for field in fields).lower()


def _action_request_text(envelope: Mapping[str, Any]) -> str:
    fields = (
        "action_type",
        "mission",
        "objective",
        "declared_intent",
        "proposed_execution_boundary",
        "selected_action",
        "proposed_action",
        "action_class",
    )
    return " ".join(str(envelope.get(field, "")) for field in fields).lower()


def _term_requested(text: str, term: str) -> bool:
    if term not in text:
        return False
    negations = (f"no {term}", f"not {term}", f"without {term}", f"do not {term}")
    return not any(negation in text for negation in negations)


def _mapping_text(value: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for item in value.values():
        if isinstance(item, Mapping):
            parts.append(_mapping_text(item))
        elif isinstance(item, list):
            parts.extend(str(part) for part in item[:10])
        else:
            parts.append(str(item))
    return " ".join(parts).lower()


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


__all__ = [
    "CEOCognitiveOSRuntimeDecisionValue",
    "CEOCognitiveOSRuntimeResult",
    "CEOMajorActionClassification",
    "classify_ceo_major_action",
    "validate_ceo_runtime_envelope",
]
