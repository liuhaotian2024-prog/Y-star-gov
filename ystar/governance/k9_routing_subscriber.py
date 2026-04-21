#!/usr/bin/env python3
"""
K9 Routing Subscriber — CIEU Event-Bus Subscriber for K9 Violations
Board 2026-04-16 P0: Pattern B event-driven routing chain implementation.

Polls CIEU database for K9_VIOLATION_DETECTED events, routes to handlers based on routing_target field.

Architecture:
  - Daemon-style subscriber with PID file (/tmp/k9_subscriber.pid)
  - 0.5s polling tick
  - Last processed seq tracking via .k9_subscriber_state.json
  - Fail-open on all exceptions (emit CIEU warning, continue)
  - Graceful shutdown on SIGTERM/SIGINT

Integration:
  - Started by governance_boot.sh (if not running)
  - Can also be started via cron: @reboot k9_routing_subscriber.py start
"""
import json
import os
import signal
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any

# Path setup (always use company root — subscriber is a company-side daemon)
COMPANY_ROOT = Path(os.environ.get("YSTAR_COMPANY_ROOT", os.getcwd()))
YGOV_ROOT = Path(__file__).parent.parent.parent  # Y-star-gov repo root
CIEU_DB = COMPANY_ROOT / ".ystar_cieu.db"
STATE_FILE = COMPANY_ROOT / ".k9_subscriber_state.json"

PID_FILE = Path("/tmp/k9_subscriber.pid")

# CIEU helpers path
sys.path.insert(0, str(COMPANY_ROOT / "scripts"))


# ═══ DAEMON MANAGEMENT ═══

class DaemonContext:
    """Daemon lifecycle management."""

    def __init__(self):
        self.running = True
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

    def _shutdown(self, signum, frame):
        """Graceful shutdown handler."""
        print(f"[K9_SUBSCRIBER] Received signal {signum}, shutting down...", file=sys.stderr)
        self.running = False

    def write_pid(self):
        """Write PID file."""
        PID_FILE.write_text(str(os.getpid()))

    def remove_pid(self):
        """Remove PID file."""
        if PID_FILE.exists():
            PID_FILE.unlink()


# ═══ STATE PERSISTENCE ═══

def get_last_processed_seq() -> int:
    """Read last processed CIEU seq_global from state file."""
    if not STATE_FILE.exists():
        return 0

    try:
        state = json.loads(STATE_FILE.read_text())
        return state.get("last_seq_global", 0)
    except Exception:
        return 0


def save_last_processed_seq(seq_global: int) -> None:
    """Save last processed CIEU seq_global to state file."""
    try:
        state = {
            "last_seq_global": seq_global,
            "updated_at": time.time(),
        }
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        print(f"[K9_SUBSCRIBER] Failed to save state: {e}", file=sys.stderr)


# ═══ CIEU DATABASE ACCESS ═══

def get_cieu_conn() -> Optional[sqlite3.Connection]:
    """Return connection to CIEU database."""
    if not CIEU_DB.exists():
        print(f"[K9_SUBSCRIBER] CIEU DB not found: {CIEU_DB}", file=sys.stderr)
        return None

    try:
        return sqlite3.connect(str(CIEU_DB), timeout=2.0)
    except Exception as e:
        print(f"[K9_SUBSCRIBER] Failed to connect to CIEU DB: {e}", file=sys.stderr)
        return None


def emit_cieu(event_type: str, metadata: dict) -> None:
    """Emit CIEU event (standalone version, doesn't depend on _cieu_helpers)."""
    try:
        conn = get_cieu_conn()
        if not conn:
            return

        cursor = conn.cursor()

        # Get next seq_global
        cursor.execute("SELECT COALESCE(MAX(seq_global), 0) + 1 FROM cieu_events")
        seq_global = cursor.fetchone()[0]

        cursor.execute(
            """
            INSERT INTO cieu_events (
                event_id, seq_global, created_at, session_id, agent_id,
                event_type, decision, passed, task_description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                seq_global,
                time.time(),
                metadata.get("session_id", "k9_subscriber"),
                metadata.get("agent_id", "system:k9_subscriber"),
                event_type,
                metadata.get("decision", "warn"),
                metadata.get("passed", 1),
                json.dumps(metadata, ensure_ascii=False)[:1000],
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[K9_SUBSCRIBER] CIEU emit failed: {e}", file=sys.stderr)


def fetch_new_violations(last_seq: int) -> list:
    """
    Fetch K9_VIOLATION_DETECTED events with seq_global > last_seq.

    Returns:
        List[dict]: Violation events with parsed task_description JSON
    """
    conn = get_cieu_conn()
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT seq_global, event_id, agent_id, task_description
            FROM cieu_events
            WHERE event_type = 'K9_VIOLATION_DETECTED'
            AND seq_global > ?
            ORDER BY seq_global ASC
            """,
            (last_seq,),
        )

        rows = cursor.fetchall()
        conn.close()

        violations = []
        for row in rows:
            seq_global, event_id, agent_id, task_description = row

            # Parse task_description JSON
            try:
                payload = json.loads(task_description)
            except Exception:
                payload = {"raw": task_description}

            violations.append({
                "seq_global": seq_global,
                "event_id": event_id,
                "agent_id": agent_id,
                "payload": payload,
            })

        return violations

    except Exception as e:
        print(f"[K9_SUBSCRIBER] Failed to fetch violations: {e}", file=sys.stderr)
        return []


# ═══ VIOLATION HANDLERS (6 MODULES) ═══

def forget_guard_handler(violation: dict) -> dict:
    """
    ForgetGuard warn handler.
    Action: Emit CIEU event + log to forget_guard trigger log.
    """
    payload = violation["payload"]
    violation_type = payload.get("violation_type", "unknown")

    emit_cieu(
        "FORGET_GUARD_K9_WARN",
        {
            "decision": "warn",
            "passed": 0,
            "violation_type": violation_type,
            "agent_id": violation["agent_id"],
            "drift_detected": 1,
            "drift_category": "k9_routing",
        }
    )

    # Log to forget_guard rule trigger log (create if missing)
    log_path = COMPANY_ROOT.parent / "ystar-company" / "scripts" / "forget_guard_triggers.log"
    try:
        with open(log_path, 'a') as f:
            f.write(f"{time.time()} | WARN | {violation_type} | agent={violation['agent_id']}\n")
    except Exception:
        pass  # fail-open

    return {
        "handled": True,
        "cieu_event": "FORGET_GUARD_K9_WARN",
        "action_taken": "emit_warn_event",
    }


def forget_guard_deny_handler(violation: dict) -> dict:
    """
    ForgetGuard deny handler (Board choice question violation).
    Action: Emit CIEU event + write to Board escalation queue.
    """
    payload = violation["payload"]
    violation_type = payload.get("violation_type", "unknown")

    emit_cieu(
        "FORGET_GUARD_K9_DENY",
        {
            "decision": "deny",
            "passed": 0,
            "violation_type": violation_type,
            "agent_id": violation["agent_id"],
            "drift_detected": 1,
            "drift_category": "choice_question_to_board",
        }
    )

    # Write to warning queue for hook re-injection
    warning_queue_path = COMPANY_ROOT.parent / "ystar-company" / ".ystar_warning_queue.json"
    try:
        if warning_queue_path.exists():
            warnings = json.loads(warning_queue_path.read_text())
        else:
            warnings = []

        warnings.append({
            "type": "FORGET_GUARD_K9_DENY",
            "violation_type": violation_type,
            "agent_id": violation["agent_id"],
            "timestamp": time.time(),
        })

        warning_queue_path.write_text(json.dumps(warnings, indent=2))
    except Exception:
        pass  # fail-open

    return {
        "handled": True,
        "cieu_event": "FORGET_GUARD_K9_DENY",
        "action_taken": "deny_inject_warning",
    }


def stop_hook_inject_handler(violation: dict) -> dict:
    """
    StopHook inject handler (deny action via hook chain).
    Action: Emit CIEU event + write to hook warning queue for pre-call injection.
    """
    payload = violation["payload"]
    violation_type = payload.get("violation_type", "unknown")

    emit_cieu(
        "STOP_HOOK_K9_DENY",
        {
            "decision": "deny",
            "passed": 0,
            "violation_type": violation_type,
            "agent_id": violation["agent_id"],
            "drift_detected": 1,
            "drift_category": "k9_routing",
        }
    )

    # Write to warning queue for hook pre-call injection
    warning_queue_path = COMPANY_ROOT.parent / "ystar-company" / ".ystar_warning_queue.json"
    try:
        if warning_queue_path.exists():
            warnings = json.loads(warning_queue_path.read_text())
        else:
            warnings = []

        warnings.append({
            "type": "STOP_HOOK_K9_DENY",
            "violation_type": violation_type,
            "agent_id": violation["agent_id"],
            "command": payload.get("command", ""),
            "timestamp": time.time(),
        })

        warning_queue_path.write_text(json.dumps(warnings, indent=2))
    except Exception:
        pass  # fail-open

    return {
        "handled": True,
        "cieu_event": "STOP_HOOK_K9_DENY",
        "action_taken": "deny_via_hook_inject",
    }


def czl_protocol_handler(violation: dict) -> dict:
    """
    CZL protocol handler (dispatch missing 5-tuple).
    Action: Emit CIEU event + log dispatch rejection.
    """
    payload = violation["payload"]
    violation_type = payload.get("violation_type", "unknown")

    emit_cieu(
        "CZL_K9_WARN",
        {
            "decision": "warn",
            "passed": 0,
            "violation_type": violation_type,
            "agent_id": violation["agent_id"],
            "drift_detected": 1,
            "drift_category": "czl_protocol",
        }
    )

    return {
        "handled": True,
        "cieu_event": "CZL_K9_WARN",
        "action_taken": "emit_czl_warn",
    }


def agent_registry_handler(violation: dict) -> dict:
    """
    Agent Registry handler (unidentified agent_id).
    Action: Emit CIEU event + log identity gap.
    """
    payload = violation["payload"]
    violation_type = payload.get("violation_type", "unknown")

    emit_cieu(
        "AGENT_REGISTRY_K9_WARN",
        {
            "decision": "warn",
            "passed": 0,
            "violation_type": violation_type,
            "agent_id": violation["agent_id"],
            "drift_detected": 1,
            "drift_category": "agent_registry",
        }
    )

    return {
        "handled": True,
        "cieu_event": "AGENT_REGISTRY_K9_WARN",
        "action_taken": "emit_registry_warn",
    }


def hook_health_handler(violation: dict) -> dict:
    """
    Hook Health handler (hook chain missing or stale).
    Action: Emit CIEU event + escalate to Board.
    """
    payload = violation["payload"]
    violation_type = payload.get("violation_type", "unknown")

    emit_cieu(
        "HOOK_HEALTH_K9_ESCALATE",
        {
            "decision": "escalate",
            "passed": 0,
            "violation_type": violation_type,
            "agent_id": violation["agent_id"],
            "drift_detected": 1,
            "drift_category": "hook_health",
        }
    )

    # Write Board escalation file
    escalation_dir = COMPANY_ROOT.parent / "ystar-company" / "reports" / "escalation"
    escalation_dir.mkdir(parents=True, exist_ok=True)

    escalation_file = escalation_dir / f"hook_health_{int(time.time())}.md"
    try:
        escalation_file.write_text(
            f"""# Hook Health K9 Escalation

**Violation Type**: {violation_type}
**Agent ID**: {violation['agent_id']}
**Timestamp**: {time.time()}

## Issue
Hook chain appears dead or stale (no HOOK_PRE_CALL/HOOK_POST_CALL events in 10min window).

## Recommended Actions
1. Check if gov-mcp daemon is running: `ps aux | grep gov-mcp`
2. Restart hook daemon: `pkill -9 -f gov-mcp && cd ~/.openclaw/workspace/gov-mcp && ./start.sh`
3. Verify hook chain: run any tool call and check for HOOK_PRE_CALL event in CIEU DB

## CIEU Evidence
Event ID: {violation['event_id']}
Seq Global: {violation['seq_global']}
"""
        )
    except Exception:
        pass  # fail-open

    return {
        "handled": True,
        "cieu_event": "HOOK_HEALTH_K9_ESCALATE",
        "action_taken": "escalate_to_board",
    }


# ═══ ROUTING DISPATCH ═══

HANDLER_MAP = {
    "forget_guard": forget_guard_handler,
    "forget_guard_deny": forget_guard_deny_handler,
    "stop_hook_inject": stop_hook_inject_handler,
    "czl_protocol": czl_protocol_handler,
    "agent_registry": agent_registry_handler,
    "hook_health": hook_health_handler,
}


def route_violation(violation: dict) -> None:
    """
    Route violation to appropriate handler based on routing_target field.

    Args:
        violation: Violation event dict with payload containing routing_target and action
    """
    payload = violation["payload"]
    routing_target = payload.get("routing_target", "unknown")
    action = payload.get("action", "warn")

    # Special case: forget_guard with deny action → use forget_guard_deny handler
    if routing_target == "forget_guard" and action == "deny":
        handler_key = "forget_guard_deny"
    else:
        handler_key = routing_target

    handler = HANDLER_MAP.get(handler_key)

    if not handler:
        # Unknown routing target — emit warning and skip
        emit_cieu(
            "K9_ROUTING_UNKNOWN_TARGET",
            {
                "decision": "warn",
                "passed": 0,
                "routing_target": routing_target,
                "violation_type": payload.get("violation_type", "unknown"),
                "agent_id": violation["agent_id"],
            }
        )
        return

    # Call handler
    try:
        result = handler(violation)

        # Emit routing success event
        emit_cieu(
            "K9_ROUTING_DISPATCHED",
            {
                "decision": "info",
                "passed": 1,
                "routing_target": routing_target,
                "action": action,
                "handler_result": result["action_taken"],
                "violation_type": payload.get("violation_type", "unknown"),
            }
        )

    except Exception as e:
        # Handler failed — emit error event, fail-open
        emit_cieu(
            "K9_ROUTING_HANDLER_ERROR",
            {
                "decision": "error",
                "passed": 0,
                "routing_target": routing_target,
                "error": str(e),
                "violation_type": payload.get("violation_type", "unknown"),
            }
        )
        print(f"[K9_SUBSCRIBER] Handler failed for {routing_target}: {e}", file=sys.stderr)


# ═══ MAIN SUBSCRIBER LOOP ═══

def run_subscriber():
    """Main subscriber loop — polls CIEU DB for new violations every 0.5s."""
    daemon = DaemonContext()
    daemon.write_pid()

    print("[K9_SUBSCRIBER] Starting K9 routing subscriber daemon...", file=sys.stderr)

    # Emit startup event
    emit_cieu(
        "K9_SUBSCRIBER_STARTED",
        {
            "decision": "info",
            "passed": 1,
            "pid": os.getpid(),
            "state_file": str(STATE_FILE),
        }
    )

    last_seq = get_last_processed_seq()
    print(f"[K9_SUBSCRIBER] Resuming from seq_global={last_seq}", file=sys.stderr)

    try:
        while daemon.running:
            # Fetch new violations
            violations = fetch_new_violations(last_seq)

            # Process each violation
            for violation in violations:
                route_violation(violation)
                last_seq = violation["seq_global"]

            # Save last processed seq
            if violations:
                save_last_processed_seq(last_seq)

            # Sleep 0.5s before next poll
            time.sleep(0.5)

    except Exception as e:
        print(f"[K9_SUBSCRIBER] Fatal error in subscriber loop: {e}", file=sys.stderr)
        emit_cieu(
            "K9_SUBSCRIBER_CRASH",
            {
                "decision": "error",
                "passed": 0,
                "error": str(e),
            }
        )

    finally:
        # Cleanup
        daemon.remove_pid()
        emit_cieu(
            "K9_SUBSCRIBER_STOPPED",
            {
                "decision": "info",
                "passed": 1,
                "last_seq": last_seq,
            }
        )
        print("[K9_SUBSCRIBER] Subscriber daemon stopped.", file=sys.stderr)


# ═══ CLI ENTRY POINT ═══

def main():
    """CLI entry point for daemon control."""
    if len(sys.argv) < 2:
        print("Usage: k9_routing_subscriber.py start|stop|status")
        sys.exit(1)

    command = sys.argv[1]

    if command == "start":
        # Check if already running
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text())
                os.kill(pid, 0)  # Check if process exists
                print(f"[K9_SUBSCRIBER] Already running with PID {pid}", file=sys.stderr)
                sys.exit(0)
            except (ProcessLookupError, ValueError):
                # Stale PID file
                PID_FILE.unlink()

        run_subscriber()

    elif command == "stop":
        if not PID_FILE.exists():
            print("[K9_SUBSCRIBER] Not running", file=sys.stderr)
            sys.exit(0)

        try:
            pid = int(PID_FILE.read_text())
            os.kill(pid, signal.SIGTERM)
            print(f"[K9_SUBSCRIBER] Sent SIGTERM to PID {pid}", file=sys.stderr)
        except Exception as e:
            print(f"[K9_SUBSCRIBER] Failed to stop: {e}", file=sys.stderr)
            sys.exit(1)

    elif command == "status":
        if not PID_FILE.exists():
            print("[K9_SUBSCRIBER] Not running", file=sys.stderr)
            sys.exit(1)

        try:
            pid = int(PID_FILE.read_text())
            os.kill(pid, 0)  # Check if process exists
            print(f"[K9_SUBSCRIBER] Running with PID {pid}", file=sys.stderr)
            sys.exit(0)
        except (ProcessLookupError, ValueError):
            print("[K9_SUBSCRIBER] Stale PID file, process not running", file=sys.stderr)
            PID_FILE.unlink()
            sys.exit(1)

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
