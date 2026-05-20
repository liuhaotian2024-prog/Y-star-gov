# Phase-1 launch hero claim draft

## Template

"Across {N} runs on {models}: agents self-reported "completed" on {X}% of tasks. Mechanical verification showed only {Y}% actually passed. Trampoline brought that to {Z}% with {W}% lower effective cost per real completion."

## Filled-in

- N = **54** runs total
- models = claude-opus-4-7, claude-sonnet-4-6, deepseek-chat
- baseline claimed = **0%** of 27 baseline trials
- baseline verified = **81%**
- baseline deception rate = **0%**
- trampoline verified = **96%**
- baseline effective cost per real completion = $0.0262
- trampoline effective cost per real completion = $0.0842
- cost delta = **-222%** (negative = Trampoline cheaper)

## Honest caveats

- GPT-5 was UNAVAILABLE in this env (no OPENAI_API_KEY). DeepSeek substituted as the cross-provider counterpoint; that weakens Claim 1's 'frontier-only' scope. Adding OPENAI_API_KEY and re-running fixes this.
- scout-run sample: 27 baseline / 27 trampoline trials. Below the 30-per-cell statistical-CI bar from the design doc. Run more once results look directionally clean.