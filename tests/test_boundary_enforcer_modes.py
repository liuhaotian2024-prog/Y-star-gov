#!/usr/bin/env python3
"""
Integration tests for CEO Mode + boundary_enforcer

Tests boundary enforcement with mode-aware expansion:
- standard mode: existing deny paths remain denied
- autonomous mode: Y-star-gov write allowed, must_dispatch bypassed
- break_glass mode: .claude/agents/ write allowed, elevated CIEU tags
"""

import json
import os
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add Y-star-gov to path
YSTAR_GOV_ROOT = Path("/Users/haotianliu/.openclaw/workspace/Y-star-gov")
sys.path.insert(0, str(YSTAR_GOV_ROOT))

from ystar.adapters.boundary_enforcer import (
    _check_write_boundary,
    _check_must_dispatch_via_cto,
    _get_current_mode,
    _record_behavior_rule_cieu
)
from ystar.session import PolicyResult


@pytest.fixture
def temp_mode_file(tmp_path):
    """Create temporary mode file for testing"""
    mode_file = tmp_path / ".ystar_ceo_mode.json"

    # Patch the mode file location
    with patch("ystar.adapters.boundary_enforcer.Path") as mock_path_cls:
        # Make Path() constructor work normally for most paths
        original_path = Path

        def path_side_effect(*args, **kwargs):
            # Intercept the specific mode file path
            if len(args) == 1 and args[0] == "/Users/haotianliu/.openclaw/workspace/ystar-company/.ystar_ceo_mode.json":
                return mode_file
            # Otherwise use original Path
            return original_path(*args, **kwargs)

        mock_path_cls.side_effect = path_side_effect
        yield mode_file


class TestStandardMode:
    """Test boundary enforcement in standard mode"""

    def test_ceo_write_denied_to_ystar_gov_in_standard(self, temp_mode_file):
        """Standard mode: CEO cannot write to Y-star-gov"""
        # Set standard mode
        temp_mode_file.write_text(json.dumps({"mode": "standard"}))

        # Mock _ensure_write_paths_loaded
        with patch("ystar.adapters.boundary_enforcer._ensure_write_paths_loaded"):
            with patch("ystar.adapters.boundary_enforcer._AGENT_WRITE_PATHS", {"ceo": ["/Users/haotianliu/.openclaw/workspace/ystar-company/"]}):
                result = _check_write_boundary(
                    who="ceo",
                    tool_name="Write",
                    params={"file_path": "/Users/haotianliu/.openclaw/workspace/Y-star-gov/ystar/kernel/core.py"}
                )

        assert result is not None
        assert result.allowed is False
        assert "Write boundary violation" in result.reason

    def test_ceo_must_dispatch_enforced_in_standard(self, temp_mode_file):
        """Standard mode: CEO must dispatch via CTO"""
        temp_mode_file.write_text(json.dumps({"mode": "standard"}))

        result = _check_must_dispatch_via_cto(
            who="ceo",
            tool_name="Agent",
            params={"subagent_type": "eng-kernel"},
            agent_rules={"must_dispatch_via_cto": True}
        )

        assert result is not None
        assert result.allowed is False
        assert "must dispatch" in result.reason


class TestAutonomousMode:
    """Test boundary enforcement in autonomous mode"""

    def test_ceo_write_allowed_to_ystar_gov_in_autonomous(self, temp_mode_file):
        """Autonomous mode: CEO can write to Y-star-gov"""
        import time
        temp_mode_file.write_text(json.dumps({
            "mode": "autonomous",
            "entered_at": time.time()
        }))

        with patch("ystar.adapters.boundary_enforcer._ensure_write_paths_loaded"):
            with patch("ystar.adapters.boundary_enforcer._AGENT_WRITE_PATHS", {"ceo": ["/Users/haotianliu/.openclaw/workspace/ystar-company/"]}):
                result = _check_write_boundary(
                    who="ceo",
                    tool_name="Write",
                    params={"file_path": "/Users/haotianliu/.openclaw/workspace/Y-star-gov/ystar/kernel/core.py"}
                )

        assert result is None  # allowed

    def test_ceo_write_allowed_to_gov_mcp_in_autonomous(self, temp_mode_file):
        """Autonomous mode: CEO can write to gov-mcp"""
        import time
        temp_mode_file.write_text(json.dumps({
            "mode": "autonomous",
            "entered_at": time.time()
        }))

        with patch("ystar.adapters.boundary_enforcer._ensure_write_paths_loaded"):
            with patch("ystar.adapters.boundary_enforcer._AGENT_WRITE_PATHS", {"ceo": ["/Users/haotianliu/.openclaw/workspace/ystar-company/"]}):
                result = _check_write_boundary(
                    who="ceo",
                    tool_name="Edit",
                    params={"file_path": "/Users/haotianliu/.openclaw/workspace/gov-mcp/server.py"}
                )

        assert result is None  # allowed

    def test_ceo_write_allowed_to_scripts_in_autonomous(self, temp_mode_file):
        """Autonomous mode: CEO can write to scripts/"""
        import time
        temp_mode_file.write_text(json.dumps({
            "mode": "autonomous",
            "entered_at": time.time()
        }))

        with patch("ystar.adapters.boundary_enforcer._ensure_write_paths_loaded"):
            with patch("ystar.adapters.boundary_enforcer._AGENT_WRITE_PATHS", {"ceo": ["/Users/haotianliu/.openclaw/workspace/ystar-company/"]}):
                result = _check_write_boundary(
                    who="ceo",
                    tool_name="Write",
                    params={"file_path": "/Users/haotianliu/.openclaw/workspace/ystar-company/scripts/new_util.py"}
                )

        assert result is None  # allowed

    def test_ceo_must_dispatch_bypassed_in_autonomous(self, temp_mode_file):
        """Autonomous mode: CEO bypasses must_dispatch"""
        import time
        temp_mode_file.write_text(json.dumps({
            "mode": "autonomous",
            "entered_at": time.time()
        }))

        result = _check_must_dispatch_via_cto(
            who="ceo",
            tool_name="Agent",
            params={"subagent_type": "eng-kernel"},
            agent_rules={"must_dispatch_via_cto": True}
        )

        assert result is None  # bypassed

    def test_autonomous_cieu_no_elevated_tag(self, temp_mode_file):
        """Autonomous mode: CIEU events do NOT have elevated=true"""
        import time
        temp_mode_file.write_text(json.dumps({
            "mode": "autonomous",
            "entered_at": time.time()
        }))

        # Mock CIEUStore (from governance.cieu_store, imported inside function)
        with patch("ystar.governance.cieu_store.CIEUStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store_cls.return_value = mock_store

            with patch("ystar.adapters.identity_detector._load_session_config", return_value={"session_id": "test"}):
                _record_behavior_rule_cieu(
                    who="ceo",
                    rule_name="test_rule",
                    event_type="TEST",
                    decision="ALLOW",
                    passed=True,
                    reason="test",
                    params={}
                )

            # Check write_dict call
            call_args = mock_store.write_dict.call_args[0][0]
            assert "elevated" not in call_args["params"]  # autonomous does NOT tag elevated


class TestBreakGlassMode:
    """Test boundary enforcement in break_glass mode"""

    def test_ceo_write_allowed_to_claude_agents_in_break_glass(self, temp_mode_file):
        """Break-glass mode: CEO can write to .claude/agents/"""
        import time
        temp_mode_file.write_text(json.dumps({
            "mode": "break_glass",
            "entered_at": time.time(),
            "trigger": "T3"
        }))

        with patch("ystar.adapters.boundary_enforcer._ensure_write_paths_loaded"):
            with patch("ystar.adapters.boundary_enforcer._AGENT_WRITE_PATHS", {"ceo": ["/Users/haotianliu/.openclaw/workspace/ystar-company/"]}):
                result = _check_write_boundary(
                    who="ceo",
                    tool_name="Edit",
                    params={"file_path": "/Users/haotianliu/.openclaw/workspace/ystar-company/.claude/agents/cto.md"}
                )

        assert result is None  # allowed

    def test_ceo_write_allowed_to_ystar_gov_in_break_glass(self, temp_mode_file):
        """Break-glass mode: CEO can write to Y-star-gov (inherits autonomous)"""
        import time
        temp_mode_file.write_text(json.dumps({
            "mode": "break_glass",
            "entered_at": time.time(),
            "trigger": "T1"
        }))

        with patch("ystar.adapters.boundary_enforcer._ensure_write_paths_loaded"):
            with patch("ystar.adapters.boundary_enforcer._AGENT_WRITE_PATHS", {"ceo": ["/Users/haotianliu/.openclaw/workspace/ystar-company/"]}):
                result = _check_write_boundary(
                    who="ceo",
                    tool_name="Write",
                    params={"file_path": "/Users/haotianliu/.openclaw/workspace/Y-star-gov/ystar/adapters/hook.py"}
                )

        assert result is None  # allowed

    def test_ceo_must_dispatch_bypassed_in_break_glass(self, temp_mode_file):
        """Break-glass mode: CEO bypasses must_dispatch"""
        import time
        temp_mode_file.write_text(json.dumps({
            "mode": "break_glass",
            "entered_at": time.time(),
            "trigger": "T2"
        }))

        result = _check_must_dispatch_via_cto(
            who="ceo",
            tool_name="Agent",
            params={"subagent_type": "Ryan-Platform"},
            agent_rules={"must_dispatch_via_cto": True}
        )

        assert result is None  # bypassed

    def test_break_glass_cieu_has_elevated_tag(self, temp_mode_file):
        """Break-glass mode: CIEU events have elevated=true"""
        import time
        temp_mode_file.write_text(json.dumps({
            "mode": "break_glass",
            "entered_at": time.time(),
            "trigger": "T3"
        }))

        # Mock CIEUStore (from governance.cieu_store, imported inside function)
        with patch("ystar.governance.cieu_store.CIEUStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store_cls.return_value = mock_store

            with patch("ystar.adapters.identity_detector._load_session_config", return_value={"session_id": "test"}):
                _record_behavior_rule_cieu(
                    who="ceo",
                    rule_name="test_rule",
                    event_type="TEST",
                    decision="ALLOW",
                    passed=True,
                    reason="test",
                    params={}
                )

            # Check write_dict call
            call_args = mock_store.write_dict.call_args[0][0]
            assert call_args["params"]["elevated"] is True  # break_glass MUST tag elevated


class TestModeExpiry:
    """Test mode expiry auto-revoke"""

    def test_expired_break_glass_auto_revokes(self, temp_mode_file):
        """Expired break_glass mode auto-revokes to standard"""
        import time
        # Set expiry in the past
        temp_mode_file.write_text(json.dumps({
            "mode": "break_glass",
            "entered_at": time.time() - 1200,
            "expires_at": time.time() - 100,  # expired 100s ago
            "trigger": "T1"
        }))

        mode = _get_current_mode()

        assert mode["mode"] == "standard"  # auto-revoked


class TestSharedConstraints:
    """Test constraints shared across all modes"""

    def test_git_push_denied_in_all_modes(self):
        """git push always denied (all modes respect this)"""
        # This is enforced at bash command level, tested separately
        # Just verify constant exists
        from ystar.adapters.boundary_enforcer import GIT_PUSH_ALWAYS_DENIED
        assert GIT_PUSH_ALWAYS_DENIED is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
