"""
CIEU ↔ Brain Mission-Behavior Alignment (Research 1 → Production)

Bridges the gap between mission-layer nodes in aiden_brain.db and
behavior-layer CIEU events. Uses the activation_log as the empirical
link: every time a CIEU event activates a brain node, that is evidence
of a mission↔behavior connection.

Tables used:
  aiden_brain.db:
    - nodes (id, node_type, ...)
    - activation_log (query=cieu_event:<uuid>, activated_nodes JSON)
    - mission_behavior_links (created by this module if missing)
  .ystar_cieu.db:
    - cieu_events (event_id, event_type, created_at, ...)

Key functions:
  populate_links_from_activation_history  — scan activation_log, UPSERT links
  compute_functional_completeness         — fit_score for a mission node
  align_weakest_link_audit                — find lowest-firing event type
"""

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple


# ── Schema bootstrap ───────────────────────────────────────────────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mission_behavior_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mission_node_id TEXT NOT NULL,
  cieu_event_type TEXT NOT NULL,
  alignment_weight REAL DEFAULT 0.5,
  sample_count INTEGER DEFAULT 0,
  last_fired REAL,
  UNIQUE(mission_node_id, cieu_event_type)
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_link_node ON mission_behavior_links(mission_node_id);",
    "CREATE INDEX IF NOT EXISTS idx_link_type ON mission_behavior_links(cieu_event_type);",
]


def ensure_table(brain_conn: sqlite3.Connection) -> None:
    """Idempotently create mission_behavior_links table + indexes."""
    brain_conn.execute(_CREATE_TABLE_SQL)
    for idx_sql in _CREATE_INDEXES_SQL:
        brain_conn.execute(idx_sql)
    brain_conn.commit()


# ── Populate links from activation history ─────────────────────────────

def populate_links_from_activation_history(
    brain_db: str,
    cieu_db: str,
    window_sec: float = 86400 * 7,
) -> int:
    """
    Scan activation_log for which nodes fired per cieu_event_type.
    UPSERT into mission_behavior_links.

    Args:
        brain_db: Path to aiden_brain.db
        cieu_db:  Path to .ystar_cieu.db
        window_sec: Time window in seconds (default 7 days). 0 = all time.

    Returns:
        Number of links upserted.
    """
    conn = sqlite3.connect(brain_db)
    conn.row_factory = sqlite3.Row
    ensure_table(conn)

    # Attach CIEU database
    conn.execute(f"ATTACH ? AS cieu", (cieu_db,))

    # Build cutoff timestamp
    cutoff = time.time() - window_sec if window_sec > 0 else 0

    # Query: join activation_log with cieu_events to get (node_id, event_type, count, max_ts)
    # activation_log.query = 'cieu_event:<uuid>' → strip prefix to match cieu_events.event_id
    # activated_nodes is a JSON array with one element per row: [{"node_id": ..., "activation_level": ...}]
    query = """
    SELECT
        json_extract(a.activated_nodes, '$[0].node_id') AS node_id,
        c.event_type,
        COUNT(*) AS cnt,
        MAX(a.timestamp) AS max_ts
    FROM activation_log a
    JOIN cieu.cieu_events c
        ON c.event_id = REPLACE(a.query, 'cieu_event:', '')
    WHERE a.timestamp >= ?
      AND c.event_type IS NOT NULL
      AND c.event_type != ''
    GROUP BY node_id, c.event_type
    """

    rows = conn.execute(query, (cutoff,)).fetchall()

    upsert_sql = """
    INSERT INTO mission_behavior_links (mission_node_id, cieu_event_type, alignment_weight, sample_count, last_fired)
    VALUES (?, ?, 0.5, ?, ?)
    ON CONFLICT(mission_node_id, cieu_event_type) DO UPDATE SET
        sample_count = sample_count + excluded.sample_count,
        last_fired = MAX(COALESCE(last_fired, 0), excluded.last_fired)
    """

    count = 0
    for row in rows:
        node_id = row["node_id"]
        event_type = row["event_type"]
        if node_id and event_type:
            conn.execute(upsert_sql, (node_id, event_type, row["cnt"], row["max_ts"]))
            count += 1

    conn.commit()
    conn.execute("DETACH cieu")
    conn.close()
    return count


# ── Functional completeness ────────────────────────────────────────────

def compute_functional_completeness(
    brain_db: str,
    cieu_db: str,
    mission_node_id: str,
    window_sec: float = 86400,
    weight_threshold: float = 0.3,
) -> float:
    """
    For a given mission node, compute fit_score = fired / required.

    'Required' event types are those linked with alignment_weight > threshold.
    'Fired' means the event type appeared in CIEU within the window.

    Returns:
        fit_score in [0.0, 1.0]. Returns 1.0 if no required types (vacuously true).
    """
    conn = sqlite3.connect(brain_db)
    conn.row_factory = sqlite3.Row
    ensure_table(conn)

    # Get required event types for this node
    required_rows = conn.execute(
        "SELECT cieu_event_type FROM mission_behavior_links "
        "WHERE mission_node_id = ? AND alignment_weight > ?",
        (mission_node_id, weight_threshold),
    ).fetchall()

    if not required_rows:
        conn.close()
        return 1.0  # vacuously complete

    required_types = [r["cieu_event_type"] for r in required_rows]

    # Attach CIEU and check which types fired recently
    conn.execute("ATTACH ? AS cieu", (cieu_db,))

    cutoff = time.time() - window_sec if window_sec > 0 else 0

    placeholders = ",".join("?" * len(required_types))
    fired_rows = conn.execute(
        f"SELECT DISTINCT event_type FROM cieu.cieu_events "
        f"WHERE event_type IN ({placeholders}) AND created_at >= ?",
        (*required_types, cutoff),
    ).fetchall()

    fired_types = {r["event_type"] for r in fired_rows}
    conn.execute("DETACH cieu")
    conn.close()

    fired_count = sum(1 for t in required_types if t in fired_types)
    return fired_count / len(required_types)


# ── Weakest link audit ─────────────────────────────────────────────────

def align_weakest_link_audit(
    brain_db: str,
    cieu_db: str,
    mission_node_id: str,
    window_sec: float = 86400,
    weight_threshold: float = 0.3,
) -> Optional[Dict[str, Any]]:
    """
    Return the cieu_event_type with lowest recent firing rate for a mission node.
    This is the actionable gap — the weakest behavioral link.

    Returns:
        Dict with {event_type, firing_count, last_fired, alignment_weight}
        or None if no required types exist.
    """
    conn = sqlite3.connect(brain_db)
    conn.row_factory = sqlite3.Row
    ensure_table(conn)

    # Get all linked event types above threshold
    link_rows = conn.execute(
        "SELECT cieu_event_type, alignment_weight, last_fired FROM mission_behavior_links "
        "WHERE mission_node_id = ? AND alignment_weight > ?",
        (mission_node_id, weight_threshold),
    ).fetchall()

    if not link_rows:
        conn.close()
        return None

    # Attach CIEU and count recent firings per type
    conn.execute("ATTACH ? AS cieu", (cieu_db,))

    cutoff = time.time() - window_sec if window_sec > 0 else 0

    weakest = None
    min_count = float("inf")

    for row in link_rows:
        et = row["cieu_event_type"]
        result = conn.execute(
            "SELECT COUNT(*) AS cnt FROM cieu.cieu_events "
            "WHERE event_type = ? AND created_at >= ?",
            (et, cutoff),
        ).fetchone()
        cnt = result["cnt"] if result else 0

        if cnt < min_count:
            min_count = cnt
            weakest = {
                "event_type": et,
                "firing_count": cnt,
                "last_fired": row["last_fired"],
                "alignment_weight": row["alignment_weight"],
            }

    conn.execute("DETACH cieu")
    conn.close()
    return weakest
