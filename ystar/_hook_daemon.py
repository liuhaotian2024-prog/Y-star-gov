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
import uuid
from pathlib import Path
from typing import Optional

SOCK_PATH = Path(os.environ.get("YSTAR_HOOK_SOCK", "/tmp/ystar_hook.sock"))
PID_FILE = Path("/tmp/ystar_hook_daemon.pid")
LOG_FILE = Path("/tmp/ystar_hook_daemon.log")
BUFFER_SIZE = 65536
SESSION_JSON_PATH = Path(".ystar_session.json")
IDLE_THRESHOLD_SECONDS = 300  # 5 minutes


def _log(msg: str) -> None:
    with LOG_FILE.open("a") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


class HookDaemon:
    """Persistent hook processor. Loads policy once, serves many requests."""

    def __init__(self) -> None:
        self.policy = None
        self.agent_id = ""
        self._session_config_cache = None
        self._session_config_mtime = 0.0
        self._last_user_message_time = time.time()
        self._autonomy_driver = None
        self._residual_loop_engine = None
        self._idle_check_thread = None
        self._file_watch_thread = None
        self._shutdown_flag = False
        self._load_policy()
        self._init_autonomy_driver()
        self._init_residual_loop_engine()
        self._start_idle_monitor()
        self._start_file_watcher()

    def _load_policy(self) -> None:
        """Load policy from AGENTS.md (once at startup)."""
        try:
            agents_md = Path("AGENTS.md")
            if agents_md.exists():
                from ystar import Policy
                with contextlib.redirect_stdout(io.StringIO()), \
                     contextlib.redirect_stderr(io.StringIO()):
                    self.policy = Policy.from_agents_md(str(agents_md), confirm=False)

            # Layer 1: Read agent identity from session config (single source of truth)
            from ystar.session import current_agent
            self.agent_id = current_agent()

            if self.agent_id and self.policy and self.agent_id not in self.policy:
                if "agent" in self.policy._rules:
                    self.policy._rules[self.agent_id] = self.policy._rules["agent"]

            _log(f"Policy loaded: roles={list(self.policy._rules.keys()) if self.policy else 'none'} agent={self.agent_id}")
        except Exception as e:
            _log(f"Policy load error: {e}")

    def _get_session_config(self) -> dict:
        """Load session.json with mtime-based caching. Reload on file change."""
        try:
            if SESSION_JSON_PATH.exists():
                current_mtime = SESSION_JSON_PATH.stat().st_mtime
                if current_mtime > self._session_config_mtime:
                    with SESSION_JSON_PATH.open() as f:
                        self._session_config_cache = json.load(f)
                    self._session_config_mtime = current_mtime
                    _log(f"Session config reloaded (mtime={current_mtime:.0f})")
                return self._session_config_cache or {}
        except Exception as e:
            _log(f"Session config load error: {e}")
        return {}

    def _init_autonomy_driver(self) -> None:
        """Initialize AutonomyEngine for idle-pull and OFF_TARGET detection."""
        try:
            from ystar.governance.autonomy_engine import AutonomyEngine
            from ystar.governance.cieu_store import CIEUStore
            # Use default priority_brief path (reports/priority_brief.md)
            cieu_store = CIEUStore()  # Default .ystar_cieu.db
            self._autonomy_driver = AutonomyEngine(
                mode="desire-driven",
                cieu_store=cieu_store
            )
            _log("AutonomyEngine initialized")
        except Exception as e:
            _log(f"AutonomyEngine init error: {e}")
            self._autonomy_driver = None

    def _init_residual_loop_engine(self) -> None:
        """Initialize ResidualLoopEngine (AMENDMENT-014)."""
        try:
            if not self._autonomy_driver:
                _log("RLE init skipped: no AutonomyEngine")
                return

            from ystar.governance.residual_loop_engine import ResidualLoopEngine
            from ystar.governance.cieu_store import CIEUStore

            cieu_store = CIEUStore()  # Same store as autonomy_driver

            # Target provider: extract Y* from event params
            def target_provider(event):
                return event.get("params", {}).get("target_y_star")

            self._residual_loop_engine = ResidualLoopEngine(
                autonomy_engine=self._autonomy_driver,
                cieu_store=cieu_store,
                target_provider=target_provider,
                max_iterations=10,
                convergence_epsilon=0.05,
                damping_gamma=0.9,
            )
            _log("ResidualLoopEngine initialized")
        except Exception as e:
            _log(f"RLE init error: {e}")
            self._residual_loop_engine = None

    def _start_idle_monitor(self) -> None:
        """Start background thread that monitors for idle periods."""
        def monitor():
            while not self._shutdown_flag:
                time.sleep(60)  # Check every minute
                if self._shutdown_flag:
                    break

                idle_time = time.time() - self._last_user_message_time
                if idle_time >= IDLE_THRESHOLD_SECONDS and self._autonomy_driver:
                    self._trigger_idle_pull()
                    # Reset timer to avoid repeated pulls
                    self._last_user_message_time = time.time()

        self._idle_check_thread = threading.Thread(target=monitor, daemon=True)
        self._idle_check_thread.start()
        _log("Idle monitor started")

    def _start_file_watcher(self) -> None:
        """
        Start background thread to watch governance files for changes.

        Monitors:
        - .ystar_session.json (agent_id changes)
        - .ystar_active_agent (active agent changes)
        - AGENTS.md (policy rule changes)

        On change: invalidate daemon caches, reload identity/policy.
        Layer 1 (AMENDMENT-015 + exp7 backport): Eliminates daemon cache lock.
        Fail-open: watcher errors do not crash daemon.
        """
        def watcher():
            # Track mtimes for all three files
            agents_md = Path("AGENTS.md")
            active_agent = Path(".ystar_active_agent")

            mtimes = {
                "session_json": SESSION_JSON_PATH.stat().st_mtime if SESSION_JSON_PATH.exists() else 0,
                "agents_md": agents_md.stat().st_mtime if agents_md.exists() else 0,
                "active_agent": active_agent.stat().st_mtime if active_agent.exists() else 0,
            }

            while not self._shutdown_flag:
                time.sleep(2)  # Poll every 2s (FSEvents would be more efficient but requires pyobjc)
                if self._shutdown_flag:
                    break

                try:
                    # Check .ystar_session.json
                    if SESSION_JSON_PATH.exists():
                        current_mtime = SESSION_JSON_PATH.stat().st_mtime
                        if current_mtime > mtimes["session_json"]:
                            # File changed, reload agent_id
                            from ystar.session import current_agent
                            new_agent_id = current_agent()
                            if new_agent_id != self.agent_id:
                                _log(f"[watcher] Agent ID changed: {self.agent_id} → {new_agent_id}")
                                self.agent_id = new_agent_id
                                # Update policy mapping if needed
                                if self.policy and self.agent_id not in self.policy:
                                    if "agent" in self.policy._rules:
                                        self.policy._rules[self.agent_id] = self.policy._rules["agent"]
                            mtimes["session_json"] = current_mtime

                    # Check AGENTS.md
                    if agents_md.exists():
                        current_mtime = agents_md.stat().st_mtime
                        if current_mtime > mtimes["agents_md"]:
                            _log(f"[watcher] AGENTS.md changed, reloading policy")
                            self._load_policy()  # Full policy reload
                            mtimes["agents_md"] = current_mtime

                    # Check .ystar_active_agent
                    if active_agent.exists():
                        current_mtime = active_agent.stat().st_mtime
                        if current_mtime > mtimes["active_agent"]:
                            # Active agent file changed, reload agent_id
                            from ystar.session import current_agent
                            new_agent_id = current_agent()
                            if new_agent_id != self.agent_id:
                                _log(f"[watcher] Active agent file changed: {self.agent_id} → {new_agent_id}")
                                self.agent_id = new_agent_id
                                # Update policy mapping if needed
                                if self.policy and self.agent_id not in self.policy:
                                    if "agent" in self.policy._rules:
                                        self.policy._rules[self.agent_id] = self.policy._rules["agent"]
                            mtimes["active_agent"] = current_mtime

                except Exception as e:
                    # Fail-open: log error but don't crash daemon
                    _log(f"[watcher] ERROR: {e}")

        self._file_watch_thread = threading.Thread(target=watcher, daemon=True)
        self._file_watch_thread.start()
        _log("File watcher started (polling session.json/AGENTS.md/.ystar_active_agent every 2s)")

    def _trigger_idle_pull(self) -> None:
        """Pull next action from AutonomyDriver and emit CIEU event."""
        try:
            if not self.agent_id or not self._autonomy_driver:
                return

            action = self._autonomy_driver.pull_next_action(self.agent_id)
            if action:
                _log(f"[IDLE_PULL] {self.agent_id} → {action.description[:60]}")
                self._write_cieu_event("IDLE_PULL_TRIGGERED", {
                    "agent_id": self.agent_id,
                    "action_id": action.action_id,
                    "description": action.description,
                    "why": action.why,
                    "verify": action.verify,
                    "priority": action.priority,
                    "idle_duration_s": time.time() - self._last_user_message_time
                })
        except Exception as e:
            _log(f"[IDLE_PULL] error: {e}")

    def _detect_off_target(self, current_action: str) -> None:
        """Detect if current action is OFF_TARGET and emit warning."""
        try:
            if not self.agent_id or not self._autonomy_driver:
                return

            is_off_target = self._autonomy_driver.detect_off_target(
                self.agent_id, current_action
            )
            if is_off_target:
                _log(f"[OFF_TARGET] {self.agent_id}: {current_action[:60]}")
                self._write_cieu_event("OFF_TARGET_WARNING", {
                    "agent_id": self.agent_id,
                    "current_action": current_action,
                })
        except Exception as e:
            _log(f"[OFF_TARGET] detection error: {e}")

    def _write_cieu_event(self, event_type: str, params: dict) -> None:
        """Write event to CIEU store (fail-open)."""
        try:
            # Try to get CIEU store from omission_engine
            if hasattr(self._autonomy_driver, 'omission_store'):
                store = self._autonomy_driver.omission_store
                if hasattr(store, 'cieu_store') and store.cieu_store:
                    import uuid
                    record = {
                        "event_id": str(uuid.uuid4()),
                        "session_id": "hook_daemon",
                        "agent_id": self.agent_id,
                        "event_type": event_type,
                        "decision": "info",
                        "evidence_grade": "ops",
                        "created_at": time.time(),
                        "seq_global": time.time_ns() // 1000,
                        "params": params,
                        "violations": [],
                        "drift_detected": False,
                        "human_initiator": self.agent_id,
                    }
                    store.cieu_store.write_dict(record)
        except Exception:
            pass  # fail-open

    def _trigger_residual_loop(self, payload: dict, ygov_result: dict) -> None:
        """Trigger ResidualLoopEngine on PostToolUse (AMENDMENT-014)."""
        try:
            # Build CIEU event from payload + ygov_result
            event = {
                "event_id": str(uuid.uuid4()),
                "session_id": payload.get("session_id", "hook_daemon"),
                "agent_id": self.agent_id,
                "event_type": payload.get("tool_name", "ToolUse"),
                "decision": ygov_result.get("action", "allow"),
                "evidence_grade": "ops",
                "created_at": time.time(),
                "seq_global": time.time_ns() // 1000,
                "params": {
                    "tool_input": payload.get("tool_input", {}),
                    "tool_result": payload.get("tool_result", {}),
                    "target_y_star": payload.get("tool_input", {}).get("target_y_star"),
                    "y_actual": payload.get("tool_result", {}).get("output"),
                },
                "violations": ygov_result.get("violations", []),
                "drift_detected": ygov_result.get("drift_detected", False),
                "human_initiator": self.agent_id,
            }
            self._residual_loop_engine.on_cieu_event(event)
        except Exception as e:
            _log(f"[RLE] trigger error: {e}")

    def _update_last_message_time(self, payload: dict) -> None:
        """Update last user message timestamp. Reset idle timer on user interaction."""
        # Check if this is a user-initiated message (not autonomous action)
        # Look for indicators in payload
        tool_name = payload.get("tool_name", "")
        # Any tool call suggests agent is active (responding to user or autonomous action)
        # We reset on any activity to avoid pulling while agent is working
        self._last_user_message_time = time.time()

    def handle(self, payload_json: str) -> str:
        """Process a hook payload, return JSON response."""
        t0 = time.perf_counter()
        try:
            payload = json.loads(payload_json)

            # Update last message timestamp (reset idle timer)
            self._update_last_message_time(payload)

            from ystar.adapters.hook import check_hook
            from ystar.adapters.hook_response import detect_host, convert_ygov_result

            host = detect_host(payload)

            # Reload session config if changed (zero perf cost if unchanged)
            _ = self._get_session_config()

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

            # OFF_TARGET detection (PreToolUse hook timing)
            # Extract action description from tool parameters
            if self._autonomy_driver and payload.get("tool_name"):
                current_action = self._extract_action_description(payload)
                if current_action:
                    self._detect_off_target(current_action)

            # AMENDMENT-014: ResidualLoopEngine — trigger on PostToolUse
            # (after tool execution, check residual and emit next action if needed)
            if self._residual_loop_engine and payload.get("hook_timing") == "PostToolUse":
                self._trigger_residual_loop(payload, ygov_result)

            # AMENDMENT-018: Whitelist MATCH/DRIFT emission (async, fail-open)
            # Check Bash commands against whitelist and emit CIEU events
            if payload.get("tool_name") == "Bash" and cmd:
                threading.Thread(
                    target=self._check_whitelist_async,
                    args=(cmd, self.agent_id),
                    daemon=True
                ).start()

            response = convert_ygov_result(ygov_result, host)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            _log(f"  {elapsed_ms:.1f}ms {payload.get('tool_name','?')} → {'DENY' if response else 'ALLOW'}")
            return json.dumps(response)

        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            _log(f"  {elapsed_ms:.1f}ms ERROR: {e}")
            return "{}"

    def _check_whitelist_async(self, command: str, agent_id: str) -> None:
        """Async whitelist check + CIEU emission (AMENDMENT-018)."""
        try:
            from ystar._whitelist_emit import check_whitelist_and_emit
            check_whitelist_and_emit(command, agent_id)
        except Exception as e:
            _log(f"[WHITELIST] emit error: {e}")

    def _extract_action_description(self, payload: dict) -> Optional[str]:
        """Extract meaningful action description from tool payload."""
        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input", {})

        # Try to get description field first
        if "description" in tool_input:
            return tool_input["description"]

        # Fallback: construct from tool_name + key parameters
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            return f"bash: {cmd[:80]}" if cmd else None
        elif tool_name == "Edit":
            file_path = tool_input.get("file_path", "")
            return f"edit {file_path}" if file_path else None
        elif tool_name == "Write":
            file_path = tool_input.get("file_path", "")
            return f"write {file_path}" if file_path else None
        elif tool_name == "Read":
            file_path = tool_input.get("file_path", "")
            return f"read {file_path}" if file_path else None

        return f"{tool_name} tool"


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
        daemon._shutdown_flag = True
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
