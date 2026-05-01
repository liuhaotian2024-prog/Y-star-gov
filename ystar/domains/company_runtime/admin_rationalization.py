from __future__ import annotations

from enum import Enum
from typing import Any, Dict


class AdminRuleDecision(str, Enum):
    KEEP_CORE = "KEEP_CORE"
    SIMPLIFY_ACTIVE = "SIMPLIFY_ACTIVE"
    REPLACE_WITH_PERMISSION_TIER = "REPLACE_WITH_PERMISSION_TIER"
    ARCHIVE_LEGACY = "ARCHIVE_LEGACY"
    OWNER_DECISION_REQUIRED = "OWNER_DECISION_REQUIRED"
    DELETE_DUPLICATE_OR_HARMFUL = "DELETE_DUPLICATE_OR_HARMFUL"


class DirectiveDecision(str, Enum):
    ACTIVE_NOW = "ACTIVE_NOW"
    REVENUE_RELEVANT_NOW = "REVENUE_RELEVANT_NOW"
    SUPERSEDED_BY_RUNTIME = "SUPERSEDED_BY_RUNTIME"
    ARCHIVE_LEGACY = "ARCHIVE_LEGACY"
    OWNER_DECISION_REQUIRED = "OWNER_DECISION_REQUIRED"
    BLOCKED_BY_MISSING_EVIDENCE = "BLOCKED_BY_MISSING_EVIDENCE"
    ADMIN_BURDEN = "ADMIN_BURDEN"


def _text(data: Dict[str, Any]) -> str:
    parts = []
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)):
            parts.append(f"{key}={value}")
        elif isinstance(value, (list, tuple, set)):
            parts.extend(str(v) for v in value)
    return " ".join(parts).lower()


def _active(data: Dict[str, Any]) -> bool:
    return bool(data.get("reactivated") or data.get("owner_approved") or data.get("mission_bound"))


def is_mission_bound_obligation(rule_dict: Dict[str, Any], mission_dict: Dict[str, Any] | None = None) -> bool:
    if rule_dict.get("mission_bound") is True or rule_dict.get("active_mission_id"):
        return True
    if not mission_dict:
        return False
    mission_id = str(mission_dict.get("mission_id") or mission_dict.get("id") or "")
    return bool(mission_id and mission_id in _text(rule_dict))


def classify_admin_rule(rule_dict: Dict[str, Any]) -> Dict[str, Any]:
    text = _text(rule_dict)
    mission_bound = is_mission_bound_obligation(rule_dict, rule_dict.get("mission") if isinstance(rule_dict.get("mission"), dict) else None)

    if any(k in text for k in ["m triangle", "m-1", "m-2", "m-3", "deterministic", "cieu", "no secrets", "secret/env", "external side effects require approval", "core writeback review"]):
        decision = AdminRuleDecision.KEEP_CORE
        reason = "Core M Triangle / deterministic / CIEU / safety boundary rule remains active."
    elif any(k in text for k in ["duplicate", "harmful", "conflicting iron rule", "contradictory"]):
        decision = AdminRuleDecision.DELETE_DUPLICATE_OR_HARMFUL
        reason = "Duplicate or harmful administrative text should be removed or replaced with the active charter."
    elif any(k in text for k in ["customer contact", "send email", "email", "publication", "social post", "form submission", "create account", "outreach", "message sending"]):
        decision = AdminRuleDecision.REPLACE_WITH_PERMISSION_TIER
        reason = "External-facing actions should be governed by permission tiers and explicit escalation."
    elif any(k in text for k in ["payment", "legal", "contract", "core writeback", "brain writeback", "secret", "private db", "wal", "shm"]):
        decision = AdminRuleDecision.KEEP_CORE
        reason = "High-risk payment/legal/core-writeback/private-runtime boundaries remain blocked or review-gated."
    elif any(k in text for k in ["hacker news", "linkedin", "content calendar", "social calendar", "hn cadence", "article cadence"]):
        decision = AdminRuleDecision.SIMPLIFY_ACTIVE if _active(rule_dict) else AdminRuleDecision.ARCHIVE_LEGACY
        reason = "Old content cadence is not active by default unless owner reactivates it for a current mission."
    elif any(k in text for k in ["enterprise sales", "warm intro", "enterprise phase", "sales phase"]):
        decision = AdminRuleDecision.OWNER_DECISION_REQUIRED if not _active(rule_dict) else AdminRuleDecision.SIMPLIFY_ACTIVE
        reason = "Enterprise sales may matter, but stale sales phases need owner re-triage and current evidence."
    elif any(k in text for k in ["daily report", "daily autonomous report", "nightly report", "weekly report", "report every night", "must report every night", "daily schedule", "weekly cycle", "reporting obligation"]):
        decision = AdminRuleDecision.SIMPLIFY_ACTIVE if mission_bound else AdminRuleDecision.ARCHIVE_LEGACY
        reason = "Recurring reports should be active only when mission-bound or explicitly approved."
    elif any(k in text for k in ["admin", "ceremony", "ritual", "cadence"]):
        decision = AdminRuleDecision.SIMPLIFY_ACTIVE if mission_bound else AdminRuleDecision.ARCHIVE_LEGACY
        reason = "Administrative ceremony without mission binding should be simplified or archived."
    else:
        decision = AdminRuleDecision.OWNER_DECISION_REQUIRED
        reason = "Rule is not clearly current; owner or active charter should decide."

    return {
        "decision": decision.value,
        "mission_bound": mission_bound,
        "reason": reason,
        "executes_action": False,
    }


def should_archive_admin_rule(rule_dict: Dict[str, Any]) -> bool:
    return classify_admin_rule(rule_dict)["decision"] == AdminRuleDecision.ARCHIVE_LEGACY.value


def classify_stale_directive(task_dict: Dict[str, Any]) -> Dict[str, Any]:
    text = _text(task_dict)
    if any(k in text for k in ["paid", "revenue", "first cash", "customer", "user interview", "pilot", "测试覆盖率", "test baseline", "external install"]):
        decision = DirectiveDecision.REVENUE_RELEVANT_NOW
        reason = "This task has a plausible link to M-3 value production or delivery credibility."
    elif any(k in text for k in ["hacker news", "linkedin", "content calendar", "article series", "podcast"]):
        decision = DirectiveDecision.ARCHIVE_LEGACY
        reason = "Old content calendar task is historical unless reactivated for a current money path."
    elif any(k in text for k in ["three repo", "three-repo", "backflow", "integration sprint", "superseded"]):
        decision = DirectiveDecision.SUPERSEDED_BY_RUNTIME
        reason = "The task has been superseded by newer runtime/backflow repair work."
    elif any(k in text for k in ["daily report", "weekly report", "nightly report", "admin", "cadence"]):
        decision = DirectiveDecision.ADMIN_BURDEN
        reason = "Administrative reporting should not remain active unless mission-bound."
    elif any(k in text for k in ["enterprise", "sales phase", "patent", "notebooklm", "lawyer", "pricing"]):
        decision = DirectiveDecision.OWNER_DECISION_REQUIRED
        reason = "Strategic or commercial work needs current owner authorization and evidence."
    elif any(k in text for k in ["missing evidence", "unknown", "unvalidated", "no evidence"]):
        decision = DirectiveDecision.BLOCKED_BY_MISSING_EVIDENCE
        reason = "The directive lacks evidence needed for activation."
    elif any(k in text for k in ["governance", "gov_order", "mcp", "permission tier", "escalation"]):
        decision = DirectiveDecision.ACTIVE_NOW
        reason = "This supports current governable company-runtime execution."
    else:
        decision = DirectiveDecision.OWNER_DECISION_REQUIRED
        reason = "The directive needs re-triage before being treated as active."

    return {
        "decision": decision.value,
        "reason": reason,
        "executes_action": False,
    }
