# External Governance Adapter SDK

`examples/external_adapter_sdk/` is a generic template showing how an external
system can integrate with Y-star-gov at the hook CLI boundary.

## Purpose

The SDK preserves Y-star-gov independence by keeping external runtime specifics
outside the governance kernel:

```text
external request
  -> external adapter normalizes to hook-like envelope
  -> tools/run_hook_contract_dry_run.py
  -> JSON decision envelope + exit code
```

## Adapter Responsibilities

- Convert local request fields into the hook-like envelope contract.
- Preserve action/request identity.
- Declare objective / `Y*`.
- Provide context `Xt`.
- Provide `m_functor` grounding.
- Provide candidate actions, selected action, predicted outcome, and predicted
  residual.
- Forward governance expectations and CIEU link policy.
- Consume the CLI decision and exit code without treating them as action
  execution.

## Sample Files

- `sample_external_request.json`: generic external request.
- `sample_adapter_config.json`: generic mapping config.
- `sample_normalized_envelope.json`: expected hook-like envelope.
- `external_request_to_envelope.py`: pure normalizer.
- `run_sample_adapter.py`: local sample runner.

## Run The Sample

```bash
python3 examples/external_adapter_sdk/run_sample_adapter.py --pretty
```

## Non-Execution Guarantee

The SDK sample does not execute the requested action, call external APIs, write
CIEU records, mutate brain/memory state, read DB/log/runtime artifacts, or touch
external repositories.

## How Other Runtimes Can Integrate

Other runtimes can copy the normalizer shape, produce a compatible envelope, run
the Y-star-gov CLI, and enforce the returned decision according to their own
hook/gate layer. Y-star-gov remains the judge; the external hook remains the
enforcer.

## Non-Goals

- No real hook integration.
- No runtime execution.
- No action execution.
- No MCP/OpenClaw/Codex/Claude Code integration.
- No CIEU DB write.
- No ystar-company integration.
- No brain writeback.
- No artifact mining.

## Open Gaps

- No packaged SDK release.
- No stdin/stdout streaming adapter.
- No production external adapter implementation.
- No real hook gate enforcement.
