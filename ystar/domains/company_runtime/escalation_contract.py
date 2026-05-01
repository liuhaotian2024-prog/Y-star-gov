from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .permission_tiers import CompanyActionDecision


@dataclass(frozen=True)
class EscalationContract:
    escalation_id: str
    requested_action: str
    action_class: str
    reason: str
    risk_summary: str
    recommended_default: str = ""
    exact_proposed_content: str = ""
    approval_options: List[str] = field(default_factory=lambda: ["approve", "reject", "request_revision", "hold"])
    status: str = "pending_owner_review"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EscalationContract":
        return cls(
            escalation_id=str(data.get("escalation_id") or data.get("id") or "escalation_unset"),
            requested_action=str(data.get("requested_action") or data.get("action") or ""),
            action_class=str(data.get("action_class") or ""),
            reason=str(data.get("reason") or ""),
            risk_summary=str(data.get("risk_summary") or ""),
            recommended_default=str(data.get("recommended_default") or data.get("recommendation") or ""),
            exact_proposed_content=str(data.get("exact_proposed_content") or ""),
            approval_options=list(data.get("approval_options") or ["approve", "reject", "request_revision", "hold"]),
            status=str(data.get("status") or "pending_owner_review"),
        )

    def validate(self) -> Dict[str, Any]:
        missing = [
            field
            for field in ("requested_action", "action_class", "reason", "risk_summary", "recommended_default")
            if not getattr(self, field)
        ]
        return {"ok": not missing, "missing_fields": missing, "status": self.status}


def build_escalation_decision(action_dict: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "decision": CompanyActionDecision.NEEDS_OWNER_APPROVAL.value,
        "requested_action": action_dict.get("action") or action_dict.get("title") or "company_action",
        "action_class": action_dict.get("action_class") or action_dict.get("type") or "external_action",
        "reason": reason,
        "risk_summary": action_dict.get("risk_summary") or "Owner approval required before any external side effect.",
        "recommended_default": action_dict.get("recommended_default") or "hold until owner approves exact scope",
        "approval_options": ["approve", "reject", "request_revision", "hold"],
        "executes_action": False,
    }
