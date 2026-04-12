---
name: ystar-govern
description: >
  Y*gov governance runtime boot and enforcement. Use automatically on session start
  to restore governance runtime (daemon, identity, hook chain, hard constraints).
  Also triggers on: subagent spawn, handoff, delegation, agent teams,
  Task tool invocation, permission boundary check, compliance validation,
  governance, compliance, audit, policy check, access control, delegation chain,
  CIEU, ystar.
allowed-tools: Bash, Read
---

# Y*gov Governance Boot & Enforcement

You are restoring and enforcing Y*gov runtime governance. On session start, you MUST boot the full governance runtime. On subsequent activations, you validate compliance before any delegation or high-risk action.

## SESSION BOOT MODE (first activation per session)

### Step 1: Run governance_boot.sh

Run the atomic governance recovery script. Replace `AGENT_ID` with the current agent's role (ceo, cto, cmo, cso, cfo, secretary, eng-kernel, eng-governance, eng-platform, eng-domains):

```bash
bash /Users/haotianliu/.openclaw/workspace/ystar-company/scripts/governance_boot.sh AGENT_ID
```

This script atomically restores:
- Agent identity (.ystar_active_agent)
- Hook daemon (_hook_daemon.py on /tmp/ystar_hook.sock)
- Cross-session memory (session_boot_yml.py)
- Session markers (.session_booted, .session_call_count)
- Session config validation (.ystar_session.json — 193 constraint items across 11 categories)
- CIEU database connectivity
- E2E hard constraint verification (5 tests)

### Step 2: Check output

If the output ends with `ALL SYSTEMS GO` — governance is fully operational. Proceed to Step 4.

If the output shows `N FAILURES` — proceed to Step 3.

### Step 3: Auto-remediate failures

For each failure type, apply the appropriate fix:

**Hook daemon FAILED:**
```bash
pkill -f "_hook_daemon.py" 2>/dev/null
rm -f /tmp/ystar_hook.sock
sleep 1
cd /Users/haotianliu/.openclaw/workspace/ystar-company
PYTHONPATH="/Users/haotianliu/.openclaw/workspace/Y-star-gov:$PYTHONPATH" python3.11 /Users/haotianliu/.openclaw/workspace/Y-star-gov/ystar/_hook_daemon.py &
sleep 3
ls -la /tmp/ystar_hook.sock
```

**Session config MISSING:** File .ystar_session.json must exist in ystar-company root. If missing, this is a P0 — report to Board immediately.

**CIEU database MISSING:** File .ystar_cieu.db must exist. If missing, report to Board immediately.

**Hard constraint NOT ENFORCING:** Re-run the specific test via hook_client_labs.sh. If daemon is up but constraint fails, check boundary_enforcer.py configuration. Note: `must_dispatch_via_cto` and `ceo_code_block` only apply when active agent is CEO — they will show NOT ENFORCING for other agents, which is expected.

**normal_operations BLOCKED:** Daemon may have crashed. Restart daemon and re-test.

**Circuit breaker ARMED:** Too many violations accumulated. Use `mcp__gov-mcp__gov_reset_breaker` to reset after confirming the violations are understood.

After fixing, re-run governance_boot.sh to confirm ALL SYSTEMS GO.

### Step 4: Confirm gov-mcp tools available

The gov-mcp MCP server provides 49 governance tools with prefix `mcp__gov-mcp__gov_*`. Verify availability by checking that tools like `mcp__gov-mcp__gov_doctor`, `mcp__gov-mcp__gov_verify`, `mcp__gov-mcp__gov_check` are listed in available tools.

If gov-mcp tools are not available, the MCP server may need to be started separately — report to Board.

### Step 5: Report governance status

Output the governance status report:

```
[Y*gov] Governance Runtime Status
====================================
Boot Result  : ALL SYSTEMS GO / N FAILURES
Daemon       : RUNNING (socket /tmp/ystar_hook.sock)
Agent        : {agent_id}
Constraints  : 193 items (11 categories)
CIEU Events  : {count}
Gov-MCP      : {tool_count} tools available
Hard Tests   : {pass_count}/5 passing
====================================
```

## ENFORCEMENT MODE (subsequent activations)

When this skill activates for a specific action (not session boot):

### Step 1: Identify the action

Determine:
- `ACTION_TYPE`: subagent_spawn / handoff / file_write / bash_exec
- `PRINCIPAL_AGENT`: the delegating agent
- `ACTOR_AGENT`: the agent receiving the task

### Step 2: Run the governance check

```bash
echo '{"tool_name":"ACTION_TYPE","tool_input":PARAMS_JSON}' | bash /Users/haotianliu/.openclaw/workspace/ystar-company/scripts/hook_client_labs.sh
```

### Step 3: Report the result

```
[Y*gov] Governance Check
=================================
Action    : <action_type>
Principal : <principal_agent>
Actor     : <actor_agent>
Decision  : ALLOW / DENY / SKIPPED
Reason    : <reason if DENY or SKIPPED>
=================================
```

## Decision rules

- **ALLOW**: Proceed with the delegation or action.
- **DENY**: Do NOT execute the blocked action. Explain the violation clearly. Suggest a concrete fix.
- **SKIPPED**: Daemon not running — warn user, proceed with caution.

## Important constraints

- You only validate. You do not execute the delegated task.
- A DENY must always include a concrete fix suggestion.
- All decisions are written to .ystar_cieu.db automatically by Y*gov.
