#!/usr/bin/env python3
"""
Migration 001: Add decision_canonical and provenance columns to cieu_events.

Operations:
  1. ALTER TABLE cieu_events ADD COLUMN decision_canonical TEXT  (idempotent)
  2. ALTER TABLE cieu_events ADD COLUMN provenance TEXT           (idempotent)
  3. CREATE INDEX idx_decision_canonical                          (idempotent)
  4. Backfill decision_canonical using normalizer for all rows    (single transaction)
  5. Backfill provenance for system:* agent_id rows              (single transaction)
  6. Print before/after distribution for verification

Per CTO Ruling Q2: ALTER TABLE ADD COLUMN is metadata-only in SQLite.
Per CTO Ruling Q6: provenance column enables self-referential guard.

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
    provenance_for_agent,
)


def run_migration(db_path: str, *, dry_run: bool = False) -> dict:
    """
    Execute migration 001 on the given database.

    Args:
        db_path: Path to .ystar_cieu.db
        dry_run: If True, print what would happen but do not modify DB.

    Returns:
        dict with before_distribution, after_distribution, row_count,
        provenance_counts, elapsed_seconds.
    """
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")

    result: dict = {}
    t0 = time.time()

    # ── Step 0: Pre-migration distribution (before) ──────────────────
    before = dict(conn.execute(
        "SELECT decision, COUNT(*) FROM cieu_events GROUP BY decision ORDER BY 2 DESC"
    ).fetchall())
    result["before_distribution"] = before

    total_rows = conn.execute("SELECT COUNT(*) FROM cieu_events").fetchone()[0]
    result["row_count_before"] = total_rows
    print(f"[001] Total rows: {total_rows:,}")
    print(f"[001] Distinct raw decision values: {len(before)}")
    print("[001] Before distribution (raw decision -> count):")
    for k, v in sorted(before.items(), key=lambda x: -x[1]):
        display_key = k if len(k) <= 60 else k[:57] + "..."
        print(f"  {display_key:60s}  {v:>8,}")

    if dry_run:
        print("[001] DRY RUN -- no changes made.")
        result["dry_run"] = True
        conn.close()
        return result

    # ── Step 1: ADD COLUMN decision_canonical (idempotent) ───────────
    existing = {row[1] for row in conn.execute("PRAGMA table_info(cieu_events)")}

    if "decision_canonical" not in existing:
        conn.execute("ALTER TABLE cieu_events ADD COLUMN decision_canonical TEXT")
        print("[001] Added column: decision_canonical TEXT")
    else:
        print("[001] Column decision_canonical already exists -- skip ALTER")

    # ── Step 2: ADD COLUMN provenance (idempotent) ──────────────────
    if "provenance" not in existing:
        conn.execute("ALTER TABLE cieu_events ADD COLUMN provenance TEXT")
        print("[001] Added column: provenance TEXT")
    else:
        print("[001] Column provenance already exists -- skip ALTER")

    # ── Step 3: CREATE INDEX (idempotent) ────────────────────────────
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_canonical "
        "ON cieu_events(decision_canonical)"
    )
    print("[001] Index idx_decision_canonical ensured")

    # ── Step 4: Backfill decision_canonical ──────────────────────────
    # Build a CASE expression from the normalizer mapping for bulk UPDATE.
    # This is more efficient than row-by-row Python UPDATE for 400K+ rows.
    # We use the normalizer's logic directly to build the SQL CASE.
    print(f"[001] Backfilling decision_canonical for {total_rows:,} rows...")

    # Fetch all distinct raw decision values
    distinct_raw = [row[0] for row in conn.execute(
        "SELECT DISTINCT decision FROM cieu_events"
    ).fetchall()]

    # Build mapping: raw_value -> canonical
    mapping = {}
    for raw in distinct_raw:
        mapping[raw] = normalize(raw)

    # Execute as single transaction with batched UPDATEs per canonical value
    conn.execute("BEGIN IMMEDIATE")
    try:
        for raw_val, canonical_val in mapping.items():
            conn.execute(
                "UPDATE cieu_events SET decision_canonical = ? WHERE decision = ?",
                (canonical_val, raw_val),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    print("[001] decision_canonical backfill complete")

    # ── Step 5: Backfill provenance ─────────────────────────────────
    print("[001] Backfilling provenance for system:* agents...")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE cieu_events SET provenance = 'system:brain' "
            "WHERE agent_id LIKE 'system:%'"
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    prov_count = conn.execute(
        "SELECT COUNT(*) FROM cieu_events WHERE provenance = 'system:brain'"
    ).fetchone()[0]
    result["provenance_system_brain_count"] = prov_count
    print(f"[001] provenance='system:brain' set on {prov_count:,} rows")

    # ── Step 6: Post-migration verification ─────────────────────────
    after = dict(conn.execute(
        "SELECT decision_canonical, COUNT(*) FROM cieu_events "
        "GROUP BY decision_canonical ORDER BY 2 DESC"
    ).fetchall())
    result["after_distribution"] = after

    total_after = conn.execute("SELECT COUNT(*) FROM cieu_events").fetchone()[0]
    result["row_count_after"] = total_after

    print(f"\n[001] After distribution (decision_canonical -> count):")
    for k, v in sorted(after.items(), key=lambda x: -x[1]):
        display_k = str(k) if k is not None else "<NULL>"
        print(f"  {display_k:20s}  {v:>8,}")

    # Verify row count: in a live DB new events may arrive during migration.
    # Allow small growth (new INSERTs) but flag if rows decreased (data loss).
    if total_after < total_rows:
        raise RuntimeError(
            f"Row count DECREASED! before={total_rows}, after={total_after} -- possible data loss"
        )
    elif total_after == total_rows:
        print(f"\n[001] Row count verified: {total_after:,} (unchanged)")
    else:
        delta = total_after - total_rows
        print(f"\n[001] Row count: {total_after:,} (+{delta} new events during migration -- live DB)")

    # Backfill any NULL decision_canonical rows (from events inserted between
    # ALTER TABLE and backfill, or from writers that haven't been updated yet)
    null_dc = conn.execute(
        "SELECT COUNT(*) FROM cieu_events WHERE decision_canonical IS NULL"
    ).fetchone()[0]
    if null_dc > 0:
        print(f"[001] Patching {null_dc} rows with NULL decision_canonical...")
        distinct_null = conn.execute(
            "SELECT DISTINCT decision FROM cieu_events WHERE decision_canonical IS NULL"
        ).fetchall()
        for row in distinct_null:
            raw_val = row[0]
            canonical_val = normalize(raw_val)
            conn.execute(
                "UPDATE cieu_events SET decision_canonical = ? "
                "WHERE decision = ? AND decision_canonical IS NULL",
                (canonical_val, raw_val),
            )
        conn.commit()
        print(f"[001] NULL patch complete")

    # Verify all canonical values are in the expected set
    after_keys = {k for k in after.keys() if k is not None}
    null_count = after.get(None, 0)
    unexpected = after_keys - CANONICAL_VALUES
    if null_count:
        print(f"[001] WARNING: {null_count:,} rows have NULL decision_canonical")
    if unexpected:
        print(f"[001] WARNING: unexpected canonical values: {unexpected}")
    if not unexpected and not null_count:
        print("[001] All canonical values in expected set -- CLEAN")

    elapsed = time.time() - t0
    result["elapsed_seconds"] = round(elapsed, 2)
    print(f"[001] Migration completed in {elapsed:.1f}s")

    conn.close()
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Migration 001: Add decision_canonical + provenance columns"
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
        print(f"\n[001] SUMMARY: {result['row_count_after']:,} rows, "
              f"{len(result['after_distribution'])} canonical buckets, "
              f"{result['provenance_system_brain_count']:,} system:brain rows, "
              f"{result['elapsed_seconds']}s elapsed")
