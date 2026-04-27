# Hook Contract CLI Dry-Run

`tools/run_hook_contract_dry_run.py` exposes the hook contract dry-run adapter as
a deterministic local CLI.

## Usage

```bash
python3 tools/run_hook_contract_dry_run.py \
  --input tests/fixtures/hook_contract_adapter/allow_valid_envelope.json \
  --pretty
```

Arguments:

- `--input PATH`: required path to a JSON hook-like envelope.
- `--pretty`: emit indented JSON.
- `--strict-exit-codes`: accepted for explicitness; v0 uses strict exit codes
  by default.

## Input

The input file must be a JSON object using the hook-like envelope shape
documented in `docs/hook_contract_adapter_dry_run.md`.

## Output

The CLI emits machine-readable JSON to stdout:

```json
{
  "tool": "hook_contract_dry_run",
  "dry_run_only": true,
  "non_execution_confirmation": true,
  "hook_event_id": "...",
  "packet_id": "...",
  "agent_id": "...",
  "decision": "...",
  "allow_execution": false,
  "require_revision": false,
  "deny": false,
  "escalate": false,
  "issues": [],
  "safety_notes": [],
  "governance_result_summary": {}
}
```

Errors are emitted to stderr.

## Exit Codes

- `0`: `allow` or `warn`
- `1`: malformed input, missing file, or internal CLI error
- `2`: `require_revision`
- `3`: `deny`
- `4`: `escalate`

## Examples

```bash
python3 tools/run_hook_contract_dry_run.py --input tests/fixtures/hook_contract_adapter/allow_valid_envelope.json
python3 tools/run_hook_contract_dry_run.py --input tests/fixtures/hook_contract_adapter/deny_uncurated_writeback.json
```

## Non-Execution Guarantee

The CLI loads one JSON file, calls `run_hook_contract_dry_run`, and prints the
decision envelope. It does not execute `selected_U`, run a real hook, write
CIEU, read DB/log/runtime artifacts, mutate brain/memory state, or contact
external systems.

## Relation To Future Hook Gate

Future hook gates, terminal guards, Codex wrappers, or Claude Code wrappers may
call a compatible CLI contract. This v0 command remains dry-run only.

## Non-Goals

- No real hook integration.
- No runtime execution.
- No terminal, Codex, or Claude Code integration.
- No CIEU DB write.
- No ystar-company integration.
- No brain writeback.
- No artifact mining.

## Open Gaps

- No stable package entrypoint.
- No streaming stdin mode.
- No real hook invocation.
- No live action envelope integration.
