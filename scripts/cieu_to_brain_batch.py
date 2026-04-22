#!/usr/bin/env python3
"""
CIEU → 6D Brain batch ingestion runner (ARCH-18 Phase 1).

Reads last N CIEU events from .ystar_cieu.db, projects each into 6D space,
activates nearest brain nodes, and records activations in aiden_brain.db.

Supports parallel processing: --workers N splits event range across N worker
processes that compute 6D projections + top-k in parallel, funneling results
through a shared queue to a single writer process that serializes DB inserts.

Usage:
    python3 scripts/cieu_to_brain_batch.py --n 100
    python3 scripts/cieu_to_brain_batch.py --n 500 --k 5
    python3 scripts/cieu_to_brain_batch.py --n 1000 --workers 4
    python3 scripts/cieu_to_brain_batch.py --cieu-db /path/to/cieu.db --brain-db /path/to/brain.db
"""

import argparse
import json
import math
import multiprocessing
import os
import sqlite3
import sys
import time

# Add project root to path so we can import ystar.governance
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from ystar.governance.cieu_brain_bridge import (
    euclidean_6d,
    insert_activation,
    process_event,
    project_event_to_6d,
    top_k_nodes,
)

# Default DB paths (ystar-company workspace)
DEFAULT_COMPANY_DIR = os.path.join(
    os.path.expanduser("~"), ".openclaw", "workspace", "ystar-company"
)
DEFAULT_CIEU_DB = os.path.join(DEFAULT_COMPANY_DIR, ".ystar_cieu.db")
DEFAULT_BRAIN_DB = os.path.join(DEFAULT_COMPANY_DIR, "aiden_brain.db")

# Sentinel value to signal writer process that all workers are done
_SENTINEL = None
# Batch size for writer commits
_WRITER_BATCH_SIZE = 500


def read_cieu_events(cieu_db_path: str, n: int) -> list:
    """Read the last N CIEU events as list of dicts."""
    conn = sqlite3.connect(cieu_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """SELECT event_id, created_at, event_type, agent_id, decision,
                      session_id, drift_detected, drift_category,
                      violations, file_path, command
               FROM cieu_events
               ORDER BY rowid DESC
               LIMIT ?""",
            (n,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        return rows
    finally:
        conn.close()


def read_cieu_events_range(cieu_db_path: str, offset: int, limit: int) -> list:
    """Read CIEU events by rowid range (for partition-based parallel reads).

    Returns events with rowid in (offset, offset+limit], ordered by rowid DESC.
    Actually uses LIMIT/OFFSET on the rowid-ordered result for deterministic partitioning.
    """
    conn = sqlite3.connect(cieu_db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """SELECT event_id, created_at, event_type, agent_id, decision,
                      session_id, drift_detected, drift_category,
                      violations, file_path, command
               FROM cieu_events
               ORDER BY rowid DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        return rows
    finally:
        conn.close()


def partition_range(total: int, num_workers: int) -> list:
    """Split total items into num_workers partitions.

    Returns list of (offset, count) tuples. No gaps, no overlaps.
    Example: partition_range(10, 3) -> [(0,4), (4,3), (7,3)]
    """
    base_size = total // num_workers
    remainder = total % num_workers
    partitions = []
    offset = 0
    for i in range(num_workers):
        size = base_size + (1 if i < remainder else 0)
        if size > 0:
            partitions.append((offset, size))
        offset += size
    return partitions


def _load_all_nodes(brain_db_path: str) -> list:
    """Load all brain nodes into memory (read-only snapshot for workers)."""
    conn = sqlite3.connect(brain_db_path)
    try:
        cur = conn.execute(
            "SELECT id, name, dim_y, dim_x, dim_z, dim_t, dim_phi, dim_c FROM nodes"
        )
        return cur.fetchall()
    finally:
        conn.close()


def _top_k_from_cached_nodes(coords, k, cached_nodes):
    """Compute top-k nearest nodes from an in-memory node list (no DB access)."""
    scored = []
    for row in cached_nodes:
        nid, name = row[0], row[1]
        node_coords = (row[2], row[3], row[4], row[5], row[6], row[7])
        dist = euclidean_6d(coords, node_coords)
        scored.append((nid, name, dist))
    scored.sort(key=lambda x: x[2])
    return scored[:k]


def worker_process(
    worker_id: int,
    cieu_db_path: str,
    brain_db_path: str,
    offset: int,
    count: int,
    k: int,
    result_queue: multiprocessing.Queue,
    cached_nodes: list,
):
    """Worker: read partition of events, compute 6D projection + top-k, push to queue.

    Each item pushed to queue is a list of dicts:
      [{"event_id": ..., "node_id": ..., "weight": ..., "query_text": ..., "session_id": ...}, ...]
    """
    try:
        events = read_cieu_events_range(cieu_db_path, offset, count)
        for event in events:
            coords = project_event_to_6d(event)
            nearest = _top_k_from_cached_nodes(coords, k, cached_nodes)

            activations = []
            for node_id, node_name, dist in nearest:
                weight = 1.0 / (1.0 + dist) if dist > 0 else 1.0
                weight = max(0.01, min(1.0, weight))
                activations.append({
                    "event_id": event.get("event_id", "unknown"),
                    "node_id": node_id,
                    "weight": weight,
                    "query_text": f"{event.get('event_type', '')}|{event.get('decision', '')}",
                    "session_id": event.get("session_id", ""),
                })
            result_queue.put(activations)
    except Exception as e:
        print(f"[worker-{worker_id}] ERROR: {e}", file=sys.stderr)
    finally:
        # Signal this worker is done
        result_queue.put(_SENTINEL)


def writer_process(
    brain_db_path: str,
    result_queue: multiprocessing.Queue,
    num_workers: int,
    stats_dict: dict,
):
    """Writer: drain queue, batch INSERT activations, commit every _WRITER_BATCH_SIZE rows.

    Waits for num_workers sentinel values before terminating.
    """
    conn = sqlite3.connect(brain_db_path)
    sentinels_received = 0
    batch = []
    total_inserted = 0
    now = time.time()

    while sentinels_received < num_workers:
        item = result_queue.get()
        if item is _SENTINEL:
            sentinels_received += 1
            continue

        # item is a list of activation dicts from one event
        for act in item:
            activated = json.dumps([{"node_id": act["node_id"], "activation_level": act["weight"]}])
            batch.append((
                f"cieu_event:{act['event_id']}",
                activated,
                act["session_id"],
                now,
            ))

        if len(batch) >= _WRITER_BATCH_SIZE:
            conn.executemany(
                """INSERT INTO activation_log (query, activated_nodes, session_id, timestamp)
                   VALUES (?, ?, ?, ?)""",
                batch,
            )
            conn.commit()
            total_inserted += len(batch)
            batch = []

    # Flush remaining batch
    if batch:
        conn.executemany(
            """INSERT INTO activation_log (query, activated_nodes, session_id, timestamp)
               VALUES (?, ?, ?, ?)""",
            batch,
        )
        conn.commit()
        total_inserted += len(batch)

    conn.close()
    stats_dict["total_inserted"] = total_inserted


def emit_cieu_event(
    cieu_db_path: str,
    event_ids_in: list,
    node_ids_out: list,
    weights: list,
    total_ingested: int,
    total_activations: int,
):
    """Emit a CIEU_TO_BRAIN_ACTIVATION meta-event back into the CIEU DB."""
    try:
        conn = sqlite3.connect(cieu_db_path)
        import uuid
        payload = json.dumps({
            "event_ids_in_count": len(event_ids_in),
            "event_ids_in_sample": event_ids_in[:5],
            "node_ids_out": list(set(node_ids_out))[:20],
            "weights_sample": weights[:10],
            "total_ingested": total_ingested,
            "total_activations": total_activations,
        })
        conn.execute(
            """INSERT INTO cieu_events
               (event_id, seq_global, created_at, session_id, agent_id,
                event_type, decision, passed, drift_detected, sealed,
                params_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                int(time.time() * 1_000_000),
                time.time(),
                "cieu_brain_batch",
                "eng-governance",
                "CIEU_TO_BRAIN_ACTIVATION",
                "info",
                1,
                0,
                0,
                payload,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WARN] Failed to emit CIEU meta-event: {e}")


def run_sequential(events, args):
    """Original sequential processing path."""
    brain_conn = sqlite3.connect(args.brain_db)
    before_count = brain_conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
    print(f"[cieu_to_brain] activation_log rows BEFORE: {before_count}")

    all_node_ids = []
    all_weights = []
    all_event_ids = []
    centroid = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    processed = 0
    t0 = time.time()

    for event in events:
        coords = project_event_to_6d(event)
        for i in range(6):
            centroid[i] += coords[i]

        activations = process_event(event, k=args.k, brain_conn=brain_conn)
        for act in activations:
            all_node_ids.append(act["node_id"])
            all_weights.append(act["weight"])
        all_event_ids.append(event.get("event_id", "?"))
        processed += 1

    elapsed = time.time() - t0

    if processed > 0:
        centroid = [c / processed for c in centroid]

    after_count = brain_conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
    brain_conn.close()

    return {
        "before_count": before_count,
        "after_count": after_count,
        "all_node_ids": all_node_ids,
        "all_weights": all_weights,
        "all_event_ids": all_event_ids,
        "centroid": centroid,
        "processed": processed,
        "elapsed": elapsed,
    }


def run_parallel(events, args):
    """Parallel processing path using multiprocessing."""
    num_workers = args.workers
    total = len(events)

    brain_conn = sqlite3.connect(args.brain_db)
    before_count = brain_conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
    brain_conn.close()

    print(f"[cieu_to_brain] activation_log rows BEFORE: {before_count}")
    print(f"[cieu_to_brain] Parallel mode: {num_workers} workers, {total} events")

    # Pre-load nodes into memory (shared across workers via fork)
    cached_nodes = _load_all_nodes(args.brain_db)
    print(f"[cieu_to_brain] Cached {len(cached_nodes)} brain nodes for workers")

    # Partition
    partitions = partition_range(total, num_workers)
    print(f"[cieu_to_brain] Partitions: {partitions}")

    # Shared queue and stats dict
    result_queue = multiprocessing.Queue(maxsize=min(total + num_workers + 10, 30000))
    manager = multiprocessing.Manager()
    stats_dict = manager.dict()
    stats_dict["total_inserted"] = 0

    t0 = time.time()

    # Start writer process
    writer = multiprocessing.Process(
        target=writer_process,
        args=(args.brain_db, result_queue, len(partitions), stats_dict),
    )
    writer.start()

    # Start worker processes
    workers = []
    for wid, (offset, count) in enumerate(partitions):
        p = multiprocessing.Process(
            target=worker_process,
            args=(wid, args.cieu_db, args.brain_db, offset, count, args.k, result_queue, cached_nodes),
        )
        p.start()
        workers.append(p)

    # Wait for all workers to finish
    for p in workers:
        p.join()

    # Wait for writer to finish draining queue
    writer.join()

    elapsed = time.time() - t0

    # Compute centroid from events (cheap, done in main process)
    centroid = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    for event in events:
        coords = project_event_to_6d(event)
        for i in range(6):
            centroid[i] += coords[i]
    if total > 0:
        centroid = [c / total for c in centroid]

    # Read final count
    brain_conn = sqlite3.connect(args.brain_db)
    after_count = brain_conn.execute("SELECT COUNT(*) FROM activation_log").fetchone()[0]
    brain_conn.close()

    all_event_ids = [e.get("event_id", "?") for e in events]

    return {
        "before_count": before_count,
        "after_count": after_count,
        "all_node_ids": [],  # not tracked per-node in parallel mode (perf tradeoff)
        "all_weights": [],
        "all_event_ids": all_event_ids,
        "centroid": centroid,
        "processed": total,
        "elapsed": elapsed,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Batch ingest CIEU events into 6D brain activation_log"
    )
    parser.add_argument("--n", type=int, default=100, help="Number of recent CIEU events to process")
    parser.add_argument("--k", type=int, default=3, help="Top-K nearest nodes per event")
    parser.add_argument("--cieu-db", default=DEFAULT_CIEU_DB, help="Path to .ystar_cieu.db")
    parser.add_argument("--brain-db", default=DEFAULT_BRAIN_DB, help="Path to aiden_brain.db")
    parser.add_argument("--workers", type=int, default=0,
                        help="Number of parallel workers (0 = sequential, default)")
    parser.add_argument("--range-from", type=int, default=0,
                        help="Start offset for event_id partition (advanced)")
    parser.add_argument("--range-to", type=int, default=0,
                        help="End offset for event_id partition (advanced)")
    args = parser.parse_args()

    print(f"[cieu_to_brain] Reading last {args.n} CIEU events from {args.cieu_db}")
    events = read_cieu_events(args.cieu_db, args.n)
    print(f"[cieu_to_brain] Loaded {len(events)} events")

    if not events:
        print("[cieu_to_brain] No events found. Exiting.")
        return

    # Apply range filter if specified
    if args.range_from > 0 or args.range_to > 0:
        end = args.range_to if args.range_to > 0 else len(events)
        events = events[args.range_from:end]
        print(f"[cieu_to_brain] After range filter: {len(events)} events")

    # Choose execution path
    if args.workers > 0:
        result = run_parallel(events, args)
    else:
        result = run_sequential(events, args)

    # Emit meta-event
    emit_cieu_event(
        args.cieu_db,
        result["all_event_ids"],
        result["all_node_ids"],
        result["all_weights"],
        result["processed"],
        result["after_count"] - result["before_count"],
    )

    # Report
    mode_str = f"parallel ({args.workers} workers)" if args.workers > 0 else "sequential"
    throughput = result["processed"] / result["elapsed"] if result["elapsed"] > 0 else 0
    centroid = result["centroid"]

    print(f"\n{'='*60}")
    print(f"CIEU -> 6D Brain Batch Report ({mode_str})")
    print(f"{'='*60}")
    print(f"  Events ingested:       {result['processed']}")
    print(f"  activation_log BEFORE: {result['before_count']}")
    print(f"  activation_log AFTER:  {result['after_count']}")
    print(f"  New activations:       {result['after_count'] - result['before_count']}")
    print(f"  Elapsed time:          {result['elapsed']:.2f}s")
    print(f"  Throughput:            {throughput:.1f} events/sec")
    print(f"  6D centroid of batch:  y={centroid[0]:.3f} x={centroid[1]:.3f} "
          f"z={centroid[2]:.3f} t={centroid[3]:.3f} phi={centroid[4]:.3f} c={centroid[5]:.3f}")
    print(f"{'='*60}")

    if result["after_count"] > result["before_count"]:
        print("[OK] Brain activation_log has live firings.")
    else:
        print("[FAIL] activation_log still empty after run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
