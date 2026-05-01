from __future__ import annotations

from typing import Any, Dict

from .permission_tiers import ActionClass, CompanyActionDecision


APPROVAL_KEYWORDS = {
    "customer contact",
    "contact customer",
    "email",
    "message sending",
    "send message",
    "outreach",
    "publication",
    "publish",
    "social post",
    "form submission",
    "submit form",
    "account creation",
    "create account",
    "live mcp",
    "mcp/live",
}

BLOCK_KEYWORDS = {
    "payment",
    "pay",
    "wire transfer",
    "charge card",
    "secret",
    "env file",
    "db/wal/shm",
    "wal",
    "shm",
    "active-agent marker",
    "active agent marker",
    "bulk outreach",
    "lead scraping",
}

REVIEW_GATED_KEYWORDS = {
    "core writeback",
    "memory writeback",
    "brain writeback",
    "canonical writeback",
    "cieu db writeback",
    "modify y-star-gov",
    "modify gov-mcp",
    "modify ystar-bridge-labs",
}

INTERNAL_KEYWORDS = {
    "internal analysis",
    "draft",
    "plan",
    "summary",
    "local packet",
    "strategy brief",
    "read-only research",
    "public page read",
    "compare",
}

ADMIN_KEYWORDS = {
    "daily report",
    "weekly report",
    "nightly report",
    "日报",
    "周报",
    "夜间报告",
    "content calendar",
    "posting schedule",
    "cadence",
    "administrative",
    "reporting obligation",
}

STALE_LEGACY_KEYWORDS = {
    "stale",
    "legacy",
    "old directive",
    "old calendar",
    "historical",
    "archive legacy",
    "旧任务",
    "历史包袱",
}


def _action_text(action_dict: Dict[str, Any]) -> str:
    values = []
    for key, value in action_dict.items():
        if isinstance(value, (str, int, float, bool)):
            values.append(f"{key}={value}")
        elif isinstance(value, (list, tuple, set)):
            values.extend(str(v) for v in value)
    return " ".join(values).lower()


def classify_company_action(action_dict: Dict[str, Any]) -> Dict[str, Any]:
    text = _action_text(action_dict)
    if any(k in text for k in BLOCK_KEYWORDS):
        return {
            "decision": CompanyActionDecision.BLOCKED.value,
            "reason_codes": ["blocked_high_risk_or_sensitive_access"],
            "owner_visible_explanation": "This action is blocked because it involves payment, secrets, private runtime artifacts, scraping, or similarly high-risk behavior.",
        }
    if any(k in text for k in REVIEW_GATED_KEYWORDS):
        return {
            "decision": CompanyActionDecision.REVIEW_GATED.value,
            "reason_codes": ["review_gated_core_or_repo_write"],
            "owner_visible_explanation": "This action requires review because it touches core writeback or protected repositories.",
        }
    if any(k in text for k in APPROVAL_KEYWORDS):
        return {
            "decision": CompanyActionDecision.NEEDS_OWNER_APPROVAL.value,
            "reason_codes": ["external_side_effect_requires_owner_approval"],
            "owner_visible_explanation": "External contact, publication, form submission, account creation, or live MCP behavior needs owner approval first.",
        }
    if any(k in text for k in INTERNAL_KEYWORDS) or not text.strip():
        return {
            "decision": CompanyActionDecision.ALLOW_INTERNAL.value,
            "reason_codes": ["safe_internal_or_read_only_preparation"],
            "owner_visible_explanation": "Local internal work or read-only preparation is allowed within mission bounds.",
        }
    return {
        "decision": CompanyActionDecision.NEEDS_OWNER_APPROVAL.value,
        "reason_codes": ["unclear_action_needs_owner_review"],
        "owner_visible_explanation": "The action is not clearly internal, so it should be escalated before execution.",
    }


def requires_owner_approval(action_dict: Dict[str, Any]) -> bool:
    return classify_company_action(action_dict)["decision"] in {
        CompanyActionDecision.NEEDS_OWNER_APPROVAL.value,
        CompanyActionDecision.REVIEW_GATED.value,
    }


def is_mission_bound_obligation(rule_dict: Dict[str, Any]) -> bool:
    return bool(
        rule_dict.get("mission_id")
        or rule_dict.get("current_mission")
        or rule_dict.get("owner_approved_cadence")
        or rule_dict.get("explicit_obligation_id")
    )


def classify_admin_rule(rule_dict: Dict[str, Any]) -> Dict[str, Any]:
    text = _action_text(rule_dict)
    mission_bound = is_mission_bound_obligation(rule_dict)
    m_alignment = str(rule_dict.get("m_triangle_alignment") or "").lower()
    has_m_alignment = any(tag in m_alignment or tag in text for tag in ("m-1", "m-2", "m-3", "survivability", "governability", "value production"))

    if any(k in text for k in STALE_LEGACY_KEYWORDS):
        return {
            "decision": CompanyActionDecision.SIMPLIFY_OR_ARCHIVE.value,
            "action_class": ActionClass.STALE_LEGACY_DIRECTIVE.value,
            "mission_bound": mission_bound,
            "reason_codes": ["stale_legacy_directive"],
            "owner_visible_explanation": "This appears to be a stale legacy directive. Archive or re-triage before treating it as active.",
        }

    if any(k in text for k in ADMIN_KEYWORDS):
        if mission_bound and has_m_alignment:
            return {
                "decision": CompanyActionDecision.ALLOW_INTERNAL.value,
                "action_class": ActionClass.MISSION_BOUND_OBLIGATION.value,
                "mission_bound": True,
                "reason_codes": ["mission_bound_admin_obligation"],
                "owner_visible_explanation": "This reporting/admin obligation is mission-bound and aligned with the M Triangle.",
            }
        return {
            "decision": CompanyActionDecision.SIMPLIFY_OR_ARCHIVE.value,
            "action_class": ActionClass.REPORTING_OBLIGATION.value,
            "mission_bound": mission_bound,
            "reason_codes": ["admin_ceremony_without_current_mission"],
            "owner_visible_explanation": "Administrative/reporting ceremony is not active by default unless mission-bound and M-aligned.",
        }

    if rule_dict.get("owner_decision_needed") is True:
        return {
            "decision": CompanyActionDecision.OWNER_DECISION_REQUIRED.value,
            "action_class": ActionClass.OWNER_DECISION_REQUIRED.value,
            "mission_bound": mission_bound,
            "reason_codes": ["owner_decision_required"],
            "owner_visible_explanation": "This ambiguous rule should be reviewed by the owner before activation or deletion.",
        }

    return {
        "decision": CompanyActionDecision.ALLOW_INTERNAL.value,
        "action_class": ActionClass.ADMINISTRATIVE_ACTION.value,
        "mission_bound": mission_bound,
        "reason_codes": ["admin_rule_not_burdensome"],
        "owner_visible_explanation": "No stale or burdensome administrative pattern was detected.",
    }


def should_archive_admin_rule(rule_dict: Dict[str, Any]) -> bool:
    return classify_admin_rule(rule_dict)["decision"] == CompanyActionDecision.SIMPLIFY_OR_ARCHIVE.value
