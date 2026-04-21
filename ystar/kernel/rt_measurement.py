"""
ystar.kernel.rt_measurement — Rt+1 Measurement CIEU Event Schema v1.1
======================================================================

This module provides the canonical interface for emitting RT_MEASUREMENT events
to the CIEU database, recording 5-tuple task closure metrics:
    Y* (ideal contract), Xt (pre-state), U (actions), Yt+1 (post-state), Rt+1 (gap)

Design Philosophy (Kernel Perspective):
    - Rt+1 = residual_violations + unclosed_subtasks + unresolved_subagent_errors
    - MVP relies on agent self-report (rt_value is manually computed and passed in)
    - Kernel does NOT auto-calculate Rt+1 in v1.0 — this is future Phase 2 work
    - Emit contract is fail-open (no exceptions raised on write failure)

Future Enhancement (Phase 2+):
    - Auto-calculation: Parse U actions, check CIEU DB for violations/subtasks
    - Causal chain: Link RT_MEASUREMENT to preceding CIEU events via task_id
    - Real-time streaming: SSE/webhook for Rt>0 gap alerts

Schema Version: 1.1
Changelog:
    - v1.1 (2026-04-16): Add framework_applied field for methodology analytics
    - v1.0 (2026-04-15): Initial 5-tuple schema
Author: eng-kernel
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Import canonical CIEU emit helper from company repo
# (Note: This module lives in Y-star-gov but emits to ystar-company's DB)
try:
    from ystar.workspace_config import get_labs_workspace
    _ws = get_labs_workspace()
    if _ws is not None:
        _scripts_dir = str(_ws / "scripts")
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
    from _cieu_helpers import emit_cieu, _get_canonical_agent
except ImportError:
    # Fallback for test environments or standalone mode
    def emit_cieu(*args, **kwargs) -> bool:
        """Stub emit for isolated tests."""
        return True

    def _get_canonical_agent() -> str:
        """Stub agent ID getter."""
        return "test-kernel"


def emit_rt_measurement(
    task_id: str,
    y_star: str,
    x_t: str,
    u: list[str],
    y_t_plus_1: str,
    rt_value: float,
    role_tags: dict[str, str],
    agent_id: str | None = None,
    framework_applied: list[str] | None = None,
) -> None:
    """
    Emit RT_MEASUREMENT CIEU event recording task closure gap.

    This is the canonical interface for all agents to report Rt+1 measurements.
    Writes to CIEU DB with schema version 1.1.

    Args:
        task_id: UUID or semantic ID linking related CIEU events (e.g., "ceo_task_42")
        y_star: Ideal contract predicate (verifiable success condition)
        x_t: Measured pre-state (tool_use observation, not impression)
        u: Actions taken (list of concrete tool calls / ops)
        y_t_plus_1: Measured post-state (tool_use verification)
        rt_value: Residual gap value (0.0 = clean closure, >0 = incomplete)
        role_tags: Three-dimensional role attribution:
            {"producer": "ceo", "executor": "eng-kernel", "governed": "eng-kernel"}
        agent_id: Override agent identity (defaults to canonical active agent)
        framework_applied: Methodology frameworks used (e.g., ["OODA", "PDCA"], default [])

    Returns:
        None (fail-open, no exceptions raised)

    Example:
        >>> emit_rt_measurement(
        ...     task_id="ceo_k9_fuse_001",
        ...     y_star="RT schema + tests pass",
        ...     x_t="No rt_measurement.py file exists",
        ...     u=["Write rt_measurement.py", "Write test_rt_measurement.py", "pytest"],
        ...     y_t_plus_1="6/6 tests pass, no violations",
        ...     rt_value=0.0,
        ...     role_tags={"producer": "ceo", "executor": "eng-kernel", "governed": "eng-kernel"},
        ...     framework_applied=["12-layer", "CIEU-5tuple"],
        ... )
    """
    try:
        # Auto-detect agent_id from canonical registry if not provided
        if agent_id is None:
            agent_id = _get_canonical_agent()

        # Default framework_applied to empty list if not provided
        if framework_applied is None:
            framework_applied = []

        # Build RT measurement 5-tuple + metadata
        rt_data = {
            "schema_version": "1.1",
            "task_id": task_id,
            "rt_value": rt_value,
            "y_star": y_star,
            "x_t": x_t,
            "u": u,
            "y_t_plus_1": y_t_plus_1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "role_tags": role_tags,
            "framework_applied": framework_applied,
        }

        # Emit to CIEU DB via canonical helper
        # params_json stores the full 5-tuple structure
        emit_cieu(
            event_type="RT_MEASUREMENT",
            decision="info",
            passed=1 if rt_value == 0.0 else 0,  # 0.0 = success, >0 = gap
            task_description=f"Rt+1={rt_value:.2f} for task {task_id}",
            params_json=json.dumps(rt_data),
            agent_id=agent_id,  # Override canonical detection if explicitly passed
        )

    except Exception as e:
        # Fail-open: RT measurement failures must never block execution
        sys.stderr.write(f"[RT_MEASUREMENT_EMIT_ERROR] task={task_id}: {e}\n")


__all__ = ["emit_rt_measurement"]
