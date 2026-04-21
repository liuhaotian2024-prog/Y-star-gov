"""
Dominance Monitor — Secondary defense against brain single-node domination.

Per CTO ruling CZL-BRAIN-3LOOP-FINAL Point 7 + CEO v2 Section 4:
- 150 nodes, uniform baseline ~0.67% per node
- 10% warn threshold (15x baseline) -> BRAIN_NODE_DOMINANCE_WARN
- 20% escalate threshold (30x baseline) -> BRAIN_NODE_DOMINANCE_ESCALATE
  + transient 50% weight suppression for next 50 queries

This is the SECONDARY defense. The primary defense is outcome-weighted
Hebbian (L2, Point 6). The dominance monitor catches runaway accumulation
that the Hebbian loop might miss due to learning lag or sparse outcome
signals.

Integration: called from L2 post-query path (after activation is recorded).
Does NOT live on L1 critical path — dominance detection is advisory, not
blocking, and must not add latency to injection.

Author: Maya Patel (eng-governance)
Date: 2026-04-19
Directive: CZL-DOMINANCE-MONITOR (Board CZL-BRAIN-3LOOP-FINAL Phase 1)
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple


# ── Constants (per CTO ruling Point 7) ──────────────────────────────────

WINDOW_SIZE = 100           # sliding window of last N L1 queries
WARN_THRESHOLD = 0.10       # 10% = 15x baseline (150 uniform nodes)
ESCALATE_THRESHOLD = 0.20   # 20% = 30x baseline
SUPPRESSION_QUERIES = 50    # suppress for next N queries after ESCALATE
SUPPRESSION_FACTOR = 0.50   # reduce effective weight by this factor
ESCALATE_CEO_COUNT = 3      # >N escalations in 30 days -> CEO flag
ESCALATE_CEO_WINDOW_DAYS = 30


# ── CIEU Event Types ────────────────────────────────────────────────────

BRAIN_NODE_DOMINANCE_WARN = "BRAIN_NODE_DOMINANCE_WARN"
BRAIN_NODE_DOMINANCE_ESCALATE = "BRAIN_NODE_DOMINANCE_ESCALATE"


# ── Data Classes ────────────────────────────────────────────────────────

@dataclass
class DominanceEvent:
    """Record of a dominance threshold crossing."""
    node_id: str
    dominance_fraction: float
    window_size: int
    event_type: str   # WARN or ESCALATE
    timestamp: float


@dataclass
class SuppressionEntry:
    """Tracks active weight suppression for a node."""
    node_id: str
    remaining_queries: int
    factor: float
    started_at: float


# ── DominanceTracker ────────────────────────────────────────────────────

class DominanceTracker:
    """Maintains rolling window of top-1 nodes from L1 queries and
    detects single-node dominance.

    Usage:
        tracker = DominanceTracker()
        # After each L1 query returns top-k nodes:
        events = tracker.record_query(top_1_node_id)
        # events is a list of DominanceEvent (WARN/ESCALATE) or empty

        # Check if a node is currently suppressed:
        factor = tracker.get_suppression_factor(node_id)
        # Returns 1.0 if not suppressed, SUPPRESSION_FACTOR if suppressed

    Thread safety: NOT thread-safe. Caller must serialize access.
    This is acceptable because the L2 path is single-threaded per session.
    """

    def __init__(
        self,
        window_size: int = WINDOW_SIZE,
        warn_threshold: float = WARN_THRESHOLD,
        escalate_threshold: float = ESCALATE_THRESHOLD,
        suppression_queries: int = SUPPRESSION_QUERIES,
        suppression_factor: float = SUPPRESSION_FACTOR,
    ) -> None:
        self._window_size = window_size
        self._warn_threshold = warn_threshold
        self._escalate_threshold = escalate_threshold
        self._suppression_queries = suppression_queries
        self._suppression_factor = suppression_factor

        # Sliding window: deque of top-1 node_ids, newest at right
        self._window: Deque[str] = deque(maxlen=window_size)

        # Per-node count within the window
        self._counts: Dict[str, int] = {}

        # Active suppressions: node_id -> SuppressionEntry
        self._suppressions: Dict[str, SuppressionEntry] = {}

        # History of all emitted events (for CEO escalation check)
        self._event_history: List[DominanceEvent] = []

    @property
    def window_size(self) -> int:
        return self._window_size

    @property
    def current_window_length(self) -> int:
        return len(self._window)

    def get_node_fraction(self, node_id: str) -> float:
        """Return current fraction of window occupied by node_id."""
        if not self._window:
            return 0.0
        return self._counts.get(node_id, 0) / len(self._window)

    def get_all_fractions(self) -> Dict[str, float]:
        """Return fraction for every node currently in the window."""
        if not self._window:
            return {}
        n = len(self._window)
        return {nid: count / n for nid, count in self._counts.items()}

    def record_query(self, top_1_node_id: str) -> List[DominanceEvent]:
        """Record a new L1 query's top-1 node and check thresholds.

        Args:
            top_1_node_id: The node_id that was ranked #1 for this query.

        Returns:
            List of DominanceEvent objects emitted (may be empty).
        """
        events: List[DominanceEvent] = []
        now = time.time()

        # Tick down all active suppressions
        self._tick_suppressions()

        # If window is full, evict oldest entry and decrement its count
        if len(self._window) == self._window_size:
            evicted = self._window[0]  # will be popped by deque maxlen
            self._counts[evicted] -= 1
            if self._counts[evicted] <= 0:
                del self._counts[evicted]

        # Add new entry
        self._window.append(top_1_node_id)
        self._counts[top_1_node_id] = self._counts.get(top_1_node_id, 0) + 1

        # Compute fraction
        fraction = self._counts[top_1_node_id] / len(self._window)

        # Check thresholds (ESCALATE checked first since it's stricter)
        if fraction > self._escalate_threshold:
            evt = DominanceEvent(
                node_id=top_1_node_id,
                dominance_fraction=fraction,
                window_size=len(self._window),
                event_type=BRAIN_NODE_DOMINANCE_ESCALATE,
                timestamp=now,
            )
            events.append(evt)
            self._event_history.append(evt)

            # Apply transient suppression
            self._suppressions[top_1_node_id] = SuppressionEntry(
                node_id=top_1_node_id,
                remaining_queries=self._suppression_queries,
                factor=self._suppression_factor,
                started_at=now,
            )

        elif fraction > self._warn_threshold:
            evt = DominanceEvent(
                node_id=top_1_node_id,
                dominance_fraction=fraction,
                window_size=len(self._window),
                event_type=BRAIN_NODE_DOMINANCE_WARN,
                timestamp=now,
            )
            events.append(evt)
            self._event_history.append(evt)

        return events

    def get_suppression_factor(self, node_id: str) -> float:
        """Return the effective weight multiplier for a node.

        Returns 1.0 if not suppressed, SUPPRESSION_FACTOR if suppressed.
        """
        entry = self._suppressions.get(node_id)
        if entry is None or entry.remaining_queries <= 0:
            return 1.0
        return entry.factor

    def get_active_suppressions(self) -> Dict[str, SuppressionEntry]:
        """Return dict of currently active suppressions."""
        return {
            nid: entry
            for nid, entry in self._suppressions.items()
            if entry.remaining_queries > 0
        }

    def _tick_suppressions(self) -> None:
        """Decrement remaining_queries for all active suppressions."""
        expired = []
        for nid, entry in self._suppressions.items():
            entry.remaining_queries -= 1
            if entry.remaining_queries <= 0:
                expired.append(nid)
        for nid in expired:
            del self._suppressions[nid]

    def get_escalation_count_in_window(
        self,
        node_id: Optional[str] = None,
        window_days: int = ESCALATE_CEO_WINDOW_DAYS,
    ) -> int:
        """Count ESCALATE events in the last window_days.

        If node_id is specified, count only for that node.
        If None, count all ESCALATE events.
        """
        cutoff = time.time() - (window_days * 86400)
        count = 0
        for evt in self._event_history:
            if evt.event_type != BRAIN_NODE_DOMINANCE_ESCALATE:
                continue
            if evt.timestamp < cutoff:
                continue
            if node_id is not None and evt.node_id != node_id:
                continue
            count += 1
        return count

    def should_flag_for_ceo(
        self,
        node_id: str,
        threshold: int = ESCALATE_CEO_COUNT,
        window_days: int = ESCALATE_CEO_WINDOW_DAYS,
    ) -> bool:
        """Check if node X has >threshold ESCALATE events in window_days.

        Per CEO v2 Section 4: if node X produces >3 ESCALATE events in
        30 days, flag in governance_boot.sh Step 8 boot report for CEO review.
        """
        return self.get_escalation_count_in_window(
            node_id=node_id, window_days=window_days
        ) > threshold

    def reset(self) -> None:
        """Clear all state. Used for testing."""
        self._window.clear()
        self._counts.clear()
        self._suppressions.clear()
        self._event_history.clear()


# ── Persistence Layer (dominance_log table) ─────────────────────────────

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


def ensure_dominance_log_table(conn: sqlite3.Connection) -> None:
    """Create dominance_log table if it does not exist."""
    conn.executescript(_DOMINANCE_LOG_SCHEMA)


def persist_dominance_event(
    conn: sqlite3.Connection,
    event: DominanceEvent,
    session_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """Write a DominanceEvent to the dominance_log table.

    Returns the rowid of the inserted record.
    """
    meta_json = json.dumps(metadata) if metadata else None
    cur = conn.execute(
        """INSERT INTO dominance_log
           (node_id, dominance_fraction, window_size, event_type, timestamp,
            session_id, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            event.node_id,
            event.dominance_fraction,
            event.window_size,
            event.event_type,
            event.timestamp,
            session_id,
            meta_json,
        ),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def query_escalations_in_window(
    conn: sqlite3.Connection,
    node_id: Optional[str] = None,
    window_days: int = ESCALATE_CEO_WINDOW_DAYS,
) -> List[Dict[str, Any]]:
    """Query ESCALATE events from dominance_log within window_days.

    Returns list of dicts with all columns.
    """
    cutoff = time.time() - (window_days * 86400)
    if node_id is not None:
        rows = conn.execute(
            """SELECT node_id, dominance_fraction, window_size, event_type,
                      timestamp, session_id, metadata
               FROM dominance_log
               WHERE event_type = 'ESCALATE' AND timestamp >= ? AND node_id = ?
               ORDER BY timestamp DESC""",
            (cutoff, node_id),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT node_id, dominance_fraction, window_size, event_type,
                      timestamp, session_id, metadata
               FROM dominance_log
               WHERE event_type = 'ESCALATE' AND timestamp >= ?
               ORDER BY timestamp DESC""",
            (cutoff,),
        ).fetchall()

    cols = [
        "node_id", "dominance_fraction", "window_size", "event_type",
        "timestamp", "session_id", "metadata",
    ]
    return [dict(zip(cols, row)) for row in rows]


def ceo_boot_report(
    conn: sqlite3.Connection,
    threshold: int = ESCALATE_CEO_COUNT,
    window_days: int = ESCALATE_CEO_WINDOW_DAYS,
) -> List[Dict[str, Any]]:
    """Generate boot report entries for nodes exceeding CEO escalation threshold.

    Returns list of dicts: {node_id, escalation_count, latest_fraction, latest_ts}
    for any node with >threshold ESCALATE events in window_days.

    Called from governance_boot.sh Step 8 to surface chronic dominance.
    """
    cutoff = time.time() - (window_days * 86400)
    rows = conn.execute(
        """SELECT node_id, COUNT(*) as cnt,
                  MAX(dominance_fraction) as max_frac,
                  MAX(timestamp) as latest_ts
           FROM dominance_log
           WHERE event_type = 'ESCALATE' AND timestamp >= ?
           GROUP BY node_id
           HAVING cnt > ?
           ORDER BY cnt DESC""",
        (cutoff, threshold),
    ).fetchall()

    return [
        {
            "node_id": row[0],
            "escalation_count": row[1],
            "max_fraction": row[2],
            "latest_timestamp": row[3],
        }
        for row in rows
    ]
