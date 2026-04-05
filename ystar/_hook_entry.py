"""Y*gov PreToolUse hook entry point — called by Claude Code on every tool use.

Claude Code hook protocol:
  Exit 0 + JSON with hookSpecificOutput.permissionDecision = "deny" → BLOCK
  Exit 0 + JSON with hookSpecificOutput.permissionDecision = "allow" → ALLOW
  Exit 2 + stderr message → BLOCK (simple mode)
  Exit 0 + empty/no output → ALLOW
"""
import io
import json
import os
import sys
import contextlib
import traceback
from pathlib import Path

from ystar.adapters.hook import check_hook


def _read_agent_id() -> str:
    aid = os.environ.get("YSTAR_AGENT_ID", "")
    if aid:
        return aid
    marker = Path(".ystar_active_agent")
    if marker.exists():
        return marker.read_text().strip()
    return ""


def _to_claude_code_response(ygov_result: dict) -> dict:
    """Convert Y*gov hook result to Claude Code's expected format.

    Y*gov returns:  {} (allow) or {"action": "block", "message": "..."}
    Claude Code expects:
      {
        "hookSpecificOutput": {
          "hookEventName": "PreToolUse",
          "permissionDecision": "allow" | "deny",
          "permissionDecisionReason": "..."
        }
      }
    """
    if not ygov_result or ygov_result == {}:
        # ALLOW
        return {}

    # DENY — extract reason from Y*gov format
    reason = ygov_result.get("message", "Blocked by Y*gov")
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


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

        # Build policy non-interactively, suppress ALL stdout
        policy = None
        agents_md = Path("AGENTS.md")
        if agents_md.exists():
            from ystar import Policy
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                policy = Policy.from_agents_md(str(agents_md), confirm=False)

        # Register real agent identity
        agent_id = _read_agent_id()
        if agent_id and policy is not None and agent_id not in policy:
            if "agent" in policy._rules:
                policy._rules[agent_id] = policy._rules["agent"]

        # Run Y*gov check (produces CIEU record)
        ygov_result = check_hook(payload, policy, agent_id=agent_id or None)

        # Pre-check: Bash command content scan (defense-in-depth)
        cmd = payload.get("tool_input", {}).get("command", "")
        if payload.get("tool_name") == "Bash" and cmd and policy and ygov_result == {}:
            contract = policy._rules.get(agent_id) or policy._rules.get("agent")
            if contract:
                from ystar import check as _chk
                cr = _chk(params={"command": cmd, "tool_name": "Bash"}, result={}, contract=contract)
                if not cr.passed:
                    msg = cr.violations[0].message if cr.violations else "deny"
                    ygov_result = {"action": "block", "message": f"[Y*] {msg}"}

        # Convert to Claude Code format
        cc_response = _to_claude_code_response(ygov_result)

        with debug_log.open("a") as f:
            f.write(f"  YGOV={json.dumps(ygov_result)[:120]} CC={json.dumps(cc_response)[:120]}\n")

        print(json.dumps(cc_response))

    except Exception as e:
        with debug_log.open("a") as f:
            f.write(f"  ERROR: {e}\n{traceback.format_exc()[:300]}\n")
        # On error, print empty (ALLOW) — fail-open
        print("{}")


if __name__ == "__main__":
    main()
