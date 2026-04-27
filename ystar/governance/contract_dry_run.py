"""Deterministic governance contract dry-run harness.

This module connects the Pre-U packet validator to the CIEU prediction-delta
validator in a local, non-executing simulation. It does not execute selected
actions, call hooks, write CIEU records, mutate memory/brain state, read DBs, or
contact external systems.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_prediction_delta import (
    DeltaValidationDecision,
    DeltaValidationResult,
    validate_prediction_delta,
)
from ystar.governance.pre_u_packet_validator import (
    ValidationDecision,
    ValidationResult,
    validate_pre_u_packet,
)


class DryRunDecision(str, Enum):
    """Decision values for the local governance dry-run."""

    PASS = "pass"
    WARN = "warn"
    REQUIRE_REVISION = "require_revision"
    DENY = "deny"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class DryRunIssue:
    """One issue raised by the dry-run harness itself."""

    code: str
    message: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "source": self.source,
        }


@dataclass(frozen=True)
class DryRunResult:
    """Structured result for the governance contract dry-run."""

    dry_run_decision: DryRunDecision
    pre_u_validation_result: ValidationResult
    delta_validation_result: Optional[DeltaValidationResult] = None
    generated_delta_record: Optional[dict[str, Any]] = None
    issues: list[DryRunIssue] = field(default_factory=list)
    safety_notes: list[str] = field(default_factory=list)
    non_execution_confirmation: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.dry_run_decision == DryRunDecision.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run_decision": self.dry_run_decision.value,
            "passed": self.passed,
            "pre_u_validation_result": self.pre_u_validation_result.to_dict(),
            "delta_validation_result": (
                self.delta_validation_result.to_dict()
                if self.delta_validation_result is not None
                else None
            ),
            "generated_delta_record": self.generated_delta_record,
            "issues": [issue.to_dict() for issue in self.issues],
            "safety_notes": list(self.safety_notes),
            "non_execution_confirmation": dict(self.non_execution_confirmation),
        }


NON_EXECUTION_CONFIRMATION = {
    "selected_u_executed": False,
    "hook_called": False,
    "cieu_written": False,
    "db_read": False,
    "brain_or_memory_mutated": False,
    "external_system_called": False,
}

SAFETY_NOTES = [
    "Dry-run only: selected_U is never executed.",
    "No hook, daemon, runtime, tool, DB, CIEU write, brain, or memory path is called.",
    "Generated delta records are structural simulation artifacts only.",
]


def run_governance_contract_dry_run(
    packet: Mapping[str, Any],
    outcome: Optional[Mapping[str, Any]] = None,
) -> DryRunResult:
    """Run a local non-executing governance contract simulation."""

    pre_u_result = validate_pre_u_packet(packet)
    issues: list[DryRunIssue] = []

    if pre_u_result.decision in {
        ValidationDecision.DENY,
        ValidationDecision.REQUIRE_REVISION,
    }:
        issues.append(
            DryRunIssue(
                code="DRY-RUN-PREU-NOT-READY",
                message="Pre-U validation did not reach a delta-eligible state.",
                source="pre_u_validator",
            )
        )
        return DryRunResult(
            dry_run_decision=DryRunDecision.REQUIRE_REVISION,
            pre_u_validation_result=pre_u_result,
            delta_validation_result=None,
            generated_delta_record=None,
            issues=issues,
            safety_notes=list(SAFETY_NOTES),
            non_execution_confirmation=dict(NON_EXECUTION_CONFIRMATION),
        )

    delta_record = build_prediction_delta_record(packet, outcome)
    delta_result = validate_prediction_delta(delta_record)
    decision = _dry_run_decision_for(pre_u_result, delta_result)

    return DryRunResult(
        dry_run_decision=decision,
        pre_u_validation_result=pre_u_result,
        delta_validation_result=delta_result,
        generated_delta_record=delta_record,
        issues=issues,
        safety_notes=list(SAFETY_NOTES),
        non_execution_confirmation=dict(NON_EXECUTION_CONFIRMATION),
    )


def build_prediction_delta_record(
    packet: Mapping[str, Any],
    outcome: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Construct a deterministic dry-run prediction-delta record."""

    outcome = outcome or {}
    packet_id = _get(packet, "packet_id", default="dry-run-packet")
    agent_id = _get(packet, "agent_id", default="unknown-agent")
    selected_action = _get(packet, "selected_action", "selected_U", "selected_u", default={})
    selected_id = _selected_candidate_id(selected_action)
    candidate = _selected_candidate(packet, selected_id) or {}

    predicted_y = _get(
        candidate,
        "predicted_y_t1",
        "predicted_Yt_plus_1",
        "predicted_Yt+1",
        default="dry-run predicted outcome",
    )
    predicted_r = _get(
        candidate,
        "predicted_r_t1",
        "predicted_Rt_plus_1",
        "predicted_Rt+1",
        default={"summary": "dry-run predicted residual"},
    )

    actual_y = _get(outcome, "actual_y_t1", "actual_Yt_plus_1", "actual_Yt+1", default=predicted_y)
    actual_r = _get(
        outcome,
        "actual_r_t1",
        "actual_Rt_plus_1",
        "actual_Rt+1",
        default={"summary": "dry-run actual residual mirrors prediction"},
    )

    record = {
        "event_id": _get(outcome, "event_id", default=f"dry-run-delta::{packet_id}"),
        "packet_id": packet_id,
        "agent_id": agent_id,
        "recorded_at": _get(outcome, "recorded_at", "timestamp", default="dry-run-no-runtime-clock"),
        "declared_y_star": _get(packet, "y_star", "Y*", "Y_star", default="dry-run y_star"),
        "selected_u": selected_id,
        "predicted_y_t1": predicted_y,
        "predicted_r_t1": predicted_r,
        "x_t": _get(packet, "x_t_summary", "Xt", default="dry-run Xt"),
        "u": _get(outcome, "u", "U", default=selected_id),
        "actual_y_t1": actual_y,
        "actual_r_t1": actual_r,
        "delta_summary": _get(
            outcome,
            "delta_summary",
            default="Dry-run simulated delta; not runtime CIEU evidence.",
        ),
        "residual_delta": _get(
            outcome,
            "residual_delta",
            default={"direction": "dry_run_no_runtime_measurement"},
        ),
        "delta_class": _get(outcome, "delta_class", "deviation_class", default="dry_run"),
        "learning_eligibility": _get(
            outcome,
            "learning_eligibility",
            default={
                "eligible": False,
                "reason": "dry_run_only",
                "requires_curation": True,
            },
        ),
        "cieu_record_ref": _get(outcome, "cieu_record_ref", "cieu_event_ref", default="dry-run://not-runtime-cieu"),
        "governance_decision_ref": _get(
            outcome,
            "governance_decision_ref",
            "validator_result_ref",
            default=f"dry-run://pre-u-validation/{packet_id}",
        ),
        "brain_writeback_policy": _get(
            outcome,
            "brain_writeback_policy",
            default={
                "eligible_after_curation": False,
                "requires_curation": True,
                "automatic_direct_writeback": False,
                "dry_run_only": True,
            },
        ),
        "dry_run_only": True,
        "not_runtime_cieu": True,
        "not_brain_writeback_eligible": True,
    }

    if "risk_level" in outcome:
        record["risk_level"] = outcome["risk_level"]
    elif "risk_tier" in packet:
        record["risk_level"] = packet["risk_tier"]

    return record


def _dry_run_decision_for(
    pre_u_result: ValidationResult,
    delta_result: DeltaValidationResult,
) -> DryRunDecision:
    if pre_u_result.decision == ValidationDecision.ESCALATE:
        return DryRunDecision.ESCALATE
    if delta_result.decision == DeltaValidationDecision.DENY:
        return DryRunDecision.DENY
    if delta_result.decision == DeltaValidationDecision.REQUIRE_REVISION:
        return DryRunDecision.REQUIRE_REVISION
    if delta_result.decision == DeltaValidationDecision.ESCALATE:
        return DryRunDecision.ESCALATE
    if (
        pre_u_result.decision == ValidationDecision.WARN
        or delta_result.decision == DeltaValidationDecision.WARN
    ):
        return DryRunDecision.WARN
    return DryRunDecision.PASS


def _get(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def _selected_candidate_id(selected_action: Any) -> str:
    if isinstance(selected_action, Mapping):
        value = (
            selected_action.get("selected_candidate_id")
            or selected_action.get("candidate_id")
            or selected_action.get("id")
            or selected_action.get("name")
        )
        return str(value) if value is not None else "dry-run-selected-u"
    return str(selected_action)


def _selected_candidate(packet: Mapping[str, Any], selected_id: str) -> Optional[Mapping[str, Any]]:
    candidates = _get(packet, "candidate_actions", "candidate_U", "candidate_u", "candidates", default=[])
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = candidate.get("candidate_id") or candidate.get("id") or candidate.get("name")
        if str(candidate_id) == selected_id:
            return candidate
    return None
