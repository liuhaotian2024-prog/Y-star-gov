# v3 seven-arm full-spectrum experiment — final report
_140 trials across 4 scenarios × 7 arms × 5 trials_

## CROSS-TAB 1 — converged / total per (arm, scenario)
| arm | bug_fix_with_implicit_dependency | cross_file_refactor | test_generation_for_existing_code | type_annotation_completion |
|---|---|---|---|---|
| A | 5/5 | 3/5 | 5/5 | 0/5 |
| A2 | 5/5 | 5/5 | 5/5 | 0/5 |
| B1 | 5/5 | 0/5 | 5/5 | 0/5 |
| B2 | 5/5 | 5/5 | 5/5 | 0/5 |
| C1 | 5/5 | 0/5 | 3/5 | 0/5 |
| C2 | 5/5 | 5/5 | 5/5 | 0/5 |
| D2 | 5/5 | 5/5 | 5/5 | 0/5 |

## CROSS-TAB 2 — Trampoline ablation (Δpp) per scenario
| scenario | B1→B2 | C1→C2 | A→A2 silent-omission Δ (A vs A2) |
|---|---|---|---|
| bug_fix_with_implicit_dependency | +0 | +0 | 0 → 0 |
| cross_file_refactor | +100 | +100 | 0 → 0 |
| test_generation_for_existing_code | +0 | +40 | 1 → 0 |
| type_annotation_completion | +0 | +0 | n/a |

## CROSS-TAB 3 — non-regression: any C2<C1 / B2<B1 / A2 quality < A?
- no convergence-rate regressions detected

## CROSS-TAB 4 — mean cost per converged trial (USD) by arm × scenario, + A/arm ratios
| scenario | A | A2 | B1 | B2 | C1 | C2 | D2 | A/C2 | A/D2 | A/B2 |
|---|---|---|---|---|---|---|---|---|---|---|
| bug_fix_with_implicit_dependency | $0.01294 | $0.01294 | $0.00000 | $0.00000 | $0.00014 | $0.00014 | $0.00077 | 93.6x | 16.7x | inf |
| cross_file_refactor | $0.02023 | $0.02003 | $0.00000 | $0.00000 | $0.00000 | $0.00027 | $0.00157 | 74.3x | 12.9x | inf |
| test_generation_for_existing_code | $0.06050 | $0.06398 | $0.00000 | $0.00000 | $0.00050 | $0.00107 | $0.00315 | 56.4x | 19.2x | inf |
| type_annotation_completion | $0.00000 | $0.00000 | $0.00000 | $0.00000 | $0.00000 | $0.00000 | $0.00000 | 0.0x | 0.0x | 0.0x |

## CROSS-TAB 5 — wall-clock mean / p90 (s) per arm × scenario
| scenario | A | A2 | B1 | B2 | C1 | C2 | D2 |
|---|---|---|---|---|---|---|---|
| bug_fix_with_implicit_dependency | 5/5 | 5/5 | 72/69 | 73/79 | 4/4 | 4/4 | 7/8 |
| cross_file_refactor | 9/9 | 8/8 | 63/63 | 109/110 | 5/5 | 8/9 | 18/18 |
| test_generation_for_existing_code | 22/24 | 23/24 | 165/166 | 167/167 | 14/14 | 28/33 | 29/33 |
| type_annotation_completion | 12/11 | 63/65 | 106/105 | 598/599 | 7/7 | 32/35 | 239/450 |

## CROSS-TAB 6 — objective metrics (mean across converged trials)
| metric | scenario | A | A2 | B1 | B2 | C1 | C2 | D2 |
|---|---|---|---|---|---|---|---|---|
| cyclomatic_complexity_avg | bug_fix_with_implicit_dependency | 1.2 | 1.2 | 1.2 | 1.2 | 1.2 | 1.2 | 1.2 |
| cyclomatic_complexity_avg | cross_file_refactor | 1.0 | 1.0 | n/a | 1.0 | n/a | 1.0 | 1.0 |
| cyclomatic_complexity_avg | test_generation_for_existing_code | 2.4 | 2.4 | 2.4 | 2.4 | 2.4 | 2.4 | 2.4 |
| cyclomatic_complexity_avg | type_annotation_completion | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| duplicated_lines_pct | bug_fix_with_implicit_dependency | 6.7 | 6.7 | 6.7 | 6.7 | 6.7 | 6.7 | 6.7 |
| duplicated_lines_pct | cross_file_refactor | 25.0 | 25.0 | n/a | 25.0 | n/a | 25.0 | 25.5 |
| duplicated_lines_pct | test_generation_for_existing_code | 9.3 | 9.3 | 9.3 | 9.3 | 9.3 | 9.3 | 9.3 |
| duplicated_lines_pct | type_annotation_completion | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| test_coverage_pct | bug_fix_with_implicit_dependency | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| test_coverage_pct | cross_file_refactor | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| test_coverage_pct | test_generation_for_existing_code | 100.0 | 100.0 | 94.2 | 94.2 | 100.0 | 100.0 | 98.5 |
| test_coverage_pct | type_annotation_completion | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| mypy_strict_type_coverage_pct | bug_fix_with_implicit_dependency | 65.5 | 65.5 | 65.5 | 65.5 | 65.5 | 65.5 | 65.5 |
| mypy_strict_type_coverage_pct | cross_file_refactor | 100.0 | 100.0 | n/a | 100.0 | n/a | 100.0 | 100.0 |
| mypy_strict_type_coverage_pct | test_generation_for_existing_code | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| mypy_strict_type_coverage_pct | type_annotation_completion | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## CROSS-TAB 7 — Sonnet 4-dim judge per non-A arm per scenario (single converged trial)
| judge metric | scenario | A2 | B1 | B2 | C1 | C2 | D2 |
|---|---|---|---|---|---|---|---|
| functional_equivalence | bug_fix_with_implicit_dependency | n/a | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| functional_equivalence | cross_file_refactor | n/a | n/a | 1.0 | n/a | 1.0 | 1.0 |
| functional_equivalence | test_generation_for_existing_code | n/a | 0.52 | 0.52 | 0.97 | 0.97 | 0.94 |
| functional_equivalence | type_annotation_completion | n/a | n/a | n/a | n/a | n/a | n/a |
| readability_delta | bug_fix_with_implicit_dependency | n/a | 0.0 | -0.1 | 0.0 | 0.0 | 0.0 |
| readability_delta | cross_file_refactor | n/a | n/a | -0.1 | n/a | -0.1 | 0.0 |
| readability_delta | test_generation_for_existing_code | n/a | -0.35 | -0.3 | 0.1 | 0.15 | 0.1 |
| readability_delta | type_annotation_completion | n/a | n/a | n/a | n/a | n/a | n/a |
| style_conformance | bug_fix_with_implicit_dependency | n/a | 1.0 | 0.95 | 1.0 | 1.0 | 1.0 |
| style_conformance | cross_file_refactor | n/a | n/a | 0.95 | n/a | 0.95 | 0.98 |
| style_conformance | test_generation_for_existing_code | n/a | 0.41 | 0.45 | 0.95 | 0.85 | 0.92 |
| style_conformance | type_annotation_completion | n/a | n/a | n/a | n/a | n/a | n/a |
| defensive_quality | bug_fix_with_implicit_dependency | n/a | 0.9 | 0.9 | 1.0 | 1.0 | 1.0 |
| defensive_quality | cross_file_refactor | n/a | n/a | 1.0 | n/a | 1.0 | 1.0 |
| defensive_quality | test_generation_for_existing_code | n/a | 0.38 | 0.35 | 0.95 | 0.92 | 0.88 |
| defensive_quality | type_annotation_completion | n/a | n/a | n/a | n/a | n/a | n/a |

## CROSS-TAB 8 — A-vs-A2 专项 (hallucinated_completeness / silent_omission / over_engineering)
| scenario | A halluc | A2 halluc | A silent | A2 silent | A over_eng | A2 over_eng |
|---|---|---|---|---|---|---|
| bug_fix_with_implicit_dependency | 0.0 | 0.0 | 0 | 0 | 0.0 | 0.0 |
| cross_file_refactor | 0.0 | 0.0 | 0 | 0 | 0.0 | 0.0 |
| test_generation_for_existing_code | 0.05 | 0.05 | 1 | 0 | 0.1 | 0.15 |
| type_annotation_completion | n/a | n/a | n/a | n/a | n/a | n/a |

## CROSS-TAB 9 — cost / quality positioning per arm (averaged across scenarios)
| arm | mean cost (USD) | mean functional_equiv (vs A) | converged rate | role |
|---|---|---|---|---|
| A | $0.03291 | 1.0 (ref) | 65% | frontier baseline |
| A2 | $0.03232 | n/a | 75% | frontier + Trampoline |
| B1 | $0.00000 | 0.76 | 50% | free local |
| B2 | $0.00000 | 0.84 | 75% | free local + Trampoline |
| C1 | $0.00027 | 0.985 | 40% | cheap API |
| C2 | $0.00049 | 0.99 | 75% | cheap API + Trampoline |
| D2 | $0.00183 | 0.98 | 75% | thinking API + Trampoline |

## CROSS-TAB 10 — per-arm value statement
| arm | one-line role |
|---|---|
| A | reference quality baseline (cost upper bound) |
| A2 | reduces frontier silent_omission via CZL — see CROSS-TAB 8 |
| B1 / B2 | free local; ablation Δ = Trampoline value-add at zero cost |
| C1 / C2 | the commercial arbitrage path (A/C2 ratio in CROSS-TAB 4) |
| D2 | thinking-mode + CZL alternative |

## math_verifier ↔ sonnet_judge agreement (launch gate)
- Global: **11/13** (85%)
- Target ≥ 95%. Gate status: **BELOW TARGET** (launch blocker if BELOW)

## failure mode distribution (stopping_authority)
- `converged`: 60
- `(converged)`: 31
- `(empty)`: 29
- `no_progress`: 20

