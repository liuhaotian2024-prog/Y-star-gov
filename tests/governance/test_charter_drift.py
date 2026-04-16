"""
tests/governance/test_charter_drift.py
======================================

Charter drift detection tests (I1 Priority, Board 2026-04-16 K9-RT Discussion).

SCOPE: Validate charter_drift.detect_charter_drift() helper detects mid-session
       charter file modifications correctly.

COVERAGE:
1. No drift (clean baseline)
2. Single file drifted (1 event)
3. Multiple files drifted (N events)
4. session_start_ts in future (no drift)
5. Missing reference path (graceful skip)

Author: Maya Patel (eng-governance)
Date: 2026-04-16
"""
import time
import tempfile
import shutil
from pathlib import Path

import pytest

from ystar.governance.charter_drift import detect_charter_drift


@pytest.fixture
def temp_workspace():
    """Create temporary workspace with charter file structure."""
    workspace = Path(tempfile.mkdtemp())

    # Create charter file structure
    (workspace / "AGENTS.md").write_text("# AGENTS charter v1.0\n")
    (workspace / "CLAUDE.md").write_text("# CLAUDE charter v1.0\n")

    governance_dir = workspace / "governance"
    governance_dir.mkdir()
    (governance_dir / "WORKING_STYLE.md").write_text("# Working style v1.0\n")
    (governance_dir / "BOARD_CHARTER_AMENDMENTS.md").write_text("# Amendments v1.0\n")

    agents_dir = workspace / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "ceo.md").write_text("# CEO agent v1.0\n")
    (agents_dir / "cto.md").write_text("# CTO agent v1.0\n")

    # Wait 100ms to ensure mtime > creation time
    time.sleep(0.1)

    yield workspace

    # Cleanup
    shutil.rmtree(workspace)


class TestCharterDriftDetection:
    """Charter drift detection test suite (I1 Priority)."""

    def test_no_drift_clean_baseline(self, temp_workspace):
        """No drift when all files created before session start."""
        # Session started now, all files created earlier (in fixture)
        session_start_ts = time.time()

        drifted = detect_charter_drift(
            reference_paths=["AGENTS.md", "CLAUDE.md", "governance/*.md", ".claude/agents/*.md"],
            session_start_ts=session_start_ts,
            workspace_root=temp_workspace
        )

        assert drifted == [], f"Expected no drift for clean baseline, got: {drifted}"

    def test_single_file_drifted(self, temp_workspace):
        """Detect single charter file modified after session start."""
        session_start_ts = time.time()

        # Modify AGENTS.md after session start
        time.sleep(0.1)
        (temp_workspace / "AGENTS.md").write_text("# AGENTS charter v2.0 — MODIFIED\n")

        drifted = detect_charter_drift(
            reference_paths=["AGENTS.md"],
            session_start_ts=session_start_ts,
            workspace_root=temp_workspace
        )

        assert len(drifted) == 1, f"Expected 1 drifted file, got {len(drifted)}: {drifted}"

        drift_event = drifted[0]
        assert drift_event["path"] == "AGENTS.md"
        assert drift_event["session_start_ts"] == session_start_ts
        assert drift_event["drift_seconds"] > 0, "drift_seconds should be positive"
        assert drift_event["current_mtime"] > session_start_ts
        assert "diff_summary" in drift_event

    def test_multiple_files_drifted(self, temp_workspace):
        """Detect multiple charter files drifted (N events)."""
        session_start_ts = time.time()

        # Modify multiple files after session start
        time.sleep(0.1)
        (temp_workspace / "AGENTS.md").write_text("# AGENTS v2.0\n")
        (temp_workspace / "CLAUDE.md").write_text("# CLAUDE v2.0\n")
        (temp_workspace / "governance" / "WORKING_STYLE.md").write_text("# WORKING_STYLE v2.0\n")

        drifted = detect_charter_drift(
            reference_paths=["AGENTS.md", "CLAUDE.md", "governance/*.md"],
            session_start_ts=session_start_ts,
            workspace_root=temp_workspace
        )

        assert len(drifted) == 3, f"Expected 3 drifted files, got {len(drifted)}: {drifted}"

        drifted_paths = {event["path"] for event in drifted}
        expected_paths = {"AGENTS.md", "CLAUDE.md", "governance/WORKING_STYLE.md"}
        assert drifted_paths == expected_paths, \
            f"Expected drifted paths {expected_paths}, got {drifted_paths}"

    def test_session_start_in_future_no_drift(self, temp_workspace):
        """session_start_ts in future should detect no drift."""
        # Modify file now
        (temp_workspace / "AGENTS.md").write_text("# AGENTS v2.0\n")

        # Session "started" 10 seconds in the future
        session_start_ts = time.time() + 10.0

        drifted = detect_charter_drift(
            reference_paths=["AGENTS.md"],
            session_start_ts=session_start_ts,
            workspace_root=temp_workspace
        )

        assert drifted == [], \
            f"Expected no drift when session_start_ts in future, got: {drifted}"

    def test_missing_reference_path_graceful_skip(self, temp_workspace):
        """Missing reference path should be gracefully skipped (no exception)."""
        session_start_ts = time.time()

        # Reference nonexistent file
        drifted = detect_charter_drift(
            reference_paths=["NONEXISTENT.md"],
            session_start_ts=session_start_ts,
            workspace_root=temp_workspace
        )

        assert drifted == [], \
            f"Expected graceful skip for missing path, got: {drifted}"

    def test_default_reference_paths(self, temp_workspace):
        """Test default reference_paths coverage (AGENTS.md, CLAUDE.md, governance/*.md, .claude/agents/*.md)."""
        session_start_ts = time.time()

        # Modify files in all default scope categories
        time.sleep(0.1)
        (temp_workspace / "AGENTS.md").write_text("# AGENTS v2.0\n")
        (temp_workspace / "governance" / "WORKING_STYLE.md").write_text("# WORKING_STYLE v2.0\n")
        (temp_workspace / ".claude" / "agents" / "ceo.md").write_text("# CEO v2.0\n")

        # Call without reference_paths (use default)
        drifted = detect_charter_drift(
            session_start_ts=session_start_ts,
            workspace_root=temp_workspace
        )

        assert len(drifted) == 3, f"Expected 3 drifted files in default scope, got {len(drifted)}"

        drifted_paths = {event["path"] for event in drifted}
        assert "AGENTS.md" in drifted_paths
        assert "governance/WORKING_STYLE.md" in drifted_paths
        assert ".claude/agents/ceo.md" in drifted_paths

    def test_drift_event_structure(self, temp_workspace):
        """Validate drift event dictionary structure."""
        session_start_ts = time.time()

        time.sleep(0.1)
        (temp_workspace / "AGENTS.md").write_text("# AGENTS v2.0\n")

        drifted = detect_charter_drift(
            reference_paths=["AGENTS.md"],
            session_start_ts=session_start_ts,
            workspace_root=temp_workspace
        )

        assert len(drifted) == 1
        event = drifted[0]

        # Required fields
        required_fields = {
            "path", "previous_mtime", "current_mtime",
            "session_start_ts", "drift_seconds", "diff_summary"
        }
        assert set(event.keys()) == required_fields, \
            f"Event missing required fields. Expected {required_fields}, got {set(event.keys())}"

        # Type checks
        assert isinstance(event["path"], str)
        assert isinstance(event["previous_mtime"], float)
        assert isinstance(event["current_mtime"], float)
        assert isinstance(event["session_start_ts"], float)
        assert isinstance(event["drift_seconds"], float)
        assert isinstance(event["diff_summary"], str)

        # Value sanity
        assert event["drift_seconds"] > 0
        assert event["current_mtime"] == event["previous_mtime"]  # Aliases
        assert event["current_mtime"] > event["session_start_ts"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
