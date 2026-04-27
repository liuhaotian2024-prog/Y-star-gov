# Governance Contract Dry-Run Harness

`ystar/governance/contract_dry_run.py` connects the existing Pre-U packet
validator and CIEU prediction-delta validator into a deterministic local
simulation.

## Purpose

The harness demonstrates the intended governance loop without executing it:

```text
Pre-U packet
  -> validate_pre_u_packet
  -> dry-run outcome envelope
  -> prediction-delta record
  -> validate_prediction_delta
  -> dry-run report
```

## Public API

- `DryRunDecision`
- `DryRunIssue`
- `DryRunResult`
- `run_governance_contract_dry_run(packet, outcome=None)`

## Decision Hierarchy

- Pre-U `deny` or `require_revision` stops before delta construction and returns
  `require_revision`.
- Pre-U `escalate` remains `escalate` even if a dry-run delta is structurally
  valid.
- Delta `deny` returns `deny`.
- Delta `require_revision` returns `require_revision`.
- Delta `escalate` returns `escalate`.
- Warnings return `warn` unless deny/revision/escalation dominates.
- If both validators pass, the dry-run returns `pass`.

## Non-Execution Guarantee

The harness never executes `selected_U`, calls hooks, writes CIEU records, reads
DBs/logs/runtime artifacts, mutates memory/brain state, or contacts external
systems. Generated delta records are dry-run simulation artifacts only.

## Relationship To Validators

The Pre-U validator judges whether a labs-generated packet is structurally ready
for governance review. The prediction-delta validator judges whether a
post-action delta record is structurally safe for future evidence-backed
learning pathways. The dry-run harness connects them without expanding either
module into runtime behavior.

## Future Hook Relationship

A future hook integration may call these validators, but this harness is not the
hook. It is a local deterministic check for governance-contract shape only.

## Non-Goals

- No hook integration.
- No runtime execution.
- No action execution.
- No CIEU DB write.
- No ystar-company integration.
- No brain writeback.
- No artifact mining.

## Open Gaps

- No real hook envelope integration.
- No real CIEU event schema write path.
- No prediction-delta persistence.
- No semantic outcome truth verification.
- No curated brain writeback queue.
