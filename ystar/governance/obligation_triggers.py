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
    triggers = match_triggers(registry, "WebSearch", {"query": "..."}, "marketing_agent")
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

from ystar.governance.omission_models import Severity, OmissionType


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
    required_event_types: List[str] = field(default_factory=list)  # Event types that fulfill this obligation

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
            "required_event_types": self.required_event_types,
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

    def register(self, trigger: ObligationTrigger, engine: Any = None) -> None:
        """
        Register a new trigger.

        Args:
            trigger: ObligationTrigger to register
            engine:  Optional OmissionEngine instance for live-reload
                     If provided, triggers immediate scan for this trigger type
        """
        self._triggers[trigger.trigger_id] = trigger

        # Live-reload: if engine provided, trigger immediate scan for this obligation type
        if engine is not None and hasattr(engine, '_scan_obligation_type'):
            engine._scan_obligation_type(trigger.obligation_type)

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
        # Auto-register default triggers on first access
        register_default_triggers(_global_registry)
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


def register_default_triggers(
    registry: TriggerRegistry,
    escalation_target: str = "supervisor",
    finance_role: str = "finance",
    tech_review_role: str = "technical_reviewer",
) -> None:
    """
    Register the 4 priority triggers from Directive #015.

    These triggers can be customized for any organizational structure by
    passing role parameters. The defaults are generic role names that can
    be mapped to any specific team structure (CEO/CTO/CFO, or any other).

    Args:
        registry:           TriggerRegistry to populate
        escalation_target:  Role ID for escalation (default: "supervisor")
        finance_role:       Role ID for financial tracking (default: "finance")
        tech_review_role:   Role ID for technical review (default: "technical_reviewer")

    Default triggers registered:
      #1: Research Knowledge Update
      #2: Session Token Recording
      #7: Failure Case Documentation
      #9: Content Accuracy Review
    """

    # Trigger #1: Research Knowledge Update
    registry.register(ObligationTrigger(
        trigger_id="research_knowledge_update",
        trigger_tool_pattern=r"(web_search|WebSearch|WebFetch)",
        obligation_type=OmissionType.KNOWLEDGE_UPDATE_REQUIRED,
        description="After web research, update knowledge/[agent_role]/ with findings",
        target_agent="caller",
        deadline_seconds=1800,  # 30 minutes
        severity="SOFT",
        grace_period_secs=180,  # 3 minute grace
        hard_overdue_secs=3600,  # 1 hour before blocking
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
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
        obligation_type=OmissionType.TOKEN_RECORDING_REQUIRED,
        description=f"After session completion, {finance_role} must run track_burn.py",
        target_agent=finance_role,
        deadline_seconds=600,  # 10 minutes
        severity="HARD",
        grace_period_secs=60,  # 1 minute grace
        hard_overdue_secs=600,  # Immediate block after deadline
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
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
        obligation_type=OmissionType.CASE_DOCUMENTATION_REQUIRED,
        description="After CIEU deny, document in knowledge/cases/",
        target_agent="caller",
        deadline_seconds=3600,  # 1 hour
        severity="SOFT",
        grace_period_secs=600,  # 10 minute grace
        hard_overdue_secs=7200,  # 2 hours before blocking
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
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
        obligation_type=OmissionType.TECHNICAL_REVIEW_REQUIRED,
        description=f"Content must be reviewed by {tech_review_role} before publish",
        target_agent=tech_review_role,
        deadline_seconds=7200,  # 2 hours
        severity="SOFT",
        grace_period_secs=600,  # 10 minute grace
        hard_overdue_secs=14400,  # 4 hours before blocking
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="review_complete",
        verification_method="file_modified",
        verification_target="content/",  # Check if writing to content/ or marketing/
        verification_hint="corresponding _code_review.md file exists",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # ── Directive #015 Additional Triggers ─────────────────────────────────

    # Trigger: Pre-Commit Test
    registry.register(ObligationTrigger(
        trigger_id="pre_commit_test",
        trigger_tool_pattern=r"Bash",
        trigger_param_filter={"command": ["git commit"]},
        obligation_type=OmissionType.PRE_COMMIT_TEST_REQUIRED,
        description="Before git commit, pytest must pass",
        target_agent="caller",
        deadline_seconds=60,  # 1 minute
        severity="HARD",
        grace_period_secs=0,  # No grace - must be immediate
        hard_overdue_secs=60,  # Block immediately after deadline
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="bash_exec",
        verification_method="command_contains",
        verification_target="pytest",
        verification_hint="pytest command executed successfully before commit",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # Trigger: Thinking Discipline Check
    registry.register(ObligationTrigger(
        trigger_id="thinking_discipline_check",
        trigger_tool_pattern=r"(Write|Edit)",  # Only file modifications, not every tool call
        trigger_param_filter=None,
        obligation_type=OmissionType.THINKING_DISCIPLINE_REQUIRED,
        description="After significant work (file write/edit), apply 4-question thinking DNA",
        target_agent="caller",
        deadline_seconds=300,  # 5 minutes
        severity="SOFT",
        grace_period_secs=60,  # 1 minute grace
        hard_overdue_secs=600,  # 10 minutes before blocking
        escalate_to_hard=False,  # Soft obligation, don't escalate
        escalate_to_actor=escalation_target,
        fulfillment_event="file_write",
        verification_method="file_modified",
        verification_target="reports/",
        verification_hint="work report includes thinking DNA questions",
        enabled=False,  # Disabled by default - too noisy, enable per session
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # Trigger: Cross-Review Critical File (FIXED: proper verification_target)
    registry.register(ObligationTrigger(
        trigger_id="cross_review_critical_file",
        trigger_tool_pattern=r"(Write|Edit)",
        trigger_param_filter={"file_path": ["src/", "ystar/"]},  # Only trigger for core code changes
        obligation_type=OmissionType.CROSS_REVIEW_REQUIRED,
        description="Critical file changes require cross-agent review",
        target_agent="*",  # Any other agent can review
        deadline_seconds=600,  # 10 minutes
        severity="SOFT",
        grace_period_secs=120,  # 2 minute grace
        hard_overdue_secs=1800,  # 30 minutes before blocking
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="file_review_comment",  # Fixed: require review comment as evidence
        verification_method="event_received",
        verification_target="file_review_comment",  # Fixed: clear verification target
        required_event_types=["file_review", "peer_review"],  # Fixed: accept review events
        verification_hint="review comment event or peer_review event required",
        enabled=False,  # Disabled by default - requires review workflow setup
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # Trigger: Commit-Push Sync
    registry.register(ObligationTrigger(
        trigger_id="commit_push_sync",
        trigger_tool_pattern=r"Bash",
        trigger_param_filter={"command": ["git commit"]},
        obligation_type=OmissionType.GIT_PUSH_REQUIRED,
        description="After git commit, push to remote within deadline",
        target_agent="caller",
        deadline_seconds=300,  # 5 minutes
        severity="SOFT",
        grace_period_secs=60,  # 1 minute grace
        hard_overdue_secs=600,  # 10 minutes before blocking
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="bash_exec",
        verification_method="command_contains",
        verification_target="git push",
        verification_hint="git push command executed after commit",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # Trigger: Knowledge Gap Bootstrap
    # Note: Disabled by default. This is redundant with research_knowledge_update
    # for most use cases. Enable if you need separate tracking of "bootstrap" vs
    # "ongoing research" knowledge updates.
    registry.register(ObligationTrigger(
        trigger_id="knowledge_gap_bootstrap",
        trigger_tool_pattern=r"(WebSearch|WebFetch)",
        trigger_param_filter=None,  # Trigger on web research
        obligation_type=OmissionType.KNOWLEDGE_UPDATE_REQUIRED,
        description="After detecting knowledge gap (web research), update knowledge/ directory",
        target_agent="caller",
        deadline_seconds=1800,  # 30 minutes
        severity="SOFT",
        grace_period_secs=180,  # 3 minute grace
        hard_overdue_secs=3600,  # 1 hour before blocking
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="file_write",
        verification_method="file_modified",
        verification_target="knowledge/",
        verification_hint="knowledge/ directory updated after research",
        enabled=False,  # Disabled - redundant with research_knowledge_update
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # ── 16 Event-Triggered Obligations (Board Directive 2026-04-03) ──────────

    # 1. commit_push_sync (after git commit) - NOTE: Different from existing commit_push_sync
    registry.register(ObligationTrigger(
        trigger_id="commit_push_sync_30min",
        trigger_tool_pattern=r"Bash",
        trigger_param_filter={"command": ["git commit"]},
        obligation_type=OmissionType.COMMIT_PUSH_REQUIRED,
        description="After git commit, must push within 30min",
        target_agent="caller",
        deadline_seconds=1800,  # 30 min
        severity="HIGH",
        grace_period_secs=60,
        hard_overdue_secs=1800,
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="bash_exec",
        verification_method="event_received",
        verification_target="git_push_event",
        required_event_types=["bash_git_push"],
        verification_hint="git push command executed",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # 2. distribution_verify_post_push (after git push)
    registry.register(ObligationTrigger(
        trigger_id="distribution_verify_post_push",
        trigger_tool_pattern=r"Bash",
        trigger_param_filter={"command": ["git push"]},
        obligation_type=OmissionType.DISTRIBUTION_VERIFY_REQUIRED,
        description="After git push, verify distribution within 5min",
        target_agent="caller",
        deadline_seconds=300,  # 5 min
        severity="MEDIUM",
        grace_period_secs=30,
        hard_overdue_secs=600,
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="distribution_check",
        verification_method="event_received",
        verification_target="distribution_check",
        required_event_types=["distribution_verified"],
        verification_hint="distribution verification event received",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # 3. article_source_verification (CMO writes content)
    registry.register(ObligationTrigger(
        trigger_id="article_source_verification",
        trigger_tool_pattern=r"(Write|Edit)",
        trigger_param_filter={"file_path": ["content/", "marketing/"]},
        obligation_type=OmissionType.SOURCE_VERIFICATION_REQUIRED,
        description="Marketing content must cite sources within 5min",
        target_agent="caller",
        deadline_seconds=300,  # 5 min
        severity="HIGH",
        grace_period_secs=60,
        hard_overdue_secs=600,
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="source_citation",
        verification_method="event_received",
        verification_target="source_citation",
        required_event_types=["source_added"],
        verification_hint="source citation event received",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # 4. p0_bug_response (after P0 bug detected)
    # NOTE: Only triggers when cieu_decision=DENY AND severity=P0/CRITICAL
    registry.register(ObligationTrigger(
        trigger_id="p0_bug_response",
        trigger_tool_pattern=r"^P0_BUG_DETECTED$",  # Only fire on P0 bug detection events
        trigger_param_filter={"cieu_decision": "DENY", "severity": ["P0", "CRITICAL"]},
        obligation_type=OmissionType.P0_BUG_FIX_REQUIRED,
        description="P0 bug must be fixed within 1 hour",
        target_agent="caller",
        deadline_seconds=3600,  # 1 hour
        severity="CRITICAL",
        grace_period_secs=0,
        hard_overdue_secs=3600,
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="bug_fix",
        verification_method="event_received",
        verification_target="p0_fix",
        required_event_types=["bug_fixed", "p0_resolved"],
        verification_hint="P0 bug fix event received",
        enabled=False,  # Disabled - requires event-driven trigger infrastructure
        deduplicate=True,
        deny_closure_on_open=True,
    ))

    # 5. p1_bug_response (after P1 bug detected)
    # NOTE: Only triggers when cieu_decision=DENY AND severity=P1/HIGH
    registry.register(ObligationTrigger(
        trigger_id="p1_bug_response",
        trigger_tool_pattern=r"^P1_BUG_DETECTED$",  # Only fire on P1 bug detection events
        trigger_param_filter={"cieu_decision": "DENY", "severity": ["P1", "HIGH"]},
        obligation_type=OmissionType.P1_BUG_FIX_REQUIRED,
        description="P1 bug must be fixed within 24 hours",
        target_agent="caller",
        deadline_seconds=86400,  # 24 hours
        severity="HIGH",
        grace_period_secs=3600,
        hard_overdue_secs=86400,
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="bug_fix",
        verification_method="event_received",
        verification_target="p1_fix",
        required_event_types=["bug_fixed", "p1_resolved"],
        verification_hint="P1 bug fix event received",
        enabled=False,  # Disabled - requires event-driven trigger infrastructure
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # 6. escalation_response (after escalation event)
    # NOTE: Disabled by default - should be triggered by escalation events, not tool calls
    registry.register(ObligationTrigger(
        trigger_id="escalation_response",
        trigger_tool_pattern=r"^ESCALATION_EVENT$",  # Only fire on actual escalation events
        trigger_param_filter=None,
        obligation_type=OmissionType.ESCALATION_RESPONSE_REQUIRED,
        description="Escalation must be responded to within 10min",
        target_agent=escalation_target,
        deadline_seconds=600,  # 10 min
        severity="HIGH",
        grace_period_secs=60,
        hard_overdue_secs=1800,
        escalate_to_hard=True,
        escalate_to_actor="board",
        fulfillment_event="escalation_response",
        verification_method="event_received",
        verification_target="escalation_response",
        required_event_types=["escalation_acknowledged", "escalation_resolved"],
        verification_hint="escalation response event received",
        enabled=False,  # Disabled - requires event-driven trigger infrastructure
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # 7. security_incident_response
    # NOTE: Only triggers when security_alert param is explicitly set
    registry.register(ObligationTrigger(
        trigger_id="security_incident_response",
        trigger_tool_pattern=r"^SECURITY_ALERT$",  # Only fire on security alert events
        trigger_param_filter={"security_alert": ["true", "1", True]},
        obligation_type=OmissionType.SECURITY_INCIDENT_RESPONSE_REQUIRED,
        description="Security incident must be responded to within 30min",
        target_agent=escalation_target,
        deadline_seconds=1800,  # 30 min
        severity="CRITICAL",
        grace_period_secs=0,
        hard_overdue_secs=1800,
        escalate_to_hard=True,
        escalate_to_actor="board",
        fulfillment_event="security_response",
        verification_method="event_received",
        verification_target="security_response",
        required_event_types=["security_incident_acknowledged", "security_incident_resolved"],
        verification_hint="security response event received",
        enabled=False,  # Disabled - requires event-driven trigger infrastructure
        deduplicate=True,
        deny_closure_on_open=True,
    ))

    # 8. directive_decomposition (CEO issues directive)
    registry.register(ObligationTrigger(
        trigger_id="directive_decomposition",
        trigger_tool_pattern=r"(Write|Edit)",
        trigger_param_filter={"file_path": [".claude/tasks/"]},
        obligation_type=OmissionType.DIRECTIVE_DECOMPOSITION_REQUIRED,
        description="CEO directive must be decomposed into tasks within 15min",
        target_agent="caller",
        deadline_seconds=900,  # 15 min
        severity="MEDIUM",
        grace_period_secs=120,
        hard_overdue_secs=1800,
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="task_created",
        verification_method="event_received",
        verification_target="task_decomposition",
        required_event_types=["task_created", "subtask_created"],
        verification_hint="task decomposition event received",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # 9. test_after_code_change (after src/ or ystar/ edit)
    registry.register(ObligationTrigger(
        trigger_id="test_after_code_change",
        trigger_tool_pattern=r"(Write|Edit)",
        trigger_param_filter={"file_path": ["src/", "ystar/"]},
        obligation_type=OmissionType.PRE_COMMIT_TEST_REQUIRED,
        description="After code change, run tests within 5min",
        target_agent="caller",
        deadline_seconds=300,  # 5 min
        severity="HIGH",
        grace_period_secs=30,
        hard_overdue_secs=600,
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="test_run",
        verification_method="event_received",
        verification_target="pytest_run",
        required_event_types=["test_executed", "pytest_run"],
        verification_hint="pytest execution event received",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # 10. knowledge_sync_after_research (after WebSearch)
    registry.register(ObligationTrigger(
        trigger_id="knowledge_sync_after_research",
        trigger_tool_pattern=r"(WebSearch|WebFetch)",
        trigger_param_filter=None,
        obligation_type=OmissionType.KNOWLEDGE_UPDATE_REQUIRED,
        description="After web research, sync to knowledge/ within 10min",
        target_agent="caller",
        deadline_seconds=600,  # 10 min
        severity="MEDIUM",
        grace_period_secs=120,
        hard_overdue_secs=1200,
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="knowledge_update",
        verification_method="event_received",
        verification_target="knowledge_sync",
        required_event_types=["knowledge_updated", "file_write_knowledge"],
        verification_hint="knowledge update event received",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # 11. session_report_before_close
    registry.register(ObligationTrigger(
        trigger_id="session_report_before_close",
        trigger_tool_pattern=r"(session_end|TaskComplete)",
        trigger_param_filter=None,
        obligation_type=OmissionType.REQUIRED_RESULT_PUBLICATION,
        description="Before session close, publish work report",
        target_agent="caller",
        deadline_seconds=300,  # 5 min
        severity="HIGH",
        grace_period_secs=60,
        hard_overdue_secs=600,
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="report_published",
        verification_method="event_received",
        verification_target="work_report",
        required_event_types=["report_written", "work_report_published"],
        verification_hint="work report published event received",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=True,
    ))

    # 12. handoff_documentation
    registry.register(ObligationTrigger(
        trigger_id="handoff_documentation",
        trigger_tool_pattern=r"(TaskComplete|task_closed)",
        trigger_param_filter=None,
        obligation_type=OmissionType.REQUIRED_RESULT_PUBLICATION,
        description="After task completion, update session_handoff.md",
        target_agent="caller",
        deadline_seconds=300,  # 5 min
        severity="MEDIUM",
        grace_period_secs=60,
        hard_overdue_secs=600,
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="handoff_updated",
        verification_method="event_received",
        verification_target="handoff_update",
        required_event_types=["handoff_documented", "session_handoff_updated"],
        verification_hint="session handoff update event received",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # 13. blocker_escalation_immediate
    # NOTE: Only triggers when status param is explicitly "blocked"
    registry.register(ObligationTrigger(
        trigger_id="blocker_escalation_immediate",
        trigger_tool_pattern=r"^BLOCKER_DETECTED$",  # Only fire on blocker detection events
        trigger_param_filter={"status": ["blocked", "BLOCKED"]},
        obligation_type=OmissionType.REQUIRED_ESCALATION,
        description="When blocked, escalate immediately (1min)",
        target_agent="caller",
        deadline_seconds=60,  # 1 min
        severity="CRITICAL",
        grace_period_secs=0,
        hard_overdue_secs=60,
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="escalation",
        verification_method="event_received",
        verification_target="blocker_escalated",
        required_event_types=["escalation_event", "blocker_reported"],
        verification_hint="escalation event received",
        enabled=False,  # Disabled - requires event-driven trigger infrastructure
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # 14. cieu_violation_root_cause
    registry.register(ObligationTrigger(
        trigger_id="cieu_violation_root_cause",
        trigger_tool_pattern=r".*",
        trigger_param_filter={"cieu_decision": "DENY"},
        obligation_type=OmissionType.CASE_DOCUMENTATION_REQUIRED,
        description="After CIEU violation, document root cause within 30min",
        target_agent="caller",
        deadline_seconds=1800,  # 30 min
        severity="HIGH",
        grace_period_secs=300,
        hard_overdue_secs=3600,
        escalate_to_hard=True,
        escalate_to_actor=escalation_target,
        fulfillment_event="root_cause_doc",
        verification_method="event_received",
        verification_target="root_cause_documented",
        required_event_types=["case_documented", "root_cause_analysis_complete"],
        verification_hint="root cause documentation event received",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=False,
    ))

    # 15. cross_agent_review_request
    registry.register(ObligationTrigger(
        trigger_id="cross_agent_review_request",
        trigger_tool_pattern=r"(Write|Edit)",
        trigger_param_filter={"file_path": ["AGENTS.md", "CLAUDE.md"]},
        obligation_type=OmissionType.CROSS_REVIEW_REQUIRED,
        description="Constitutional changes require cross-agent review",
        target_agent=escalation_target,
        deadline_seconds=600,  # 10 min
        severity="CRITICAL",
        grace_period_secs=0,
        hard_overdue_secs=600,
        escalate_to_hard=True,
        escalate_to_actor="board",
        fulfillment_event="constitutional_review",
        verification_method="event_received",
        verification_target="constitutional_review_complete",
        required_event_types=["constitutional_review", "cross_review_complete"],
        verification_hint="constitutional review event received",
        enabled=True,
        deduplicate=True,
        deny_closure_on_open=True,
    ))

    # 16. daily_standup_check
    registry.register(ObligationTrigger(
        trigger_id="daily_standup_check",
        trigger_tool_pattern=r"(session_start|boot_complete)",
        trigger_param_filter=None,
        obligation_type=OmissionType.REQUIRED_STATUS_UPDATE,
        description="Daily session start requires status check-in",
        target_agent="caller",
        deadline_seconds=600,  # 10 min
        severity="LOW",
        grace_period_secs=300,
        hard_overdue_secs=1800,
        escalate_to_hard=False,
        escalate_to_actor=escalation_target,
        fulfillment_event="status_update",
        verification_method="event_received",
        verification_target="daily_checkin",
        required_event_types=["status_updated", "daily_standup_complete"],
        verification_hint="daily status update event received",
        enabled=False,  # Disabled by default - enable if daily standups required
        deduplicate=True,
        deny_closure_on_open=False,
    ))
