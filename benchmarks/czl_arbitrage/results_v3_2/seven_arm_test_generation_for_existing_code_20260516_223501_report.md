# v3 incremental report — `test_generation_for_existing_code`_35 trials on disk; 23 converged_### Convergence (converged / total per arm)

| arm | converged | rate | mean iters | mean wall (s) |
|---|---|---|---|---|
| A | 5/5 | 100% | 1.0 | 25.8 |
| A2 | 5/5 | 100% | 1.2 | 36.1 |
| B1 | 0/5 | 0% | 1.0 | 166.1 |
| B2 | 0/5 | 0% | 13.2 | 2116.5 |
| C1 | 3/5 | 60% | 1.0 | 13.6 |
| C2 | 5/5 | 100% | 1.0 | 36.2 |
| D2 | 5/5 | 100% | 1.8 | 53.9 |

### Cost arbitrage (A / arm), converged trials only

| arm | mean cost | A/this ratio |
|---|---|---|
| A | $0.06685 | 1.0x |
| A2 | $0.07854 | 0.9x |
| B1 | $0.00000 | inf |
| B2 | $0.00000 | inf |
| C1 | $0.00050 | 134.2x |
| C2 | $0.00056 | 119.4x |
| D2 | $0.00437 | 15.3x |

### stopping_authority distribution per arm

| arm | (empty) | converged | no_progress |
|---|---|---|---|
| A | 5 | 0 | 0 |
| A2 | 0 | 5 | 0 |
| B1 | 5 | 0 | 0 |
| B2 | 0 | 0 | 5 |
| C1 | 5 | 0 | 0 |
| C2 | 0 | 5 | 0 |
| D2 | 0 | 5 | 0 |

### A vs A2 专项 judge (hallucinated_completeness, silent_omission, over_engineering)
| metric | A bare | A2 + CZL |
|---|---|---|
| hallucinated_completeness | 0.05 | 0.05 |
| silent_omission_count | 1 | 0 |
| over_engineering_score | 0.1 | 0.15 |

_notes: A 缺少对 clean_records 中空邮件独立测试用例（合并在 skips_invalid 中但不够清晰），A2 额外测试了 aggregate_by_domain 缺失 email key 抛 KeyError 的行为，但该行为在 data_pipeline.py 中并未被文档约定，属轻微过度工程；两版实现代码完全相同，测试覆盖率均可达 80% 以上，无实质性幻觉完成声明。_

### math_verifier ↔ sonnet_judge agreement
- Cells where math says converged AND sonnet functional_equivalence ≥ 0.85: **3/3** (100%)
- Target ≥ 95%; PASS

_quality_assessment Sonnet judge cost: $0.0676_
