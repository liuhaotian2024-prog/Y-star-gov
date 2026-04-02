# Y*gov Architecture Roles — Clarifying Core Component Relationships

## Purpose

This document clarifies the architectural roles of major Y*gov components to prevent misunderstandings about control flow and authority.

## Core Component Roles

### GovernanceLoop
**Role**: Feedback bridge / observation aggregator  
**NOT**: Total brain or central controller

GovernanceLoop aggregates feedback signals (observation results, drift metrics, violations) and makes them available to other components. It does not issue binding governance decisions.

Key characteristics:
- Collects and structures feedback data
- Provides observation APIs for other components
- Does NOT enforce policies directly
- Does NOT control Path A or runtime enforcement

### Path A (Self-Governance Agent)
**Role**: Independent self-governance agent with full sovereignty  
**NOT**: A sub-function of GovernanceLoop

Path A is an autonomous agent that:
- Makes its own governance decisions
- Has independent authority over self-governance actions
- May consult GovernanceLoop for observation data
- Is NOT subordinate to GovernanceLoop
- Operates in parallel with runtime enforcement, not as a subprocess

Key characteristics:
- Sovereign decision-making authority
- Can invoke CausalEngine for structural analysis
- Reports to CIEU but is not controlled by it
- Independent from GovernanceLoop's aggregation flow

### CausalEngine
**Role**: Advisory / structure support layer  
**NOT**: Binding decision authority

CausalEngine provides:
- Causal chain analysis
- Structural decomposition of actions
- Advisory input for Path A and other components
- Explanatory trace generation

Key characteristics:
- Non-binding: provides analysis, not verdicts
- Support tool for other decision makers
- Does NOT issue block/allow decisions
- Helps Path A reason about actions, does not decide for Path A

## Where Binding Decisions Come From

Runtime binding decisions (block/allow) come from the **deterministic governance path**:

```
hook.py (ingress)
  → orchestrator.py (routing)
    → check/enforce functions (policy evaluation)
      → domain adapters (domain-specific logic)
        → CIEU recording (audit trail)
```

This path is deterministic, synchronous, and produces binding results.

Path A, GovernanceLoop, and CausalEngine operate **alongside** this path:
- They provide feedback, analysis, and adaptive responses
- They do NOT override or replace the deterministic enforcement path
- They influence future policy updates, not current blocking decisions

## Summary Table

| Component        | Role                          | Authority Level  | Relation to Enforcement |
|------------------|-------------------------------|------------------|-------------------------|
| GovernanceLoop   | Feedback aggregator           | Advisory         | Observes, does not bind |
| Path A           | Self-governance agent         | Sovereign (self) | Independent parallel    |
| CausalEngine     | Structural analysis support   | Advisory         | Non-binding analysis    |
| check/enforce    | Runtime policy enforcement    | Binding          | Produces block/allow    |
| hook.py          | Runtime ingress controller    | Binding          | Entry point for all     |
| domain adapters  | Domain-specific logic         | Binding          | Implements checks       |

## Design Philosophy

Y*gov separates **binding enforcement** (deterministic, synchronous, auditable) from **adaptive feedback** (asynchronous, learning, advisory).

- Enforcement happens in the main runtime path
- Feedback/learning happens in parallel observation layers
- Path A is a peer to enforcement, not a subprocess
- GovernanceLoop aggregates but does not command

This separation ensures:
1. Predictable, auditable enforcement
2. Safe exploration in adaptive layers
3. Clear accountability for binding decisions
4. Sovereign agents remain sovereign

---

**Version**: 0.48.0  
**Last Updated**: 2026-04-01  
**Audience**: Developers, architects, governance engineers
