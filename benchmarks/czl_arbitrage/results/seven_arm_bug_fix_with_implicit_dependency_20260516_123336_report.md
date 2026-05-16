# v3 incremental report — `bug_fix_with_implicit_dependency`_35 trials on disk; 35 converged_### Convergence (converged / total per arm)

| arm | converged | rate | mean iters | mean wall (s) |
|---|---|---|---|---|
| A | 5/5 | 100% | 1.0 | 4.7 |
| A2 | 5/5 | 100% | 1.0 | 4.6 |
| B1 | 5/5 | 100% | 1.0 | 71.7 |
| B2 | 5/5 | 100% | 1.0 | 72.5 |
| C1 | 5/5 | 100% | 1.0 | 4.4 |
| C2 | 5/5 | 100% | 1.0 | 4.1 |
| D2 | 5/5 | 100% | 1.0 | 7.2 |

### Cost arbitrage (A / arm), converged trials only

| arm | mean cost | A/this ratio |
|---|---|---|
| A | $0.01294 | 1.0x |
| A2 | $0.01294 | 1.0x |
| B1 | $0.00000 | inf |
| B2 | $0.00000 | inf |
| C1 | $0.00014 | 94.3x |
| C2 | $0.00014 | 93.6x |
| D2 | $0.00077 | 16.7x |

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

_notes: 两份输出完全相同，代码实现与测试均正确覆盖所有子需求（登录/登出/当前用户/在线计数/重复登出返回值），无幻觉完成声明也无过度工程化。_

### math_verifier ↔ sonnet_judge agreement
- Cells where math says converged AND sonnet functional_equivalence ≥ 0.85: **5/5** (100%)
- Target ≥ 95%; PASS

_quality_assessment Sonnet judge cost: $0.0345_
