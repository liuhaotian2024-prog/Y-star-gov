# External Governance Adapter SDK v0

This directory is a generic template for connecting an external system to the
Y-star-gov hook CLI contract.

It demonstrates:

- transforming an external action request into a hook-like envelope
- invoking `tools/run_hook_contract_dry_run.py`
- consuming the CLI JSON decision envelope and exit code
- preserving non-execution, no-CIEU-write, and no-brain-writeback boundaries

This is not a real runtime adapter. It does not execute actions, call external
APIs, write CIEU records, mutate memory/brain state, or read runtime artifacts.

Run the sample:

```bash
python3 examples/external_adapter_sdk/run_sample_adapter.py
```
