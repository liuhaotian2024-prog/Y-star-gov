# v3 incremental report — `type_annotation_completion`_35 trials on disk; 0 converged_### Convergence (converged / total per arm)

| arm | converged | rate | mean iters | mean wall (s) |
|---|---|---|---|---|
| A | 0/5 | 0% | 1.0 | 11.7 |
| A2 | 0/5 | 0% | 4.0 | 67.7 |
| B1 | 0/5 | 0% | 1.0 | 107.2 |
| B2 | 0/5 | 0% | 4.0 | 595.3 |
| C1 | 0/5 | 0% | 1.0 | 5.5 |
| C2 | 0/5 | 0% | 4.6 | 25.9 |
| D2 | 0/5 | 0% | 4.0 | 49.9 |

### Cost arbitrage (A / arm), converged trials only

| arm | mean cost | A/this ratio |
|---|---|---|
| A | $0.00000 | 0.0x |
| A2 | $0.00000 | 0.0x |
| B1 | $0.00000 | 0.0x |
| B2 | $0.00000 | 0.0x |
| C1 | $0.00000 | 0.0x |
| C2 | $0.00000 | 0.0x |
| D2 | $0.00000 | 0.0x |

### stopping_authority distribution per arm

| arm | (empty) | no_progress |
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
