"""Tests for stuck_claim_watchdog — 3 scenarios."""

import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pytest

from ystar.governance.stuck_claim_watchdog import (
    scan_stuck_claims,
    write_stuck_report,
    run_once,
)

# ── helpers ──────────────────────────────────────────────────────────────

def _make_board(tmp_path: Path, tasks: list) -> Path:
    p = tmp_path / "dispatch_board.json"
    p.write_text(json.dumps({"tasks": tasks}))
    return p


def _make_cieu_db(tmp_path: Path, rows: Optional[list] = None) -> Path:
    db = tmp_path / "cieu.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE cieu_events ("
        "  rowid INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  event_id TEXT, seq_global INTEGER, created_at REAL,"
        "  session_id TEXT, agent_id TEXT, event_type TEXT,"
        "  decision TEXT, passed INTEGER DEFAULT 0,"
        "  task_description TEXT, params_json TEXT"
        ")"
    )
    if rows:
        for r in rows:
            conn.execute(
                "INSERT INTO cieu_events "
                "(event_id,seq_global,created_at,session_id,agent_id,"
                " event_type,decision,passed,task_description,params_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", r,
            )
    conn.commit()
    conn.close()
    return db


# ── Test 1: fresh claim (< 5 min) => empty ──────────────────────────────

def test_fresh_claim_not_stuck(tmp_path):
    """A claim made 2 minutes ago should NOT be flagged."""
    now = datetime.now(timezone.utc)
    board = _make_board(tmp_path, [{
        "atomic_id": "FRESH-1",
        "status": "claimed",
        "claimed_by": "eng-kernel",
        "claimed_at": (now - timedelta(minutes=2)).isoformat(),
        "scope": "test",
    }])
    db = _make_cieu_db(tmp_path)

    result = scan_stuck_claims(board, db, threshold_min=5, now=now)
    assert result == []


# ── Test 2: stale claim (> 5 min + no CIEU) => 1 item ───────────────────

def test_stale_claim_detected(tmp_path):
    """A claim older than threshold with no CIEU activity is stuck."""
    now = datetime.now(timezone.utc)
    board = _make_board(tmp_path, [{
        "atomic_id": "STALE-1",
        "status": "claimed",
        "claimed_by": "eng-governance",
        "claimed_at": (now - timedelta(minutes=10)).isoformat(),
        "scope": "governance",
    }])
    db = _make_cieu_db(tmp_path)  # no events at all

    result = scan_stuck_claims(board, db, threshold_min=5, now=now)
    assert len(result) == 1
    assert result[0]["atomic_id"] == "STALE-1"
    assert result[0]["claimed_by"] == "eng-governance"
    assert result[0]["stale_minutes"] >= 10.0


# ── Test 3: run_once writes markdown with count ──────────────────────────

def test_run_once_writes_report(tmp_path):
    """run_once should detect stuck claims AND write markdown report."""
    now = datetime.now(timezone.utc)
    board = _make_board(tmp_path, [
        {
            "atomic_id": "RUN-STUCK-1",
            "status": "claimed",
            "claimed_by": "eng-platform",
            "claimed_at": (now - timedelta(minutes=15)).isoformat(),
            "scope": "platform",
        },
        {
            "atomic_id": "RUN-FRESH-1",
            "status": "claimed",
            "claimed_by": "eng-domains",
            "claimed_at": (now - timedelta(minutes=1)).isoformat(),
            "scope": "domains",
        },
    ])
    db = _make_cieu_db(tmp_path)
    report = tmp_path / "stuck_claims.md"

    count = run_once(board, db, report, threshold_min=5)
    assert count == 1

    text = report.read_text()
    assert "RUN-STUCK-1" in text
    assert "1 stuck claim(s)" in text
    assert "RUN-FRESH-1" not in text
