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

        with debug_log.open("a") as f:
            f.write(json.dumps(payload, default=str)[:500] + "\n")

        from ystar.adapters.hook import check_hook

        # Build policy non-interactively
        policy = None
        agents_md = Path("AGENTS.md")
        if agents_md.exists():
            from ystar import Policy
            policy = Policy.from_agents_md(str(agents_md), confirm=False)

        # Register real agent identity
        agent_id = _read_agent_id()
        if agent_id and policy is not None and agent_id not in policy:
            if "agent" in policy._rules:
                policy._rules[agent_id] = policy._rules["agent"]

        result = check_hook(payload, policy, agent_id=agent_id or None)

        with debug_log.open("a") as f:
            f.write(f"  RESULT: {json.dumps(result)[:200]}\n")

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
