# Layer: Foundation
"""
RULE-CHARTER-001: Charter Amendment Flow Enforcement

Source: governance/BOARD_CHARTER_AMENDMENTS.md lines 1-25
Authority: Board charter amendment flow (2026-04-10 update)

Protocol being enforced:
    Board expresses amendment intent
    -> Secretary records in BOARD_CHARTER_AMENDMENTS.md
    -> Secretary executes the edit (AGENTS.md or other charter files)
    -> Secretary commits, sends Board the commit hash
    -> Secretary updates amendment status to "completed"

This rule detects when a NON-secretary agent attempts to write to charter
files (AGENTS.md, .claude/agents/*.md, BOARD_CHARTER_AMENDMENTS.md) and
returns a REDIRECT decision instructing the agent to route the change
through Samantha-Secretary instead.

Secretary role is allowed through (returns ALLOW) because she is the
designated executor per the Board-approved flow.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from ystar.governance.router_registry import RouterResult, RouterRule


# ── Charter file patterns ──────────────────────────────────────────────

# Files protected by the charter amendment flow.
# Matched against the file_path in Write/Edit tool_input.
CHARTER_FILE_PATTERNS = [
    re.compile(r"AGENTS\.md$"),
    re.compile(r"BOARD_CHARTER_AMENDMENTS\.md$"),
    re.compile(r"\.claude/agents/[^/]+\.md$"),
]

# Tools that modify files (Write, Edit, NotebookEdit).
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}

# Agent tool (for sub-agent spawns targeting charter changes).
AGENT_TOOL = "Agent"

# Secretary identities that are ALLOWED to edit charter files.
SECRETARY_IDENTITIES = {
    "secretary",
    "samantha",
    "samantha-secretary",
    "eng-secretary",
}

# Injected context: the charter amendment flow header from
# BOARD_CHARTER_AMENDMENTS.md (hardcoded to avoid file I/O in detector).
CHARTER_FLOW_CONTEXT = """## Charter Amendment Flow (Board 2026-04-10)

1. Board expresses amendment intent (verbal or written)
2. Secretary records in BOARD_CHARTER_AMENDMENTS.md (content, rationale, Board auth timestamp)
3. Secretary executes the edit directly (AGENTS.md or other charter files)
4. Secretary commits, sends Board the commit hash
5. Secretary updates amendment status in BOARD_CHARTER_AMENDMENTS.md

IMPORTANT: Only Secretary (Samantha) executes charter amendments.
Other roles must route through Secretary, not edit charter files directly."""


# ── Detector ───────────────────────────────────────────────────────────

def _is_charter_file(file_path: str) -> bool:
    """Check if a file path matches any charter file pattern."""
    if not file_path:
        return False
    for pattern in CHARTER_FILE_PATTERNS:
        if pattern.search(file_path):
            return True
    return False


def _get_agent_id(payload: Dict[str, Any]) -> str:
    """Extract agent_id from payload, normalized to lowercase."""
    agent_id = (
        payload.get("agent_id", "")
        or payload.get("agentId", "")
        or ""
    )
    return agent_id.lower().strip()


def _is_secretary(agent_id: str) -> bool:
    """Check if the agent_id belongs to the Secretary role."""
    return agent_id in SECRETARY_IDENTITIES


def detect_charter_amendment(payload: Dict[str, Any]) -> bool:
    """
    Detect attempts to modify charter files by non-secretary agents.

    Returns True (rule fires) when:
    - Tool is Write/Edit/NotebookEdit AND file_path matches a charter file
      AND agent is NOT secretary
    - Tool is Agent AND the spawn prompt references charter file edits
      AND spawned subagent is NOT secretary

    Returns False (rule does not fire) when:
    - Secretary is the actor (allowed per protocol)
    - Target file is not a charter file
    - Tool is not a write/agent tool

    Detector is pure (no side effects) and fast (<1ms).
    """
    tool_name = payload.get("tool_name", "") or payload.get("toolName", "")
    tool_input = payload.get("tool_input", {}) or payload.get("input", {})
    if not isinstance(tool_input, dict):
        return False

    agent_id = _get_agent_id(payload)

    # ── Case 1: Direct Write/Edit to a charter file ───────────────
    if tool_name in WRITE_TOOLS:
        file_path = tool_input.get("file_path", "")
        if _is_charter_file(file_path) and not _is_secretary(agent_id):
            return True

    # ── Case 2: Agent spawn targeting charter files ───────────────
    if tool_name == AGENT_TOOL:
        # Check if the spawn prompt references charter files
        prompt = tool_input.get("prompt", "")
        subagent_type = (tool_input.get("subagent_type", "") or "").lower()

        # If spawning secretary, allow (she is the designated executor)
        if subagent_type in SECRETARY_IDENTITIES:
            return False

        # Check if prompt references charter file editing
        if not _is_secretary(agent_id):
            charter_refs = [
                "AGENTS.md",
                "BOARD_CHARTER_AMENDMENTS.md",
                ".claude/agents/",
            ]
            prompt_lower = prompt.lower() if prompt else ""
            for ref in charter_refs:
                if ref.lower() in prompt_lower:
                    # Check if it's an edit intent (not just reading)
                    edit_signals = [
                        "edit", "modify", "change", "update", "write",
                        "add", "remove", "delete", "amend", "revise",
                    ]
                    for signal in edit_signals:
                        if signal in prompt_lower:
                            return True

    return False


# ── Executor ───────────────────────────────────────────────────────────

def execute_charter_redirect(payload: Dict[str, Any]) -> RouterResult:
    """
    Return a REDIRECT result instructing the agent to route through Secretary.

    Provides:
    - fix_command: the Agent call to spawn Samantha-Secretary
    - injected_context: the charter amendment flow (the 4-step process)
    - message: human-readable explanation of what went wrong and how to fix
    """
    tool_name = payload.get("tool_name", "") or payload.get("toolName", "")
    tool_input = payload.get("tool_input", {}) or payload.get("input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}
    agent_id = _get_agent_id(payload)
    file_path = tool_input.get("file_path", "") or ""

    # Build a description of what was attempted
    if tool_name in WRITE_TOOLS:
        attempted = f"{agent_id} tried to {tool_name} {file_path}"
    else:
        attempted = f"{agent_id} tried to spawn sub-agent to edit charter files"

    # Build the fix command
    fix_command = (
        "Agent(subagent_type='Samantha-Secretary', "
        "prompt='Charter amendment requested. "
        "Please record this amendment intent in BOARD_CHARTER_AMENDMENTS.md, "
        "then execute the edit per the charter amendment flow. "
        f"Original intent: {tool_name} on {file_path}')"
    )

    message = (
        f"CHARTER FLOW VIOLATION: {attempted}. "
        f"Charter files (AGENTS.md, BOARD_CHARTER_AMENDMENTS.md, .claude/agents/*.md) "
        f"may only be edited by Secretary (Samantha) per Board 2026-04-10 directive. "
        f"FIX: Route this change through Secretary. "
        f"Command: {fix_command}"
    )

    return RouterResult(
        decision="redirect",
        message=message,
        injected_context=CHARTER_FLOW_CONTEXT,
        args={
            "fix_command": fix_command,
            "attempted_tool": tool_name,
            "attempted_file": file_path,
            "violating_agent": agent_id,
        },
    )


# ── Rule Registration ──────────────────────────────────────────────────

RULES = [
    RouterRule(
        rule_id="RULE-CHARTER-001",
        detector=detect_charter_amendment,
        executor=execute_charter_redirect,
        priority=1000,  # Constitutional: charter is highest authority
        metadata={
            "source": "governance/BOARD_CHARTER_AMENDMENTS.md:1-25",
            "authority": "Board charter amendment flow (2026-04-10)",
            "description": (
                "Redirect non-secretary charter file edits to Samantha-Secretary. "
                "Enforces the 4-step amendment flow."
            ),
            "phase": "P2-d-pilot",
            "cieu_event": "CHARTER_FLOW_REDIRECT",
        },
    ),
]
