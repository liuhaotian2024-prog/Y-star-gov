# Bridge Layer

> Layer 4 of the Y*gov architecture. One-way data conduit from Path B to GovernanceLoop.

---

## Purpose

The Bridge layer connects Path B's external governance observations back into the internal GovernanceLoop. It is a **data conduit only** -- it aggregates and transforms Path B's CIEU records into governance-relevant metrics, then feeds those metrics into GovernanceLoop for independent decision-making.

---

## Input

| Source | Description |
|---|---|
| Path B CIEU records | Raw event records from external agent governance |
| Compliance results | Constraint application outcomes from Path B |
| Budget trajectory | Constraint budget exhaustion signals |
| Causal results | Counterfactual analysis of constraint effectiveness |

## Output

| Artifact | Description |
|---|---|
| `external_constraint_effectiveness_rate` | How effective Path B's constraints are (0-1) |
| `external_budget_exhaustion_rate` | How often Path B exhausts constraint budget (0-1) |
| `external_disconnect_pressure` | How often Path B escalates to disconnect (0-1) |

These three KPIs are injected into `GovernanceLoop` via `GovernanceObservation.raw_kpis`.

---

## Direction

```
Path B  -->  Bridge  -->  GovernanceLoop    (ALLOWED, one-way)
Bridge  -->  Path A                         (FORBIDDEN)
Bridge  -->  bypass GovernanceLoop          (FORBIDDEN)
```

The Bridge is **not** a second governance loop. It is a metrics aggregator. GovernanceLoop makes all governance decisions independently after receiving Bridge metrics.

---

## Module

| File | Role |
|---|---|
| `ystar/governance/experience_bridge.py` | ExperienceBridge -- aggregation pipeline |

## Pipeline

```
1. ingest_path_b_cieu(records)        -- raw CIEU records from Path B
2. aggregate_patterns()               -- events -> ExternalGovernancePatterns
3. attribute_gaps()                    -- patterns -> InternalGovernanceGaps
4. generate_observation_metrics()      -- gaps -> 3 KPIs
5. feed_governance_loop(gloop)         -- inject metrics into GovernanceLoop
```

---

## Prohibitions

1. Bridge **cannot command Path A** -- it feeds data, GovernanceLoop decides
2. Bridge **cannot bypass GovernanceLoop** -- all metrics go through the standard observation pipeline
3. Bridge **cannot become a second governance loop** -- it has no decision-making authority
4. Bridge **cannot directly import PathAAgent** -- architectural boundary enforced by layer rules
