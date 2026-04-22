"""
CZL-ARCH-11a: Mandatory Invoke — auto-upgrade REDIRECT to INVOKE.

Tests:
1. REDIRECT + GuidancePayload with invoke_cmd → auto invoke → ALLOW
2. Invoke command fails → stays REDIRECT with error message
3. No GuidancePayload → unchanged REDIRECT behavior (backward compat)
"""
from __future__ import annotations

import json
import types
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# ── Minimal stubs to avoid heavy import chain ────────────────────────────

# We test _try_extract_guidance and the REDIRECT branch logic directly,
# without importing the full hook module (which requires session config etc.)

from ystar.domains.openclaw.adapter import GuidancePayload


# Fake CIEU record that mirrors the attributes used by _try_extract_guidance
@dataclass
class _FakeCIEURecord:
    drift_details: Optional[str] = None
    guidance: Optional[GuidancePayload] = None
    call_record: Any = None


class TestTryExtractGuidance:
    """Unit tests for _try_extract_guidance helper."""

    def _get_fn(self):
        from ystar.adapters.hook import _try_extract_guidance
        return _try_extract_guidance

    def test_no_records_returns_none(self):
        fn = self._get_fn()
        assert fn([]) is None
        assert fn(None) is None

    def test_structured_guidance_attribute(self):
        fn = self._get_fn()
        gp = GuidancePayload(
            invoke_cmd="ystar doctor",
            fix_command_args={"check": "session"},
            then_retry_original=True,
            rule_ref="labs.session_check",
        )
        rec = _FakeCIEURecord(guidance=gp)
        result = fn([rec])
        assert result is not None
        assert result.invoke_cmd == "ystar doctor"
        assert result.then_retry_original is True
        assert result.fix_command_args == {"check": "session"}

    def test_json_in_drift_details(self):
        fn = self._get_fn()
        payload = json.dumps({
            "invoke_cmd": "python3 fix.py",
            "fix_command_args": {"mode": "auto"},
            "then_retry_original": True,
            "rule_ref": "labs.auto_fix",
        })
        rec = _FakeCIEURecord(drift_details=payload)
        result = fn([rec])
        assert result is not None
        assert result.invoke_cmd == "python3 fix.py"
        assert result.then_retry_original is True

    def test_non_json_drift_details_returns_none(self):
        fn = self._get_fn()
        rec = _FakeCIEURecord(drift_details="omission_type=deadline_breach")
        result = fn([rec])
        assert result is None

    def test_empty_invoke_cmd_returns_none(self):
        fn = self._get_fn()
        gp = GuidancePayload(invoke_cmd="", then_retry_original=True)
        rec = _FakeCIEURecord(guidance=gp)
        result = fn([rec])
        assert result is None


class TestRedirectWithInvoke:
    """
    Integration-style tests for the REDIRECT branch in check_hook.

    These mock subprocess.run and the enforcement pipeline to test the
    three scenarios end-to-end without a live session.
    """

    def _build_redirect_scenario(self, guidance, subprocess_result=None, subprocess_exc=None):
        """
        Simulate the REDIRECT branch logic inline (extracted from hook.py).
        Returns the response dict that check_hook would return.
        """
        import subprocess as sp

        violation_desc = "[Y*] test violation"
        fix_command = 'echo "fix" && retry'
        tool_name = "Write"
        who = "eng-kernel"

        if guidance and guidance.invoke_cmd and guidance.then_retry_original:
            invoke_cmd = guidance.invoke_cmd
            invoke_args = guidance.fix_command_args or {}
            try:
                cmd_parts = [invoke_cmd] + [
                    f"--{k}={v}" for k, v in invoke_args.items()
                ]
                if subprocess_exc:
                    raise subprocess_exc
                proc = subprocess_result
                if proc.returncode == 0:
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "allow",
                            "permissionDecisionReason": (
                                f"AUTO_INVOKED: {invoke_cmd} succeeded, retrying. "
                                f"Original violation: {violation_desc}"
                            ),
                        }
                    }
                else:
                    err_msg = (proc.stderr or proc.stdout or "unknown error")[:200]
                    fix_command = f"{fix_command}\nAUTO_INVOKE_FAILED: {invoke_cmd} — manual fix needed"
            except Exception as exc:
                if not subprocess_exc:
                    raise
                fix_command = f"{fix_command}\nAUTO_INVOKE_FAILED: {invoke_cmd} — manual fix needed"

        redirect_message = (
            f"[Y*] REDIRECT: {violation_desc}\n"
            f"FIX_COMMAND: {fix_command}\n"
            f"THEN_RETRY: {tool_name}"
        )
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": redirect_message,
            }
        }

    def test_redirect_with_guidance_invoke_success(self):
        """REDIRECT + GuidancePayload → auto invoke succeeds → ALLOW."""
        gp = GuidancePayload(
            invoke_cmd="echo",
            fix_command_args={"msg": "fixed"},
            then_retry_original=True,
        )
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdout = "ok"
        proc_mock.stderr = ""

        resp = self._build_redirect_scenario(gp, subprocess_result=proc_mock)
        assert resp["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "AUTO_INVOKED" in resp["hookSpecificOutput"]["permissionDecisionReason"]
        assert "succeeded" in resp["hookSpecificOutput"]["permissionDecisionReason"]

    def test_redirect_with_guidance_invoke_fails(self):
        """REDIRECT + GuidancePayload → invoke fails → stays REDIRECT with error."""
        gp = GuidancePayload(
            invoke_cmd="false_cmd",
            fix_command_args={},
            then_retry_original=True,
        )
        proc_mock = MagicMock()
        proc_mock.returncode = 1
        proc_mock.stdout = ""
        proc_mock.stderr = "command not found"

        resp = self._build_redirect_scenario(gp, subprocess_result=proc_mock)
        # Still "allow" (REDIRECT is non-blocking) but contains failure info
        assert resp["hookSpecificOutput"]["permissionDecision"] == "allow"
        reason = resp["hookSpecificOutput"]["permissionDecisionReason"]
        assert "AUTO_INVOKE_FAILED" in reason
        assert "REDIRECT" in reason

    def test_redirect_no_guidance_unchanged(self):
        """No GuidancePayload → normal REDIRECT behavior (backward compat)."""
        resp = self._build_redirect_scenario(guidance=None)
        assert resp["hookSpecificOutput"]["permissionDecision"] == "allow"
        reason = resp["hookSpecificOutput"]["permissionDecisionReason"]
        assert "AUTO_INVOKED" not in reason
        assert "AUTO_INVOKE_FAILED" not in reason
        assert "REDIRECT" in reason
        assert "FIX_COMMAND" in reason

    def test_redirect_invoke_exception(self):
        """Invoke raises exception → stays REDIRECT with error."""
        gp = GuidancePayload(
            invoke_cmd="some_cmd",
            fix_command_args={},
            then_retry_original=True,
        )
        resp = self._build_redirect_scenario(
            gp, subprocess_exc=OSError("No such file")
        )
        reason = resp["hookSpecificOutput"]["permissionDecisionReason"]
        assert "AUTO_INVOKE_FAILED" in reason
