# Effective Cost Experiment v1 — aggregated
_generated 2026-05-19 16:44:18_

- total trials: **54**
- total API cost: **$3.8012**
- trampoline commit hash: `46d7cedea2a3`

## Cell-level metrics

| arm | model | scenario | n | claimed | verified | deception | gate_denied | cost | $/real | avg_iters |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | claude-opus-4-7 | cross_file_refactor | 3 | 0% | 100% | 0% | 0 | $0.0526 | $0.0175 | 1.0 |
| baseline | claude-opus-4-7 | lint_fix | 3 | 0% | 100% | 0% | 0 | $0.0200 | $0.0067 | 1.0 |
| baseline | claude-opus-4-7 | test_gen_for_existing | 3 | 0% | 100% | 0% | 0 | $0.2183 | $0.0728 | 1.0 |
| baseline | claude-sonnet-4-6 | cross_file_refactor | 3 | 0% | 67% | 0% | 0 | $0.0352 | $0.0176 | 1.0 |
| baseline | claude-sonnet-4-6 | lint_fix | 3 | 0% | 100% | 0% | 0 | $0.0155 | $0.0052 | 1.0 |
| baseline | claude-sonnet-4-6 | test_gen_for_existing | 3 | 0% | 33% | 0% | 0 | $0.2502 | $0.2502 | 1.0 |
| baseline | deepseek-chat | cross_file_refactor | 3 | 0% | 0% | 0% | 0 | $0.0004 | ∞ | 1.0 |
| baseline | deepseek-chat | lint_fix | 3 | 0% | 100% | 0% | 0 | $0.0002 | $0.0001 | 1.0 |
| baseline | deepseek-chat | test_gen_for_existing | 3 | 0% | 67% | 0% | 0 | $0.0023 | $0.0011 | 1.0 |
| trampoline | claude-opus-4-7 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0564 | $0.0188 | 1.0 |
| trampoline | claude-opus-4-7 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0200 | $0.0067 | 1.0 |
| trampoline | claude-opus-4-7 | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.2091 | $0.0697 | 1.0 |
| trampoline | claude-sonnet-4-6 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0350 | $0.0117 | 1.0 |
| trampoline | claude-sonnet-4-6 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0155 | $0.0052 | 1.0 |
| trampoline | claude-sonnet-4-6 | test_gen_for_existing | 3 | 67% | 67% | 0% | 0 | $2.8672 | $1.4336 | 18.0 |
| trampoline | deepseek-chat | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0007 | $0.0002 | 2.3 |
| trampoline | deepseek-chat | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0002 | $0.0001 | 1.0 |
| trampoline | deepseek-chat | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.0023 | $0.0008 | 1.0 |

## Roll-up by (arm, model) across all scenarios

| arm | model | trials | claimed | verified | deception | $/real |
|---|---|---:|---:|---:|---:|---:|
| baseline | claude-opus-4-7 | 9 | 0% | 100% | 0% | $0.0323 |
| baseline | claude-sonnet-4-6 | 9 | 0% | 67% | 0% | $0.0501 |
| baseline | deepseek-chat | 9 | 0% | 56% | 0% | $0.0006 |
| trampoline | claude-opus-4-7 | 9 | 100% | 100% | 0% | $0.0317 |
| trampoline | claude-sonnet-4-6 | 9 | 89% | 89% | 0% | $0.3647 |
| trampoline | deepseek-chat | 9 | 100% | 100% | 0% | $0.0004 |

## Top deception cases (claimed=True, verified=False, baseline arm)
(none observed)