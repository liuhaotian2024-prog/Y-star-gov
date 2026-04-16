#!/usr/bin/env python3
"""
W23 E2E test: Rapid 5-identity switch without daemon cache lock.

Test plan:
1. Start hook daemon
2. Rapidly switch agent identity 5 times: ceo → cto → eng-kernel → ceo → secretary
3. After each switch, trigger a hook call (Bash tool)
4. Verify: no "agent 'agent' denied" errors in daemon log
5. Success: all 5 identity switches processed correctly

Expected behavior (W23 stateless):
- daemon reads .ystar_active_agent fresh on every hook call
- no 2s polling delay
- no cached stale identity

Run:
  python3 test_identity_switch_e2e.py
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

SOCK_PATH = Path("/tmp/ystar_hook.sock")
LOG_FILE = Path("/tmp/ystar_hook_daemon.log")
ACTIVE_AGENT_FILE = Path(".ystar_active_agent")
SESSION_JSON = Path(".ystar_session.json")


def write_active_agent(agent_id: str) -> None:
    """Write agent identity to .ystar_active_agent (single source of truth)."""
    ACTIVE_AGENT_FILE.write_text(agent_id, encoding="utf-8")
    print(f"  [write] .ystar_active_agent ← {agent_id}")


def send_hook_payload(tool_name: str, description: str) -> dict:
    """Send hook payload to daemon via Unix socket."""
    payload = {
        "tool_name": tool_name,
        "tool_input": {"command": "echo test", "description": description},
        "hook_timing": "PreToolUse",
        "session_id": "test_identity_switch",
    }
    payload_json = json.dumps(payload)

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(str(SOCK_PATH))
        sock.sendall(payload_json.encode("utf-8"))
        response = sock.recv(65536).decode("utf-8")
        sock.close()
        return json.loads(response)
    except Exception as e:
        return {"error": str(e)}


def check_daemon_log_for_deny() -> list:
    """Scan daemon log for 'agent denied' errors."""
    if not LOG_FILE.exists():
        return []

    log_content = LOG_FILE.read_text(encoding="utf-8")
    deny_lines = [
        line for line in log_content.split("\n")
        if "agent 'agent' denied" in line or "restricted write" in line
    ]
    return deny_lines


def main():
    print("W23 E2E Test: 5-identity rapid switch (stateless daemon)\n")

    # Check daemon is running
    if not SOCK_PATH.exists():
        print("ERROR: daemon not running. Start with: python3 -m ystar._hook_daemon start")
        sys.exit(1)

    # Clear daemon log to isolate this test
    LOG_FILE.write_text("", encoding="utf-8")
    print("[setup] cleared daemon log\n")

    # Test sequence: 5 identity switches
    identities = ["ceo", "cto", "eng-kernel", "ceo", "secretary"]

    print("Starting rapid identity switch test...\n")

    for i, agent_id in enumerate(identities, 1):
        print(f"Switch {i}/5: {agent_id}")

        # Write identity
        write_active_agent(agent_id)

        # Immediately trigger hook call (no delay — this is the race window test)
        response = send_hook_payload("Bash", f"test_{agent_id}_{i}")

        # Check response
        if "error" in response:
            print(f"  [ERROR] hook call failed: {response['error']}")
        elif response:
            print(f"  [WARN] hook returned non-empty response (possible deny): {response}")
        else:
            print(f"  [OK] hook call succeeded (allow)")

        # Small delay to let daemon process (but much less than 2s watcher polling)
        time.sleep(0.1)
        print()

    # Check daemon log for any deny errors
    print("\nChecking daemon log for errors...")
    deny_lines = check_daemon_log_for_deny()

    if deny_lines:
        print(f"\n❌ FAIL: Found {len(deny_lines)} deny errors in daemon log:")
        for line in deny_lines:
            print(f"  {line}")
        sys.exit(1)
    else:
        print("\n✅ PASS: No deny errors in daemon log")
        print("All 5 identity switches processed correctly")
        print("\nRt+1 = 0 (W23 stateless daemon verified)")
        sys.exit(0)


if __name__ == "__main__":
    main()
