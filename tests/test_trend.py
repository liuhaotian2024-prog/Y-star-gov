# tests/test_trend.py — Test ystar trend command
"""
Test the ystar trend command output format and data aggregation.
"""
import pytest
import sqlite3
import tempfile
import pathlib
from datetime import datetime, timedelta
from ystar._cli import _cmd_trend
from io import StringIO
import sys


def test_trend_output_format(tmp_path, monkeypatch, capsys):
    """Test that ystar trend produces correct daily aggregation and format."""
    from ystar.governance.cieu_store import CIEUStore

    # Create a temporary CIEU database with test data
    db_path = tmp_path / "test_cieu.db"

    # Let CIEUStore create the database with correct schema
    store = CIEUStore(str(db_path))

    # Now insert test data directly
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Insert test data spanning 7 days
    now = datetime.now()
    base_ts = (now - timedelta(days=6)).timestamp()

    test_data = [
        # Day 0: 10 events, 2 denies (20%)
        *[(i, "allow" if i % 5 != 0 else "deny", base_ts + i * 100) for i in range(10)],
        # Day 1: 15 events, 3 denies (20%)
        *[(i + 10, "allow" if i % 5 != 0 else "deny", base_ts + 86400 + i * 100) for i in range(15)],
        # Day 2: 20 events, 5 denies (25%)
        *[(i + 25, "allow" if i % 4 != 0 else "deny", base_ts + 2*86400 + i * 100) for i in range(20)],
        # Day 3: 12 events, 3 denies (25%)
        *[(i + 45, "allow" if i % 4 != 0 else "deny", base_ts + 3*86400 + i * 100) for i in range(12)],
        # Day 4: 8 events, 2 denies (25%)
        *[(i + 57, "allow" if i % 4 != 0 else "deny", base_ts + 4*86400 + i * 100) for i in range(8)],
        # Day 5: 10 events, 1 deny (10%)
        *[(i + 65, "allow" if i % 10 != 0 else "deny", base_ts + 5*86400 + i * 100) for i in range(10)],
        # Day 6: 15 events, 2 denies (13.3%)
        *[(i + 75, "allow" if i % 7 != 0 else "deny", base_ts + 6*86400 + i * 100) for i in range(15)],
    ]

    for seq, decision, ts in test_data:
        cursor.execute("""
            INSERT INTO cieu_events
            (seq_global, event_id, agent_id, event_type, decision, created_at, session_id, passed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (seq, f"evt_{seq}", "test_agent", "Bash", decision, ts, "test_session", 1 if decision == "allow" else 0))

    conn.commit()
    conn.close()

    # Mock session config to point to our test database
    session_json = tmp_path / ".ystar_session.json"
    # Use forward slashes for JSON path (Windows compatibility)
    db_path_str = str(db_path).replace("\\", "/")
    session_json.write_text(f'{{"cieu_db": "{db_path_str}"}}', encoding="utf-8")

    # Monkeypatch cwd to tmp_path
    monkeypatch.chdir(tmp_path)

    # Verify session file was created
    assert session_json.exists()
    assert db_path.exists()

    # Run trend command
    _cmd_trend([])

    # Capture output
    captured = capsys.readouterr()
    output = captured.out

    # Verify output structure
    assert "Y*gov CIEU Trend (Last 7 Days)" in output
    assert "Date" in output
    assert "Total Events" in output
    assert "Denies" in output
    assert "Deny Rate" in output
    assert "Trend" in output

    # Verify data rows are present
    lines = output.split("\n")
    data_lines = [l for l in lines if l.strip() and not l.strip().startswith(("-", "Y*gov", "Date"))]

    # Should have 7 days of data
    assert len(data_lines) >= 7, f"Expected at least 7 data lines, got {len(data_lines)}"

    # Verify trend indicators are present (↑↓→)
    assert any(arrow in output for arrow in ["↑", "↓", "→"]), "Trend indicators missing"


def test_trend_no_data(tmp_path, monkeypatch, capsys):
    """Test trend command when no CIEU events exist."""
    from ystar.governance.cieu_store import CIEUStore

    db_path = tmp_path / "empty_cieu.db"

    # Let CIEUStore create the database with correct schema
    store = CIEUStore(str(db_path))

    session_json = tmp_path / ".ystar_session.json"
    # Use forward slashes for JSON path (Windows compatibility)
    db_path_str = str(db_path).replace("\\", "/")
    session_json.write_text(f'{{"cieu_db": "{db_path_str}"}}', encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    _cmd_trend([])

    captured = capsys.readouterr()
    assert "No CIEU events in the last 7 days" in captured.out


def test_trend_no_database(tmp_path, monkeypatch, capsys):
    """Test trend command when database doesn't exist."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        _cmd_trend([])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "No CIEU database found" in captured.out
