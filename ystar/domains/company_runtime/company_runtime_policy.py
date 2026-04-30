from __future__ import annotations

from typing import Any, Dict

from .company_action_classifier import classify_company_action
from .delegated_mission_contract import DelegatedMissionContract
from .escalation_contract import build_escalation_decision
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
