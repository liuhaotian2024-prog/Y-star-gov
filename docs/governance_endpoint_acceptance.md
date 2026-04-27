# Governance Endpoint Acceptance

`tools/run_governance_endpoint_acceptance.py` is the endpoint-level dry-run
acceptance command for the generic Y-star-gov governance interface.

Run from the repository root:

```bash
python3 tools/run_governance_endpoint_acceptance.py
```

## Acceptance Checks

The acceptance runner verifies:

1. External adapter SDK sample.
2. Hook CLI allow fixture smoke.
3. Hook adapter fixture matrix.
4. Hook CLI compatibility checker.
5. Combined targeted governance tests.
6. Local governance wrapper.

Expected success output includes:

```text
Result: PASS
Endpoint status: ACCEPTED
```

## Meaning Of Acceptance

Acceptance means the local deterministic endpoint contract is internally
consistent across the external adapter template, hook-like envelope
normalization, hook CLI, compatibility examples, fixture matrix, targeted tests,
and local wrapper.

Acceptance does not mean a real hook is integrated or any action has been
executed.

## JSON Report

For machine-readable output:

```bash
python3 tools/run_governance_endpoint_acceptance.py --json
```

## Non-Execution Guarantee

The acceptance pack uses only local deterministic fixtures/examples and does not
execute hooks, execute actions, write CIEU records, mutate brain/memory, read
runtime artifacts, or call external systems.

## Relationship To Existing Layers

- External adapter SDK proves generic request normalization.
- Hook CLI compatibility proves stable JSON/exit-code contract.
- Fixture matrix proves decision coverage.
- Local governance wrapper proves the validator/tool/test stack remains green.

## Open Gaps

- No real hook gate integration.
- No production external adapter.
- No CIEU DB write path.
- No brain writeback path.
- No runtime artifact mining.
