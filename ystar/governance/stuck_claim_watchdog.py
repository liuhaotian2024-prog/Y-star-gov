"""
stuck_claim_watchdog — detect dispatch board tasks stuck in 'claimed' state.

Scans dispatch_board.json for tasks where:
  - status == "claimed"
  - claimed_at > threshold_min ago
  - no CIEU events referencing that atomic_id within threshold_min

Emits STUCK_CLAIM_DETECTED CIEU event and writes markdown report.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# Defaults — overridable via function args
_DEFAULT_BOARD = Path("/Users/haotianliu/.openclaw/workspace/ystar-company/governance/dispatch_board.json")
_DEFAULT_CIEU_DB = Path("/Users/haotianliu/.openclaw/workspace/ystar-company/.ystar_cieu.db")
_DEFAULT_REPORT = Path("/Users/haotianliu/.openclaw/workspace/ystar-company/reports/ceo/stuck_claims.md")


def _read_board(board_path: Path) -> Dict[str, Any]:
    if not board_path.exists():
        return {"tasks": []}
    with open(board_path, "r") as f:
        return json.load(f)


def _has_recent_cieu(db_path: Path, atomic_id: str, since_ts: float) -> bool:
    """Check if any CIEU event references atomic_id since given unix timestamp."""
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT COUNT(*) FROM cieu_events WHERE created_at >= ? AND "
            "(task_description LIKE ? OR params_json LIKE ?)",
            (since_ts, f"%{atomic_id}%", f"%{atomic_id}%"),
        )
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return False


def scan_stuck_claims(
    board_path: Path = _DEFAULT_BOARD,
    cieu_db: Path = _DEFAULT_CIEU_DB,
    threshold_min: int = 5,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Return list of stuck claimed tasks.

    A task is stuck when:
      1. status == "claimed"
      2. claimed_at is older than threshold_min minutes
      3. No CIEU events reference its atomic_id in the last threshold_min minutes
    """
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=threshold_min)
    cutoff_ts = cutoff.timestamp()

    board = _read_board(board_path)
    stuck = []

    for task in board.get("tasks", []):
        if task.get("status") != "claimed":
            continue
        claimed_at_str = task.get("claimed_at")
        if not claimed_at_str:
            continue
        try:
            claimed_at = datetime.fromisoformat(claimed_at_str)
        except (ValueError, TypeError):
            continue
        if claimed_at >= cutoff:
            continue  # fresh claim, not stuck yet
        if _has_recent_cieu(cieu_db, task["atomic_id"], cutoff_ts):
            continue  # has recent activity
        stuck.append({
            "atomic_id": task["atomic_id"],
            "claimed_by": task.get("claimed_by", "unknown"),
            "claimed_at": claimed_at_str,
            "stale_minutes": round((now - claimed_at).total_seconds() / 60, 1),
            "scope": task.get("scope", ""),
        })

    return stuck


def write_stuck_report(stuck_list: List[Dict[str, Any]], out_path: Path = _DEFAULT_REPORT) -> str:
    """Append stuck claims to markdown report. Returns the appended block."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"\n## Stuck Claims Scan  {ts}\n"]
    if not stuck_list:
        lines.append("No stuck claims detected.\n")
    else:
        lines.append(f"**{len(stuck_list)} stuck claim(s) detected:**\n")
        for s in stuck_list:
            lines.append(
                f"- `{s['atomic_id']}` claimed by {s['claimed_by']} "
                f"({s['stale_minutes']} min stale, scope: {s['scope']})"
            )
        lines.append("")

    block = "\n".join(lines)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "a") as f:
        f.write(block)
    return block


def _emit_stuck_cieu(stuck_list: List[Dict[str, Any]], db_path: Path) -> None:
    """Write STUCK_CLAIM_DETECTED events to CIEU store."""
    if not db_path.exists() or not stuck_list:
        return
    import uuid
    try:
        conn = sqlite3.connect(str(db_path))
        for s in stuck_list:
            conn.execute(
                "INSERT INTO cieu_events "
                "(event_id, seq_global, created_at, session_id, agent_id, event_type, "
                " decision, passed, task_description, params_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    int(time.time() * 1_000_000),
                    time.time(),
                    "watchdog",
                    "stuck_claim_watchdog",
                    "STUCK_CLAIM_DETECTED",
                    "escalate",
                    0,
                    f"Stuck: {s['atomic_id']} by {s['claimed_by']} ({s['stale_minutes']}min)",
                    json.dumps(s),
                ),
            )
        conn.commit()
        conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass  # best-effort; don't crash the watchdog


def run_once(
    board_path: Path = _DEFAULT_BOARD,
    cieu_db: Path = _DEFAULT_CIEU_DB,
    report_path: Path = _DEFAULT_REPORT,
    threshold_min: int = 5,
) -> int:
    """Single scan cycle. Returns count of stuck claims found."""
    stuck = scan_stuck_claims(board_path, cieu_db, threshold_min)
    if stuck:
        _emit_stuck_cieu(stuck, cieu_db)
        write_stuck_report(stuck, report_path)
    return len(stuck)
