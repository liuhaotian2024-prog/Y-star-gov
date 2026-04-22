# Layer: Test
"""
Tests for RULE-CHARTER-001: Charter Amendment Flow Enforcement

Validates the router rule that redirects non-secretary charter file edits
to Samantha-Secretary per Board 2026-04-10 directive.

Test matrix:
  1. Happy path: Secretary editing AGENTS.md -> ALLOW (rule does NOT fire)
  2. Redirect path: CEO editing AGENTS.md -> REDIRECT with fix_command
  3. Redirect path: CTO editing BOARD_CHARTER_AMENDMENTS.md -> REDIRECT
  4. Redirect path: Engineer editing .claude/agents/foo.md -> REDIRECT
  5. Boundary: Unknown role editing non-charter file -> rule does NOT fire
  6. Agent spawn: CEO spawning Ethan to edit AGENTS.md -> REDIRECT
  7. Agent spawn: CEO spawning Samantha to edit AGENTS.md -> ALLOW
  8. Edge: Empty payload -> rule does NOT fire
"""
from __future__ import annotations

import pytest

from ystar.governance.router_registry import (
    RouterRegistry,
    RouterResult,
    RouterRule,
)
from ystar.governance.rules.charter_amendment_flow import (
    CHARTER_FILE_PATTERNS,
    CHARTER_FLOW_CONTEXT,
    RULES,
    detect_charter_amendment,
    execute_charter_redirect,
)


@pytest.fixture
def registry():
    """Create a fresh RouterRegistry with the charter rule registered."""
    reg = RouterRegistry()
    for rule in RULES:
        reg.register_rule(rule)
    return reg


# ── Structural Tests ──────────────────────────────────────────────────

class TestRuleStructure:
    """Verify the rule object is correctly formed."""

    def test_rule_id(self):
        assert len(RULES) == 1
        rule = RULES[0]
        assert rule.rule_id == "RULE-CHARTER-001"

    def test_priority_is_constitutional(self):
        rule = RULES[0]
        assert rule.priority >= 1000, "Charter rule must be constitutional priority"

    def test_metadata_has_required_fields(self):
        rule = RULES[0]
        assert "source" in rule.metadata
        assert "authority" in rule.metadata
        assert "BOARD_CHARTER_AMENDMENTS" in rule.metadata["source"]

    def test_detector_and_executor_are_callable(self):
        rule = RULES[0]
        assert callable(rule.detector)
        assert callable(rule.executor)


# ── Test 1: Happy Path — Secretary is ALLOWED ─────────────────────────

class TestSecretaryAllowed:
    """Secretary (Samantha) edits charter files -> rule does NOT fire."""

    def test_secretary_edit_agents_md(self):
        """Secretary editing AGENTS.md should NOT trigger the rule."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/ystar-company/AGENTS.md"},
            "agent_id": "secretary",
        }
        assert detect_charter_amendment(payload) is False

    def test_samantha_write_agents_md(self):
        """Samantha writing AGENTS.md should NOT trigger the rule."""
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/path/to/AGENTS.md"},
            "agent_id": "samantha",
        }
        assert detect_charter_amendment(payload) is False

    def test_samantha_secretary_alias(self):
        """samantha-secretary alias should also be allowed."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/path/BOARD_CHARTER_AMENDMENTS.md"},
            "agent_id": "samantha-secretary",
        }
        assert detect_charter_amendment(payload) is False

    def test_secretary_no_redirect_in_registry(self, registry):
        """When secretary edits, registry finds NO matching rules."""
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/AGENTS.md"},
            "agent_id": "secretary",
        }
        matches = registry.find_matching_rules(payload)
        assert len(matches) == 0


# ── Test 2: Redirect Path — CEO editing AGENTS.md ─────────────────────

class TestCEORedirect:
    """CEO editing charter files -> REDIRECT to Samantha."""

    def test_ceo_edit_agents_md_detected(self):
        """CEO editing AGENTS.md should trigger the rule."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/ystar-company/AGENTS.md"},
            "agent_id": "ceo",
        }
        assert detect_charter_amendment(payload) is True

    def test_ceo_edit_agents_md_redirect_result(self):
        """Executor should return REDIRECT with fix_command."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/ystar-company/AGENTS.md"},
            "agent_id": "ceo",
        }
        result = execute_charter_redirect(payload)
        assert result.decision == "redirect"
        assert "Samantha-Secretary" in result.args.get("fix_command", "")
        assert "CHARTER FLOW VIOLATION" in result.message
        assert result.injected_context == CHARTER_FLOW_CONTEXT

    def test_ceo_redirect_contains_original_file(self):
        """Redirect result must reference the file that was targeted."""
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/AGENTS.md"},
            "agent_id": "ceo",
        }
        result = execute_charter_redirect(payload)
        assert "AGENTS.md" in result.args.get("attempted_file", "")
        assert result.args.get("violating_agent") == "ceo"
        assert result.args.get("attempted_tool") == "Write"

    def test_ceo_full_pipeline_via_registry(self, registry):
        """End-to-end: registry match + execute returns REDIRECT."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/ystar-company/AGENTS.md"},
            "agent_id": "ceo",
        }
        matches = registry.find_matching_rules(payload)
        assert len(matches) == 1
        assert matches[0].rule_id == "RULE-CHARTER-001"

        results = registry.execute_rules(payload, rules=matches)
        assert len(results) == 1
        assert results[0].decision == "redirect"
        assert results[0].rule_id == "RULE-CHARTER-001"


# ── Test 3: Redirect Path — CTO editing BOARD_CHARTER_AMENDMENTS.md ───

class TestCTORedirect:
    """CTO editing charter amendments file -> REDIRECT."""

    def test_cto_edit_charter_amendments(self):
        payload = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/governance/BOARD_CHARTER_AMENDMENTS.md"
            },
            "agent_id": "cto",
        }
        assert detect_charter_amendment(payload) is True

    def test_cto_redirect_result(self):
        payload = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/governance/BOARD_CHARTER_AMENDMENTS.md"
            },
            "agent_id": "cto",
        }
        result = execute_charter_redirect(payload)
        assert result.decision == "redirect"
        assert "Secretary" in result.message


# ── Test 4: Redirect Path — Engineer editing .claude/agents/*.md ──────

class TestEngineerRedirect:
    """Engineer editing agent definition files -> REDIRECT."""

    def test_engineer_edit_agent_definition(self):
        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/.claude/agents/cto-ethan.md"
            },
            "agent_id": "eng-kernel",
        }
        assert detect_charter_amendment(payload) is True

    def test_engineer_redirect_fix_command(self):
        payload = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/.claude/agents/cto-ethan.md"
            },
            "agent_id": "eng-kernel",
        }
        result = execute_charter_redirect(payload)
        assert result.decision == "redirect"
        assert "Samantha-Secretary" in result.args["fix_command"]
        assert "charter amendment flow" in result.injected_context.lower()


# ── Test 5: Boundary — Non-charter file -> Rule does NOT fire ─────────

class TestBoundaryNoFire:
    """Editing non-charter files should NOT trigger this rule."""

    def test_ceo_edit_regular_file(self):
        """CEO editing a regular .py file -> no detection."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/ystar/governance/causal_engine.py"},
            "agent_id": "ceo",
        }
        assert detect_charter_amendment(payload) is False

    def test_ceo_read_agents_md(self):
        """Reading AGENTS.md (not writing) -> no detection."""
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/AGENTS.md"},
            "agent_id": "ceo",
        }
        assert detect_charter_amendment(payload) is False

    def test_unknown_role_regular_file(self):
        """Unknown role editing a non-charter file -> no detection."""
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/workspace/src/main.py"},
            "agent_id": "unknown-role-xyz",
        }
        assert detect_charter_amendment(payload) is False

    def test_bash_tool_not_matched(self):
        """Bash tool calls are not Write/Edit, should not match."""
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat AGENTS.md"},
            "agent_id": "ceo",
        }
        assert detect_charter_amendment(payload) is False

    def test_no_match_in_registry(self, registry):
        """Non-charter file edit should produce zero matching rules."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/src/main.py"},
            "agent_id": "ceo",
        }
        matches = registry.find_matching_rules(payload)
        assert len(matches) == 0


# ── Test 6: Agent Spawn — CEO spawning Ethan to edit AGENTS.md ────────

class TestAgentSpawnRedirect:
    """CEO spawning non-secretary sub-agent to edit charter -> REDIRECT."""

    def test_ceo_spawn_ethan_edit_agents(self):
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "Ethan-CTO",
                "prompt": "Edit AGENTS.md to add a new section for eng-data role",
            },
            "agent_id": "ceo",
        }
        assert detect_charter_amendment(payload) is True

    def test_ceo_spawn_ethan_redirect_result(self):
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "Ethan-CTO",
                "prompt": "Modify AGENTS.md to update the CTO section",
            },
            "agent_id": "ceo",
        }
        result = execute_charter_redirect(payload)
        assert result.decision == "redirect"
        assert "Samantha-Secretary" in result.args["fix_command"]


# ── Test 7: Agent Spawn — CEO spawning Samantha -> ALLOW ──────────────

class TestAgentSpawnSamanthaAllowed:
    """CEO spawning Samantha to edit charter files -> rule does NOT fire."""

    def test_ceo_spawn_samantha_to_edit(self):
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "Samantha-Secretary",
                "prompt": "Edit AGENTS.md to add the new amendment",
            },
            "agent_id": "ceo",
        }
        assert detect_charter_amendment(payload) is False

    def test_ceo_spawn_secretary_alias(self):
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "secretary",
                "prompt": "Update BOARD_CHARTER_AMENDMENTS.md with new entry",
            },
            "agent_id": "ceo",
        }
        assert detect_charter_amendment(payload) is False


# ── Test 8: Edge Cases ────────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases: empty payloads, missing keys, unusual inputs."""

    def test_empty_payload(self):
        assert detect_charter_amendment({}) is False

    def test_missing_tool_input(self):
        payload = {"tool_name": "Edit", "agent_id": "ceo"}
        assert detect_charter_amendment(payload) is False

    def test_non_dict_tool_input(self):
        payload = {
            "tool_name": "Edit",
            "tool_input": "not a dict",
            "agent_id": "ceo",
        }
        assert detect_charter_amendment(payload) is False

    def test_agent_id_case_insensitive(self):
        """Agent ID matching should be case-insensitive."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/AGENTS.md"},
            "agent_id": "CEO",
        }
        assert detect_charter_amendment(payload) is True

    def test_secretary_uppercase(self):
        """Secretary identity check is case-insensitive."""
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/workspace/AGENTS.md"},
            "agent_id": "Secretary",
        }
        assert detect_charter_amendment(payload) is False

    def test_agent_spawn_no_edit_intent(self):
        """Agent spawn that mentions AGENTS.md but no edit intent -> no fire."""
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "Ethan-CTO",
                "prompt": "Read AGENTS.md and summarize the governance rules",
            },
            "agent_id": "ceo",
        }
        assert detect_charter_amendment(payload) is False
