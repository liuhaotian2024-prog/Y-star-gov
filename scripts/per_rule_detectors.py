#!/usr/bin/env python3
"""
Per-Rule Detector Functions — CZL-78 P1 Atomic Task
Platform Engineer: Ryan Park (eng-platform)
Version: 1.0 (2026-04-16)

Ethan#P0.2 architectural finding: ForgetGuard currently emits aggregate
BEHAVIOR_RULE_VIOLATION events covering 10+ rules. Only 4/10 critical rules
have per-rule specialized detectors today:
  - DEFER_LANGUAGE_DRIFT
  - BOARD_CHOICE_QUESTION_DRIFT
  - MATURITY_TAG_MISSING
  - COORDINATOR_REPLY_MISSING_5TUPLE

This module implements 6 additional per-rule detector functions for granular CIEU telemetry.

Design Pattern (from stop_hook.py):
  Each detector: detect_{rule_id}(payload: dict) -> dict | None
  Returns: {violation_type, evidence, severity} or None if no violation

Integration:
  Wire into scripts/hook_observe.py PreToolUse path via _check_behavior_rules()
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


# ── Rule 1: czl_dispatch_missing_5tuple ───────────────────────────────────

def detect_czl_dispatch_missing_5tuple(payload: dict) -> Optional[dict]:
    """
    Detect Agent tool calls with dispatch prompts lacking CZL 5-tuple structure.

    Trigger: tool_name="Agent" AND subagent_type present
    Validation: Prompt MUST contain Y*, Xt, U, Yt+1, Rt+1 sections

    Returns:
        {violation_type, evidence, severity} or None
    """
    tool_name = payload.get("tool_name")
    if tool_name != "Agent":
        return None

    tool_input = payload.get("tool_input", {})
    subagent_type = tool_input.get("subagent_type")
    if not subagent_type:
        return None

    # Extract dispatch prompt from tool_input
    prompt = tool_input.get("instructions") or tool_input.get("prompt") or ""

    # Check for required 5-tuple sections
    required_sections = ["Y*", "Xt", "U", "Yt+1", "Rt+1"]
    missing_sections = []

    for section in required_sections:
        # Match section headers: **Y*** or **Xt** or **U** etc
        pattern = rf"\*\*{re.escape(section)}\*\*"
        if not re.search(pattern, prompt, re.IGNORECASE):
            missing_sections.append(section)

    if not missing_sections:
        return None  # All sections present

    return {
        "violation_type": "CZL_DISPATCH_MISSING_5TUPLE",
        "evidence": f"Missing sections: {', '.join(missing_sections)}. Dispatch to {subagent_type} lacks CZL structure.",
        "severity": "high",
        "missing_sections": missing_sections,
        "subagent_type": subagent_type,
    }


# ── Rule 2: czl_receipt_rt_not_zero ───────────────────────────────────────

def detect_czl_receipt_rt_not_zero(payload: dict) -> Optional[dict]:
    """
    Detect SendMessage receipts claiming Rt+1=0 but missing empirical evidence.

    Trigger: tool_name="SendMessage" AND receipt contains "Rt+1" claim
    Validation: If Rt+1=0 claimed, MUST have bash verification output

    Returns:
        {violation_type, evidence, severity} or None
    """
    tool_name = payload.get("tool_name")
    if tool_name != "SendMessage":
        return None

    tool_input = payload.get("tool_input", {})
    message_text = tool_input.get("content") or tool_input.get("message") or ""

    # Check if receipt contains Rt+1 claim
    rt_match = re.search(r"Rt\+1.*?[=:]\s*([\d.]+)", message_text, re.IGNORECASE)
    if not rt_match:
        return None  # Not a CZL receipt

    claimed_rt = float(rt_match.group(1))
    if claimed_rt != 0.0:
        return None  # Not claiming closure

    # Validate empirical evidence presence
    bash_markers = ["ls -la", "wc -l", "pytest", "git diff --stat", "grep -r", "find "]
    has_bash_evidence = any(marker in message_text for marker in bash_markers)

    if has_bash_evidence:
        return None  # Evidence present

    return {
        "violation_type": "CZL_RECEIPT_RT_NOT_ZERO",
        "evidence": f"Receipt claims Rt+1=0 but lacks bash verification output (no ls/wc/pytest/git paste).",
        "severity": "high",
        "claimed_rt": claimed_rt,
    }


# ── Rule 3: charter_drift_mid_session ─────────────────────────────────────

def detect_charter_drift_mid_session(payload: dict) -> Optional[dict]:
    """
    Detect mid-session edits to AGENTS.md or WORKING_STYLE.md without break-glass mode.

    Trigger: Edit/Write to governance files mid-session (not during boot)
    Validation: Active agent must be in break_glass mode or be Secretary

    Returns:
        {violation_type, evidence, severity} or None
    """
    tool_name = payload.get("tool_name")
    if tool_name not in ["Edit", "Write"]:
        return None

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path") or ""

    # Check if governance file
    governance_files = [
        "AGENTS.md",
        "governance/WORKING_STYLE.md",
        "governance/BOARD_CHARTER_AMENDMENTS.md",
    ]
    is_governance = any(file_path.endswith(gf) for gf in governance_files)
    if not is_governance:
        return None

    # Check active agent (from payload metadata or .ystar_active_agent)
    agent_id = payload.get("agent_id") or _read_active_agent()
    ceo_mode = payload.get("ceo_mode") or "normal"

    # Allow Secretary or break_glass mode
    if agent_id == "Samantha-Secretary" or ceo_mode == "break_glass":
        return None

    return {
        "violation_type": "CHARTER_DRIFT_MID_SESSION",
        "evidence": f"Agent {agent_id} editing {file_path} without break-glass mode.",
        "severity": "high",
        "file_path": file_path,
        "agent_id": agent_id,
    }


# ── Rule 4: wave_scope_undeclared ─────────────────────────────────────────

def detect_wave_scope_undeclared(payload: dict) -> Optional[dict]:
    """
    Detect CEO creating campaign/wave reports without declaring scope/goal in first 200 chars.

    Trigger: CEO writes to reports/ceo/campaign* or reports/wave*
    Validation: File content MUST have "Goal:" or "Scope:" in first paragraph

    Returns:
        {violation_type, evidence, severity} or None
    """
    tool_name = payload.get("tool_name")
    if tool_name != "Write":
        return None

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path") or ""

    # Check if campaign/wave report
    if not ("campaign" in file_path.lower() or "wave" in file_path.lower()):
        return None
    if not file_path.startswith("reports/ceo/"):
        return None

    # Extract file content (first 200 chars)
    content = tool_input.get("content") or ""
    first_para = content[:200]

    # Check for scope/goal declaration
    has_scope = any(marker in first_para for marker in ["Goal:", "Scope:", "目标:", "范围:"])
    if has_scope:
        return None

    return {
        "violation_type": "WAVE_SCOPE_UNDECLARED",
        "evidence": f"Campaign report {file_path} lacks Goal/Scope declaration in first paragraph.",
        "severity": "medium",
        "file_path": file_path,
    }


# ── Rule 5: subagent_unauthorized_git_op ──────────────────────────────────

def detect_subagent_unauthorized_git_op(payload: dict) -> Optional[dict]:
    """
    Detect sub-agents attempting git reset/push --force/branch -D without Board authorization.

    Trigger: Bash command contains destructive git operations
    Validation: Active agent must be in .claude/tasks/ authorized list or CEO/CTO

    Returns:
        {violation_type, evidence, severity} or None
    """
    tool_name = payload.get("tool_name")
    if tool_name != "Bash":
        return None

    tool_input = payload.get("tool_input", {})
    command = tool_input.get("command") or ""

    # Check for destructive git operations
    destructive_patterns = [
        r"git\s+reset\s+--hard",
        r"git\s+push\s+.*--force",
        r"git\s+branch\s+-D",
        r"git\s+clean\s+-f",
        r"git\s+checkout\s+\.",
        r"git\s+restore\s+\.",
    ]
    is_destructive = any(re.search(p, command, re.IGNORECASE) for p in destructive_patterns)
    if not is_destructive:
        return None

    # Check active agent authorization
    agent_id = payload.get("agent_id") or _read_active_agent()
    authorized_agents = ["ceo", "Aiden-CEO", "cto", "Ethan-CTO", "Samantha-Secretary"]

    if agent_id in authorized_agents:
        return None  # Authorized

    return {
        "violation_type": "SUBAGENT_UNAUTHORIZED_GIT_OP",
        "evidence": f"Agent {agent_id} attempted destructive git operation: {command[:80]}",
        "severity": "high",
        "agent_id": agent_id,
        "command": command[:200],
    }


# ── Rule 6: realtime_artifact_archival_sla ───────────────────────────────

def detect_realtime_artifact_archival_sla(payload: dict) -> Optional[dict]:
    """
    Detect new artifacts in archival scope lacking ARCHIVE_INDEX entry within 30min SLA.

    Trigger: Write/Edit to reports/ knowledge/ products/ content/ governance/
    Validation: Artifact must appear in knowledge/ARCHIVE_INDEX.md OR emit ARTIFACT_ARCHIVAL_SCOPE_DETECTED

    Returns:
        {violation_type, evidence, severity} or None

    Note: This detector emits audit event for SLA tracking. Actual SLA enforcement
    is handled by scripts/archive_sla_scan.py cron job.
    """
    tool_name = payload.get("tool_name")
    if tool_name not in ["Write", "Edit"]:
        return None

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path") or ""

    # Check if in archival scope
    archival_prefixes = ["reports/", "knowledge/", "products/", "content/", "governance/"]
    is_archival = any(file_path.startswith(prefix) for prefix in archival_prefixes)
    if not is_archival:
        return None

    # This is an audit-level detector — emit event for SLA tracking
    # (No violation return, just telemetry for archive_sla_scan.py to consume)
    return {
        "violation_type": "ARTIFACT_ARCHIVAL_SCOPE_DETECTED",
        "evidence": f"New artifact created in archival scope: {file_path}. Secretary SLA: index ≤30min.",
        "severity": "low",
        "file_path": file_path,
    }


# ── Helpers ───────────────────────────────────────────────────────────────

def _read_active_agent() -> str:
    """Read .ystar_active_agent file (fallback if not in payload metadata)."""
    try:
        active_agent_path = Path.cwd() / ".ystar_active_agent"
        if active_agent_path.exists():
            return active_agent_path.read_text().strip()
    except Exception:
        pass
    return "unknown"


# ── Registry ──────────────────────────────────────────────────────────────

# Export all detector functions for hook_observe.py integration
ALL_DETECTORS = [
    detect_czl_dispatch_missing_5tuple,
    detect_czl_receipt_rt_not_zero,
    detect_charter_drift_mid_session,
    detect_wave_scope_undeclared,
    detect_subagent_unauthorized_git_op,
    detect_realtime_artifact_archival_sla,
]
