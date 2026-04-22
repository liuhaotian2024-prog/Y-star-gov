#!/usr/bin/env python3
"""
CLI runner for CIEU Brain Learning Cycle (ARCH-18 Phase 3).

Intended for cron/launchd invocation:
    python3 scripts/cieu_brain_learning_cycle.py [--brain-db PATH] [--cieu-db PATH] [--window SECS]

Defaults look for DBs at the standard ystar-company workspace paths.
"""

import argparse
import os
import sys

# Ensure ystar package is importable
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from ystar.governance.cieu_brain_learning import run_learning_cycle


_DEFAULT_COMPANY = os.path.expanduser(
    "~/.openclaw/workspace/ystar-company"
)


def main():
    parser = argparse.ArgumentParser(
        description="Run CIEU brain learning cycle (dim-centroid drift + embedding refinement)"
    )
    parser.add_argument(
        "--brain-db",
        default=os.path.join(_DEFAULT_COMPANY, "aiden_brain.db"),
        help="Path to brain SQLite DB",
    )
    parser.add_argument(
        "--cieu-db",
        default=os.path.join(_DEFAULT_COMPANY, ".ystar_cieu.db"),
        help="Path to CIEU events SQLite DB",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=86400,
        help="Lookback window in seconds (default: 86400 = 24h)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.brain_db):
        print(f"ERROR: brain DB not found at {args.brain_db}", file=sys.stderr)
        sys.exit(1)

    print(f"Brain DB : {args.brain_db}")
    print(f"CIEU DB  : {args.cieu_db}")
    print(f"Window   : {args.window}s")
    print()

    result = run_learning_cycle(
        brain_db_path=args.brain_db,
        cieu_db_path=args.cieu_db if os.path.exists(args.cieu_db) else None,
        window_sec=args.window,
    )

    drift = result["drift_summary"]
    print(f"Drift    : {drift['updated']} nodes updated, {drift['skipped']} skipped, {drift['total']} total")
    print(f"Centroids: {result['centroid_count']} event_types written to event_type_coords")
    print(f"Event ID : {result['event_id']}")
    print()
    print("Learning cycle complete.")


if __name__ == "__main__":
    main()
