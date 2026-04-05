"""test_hook_response.py — Ecosystem-neutral hook response formatter tests."""
import json
import os
import pytest
from unittest.mock import patch
from ystar.adapters.hook_response import (
    detect_host, format_allow, format_deny, convert_ygov_result,
)


class TestDetectHost:
    """Host detection priority: env > session > payload > generic."""

    def test_env_var_highest_priority(self):
        with patch.dict(os.environ, {"YSTAR_HOST": "openclaw"}):
            assert detect_host({"transcript_path": "/x"}) == "openclaw"

    def test_env_var_case_insensitive(self):
        with patch.dict(os.environ, {"YSTAR_HOST": "Claude_Code"}):
            assert detect_host() == "claude_code"

    def test_claude_code_auto_detect_transcript(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("YSTAR_HOST", None)
            assert detect_host({"transcript_path": "/path/to/t.jsonl"}) == "claude_code"

    def test_claude_code_auto_detect_hook_event(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("YSTAR_HOST", None)
            assert detect_host({"hook_event_name": "PreToolUse"}) == "claude_code"

    def test_openclaw_auto_detect(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("YSTAR_HOST", None)
            assert detect_host({"openclaw_version": "1.0"}) == "openclaw"

    def test_generic_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("YSTAR_HOST", None)
            assert detect_host({"tool_name": "Bash"}) == "generic"

    def test_no_payload(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("YSTAR_HOST", None)
            assert detect_host(None) == "generic"


class TestFormatAllow:
    """ALLOW is empty dict for all hosts."""

    def test_claude_code(self):
        assert format_allow("claude_code") == {}

    def test_openclaw(self):
        assert format_allow("openclaw") == {}

    def test_generic(self):
        assert format_allow("generic") == {}


class TestFormatDeny:
    """DENY format varies by host."""

    def test_claude_code_format(self):
        r = format_deny("claude_code", "[Y*] /etc blocked")
        assert r == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "[Y*] /etc blocked",
            }
        }

    def test_claude_code_no_violations_field(self):
        """Claude Code format should not include violations at top level."""
        r = format_deny("claude_code", "reason", [{"dimension": "deny", "message": "x"}])
        assert "violations" not in r
        assert r["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_openclaw_format(self):
        r = format_deny("openclaw", "[Y*] blocked")
        assert r == {"action": "block", "message": "[Y*] blocked"}

    def test_openclaw_with_violations(self):
        viols = [{"dimension": "deny", "message": "/etc blocked"}]
        r = format_deny("openclaw", "msg", viols)
        assert r["action"] == "block"
        assert r["violations"] == viols

    def test_generic_format(self):
        r = format_deny("generic", "reason here")
        assert r == {"decision": "deny", "reason": "reason here"}

    def test_generic_with_violations(self):
        viols = [{"dimension": "deny_commands", "message": "rm -rf"}]
        r = format_deny("generic", "blocked", viols)
        assert r["decision"] == "deny"
        assert r["violations"] == viols

    def test_unknown_host_uses_generic(self):
        r = format_deny("some_future_framework", "reason")
        assert r == {"decision": "deny", "reason": "reason"}


class TestConvertYgovResult:
    """Converts Y*gov internal format to host-specific format."""

    def test_allow_all_hosts(self):
        for host in ["claude_code", "openclaw", "generic"]:
            assert convert_ygov_result({}, host) == {}

    def test_deny_claude_code(self):
        ygov = {"action": "block", "message": "[Y*] denied"}
        r = convert_ygov_result(ygov, "claude_code")
        assert r["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "[Y*] denied" in r["hookSpecificOutput"]["permissionDecisionReason"]

    def test_deny_openclaw(self):
        ygov = {"action": "block", "message": "[Y*] denied", "violations": [{"dimension": "deny", "message": "x"}]}
        r = convert_ygov_result(ygov, "openclaw")
        assert r["action"] == "block"
        assert r["violations"][0]["dimension"] == "deny"

    def test_deny_generic(self):
        ygov = {"action": "block", "message": "reason"}
        r = convert_ygov_result(ygov, "generic")
        assert r["decision"] == "deny"
        assert r["reason"] == "reason"

    def test_none_result_is_allow(self):
        assert convert_ygov_result(None, "claude_code") == {}

    def test_empty_dict_is_allow(self):
        assert convert_ygov_result({}, "openclaw") == {}
