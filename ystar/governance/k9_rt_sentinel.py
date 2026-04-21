#!/usr/bin/env python3
"""
K9-RT Sentinel Engine
CIEU stream subscriber detecting Rt+1 closure gaps and 3D role violations

Emits warnings to `.ystar_warning_queue.json` (append-only JSON lines).
Consumed by the platform hook injector (out of scope for this module).

Pilot Rule (hardcoded MVP):
- Trigger warning if:
  1. producer=="ceo" AND executor=="ceo"
  2. Task writes to restricted paths: reports/cto, reports/eng-*, src/ystar, tests
  3. OR rt_value > 0 (closure gap)

Dual detection axes:
- 3D role baseline (Producer/Executor/Governed taxonomy from dedf11d7)
- 5-tuple closure (per-task_id Rt+1 > 0)
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Configurable DB path: use environment variable or relative to current working directory
DEFAULT_CIEU_DB = str(Path(os.getcwd()) / ".ystar_cieu.db")
REPO_ROOT = Path(__file__).resolve().parents[2]
CIEU_DB_PATH = Path(os.environ.get("YSTAR_CIEU_DB_PATH", DEFAULT_CIEU_DB))
WARNING_QUEUE_PATH = REPO_ROOT / ".ystar_warning_queue.json"

# CEO engineering boundary (restricted paths from pilot rule)
CEO_RESTRICTED_PATHS = [
    "reports/cto",
    "reports/eng-kernel",
    "reports/eng-governance",
    "reports/eng-platform",
    "reports/eng-domains",
    "src/ystar",
    "tests",
]


def _check_restricted_path_violation(task_context: str) -> bool:
    """
    Check if task context involves CEO writes to engineering territory.
    task_context is expected to contain file paths or operation description.
    """
    for restricted in CEO_RESTRICTED_PATHS:
        if restricted in task_context:
            return True
    return False


def _extract_role_violation(event: Dict) -> Optional[Dict]:
    """
    3D Role Baseline detection (reuse dedf11d7 taxonomy).
    Trigger if producer==ceo AND executor==ceo AND writes to engineering paths.
    """
    # Support both nested `role_tags` (Leo's fixtures) and flat `producer`/`executor` (production emit)
    role_tags = event.get("role_tags", {})
    producer = event.get("producer") or role_tags.get("producer", "")
    executor = event.get("executor") or role_tags.get("executor", "")
    task_context = event.get("y_star", "") + " " + " ".join(event.get("u", []))
    task_context_str = task_context.lower()

    if producer == "ceo" and executor == "ceo":
        if _check_restricted_path_violation(task_context_str):
            rt_value = event.get("rt_plus_1") or event.get("rt_value", 0.0)
            return {
                "task_id": event.get("task_id"),
                "violation_type": "3d_role_mismatch",
                "details": f"CEO acting as executor on engineering paths: {task_context_str[:100]}",
                "rt_value": rt_value,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "agent_id": event.get("agent_id"),
                "role_tags": role_tags,
            }
    return None


def _extract_closure_gap(event: Dict) -> Optional[Dict]:
    """
    5-Tuple Closure detection: Rt+1 > 0 indicates task not closed.
    """
    # Support both `rt_value` (Leo's fixtures) and `rt_plus_1` (production emit)
    rt_value = event.get("rt_plus_1") or event.get("rt_value", 0.0)
    if rt_value > 0:
        return {
            "task_id": event.get("task_id"),
            "violation_type": "rt_not_closed",
            "details": f"Task incomplete: Rt+1={rt_value}. Y*={event.get('y_star', 'N/A')[:80]}",
            "rt_value": rt_value,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "agent_id": event.get("agent_id"),
            "role_tags": event.get("role_tags", {}),
        }
    return None


def _emit_tick_event(scanned: int, warnings_emitted: int):
    """
    Emit K9_RT_SENTINEL_TICK CIEU event for monitoring.
    Confirms sentinel is alive and processing events.
    """
    try:
        if not CIEU_DB_PATH.exists():
            return

        conn = sqlite3.connect(CIEU_DB_PATH)
        tables_cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in tables_cursor.fetchall()]

        tick_payload = {
            "scanned": scanned,
            "warnings_emitted": warnings_emitted,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        if "events" in tables:
            # Production schema: events(id, timestamp, event_type, agent, metadata)
            conn.execute(
                "INSERT INTO events (event_type, agent, metadata, timestamp) VALUES (?, ?, ?, ?)",
                ("K9_RT_SENTINEL_TICK", "k9_rt_sentinel", json.dumps(tick_payload), datetime.utcnow().timestamp())
            )
        elif "cieu_events" in tables:
            # Test schema
            conn.execute(
                "INSERT INTO cieu_events (event_type, payload, created_at) VALUES (?, ?, ?)",
                ("K9_RT_SENTINEL_TICK", json.dumps(tick_payload), datetime.utcnow().timestamp())
            )

        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass  # Graceful degradation: if CIEU DB unavailable, skip tick


def poll_rt_measurements(limit: int = 100, processed_ids: set = None) -> List[Dict]:
    """
    Batch poll CIEU DB for RT_MEASUREMENT events.
    Returns list of event dicts (schema v1.0).
    Filters out events with task_id in processed_ids (dedup).

    Real CIEU DB schema uses `events` table with `metadata` column (JSON).
    Test schema uses `cieu_events` table with `payload` column. Auto-detect.
    """
    if not CIEU_DB_PATH.exists():
        return []

    if processed_ids is None:
        processed_ids = set()

    try:
        conn = sqlite3.connect(CIEU_DB_PATH)
        conn.row_factory = sqlite3.Row

        # Auto-detect schema: check for `events` table (production) vs `cieu_events` (test)
        tables_cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in tables_cursor.fetchall()]

        if "events" in tables:
            # Production schema: events(event_type, metadata, timestamp)
            cursor = conn.execute(
                """
                SELECT event_type, metadata, timestamp
                FROM events
                WHERE event_type = 'RT_MEASUREMENT'
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
            events = []
            for row in cursor.fetchall():
                metadata = json.loads(row["metadata"])
                metadata["timestamp"] = metadata.get("timestamp", str(row["timestamp"]))
                task_id = metadata.get("task_id")
                if task_id not in processed_ids:
                    events.append(metadata)
        elif "cieu_events" in tables:
            # Test schema: cieu_events(event_type, payload, created_at)
            cursor = conn.execute(
                """
                SELECT event_type, payload, created_at
                FROM cieu_events
                WHERE event_type = 'RT_MEASUREMENT'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            events = []
            for row in cursor.fetchall():
                payload = json.loads(row["payload"])
                payload["timestamp"] = payload.get("timestamp", str(row["created_at"]))
                task_id = payload.get("task_id")
                if task_id not in processed_ids:
                    events.append(payload)
        else:
            # No known table schema
            conn.close()
            return []

        conn.close()
        return events
    except sqlite3.Error as e:
        # Graceful degradation: log error, return empty (tests verify this)
        print(f"[K9-RT Sentinel] CIEU DB error: {e}", flush=True)
        return []


def scan_and_emit_warnings(processed_ids: set = None) -> int:
    """
    Main sentinel loop:
    1. Poll RT_MEASUREMENT events
    2. Detect violations (role + closure)
    3. Write warnings to queue (append-only JSON lines)
    4. Track processed task_ids to avoid re-scanning same events
    5. Emit K9_RT_SENTINEL_TICK CIEU event for monitoring

    Returns: number of warnings emitted.
    """
    if processed_ids is None:
        processed_ids = set()

    events = poll_rt_measurements(limit=100, processed_ids=processed_ids)
    warnings = []

    for event in events:
        task_id = event.get("task_id")
        if task_id:
            processed_ids.add(task_id)

        # Axis 1: 3D role violation
        role_warning = _extract_role_violation(event)
        if role_warning:
            warnings.append(role_warning)

        # Axis 2: Closure gap
        closure_warning = _extract_closure_gap(event)
        if closure_warning:
            warnings.append(closure_warning)

    # Write warnings to queue (append-only JSON lines)
    if warnings:
        with open(WARNING_QUEUE_PATH, "a", encoding="utf-8") as f:
            for w in warnings:
                f.write(json.dumps(w) + "\n")

    # Emit TICK event for cron monitoring (verify sentinel is alive)
    _emit_tick_event(scanned=len(events), warnings_emitted=len(warnings))

    return len(warnings)


if __name__ == "__main__":
    count = scan_and_emit_warnings()
    print(f"[K9-RT Sentinel] Emitted {count} warnings", flush=True)
