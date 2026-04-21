#!/usr/bin/env python3
"""
Migration 003: Split route/dispatch out of rewrite canonical into new route bucket.

Operations:
  1. Print before-migration distribution (decision_canonical counts)
  2. UPDATE cieu_events SET decision_canonical='route'
     WHERE decision IN ('route','dispatch')
  3. Print after-migration distribution
  4. Verify: rewrite count should drop to ~7 (true REWRITE_APPLIED),
     route count should be ~56 (46 ROUTING_GATE_CHECK + 3 CTO_BROKER + others)

Per Maya CZL-REWRITE-AUDIT (2026-04-19): 56 events with decision_canonical='rewrite'
contained 46 ROUTING_GATE_CHECK + 3 CTO_BROKER dispatches that are routing decisions,
not corrective rewrites.  Only ~7 REWRITE_APPLIED events are real rewrites.

Author: Leo Chen (eng-kernel)
Date: 2026-04-19
Directive: Board CZL-NORMALIZER-V3-ROUTE-FIX
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

# Add project root to path so normalizer can be imported
_proj_root = Path(__file__).resolve().parents[3]  # Y-star-gov/
if str(_proj_root) not in sys.path:
    sys.path.insert(0, str(_proj_root))

from ystar.governance.cieu_decision_normalizer import CANONICAL_VALUES


def run_migration(db_path: str, *, dry_run: bool = False) -> dict:
    """
    Execute migration 003 on the given database.

    Args:
        db_path: Path to .ystar_cieu.db
        dry_run: If True, print what would happen but do not modify DB.

    Returns:
        dict with before_distribution, after_distribution,
        rewrite_before, rewrite_after, route_after, elapsed_seconds.
    """
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA journal_mode = WAL")

    result: dict = {}
    t0 = time.time()

    total_rows = conn.execute("SELECT COUNT(*) FROM cieu_events").fetchone()[0]
    result["row_count"] = total_rows
    print(f"[003] Total rows: {total_rows:,}")

    # ── Step 0: Pre-migration distribution ───────────────────────────
    before = conn.execute(
        "SELECT decision_canonical, COUNT(*) as n "
        "FROM cieu_events "
        "GROUP BY decision_canonical "
        "ORDER BY n DESC"
    ).fetchall()
    before_dist = {row[0]: row[1] for row in before}
    result["before_distribution"] = before_dist

    print("[003] BEFORE distribution (decision_canonical -> count):")
    for canonical, n in sorted(before_dist.items(), key=lambda x: -x[1]):
        print(f"  {str(canonical):20s}  {n:>8,}")

    rewrite_before = before_dist.get("rewrite", 0)
    route_before = before_dist.get("route", 0)
    result["rewrite_before"] = rewrite_before
    result["route_before"] = route_before
    print(f"\n[003] rewrite BEFORE: {rewrite_before}")
    print(f"[003] route BEFORE:   {route_before}")

    # Count how many rows will be affected
    affected = conn.execute(
        "SELECT COUNT(*) FROM cieu_events WHERE decision IN ('route', 'dispatch')"
    ).fetchone()[0]
    result["rows_to_migrate"] = affected
    print(f"[003] Rows to migrate (decision IN ('route','dispatch')): {affected}")

    if dry_run:
        print("[003] DRY RUN -- no changes made.")
        result["dry_run"] = True
        conn.close()
        return result

    # ── Step 1: UPDATE decision_canonical for route/dispatch ─────────
    conn.execute("BEGIN IMMEDIATE")
    try:
        updated = conn.execute(
            "UPDATE cieu_events SET decision_canonical = 'route' "
            "WHERE decision IN ('route', 'dispatch')"
        ).rowcount
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result["rows_updated"] = updated
    print(f"[003] Updated {updated} rows: decision_canonical 'rewrite' -> 'route'")

    # ── Step 2: Post-migration distribution ──────────────────────────
    after = conn.execute(
        "SELECT decision_canonical, COUNT(*) as n "
        "FROM cieu_events "
        "GROUP BY decision_canonical "
        "ORDER BY n DESC"
    ).fetchall()
    after_dist = {row[0]: row[1] for row in after}
    result["after_distribution"] = after_dist

    print(f"\n[003] AFTER distribution (decision_canonical -> count):")
    for canonical, n in sorted(after_dist.items(), key=lambda x: -x[1]):
        print(f"  {str(canonical):20s}  {n:>8,}")

    rewrite_after = after_dist.get("rewrite", 0)
    route_after = after_dist.get("route", 0)
    result["rewrite_after"] = rewrite_after
    result["route_after"] = route_after

    print(f"\n[003] rewrite AFTER:  {rewrite_after} (expected ~7)")
    print(f"[003] route AFTER:    {route_after} (expected ~56)")
    print(f"[003] Delta:          rewrite dropped by {rewrite_before - rewrite_after}, "
          f"route grew by {route_after - route_before}")

    # ── Step 3: Verify canonical values are all expected ─────────────
    after_canonicals = {row[0] for row in after if row[0] is not None}
    unexpected = after_canonicals - CANONICAL_VALUES
    if unexpected:
        print(f"[003] WARNING: unexpected canonical values: {unexpected}")
        result["clean"] = False
    else:
        print("[003] All canonical values in expected set -- CLEAN")
        result["clean"] = True

    elapsed = time.time() - t0
    result["elapsed_seconds"] = round(elapsed, 2)
    print(f"[003] Migration completed in {elapsed:.1f}s")

    conn.close()
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Migration 003: Split route/dispatch out of rewrite canonical"
    )
    parser.add_argument(
        "db_path",
        nargs="?",
        default=str(Path.home() / ".openclaw/workspace/ystar-company/.ystar_cieu.db"),
        help="Path to .ystar_cieu.db",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    result = run_migration(args.db_path, dry_run=args.dry_run)

    if not args.dry_run:
        print(f"\n[003] SUMMARY: {result['row_count']:,} rows, "
              f"rewrite {result['rewrite_before']}->{result['rewrite_after']}, "
              f"route {result['route_before']}->{result['route_after']}, "
              f"{result['rows_updated']} migrated, "
              f"{result['elapsed_seconds']}s elapsed")
