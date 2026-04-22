"""
Tests for CZL-P1-b identity_detector.py fixes:
  1. Absolute paths (no cwd dependency) for marker file resolution
  2. Priority 1.5 filter: _map_agent_type returning "agent" does NOT early return
  3. _map_agent_type unknown agent fallback logs warning

These tests use monkeypatching to avoid relying on filesystem state.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ystar.adapters.identity_detector import (
    _detect_agent_id,
    _map_agent_type,
    _load_session_config,
    _AGENT_TYPE_MAP,
)


# ── Test 1: _map_agent_type unknown agent fallback logs warning ─────────────

class TestMapAgentTypeWarning:
    def test_known_agent_no_warning(self, caplog):
        """Known agent types should NOT produce warnings."""
        with caplog.at_level(logging.WARNING, logger="ystar.identity"):
            result = _map_agent_type("Agent-CEO")
        assert result == "ceo"
        assert "Unknown agent_type" not in caplog.text

    def test_unknown_agent_logs_warning(self, caplog):
        """Unknown agent types should produce a warning log."""
        with caplog.at_level(logging.WARNING, logger="ystar.identity"):
            result = _map_agent_type("SomeRandomAgent")
        assert result == "SomeRandomAgent"
        assert "Unknown agent_type 'SomeRandomAgent'" in caplog.text

    def test_legacy_known_no_warning(self, caplog):
        """Legacy format like 'eng-kernel' should NOT produce warnings."""
        with caplog.at_level(logging.WARNING, logger="ystar.identity"):
            result = _map_agent_type("eng-kernel")
        assert result == "eng-kernel"
        assert "Unknown agent_type" not in caplog.text


# ── Test 2: Priority 1.5 filter — "agent" mapped result continues detection ──

class TestPriority15AgentFilter:
    def test_agent_type_agent_does_not_early_return(self, monkeypatch):
        """
        When payload.agent_type maps to 'agent' (generic),
        detection should continue to env vars / session / marker file.
        """
        monkeypatch.setenv("YSTAR_AGENT_ID", "ceo")
        payload = {"agent_type": "agent"}
        result = _detect_agent_id(payload)
        assert result == "ceo", (
            "Expected priority 2 (YSTAR_AGENT_ID=ceo) to win over "
            "priority 1.5 generic 'agent' mapping"
        )

    def test_agent_type_valid_still_returns(self, monkeypatch):
        """
        When payload.agent_type maps to a specific ID (not 'agent'),
        it should still early return at priority 1.5.
        """
        monkeypatch.setenv("YSTAR_AGENT_ID", "cto")
        payload = {"agent_type": "Agent-CEO"}
        result = _detect_agent_id(payload)
        assert result == "ceo", (
            "Expected priority 1.5 (agent_type=Agent-CEO -> ceo) to win "
            "over priority 2 (YSTAR_AGENT_ID=cto)"
        )

    def test_unknown_agent_type_continues_to_env(self, monkeypatch):
        """
        When payload.agent_type is unknown and maps to itself,
        if the mapped value looks like a real agent name (not 'agent'),
        it should still return it.
        """
        monkeypatch.delenv("YSTAR_AGENT_ID", raising=False)
        monkeypatch.delenv("CLAUDE_AGENT_NAME", raising=False)
        payload = {"agent_type": "custom-agent-name"}
        result = _detect_agent_id(payload)
        # 'custom-agent-name' is not 'agent', so it should early return
        assert result == "custom-agent-name"

    def test_agent_type_empty_string_skips(self, monkeypatch):
        """Empty agent_type should skip priority 1.5 entirely."""
        monkeypatch.setenv("YSTAR_AGENT_ID", "eng-kernel")
        payload = {"agent_type": ""}
        result = _detect_agent_id(payload)
        assert result == "eng-kernel"


# ── Test 3: Absolute paths in marker file resolution ──────────────────────────

class TestAbsolutePathMarkerResolution:
    def test_marker_uses_ystar_repo_root_env(self, monkeypatch, tmp_path):
        """
        When YSTAR_REPO_ROOT is set, marker file should be resolved
        using that absolute path, not os.getcwd().
        """
        # Set up a marker file at the env-specified root
        marker = tmp_path / ".ystar_active_agent"
        marker.write_text("ceo")

        monkeypatch.setenv("YSTAR_REPO_ROOT", str(tmp_path))
        # Clear all higher-priority sources
        monkeypatch.delenv("YSTAR_AGENT_ID", raising=False)
        monkeypatch.delenv("CLAUDE_AGENT_NAME", raising=False)

        # Mock session config to fail (so we fall through to marker file)
        with patch("ystar.adapters.identity_detector.Path") as MockPath:
            # We need Path to work for the marker_path candidates
            # but the session import should fail
            MockPath.side_effect = Path  # Use real Path
            with patch("ystar.session.current_agent", side_effect=Exception("no session")):
                payload = {}
                result = _detect_agent_id(payload)

        assert result == "ceo", f"Expected 'ceo' from marker file at {marker}, got '{result}'"

    def test_marker_with_generic_agent_continues(self, monkeypatch, tmp_path):
        """
        CZL-P1-b + CZL-ARCH-1: Even if marker file contains value that maps
        to the "generic/unknown" token, detection should skip it and fall back
        to the read-only "guest" identity (not blanket-deny "agent").
        """
        marker = tmp_path / ".ystar_active_agent"
        marker.write_text("agent")

        monkeypatch.setenv("YSTAR_REPO_ROOT", str(tmp_path))
        monkeypatch.delenv("YSTAR_AGENT_ID", raising=False)
        monkeypatch.delenv("CLAUDE_AGENT_NAME", raising=False)

        with patch("ystar.session.current_agent", side_effect=Exception("no session")):
            payload = {}
            result = _detect_agent_id(payload)

        # CZL-ARCH-1: final fallback is 'guest' (read-only), not 'agent' (blanket-deny)
        assert result == "guest"


# ── Test 4: _load_session_config uses YSTAR_REPO_ROOT, not cwd ────────────

class TestLoadSessionConfigAbsolutePath:
    def test_uses_repo_root_env(self, monkeypatch, tmp_path):
        """_load_session_config should check YSTAR_REPO_ROOT before cwd."""
        import json
        session_file = tmp_path / ".ystar_session.json"
        session_data = {"agent_stack": ["ceo"], "cieu_db": "/tmp/test.db"}
        session_file.write_text(json.dumps(session_data))

        monkeypatch.setenv("YSTAR_REPO_ROOT", str(tmp_path))

        # Clear the cache to force re-read
        import ystar.adapters.identity_detector as imod
        orig_cache = imod._SESSION_CONFIG_CACHE
        imod._SESSION_CONFIG_CACHE = None
        try:
            result = _load_session_config()
            assert result is not None
            assert result.get("agent_stack") == ["ceo"]
        finally:
            imod._SESSION_CONFIG_CACHE = orig_cache

    def test_no_cwd_dependency(self, monkeypatch, tmp_path):
        """When YSTAR_REPO_ROOT is set, _load_session_config should NOT call os.getcwd()."""
        monkeypatch.setenv("YSTAR_REPO_ROOT", str(tmp_path))

        import ystar.adapters.identity_detector as imod
        orig_cache = imod._SESSION_CONFIG_CACHE
        imod._SESSION_CONFIG_CACHE = None
        try:
            with patch("os.getcwd") as mock_getcwd:
                _load_session_config()
                mock_getcwd.assert_not_called()
        finally:
            imod._SESSION_CONFIG_CACHE = orig_cache
