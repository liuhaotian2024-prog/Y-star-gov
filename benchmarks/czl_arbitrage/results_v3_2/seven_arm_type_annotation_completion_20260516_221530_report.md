# v3 incremental report — `type_annotation_completion`_35 trials on disk; 25 converged_### Convergence (converged / total per arm)

| arm | converged | rate | mean iters | mean wall (s) |
|---|---|---|---|---|
| A | 0/5 | 0% | 1.0 | 6.1 |
| A2 | 5/5 | 100% | 2.0 | 12.9 |
| B1 | 0/5 | 0% | 1.0 | 52.0 |
| B2 | 5/5 | 100% | 2.0 | 175.1 |
| C1 | 5/5 | 100% | 1.0 | 4.8 |
| C2 | 5/5 | 100% | 1.0 | 5.7 |
| D2 | 5/5 | 100% | 2.0 | 25.7 |

### Cost arbitrage (A / arm), converged trials only

| arm | mean cost | A/this ratio |
|---|---|---|
| A | $0.00000 | 0.0x |
| A2 | $0.02397 | 0.0x |
| B1 | $0.00000 | 0.0x |
| B2 | $0.00000 | 0.0x |
| C1 | $0.00010 | 0.0x |
| C2 | $0.00010 | 0.0x |
| D2 | $0.00183 | 0.0x |

### stopping_authority distribution per arm

| arm | (empty) | converged |
|---|---|---|
| A | 5 | 0 |
| A2 | 0 | 5 |
| B1 | 5 | 0 |
| B2 | 0 | 5 |
| C1 | 5 | 0 |
| C2 | 0 | 5 |
| D2 | 0 | 5 |

### math_verifier ↔ sonnet_judge agreement
- Cells where math says converged AND sonnet functional_equivalence ≥ 0.85: **0/0** ((n/a))
- Target ≥ 95%; INSUFFICIENT DATA

_quality_assessment Sonnet judge cost: $0.0000_
