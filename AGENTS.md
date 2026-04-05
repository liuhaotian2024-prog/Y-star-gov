# Y*gov Governance Contract

## Constitutional Principles (immutable, never violate)

### Iron Rule 1: Deterministic Enforcement
Y*gov's enforcement layer contains no LLM. All ALLOW/DENY decisions are computed deterministically from the contract. Governance cannot be prompt-injected.

### Iron Rule 2: No Hardcoded Paths
All file paths, ports, agent IDs, and configuration locations are passed via parameters or environment variables. No default path strings in code. All paths use pathlib for cross-platform compatibility.

### Iron Rule 3: Ecosystem Neutrality (Constitutional, non-violable)

Y*gov and GOV MCP are ecosystem-neutral infrastructure. Any code implementation must comply:

1. **No hardcoded protocol formats for any specific ecosystem.**
   Wrong: writing Claude Code's hookSpecificOutput format directly in code.
   Right: using an adapter layer that selects format dynamically based on host parameter.

2. **All external interfaces must simultaneously support:**
   - Claude Code ecosystem
   - OpenClaw ecosystem
   - Generic MCP ecosystem
   - Future ecosystems (extensible by adding a format function, no existing code changes)

3. **Adding support for a new ecosystem must not break existing ones.**
   Every PR touching ecosystem interfaces must test all supported hosts.

4. **Every code review must include the check:**
   "Does this implementation bind to a specific ecosystem?"

Violation of this principle = P0-level violation. Stop all work and fix immediately.

**Fulfillment mechanism:** Every commit touching ecosystem interfaces must include:
"Ecosystem-neutral verified: Claude Code / OpenClaw / Generic"

---

## GOV MCP Usage Rule (Internal — Y* Bridge Labs)

GOV MCP server runs at 192.168.1.228:7922 (Mac mini, SSE transport).

When executing deterministic commands (git, grep, pytest, ls, wc, find, head, tail, etc.), agents MUST use the gov_check MCP tool. If the response contains auto_routed: true, the command has already been executed — do NOT call Bash separately.

For non-deterministic commands or commands requiring interactive input, use Bash directly. The PreToolUse hook daemon provides the safety net.

This is MUST (internal team policy), not SHOULD. The GOV MCP server is always available.

---

## ystar-cto

- Never access /etc or /proc or /sys
- Never access .env files or .ssh directories or credentials files
- Never access /production or /staging environments
- Never run rm -rf
- Never run sudo
- Never run git push --force
- Never run curl piped to sh or bash
