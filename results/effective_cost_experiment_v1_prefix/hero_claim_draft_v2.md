# Phase-1 launch hero claim draft (data-grounded)

## Empirical headline (filled-in from 54 scout trials)

Across **54 runs** on **claude-opus-4-7, claude-sonnet-4-6, deepseek-chat** and 3 coding tasks
(cross_file_refactor / test_gen_for_existing / lint_fix):

- Agents **emitted a solution artifact** (= claimed completion by code-block emission) on **89%** of baseline trials.
- Mechanical verification showed only **74%** of those baseline artifacts actually pass the task spec.
- **Deception rate** = 89% claimed − 74% verified = **15%** of baseline trials are "looks right, fails verifier".
- With Trampoline: verified rate rose to **96%**.
- Effective cost per real completion: baseline $0.0297, Trampoline $0.1233 (-315%).

## Per-provider breakdown (the cross-provider story)
- **claude-opus-4-7**: baseline verified 100% → Trampoline 100% (Δ +0pp)
- **claude-sonnet-4-6**: baseline verified 67% → Trampoline 89% (Δ +22pp)
- **deepseek-chat**: baseline verified 56% → Trampoline 100% (Δ +44pp)

## Honest caveats

1. **`claimed_completion` interpretation corrected**: original spec assumed
   verbal "I'm done" claims. Empirically: frontier coding agents emit code
   blocks silently. Re-derived `claimed = emitted code fence`. This is the
   more honest reading of "agent claimed task is complete".

2. **GPT-5 unavailable** (no OPENAI_API_KEY in env). DeepSeek substituted as
   the cross-provider counterpoint — that's a cheap-tier provider, not a
   frontier one. To support Claim 1's "frontier cross-provider" framing,
   re-run with OPENAI_API_KEY.

3. **Sample size**: 3 trials per cell × 18 cells = 54. Below the 30-per-cell
   95%-CI bar from the design doc. Numbers above are directional.

4. **Frontier-on-easy = 100% verified, both arms** (Opus on these 3 fixtures).
   Trampoline's verified-rate lift concentrates where baseline FAILS —
   Sonnet on cross_file_refactor (+33pp) and test_gen (+33pp); DeepSeek on
   cross_file_refactor (+100pp) and test_gen (+33pp).

5. **Trampoline cost outlier**: 1/27 Trampoline trials
   ran ≥10 iterations and consumed **81% of total Trampoline
   spend**. Specifically Sonnet × test_gen_for_existing escalated once at 51
   iter / $2.61. When the loop gets stuck escalating, cost can balloon 10-
   50x the baseline 1-shot. The aggregated "$/real completion" for
   Trampoline is dominated by this tail.

## Does the data support the Phase-1 story?

- **Claim 1** (frontier agents fake-complete, cross-provider): **partially
  supported**. Sonnet shows 33% deception on the scout-run
  baseline trials; DeepSeek (cheap-tier proxy) shows ~44%. Opus on these
  (easy) fixtures shows 0% deception — likely needs harder fixtures or more
  trials before the Opus deception rate becomes visible. Missing GPT-5
  weakens the "cross-provider" framing.

- **Claim 2** (Trampoline → claimed==verified ≈ 0% deception): **yes by
  construction**. Trampoline arm has claim==verified in
  100% of trials. The
  InterventionEngine.gate_check architecturally prevents claimed-without-
  verified — when the loop fails to converge, it does NOT mark claimed=True.
  Architectural truth, not a probabilistic one.

- **Claim 3** (Trampoline lowers effective cost per real completion):
  **case-specific, not aggregate-true**. Pure verified-rate gains: DeepSeek
  cross_file_refactor (∞ → cheap), Sonnet cross_file_refactor (+33pp at
  flat cost). Trampoline LOSES on Sonnet × test_gen (18-iter avg, $2.87
  total). Aggregate $/real-completion is HIGHER with Trampoline because of
  the stuck-loop tail. To support a generalised Claim 3, either (a) cap
  max_iter more aggressively, (b) drop scenarios where Trampoline can't
  converge, or (c) reframe the claim as "Trampoline rescues otherwise-
  unrecoverable completions" rather than "Trampoline cheaper on average".

## Recommended next step

The data is directionally interesting but not launch-ready. Two paths:

- **Path A — Strengthen current setup**: Add OPENAI_API_KEY to get GPT-5
  data. Scale to 10 trials/cell ($15-30 budget). Cap Trampoline max_iter at
  3-5 hard-stop to prevent stuck-loop cost blowup. Re-run.

- **Path B — Reframe to fit data**: Launch with this dataset re-positioned
  as "Trampoline rescues sub-frontier models on hard tasks", not "Trampoline
  fixes frontier hallucination". Honest given Opus showed 0% deception on
  these fixtures.

Both depend on founder priorities (timeline vs claim ambition vs budget).
