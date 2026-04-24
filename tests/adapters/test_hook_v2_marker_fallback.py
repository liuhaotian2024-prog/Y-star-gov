"""
tests/adapters/test_hook_v2_marker_fallback.py — Marker fallback regression test

Post-INC-2026-04-23: v2 thin adapter path lacked the marker fallback chain
that v1 hook_wrapper.py provides (lines 167-253). When Claude Code sends
agent_id="" and agent_type="agent" (root process defaults), the v2 path
resolved to "agent"/"guest" → session_start_protocol_incomplete DENY-all
→ fail-closed deadlock (~3 hours, Board manual rescue).

This test verifies that handle_hook_event() pre-injects the marker identity
into the payload before any rule evaluation or check_hook call.
"""
import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock

from ystar.adapters.hook import handle_hook_event, _read_marker_fallback


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def marker_dir(tmp_path):
    """Create a temp directory with a global .ystar_active_agent marker."""
    marker_file = tmp_path / ".ystar_active_agent"
    marker_file.write_text("ceo", encoding="utf-8")
    return tmp_path


@pytest.fixture
def marker_dir_with_ppid(tmp_path):
    """Create temp directory with per-PPID marker file."""
    ppid = str(os.getppid())
    marker_file = tmp_path / f".ystar_active_agent.ppid_{ppid}"
    marker_file.write_text("eng-kernel", encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset router registry to prevent cross-test leakage."""
    try:
        from ystar.governance.router_registry import reset_default_registry
        reset_default_registry()
    except Exception:
        pass
    yield
    try:
        from ystar.governance.router_registry import reset_default_registry
        reset_default_registry()
    except Exception:
        pass


# ── _read_marker_fallback unit tests ─────────────────────────────────

class TestReadMarkerFallback:
    """Test the marker fallback chain used by handle_hook_event v2 path."""

    def test_global_marker_found(self, marker_dir):
        """Global marker file is read when YSTAR_REPO_ROOT is set."""
        with patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(marker_dir)}):
            result = _read_marker_fallback()
            assert result == "ceo"

    def test_ppid_marker_takes_priority_over_global(self, tmp_path):
        """Per-PPID marker is checked before global marker."""
        ppid = str(os.getppid())
        (tmp_path / f".ystar_active_agent.ppid_{ppid}").write_text("eng-kernel")
        (tmp_path / ".ystar_active_agent").write_text("ceo")

        with patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(tmp_path)}):
            result = _read_marker_fallback()
            assert result == "eng-kernel"

    def test_session_id_marker_takes_priority(self, tmp_path):
        """Per-session marker (CLAUDE_SESSION_ID) is checked first."""
        (tmp_path / ".ystar_active_agent.test123").write_text("cto")
        (tmp_path / ".ystar_active_agent").write_text("ceo")

        with patch.dict(os.environ, {
            "YSTAR_REPO_ROOT": str(tmp_path),
            "CLAUDE_SESSION_ID": "test123",
        }):
            result = _read_marker_fallback()
            assert result == "cto"

    def test_no_marker_returns_none(self, tmp_path):
        """Returns None when no marker files exist."""
        with patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(tmp_path)}):
            result = _read_marker_fallback()
            assert result is None

    def test_empty_marker_returns_none(self, tmp_path):
        """Returns None when marker file is empty."""
        (tmp_path / ".ystar_active_agent").write_text("")
        with patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(tmp_path)}):
            result = _read_marker_fallback()
            assert result is None

    def test_scripts_subdir_marker(self, tmp_path):
        """Marker in scripts/ subdirectory is found."""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / ".ystar_active_agent").write_text("eng-platform")

        with patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(tmp_path)}):
            result = _read_marker_fallback()
            assert result == "eng-platform"

    def test_newest_global_marker_wins(self, tmp_path):
        """When both repo-root and scripts/ have global markers, newest wins."""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        root_marker = tmp_path / ".ystar_active_agent"
        scripts_marker = scripts / ".ystar_active_agent"

        # Write scripts marker first (older)
        scripts_marker.write_text("old-agent")
        import time; time.sleep(0.05)
        # Write root marker second (newer)
        root_marker.write_text("new-agent")

        with patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(tmp_path)}):
            result = _read_marker_fallback()
            assert result == "new-agent"


# ── handle_hook_event integration tests ──────────────────────────────

class TestHandleHookEventMarkerInjection:
    """Verify handle_hook_event pre-injects marker into payload."""

    def test_v2_injects_marker_when_agent_id_empty(self, marker_dir):
        """When payload has agent_id="" (root process default), marker is injected."""
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/some/file.py"},
            "agent_id": "",
            "agent_type": "agent",
        }

        with patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(marker_dir)}), \
             patch("ystar.adapters.hook.check_hook", return_value={}) as mock_check:
            handle_hook_event(payload)
            # Verify the payload was mutated before check_hook saw it
            call_payload = mock_check.call_args[0][0]
            assert call_payload["agent_id"] == "ceo"
            assert "agent_type" not in call_payload or call_payload.get("agent_type") != "agent"

    def test_v2_preserves_explicit_agent_id(self, marker_dir):
        """When payload has a real agent_id, marker injection is skipped."""
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/some/file.py"},
            "agent_id": "eng-kernel",
            "agent_type": "eng-kernel",
        }

        with patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(marker_dir)}), \
             patch("ystar.adapters.hook.check_hook", return_value={}) as mock_check:
            handle_hook_event(payload)
            call_payload = mock_check.call_args[0][0]
            assert call_payload["agent_id"] == "eng-kernel"

    def test_v2_marker_ceo_allows_edit_reports(self, marker_dir):
        """CEO resolved via marker can Edit reports/ paths (not denied by protocol)."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/reports/status.md"},
            "agent_id": "",
            "agent_type": "agent",
        }

        with patch.dict(os.environ, {"YSTAR_REPO_ROOT": str(marker_dir)}), \
             patch("ystar.adapters.hook.check_hook", return_value={}) as mock_check:
            result = handle_hook_event(payload)
            # Should not be denied by CEO constitutional (reports/ is not Y-star-gov source)
            call_payload = mock_check.call_args[0][0]
            assert call_payload["agent_id"] == "ceo"
