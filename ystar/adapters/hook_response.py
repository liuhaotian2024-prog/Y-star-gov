"""
ystar.adapters.hook_response — Ecosystem-neutral hook response formatter.

Translates Y*gov's internal ALLOW/DENY decisions into the response format
expected by the host agent framework. No host-specific format is hardcoded
anywhere else in the codebase.

Host detection priority:
  1. YSTAR_HOST environment variable (explicit user choice)
  2. .ystar_session.json "host" field (set during ystar setup)
  3. Auto-detect from hook payload structure
  4. Fallback: "generic"

Supported hosts:
  claude_code  — hookSpecificOutput with permissionDecision
  openclaw     — {"action": "block", "message": "..."}
  generic      — {"decision": "deny", "reason": "..."}
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Host detection ──────────────────────────────────────────────────────────

def detect_host(payload: Optional[Dict[str, Any]] = None) -> str:
    """Detect the host agent framework.

    Priority:
      1. YSTAR_HOST env var
      2. .ystar_session.json "host" field
      3. Payload-based auto-detection
      4. "generic"
    """
    # 1. Env var (explicit user choice, highest priority)
    host = os.environ.get("YSTAR_HOST", "").strip().lower()
    if host:
        return host

    # 2. Session config
    try:
        session_path = Path(".ystar_session.json")
        if session_path.exists():
            cfg = json.loads(session_path.read_text(encoding="utf-8"))
            host = cfg.get("host", "").strip().lower()
            if host:
                return host
    except Exception:
        pass

    # 3. Auto-detect from payload
    if payload:
        # Claude Code payloads have "transcript_path" and "hook_event_name"
        if "transcript_path" in payload or "hook_event_name" in payload:
            return "claude_code"
        # OpenClaw payloads have "openclaw_version" or "agent_runtime"
        if "openclaw_version" in payload or "agent_runtime" in payload:
            return "openclaw"

    # 4. Fallback
    return "generic"


# ── Response formatters ─────────────────────────────────────────────────────

def format_allow(host: str) -> Dict[str, Any]:
    """Format an ALLOW response for the given host."""
    if host == "claude_code":
        return {}
    elif host == "openclaw":
        return {}
    else:
        return {}


def format_deny(host: str, message: str, violations: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """Format a DENY response for the given host.

    Args:
        host: Target host framework identifier.
        message: Human-readable deny reason.
        violations: Optional list of violation dicts with "dimension" and "message".
    """
    if host == "claude_code":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            }
        }
    elif host == "openclaw":
        resp: Dict[str, Any] = {
            "action": "block",
            "message": message,
        }
        if violations:
            resp["violations"] = violations
        return resp
    else:
        # Generic format — usable by any MCP client or custom framework
        resp = {
            "decision": "deny",
            "reason": message,
        }
        if violations:
            resp["violations"] = violations
        return resp


def convert_ygov_result(ygov_result: Dict[str, Any], host: str) -> Dict[str, Any]:
    """Convert a Y*gov internal hook result to the host-specific format.

    Y*gov internal format:
      ALLOW: {}
      DENY:  {"action": "block", "message": "...", "violations": [...]}

    This function translates to whatever the host expects.
    """
    if not ygov_result or ygov_result == {}:
        return format_allow(host)

    message = ygov_result.get("message", "Blocked by Y*gov")
    violations = ygov_result.get("violations")
    return format_deny(host, message, violations)
