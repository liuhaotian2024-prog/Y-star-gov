# Effective Cost Experiment v1 — aggregated
_generated 2026-05-19 23:56:48_

- total trials: **72**
- total API cost: **$2.1609**
- trampoline commit hash: `7311ffe0203e`

## Cell-level metrics

| arm | model | scenario | n | claimed | verified | deception | gate_denied | cost | $/real | avg_iters |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | claude-opus-4-7 | cross_file_refactor | 3 | 0% | 67% | 0% | 0 | $0.0547 | $0.0273 | 1.0 |
| baseline | claude-opus-4-7 | lint_fix | 3 | 0% | 100% | 0% | 0 | $0.0200 | $0.0067 | 1.0 |
| baseline | claude-opus-4-7 | test_gen_for_existing | 3 | 0% | 100% | 0% | 0 | $0.2042 | $0.0681 | 1.0 |
| baseline | claude-sonnet-4-6 | cross_file_refactor | 3 | 0% | 100% | 0% | 0 | $0.0352 | $0.0117 | 1.0 |
| baseline | claude-sonnet-4-6 | lint_fix | 3 | 0% | 100% | 0% | 0 | $0.0155 | $0.0052 | 1.0 |
| baseline | claude-sonnet-4-6 | test_gen_for_existing | 3 | 0% | 0% | 0% | 0 | $0.2390 | ∞ | 1.0 |
| baseline | deepseek-chat | cross_file_refactor | 3 | 0% | 0% | 0% | 0 | $0.0004 | ∞ | 1.0 |
| baseline | deepseek-chat | lint_fix | 3 | 0% | 100% | 0% | 0 | $0.0002 | $0.0001 | 1.0 |
| baseline | deepseek-chat | test_gen_for_existing | 3 | 0% | 100% | 0% | 0 | $0.0022 | $0.0007 | 1.0 |
| baseline | gpt-5 | cross_file_refactor | 3 | 0% | 100% | 0% | 0 | $0.0957 | $0.0319 | 1.0 |
| baseline | gpt-5 | lint_fix | 3 | 0% | 100% | 0% | 0 | $0.0385 | $0.0128 | 1.0 |
| baseline | gpt-5 | test_gen_for_existing | 3 | 0% | 100% | 0% | 0 | $0.1622 | $0.0541 | 1.0 |
| trampoline | claude-opus-4-7 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0573 | $0.0191 | 1.0 |
| trampoline | claude-opus-4-7 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0200 | $0.0067 | 1.0 |
| trampoline | claude-opus-4-7 | test_gen_for_existing | 3 | 67% | 67% | 0% | 0 | $0.3908 | $0.1954 | 2.0 |
| trampoline | claude-sonnet-4-6 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0420 | $0.0140 | 1.3 |
| trampoline | claude-sonnet-4-6 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0155 | $0.0052 | 1.0 |
| trampoline | claude-sonnet-4-6 | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.4264 | $0.1421 | 2.3 |
| trampoline | deepseek-chat | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0007 | $0.0002 | 2.3 |
| trampoline | deepseek-chat | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0002 | $0.0001 | 1.0 |
| trampoline | deepseek-chat | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.0024 | $0.0008 | 1.7 |
| trampoline | gpt-5 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0836 | $0.0279 | 1.3 |
| trampoline | gpt-5 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0674 | $0.0225 | 1.0 |
| trampoline | gpt-5 | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.1868 | $0.0623 | 1.0 |

## Roll-up by (arm, model) across all scenarios

| arm | model | trials | claimed | verified | deception | $/real |
|---|---|---:|---:|---:|---:|---:|
| baseline | claude-opus-4-7 | 9 | 0% | 89% | 0% | $0.0349 |
| baseline | claude-sonnet-4-6 | 9 | 0% | 67% | 0% | $0.0483 |
| baseline | deepseek-chat | 9 | 0% | 67% | 0% | $0.0005 |
| baseline | gpt-5 | 9 | 0% | 100% | 0% | $0.0329 |
| trampoline | claude-opus-4-7 | 9 | 89% | 89% | 0% | $0.0585 |
| trampoline | claude-sonnet-4-6 | 9 | 100% | 100% | 0% | $0.0538 |
| trampoline | deepseek-chat | 9 | 100% | 100% | 0% | $0.0004 |
| trampoline | gpt-5 | 9 | 100% | 100% | 0% | $0.0375 |

## Top deception cases (claimed=True, verified=False, baseline arm)
(none observed)