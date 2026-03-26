# Y*gov Governance Skill for Claude Code

**Multi-agent compliance governance — in one skill.**

## Install

```bash
# Step 1: Install Y*gov
pip install ystar

# Step 2: Add this marketplace to Claude Code
/plugin marketplace add liuhaotian2024-prog/Y-star-gov/skill

# Step 3: Install the governance plugin
/plugin install ystar-governance@ystar-governance-marketplace
```

Restart Claude Code. Done.

---

## What you get

### `/ystar-governance:ystar-govern` — Auto-invoked governance

Claude automatically runs this before every subagent spawn, handoff, or high-risk operation. No manual invocation needed.

```
[Y*gov] Governance Check
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Action    : subagent_spawn
Principal : orchestrator
Actor     : code-reviewer
Decision  : ✅ ALLOW
CIEU      : 4f2a1b3c9e10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### `/ystar-governance:ystar-setup` — First-time setup

Run once to create your `AGENTS.md` governance contract.

### `/ystar-governance:ystar-report` — Audit report

```bash
/ystar-governance:ystar-report
```

Shows: total decisions, deny rate, top blocked paths, agent activity.

---

## Write your governance rules in plain language

Create `AGENTS.md` in your project:

```markdown
## Never access
- /etc
- /production
- .env

## Never run
- rm -rf
- sudo

## Obligations
- task_completion: 600 seconds
```

That's it. Y*gov reads this file and enforces it automatically.

---

## Why this is different from Auto Mode

Claude Code's Auto Mode uses an opaque classifier. You can't see its rules, can't audit its decisions, can't prove to anyone what it allowed or denied.

Y*gov uses **your** rules, written in plain language, enforced deterministically, with every decision written to a tamper-proof audit chain (CIEU). Any historical decision can be replayed exactly.

For personal projects: use Auto Mode.  
For anything that needs to answer "what did the agent do and why": use Y*gov.

---

## Requirements

- Python 3.11+
- Claude Code (any plan)
- `pip install ystar` (Y*gov v0.41.0+)

## License

MIT — free for commercial use.  
US Provisional Patent 63/981,777.
