"""
Tests for rule_lifecycle_observer — 3 cases:
1. Empty DB → empty report (no error, zero counts)
2. Injected fake CIEU events → correct LIVE/DORMANT/DEAD classification
3. Markdown output contains counts summary line
"""

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from ystar.governance.rule_lifecycle_observer import (
    LivenessReport,
    scan_rule_liveness,
    write_markdown_report,
)

# ── Schema needed for test DBs (minimal cieu_events table) ───────────

_MINIMAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS cieu_events (
    rowid        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT    NOT NULL UNIQUE,
    seq_global   INTEGER NOT NULL,
    created_at   REAL    NOT NULL,
    session_id   TEXT    NOT NULL DEFAULT '',
    agent_id     TEXT    NOT NULL DEFAULT '',
    event_type   TEXT    NOT NULL DEFAULT '',
    decision     TEXT    NOT NULL DEFAULT 'allow',
    passed       INTEGER NOT NULL DEFAULT 1,
    violations   TEXT,
    drift_detected INTEGER NOT NULL DEFAULT 0,
    drift_details TEXT,
    drift_category TEXT,
    file_path    TEXT,
    command      TEXT,
    url          TEXT,
    skill_name   TEXT,
    skill_source TEXT,
    task_description TEXT,
    contract_hash TEXT,
    chain_depth   INTEGER DEFAULT 0,
    params_json   TEXT,
    result_json   TEXT,
    human_initiator TEXT,
    lineage_path  TEXT,
    sealed        INTEGER NOT NULL DEFAULT 0
);
"""


def _make_db(tmp: str) -> str:
    """Create an empty CIEU SQLite DB and return its path."""
    db_path = str(Path(tmp) / "test_cieu.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(_MINIMAL_SCHEMA)
    conn.close()
    return db_path


def _make_fg_yaml(tmp: str, rule_ids: list) -> str:
    """Create a minimal forget_guard_rules.yaml with given top-level rule ids."""
    yaml_path = str(Path(tmp) / "fg_rules.yaml")
    lines = []
    for rid in rule_ids:
        lines.append(f"{rid}:\n")
        lines.append(f"  action: warn\n")
    Path(yaml_path).write_text("".join(lines), encoding="utf-8")
    return yaml_path


def _insert_event(db_path: str, rule_id: str, created_at: float) -> None:
    """Insert a fake CIEU event that references rule_id in violations."""
    import json
    import uuid
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT INTO cieu_events
            (event_id, seq_global, created_at, session_id, agent_id,
             event_type, decision, passed, violations)
           VALUES (?, ?, ?, 'test-session', 'test-agent',
                   'fg_check', 'deny', 0, ?)""",
        (
            str(uuid.uuid4()),
            int(created_at * 1_000_000),
            created_at,
            json.dumps([{"rule_id": rule_id, "dimension": rule_id}]),
        ),
    )
    conn.commit()
    conn.close()


# ── Test 1: Empty DB → empty report ──────────────────────────────────

def test_empty_db_empty_report():
    """Empty CIEU DB + rules → all rules classified as DEAD, no error."""
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        fg = _make_fg_yaml(tmp, ["rule_alpha", "rule_beta"])

        report = scan_rule_liveness(db, fg)

        assert report.error is None
        assert report.total_rules == 2
        assert report.counts["DEAD"] == 2
        assert report.counts["LIVE"] == 0
        assert report.counts["DORMANT"] == 0
        assert report.counts["ZOMBIE"] == 0


# ── Test 2: Injected events → correct classification ─────────────────

def test_classification_with_fake_events():
    """
    Three rules defined:
      - rule_live:    event 1 day ago → LIVE
      - rule_dormant: event 15 days ago → DORMANT
      - rule_dead:    no events → DEAD
    """
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        fg = _make_fg_yaml(tmp, ["rule_live", "rule_dormant", "rule_dead"])
        now = time.time()

        # rule_live: fired 1 day ago
        _insert_event(db, "rule_live", now - 1 * 86400)
        # rule_dormant: fired 15 days ago (within 30d but outside 7d)
        _insert_event(db, "rule_dormant", now - 15 * 86400)
        # rule_dead: no events

        report = scan_rule_liveness(db, fg)

        assert report.error is None
        assert report.total_rules == 3

        by_id = {r.rule_id: r for r in report.rules}
        assert by_id["rule_live"].category == "LIVE"
        assert by_id["rule_live"].fires_7d >= 1
        assert by_id["rule_dormant"].category == "DORMANT"
        assert by_id["rule_dormant"].fires_30d >= 1
        assert by_id["rule_dormant"].fires_7d == 0
        assert by_id["rule_dead"].category == "DEAD"
        assert by_id["rule_dead"].fires_7d == 0
        assert by_id["rule_dead"].fires_30d == 0


# ── Test 3: Markdown output contains counts summary ──────────────────

def test_markdown_output_contains_summary():
    """write_markdown_report produces markdown with Summary line and table."""
    with tempfile.TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        fg = _make_fg_yaml(tmp, ["rule_a", "rule_b"])
        now = time.time()
        _insert_event(db, "rule_a", now - 2 * 86400)  # LIVE

        report = scan_rule_liveness(db, fg)
        out_path = str(Path(tmp) / "report.md")
        result_path = write_markdown_report(report, out_path)

        assert Path(result_path).exists()
        content = Path(result_path).read_text(encoding="utf-8")

        # Must contain summary line with counts
        assert "**Summary**:" in content
        assert "LIVE=" in content
        assert "DEAD=" in content
        assert "DORMANT=" in content
        assert "ZOMBIE=" in content
        assert "total=" in content
        # Must contain markdown table
        assert "| rule_id |" in content
        assert "| `rule_a` |" in content
        assert "| `rule_b` |" in content
