"""
CIEU → 6D Brain Activation Bridge (ARCH-18 Phase 1)

Minimum viable pipeline: project CIEU events into 6D brain space,
find nearest nodes, record activations. First implementation uses
hand-rule heuristics for 6D projection (no embedding model yet).

6D dimensions:
  dim_y  — depth/identity (self-knowledge, who-am-I)
  dim_x  — breadth/knowledge (learning, skill acquisition)
  dim_z  — impact/transcendence (system-level effect)
  dim_t  — evolution/direction (temporal, trajectory)
  dim_phi — metacognition/counterfactual (reflection, meta-reasoning)
  dim_c  — courage/action (execution, decisiveness)

Scoring table (heuristics v1):
  ┌───────────────────────────────┬──────┬──────┬──────┬──────┬──────┬──────┐
  │ Signal                        │ dim_y│ dim_x│ dim_z│ dim_t│dim_phi│dim_c│
  ├───────────────────────────────┼──────┼──────┼──────┼──────┼──────┼──────┤
  │ decision=deny + agent='agent' │  0.9 │  0.3 │  0.7 │  0.4 │  0.6 │  0.9 │
  │ K9_VIOLATION_DETECTED         │  0.5 │  0.4 │  0.6 │  0.3 │  0.95│  0.4 │
  │ BEHAVIOR_RULE_VIOLATION       │  0.7 │  0.5 │  0.5 │  0.3 │  0.85│  0.5 │
  │ ceo_learning (event_type)     │  0.8 │  0.9 │  0.4 │  0.6 │  0.5 │  0.3 │
  │ identity_violation (drift)    │  0.95│  0.3 │  0.5 │  0.3 │  0.7 │  0.6 │
  │ intervention_gate:deny        │  0.8 │  0.3 │  0.7 │  0.4 │  0.6 │  0.8 │
  │ escalate decision             │  0.6 │  0.5 │  0.8 │  0.5 │  0.7 │  0.7 │
  │ file_write (any)              │  0.3 │  0.5 │  0.4 │  0.5 │  0.3 │  0.7 │
  │ cmd_exec (any)                │  0.2 │  0.4 │  0.3 │  0.5 │  0.2 │  0.8 │
  │ orchestration:* (heartbeat)   │  0.1 │  0.1 │  0.1 │  0.5 │  0.1 │  0.1 │
  │ default fallback              │  0.3 │  0.3 │  0.3 │  0.5 │  0.3 │  0.3 │
  └───────────────────────────────┴──────┴──────┴──────┴──────┴──────┴──────┘
"""

import math
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

# Type alias for a 6D coordinate tuple
Coord6D = Tuple[float, float, float, float, float, float]

# ── Heuristic projection rules ──────────────────────────────────────────

# Each rule: (match_fn, coord_6d)
# Rules are checked in order; first match wins.

def _match_deny_agent_generic(row: Dict[str, Any]) -> bool:
    return (row.get("decision") == "deny"
            and row.get("agent_id") in ("agent", ""))

def _match_k9_violation(row: Dict[str, Any]) -> bool:
    et = row.get("event_type", "") or ""
    return "K9_VIOLATION" in et.upper()

def _match_behavior_rule_violation(row: Dict[str, Any]) -> bool:
    et = row.get("event_type", "") or ""
    return et == "BEHAVIOR_RULE_VIOLATION"

def _match_ceo_learning(row: Dict[str, Any]) -> bool:
    et = row.get("event_type", "") or ""
    return "ceo_learning" in et.lower()

def _match_identity_violation_drift(row: Dict[str, Any]) -> bool:
    dc = row.get("drift_category", "") or ""
    return dc == "identity_violation"

def _match_intervention_deny(row: Dict[str, Any]) -> bool:
    et = row.get("event_type", "") or ""
    return et == "intervention_gate:deny"

def _match_escalate(row: Dict[str, Any]) -> bool:
    return row.get("decision") == "escalate"

def _match_file_write(row: Dict[str, Any]) -> bool:
    et = row.get("event_type", "") or ""
    return et in ("file_write", "Write")

def _match_cmd_exec(row: Dict[str, Any]) -> bool:
    et = row.get("event_type", "") or ""
    return et in ("cmd_exec", "Bash")

def _match_orchestration(row: Dict[str, Any]) -> bool:
    et = row.get("event_type", "") or ""
    return et.startswith("orchestration:")

# Projection rules: (matcher, 6D coords)
_PROJECTION_RULES: List[Tuple[Any, Coord6D]] = [
    (_match_deny_agent_generic,       (0.9, 0.3, 0.7, 0.4, 0.6, 0.9)),
    (_match_k9_violation,             (0.5, 0.4, 0.6, 0.3, 0.95, 0.4)),
    (_match_behavior_rule_violation,  (0.7, 0.5, 0.5, 0.3, 0.85, 0.5)),
    (_match_ceo_learning,             (0.8, 0.9, 0.4, 0.6, 0.5, 0.3)),
    (_match_identity_violation_drift, (0.95, 0.3, 0.5, 0.3, 0.7, 0.6)),
    (_match_intervention_deny,        (0.8, 0.3, 0.7, 0.4, 0.6, 0.8)),
    (_match_escalate,                 (0.6, 0.5, 0.8, 0.5, 0.7, 0.7)),
    (_match_file_write,               (0.3, 0.5, 0.4, 0.5, 0.3, 0.7)),
    (_match_cmd_exec,                 (0.2, 0.4, 0.3, 0.5, 0.2, 0.8)),
    (_match_orchestration,            (0.1, 0.1, 0.1, 0.5, 0.1, 0.1)),
]

_DEFAULT_COORD: Coord6D = (0.3, 0.3, 0.3, 0.5, 0.3, 0.3)


def project_event_to_6d(event_row: Dict[str, Any]) -> Coord6D:
    """Project a CIEU event row dict into 6D brain coordinates.

    Uses hand-rule heuristics. First matching rule wins.
    Returns (dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c).
    """
    for matcher, coords in _PROJECTION_RULES:
        if matcher(event_row):
            return coords
    return _DEFAULT_COORD


def euclidean_6d(a: Coord6D, b: Coord6D) -> float:
    """Euclidean distance in 6D space."""
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


def top_k_nodes(
    coords: Coord6D,
    k: int = 3,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Tuple[str, str, float]]:
    """Find k nearest brain nodes to the given 6D coordinates.

    Returns list of (node_id, node_name, distance) sorted by distance ascending.
    Caller must supply either db_path or conn. conn takes precedence.
    """
    close_after = False
    if conn is None:
        if db_path is None:
            raise ValueError("Either db_path or conn must be provided")
        conn = sqlite3.connect(db_path)
        close_after = True

    try:
        cur = conn.execute(
            "SELECT id, name, dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c FROM nodes"
        )
        rows = cur.fetchall()

        scored: List[Tuple[str, str, float]] = []
        for row in rows:
            nid, name = row[0], row[1]
            node_coords: Coord6D = (row[2], row[3], row[4], row[5], row[6], row[7])
            dist = euclidean_6d(coords, node_coords)
            scored.append((nid, name, dist))

        scored.sort(key=lambda x: x[2])
        return scored[:k]
    finally:
        if close_after:
            conn.close()


def insert_activation(
    event_id: str,
    node_id: str,
    weight: float,
    query_text: str = "",
    session_id: str = "",
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Insert a single activation record into activation_log.

    The activation_log schema stores activations as JSON list in
    activated_nodes column. This function inserts one row per
    (event, node) pair for granular tracking.

    Returns the rowid of the inserted record.
    """
    close_after = False
    if conn is None:
        if db_path is None:
            raise ValueError("Either db_path or conn must be provided")
        conn = sqlite3.connect(db_path)
        close_after = True

    import json
    activated = json.dumps([{"node_id": node_id, "activation_level": weight}])
    try:
        cur = conn.execute(
            """INSERT INTO activation_log (query, activated_nodes, session_id, timestamp)
               VALUES (?, ?, ?, ?)""",
            (
                f"cieu_event:{event_id}",
                activated,
                session_id,
                time.time(),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        if close_after:
            conn.close()


def apply_hebbian_update(
    activated_node_ids: List[str],
    delta: float = 0.05,
    initial_weight: float = 0.1,
    max_weight: float = 1.0,
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Hebbian co-firing: strengthen edges between co-activated nodes.

    For each unordered pair (A, B) of co-fired nodes:
      - If edge exists: weight += delta, co_activations += 1 (cap at max_weight)
      - If no edge: create with weight=initial_weight, edge_type='hebbian',
        co_activations=1

    Args:
        activated_node_ids: List of node IDs that fired together.
        delta: Weight increment per co-firing.
        initial_weight: Weight for newly created edges.
        max_weight: Upper bound for edge weight.
        db_path: Path to brain DB (used if conn is None).
        conn: Existing connection (takes precedence over db_path).

    Returns:
        Number of edge updates (created + strengthened).
    """
    if len(activated_node_ids) < 2:
        return 0

    close_after = False
    if conn is None:
        if db_path is None:
            raise ValueError("Either db_path or conn must be provided")
        conn = sqlite3.connect(db_path)
        close_after = True

    updates = 0
    now = time.time()
    try:
        # Generate all unique pairs (canonical order: sorted)
        ids = sorted(set(activated_node_ids))
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                src, tgt = ids[i], ids[j]
                existing = conn.execute(
                    "SELECT weight, co_activations FROM edges "
                    "WHERE source_id = ? AND target_id = ?",
                    (src, tgt),
                ).fetchone()

                if existing:
                    new_weight = min(existing[0] + delta, max_weight)
                    new_co = (existing[1] or 0) + 1
                    conn.execute(
                        "UPDATE edges SET weight = ?, co_activations = ?, "
                        "updated_at = ? WHERE source_id = ? AND target_id = ?",
                        (new_weight, new_co, now, src, tgt),
                    )
                else:
                    conn.execute(
                        "INSERT INTO edges "
                        "(source_id, target_id, edge_type, weight, "
                        "created_at, updated_at, co_activations) "
                        "VALUES (?, ?, 'hebbian', ?, ?, ?, 1)",
                        (src, tgt, initial_weight, now, now),
                    )
                updates += 1

        conn.commit()
    finally:
        if close_after:
            conn.close()

    return updates


def process_event(
    event_row: Dict[str, Any],
    k: int = 3,
    brain_db_path: Optional[str] = None,
    brain_conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """Full pipeline: project event → find top-k nodes → insert activations.

    Returns list of activation dicts: [{node_id, node_name, weight, distance}].
    """
    coords = project_event_to_6d(event_row)
    nearest = top_k_nodes(coords, k=k, db_path=brain_db_path, conn=brain_conn)

    activations = []
    for node_id, node_name, dist in nearest:
        # Weight: inverse distance, clamped to [0.01, 1.0]
        weight = 1.0 / (1.0 + dist) if dist > 0 else 1.0
        weight = max(0.01, min(1.0, weight))

        insert_activation(
            event_id=event_row.get("event_id", "unknown"),
            node_id=node_id,
            weight=weight,
            query_text=f"{event_row.get('event_type', '')}|{event_row.get('decision', '')}",
            session_id=event_row.get("session_id", ""),
            db_path=brain_db_path,
            conn=brain_conn,
        )
        activations.append({
            "node_id": node_id,
            "node_name": node_name,
            "weight": round(weight, 4),
            "distance": round(dist, 4),
        })

    return activations
