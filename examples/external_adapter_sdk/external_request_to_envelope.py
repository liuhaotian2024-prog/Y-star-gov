"""Generic external request to Y-star-gov hook envelope normalizer."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


def normalize_external_request_to_hook_envelope(
    request: Mapping[str, Any],
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a generic external action request into a hook-like envelope."""

    if not isinstance(request, Mapping):
        raise TypeError("request must be a mapping")
    config = config or {}

    action_request_id = _required_str(request, "action_request_id")
    selected_action_id = _required_str(request, "selected_action_id")
    packet_prefix = str(config.get("default_packet_prefix", "external-adapter"))
    actions = request.get("proposed_actions")
    if not isinstance(actions, list) or not actions:
        raise ValueError("proposed_actions must be a non-empty list")

    return {
        "hook_event_id": _required_str(request, "external_event_id"),
        "agent_id": _required_str(request, "agent_id"),
        "packet_id": f"{packet_prefix}-{action_request_id}",
        "agent_capsule_ref": config.get("default_agent_capsule_ref", "external-adapter://generic-agent"),
        "task_id": action_request_id,
        "risk_tier": request.get("risk_tier", "normal"),
        "declared_Y_star": deepcopy(request.get("declared_objective")),
        "Xt": deepcopy(request.get("context")),
        "m_functor": deepcopy(config.get("m_functor_template", {"summary": "External request governance grounding"})),
        "candidate_U": [
            _normalize_action(action, request)
            for action in actions
        ],
        "selected_U_id": selected_action_id,
        "why_min_residual": request.get(
            "why_min_residual",
            "Selected action is the adapter-provided path with lowest declared residual.",
        ),
        "governance_expectations": deepcopy(request.get("governance_expectations")),
        "cieu_link_policy": deepcopy(request.get("cieu_link_policy")),
        "packet_status": config.get("packet_status", "ready_for_validation"),
    }


def _normalize_action(action: Any, request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(action, Mapping):
        raise TypeError("each proposed action must be a mapping")
    return {
        "id": action.get("id"),
        "action_type": action.get("action_type"),
        "description": action.get("description"),
        "predicted_Yt_plus_1": action.get("predicted_outcome") or request.get("predicted_outcome"),
        "predicted_Rt_plus_1": action.get("predicted_residual") or request.get("predicted_residual"),
    }


def _required_str(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{key} is required")
    return str(value)
