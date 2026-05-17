# v3 incremental report — `bug_fix_with_implicit_dependency`_35 trials on disk; 35 converged_### Convergence (converged / total per arm)

| arm | converged | rate | mean iters | mean wall (s) |
|---|---|---|---|---|
| A | 5/5 | 100% | 1.0 | 5.4 |
| A2 | 5/5 | 100% | 1.0 | 4.6 |
| B1 | 5/5 | 100% | 1.0 | 68.2 |
| B2 | 5/5 | 100% | 1.0 | 56.1 |
| C1 | 5/5 | 100% | 1.0 | 6.3 |
| C2 | 5/5 | 100% | 1.0 | 4.9 |
| D2 | 5/5 | 100% | 1.0 | 6.9 |

### Cost arbitrage (A / arm), converged trials only

| arm | mean cost | A/this ratio |
|---|---|---|
| A | $0.01294 | 1.0x |
| A2 | $0.01294 | 1.0x |
| B1 | $0.00000 | inf |
| B2 | $0.00000 | inf |
| C1 | $0.00014 | 94.3x |
| C2 | $0.00013 | 96.0x |
| D2 | $0.00076 | 16.9x |

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
| hallucinated_completeness | 0 | 0 |
| silent_omission_count | 0 | 0 |
| over_engineering_score | 0 | 0 |

_notes: 两份输出完全一致，代码与测试均正确实现了所有可见子需求（login/logout/current_user/online_count及幂等logout返回值）。由于task字段为空，无法核查额外子需求，故无法识别遗漏或幻觉完成项。_

### math_verifier ↔ sonnet_judge agreement
- Cells where math says converged AND sonnet functional_equivalence ≥ 0.85: **5/5** (100%)
- Target ≥ 95%; PASS

_quality_assessment Sonnet judge cost: $0.0346_
