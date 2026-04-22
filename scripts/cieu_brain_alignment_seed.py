#!/usr/bin/env python3
"""
Seed script: run populate_links_from_activation_history once.
Reports count of links created + top-10 strongest links.

Usage:
    python3 scripts/cieu_brain_alignment_seed.py
"""

import os
import sqlite3
import sys

# Add Y-star-gov to path so we can import the module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ystar.governance.cieu_brain_alignment import (
    compute_functional_completeness,
    populate_links_from_activation_history,
)

COMPANY = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ystar-company")
)
BRAIN_DB = os.path.join(COMPANY, "aiden_brain.db")
CIEU_DB = os.path.join(COMPANY, ".ystar_cieu.db")


def main():
    print(f"Brain DB: {BRAIN_DB}")
    print(f"CIEU DB:  {CIEU_DB}")
    print()

    # Populate with all-time window (window_sec=0 means no cutoff)
    count = populate_links_from_activation_history(BRAIN_DB, CIEU_DB, window_sec=0)
    print(f"Links upserted: {count}")
    print()

    # Report total
    conn = sqlite3.connect(BRAIN_DB)
    total = conn.execute("SELECT COUNT(*) FROM mission_behavior_links").fetchone()[0]
    print(f"Total links in table: {total}")
    print()

    # Top-10 by sample_count
    print("Top-10 strongest links (by sample_count):")
    print(f"{'node_id':<45} {'event_type':<35} {'samples':>8}")
    print("-" * 90)
    rows = conn.execute(
        "SELECT mission_node_id, cieu_event_type, sample_count "
        "FROM mission_behavior_links ORDER BY sample_count DESC LIMIT 10"
    ).fetchall()
    for r in rows:
        print(f"{r[0]:<45} {r[1]:<35} {r[2]:>8}")
    print()

    # Top-3 most-linked nodes
    print("Top-3 most-linked nodes (by distinct event types):")
    node_rows = conn.execute(
        "SELECT mission_node_id, COUNT(DISTINCT cieu_event_type) AS type_count, "
        "SUM(sample_count) AS total_samples "
        "FROM mission_behavior_links GROUP BY mission_node_id "
        "ORDER BY type_count DESC LIMIT 3"
    ).fetchall()
    for r in node_rows:
        print(f"  {r[0]}: {r[1]} event types, {r[2]} total samples")
    print()

    # Demo: functional completeness for team/ceo
    fit = compute_functional_completeness(BRAIN_DB, CIEU_DB, "team/ceo", window_sec=86400)
    print(f"Demo -- compute_functional_completeness('team/ceo', 24h): {fit:.4f}")

    conn.close()


if __name__ == "__main__":
    main()
