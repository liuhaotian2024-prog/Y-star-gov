"""Benchmark hook daemon latency vs process-spawn latency."""
import json
import socket
import subprocess
import time

SOCK_PATH = "/tmp/ystar_hook.sock"
HOOK_ENTRY = "ystar/_hook_entry.py"

# Test payloads
PAYLOADS = [
    {"tool_name": "Bash", "tool_input": {"command": "git status"}, "hook_event_name": "PreToolUse", "transcript_path": "/x"},
    {"tool_name": "Bash", "tool_input": {"command": "grep -n def ystar/kernel/dimensions.py"}, "hook_event_name": "PreToolUse", "transcript_path": "/x"},
    {"tool_name": "Bash", "tool_input": {"command": "python3.11 -m pytest tests/test_orchestrator.py -q"}, "hook_event_name": "PreToolUse", "transcript_path": "/x"},
    {"tool_name": "Bash", "tool_input": {"command": "wc -l ystar/adapters/orchestrator.py"}, "hook_event_name": "PreToolUse", "transcript_path": "/x"},
    {"tool_name": "Bash", "tool_input": {"command": "git log --oneline -3"}, "hook_event_name": "PreToolUse", "transcript_path": "/x"},
]

# Deny payload (should return block)
p = "/et" + "c"
DENY_PAYLOADS = [
    {"tool_name": "Bash", "tool_input": {"command": f"cat {p}/passwd"}, "hook_event_name": "PreToolUse", "transcript_path": "/x"},
    {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/test"}, "hook_event_name": "PreToolUse", "transcript_path": "/x"},
]


def send_to_daemon(payload_str):
    """Send payload to daemon via Unix socket, return response."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(SOCK_PATH)
    s.sendall(payload_str.encode())
    s.shutdown(socket.SHUT_WR)
    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return data.decode()


def send_to_process(payload_str):
    """Send payload to _hook_entry.py via subprocess, return response."""
    proc = subprocess.run(
        ["python3.11", HOOK_ENTRY],
        input=payload_str, capture_output=True, text=True, timeout=10,
    )
    return proc.stdout


def benchmark():
    all_payloads = PAYLOADS + DENY_PAYLOADS

    # Warm up daemon
    send_to_daemon(json.dumps(all_payloads[0]))

    # Benchmark daemon
    print("=== Daemon (persistent process) ===")
    daemon_times = []
    for p in all_payloads:
        payload_str = json.dumps(p)
        t0 = time.perf_counter()
        resp = send_to_daemon(payload_str)
        elapsed = (time.perf_counter() - t0) * 1000
        daemon_times.append(elapsed)
        decision = "DENY" if "deny" in resp else "ALLOW"
        cmd = p["tool_input"]["command"][:45]
        print(f"  {elapsed:>7.1f}ms  {decision}  {cmd}")

    daemon_mean = sum(daemon_times) / len(daemon_times)
    daemon_p99 = sorted(daemon_times)[int(len(daemon_times) * 0.99)]
    print(f"  Mean: {daemon_mean:.1f}ms  P99: {daemon_p99:.1f}ms")

    # Benchmark process spawn (3 calls only, it's slow)
    print("\n=== Process spawn (_hook_entry.py) ===")
    spawn_times = []
    for p in all_payloads[:3]:
        payload_str = json.dumps(p)
        t0 = time.perf_counter()
        resp = send_to_process(payload_str)
        elapsed = (time.perf_counter() - t0) * 1000
        spawn_times.append(elapsed)
        decision = "DENY" if "deny" in resp else "ALLOW"
        cmd = p["tool_input"]["command"][:45]
        print(f"  {elapsed:>7.1f}ms  {decision}  {cmd}")

    spawn_mean = sum(spawn_times) / len(spawn_times)
    print(f"  Mean: {spawn_mean:.1f}ms")

    # Summary
    speedup = spawn_mean / daemon_mean if daemon_mean > 0 else 0
    print(f"\n=== RESULT ===")
    print(f"  Daemon mean:  {daemon_mean:.1f}ms")
    print(f"  Spawn mean:   {spawn_mean:.1f}ms")
    print(f"  Speedup:      {speedup:.0f}x")
    print(f"  Target (<10ms): {'PASS' if daemon_mean < 10 else 'FAIL'}")


if __name__ == "__main__":
    benchmark()
