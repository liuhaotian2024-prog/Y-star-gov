"""CIEU prediction-delta record validator skeleton.

This module validates post-action prediction-vs-actual delta record structure
only. It does not write CIEU events, read DBs, inspect logs, judge semantic
truth, or perform brain writeback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


class DeltaValidationSeverity(str, Enum):
    """Severity for deterministic prediction-delta validation issues."""

    WARNING = "warning"
    REQUIRE_REVISION = "require_revision"
    ESCALATE = "escalate"
    DENY = "deny"


class DeltaValidationDecision(str, Enum):
    """Decision values for prediction-delta record readiness."""

    ALLOW = "allow"
    WARN = "warn"
    REQUIRE_REVISION = "require_revision"
    ESCALATE = "escalate"
    DENY = "deny"


@dataclass(frozen=True)
class DeltaValidationIssue:
    """One deterministic issue found in a prediction-delta record."""

    code: str
    message: str
    severity: DeltaValidationSeverity
    field: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "field": self.field,
        }


@dataclass(frozen=True)
class DeltaValidationResult:
    """Result returned by the CIEU prediction-delta validator."""

    decision: DeltaValidationDecision
    passed: bool
    issues: list[DeltaValidationIssue] = field(default_factory=list)
    warnings: list[DeltaValidationIssue] = field(default_factory=list)
    checked_fields: list[str] = field(default_factory=list)
    failure_action: Optional[str] = None
    normalized_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def validation_status(self) -> str:
        if self.decision == DeltaValidationDecision.ALLOW:
            return "valid"
        if self.decision == DeltaValidationDecision.WARN:
            return "warning_only"
        if self.decision == DeltaValidationDecision.ESCALATE:
            return "requires_escalation"
        if self.decision == DeltaValidationDecision.REQUIRE_REVISION:
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
            if issue.severity == DeltaValidationSeverity.REQUIRE_REVISION
        ]

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
            "checked_fields": list(self.checked_fields),
            "normalized_summary": dict(self.normalized_summary),
        }


_MISSING = object()

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "event_id": ("event_id", "delta_event_id"),
    "packet_id": ("packet_id",),
    "agent_or_role_id": ("agent_id", "role_id", "agent_or_role_id"),
    "recorded_at": ("recorded_at", "timestamp", "created_at"),
    "declared_y_star": ("declared_y_star", "y_star", "Y*"),
    "selected_u": ("selected_u", "selected_U", "selected_action"),
    "predicted_y_t1": ("predicted_y_t1", "predicted_Yt_plus_1", "predicted_Yt+1"),
    "predicted_r_t1": ("predicted_r_t1", "predicted_Rt_plus_1", "predicted_Rt+1"),
    "x_t": ("x_t", "Xt", "x_t_summary"),
    "u": ("u", "U", "actual_u"),
    "actual_y_t1": ("actual_y_t1", "actual_Yt_plus_1", "actual_Yt+1"),
    "actual_r_t1": ("actual_r_t1", "actual_Rt_plus_1", "actual_Rt+1"),
    "delta_summary": ("delta_summary",),
    "residual_delta": ("residual_delta",),
    "delta_class": ("delta_class", "deviation_class"),
    "learning_eligibility": ("learning_eligibility",),
    "cieu_ref": ("cieu_record_ref", "cieu_event_ref", "cieu_ref"),
    "governance_ref": ("governance_decision_ref", "validator_result_ref", "governance_ref"),
    "brain_writeback_policy": ("brain_writeback_policy",),
    "risk_level": ("risk_level", "risk_tier"),
}

CRITICAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("event_id", "CIEU-DELTA-EVENT-ID"),
    ("packet_id", "CIEU-DELTA-PACKET-ID"),
    ("agent_or_role_id", "CIEU-DELTA-ACTOR"),
    ("recorded_at", "CIEU-DELTA-TIMESTAMP"),
    ("declared_y_star", "CIEU-DELTA-Y-STAR"),
    ("selected_u", "CIEU-DELTA-SELECTED-U"),
    ("predicted_y_t1", "CIEU-DELTA-PREDICTED-Y"),
    ("predicted_r_t1", "CIEU-DELTA-PREDICTED-R"),
    ("x_t", "CIEU-DELTA-XT"),
    ("u", "CIEU-DELTA-U"),
    ("actual_y_t1", "CIEU-DELTA-ACTUAL-Y"),
    ("actual_r_t1", "CIEU-DELTA-ACTUAL-R"),
    ("delta_summary", "CIEU-DELTA-SUMMARY"),
    ("residual_delta", "CIEU-DELTA-RESIDUAL"),
    ("learning_eligibility", "CIEU-DELTA-LEARNING-ELIGIBILITY"),
    ("cieu_ref", "CIEU-DELTA-CIEU-REF"),
    ("brain_writeback_policy", "CIEU-DELTA-WRITEBACK-POLICY"),
)


def validate_prediction_delta(record: Mapping[str, Any]) -> DeltaValidationResult:
    """Validate a post-action prediction-delta record structurally."""

    issues: list[DeltaValidationIssue] = []
    warnings: list[DeltaValidationIssue] = []

    if not isinstance(record, Mapping):
        issue = DeltaValidationIssue(
            code="CIEU-DELTA-SCHEMA",
            message="Prediction-delta record must be a mapping/object.",
            severity=DeltaValidationSeverity.DENY,
        )
        return _build_result([issue], [], ["record"], {})

    normalized = {field: _get(record, aliases) for field, aliases in FIELD_ALIASES.items()}

    for field_name, code in CRITICAL_FIELDS:
        _require_non_empty(issues, normalized, field_name, code, DeltaValidationSeverity.REQUIRE_REVISION)

    if not _is_non_empty(normalized["delta_class"]):
        warnings.append(
            DeltaValidationIssue(
                code="CIEU-DELTA-CLASS",
                message="delta_class / deviation_class is missing.",
                severity=DeltaValidationSeverity.WARNING,
                field="delta_class",
            )
        )

    writeback_policy = normalized["brain_writeback_policy"]
    if _is_uncurated_direct_writeback(writeback_policy):
        issues.append(
            DeltaValidationIssue(
                code="CIEU-DELTA-WRITEBACK-POLICY",
                message="brain_writeback_policy must not allow automatic uncurated direct writeback.",
                severity=DeltaValidationSeverity.DENY,
                field="brain_writeback_policy",
            )
        )

    if _declares_raw_artifact_learning_source(record):
        issues.append(
            DeltaValidationIssue(
                code="CIEU-DELTA-RAW-ARTIFACT-SOURCE",
                message="Prediction-delta record must not use raw DB/log/runtime artifacts as direct learning source.",
                severity=DeltaValidationSeverity.DENY,
                field="learning_source",
            )
        )

    if _is_high_risk_unresolved(normalized["risk_level"], normalized["delta_class"], normalized["residual_delta"]):
        issues.append(
            DeltaValidationIssue(
                code="CIEU-DELTA-HIGH-RISK-UNRESOLVED",
                message="High-risk unresolved prediction delta requires escalation.",
                severity=DeltaValidationSeverity.ESCALATE,
                field="risk_level",
            )
        )

    checked_fields = list(FIELD_ALIASES.keys())
    summary = {
        "event_id": None if normalized["event_id"] is _MISSING else normalized["event_id"],
        "packet_id": None if normalized["packet_id"] is _MISSING else normalized["packet_id"],
        "agent_or_role_id": None if normalized["agent_or_role_id"] is _MISSING else normalized["agent_or_role_id"],
        "delta_class": None if normalized["delta_class"] is _MISSING else normalized["delta_class"],
    }
    return _build_result(issues, warnings, checked_fields, summary)


def _build_result(
    issues: list[DeltaValidationIssue],
    warnings: list[DeltaValidationIssue],
    checked_fields: list[str],
    normalized_summary: dict[str, Any],
) -> DeltaValidationResult:
    decision = _decision_for(issues, warnings)
    return DeltaValidationResult(
        decision=decision,
        passed=decision == DeltaValidationDecision.ALLOW,
        issues=issues,
        warnings=warnings,
        checked_fields=checked_fields,
        failure_action=None if decision == DeltaValidationDecision.ALLOW else decision.value,
        normalized_summary=normalized_summary,
    )


def _decision_for(
    issues: list[DeltaValidationIssue],
    warnings: list[DeltaValidationIssue],
) -> DeltaValidationDecision:
    severities = {issue.severity for issue in issues}
    if DeltaValidationSeverity.DENY in severities:
        return DeltaValidationDecision.DENY
    if DeltaValidationSeverity.REQUIRE_REVISION in severities:
        return DeltaValidationDecision.REQUIRE_REVISION
    if DeltaValidationSeverity.ESCALATE in severities:
        return DeltaValidationDecision.ESCALATE
    if warnings:
        return DeltaValidationDecision.WARN
    return DeltaValidationDecision.ALLOW


def _get(record: Mapping[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        if alias in record:
            return record[alias]
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
    issues: list[DeltaValidationIssue],
    normalized: Mapping[str, Any],
    field_name: str,
    code: str,
    severity: DeltaValidationSeverity,
) -> None:
    if not _is_non_empty(normalized[field_name]):
        issues.append(
            DeltaValidationIssue(
                code=code,
                message=f"{field_name} is missing or empty.",
                severity=severity,
                field=field_name,
            )
        )


def _is_uncurated_direct_writeback(policy: Any) -> bool:
    if isinstance(policy, Mapping):
        if policy.get("automatic_direct_writeback") is True:
            return True
        if policy.get("requires_curation") is False:
            return True
        mode = str(policy.get("mode", "")).lower()
        return "direct" in mode and "curat" not in mode
    if isinstance(policy, str):
        lowered = policy.lower()
        return (
            "automatic" in lowered
            and "direct" in lowered
            and "writeback" in lowered
            and "curat" not in lowered
        )
    return False


def _declares_raw_artifact_learning_source(record: Mapping[str, Any]) -> bool:
    for key in ("learning_source", "brain_writeback_policy", "evidence_source"):
        value = record.get(key)
        text = str(value).lower()
        if any(marker in text for marker in ("raw db", "raw log", "runtime artifact", ".db-wal", ".db-shm")):
            return True
    return False


def _is_high_risk_unresolved(risk_level: Any, delta_class: Any, residual_delta: Any) -> bool:
    risk_text = str(risk_level).strip().lower()
    delta_text = str(delta_class).strip().lower()
    residual_text = str(residual_delta).strip().lower()
    high_risk = risk_text in {"high", "critical", "tier3", "tier 3", "3", "tier4", "tier 4", "4"}
    unresolved = any(token in delta_text for token in ("unresolved", "worse", "regression")) or any(
        token in residual_text for token in ("unresolved", "worse", "increased", "regression")
    )
    return high_risk and unresolved
