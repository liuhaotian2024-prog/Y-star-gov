# Y*gov System Architecture

> For papers, investors, and new developers.

---

## What is Y*gov

Y*gov is a deterministic AI governance framework that translates human intent (written in natural language) into machine-verifiable behavioral contracts. It governs both its own self-improvement (Path A) and external AI agents (Path B) using the same architectural pattern, providing a formal answer to "who governs the governors?" Every governance action is auditable via the CIEU (Compliance, Integrity, Evidence, Utility) immutable log.

---

## The Five Layers

```
                    +---------------------------+
                    |   Intent Compilation (L1)  |
                    |  NL rules -> IntentContract |
                    +-------------+-------------+
                                  |
                                  v
+-------------------+   +-----------------+   +-------------------+
|   Path A (L2)     |   |  Foundation (L0) |   |   Path B (L3)     |
| Internal meta-gov |<--|  Contract engine |-->| External agent gov|
| Self-improvement   |   |  CIEU, Omission  |   | Constraint budget  |
+-------------------+   |  Causal, Interv. |   +--------+----------+
                         +-----------------+            |
                                  ^                     |
                                  |            +--------v----------+
                                  +------------|   Bridge (L4)      |
                                               | Path B -> GovLoop  |
                                               +-------------------+
```

### Call Direction Rules

| From | To | Allowed? |
|---|---|---|
| Intent Compilation | Foundation | Yes |
| Path A | Foundation | Yes |
| Path B | Foundation | Yes |
| Path B | Bridge -> GovernanceLoop | Yes (one-way) |
| Path A | Path B (direct) | **No** |
| Path B | Path A (direct) | **No** |
| Bridge | Path A (direct) | **No** |
| Intent Compilation | Path A/B execution | **No** |

---

## Layer Descriptions

### Layer 0: Foundation

The shared substrate that every other layer depends on. Contains the deterministic contract engine (`check()`), the CIEU immutable audit store, the omission governance engine (anti-passivity), the intervention engine, the causal reasoning engine (Pearl Levels 2-3), and the governance meta-learning loop. Foundation depends on nothing above it.

### Layer 1: Intent Compilation

Translates natural-language rules from AGENTS.md and other policy documents into structured IntentContract objects. Uses LLM-assisted translation with deterministic regex fallback. Also provides rule optimization suggestions from historical data. Produces contracts but never executes governance actions.

### Layer 2: Path A (Internal Meta-Governance)

Governs Y*gov's own module graph. Observes system health via GovernanceLoop suggestions, converts them into IntentContracts, wires modules through the ModuleGraph, and verifies results via causal reasoning. Single-track, fail-closed. Cannot expand its own permissions.

### Layer 3: Path B (External Governance)

Governs external AI agents using the same architectural pattern as Path A. Observes external agent behavior, derives constraints using a monotonic constraint budget, and enforces them via IntentContract checks. Failure mode: disconnect the external agent.

### Layer 4: Bridge

One-way data conduit from Path B back to GovernanceLoop. Aggregates Path B's CIEU records into three KPIs (constraint effectiveness, budget exhaustion, disconnect pressure) and injects them into GovernanceLoop. Has no decision-making authority -- GovernanceLoop decides independently.

---

## Key Invariants

1. **Determinism**: Same contract + same parameters = same check result. Always.
2. **Auditability**: Every governance action writes to the CIEU immutable log.
3. **Monotonicity**: Path A and Path B cannot expand their own permissions.
4. **Sibling isolation**: Path A and Path B cannot command each other directly.
5. **Fail-closed**: Unknown states default to deny, not allow.
