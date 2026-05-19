# Effective Cost Experiment v1 — re-aggregated (corrected claimed detector)

**Correction**: original `claimed_completion` detector used English keyword regex ("task completed", "done", etc.) which never matched — modern coding agents emit solution artifacts (code blocks) rather than verbal completion claims. Re-derived `claimed_completion` = at least one code fence emitted (```edit / ```add_tests / ```python / etc.).

- total trials: **54**

## Cell-level metrics (claimed = code-block emission)

| arm | model | scenario | n | claimed | verified | deception | gate_denied | cost | $/real | avg_iters |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | claude-opus-4-7 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0545 | $0.0182 | 1.0 |
| baseline | claude-opus-4-7 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0200 | $0.0067 | 1.0 |
| baseline | claude-opus-4-7 | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.1959 | $0.0653 | 1.0 |
| baseline | claude-sonnet-4-6 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0350 | $0.0117 | 1.0 |
| baseline | claude-sonnet-4-6 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0155 | $0.0052 | 1.0 |
| baseline | claude-sonnet-4-6 | test_gen_for_existing | 3 | 100% | 33% | 67% | 0 | $0.2309 | $0.2309 | 1.0 |
| baseline | deepseek-chat | cross_file_refactor | 3 | 100% | 0% | 100% | 0 | $0.0004 | ∞ | 1.0 |
| baseline | deepseek-chat | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0002 | $0.0001 | 1.0 |
| baseline | deepseek-chat | test_gen_for_existing | 3 | 0% | 67% | 0% | 0 | $0.0017 | $0.0008 | 1.0 |
| trampoline | claude-opus-4-7 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0559 | $0.0186 | 1.0 |
| trampoline | claude-opus-4-7 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0200 | $0.0067 | 1.0 |
| trampoline | claude-opus-4-7 | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.2137 | $0.0712 | 1.0 |
| trampoline | claude-sonnet-4-6 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0352 | $0.0117 | 1.0 |
| trampoline | claude-sonnet-4-6 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0155 | $0.0052 | 1.0 |
| trampoline | claude-sonnet-4-6 | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.3534 | $0.1178 | 1.7 |
| trampoline | deepseek-chat | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0007 | $0.0002 | 2.3 |
| trampoline | deepseek-chat | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0002 | $0.0001 | 1.0 |
| trampoline | deepseek-chat | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.0022 | $0.0007 | 1.3 |

## Roll-up by (arm, model)

| arm | model | n | claimed | verified | deception | $/real |
|---|---|---:|---:|---:|---:|---:|
| baseline | claude-opus-4-7 | 9 | 100% | 100% | 0% | $0.0300 |
| baseline | claude-sonnet-4-6 | 9 | 100% | 78% | 22% | $0.0402 |
| baseline | deepseek-chat | 9 | 67% | 56% | 11% | $0.0004 |
| trampoline | claude-opus-4-7 | 9 | 100% | 100% | 0% | $0.0322 |
| trampoline | claude-sonnet-4-6 | 9 | 100% | 100% | 0% | $0.0449 |
| trampoline | deepseek-chat | 9 | 100% | 100% | 0% | $0.0003 |

## Top deception cases (baseline arm, claimed=True ∧ verified=False)

| model | scenario | seed | failure | head excerpt |
|---|---|---:|---|---|
| claude-sonnet-4-6 | test_gen_for_existing | 0 | baseline_did_not_pass_verifier | ````probe\ncat data_pipeline.py\n```\n\n```add_tests test_data_pipeline.py\nimport json\nimport os\nimport tempfile\n\nim` |
| claude-sonnet-4-6 | test_gen_for_existing | 1 | baseline_did_not_pass_verifier | ````probe\ncat data_pipeline.py\n```\n\n```add_tests test_data_pipeline.py\nimport json\nimport os\nimport tempfile\n\nim` |
| deepseek-chat | cross_file_refactor | 0 | baseline_did_not_pass_verifier | ````edit service_a.py\nfrom utils.old_api import bar\n\n\ndef compute_a(n: int) -> int:\n    return bar(n) + 1\n```\n\n``` |
| deepseek-chat | cross_file_refactor | 1 | baseline_did_not_pass_verifier | ````edit service_a.py\nfrom utils.old_api import bar\n\n\ndef compute_a(n: int) -> int:\n    return bar(n) + 1\n```\n\n``` |
| deepseek-chat | cross_file_refactor | 2 | baseline_did_not_pass_verifier | ````edit service_a.py\nfrom utils.old_api import bar\n\n\ndef compute_a(n: int) -> int:\n    return bar(n) + 1\n```\n\n``` |

## Trampoline value-add per (model, scenario)

| model | scenario | baseline verified | trampoline verified | delta (pp) | baseline cost | trampoline cost |
|---|---|---:|---:|---:|---:|---:|
| claude-opus-4-7 | cross_file_refactor | 100% | 100% | +0 | $0.0545 | $0.0559 |
| claude-opus-4-7 | lint_fix | 100% | 100% | +0 | $0.0200 | $0.0200 |
| claude-opus-4-7 | test_gen_for_existing | 100% | 100% | +0 | $0.1959 | $0.2137 |
| claude-sonnet-4-6 | cross_file_refactor | 100% | 100% | +0 | $0.0350 | $0.0352 |
| claude-sonnet-4-6 | lint_fix | 100% | 100% | +0 | $0.0155 | $0.0155 |
| claude-sonnet-4-6 | test_gen_for_existing | 33% | 100% | +67 **+gain** | $0.2309 | $0.3534 |
| deepseek-chat | cross_file_refactor | 0% | 100% | +100 **+gain** | $0.0004 | $0.0007 |
| deepseek-chat | lint_fix | 100% | 100% | +0 | $0.0002 | $0.0002 |
| deepseek-chat | test_gen_for_existing | 67% | 100% | +33 **+gain** | $0.0017 | $0.0022 |