# Foundation API Reference

> Stable public API surface of the Y*gov Foundation layer (Layer 0).

---

## Contract

| Symbol | Module | Description |
|---|---|---|
| `IntentContract` | `ystar.kernel.dimensions` | 8-dimension constraint contract |
| `check()` | `ystar.kernel.engine` | Deterministic contract compliance check |
| `CheckResult` | `ystar.kernel.engine` | Result of a check() call |
| `Violation` | `ystar.kernel.engine` | Individual constraint violation detail |

## Audit

| Symbol | Module | Description |
|---|---|---|
| `CIEUStore` | `ystar.governance.cieu_store` | SQLite-backed CIEU persistent store |
| `CIEUStore.write_dict()` | `ystar.governance.cieu_store` | Write a CIEU record |
| `seal_session()` | `ystar.governance.cieu_store` | Seal a session with integrity hash |
| `verify_session_seal()` | `ystar.governance.cieu_store` | Verify session seal integrity |

## Omission

| Symbol | Module | Description |
|---|---|---|
| `OmissionEngine` | `ystar.governance.omission_engine` | Deterministic omission governance engine |
| `ObligationRecord` | `ystar.governance.omission_models` | Obligation lifecycle record |
| `scan()` | `ystar.governance.omission_engine` | Scan pending obligations for violations |

## Intervention

| Symbol | Module | Description |
|---|---|---|
| `InterventionEngine` | `ystar.governance.intervention_engine` | Active intervention engine |
| `gate_check()` | `ystar.governance.intervention_engine` | Pre-action obligation gate |

## Governance

| Symbol | Module | Description |
|---|---|---|
| `GovernanceLoop` | `ystar.governance.governance_loop` | Meta-learning governance bridge |
| `tighten()` | `ystar.governance.governance_loop` | Apply governance tightening |
| `GovernanceSuggestion` | `ystar.governance.governance_loop` | Governance improvement suggestion |

## Causal

| Symbol | Module | Description |
|---|---|---|
| `CausalEngine` | `ystar.governance.causal_engine` | Pearl Level 2 & 3 causal reasoning |
| `CausalGraph` | `ystar.governance.causal_engine` | Explicit causal DAG |
| `do_wire_query()` | `ystar.governance.causal_engine` | Level 2 intervention query |
| `counterfactual_query()` | `ystar.governance.causal_engine` | Level 3 counterfactual query |
| `discover_structure()` | `ystar.governance.causal_engine` | Causal structure discovery |

## Delegation

| Symbol | Module | Description |
|---|---|---|
| `DelegationChain` | `ystar.governance.governance_loop` | Delegation chain with monotonicity |
| `DelegationContract` | `ystar.governance.governance_loop` | Delegation contract definition |

---

## Stability Guarantee

These APIs are considered stable as of architecture freeze v1. Breaking changes require Chairman approval and a version bump.
