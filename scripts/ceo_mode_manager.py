#!/usr/bin/env python3
"""
CEO Mode Manager — Autonomous + Break-Glass mode enforcement
Part of AMENDMENT-011 capability-based governance (dual-mode implementation)

Modes:
- standard: default session.json constraints
- autonomous: Board silence ≥15min → CEO self-drive (Y-star-gov write + bypass must_dispatch)
- break_glass: system deadlock → CEO emergency unlock (5min sliding idle, 20min hard cap)

Usage:
  python3 ceo_mode_manager.py tick              # evaluate triggers + update last_activity
  python3 ceo_mode_manager.py status            # show current mode + timing
  python3 ceo_mode_manager.py revoke            # force back to standard
  python3 ceo_mode_manager.py force_autonomous  # manual trigger
  python3 ceo_mode_manager.py force_break_glass --trigger T1  # manual break-glass
"""

import json
import os
import sys
import time
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

WORKSPACE_ROOT = Path("/Users/haotianliu/.openclaw/workspace/ystar-company")
YSTAR_GOV_ROOT = Path("/Users/haotianliu/.openclaw/workspace/Y-star-gov")
MODE_FILE = WORKSPACE_ROOT / ".ystar_ceo_mode.json"
LAST_BOARD_MSG = WORKSPACE_ROOT / "scripts/.ystar_last_board_msg"

# Timing constants (seconds)
BOARD_SILENCE_THRESHOLD = 15 * 60      # 15 min
BREAK_GLASS_IDLE_TIMEOUT = 5 * 60      # 5 min sliding idle
BREAK_GLASS_HARD_CAP = 20 * 60         # 20 min total
HEALTH_CHECK_DEGRADED_THRESHOLD = 5 * 60  # 5 min

# CIEU recording
try:
    sys.path.insert(0, str(YSTAR_GOV_ROOT))
    from ystar.cieu.recorder import emit_cieu
except ImportError:
    def emit_cieu(event_type: str, **kwargs):
        """Fallback if CIEU not available"""
        print(f"[CIEU-fallback] {event_type}: {kwargs}", file=sys.stderr)


class CEOModeManager:
    """Manages CEO mode transitions and enforcement"""

    def __init__(self):
        self.mode_file = MODE_FILE
        self.last_board_msg_file = LAST_BOARD_MSG

    def _atomic_write(self, data: Dict[str, Any]):
        """Atomic write using temp file + os.replace"""
        temp_file = self.mode_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(temp_file, self.mode_file)

    def _read_mode(self) -> Dict[str, Any]:
        """Read current mode state, return standard defaults if not exists"""
        if not self.mode_file.exists():
            return {
                "mode": "standard",
                "entered_at": None,
                "last_activity": None,
                "expires_at": None,
                "trigger": None,
                "trigger_evidence": {}
            }
        with open(self.mode_file) as f:
            return json.load(f)

    def _get_last_board_msg_time(self) -> Optional[float]:
        """Get timestamp of last Board message"""
        if not self.last_board_msg_file.exists():
            return None
        with open(self.last_board_msg_file) as f:
            try:
                return float(f.read().strip())
            except ValueError:
                return None

    def _check_health_degraded(self) -> bool:
        """Check if gov_doctor reports degraded health for ≥5min"""
        try:
            result = subprocess.run(
                ["ystar", "doctor", "--json"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                return False

            data = json.loads(result.stdout)
            health = data.get("health", "unknown")

            if health != "degraded":
                return False

            # Check if degraded for ≥5min
            # (simplified: would need persistent timestamp tracking in production)
            # For now, just return True if currently degraded
            return True

        except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
            return False

    def _check_circuit_breaker_armed(self) -> bool:
        """Check if circuit breaker is ARMED"""
        try:
            result = subprocess.run(
                ["ystar", "doctor", "--json"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                return False

            data = json.loads(result.stdout)
            return data.get("circuit_breaker", {}).get("state") == "ARMED"

        except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
            return False

    def _check_must_dispatch_denials(self) -> int:
        """Count must_dispatch_via_cto denials in current session"""
        # Read from CIEU events in current session
        try:
            from ystar.cieu.query import query_cieu
            events = query_cieu(
                event_type="behavior_rule_violation",
                filters={"rule": "must_dispatch_via_cto"}
            )
            return len(events)
        except ImportError:
            return 0

    def _check_cto_subagent_exists(self) -> bool:
        """Check if CTO sub-agent is available"""
        # This would need integration with Agent tool discovery
        # For now, simplified check
        cto_agent_file = WORKSPACE_ROOT / ".claude/agents/cto.md"
        return cto_agent_file.exists()

    def _check_processes_running(self) -> bool:
        """Check if gov-mcp and hook daemon are running"""
        try:
            # Check gov-mcp
            result = subprocess.run(
                ["pgrep", "-f", "gov-mcp"],
                capture_output=True
            )
            gov_mcp_running = result.returncode == 0

            # Check hook daemon
            result = subprocess.run(
                ["pgrep", "-f", "hook.*daemon"],
                capture_output=True
            )
            hook_running = result.returncode == 0

            return gov_mcp_running and hook_running

        except subprocess.SubprocessError:
            return False

    def evaluate_triggers(self) -> Optional[str]:
        """
        Evaluate all break-glass triggers, return first match or None

        Triggers:
        - T1: gov_doctor health=degraded for ≥5min
        - T2: circuit breaker ARMED and reset failed
        - T3: must_dispatch_via_cto denied ≥3 times in session
        - T4: CTO sub-agent not found
        - T5: gov-mcp or hook daemon process down
        """
        now = time.time()

        # T1: health degraded
        if self._check_health_degraded():
            return "T1", {"reason": "gov_doctor health=degraded", "checked_at": now}

        # T2: circuit breaker ARMED
        if self._check_circuit_breaker_armed():
            return "T2", {"reason": "circuit_breaker=ARMED", "checked_at": now}

        # T3: must_dispatch denials ≥3
        denials = self._check_must_dispatch_denials()
        if denials >= 3:
            return "T3", {"reason": f"must_dispatch denied {denials} times", "checked_at": now}

        # T4: CTO missing
        if not self._check_cto_subagent_exists():
            return "T4", {"reason": "CTO sub-agent not found", "checked_at": now}

        # T5: processes down
        if not self._check_processes_running():
            return "T5", {"reason": "gov-mcp or hook daemon not running", "checked_at": now}

        return None, {}

    def check_should_revoke(self, current_state: Dict[str, Any]) -> tuple[bool, str]:
        """
        Check if current mode should be revoked

        Returns: (should_revoke, reason)
        """
        mode = current_state["mode"]
        now = time.time()

        # All modes: Board message → immediate revoke
        last_board = self._get_last_board_msg_time()
        entered_at = current_state.get("entered_at")
        if last_board and entered_at and last_board > entered_at:
            return True, "board_message_received"

        if mode == "autonomous":
            # No auto-revoke for autonomous (only on Board message)
            return False, ""

        elif mode == "break_glass":
            # Sliding idle: 5min no activity
            last_activity = current_state.get("last_activity")
            if last_activity and (now - last_activity) > BREAK_GLASS_IDLE_TIMEOUT:
                return True, "idle_timeout_5min"

            # Hard cap: 20min total
            entered_at = current_state.get("entered_at")
            if entered_at and (now - entered_at) > BREAK_GLASS_HARD_CAP:
                return True, "hard_cap_20min"

            # Triggers cleared
            trigger_id, _ = self.evaluate_triggers()
            if trigger_id is None:
                return True, "triggers_cleared"

        return False, ""

    def tick(self) -> Dict[str, Any]:
        """
        Main tick function: evaluate triggers, update last_activity, check revoke
        Called on every CEO tool call
        """
        current = self._read_mode()
        now = time.time()

        # Update last_activity if in elevated mode
        if current["mode"] in ("autonomous", "break_glass"):
            current["last_activity"] = now
            self._atomic_write(current)

        # Check if should revoke
        should_revoke, reason = self.check_should_revoke(current)
        if should_revoke:
            self.revoke(reason)
            return self._read_mode()

        # Check if should enter autonomous (from standard only)
        if current["mode"] == "standard":
            last_board = self._get_last_board_msg_time()
            if last_board and (now - last_board) > BOARD_SILENCE_THRESHOLD:
                self.enter_autonomous()
                return self._read_mode()

        # Check if should enter break_glass (from any mode, except if already in it with same trigger)
        trigger_id, evidence = self.evaluate_triggers()
        if trigger_id:
            # Only enter if not already in break_glass, or trigger changed
            if current["mode"] != "break_glass" or current.get("trigger") != trigger_id:
                self.enter_break_glass(trigger_id, evidence)
                return self._read_mode()

        return current

    def enter_autonomous(self):
        """Enter autonomous mode"""
        now = time.time()
        data = {
            "mode": "autonomous",
            "entered_at": now,
            "last_activity": now,
            "expires_at": None,
            "trigger": None,
            "trigger_evidence": {}
        }
        self._atomic_write(data)

        emit_cieu(
            "ceo_mode_transition",
            from_mode="standard",
            to_mode="autonomous",
            timestamp=now,
            reason="board_silence_15min"
        )

        print(f"[CEO Mode] → AUTONOMOUS (Board silence ≥15min)", file=sys.stderr)

    def enter_break_glass(self, trigger_id: str, evidence: Dict[str, Any]):
        """Enter break-glass mode"""
        now = time.time()
        data = {
            "mode": "break_glass",
            "entered_at": now,
            "last_activity": now,
            "expires_at": now + BREAK_GLASS_HARD_CAP,
            "trigger": trigger_id,
            "trigger_evidence": evidence
        }
        self._atomic_write(data)

        emit_cieu(
            "BREAK_GLASS_CLAIM",
            trigger=trigger_id,
            evidence=evidence,
            timestamp=now,
            hard_cap_expires_at=now + BREAK_GLASS_HARD_CAP
        )

        print(f"[CEO Mode] → BREAK_GLASS (trigger={trigger_id})", file=sys.stderr)

    def revoke(self, reason: str = "manual"):
        """Revoke to standard mode"""
        current = self._read_mode()
        prev_mode = current["mode"]

        if prev_mode == "standard":
            print("[CEO Mode] Already in standard mode", file=sys.stderr)
            return

        now = time.time()

        # Emit release event if break_glass
        if prev_mode == "break_glass":
            emit_cieu(
                "BREAK_GLASS_RELEASE",
                trigger=current.get("trigger"),
                duration_seconds=now - current.get("entered_at", now),
                reason=reason,
                timestamp=now
            )

        # Reset to standard
        data = {
            "mode": "standard",
            "entered_at": None,
            "last_activity": None,
            "expires_at": None,
            "trigger": None,
            "trigger_evidence": {}
        }
        self._atomic_write(data)

        emit_cieu(
            "ceo_mode_transition",
            from_mode=prev_mode,
            to_mode="standard",
            timestamp=now,
            reason=reason
        )

        print(f"[CEO Mode] → STANDARD (reason={reason})", file=sys.stderr)

    def status(self) -> Dict[str, Any]:
        """Get current mode status with human-readable timing"""
        current = self._read_mode()
        now = time.time()

        result = {**current}

        # Add human-readable timing
        if current.get("entered_at"):
            elapsed = now - current["entered_at"]
            result["elapsed_seconds"] = int(elapsed)
            result["elapsed_human"] = self._format_duration(elapsed)

        if current.get("last_activity"):
            idle = now - current["last_activity"]
            result["idle_seconds"] = int(idle)
            result["idle_human"] = self._format_duration(idle)

        if current.get("expires_at"):
            remaining = current["expires_at"] - now
            result["remaining_seconds"] = int(remaining)
            result["remaining_human"] = self._format_duration(remaining)

        # Check if Board is active
        last_board = self._get_last_board_msg_time()
        if last_board:
            board_silence = now - last_board
            result["board_silence_seconds"] = int(board_silence)
            result["board_silence_human"] = self._format_duration(board_silence)

        return result

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format seconds as human-readable duration"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds / 60)}m {int(seconds % 60)}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"


def main():
    """CLI entry point"""
    manager = CEOModeManager()

    if len(sys.argv) < 2:
        print("Usage: ceo_mode_manager.py {tick|status|revoke|force_autonomous|force_break_glass}")
        sys.exit(1)

    command = sys.argv[1]

    if command == "tick":
        state = manager.tick()
        print(json.dumps(state, indent=2))

    elif command == "status":
        status = manager.status()
        print(json.dumps(status, indent=2))

    elif command == "revoke":
        manager.revoke("manual_cli")
        print("Revoked to standard mode")

    elif command == "force_autonomous":
        manager.enter_autonomous()
        print("Forced into autonomous mode")

    elif command == "force_break_glass":
        # Parse --trigger arg
        trigger = "T1"  # default
        if "--trigger" in sys.argv:
            idx = sys.argv.index("--trigger")
            if idx + 1 < len(sys.argv):
                trigger = sys.argv[idx + 1]

        evidence = {
            "reason": f"Manual trigger {trigger}",
            "timestamp": time.time()
        }
        manager.enter_break_glass(trigger, evidence)
        print(f"Forced into break-glass mode (trigger={trigger})")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
