# External Adapter Contract

An external adapter owns only translation at the boundary:

```text
external request
  -> hook-like envelope
  -> Y-star-gov hook dry-run CLI
  -> JSON decision envelope + exit code
```

## Adapter Responsibilities

- Preserve the external request identity.
- Declare `Y*` / objective explicitly.
- Provide current context `Xt`.
- Provide `m_functor` grounding from available local context.
- Provide candidate actions and selected action ID.
- Provide predicted outcome and predicted residual.
- Provide governance expectations and CIEU link policy.
- Consume the CLI decision without treating it as action execution.

## Adapter Must Not

- Execute the requested action.
- Write CIEU records.
- Mutate brain or memory.
- Read DB/log/runtime artifacts.
- Hide runtime mutations inside envelope text.
- Treat speculative predicted outcomes as actual outcomes.
