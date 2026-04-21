"""
CIEU → 6D Brain Continuous Streamer (ARCH-18 Phase 2)

Polls for new CIEU events since the last-ingested seq_global,
projects each into 6D brain space via cieu_brain_bridge.process_event,
and applies Hebbian co-firing updates to strengthen edges between
co-activated nodes.

Functions:
  stream_new_events_to_brain(since_seq_global, poll_interval_sec, max_iterations,
                             cieu_db, brain_db, k)
  install_cron_trigger(brain_db, cieu_db)
"""

import json
import os
import sqlite3
import sys
import time
import uuid
from typing import List, Optional, Tuple

# Ensure project root on path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from ystar.governance.cieu_brain_bridge import (
    process_event,
    apply_hebbian_update,
)

# Default DB paths
_COMPANY_DIR = os.path.join(
    os.path.expanduser("~"), ".openclaw", "workspace", "ystar-company"
)
DEFAULT_CIEU_DB = os.path.join(_COMPANY_DIR, ".ystar_cieu.db")
DEFAULT_BRAIN_DB = os.path.join(_COMPANY_DIR, "aiden_brain.db")


def _get_last_ingested_seq(brain_db: str) -> int:
    """Derive the highest seq_global already ingested.

    We look at the activation_log.query column which stores
    'cieu_event:<event_id>'. We cross-reference with the CIEU DB
    to find the max seq_global of those event_ids.

    Falls back to querying the activation_log timestamp and mapping
    to the nearest CIEU event's seq_global.

    If activation_log is empty, returns 0.
    """
    conn = sqlite3.connect(brain_db)
    row = conn.execute("SELECT MAX(timestamp) FROM activation_log").fetchone()
    conn.close()
    if row is None or row[0] is None:
        return 0
    # Convert timestamp to microsecond seq_global estimate
    return int(row[0] * 1_000_000)


def _fetch_new_cieu_events(
    cieu_db: str, since_seq_global: int, limit: int = 500
) -> list:
    """Fetch CIEU events with seq_global > since_seq_global, ordered ASC."""
    conn = sqlite3.connect(cieu_db)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """SELECT event_id, seq_global, created_at, event_type, agent_id,
                      decision, session_id, drift_detected, drift_category,
                      violations, file_path, command, params_json
               FROM cieu_events
               WHERE seq_global > ?
                 AND event_type NOT IN (
                     'CIEU_TO_BRAIN_STREAM_BATCH',
                     'CIEU_TO_BRAIN_ACTIVATION'
                 )
               ORDER BY seq_global ASC
               LIMIT ?""",
            (since_seq_global, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _emit_stream_meta_event(
    cieu_db: str,
    count_ingested: int,
    max_seq: int,
    elapsed: float,
    edge_updates: int,
):
    """Emit CIEU_TO_BRAIN_STREAM_BATCH meta-event into CIEU DB."""
    try:
        conn = sqlite3.connect(cieu_db)
        payload = json.dumps({
            "count_ingested": count_ingested,
            "max_seq_global": max_seq,
            "elapsed_sec": round(elapsed, 3),
            "hebbian_edge_updates": edge_updates,
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
                "cieu_brain_streamer",
                "eng-governance",
                "CIEU_TO_BRAIN_STREAM_BATCH",
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
        print(f"[WARN] Failed to emit stream meta-event: {e}", file=sys.stderr)


def stream_new_events_to_brain(
    since_seq_global: int = 0,
    poll_interval_sec: float = 5.0,
    max_iterations: int = 0,
    cieu_db: str = DEFAULT_CIEU_DB,
    brain_db: str = DEFAULT_BRAIN_DB,
    k: int = 3,
) -> dict:
    """Continuously poll for new CIEU events and ingest into 6D brain.

    Args:
        since_seq_global: Start from this seq_global (0 = auto-detect from
                          last activation_log timestamp).
        poll_interval_sec: Seconds between polls.
        max_iterations: Number of poll cycles (0 = infinite).
        cieu_db: Path to .ystar_cieu.db.
        brain_db: Path to aiden_brain.db.
        k: Top-k nearest nodes per event.

    Returns:
        dict with stats: total_events_ingested, total_activations,
        total_hebbian_updates, iterations_run.
    """
    if since_seq_global == 0:
        since_seq_global = _get_last_ingested_seq(brain_db)

    cursor = since_seq_global
    iteration = 0
    total_events = 0
    total_activations = 0
    total_hebbian = 0

    while True:
        iteration += 1

        events = _fetch_new_cieu_events(cieu_db, cursor)
        if events:
            t0 = time.time()
            batch_activations = 0
            batch_hebbian = 0
            brain_conn = sqlite3.connect(brain_db)

            for event in events:
                activations = process_event(
                    event, k=k, brain_conn=brain_conn
                )
                batch_activations += len(activations)

                # Hebbian co-firing: all activated node IDs for this event
                activated_node_ids = [a["node_id"] for a in activations]
                if len(activated_node_ids) >= 2:
                    n_updates = apply_hebbian_update(
                        activated_node_ids, conn=brain_conn
                    )
                    batch_hebbian += n_updates

                # Advance cursor
                seq = event.get("seq_global", 0)
                if seq > cursor:
                    cursor = seq

            brain_conn.close()
            elapsed = time.time() - t0

            total_events += len(events)
            total_activations += batch_activations
            total_hebbian += batch_hebbian

            _emit_stream_meta_event(
                cieu_db,
                count_ingested=len(events),
                max_seq=cursor,
                elapsed=elapsed,
                edge_updates=batch_hebbian,
            )

            print(
                f"[streamer] iter={iteration} ingested={len(events)} "
                f"activations={batch_activations} hebbian={batch_hebbian} "
                f"cursor={cursor} elapsed={elapsed:.2f}s"
            )

        if max_iterations > 0 and iteration >= max_iterations:
            break

        time.sleep(poll_interval_sec)

    return {
        "total_events_ingested": total_events,
        "total_activations": total_activations,
        "total_hebbian_updates": total_hebbian,
        "iterations_run": iteration,
        "final_cursor": cursor,
    }


def install_cron_trigger(
    brain_db: str = DEFAULT_BRAIN_DB,
    cieu_db: str = DEFAULT_CIEU_DB,
) -> str:
    """Install a launchd plist for nightly catch-up ingest.

    Returns the path to the installed plist file.
    """
    label = "com.ystar.cieu-brain-daemon"
    plist_dir = os.path.expanduser("~/Library/LaunchAgents")
    os.makedirs(plist_dir, exist_ok=True)
    plist_path = os.path.join(plist_dir, f"{label}.plist")

    daemon_script = os.path.join(
        _PROJECT_ROOT, "scripts", "cieu_brain_daemon.py"
    )

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>{daemon_script}</string>
        <string>--poll-interval</string>
        <string>60</string>
        <string>--max-iterations</string>
        <string>100</string>
        <string>--cieu-db</string>
        <string>{cieu_db}</string>
        <string>--brain-db</string>
        <string>{brain_db}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/cieu_brain_daemon.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/cieu_brain_daemon.err</string>
</dict>
</plist>
"""

    with open(plist_path, "w") as f:
        f.write(plist_content)

    print(f"[install_cron_trigger] Wrote {plist_path}")
    print(f"[install_cron_trigger] To load: launchctl load {plist_path}")
    return plist_path
