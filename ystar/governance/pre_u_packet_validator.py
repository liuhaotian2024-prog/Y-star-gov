"""Deterministic Pre-U Counterfactual Packet validator skeleton.

This module validates packet structure only. It does not generate packets,
execute actions, call hooks, write CIEU events, read DBs, or perform semantic
Y* / m_functor proof.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class ValidationSeverity(str, Enum):
    """Severity for deterministic Pre-U validation issues."""

    WARNING = "warning"
    REQUIRE_REVISION = "require_revision"
    ESCALATE = "escalate"
    DENY = "deny"


class ValidationDecision(str, Enum):
    """Hook-facing decision hint aligned with the interface spec."""

    ALLOW = "allow"
    WARN = "warn"
    REQUIRE_REVISION = "require_revision"
    ESCALATE = "escalate"
    DENY = "deny"


@dataclass(frozen=True)
class ValidationIssue:
    """One deterministic issue found in a Pre-U packet."""

    code: str
    message: str
    severity: ValidationSeverity
    field: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "field": self.field,
        }


@dataclass(frozen=True)
class ValidationResult:
    """Result returned by the Pre-U packet validator skeleton."""

    decision: ValidationDecision
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    checked_fields: list[str] = field(default_factory=list)
    failure_action: Optional[str] = None
    normalized_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def validation_status(self) -> str:
        if self.decision == ValidationDecision.ALLOW:
            return "valid"
        if self.decision == ValidationDecision.WARN:
            return "warning_only"
        if self.decision == ValidationDecision.ESCALATE:
            return "requires_escalation"
        if self.decision == ValidationDecision.REQUIRE_REVISION:
            return "requires_revision"
        return "invalid"

    @property
    def failure_codes(self) -> list[str]:
        return [issue.code for issue in self.issues]

    @property
    def required_revisions(self) -> list[str]:
        return [
            issue.message
            for issue in self.issues
            if issue.severity == ValidationSeverity.REQUIRE_REVISION
        ]

    @property
    def hook_decision_hint(self) -> str:
        return self.decision.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "validation_status": self.validation_status,
            "decision": self.decision.value,
            "passed": self.passed,
            "failure_codes": self.failure_codes,
            "issues": [issue.to_dict() for issue in self.issues],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "required_revisions": self.required_revisions,
            "failure_action": self.failure_action,
            "hook_decision_hint": self.hook_decision_hint,
            "checked_fields": list(self.checked_fields),
            "normalized_summary": dict(self.normalized_summary),
        }


_MISSING = object()

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "packet_id": ("packet_id",),
    "agent_id": ("agent_id",),
    "agent_capsule_ref": ("agent_capsule_ref",),
    "task_id": ("task_id",),
    "y_star": ("y_star", "Y*", "y*", "Y_star"),
    "m_functor": ("m_functor", "M_functor", "mFunctor"),
    "x_t_summary": ("x_t_summary", "Xt", "x_t", "xt_summary"),
    "candidate_actions": ("candidate_actions", "candidate_U", "candidate_u", "candidates"),
    "selected_action": ("selected_action", "selected_U", "selected_u"),
    "residual_minimization_rationale": (
        "residual_minimization_rationale",
        "why_min_residual",
        "why_selected_min_residual",
    ),
    "governance_expectations": ("governance_expectations",),
    "cieu_link_policy": ("cieu_link_policy", "CIEU_link_policy"),
    "packet_status": ("packet_status",),
    "risk_tier": ("risk_tier", "riskTier"),
}

VALID_PACKET_STATUSES = {
    "draft",
    "ready_for_validation",
    "validation_failed",
    "approved_for_action",
    "superseded",
}


def validate_pre_u_packet(packet: Mapping[str, Any]) -> ValidationResult:
    """Validate a labs-generated Pre-U packet using deterministic checks only."""

    issues: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    checked_fields: list[str] = []

    if not isinstance(packet, Mapping):
        issue = ValidationIssue(
            code="PREU-SCHEMA",
            message="Packet must be a mapping/object.",
            severity=ValidationSeverity.DENY,
            field=None,
        )
        return _build_result([issue], [], ["packet"], {})

    normalized = {field: _get(packet, aliases) for field, aliases in FIELD_ALIASES.items()}

    _require_non_empty(issues, normalized, "packet_id", "PREU-SCHEMA", ValidationSeverity.DENY)
    _require_non_empty(issues, normalized, "agent_id", "PREU-AGENT-ID", ValidationSeverity.DENY)
    _require_non_empty(
        issues,
        normalized,
        "agent_capsule_ref",
        "PREU-SCHEMA",
        ValidationSeverity.REQUIRE_REVISION,
    )
    _require_non_empty(issues, normalized, "task_id", "PREU-TASK-ID", ValidationSeverity.REQUIRE_REVISION)
    _require_non_empty(issues, normalized, "y_star", "PREU-Y-STAR", ValidationSeverity.REQUIRE_REVISION)
    _require_non_empty(issues, normalized, "m_functor", "PREU-M-FUNCTOR", ValidationSeverity.REQUIRE_REVISION)
    if not _is_non_empty(normalized["x_t_summary"]):
        warnings.append(
            ValidationIssue(
                code="PREU-XT",
                message="x_t_summary / Xt is missing or empty.",
                severity=ValidationSeverity.WARNING,
                field="x_t_summary",
            )
        )
    _require_non_empty(
        issues,
        normalized,
        "residual_minimization_rationale",
        "PREU-RESIDUAL-RATIONALE",
        ValidationSeverity.REQUIRE_REVISION,
    )
    _require_non_empty(
        issues,
        normalized,
        "governance_expectations",
        "PREU-RISK-TIER",
        ValidationSeverity.REQUIRE_REVISION,
    )
    _require_non_empty(
        issues,
        normalized,
        "cieu_link_policy",
        "PREU-CIEU-LINK",
        ValidationSeverity.REQUIRE_REVISION,
    )

    packet_status = normalized["packet_status"]
    if packet_status is not _MISSING and packet_status not in VALID_PACKET_STATUSES:
        issues.append(
            ValidationIssue(
                code="PREU-SCHEMA",
                message=f"packet_status is not valid: {packet_status!r}.",
                severity=ValidationSeverity.REQUIRE_REVISION,
                field="packet_status",
            )
        )

    candidates = normalized["candidate_actions"]
    if not isinstance(candidates, list) or not candidates:
        issues.append(
            ValidationIssue(
                code="PREU-CANDIDATES",
                message="candidate_actions / candidate_U must be a non-empty list.",
                severity=ValidationSeverity.DENY,
                field="candidate_actions",
            )
        )
        candidates = []

    candidate_ids = _candidate_ids(candidates, issues)
    _check_predicted_residuals(candidates, issues)
    _check_selected_action(normalized["selected_action"], candidate_ids, issues)

    if _is_high_risk(normalized["risk_tier"], normalized["governance_expectations"]):
        issues.append(
            ValidationIssue(
                code="PREU-RISK-TIER",
                message="High-risk packet requires escalation before hook allow.",
                severity=ValidationSeverity.ESCALATE,
                field="risk_tier",
            )
        )

    checked_fields.extend(
        [
            "packet_id",
            "agent_id",
            "agent_capsule_ref",
            "task_id",
            "y_star",
            "m_functor",
            "x_t_summary",
            "candidate_actions",
            "selected_action",
            "predicted_r_t1",
            "residual_minimization_rationale",
            "governance_expectations",
            "cieu_link_policy",
            "packet_status",
            "risk_tier",
        ]
    )

    summary = {
        "packet_id": None if normalized["packet_id"] is _MISSING else normalized["packet_id"],
        "agent_id": None if normalized["agent_id"] is _MISSING else normalized["agent_id"],
        "candidate_count": len(candidates),
        "risk_tier": None if normalized["risk_tier"] is _MISSING else normalized["risk_tier"],
    }
    return _build_result(issues, warnings, checked_fields, summary)


def _build_result(
    issues: list[ValidationIssue],
    warnings: list[ValidationIssue],
    checked_fields: list[str],
    normalized_summary: dict[str, Any],
) -> ValidationResult:
    decision = _decision_for(issues, warnings)
    return ValidationResult(
        decision=decision,
        passed=decision == ValidationDecision.ALLOW,
        issues=issues,
        warnings=warnings,
        checked_fields=checked_fields,
        failure_action=None if decision == ValidationDecision.ALLOW else decision.value,
        normalized_summary=normalized_summary,
    )


def _decision_for(issues: list[ValidationIssue], warnings: list[ValidationIssue]) -> ValidationDecision:
    severities = {issue.severity for issue in issues}
    if ValidationSeverity.DENY in severities:
        return ValidationDecision.DENY
    if ValidationSeverity.REQUIRE_REVISION in severities:
        return ValidationDecision.REQUIRE_REVISION
    if ValidationSeverity.ESCALATE in severities:
        return ValidationDecision.ESCALATE
    if warnings:
        return ValidationDecision.WARN
    return ValidationDecision.ALLOW


def _get(packet: Mapping[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        if alias in packet:
            return packet[alias]
    return _MISSING


def _is_non_empty(value: Any) -> bool:
    if value is _MISSING or value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _require_non_empty(
    issues: list[ValidationIssue],
    normalized: Mapping[str, Any],
    field_name: str,
    code: str,
    severity: ValidationSeverity,
) -> None:
    if not _is_non_empty(normalized[field_name]):
        issues.append(
            ValidationIssue(
                code=code,
                message=f"{field_name} is missing or empty.",
                severity=severity,
                field=field_name,
            )
        )


def _candidate_ids(candidates: list[Any], issues: list[ValidationIssue]) -> set[str]:
    ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            issues.append(
                ValidationIssue(
                    code="PREU-CANDIDATES",
                    message=f"candidate_actions[{index}] must be an object.",
                    severity=ValidationSeverity.DENY,
                    field=f"candidate_actions[{index}]",
                )
            )
            continue
        candidate_id = candidate.get("candidate_id") or candidate.get("id") or candidate.get("name")
        if not _is_non_empty(candidate_id):
            issues.append(
                ValidationIssue(
                    code="PREU-CANDIDATES",
                    message=f"candidate_actions[{index}] is missing candidate_id.",
                    severity=ValidationSeverity.DENY,
                    field=f"candidate_actions[{index}].candidate_id",
                )
            )
            continue
        ids.add(str(candidate_id))
    return ids


def _check_predicted_residuals(candidates: list[Any], issues: list[ValidationIssue]) -> None:
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            continue
        predicted = (
            candidate.get("predicted_r_t1")
            or candidate.get("predicted_Rt+1")
            or candidate.get("predicted_rt1")
        )
        if not _is_non_empty(predicted):
            issues.append(
                ValidationIssue(
                    code="PREU-PREDICTED-R",
                    message=f"candidate_actions[{index}] is missing predicted_r_t1.",
                    severity=ValidationSeverity.DENY,
                    field=f"candidate_actions[{index}].predicted_r_t1",
                )
            )


def _check_selected_action(
    selected_action: Any,
    candidate_ids: set[str],
    issues: list[ValidationIssue],
) -> None:
    if not _is_non_empty(selected_action):
        issues.append(
            ValidationIssue(
                code="PREU-SELECTED-U",
                message="selected_action / selected_U is missing or empty.",
                severity=ValidationSeverity.DENY,
                field="selected_action",
            )
        )
        return

    if isinstance(selected_action, Mapping):
        selected_id = (
            selected_action.get("selected_candidate_id")
            or selected_action.get("candidate_id")
            or selected_action.get("id")
            or selected_action.get("name")
        )
    else:
        selected_id = selected_action

    if not _is_non_empty(selected_id):
        issues.append(
            ValidationIssue(
                code="PREU-SELECTED-U",
                message="selected_action does not identify a candidate.",
                severity=ValidationSeverity.DENY,
                field="selected_action",
            )
        )
        return

    if str(selected_id) not in candidate_ids:
        issues.append(
            ValidationIssue(
                code="PREU-SELECTED-U",
                message=f"selected_action references unknown candidate: {selected_id!r}.",
                severity=ValidationSeverity.DENY,
                field="selected_action",
            )
        )


def _is_high_risk(risk_tier: Any, governance_expectations: Any) -> bool:
    if isinstance(risk_tier, int):
        return risk_tier >= 3
    if isinstance(risk_tier, str):
        lowered = risk_tier.strip().lower()
        if lowered in {"tier3", "tier 3", "3", "tier4", "tier 4", "4", "high", "critical"}:
            return True
    if isinstance(governance_expectations, Mapping):
        return bool(
            governance_expectations.get("requires_high_risk_review")
            or governance_expectations.get("requires_escalation")
        )
    return False
