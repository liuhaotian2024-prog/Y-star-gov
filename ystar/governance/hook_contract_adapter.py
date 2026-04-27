"""Deterministic dry-run adapter for future hook contract envelopes.

This module models the future hook boundary without connecting to a real hook.
It normalizes a hook-like envelope into a Pre-U packet, runs the local
governance contract dry-run harness, and returns a hook-like decision envelope.
It never executes actions, calls hooks, writes CIEU records, reads DBs/logs, or
mutates brain/memory state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.contract_dry_run import (
    DryRunDecision,
    DryRunResult,
    run_governance_contract_dry_run,
)


class HookAdapterDecision(str, Enum):
    """Hook-like decision values returned by the dry-run adapter."""

    ALLOW = "allow"
    WARN = "warn"
    REQUIRE_REVISION = "require_revision"
    DENY = "deny"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class HookAdapterIssue:
    """One deterministic issue found while adapting a hook envelope."""

    code: str
    message: str
    field: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "field": self.field,
        }


@dataclass(frozen=True)
class HookAdapterResult:
    """Structured hook-like dry-run adapter result."""

    decision: HookAdapterDecision
    hook_decision_envelope: dict[str, Any]
    dry_run_result: Optional[DryRunResult] = None
    normalized_packet: Optional[dict[str, Any]] = None
    issues: list[HookAdapterIssue] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=list)

    @property
    def allow_execution(self) -> bool:
        return bool(self.hook_decision_envelope.get("allow_execution"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "allow_execution": self.allow_execution,
            "hook_decision_envelope": dict(self.hook_decision_envelope),
            "dry_run_result": self.dry_run_result.to_dict() if self.dry_run_result is not None else None,
            "normalized_packet": dict(self.normalized_packet) if self.normalized_packet is not None else None,
            "issues": [issue.to_dict() for issue in self.issues],
            "safety_notes": list(self.safety_notes),
        }


SAFETY_NOTES = [
    "Hook adapter dry-run only: no real hook is called.",
    "Selected_U is never executed, even when the decision envelope says allow_execution=true.",
    "No CIEU write, DB/log/runtime read, brain/memory mutation, or external tool call occurs.",
]

REQUIRED_ENVELOPE_FIELDS = (
    "hook_event_id",
    "agent_id",
    "packet_id",
    "declared_Y_star",
    "Xt",
    "m_functor",
    "candidate_U",
    "selected_U_id",
    "why_min_residual",
    "governance_expectations",
    "cieu_link_policy",
)


def run_hook_contract_dry_run(envelope: Mapping[str, Any]) -> HookAdapterResult:
    """Run a local non-executing hook contract dry-run."""

    issues = _validate_envelope(envelope)
    if issues:
        decision = HookAdapterDecision.REQUIRE_REVISION
        decision_envelope = _decision_envelope(
            envelope=envelope if isinstance(envelope, Mapping) else {},
            decision=decision,
            dry_run_result=None,
            issues=issues,
        )
        return HookAdapterResult(
            decision=decision,
            hook_decision_envelope=decision_envelope,
            dry_run_result=None,
            normalized_packet=None,
            issues=issues,
            safety_notes=list(SAFETY_NOTES),
        )

    packet = _normalize_to_pre_u_packet(envelope)
    dry_run_result = run_governance_contract_dry_run(packet, outcome=envelope.get("mock_outcome"))
    decision = _decision_from_dry_run(dry_run_result.dry_run_decision)
    decision_envelope = _decision_envelope(
        envelope=envelope,
        decision=decision,
        dry_run_result=dry_run_result,
        issues=[],
    )
    return HookAdapterResult(
        decision=decision,
        hook_decision_envelope=decision_envelope,
        dry_run_result=dry_run_result,
        normalized_packet=packet,
        issues=[],
        safety_notes=list(SAFETY_NOTES),
    )


def _validate_envelope(envelope: Mapping[str, Any]) -> list[HookAdapterIssue]:
    if not isinstance(envelope, Mapping):
        return [
            HookAdapterIssue(
                code="HOOK-ADAPTER-SCHEMA",
                message="Hook envelope must be a mapping/object.",
            )
        ]

    issues: list[HookAdapterIssue] = []
    for field_name in REQUIRED_ENVELOPE_FIELDS:
        if not _is_non_empty(envelope.get(field_name)):
            issues.append(
                HookAdapterIssue(
                    code="HOOK-ADAPTER-MISSING-FIELD",
                    message=f"{field_name} is missing or empty.",
                    field=field_name,
                )
            )

    candidates = envelope.get("candidate_U")
    if candidates is not None and (not isinstance(candidates, list) or not candidates):
        issues.append(
            HookAdapterIssue(
                code="HOOK-ADAPTER-CANDIDATES",
                message="candidate_U must be a non-empty list.",
                field="candidate_U",
            )
        )
    return issues


def _normalize_to_pre_u_packet(envelope: Mapping[str, Any]) -> dict[str, Any]:
    agent_id = str(envelope["agent_id"])
    hook_event_id = str(envelope["hook_event_id"])
    packet_id = str(envelope["packet_id"])

    return {
        "packet_id": packet_id,
        "agent_id": agent_id,
        "agent_capsule_ref": envelope.get("agent_capsule_ref", f"hook-envelope://agent/{agent_id}"),
        "task_id": envelope.get("task_id", hook_event_id),
        "Y*": envelope["declared_Y_star"],
        "Xt": envelope["Xt"],
        "m_functor": envelope["m_functor"],
        "candidate_U": [_normalize_candidate(candidate) for candidate in envelope["candidate_U"]],
        "selected_U": {"selected_candidate_id": str(envelope["selected_U_id"])},
        "why_min_residual": envelope["why_min_residual"],
        "governance_expectations": envelope["governance_expectations"],
        "cieu_link_policy": envelope["cieu_link_policy"],
        "packet_status": envelope.get("packet_status", "ready_for_validation"),
        "risk_tier": envelope.get("risk_tier", "normal"),
    }


def _normalize_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        return {"candidate_id": "", "predicted_r_t1": None}
    return {
        "candidate_id": candidate.get("candidate_id") or candidate.get("id") or candidate.get("name"),
        "u_summary": candidate.get("u_summary") or candidate.get("description") or candidate.get("action_type"),
        "action_type": candidate.get("action_type"),
        "predicted_y_t1": (
            candidate.get("predicted_y_t1")
            or candidate.get("predicted_Yt_plus_1")
            or candidate.get("predicted_Yt+1")
        ),
        "predicted_r_t1": (
            candidate.get("predicted_r_t1")
            or candidate.get("predicted_Rt_plus_1")
            or candidate.get("predicted_Rt+1")
        ),
    }


def _decision_from_dry_run(decision: DryRunDecision) -> HookAdapterDecision:
    if decision == DryRunDecision.PASS:
        return HookAdapterDecision.ALLOW
    if decision == DryRunDecision.WARN:
        return HookAdapterDecision.WARN
    if decision == DryRunDecision.REQUIRE_REVISION:
        return HookAdapterDecision.REQUIRE_REVISION
    if decision == DryRunDecision.DENY:
        return HookAdapterDecision.DENY
    return HookAdapterDecision.ESCALATE


def _decision_envelope(
    envelope: Mapping[str, Any],
    decision: HookAdapterDecision,
    dry_run_result: Optional[DryRunResult],
    issues: list[HookAdapterIssue],
) -> dict[str, Any]:
    allow_execution = decision in {HookAdapterDecision.ALLOW, HookAdapterDecision.WARN}
    return {
        "hook_event_id": envelope.get("hook_event_id"),
        "packet_id": envelope.get("packet_id"),
        "agent_id": envelope.get("agent_id"),
        "decision": decision.value,
        "allow_execution": allow_execution,
        "require_revision": decision == HookAdapterDecision.REQUIRE_REVISION,
        "escalate": decision == HookAdapterDecision.ESCALATE,
        "deny": decision == HookAdapterDecision.DENY,
        "dry_run_only": True,
        "non_execution_confirmation": True,
        "governance_result_summary": _governance_summary(dry_run_result),
        "issues": [issue.to_dict() for issue in issues],
        "safety_notes": list(SAFETY_NOTES),
    }


def _governance_summary(dry_run_result: Optional[DryRunResult]) -> dict[str, Any]:
    if dry_run_result is None:
        return {
            "dry_run_decision": None,
            "pre_u_validation_status": None,
            "delta_validation_status": None,
        }
    return {
        "dry_run_decision": dry_run_result.dry_run_decision.value,
        "pre_u_validation_status": dry_run_result.pre_u_validation_result.validation_status,
        "delta_validation_status": (
            dry_run_result.delta_validation_result.validation_status
            if dry_run_result.delta_validation_result is not None
            else None
        ),
    }


def _is_non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True
