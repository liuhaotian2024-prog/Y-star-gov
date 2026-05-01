from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class CompanyActionDecision(str, Enum):
    ALLOW_INTERNAL = "ALLOW_INTERNAL"
    NEEDS_OWNER_APPROVAL = "NEEDS_OWNER_APPROVAL"
    BLOCKED = "BLOCKED"
    REVIEW_GATED = "REVIEW_GATED"
    SIMPLIFY_OR_ARCHIVE = "SIMPLIFY_OR_ARCHIVE"
    OWNER_DECISION_REQUIRED = "OWNER_DECISION_REQUIRED"


class ActionClass(str, Enum):
    INTERNAL_WORK = "internal_autonomous_work"
    READ_ONLY_RESEARCH = "read_only_external_research"
    PREPARATION_ONLY = "preparation_only_owner_approved_execution"
    CONSTRAINED_EXTERNAL = "pre_approved_constrained_external_action"
    HIGH_RISK = "high_risk_review_gated"
    ADMINISTRATIVE_ACTION = "administrative_action"
    REPORTING_OBLIGATION = "reporting_obligation"
    STALE_LEGACY_DIRECTIVE = "stale_legacy_directive"
    OWNER_DECISION_REQUIRED = "owner_decision_required"
    MISSION_BOUND_OBLIGATION = "mission_bound_obligation"


@dataclass(frozen=True)
class PermissionTier:
    tier_id: int
    tier_name: str
    allowed_action_classes: List[ActionClass] = field(default_factory=list)
    requires_budget: bool = False
    requires_owner_approval: bool = False
    forbidden_action_classes: List[str] = field(default_factory=list)
    escalation_required_for: List[str] = field(default_factory=list)
    explanation: str = ""


TIER_REGISTRY = {
    0: PermissionTier(
        0,
        "Tier 0 — internal autonomous work",
        [ActionClass.INTERNAL_WORK, ActionClass.PREPARATION_ONLY],
        explanation="Local analysis, planning, drafts, packet creation, and review-gated candidates.",
    ),
    1: PermissionTier(
        1,
        "Tier 1 — read-only external research with budget",
        [ActionClass.INTERNAL_WORK, ActionClass.READ_ONLY_RESEARCH, ActionClass.PREPARATION_ONLY],
        requires_budget=True,
        escalation_required_for=["contact", "submit", "payment", "publication", "account_creation"],
        explanation="Budgeted public read-only search/page read. No login/contact/submit/payment/publication.",
    ),
    2: PermissionTier(
        2,
        "Tier 2 — preparation only, owner-approved execution",
        [ActionClass.INTERNAL_WORK, ActionClass.READ_ONLY_RESEARCH, ActionClass.PREPARATION_ONLY],
        requires_owner_approval=True,
        escalation_required_for=["external_execution"],
        explanation="Prepare drafts and packages; owner must approve execution.",
    ),
    3: PermissionTier(
        3,
        "Tier 3 — pre-approved constrained external action",
        [ActionClass.INTERNAL_WORK, ActionClass.READ_ONLY_RESEARCH, ActionClass.PREPARATION_ONLY, ActionClass.CONSTRAINED_EXTERNAL],
        requires_owner_approval=True,
        escalation_required_for=["exact_recipient", "exact_content", "explicit_scope"],
        explanation="Future slot for pre-approved constrained external actions.",
    ),
    4: PermissionTier(
        4,
        "Tier 4 — high-risk action, blocked/review-gated",
        [],
        requires_owner_approval=True,
        forbidden_action_classes=["payment", "legal", "core_writeback", "secret_read", "db_log_read", "repo_modification"],
        explanation="High-risk actions remain blocked or review-gated.",
    ),
}


def get_permission_tier(tier_id: int) -> PermissionTier:
    if tier_id not in TIER_REGISTRY:
        raise ValueError(f"unknown permission tier: {tier_id}")
    return TIER_REGISTRY[tier_id]
