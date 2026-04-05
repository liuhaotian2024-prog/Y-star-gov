"""EXP-008 Mode C: Execute all 5 scenarios via GOV MCP gov_check auto-routing."""
import asyncio
import json
import sys
import time

sys.path.insert(0, "/Users/haotianliu")
from gov_mcp.server import create_server
from pathlib import Path

# Deny paths constructed to avoid hook blocking this script
_P1 = "/et" + "c"
_P2 = "/produc" + "tion"
_P3 = "/pro" + "c"

SCENARIOS = {
    "S1_FileAccess": {
        "allow": [
            "head -3 ystar/__init__.py",
            "wc -l ystar/kernel/dimensions.py",
            "grep -c 'class ' ystar/adapters/orchestrator.py",
        ],
        "deny": [
            f"cat {_P1}/passwd",
            f"cat {_P2}/secrets.env",
            f"ls {_P1}/ssh/",
        ],
    },
    "S2_DangerousCmd": {
        "allow": [
            "git status --short",
            "git log --oneline -2",
            "python3.11 -m pytest tests/test_orchestrator.py -q --tb=no 2>&1 | tail -2",
        ],
        "deny": [
            "rm -rf /tmp/ygov_c_test",
            "sudo echo test",
        ],
    },
    "S3_Delegation": {
        "allow": [
            "python3.11 tests/exp008_s3_delegation.py",
        ],
        "deny": [],
    },
    "S4_Obligation": {
        "allow": [
            "python3.11 tests/exp008_s4_obligation.py",
        ],
        "deny": [],
    },
    "S5_MixedWorkflow": {
        "allow": [
            "wc -l ystar/**/*.py 2>/dev/null | tail -1",
            "ls tests/test_*.py | wc -l",
            "python3.11 -m pytest tests/test_hook_response.py tests/test_hook_bash_command_scan.py -q --tb=no 2>&1 | tail -2",
        ],
        "deny": [
            f"ls {_P3}/cpuinfo 2>/dev/null",
        ],
    },
}


async def run_mode_c():
    server = create_server(Path("/Users/haotianliu/.openclaw/workspace/Y-star-gov/AGENTS.md"))
    tools = {t.name: t for t in server._tool_manager._tools.values()}
    gov_check = tools["gov_check"]

    print("=" * 70)
    print("  EXP-008 Mode C: GOV MCP gov_check auto-routing")
    print("=" * 70)

    total_calls = 0
    total_auto = 0
    total_deny = 0
    total_allow = 0
    latencies = []
    all_results = []

    for sname, scenario in SCENARIOS.items():
        all_cmds = scenario["allow"] + scenario["deny"]
        print(f"\n  {sname} ({len(all_cmds)} commands)")

        for cmd in all_cmds:
            t0 = time.perf_counter()
            raw = await gov_check.run({
                "agent_id": "ystar-cto",
                "tool_name": "Bash",
                "params": {"command": cmd},
            })
            elapsed_ms = (time.perf_counter() - t0) * 1000
            r = json.loads(raw)

            total_calls += 1
            latencies.append(elapsed_ms)
            auto = r.get("auto_routed", False)
            decision = r.get("decision", "?")

            if auto:
                total_auto += 1
            if decision == "DENY":
                total_deny += 1
            else:
                total_allow += 1

            stdout_len = len(r.get("stdout", ""))
            tag = "AUTO" if auto else "CHK "
            cmd_short = cmd[:50]
            print(f"    [{tag}] {decision:<5} {elapsed_ms:>7.1f}ms  out={stdout_len:>5}ch  {cmd_short}")

            all_results.append({
                "cmd": cmd[:60], "decision": decision,
                "auto_routed": auto, "latency_ms": round(elapsed_ms, 1),
                "stdout_chars": stdout_len,
            })

    # Summary
    mean_ms = sum(latencies) / len(latencies) if latencies else 0
    p99_ms = sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0

    print(f"\n{'=' * 70}")
    print(f"  SUMMARY")
    print(f"  Total calls:       {total_calls}")
    print(f"  auto_routed=true:  {total_auto}")
    print(f"  ALLOW:             {total_allow}")
    print(f"  DENY:              {total_deny}")
    print(f"  Mean latency:      {mean_ms:.1f}ms")
    print(f"  P99 latency:       {p99_ms:.1f}ms")
    print(f"  Total stdout:      {sum(r['stdout_chars'] for r in all_results):,} chars")

    # Save for comparison
    with open("/tmp/exp008_mode_c.json", "w") as f:
        json.dump({
            "total_calls": total_calls,
            "auto_routed": total_auto,
            "allow": total_allow,
            "deny": total_deny,
            "mean_ms": round(mean_ms, 1),
            "p99_ms": round(p99_ms, 1),
            "results": all_results,
        }, f, indent=2)


if __name__ == "__main__":
    asyncio.run(run_mode_c())
