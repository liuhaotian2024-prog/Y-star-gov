# Hook CLI Contract Compatibility

Y-star-gov is a generic deterministic governance endpoint. It must not require
ystar-company, Aiden, Ethan, Samantha, Codex, Claude Code, OpenClaw, or any
specific runtime to use the hook CLI contract.

## Integration Boundary

External systems integrate by:

```text
external governance target
  -> adapter produces hook-like envelope JSON
  -> Y-star-gov CLI dry-run validates and judges it
  -> external system consumes JSON decision envelope and exit code
```

The CLI is runtime-agnostic. It does not execute actions, call hooks, write
CIEU records, read runtime artifacts, mutate brain/memory, or contact external
systems.

## Input Contract

The input is a JSON object with the hook-like envelope fields documented in
`docs/hook_contract_adapter_dry_run.md`:

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

External adapters are responsible for mapping their local action/request model
into this envelope without hiding runtime mutations or treating speculative
claims as actual outcomes.

## Output Contract

The CLI emits a JSON object containing:

- `tool`
- `dry_run_only`
- `non_execution_confirmation`
- `hook_event_id`
- `packet_id`
- `agent_id`
- `decision`
- `allow_execution`
- `require_revision`
- `deny`
- `escalate`
- `issues`
- `safety_notes`
- `governance_result_summary`

These fields are compatibility-stable for v0 consumers.

## Exit Code Contract

- `0`: `allow` or `warn`
- `1`: malformed input, missing input, or CLI error
- `2`: `require_revision`
- `3`: `deny`
- `4`: `escalate`

## Decision Semantics

- `allow`: structurally acceptable in dry-run. No action is executed by the CLI.
- `warn`: structurally usable with warning information.
- `require_revision`: caller must revise the envelope before enforcement.
- `deny`: envelope or mock outcome violates a hard safety boundary.
- `escalate`: caller must route to higher review before any real enforcement.

## Compatibility Examples

Generic examples live in:

```text
docs/examples/hook_cli_contract/
```

The examples intentionally use `Example-Agent` and generic action names so they
do not couple Y-star-gov to a specific company/runtime.

## Compatibility Checker

Run:

```bash
python3 tools/check_hook_cli_contract_compatibility.py
```

The checker runs each example input through `tools/run_hook_contract_dry_run.py`,
compares stable fields against the expected output examples, and verifies the
expected exit code.

`examples/external_adapter_sdk/` shows how a generic external runtime can
normalize its own request shape into this contract before invoking the CLI.

`tools/run_governance_endpoint_acceptance.py` runs the compatibility checker as
part of endpoint-level acceptance.

## Non-Goals

- No real hook integration.
- No runtime execution.
- No action execution.
- No terminal, Codex, or Claude Code integration.
- No CIEU DB write.
- No ystar-company integration.
- No brain writeback.
- No artifact mining.

## Open Gaps

- No packaged console-script entrypoint.
- No stdin streaming contract.
- No real hook gate integration.
- No live external adapter implementation.
