"""
tests/break_glass/test_self_heal_write.py — Break-glass self-heal (CZL-P1-d)

Tests for the break-glass self-heal invariant:
  - When identity detection fails (who='agent'), writes to .ystar_active_agent
    and .ystar_session.json MUST be allowed (prevents chicken-and-egg lockout).
  - A SELF_HEAL_WRITE CIEU event is recorded for auditability.
  - Break-glass does NOT extend to other restricted files (e.g. AGENTS.md).
  - When identity IS known (who='ceo'), the normal restricted check applies.
"""
import pytest
from unittest.mock import patch, MagicMock

import ystar.adapters.boundary_enforcer as be
from ystar.adapters.boundary_enforcer import (
    _check_restricted_write_paths,
    _BREAK_GLASS_SELF_HEAL_PATHS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

RESTRICTED_CONFIG = {
    ".ystar_active_agent": ["secretary"],
    ".ystar_session.json": ["secretary"],
    "AGENTS.md": ["secretary"],
    ".claude/agents/": ["secretary"],
}


@pytest.fixture(autouse=True)
def reset_restricted_write_state():
    """Reset the lazy-loaded restricted_write_paths state between tests."""
    old_paths = be._RESTRICTED_WRITE_PATHS
    old_loaded = be._RESTRICTED_WRITE_LOADED
    # Pre-load with our test config
    be._RESTRICTED_WRITE_PATHS = dict(RESTRICTED_CONFIG)
    be._RESTRICTED_WRITE_LOADED = True
    yield
    # Restore
    be._RESTRICTED_WRITE_PATHS = old_paths
    be._RESTRICTED_WRITE_LOADED = old_loaded


# ── Test 1: identity='agent' + .ystar_active_agent → ALLOW ───────────────

class TestBreakGlassAllow:
    """Break-glass must allow identity-recovery writes when who='agent'."""

    @patch("ystar.adapters.boundary_enforcer._write_self_heal_cieu")
    def test_agent_write_active_agent_allowed(self, mock_cieu):
        """identity='agent' writing .ystar_active_agent → allowed + CIEU recorded."""
        result = _check_restricted_write_paths(
            "Write",
            {"file_path": "/workspace/.ystar_active_agent"},
            who="agent",
        )
        assert result is None  # None = allowed
        mock_cieu.assert_called_once_with("/workspace/.ystar_active_agent")

    @patch("ystar.adapters.boundary_enforcer._write_self_heal_cieu")
    def test_agent_write_session_json_allowed(self, mock_cieu):
        """identity='agent' writing .ystar_session.json → allowed + CIEU recorded."""
        result = _check_restricted_write_paths(
            "Write",
            {"file_path": "/workspace/.ystar_session.json"},
            who="agent",
        )
        assert result is None  # None = allowed
        mock_cieu.assert_called_once_with("/workspace/.ystar_session.json")

    @patch("ystar.adapters.boundary_enforcer._write_self_heal_cieu")
    def test_agent_edit_active_agent_allowed(self, mock_cieu):
        """identity='agent' editing .ystar_active_agent → also allowed (Edit tool)."""
        result = _check_restricted_write_paths(
            "Edit",
            {"file_path": ".ystar_active_agent"},
            who="agent",
        )
        assert result is None
        mock_cieu.assert_called_once()


# ── Test 2: identity='agent' + AGENTS.md → still DENY ────────────────────

class TestBreakGlassNoEscalation:
    """Break-glass must NOT extend to non-identity files."""

    @patch("ystar.adapters.boundary_enforcer._write_self_heal_cieu")
    def test_agent_write_agents_md_denied(self, mock_cieu):
        """identity='agent' writing AGENTS.md → still denied (break-glass is narrow)."""
        result = _check_restricted_write_paths(
            "Write",
            {"file_path": "/workspace/AGENTS.md"},
            who="agent",
        )
        assert result is not None
        assert result.allowed is False
        assert "Restricted write path violation" in result.reason
        mock_cieu.assert_not_called()  # No self-heal event for non-recovery files

    @patch("ystar.adapters.boundary_enforcer._write_self_heal_cieu")
    def test_agent_write_claude_agents_dir_denied(self, mock_cieu):
        """identity='agent' writing .claude/agents/ceo.md → still denied."""
        result = _check_restricted_write_paths(
            "Write",
            {"file_path": "/workspace/.claude/agents/ceo.md"},
            who="agent",
        )
        assert result is not None
        assert result.allowed is False
        mock_cieu.assert_not_called()


# ── Test 3: identity='ceo' + .ystar_active_agent → normal restricted check ─

class TestNormalIdentityRestrictedCheck:
    """When identity IS known, the normal restricted path rules apply."""

    def test_ceo_write_active_agent_denied(self):
        """identity='ceo' writing .ystar_active_agent → denied (only secretary allowed)."""
        result = _check_restricted_write_paths(
            "Write",
            {"file_path": "/workspace/.ystar_active_agent"},
            who="ceo",
        )
        assert result is not None
        assert result.allowed is False
        assert "secretary" in result.reason

    def test_secretary_write_active_agent_allowed(self):
        """identity='secretary' writing .ystar_active_agent → allowed (in allowed list)."""
        result = _check_restricted_write_paths(
            "Write",
            {"file_path": "/workspace/.ystar_active_agent"},
            who="secretary",
        )
        assert result is None  # Allowed

    def test_ceo_write_session_json_denied(self):
        """identity='ceo' writing .ystar_session.json → denied (only secretary allowed)."""
        result = _check_restricted_write_paths(
            "Write",
            {"file_path": "/workspace/.ystar_session.json"},
            who="ceo",
        )
        assert result is not None
        assert result.allowed is False


# ── Test 4: CIEU event content verification ───────────────────────────────

class TestSelfHealCIEUEvent:
    """Verify the SELF_HEAL_WRITE CIEU event is correctly formed."""

    def test_cieu_event_written_to_store(self):
        """_write_self_heal_cieu writes a correctly-formed CIEU event."""
        from ystar.adapters.boundary_enforcer import _write_self_heal_cieu
        mock_store = MagicMock()

        with patch("ystar.governance.cieu_store.CIEUStore", return_value=mock_store) as mock_cls:
            # Patch _load_session_config to return a session with cieu_db
            with patch(
                "ystar.adapters.identity_detector._load_session_config",
                return_value={"cieu_db": ":memory:"},
            ):
                _write_self_heal_cieu("/workspace/.ystar_active_agent")

            mock_store.write_dict.assert_called_once()
            event = mock_store.write_dict.call_args[0][0]

            assert event["agent_id"] == "agent"
            assert event["event_type"] == "SELF_HEAL_WRITE"
            assert event["decision"] == "allow"
            assert event["passed"] is True
            assert event["params"]["path"] == "/workspace/.ystar_active_agent"
            assert event["params"]["reason"] == "identity_detection_failed_self_heal"
            assert event["evidence_grade"] == "governance"


# ── Test 5: Break-glass path set is exactly correct ───────────────────────

class TestBreakGlassPathSet:
    """The break-glass set must be minimal and exact."""

    def test_break_glass_paths_are_exactly_two(self):
        """Only .ystar_active_agent and .ystar_session.json in break-glass set."""
        assert _BREAK_GLASS_SELF_HEAL_PATHS == {
            ".ystar_active_agent",
            ".ystar_session.json",
        }

    def test_agents_md_not_in_break_glass(self):
        """AGENTS.md must NOT be in the break-glass set."""
        assert "AGENTS.md" not in _BREAK_GLASS_SELF_HEAL_PATHS

    def test_claude_agents_not_in_break_glass(self):
        """.claude/agents/ must NOT be in the break-glass set."""
        assert ".claude/agents/" not in _BREAK_GLASS_SELF_HEAL_PATHS


# ── Test 6: Non-write tools bypass break-glass entirely ───────────────────

class TestNonWriteToolsBypass:
    """Non-write tools (Read, Bash) should not trigger restricted check at all."""

    def test_read_tool_bypasses_restricted_check(self):
        """Read tool is not a write tool — restricted check returns None."""
        result = _check_restricted_write_paths(
            "Read",
            {"file_path": "/workspace/.ystar_active_agent"},
            who="agent",
        )
        assert result is None

    def test_bash_tool_bypasses_restricted_check(self):
        """Bash tool is not in _WRITE_TOOLS — restricted check returns None."""
        result = _check_restricted_write_paths(
            "Bash",
            {"file_path": "/workspace/.ystar_active_agent"},
            who="agent",
        )
        assert result is None
