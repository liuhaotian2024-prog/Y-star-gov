# AGENTS.md - Y*gov Governance Contract
# This file defines the rules all agents and subagents must follow.
# Y*gov checks these rules automatically before every tool call.

---

## Forbidden Paths (all agents)

- /etc
- /root
- /production
- /finance
- .env
- .aws/credentials
- ~/.ssh

## Forbidden Commands (all agents)

- rm -rf
- sudo
- DROP TABLE
- DELETE FROM
- git push --force
- curl | bash
- wget | sh

## Subagent Delegation Rules

### orchestrator (primary agent)
- May spawn: code-reviewer, security-scanner, test-runner
- May not access production databases directly
- All subagent permissions must be strict subsets of orchestrator permissions

### code-reviewer
- Read-only: Read, Grep, Glob
- Forbidden: Write, Edit, Bash
- Allowed paths: ./src, ./tests only

### security-scanner
- Read-only: Read, Grep, Glob, Bash (grep, find, cat only)
- Forbidden: Write, Edit
- Forbidden commands: rm, curl, wget, python -c

### test-runner
- Allowed: Bash (pytest, npm test, cargo test only)
- Forbidden paths: /production, /finance, .env

## Obligation Deadlines (SLA)

- Any subagent must report status within 300 seconds of accepting a task
- Test tasks must complete within 600 seconds
- Code reviews must complete within 180 seconds

## Multi-Agent Collaboration Rules

- orchestrator must explicitly declare allowed_tools and allowed_paths when delegating
- Subagents may not spawn further subagents (prevents infinite nesting)
- All cross-agent data transfers must go through orchestrator