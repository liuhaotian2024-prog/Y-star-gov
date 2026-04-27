# Governance Local Checks

`tools/run_governance_local_checks.py` is a safe local wrapper for the current
Y-star-gov governance validation stack.

It checks the L2.8 and L2.9 deterministic validator skeletons:

- governance validator imports from `ystar.governance`
- `py_compile` for `pre_u_packet_validator.py`
- `py_compile` for `cieu_prediction_delta.py`
- `py_compile` for `contract_dry_run.py`
- `py_compile` for `hook_contract_adapter.py`
- `py_compile` for `run_hook_adapter_fixture_matrix.py`
- `py_compile` for `run_hook_contract_dry_run.py`
- `py_compile` for `check_hook_cli_contract_compatibility.py`
- `py_compile` for the external adapter SDK normalizer and sample runner
- `py_compile` for the endpoint acceptance runner
- targeted Pre-U packet validator tests
- targeted CIEU prediction-delta validator tests
- targeted governance contract dry-run harness tests
- targeted hook contract adapter tests
- targeted hook adapter fixture tests
- targeted hook contract CLI tests
- targeted hook CLI contract compatibility tests
- hook adapter fixture matrix runner
- hook contract CLI smoke check with allow fixture
- hook CLI contract compatibility checker
- external adapter SDK sample smoke check
- targeted endpoint acceptance tests
- combined targeted governance tests for the validator, dry-run, and adapter
  modules

Run from the repository root:

```bash
python3 tools/run_governance_local_checks.py
```

Optional flags:

- `--verbose`: print command output for every check.
- `--continue-on-failure`: run all checks before reporting failures.

## Safety Boundary

This wrapper is not CI wiring, hook integration, runtime execution, packet
generation, CIEU writing, DB access, artifact mining, or ystar-company
integration.

It must not read DB/WAL/SHM contents, logs, active-agent markers, daemon state,
or raw runtime reports. It also must not execute hook, daemon, runtime, or agent
scripts.

The wrapper sets `PYTHONPYCACHEPREFIX=/tmp/ystar_gov_pycache` for subprocesses
so compile/import checks do not need repo-local bytecode writes.

## Relationship To L2.8 And L2.9

L2.8 added the deterministic Pre-U packet validator skeleton. L2.9 added the
CIEU prediction-delta schema validator. L2.11 adds a dry-run harness connecting
them without expanding their runtime scope.

L2.12 adds a hook contract dry-run adapter that models the future hook boundary
without calling a real hook or executing actions.

L2.13 adds a fixture pack and decision matrix runner for the hook adapter's five
expected outcomes: allow, warn, require revision, deny, and escalate.

L2.14 adds a CLI dry-run entrypoint that emits machine-readable JSON decision
envelopes and deterministic exit codes from hook-like envelope files.

L2.15 adds a runtime-agnostic CLI compatibility contract, generic example
inputs/outputs, and a compatibility checker for external integrators.

L2.16 adds a generic external adapter SDK/template showing how external systems
can normalize requests into hook-like envelopes without coupling Y-star-gov to a
runtime.

L2.17 adds the endpoint acceptance runner as the single command proving the
local deterministic endpoint stack remains accepted.
