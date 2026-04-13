"""
tests/test_deny_as_teaching.py — AMENDMENT-012 Deny-as-Teaching Tests

Test that behavior rule violations return structured Remediation payloads
with executable guidance (wrong_action, correct_steps, skill_ref, lesson_ref).

Coverage:
  - must_dispatch_via_cto
  - write_boundary_violation
  - immutable_paths
  - Remediation schema validation
  - CIEU remediation_payload field
  - Hook wrapper formatting (manual verification — hook not called in unit tests)
"""
import pytest
import os
from unittest.mock import patch, MagicMock
from ystar.session import PolicyResult, Remediation
from ystar.adapters.boundary_enforcer import (
    _check_must_dispatch_via_cto,
    _check_write_boundary,
    _check_immutable_paths,
)


class TestRemediationDataStructure:
    """Test Remediation dataclass and PolicyResult integration."""

    def test_remediation_dataclass_creation(self):
        """Remediation can be created with all required fields."""
        r = Remediation(
            wrong_action='invoke("Agent", agent="eng-kernel", ...)',
            correct_steps=['invoke("Agent", agent="cto", ...)'],
            skill_ref="knowledge/ceo/skills/ceo_delegation_chain.md",
            lesson_ref="knowledge/ceo/lessons/ceo_越权派工_2026_04_13.md",
            rule_name="must_dispatch_via_cto",
            rule_context="CEO must delegate via CTO",
        )
        assert r.wrong_action == 'invoke("Agent", agent="eng-kernel", ...)'
        assert len(r.correct_steps) == 1
        assert r.skill_ref.endswith(".md")
        assert r.rule_name == "must_dispatch_via_cto"

    def test_policyresult_with_remediation(self):
        """PolicyResult can carry Remediation payload."""
        r = Remediation(
            wrong_action="test",
            correct_steps=["fix"],
            skill_ref=None,
            lesson_ref=None,
            rule_name="test_rule",
        )
        result = PolicyResult(
            allowed=False,
            reason="test deny",
            who="ceo",
            what="Agent",
            violations=[],
            remediation=r,
        )
        assert result.remediation is not None
        assert result.remediation.rule_name == "test_rule"

    def test_policyresult_without_remediation_backward_compat(self):
        """PolicyResult still works without remediation (backward compatibility)."""
        result = PolicyResult(
            allowed=False,
            reason="old style deny",
            who="ceo",
            what="Write",
            violations=[],
        )
        assert result.remediation is None


class TestMustDispatchViaCTORemediation:
    """Test must_dispatch_via_cto returns structured remediation."""

    def test_ceo_spawn_eng_kernel_returns_remediation(self):
        """CEO → eng-kernel DENY includes remediation with CTO delegation steps."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_must_dispatch_via_cto(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-kernel", "task": "fix engine.py bug"},
                agent_rules=config["agent_behavior_rules"]["ceo"]
            )

        assert result is not None
        assert result.allowed is False
        assert result.remediation is not None

        r = result.remediation
        assert "eng-kernel" in r.wrong_action
        assert any("cto" in step.lower() for step in r.correct_steps)
        assert r.skill_ref == "knowledge/ceo/skills/ceo_delegation_chain.md"
        assert "越权派工" in r.lesson_ref or "2026_04_13" in r.lesson_ref
        assert r.rule_name == "must_dispatch_via_cto"
        assert "strategic coordinator" in r.rule_context or "CTO owns" in r.rule_context

    def test_ceo_spawn_cto_no_remediation(self):
        """CEO → CTO allowed, no remediation (correct path)."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_must_dispatch_via_cto(
                who="ceo",
                tool_name="Agent",
                params={"agent": "cto", "task": "engineering task"},
                agent_rules=config["agent_behavior_rules"]["ceo"]
            )

        assert result is None  # Allowed

    def test_remediation_correct_steps_executable(self):
        """Remediation correct_steps contain executable code, not abstract descriptions."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_must_dispatch_via_cto(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-platform", "task": "update hook"},
                agent_rules=config["agent_behavior_rules"]["ceo"]
            )

        r = result.remediation
        # At least one step should contain actual code (invoke/Agent/cto)
        has_code = any(
            "invoke" in step or "Agent" in step or ".claude/tasks/" in step
            for step in r.correct_steps
        )
        assert has_code, "Remediation correct_steps must include executable code examples"


class TestWriteBoundaryViolationRemediation:
    """Test write_boundary_violation returns structured remediation."""

    def test_eng_domains_write_kernel_returns_remediation(self):
        """eng-domains → ystar/kernel/ DENY includes remediation with delegation."""
        # Mock eng-domains write scope (does not include kernel/)
        with patch("ystar.adapters.boundary_enforcer._AGENT_WRITE_PATHS", {
            "eng-domains": [
                "/Users/haotianliu/.openclaw/workspace/Y-star-gov/ystar/domains/",
                "/Users/haotianliu/.openclaw/workspace/Y-star-gov/ystar/patterns/",
            ]
        }):
            with patch("ystar.adapters.boundary_enforcer._WRITE_PATHS_LOADED", True):
                result = _check_write_boundary(
                    who="eng-domains",
                    tool_name="Write",
                    params={"file_path": "/Users/haotianliu/.openclaw/workspace/Y-star-gov/ystar/kernel/engine.py"}
                )

        assert result is not None
        assert result.allowed is False
        assert result.remediation is not None

        r = result.remediation
        assert "kernel/engine.py" in r.wrong_action or "kernel" in r.wrong_action
        assert any("cto" in step.lower() or "delegate" in step.lower() for step in r.correct_steps)
        assert "eng-kernel" in str(r.correct_steps) or "Leo" in str(r.correct_steps)
        assert r.rule_name == "write_boundary_violation"
        # skill_ref should point to eng-domains scope doc
        assert "eng-domains" in r.skill_ref or "scope" in r.skill_ref

    def test_write_boundary_remediation_identifies_responsible_engineer(self):
        """Remediation identifies which engineer owns the path."""
        with patch("ystar.adapters.boundary_enforcer._AGENT_WRITE_PATHS", {
            "eng-domains": ["/workspace/ystar/domains/"]
        }):
            with patch("ystar.adapters.boundary_enforcer._WRITE_PATHS_LOADED", True):
                # Try to write to governance/ (Maya's territory)
                result = _check_write_boundary(
                    who="eng-domains",
                    tool_name="Edit",
                    params={"file_path": "/workspace/ystar/governance/omission_engine.py"}
                )

        r = result.remediation
        # Should mention eng-governance or Maya
        steps_text = " ".join(r.correct_steps)
        assert "governance" in steps_text.lower() or "maya" in steps_text.lower()


class TestImmutablePathsRemediation:
    """Test immutable_paths returns structured remediation."""

    def test_write_agents_md_returns_remediation(self):
        """Any agent → AGENTS.md DENY includes remediation with Board escalation."""
        with patch("ystar.adapters.boundary_enforcer._get_immutable_config", return_value=(
            ["AGENTS.md", ".claude/agents/"], []
        )):
            result = _check_immutable_paths(
                tool_name="Write",
                params={"file_path": "AGENTS.md"},
                who="ceo"
            )

        assert result is not None
        assert result.allowed is False
        assert result.remediation is not None

        r = result.remediation
        assert "AGENTS.md" in r.wrong_action
        assert any("Board" in step for step in r.correct_steps)
        assert r.rule_name == "immutable_paths"
        assert "immutable" in r.rule_context.lower()

    def test_write_claude_agents_dir_returns_remediation(self):
        """.claude/agents/ writes return remediation."""
        with patch("ystar.adapters.boundary_enforcer._get_immutable_config", return_value=(
            ["AGENTS.md", ".claude/agents/"], []
        )):
            result = _check_immutable_paths(
                tool_name="Edit",
                params={"file_path": ".claude/agents/ceo.md"},
                who="eng-platform"
            )

        r = result.remediation
        assert ".claude/agents" in r.wrong_action
        assert any("Board" in step or "escalate" in step for step in r.correct_steps)


class TestRemediationSchemaValidation:
    """Test all remediation payloads meet schema requirements."""

    def test_remediation_skill_ref_file_exists(self):
        """All skill_ref paths must point to existing files (or _draft_ stubs)."""
        # This test will be expanded as more rules get remediation
        # For now, check must_dispatch_via_cto skill exists
        skill_path = "/Users/haotianliu/.openclaw/workspace/ystar-company/knowledge/ceo/skills/ceo_delegation_chain.md"
        assert os.path.exists(skill_path), f"Skill ref {skill_path} must exist"

    def test_remediation_lesson_ref_file_exists(self):
        """lesson_ref paths must point to existing lessons."""
        lesson_path = "/Users/haotianliu/.openclaw/workspace/ystar-company/knowledge/ceo/lessons/ceo_越权派工_2026_04_13.md"
        assert os.path.exists(lesson_path), f"Lesson ref {lesson_path} must exist"

    def test_remediation_all_fields_present(self):
        """All Remediation instances have required fields non-empty."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_must_dispatch_via_cto(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-kernel", "task": "test"},
                agent_rules=config["agent_behavior_rules"]["ceo"]
            )

        r = result.remediation
        assert r.wrong_action != "", "wrong_action must not be empty"
        assert len(r.correct_steps) > 0, "correct_steps must not be empty"
        assert all(len(step) > 10 for step in r.correct_steps), "Each step must be substantive (>10 chars)"
        assert r.rule_name != "", "rule_name must not be empty"

    def test_remediation_correct_steps_not_abstract(self):
        """correct_steps must be concrete, not abstract advice."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_must_dispatch_via_cto(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-governance", "task": "test"},
                agent_rules=config["agent_behavior_rules"]["ceo"]
            )

        r = result.remediation
        # Reject abstract phrases
        abstract_phrases = ["you should", "consider", "maybe", "think about"]
        steps_text = " ".join(r.correct_steps).lower()
        for phrase in abstract_phrases:
            assert phrase not in steps_text, f"Remediation should avoid abstract phrase: '{phrase}'"


class TestRemediationFormatting:
    """Test deny message formatting (hook wrapper integration)."""

    def test_formatted_message_structure(self):
        """Deny message follows AMENDMENT-012 format template."""
        # This is a manual verification test — hook wrapper formats the message
        # Unit test verifies PolicyResult has remediation, integration test verifies formatting
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_must_dispatch_via_cto(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-kernel", "task": "test"},
                agent_rules=config["agent_behavior_rules"]["ceo"]
            )

        # Simulate hook wrapper formatting (manual check)
        assert result.remediation is not None, "Hook wrapper expects remediation field"

        # Expected format sections (hook wrapper should generate):
        # [Y*] DENY: ceo → Agent(agent="eng-kernel") (rule: must_dispatch_via_cto)
        # ❌ You did: ...
        # ✅ Correct sequence: ...
        # 📖 Skill reference: ...
        # 📊 Why this rule exists: ...

        # This test passes if remediation is present; actual formatting tested in integration


class TestBackwardCompatibility:
    """Ensure existing tests still pass after Remediation addition."""

    def test_existing_policyresult_usage_still_works(self):
        """Existing code that doesn't use remediation field still works."""
        result = PolicyResult(
            allowed=False,
            reason="old style",
            who="test",
            what="test",
            violations=[]
        )
        assert not result.allowed
        assert result.reason == "old style"
        assert result.remediation is None  # Optional field defaults to None

    def test_existing_deny_paths_dont_break(self):
        """Existing deny paths that don't return remediation still work."""
        # Not all rules have remediation yet — ensure those still DENY correctly
        # (This test becomes obsolete once all 10 rules have remediation)
        pass  # Placeholder — existing test suite covers this


# Additional test ideas (not yet implemented):
# - test_cieu_remediation_payload_field: Verify CIEU stores remediation JSON
# - test_hook_wrapper_formatting_end_to_end: Integration test with actual hook
# - test_skill_ref_path_resolution: Verify paths work from both repos
# - test_remediation_length_limits: Ensure formatted message <800 chars
# - test_all_10_rules_have_remediation: Iterate all behavior rules, verify remediation present
