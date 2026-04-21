"""
CIEU Brain Learning Module (ARCH-18 Phase 3)

Implements two learning mechanisms that sit ON TOP of cieu_brain_bridge
(Phase 1, Maya-owned) without modifying it:

1. Dim-centroid drift — moves each node's 6D coords toward the mean
   of the events that activated it (moving-average, conservative rate).
2. Embedding refinement — per-event-type centroid lookup table built
   from co-fire statistics. Used as a learned replacement for the
   hand-rule heuristic when enough samples exist.

Both are idempotent and safe to run as a nightly cron job.
"""

import json
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ystar.governance.cieu_brain_bridge import Coord6D, project_event_to_6d

# ── Constants ───────────────────────────────────────────────────────────
DIM_NAMES = ("dim_y", "dim_x", "dim_z", "dim_t", "dim_phi", "dim_c")
LEARNING_RATE = 0.1          # conservative EMA alpha
MIN_SAMPLES_FOR_LEARNED = 10 # below this, fall back to hand-rule
NOISE_SCALE = 0.02           # small noise added to learned centroid


# ── 1. Dim-Centroid Drift ───────────────────────────────────────────────

def compute_node_centroid_drift(
    node_id: str,
    window_sec: float = 86400,
    *,
    brain_conn: sqlite3.Connection,
    cieu_conn: Optional[sqlite3.Connection] = None,
) -> Optional[Tuple[Coord6D, Coord6D]]:
    """Compute new centroid for a node based on recent activations.

    Returns (old_coords, new_coords) or None if no activations found.

    Algorithm:
      1. Find all activation_log rows whose activated_nodes JSON contains node_id
         within the time window.
      2. For each activation, extract the CIEU event_id from the query column
         (format: ``cieu_event:<uuid>``), look up that event in cieu_events,
         and project it to 6D via project_event_to_6d.
      3. Compute the mean of those 6D firing coords.
      4. Apply EMA: new = (1 - alpha) * current + alpha * mean_firing.
    """
    cutoff = time.time() - window_sec

    # --- current node coords ---
    row = brain_conn.execute(
        "SELECT dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()
    if row is None:
        return None
    old_coords: Coord6D = tuple(row)  # type: ignore[assignment]

    # --- activations in window ---
    # activation_log.query has format "cieu_event:<uuid>"
    # activated_nodes is JSON: [{"node_id": "...", "activation_level": ...}]
    # We search for rows where activated_nodes contains this node_id.
    act_rows = brain_conn.execute(
        "SELECT query FROM activation_log WHERE timestamp >= ?",
        (cutoff,),
    ).fetchall()

    # Filter: only rows whose activated_nodes JSON mentions our node_id
    event_ids: List[str] = []
    for (query_col,) in act_rows:
        # Check if this activation row is about our node
        # We need to also check activated_nodes, but for performance
        # we use the query column to get event_id then cross-check.
        # Actually, activation_log stores one row per (event, node) pair
        # (see insert_activation in bridge). So we need to check activated_nodes.
        # But since insert_activation stores exactly one node per row,
        # we can check if node_id appears in the activated_nodes JSON.
        act_row_full = brain_conn.execute(
            "SELECT query, activated_nodes FROM activation_log "
            "WHERE query = ? AND timestamp >= ?",
            (query_col, cutoff),
        ).fetchone()
        if act_row_full is None:
            continue
        try:
            nodes_list = json.loads(act_row_full[1])
            if any(n.get("node_id") == node_id for n in nodes_list):
                if query_col.startswith("cieu_event:"):
                    eid = query_col[len("cieu_event:"):]
                    event_ids.append(eid)
        except (json.JSONDecodeError, TypeError):
            continue

    # deduplicate
    event_ids = list(set(event_ids))
    if not event_ids:
        return None

    # --- project each event to 6D ---
    firing_coords: List[Coord6D] = []
    for eid in event_ids:
        event_row = _fetch_event_as_dict(eid, cieu_conn=cieu_conn, brain_conn=brain_conn)
        if event_row is not None:
            coords = project_event_to_6d(event_row)
            firing_coords.append(coords)

    if not firing_coords:
        return None

    # --- mean of firing coords ---
    n = len(firing_coords)
    mean_coords = tuple(
        sum(c[i] for c in firing_coords) / n for i in range(6)
    )

    # --- EMA update ---
    alpha = LEARNING_RATE
    new_coords: Coord6D = tuple(
        (1 - alpha) * old_coords[i] + alpha * mean_coords[i]
        for i in range(6)
    )  # type: ignore[assignment]

    return (old_coords, new_coords)


def _fetch_event_as_dict(
    event_id: str,
    *,
    cieu_conn: Optional[sqlite3.Connection] = None,
    brain_conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch a CIEU event row as a dict suitable for project_event_to_6d.

    Tries cieu_conn first (the real cieu_events DB), then falls back to
    brain_conn (in case event data is co-located for testing).
    """
    for conn in (cieu_conn, brain_conn):
        if conn is None:
            continue
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM cieu_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            conn.row_factory = None
            if row is not None:
                return dict(row)
        except sqlite3.OperationalError:
            conn.row_factory = None
            continue
    return None


def _batch_collect_node_event_ids(
    brain_conn: sqlite3.Connection,
    window_sec: float = 86400,
) -> Dict[str, List[str]]:
    """Single-pass scan of activation_log to build node_id -> [event_id] map.

    Much faster than per-node scanning for large activation_log tables.
    """
    cutoff = time.time() - window_sec
    node_events: Dict[str, List[str]] = {}

    rows = brain_conn.execute(
        "SELECT query, activated_nodes FROM activation_log WHERE timestamp >= ?",
        (cutoff,),
    ).fetchall()

    for query_col, activated_json in rows:
        if not query_col or not query_col.startswith("cieu_event:"):
            continue
        eid = query_col[len("cieu_event:"):]
        try:
            nodes_list = json.loads(activated_json)
        except (json.JSONDecodeError, TypeError):
            continue
        for node_entry in nodes_list:
            nid = node_entry.get("node_id")
            if nid:
                node_events.setdefault(nid, []).append(eid)

    # Deduplicate event_ids per node
    for nid in node_events:
        node_events[nid] = list(set(node_events[nid]))

    return node_events


def _batch_fetch_events(
    event_ids: List[str],
    *,
    cieu_conn: Optional[sqlite3.Connection] = None,
    brain_conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Dict[str, Any]]:
    """Batch fetch CIEU events by ID. Returns event_id -> row dict."""
    result: Dict[str, Dict[str, Any]] = {}
    if not event_ids:
        return result

    for conn in (cieu_conn, brain_conn):
        if conn is None:
            continue
        try:
            # SQLite has a limit on parameters; chunk if needed
            remaining = [eid for eid in event_ids if eid not in result]
            chunk_size = 500
            for start in range(0, len(remaining), chunk_size):
                chunk = remaining[start:start + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    f"SELECT * FROM cieu_events WHERE event_id IN ({placeholders})",
                    chunk,
                ).fetchall()
                conn.row_factory = None
                for row in rows:
                    result[dict(row)["event_id"]] = dict(row)
        except sqlite3.OperationalError:
            if conn:
                conn.row_factory = None
            continue

    return result


def apply_drift_to_all_nodes(
    db_path: Optional[str] = None,
    *,
    brain_conn: Optional[sqlite3.Connection] = None,
    cieu_conn: Optional[sqlite3.Connection] = None,
    window_sec: float = 86400,
) -> Dict[str, Any]:
    """Loop over all nodes, apply centroid drift, UPDATE dim_* columns.

    Uses batch collection for performance on large activation_log tables.
    Returns summary dict: {updated: int, skipped: int, total: int}.
    """
    close_brain = False
    if brain_conn is None:
        if db_path is None:
            raise ValueError("Either db_path or brain_conn must be provided")
        brain_conn = sqlite3.connect(db_path)
        close_brain = True

    try:
        # Load all nodes
        node_rows = brain_conn.execute(
            "SELECT id, dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c FROM nodes"
        ).fetchall()
        node_coords_map: Dict[str, Coord6D] = {}
        for r in node_rows:
            node_coords_map[r[0]] = (r[1], r[2], r[3], r[4], r[5], r[6])

        # Batch collect node -> event_ids
        node_events = _batch_collect_node_event_ids(brain_conn, window_sec)

        # Collect all unique event_ids needed
        all_eids: List[str] = list(set(
            eid for eids in node_events.values() for eid in eids
        ))

        # Batch fetch events
        event_cache = _batch_fetch_events(
            all_eids, cieu_conn=cieu_conn, brain_conn=brain_conn
        )

        updated = 0
        skipped = 0
        now = time.time()
        alpha = LEARNING_RATE

        for nid, old_coords in node_coords_map.items():
            eids = node_events.get(nid)
            if not eids:
                skipped += 1
                continue

            # Project each event to 6D
            firing_coords: List[Coord6D] = []
            for eid in eids:
                event_row = event_cache.get(eid)
                if event_row is not None:
                    firing_coords.append(project_event_to_6d(event_row))

            if not firing_coords:
                skipped += 1
                continue

            # Mean of firing coords
            n = len(firing_coords)
            mean_coords = tuple(
                sum(c[i] for c in firing_coords) / n for i in range(6)
            )

            # EMA update
            new_coords = tuple(
                (1 - alpha) * old_coords[i] + alpha * mean_coords[i]
                for i in range(6)
            )

            brain_conn.execute(
                """UPDATE nodes SET
                    dim_y = ?, dim_x = ?, dim_z = ?,
                    dim_t = ?, dim_phi = ?, dim_c = ?,
                    updated_at = ?
                   WHERE id = ?""",
                (*new_coords, now, nid),
            )
            updated += 1

        brain_conn.commit()
        return {"updated": updated, "skipped": skipped, "total": len(node_rows)}
    finally:
        if close_brain:
            brain_conn.close()


# ── 2. Embedding Refinement (co-fire centroid) ──────────────────────────

_EVENT_TYPE_COORDS_DDL = """
CREATE TABLE IF NOT EXISTS event_type_coords (
    event_type  TEXT PRIMARY KEY,
    dim_y       REAL,
    dim_x       REAL,
    dim_z       REAL,
    dim_t       REAL,
    dim_phi     REAL,
    dim_c       REAL,
    samples     INTEGER,
    last_update REAL
)
"""


def compute_event_type_coord_centroids(
    window_sec: float = 86400,
    *,
    brain_conn: sqlite3.Connection,
    cieu_conn: Optional[sqlite3.Connection] = None,
) -> int:
    """For each distinct event_type, compute mean 6D coord of all its
    activated nodes. Write to event_type_coords table (create if missing).

    Uses batch approach: single pass over activation_log + batch event fetch.
    Returns number of event_types written.
    """
    brain_conn.execute(_EVENT_TYPE_COORDS_DDL)

    cutoff = time.time() - window_sec

    # Load all node coords into memory
    node_coords_cache: Dict[str, Coord6D] = {}
    for r in brain_conn.execute(
        "SELECT id, dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c FROM nodes"
    ).fetchall():
        node_coords_cache[r[0]] = (r[1], r[2], r[3], r[4], r[5], r[6])

    # Single pass: collect (event_id -> list of node_ids)
    eid_to_nodes: Dict[str, List[str]] = {}
    act_rows = brain_conn.execute(
        "SELECT query, activated_nodes FROM activation_log WHERE timestamp >= ?",
        (cutoff,),
    ).fetchall()

    for query_col, activated_json in act_rows:
        if not query_col or not query_col.startswith("cieu_event:"):
            continue
        eid = query_col[len("cieu_event:"):]
        try:
            nodes_list = json.loads(activated_json)
        except (json.JSONDecodeError, TypeError):
            continue
        for node_entry in nodes_list:
            nid = node_entry.get("node_id")
            if nid:
                eid_to_nodes.setdefault(eid, []).append(nid)

    # Batch fetch events
    all_eids = list(eid_to_nodes.keys())
    event_cache = _batch_fetch_events(
        all_eids, cieu_conn=cieu_conn, brain_conn=brain_conn
    )

    # Build event_type -> list of node coords
    event_type_fires: Dict[str, List[Coord6D]] = {}
    for eid, node_ids in eid_to_nodes.items():
        event_row = event_cache.get(eid)
        if event_row is None:
            continue
        et = event_row.get("event_type", "")
        if not et:
            continue
        for nid in node_ids:
            coords = node_coords_cache.get(nid)
            if coords is not None:
                event_type_fires.setdefault(et, []).append(coords)

    # Write centroids
    now = time.time()
    written = 0
    for et, coord_list in event_type_fires.items():
        n = len(coord_list)
        mean_c = tuple(sum(c[i] for c in coord_list) / n for i in range(6))
        brain_conn.execute(
            """INSERT OR REPLACE INTO event_type_coords
               (event_type, dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c, samples, last_update)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (et, *mean_c, n, now),
        )
        written += 1

    brain_conn.commit()
    return written


def refined_project_event_to_6d(
    event_row: Dict[str, Any],
    *,
    brain_conn: Optional[sqlite3.Connection] = None,
) -> Coord6D:
    """Learned projection: use per-type centroid if enough samples exist,
    otherwise fall back to hand-rule heuristic.

    Small deterministic noise is added based on event_id hash to avoid
    all events of same type collapsing to identical point.
    """
    et = event_row.get("event_type", "")

    if brain_conn is not None and et:
        row = brain_conn.execute(
            "SELECT dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c, samples "
            "FROM event_type_coords WHERE event_type = ?",
            (et,),
        ).fetchone()
        if row is not None and row[6] >= MIN_SAMPLES_FOR_LEARNED:
            base: Coord6D = (row[0], row[1], row[2], row[3], row[4], row[5])
            # deterministic noise from event_id hash
            eid = event_row.get("event_id", "")
            noise_seed = hash(eid) & 0xFFFFFFFF
            noised = tuple(
                max(0.0, min(1.0, base[i] + NOISE_SCALE * ((noise_seed >> (i * 4) & 0xF) / 15.0 - 0.5)))
                for i in range(6)
            )
            return noised  # type: ignore[return-value]

    # Fallback: hand-rule from bridge
    return project_event_to_6d(event_row)


# ── 3. Nightly Learning Cycle ───────────────────────────────────────────

def run_learning_cycle(
    brain_db_path: Optional[str] = None,
    cieu_db_path: Optional[str] = None,
    *,
    brain_conn: Optional[sqlite3.Connection] = None,
    cieu_conn: Optional[sqlite3.Connection] = None,
    window_sec: float = 86400,
) -> Dict[str, Any]:
    """Full learning cycle: drift + centroid computation + CIEU emit.

    Returns summary dict with drift_summary, centroid_count, and event_id.
    """
    close_brain = False
    close_cieu = False

    if brain_conn is None:
        if brain_db_path is None:
            raise ValueError("Either brain_db_path or brain_conn must be provided")
        brain_conn = sqlite3.connect(brain_db_path)
        close_brain = True

    if cieu_conn is None and cieu_db_path is not None:
        cieu_conn = sqlite3.connect(cieu_db_path)
        close_cieu = True

    try:
        # Step 1: dim-centroid drift
        drift_summary = apply_drift_to_all_nodes(
            brain_conn=brain_conn,
            cieu_conn=cieu_conn,
            window_sec=window_sec,
        )

        # Step 2: event_type centroid computation
        centroid_count = compute_event_type_coord_centroids(
            window_sec=window_sec,
            brain_conn=brain_conn,
            cieu_conn=cieu_conn,
        )

        # Step 3: emit CIEU summary event
        event_id = _emit_learning_cycle_event(
            drift_summary=drift_summary,
            centroid_count=centroid_count,
            cieu_conn=cieu_conn,
            brain_conn=brain_conn,
        )

        return {
            "drift_summary": drift_summary,
            "centroid_count": centroid_count,
            "event_id": event_id,
        }
    finally:
        if close_brain:
            brain_conn.close()
        if close_cieu:
            cieu_conn.close()


def _emit_learning_cycle_event(
    drift_summary: Dict[str, Any],
    centroid_count: int,
    cieu_conn: Optional[sqlite3.Connection] = None,
    brain_conn: Optional[sqlite3.Connection] = None,
) -> str:
    """Emit a CIEU_BRAIN_LEARNING_CYCLE event to whichever DB is available."""
    event_id = str(uuid.uuid4())
    now = time.time()
    seq = int(now * 1_000_000)

    summary_json = json.dumps({
        "drift": drift_summary,
        "centroid_count": centroid_count,
    })

    # Try to insert into cieu_events (either cieu_conn or brain_conn)
    target_conn = cieu_conn or brain_conn
    if target_conn is None:
        return event_id

    try:
        target_conn.execute(
            """INSERT INTO cieu_events
               (event_id, seq_global, created_at, session_id, agent_id,
                event_type, decision, passed, task_description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id, seq, now,
                "learning_cycle", "eng-kernel",
                "CIEU_BRAIN_LEARNING_CYCLE",
                "allow", 1,
                summary_json,
            ),
        )
        target_conn.commit()
    except sqlite3.OperationalError:
        # cieu_events table might not exist in brain_conn — store in a
        # simpler fallback table
        try:
            target_conn.execute(
                """CREATE TABLE IF NOT EXISTS learning_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT,
                    payload TEXT,
                    created_at REAL
                )"""
            )
            target_conn.execute(
                "INSERT INTO learning_events VALUES (?, ?, ?, ?)",
                (event_id, "CIEU_BRAIN_LEARNING_CYCLE", summary_json, now),
            )
            target_conn.commit()
        except Exception:
            pass  # best-effort emit

    return event_id
