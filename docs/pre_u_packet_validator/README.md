# Pre-U Counterfactual Packet Validator Interface

This directory defines the Y-star-gov-side validator interface and v0
deterministic skeleton for labs-generated Pre-U Counterfactual Packets.

The v0 skeleton lives at `ystar/governance/pre_u_packet_validator.py`. It
validates packet structure only. It does not generate packets, execute hooks,
write CIEU events, open DBs, or move Aiden's brain into Y-star-gov.

Boundary preserved:

- `ystar-company` / labs thinks.
- Y-star-gov judges.
- Hook enforces.
- CIEU records and teaches.
- Brain learns from evidence-backed deltas.

The source packet shape is the Aiden-side reference schema in
`/Users/haotianliu/.openclaw/workspace/ystar-company/agent_brains/Aiden-CEO/pre_u_counterfactual/packet_schema.json`.
Y-star-gov may later validate that packet, but it does not own Aiden's brain,
subjective cognition, or packet generation.

This spec prepares a future deterministic validation interface around schema,
agent identity, Y*, m_functor grounding, candidate actions, selected action
consistency, residual logic, risk tier, CIEU linkage, and forbidden mutation
checks.

See `skeleton_v0.md` for the implemented structural checks and remaining
non-goals.
