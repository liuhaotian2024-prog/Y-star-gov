"""
ystar.governance.parent_session_rules  —  Parent Session Omission Rules
========================================================================

Defines 4 obligations for the CEO parent session entity type "ceo_parent":

1. parent_tool_uses_density: tool_uses/30min must not exceed threshold (100)
2. parent_drift_rate: drift_count/30min must not exceed 2
3. parent_reply_latency: reply response time < 2x baseline
4. parent_stream_timeout: sub-agent stream_timeout/session must not exceed 2

These rules trigger on ENTITY_CREATED for ceo_parent entities and require
periodic STATUS_UPDATE_EVENT to fulfill (heartbeat pattern).

Board directive: CZL-PARENT-SESSION-REGISTER-AS-ENTITY (2026-04-20)
"""
from __future__ import annotations

import time
from typing import Optional

from ystar.governance.omission_models import (
    EscalationAction,
    EscalationPolicy,
    EntityStatus,
    GEventType,
    GovernanceEvent,
    OmissionType,
    ObligationRecord,
    Severity,
    TrackedEntity,
)
from ystar.governance.omission_rules import (
    OmissionRule,
    RuleRegistry,
    _select_current_owner,
)


# ── Actor selector for parent session ────────────────────────────────────────

def _select_parent_session_owner(entity: TrackedEntity, event: GovernanceEvent) -> Optional[str]:
    """Select current_owner for parent session entities."""
    if entity.entity_type == "ceo_parent":
        return entity.current_owner_id or entity.initiator_id
    return None


# ── Parent Session Escalation Policy ─────────────────────────────────────────

_PARENT_ESCALATION = EscalationPolicy(
    reminder_after_secs=900.0,    # 15 min reminder
    violation_after_secs=1800.0,  # 30 min violation
    escalate_after_secs=3600.0,   # 1h escalate
    actions=[EscalationAction.REMINDER, EscalationAction.VIOLATION, EscalationAction.ESCALATE],
    escalate_to="board",
    deny_closure_on_open=True,
)


# ── Rule I: Parent tool_uses density ─────────────────────────────────────────

RULE_PARENT_TOOL_USES_DENSITY = OmissionRule(
    rule_id="rule_i_parent_tool_uses_density",
    name="Parent Tool Uses Density",
    description=(
        "Parent session must emit periodic status updates proving "
        "tool_uses/30min does not exceed threshold (100). "
        "Absence of heartbeat = potential drift without self-correction."
    ),
    trigger_event_types=[GEventType.ENTITY_CREATED],
    entity_types=["ceo_parent"],
    actor_selector=_select_parent_session_owner,
    obligation_type="parent_tool_uses_density",
    required_event_types=[
        GEventType.STATUS_UPDATE_EVENT,
        GEventType.INTERVENTION_PULSE,
    ],
    due_within_secs=1800.0,  # 30 min window
    hard_overdue_secs=3600.0,  # 1h hard
    violation_code="parent_tool_uses_density_violation",
    severity=Severity.HIGH,
    escalation_policy=_PARENT_ESCALATION,
    deny_closure_on_open=True,
)


# ── Rule J: Parent drift rate ────────────────────────────────────────────────

RULE_PARENT_DRIFT_RATE = OmissionRule(
    rule_id="rule_j_parent_drift_rate",
    name="Parent Drift Rate",
    description=(
        "Parent session drift_count/30min must not exceed 2. "
        "Tracks whether the parent is drifting without self-awareness. "
        "Fulfilled by STATUS_UPDATE_EVENT confirming drift < threshold."
    ),
    trigger_event_types=[GEventType.ENTITY_CREATED],
    entity_types=["ceo_parent"],
    actor_selector=_select_parent_session_owner,
    obligation_type="parent_drift_rate",
    required_event_types=[
        GEventType.STATUS_UPDATE_EVENT,
        GEventType.INTERVENTION_PULSE,
    ],
    due_within_secs=1800.0,  # 30 min window
    hard_overdue_secs=3600.0,
    violation_code="parent_drift_rate_violation",
    severity=Severity.HIGH,
    escalation_policy=_PARENT_ESCALATION,
    deny_closure_on_open=True,
)


# ── Rule K: Parent reply latency ─────────────────────────────────────────────

RULE_PARENT_REPLY_LATENCY = OmissionRule(
    rule_id="rule_k_parent_reply_latency",
    name="Parent Reply Latency",
    description=(
        "Parent session reply response time must stay < 2x baseline. "
        "Excessive latency indicates governance loop overload or context bloat. "
        "Fulfilled by STATUS_UPDATE_EVENT with acceptable latency metric."
    ),
    trigger_event_types=[GEventType.ENTITY_CREATED],
    entity_types=["ceo_parent"],
    actor_selector=_select_parent_session_owner,
    obligation_type="parent_reply_latency",
    required_event_types=[
        GEventType.STATUS_UPDATE_EVENT,
        GEventType.INTERVENTION_PULSE,
    ],
    due_within_secs=1800.0,
    hard_overdue_secs=3600.0,
    violation_code="parent_reply_latency_violation",
    severity=Severity.MEDIUM,
    escalation_policy=_PARENT_ESCALATION,
    deny_closure_on_open=False,
)


# ── Rule L: Parent stream timeout ────────────────────────────────────────────

RULE_PARENT_STREAM_TIMEOUT = OmissionRule(
    rule_id="rule_l_parent_stream_timeout",
    name="Parent Stream Timeout",
    description=(
        "Sub-agent stream_timeout/session must not exceed 2. "
        "Repeated timeouts indicate systematic dispatch failure. "
        "Fulfilled by STATUS_UPDATE_EVENT confirming timeout count < threshold."
    ),
    trigger_event_types=[GEventType.ENTITY_CREATED],
    entity_types=["ceo_parent"],
    actor_selector=_select_parent_session_owner,
    obligation_type="parent_stream_timeout",
    required_event_types=[
        GEventType.STATUS_UPDATE_EVENT,
        GEventType.INTERVENTION_PULSE,
    ],
    due_within_secs=1800.0,
    hard_overdue_secs=3600.0,
    violation_code="parent_stream_timeout_violation",
    severity=Severity.MEDIUM,
    escalation_policy=_PARENT_ESCALATION,
    deny_closure_on_open=False,
)


# ── All parent rules ─────────────────────────────────────────────────────────

PARENT_SESSION_RULES = [
    RULE_PARENT_TOOL_USES_DENSITY,
    RULE_PARENT_DRIFT_RATE,
    RULE_PARENT_REPLY_LATENCY,
    RULE_PARENT_STREAM_TIMEOUT,
]


# ── Registration helper ──────────────────────────────────────────────────────

def register_parent_session_rules(registry: RuleRegistry) -> int:
    """
    Register all parent session rules into the given RuleRegistry.
    Returns the count of rules registered.
    """
    for rule in PARENT_SESSION_RULES:
        registry.register(rule)
    return len(PARENT_SESSION_RULES)


def create_parent_entity(session_id: str, agent_id: str = "ceo") -> TrackedEntity:
    """
    Factory: create a TrackedEntity for the parent session.

    Args:
        session_id: unique session identifier (from .ystar_session.json)
        agent_id: the agent role (default "ceo")

    Returns:
        TrackedEntity ready for OmissionEngine.register_entity()
    """
    entity_id = f"parent-{session_id}"
    return TrackedEntity(
        entity_id=entity_id,
        entity_type="ceo_parent",
        initiator_id=agent_id,
        current_owner_id=agent_id,
        status=EntityStatus.ACTIVE,
        goal_summary=f"Parent session governance for {agent_id} (session {session_id})",
        metadata={
            "session_id": session_id,
            "agent_id": agent_id,
            "registered_at": time.time(),
        },
    )


def create_parent_obligations(
    entity_id: str,
    actor_id: str = "ceo",
    session_id: Optional[str] = None,
) -> list:
    """
    Create the 4 ObligationRecord instances for a parent session entity.

    Returns list of ObligationRecord ready for store.add_obligation().
    """
    now = time.time()
    obligations = []

    for rule in PARENT_SESSION_RULES:
        ob = ObligationRecord(
            entity_id=entity_id,
            actor_id=actor_id,
            obligation_type=rule.obligation_type,
            rule_id=rule.rule_id,
            required_event_types=rule.required_event_types,
            due_at=now + rule.due_within_secs,
            grace_period_secs=rule.grace_period_secs,
            hard_overdue_secs=rule.hard_overdue_secs,
            violation_code=rule.violation_code,
            severity=rule.severity,
            escalation_policy=rule.escalation_policy,
            session_id=session_id,
        )
        obligations.append(ob)

    return obligations
