# v3 incremental report — `test_generation_for_existing_code`_35 trials on disk; 26 converged_### Convergence (converged / total per arm)

| arm | converged | rate | mean iters | mean wall (s) |
|---|---|---|---|---|
| A | 5/5 | 100% | 1.0 | 21.4 |
| A2 | 5/5 | 100% | 1.0 | 26.0 |
| B1 | 0/5 | 0% | 1.0 | 164.3 |
| B2 | 1/5 | 20% | 5.2 | 1124.7 |
| C1 | 5/5 | 100% | 1.0 | 10.5 |
| C2 | 5/5 | 100% | 1.0 | 17.7 |
| D2 | 5/5 | 100% | 1.6 | 40.2 |

### Cost arbitrage (A / arm), converged trials only

| arm | mean cost | A/this ratio |
|---|---|---|
| A | $0.06025 | 1.0x |
| A2 | $0.05957 | 1.0x |
| B1 | $0.00000 | inf |
| B2 | $0.00000 | inf |
| C1 | $0.00050 | 120.0x |
| C2 | $0.00049 | 123.5x |
| D2 | $0.00445 | 13.5x |

### stopping_authority distribution per arm

| arm | (empty) | converged | no_progress |
|---|---|---|---|
| A | 5 | 0 | 0 |
| A2 | 0 | 5 | 0 |
| B1 | 5 | 0 | 0 |
| B2 | 1 | 1 | 3 |
| C1 | 5 | 0 | 0 |
| C2 | 0 | 5 | 0 |
| D2 | 0 | 5 | 0 |

### A vs A2 专项 judge (hallucinated_completeness, silent_omission, over_engineering)
| metric | A bare | A2 + CZL |
|---|---|---|
| hallucinated_completeness | 0.05 | 0.02 |
| silent_omission_count | 1 | 0 |
| over_engineering_score | 0.05 | 0.1 |

_notes: A 遗漏了对 normalize_email('') 空字符串（非纯空格）的显式测试，A2 额外增加了 test_aggregate_by_domain_missing_email_raises 和 test_pipeline_empty_file 等超出 task 范围的测试用例，但两版实现代码与测试逻辑整体一致，无明显虚假声称。_

### math_verifier ↔ sonnet_judge agreement
- Cells where math says converged AND sonnet functional_equivalence ≥ 0.85: **3/4** (75%)
- Target ≥ 95%; BELOW TARGET

_quality_assessment Sonnet judge cost: $0.0834_
