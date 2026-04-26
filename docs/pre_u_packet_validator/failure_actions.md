# Failure Actions

## allow

- When to use: Packet is valid for the requested risk tier and action scope.
- Hook later: Allow action if all other governance checks pass.
- CIEU pre-action event: Should be emitted or linked when configured.
- Brain learning: No learning yet; learning waits for post-action evidence.
- Human/operator review: Not required unless another policy requires it.

## warn

- When to use: Packet has non-blocking weakness that does not invalidate the
  action for the current risk tier.
- Hook later: Allow with warning or surface warning to operator/runtime.
- CIEU pre-action event: Should include warning if event exists.
- Brain learning: Warning alone should not train brain without outcome evidence.
- Human/operator review: Optional.

## require_revision

- When to use: Packet is incomplete, internally inconsistent, or lacks required
  rationale but is not inherently dangerous.
- Hook later: Block action until revised packet passes validation.
- CIEU pre-action event: May log attempted invalid packet as governance evidence.
- Brain learning: Speculative packet failure alone should not become learning
  unless later evidence supports it.
- Human/operator review: Usually not required unless repeated.

## escalate

- When to use: High-risk action, unclear authority, weak field grounding,
  possible Goodhart/fake alignment, or governance-sensitive scope.
- Hook later: Stop normal flow and require escalation path.
- CIEU pre-action event: Should record escalation reason if event path exists.
- Brain learning: Only evidence-backed escalation patterns should feed learning.
- Human/operator review: Required or strongly expected.

## deny

- When to use: Schema invalid, identity invalid, selected action impossible to
  reference, forbidden mutation hidden in packet, or Tier 4 action lacks explicit
  authorization.
- Hook later: Deny action.
- CIEU pre-action event: Denied dangerous action may still be logged as
  governance evidence.
- Brain learning: Denial alone is not enough for durable brain update; use CIEU
  evidence and repeated deltas.
- Human/operator review: Needed if denial blocks critical work or indicates
  serious boundary violation.
