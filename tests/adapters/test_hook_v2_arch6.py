"""
tests/adapters/test_hook_v2_arch6.py — ARCH-6 integration tests

Tests for handle_hook_event() — the v2 thin adapter entry point.
Verifies:
  1. handle_hook_event falls through to check_hook when no rules match
  2. Router deny rules short-circuit before check_hook
  3. Router redirect rules return redirect response
  4. Router inject rules pass through (allow) to check_hook
  5. rules_dir loading from filesystem
  6. Feature flag parity: v1 (check_hook) vs v2 (handle_hook_event) on same payload
  7. Invalid rules_dir is handled gracefully
  8. Multiple rules execute in priority order
"""
import json
import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock

from ystar.kernel.dimensions import IntentContract
from ystar.session import Policy
from ystar.adapters.hook import check_hook, handle_hook_event, _load_rules_from_dir
from ystar.governance.router_registry import (
    RouterRegistry,
    RouterRule,
    RouterResult,
    get_default_registry,
    reset_default_registry,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_registry():
    """Reset default registry before each test to prevent cross-test leakage."""
    reset_default_registry()
    yield
    reset_default_registry()


def _make_policy() -> Policy:
    ic = IntentContract(
        deny=["/etc", "/production"],
        deny_commands=["rm -rf", "sudo"],
    )
    return Policy({"test_agent": ic})


def _make_payload(
    tool_name="Read",
    path="/workspace/file.py",
    agent_id="test_agent",
    session_id="test_sess",
):
    return {
        "tool_name": tool_name,
        "tool_input": {"file_path": path},
        "agent_id": agent_id,
        "session_id": session_id,
    }


# ── Test 1: Passthrough — no router rules, falls through to check_hook ──

class TestHandleHookPassthrough:

    def test_allow_when_no_rules_registered(self):
        """handle_hook_event with empty registry should behave like check_hook."""
        policy = _make_policy()
        payload = _make_payload(path="/workspace/safe.py")
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = handle_hook_event(payload, policy=policy)
        assert result == {}

    def test_deny_falls_through_to_check_hook(self):
        """Denied by check_hook policy (not router) — should still deny."""
        policy = _make_policy()
        payload = _make_payload(path="/etc/passwd")
        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = handle_hook_event(payload, policy=policy)
        assert "hookSpecificOutput" in result
        out = result["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny"


# ── Test 2: Router deny rule short-circuits ──

class TestRouterDenyShortCircuit:

    def test_router_deny_blocks_before_check_hook(self):
        """A router deny rule should block without reaching check_hook."""
        registry = get_default_registry()
        registry.register_rule(RouterRule(
            rule_id="test_block_bash",
            detector=lambda p: p.get("tool_name") == "Bash",
            executor=lambda p: RouterResult(
                decision="deny",
                message="Bash blocked by router rule",
            ),
            priority=1000,
        ))

        payload = _make_payload(tool_name="Bash")
        payload["tool_input"] = {"command": "ls"}
        policy = _make_policy()

        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = handle_hook_event(payload, policy=policy)

        assert "hookSpecificOutput" in result
        out = result["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny"
        assert "test_block_bash" in out["permissionDecisionReason"]
        assert "Bash blocked by router rule" in out["permissionDecisionReason"]


# ── Test 3: Router redirect rule ──

class TestRouterRedirect:

    def test_redirect_returns_deny_with_redirect_tag(self):
        """Router redirect decisions are formatted as deny with REDIRECT tag."""
        registry = get_default_registry()
        registry.register_rule(RouterRule(
            rule_id="test_redirect_write",
            detector=lambda p: p.get("tool_name") == "Write",
            executor=lambda p: RouterResult(
                decision="redirect",
                message="Use Edit instead of Write for existing files",
            ),
            priority=500,
        ))

        payload = _make_payload(tool_name="Write", path="/workspace/existing.py")
        policy = _make_policy()

        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = handle_hook_event(payload, policy=policy)

        assert "hookSpecificOutput" in result
        out = result["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny"
        assert "REDIRECT" in out["permissionDecisionReason"]
        assert "test_redirect_write" in out["permissionDecisionReason"]


# ── Test 4: Router inject rule passes through ──

class TestRouterInject:

    def test_inject_allows_and_falls_through(self):
        """Router inject decisions should NOT block — they add context and allow."""
        registry = get_default_registry()
        registry.register_rule(RouterRule(
            rule_id="test_inject_context",
            detector=lambda p: p.get("tool_name") == "Read",
            executor=lambda p: RouterResult(
                decision="inject",
                message="Injecting SOP context",
                injected_context="## SOP: Always check file exists first",
            ),
            priority=100,
        ))

        payload = _make_payload(tool_name="Read", path="/workspace/safe.py")
        policy = _make_policy()

        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = handle_hook_event(payload, policy=policy)

        # Inject does not block — falls through to check_hook which allows
        assert result == {}


# ── Test 5: rules_dir loading from filesystem ──

class TestRulesDirLoading:

    def test_load_rules_from_dir(self):
        """Rules .py files in a directory should be loaded and registered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = os.path.join(tmpdir, "block_grep.py")
            with open(rule_file, "w") as f:
                f.write(
                    "from ystar.governance.router_registry import RouterRule, RouterResult\n"
                    "RULES = [RouterRule(\n"
                    "    rule_id='fs_block_grep',\n"
                    "    detector=lambda p: p.get('tool_name') == 'Grep',\n"
                    "    executor=lambda p: RouterResult(decision='deny', message='Grep blocked'),\n"
                    "    priority=500,\n"
                    ")]\n"
                )

            payload = _make_payload(tool_name="Grep", path="/workspace")
            policy = _make_policy()

            with patch("ystar.adapters.hook._load_session_config", return_value=None):
                result = handle_hook_event(payload, rules_dir=tmpdir, policy=policy)

            assert "hookSpecificOutput" in result
            out = result["hookSpecificOutput"]
            assert out["permissionDecision"] == "deny"
            assert "fs_block_grep" in out["permissionDecisionReason"]

    def test_invalid_rules_dir_graceful(self):
        """Non-existent rules_dir should not crash — just skip loading."""
        payload = _make_payload(path="/workspace/safe.py")
        policy = _make_policy()

        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = handle_hook_event(
                payload,
                rules_dir="/nonexistent/path/rules",
                policy=policy,
            )

        # Should fall through to check_hook and allow
        assert result == {}


# ── Test 6: V1 vs V2 parity on same payload ──

class TestV1V2Parity:

    def test_same_allow_result(self):
        """check_hook (v1) and handle_hook_event (v2) should return same result for allow."""
        policy = _make_policy()
        payload = _make_payload(path="/workspace/safe.py")

        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            v1 = check_hook(payload, policy=policy, agent_id="test_agent")
            # Reset registry to ensure no stale rules
            reset_default_registry()
            v2 = handle_hook_event(payload, policy=policy)

        assert v1 == v2 == {}

    def test_same_deny_result(self):
        """check_hook (v1) and handle_hook_event (v2) should return same deny for policy violation."""
        policy = _make_policy()
        payload = _make_payload(path="/etc/passwd")

        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            v1 = check_hook(payload, policy=policy, agent_id="test_agent")
            reset_default_registry()
            v2 = handle_hook_event(payload, policy=policy)

        # Both should deny
        assert "hookSpecificOutput" in v1
        assert "hookSpecificOutput" in v2
        assert v1["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert v2["hookSpecificOutput"]["permissionDecision"] == "deny"


# ── Test 7: Priority ordering ──

class TestPriorityOrdering:

    def test_higher_priority_rule_evaluated_first(self):
        """Higher priority rules should be evaluated before lower ones."""
        registry = get_default_registry()

        # Low priority allow rule (should be skipped)
        registry.register_rule(RouterRule(
            rule_id="low_allow",
            detector=lambda p: True,
            executor=lambda p: RouterResult(decision="allow", message="low allows"),
            priority=10,
        ))

        # High priority deny rule (should win)
        registry.register_rule(RouterRule(
            rule_id="high_deny",
            detector=lambda p: True,
            executor=lambda p: RouterResult(decision="deny", message="high denies"),
            priority=1000,
        ))

        payload = _make_payload()
        policy = _make_policy()

        with patch("ystar.adapters.hook._load_session_config", return_value=None):
            result = handle_hook_event(payload, policy=policy)

        assert "hookSpecificOutput" in result
        out = result["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny"
        assert "high_deny" in out["permissionDecisionReason"]


# ── Test 8: _load_rules_from_dir skips underscored and non-py files ──

class TestRulesDirFiltering:

    def test_skips_underscore_and_nonpy_files(self):
        """Files starting with _ or not ending in .py should be skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Should be loaded
            good = os.path.join(tmpdir, "good_rule.py")
            with open(good, "w") as f:
                f.write(
                    "from ystar.governance.router_registry import RouterRule, RouterResult\n"
                    "RULES = [RouterRule(\n"
                    "    rule_id='good_rule',\n"
                    "    detector=lambda p: False,\n"
                    "    executor=lambda p: RouterResult(),\n"
                    ")]\n"
                )

            # Should be skipped (underscore prefix)
            skip1 = os.path.join(tmpdir, "_internal.py")
            with open(skip1, "w") as f:
                f.write("RULES = ['should not load']\n")

            # Should be skipped (not .py)
            skip2 = os.path.join(tmpdir, "readme.txt")
            with open(skip2, "w") as f:
                f.write("not a rule file\n")

            _load_rules_from_dir(tmpdir)

            registry = get_default_registry()
            assert registry.get_rule("good_rule") is not None
            # Only 1 rule should be registered
            assert registry.rule_count == 1
