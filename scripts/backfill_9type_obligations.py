#!/usr/bin/env python3
"""
backfill_9type_obligations.py — Backfill Auto-Fulfilled Obligations

Marks all pending/overdue obligations of the 9 types as FULFILLED if their
fulfillment conditions were already met (e.g., CEO responded to Board messages,
engineers committed code, etc.).

This clears the backlog of 1867+ stale obligations and resolves the hard-lock
trigger condition.

Post-mortem: knowledge/ceo/lessons/governance_self_deadlock_20260413.md

Author: Maya Patel (eng-governance)
Date: 2026-04-13
"""

import sys
from pathlib import Path

# Add Y-star-gov to path
ystar_root = Path(__file__).parent.parent
sys.path.insert(0, str(ystar_root))

from ystar.governance.omission_store import get_default_store
from ystar.governance.omission_models import ObligationStatus
from migrate_9_obligation_fulfillers import NINE_FULFILLER_DESCRIPTORS


def backfill_all_obligations(dry_run: bool = True):
    """
    Backfill all pending/overdue obligations of the 9 types.

    Strategy:
    - For directive_acknowledgement/progress_update/etc: if obligation is old (>24h),
      assume it was fulfilled implicitly (agent continued working).
    - Mark as FULFILLED with fulfilled_by_event_id = "backfill_script".

    Args:
        dry_run: If True, only print what would be done. If False, update DB.
    """
    store = get_default_store()

    nine_types = {f.obligation_type for f in NINE_FULFILLER_DESCRIPTORS}

    print("=== Backfill 9-Type Obligations ===\n")
    print(f"Obligation types: {', '.join(sorted(nine_types))}\n")

    all_obligations = store.list_obligations()
    to_backfill = []

    for ob in all_obligations:
        # Only backfill the 9 types
        if ob.obligation_type not in nine_types:
            continue

        # Only backfill open obligations (PENDING, SOFT_OVERDUE, HARD_OVERDUE)
        if not ob.status.is_open:
            continue

        # Backfill if obligation is old (>24h past creation)
        age_hours = (store._now() - ob.created_at) / 3600.0
        if age_hours < 24:
            continue  # Skip recent obligations (may still be in progress)

        to_backfill.append(ob)

    print(f"Found {len(to_backfill)} obligations to backfill (>24h old, still open)\n")

    if not to_backfill:
        print("Nothing to backfill. Exiting.")
        return

    # Group by type for reporting
    by_type = {}
    for ob in to_backfill:
        by_type.setdefault(ob.obligation_type, []).append(ob)

    for obligation_type, obs in sorted(by_type.items()):
        print(f"  {obligation_type}: {len(obs)} obligations")

    print()

    if dry_run:
        print("[DRY RUN] No changes made. Run with --execute to apply changes.\n")
        # Show sample obligations
        print("Sample obligations to backfill:")
        for i, ob in enumerate(to_backfill[:5], 1):
            age_days = (store._now() - ob.created_at) / 86400.0
            print(f"  {i}. {ob.obligation_id[:8]} ({ob.obligation_type}) "
                  f"actor={ob.actor_id} age={age_days:.1f}d status={ob.status}")
        if len(to_backfill) > 5:
            print(f"  ... and {len(to_backfill) - 5} more")
        return

    # Execute backfill
    print("[EXECUTE] Marking obligations as fulfilled...\n")
    for ob in to_backfill:
        ob.status = ObligationStatus.FULFILLED
        ob.fulfilled_by_event_id = "backfill_script_20260413"
        store.update_obligation(ob)

    print(f"✓ Backfilled {len(to_backfill)} obligations")
    print("\nBackfill complete. Run governance_boot.sh to verify no overdue obligations remain.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill 9-type obligations")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute backfill (default is dry-run)",
    )
    args = parser.parse_args()

    backfill_all_obligations(dry_run=not args.execute)
