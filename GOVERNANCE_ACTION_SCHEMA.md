# Governance Action Schema

> Unified action format across all Y*gov governance operations.

---

## Unified Action Fields

Every governance action record contains these fields:

| Field | Type | Description |
|---|---|---|
| `actor` | str | Who performed the action (e.g. "path_a_agent", "path_b_agent", "governance_loop") |
| `target` | str | What was acted upon (module_id, agent_id, contract_name) |
| `scope` | str | Constraint scope (module:X, external:Y, external_domain:Z) |
| `decision` | str | "allow" / "deny" / "escalate" / "inconclusive" |
| `evidence_ref` | str | CIEU record ID or causal evidence reference |
| `contract_ref` | str | IntentContract.name that authorized this action |
| `constitution_ref` | str | Hash of the constitution document in effect |
| `followup_obligation` | str | Obligation ID created as a result of this action (if any) |
| `rollback_semantics` | str | What happens if this action needs to be undone |

---

## Action Types by Subsystem

### Intent Compilation
| Action | Actor | Description |
|---|---|---|
| `compile_contract` | nl_to_contract | Translate NL intent to IntentContract |
| `prefill_contract` | prefill | Auto-fill contract from context |
| `derive_constraint` | constraints | Derive constraint from proposals |
| `generate_proposal` | proposals | Generate governance proposal |
| `advise_rule` | rule_advisor | Suggest rule change |

### Engine (check/enforce)
| Action | Actor | Description |
|---|---|---|
| `check_params` | engine.check | Validate params against contract |
| `enforce_action` | engine.enforce | Enforce with mode (FAIL_CLOSED, etc.) |
| `legitimacy_check` | engine.check | Verify contract effective_status |

### Path A (Internal Meta-Governance)
| Action | Actor | Description |
|---|---|---|
| `wire_modules` | path_a_agent | Wire modules in ModuleGraph |
| `runtime_activation` | path_a_agent | Activate module via activate()/on_wired() |
| `partial_activation_warning` | path_a_agent | GRAPH_ONLY activation (no runtime effect) |
| `causal_plan_selection` | path_a_agent | Select plan based on do-calculus scores |
| `constitution_integrity_check` | path_a_agent | Verify constitution hash |
| `propose_amendment` | path_a_agent | Propose constitution change |
| `handoff_registration` | path_a_agent | Register in DelegationChain |
| `health_improved` | path_a_agent | Record health improvement |
| `obligation_fulfilled` | path_a_agent | Mark obligation as fulfilled |
| `inconclusive_threshold` | path_a_agent | 3+ inconclusive cycles |

### Path B (External Governance)
| Action | Actor | Description |
|---|---|---|
| `apply_constraint` | path_b_agent | Apply constraint to external agent |
| `verify_compliance` | path_b_agent | Check if external agent is complying |
| `downgrade_contract` | path_b_agent | Reduce external agent permissions |
| `freeze_session` | path_b_agent | Freeze external agent session |
| `disconnect_agent` | path_b_agent | Full disconnect of external agent |
| `require_human_review` | path_b_agent | Escalate to human review |

### Bridge
| Action | Actor | Description |
|---|---|---|
| `ingest_cieu` | experience_bridge | Ingest Path B CIEU records |
| `aggregate_patterns` | experience_bridge | Detect patterns in external data |
| `attribute_gaps` | experience_bridge | Infer internal governance gaps |
| `feed_governance_loop` | experience_bridge | Inject metrics into GovernanceLoop |

### Obligation / Omission
| Action | Actor | Description |
|---|---|---|
| `create_obligation` | omission_engine | Create obligation with deadline |
| `fulfill_obligation` | omission_engine | Mark obligation as fulfilled |
| `fail_obligation` | omission_engine | Mark obligation as failed |
| `hard_overdue` | omission_engine | Obligation exceeded deadline |
| `scan_violations` | omission_engine | Scan for missing obligations |

### Intervention
| Action | Actor | Description |
|---|---|---|
| `intervene` | intervention_engine | Block or modify an action |
| `escalate_to_human` | intervention_engine | Require human decision |
| `auto_deny` | intervention_engine | Automatic denial based on rules |

---

## Rollback Semantics

| Action Category | Rollback |
|---|---|
| `wire_modules` | Set edge.is_wired = False |
| `runtime_activation` | No automatic rollback (module may have side effects) |
| `apply_constraint` | Remove constraint from _active_constraints |
| `downgrade_contract` | Restore previous contract version |
| `freeze_session` | Unfreeze session |
| `disconnect_agent` | Cannot rollback (requires new onboarding) |
| `create_obligation` | Cancel obligation |
| `propose_amendment` | Withdraw proposal |
