# Layer: Foundation
"""
ystar.rules.break_glass — Emergency enforcement bypass (priority 2000)
======================================================================

CZL-ARCH-5: Break-glass emergency override for lock-death scenarios.

When environment variable ``YSTAR_BREAK_GLASS=1`` is set, ALL
enforcement is bypassed — every action is ALLOWED.  Every action
taken during break-glass is logged with a CIEU event of type
``BREAK_GLASS_ACTIVE`` for post-incident review.

This is the escape hatch for lock-death scenarios where the
governance layer itself prevents agents from operating.  It runs
at priority 2000 (highest constitutional level) so it is evaluated
before any other router rule.

Usage:
    # Enable break-glass (in shell or .env):
    export YSTAR_BREAK_GLASS=1

    # Disable (restore normal enforcement):
    unset YSTAR_BREAK_GLASS

Security considerations:
  - Break-glass CIEU events have evidence_grade="break_glass" for
    easy filtering in ``ystar report`` and audit queries.
  - The break-glass session is tamper-evident: every single action
    during the window is recorded.
  - Intended for human-initiated emergency use only.

Author: eng-governance, CZL-ARCH-5 (2026-04-18).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List

from ystar.governance.router_registry import RouterResult, RouterRule

_log = logging.getLogger("ystar.rules.break_glass")

# Environment variable that activates break-glass mode
_BREAK_GLASS_ENV = "YSTAR_BREAK_GLASS"


# ══════════════════════════════════════════════════════════════════════
# Detector + Executor
# ══════════════════════════════════════════════════════════════════════

def _break_glass_detector(payload: Dict[str, Any]) -> bool:
    """
    Returns True when YSTAR_BREAK_GLASS=1 is set in the environment.

    This detector is intentionally simple and fast — it reads one
    environment variable.  No file I/O, no imports, no side effects.
    """
    return os.environ.get(_BREAK_GLASS_ENV) == "1"


def _break_glass_executor(payload: Dict[str, Any]) -> RouterResult:
    """
    Allow the action unconditionally and emit a BREAK_GLASS_ACTIVE CIEU event.

    Every action during break-glass is logged for post-incident review.
    The CIEU event includes the full tool name and agent ID for
    forensic reconstruction of the break-glass session.
    """
    tool_name = payload.get("tool_name", "unknown")
    agent_id = payload.get("agent_id", "unknown")

    # Emit CIEU event for audit trail
    try:
        from ystar.governance.cieu_store import CIEUStore
        store = CIEUStore()
        store.write_dict({
            "event_type": "BREAK_GLASS_ACTIVE",
            "entity_id": agent_id,
            "timestamp": time.time(),
            "decision": "allow",
            "evidence_grade": "break_glass",
            "params": {
                "tool_name": tool_name,
                "source": "ystar.rules.break_glass",
                "reason": "YSTAR_BREAK_GLASS=1 environment override active",
            }
        })
    except Exception as e:
        # Even if CIEU fails, break-glass MUST still allow the action.
        # Log to stderr as fallback.
        _log.warning("BREAK_GLASS CIEU emit failed: %s — action still allowed", e)

    _log.warning(
        "BREAK_GLASS_ACTIVE: allowing %s for agent %s (enforcement bypassed)",
        tool_name, agent_id,
    )

    return RouterResult(
        decision="allow",
        message=f"BREAK_GLASS_ACTIVE: enforcement bypassed for {tool_name} (agent={agent_id})",
    )


# ══════════════════════════════════════════════════════════════════════
# RouterRule definition
# ══════════════════════════════════════════════════════════════════════

break_glass_rule = RouterRule(
    rule_id="builtin.break_glass",
    detector=_break_glass_detector,
    executor=_break_glass_executor,
    priority=2000,  # Highest — evaluated before all other rules
    metadata={
        "phase": "ARCH-5",
        "description": "Emergency enforcement bypass via YSTAR_BREAK_GLASS=1 env var",
        "author": "eng-governance",
    },
)

# RULES export for load_rules_dir compatibility
RULES: List[RouterRule] = [break_glass_rule]


def register_break_glass_rule() -> bool:
    """
    Register the break-glass rule into the default RouterRegistry.

    Returns True if registered, False if already registered.
    """
    from ystar.governance.router_registry import get_default_registry
    registry = get_default_registry()
    try:
        registry.register_rule(break_glass_rule)
        return True
    except ValueError:
        return False  # Already registered
