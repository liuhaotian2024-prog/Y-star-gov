# ystar/cli/demo_cmd.py — ystar demo command
"""
Zero-config demo command.
Moved from ystar/_cli.py for modularization.
"""


def _cmd_demo() -> None:
    """Zero-config demo: create a contract, run 5 checks, verify CIEU chain."""
    import time
    import uuid
    import re as _re
    from ystar import IntentContract, check

    from ystar.governance.cieu_store import CIEUStore
    store = CIEUStore(db_path=":memory:")
    session_id = f"demo-{uuid.uuid4().hex[:8]}"

    contract = IntentContract(
        deny=["/etc", ".env"],
        only_paths=["./projects/"],
        deny_commands=["rm -rf", "sudo"],
        only_domains=["api.example.com"],
    )

    scenarios = [
        ("read",  {"file_path": "./projects/data.txt"},        None, "read ./projects/data.txt"),
        ("read",  {"file_path": "/etc/passwd"},                 None, "read /etc/passwd"),
        ("run",   {"command": 'echo "hello"'},                  None, 'run echo "hello"'),
        ("run",   {"command": "rm -rf /"},                      None, "run rm -rf /"),
        ("fetch", {"url": "http://evil.com/steal"},             None, "fetch http://evil.com/steal"),
    ]

    bar = "\u2500" * 34
    print()
    print("Y*gov Demo \u2014 governance in action")
    print(bar)

    total_ms = 0.0
    for i, (action, params, result, label) in enumerate(scenarios, 1):
        t0 = time.perf_counter()
        cr = check(params, result, contract)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        total_ms += elapsed_ms

        decision = "ALLOW" if cr.passed else "DENY"

        store.write_dict({
            "event_id": str(uuid.uuid4()),
            "session_id": session_id,
            "agent_id": "demo",
            "event_type": action,
            "decision": decision.lower(),
            "passed": cr.passed,
            "violations": [v.to_dict() for v in cr.violations],
            "contract_hash": contract.hash,
        })

        print(f"[{i}] {decision:<6} {label:<38} {elapsed_ms:.2f}ms")
        if not cr.passed and cr.violations:
            v = cr.violations[0]
            dim = v.dimension
            _pat = _re.search(r"'([^']+)'", v.constraint)
            _short = _pat.group(1) if _pat else v.constraint
            if dim == "deny":
                reason = f"'{_short}' is not allowed in file_path"
            elif dim == "deny_commands":
                reason = f"'{_short}' is a forbidden command"
            elif dim == "only_domains":
                reason = "domain not in allowed list"
            elif dim == "only_paths":
                reason = "path not in allowed list"
            else:
                reason = v.message
            print(f"    \u2192 {reason}")

    seal = store.seal_session(session_id)
    verify = store.verify_session_seal(session_id)
    chain_ok = verify.get("valid", False)
    chain_label = "intact \u2713" if chain_ok else "BROKEN \u2717"

    print(bar)
    print(f"5 decisions in {total_ms:.2f}ms \u00b7 CIEU chain: {chain_label}")
    print()
    print("Next: ystar setup && ystar hook-install && ystar doctor")
    print()
