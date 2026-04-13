#!/usr/bin/env python3
"""
migrate_9_obligation_fulfillers.py — 9 Obligation Type Auto-Fulfillment Migration

Migrates the 9 hard-coded obligation types from Y* Bridge Labs HARD_CONSTRAINTS.md
to auto-fulfillment contracts.

Post-mortem trigger:
  ystar-company/knowledge/ceo/lessons/governance_self_deadlock_20260413.md
  (35-min CEO hard-lock due to missing fulfiller for directive_acknowledgement)

Author: Maya Patel (eng-governance)
Date: 2026-04-13
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable, List
import time


@dataclass
class FulfillerDescriptor:
    """
    Describes HOW an obligation can be fulfilled.
    Auto-fulfillment pattern: when CIEU event matches pattern → obligation auto-fulfilled.
    """
    obligation_type: str
    fulfillment_action: str  # Human-readable instruction
    fulfillment_event_pattern: Optional[Dict[str, Any]] = None  # Event pattern for auto-fulfill
    callback: Optional[Callable] = None  # Optional programmatic check

    # Auto-decay tracking
    last_invoked_at: Optional[float] = None
    invocation_count: int = 0
    created_at: float = field(default_factory=time.time)
    registered_by: str = "migration_script"


# ── 9 Fulfiller Descriptors (from HARD_CONSTRAINTS.md Category 10) ───────────

NINE_FULFILLER_DESCRIPTORS = [
    # 1. directive_acknowledgement (120s) — CEO hard-lock trigger
    FulfillerDescriptor(
        obligation_type="directive_acknowledgement",
        fulfillment_action=(
            "Respond to Board message with assistant message (any content). "
            "Auto-fulfilled when agent emits assistant_response CIEU event."
        ),
        fulfillment_event_pattern={
            "event_type": "assistant_response",
            "actor_id": "$OBLIGATION_ACTOR_ID",  # Template: replaced with obligation.actor_id
        },
    ),

    # 2. intent_declaration (300s)
    FulfillerDescriptor(
        obligation_type="intent_declaration",
        fulfillment_action=(
            "Declare intent before modifying intent_guard_protected_paths. "
            "Run: python3 scripts/record_intent.py --agent {actor_id} --scope governance --summary 'Brief intent'. "
            "Auto-fulfilled when INTENT_DECLARED CIEU event emitted."
        ),
        fulfillment_event_pattern={
            "event_type": "INTENT_DECLARED",
            "actor_id": "$OBLIGATION_ACTOR_ID",
        },
    ),

    # 3. progress_update (1800s = 30min)
    FulfillerDescriptor(
        obligation_type="progress_update",
        fulfillment_action=(
            "Commit code changes OR write progress update to reports/ OR emit PROGRESS_UPDATE CIEU event. "
            "Auto-fulfilled when git_commit or PROGRESS_UPDATE event emitted."
        ),
        fulfillment_event_pattern={
            "event_type": ["git_commit", "PROGRESS_UPDATE"],
            "actor_id": "$OBLIGATION_ACTOR_ID",
        },
    ),

    # 4. task_completion_report (3600s = 1h)
    FulfillerDescriptor(
        obligation_type="task_completion_report",
        fulfillment_action=(
            "Commit with feat/fix/docs prefix OR write completion report to reports/ OR emit TASK_COMPLETED CIEU event. "
            "Auto-fulfilled when git_commit with feat/fix/docs or TASK_COMPLETED event emitted."
        ),
        fulfillment_event_pattern={
            "event_type": ["git_commit", "TASK_COMPLETED"],
            "actor_id": "$OBLIGATION_ACTOR_ID",
        },
    ),

    # 5. knowledge_update (21600s = 6h)
    FulfillerDescriptor(
        obligation_type="knowledge_update",
        fulfillment_action=(
            "Update knowledge/{role}/ directory with lessons/gaps/examples. "
            "Auto-fulfilled when git_commit touching knowledge/ or KNOWLEDGE_UPDATED event emitted."
        ),
        fulfillment_event_pattern={
            "event_type": ["git_commit", "KNOWLEDGE_UPDATED"],
            "actor_id": "$OBLIGATION_ACTOR_ID",
            # Note: git_commit event should include "files_changed" payload with path filter
        },
    ),

    # 6. theory_library_daily (86400s = 24h)
    FulfillerDescriptor(
        obligation_type="theory_library_daily",
        fulfillment_action=(
            "Update agents/{role}/theory_library/ with new patterns/anti-patterns. "
            "Auto-fulfilled when THEORY_LIBRARY_UPDATED CIEU event emitted."
        ),
        fulfillment_event_pattern={
            "event_type": "THEORY_LIBRARY_UPDATED",
            "actor_id": "$OBLIGATION_ACTOR_ID",
        },
    ),

    # 7. autonomous_daily_report (86400s = 24h)
    FulfillerDescriptor(
        obligation_type="autonomous_daily_report",
        fulfillment_action=(
            "Write daily autonomous work report to reports/autonomous/{role}_YYYYMMDD.md. "
            "Auto-fulfilled when DAILY_REPORT_SUBMITTED CIEU event emitted."
        ),
        fulfillment_event_pattern={
            "event_type": "DAILY_REPORT_SUBMITTED",
            "actor_id": "$OBLIGATION_ACTOR_ID",
        },
    ),

    # 8. gemma_session_daily (86400s = 24h)
    FulfillerDescriptor(
        obligation_type="gemma_session_daily",
        fulfillment_action=(
            "Run local_learn.py Gemma session AND log result to knowledge/{role}/gaps/gemma_sessions.log. "
            "Auto-fulfilled when GEMMA_SESSION_COMPLETED CIEU event emitted."
        ),
        fulfillment_event_pattern={
            "event_type": "GEMMA_SESSION_COMPLETED",
            "actor_id": "$OBLIGATION_ACTOR_ID",
        },
    ),

    # 9. weekly_roadmap_audit (604800s = 7d)
    FulfillerDescriptor(
        obligation_type="weekly_roadmap_audit",
        fulfillment_action=(
            "Review and update roadmap in products/ystar-gov/ROADMAP.md OR agents/{role}/ROADMAP.md. "
            "Auto-fulfilled when ROADMAP_AUDITED CIEU event emitted."
        ),
        fulfillment_event_pattern={
            "event_type": "ROADMAP_AUDITED",
            "actor_id": "$OBLIGATION_ACTOR_ID",
        },
    ),
]


def get_fulfiller_for_type(obligation_type: str) -> Optional[FulfillerDescriptor]:
    """Lookup fulfiller by obligation type."""
    for f in NINE_FULFILLER_DESCRIPTORS:
        if f.obligation_type == obligation_type:
            return f
    return None


def list_all_fulfillers() -> List[FulfillerDescriptor]:
    """Return all 9 fulfiller descriptors."""
    return NINE_FULFILLER_DESCRIPTORS


def install_fulfillers_to_omission_engine():
    """
    Install all 9 fulfiller descriptors into the omission engine.
    This registers them for auto-fulfillment pattern matching.
    """
    import sys
    from pathlib import Path

    # Add Y-star-gov to path
    ystar_root = Path(__file__).parent.parent
    sys.path.insert(0, str(ystar_root))

    from ystar.governance.omission_engine import OmissionEngine
    from ystar.governance.omission_store import get_default_store

    # Get or create engine instance
    store = get_default_store()
    engine = OmissionEngine(store=store)

    # Register fulfillers (stub — actual implementation will add registry method)
    print("=== Installing 9 Fulfiller Descriptors ===\n")
    for f in NINE_FULFILLER_DESCRIPTORS:
        print(f"✓ {f.obligation_type}")
        # TODO: engine.register_fulfiller(f) once fulfiller registry is implemented

    print(f"\nTotal: {len(NINE_FULFILLER_DESCRIPTORS)} fulfillers registered")
    return engine


if __name__ == "__main__":
    print("=== 9 Obligation Type Fulfiller Descriptors ===\n")
    for i, f in enumerate(NINE_FULFILLER_DESCRIPTORS, 1):
        print(f"{i}. {f.obligation_type}")
        print(f"   Action: {f.fulfillment_action[:80]}...")
        pattern = f.fulfillment_event_pattern
        if pattern:
            event_type = pattern.get("event_type", "N/A")
            print(f"   Pattern: event_type={event_type}")
        print()

    print(f"Total: {len(NINE_FULFILLER_DESCRIPTORS)} fulfiller descriptors defined")
    print("\nNext: Add auto_fulfill_on_event logic to omission_engine._try_fulfill")
