"""Y*gov PreToolUse hook entry point — ecosystem-neutral.

Detects the host framework automatically and returns the response
in the format the host expects. No host-specific format is hardcoded
here — all formatting is delegated to hook_response.py.
"""
import io
import json
import os
import sys
import contextlib
import traceback
from pathlib import Path


def _read_agent_id() -> str:
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
        from ystar.adapters.hook_response import detect_host, convert_ygov_result

        # Detect host framework from payload
        host = detect_host(payload)

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

        # Defense-in-depth: Bash command content scan
        cmd = payload.get("tool_input", {}).get("command", "")
        if payload.get("tool_name") == "Bash" and cmd and policy and ygov_result == {}:
            contract = policy._rules.get(agent_id) or policy._rules.get("agent")
            if contract:
                from ystar import check as _chk
                cr = _chk(params={"command": cmd, "tool_name": "Bash"}, result={}, contract=contract)
                if not cr.passed:
                    msg = cr.violations[0].message if cr.violations else "deny"
                    ygov_result = {"action": "block", "message": f"[Y*] {msg}"}

        # Convert to host-specific format (ecosystem-neutral)
        response = convert_ygov_result(ygov_result, host)

        with debug_log.open("a") as f:
            f.write(f"  HOST={host} YGOV={json.dumps(ygov_result)[:80]} OUT={json.dumps(response)[:80]}\n")

        print(json.dumps(response))

    except Exception as e:
        with debug_log.open("a") as f:
            f.write(f"  ERROR: {e}\n{traceback.format_exc()[:300]}\n")
        print("{}")


if __name__ == "__main__":
    main()
