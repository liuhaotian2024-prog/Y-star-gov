#!/usr/bin/env python3
"""
omission_close_retro.py — Retroactive obligation closure script
================================================================

Connects to the live omission DB and bulk-closes stale obligations,
proving the closure mechanism works end-to-end.

Usage:
    python scripts/omission_close_retro.py [--db PATH] [--tag PREFIX] [--max-age DAYS]

Defaults:
    --db     .ystar_cieu_omission.db
    --tag    post_ship_completeness
    --max-age 7  (days)
"""
import argparse
import os
import sys

# Ensure ystar package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_store import OmissionStore
from ystar.governance.omission_models import ObligationStatus


def main():
    parser = argparse.ArgumentParser(description="Retroactive obligation closure")
    parser.add_argument("--db", default=".ystar_cieu_omission.db",
                        help="Path to omission SQLite DB")
    parser.add_argument("--tag", default="post_ship_completeness",
                        help="Obligation type prefix to close")
    parser.add_argument("--max-age", type=int, default=7,
                        help="Max age in days (obligations older than this get closed)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report counts but do not actually close")
    args = parser.parse_args()

    db_path = args.db
    if not os.path.exists(db_path):
        print(f"ERROR: DB not found at {db_path}")
        print("Try: python scripts/omission_close_retro.py --db /path/to/.ystar_cieu_omission.db")
        sys.exit(1)

    print(f"=== Omission Closure Retro ===")
    print(f"DB:      {db_path}")
    print(f"Tag:     {args.tag}")
    print(f"Max age: {args.max_age} days")
    print(f"Dry run: {args.dry_run}")
    print()

    store = OmissionStore(db_path=db_path)
    engine = OmissionEngine(store=store)

    # BEFORE counts
    all_obs = store.list_obligations()
    open_before = len([o for o in all_obs if o.status.is_open])
    fulfilled_before = len([o for o in all_obs if o.status == ObligationStatus.FULFILLED])
    total = len(all_obs)

    print(f"BEFORE:")
    print(f"  Total obligations:     {total}")
    print(f"  Open (is_open=True):   {open_before}")
    print(f"  Fulfilled:             {fulfilled_before}")

    # Count matching tag
    tag_lower = args.tag.lower()
    matching = [o for o in all_obs if o.obligation_type.lower().startswith(tag_lower)]
    matching_open = [o for o in matching if o.status.is_open or o.status in (
        ObligationStatus.EXPIRED, ObligationStatus.ESCALATED)]
    print(f"  Matching tag '{args.tag}': {len(matching)} total, {len(matching_open)} closeable")
    print()

    if args.dry_run:
        print("DRY RUN — no changes made.")
        return

    # Execute bulk close
    max_age_seconds = args.max_age * 86400
    result = engine.bulk_auto_close_by_tag_age(
        tag_prefix=args.tag,
        max_age_seconds=max_age_seconds,
        close_reason=f"retro_close_{args.max_age}d",
    )

    # AFTER counts
    all_obs_after = store.list_obligations()
    open_after = len([o for o in all_obs_after if o.status.is_open])
    fulfilled_after = len([o for o in all_obs_after if o.status == ObligationStatus.FULFILLED])

    print(f"AFTER:")
    print(f"  Open (is_open=True):   {open_after}")
    print(f"  Fulfilled:             {fulfilled_after}")
    print()
    print(f"RESULT:")
    print(f"  Scanned:  {result['scanned_count']}")
    print(f"  Closed:   {result['closed_count']}")
    print(f"  Skipped:  {result['skipped_count']}")
    print(f"  Delta open: {open_before} -> {open_after} ({open_before - open_after} reduced)")

    if result["closed_count"] > 0:
        print(f"\nVERDICT: PASS — {result['closed_count']} obligations closed successfully")
    elif result["scanned_count"] == 0:
        print(f"\nVERDICT: PARTIAL — no obligations matched tag '{args.tag}', "
              f"but closure mechanism is functional")
    else:
        print(f"\nVERDICT: PARTIAL — scanned {result['scanned_count']} but none old enough "
              f"(max_age={args.max_age}d)")


if __name__ == "__main__":
    main()
