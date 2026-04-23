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


# ── Node 6D Coordinate Computation ─────────────────────────────────────
# Unlike project_event_to_6d (which projects CIEU events into 6D space),
# compute_6d_coords computes the intrinsic 6D position for brain *nodes*
# based on their metadata: node_type, textual content, creation time,
# and access pattern.

# Node-type base profiles: (dim_y, dim_x, dim_z, dim_t_base, dim_phi, dim_c)
# dim_t_base is overridden by recency computation; value here is fallback weight.
_NODE_TYPE_PROFILES: Dict[str, Coord6D] = {
    # High identity/depth
    "self_knowledge":       (0.85, 0.40, 0.50, 0.50, 0.60, 0.45),
    "identity":             (0.90, 0.35, 0.45, 0.50, 0.55, 0.50),
    # High breadth/knowledge
    "knowledge":            (0.40, 0.80, 0.45, 0.50, 0.50, 0.35),
    "meta":                 (0.55, 0.75, 0.50, 0.50, 0.80, 0.40),
    # High impact/transcendence
    "strategic":            (0.55, 0.60, 0.80, 0.55, 0.60, 0.75),
    "paradigm":             (0.60, 0.65, 0.85, 0.50, 0.70, 0.55),
    # High metacognition
    "ceo_learning":         (0.65, 0.70, 0.55, 0.55, 0.80, 0.45),
    # Mid-range ecosystem types
    "ecosystem_team":       (0.30, 0.55, 0.40, 0.50, 0.30, 0.40),
    "ecosystem_module":     (0.25, 0.65, 0.45, 0.50, 0.35, 0.45),
    "ecosystem_product":    (0.30, 0.60, 0.55, 0.50, 0.30, 0.50),
    "ecosystem_entanglement": (0.35, 0.55, 0.50, 0.50, 0.40, 0.35),
    # Hub nodes
    "hub":                  (0.40, 0.50, 0.55, 0.50, 0.45, 0.40),
    # Memory nodes
    "memory":               (0.50, 0.45, 0.30, 0.60, 0.45, 0.30),
    # Report nodes (bulk -- low identity, mid knowledge, low transcendence)
    "report":               (0.25, 0.55, 0.30, 0.55, 0.25, 0.35),
}

# Default for unknown/empty node_type
_NODE_TYPE_DEFAULT: Coord6D = (0.30, 0.40, 0.30, 0.50, 0.30, 0.35)

# Content keyword boosters: keyword -> (dim_index, boost_amount)
# dim indices: 0=y, 1=x, 2=z, 3=t, 4=phi, 5=c
_KEYWORD_BOOSTS: List[Tuple[str, int, float]] = [
    # dim_y (identity/depth) boosters
    ("identity", 0, 0.12),
    ("self", 0, 0.08),
    ("who am i", 0, 0.10),
    ("who-am-i", 0, 0.10),
    ("aiden", 0, 0.06),
    ("身份", 0, 0.10),
    # dim_x (knowledge/breadth) boosters
    ("framework", 1, 0.08),
    ("architecture", 1, 0.10),
    ("model", 1, 0.06),
    ("theory", 1, 0.08),
    ("analysis", 1, 0.06),
    # dim_z (impact/transcendence) boosters
    ("mission", 2, 0.10),
    ("m triangle", 2, 0.12),
    ("m-triangle", 2, 0.12),
    ("impact", 2, 0.08),
    ("value", 2, 0.06),
    ("transcend", 2, 0.10),
    # dim_phi (metacognition) boosters
    ("reflection", 4, 0.10),
    ("meta", 4, 0.08),
    ("counterfactual", 4, 0.12),
    ("反事实", 4, 0.12),
    ("metacog", 4, 0.10),
    ("lesson", 4, 0.08),
    ("learning", 4, 0.06),
    ("wisdom", 4, 0.08),
    # dim_c (courage/action) boosters
    ("ship", 5, 0.10),
    ("action", 5, 0.08),
    ("execute", 5, 0.10),
    ("deploy", 5, 0.08),
    ("决策", 5, 0.08),
    ("courage", 5, 0.12),
    ("勇气", 5, 0.12),
    ("decisive", 5, 0.08),
]


def compute_6d_coords(
    node_type: str,
    content: str,
    created_at: float,
    access_count: int,
    *,
    time_range: Optional[Tuple[float, float]] = None,
    max_access: int = 1000,
) -> Coord6D:
    """Compute intrinsic 6D coordinates for a brain node.

    Args:
        node_type: The node's type (e.g. 'self_knowledge', 'report', 'meta').
        content: Combined name + summary text for keyword matching.
        created_at: Unix timestamp of node creation.
        access_count: How many times the node has been accessed.
        time_range: (min_ts, max_ts) for normalization. If None, dim_t uses
                    a sigmoid fallback based on absolute recency.
        max_access: Cap for access_count normalization (default 1000).

    Returns:
        (dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c) each in [0.0, 1.0].
    """
    # 1. Start with node_type base profile
    nt = (node_type or "").strip().lower()
    base = list(_NODE_TYPE_PROFILES.get(nt, _NODE_TYPE_DEFAULT))

    # 2. Apply content keyword boosts
    content_lower = (content or "").lower()
    for keyword, dim_idx, boost in _KEYWORD_BOOSTS:
        if keyword in content_lower:
            base[dim_idx] = min(1.0, base[dim_idx] + boost)

    # 2b. Metacognitive dim_phi refinement — node_type + content signal
    # High-metacog node types get a base floor to ensure retrieval salience.
    _METACOG_TYPE_BOOST: Dict[str, float] = {
        "ceo_learning": 0.10,
        "meta": 0.10,
        "self_knowledge": 0.10,
        "paradigm": 0.05,
    }
    if nt in _METACOG_TYPE_BOOST:
        base[4] = min(1.0, base[4] + _METACOG_TYPE_BOOST[nt])

    # Content-based metacog signal: reflection/metacog/meta-rule/self-check
    _METACOG_CONTENT_KEYWORDS = ["reflection", "metacog", "meta-rule", "self-check"]
    for kw in _METACOG_CONTENT_KEYWORDS:
        if kw in content_lower:
            base[4] = min(1.0, base[4] + 0.20)

    # 3. Compute dim_t (evolution/direction): recency + access momentum
    if created_at and created_at > 0:
        if time_range and time_range[1] > time_range[0]:
            t_min, t_max = time_range
            # Linear recency in [0.2, 0.9] range
            recency = (created_at - t_min) / (t_max - t_min)
            recency = 0.2 + 0.7 * max(0.0, min(1.0, recency))
        else:
            # Fallback: sigmoid of seconds-ago / day
            now = time.time()
            age_days = max(0, (now - created_at)) / 86400.0
            recency = 0.9 / (1.0 + age_days / 7.0)  # half-life ~7 days

        # Access momentum: log-scaled, adds up to 0.1
        if access_count > 0:
            access_factor = min(1.0, math.log1p(access_count) / math.log1p(max_access))
            momentum = 0.1 * access_factor
        else:
            momentum = 0.0

        base[3] = min(1.0, recency + momentum)
    # else keep base[3] as profile default

    # 4. Clamp all to [0.05, 0.95] to avoid degenerate extremes
    result = tuple(max(0.05, min(0.95, v)) for v in base)
    return result  # type: ignore[return-value]


def backfill_6d_coords(
    db_path: str,
    *,
    batch_size: int = 500,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Batch-update 6D coordinates for all nodes with default (0.5, 0.5) coords.

    Reads all unset nodes, computes 6D coords via compute_6d_coords,
    and writes them back in batches.

    Args:
        db_path: Path to aiden_brain.db.
        batch_size: Number of rows per UPDATE transaction.
        dry_run: If True, compute but do not write.

    Returns:
        Dict with keys: total_updated, time_range, sample_updates.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    # Get time range for normalization
    row = conn.execute(
        "SELECT min(created_at), max(created_at) FROM nodes WHERE created_at > 0"
    ).fetchone()
    t_min = row[0] if row and row[0] else 0
    t_max = row[1] if row and row[1] else time.time()
    time_range_val = (t_min, t_max) if t_min > 0 else None

    # Get max access_count for normalization (capped at p99 to avoid outlier domination)
    max_acc_row = conn.execute(
        "SELECT access_count FROM nodes ORDER BY access_count DESC LIMIT 1 OFFSET "
        "(SELECT cast(count(*) * 0.01 as integer) FROM nodes)"
    ).fetchone()
    max_access = max(1, max_acc_row[0] if max_acc_row and max_acc_row[0] else 1000)

    # Fetch unset nodes
    cur = conn.execute(
        "SELECT id, node_type, name, summary, created_at, access_count "
        "FROM nodes WHERE dim_y = 0.5 AND dim_x = 0.5"
    )
    rows = cur.fetchall()

    total = len(rows)
    updates = []
    samples = []

    for i, r in enumerate(rows):
        nid, ntype, name, summary, c_at, acc = r
        content = f"{name or ''} {summary or ''}"
        coords = compute_6d_coords(
            node_type=ntype or "",
            content=content,
            created_at=c_at or 0,
            access_count=acc or 0,
            time_range=time_range_val,
            max_access=max_access,
        )
        updates.append((coords[0], coords[1], coords[2],
                        coords[3], coords[4], coords[5], nid))

        if len(samples) < 10:
            samples.append({
                "id": nid,
                "node_type": ntype,
                "name": (name or "")[:60],
                "coords": {
                    "dim_y": round(coords[0], 4),
                    "dim_x": round(coords[1], 4),
                    "dim_z": round(coords[2], 4),
                    "dim_t": round(coords[3], 4),
                    "dim_phi": round(coords[4], 4),
                    "dim_c": round(coords[5], 4),
                },
            })

    if not dry_run:
        # Batch update
        for start in range(0, len(updates), batch_size):
            batch = updates[start:start + batch_size]
            conn.executemany(
                "UPDATE nodes SET dim_y=?, dim_x=?, dim_z=?, "
                "dim_t=?, dim_phi=?, dim_c=? WHERE id=?",
                batch,
            )
            conn.commit()

    conn.close()

    return {
        "total_updated": total if not dry_run else 0,
        "total_candidates": total,
        "time_range": time_range_val,
        "max_access_p99": max_access,
        "sample_updates": samples,
    }
