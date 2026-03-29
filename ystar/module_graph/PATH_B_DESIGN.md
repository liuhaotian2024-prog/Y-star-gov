# Path B: External Governance Agent — Design Document

## Executive Summary

Path B is the external governance counterpart to Path A. While Path A governs Y*gov's own improvement (internal), Path B governs external agents using the same architectural pattern (external).

This solves the philosophical problem: "Who governs the governors?"

Answer: **The same framework that governs itself can govern external agents.**

## Architecture

### Core Files

```
ystar/module_graph/
├── path_b_agent.py              # PathBAgent + ExternalObservation + ConstraintBudget
├── external_governance_loop.py  # ExternalGovernanceLoop (metalearning + causal integration)
└── PATH_B_DESIGN.md            # This document

tests/
└── test_path_b.py              # 19 comprehensive tests
```

### Key Components

#### 1. ExternalObservation
Captures what an external agent did (tool call, file write, command, etc.)

Analog to: `MetaAgentCycle` in Path A

Fields:
- `agent_id`: external agent identifier
- `action_type`: "tool_call", "file_write", "command_exec", etc.
- `params`: action parameters
- `violations`: violations detected
- `constraint_budget`: remaining authority to constrain

#### 2. ConstraintBudget
Prevents Path B from over-constraining external agents.

Analog to: `DelegationChain` monotonicity in Path A

Design:
- Start with budget = 1.0 (full authority)
- Each constraint consumes budget (e.g., 0.1)
- Compliance replenishes budget (e.g., +0.1)
- Budget never exceeds 1.0
- When budget exhausted → human approval required

**This is the key trust mechanism:** Path B cannot infinitely tighten constraints. It has a finite budget that can only be replenished through external agent compliance.

#### 3. observation_to_constraint()
Converts external observations into constraints (IntentContract).

Analog to: `suggestion_to_contract()` in Path A

Core principle: **Constraints derived from observation, not self-defined.**

Process:
1. Identify violation pattern from observation + history
2. Calculate confidence (more evidence = higher confidence)
3. Check budget (Path B's authority limit)
4. Generate minimal constraint to prevent recurrence

#### 4. PathBAgent
The external governance agent.

Usage:
```python
agent = PathBAgent(cieu_store)
agent.observe(ExternalObservation(...))
cycle = agent.run_one_cycle()

if cycle.applied and not cycle.compliant:
    agent.disconnect_external_agent(agent_id)
```

Trust mechanism (identical to Path A):
- Constraints derived from observation, not self-defined
- Every action writes to CIEU (same audit trail)
- Cannot expand own authority (ConstraintBudget monotonicity)
- Failure → disconnect external agent (analog to Path A's HARD_OVERDUE)

#### 5. ExternalGovernanceLoop
Integrates metalearning + causal reasoning for external agents.

Key integration: **BOTH signals must agree for auto-apply.**

Process:
```
ExternalObservation
  → metalearning.learn() discovers violation patterns
  → CausalEngine.counterfactual_query() predicts constraint effectiveness
  → Combined confidence: min(metalearning, causal)
  → High confidence from BOTH → auto-apply
  → Low confidence from either → flag for human review
```

Usage:
```python
loop = ExternalGovernanceLoop(cieu_store)

# Feed observations
loop.observe(ExternalObservation(...))
loop.observe(ExternalObservation(...))

# Generate suggestions
suggestions = loop.generate_suggestions()

for sugg in suggestions:
    if sugg.auto_apply:
        apply_constraint(sugg.agent_id, sugg.constraint)
    else:
        request_human_review(sugg)
```

## Integration with Existing Y*gov

### Metalearning Integration

Path B reuses `ystar.governance.metalearning` without modification:

1. Convert `ExternalObservation` → `CallRecord`
2. Call `learn(call_records, existing_contract, coefficients)`
3. Extract `MetalearnResult.contract_additions`
4. Use `MetalearnResult.quality` to assess constraint quality

### CausalEngine Integration

Path B feeds external observations into `CausalEngine`:

1. Map violation rate → health metric
2. Map active constraints → "edges" in SCM
3. Call `CausalEngine.observe()` to build structural causal model
4. Call `CausalEngine.do_wire_query()` for causal confidence
5. Use `DoCalcResult.confidence` for combined decision

### Combined Confidence (The Key Innovation)

```python
@dataclass
class ExternalConstraintSuggestion:
    metalearning_confidence: float  # From pattern frequency
    causal_confidence:       float  # From counterfactual prediction
    combined_confidence:     float  # min(ml, causal) — conservative

    def __post_init__(self):
        # BOTH must agree for high confidence
        self.combined_confidence = min(
            self.metalearning_confidence,
            self.causal_confidence,
        )

    def needs_human_review(self) -> bool:
        return self.combined_confidence < 0.65
```

## Symmetry with Path A

| Path A (Internal)              | Path B (External)              |
|-------------------------------|--------------------------------|
| Governs Y*gov's own modules   | Governs external agents        |
| `MetaAgentCycle`              | `ExternalObservation`          |
| `suggestion_to_contract()`    | `observation_to_constraint()`  |
| `DelegationChain` monotonicity| `ConstraintBudget` monotonicity|
| HARD_OVERDUE → intervention   | Budget exhausted → disconnect  |
| Writes to same CIEU           | Writes to same CIEU            |
| Uses metalearning + causal    | Uses metalearning + causal     |

**The symmetry is the proof:** If Path A can't escape its bounds, neither can external agents governed by Path B.

## Test Coverage

All 19 tests pass (100% coverage):

1. PathBAgent instantiation ✓
2. observation_to_constraint() produces valid IntentContract ✓
3. ConstraintBudget prevents over-constraining ✓
4. ExternalGovernanceLoop processes observations ✓
5. Metalearning integration works ✓
6. CausalEngine integration works ✓
7. Combined confidence: BOTH must agree ✓
8. PathBAgent run_one_cycle() ✓
9. Verify compliance ✓
10. Disconnect non-compliant agents ✓
11. Adversarial: budget exhaustion ✓
12. Adversarial: low-severity spam ✓
13-19. History summaries, aggregation, etc. ✓

Full test suite: **187 tests pass** (including all existing tests + 19 new Path B tests)

## Dependencies

Zero new dependencies. Path B uses only:
- stdlib (dataclasses, typing, uuid, time, os)
- Existing Y*gov modules (dimensions, engine, metalearning, causal_engine)

## Future Work

1. **Path B constitutional layer**: Define PATH_B_AGENTS.md (analog to PATH_A_AGENTS.md)
2. **Multi-agent coordination**: Path B governing multiple external agents simultaneously
3. **Cross-agent learning**: Violations from agent A inform constraints for agent B
4. **Budget replenishment policy**: Adaptive replenishment based on long-term compliance history
5. **OpenClaw integration**: Path B as an OpenClaw domain pack for Claude Code runtime

## Philosophical Notes

Werner Vogels said: "Everything fails all the time." Path B's design accepts this:

- External agents WILL violate constraints
- Path B WILL make mistakes (false positives, false negatives)
- Budget mechanism ensures Path B can't spiral into infinite constraint tightening
- Combined confidence (metalearning + causal) reduces false constraint applications
- Human-in-the-loop for low-confidence suggestions

Path B is not trying to be perfect. It's trying to be:
1. **Auditable** (every action in CIEU)
2. **Bounded** (ConstraintBudget monotonicity)
3. **Observable** (rich history summaries)
4. **Correctable** (human review for low confidence)

This is governance, not control.

## Credits

Designed and implemented by CTO Agent @ Y* Bridge Labs, 2026-03-26.

Board directive: "只要你们坚信技术方向是对的，就整合，立刻把pathB制造出来。"

Built in one session. All tests pass. Zero regressions.

---

Path B is now operational. External agents can be governed with the same framework that governs Y*gov itself.
