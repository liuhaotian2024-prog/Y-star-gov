"""
Brain Dream Scheduler -- L3 Dream Consolidation for aiden_brain.db.

Scans activation_log for co-activation patterns, proposes new edges/nodes/
archives, emits CIEU events, and writes proposals to .dream_proposals.jsonl.

Trigger conditions:
  A) session_close_yml.py invokes: brain_dream_scheduler.py --mode consolidate --scope session-close
  B) Board-offline-4h idle detector invokes: brain_dream_scheduler.py --mode consolidate --scope idle

Idempotency: .last_dream_timestamp sentinel prevents concurrent dreams (30min lockout).

Per CEO spec brain_3loop_live_architecture_v1.md Section 4.2:
  Pattern A: node pairs co-activated >3x without existing edge -> propose new edge
  Pattern B: 3+ node clusters always co-activating -> propose ecosystem_entanglement node
  Pattern C: nodes with access_count <=2 in 30 days -> propose archive
  Pattern D: recurring prompt contexts activating NO high-relevance node -> propose new node
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ystar.governance.cieu_store import (
    CIEUStore,
    BRAIN_DREAM_CYCLE_START,
    BRAIN_DREAM_CYCLE_COMPLETE,
    BRAIN_NODE_PROPOSED,
    BRAIN_EDGE_PROPOSED,
    BRAIN_ARCHIVE_PROPOSED,
    BRAIN_ENTANGLEMENT_PROPOSED,
)

# -- Constants --
LOCKOUT_SECONDS = 30 * 60  # 30 minutes
DEFAULT_ACTIVATION_WINDOW = 5000  # rows
# Pattern thresholds
CO_ACTIVATION_THRESHOLD = 3   # Pattern A: min co-activations to propose edge
CLUSTER_MIN_SIZE = 3           # Pattern B: min nodes in cluster
LOW_ACCESS_THRESHOLD = 2       # Pattern C: access_count <= this
LOW_ACCESS_DAYS = 30           # Pattern C: within this many days
HIGH_RELEVANCE_FLOOR = 0.5    # Pattern D: activation_level below this = "no high-relevance"


def _emit(store: Optional[CIEUStore], event_type: str, payload: dict, session_id: str) -> bool:
    """Emit a BRAIN CIEU event if store available."""
    if store is None:
        return False
    try:
        return store.emit_brain_event(
            event_type=event_type,
            payload=payload,
            session_id=session_id,
            agent_id="brain-dream",
        )
    except Exception:
        return False


# ── Idempotency Guard ─────────────────────────────────────────────────

def check_lockout(sentinel_path: Path) -> Tuple[bool, float]:
    """
    Check if a dream cycle ran within the lockout window.
    Returns (is_locked, seconds_remaining).
    """
    if not sentinel_path.exists():
        return False, 0.0
    try:
        ts = float(sentinel_path.read_text().strip())
        elapsed = time.time() - ts
        if elapsed < LOCKOUT_SECONDS:
            return True, LOCKOUT_SECONDS - elapsed
        return False, 0.0
    except (ValueError, OSError):
        return False, 0.0


def set_sentinel(sentinel_path: Path) -> None:
    """Write current timestamp to sentinel file."""
    sentinel_path.parent.mkdir(parents=True, exist_ok=True)
    sentinel_path.write_text(str(time.time()))


# ── Pattern A: Co-activation -> New Edge ──────────────────────────────

def pattern_a_coactivation_edges(
    conn,
    window: int = DEFAULT_ACTIVATION_WINDOW,
) -> List[Dict[str, Any]]:
    """
    Find node pairs co-activated >CO_ACTIVATION_THRESHOLD times without an
    existing edge. Propose new edge with low initial weight.
    """
    rows = conn.execute(
        "SELECT activated_nodes FROM activation_log "
        "ORDER BY id DESC LIMIT ?",
        (window,)
    ).fetchall()

    pair_counts: Counter = Counter()
    for row in rows:
        try:
            nodes_raw = row["activated_nodes"] if isinstance(row, dict) else row[0]
            nodes = json.loads(nodes_raw) if isinstance(nodes_raw, str) else nodes_raw
            if not isinstance(nodes, list):
                continue
            ids = [n["node_id"] for n in nodes if isinstance(n, dict) and "node_id" in n]
            # Count all pairs
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    pair = tuple(sorted([ids[i], ids[j]]))
                    pair_counts[pair] += 1
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    proposals = []
    for (src, tgt), count in pair_counts.items():
        if count <= CO_ACTIVATION_THRESHOLD:
            continue
        # Check if edge already exists
        existing = conn.execute(
            "SELECT 1 FROM edges WHERE "
            "(source_id=? AND target_id=?) OR (source_id=? AND target_id=?)",
            (src, tgt, tgt, src)
        ).fetchone()
        if existing:
            continue
        proposals.append({
            "type": "new_edge",
            "pattern": "A",
            "source_id": src,
            "target_id": tgt,
            "co_activations": count,
            "proposed_weight": 0.15,
            "reason": f"Co-activated {count} times without existing edge",
            "id": str(uuid.uuid4())[:8],
        })
    return proposals


# ── Pattern B: Cluster -> Entanglement Node ───────────────────────────

def pattern_b_cluster_entanglement(
    conn,
    window: int = DEFAULT_ACTIVATION_WINDOW,
) -> List[Dict[str, Any]]:
    """
    Find clusters of 3+ nodes that always co-activate together.
    Propose new ecosystem_entanglement node if cluster bridges 2+ categories.
    """
    rows = conn.execute(
        "SELECT activated_nodes FROM activation_log "
        "ORDER BY id DESC LIMIT ?",
        (window,)
    ).fetchall()

    # Track which sets of nodes co-activate
    activation_sets: List[frozenset] = []
    for row in rows:
        try:
            nodes_raw = row["activated_nodes"] if isinstance(row, dict) else row[0]
            nodes = json.loads(nodes_raw) if isinstance(nodes_raw, str) else nodes_raw
            if not isinstance(nodes, list):
                continue
            ids = frozenset(
                n["node_id"] for n in nodes
                if isinstance(n, dict) and "node_id" in n
            )
            if len(ids) >= CLUSTER_MIN_SIZE:
                activation_sets.append(ids)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    # Find subsets that appear frequently
    set_counts: Counter = Counter()
    for s in activation_sets:
        set_counts[s] += 1

    proposals = []
    seen_clusters = set()
    for node_set, count in set_counts.items():
        if count < CO_ACTIVATION_THRESHOLD or len(node_set) < CLUSTER_MIN_SIZE:
            continue
        # Check if cluster bridges 2+ module categories
        categories = set()
        for nid in node_set:
            parts = nid.split("/")
            categories.add(parts[0] if len(parts) > 1 else "root")
        if len(categories) < 2:
            continue
        # Deduplicate
        cluster_key = frozenset(node_set)
        if cluster_key in seen_clusters:
            continue
        seen_clusters.add(cluster_key)
        # Check no existing entanglement node for this cluster
        cluster_id_fragment = "_".join(sorted(node_set))[:20]
        existing = conn.execute(
            "SELECT 1 FROM nodes WHERE id LIKE ? AND node_type='ecosystem_entanglement'",
            (f"%{cluster_id_fragment}%",)
        ).fetchone()
        if existing:
            continue
        proposals.append({
            "type": "new_entanglement_node",
            "pattern": "B",
            "cluster_node_ids": sorted(node_set),
            "co_activation_count": count,
            "categories_bridged": sorted(categories),
            "reason": (f"Cluster of {len(node_set)} nodes co-activated {count} times "
                       f"across {len(categories)} categories"),
            "id": str(uuid.uuid4())[:8],
        })
    return proposals


# ── Pattern C: Low-Access -> Archive Proposal ─────────────────────────

def pattern_c_archive_candidates(conn) -> List[Dict[str, Any]]:
    """
    Find nodes with access_count <= LOW_ACCESS_THRESHOLD in past LOW_ACCESS_DAYS.
    Propose archive (never auto-actioned).
    """
    cutoff = time.time() - (LOW_ACCESS_DAYS * 86400)
    rows = conn.execute(
        "SELECT id, name, access_count, last_accessed FROM nodes "
        "WHERE access_count <= ? AND (last_accessed IS NULL OR last_accessed < ?)",
        (LOW_ACCESS_THRESHOLD, cutoff)
    ).fetchall()

    proposals = []
    for row in rows:
        node_id = row["id"] if isinstance(row, dict) else row[0]
        node_name = row["name"] if isinstance(row, dict) else row[1]
        access_count = row["access_count"] if isinstance(row, dict) else row[2]
        last_acc_val = row["last_accessed"] if isinstance(row, dict) else row[3]
        last_acc = last_acc_val or 0
        days_ago = int((time.time() - last_acc) / 86400) if last_acc > 0 else 999
        proposals.append({
            "type": "archive",
            "pattern": "C",
            "node_id": node_id,
            "node_name": node_name,
            "access_count": access_count,
            "last_accessed_days_ago": days_ago,
            "reason": f"access_count={access_count}, last accessed {days_ago}d ago",
            "id": str(uuid.uuid4())[:8],
        })
    return proposals


# ── Pattern D: Blind Spots -> New Node Proposal ──────────────────────

def pattern_d_blind_spots(
    conn,
    window: int = DEFAULT_ACTIVATION_WINDOW,
) -> List[Dict[str, Any]]:
    """
    Find recurring prompt contexts where NO high-relevance node activated.
    These represent knowledge gaps the brain should fill.
    """
    rows = conn.execute(
        "SELECT query, activated_nodes FROM activation_log "
        "ORDER BY id DESC LIMIT ?",
        (window,)
    ).fetchall()

    # Track queries with no high-relevance activation
    weak_queries: Counter = Counter()
    for row in rows:
        query = (row["query"] if isinstance(row, dict) else row[0]) or ""
        if not query or query.startswith("auto_ingest:"):
            continue
        try:
            nodes_raw = row["activated_nodes"] if isinstance(row, dict) else row[1]
            nodes = json.loads(nodes_raw) if isinstance(nodes_raw, str) else nodes_raw
            if not isinstance(nodes, list):
                weak_queries[query] += 1
                continue
            max_relevance = max(
                (n.get("activation_level", 0) for n in nodes if isinstance(n, dict)),
                default=0,
            )
            if max_relevance < HIGH_RELEVANCE_FLOOR:
                weak_queries[query] += 1
        except (json.JSONDecodeError, KeyError, TypeError):
            weak_queries[query] += 1

    proposals = []
    for query, count in weak_queries.most_common(10):
        if count < CO_ACTIVATION_THRESHOLD:
            continue
        node_id = f"blind_spot/{query[:40].replace(' ', '_').lower()}"
        proposals.append({
            "type": "new_node",
            "pattern": "D",
            "proposed_node_id": node_id,
            "trigger_query": query,
            "occurrence_count": count,
            "reason": f"Query '{query[:60]}' activated no high-relevance node {count} times",
            "id": str(uuid.uuid4())[:8],
        })
    return proposals


# ── Dream Consolidation Main ─────────────────────────────────────────

def consolidate(
    scope: str = "session-close",
    activation_window: int = DEFAULT_ACTIVATION_WINDOW,
    brain_db_path: Optional[str] = None,
    sentinel_path: Optional[Path] = None,
    proposals_path: Optional[Path] = None,
    cieu_store: Optional[CIEUStore] = None,
    session_id: str = "",
    force: bool = False,
    db_connector: Optional[Callable] = None,
    db_initializer: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    Run full dream consolidation cycle.

    Args:
        scope: "session-close" or "idle"
        activation_window: Number of activation_log rows to scan
        brain_db_path: Path to aiden_brain.db
        sentinel_path: Path for lockout sentinel file
        proposals_path: Path for .dream_proposals.jsonl output
        cieu_store: CIEUStore instance for event emission (None = no emission)
        session_id: Current session identifier
        force: Bypass lockout sentinel
        db_connector: Callable returning a DB connection (for testing)
        db_initializer: Callable to initialize DB schema (for testing)

    Returns summary dict with proposal counts and status.
    """
    if not session_id:
        session_id = f"dream-{int(time.time())}"
    if sentinel_path is None:
        sentinel_path = Path(".last_dream_timestamp")
    if proposals_path is None:
        proposals_path = Path(".dream_proposals.jsonl")

    t0 = time.time()

    # Idempotency check
    if not force:
        locked, remaining = check_lockout(sentinel_path)
        if locked:
            msg = f"Dream locked out for {remaining:.0f}s more"
            return {"status": "skipped", "reason": msg, "remaining_s": remaining}

    # Set sentinel BEFORE starting (prevents concurrent runs)
    set_sentinel(sentinel_path)

    # Emit cycle start
    _emit(cieu_store, BRAIN_DREAM_CYCLE_START, {
        "scope": scope,
        "activation_window": activation_window,
        "session_id": session_id,
    }, session_id)

    # Open brain DB
    if db_initializer:
        db_initializer()
    elif brain_db_path:
        from ystar.governance.brain_dream_scheduler import _lazy_init_db
        _lazy_init_db(brain_db_path)

    if db_connector:
        conn = db_connector()
    elif brain_db_path:
        import sqlite3
        conn = sqlite3.connect(brain_db_path)
        conn.row_factory = sqlite3.Row
    else:
        raise ValueError("Either db_connector or brain_db_path must be provided")

    a_props: List[Dict] = []
    b_props: List[Dict] = []
    c_props: List[Dict] = []
    d_props: List[Dict] = []
    all_proposals: List[Dict[str, Any]] = []

    try:
        # Pattern A: co-activation edges
        a_props = pattern_a_coactivation_edges(conn, activation_window)
        for p in a_props:
            _emit(cieu_store, BRAIN_EDGE_PROPOSED, {
                "source_id": p["source_id"],
                "target_id": p["target_id"],
                "co_activations": p["co_activations"],
                "pattern": "A",
                "session_id": session_id,
            }, session_id)
        all_proposals.extend(a_props)

        # Pattern B: cluster entanglement
        b_props = pattern_b_cluster_entanglement(conn, activation_window)
        for p in b_props:
            _emit(cieu_store, BRAIN_ENTANGLEMENT_PROPOSED, {
                "cluster_node_ids": p["cluster_node_ids"],
                "co_activation_count": p["co_activation_count"],
                "pattern": "B",
                "session_id": session_id,
            }, session_id)
        all_proposals.extend(b_props)

        # Pattern C: archive candidates
        c_props = pattern_c_archive_candidates(conn)
        for p in c_props:
            _emit(cieu_store, BRAIN_ARCHIVE_PROPOSED, {
                "node_id": p["node_id"],
                "access_count": p["access_count"],
                "last_accessed_days_ago": p["last_accessed_days_ago"],
                "pattern": "C",
                "session_id": session_id,
            }, session_id)
        all_proposals.extend(c_props)

        # Pattern D: blind spot nodes
        d_props = pattern_d_blind_spots(conn, activation_window)
        for p in d_props:
            _emit(cieu_store, BRAIN_NODE_PROPOSED, {
                "node_id": p["proposed_node_id"],
                "reason": p["reason"],
                "pattern": "D",
                "session_id": session_id,
            }, session_id)
        all_proposals.extend(d_props)

    finally:
        conn.close()

    # Write proposals to JSONL
    _write_proposals(all_proposals, proposals_path)

    duration_ms = int((time.time() - t0) * 1000)
    summary = {
        "status": "complete",
        "scope": scope,
        "proposals_total": len(all_proposals),
        "new_edges": len(a_props),
        "entanglements": len(b_props),
        "archives": len(c_props),
        "new_nodes": len(d_props),
        "duration_ms": duration_ms,
        "session_id": session_id,
        "proposals_file": str(proposals_path),
    }

    # Emit cycle complete
    _emit(cieu_store, BRAIN_DREAM_CYCLE_COMPLETE, summary, session_id)

    return summary


def _lazy_init_db(db_path: str) -> None:
    """Initialize brain DB if needed (lazy import to avoid circular deps)."""
    try:
        sys.path.insert(0, str(Path(db_path).parent))
        from aiden_brain import init_db
        init_db(db_path)
    except ImportError:
        pass  # DB must already be initialized


def _write_proposals(proposals: List[Dict[str, Any]], proposals_path: Path) -> None:
    """Append proposals to .dream_proposals.jsonl."""
    proposals_path.parent.mkdir(parents=True, exist_ok=True)
    with open(proposals_path, "a") as f:
        for p in proposals:
            p["timestamp"] = time.time()
            f.write(json.dumps(p, default=str) + "\n")


def show_proposals(proposals_path: Optional[Path] = None) -> None:
    """Display current dream proposals."""
    if proposals_path is None:
        proposals_path = Path(".dream_proposals.jsonl")
    if not proposals_path.exists():
        print("No dream proposals found. Run a consolidation first.")
        return
    lines = proposals_path.read_text().strip().split("\n")
    print(f"=== Dream Proposals ({len(lines)} total) ===\n")
    for line in lines[-20:]:
        try:
            p = json.loads(line)
            pattern = p.get("pattern", "?")
            ptype = p.get("type", "unknown")
            reason = p.get("reason", "")[:80]
            print(f"  [{pattern}] {ptype}: {reason}")
        except json.JSONDecodeError:
            pass


# ── CLI ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Brain Dream Scheduler")
    parser.add_argument("--mode", choices=["consolidate", "show-proposals"],
                        required=True)
    parser.add_argument("--scope", choices=["session-close", "idle"],
                        default="session-close")
    parser.add_argument("--window", type=int, default=DEFAULT_ACTIVATION_WINDOW,
                        help="Number of activation_log rows to scan")
    parser.add_argument("--force", action="store_true",
                        help="Bypass lockout sentinel")
    parser.add_argument("--brain-db", type=str, default=None,
                        help="Path to aiden_brain.db")
    parser.add_argument("--sentinel", type=str, default=None,
                        help="Path to sentinel file")
    parser.add_argument("--proposals", type=str, default=None,
                        help="Path to proposals JSONL file")
    args = parser.parse_args()

    if args.mode == "consolidate":
        result = consolidate(
            scope=args.scope,
            activation_window=args.window,
            brain_db_path=args.brain_db,
            sentinel_path=Path(args.sentinel) if args.sentinel else None,
            proposals_path=Path(args.proposals) if args.proposals else None,
            force=args.force,
        )
        print(json.dumps(result))
        sys.exit(0 if result.get("status") in ("complete", "skipped") else 1)
    elif args.mode == "show-proposals":
        show_proposals(Path(args.proposals) if args.proposals else None)
