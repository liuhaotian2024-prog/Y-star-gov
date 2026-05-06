# Runtime Linkage Governance

Y-star-gov owns the generic anti-drift contract for runtime artifacts. It does not know Y*Bridge Labs route names or business content. It validates structure and invariants:

- P0 artifacts require writers, readers, and evidence.
- Selected routes require writer, reader, and readback test.
- Next milestone and blocker state require writer and next-runtime reader.
- Brain updates that change route/strategy/blocker must be loaded by a current-state reader.
- KG, CZL, and CIEU closures must be linked when decision state changes.
- Report-only P0 closures fail.
- Stale next-milestone reads fail.
- External action boundary bypass fails.

Use `evaluate_anti_drift_gate(payload)` to validate a system-specific manifest. The payload may come from Bridge Labs, another company runtime, or a future gov-mcp tool call.
