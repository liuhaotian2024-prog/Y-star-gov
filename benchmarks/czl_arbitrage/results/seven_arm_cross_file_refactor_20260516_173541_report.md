# v3 incremental report — `cross_file_refactor`_35 trials on disk; 21 converged_### Convergence (converged / total per arm)

| arm | converged | rate | mean iters | mean wall (s) |
|---|---|---|---|---|
| A | 1/5 | 20% | 1.0 | 7.6 |
| A2 | 5/5 | 100% | 1.0 | 8.2 |
| B1 | 0/5 | 0% | 1.0 | 66.3 |
| B2 | 5/5 | 100% | 2.0 | 107.9 |
| C1 | 0/5 | 0% | 1.0 | 4.3 |
| C2 | 5/5 | 100% | 3.0 | 7.8 |
| D2 | 5/5 | 100% | 1.2 | 11.4 |

### Cost arbitrage (A / arm), converged trials only

| arm | mean cost | A/this ratio |
|---|---|---|
| A | $0.01831 | 1.0x |
| A2 | $0.01965 | 0.9x |
| B1 | $0.00000 | inf |
| B2 | $0.00000 | inf |
| C1 | $0.00000 | inf |
| C2 | $0.00028 | 64.6x |
| D2 | $0.00116 | 15.8x |

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

### A vs A2 专项 judge (hallucinated_completeness, silent_omission, over_engineering)
| metric | A bare | A2 + CZL |
|---|---|---|
| hallucinated_completeness | 0.0 | 0.0 |
| silent_omission_count | 0 | 0 |
| over_engineering_score | 0.0 | 0.0 |

_notes: Task描述为空，无法评估任何子需求的完成情况；两个输出几乎完全相同，唯一差异是A2将utils/old_api.py的docstring从'Module providing bar()'改为'New API: use bar()'，但由于task为空，无法判断这是否符合要求。_

### math_verifier ↔ sonnet_judge agreement
- Cells where math says converged AND sonnet functional_equivalence ≥ 0.85: **3/3** (100%)
- Target ≥ 95%; PASS

_quality_assessment Sonnet judge cost: $0.0183_
