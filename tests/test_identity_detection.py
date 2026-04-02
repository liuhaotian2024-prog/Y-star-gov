"""
tests/test_identity_detection.py  —  Agent Identity Detection Integration Tests
==================================================================================

Covers all 5 priority levels in _detect_agent_id():
  1. hook_payload["agent_id"]
  2. YSTAR_AGENT_ID env var
  3. CLAUDE_AGENT_NAME env var
  4. .ystar_active_agent file
  5. Fallback to "agent"

Critical for autonomous/cron contexts where CLAUDE_AGENT_NAME may not be set.
"""
import os
import tempfile
from pathlib import Path

import pytest

from ystar.adapters.identity_detector import _detect_agent_id


class TestAgentIdentityDetection:
    """Test all identity detection priority levels."""

    def test_priority_1_payload(self):
        """Priority 1: hook_payload['agent_id'] should win."""
        result = _detect_agent_id({"agent_id": "cto"})
        assert result == "cto"

    def test_priority_2_env_ystar(self, monkeypatch):
        """Priority 2: YSTAR_AGENT_ID env var."""
        monkeypatch.setenv("YSTAR_AGENT_ID", "test_agent")
        result = _detect_agent_id({})
        assert result == "test_agent"

    def test_priority_3_env_claude(self, monkeypatch, tmp_path):
        """Priority 3: CLAUDE_AGENT_NAME env var (Claude Code standard)."""
        # Clear YSTAR_AGENT_ID to ensure CLAUDE_AGENT_NAME is checked
        monkeypatch.delenv("YSTAR_AGENT_ID", raising=False)
        monkeypatch.setenv("CLAUDE_AGENT_NAME", "claude_agent")
        # Change to temp directory to avoid reading .ystar_active_agent from other repos
        monkeypatch.chdir(tmp_path)
        result = _detect_agent_id({})
        assert result == "claude_agent"

    def test_priority_4_marker_file(self, monkeypatch, tmp_path):
        """Priority 4: .ystar_active_agent file."""
        # Clear env vars so they don't interfere
        monkeypatch.delenv("YSTAR_AGENT_ID", raising=False)
        monkeypatch.delenv("CLAUDE_AGENT_NAME", raising=False)

        # Change to temp directory and create marker file
        marker = tmp_path / ".ystar_active_agent"
        marker.write_text("file_agent", encoding="utf-8")

        monkeypatch.chdir(tmp_path)
        result = _detect_agent_id({})
        assert result == "file_agent"

    def test_priority_5_fallback(self, monkeypatch, tmp_path):
        """Priority 5: Fallback to 'agent' when all else fails."""
        # Clear all hints
        monkeypatch.delenv("YSTAR_AGENT_ID", raising=False)
        monkeypatch.delenv("CLAUDE_AGENT_NAME", raising=False)
        monkeypatch.chdir(tmp_path)  # No marker file

        result = _detect_agent_id({})
        assert result == "agent"

    def test_env_priority_order(self, monkeypatch, tmp_path):
        """YSTAR_AGENT_ID should beat CLAUDE_AGENT_NAME."""
        monkeypatch.setenv("YSTAR_AGENT_ID", "ystar_wins")
        monkeypatch.setenv("CLAUDE_AGENT_NAME", "claude_loses")

        result = _detect_agent_id({})
        assert result == "ystar_wins"

    def test_payload_beats_env(self, monkeypatch):
        """Payload should beat all env vars."""
        monkeypatch.setenv("YSTAR_AGENT_ID", "env_loses")

        result = _detect_agent_id({"agent_id": "payload_wins"})
        assert result == "payload_wins"

    def test_empty_payload_agent_id_ignored(self, monkeypatch):
        """Empty string in payload should fall through to next priority."""
        monkeypatch.setenv("YSTAR_AGENT_ID", "env_wins")

        result = _detect_agent_id({"agent_id": ""})
        assert result == "env_wins"

    def test_agent_string_in_payload_falls_through(self, monkeypatch):
        """'agent' literal in payload should fall through (line 49 check)."""
        monkeypatch.setenv("YSTAR_AGENT_ID", "env_wins")

        result = _detect_agent_id({"agent_id": "agent"})
        assert result == "env_wins"

    def test_marker_file_read_error_falls_back(self, monkeypatch, tmp_path):
        """If marker file exists but can't be read, fall back to 'agent'."""
        monkeypatch.delenv("YSTAR_AGENT_ID", raising=False)
        monkeypatch.delenv("CLAUDE_AGENT_NAME", raising=False)

        # Create unreadable file (empty/corrupted)
        marker = tmp_path / ".ystar_active_agent"
        marker.write_bytes(b"\xff\xfe")  # Invalid UTF-8

        monkeypatch.chdir(tmp_path)
        result = _detect_agent_id({})
        # Should fall back to "agent" due to read error
        assert result == "agent"

    def test_cross_repo_identity_isolation(self, monkeypatch, tmp_path):
        """
        Regression test: .ystar_active_agent in one repo should not leak
        to another repo's operations.

        Simulates the ystar-company/.ystar_active_agent = "ystar-cfo" case
        when operating in Y-star-gov repo.
        """
        # Set up "company" repo with marker
        company_repo = tmp_path / "ystar-company"
        company_repo.mkdir()
        (company_repo / ".ystar_active_agent").write_text("ystar-cfo", encoding="utf-8")

        # Set up "gov" repo without marker
        gov_repo = tmp_path / "Y-star-gov"
        gov_repo.mkdir()

        # Clear env vars
        monkeypatch.delenv("YSTAR_AGENT_ID", raising=False)
        monkeypatch.delenv("CLAUDE_AGENT_NAME", raising=False)

        # Operating in gov repo should fall back to "agent"
        monkeypatch.chdir(gov_repo)
        result = _detect_agent_id({})
        assert result == "agent", "Should not leak identity from other repo"
