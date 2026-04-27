# Governance Local Checks

`tools/run_governance_local_checks.py` is a safe local wrapper for the current
Y-star-gov governance validation stack.

It checks the L2.8 and L2.9 deterministic validator skeletons:

- governance validator imports from `ystar.governance`
- `py_compile` for `pre_u_packet_validator.py`
- `py_compile` for `cieu_prediction_delta.py`
- `py_compile` for `contract_dry_run.py`
- targeted Pre-U packet validator tests
- targeted CIEU prediction-delta validator tests
- targeted governance contract dry-run harness tests
- combined targeted governance tests for the validator and dry-run modules

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
