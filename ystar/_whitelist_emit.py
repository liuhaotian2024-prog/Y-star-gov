"""Whitelist matcher for hook daemon — emits WHITELIST_MATCH/DRIFT events.

AMENDMENT-018 sync mechanism A: emit WHITELIST events from FAST PATH.
Called async from hook daemon after processing each Bash command.

Design:
- Load whitelist once at module import (performance)
- Match command against allowed_prefixes
- Emit CIEU event: WHITELIST_MATCH or WHITELIST_DRIFT
- Fail-open: errors don't block hook processing
- Target latency: <100ms (async background OK)
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

# Load whitelist at module import time (once per daemon lifetime)
_WHITELIST: Optional[Dict[str, List[str]]] = None


def _load_whitelist() -> Dict[str, List[str]]:
    """Load platform-specific whitelist YAML."""
    global _WHITELIST
    if _WHITELIST is not None:
        return _WHITELIST

    try:
        import yaml
        pkg_dir = Path(__file__).parent.parent / "gov_mcp"

        # Platform auto-detection
        if sys.platform == "win32":
            path = pkg_dir / "whitelist_windows.yaml"
        else:
            path = pkg_dir / "whitelist_unix.yaml"

        if not path.is_file():
            path = pkg_dir / "exec_whitelist.yaml"

        if not path.is_file():
            _WHITELIST = {"allowed_prefixes": [], "always_deny": []}
            return _WHITELIST

        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        _WHITELIST = {
            "allowed_prefixes": data.get("allowed_prefixes", []),
            "always_deny": data.get("always_deny", []),
        }
        return _WHITELIST
    except Exception:
        _WHITELIST = {"allowed_prefixes": [], "always_deny": []}
        return _WHITELIST


def check_whitelist_and_emit(command: str, agent_id: str) -> None:
    """
    Check if command matches whitelist and emit CIEU event.

    Emits:
    - WHITELIST_MATCH: command matches allowed_prefixes
    - WHITELIST_DRIFT: command does NOT match (potential governance gap)

    Fail-open: any error is silently ignored.
    """
    try:
        whitelist = _load_whitelist()
        cmd = command.strip()

        # Check always_deny first
        deny_list = whitelist.get("always_deny", [])
        if any(cmd.startswith(p) for p in deny_list):
            event_type = "WHITELIST_DRIFT"
            reason = "always_deny match"
        # Check allowed_prefixes
        elif any(cmd.startswith(p) for p in whitelist.get("allowed_prefixes", [])):
            event_type = "WHITELIST_MATCH"
            reason = "prefix match"
        else:
            event_type = "WHITELIST_DRIFT"
            reason = "no prefix match"

        # Emit CIEU event
        _emit_cieu_event(
            event_type=event_type,
            params={
                "agent_id": agent_id,
                "command": cmd[:200],  # Truncate for storage
                "reason": reason,
            }
        )
    except Exception:
        # Fail-open: whitelist emission errors don't block hook processing
        pass


def _emit_cieu_event(event_type: str, params: dict) -> None:
    """Write CIEU event to database."""
    try:
        from ystar.governance.cieu_store import CIEUStore

        store = CIEUStore()  # Default .ystar_cieu.db

        record = {
            "event_id": str(uuid.uuid4()),
            "session_id": "hook_daemon",
            "agent_id": params.get("agent_id", "unknown"),
            "event_type": event_type,
            "decision": "info",
            "evidence_grade": "ops",
            "created_at": time.time(),
            "seq_global": time.time_ns() // 1000,
            "params": params,
            "violations": [],
            "drift_detected": (event_type == "WHITELIST_DRIFT"),
            "human_initiator": params.get("agent_id", "unknown"),
        }

        store.write_dict(record)
    except Exception:
        # Fail-open
        pass


if __name__ == "__main__":
    # Standalone mode: read payload from stdin, emit event
    try:
        payload = json.loads(sys.stdin.read())
        tool_name = payload.get("tool_name", "")

        if tool_name == "Bash":
            command = payload.get("tool_input", {}).get("command", "")
            agent_id = payload.get("agent_id", "unknown")

            if command:
                check_whitelist_and_emit(command, agent_id)
    except Exception:
        # Fail-open: errors in standalone mode are silent
        pass
