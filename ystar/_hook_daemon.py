"""Y*gov hook daemon — persistent process, eliminates per-call Python startup.

Instead of spawning a fresh Python interpreter for every tool call (~1.4s),
this daemon stays running and processes hook payloads over a Unix socket.

Usage:
  Start:  python3.11 -m ystar._hook_daemon start
  Stop:   python3.11 -m ystar._hook_daemon stop
  Status: python3.11 -m ystar._hook_daemon status

The hook command in settings.json becomes a thin shell client:
  echo "$PAYLOAD" | nc -U /tmp/ystar_hook.sock

Latency target: <10ms per call (vs 1.4s with process spawn).
"""
from __future__ import annotations

import io
import json
import os
import signal
import socket
import sys
import contextlib
import threading
import time
from pathlib import Path

SOCK_PATH = Path(os.environ.get("YSTAR_HOOK_SOCK", "/tmp/ystar_hook.sock"))
PID_FILE = Path("/tmp/ystar_hook_daemon.pid")
LOG_FILE = Path("/tmp/ystar_hook_daemon.log")
BUFFER_SIZE = 65536


def _log(msg: str) -> None:
    with LOG_FILE.open("a") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


class HookDaemon:
    """Persistent hook processor. Loads policy once, serves many requests."""

    def __init__(self) -> None:
        self.policy = None
        self.agent_id = ""
        self._load_policy()

    def _load_policy(self) -> None:
        """Load policy from AGENTS.md (once at startup)."""
        try:
            agents_md = Path("AGENTS.md")
            if agents_md.exists():
                from ystar import Policy
                with contextlib.redirect_stdout(io.StringIO()), \
                     contextlib.redirect_stderr(io.StringIO()):
                    self.policy = Policy.from_agents_md(str(agents_md), confirm=False)

            marker = Path(".ystar_active_agent")
            if marker.exists():
                self.agent_id = marker.read_text().strip()

            if self.agent_id and self.policy and self.agent_id not in self.policy:
                if "agent" in self.policy._rules:
                    self.policy._rules[self.agent_id] = self.policy._rules["agent"]

            _log(f"Policy loaded: roles={list(self.policy._rules.keys()) if self.policy else 'none'} agent={self.agent_id}")
        except Exception as e:
            _log(f"Policy load error: {e}")

    def handle(self, payload_json: str) -> str:
        """Process a hook payload, return JSON response."""
        t0 = time.perf_counter()
        try:
            payload = json.loads(payload_json)

            from ystar.adapters.hook import check_hook
            from ystar.adapters.hook_response import detect_host, convert_ygov_result

            host = detect_host(payload)

            # Run Y*gov check
            ygov_result = check_hook(payload, self.policy, agent_id=self.agent_id or None)

            # Defense-in-depth: Bash command content scan
            cmd = payload.get("tool_input", {}).get("command", "")
            if payload.get("tool_name") == "Bash" and cmd and self.policy and ygov_result == {}:
                contract = self.policy._rules.get(self.agent_id) or self.policy._rules.get("agent")
                if contract:
                    from ystar import check as _chk
                    cr = _chk(params={"command": cmd, "tool_name": "Bash"}, result={}, contract=contract)
                    if not cr.passed:
                        msg = cr.violations[0].message if cr.violations else "deny"
                        ygov_result = {"action": "block", "message": f"[Y*] {msg}"}

            response = convert_ygov_result(ygov_result, host)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            _log(f"  {elapsed_ms:.1f}ms {payload.get('tool_name','?')} → {'DENY' if response else 'ALLOW'}")
            return json.dumps(response)

        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            _log(f"  {elapsed_ms:.1f}ms ERROR: {e}")
            return "{}"


def _handle_client(conn: socket.socket, daemon: HookDaemon) -> None:
    """Handle a single client connection."""
    try:
        data = b""
        while True:
            chunk = conn.recv(BUFFER_SIZE)
            if not chunk:
                break
            data += chunk
            # Check if we have complete JSON
            try:
                json.loads(data)
                break
            except json.JSONDecodeError:
                continue

        if data:
            response = daemon.handle(data.decode("utf-8", errors="replace"))
            conn.sendall(response.encode("utf-8"))
    except Exception as e:
        _log(f"Client error: {e}")
    finally:
        conn.close()


def start_daemon() -> None:
    """Start the hook daemon."""
    if SOCK_PATH.exists():
        SOCK_PATH.unlink()

    # Write PID
    PID_FILE.write_text(str(os.getpid()))

    daemon = HookDaemon()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(SOCK_PATH))
    server.listen(8)
    # Allow other users to connect
    os.chmod(str(SOCK_PATH), 0o777)

    _log(f"Daemon started: pid={os.getpid()} sock={SOCK_PATH}")
    print(f"Y*gov hook daemon started (pid={os.getpid()}, sock={SOCK_PATH})")

    def shutdown(signum, frame):
        _log("Daemon shutting down")
        server.close()
        SOCK_PATH.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        try:
            conn, _ = server.accept()
            # Handle in thread to avoid blocking
            t = threading.Thread(target=_handle_client, args=(conn, daemon), daemon=True)
            t.start()
        except OSError:
            break


def stop_daemon() -> None:
    """Stop the hook daemon."""
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"Daemon stopped (pid={pid})")
        except ProcessLookupError:
            print(f"Daemon not running (stale pid={pid})")
        PID_FILE.unlink(missing_ok=True)
    else:
        print("Daemon not running")

    SOCK_PATH.unlink(missing_ok=True)


def status_daemon() -> None:
    """Check daemon status."""
    if PID_FILE.exists():
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)
            print(f"Daemon running (pid={pid}, sock={SOCK_PATH})")
        except ProcessLookupError:
            print(f"Daemon not running (stale pid={pid})")
    else:
        print("Daemon not running")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        start_daemon()
    elif cmd == "stop":
        stop_daemon()
    elif cmd == "status":
        status_daemon()
    else:
        print(f"Usage: python -m ystar._hook_daemon [start|stop|status]")
