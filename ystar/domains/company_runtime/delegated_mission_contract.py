from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class DelegatedMissionContract:
    mission_id: str
    owner_goal: str
    allowed_permission_tier: int = 0
    research_budget: Dict[str, Any] = field(default_factory=dict)
    forbidden_action_classes: List[str] = field(default_factory=list)
    required_review_points: List[str] = field(default_factory=list)
    status: str = "active"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedMissionContract":
        return cls(
            mission_id=str(data.get("mission_id") or data.get("id") or "mission_unset"),
            owner_goal=str(data.get("owner_goal") or data.get("goal") or ""),
            allowed_permission_tier=int(data.get("allowed_permission_tier", data.get("permission_tier", 0))),
            research_budget=dict(data.get("research_budget") or {}),
            forbidden_action_classes=list(data.get("forbidden_action_classes") or []),
            required_review_points=list(data.get("required_review_points") or []),
            status=str(data.get("status") or "active"),
        )
