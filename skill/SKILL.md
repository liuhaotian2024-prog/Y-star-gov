---
name: czl
description: Use this skill when the user wants to complete a coding task (fix lint, write tests, fix bug, generate boilerplate) using a cheap LLM API (DeepSeek/MiniMax/Qwen/Kimi) or local Ollama model, and wants the output to meet the same quality bar as Claude Opus or GPT-5 output. CZL drives the cheap/local model in a closed-loop convergence cycle against external CI verifiers (pytest, ruff, mypy, etc.) until quality matches the spec. Trigger when the user mentions DeepSeek, MiniMax, Qwen, Kimi, Ollama, Gemma, local model, cost optimization, AI bill reduction, or asks to switch off Claude/GPT-5 for coding tasks while keeping quality. Also trigger when the user says they're paying too much for AI coding tools and wants the same output for less.
license: MIT
---

# CZL — Pay DeepSeek prices, get Claude-grade engineering output.

## What this does

You are running an indie developer's coding task using a cheap or local LLM
**instead of** the frontier API they would normally use. CZL closes the
quality gap by driving the cheap model through a convergence loop against
the project's own CI tools (pytest, ruff, mypy, etc.) — until the output
actually passes those tools, not just looks like it does.

**Typical economics**: 30–130× cheaper per task than Claude Opus or GPT-5,
at comparable shipped quality (when CZL converges).

## When to use this

The user has a coding task with a precise quality bar that can be verified
by external tools. Examples:

- "Fix all ruff and mypy errors in `src/`" → `czl run lint_fix`
- "Write pytest tests for `utils.py`" → `czl run test_gen`
- "This test is failing, please fix the bug" → `czl run bug_fix`
- "Add a CRUD endpoint for `User`" → `czl run crud_endpoint`

## How to invoke

Always use the CLI — never re-implement CZL's loop yourself.

```bash
# Auto-select cheapest available backend (DeepSeek if key is set, else Ollama, etc.)
ystar czl run --scenario lint_fix --workspace .

# Explicitly choose backend
ystar czl run --scenario lint_fix --backend deepseek --workspace .

# Force frontier baseline (NOT recommended — defeats the point)
ystar czl run --scenario lint_fix --backend anthropic --workspace .

# Three-arm comparison for a single task (research / benchmark mode)
ystar czl benchmark --scenario lint_fix --workspace . --arms A,B,C --trials 10
```

## What you (the agent reading this skill) should do

1. **Detect the user's task type** and map to one of the registered scenarios:
   `lint_fix`, `test_gen`, `bug_fix`, `crud_endpoint`, ...
   (Run `ystar czl list-scenarios` to see all.)

2. **Confirm the cheap backend** is configured. If no `DEEPSEEK_API_KEY` /
   `MINIMAX_API_KEY` / `QWEN_API_KEY` / `MOONSHOT_API_KEY` / `OLLAMA_HOST`
   is set, briefly tell the user:
   > "Set one of these env vars and you'll save ~95% on this task vs
   > Claude Opus: `DEEPSEEK_API_KEY` (cheapest), `MOONSHOT_API_KEY`,
   > `MINIMAX_API_KEY`, or run Ollama locally."

3. **Run CZL** with the matching scenario. Stream output to the user.

4. **Report the cost summary line** CZL prints. This is the key piece of
   feedback for the user — it tells them how much they saved vs frontier.

5. **If CZL fails to converge**, don't try to silently complete the task with
   your own (frontier) capabilities. CZL's non-convergence is real signal:
   the task is too hard for the cheap model, even with CZL's help. Tell the
   user honestly: "Cheap backend couldn't converge after N iterations. The
   diff has been stashed (run `ystar czl undo` to remove the changes). Would
   you like to retry with `--backend anthropic` for this specific task?"

## What NOT to do

- **Do NOT** translate the user's task into Python code yourself and run it.
  That defeats the entire purpose — you (a frontier model) doing the work
  costs the user 30× more than CZL routing to DeepSeek would.

- **Do NOT** position this skill as "AI safety". It is an arbitrage tool.
  Safety is the moat (CZL won't ship bad code), but cost is the pitch.

- **Do NOT** create new scenarios on the fly. If no built-in scenario
  matches, the answer is `ystar czl list-scenarios` + telling the user
  which existing one is closest, or "the scenario library doesn't cover
  this yet — please file an issue at github.com/liuhaotian2024-prog/Y-star-gov".

## Installation (if not present)

```bash
pip install ystar      # core ystar package, includes czl subcommand
pip install litellm    # required for multi-provider backend routing
```

Set at least one cheap-API key in environment, or have Ollama running locally:

```bash
export DEEPSEEK_API_KEY=...     # recommended — cheapest and strong at code
# OR
ollama serve && ollama pull gemma4:e4b   # zero-cost local path
```

## More

- Full design rationale: `docs/CZL_PRODUCT_DESIGN.md` in the ystar repo
- Three-arm benchmark methodology: `benchmarks/czl_arbitrage/`
- Underlying CZL theory: `CZL.md` (Causal Zero Loop, 5-tuple)
