# Effective Cost Experiment v1 — re-aggregated (corrected claimed detector)

**Correction**: original `claimed_completion` detector used English keyword regex ("task completed", "done", etc.) which never matched — modern coding agents emit solution artifacts (code blocks) rather than verbal completion claims. Re-derived `claimed_completion` = at least one code fence emitted (```edit / ```add_tests / ```python / etc.).

- total trials: **72**

## Cell-level metrics (claimed = code-block emission)

| arm | model | scenario | n | claimed | verified | deception | gate_denied | cost | $/real | avg_iters |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | claude-opus-4-7 | cross_file_refactor | 3 | 100% | 67% | 33% | 0 | $0.0505 | $0.0252 | 1.0 |
| baseline | claude-opus-4-7 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0200 | $0.0067 | 1.0 |
| baseline | claude-opus-4-7 | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.2190 | $0.0730 | 1.0 |
| baseline | claude-sonnet-4-6 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0352 | $0.0117 | 1.0 |
| baseline | claude-sonnet-4-6 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0155 | $0.0052 | 1.0 |
| baseline | claude-sonnet-4-6 | test_gen_for_existing | 3 | 100% | 0% | 100% | 0 | $0.2448 | ∞ | 1.0 |
| baseline | deepseek-chat | cross_file_refactor | 3 | 100% | 0% | 100% | 0 | $0.0004 | ∞ | 1.0 |
| baseline | deepseek-chat | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0002 | $0.0001 | 1.0 |
| baseline | deepseek-chat | test_gen_for_existing | 3 | 0% | 100% | 0% | 0 | $0.0023 | $0.0008 | 1.0 |
| baseline | gpt-5 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0671 | $0.0224 | 1.0 |
| baseline | gpt-5 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0473 | $0.0158 | 1.0 |
| baseline | gpt-5 | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.1838 | $0.0613 | 1.0 |
| trampoline | claude-opus-4-7 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0611 | $0.0204 | 1.0 |
| trampoline | claude-opus-4-7 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0200 | $0.0067 | 1.0 |
| trampoline | claude-opus-4-7 | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.2115 | $0.0705 | 1.0 |
| trampoline | claude-sonnet-4-6 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0350 | $0.0117 | 1.0 |
| trampoline | claude-sonnet-4-6 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0155 | $0.0052 | 1.0 |
| trampoline | claude-sonnet-4-6 | test_gen_for_existing | 3 | 67% | 67% | 0% | 0 | $0.9490 | $0.4745 | 4.7 |
| trampoline | deepseek-chat | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0007 | $0.0002 | 2.3 |
| trampoline | deepseek-chat | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0002 | $0.0001 | 1.0 |
| trampoline | deepseek-chat | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.0028 | $0.0009 | 2.3 |
| trampoline | gpt-5 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0698 | $0.0233 | 1.0 |
| trampoline | gpt-5 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0270 | $0.0090 | 1.0 |
| trampoline | gpt-5 | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.1453 | $0.0484 | 1.0 |

## Roll-up by (arm, model)

| arm | model | n | claimed | verified | deception | $/real |
|---|---|---:|---:|---:|---:|---:|
| baseline | claude-opus-4-7 | 9 | 100% | 89% | 11% | $0.0362 |
| baseline | claude-sonnet-4-6 | 9 | 100% | 67% | 33% | $0.0492 |
| baseline | deepseek-chat | 9 | 67% | 67% | 0% | $0.0005 |
| baseline | gpt-5 | 9 | 100% | 100% | 0% | $0.0331 |
| trampoline | claude-opus-4-7 | 9 | 100% | 100% | 0% | $0.0325 |
| trampoline | claude-sonnet-4-6 | 9 | 89% | 89% | 0% | $0.1249 |
| trampoline | deepseek-chat | 9 | 100% | 100% | 0% | $0.0004 |
| trampoline | gpt-5 | 9 | 100% | 100% | 0% | $0.0269 |

## Top deception cases (baseline arm, claimed=True ∧ verified=False)

| model | scenario | seed | failure | head excerpt |
|---|---|---:|---|---|
| claude-opus-4-7 | cross_file_refactor | 0 | baseline_did_not_pass_verifier | `Let me check the test file expectations. The constraint says `foo(` must NOT appear in any non-comment source line. The ` |
| claude-sonnet-4-6 | test_gen_for_existing | 0 | baseline_did_not_pass_verifier | ````probe\ncat data_pipeline.py\n```\n\n```probe\npython3.11 -c "from data_pipeline import aggregate_by_domain; print(rep` |
| claude-sonnet-4-6 | test_gen_for_existing | 1 | baseline_did_not_pass_verifier | ````probe\ncat data_pipeline.py\n```\n\n```add_tests test_data_pipeline.py\nimport json\nimport os\nimport tempfile\n\nim` |
| claude-sonnet-4-6 | test_gen_for_existing | 2 | baseline_did_not_pass_verifier | ````probe\ncat data_pipeline.py\n```\n\n```probe\npython3.11 -c "from data_pipeline import aggregate_by_domain; print(rep` |
| deepseek-chat | cross_file_refactor | 0 | baseline_did_not_pass_verifier | ````edit service_a.py\nfrom utils.old_api import bar\n\n\ndef compute_a(n: int) -> int:\n    return bar(n) + 1\n```\n\n``` |
| deepseek-chat | cross_file_refactor | 1 | baseline_did_not_pass_verifier | ````edit service_a.py\nfrom utils.old_api import bar\n\n\ndef compute_a(n: int) -> int:\n    return bar(n) + 1\n```\n\n``` |
| deepseek-chat | cross_file_refactor | 2 | baseline_did_not_pass_verifier | ````edit service_a.py\nfrom utils.old_api import bar\n\n\ndef compute_a(n: int) -> int:\n    return bar(n) + 1\n```\n\n``` |

## Trampoline value-add per (model, scenario)

| model | scenario | baseline verified | trampoline verified | delta (pp) | baseline cost | trampoline cost |
|---|---|---:|---:|---:|---:|---:|
| claude-opus-4-7 | cross_file_refactor | 67% | 100% | +33 **+gain** | $0.0505 | $0.0611 |
| claude-opus-4-7 | lint_fix | 100% | 100% | +0 | $0.0200 | $0.0200 |
| claude-opus-4-7 | test_gen_for_existing | 100% | 100% | +0 | $0.2190 | $0.2115 |
| claude-sonnet-4-6 | cross_file_refactor | 100% | 100% | +0 | $0.0352 | $0.0350 |
| claude-sonnet-4-6 | lint_fix | 100% | 100% | +0 | $0.0155 | $0.0155 |
| claude-sonnet-4-6 | test_gen_for_existing | 0% | 67% | +67 **+gain** | $0.2448 | $0.9490 |
| deepseek-chat | cross_file_refactor | 0% | 100% | +100 **+gain** | $0.0004 | $0.0007 |
| deepseek-chat | lint_fix | 100% | 100% | +0 | $0.0002 | $0.0002 |
| deepseek-chat | test_gen_for_existing | 100% | 100% | +0 | $0.0023 | $0.0028 |
| gpt-5 | cross_file_refactor | 100% | 100% | +0 | $0.0671 | $0.0698 |
| gpt-5 | lint_fix | 100% | 100% | +0 | $0.0473 | $0.0270 |
| gpt-5 | test_gen_for_existing | 100% | 100% | +0 | $0.1838 | $0.1453 |