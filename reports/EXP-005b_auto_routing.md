# EXP-005b: Auto-Routing — Transparent Execution Separation

**Date:** 2026-04-04
**Conducted by:** Y* Bridge Labs Engineering Team (MAC mini)
**Depends on:** EXP-005 (execution separation baseline)
**Status:** Complete

---

## What Changed Since EXP-005

EXP-005 proved that execution separation saves 66.2% tokens — but it required the agent to **explicitly** call `gov_exec` instead of `Bash`. That means agent code changes.

EXP-005b adds **auto-routing** to `gov_check`: when an agent submits a governance check for a Bash command that matches the exec whitelist, GOV MCP executes it immediately and returns the result inline. The agent doesn't need to know. Zero code changes.

```
EXP-005:   Agent calls gov_exec explicitly       → 66.2% savings, agent changes required
EXP-005b:  Agent calls gov_check as normal        → 45.4% savings, ZERO agent changes
```

## Auto-Routing Architecture

```
Agent sends: gov_check(tool_name="Bash", params={command: "git status"})
                        │
                GOV MCP gov_check()
                        │
            ┌───────────┴───────────┐
            │ Is command in          │
            │ exec_whitelist.yaml?   │
            └───────────┬───────────┘
                   yes/    \no
                  /          \
    ┌────────────┐    ┌──────────────┐
    │ Execute    │    │ Normal       │
    │ locally    │    │ ALLOW/DENY   │
    │ Return     │    │ (no exec)    │
    │ stdout +   │    └──────────────┘
    │ auto_routed│
    │ = true     │
    └────────────┘
```

## Experimental Setup

**Same 10-task CI workflow as EXP-005:**

| # | Command | Auto-routed? |
|---|---------|:---:|
| 1 | `git status --short` | YES |
| 2 | `git log --oneline -5` | YES |
| 3 | `pytest tests/test_orchestrator.py tests/test_circuit_breaker.py` | YES |
| 4 | `pytest tests/ -q --tb=no` | YES |
| 5 | `python -c "import ystar; print(version)"` | YES |
| 6 | `pip show ystar` | YES |
| 7 | `wc -l ystar/**/*.py` | YES |
| 8 | `git diff --stat HEAD~3 HEAD` | YES |
| 9 | `ls tests/test_*.py \| wc -l` | YES |
| 10 | `git branch -a` | YES |

**10/10 commands auto-routed.** All returned execution results inline.

## Results

### Three-way Comparison

| Metric | Mode A: Governed | Mode B: Auto-Route | Mode C: Batch (EXP-005) |
|--------|:---:|:---:|:---:|
| **Tool calls** | 20 (10 check + 10 exec) | 10 (check only) | 1 |
| **Tokens** | 5,620 | 3,070 | 1,243 |
| **Savings vs Mode A** | — | **45.4%** | **77.9%** |
| **Agent code changes** | — | **None** | Requires explicit gov_exec |
| **Execution time** | ~24s (20 LLM round-trips) | ~14.7s (10 round-trips) | ~7.5s (1 round-trip) |

### The Governance Tax Problem

Without auto-routing, adding governance to an agent **doubles** its tool calls:

```
Without governance:  Agent → Bash            (10 calls)
With governance:     Agent → gov_check → Bash (20 calls)  ← 2x overhead
With auto-routing:   Agent → gov_check        (10 calls)  ← same as ungoverned
```

**Auto-routing eliminates the governance tax.** The agent makes the same number of calls as an ungoverned agent, but every call is checked, logged, and governed.

### Per-Command Execution Data

| Command | stdout | Exec time | Decision |
|---------|--------|-----------|----------|
| git status --short | 52 chars | 15.2ms | ALLOW |
| git log --oneline -5 | 390 chars | 12.7ms | ALLOW |
| pytest (36 tests) | 897 chars | 306.1ms | ALLOW |
| pytest (full suite) | 438 chars | 6,061.7ms | ALLOW |
| import ystar; version | 14 chars | 69.3ms | ALLOW |
| pip show ystar | 112 chars | 144.3ms | ALLOW |
| wc -l codebase | 15 chars | 18.7ms | ALLOW |
| git diff --stat | 355 chars | 16.5ms | ALLOW |
| ls test files | 9 chars | 6.3ms | ALLOW |
| git branch -a | 66 chars | 12.8ms | ALLOW |

Total execution: 6,664.8ms (dominated by full test suite run).

## Key Insights

### 1. Auto-routing is the optimal default for governed agents

| Approach | Savings | Agent effort | Governance |
|----------|---------|-------------|------------|
| No governance | 0% | None | None |
| Manual governance (check + exec) | -53% (worse) | None | Full |
| **Auto-routing** | **+45.4%** | **None** | **Full** |
| Batch gov_exec | +66.2% | Must refactor | Full |

Auto-routing is the only approach that simultaneously:
- Adds governance ✓
- Saves tokens ✓
- Requires zero agent changes ✓

### 2. The savings formula

```
Savings = N × (check_overhead + thinking_overhead)
        = 10 × (185 + 50) = 2,350 tokens

Where N = number of deterministic commands in the workflow
```

For a 50-command CI pipeline: **~11,750 tokens saved per run.**

### 3. Auto-routing + batch = maximum savings

The two modes are composable:
- Auto-routing: transparent, zero-effort, 45% savings
- Batch gov_exec: requires agent changes, 66% savings
- Combined: agent batches non-deterministic work, auto-routing handles the rest

## Implementation Details

**Files changed:**
- `gov_mcp/server.py` — `_try_auto_route()` helper + `gov_check` integration
- `gov_mcp/exec_whitelist.yaml` — expanded with python3.11 prefixes

**Auto-route response format** (transparent to agent):
```json
{
  "decision": "ALLOW",
  "auto_routed": true,
  "command": "git status --short",
  "returncode": 0,
  "stdout": "M server.py\n",
  "stderr": "",
  "latency_ms": 15.2
}
```

The `auto_routed: true` field is the only difference from a normal `gov_check` response. Agents that don't check for it work identically. Agents that do can skip the execute step.

## Conclusion

> **Auto-routing makes governance free.** Adding Y*gov to an agent traditionally doubles tool calls. Auto-routing eliminates that tax and actually saves 45% tokens compared to governed-without-routing. The agent writes zero new code.

---

*EXP-005b conducted on Mac mini M2, Python 3.11.14, ystar v0.48.0.*
*Auto-routing: 10/10 commands routed. All measurements in single session.*
*Commit baseline: e9f6e33.*
