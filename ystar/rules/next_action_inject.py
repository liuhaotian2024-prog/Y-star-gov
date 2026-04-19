# Layer: Foundation
"""
ystar.rules.next_action_inject — NEXT_ACTION hint injection (priority 50)
=========================================================================

CZL-ARCH-8: On every ALLOW decision for tool calls (Bash, Edit, Write),
inject the agent's next action hint from dispatch_board.json so the agent
never has to poll for its next task.

Logic (mirrors CEO demonstrator ``goal_2_next_action_inject_pattern.py``):

  1. Agent has a claimed task → NEXT: resume it
  2. Agent has no claimed task but open tasks exist → NEXT: claim highest-priority
  3. No tasks at all → empty (no injection)

The rule returns ``RouterResult(decision="inject", injected_context=...)``
when a hint is available, or ``RouterResult(decision="allow")`` when there
is nothing to surface.

Author: eng-kernel, CZL-ARCH-8 (2026-04-18).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from ystar.governance.router_registry import RouterResult, RouterRule

_log = logging.getLogger("ystar.rules.next_action_inject")

# Tools that trigger injection (high-frequency agent actions)
_INJECTABLE_TOOLS = {"Bash", "Edit", "Write"}

# Default board path — overridable via payload["dispatch_board_path"]
_DEFAULT_BOARD_PATH = "governance/dispatch_board.json"


# ══════════════════════════════════════════════════════════════════════
# Board reader
# ══════════════════════════════════════════════════════════════════════

def _read_board(board_path: str) -> Dict[str, Any]:
    """Read dispatch_board.json, returning empty structure on any failure."""
    p = Path(board_path)
    if not p.exists():
        return {"tasks": []}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"tasks": []}


def _next_for_agent(agent_id: str, board_path: str) -> str:
    """
    Compute NEXT_ACTION hint for the given agent.

    Returns a non-empty string when there is a hint, or empty string
    when nothing to surface (agent is free).
    """
    board = _read_board(board_path)
    tasks = board.get("tasks", [])

    # Rule 1: claimed task not yet completed → continue it
    for t in tasks:
        if t.get("status") == "claimed" and t.get("claimed_by") == agent_id:
            desc = (t.get("description") or "")[:140]
            return (
                f"NEXT: resume claimed task {t['atomic_id']}\n"
                f"  scope: {t.get('scope', '')}\n"
                f"  desc:  {desc}"
            )

    # Rule 2: open task → claim the highest-priority open
    open_tasks = [t for t in tasks if t.get("status") == "open"]
    priority_rank = {"P0": 0, "P1": 1, "P2": 2}
    open_tasks.sort(key=lambda t: priority_rank.get(t.get("urgency", "P2"), 9))
    if open_tasks:
        t = open_tasks[0]
        return (
            f"NEXT: claim open task {t['atomic_id']}\n"
            f"  urgency: {t.get('urgency', '?')}\n"
            f"  scope:   {t.get('scope', '')}"
        )

    # Rule 3: no tasks → nothing to inject
    return ""


# ══════════════════════════════════════════════════════════════════════
# Detector + Executor
# ══════════════════════════════════════════════════════════════════════

def _next_action_detector(payload: Dict[str, Any]) -> bool:
    """
    Match when tool_name is in the injectable set AND the upstream
    decision is 'allow'.  Payload must carry ``decision`` and
    ``tool_name`` keys.
    """
    tool = payload.get("tool_name", "")
    decision = payload.get("decision", "")
    return tool in _INJECTABLE_TOOLS and decision == "allow"


def _next_action_executor(payload: Dict[str, Any]) -> RouterResult:
    """
    Query dispatch_board.json for the agent's next action and return
    an INJECT result with the hint, or plain ALLOW if nothing to say.
    """
    agent_id = payload.get("agent_id", "unknown")
    board_path = payload.get("dispatch_board_path", _DEFAULT_BOARD_PATH)

    hint = _next_for_agent(agent_id, board_path)

    if hint:
        return RouterResult(
            decision="inject",
            message=f"Next action hint injected for {agent_id}",
            injected_context=hint,
        )
    else:
        return RouterResult(
            decision="allow",
            message="No pending tasks — no injection needed",
        )


# ══════════════════════════════════════════════════════════════════════
# RouterRule definition
# ══════════════════════════════════════════════════════════════════════

next_action_inject_rule = RouterRule(
    rule_id="builtin.next_action_inject",
    detector=_next_action_detector,
    executor=_next_action_executor,
    priority=50,  # Advisory tier
    metadata={
        "phase": "ARCH-8",
        "description": "Inject NEXT_ACTION hint from dispatch_board on allow decisions",
        "author": "eng-kernel",
    },
)

# RULES export for load_rules_dir compatibility
RULES: List[RouterRule] = [next_action_inject_rule]


def register_next_action_rule(registry=None) -> bool:
    """
    Register the next-action-inject rule into the given registry
    (or the default singleton).

    Returns True if registered, False if already registered.
    """
    if registry is None:
        from ystar.governance.router_registry import get_default_registry
        registry = get_default_registry()
    try:
        registry.register_rule(next_action_inject_rule)
        return True
    except ValueError:
        return False  # Already registered
