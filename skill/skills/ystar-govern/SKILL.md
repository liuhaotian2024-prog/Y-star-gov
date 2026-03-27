---
name: ystar-govern
description: >
  Y*gov multi-agent governance. Use automatically when: spawning a subagent,
  handing off a task between agents, delegating work to a specialist agent,
  or when any agent is about to access paths/commands that may violate policy.
  Triggers include: subagent spawn, handoff, delegation, agent teams,
  Task tool invocation, permission boundary check, compliance validation.
  Also use when user mentions: governance, compliance, audit, policy check,
  access control, delegation chain, CIEU, ystar.
allowed-tools: Bash, Read
---

# Y*gov Governance Check

You are enforcing Y*gov runtime governance. Your job is to validate compliance **before** any delegation or high-risk action executes.

## When this skill activates

This skill runs automatically when Claude Code is about to:
- Spawn a subagent (Task tool, Agent Teams)
- Hand off a task to another agent
- Execute a high-risk operation (file write, bash command, web fetch)
- Delegate work across an agent boundary

## Step 1: Check if Y*gov is installed

```bash
python3 -c "import ystar; print('Y*gov', ystar.__version__)" 2>/dev/null || echo "NOT_INSTALLED"
```

**If NOT_INSTALLED:** Inform the user Y*gov is not installed and skip to Step 4.

## Step 2: Load the governance contract

```bash
# Check for AGENTS.md (governance rules)
if [ -f "AGENTS.md" ]; then
  echo "CONTRACT_FOUND"
  head -80 AGENTS.md
else
  echo "NO_CONTRACT — governance check skipped (no AGENTS.md)"
fi
```

**If NO_CONTRACT:** Warn the user that no governance contract exists. Suggest running `/ystar-governance:ystar-setup` to create one. Proceed without blocking.

## Step 3: Run the governance check

Run the check script:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/ystar-govern/check.py" \
  --action "$ACTION_TYPE" \
  --principal "$PRINCIPAL_AGENT" \
  --actor "$ACTOR_AGENT" \
  --params "$ACTION_PARAMS"
```

Where:
- `ACTION_TYPE`: what is happening (subagent_spawn / handoff / file_write / bash_exec)
- `PRINCIPAL_AGENT`: the delegating agent (usually "orchestrator" or "main")
- `ACTOR_AGENT`: the agent receiving the task (subagent name or "self")
- `ACTION_PARAMS`: JSON string of relevant parameters (path, command, etc.)

If the script is unavailable, run the inline check:

```bash
python3 -c "
import json, sys, os

action = os.environ.get('YSTAR_ACTION', 'unknown')
principal = os.environ.get('YSTAR_PRINCIPAL', 'main')
actor = os.environ.get('YSTAR_ACTOR', 'subagent')

try:
    from ystar.kernel.dimensions import IntentContract
    from ystar.session import Policy
    from ystar.adapters.hook import check_hook

    if not os.path.exists('AGENTS.md'):
        print(json.dumps({'decision': 'ALLOW', 'reason': 'no AGENTS.md'}))
        sys.exit(0)

    policy = Policy.from_agents_md('AGENTS.md')
    payload = {
        'tool_name': action,
        'tool_input': json.loads(os.environ.get('YSTAR_PARAMS', '{}')),
        'agent_id': principal,
        'session_id': os.environ.get('YSTAR_SESSION_ID', 'default'),
    }
    result = check_hook(payload, policy, agent_id=principal)
    if result.get('action') == 'block':
        print(json.dumps({'decision': 'DENY', 'reason': result.get('message', '')}))
    else:
        print(json.dumps({'decision': 'ALLOW'}))
except Exception as e:
    print(json.dumps({'decision': 'ALLOW', 'warning': str(e)}))
"
```

## Step 4: Report the result

Always output a governance report in this format:

```
[Y*gov] Governance Check
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Action    : <action_type>
Principal : <principal_agent>
Actor     : <actor_agent>
Decision  : ✅ ALLOW  /  ❌ DENY  /  ⚠️ SKIPPED
Reason    : <reason if DENY or SKIPPED>
CIEU      : <record ID if written>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Decision rules

- **ALLOW**: Proceed with the delegation or action.
- **DENY**: Do NOT execute the blocked action. Explain the violation clearly. Suggest what the actor should do instead (e.g., "use a path within `./workspace/` instead of `/etc/`").
- **SKIPPED**: Y*gov not installed or no contract — warn user, proceed.

## Important constraints

- You only validate. You do not execute the delegated task.
- You do not modify code, files, or configuration.
- A DENY must always include a concrete fix suggestion.
- All decisions are written to `.ystar_cieu.db` automatically by Y*gov.
