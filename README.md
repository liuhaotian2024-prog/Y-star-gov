# Y\*gov — Runtime Governance for AI Agents

**US Provisional Patent 63/981,777 · MIT License · v0.40.0**

> *"You can't govern what you can't see. You can't trust what you can't verify. Y\*gov makes both possible — in real time, before damage is done."*

---

## What is Y\*

Y\* (pronounced "Y-star") is a formal governance framework for multi-agent AI systems.

The name comes from **Y\*_t** — the intent contract at time *t* that every agent action is measured against. Not a log. Not a report after the fact. A living, causal binding between what an agent *promised* to do and what it actually did.

Y\*gov is the open-source implementation of Y\*, designed to connect to any agent framework in minutes.

---

## The problem Y\*gov solves

When you deploy an AI agent, two things go wrong that existing tools don't catch:

**1. Agents do things they shouldn't.**
They access files outside their scope. They run dangerous commands. They bypass the rules you set. By the time you find out, the damage is done.

**2. Agents don't do things they should.**
They receive a task, start something else, and quietly let the obligation expire. No error. No alert. Just silence — until the customer complains, the deadline passes, or the audit finds the gap.

Current tools log what happened. They don't stop it.

Y\*gov stops it — before execution, every time.

---

## Install on Mac

### Step 1 — Download

Download `ystar-0.40.0-py3-none-any.whl` from this repository.

### Step 2 — Install

**Option A: Virtual environment (recommended)**

```bash
python3 -m venv ystar-env
source ystar-env/bin/activate
pip install ystar-0.40.0-py3-none-any.whl
```

**Option B: System install**

```bash
pip3 install ystar-0.40.0-py3-none-any.whl --break-system-packages
```

### Step 3 — Generate session config

Run in your project directory:

```bash
ystar setup --yes
```

This creates `.ystar_session.json` with default settings.
To customize paths, commands, and SLA timeouts interactively:

```bash
ystar setup
```

### Step 4 — Register the hook

```bash
ystar hook-install
```

Y\*gov automatically detects your OpenClaw/Claude Code config location:
- `~/.claude/settings.json`
- `~/.config/openclaw/openclaw.json`
- `~/Library/Application Support/Claude/settings.json`

Restart Claude Code / OpenClaw after this step.

### Step 5 — Write your AGENTS.md

Create `AGENTS.md` in your project directory:

```markdown
# AGENTS.md

## Never access
- /etc, /root, /production, /finance

## Never run
- rm -rf, sudo, DROP TABLE, DELETE FROM

## Obligations
- respond_to_complaint: 300 seconds
```

**Y\*gov is now active.** Every tool call your agent makes will be checked against this contract before execution.

---

## Verify it's working

Run any tool call in Claude Code. If Y\*gov is active, blocked actions will show:

```
[Y*] '/etc' is not allowed in file_path
     Attempted: Read /etc/passwd
     → Complete the required action to unblock.
```

---

## Set up automatic data sync (optional)

Syncs your CIEU audit data to GitHub every 15 minutes for remote analysis.

```bash
bash ystar_sync_setup.sh
```

You will be prompted for:
- GitHub Personal Access Token
- Project directory (where `.ystar_cieu.db` lives)
- Sync interval (default: 15 minutes)
- Machine label (e.g. `mac-test`)

To check sync status:
```bash
cat ~/.ystar/sync.log
```

To trigger a manual sync:
```bash
bash ~/.ystar/sync.sh
```

To stop syncing:
```bash
crontab -e    # delete the line containing "ystar"
```

---

## How it works

```
Agent calls any tool
        ↓
PreToolUse hook fires automatically
        ↓
Y*gov checks against IntentContract
        ↓
   ALLOW  ──or──  DENY + reason + "here's what to do instead"
        ↓
Every decision written to CIEU (tamper-proof causal audit chain)
```

**No code changes to your agents. No decorators. No wrappers.**
One hook, every tool call covered.

---

## What you get

### Violation governance

When an agent tries something outside its contract:

```
[Y*] '/etc' is not allowed in file_path
     Attempted: Read /etc/passwd
     Agent: cs_agent | Session: proj_abc123
     CIEU record: sha256:4f2a...
```

Action blocked. CIEU chain records the attempt. Agent receives a clear message and can retry with a corrected path.

### Passive inaction governance

When an agent ignores a time-bound obligation:

```
[RECOMMENDED] Obligation overdue: respond_to_complaint
  Required action(s): complaint_processed
  Overdue by: 312s
  Context: 5-minute SLA for customer complaints
  → Complete the required action to unblock.
```

The next tool call the agent makes — any tool call — triggers detection.
The agent is redirected until the obligation is fulfilled. Then the block lifts automatically.

### Multi-agent delegation chain

When agents spawn sub-agents, Y\*gov enforces monotonic constraint inheritance:

```
orchestrator.deny ⊆ cs_agent.deny ⊆ data_agent.deny
```

A child agent can never have looser permissions than its parent. Verified at every HANDOFF.

### CIEU — Causal Immutable Evidence Units

Every decision is written as a tamper-proof 5-tuple:

```json
{
  "session_id":    "proj_abc123",
  "agent_id":      "cs_agent",
  "action":        "file_read",
  "params":        {"file_path": "/etc/passwd"},
  "result":        {"decision": "deny", "violations": [...]},
  "contract_hash": "sha256:4f2a..."
}
```

SHA-256 hash chain. Append-only. Any historical decision can be replayed exactly — fully auditable, legally defensible.

---

## Path A — Self-evolving governance

Y\*gov includes **Path A**, a deterministic causal reasoning agent that improves the governance system itself over time.

Path A is not an LLM. It has no random outputs. It uses:

- **TypeBasedPlanner** — backward-chains from governance gaps to module combinations
- **CausalEngine** — Pearl Level 2/3 causal inference over accumulated CIEU history
- **GovernanceLoop** — observe → suggest → tighten, running autonomously in the background

The more CIEU data accumulates, the more accurately Path A understands what good governance looks like in your specific context. Same CIEU history, same decision — always deterministic and auditable.

---

## Comparison with K9Audit

[K9Audit](https://github.com/liuhaotian2024-prog/K9Audit) and Y\*gov are complementary.

| | K9Audit | Y\*gov |
|---|---|---|
| Integration | `@k9` decorator per function | One hook, all tool calls |
| Timing | Records during execution | Blocks before execution |
| Action | Causal trace | Govern + guide |
| Obligation tracking | No | Yes — SLA enforcement |
| Multi-agent delegation | No | Yes — monotonic chains |
| Self-evolving | No | Yes — Path A |

Use K9Audit for function-level causal tracing.
Use Y\*gov for framework-level real-time governance.
Use both for full coverage.

---

## Requirements

- Python 3.11+
- OpenClaw (Claude Code) for hook integration
- SQLite (bundled, no server required)

---

## Benchmarks

Core hot path performance (single thread):

| Operation | Mean | p99 |
|-----------|------|-----|
| `check()` ALLOW | 0.042ms | 0.080ms |
| `check()` DENY | 0.041ms | 0.065ms |
| `enforce()` full chain | 0.021ms | 0.055ms |
| `OmissionEngine.scan()` 20 obligations | 0.011ms | 0.018ms |
| `gate_check()` | 0.001ms | 0.002ms |

Industry reference (Microsoft AGT): < 0.1ms.
Y\*gov runs at 2× that benchmark.
At 100 agents × 10 tool calls/second, `check()` uses 4.2% CPU.

---

## License & Patent

**MIT License** — free for commercial use, internal deployment, academic research.

**US Provisional Patent 63/981,777** covers:
- CIEU five-tuple causal evidence structure
- Self-referential contract closure
- Passive non-compliance detection (omission governance)
- DelegationChain monotonicity formal verification
- Path A deterministic causal meta-governance

---

## Contact

**Haotian Liu** · liuhaotian2024@gmail.com

Enterprise licensing, OEM embedding, research collaboration.

---

*Y\*gov: the first open-source runtime governance framework that closes both loops —*
*what agents shouldn't do, and what they must.*
