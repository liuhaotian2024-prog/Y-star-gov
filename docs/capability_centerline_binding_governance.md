# Capability Centerline Binding Governance

Capability binding governance classifies every capability by functional nature before it can be treated as active runtime state.

Functional classes:

- `cognitive_capability`: must bind to the CEO brain/cognition centerline or be marked `reference_only`.
- `behavior_control_capability`: must bind to canonical action runtime and Y-star-gov governance boundary.
- `evidence_closure_capability`: must bind to KG/CZL/CIEU/K9 evidence/readback when it affects current state.
- `boundary_capability`: must bind to Y-star-gov invariants and gov-mcp exposure when agent-facing.
- `reference_only_artifact`: must not be consumed as current state.

P0 `missing_binding`, `wrong_centerline`, or stale/reference-only current-state consumption fails the gate.

This module validates generic invariants only. It does not know Bridge Labs route names and does not authorize external action.
