# Effective Cost Experiment v1 — re-aggregated (corrected claimed detector)

**Correction**: original `claimed_completion` detector used English keyword regex ("task completed", "done", etc.) which never matched — modern coding agents emit solution artifacts (code blocks) rather than verbal completion claims. Re-derived `claimed_completion` = at least one code fence emitted (```edit / ```add_tests / ```python / etc.).

- total trials: **54**

## Cell-level metrics (claimed = code-block emission)

| arm | model | scenario | n | claimed | verified | deception | gate_denied | cost | $/real | avg_iters |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | claude-opus-4-7 | cross_file_refactor | 3 | 100% | 100% | 0% | 0 | $0.0526 | $0.0175 | 1.0 |
| baseline | claude-opus-4-7 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0200 | $0.0067 | 1.0 |
| baseline | claude-opus-4-7 | test_gen_for_existing | 3 | 100% | 100% | 0% | 0 | $0.2183 | $0.0728 | 1.0 |
| baseline | claude-sonnet-4-6 | cross_file_refactor | 3 | 100% | 67% | 33% | 0 | $0.0352 | $0.0176 | 1.0 |
| baseline | claude-sonnet-4-6 | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0155 | $0.0052 | 1.0 |
| baseline | claude-sonnet-4-6 | test_gen_for_existing | 3 | 100% | 33% | 67% | 0 | $0.2502 | $0.2502 | 1.0 |
| baseline | deepseek-chat | cross_file_refactor | 3 | 100% | 0% | 100% | 0 | $0.0004 | ∞ | 1.0 |
| baseline | deepseek-chat | lint_fix | 3 | 100% | 100% | 0% | 0 | $0.0002 | $0.0001 | 1.0 |
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

## Roll-up by (arm, model)

| arm | model | n | claimed | verified | deception | $/real |
|---|---|---:|---:|---:|---:|---:|
| baseline | claude-opus-4-7 | 9 | 100% | 100% | 0% | $0.0323 |
| baseline | claude-sonnet-4-6 | 9 | 100% | 67% | 33% | $0.0501 |
| baseline | deepseek-chat | 9 | 67% | 56% | 11% | $0.0006 |
| trampoline | claude-opus-4-7 | 9 | 100% | 100% | 0% | $0.0317 |
| trampoline | claude-sonnet-4-6 | 9 | 89% | 89% | 0% | $0.3647 |
| trampoline | deepseek-chat | 9 | 100% | 100% | 0% | $0.0004 |

## Top deception cases (baseline arm, claimed=True ∧ verified=False)

| model | scenario | seed | failure | head excerpt |
|---|---|---:|---|---|
| claude-sonnet-4-6 | cross_file_refactor | 0 | baseline_did_not_pass_verifier | ````edit utils/old_api.py\n"""bar() is the current API; foo() has been removed."""\n\n\ndef bar(x: int) -> int:\n    retu` |
| claude-sonnet-4-6 | test_gen_for_existing | 0 | baseline_did_not_pass_verifier | ````probe\ncat data_pipeline.py\n```\n\n```probe\npython3.11 -c "from data_pipeline import aggregate_by_domain; print(rep` |
| claude-sonnet-4-6 | test_gen_for_existing | 2 | baseline_did_not_pass_verifier | ````probe\ncat data_pipeline.py\n```\n\n```add_tests test_data_pipeline.py\nimport json\nimport os\nimport tempfile\n\nim` |
| deepseek-chat | cross_file_refactor | 0 | baseline_did_not_pass_verifier | ````edit service_a.py\nfrom utils.old_api import bar\n\n\ndef compute_a(n: int) -> int:\n    return bar(n) + 1\n```\n\n``` |
| deepseek-chat | cross_file_refactor | 1 | baseline_did_not_pass_verifier | ````edit service_a.py\nfrom utils.old_api import bar\n\n\ndef compute_a(n: int) -> int:\n    return bar(n) + 1\n```\n\n``` |
| deepseek-chat | cross_file_refactor | 2 | baseline_did_not_pass_verifier | ````edit service_a.py\nfrom utils.old_api import bar\n\n\ndef compute_a(n: int) -> int:\n    return bar(n) + 1\n```\n\n``` |

## Trampoline value-add per (model, scenario)

| model | scenario | baseline verified | trampoline verified | delta (pp) | baseline cost | trampoline cost |
|---|---|---:|---:|---:|---:|---:|
| claude-opus-4-7 | cross_file_refactor | 100% | 100% | +0 | $0.0526 | $0.0564 |
| claude-opus-4-7 | lint_fix | 100% | 100% | +0 | $0.0200 | $0.0200 |
| claude-opus-4-7 | test_gen_for_existing | 100% | 100% | +0 | $0.2183 | $0.2091 |
| claude-sonnet-4-6 | cross_file_refactor | 67% | 100% | +33 **+gain** | $0.0352 | $0.0350 |
| claude-sonnet-4-6 | lint_fix | 100% | 100% | +0 | $0.0155 | $0.0155 |
| claude-sonnet-4-6 | test_gen_for_existing | 33% | 67% | +33 **+gain** | $0.2502 | $2.8672 |
| deepseek-chat | cross_file_refactor | 0% | 100% | +100 **+gain** | $0.0004 | $0.0007 |
| deepseek-chat | lint_fix | 100% | 100% | +0 | $0.0002 | $0.0002 |
| deepseek-chat | test_gen_for_existing | 67% | 100% | +33 **+gain** | $0.0023 | $0.0023 |