# Hook Contract

The future hook layer should remain thin.

Hook responsibilities:

- Determine or receive action risk tier.
- Require Pre-U packet based on risk tier.
- Pass action envelope and packet to the Y-star-gov validator.
- Act on validator output.
- Emit or link pre-action CIEU evidence when required.
- Never open DB contents.

Hook must not:

- Generate counterfactuals.
- Validate `m_functor` itself except by calling Y-star-gov validator.
- Perform complex reasoning.
- Replace Y-star-gov governance judgment.
- Treat speculative predictions as actual outcomes.

## Risk Tier Policy

| Tier | Action class | Packet policy | Hook behavior |
| --- | --- | --- | --- |
| Tier 0 | Read-only action. | Packet optional. | Allow if normal governance allows. |
| Tier 1 | Docs/index update. | Lightweight packet recommended. | Warn or allow depending on policy. |
| Tier 2 | Source modification. | Packet required. | Deny or require revision if missing/invalid. |
| Tier 3 | Governance, hook, runtime script, scheduler, or enforcement change. | Packet required plus escalation. | Require validator approval and escalation. |
| Tier 4 | DB/WAL/SHM/log/active-agent mutation. | Packet required plus hard review; normally deny unless explicitly authorized. | Deny by default or require explicit authorization and validator approval. |

Hook decision should be based on validator result plus existing governance checks.
The packet stores the reasoning. The hook enforces the gate.
