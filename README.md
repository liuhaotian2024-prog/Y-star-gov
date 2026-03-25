# Y\*gov — Runtime Governance for AI Agents

**US Provisional Patent 63/981,777 · MIT License · v0.40.0**

> *"You can't govern what you can't see. You can't trust what you can't verify. Y\*gov makes both possible — in real time, before damage is done."*

---

## What is Y\*

Y\* (pronounced "Y-star") is a formal governance framework for multi-agent AI systems.

The name comes from **Y\*_t** — the intent contract at time *t* that every agent action is measured against. Not a log. Not a report. A living, causal binding between what an agent *promised* to do and what it actually did.

Y\*gov is the open-source implementation of Y\*, designed to connect to any agent framework in three commands.

---

## The problem Y\*gov solves

When you deploy an AI agent, two things go wrong that no one talks about:

**1. Agents do things they shouldn't.**
They access files outside their scope. They run dangerous commands. They bypass the rules you thought you set. By the time you find out, the damage is done.

**2. Agents don't do things they should.**
They receive a task, start something else, and quietly let the obligation expire. No error. No alert. Just silence — until the customer complains, the deadline passes, or the audit finds the gap.

Current tools catch *neither* of these reliably. They log what happened. They don't stop it.

Y\*gov stops it.

---

## How it works

Y\*gov attaches to your agent framework as a `PreToolUse` hook. Every time an agent calls a tool — read a file, run a command, fetch a URL — Y\*gov intercepts it *before* execution.

```
Agent calls any tool
        ↓
PreToolUse hook fires
        ↓
Y*gov checks against IntentContract
        ↓
   ALLOW  or  DENY + reason + "here's what to do instead"
        ↓
Every decision written to CIEU (tamper-proof audit chain)
```

No code changes to your agents. No decorators. No wrappers. One hook, everything covered.

---

## Three-command install

```bash
pip install ystar
ystar setup           # generates .ystar_session.json
ystar hook-install    # registers PreToolUse hook in ~/.claude/settings.json
```

Then write your `AGENTS.md`:

```markdown
# AGENTS.md

## Never access
- /etc, /root, /production, /finance

## Never run
- rm -rf, sudo, DROP TABLE, DELETE FROM

## Obligations
- respond_to_complaint: 300 seconds
```

That's it. Restart OpenClaw. Y\*gov is active.

---

## What you get

### Violation governance (做错了)
When an agent tries something outside its contract:

```
[Y*] '/etc' is not allowed in file_path
     Attempted: Read /etc/passwd
     Agent: cs_agent | Session: proj_abc123
     CIEU record: #4f2a...
```

The action is blocked. The CIEU chain records the attempt. The agent gets a clear message and can retry with a corrected path.

### Passive inaction governance (该做的不做)
When an agent ignores an obligation:

```
[RECOMMENDED] Obligation overdue: capability_demonstration
  Required action(s): complaint_processed
  Overdue by: 312s
  Context: 5-minute SLA for customer complaints
  → Complete the required action to unblock.
```

The next tool call the agent makes — any tool call — triggers detection. The agent is redirected until the obligation is fulfilled. Then the block lifts automatically.

### Multi-agent delegation chain
When agents spawn sub-agents, Y\*gov enforces monotonic constraint inheritance:

```
orchestrator.deny ⊆ cs_agent.deny ⊆ data_agent.deny
```

A child agent can never have looser permissions than its parent. Verified cryptographically at every HANDOFF.

### CIEU — Causal Immutable Evidence Units
Every decision (allow, deny, redirect) is written as a 5-tuple:

```json
{
  "session_id": "proj_abc123",
  "agent_id":   "cs_agent",
  "action":     "file_read",
  "params":     {"file_path": "/etc/passwd"},
  "result":     {"decision": "deny", "violations": [...]},
  "contract_hash": "sha256:4f2a..."
}
```

SHA-256 hash chain. Append-only. Any historical decision can be replayed exactly from the CIEU snapshot at that moment.

---

## Path A — Self-evolving governance

Y\*gov includes **Path A**, a deterministic causal reasoning agent that improves the governance system itself.

Path A is not an LLM. It has no random outputs. It uses:
- **TypeBasedPlanner** — backward-chains from governance gaps to module combinations
- **CausalEngine** — Pearl Level 2/3 causal inference over CIEU history
- **GovernanceLoop** — observe → suggest → tighten, autonomous cycle

The "intelligence" grows from CIEU data. Same history, same decision — always. Every Path A action is itself governed by `PATH_A_AGENTS.md` and verified by SHA-256 on every cycle.

---

## Relationship to K9Audit

[K9Audit](https://github.com/liuhaotian2024-prog/K9Audit) records what happened.

Y\*gov governs what happens.

They are complementary. K9Audit's `@k9` decorator gives you function-level causal tracing. Y\*gov's `PreToolUse` hook gives you framework-level real-time governance. Use both for full coverage.

| | K9Audit | Y\*gov |
|---|---|---|
| Integration | `@k9` decorator per function | One hook, all tools |
| Timing | After execution | Before execution |
| Action | Records | Blocks + guides |
| Obligation tracking | No | Yes |
| Multi-agent delegation | No | Yes (monotonic) |

---

## Architecture

```
AGENTS.md
    ↓ (NL → IntentContract)
IntentContract  ←──────────────────────────────────────────┐
    ↓                                                       │
PreToolUse hook → enforce() → check() → ALLOW / DENY       │
                                  ↓                        │
                          OmissionEngine                   │
                                  ↓                        │
                         InterventionEngine                │
                          (gate + suggest)                 │
                                  ↓                        │
                            CIEU chain                     │
                                  ↓                        │
                            Path A agent ──────────────────┘
                         (causal reasoning,
                          self-improves governance)
```

---

## Requirements

- Python 3.11+
- OpenClaw (Claude Code) for hook integration
- SQLite (bundled, no server needed)

---

## License & Patent

MIT License. Free for commercial use, academic use, internal deployment.

US Provisional Patent 63/981,777 covers:
- CIEU five-tuple causal evidence structure
- Self-referential contract closure (GovernanceSuggestion = IntentContract)
- Passive non-compliance detection (omission governance)
- DelegationChain monotonicity formal verification

---

## Contact

**Haotian Liu** · liuhaotian2024@gmail.com

For enterprise licensing, OEM embedding, or research collaboration.

---

*Y\*gov: the first open-source runtime governance framework that closes both loops — what agents shouldn't do, and what they must.*
