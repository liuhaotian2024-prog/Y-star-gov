# v3 incremental report — `test_generation_for_existing_code`_35 trials on disk; 33 converged_### Convergence (converged / total per arm)

| arm | converged | rate | mean iters | mean wall (s) |
|---|---|---|---|---|
| A | 5/5 | 100% | 1.0 | 21.7 |
| A2 | 5/5 | 100% | 1.0 | 23.1 |
| B1 | 5/5 | 100% | 1.0 | 165.1 |
| B2 | 5/5 | 100% | 1.0 | 166.5 |
| C1 | 3/5 | 60% | 1.0 | 13.6 |
| C2 | 5/5 | 100% | 1.8 | 28.5 |
| D2 | 5/5 | 100% | 1.0 | 28.8 |

### Cost arbitrage (A / arm), converged trials only

| arm | mean cost | A/this ratio |
|---|---|---|
| A | $0.06050 | 1.0x |
| A2 | $0.06398 | 0.9x |
| B1 | $0.00000 | inf |
| B2 | $0.00000 | inf |
| C1 | $0.00050 | 120.3x |
| C2 | $0.00107 | 56.4x |
| D2 | $0.00315 | 19.2x |

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
| hallucinated_completeness | 0.05 | 0.05 |
| silent_omission_count | 1 | 0 |
| over_engineering_score | 0.1 | 0.15 |

_notes: A的test_pipeline_end_to_end中断言result=={'x.com':1,'y.com':1}，但数据里A@x.com与a@x.com重复后只剩1条x.com记录，逻辑正确；A2的SCHEMA含name字段使测试数据更严格但也增加了不必要复杂度。两版实现代码完全一致，A2多了test_load_records_top_level_int和test_aggregate_by_domain_unknown计数为2的额外用例，覆盖更全面。_

### math_verifier ↔ sonnet_judge agreement
- Cells where math says converged AND sonnet functional_equivalence ≥ 0.85: **3/5** (60%)
- Target ≥ 95%; BELOW TARGET

_quality_assessment Sonnet judge cost: $0.1086_
