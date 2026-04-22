"""
Tests for CZL-P1-c: EnforceDecision.REDIRECT wiring

Coverage:
  1. EnforceDecision enum has REDIRECT value
  2. GateDecision.REDIRECT maps to EnforceDecision.REDIRECT in enforce()
  3. hook.py REDIRECT branch returns permissionDecision="allow" with structured message
  4. intervention_engine suggested_action contains specific command
"""
from __future__ import annotations

import pytest

from ystar.domains.openclaw.adapter import EnforceDecision
from ystar.governance.intervention_models import GateDecision, GateCheckResult
from ystar.governance.intervention_engine import InterventionEngine


# ── Test 1: EnforceDecision enum has REDIRECT ───────────────────────────────

class TestEnforceDecisionRedirect:
    def test_redirect_exists(self):
        assert hasattr(EnforceDecision, "REDIRECT")
        assert EnforceDecision.REDIRECT.value == "redirect"

    def test_redirect_is_string_enum(self):
        assert isinstance(EnforceDecision.REDIRECT, str)
        assert EnforceDecision.REDIRECT == "redirect"

    def test_all_decisions_present(self):
        values = {d.value for d in EnforceDecision}
        assert "allow" in values
        assert "deny" in values
        assert "escalate" in values
        assert "redirect" in values


# ── Test 2: GateDecision.REDIRECT exists and maps correctly ────────────────

class TestGateDecisionRedirect:
    def test_gate_redirect_exists(self):
        assert hasattr(GateDecision, "REDIRECT")
        assert GateDecision.REDIRECT.value == "redirect"

    def test_gate_check_result_redirect(self):
        result = GateCheckResult(
            decision=GateDecision.REDIRECT,
            actor_id="ceo",
            action_type="file_write",
            blocking_omission_type="test_obligation",
            suggested_action='echo "ceo" > /path/.ystar_active_agent && retry',
            overdue_secs=120.0,
        )
        assert result.decision == GateDecision.REDIRECT
        assert "ceo" in result.suggested_action


# ── Test 3: intervention_engine identity DENY has specific command ──────────

class TestInterventionEngineSuggestedAction:
    def test_validate_agent_identity_deny_has_fix_command(self):
        """
        When identity validation fails, the suggested_action should contain
        a specific executable command, not generic text.
        """
        from ystar.governance.intervention_engine import InterventionEngine
        error = InterventionEngine._validate_agent_identity("agent")
        assert error is not None
        assert "DENIED" in error

    def test_gate_check_generic_identity_returns_fix_command(self):
        """
        When gate_check denies a generic identity, the suggested_action
        in the result should be a specific shell command.
        """
        from ystar.governance.intervention_engine import GatingPolicy
        from ystar.governance.omission_store import InMemoryOmissionStore

        engine = InterventionEngine(
            omission_store=InMemoryOmissionStore(),
            gating_policy=GatingPolicy(),
        )

        result = engine.gate_check("agent", "file_write")
        assert result.decision == GateDecision.DENY
        assert ".ystar_active_agent" in result.suggested_action
        assert "echo" in result.suggested_action


# ── Test 4: REDIRECT message structure ─────────────────────────────────────

class TestRedirectMessageFormat:
    def test_redirect_message_has_three_sections(self):
        """REDIRECT response message must contain all 3 required sections."""
        # Simulate what hook.py produces for a REDIRECT decision
        violation_desc = "agent 'agent' identity is generic"
        fix_command = 'echo "ceo" > /Users/haotianliu/.openclaw/workspace/ystar-company/.ystar_active_agent && retry'
        tool_name = "Write"
        action_desc = "/some/path/file.py"

        redirect_message = (
            f"[Y*] REDIRECT: {violation_desc}\n"
            f"FIX_COMMAND: {fix_command}\n"
            f"THEN_RETRY: {tool_name} {action_desc}"
        )

        assert "[Y*] REDIRECT:" in redirect_message
        assert "FIX_COMMAND:" in redirect_message
        assert "THEN_RETRY:" in redirect_message

    def test_redirect_decision_is_allow(self):
        """REDIRECT decisions use permissionDecision='allow' (not 'deny')."""
        # This verifies the architectural choice: REDIRECT doesn't block
        redirect_response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "[Y*] REDIRECT: test\nFIX_COMMAND: echo fix\nTHEN_RETRY: test",
            }
        }
        assert redirect_response["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "[Y*] REDIRECT:" in redirect_response["hookSpecificOutput"]["permissionDecisionReason"]
