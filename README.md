# Y-star-gov

Y-star-gov is the governance reflex center for the Y* agent-company runtime. It
owns deterministic governance, runtime hooks, contract validation, check/enforce
semantics, and formal CIEUStore governance records.

It is not the CEO behavior center and it is not the provider executor.
bridge-labs produces company decisions and CEO packets. Y-star-gov validates and
records them. gov-mcp handles provider/tool execution boundaries.

## Current role in the system

| Repository | Canonical role |
| --- | --- |
| `Y-star-gov` | Governance reflex center, deterministic validators, runtime hooks, IntentContract, CIEUStore records, seal/verify paths. |
| `ystar-bridge-labs` | CEO/company behavior center, mission command, owner decisions, pre-action packets, post-action residuals. |
| `gov-mcp` | Provider/tool execution boundary, dry-run/no-send receipts, future owner-activated execution preflight. |
| `K9Audit` | Separate stronger evidence-chain ledger. It is not currently the default write path for CEO runtime decisions. |

## What is implemented

### Deterministic governance path

Y-star-gov keeps enforcement deterministic. The governance path does not rely on
an LLM to decide whether an action is allowed.

Key modules include:

- `ystar/kernel/engine.py`
- `ystar/kernel/dimensions.py`
- `ystar/governance/contract.py`
- `ystar/governance/intent_contract.py`
- `ystar/governance/hook_contract_adapter.py`
- `ystar/adapters/hook.py`

### CEO Cognitive OS governance

The CEO Cognitive OS modules validate CEO major actions before they can be
accepted by the runtime:

- `ystar/governance/ceo_cognitive_os_contract.py`
- `ystar/governance/ceo_cognitive_os_runtime_hook.py`
- `ystar/governance/ceo_cognitive_os_cieu_log.py`

Runtime decisions are:

| Decision | Runtime meaning |
| --- | --- |
| `ALLOW` | Continue to the approved next step only. It does not directly execute external work. |
| `REQUIRE_REVISION` | Return correct_path guidance to the CEO for repair. Missing or incomplete cognition should normally land here, not in human escalation. |
| `DENY` | Hard stop for bypass attempts, forbidden claims, unsafe boundaries, or unsupported CIEU/log claims. |
| `ESCALATE` | Generate an owner decision path when the packet is complete but needs human authority. It does not execute. |
| `STATUS_ONLY` | Non-major runtime status; no CEO Cognitive OS gate required. |

### Formal CIEUStore write path

The formal governance record path for CEO Cognitive OS runtime decisions is:

```text
ystar.governance.ceo_cognitive_os_cieu_log.validate_and_write_ceo_runtime_envelope(...)
-> ystar.governance.cieu_store.CIEUStore.write_dict(...)
```

This writes formal Y-star-gov CIEUStore records. It does not create a parallel
ledger. K9Audit remains a separate stronger evidence-chain system unless a
future owner-approved bridge is implemented.

### CIEUStore

The current CIEUStore is SQLite-backed and supports:

- formal record writes through `CIEUStore.write_dict`;
- session replay and statistics;
- evidence grading;
- session sealing;
- seal verification.

Relevant module:

- `ystar/governance/cieu_store.py`

## Current verified runtime chain

The current integrated internal chain is:

```text
bridge-labs CEO packet
-> Y-star-gov CEO Cognitive OS runtime hook
-> Y-star-gov CIEUStore formal record
-> bridge-labs route decision
-> gov-mcp dry-run boundary when provider/tool work is involved
-> bridge-labs post-action residual
-> Y-star-gov CIEUStore formal residual record
```

This proves L5-A internal runtime foundation. It does not prove L5-B CEO
intelligence completion, L5-C live execution, or L5-D revenue/customer/payment
completion.

## What this repository does not claim

Y-star-gov does not claim:

- to be the CEO behavior center;
- to execute provider/tool actions;
- to send messages, publish content, create accounts, or take payments;
- to prove customer validation or paid signal;
- to replace K9Audit;
- to complete the full L5 revenue/customer/payment loop.

## Targeted validation commands

Useful checks:

```bash
python3 -m py_compile ystar/governance/ceo_cognitive_os_runtime_hook.py
python3 -m py_compile ystar/governance/ceo_cognitive_os_cieu_log.py
pytest -q tests/governance/test_ceo_cognitive_os_runtime_hook.py
pytest -q tests/governance/test_ceo_cognitive_os_cieu_log.py
```

## Installation and local use

For package-level usage:

```bash
pip install ystar
```

For repository development, clone the repository and run targeted tests against
the governance modules you change.

## Next engineering direction

The next governance-facing work should support the bridge-labs CEO intelligence
compiler and future gov-mcp live-ready preflight without weakening the current
deterministic runtime semantics. Any future K9Audit mirror must be explicit,
owner-approved, and tested as a bridge rather than treated as an automatic
replacement for CIEUStore.
