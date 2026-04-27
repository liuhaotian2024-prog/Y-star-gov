# Hook Contract Dry-Run Adapter

`ystar/governance/hook_contract_adapter.py` models the future hook boundary
without connecting to a real hook or runtime.

## Purpose

The adapter demonstrates this deterministic local flow:

```text
hook-like envelope
  -> normalize into Pre-U packet
  -> run_governance_contract_dry_run
  -> hook-like decision envelope
```

It lets Y-star-gov define the future hook contract shape while preserving the
boundary that hooks enforce but do not reason subjectively.

## Public API

- `HookAdapterDecision`
- `HookAdapterIssue`
- `HookAdapterResult`
- `run_hook_contract_dry_run(envelope)`

## Input Envelope Shape

The v0 adapter expects a mapping with:

- `hook_event_id`
- `agent_id`
- `packet_id`
- `risk_tier`
- `declared_Y_star`
- `Xt`
- `m_functor`
- `candidate_U`
- `selected_U_id`
- `why_min_residual`
- `governance_expectations`
- `cieu_link_policy`
- optional `mock_outcome`

The adapter maps these fields into the Pre-U packet aliases already accepted by
the Pre-U packet validator. It does not invent semantic content.

## Output Decision Envelope

The returned hook-like envelope includes:

- `hook_event_id`
- `packet_id`
- `agent_id`
- `decision`
- `allow_execution`
- `require_revision`
- `escalate`
- `deny`
- `dry_run_only`
- `non_execution_confirmation`
- `governance_result_summary`
- `issues`
- `safety_notes`

`allow_execution` is only a dry-run decision hint. No action is executed.

`docs/hook_contract_adapter_fixture_matrix.md` records the fixture pack that
locks the expected `allow`, `warn`, `require_revision`, `deny`, and `escalate`
decision behavior.

`docs/hook_contract_cli_dry_run.md` describes the local CLI entrypoint that
loads a hook-like envelope JSON file and emits a machine-readable decision
envelope.

## Decision Mapping

- dry-run `pass` -> hook adapter `allow`
- dry-run `warn` -> hook adapter `warn` with `allow_execution=true`
- dry-run `require_revision` -> hook adapter `require_revision`
- dry-run `deny` -> hook adapter `deny`
- dry-run `escalate` -> hook adapter `escalate`

## Non-Execution Guarantee

The adapter never calls a real hook, executes `selected_U`, writes CIEU records,
reads DB/log/runtime artifacts, mutates brain/memory state, or contacts external
systems.

## Relationship To Governance Contract Dry-Run

The adapter is a thin boundary shim. The governance contract dry-run remains the
component that connects Pre-U packet validation to prediction-delta validation.

## Relationship To Future Hook Gate

A future hook gate may use a related contract, but this adapter is not that
runtime hook. It is a local deterministic contract dry-run only.

## Non-Goals

- No real hook integration.
- No runtime execution.
- No terminal, Codex, or Claude Code integration.
- No action execution.
- No CIEU DB write.
- No ystar-company integration.
- No brain writeback.
- No artifact mining.

## Open Gaps

- No real hook envelope parser.
- No risk-tier enforcement in an actual hook.
- No CIEU event write path.
- No live packet handoff from ystar-company.
- No semantic validation of action outcomes.
