"""
ystar.governance.obligation_triggers — Automatic Consequent Obligation Creation
================================================================================

ObligationTrigger framework bridges the gap between tool-call-layer governance
and obligation-layer governance.

When certain tool calls occur and are ALLOWED, automatically create follow-up
obligations that OmissionEngine tracks and enforces.

Core Components:
  - ObligationTrigger: dataclass defining when/what obligations are created
  - TriggerRegistry:   stores triggers, matches against tool calls
  - match_trigger():   matches tool calls → returns triggered obligations

Design principles:
  - Backward compatible: no triggers registered = no change in behavior
  - Deduplicates same-type pending obligations
  - Supports pattern matching on tool names and parameters
  - Severity escalation from SOFT → HARD
  - Integrates with OmissionEngine for tracking and enforcement

Usage:
    from ystar.governance.obligation_triggers import (
        ObligationTrigger, TriggerRegistry, match_triggers
    )

    # Create registry
    registry = TriggerRegistry()

    # Register trigger
    trigger = ObligationTrigger(
        trigger_id="research_knowledge_update",
        trigger_tool_pattern=r"web_search|WebSearch|WebFetch",
        obligation_type="knowledge_update_required",
        description="After web research, update knowledge/[role]/ with findings",
        target_agent="caller",
        deadline_seconds=1800,
        severity="SOFT",
    )
    registry.register(trigger)

    # Match tool calls
    triggers = match_triggers(registry, "WebSearch", {"query": "..."}, "CMO")
    for t in triggers:
        # Create obligation in OmissionEngine
        ...
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ystar.governance.omission_models import Severity


@dataclass
class ObligationTrigger:
    """
    Defines when a tool call creates a follow-up obligation.

    When an agent calls a tool matching trigger_tool_pattern,
    the system automatically creates an obligation that must be
    fulfilled within deadline_seconds.

    Attributes:
        trigger_id:           Unique identifier for this trigger
        trigger_tool_pattern: Regex pattern for tool_name (e.g., "web_search|WebSearch")
        obligation_type:      Obligation type identifier (e.g., "knowledge_update_required")
        description:          Human-readable description of the obligation
        target_agent:         "caller" | specific agent_id who must fulfill
        deadline_seconds:     How long they have to fulfill (seconds from trigger)
        severity:             "SOFT" | "HARD" - initial severity level
        verification_hint:    Hint for how to verify fulfillment (optional)
        enabled:              Whether this trigger is active
        deduplicate:          Don't create if same obligation already pending
    """
    trigger_id:           str
    trigger_tool_pattern: str
    obligation_type:      str
    description:          str
    target_agent:         str               # "caller" or specific agent_id
    deadline_seconds:     int
    severity:             str = "SOFT"      # SOFT | HARD
    verification_hint:    Optional[str] = None
    enabled:              bool = True
    deduplicate:          bool = True

    # Additional fields for advanced matching
    trigger_param_filter: Optional[Dict[str, Any]] = None  # optional param conditions

    # Escalation policy
    grace_period_secs:    float = 0.0       # soft grace before violation
    hard_overdue_secs:    float = 0.0       # when to block all unrelated actions
    escalate_to_hard:     bool = True       # auto-escalate after deadline
    escalate_to_actor:    Optional[str] = None  # who gets notified on escalation

    # Fulfillment specification
    fulfillment_event:    str = "file_write"  # what event type fulfills this
    verification_method:  str = "file_modified"  # "file_modified" | "event_received" | "custom"
    verification_target:  Optional[str] = None  # e.g., "knowledge/{role}/" for file_modified

    # Control
    deny_closure_on_open: bool = False  # block session close if unfulfilled

    def matches_tool(self, tool_name: str) -> bool:
        """Check if this trigger matches the given tool name."""
        try:
            return bool(re.match(self.trigger_tool_pattern, tool_name, re.IGNORECASE))
        except re.error:
            return False

    def matches_params(self, tool_input: dict) -> bool:
        """
        Check if this trigger matches the given tool parameters.
        Returns True if no filter is specified, or if filter matches.
        """
        if not self.trigger_param_filter:
            return True

        for key, expected_value in self.trigger_param_filter.items():
            actual_value = tool_input.get(key)

            # Handle different match types
            if isinstance(expected_value, list):
                # Check if actual value contains any of the expected values
                if actual_value is None:
                    return False
                if not any(str(ev) in str(actual_value) for ev in expected_value):
                    return False
            elif isinstance(expected_value, str):
                # Simple string match
                if str(actual_value) != expected_value:
                    return False
            else:
                # Exact match
                if actual_value != expected_value:
                    return False

        return True

    def get_target_actor(self, agent_id: str) -> str:
        """Resolve target actor from 'caller' or specific agent_id."""
        if self.target_agent == "caller":
            return agent_id
        return self.target_agent

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "trigger_id": self.trigger_id,
            "trigger_tool_pattern": self.trigger_tool_pattern,
            "obligation_type": self.obligation_type,
            "description": self.description,
            "target_agent": self.target_agent,
            "deadline_seconds": self.deadline_seconds,
            "severity": self.severity,
            "verification_hint": self.verification_hint,
            "enabled": self.enabled,
            "deduplicate": self.deduplicate,
            "trigger_param_filter": self.trigger_param_filter,
            "grace_period_secs": self.grace_period_secs,
            "hard_overdue_secs": self.hard_overdue_secs,
            "escalate_to_hard": self.escalate_to_hard,
            "escalate_to_actor": self.escalate_to_actor,
            "fulfillment_event": self.fulfillment_event,
            "verification_method": self.verification_method,
            "verification_target": self.verification_target,
            "deny_closure_on_open": self.deny_closure_on_open,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ObligationTrigger":
        """Deserialize from dict."""
        return cls(**data)


class TriggerRegistry:
    """
    Global registry for ObligationTriggers.

    Stores triggers and provides matching against tool calls.
    Can be loaded from AGENTS.md or separate trigger config.
    """

    def __init__(self) -> None:
        self._triggers: Dict[str, ObligationTrigger] = {}

    def register(self, trigger: ObligationTrigger) -> None:
        """Register a new trigger."""
        self._triggers[trigger.trigger_id] = trigger

    def get(self, trigger_id: str) -> Optional[ObligationTrigger]:
        """Get trigger by ID."""
        return self._triggers.get(trigger_id)

    def all_enabled(self) -> List[ObligationTrigger]:
        """Return all enabled triggers."""
        return [t for t in self._triggers.values() if t.enabled]

    def triggers_for_tool(self, tool_name: str) -> List[ObligationTrigger]:
        """Return all enabled triggers that match the given tool name."""
        return [
            t for t in self.all_enabled()
            if t.matches_tool(tool_name)
        ]

    def clear(self) -> None:
        """Clear all registered triggers."""
        self._triggers.clear()

    def to_dict(self) -> dict:
        """Serialize registry to dict."""
        return {
            trigger_id: trigger.to_dict()
            for trigger_id, trigger in self._triggers.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TriggerRegistry":
        """Deserialize registry from dict."""
        registry = cls()
        for trigger_id, trigger_data in data.items():
            trigger = ObligationTrigger.from_dict(trigger_data)
            registry.register(trigger)
        return registry


# ── Global registry instance ────────────────────────────────────────────────

_global_registry: Optional[TriggerRegistry] = None


def get_trigger_registry() -> TriggerRegistry:
    """Get or create the global trigger registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = TriggerRegistry()
    return _global_registry


def reset_trigger_registry() -> TriggerRegistry:
    """Reset the global trigger registry (for testing)."""
    global _global_registry
    _global_registry = TriggerRegistry()
    return _global_registry


# ── Trigger matching ────────────────────────────────────────────────────────


def match_triggers(
    registry: TriggerRegistry,
    tool_name: str,
    tool_input: dict,
    agent_id: str,
    check_result: Optional[Any] = None,  # PolicyResult or EnforceDecision
) -> List[ObligationTrigger]:
    """
    Match tool call against registered ObligationTriggers.

    Returns all triggers that match this tool call.

    Args:
        registry:      TriggerRegistry to search
        tool_name:     Name of the tool being called
        tool_input:    Parameters passed to the tool
        agent_id:      ID of the agent making the call
        check_result:  Optional result from policy check (for DENY triggers)

    Returns:
        List of matching ObligationTrigger instances
    """
    matches = []

    for trigger in registry.all_enabled():
        # Check tool name pattern
        if not trigger.matches_tool(tool_name):
            continue

        # Check if this is a DENY-only trigger (special case)
        if trigger.trigger_param_filter and "cieu_decision" in trigger.trigger_param_filter:
            expected_decision = trigger.trigger_param_filter["cieu_decision"]
            # Only match if check_result indicates DENY
            if check_result is not None:
                # Handle PolicyResult or EnforceDecision
                if hasattr(check_result, "allowed"):
                    # PolicyResult
                    is_deny = not check_result.allowed
                else:
                    # EnforceDecision or string
                    is_deny = str(check_result) == "DENY"

                if expected_decision == "DENY" and not is_deny:
                    continue
                elif expected_decision == "DENY" and is_deny:
                    # Match DENY trigger, skip other param checks
                    matches.append(trigger)
                    continue
            else:
                # No check_result provided, can't match DENY trigger
                continue

        # Check other param filters if specified
        if not trigger.matches_params(tool_input):
            continue

        matches.append(trigger)

    return matches


def create_obligation_from_trigger(
    trigger: ObligationTrigger,
    agent_id: str,
    session_id: str,
    omission_adapter: Any,
    tool_name: str = "",
    tool_input: Optional[dict] = None,
) -> Optional[Any]:
    """
    Create an ObligationRecord from an ObligationTrigger.
    Inject into OmissionEngine for tracking.

    Args:
        trigger:           ObligationTrigger that fired
        agent_id:          Agent who triggered the obligation
        session_id:        Current session ID
        omission_adapter:  OmissionAdapter instance
        tool_name:         Name of the tool that triggered this (for logging)
        tool_input:        Tool input parameters (for logging)

    Returns:
        The created ObligationRecord, or None if creation failed
    """
    if omission_adapter is None:
        return None

    # Determine target actor
    target_actor = trigger.get_target_actor(agent_id)

    # Check for duplicate if deduplicate is enabled
    if trigger.deduplicate:
        if omission_adapter.engine.store.has_pending_obligation(
            entity_id=session_id,
            obligation_type=trigger.obligation_type,
            actor_id=target_actor,
        ):
            # Already have a pending obligation of this type, skip
            return None

    # Create governance event to trigger obligation
    from ystar.governance.omission_models import GovernanceEvent

    now = time.time()
    event_id = f"trigger:{trigger.trigger_id}:{uuid.uuid4().hex[:8]}"

    ev = GovernanceEvent(
        event_id    = event_id,
        event_type  = f"tool_trigger:{trigger.trigger_id}",
        entity_id   = session_id,
        actor_id    = target_actor,
        ts          = now,
        payload     = {
            "trigger_id":     trigger.trigger_id,
            "obligation_type": trigger.obligation_type,
            "deadline_secs":  trigger.deadline_seconds,
            "fulfillment":    trigger.fulfillment_event,
            "tool_name":      tool_name,
            "tool_input":     tool_input or {},
            "triggered_by":   agent_id,
        },
    )

    # Ingest event into OmissionEngine
    result = omission_adapter.engine.ingest_event(ev)

    # Return the first new obligation created, if any
    if result.new_obligations:
        return result.new_obligations[0]

    return None


# ── Built-in trigger definitions ────────────────────────────────────────────


def register_default_triggers(registry: TriggerRegistry) -> None:
    """
    Register the 4 priority triggers from Directive #015.

    These are the triggers approved by the Board for Y* Bridge Labs operations:
      #1: Research Knowledge Update
      #2: Session Token Recording
      #7: Failure Case Documentation
      #9: Content Accuracy Review
    """

    # Trigger #1: Research Knowledge Update
    registry.register(ObligationTrigger(
        trigger_id="research_knowledge_update",
        trigger_tool_pattern=r"(web_search|WebSearch|WebFetch)",
        obligation_type="knowledge_update_required",
        description="After web research, update knowledge/[agent_role]/ with findings",
        target_agent="caller",
        deadline_seconds=1800,  # 30 minutes
        severity="SOFT",
        grace_period_secs=180,  # 3 minute grace
        hard_overdue_secs=3600,  # 1 hour before blocking
        escalate_to_hard=True,
        escalate_to_actor="CEO",
        fulfillment_event="file_write",
        verification_method="file_modified",
        verification_target="knowledge/{agent_role}/",
        verification_hint="knowledge/[role]/ file modified after trigger time",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # Trigger #2: Session Token Recording
    registry.register(ObligationTrigger(
        trigger_id="session_token_recording",
        trigger_tool_pattern=r"(session_end|TaskComplete|task_closed)",
        obligation_type="token_recording_required",
        description="After session completion, CFO must run track_burn.py",
        target_agent="CFO",
        deadline_seconds=600,  # 10 minutes
        severity="HARD",
        grace_period_secs=60,  # 1 minute grace
        hard_overdue_secs=600,  # Immediate block after deadline
        escalate_to_hard=True,
        escalate_to_actor="CEO",
        fulfillment_event="bash_exec",
        verification_method="command_contains",
        verification_target="track_burn.py",
        verification_hint="finance/daily_burn.md modified after trigger time",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=True,  # Cannot close session without recording
    ))

    # Trigger #7: Failure Case Documentation
    registry.register(ObligationTrigger(
        trigger_id="failure_case_documentation",
        trigger_tool_pattern=r".*",  # Any tool
        trigger_param_filter={"cieu_decision": "DENY"},
        obligation_type="case_documentation_required",
        description="After CIEU deny, document in knowledge/cases/",
        target_agent="caller",
        deadline_seconds=3600,  # 1 hour
        severity="SOFT",
        grace_period_secs=600,  # 10 minute grace
        hard_overdue_secs=7200,  # 2 hours before blocking
        escalate_to_hard=True,
        escalate_to_actor="CEO",
        fulfillment_event="file_write",
        verification_method="file_modified",
        verification_target="knowledge/cases/",
        verification_hint="new file in knowledge/cases/",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # Trigger #9: Content Accuracy Review
    registry.register(ObligationTrigger(
        trigger_id="content_accuracy_review",
        trigger_tool_pattern=r"(Write|Edit)",
        trigger_param_filter=None,  # Will check file path in verification
        obligation_type="cto_review_required",
        description="CMO content must be reviewed by CTO before publish",
        target_agent="CTO",
        deadline_seconds=7200,  # 2 hours
        severity="SOFT",
        grace_period_secs=600,  # 10 minute grace
        hard_overdue_secs=14400,  # 4 hours before blocking
        escalate_to_hard=True,
        escalate_to_actor="CEO",
        fulfillment_event="review_complete",
        verification_method="file_modified",
        verification_target="content/",  # Check if writing to content/ or marketing/
        verification_hint="corresponding _code_review.md file exists",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))
