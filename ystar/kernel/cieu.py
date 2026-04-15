# Layer: Foundation
"""
ystar.kernel.cieu  —  CIEU Emit Shim  v0.1.0
==============================================

Compatibility shim for hook_wrapper.py and other callers expecting
`from ystar.kernel.cieu import emit`.

This module provides a simple emit() function that delegates to the
canonical CIEU infrastructure in ystar.governance.cieu_store.

Design:
  - emit() is a convenience wrapper for ad-hoc CIEU events
  - All writes go through CIEUStore for consistency
  - Silent-fail like all CIEU operations (never break execution path)
"""
from __future__ import annotations

from ystar.governance.cieu_store import CIEUStore

import logging
import os
import time
from typing import Any

_log = logging.getLogger("ystar.kernel.cieu")

# Default CIEU database path (can be overridden by environment)
_DEFAULT_CIEU_DB = os.environ.get("YSTAR_CIEU_DB", ".ystar_cieu.db")


def emit(
    event_type: str,
    agent: str | None = None,
    session_id: str | None = None,
    **kwargs: Any,
) -> None:
    """
    Emit a CIEU event with the given event_type and parameters.

    Args:
        event_type: Event type (e.g., "SKILL_ACTIVATION", "TASK_START")
        agent: Agent ID (defaults to YSTAR_ACTIVE_AGENT env var or "unknown")
        session_id: Session ID (defaults to YSTAR_SESSION_ID env var or "unknown")
        **kwargs: Additional parameters to record in the event

    This is a convenience function for callers that need quick CIEU emission.
    All writes go through CIEUStore for consistency.

    Silent-fail: any errors are logged but never raised.
    """
    try:
        from ystar.governance.cieu_store import CIEUStore

        # Resolve defaults from environment
        agent = agent or os.environ.get("YSTAR_ACTIVE_AGENT", "unknown")
        session_id = session_id or os.environ.get("YSTAR_SESSION_ID", "unknown")

        # Build event record
        event = {
            "session_id": session_id,
            "agent_id": agent,
            "event_type": event_type,
            "decision": "info",  # emit() is for informational events
            "passed": True,
            "violations": [],
            "params": {
                "ts": time.time(),
                **kwargs,
            },
            "contract_hash": "",
            "evidence_grade": "ops",  # Operational/diagnostic event
        }

        # Write to CIEU database
        db_path = os.environ.get("YSTAR_CIEU_DB", _DEFAULT_CIEU_DB)
        store = CIEUStore(db_path)
        store.write_dict(event)

        _log.debug(f"CIEU event emitted: {event_type} (agent={agent})")

    except Exception as e:
        # Silent-fail: CIEU emission failures must never break execution
        _log.error(f"CIEU emit failed (non-fatal): {e}", exc_info=True)


__all__ = ["emit", "CIEUStore"]
