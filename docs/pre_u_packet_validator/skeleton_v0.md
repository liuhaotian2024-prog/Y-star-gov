# Pre-U Packet Validator Skeleton v0

This file documents the first deterministic validator skeleton in
`ystar/governance/pre_u_packet_validator.py`.

## What It Checks

- Packet is a mapping/object.
- Core packet identity fields are present.
- `agent_id`, `agent_capsule_ref`, and `task_id` are structurally present.
- Y* and `m_functor` are present.
- `candidate_actions` / candidate U list is non-empty.
- Each candidate has an identifier and predicted `Rt+1`.
- `selected_action` / selected U references one candidate.
- Residual-minimization rationale is present.
- Governance expectations are present.
- CIEU link policy is present.
- High-risk tiers return an escalation decision.

## What It Does Not Check

- It does not generate packets.
- It does not call an LLM.
- It does not execute actions.
- It does not call hooks.
- It does not write or read CIEU events.
- It does not inspect DBs, logs, active-agent state, daemon state, or runtime
  artifacts.
- It does not prove Y* / `m_functor` semantics.
- It does not perform Goodhart or omission semantic validation.

## Decisions

The skeleton returns one hook-facing decision:

- `allow`
- `warn`
- `require_revision`
- `escalate`
- `deny`

The result also exposes `validation_status`, `failure_codes`, `issues`,
`warnings`, `required_revisions`, `checked_fields`, and a small
`normalized_summary`.

## Boundary

Labs still thinks and generates the Pre-U packet. Y-star-gov only judges
deterministic structure and governance readiness. Hook integration, CIEU event
schema updates, prediction-delta metrics, and brain writeback remain future
work.
