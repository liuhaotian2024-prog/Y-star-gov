#!/usr/bin/env python3
"""
Regression tests for CZL-KERNEL-OVERRIDE-PRE-FALLBACK.

Bug: hook.py applied policy-membership fallback (rewriting who="secretary"
to who="agent") BEFORE _check_immutable_paths consulted override_roles.
This structurally defeated the override mechanism for roles not registered
in AGENTS.md Policy.

Fix: Run _check_immutable_paths BEFORE the policy-membership fallback so
that override_roles is checked against the original detected identity.

Test matrix:
  Case 1: secretary writes AGENTS.md    -> ALLOW (override_roles wins)
  Case 2: unknown "foo-unknown" writes   -> DENY  (fallback catches)
  Case 3: ceo writes AGENTS.md          -> DENY  (not in override_roles)
  Case 4: eng-kernel writes protocols/  -> ALLOW (non-immutable path)
  Case 5: secretary writes .claude/agents/X.md -> ALLOW (override on dir pattern)
  Case 6: agent writes AGENTS.md        -> DENY  (registered but not override)
  Case 7: secretary reads AGENTS.md     -> ALLOW (read is not a write tool)
"""
import pytest
import os
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from pathlib import Path

import sys

# Ensure ystar is importable
_ystar_root = Path(__file__).resolve().parent.parent.parent
if str(_ystar_root) not in sys.path:
    sys.path.insert(0, str(_ystar_root))

from ystar.session import Policy, IntentContract, PolicyResult
from ystar.adapters.hook import check_hook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_policy(*roles):
    """Build a Policy with minimal IntentContract rules for given roles."""
    rules = {}
    for role in roles:
        rules[role] = IntentContract(name=role)
    return Policy(rules)


def _make_hook_payload(tool_name, file_path=None, command=None):
    """Build a hook payload dict for testing."""
    tool_input = {}
    if file_path is not None:
        tool_input["file_path"] = file_path
    if command is not None:
        tool_input["command"] = command
    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": "test-session",
    }


def _is_deny(result):
    """Check if a hook result is a deny decision (any format)."""
    if not result:
        return False
    # Format 1: {"action": "block", ...}
    if result.get("action") == "block":
        return True
    # Format 2: {"hookSpecificOutput": {"permissionDecision": "deny", ...}}
    hso = result.get("hookSpecificOutput", {})
    if hso.get("permissionDecision") == "deny":
        return True
    return False


def _is_allow(result):
    """Check if a hook result is an allow decision."""
    return result == {} or not _is_deny(result)


# Immutable config mock: AGENTS.md + .claude/agents/ are immutable,
# override_roles = ["secretary"]
_IMMUTABLE_CONFIG = (
    ["AGENTS.md", ".claude/agents/"],
    ["secretary"],
)


def _mock_immutable_config():
    return _IMMUTABLE_CONFIG


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestImmutableOverrideOrdering:
    """Verify immutable check runs before policy-membership fallback."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # Suppress CIEU writes and boot records during tests
        os.environ.setdefault("YSTAR_CIEU_DB", os.path.join(self.tmpdir, "test_cieu.db"))

    def teardown_method(self):
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)
        os.environ.pop("YSTAR_CIEU_DB", None)

    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case1_secretary_writes_agents_md_allow(self, mock_cfg, mock_boot):
        """Case 1: secretary writes AGENTS.md -> ALLOW (override_roles wins)."""
        # Policy has ceo, cto, agent — but NOT secretary.
        # Pre-fix: secretary would be rewritten to "agent" before immutable check.
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Edit", file_path="/workspace/AGENTS.md")

        result = check_hook(payload, policy=policy, agent_id="secretary")

        # ALLOW = empty dict
        assert result == {}, (
            f"secretary should be ALLOWED to write AGENTS.md via override_roles, "
            f"but got: {result}"
        )

    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case2_unknown_role_writes_agents_md_deny(self, mock_cfg, mock_boot):
        """Case 2: unknown role 'foo-unknown' writes AGENTS.md -> DENY."""
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Write", file_path="/workspace/AGENTS.md")

        result = check_hook(payload, policy=policy, agent_id="foo-unknown")

        assert _is_deny(result), (
            f"foo-unknown should be DENIED writing AGENTS.md, got: {result}"
        )

    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case3_ceo_writes_agents_md_deny(self, mock_cfg, mock_boot):
        """Case 3: ceo writes AGENTS.md -> DENY (ceo is not in override_roles)."""
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Edit", file_path="/workspace/AGENTS.md")

        result = check_hook(payload, policy=policy, agent_id="ceo")

        assert _is_deny(result), (
            f"ceo should be DENIED writing AGENTS.md, got: {result}"
        )

    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case4_eng_kernel_writes_non_immutable_allow(self, mock_cfg, mock_boot):
        """Case 4: eng-kernel writes protocols/ (non-immutable) -> not immutable deny.

        The immutable check should pass (non-immutable path). Downstream
        checks (CIEU marker, policy) may still deny for unrelated reasons,
        but the immutable path check itself must not block this.
        """
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Write", file_path="/workspace/protocols/foo.md")

        result = check_hook(payload, policy=policy, agent_id="eng-kernel")

        # The result may be deny for other reasons (CIEU marker check, etc.)
        # but it must NOT be an immutable path deny.
        if _is_deny(result):
            reason = ""
            hso = result.get("hookSpecificOutput", {})
            reason = hso.get("permissionDecisionReason", result.get("reason", ""))
            assert "immutable" not in reason.lower(), (
                f"eng-kernel writing non-immutable path should NOT be denied by "
                f"immutable check, got: {reason}"
            )

    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case5_secretary_writes_claude_agents_allow(self, mock_cfg, mock_boot):
        """Case 5: secretary writes .claude/agents/X.md -> ALLOW (override on dir)."""
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Write", file_path="/workspace/.claude/agents/Secretary.md")

        result = check_hook(payload, policy=policy, agent_id="secretary")

        assert result == {}, (
            f"secretary should be ALLOWED to write .claude/agents/ via override, got: {result}"
        )

    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case6_agent_writes_agents_md_deny(self, mock_cfg, mock_boot):
        """Case 6: 'agent' (registered role) writes AGENTS.md -> DENY."""
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Edit", file_path="/workspace/AGENTS.md")

        result = check_hook(payload, policy=policy, agent_id="agent")

        assert _is_deny(result), (
            f"'agent' role should be DENIED writing AGENTS.md, got: {result}"
        )

    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case7_secretary_reads_agents_md_allow(self, mock_cfg, mock_boot):
        """Case 7: secretary reads AGENTS.md -> ALLOW (Read is not a write tool)."""
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Read", file_path="/workspace/AGENTS.md")

        result = check_hook(payload, policy=policy, agent_id="secretary")

        assert result == {}, (
            f"secretary reading AGENTS.md should always be ALLOWED, got: {result}"
        )


class TestImmutableOverrideOrderingUnit:
    """Unit-level tests directly on _check_immutable_paths to verify override logic."""

    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    def test_override_role_returns_none(self):
        """_check_immutable_paths returns None (allow) for override role."""
        from ystar.adapters.boundary_enforcer import _check_immutable_paths

        result = _check_immutable_paths("Edit", {"file_path": "/x/AGENTS.md"}, "secretary")
        assert result is None, f"secretary override should return None (allow), got {result}"

    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    def test_non_override_role_returns_deny(self):
        """_check_immutable_paths returns PolicyResult(allowed=False) for non-override role."""
        from ystar.adapters.boundary_enforcer import _check_immutable_paths

        result = _check_immutable_paths("Edit", {"file_path": "/x/AGENTS.md"}, "ceo")
        assert result is not None, "ceo should be denied (not in override_roles)"
        assert result.allowed is False

    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    def test_empty_who_returns_deny(self):
        """_check_immutable_paths denies when who is empty string."""
        from ystar.adapters.boundary_enforcer import _check_immutable_paths

        result = _check_immutable_paths("Write", {"file_path": "/x/AGENTS.md"}, "")
        assert result is not None, "Empty who should be denied"
        assert result.allowed is False
