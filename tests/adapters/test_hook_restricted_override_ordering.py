#!/usr/bin/env python3
"""
Regression tests for CZL-KERNEL-OVERRIDE-PRE-FALLBACK-PHASE-2.

Bug: hook.py applied policy-membership fallback (rewriting who="secretary"
to who="agent") BEFORE _check_restricted_write_paths consulted the
allowed_roles list from restricted_write_paths config. This structurally
defeated the restricted-write mechanism for roles not registered in
AGENTS.md Policy (e.g. secretary).

Fix: Run _check_restricted_write_paths BEFORE the policy-membership
fallback so that allowed_roles is checked against the original detected
identity. Remove the post-fallback duplicate check to prevent re-deny.

Test matrix (restricted_write_paths):
  Case 1: secretary writes AGENTS.md (restricted + immutable) -> ALLOW
  Case 2: unknown "foo-unknown" writes AGENTS.md -> DENY
  Case 3: ceo writes AGENTS.md -> DENY (not in restricted allowed_roles)
  Case 4: secretary writes .ystar_active_agent (restricted only) -> ALLOW
  Case 5: non-override role writes .ystar_active_agent -> DENY
  Case 6: secretary reads AGENTS.md -> ALLOW (read is not write)

Combined Phase 1 + Phase 2 ordering tests:
  Case 7: secretary writes AGENTS.md passes BOTH immutable AND restricted
  Case 8: ceo blocked by immutable before restricted even runs
  Case 9: secretary writes non-restricted/non-immutable path -> pass both
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
# Helpers (mirrored from test_hook_immutable_override_ordering.py)
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
    if result.get("action") == "block":
        return True
    hso = result.get("hookSpecificOutput", {})
    if hso.get("permissionDecision") == "deny":
        return True
    return False


def _is_allow(result):
    """Check if a hook result is an allow decision."""
    return result == {} or not _is_deny(result)


def _deny_reason(result):
    """Extract the deny reason string from a hook result."""
    if not result:
        return ""
    hso = result.get("hookSpecificOutput", {})
    return hso.get("permissionDecisionReason", result.get("reason", ""))


# Immutable config mock: AGENTS.md + .claude/agents/ are immutable,
# override_roles = ["secretary"]
_IMMUTABLE_CONFIG = (
    ["AGENTS.md", ".claude/agents/"],
    ["secretary"],
)

# Restricted write paths mock:
# AGENTS.md -> only secretary can write
# .ystar_active_agent -> only secretary can write
# .claude/agents/ -> only secretary can write
_RESTRICTED_WRITE_PATHS = {
    "AGENTS.md": ["secretary"],
    ".ystar_active_agent": ["secretary"],
    ".claude/agents/": ["secretary"],
}


def _mock_immutable_config():
    return _IMMUTABLE_CONFIG


# ---------------------------------------------------------------------------
# Phase 2 Tests: restricted_write_paths override ordering
# ---------------------------------------------------------------------------

class TestRestrictedOverrideOrdering:
    """Verify restricted_write_paths check runs before policy-membership fallback."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        os.environ.setdefault("YSTAR_CIEU_DB", os.path.join(self.tmpdir, "test_cieu.db"))

    def teardown_method(self):
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)
        os.environ.pop("YSTAR_CIEU_DB", None)

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case1_secretary_writes_agents_md_allow(self, mock_cfg, mock_boot):
        """Case 1: secretary writes AGENTS.md (restricted + immutable) -> ALLOW.

        This is the exact Samantha#5 deadlock scenario. Secretary is in both
        immutable override_roles AND restricted allowed_roles. Pre-fix, the
        fallback rewrote secretary to 'agent' before the restricted check,
        causing a deny even though secretary is the authorized writer.
        """
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Edit", file_path="/workspace/AGENTS.md")

        result = check_hook(payload, policy=policy, agent_id="secretary")

        assert _is_allow(result), (
            f"secretary should be ALLOWED to write AGENTS.md via restricted "
            f"allowed_roles, but got DENY: {_deny_reason(result)}"
        )

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case2_unknown_role_writes_agents_md_deny(self, mock_cfg, mock_boot):
        """Case 2: unknown 'foo-unknown' writes AGENTS.md -> DENY.

        Unknown role is not in immutable override_roles, so immutable check
        denies first. Even without immutable, restricted check would also deny.
        """
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Write", file_path="/workspace/AGENTS.md")

        result = check_hook(payload, policy=policy, agent_id="foo-unknown")

        assert _is_deny(result), (
            f"foo-unknown should be DENIED writing AGENTS.md, got: {result}"
        )

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case3_ceo_writes_agents_md_deny(self, mock_cfg, mock_boot):
        """Case 3: ceo writes AGENTS.md -> DENY (not in override_roles or allowed_roles).

        CEO is registered in policy but is NOT in immutable override_roles and
        NOT in restricted allowed_roles. Should be denied by immutable check.
        """
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Edit", file_path="/workspace/AGENTS.md")

        result = check_hook(payload, policy=policy, agent_id="ceo")

        assert _is_deny(result), (
            f"ceo should be DENIED writing AGENTS.md, got: {result}"
        )

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case4_secretary_writes_active_agent_allow(self, mock_cfg, mock_boot):
        """Case 4: secretary writes .ystar_active_agent (restricted only) -> ALLOW.

        .ystar_active_agent is in restricted_write_paths but NOT in immutable_paths.
        Secretary is in the allowed_roles list. Pre-fix: secretary not in policy ->
        fallback to 'agent' -> restricted deny. Post-fix: restricted check sees
        original 'secretary' identity -> ALLOW.
        """
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Write", file_path="/workspace/.ystar_active_agent")

        result = check_hook(payload, policy=policy, agent_id="secretary")

        assert _is_allow(result), (
            f"secretary should be ALLOWED to write .ystar_active_agent, "
            f"but got DENY: {_deny_reason(result)}"
        )

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case5_non_override_writes_active_agent_deny(self, mock_cfg, mock_boot):
        """Case 5: non-override role 'eng-kernel' writes .ystar_active_agent -> DENY.

        eng-kernel is not in allowed_roles for .ystar_active_agent. The restricted
        check should deny with the original identity (no fallback needed since
        eng-kernel inherits cto, but cto is also not in allowed_roles).
        """
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Write", file_path="/workspace/.ystar_active_agent")

        result = check_hook(payload, policy=policy, agent_id="eng-kernel")

        assert _is_deny(result), (
            f"eng-kernel should be DENIED writing .ystar_active_agent, got: {result}"
        )
        reason = _deny_reason(result)
        assert "restricted" in reason.lower() or "Restricted" in reason, (
            f"Deny reason should mention restricted write path, got: {reason}"
        )

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case6_secretary_reads_agents_md_allow(self, mock_cfg, mock_boot):
        """Case 6: secretary reads AGENTS.md -> ALLOW (Read is not a write tool).

        Both immutable and restricted checks only apply to write tools. Read
        operations must always pass regardless of identity.
        """
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Read", file_path="/workspace/AGENTS.md")

        result = check_hook(payload, policy=policy, agent_id="secretary")

        assert _is_allow(result), (
            f"secretary reading AGENTS.md should always be ALLOWED, got: {result}"
        )


# ---------------------------------------------------------------------------
# Combined Phase 1 + Phase 2 ordering tests
# ---------------------------------------------------------------------------

class TestCombinedImmutableAndRestrictedOrdering:
    """Verify both Phase 1 (immutable) and Phase 2 (restricted) hoists work together."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        os.environ.setdefault("YSTAR_CIEU_DB", os.path.join(self.tmpdir, "test_cieu.db"))

    def teardown_method(self):
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)
        os.environ.pop("YSTAR_CIEU_DB", None)

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case7_secretary_passes_both_immutable_and_restricted(self, mock_cfg, mock_boot):
        """Case 7: secretary writes AGENTS.md passes BOTH immutable AND restricted.

        AGENTS.md is covered by both immutable_paths (override_roles=["secretary"])
        and restricted_write_paths (AGENTS.md: ["secretary"]). Secretary must pass
        both checks with original identity before any fallback occurs.
        """
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Edit", file_path="/workspace/AGENTS.md")

        result = check_hook(payload, policy=policy, agent_id="secretary")

        assert _is_allow(result), (
            f"secretary should pass BOTH immutable and restricted checks for AGENTS.md, "
            f"got DENY: {_deny_reason(result)}"
        )

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case8_ceo_blocked_by_immutable_before_restricted(self, mock_cfg, mock_boot):
        """Case 8: ceo blocked by immutable check before restricted check even runs.

        CEO is not in immutable override_roles, so the immutable check at Phase 1
        denies before the restricted check at Phase 2 is reached. The deny reason
        should reference 'immutable', not 'restricted'.
        """
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Edit", file_path="/workspace/AGENTS.md")

        result = check_hook(payload, policy=policy, agent_id="ceo")

        assert _is_deny(result), f"ceo should be DENIED, got: {result}"
        reason = _deny_reason(result)
        assert "immutable" in reason.lower() or "Immutable" in reason, (
            f"ceo deny should be from immutable check (first gate), got: {reason}"
        )

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    @patch("ystar.adapters.boundary_enforcer._get_immutable_config", _mock_immutable_config)
    @patch("ystar.adapters.hook._write_boot_record")
    @patch("ystar.adapters.hook._load_session_config_cached", return_value=None)
    def test_case9_secretary_writes_non_restricted_non_immutable(self, mock_cfg, mock_boot):
        """Case 9: secretary writes a non-restricted, non-immutable path.

        Both immutable and restricted checks should pass (path not matched).
        Downstream checks may deny for other reasons, but neither immutable
        nor restricted checks should block.
        """
        policy = _make_minimal_policy("ceo", "cto", "agent")
        payload = _make_hook_payload("Write", file_path="/workspace/reports/test.md")

        result = check_hook(payload, policy=policy, agent_id="secretary")

        if _is_deny(result):
            reason = _deny_reason(result)
            assert "immutable" not in reason.lower(), (
                f"Non-immutable path should not be denied by immutable check: {reason}"
            )
            assert "restricted" not in reason.lower(), (
                f"Non-restricted path should not be denied by restricted check: {reason}"
            )


# ---------------------------------------------------------------------------
# Unit-level tests directly on _check_restricted_write_paths
# ---------------------------------------------------------------------------

class TestRestrictedWritePathsUnit:
    """Unit tests for _check_restricted_write_paths override logic."""

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    def test_allowed_role_returns_none(self):
        """_check_restricted_write_paths returns None (allow) for allowed role."""
        from ystar.adapters.boundary_enforcer import _check_restricted_write_paths

        result = _check_restricted_write_paths("Edit", {"file_path": "/x/AGENTS.md"}, "secretary")
        assert result is None, f"secretary should return None (allow), got {result}"

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    def test_disallowed_role_returns_deny(self):
        """_check_restricted_write_paths returns PolicyResult(allowed=False) for non-allowed role."""
        from ystar.adapters.boundary_enforcer import _check_restricted_write_paths

        result = _check_restricted_write_paths("Edit", {"file_path": "/x/AGENTS.md"}, "ceo")
        assert result is not None, "ceo should be denied (not in allowed_roles)"
        assert result.allowed is False

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    def test_agent_role_returns_deny_for_agents_md(self):
        """_check_restricted_write_paths denies 'agent' for AGENTS.md (non-self-heal path)."""
        from ystar.adapters.boundary_enforcer import _check_restricted_write_paths

        result = _check_restricted_write_paths("Edit", {"file_path": "/x/AGENTS.md"}, "agent")
        assert result is not None, "'agent' should be denied for AGENTS.md"
        assert result.allowed is False

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    def test_non_write_tool_returns_none(self):
        """_check_restricted_write_paths returns None for non-write tools."""
        from ystar.adapters.boundary_enforcer import _check_restricted_write_paths

        result = _check_restricted_write_paths("Read", {"file_path": "/x/AGENTS.md"}, "ceo")
        assert result is None, f"Read tool should not be restricted, got {result}"

    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_PATHS", _RESTRICTED_WRITE_PATHS)
    @patch("ystar.adapters.boundary_enforcer._RESTRICTED_WRITE_LOADED", True)
    def test_unmatched_path_returns_none(self):
        """_check_restricted_write_paths returns None for paths not in restricted config."""
        from ystar.adapters.boundary_enforcer import _check_restricted_write_paths

        result = _check_restricted_write_paths("Write", {"file_path": "/x/reports/foo.md"}, "ceo")
        assert result is None, f"Non-restricted path should return None, got {result}"
