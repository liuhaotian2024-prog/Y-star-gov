"""Y*gov PreToolUse hook entry point — called by Claude Code on every tool use."""
import json
import os
import sys
import traceback
from pathlib import Path


def _read_agent_id() -> str:
    """Read agent identity from env or marker file."""
    aid = os.environ.get("YSTAR_AGENT_ID", "")
    if aid:
        return aid
    marker = Path(".ystar_active_agent")
    if marker.exists():
        return marker.read_text().strip()
    return ""


def main():
    debug_log = Path("/tmp/ystar_hook_debug.log")
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)

        # Ensure cwd's ystar/ shadows the installed package
        cwd = payload.get("cwd", "")
        if cwd and cwd not in sys.path:
            sys.path.insert(0, cwd)

        with debug_log.open("a") as f:
            f.write(json.dumps(payload, default=str)[:500] + "\n")

        from ystar.adapters.hook import check_hook

        # Build policy non-interactively, suppress ALL stdout from policy loading
        policy = None
        agents_md = Path("AGENTS.md")
        if agents_md.exists():
            import io, contextlib
            from ystar import Policy
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                policy = Policy.from_agents_md(str(agents_md), confirm=False)

        # Register real agent identity
        agent_id = _read_agent_id()
        if agent_id and policy is not None and agent_id not in policy:
            if "agent" in policy._rules:
                policy._rules[agent_id] = policy._rules["agent"]

        # Before check_hook, run our own P0-1.6 check to verify it works
        cmd = payload.get("tool_input", {}).get("command", "")
        pre_check_deny = None
        if payload.get("tool_name") == "Bash" and cmd and policy:
            contract = policy._rules.get(agent_id) or policy._rules.get("agent")
            if contract:
                from ystar import check as _chk
                cr = _chk(params={"command": cmd, "tool_name": "Bash"}, result={}, contract=contract)
                if not cr.passed:
                    pre_check_deny = cr.violations[0].message if cr.violations else "deny"

        result = check_hook(payload, policy, agent_id=agent_id or None)

        # If pre_check found a deny but check_hook returned ALLOW, override
        if pre_check_deny and result == {}:
            result = {
                "action": "block",
                "message": f"[Y*] {pre_check_deny}",
            }

        with debug_log.open("a") as f:
            f.write(f"  AGENT={agent_id} PRE_DENY={pre_check_deny} RESULT: {json.dumps(result)[:200]}\n")

        print(json.dumps(result))

    except Exception as e:
        # Log the error — this is the key: if check_hook crashes, we log WHY
        with debug_log.open("a") as f:
            f.write(f"  ERROR: {e}\n")
            f.write(f"  TRACEBACK: {traceback.format_exc()[:500]}\n")
        # On error, print empty dict (ALLOW) — fail-open
        print("{}")


if __name__ == "__main__":
    main()
