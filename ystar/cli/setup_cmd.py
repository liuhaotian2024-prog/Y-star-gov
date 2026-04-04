# ystar/cli/setup_cmd.py — ystar setup & hook-install commands
"""
Setup and hook installation commands.
Moved from ystar/_cli.py for modularization.
"""
import sys
import json
import pathlib


def _generate_delegation_chain_if_needed(project: str, deny_paths: list, deny_cmds: list) -> dict:
    """
    Generate delegation chain if multiple agents detected in .claude/agents/.

    Creates a simple tree structure:
    - First agent becomes root with full permissions
    - Other agents become children with default restricted permissions

    Returns:
        Delegation chain dict (tree structure) or empty dict if not multi-agent setup
    """
    claude_agents_dir = pathlib.Path.home() / ".claude" / "agents"

    if not claude_agents_dir.exists():
        return {}

    agents = [f.stem for f in claude_agents_dir.glob("*.md")]

    # Only generate delegation chain if multiple agents detected
    if len(agents) <= 1:
        return {}

    from ystar.kernel.dimensions import DelegationContract, DelegationChain, IntentContract

    # Assume first agent is root (typically CEO)
    root_agent = agents[0]

    # Create root node with full permissions
    root_contract = DelegationContract(
        principal="system",
        actor=root_agent,
        contract=IntentContract(
            name=f"{root_agent}_root",
            deny=deny_paths,
            deny_commands=deny_cmds,
        ),
        action_scope=[],  # Empty = unrestricted
        children=[],
    )

    # Create child nodes for other agents with default restrictions
    for agent in agents[1:]:
        child_contract = DelegationContract(
            principal=root_agent,
            actor=agent,
            contract=IntentContract(
                name=f"{agent}_delegated",
                deny=deny_paths + ["/etc", "/root"],  # More restrictive
                deny_commands=deny_cmds + ["sudo"],   # Add sudo restriction
            ),
            action_scope=["Read", "Write", "Bash", "Grep", "Glob"],  # Default tool allowlist
            children=[],
        )
        root_contract.children.append(child_contract)

    chain = DelegationChain(root=root_contract)

    # Validate tree structure
    valid, violations = chain.validate_tree()
    if not valid:
        print(f"  Warning: Delegation chain validation failed: {violations}")
        return {}

    return chain.to_dict()


def _cmd_setup(skip_prompt: bool = False) -> None:
    """
    Interactive .ystar_session.json generation.
    This is the required config for enforce() full governance pipeline.
    """
    import uuid

    print()
    print("  Y* Session Setup")
    print("  " + "-" * 40)
    print()
    print("  This will generate .ystar_session.json in the current directory.")
    print("  Y* hook reads this file on startup to enable the full governance pipeline.")
    print()

    default_name = pathlib.Path.cwd().name
    if skip_prompt:
        project = default_name
        print(f"  Project name: {project}")
    else:
        project = input(f"  Project name [{default_name}]: ").strip() or default_name
    session_id = f"{project}_{uuid.uuid4().hex[:8]}"

    if skip_prompt:
        cieu_db = ".ystar_cieu.db"
        print(f"  CIEU DB path: {cieu_db}")
    else:
        cieu_db = input(f"  CIEU DB path [.ystar_cieu.db]: ").strip() or ".ystar_cieu.db"

    print()
    if skip_prompt:
        deny_paths = ["/etc", "/root", "/production"]
        print(f"  Deny paths: {deny_paths}")
    else:
        print("  Deny paths (comma-separated, enter for default):")
        raw_deny = input("  [/etc,/root,/production]: ").strip()
        deny_paths = ([p.strip() for p in raw_deny.split(",") if p.strip()]
                      if raw_deny else ["/etc", "/root", "/production"])

    if skip_prompt:
        deny_cmds = ["rm -rf", "sudo", "DROP TABLE"]
        print(f"  Deny commands: {deny_cmds}")
    else:
        print("  Deny commands (comma-separated):")
        raw_cmds = input("  [rm -rf,sudo,DROP TABLE]: ").strip()
        deny_cmds = ([c.strip() for c in raw_cmds.split(",") if c.strip()]
                     if raw_cmds else ["rm -rf", "sudo", "DROP TABLE"])

    print()
    if skip_prompt:
        complaint_timeout = 300.0
        print(f"  Obligation timing: respond_to_complaint={complaint_timeout}s")
    else:
        print("  Obligation timing (seconds, 0=disable):")
        complaint_secs = input("  respond_to_complaint [300]: ").strip()
        try:
            complaint_timeout = float(complaint_secs) if complaint_secs else 300.0
        except ValueError:
            complaint_timeout = 300.0

    obligation_timing = {}
    if complaint_timeout > 0:
        obligation_timing["respond_to_complaint"] = complaint_timeout

    session_config = {
        "session_id": session_id,
        "cieu_db":    cieu_db,
        "contract": {
            "name":               f"{project}_policy",
            "deny":               deny_paths,
            "deny_commands":      deny_cmds,
            "obligation_timing":  obligation_timing,
        }
    }

    # ── NEW v0.48: Generate delegation_chain if multiple agents detected ──
    delegation_chain = _generate_delegation_chain_if_needed(project, deny_paths, deny_cmds)
    if delegation_chain:
        session_config["delegation_chain"] = delegation_chain
        print(f"  Generated delegation chain for multi-agent setup")

    out_path = pathlib.Path(".ystar_session.json")
    out_path.write_text(json.dumps(session_config, ensure_ascii=False, indent=2))

    print()
    print(f"  Done: {out_path}")
    print(f"     session_id: {session_id}")
    print(f"     cieu_db:    {cieu_db}")
    print(f"     deny:       {deny_paths}")
    print(f"     commands:   {deny_cmds}")
    if obligation_timing:
        print(f"     obligations: {obligation_timing}")
    print()

    from ystar._cli import _run_retroactive_baseline
    _run_retroactive_baseline(session_config["contract"], skip_prompt=skip_prompt)
    print()

    print("  Next: ystar hook-install")
    print()


def _cmd_hook_install() -> None:
    """Register Y* PreToolUse hook in settings.json."""
    print()
    print("  Y* Hook Install")
    print("  " + "-" * 40)
    print()

    candidate_paths = [
        pathlib.Path.home() / ".claude" / "settings.json",
        pathlib.Path.home() / ".config" / "openclaw" / "openclaw.json",
        pathlib.Path.home() / "Library" / "Application Support" / "Claude" / "settings.json",
    ]

    settings_path = None
    for p in candidate_paths:
        if p.exists():
            settings_path = p
            print(f"  Found existing config: {p}")
            break
    if settings_path is None:
        settings_path = candidate_paths[0]
        print(f"  No existing config found, will create: {settings_path}")

    python_exec = sys.executable
    if sys.platform == "win32":
        python_exec = python_exec.replace("\\", "/")

    hook_script = (
        "import json,sys;"
        "from ystar import Policy;"
        "from ystar.adapters.hook import check_hook;"
        "p=json.loads(sys.stdin.read());"
        "policy=Policy.from_agents_md('AGENTS.md',confirm=False) if __import__('pathlib').Path('AGENTS.md').exists() "
        "else Policy({});"
        "r=check_hook(p,policy);"
        "print(json.dumps(r))"
    )

    # Windows: Create a .bat wrapper to avoid cmd.exe quoting issues
    if sys.platform == "win32":
        wrapper_path = pathlib.Path.home() / ".claude" / "ystar_hook_wrapper.bat"
        wrapper_path.parent.mkdir(parents=True, exist_ok=True)

        # Write a .bat file that receives stdin and runs the Python hook script
        wrapper_content = f'@echo off\n{python_exec} -c "{hook_script.replace(chr(34), chr(34)+chr(34))}"'
        wrapper_path.write_text(wrapper_content, encoding="utf-8")

        ystar_hook = {
            "type":    "command",
            "command": str(wrapper_path).replace("\\", "/"),
        }
    else:
        ystar_hook = {
            "type":    "command",
            "command": f"MSYS_NO_PATHCONV=1 {python_exec} -c '{hook_script}'",
        }

    hook_entry = {
        "matcher": "",
        "hooks":   [ystar_hook],
    }

    existing = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except Exception:
            existing = {}

    existing_hooks = existing.get("hooks", {})
    pre_tool_use   = existing_hooks.get("PreToolUse", [])
    already_installed = any(
        "ystar" in str(h.get("hooks", []))
        for h in pre_tool_use
        if isinstance(h, dict)
    )

    if already_installed:
        print("  Y* hook already installed.")
        print(f"     Config: {settings_path}")
    else:
        pre_tool_use.insert(0, hook_entry)
        existing.setdefault("hooks", {})["PreToolUse"] = pre_tool_use
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
        print(f"  Hook written to {settings_path}")

    print()
    print("  [Self-test] Sending test payload...")
    try:
        from ystar.kernel.dimensions import IntentContract
        from ystar.session import Policy
        from ystar.adapters.hook import check_hook
        from unittest.mock import patch

        ic = IntentContract(deny=["/etc"], deny_commands=["rm -rf"])
        policy = Policy({"test_agent": ic})
        bad_payload  = {"tool_name": "Read", "tool_input": {"path": "/etc/passwd"},
                        "agent_id": "test_agent", "session_id": "install_test"}
        good_payload = {"tool_name": "Read", "tool_input": {"path": "/workspace/ok.py"},
                        "agent_id": "test_agent", "session_id": "install_test"}

        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            bad_result  = check_hook(bad_payload, policy, agent_id="test_agent")
            good_result = check_hook(good_payload, policy, agent_id="test_agent")

        if bad_result.get("action") == "block" and good_result == {}:
            print("  Self-test passed: /etc/passwd blocked, /workspace/ok.py allowed")
        else:
            print("  Self-test anomaly:")
            print(f"     /etc/passwd -> {bad_result}")
            print(f"     /workspace/ -> {good_result}")
    except Exception as e:
        print(f"  Self-test skipped: {e}")

    print()
    print("  Done. Restart Claude Code / OpenClaw to activate.")
    print()
