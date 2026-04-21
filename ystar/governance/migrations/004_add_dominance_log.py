#!/usr/bin/env python3
"""
Migration 004: Create dominance_log table for brain node dominance monitoring.

Per CTO ruling CZL-BRAIN-3LOOP-FINAL Point 7 + CEO v2 Section 4:
- Tracks WARN (10% threshold) and ESCALATE (20% threshold) events
- Enables CEO boot report: nodes with >3 ESCALATE in 30 days flagged
- Indexes on node_id, event_type, timestamp for efficient queries

Author: Maya Patel (eng-governance)
Date: 2026-04-19
Directive: CZL-DOMINANCE-MONITOR
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path


_DOMINANCE_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS dominance_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id    TEXT    NOT NULL,
    dominance_fraction REAL NOT NULL,
    window_size INTEGER NOT NULL,
    event_type TEXT    NOT NULL CHECK(event_type IN ('WARN', 'ESCALATE')),
    timestamp  REAL    NOT NULL,
    session_id TEXT,
    metadata   TEXT
);

CREATE INDEX IF NOT EXISTS idx_dominance_log_node_id
    ON dominance_log (node_id);
CREATE INDEX IF NOT EXISTS idx_dominance_log_event_type
    ON dominance_log (event_type);
CREATE INDEX IF NOT EXISTS idx_dominance_log_timestamp
    ON dominance_log (timestamp);
"""


def run_migration(db_path: str, *, dry_run: bool = False) -> dict:
    """
    Execute migration 004: create dominance_log table.

    Args:
        db_path: Path to the SQLite database (brain DB or governance DB).
        dry_run: If True, preview only.

    Returns:
        dict with migration result metadata.
    """
    result: dict = {"migration": "004_add_dominance_log"}
    t0 = time.time()

    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA journal_mode = WAL")

    # Check if table already exists
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dominance_log'"
    ).fetchone()

    if existing:
        print("[004] dominance_log table already exists -- SKIP")
        result["status"] = "already_exists"
        result["elapsed_seconds"] = round(time.time() - t0, 2)
        conn.close()
        return result

    if dry_run:
        print("[004] DRY RUN -- would create dominance_log table with columns:")
        print("  id (INTEGER PK), node_id (TEXT), dominance_fraction (REAL),")
        print("  window_size (INTEGER), event_type (TEXT WARN|ESCALATE),")
        print("  timestamp (REAL), session_id (TEXT), metadata (TEXT)")
        print("  + 3 indexes (node_id, event_type, timestamp)")
        result["status"] = "dry_run"
        result["elapsed_seconds"] = round(time.time() - t0, 2)
        conn.close()
        return result

    # Create table + indexes
    conn.executescript(_DOMINANCE_LOG_SCHEMA)

    # Verify creation
    verify = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dominance_log'"
    ).fetchone()
    if verify is None:
        raise RuntimeError("[004] FAILED: dominance_log table not created")

    # Verify indexes
    indexes = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='dominance_log'"
    ).fetchall()
    index_names = {row[0] for row in indexes}

    expected_indexes = {
        "idx_dominance_log_node_id",
        "idx_dominance_log_event_type",
        "idx_dominance_log_timestamp",
    }
    missing = expected_indexes - index_names
    if missing:
        print(f"[004] WARNING: missing indexes: {missing}")
        result["missing_indexes"] = list(missing)

    # Column info
    cols = conn.execute("PRAGMA table_info(dominance_log)").fetchall()
    col_names = [c[1] for c in cols]
    result["columns"] = col_names
    print(f"[004] Created dominance_log with columns: {col_names}")
    print(f"[004] Indexes: {sorted(index_names)}")

    elapsed = time.time() - t0
    result["status"] = "created"
    result["index_count"] = len(index_names)
    result["elapsed_seconds"] = round(elapsed, 2)
    print(f"[004] Migration completed in {elapsed:.2f}s")

    conn.close()
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Migration 004: Create dominance_log table"
    )
    parser.add_argument(
        "db_path",
        nargs="?",
        default=str(Path.home() / ".openclaw/workspace/ystar-company/.ystar_cieu.db"),
        help="Path to SQLite database",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    result = run_migration(args.db_path, dry_run=args.dry_run)
    print(f"\n[004] RESULT: {result}")
