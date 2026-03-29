# Example Y*gov Agent Governance Contract

This is a minimal but complete AGENTS.md example for Y*gov.
Copy this to your project root and customize it.

## CEO Agent
- Never modify files in /production, /finance, or /sales
- Never run destructive commands: rm -rf, git reset --hard, git push --force
- Only write to /workspace and /reports
- Must ask user before committing to git (obligation: before-action)
- Must log all file modifications to CIEU database (obligation: after-action)

## CTO Agent
- Can only access /src, /tests, /docs
- Never modify /production
- Never run: rm -rf, DROP DATABASE, truncate
- Must run tests before any git commit (obligation: before-action)

## Marketing Agent
- Can only access /content, /marketing
- Can only write files, no system commands
- Never access /finance or /sales
- Must review budget before paid campaigns (obligation: before-action)

---
Generated with Y*gov v0.41+
See: https://github.com/your-org/ystar-gov
