# ystar/cli/doctor_cmd.py — ystar doctor command
"""
Environment diagnostic command.
Moved from ystar/_cli.py for modularization.
"""
import json
import pathlib
import os


def _cmd_doctor(args: list) -> None:
    """
    ystar doctor -- diagnose current environment integrity.
    Checks: session config / hook registration / CIEU writable / omission config
    """
    ok_count = 0
    fail_count = 0

    def ok(msg):
        nonlocal ok_count
        print(f"  ok: {msg}")
        ok_count += 1

    def fail(msg, hint=""):
        nonlocal fail_count
        print(f"  FAIL: {msg}")
        if hint:
            print(f"     -> {hint}")
        fail_count += 1

    def warn(msg):
        print(f"  WARN: {msg}")

    print()
    print("  Y*gov Doctor -- Environment Diagnostic")
    print("  " + "-" * 41)
    print()

    # 1. Check session config
    print("  [1] Session Config")
    session_cfg = None
    for search_dir in [os.getcwd(), str(pathlib.Path.home())]:
        p = pathlib.Path(search_dir) / ".ystar_session.json"
        if p.exists():
            try:
                session_cfg = json.loads(p.read_text())
                ok(f".ystar_session.json found at {p}")
                break
            except Exception as e:
                fail(f".ystar_session.json found but invalid JSON: {e}",
                     "Run: ystar setup --yes")
    if session_cfg is None:
        fail(".ystar_session.json not found",
             "Run: ystar setup --yes")

    # 2. Check hook registration
    print()
    print("  [2] Hook Registration")
    hook_locations = [
        pathlib.Path.home() / ".claude" / "settings.json",
        pathlib.Path.home() / ".config" / "openclaw" / "openclaw.json",
        pathlib.Path.home() / "Library" / "Application Support" / "Claude" / "settings.json",
    ]
    hook_found = False
    for loc in hook_locations:
        if loc.exists():
            try:
                cfg = json.loads(loc.read_text())
                hooks_obj = cfg.get("hooks", {})
                if "ystar" in json.dumps(hooks_obj).lower():
                    ok(f"Hook registered in {loc}")
                    hook_found = True
                    break
                else:
                    warn(f"{loc} exists but no ystar hook found")
            except Exception:
                warn(f"Could not parse {loc}")
    if not hook_found:
        fail("No ystar hook registered in any config location",
             "Run: ystar hook-install")

    # 3. Check CIEU database writable
    print()
    print("  [3] CIEU Database")
    cieu_path = ".ystar_cieu.db"
    if session_cfg:
        cieu_path = session_cfg.get("cieu_db", cieu_path)
    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore(cieu_path)
        stats = store.stats()
        ok(f"CIEU database accessible: {stats['total']} records at {cieu_path}")
        if stats["total"] > 0:
            ok(f"  allow={stats['by_decision'].get('allow',0)}  "
               f"deny={stats['by_decision'].get('deny',0)}  "
               f"deny_rate={stats.get('deny_rate',0):.1%}")
    except Exception as e:
        fail(f"CIEU database not accessible: {e}",
             f"Check path: {cieu_path}")

    # 4. Check AGENTS.md
    print()
    print("  [4] AGENTS.md")
    agents_md = pathlib.Path("AGENTS.md")
    if agents_md.exists():
        lines = agents_md.read_text().splitlines()
        ok(f"AGENTS.md found ({len(lines)} lines)")
        has_deny = any("never" in l.lower() or "deny" in l.lower() or "- /" in l for l in lines)
        if has_deny:
            ok("AGENTS.md contains constraint rules")
        else:
            warn("AGENTS.md exists but may have no constraint rules")
    else:
        fail("AGENTS.md not found in current directory",
             "Create AGENTS.md with governance rules in plain English. Example:\n"
             "\n"
             "         # Governance Rules\n"
             "         - Never access /production\n"
             "         - Never run rm -rf or sudo\n"
             "         - Only write to ./workspace/\n"
             "\n"
             "       Then run 'ystar init' to translate rules to an IntentContract.")

    # 4.5 Check Retroactive Baseline
    print()
    print("  [4.5] Retroactive Baseline")
    baseline_db = pathlib.Path(".ystar_retro_baseline.db")
    if baseline_db.exists():
        try:
            from ystar.governance.retro_store import RetroBaselineStore
            RetroBaselineStore()
            ok(f"Baseline database found at {baseline_db}")
        except Exception as e:
            warn(f"Baseline database exists but may be corrupted: {e}")
    else:
        warn("No baseline found. Run 'ystar setup' to capture baseline.")

    # 5. Hook self-test
    print()
    print("  [5] Hook Self-Test")
    try:
        from ystar.kernel.dimensions import IntentContract
        from ystar.session import Policy
        from ystar.adapters.hook import check_hook
        from unittest.mock import patch

        ic = IntentContract(deny=["/etc"], deny_commands=["rm -rf"])
        policy = Policy({"doctor_agent": ic})
        test_payload = {"tool_name": "Read",
                        "tool_input": {"path": "/etc/passwd"},
                        "agent_id": "doctor_agent",
                        "session_id": "doctor_test"}
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = check_hook(test_payload, policy, agent_id="doctor_agent")
        if result.get("action") == "block":
            ok("Hook self-test passed: /etc/passwd correctly blocked")
        else:
            fail("Hook self-test failed: /etc/passwd was NOT blocked",
                 "Check your AGENTS.md and session config")
    except Exception as e:
        fail(f"Hook self-test error: {e}")

    # Summary
    print()
    print("  " + "-" * 41)
    if fail_count == 0:
        print(f"  All {ok_count} checks passed -- Y*gov is healthy")
    else:
        print(f"  {ok_count} passed, {fail_count} failed")
        print("     Run the suggested commands above to fix issues")
    print()
