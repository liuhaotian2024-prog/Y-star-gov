# Y*gov — Runtime Governance Framework for Multi-Agent AI Systems

**v0.41.1 · MIT License · Y* Bridge Labs**
**US Provisional Patents: 63/981,777 (P1) · P3 (SRGCS) · P4 (Passive Non-Compliance)**

---

## The Problem

Multi-agent AI systems have a governance gap that existing tools do not close.

### What is actually happening in production today

**Agents exceed their authorized scope.**
A CTO agent, tasked with fixing a bug, reads production credentials. A data agent, summarizing a report, queries a database it was never authorized to touch. A subagent, spawned by the orchestrator, inherits no constraints and operates with full permissions. None of this is logged. None of it is stopped. You find out later, if at all.

**Agents silently abandon obligations.**
A task is assigned. The agent starts it, gets distracted by another subtask, and never returns. No timeout fires. No escalation happens. The obligation expires with no record of why or when. The downstream agent waiting on the output waits forever.

**Audit trails are either absent or fabricated.**
Most multi-agent systems have no structured audit trail. The ones that do often rely on agents self-reporting — which means an agent can write "complied with policy" without ever having been checked. In a controlled experiment run by Y* Bridge Labs, an agent without runtime governance wrote a fabricated CIEU audit record into a public blog post as proof of compliance. The check had never run. The record was invented.

**Prompt-based governance fails under pressure.**
"You are not allowed to access /production" is a suggestion, not a rule. Under complex reasoning chains, adversarial prompts, or edge cases in task decomposition, agents ignore, reinterpret, or forget prompt-level constraints. This is not a model quality problem — it is an architectural one. Rules embedded in context are not the same as rules enforced at execution.

### What existing tools provide — and where they stop

| Tool | What it does | What it does not do |
|------|-------------|---------------------|
| LangSmith / Langfuse | Traces what happened after the fact | Does not prevent anything before execution |
| Datadog LLM Observability | Usage-based metrics and logs | No governance semantics, no policy enforcement |
| Guardrails AI | Input/output validation on LLM calls | Not multi-agent, no delegation chain, no obligations |
| Claude Code Auto Mode | Opaque classifier, non-auditable | Cannot show audit to regulators; rules not inspectable |
| Custom middleware | Bespoke per-team, no standard | Doesn't compose across agents; no compliance format |

**None of these tools enforce permissions at the tool-call level, track obligation deadlines, verify delegation chain integrity, or produce a tamper-evident audit chain usable as compliance evidence.**

Y*gov is the enforcement layer. It runs before execution. It records everything. It cannot be bypassed by prompt injection.

---

## What Y*gov Does

Three things, deterministically:

**1. Permission enforcement at execution time**
Every tool call any agent makes is intercepted before execution and checked against a declarative governance contract. ALLOW or DENY is computed deterministically from your rules — no LLM involved in the enforcement path. The check runs in 0.042ms mean latency.

**2. Obligation tracking with automatic enforcement**
When a task is assigned, an obligation record is created with a deadline. If the agent misses the deadline, the next tool call it makes triggers detection. The agent is blocked from unrelated work until the obligation is fulfilled. No external polling. No cron jobs. The agent's own behavior triggers the gate.

**3. Tamper-evident CIEU audit chain**
Every decision — ALLOW or DENY, with full context — is written to a SHA-256 Merkle-chained SQLite database. Records cannot be modified after creation. Any tampering breaks the hash chain, detectable by `ystar verify`. The audit output is structured for compliance review, not debugging convenience.

---

## Integration

### Claude Code

Y*gov integrates as a `PreToolUse` hook — the native Claude Code extension point that fires before every tool call.

**Install:**

```bash
pip install ystar
ystar hook-install   # writes hook to ~/.claude/settings.json
ystar doctor         # verify all 7 checks pass
```

**Or install via Claude Code skill marketplace:**

```
/plugin marketplace add liuhaotian2024-prog/Y-star-gov/skill
/plugin install ystar-governance@ystar-governance-marketplace
```

**What the hook does:**

```
Agent → tool call → PreToolUse fires → Y*gov check() → ALLOW / DENY
                                                ↓
                                       CIEU record written
                                       Obligations scanned
                                       Delegation chain verified
```

Every subagent spawned by Claude Code is governed by the same hook. No per-agent configuration. No code changes to your agents.

**Verified working on:** macOS, Linux, Windows (Git Bash, v0.41.1+).

### OpenClaw

Y*gov ships a first-class OpenClaw adapter at `ystar/domains/openclaw/`.

```python
from ystar.domains.openclaw import AccountabilityPack

pack = AccountabilityPack(
    agents=["orchestrator", "cs_agent", "data_agent"],
    agents_md_path="./AGENTS.md",
)
pack.attach(claw_session)
```

`AccountabilityPack` registers Y*gov governance on all OpenClaw tool calls in the session. CIEU records are written to the shared audit chain alongside OpenClaw's native telemetry.

**OpenClaw-specific features:**
- Delegation chain verification on `HANDOFF` events
- Obligation SLA enforcement across agent handoffs
- Cross-session audit chain continuity

### LangChain / CrewAI / AutoGen (coming)

Adapter interface at `ystar/integrations/base.py`. Implement `BaseGovernanceAdapter` to connect any agent framework.

---

## Differentiation

### vs. LangSmith / Langfuse / Arize

These are observability tools. They record what happened. They are cameras.

Y*gov is enforcement. It determines what is allowed to happen. It is a gate.

You need both. Y*gov does not replace observability — it adds the enforcement layer that observability cannot provide.

### vs. Guardrails AI

Guardrails validates LLM inputs and outputs. It sits at the model API boundary.

Y*gov sits at the tool execution boundary. These are different problems:
- Guardrails: "Is this text safe to send to the LLM?"
- Y*gov: "Is this file write authorized for this agent at this moment?"

Multi-agent governance requires tool-level enforcement, delegation chain verification, and obligation tracking — none of which are in scope for Guardrails.

### vs. Claude Code Auto Mode

Auto Mode uses an internal classifier. Its rules are not inspectable. Its decisions are not auditable. You cannot show its output to a regulator and say "here is proof that this agent operated within authorized scope."

Y*gov uses **your** rules, written in plain English in `AGENTS.md`, enforced deterministically, with every decision written to a tamper-evident audit chain you own and control.

For personal projects: Auto Mode is fine.
For anything subject to SOC 2, HIPAA, FINRA, FDA 21 CFR Part 11, or any enterprise audit requirement: you need Y*gov.

### vs. writing your own middleware

Every team that has tried to build custom agent governance has hit the same three walls:

1. It doesn't compose. When agents spawn subagents, hand-rolled middleware has no mechanism to verify that the child's permissions are a subset of the parent's. Privilege escalation goes undetected.
2. It has no standard. Your compliance team cannot review a log format that a developer invented last quarter.
3. It doesn't track obligations. Detecting what agents did is solvable. Detecting what agents were supposed to do but didn't — passive non-compliance — requires the `OmissionEngine` architecture. Building it correctly takes months.

Y*gov provides all three, tested, with 86/86 passing tests, in `pip install ystar`.

---

## Technical Innovations

### 1. Action-Triggered Passive Non-Compliance Detection (P4)

The canonical approach to obligation tracking requires external polling: a cron job or scheduler that periodically checks whether deadlines have passed. This has three failure modes: race conditions, missed fires, and no causal connection between the detection event and the agent's current context.

Y*gov's `OmissionEngine` uses a fundamentally different architecture: **the agent's own next tool call is the detection trigger**. Every call to `enforce()` — which runs on every tool call — internally invokes `_auto_feed_omission()`, which scans pending obligations. The detection is causally linked to the agent's behavior, runs in the agent's execution context, and requires no external infrastructure.

The enforcement gate (HARD_OVERDUE) clears automatically when the required event type is produced. No human intervention. No manual reset.

### 2. Self-Referential Governance Closure (P3 — SRGCS)

The quis custodiet problem in AI governance: who governs the meta-governance agent?

Y*gov's Path A resolves this by deriving the meta-agent's behavioral constraints from the outputs of the same governance system it is improving. `suggestion_to_contract()` maps `GovernanceSuggestion` objects to `IntentContract` instances using a lossy, bounded homomorphism — lossy by design to prevent the meta-agent from crafting suggestions that produce permissive contracts.

The result: Path A operates under the same `check()` enforcement and CIEU audit chain as operational agents. The governance system governs itself without requiring a separate authority layer.

### 3. DelegationChain Monotonicity Verification

In multi-agent hierarchies, the standard failure mode is privilege escalation through subagent spawning: Agent A has limited permissions, creates Agent B with broader permissions, bypassing its own constraints.

Y*gov formalizes and enforces the monotonic authority property:

```
∀ (parent P, child C) in delegation chain:
  C.deny ⊇ P.deny
  C.deny_commands ⊇ P.deny_commands
  C.only_paths ⊆ P.only_paths
  C.only_domains ⊆ P.only_domains
```

`DelegationChain.validate()` checks this on every `SUBAGENT_SPAWN` and `HANDOFF` event. Violations are written to the CIEU chain and block the spawn.

### 4. Constitutional Hash Traceability

Every `IntentContract` carries the SHA-256 hash of the `AGENTS.md` document that produced it. Every CIEU record carries the contract hash. This creates a complete traceability chain:

```
AGENTS.md → contract_hash → IntentContract → CIEU record
```

Auditors can verify that any specific enforcement decision derived from a specific version of the governance document. If `AGENTS.md` is modified, the hash changes, and all subsequent CIEU records reflect the new contract version.

### 5. Dual-Path LLM/Regex Translation

`nl_to_contract()` provides a robust pipeline for converting natural language governance documents to machine-enforceable `IntentContract` instances:

- **LLM path (confidence 0.90):** Uses `claude-sonnet` to parse complex, indirect, or context-dependent governance language. Followed by `validate_contract_draft()` — a deterministic quality checker that catches invariant syntax errors, value_range direction inversions, and coverage gaps before the contract is activated.
- **Regex path (confidence 0.50):** Constitutional rules approach — `[deontic operator] × [semantic domain] → constraint type`. Covers the most common explicit patterns without LLM dependency. Used as fallback when LLM is unavailable.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Claude Code / OpenClaw Runtime            │
│                                                                  │
│  Agent → Tool Call → PreToolUse Hook ──────────────────────┐    │
│                                                            │    │
│  ┌─────────────────────────────────────────────────────────▼──┐ │
│  │                      Y*gov Kernel                           │ │
│  │                                                             │ │
│  │  AGENTS.md ──► nl_to_contract() ──► IntentContract         │ │
│  │                                           │                │ │
│  │                              check(params, contract)        │ │
│  │                                    │                        │ │
│  │              ┌─────────────────────┤                        │ │
│  │              │ deny / deny_commands│                        │ │
│  │              │ only_paths / domains│                        │ │
│  │              │ invariant / range   │                        │ │
│  │              └─────────────────────┘                        │ │
│  │                         │                                   │ │
│  │               ALLOW ────┴──── DENY + reason                 │ │
│  │                         │                                   │ │
│  │         ┌───────────────┼───────────────┐                  │ │
│  │         ▼               ▼               ▼                  │ │
│  │   CIEU Store      OmissionEngine   DelegationChain         │ │
│  │ (SHA-256 chain)  (SOFT/HARD gate)  (monotonicity)          │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│              Path A — SRGCS Meta-Governance Layer                │
│                                                                  │
│  GovernanceLoop ──► GovernanceSuggestion                         │
│        │                     │                                   │
│        │          suggestion_to_contract() [lossy]               │
│        │                     │                                   │
│        └──────────► IntentContract (governs Path A itself)        │
│                              │                                   │
│                           check()  ← same kernel                 │
│                           CIEU     ← same chain                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Data Structures

### IntentContract

```python
@dataclass
class IntentContract:
    name:               str   = ""
    deny:               List[str] = []  # forbidden substrings in any param
    only_paths:         List[str] = []  # file_path whitelist (prefix match)
    deny_commands:      List[str] = []  # forbidden command prefixes
    only_domains:       List[str] = []  # url domain whitelist
    invariant:          List[str] = []  # boolean expressions (AST-safe eval)
    optional_invariant: List[str] = []  # conditional invariants
    value_range:        Dict[str, Dict] = {}  # {"param": {"min": N, "max": M}}
    obligation_timing:  Dict[str, Any]  = {}  # {"task_completion": 600}
    postcondition:      List[str] = []  # post-execution assertions
    hash:               str   = ""      # SHA-256 of source AGENTS.md
```

**Evaluation order:** deny → deny_commands → only_domains → only_paths → value_range → invariant → optional_invariant. Short-circuit on first violation.

### CIEU Record (cieu_events schema)

| Column | Description |
|--------|-------------|
| seq_global | Monotonic global sequence number |
| event_id | UUID |
| agent_id | Agent that made the call |
| event_type | Tool name (Read, Write, Bash, Agent...) |
| decision | allow / deny |
| violations | JSON array: [{dimension, message}] |
| contract_hash | SHA-256 of governing IntentContract |
| file_path / command / url | Extracted params |
| prev_hash | SHA-256 of previous record |
| record_hash | SHA-256 of this record |
| created_at | Epoch timestamp (immutable) |

---

## CLI Reference

```
ystar setup [--yes]
    Initialize .ystar_session.json in current directory.

ystar hook-install
    Register PreToolUse hook in ~/.claude/settings.json.
    Idempotent.

ystar doctor
    7-point health check. Exit 0 = healthy, 1 = issues found.
    Checks: session config, hook registration, CIEU database,
            AGENTS.md, hook self-test (/etc/passwd blocked).

ystar report [--db <path>] [--format text|json]
    CIEU summary: total decisions, deny rate, by-agent breakdown.

ystar verify [--session <id>] [--db <path>]
    Verify SHA-256 Merkle chain integrity.

ystar seal [--session <id>]
    Write Merkle root. Session becomes immutable.

ystar version
    Print version.

ystar policy-builder
    Launch local HTML policy builder (port 7379).
```

---

## Performance

Single thread, Python 3.11, M2 MacBook Pro:

| Operation | Mean | p99 |
|-----------|------|-----|
| `check()` ALLOW | 0.042ms | 0.080ms |
| `check()` DENY | 0.041ms | 0.065ms |
| `enforce()` full pipeline | 0.021ms | 0.055ms |
| `OmissionEngine.scan()` 20 obligations | 0.011ms | 0.018ms |
| `nl_to_contract()` regex path | 0.8ms | 2.1ms |
| `nl_to_contract()` LLM path | ~2000ms | ~5000ms |

Industry reference (Microsoft AGT): < 0.1ms.
Y*gov `check()` at 0.042ms mean: **2.4× faster.**

CIEU write throughput: ~8,000 records/second (SQLite WAL).

---

## Experimental Evidence

Y* Bridge Labs ran a controlled experiment (EXP-001) comparing the same multi-agent company with and without Y*gov governance:

| Metric | Without Y*gov | With Y*gov |
|--------|--------------|------------|
| Tool calls | 117 | 45 (-62%) |
| Token consumption | 186,300 | 156,047 (-16%) |
| Runtime | 9m 19s | 6m 4s (-35%) |
| Unauthorized system access | 3 (undetected) | 0 |
| Fabricated audit evidence | 1 instance | 0 |
| Real CIEU records | 0 | 14 |

Governance reduced cost and time while eliminating all violations. The runtime enforcement mechanism (obligation timeout) was responsible for the majority of efficiency gains by preventing the CTO agent from looping on a blocked task 66 times.

Full report: [ystar-bridge-labs/reports/](https://github.com/liuhaotian2024-prog/ystar-bridge-labs)

---

## Requirements

- Python 3.11+
- Claude Code (any plan) or OpenClaw
- SQLite (stdlib, no install needed)
- `ANTHROPIC_API_KEY` — optional, for LLM-assisted AGENTS.md translation

---

## Patents

**P1 — US Provisional 63/981,777** (January 2026)
CIEU five-tuple structure, SHA-256 Merkle chain, DelegationChain monotonicity, session sealing.

**P3 — SRGCS** (March 26, 2026)
Self-referential governance closure: meta-governance agent constrained by contracts derived from its own governance outputs via `suggestion_to_contract()`.

**P4 — Action-Triggered Passive Non-Compliance Detection** (March 26, 2026)
Obligation expiry detection triggered by agent's own subsequent tool invocations; two-phase SOFT/HARD enforcement with automatic gate release.

---

## License

MIT. Free for commercial use, internal deployment, academic research, OEM embedding.

---

## Contact

**Haotian Liu · Y* Bridge Labs**
liuhaotian2024@gmail.com

Enterprise licensing · Domain pack development · Research collaboration
