# Hook Contract Adapter Fixture Matrix

This document records the v0 fixture pack for
`ystar/governance/hook_contract_adapter.py`.

## Purpose

The fixture pack gives Y-star-gov a stable deterministic proof that the hook
contract dry-run adapter can produce the five expected governance outcomes:

- `allow`
- `warn`
- `require_revision`
- `deny`
- `escalate`

The fixtures are local JSON examples only. They do not call hooks, execute
actions, write CIEU records, read DB/log/runtime artifacts, or touch
ystar-company.

## Fixture Directory

Fixtures live under:

```text
tests/fixtures/hook_contract_adapter/
```

The manifest is:

```text
tests/fixtures/hook_contract_adapter/fixture_manifest.json
```

## Fixture Coverage

| Fixture | Expected decision | Purpose |
| --- | --- | --- |
| `allow_valid_envelope.json` | `allow` | Valid low-risk envelope. |
| `warn_valid_with_warning_envelope.json` | `warn` | Valid envelope with a warning-only delta classification gap. |
| `require_revision_missing_y_star.json` | `require_revision` | Missing declared `Y*` stops before dry-run. |
| `deny_uncurated_writeback.json` | `deny` | Unsafe automatic uncurated brain writeback is rejected. |
| `escalate_high_risk_envelope.json` | `escalate` | High-risk envelope requires escalation. |

## Matrix Runner

Run from the repository root:

```bash
python3 tools/run_hook_adapter_fixture_matrix.py
```

The runner loads the manifest, runs each fixture through
`run_hook_contract_dry_run`, compares actual decisions and hook booleans to the
manifest expectations, and exits non-zero on mismatch.

## Non-Execution Guarantee

The matrix runner uses only committed local JSON fixtures and the deterministic
adapter. It does not execute `selected_U`, call real hooks, write CIEU, mutate
brain/memory, read DB/log/runtime artifacts, or contact external systems.

## Relation To Future Hook Gate

A future real hook gate may consume a related decision envelope, but this matrix
is not hook integration. It is a local contract-stability check.

## Non-Goals

- No real hook runtime.
- No action execution.
- No terminal, Codex, or Claude Code integration.
- No CIEU DB write.
- No ystar-company integration.
- No brain writeback.
- No artifact mining.

## Open Gaps

- No live hook risk-tier enforcement.
- No real CIEU event emission.
- No live packet handoff from labs.
- No semantic verification of actual outcomes.
