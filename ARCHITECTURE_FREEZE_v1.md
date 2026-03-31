# ARCHITECTURE FREEZE v1 — "One Foundation + Three Lines"

> Effective: 2026-03-29
> Status: **FROZEN** — all structural changes require Chairman approval

---

## Section 1: Five Layers

### Layer 0 — Foundation (54 modules)

The shared substrate. Every other layer depends on Foundation; Foundation depends on nothing above it.

| Package | Modules |
|---|---|
| `ystar/kernel/` | `engine.py`, `dimensions.py`, `history_scanner.py`, `retroactive.py` |
| `ystar/governance/` | `cieu_store.py`, `omission_models.py`, `omission_engine.py`, `omission_rules.py`, `omission_scanner.py`, `omission_store.py`, `omission_summary.py`, `governance_loop.py`, `metalearning.py`, `intervention_engine.py`, `intervention_models.py`, `adaptive.py`, `auto_configure.py`, `domain_context.py`, `experience_bridge.py`, `metrics.py`, `obligation_triggers.py`, `proposals.py`, `report_metrics.py`, `reporting.py`, `retro_store.py`, `causal_engine.py`, `ml/loop.py`, `ml/objectives.py`, `ml/records.py`, `ml/registry.py`, `ml_adaptive.py`, `ml_core.py`, `ml_discovery.py`, `ml_loop.py`, `ml_registry.py`, `ml_semantic.py` |
| `ystar/module_graph/` | `graph.py`, `planner.py`, `registry.py`, `discovery.py` |
| `ystar/adapters/` | `connector.py`, `hook.py`, `omission_adapter.py`, `report_delivery.py`, `claude_code_scanner.py` |
| `ystar/domains/` | `omission_domain_packs.py`, `finance/`, `healthcare/`, `crypto/`, `devops/`, `openclaw/`, `pharma/`, `ystar_dev/` |
| `ystar/integrations/` | `base.py`, `openclaw.py`, `runner.py`, `simulation.py` |
| `ystar/pretrain/` | `loader.py`, `synthesize_obligations.py` |
| `ystar/products/` | `omission_experiment.py`, `report_delivery.py`, `report_render.py` |
| `ystar/` (root) | `session.py`, `template.py`, `_cli.py`, `_hook_server.py`, `check_service.py`, `dev_cli.py` |

### Layer 1 — Intent Compilation (5 modules)

Translates natural-language user intent into Foundation-layer contracts.

| Module | Role |
|---|---|
| `ystar/kernel/nl_to_contract.py` | NL -> IntentContract translation |
| `ystar/kernel/prefill.py` | Contract prefill from context |
| `ystar/governance/constraints.py` | Constraint derivation |
| `ystar/governance/proposals.py` | Proposal generation |
| `ystar/governance/rule_advisor.py` | Rule suggestion |

### Layer 2 — Path A: Internal Meta-Governance (1 module + constitution)

Governs Y*gov's own module graph. Single-track, fail-closed.

| File | Role |
|---|---|
| `ystar/path_a/meta_agent.py` | PathAAgent — self-improvement agent |
| `ystar/path_a/PATH_A_AGENTS.md` | Path A constitution |

### Layer 3 — Path B: External Governance (2 modules + constitution)

Governs external agents using the same architectural pattern as Path A.

| File | Role |
|---|---|
| `ystar/path_b/path_b_agent.py` | PathBAgent — external governance agent |
| `ystar/path_b/external_governance_loop.py` | External observation loop |
| `ystar/path_b/PATH_B_AGENTS.md` | Path B constitution |
| `ystar/path_b/PATH_B_DESIGN.md` | Path B design document |

### Layer 4 — Bridge (1 module)

Connects Path B observations back into the GovernanceLoop without giving Path B direct command authority over Path A.

| File | Role |
|---|---|
| `ystar/governance/experience_bridge.py` | Path B -> GovernanceLoop bridge |

---

## Section 2: Call Direction Rules

```
Intent Compilation  -->  Foundation     : ALLOWED
Path A              -->  Foundation     : ALLOWED
Path B              -->  Foundation     : ALLOWED
Path B  -->  Bridge  -->  GovernanceLoop : ALLOWED

Path A  <-->  Path B  (direct)         : FORBIDDEN
Bridge  -->   Path A  (direct commands): FORBIDDEN
Intent Compilation  -->  direct execution : FORBIDDEN
```

### Rationale

- Path A and Path B are **siblings**, not parent-child. Neither may command the other.
- Bridge is a **data conduit**, not a command channel. It feeds observations into GovernanceLoop, which decides independently.
- Intent Compilation produces contracts; it never executes actions directly.

---

## Section 3: Module Attribution Table

| Module | Layer |
|---|---|
| `ystar/kernel/engine.py` | Foundation |
| `ystar/kernel/dimensions.py` | Foundation |
| `ystar/kernel/history_scanner.py` | Foundation |
| `ystar/kernel/retroactive.py` | Foundation |
| `ystar/kernel/nl_to_contract.py` | Intent Compilation |
| `ystar/kernel/prefill.py` | Intent Compilation |
| `ystar/governance/cieu_store.py` | Foundation |
| `ystar/governance/omission_models.py` | Foundation |
| `ystar/governance/omission_engine.py` | Foundation |
| `ystar/governance/omission_rules.py` | Foundation |
| `ystar/governance/omission_scanner.py` | Foundation |
| `ystar/governance/omission_store.py` | Foundation |
| `ystar/governance/omission_summary.py` | Foundation |
| `ystar/governance/governance_loop.py` | Foundation |
| `ystar/governance/metalearning.py` | Foundation |
| `ystar/governance/intervention_engine.py` | Foundation |
| `ystar/governance/intervention_models.py` | Foundation |
| `ystar/governance/adaptive.py` | Foundation |
| `ystar/governance/auto_configure.py` | Foundation |
| `ystar/governance/domain_context.py` | Foundation |
| `ystar/governance/experience_bridge.py` | Bridge |
| `ystar/governance/metrics.py` | Foundation |
| `ystar/governance/obligation_triggers.py` | Foundation |
| `ystar/governance/proposals.py` | Intent Compilation |
| `ystar/governance/report_metrics.py` | Foundation |
| `ystar/governance/reporting.py` | Foundation |
| `ystar/governance/retro_store.py` | Foundation |
| `ystar/governance/rule_advisor.py` | Intent Compilation |
| `ystar/governance/causal_engine.py` | Foundation |
| `ystar/governance/constraints.py` | Intent Compilation |
| `ystar/governance/ml/*.py` | Foundation |
| `ystar/governance/ml_*.py` | Foundation |
| `ystar/module_graph/graph.py` | Foundation |
| `ystar/module_graph/planner.py` | Foundation |
| `ystar/module_graph/registry.py` | Foundation |
| `ystar/module_graph/discovery.py` | Foundation |
| `ystar/adapters/*.py` | Foundation |
| `ystar/domains/**/*.py` | Foundation |
| `ystar/integrations/*.py` | Foundation |
| `ystar/pretrain/*.py` | Foundation |
| `ystar/products/*.py` | Foundation |
| `ystar/path_a/meta_agent.py` | Path A |
| `ystar/path_a/PATH_A_AGENTS.md` | Path A |
| `ystar/path_b/path_b_agent.py` | Path B |
| `ystar/path_b/external_governance_loop.py` | Path B |
| `ystar/path_b/PATH_B_AGENTS.md` | Path B |
| `ystar/path_b/PATH_B_DESIGN.md` | Path B |

---

## Constitution Amendment Protocol

- Amendments can only be proposed by: Board (human), Path A (via propose_amendment())
- Amendment format: diff of constitutional document + rationale + hash of new version
- Amendment must be written to CIEU with event_type 'constitution_amendment'
- Amendment does NOT take effect until Board confirms
- Path A and Path B cannot amend their own constitutions unilaterally

### Amendment Layer Neutrality

Constitution amendments do not belong to Path A or Path B. They are a root-level governance act requiring Board authority. Neither Path A nor Path B may initiate, approve, or execute amendments to their own constitutions without Board confirmation. The Intent Compilation line may assist in translating amendment proposals into structured diffs, but the decision authority rests with the Board.

---

## Section 4: Structure Gate Rules

1. **Every new module** must declare its layer in a docstring header before creation.
2. **Every new import** must respect the call direction rules in Section 2.
3. **No backward-compat shims** — old paths are deleted, not aliased.
4. **Layer violations** detected in CI block the merge.

### New Module Checklist

```
[ ] Layer declared in module docstring
[ ] Imports only from same layer or lower layers
[ ] No Path A <-> Path B cross-imports
[ ] No Bridge -> Path A direct commands
[ ] Added to Module Attribution Table above
[ ] Tests pass: python -m pytest tests/ -q
```

---

## Section 5: 100% Maintenance

> Added: 2026-03-29 (Framework Validation v1)

### Scenario Battery

The scenario battery (`tests/test_scenarios.py`) **must run on every release**.
It covers 8 integration scenarios that exercise the full governance framework
end-to-end. A failing scenario blocks the release.

```
python -m pytest tests/test_scenarios.py -v
```

### Architecture Drift Check

`tests/test_architecture.py` **must pass before any merge to main**.
It enforces:
- Path A does not import Path B (and vice versa)
- Bridge does not import PathAAgent
- GovernanceLoop does not import PathBAgent or ExternalGovernanceLoop
- Intent Compilation does not import Path A or Path B

```
python -m pytest tests/test_architecture.py -v
```

### New Module Admission

All new modules must follow the rules in `CONTRIBUTING_ARCHITECTURE.md`:
1. Declare layer in module docstring header
2. Import only from same layer or lower layers
3. No cross-imports between Path A and Path B
4. Added to Module Attribution Table (Section 3 above)
5. Full test suite passes after addition

### Board Approval for Structural Changes

The following changes require explicit Chairman/Board approval:
- Adding a new layer
- Changing call direction rules (Section 2)
- Modifying the DelegationChain structure
- Constitution amendments (PATH_A_AGENTS.md, PATH_B_AGENTS.md)
- Removing or merging existing modules listed in Section 3
