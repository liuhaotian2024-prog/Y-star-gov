"""Y*gov PreToolUse hook entry point — called by Claude Code on every tool use."""
import json
import os
import sys
from pathlib import Path

from ystar.adapters.hook import check_hook


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
    payload = json.loads(sys.stdin.read())

    # Build policy with confirm=False (non-interactive hook)
    policy = None
    agents_md = Path("AGENTS.md")
    if agents_md.exists():
        from ystar import Policy
        policy = Policy.from_agents_md(str(agents_md), confirm=False)

    # Register the active agent identity in the policy
    # from_agents_md defaults to role="agent", but the intervention gate
    # rejects generic identities. Copy the contract under the real agent name.
    agent_id = _read_agent_id()
    if agent_id and policy is not None and agent_id not in policy:
        if "agent" in policy._rules:
            policy._rules[agent_id] = policy._rules["agent"]

    result = check_hook(payload, policy, agent_id=agent_id or None)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
