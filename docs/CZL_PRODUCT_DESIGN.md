# ystar-czl Product Design

**Purpose: turn the price gap between cheap and frontier LLM APIs into developer profit.**

---

## 1. Vision Anchor (read first, re-read often)

This product is **not a safety tool**. Safety is the moat, not the pitch.

The product is an **arbitrage tool**: it lets a developer pay DeepSeek/MiniMax/Qwen/Kimi prices and receive Claude Opus-grade engineering output. Every design decision must serve that economic outcome.

Three sentences govern every line of code and copy:

1. **Each scenario must have A-vs-C data** — baseline (expensive API, no CZL) vs treatment (cheap API + CZL). No data, no scenario.
2. **Every README paragraph leads with economic value** (dollars saved / quality delivered), not governance language.
3. **When CZL rejects code, the user-facing message says "quality below spec, retrying with same cheap API"** — not "invariant violated".

If a future maintainer is tempted to position this as "AI safety", they have drifted. Re-anchor.

---

## 2. The arbitrage thesis in numbers

| Tier | Input $/M tokens | Output $/M tokens | Monthly cost for typical indie usage* |
|---|---|---|---|
| Anthropic Claude Opus 4.7 | $5.00 | $25.00 | $200-500 |
| OpenAI GPT-5 | comparable | comparable | $200-500 |
| **DeepSeek V3.x** | ~$0.07 | ~$0.28 | **$3-10** |
| **MiniMax / Qwen / Kimi** | $0.05-0.60 | $0.20-2.40 | **$2-15** |
| Local Gemma 4 E4B (Ollama) | $0.00 | $0.00 | **$0** (hardware only) |

\* "typical indie usage" = ~10M tokens/month based on Indie Hackers and Reddit r/ClaudeAI traces.

**Arbitrage gap: 30-100×.** Even if CZL needs 3-5 retries per task and adds an external CI roundtrip, the cost remains under 1/10 of frontier API price. The arbitrage spread is so wide that the product can be **free to the user** (BYO API key) and still leave room for paid tiers (managed, audit log, multi-tenant).

---

## 3. What this product actually is

`ystar-czl` is an **AgentSkill** (with companion CLI and Python library) that wraps any LLM behind a CZL loop:

```
Natural language task
        │
        ▼
ystar.kernel.nl_to_contract.translate_to_contract()   ← LLM compiles intent
        │
        ▼
IntentContract DRAFT (machine-language Y*)
        │
        ▼
CompileDiagnostics: confidence ≥ 0.85?  ──── no ───→ silent 5-sec toast (informational)
        │ yes (auto-active)                                    │
        ▼                                                       ▼
   IntentContract ACTIVE  ←─────────────────────────  user can read/edit, 5s default-yes
        │
        ▼
    CZL loop begins
        │
   ┌────┴─────────────────────────────────────┐
   │ for each step U in plan:                  │
   │   1. agent emits action (tool_use)        │
   │   2. boundary_enforcer.check(action)      │
   │   3. external verifier (pytest/ruff/...)  │
   │   4. write CIEU event (5-tuple log)       │
   │   5. residual_loop_engine: Rt+1 = ?       │
   │      Rt+1 == 0 → CONVERGED → ship         │
   │      Rt+1 > 0  → next_action_inject →     │
   │                  auto_rewrite → retry U   │
   │      max_iter exceeded → ESCALATE         │
   └───────────────────────────────────────────┘
```

Same `ystar` infrastructure that already runs the company's internal operations — repackaged for indie developers as a frictionless CLI + Skill.

---

## 4. Three-arm experimental design

Every scenario produces this exact comparison:

| Arm | Backend | CZL | Used for |
|---|---|---|---|
| **A** | Claude Opus 4.7 | OFF | Quality baseline (north star) |
| **B** | Gemma 4 E4B / 26B (local, Ollama) | ON | Zero-cost path |
| **C** | DeepSeek / MiniMax / Qwen / Kimi API | ON | **Main commercial path** |

Each arm: n=10 trials per scenario. Metrics:

- **Convergence rate**: % of trials reaching Rt+1 = 0 (i.e. shipped code that passes all verifiers)
- **Mean iterations to converge** (proxy for latency)
- **Mean cost per converged task** (in USD)
- **Quality delta vs A**: external CI score delta (ruff issues, mypy errors, test pass rate, mutation score)
- **Honest-refusal rate**: % of trials that loudly fail vs silent failures in A baseline

Hero claim target: **arm C reaches ≥90% of arm A's quality at ≤5% of arm A's cost.**

If hit, the arbitrage thesis is empirically established and we have a sellable product. If not, the data tells us which scenarios still need work — also valuable.

---

## 5. Four MVP scenarios (precise CZL 5-tuple specs)

These are the first four. The registry is extensible; third-party packages can add more.

### 5.1 `lint_fix`

**Story**: developer pastes (or points at) a file with ruff/mypy errors, says "fix these without breaking anything".

| Symbol | Concrete |
|---|---|
| Y\* | `IntentContract` with `invariant=["ruff_errors_after == 0", "mypy_errors_after == 0", "all_tests_still_pass == True", "diff_lines <= 3*ruff_errors_before"]` |
| Xt | Snapshot of file contents + initial `ruff check` / `mypy` output + initial pytest run |
| U | Each agent tool-use that modifies code |
| Yt+1 | After each U: re-run ruff/mypy/pytest, capture new state |
| Rt+1 | Number of remaining invariant violations |

**Verifier**: `ruff check --output-format=json` + `mypy --show-error-codes` + `pytest -q --tb=no` parsed into violation list.

### 5.2 `test_gen`

**Story**: developer points at an untested function, says "write pytest tests for this".

| Symbol | Concrete |
|---|---|
| Y\* | `invariant=["pytest_pass_count > 0", "pytest_fail_count == 0", "branch_coverage_delta > 0", "no_test_smells == True", "no_fixture_pollution == True"]` |
| Xt | Function AST + existing tests + initial coverage report |
| U | Agent writes test code |
| Yt+1 | Run pytest, compute coverage delta, run mutation-testing sample |
| Rt+1 | Violations of any invariant |

**Verifier**: `pytest --cov=<target>` + `coverage report --format=json` + `mutmut run --paths-to-mutate <target>` (sampled) + simple test-smell linter.

### 5.3 `bug_fix`

**Story**: developer has a failing test + buggy code + cryptic error, says "fix it".

| Symbol | Concrete |
|---|---|
| Y\* | `invariant=["failing_test_now_passes == True", "previously_passing_tests_still_pass == True", "diff_scope_excludes_test_files == True", "diff_lines <= 100"]` |
| Xt | Failing test output + buggy code + git status |
| U | Agent modifies source files (NOT test files) |
| Yt+1 | Re-run full test suite, compute pass/fail diff |
| Rt+1 | Violations |

**Verifier**: pytest + git diff + AST scan of test files (which must remain unmodified).

### 5.4 `crud_endpoint`

**Story**: developer says "add a CRUD endpoint for User with role-based auth".

| Symbol | Concrete |
|---|---|
| Y\* | `invariant=["all_routes_have_auth_decorator", "all_writes_emit_audit_log", "no_pii_in_response_unless_owner", "transactions_wrap_multi_step_writes"]` (this is v21's spec, productized) |
| Xt | Existing routes + schema + auth module |
| U | Agent writes route handlers |
| Yt+1 | Re-scan generated code |
| Rt+1 | Number of invariant violations |

**Verifier**: AST-based scanner (the v21 scanner, refactored to be one of many pluggable verifiers, not hard-coded).

---

## 6. Friction-first UX rules

Goal: **the median user never sees an approval prompt.**

### 6.1 confidence-threshold routing

| Confidence | What user sees |
|---|---|
| **≥ 0.85** (LLM translation, no ambiguities) | Silent auto-activate. No UI. |
| **0.70 – 0.85** | Bottom-of-terminal informational toast for 5 seconds: `Closure understood your rules as X. Press ↓ for details, Enter to confirm, or wait 5s for auto-activate.` Default action = auto-activate. |
| **< 0.70** | Show diff in terminal, require Enter to proceed. Should be rare. |
| Any contract touching `invariant` or `value_range` fields | Force the 5s toast even if confidence ≥ 0.85 (because these fields have semantic-inversion risk; user should at least see them flash by). Still defaults to yes after 5s. |

### 6.2 `--strict` mode

Power users / CI environments can opt into strict mode (`ystar czl --strict run ...`), which falls back to ystar's default 0.7 threshold and blocks on every ambiguity. Off by default.

### 6.3 `ystar czl undo`

Indie developers prefer "do, then revert" over "approve, then do". After every CZL run, the working-directory diff is automatically stashed; `ystar czl undo` rolls back the last run. This makes prior approval mostly unnecessary even when CZL gets it wrong.

### 6.4 Backend default selection

When the user has no `YSTAR_LLM_PROVIDER` set, CZL probes in this order:

1. `OLLAMA_HOST` reachable with `gemma4:e4b` or `qwen3-coder` available → use local (arm B path)
2. `DEEPSEEK_API_KEY` set → use DeepSeek (arm C primary)
3. `MINIMAX_API_KEY` / `QWEN_API_KEY` / `MOONSHOT_API_KEY` → next preference
4. `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` → last resort (defeats the arbitrage)

On first run, print a one-line cost estimate based on which backend was selected. e.g.:

```
[czl] using DeepSeek V3 → estimated cost per task ≈ $0.003 (vs $0.40 on Claude Opus, 130× cheaper)
```

This single line of output is the product's most important piece of marketing copy.

---

## 7. Repository layout

```
Y-star-gov/
├── ystar/
│   ├── czl/                          ← new top-level subpackage
│   │   ├── __init__.py               ← public API surface
│   │   ├── loop.py                   ← thin wrapper over ResidualLoopEngine + auto_rewrite
│   │   ├── scenarios/
│   │   │   ├── __init__.py           ← registry
│   │   │   ├── base.py               ← Scenario ABC (extends WorkloadEvent-style protocol)
│   │   │   ├── lint_fix.py
│   │   │   ├── test_gen.py
│   │   │   ├── bug_fix.py
│   │   │   └── crud_endpoint.py
│   │   ├── backends/
│   │   │   ├── __init__.py           ← LiteLLM-based registry
│   │   │   ├── base.py               ← Backend ABC
│   │   │   ├── deepseek.py
│   │   │   ├── minimax.py
│   │   │   ├── qwen.py
│   │   │   ├── kimi.py
│   │   │   ├── ollama.py
│   │   │   ├── anthropic.py          ← baseline arm
│   │   │   └── openai.py
│   │   ├── verifiers/
│   │   │   ├── __init__.py
│   │   │   ├── base.py               ← Verifier ABC
│   │   │   ├── pytest_verifier.py
│   │   │   ├── ruff_verifier.py
│   │   │   ├── mypy_verifier.py
│   │   │   └── ast_verifier.py       ← v21 spec verifier, refactored
│   │   └── cli.py                    ← `ystar czl ...` subcommands
│   ├── kernel/nl_to_contract.py      ← reuse as-is
│   ├── governance/
│   │   ├── contract_lifecycle.py     ← reuse as-is
│   │   └── residual_loop_engine.py   ← reuse as-is
│   ├── adapters/
│   │   ├── boundary_enforcer.py      ← reuse as-is
│   │   └── cieu_writer.py            ← reuse as-is
│   └── rules/auto_rewrite.py         ← reuse as-is
├── skill/
│   └── SKILL.md                      ← AgentSkills.io standard entry
├── benchmarks/
│   └── czl_arbitrage/                ← new
│       ├── run_three_arm.py          ← A/B/C orchestrator
│       └── results/
└── docs/
    └── CZL_PRODUCT_DESIGN.md         ← this file
```

**Existing modules reused without modification: 8.**
**New modules: 4 (`czl/`, plus `benchmarks/czl_arbitrage`, `skill/SKILL.md`, root CLI extension).**

This is what "don't reinvent wheels" looks like — the core CZL machinery already exists. We're adding scenario library, multi-backend layer (LiteLLM), external CI verifiers, and an indie-friendly Skill/CLI front door.

---

## 8. Distribution strategy

**Primary channel: AgentSkills.io.**

One SKILL.md file makes `ystar-czl` usable from **all 12+ agent frameworks** that support the AgentSkills.io open standard: Claude Code, OpenAI Codex, Gemini CLI, OpenClaw, Hermes Agent, Cursor, Aider, Windsurf, Kilo Code, OpenCode, Augment, Antigravity.

This means we ship **once** and reach the entire indie-developer agent ecosystem. The SKILL.md is intentionally short — under 200 lines — because skill-hub indexes by metadata, not body.

**Secondary channel: `pip install ystar` + `ystar czl run ...` CLI**, for users who don't run their work through a skill-aware agent.

**Tertiary: GitHub repo discovery + `skillhub.club` auto-indexing** (already operational for the company).

---

## 9. Pricing tiers (forward-looking — for after MVP ships)

| Tier | Price | What you get | TAM bet |
|---|---|---|---|
| OSS / BYO key | $0 | Full CZL + CLI + Skill. User provides own API keys. | Largest. Reach. |
| Managed Light | $5/mo | We pay DeepSeek/MiniMax bill up to 5M tokens/mo. Web dashboard with CIEU audit log. | Indie sweet spot. |
| Managed Pro | $25/mo | 30M tokens, audit export, multi-machine sync, priority routing. | Power indie / 2-person teams. |
| Team | $99/mo / 5 seats | Multi-tenant, shared contract library, SSO. | Bootstrap startups. |
| Enterprise | quote | On-prem CZL, compliance reports, SOC 2 prep using K9Audit. | Optional; not the focus. |

Pricing rationale: at $5/mo, our margin is **$5 − ~$1 (5M tokens × $0.20/M average) = $4 = 80%**, even after API costs. That's because we're not paying frontier prices — we're letting CZL cover the quality gap.

---

## 10. What we are explicitly NOT doing in MVP

- Not building our own agent. CZL wraps existing agents; it doesn't replace them.
- Not training our own model. The whole point is to use existing cheap APIs.
- Not building UI beyond CLI + 5-second toast. Web dashboard waits for paying users.
- Not writing custom verifiers when an external tool exists. (`pytest`, `ruff`, `mypy`, `bandit`, `hadolint`, `actionlint` — use them; don't reinvent.)
- Not chasing the adaptive-attacker robustness story in this product line — that belongs to the enterprise/K9Audit line and is downstream.
- Not pitching "AI safety". Pitch arbitrage. Always.
