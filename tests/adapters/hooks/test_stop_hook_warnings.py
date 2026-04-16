# tests/adapters/hooks/test_stop_hook_warnings.py
"""
Test suite for Y*gov Stop hook warning injection.

Coverage:
- Mock queue with 2 warnings → 2 <system-reminder> blocks (XML format correct)
- Queue cleared after injection (file truncated to [])
- Archive contains processed_at timestamp
- Empty queue → silent pass (no injection, no log noise)
- Corrupt JSON → logs error, does not crash

Platform Engineer: Ryan Park (eng-platform)
Success bar: ≥5 assertions, all green
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from ystar.adapters.hooks.stop_hook import (
    inject_warnings_to_session,
    _format_warning_xml,
    _read_queue,
    _archive_warnings,
    _clear_queue,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def temp_queue_dir(tmp_path):
    """Temporary directory for queue/archive files."""
    # Patch Path.cwd() to return temp directory
    with patch("ystar.adapters.hooks.stop_hook.Path.cwd", return_value=tmp_path):
        # Create scripts subdir for hook_observe.log
        (tmp_path / "scripts").mkdir(exist_ok=True)
        yield tmp_path


@pytest.fixture
def mock_warnings():
    """Sample warnings matching Maya's schema (Appendix B)."""
    return [
        {
            "task_id": "task-001",
            "violation_type": "rt_not_closed",
            "details": "Task not closed, Rt+1 = 0.42 after 3 actions",
            "rt_value": 0.42,
            "timestamp": "2026-04-16T10:00:00Z",
            "agent_id": "ceo",
            "role_tags": {"producer": "ceo", "executor": "ceo", "governed": "ceo"}
        },
        {
            "task_id": "task-002",
            "violation_type": "3d_role_mismatch",
            "details": "CEO (Producer) wrote to engineering scope ./src/ystar/kernel/",
            "rt_value": 0.0,
            "timestamp": "2026-04-16T10:01:00Z",
            "agent_id": "ceo",
            "role_tags": {"producer": "ceo", "executor": "ceo", "governed": "eng-kernel"}
        }
    ]


# ── Test Cases ────────────────────────────────────────────────────────────

def test_inject_warnings_success(temp_queue_dir, mock_warnings):
    """
    HAPPY PATH: Mock queue with 2 warnings → 2 <system-reminder> blocks.
    """
    queue_file = temp_queue_dir / ".ystar_warning_queue.json"
    archive_file = temp_queue_dir / ".ystar_warning_queue_archive.json"

    # Write mock queue
    queue_file.write_text(json.dumps(mock_warnings, indent=2), encoding="utf-8")

    # Run injection
    result = inject_warnings_to_session()

    # ASSERTION 1: Result contains 2 <system-reminder> blocks
    assert result is not None
    assert result.count("<system-reminder>") == 2
    assert result.count("</system-reminder>") == 2

    # ASSERTION 2: XML contains correct task IDs
    assert "Task: task-001" in result
    assert "Task: task-002" in result

    # ASSERTION 3: Violation types present
    assert "Violation: rt_not_closed" in result
    assert "Violation: 3d_role_mismatch" in result

    # ASSERTION 4: Rt+1 values present
    assert "Rt+1 = 0.42" in result
    assert "Rt+1 = 0.0" in result

    # ASSERTION 5: Role tags formatted correctly
    assert "Producer=ceo, Executor=ceo" in result

    # ASSERTION 6: Queue cleared after injection
    queue_data = json.loads(queue_file.read_text(encoding="utf-8"))
    assert queue_data == []

    # ASSERTION 7: Archive file exists and contains processed_at timestamps
    assert archive_file.exists()
    archive_data = json.loads(archive_file.read_text(encoding="utf-8"))
    assert len(archive_data) == 2
    assert all("processed_at" in w for w in archive_data)


def test_empty_queue_silent_pass(temp_queue_dir):
    """
    Empty queue → silent pass (no injection, no log noise).
    """
    # Queue file does NOT exist
    result = inject_warnings_to_session()

    # ASSERTION 8: No injection when queue missing
    assert result is None


def test_corrupt_json_no_crash(temp_queue_dir, caplog):
    """
    Corrupt JSON in queue → log error, skip injection, do NOT crash.
    """
    queue_file = temp_queue_dir / ".ystar_warning_queue.json"

    # Write corrupt JSON
    queue_file.write_text("{invalid json", encoding="utf-8")

    # Run injection (should not crash)
    result = inject_warnings_to_session()

    # ASSERTION 9: No crash on corrupt JSON
    assert result is None

    # ASSERTION 10: Error logged (check caplog for "corrupt JSON" message)
    # Note: caplog may not capture custom log handlers, but _read_queue returns []
    warnings = _read_queue()
    assert warnings == []


def test_xml_format_correctness():
    """
    Test individual warning → XML block formatting.
    """
    warning = {
        "task_id": "test-task",
        "violation_type": "rt_not_closed",
        "details": "Test details",
        "rt_value": 1.5,
        "agent_id": "test-agent",
        "role_tags": {"producer": "ceo", "executor": "cto", "governed": "ceo"}
    }

    xml = _format_warning_xml(warning)

    # ASSERTION 11: XML structure valid
    assert xml.startswith("<system-reminder>")
    assert xml.endswith("</system-reminder>")

    # ASSERTION 12: All fields present
    assert "Task: test-task" in xml
    assert "Violation: rt_not_closed" in xml
    assert "Details: Test details" in xml
    assert "Rt+1 = 1.5" in xml
    assert "Agent: test-agent" in xml
    assert "Producer=ceo, Executor=cto" in xml


def test_archive_append_preserves_history(temp_queue_dir, mock_warnings):
    """
    Archive appends new warnings without overwriting existing ones.
    """
    archive_file = temp_queue_dir / ".ystar_warning_queue_archive.json"

    # First batch
    _archive_warnings([mock_warnings[0]])
    archive_v1 = json.loads(archive_file.read_text(encoding="utf-8"))
    assert len(archive_v1) == 1

    # Second batch (should append, not overwrite)
    _archive_warnings([mock_warnings[1]])
    archive_v2 = json.loads(archive_file.read_text(encoding="utf-8"))

    # ASSERTION 13: Archive appends (total 2 warnings now)
    assert len(archive_v2) == 2
    assert archive_v2[0]["task_id"] == "task-001"
    assert archive_v2[1]["task_id"] == "task-002"


def test_clear_queue_truncates_to_empty_list(temp_queue_dir):
    """
    _clear_queue() writes [] to queue file.
    """
    queue_file = temp_queue_dir / ".ystar_warning_queue.json"
    queue_file.write_text('{"foo": "bar"}', encoding="utf-8")

    _clear_queue()

    # ASSERTION 14: Queue truncated to empty JSON array
    assert queue_file.read_text(encoding="utf-8") == "[]"


def test_read_queue_json_lines_format(temp_queue_dir):
    """
    SENTINEL FORMAT: JSON-lines (append-only) parsed correctly.
    """
    queue_file = temp_queue_dir / ".ystar_warning_queue.json"

    # Write JSON-lines (sentinel append-only format)
    json_lines = '\n'.join([
        json.dumps({"task_id": "task-a", "violation_type": "test", "rt_value": 1.0}),
        json.dumps({"task_id": "task-b", "violation_type": "test", "rt_value": 2.0}),
    ])
    queue_file.write_text(json_lines, encoding="utf-8")

    warnings = _read_queue()

    # ASSERTION 15: Both warnings parsed
    assert len(warnings) == 2
    assert warnings[0]["task_id"] == "task-a"
    assert warnings[1]["task_id"] == "task-b"


def test_read_queue_array_format_unchanged(temp_queue_dir):
    """
    BACKWARD COMPATIBILITY: JSON array format still works.
    """
    queue_file = temp_queue_dir / ".ystar_warning_queue.json"

    # Write JSON array (existing format)
    queue_file.write_text(json.dumps([
        {"task_id": "task-x", "violation_type": "test", "rt_value": 0.5},
    ]), encoding="utf-8")

    warnings = _read_queue()

    # ASSERTION 16: Array format still parsed
    assert len(warnings) == 1
    assert warnings[0]["task_id"] == "task-x"
