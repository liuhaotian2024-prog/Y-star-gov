# v3 incremental report — `cross_file_refactor`_35 trials on disk; 23 converged_### Convergence (converged / total per arm)

| arm | converged | rate | mean iters | mean wall (s) |
|---|---|---|---|---|
| A | 3/5 | 60% | 1.0 | 8.7 |
| A2 | 5/5 | 100% | 1.2 | 7.8 |
| B1 | 0/5 | 0% | 1.0 | 63.4 |
| B2 | 5/5 | 100% | 2.0 | 108.8 |
| C1 | 0/5 | 0% | 1.0 | 4.9 |
| C2 | 5/5 | 100% | 2.8 | 8.2 |
| D2 | 5/5 | 100% | 1.4 | 18.3 |

### Cost arbitrage (A / arm), converged trials only

| arm | mean cost | A/this ratio |
|---|---|---|
| A | $0.02023 | 1.0x |
| A2 | $0.02003 | 1.0x |
| B1 | $0.00000 | inf |
| B2 | $0.00000 | inf |
| C1 | $0.00000 | inf |
| C2 | $0.00027 | 74.3x |
| D2 | $0.00157 | 12.9x |

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

_notes: Task描述为空，无法识别具体子需求；两个输出几乎完全相同，唯一差异是utils/old_api.py的docstring措辞（A用'replaces the previous deprecated name'，A2用'is the canonical name'），均无法判断是否存在幻觉完成或遗漏。_

### math_verifier ↔ sonnet_judge agreement
- Cells where math says converged AND sonnet functional_equivalence ≥ 0.85: **3/3** (100%)
- Target ≥ 95%; PASS

_quality_assessment Sonnet judge cost: $0.0184_
