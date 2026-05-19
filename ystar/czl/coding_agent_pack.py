"""
ystar.czl.coding_agent_pack — coding-agent-specific omission rules + gating
policy + obligation registration, runtime-bound for Trampoline.

This module is the trampoline-specific layer that sits ON TOP OF the generic
governance primitives in `ystar.governance.{omission_engine,intervention_engine}`.
It declares:

  - `CodingAgentEventType` — action-type string constants that the
    Trampoline loop emits while driving a coding agent (NOT part of the
    generic governance vocabulary).
  - `TRAMPOLINE_GATING_POLICY` — a `GatingPolicy` extended with the
    trampoline-side fulfilment and high-risk action strings. The generic
    governance core stays free of any trampoline string.
  - 3+ coding-specific `OmissionRule`s registered via
    `register_coding_agent_rules(registry)`:
      1. agent must emit a first tool_use shortly after dispatch
         (deadlock / silent-agent detection),
      2. agent must NOT declare done without a `verifier_passed` event
         (fake-completion detection),
      3. residual must decrease within a window (no-progress detection).
  - `register_post_declare_done_obligation` — a trampoline-side analogue
    of Y*'s `register_post_ship_completeness_obligation`. It is fully
    independent and does NOT call the Y*-internal (now DeprecationWarning'd)
    ship variant.

Design constraint: nothing in this file imports from Y*-internal helpers
(no ship / manifest / phase-N / redirect / action_promise dependencies).
"""
from __future__ import annotations

import time
import uuid
from typing import List, Optional

from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_models import (
    EntityStatus, GEventType, ObligationRecord, ObligationStatus,
    OmissionType, Severity, TrackedEntity,
)
from ystar.governance.omission_rules import OmissionRule, RuleRegistry
from ystar.governance.intervention_engine import GatingPolicy


# === Coding-agent action-type strings =======================================
# Strings injected into the GatingPolicy. The generic governance core does
# not know about them — they live entirely on the trampoline side.

class CodingAgentEventType:
    """Action-type strings emitted by the Trampoline loop on behalf of a
    coding agent. These are reactive-feedback breadcrumbs; the obligation
    engine consumes them when deciding fulfilment / violation."""

    TOOL_USE          = "trampoline.tool_use"
    """An agent-initiated probe / fix / edit attempt was observed."""

    VERIFIER_PASSED   = "trampoline.verifier_passed"
    """All scenario verifiers reported `passed=True` at this iteration."""

    VERIFIER_FAILED   = "trampoline.verifier_failed"
    """At least one verifier reported `passed=False`."""

    RESIDUAL_REPORT   = "trampoline.residual_report"
    """The loop computed an Rt+1 value and is publishing it."""

    REDUCE_RESIDUAL   = "trampoline.reduce_residual"
    """The agent's last action produced a strictly-lower residual than the
    previous iteration (fulfilment of the no-progress obligation)."""

    DECLARE_DONE      = "trampoline.declare_done"
    """The loop / agent is about to mark the run converged. High-risk
    action gated by `gate_check`."""


# === Trampoline gating policy ===============================================

# Build the gating policy by extending the generic GatingPolicy with
# trampoline-specific strings. The generic core was deliberately set up to
# accept policy extension via `extend()` so domain packs (this file) can
# bolt their own vocabulary on without modifying core code.
TRAMPOLINE_GATING_POLICY: GatingPolicy = GatingPolicy().extend(
    fulfillment={
        # Any agent-initiated work toward paying down obligations.
        CodingAgentEventType.TOOL_USE,
        CodingAgentEventType.VERIFIER_PASSED,
        CodingAgentEventType.REDUCE_RESIDUAL,
        CodingAgentEventType.RESIDUAL_REPORT,
    },
    high_risk={
        # The canonical "claim completed" — gate blocks if there are open
        # critical obligations against this agent.
        CodingAgentEventType.DECLARE_DONE,
    },
)


# === Coding-agent OmissionRules =============================================

def _stuck_after_dispatch_rule() -> OmissionRule:
    """Agent must emit a first tool-use shortly after the run starts —
    otherwise we treat it as a silent / stuck agent. obligation_type is
    mapped to OmissionType.REQUIRED_ACKNOWLEDGEMENT — the agent hasn't
    acknowledged the dispatched task with any work."""
    return OmissionRule(
        rule_id="trampoline.stuck_after_dispatch",
        name="first tool_use missing",
        description=(
            "After the trampoline loop dispatches a coding task, the agent "
            "must emit at least one TOOL_USE event within the window. "
            "Empty windows are treated as a stuck / silent agent."
        ),
        trigger_event_types=[
            GEventType.ENTITY_CREATED,
            GEventType.TASK_DISPATCHED,
        ],
        entity_types=["coding_agent"],
        obligation_type=OmissionType.REQUIRED_ACKNOWLEDGEMENT.value,
        required_event_types=[CodingAgentEventType.TOOL_USE],
        due_within_secs=30.0,
        severity=Severity.MEDIUM,
        violation_code="trampoline.silent_agent",
    )


def _fake_done_rule() -> OmissionRule:
    """If the agent reports DECLARE_DONE, there must be a recent
    VERIFIER_PASSED — otherwise it's a fake-completion claim. obligation_type
    re-uses OmissionType.POST_SHIP_COMPLETENESS semantically; the rule_id
    keeps trampoline-distinctive identity."""
    return OmissionRule(
        rule_id="trampoline.fake_declare_done",
        name="declare_done without verifier evidence",
        description=(
            "DECLARE_DONE must be preceded by VERIFIER_PASSED. The "
            "obligation is created on DECLARE_DONE and requires the loop "
            "to have already published a verifier_passed event."
        ),
        trigger_event_types=[CodingAgentEventType.DECLARE_DONE],
        entity_types=["coding_agent"],
        obligation_type=OmissionType.POST_SHIP_COMPLETENESS.value,
        required_event_types=[CodingAgentEventType.VERIFIER_PASSED],
        # Tight window — the verifier_passed event should already be in
        # the store before declare_done arrives, so any reasonable scan
        # will mark it fulfilled immediately. If it isn't, we want the
        # violation now, not in 5 minutes.
        due_within_secs=5.0,
        severity=Severity.HIGH,
        violation_code="trampoline.fake_completion",
    )


def _residual_stuck_rule() -> OmissionRule:
    """Once we've observed a residual, we expect the agent to reduce it
    within a small number of iterations. obligation_type mapped to
    OmissionType.REQUIRED_STATUS_UPDATE — a residual report demands a
    follow-up status update (in our case, a residual-reducing edit)."""
    return OmissionRule(
        rule_id="trampoline.residual_stuck",
        name="residual not decreasing",
        description=(
            "When the loop publishes RESIDUAL_REPORT, the agent must "
            "produce a REDUCE_RESIDUAL event within the window or the "
            "iteration is treated as stalled."
        ),
        trigger_event_types=[CodingAgentEventType.RESIDUAL_REPORT],
        entity_types=["coding_agent"],
        obligation_type=OmissionType.REQUIRED_STATUS_UPDATE.value,
        required_event_types=[CodingAgentEventType.REDUCE_RESIDUAL],
        # ~3 iterations at the cheap-API per-iter cost (~60s each).
        due_within_secs=180.0,
        severity=Severity.MEDIUM,
        violation_code="trampoline.residual_stuck",
    )


def register_coding_agent_rules(registry: RuleRegistry) -> None:
    """Register the trampoline coding-agent rules into a RuleRegistry.

    Idempotent: re-registering the same rule_id is a no-op via the
    registry's own dedup."""
    for factory in (
        _stuck_after_dispatch_rule,
        _fake_done_rule,
        _residual_stuck_rule,
    ):
        rule = factory()
        # RuleRegistry.register accepts a rule; if already present, skip.
        if registry.get(rule.rule_id) is None:
            registry.register(rule)


# === register_post_declare_done_obligation ==================================

def register_post_declare_done_obligation(
    engine: OmissionEngine,
    session_id: str,
    actor_id: str,
    entity_id: Optional[str] = None,
    due_within_secs: float = 600.0,
) -> ObligationRecord:
    """Trampoline-side counterpart to Y*'s
    `register_post_ship_completeness_obligation`. Creates ONE obligation
    against a coding-agent entity that requires either:
      - VERIFIER_PASSED, or
      - COMPLETION_EVENT
    to be observed before the entity may be closed.

    This is intentionally independent of the Y* ship variant — it does
    NOT call `register_post_ship_completeness_obligation` and shares no
    code path with it. When trampoline-core is physically split out,
    this function is what remains; the Y* variant is left behind.

    Parameters
    ----------
    engine          : OmissionEngine — store + registry must be set up
    session_id      : the CZLRun.run_id
    actor_id        : the responsible agent identity (e.g. backend.name)
    entity_id       : entity to attach the obligation to; defaults to
                      `f"coding_agent.{session_id}"`
    due_within_secs : window from now within which fulfilment is expected
    """
    eid = entity_id or f"coding_agent.{session_id}"
    now = time.time()

    # Make sure the entity exists so list_obligations / fulfilment work.
    existing = engine.store.get_entity(eid)
    if existing is None:
        engine.store.upsert_entity(TrackedEntity(
            entity_id=eid,
            entity_type="coding_agent",
            initiator_id=actor_id,
            current_owner_id=actor_id,
            status=EntityStatus.CREATED,
            goal_summary=f"Trampoline coding-agent run {session_id}",
        ))

    ob = ObligationRecord(
        obligation_id=f"trampoline.post_declare_done.{session_id}.{uuid.uuid4().hex[:8]}",
        entity_id=eid,
        actor_id=actor_id,
        # Reuses OmissionType.POST_SHIP_COMPLETENESS enum value so the
        # omission engine's obligation-type registry accepts it. The
        # rule_id keeps trampoline-distinctive identity for audit.
        obligation_type=OmissionType.POST_SHIP_COMPLETENESS.value,
        required_event_types=[
            CodingAgentEventType.VERIFIER_PASSED,
            GEventType.COMPLETION_EVENT,
        ],
        due_at=now + due_within_secs,
        status=ObligationStatus.PENDING,
        rule_id="trampoline.post_declare_done",
    )
    engine.store.add_obligation(ob)
    return ob
