#!/usr/bin/env python3
"""
CIEU → 6D Brain Continuous Daemon (ARCH-18 Phase 2)

Long-running process that polls for new CIEU events and streams them
into the 6D brain with Hebbian co-firing updates.

Usage:
    python3 scripts/cieu_brain_daemon.py
    python3 scripts/cieu_brain_daemon.py --poll-interval 10 --max-iterations 50
    python3 scripts/cieu_brain_daemon.py --cieu-db /path/to/cieu.db --brain-db /path/to/brain.db

Lifecycle:
    - Writes PID to scripts/.cieu_brain_daemon.pid on start
    - Removes PID file on clean shutdown (SIGTERM / SIGINT / max-iterations)
    - Graceful: SIGTERM → finish current poll → exit
"""

import argparse
import atexit
import os
import signal
import sys
import time

# Add project root to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from ystar.governance.cieu_brain_streamer import (
    DEFAULT_BRAIN_DB,
    DEFAULT_CIEU_DB,
    _fetch_new_cieu_events,
    _get_last_ingested_seq,
    _emit_stream_meta_event,
    stream_new_events_to_brain,
)
from ystar.governance.cieu_brain_bridge import (
    apply_hebbian_update,
    process_event,
)
import sqlite3

PID_FILE = os.path.join(SCRIPT_DIR, ".cieu_brain_daemon.pid")

_shutdown_requested = False


def _write_pid():
    """Write current PID to file."""
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    print(f"[daemon] PID {os.getpid()} written to {PID_FILE}")


def _remove_pid():
    """Remove PID file on exit."""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
            print(f"[daemon] PID file removed: {PID_FILE}")
    except OSError:
        pass


def _handle_signal(signum, frame):
    """Signal handler for graceful shutdown."""
    global _shutdown_requested
    _shutdown_requested = True
    print(f"[daemon] Received signal {signum}, shutting down gracefully...")


def main():
    global _shutdown_requested

    parser = argparse.ArgumentParser(
        description="CIEU → 6D Brain continuous ingestion daemon"
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Seconds between polls (default: 5)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=0,
        help="Max poll cycles, 0 = infinite (default: 0)",
    )
    parser.add_argument(
        "--cieu-db",
        default=DEFAULT_CIEU_DB,
        help="Path to .ystar_cieu.db",
    )
    parser.add_argument(
        "--brain-db",
        default=DEFAULT_BRAIN_DB,
        help="Path to aiden_brain.db",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=3,
        help="Top-k nearest nodes per event (default: 3)",
    )
    parser.add_argument(
        "--since-seq",
        type=int,
        default=0,
        help="Start from this seq_global (0 = auto-detect)",
    )
    args = parser.parse_args()

    # Install signal handlers
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # PID lifecycle
    _write_pid()
    atexit.register(_remove_pid)

    # Determine starting cursor
    cursor = args.since_seq
    if cursor == 0:
        cursor = _get_last_ingested_seq(args.brain_db)
    print(f"[daemon] Starting from seq_global={cursor}")
    print(f"[daemon] poll_interval={args.poll_interval}s, "
          f"max_iterations={args.max_iterations}, k={args.k}")

    iteration = 0
    total_events = 0
    total_activations = 0
    total_hebbian = 0

    while not _shutdown_requested:
        iteration += 1

        events = _fetch_new_cieu_events(args.cieu_db, cursor)
        if events:
            t0 = time.time()
            batch_act = 0
            batch_heb = 0
            brain_conn = sqlite3.connect(args.brain_db)

            for event in events:
                activations = process_event(
                    event, k=args.k, brain_conn=brain_conn
                )
                batch_act += len(activations)

                activated_ids = [a["node_id"] for a in activations]
                if len(activated_ids) >= 2:
                    n_updates = apply_hebbian_update(
                        activated_ids, conn=brain_conn
                    )
                    batch_heb += n_updates

                seq = event.get("seq_global", 0)
                if seq > cursor:
                    cursor = seq

            brain_conn.close()
            elapsed = time.time() - t0

            total_events += len(events)
            total_activations += batch_act
            total_hebbian += batch_heb

            _emit_stream_meta_event(
                args.cieu_db,
                count_ingested=len(events),
                max_seq=cursor,
                elapsed=elapsed,
                edge_updates=batch_heb,
            )

            print(
                f"[daemon] iter={iteration} ingested={len(events)} "
                f"activations={batch_act} hebbian={batch_heb} "
                f"cursor={cursor}"
            )
        else:
            if iteration % 12 == 0:  # heartbeat every ~60s at 5s interval
                print(f"[daemon] iter={iteration} idle, cursor={cursor}")

        if args.max_iterations > 0 and iteration >= args.max_iterations:
            print(f"[daemon] Reached max_iterations={args.max_iterations}")
            break

        if _shutdown_requested:
            break

        time.sleep(args.poll_interval)

    # Final summary
    print(f"\n[daemon] Shutdown complete.")
    print(f"[daemon] Total events={total_events} activations={total_activations} "
          f"hebbian_updates={total_hebbian} iterations={iteration}")


if __name__ == "__main__":
    main()
