#!/usr/bin/env python3
"""
Migration 002: Add training_eligible column + re-normalize decision_canonical
with v2 escape-aware normalizer.

Operations:
  1. ALTER TABLE cieu_events ADD COLUMN training_eligible INTEGER DEFAULT 0
  2. Backfill training_eligible: 1 if created_at >= 2026-04-16 05:07:20 UTC, else 0
  3. CREATE INDEX idx_training_eligible_decision on (training_eligible, decision_canonical)
  4. Re-normalize decision_canonical using v2 normalizer (raw_decision, passed)
     to reclassify warn+passed=0 from escalate -> escape
  5. Print distribution: decision_canonical x passed x training_eligible

Per Board 2026-04-19 Finding 1: warn+passed=0 = escape, not escalate.
Per Board 2026-04-19 Finding 2: Pre-hook events before 2026-04-16 05:07:20 are
contamination-suspect (21.4% of positive samples).

Author: Leo Chen (eng-kernel)
Date: 2026-04-19
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

from ystar.governance.cieu_decision_normalizer import (
    CANONICAL_VALUES,
    normalize,
)

# PreToolUse hook registration anchor: first HOOK_PRE_CALL CIEU event
# Board 2026-04-19 Finding 2
HOOK_REGISTRATION_EPOCH_ISO = "2026-04-16T05:07:20"
HOOK_REGISTRATION_EPOCH_UNIX = 1776316040.0  # exact epoch seconds for 2026-04-16 05:07:20 UTC


def run_migration(db_path: str, *, dry_run: bool = False) -> dict:
    """
    Execute migration 002 on the given database.

    Args:
        db_path: Path to .ystar_cieu.db
        dry_run: If True, print what would happen but do not modify DB.

    Returns:
        dict with before_distribution, after_distribution,
        training_eligible_counts, elapsed_seconds.
    """
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")

    result: dict = {}
    t0 = time.time()

    total_rows = conn.execute("SELECT COUNT(*) FROM cieu_events").fetchone()[0]
    result["row_count"] = total_rows
    print(f"[002] Total rows: {total_rows:,}")

    # ── Step 0: Pre-migration distribution ───────────────────────────
    before = conn.execute(
        "SELECT decision_canonical, passed, COUNT(*) as n "
        "FROM cieu_events "
        "GROUP BY decision_canonical, passed "
        "ORDER BY n DESC"
    ).fetchall()
    before_dist = [(row[0], row[1], row[2]) for row in before]
    result["before_distribution"] = before_dist
    print("[002] Before distribution (decision_canonical, passed, count):")
    for canonical, passed, n in before_dist:
        print(f"  {str(canonical):20s}  passed={passed}  {n:>8,}")

    if dry_run:
        print("[002] DRY RUN -- no changes made.")
        result["dry_run"] = True
        conn.close()
        return result

    # ── Step 1: ADD COLUMN training_eligible (idempotent) ────────────
    existing = {row[1] for row in conn.execute("PRAGMA table_info(cieu_events)")}

    if "training_eligible" not in existing:
        conn.execute(
            "ALTER TABLE cieu_events ADD COLUMN training_eligible INTEGER DEFAULT 0"
        )
        print("[002] Added column: training_eligible INTEGER DEFAULT 0")
    else:
        print("[002] Column training_eligible already exists -- skip ALTER")

    # ── Step 2: Backfill training_eligible ───────────────────────────
    # Events at or after the hook registration anchor are training-eligible.
    # created_at stores epoch seconds (REAL) for most rows, but some rows
    # use ISO 8601 text.  We handle both formats with typeof() dispatch.
    print(f"[002] Backfilling training_eligible (anchor: {HOOK_REGISTRATION_EPOCH_ISO} / {HOOK_REGISTRATION_EPOCH_UNIX})...")

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE cieu_events SET training_eligible = CASE "
            "  WHEN typeof(created_at) = 'real' AND created_at >= ? THEN 1 "
            "  WHEN typeof(created_at) = 'integer' AND created_at >= ? THEN 1 "
            "  WHEN typeof(created_at) = 'text' AND created_at >= ? THEN 1 "
            "  ELSE 0 "
            "END",
            (HOOK_REGISTRATION_EPOCH_UNIX, HOOK_REGISTRATION_EPOCH_UNIX, HOOK_REGISTRATION_EPOCH_ISO),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    eligible_1 = conn.execute(
        "SELECT COUNT(*) FROM cieu_events WHERE training_eligible = 1"
    ).fetchone()[0]
    eligible_0 = conn.execute(
        "SELECT COUNT(*) FROM cieu_events WHERE training_eligible = 0"
    ).fetchone()[0]
    result["training_eligible_1"] = eligible_1
    result["training_eligible_0"] = eligible_0
    print(f"[002] training_eligible=1 (post-hook): {eligible_1:,}")
    print(f"[002] training_eligible=0 (pre-hook contamination-suspect): {eligible_0:,}")

    # ── Step 3: CREATE INDEX (idempotent) ────────────────────────────
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_eligible_decision "
        "ON cieu_events(training_eligible, decision_canonical)"
    )
    print("[002] Index idx_training_eligible_decision ensured")

    # ── Step 4: Re-normalize decision_canonical with v2 normalizer ───
    # Fetch all distinct (decision, passed) pairs and compute new canonical
    print("[002] Re-normalizing decision_canonical with v2 normalizer (escape-aware)...")

    distinct_pairs = conn.execute(
        "SELECT DISTINCT decision, passed FROM cieu_events"
    ).fetchall()

    conn.execute("BEGIN IMMEDIATE")
    try:
        for row in distinct_pairs:
            raw_val = row[0]
            passed_val = row[1]
            new_canonical = normalize(raw_val, passed=passed_val)
            conn.execute(
                "UPDATE cieu_events SET decision_canonical = ? "
                "WHERE decision = ? AND passed = ?",
                (new_canonical, raw_val, passed_val),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    print("[002] Re-normalization complete")

    # Handle any NULL passed values separately
    null_passed_rows = conn.execute(
        "SELECT DISTINCT decision FROM cieu_events WHERE passed IS NULL"
    ).fetchall()
    if null_passed_rows:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for row in null_passed_rows:
                raw_val = row[0]
                new_canonical = normalize(raw_val, passed=None)
                conn.execute(
                    "UPDATE cieu_events SET decision_canonical = ? "
                    "WHERE decision = ? AND passed IS NULL",
                    (new_canonical, raw_val),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        print(f"[002] Handled {len(null_passed_rows)} distinct decisions with NULL passed")

    # ── Step 5: Post-migration verification (D5) ────────────────────
    after = conn.execute(
        "SELECT decision_canonical, passed, training_eligible, COUNT(*) as n "
        "FROM cieu_events "
        "GROUP BY decision_canonical, passed, training_eligible "
        "ORDER BY n DESC"
    ).fetchall()
    after_dist = [(row[0], row[1], row[2], row[3]) for row in after]
    result["after_distribution"] = after_dist

    print(f"\n[002] After distribution (decision_canonical, passed, training_eligible, count):")
    print(f"  {'canonical':20s}  {'passed':>6s}  {'eligible':>8s}  {'count':>8s}")
    print(f"  {'-'*20}  {'-'*6}  {'-'*8}  {'-'*8}")
    for canonical, passed, eligible, n in after_dist:
        print(f"  {str(canonical):20s}  {str(passed):>6s}  {str(eligible):>8s}  {n:>8,}")

    # Summary: count escape bucket total
    escape_total = conn.execute(
        "SELECT COUNT(*) FROM cieu_events WHERE decision_canonical = 'escape'"
    ).fetchone()[0]
    result["escape_total"] = escape_total
    print(f"\n[002] Total escape events: {escape_total:,}")

    # Verify all canonical values are in expected set
    after_canonicals = {row[0] for row in after if row[0] is not None}
    unexpected = after_canonicals - CANONICAL_VALUES
    if unexpected:
        print(f"[002] WARNING: unexpected canonical values: {unexpected}")
    else:
        print("[002] All canonical values in expected set -- CLEAN")

    elapsed = time.time() - t0
    result["elapsed_seconds"] = round(elapsed, 2)
    print(f"[002] Migration completed in {elapsed:.1f}s")

    conn.close()
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Migration 002: Add training_eligible + re-normalize with escape bucket"
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
        print(f"\n[002] SUMMARY: {result['row_count']:,} rows, "
              f"escape={result.get('escape_total', '?')}, "
              f"eligible_1={result.get('training_eligible_1', '?')}, "
              f"eligible_0={result.get('training_eligible_0', '?')}, "
              f"{result['elapsed_seconds']}s elapsed")
