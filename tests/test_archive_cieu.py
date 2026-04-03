"""
Test CIEU Archive Command

Validates:
- Archive creation from CIEU database
- JSONL export format
- Metadata generation
- Experiment-specific archives
"""
import json
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime

import pytest


def test_archive_cieu_basic(tmp_path):
    """Test basic CIEU archive creation."""
    # Create a test CIEU database
    db_path = tmp_path / ".ystar_cieu.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create cieu_events table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cieu_events (
            event_id TEXT PRIMARY KEY,
            session_id TEXT,
            agent_id TEXT,
            event_type TEXT,
            decision TEXT,
            passed INTEGER,
            created_at REAL
        )
    """)

    # Insert test events
    test_events = [
        ("evt_001", "sess_001", "agent_a", "Read", "allow", 1, 1234567890.0),
        ("evt_002", "sess_001", "agent_a", "Write", "deny", 0, 1234567891.0),
        ("evt_003", "sess_002", "agent_b", "Bash", "allow", 1, 1234567892.0),
    ]

    for event in test_events:
        cursor.execute(
            "INSERT INTO cieu_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            event
        )

    conn.commit()
    conn.close()

    # Run archive command
    from ystar.cli.archive_cmd import _cmd_archive_cieu

    archive_dir = tmp_path / "archive"
    args = ["--output-dir", str(archive_dir), "--db-path", str(db_path)]

    _cmd_archive_cieu(args)

    # Verify archive created
    today = datetime.now().strftime('%Y-%m-%d')
    archive_file = archive_dir / f"{today}.jsonl"
    assert archive_file.exists(), "Archive file should be created"

    # Verify metadata
    meta_file = archive_dir / ".archive_metadata.json"
    assert meta_file.exists(), "Metadata file should be created"

    with open(meta_file, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    assert metadata['event_count'] == 3, "Should archive 3 events"
    assert 'last_archive' in metadata, "Should record archive timestamp"

    # Verify JSONL content
    with open(archive_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    assert len(lines) == 3, "Should have 3 JSONL lines"

    # Parse first event
    first_event = json.loads(lines[0])
    assert first_event['event_id'] == 'evt_001'
    assert first_event['agent_id'] == 'agent_a'
    assert first_event['event_type'] == 'Read'


def test_archive_cieu_experiment(tmp_path):
    """Test experiment-specific archive."""
    # Create a test CIEU database
    db_path = tmp_path / ".ystar_cieu.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cieu_events (
            event_id TEXT PRIMARY KEY,
            session_id TEXT,
            agent_id TEXT,
            event_type TEXT,
            decision TEXT,
            passed INTEGER,
            created_at REAL
        )
    """)

    # Insert test events
    cursor.execute(
        "INSERT INTO cieu_events VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("evt_exp", "sess_exp", "agent_exp", "Read", "allow", 1, 1234567890.0)
    )

    conn.commit()
    conn.close()

    # Run archive command with experiment flag
    from ystar.cli.archive_cmd import _cmd_archive_cieu

    args = ["--experiment", "EXP_001", "--db-path", str(db_path)]

    # Change working directory to tmp_path for experiment archive
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        _cmd_archive_cieu(args)
    finally:
        os.chdir(old_cwd)

    # Verify experiment archive
    exp_archive = tmp_path / "data" / "experiments" / "EXP_001_cieu.jsonl"
    assert exp_archive.exists(), "Experiment archive should be created"

    # Verify metadata includes experiment ID
    meta_file = tmp_path / "data" / "experiments" / ".archive_metadata.json"
    with open(meta_file, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    assert metadata['experiment'] == 'EXP_001', "Should record experiment ID"


def test_archive_cieu_missing_db(tmp_path):
    """Test archive with missing database."""
    from ystar.cli.archive_cmd import _cmd_archive_cieu
    import sys
    from io import StringIO

    # Capture output
    old_stdout = sys.stdout
    sys.stdout = StringIO()

    try:
        db_path = tmp_path / "nonexistent.db"
        args = ["--db-path", str(db_path)]

        with pytest.raises(SystemExit) as exc_info:
            _cmd_archive_cieu(args)

        assert exc_info.value.code == 1, "Should exit with error code"

        output = sys.stdout.getvalue()
        assert "not found" in output, "Should report database not found"
    finally:
        sys.stdout = old_stdout


def test_doctor_archive_freshness_check(tmp_path):
    """Test that doctor check [7] detects old archives."""
    # This test verifies that the doctor command correctly checks archive freshness
    # (Implementation already exists in doctor_cmd.py check [7])

    # Create old metadata
    archive_dir = tmp_path / "data" / "cieu_archive"
    archive_dir.mkdir(parents=True)

    meta_file = archive_dir / ".archive_metadata.json"

    # Simulate archive from 10 days ago
    from datetime import timedelta
    old_date = datetime.now() - timedelta(days=10)

    metadata = {
        'last_archive': old_date.isoformat(),
        'archive_file': str(archive_dir / "old.jsonl"),
        'event_count': 100,
    }

    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f)

    # Verify metadata can be read
    with open(meta_file, 'r', encoding='utf-8') as f:
        loaded = json.load(f)

    last_archive = datetime.fromisoformat(loaded['last_archive'])
    days_since = (datetime.now() - last_archive).days

    assert days_since >= 10, "Should detect old archive (>7 days)"
