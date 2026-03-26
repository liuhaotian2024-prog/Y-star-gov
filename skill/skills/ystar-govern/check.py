#!/usr/bin/env python3
"""
Y*gov governance check script.
Called by the ystar-govern skill to validate a delegation or action.

Usage:
    python3 check.py --action <type> --principal <agent> --actor <agent> --params <json>

Exit codes:
    0 = ALLOW
    1 = DENY
    2 = SKIPPED (ystar not installed or no contract)
"""
import argparse
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser(description="Y*gov governance check")
    parser.add_argument("--action",    default="unknown",  help="Action type")
    parser.add_argument("--principal", default="main",     help="Delegating agent ID")
    parser.add_argument("--actor",     default="subagent", help="Receiving agent ID")
    parser.add_argument("--params",    default="{}",       help="Action params (JSON)")
    parser.add_argument("--agents-md", default="AGENTS.md", help="Path to AGENTS.md")
    parser.add_argument("--db",        default=".ystar_cieu.db", help="CIEU database path")
    args = parser.parse_args()

    # ── 1. Check Y*gov installed ──────────────────────────────────────
    try:
        import ystar
        from ystar.kernel.dimensions import IntentContract
        from ystar.session import Policy
        from ystar.adapters.hook import check_hook
    except ImportError:
        result = {
            "decision": "SKIPPED",
            "reason": "Y*gov not installed. Run: pip install ystar",
            "install": "pip install ystar",
        }
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(2)

    # ── 2. Check contract exists ──────────────────────────────────────
    agents_md = args.agents_md
    if not os.path.exists(agents_md):
        result = {
            "decision": "SKIPPED",
            "reason": f"No governance contract found at {agents_md}",
            "hint": "Run /ystar-governance:ystar-setup to create AGENTS.md",
        }
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(2)

    # ── 3. Load policy ────────────────────────────────────────────────
    try:
        policy = Policy.from_agents_md(agents_md)
    except Exception as e:
        result = {
            "decision": "SKIPPED",
            "reason": f"Failed to load policy from {agents_md}: {e}",
        }
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(2)

    # ── 4. Parse params ───────────────────────────────────────────────
    try:
        params = json.loads(args.params) if args.params else {}
    except json.JSONDecodeError:
        params = {}

    # ── 5. Run check ──────────────────────────────────────────────────
    payload = {
        "tool_name":  args.action,
        "tool_input": params,
        "agent_id":   args.principal,
        "session_id": os.environ.get("YSTAR_SESSION_ID", "default"),
    }

    try:
        result = check_hook(payload, policy, agent_id=args.principal)
    except Exception as e:
        output = {
            "decision": "ALLOW",
            "warning":  f"Governance check error (proceeding): {e}",
        }
        print(json.dumps(output, ensure_ascii=False))
        sys.exit(0)

    # ── 6. Write to CIEU ─────────────────────────────────────────────
    cieu_ref = None
    try:
        from ystar.governance.cieu_store import CIEUStore
        import uuid, time
        store = CIEUStore(args.db)
        event_id = uuid.uuid4().hex
        store.write_dict({
            "event_id":    event_id,
            "session_id":  os.environ.get("YSTAR_SESSION_ID", "skill_invoked"),
            "agent_id":    args.principal,
            "event_type":  args.action,
            "decision":    "deny" if result.get("action") == "block" else "allow",
            "passed":      result.get("action") != "block",
            "violations":  result.get("violations", []),
            "contract_hash": "",
            "file_path":   params.get("path", params.get("file_path", "")),
            "command":     params.get("command", ""),
        })
        cieu_ref = event_id[:12]
    except Exception:
        pass

    # ── 7. Output result ─────────────────────────────────────────────
    if result.get("action") == "block":
        output = {
            "decision":   "DENY",
            "reason":     result.get("message", "Policy violation"),
            "violations": result.get("violations", []),
            "cieu_ref":   cieu_ref,
        }
        print(json.dumps(output, ensure_ascii=False))
        sys.exit(1)
    else:
        output = {
            "decision": "ALLOW",
            "cieu_ref": cieu_ref,
        }
        print(json.dumps(output, ensure_ascii=False))
        sys.exit(0)


if __name__ == "__main__":
    main()
