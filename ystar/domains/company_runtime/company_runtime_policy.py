from __future__ import annotations

from typing import Any, Dict

from .admin_rationalization import classify_admin_rule, classify_stale_directive
from .company_action_classifier import classify_company_action
from .delegated_mission_contract import DelegatedMissionContract
from .escalation_contract import build_escalation_decision
from .mission_alignment import classify_m_triangle_alignment, value_production_relevance
from .permission_tiers import CompanyActionDecision, get_permission_tier


def _budget_missing(mission: DelegatedMissionContract, action_dict: Dict[str, Any]) -> bool:
    decision = classify_company_action(action_dict)
    text = " ".join(str(v) for v in action_dict.values()).lower()
    if "read-only research" not in text and "public page" not in text and "search" not in text:
        return False
    tier = get_permission_tier(mission.allowed_permission_tier)
    return tier.requires_budget and not mission.research_budget


def mission_permission_check(mission_dict: Dict[str, Any], action_dict: Dict[str, Any]) -> Dict[str, Any]:
    mission = DelegatedMissionContract.from_dict(mission_dict)
    tier = get_permission_tier(mission.allowed_permission_tier)
    classification = classify_company_action(action_dict)
    decision = classification["decision"]

    if any(cls.lower() in " ".join(str(v).lower() for v in action_dict.values()) for cls in mission.forbidden_action_classes):
        decision = CompanyActionDecision.BLOCKED.value
        classification["reason_codes"] = ["mission_forbidden_action_class"]
        classification["owner_visible_explanation"] = "Mission explicitly forbids this action class."

    missing_budget = _budget_missing(mission, action_dict)
    if missing_budget:
        decision = CompanyActionDecision.NEEDS_OWNER_APPROVAL.value

    escalation = None
    if decision in {CompanyActionDecision.NEEDS_OWNER_APPROVAL.value, CompanyActionDecision.REVIEW_GATED.value}:
        escalation = build_escalation_decision(action_dict, classification["owner_visible_explanation"])

    return {
        "decision": decision,
        "permission_tier": tier.tier_id,
        "tier_name": tier.tier_name,
        "missing_budget": missing_budget,
        "reason_codes": classification["reason_codes"],
        "owner_visible_explanation": classification["owner_visible_explanation"],
        "escalation": escalation,
        "executes_action": False,
    }


def mission_action_preflight(mission_dict: Dict[str, Any], action_dict: Dict[str, Any]) -> Dict[str, Any]:
    permission = mission_permission_check(mission_dict, action_dict)
    admin = None
    stale_directive = None
    action_text = " ".join(str(value).lower() for value in action_dict.values())

    if any(keyword in action_text for keyword in ["daily report", "weekly report", "nightly report", "content calendar", "hacker news", "linkedin", "admin", "cadence"]):
        admin = classify_admin_rule(action_dict)
    if any(keyword in action_text for keyword in ["directive", "tracker", "stale", "not started", "未追踪", "❌"]):
        stale_directive = classify_stale_directive(action_dict)

    alignment = classify_m_triangle_alignment(action_dict)
    value = value_production_relevance(action_dict)

    recommended_priority = "normal"
    if value["relevance"] == "HIGH":
        recommended_priority = "raise_if_no_m1_m2_incident"
    elif admin and admin["decision"] in {"ARCHIVE_LEGACY", "SIMPLIFY_ACTIVE"} and value["relevance"] in {"LOW", "UNKNOWN"}:
        recommended_priority = "simplify_or_archive"

    return {
        "permission": permission,
        "admin_rule": admin,
        "stale_directive": stale_directive,
        "m_triangle_alignment": alignment,
        "value_production_relevance": value,
        "recommended_priority": recommended_priority,
        "executes_action": False,
    }
