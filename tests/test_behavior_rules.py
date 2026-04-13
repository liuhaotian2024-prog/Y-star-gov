"""
tests/test_behavior_rules.py — Test agent behavior rules enforcement

Tests for the agent behavior rules engine that enforces constitutional
behavior constraints at runtime.

Test coverage:
  - CEO must_dispatch_via_cto rule (CEO cannot spawn eng-* directly)
  - Behavior rules from session config
  - Backward compatibility when no behavior_rules config exists
  - Integration with hook.py
"""
import pytest
import time
from unittest.mock import patch
from ystar.adapters.boundary_enforcer import _check_behavior_rules
from ystar.adapters.hook import check_hook


class TestBehaviorRulesBasics:
    """Test basic behavior rules functionality."""

    def test_no_config_allows_all(self):
        """When no session config exists, all behavior is allowed."""
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=None):
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-kernel"}
            )
            assert result is None  # Allow

    def test_empty_behavior_rules_allows_all(self):
        """When session config has no behavior_rules, all behavior is allowed."""
        config = {"other_key": "value"}
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-kernel"}
            )
            assert result is None  # Allow

    def test_agent_without_rules_allowed(self):
        """Agents without specific behavior rules are allowed all behavior."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            # CTO has no rules, should be allowed
            result = _check_behavior_rules(
                who="cto",
                tool_name="Agent",
                params={"agent": "eng-kernel"}
            )
            assert result is None  # Allow


class TestCEOMustDispatchViaCTO:
    """Test CEO must_dispatch_via_cto rule enforcement."""

    def test_ceo_spawn_eng_kernel_denied(self):
        """CEO spawning eng-kernel directly should be DENIED."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-kernel"}
            )
            assert result is not None
            assert result.allowed is False
            assert "must dispatch engineering tasks via CTO" in result.reason
            assert "eng-kernel" in result.reason

    def test_ceo_spawn_eng_governance_denied(self):
        """CEO spawning eng-governance directly should be DENIED."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-governance"}
            )
            assert result is not None
            assert result.allowed is False

    def test_ceo_spawn_eng_platform_denied(self):
        """CEO spawning eng-platform directly should be DENIED."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-platform"}
            )
            assert result is not None
            assert result.allowed is False

    def test_ceo_spawn_eng_domains_denied(self):
        """CEO spawning eng-domains directly should be DENIED."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-domains"}
            )
            assert result is not None
            assert result.allowed is False

    def test_ceo_spawn_cto_allowed(self):
        """CEO spawning CTO should be ALLOWED (correct delegation chain)."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "cto"}
            )
            assert result is None  # Allow

    def test_ceo_spawn_cmo_allowed(self):
        """CEO spawning CMO should be ALLOWED (not an engineering role)."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "cmo"}
            )
            assert result is None  # Allow

    def test_ceo_non_agent_tool_allowed(self):
        """CEO using non-Agent tools should be ALLOWED."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            # Write tool should be allowed
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Write",
                params={"file_path": "reports/status.md"}
            )
            assert result is None  # Allow

    def test_cto_spawn_eng_kernel_allowed(self):
        """CTO spawning eng-kernel should be ALLOWED (correct delegation chain)."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            # CTO doesn't have the restriction, should be allowed
            result = _check_behavior_rules(
                who="cto",
                tool_name="Agent",
                params={"agent": "eng-kernel"}
            )
            assert result is None  # Allow

    def test_rule_disabled_allows_all(self):
        """When must_dispatch_via_cto is false, CEO can spawn eng-* directly."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": False}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-kernel"}
            )
            assert result is None  # Allow


class TestHookIntegration:
    """Test behavior rules integration with check_hook.

    Note: These tests use lightweight path (no session_cfg) to avoid
    complexity of full governance path with intervention engine.
    """

    def test_hook_denies_ceo_eng_spawn(self):
        """check_hook should deny CEO spawning eng-* when rule is active."""
        from ystar.session import Policy
        from ystar.kernel.dimensions import IntentContract

        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }

        hook_payload = {
            "tool_name": "Agent",
            "tool_input": {"agent": "eng-kernel", "task": "Fix bug"},
            "session_id": "test_session",
            "agent_id": "ceo"
        }

        # Create minimal policy with CEO agent
        policy = Policy({
            "ceo": IntentContract(
                deny=[],
                only_paths=[],
                deny_commands=[],
                only_domains=[],
                invariant=[],
                value_range={},
                hash="test_hash"
            )
        })

        # Mock _load_session_config_cached which is what hook.py actually calls
        with patch("ystar.adapters.hook._load_session_config_cached", return_value=config):
            with patch("ystar.adapters.cieu_writer._write_boot_record"):
                with patch("ystar.adapters.cieu_writer._write_cieu"):
                    response = check_hook(hook_payload, agent_id="ceo", policy=policy)

                    assert response.get("action") == "block"
                    assert "must dispatch engineering tasks via CTO" in response.get("message", "")

    def test_hook_allows_ceo_cto_spawn(self):
        """check_hook should allow CEO spawning CTO when rule is active."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }

        hook_payload = {
            "tool_name": "Agent",
            "tool_input": {"agent": "cto", "task": "Review code"},
            "session_id": "test_session",
            "agent_id": "ceo"
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.hook._load_session_config_cached", return_value=None):
                with patch("ystar.adapters.cieu_writer._write_boot_record"):
                    with patch("ystar.adapters.cieu_writer._write_cieu"):
                        response = check_hook(hook_payload, agent_id="ceo")

                        # Should not block (response is {} or doesn't have "block" action)
                        assert response.get("action") != "block"

    def test_hook_allows_cto_eng_spawn(self):
        """check_hook should allow CTO spawning eng-* agents."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }

        hook_payload = {
            "tool_name": "Agent",
            "tool_input": {"agent": "eng-kernel", "task": "Implement feature"},
            "session_id": "test_session",
            "agent_id": "cto"
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.hook._load_session_config_cached", return_value=None):
                with patch("ystar.adapters.cieu_writer._write_boot_record"):
                    with patch("ystar.adapters.cieu_writer._write_cieu"):
                        response = check_hook(hook_payload, agent_id="cto")

                        # Should not block
                        assert response.get("action") != "block"


class TestMultipleRules:
    """Test multiple behavior rules for the same agent."""

    def test_multiple_rules_all_checked(self):
        """Multiple rules for same agent should all be enforced."""
        config = {
            "agent_behavior_rules": {
                "ceo": {
                    "must_dispatch_via_cto": True,
                    "verification_before_assertion": True  # Not implemented yet in tool check
                }
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            # must_dispatch_via_cto should still be enforced
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-kernel"}
            )
            assert result is not None
            assert result.allowed is False

    def test_unimplemented_rules_ignored(self):
        """Rules that are defined but not implemented should not cause errors."""
        config = {
            "agent_behavior_rules": {
                "ceo": {
                    "future_rule_not_yet_implemented": True
                }
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            # Should not crash, should allow
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "eng-kernel"}
            )
            assert result is None  # Allow (rule not implemented)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_agent_param(self):
        """Agent tool call without agent parameter should be allowed (will fail elsewhere)."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={}  # Missing agent parameter
            )
            # Should allow (empty string doesn't start with "eng-")
            assert result is None

    def test_empty_agent_param(self):
        """Agent tool call with empty agent parameter should be allowed."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": ""}
            )
            assert result is None  # Allow

    def test_case_sensitive_agent_match(self):
        """Agent name matching should be case-sensitive."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            # "ENG-kernel" (uppercase) should still be denied
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "ENG-kernel"}
            )
            # Currently checks startswith("eng-"), so uppercase might be allowed
            # This documents current behavior - could be changed if needed
            assert result is None  # Allow (case mismatch)

    def test_eng_prefix_in_middle_allowed(self):
        """Agent name with 'eng-' in middle but not start should be allowed."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"must_dispatch_via_cto": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="ceo",
                tool_name="Agent",
                params={"agent": "senior-eng-advisor"}
            )
            assert result is None  # Allow (doesn't start with "eng-")


class TestVerificationBeforeAssertion:
    """Test verification_before_assertion rule (Rule 2)."""

    def test_assertion_without_verification_warns(self):
        """Asserting impossibility without prior verification should WARN."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"verification_before_assertion": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                # Write with assertion keyword but no prior verification
                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Write",
                    params={"file_path": "report.md", "content": "This is impossible to implement."}
                )

                assert result is None  # Don't block
                # Check CIEU was called with WARNING
                assert mock_cieu.called
                call_args = mock_cieu.call_args[1]
                assert call_args["rule_name"] == "verification_before_assertion"
                assert call_args["decision"] == "WARNING"
                assert call_args["passed"] is False

    def test_assertion_with_verification_passes(self):
        """Asserting impossibility after verification should pass."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"verification_before_assertion": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                # First do verification
                _check_behavior_rules(
                    who="ceo",
                    tool_name="Read",
                    params={"file_path": "config.json"}
                )

                # Then assert impossibility - should not warn
                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Write",
                    params={"file_path": "report.md", "content": "After checking, this is impossible."}
                )

                assert result is None  # Don't block
                # Should not have warned about verification
                if mock_cieu.called:
                    call_args = mock_cieu.call_args[1]
                    assert call_args["rule_name"] != "verification_before_assertion"


class TestRootCauseFixRequired:
    """Test root_cause_fix_required rule (Rule 3)."""

    def test_code_edit_without_test_warns(self):
        """Editing code without writing tests should WARN."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "cto": {"root_cause_fix_required": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                result = _check_behavior_rules(
                    who="cto",
                    tool_name="Edit",
                    params={"file_path": "ystar/kernel/engine.py", "old_string": "bug", "new_string": "fix"}
                )

                assert result is None  # Don't block
                assert mock_cieu.called
                call_args = mock_cieu.call_args[1]
                assert call_args["rule_name"] == "root_cause_fix_required"
                assert call_args["decision"] == "WARNING"

    def test_code_edit_with_test_passes(self):
        """Editing code with test write should pass."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "cto": {"root_cause_fix_required": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu"):
                # First write a test
                _check_behavior_rules(
                    who="cto",
                    tool_name="Write",
                    params={"file_path": "tests/test_engine.py", "content": "def test_fix(): pass"}
                )

                # Then edit code - should not warn
                result = _check_behavior_rules(
                    who="cto",
                    tool_name="Edit",
                    params={"file_path": "ystar/kernel/engine.py", "old_string": "bug", "new_string": "fix"}
                )

                assert result is None


class TestDocumentRequiresExecutionPlan:
    """Test document_requires_execution_plan rule (Rule 4)."""

    def test_protocol_doc_without_execution_warns(self):
        """Creating protocol doc without execution should WARN."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"document_requires_execution_plan": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Write",
                    params={"file_path": "PROTOCOL.md", "content": "# New Governance Protocol\nRules here..."}
                )

                assert result is None  # Don't block
                assert mock_cieu.called
                call_args = mock_cieu.call_args[1]
                assert call_args["rule_name"] == "document_requires_execution_plan"

    def test_protocol_doc_with_execution_passes(self):
        """Creating protocol doc with execution should pass."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"document_requires_execution_plan": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu"):
                # First dispatch execution
                _check_behavior_rules(
                    who="ceo",
                    tool_name="Agent",
                    params={"agent": "cto", "task": "Implement protocol"}
                )

                # Then write protocol - should not warn
                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Write",
                    params={"file_path": "PROTOCOL.md", "content": "# New Protocol\nRules..."}
                )

                assert result is None


class TestNoFabrication:
    """Test no_fabrication rule (Rule 5)."""

    def test_statistics_without_verification_warns(self):
        """Including statistics without verification should WARN."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"no_fabrication": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Write",
                    params={"file_path": "report.md", "content": "We have 95% test coverage and $100k revenue."}
                )

                assert result is None  # Don't block
                assert mock_cieu.called
                call_args = mock_cieu.call_args[1]
                assert call_args["rule_name"] == "no_fabrication"

    def test_statistics_with_verification_passes(self):
        """Including statistics with verification should pass."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"no_fabrication": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu"):
                # First verify data
                _check_behavior_rules(
                    who="ceo",
                    tool_name="Bash",
                    params={"command": "pytest --cov"}
                )

                # Then cite statistics - should not warn
                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Write",
                    params={"file_path": "report.md", "content": "We have 95% test coverage."}
                )

                assert result is None


class TestCounterfactualBeforeMajorDecision:
    """Test counterfactual_before_major_decision rule (Rule 6)."""

    def test_major_decision_without_counterfactual_warns(self):
        """Major decision without counterfactual should WARN."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"counterfactual_before_major_decision": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Agent",
                    params={"agent": "cto", "task": "Level 2: Implement new architecture"}
                )

                assert result is None  # Don't block
                assert mock_cieu.called
                call_args = mock_cieu.call_args[1]
                assert call_args["rule_name"] == "counterfactual_before_major_decision"

    def test_major_decision_with_counterfactual_passes(self):
        """Major decision with counterfactual should pass."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"counterfactual_before_major_decision": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu"):
                # First do counterfactual analysis
                _check_behavior_rules(
                    who="ceo",
                    tool_name="Write",
                    params={"file_path": "analysis.md", "content": "What if we used alternative B instead?"}
                )

                # Then make decision - should not warn
                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Agent",
                    params={"agent": "cto", "task": "Level 2: Implement architecture"}
                )

                assert result is None


class TestMustCheckHealthOnSessionStart:
    """Test must_check_health_on_session_start rule (Rule 7)."""

    def test_no_health_check_in_first_5_calls_warns(self):
        """No health check in first 5 calls should WARN."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"must_check_health_on_session_start": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                # Make 5 calls without health check
                for i in range(5):
                    _check_behavior_rules(
                        who="ceo",
                        tool_name="Write",
                        params={"file_path": f"file{i}.md", "content": "content"}
                    )

                # On 5th call, should warn
                assert mock_cieu.called
                # Find the health check warning
                for call in mock_cieu.call_args_list:
                    if call[1].get("rule_name") == "must_check_health_on_session_start":
                        assert call[1]["decision"] == "WARNING"
                        break

    def test_health_check_in_first_5_calls_passes(self):
        """Health check in first 5 calls should pass."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"must_check_health_on_session_start": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                # First call is health check
                _check_behavior_rules(
                    who="ceo",
                    tool_name="Read",
                    params={"file_path": "memory/learning_report.md"}
                )

                # Make 4 more calls
                for i in range(4):
                    _check_behavior_rules(
                        who="ceo",
                        tool_name="Write",
                        params={"file_path": f"file{i}.md", "content": "content"}
                    )

                # Should not have warned about health check
                for call in mock_cieu.call_args_list:
                    if call[1].get("rule_name") == "must_check_health_on_session_start":
                        assert False, "Should not warn when health check is present"


class TestAutonomousMissionRequiresArticle11:
    """Test autonomous_mission_requires_article_11 rule (Rule 9)."""

    def test_autonomous_mission_without_7_layers_denied(self):
        """Autonomous mission without 7-layer construction should be DENIED."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"autonomous_mission_requires_article_11": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Agent",
                    params={"agent": "cto", "task": "Autonomous Mission: Build new system"}
                )

                assert result is not None
                assert result.allowed is False
                assert "Article 11" in result.reason or "7-layer" in result.reason
                assert mock_cieu.called
                call_args = mock_cieu.call_args[1]
                assert call_args["decision"] == "DENY"

    def test_autonomous_mission_with_7_layers_allowed(self):
        """Autonomous mission with complete 7-layer construction should be ALLOWED."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"autonomous_mission_requires_article_11": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                # First do 7-layer construction
                layer_content = "\n".join([f"Layer {i}: Analysis for layer {i}" for i in range(8)])
                _check_behavior_rules(
                    who="ceo",
                    tool_name="Write",
                    params={"file_path": "construction.md", "content": layer_content}
                )

                # Then dispatch autonomous mission - should be allowed
                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Agent",
                    params={"agent": "cto", "task": "Autonomous Mission: Build system"}
                )

                assert result is None  # Allow
                assert mock_cieu.called
                # Find the ALLOW decision
                for call in mock_cieu.call_args_list:
                    if call[1].get("rule_name") == "autonomous_mission_requires_article_11":
                        assert call[1]["decision"] == "ALLOW"
                        assert call[1]["passed"] is True
                        break

    def test_non_autonomous_mission_not_checked(self):
        """Non-autonomous missions should not trigger Article 11 check."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"autonomous_mission_requires_article_11": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Agent",
                    params={"agent": "cto", "task": "Regular task: Fix bug"}
                )

                assert result is None  # Allow
                # Should not have triggered Article 11 check
                if mock_cieu.called:
                    for call in mock_cieu.call_args_list:
                        assert call[1].get("rule_name") != "autonomous_mission_requires_article_11"


class TestCompletionRequiresCIEUAudit:
    """Test completion_requires_cieu_audit rule (Rule 10)."""

    def test_completion_without_audit_warns(self):
        """Claiming completion without CIEU audit should WARN."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "cto": {"completion_requires_cieu_audit": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                result = _check_behavior_rules(
                    who="cto",
                    tool_name="Write",
                    params={"file_path": "report.md", "content": "Task completed. All bugs fixed."}
                )

                assert result is None  # Don't block
                assert mock_cieu.called
                call_args = mock_cieu.call_args[1]
                assert call_args["rule_name"] == "completion_requires_cieu_audit"
                assert call_args["decision"] == "WARNING"
                assert call_args["passed"] is False

    def test_completion_with_audit_passes(self):
        """Claiming completion with CIEU audit should pass."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "cto": {"completion_requires_cieu_audit": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                # First audit CIEU
                _check_behavior_rules(
                    who="cto",
                    tool_name="Bash",
                    params={"command": "gov_audit"}
                )

                # Then claim completion - should not warn
                result = _check_behavior_rules(
                    who="cto",
                    tool_name="Write",
                    params={"file_path": "report.md", "content": "Task completed. Rt=0 confirmed."}
                )

                assert result is None  # Don't block
                # Should not have warned about completion
                if mock_cieu.called:
                    for call in mock_cieu.call_args_list:
                        if call[1].get("rule_name") == "completion_requires_cieu_audit":
                            assert False, "Should not warn when CIEU audit is present"

    def test_non_completion_content_not_checked(self):
        """Content without completion markers should not trigger check."""
        from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
        _SESSION_TOOL_CALLS.clear()

        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "cto": {"completion_requires_cieu_audit": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                result = _check_behavior_rules(
                    who="cto",
                    tool_name="Write",
                    params={"file_path": "notes.md", "content": "Working on the bug fix..."}
                )

                assert result is None  # Don't block
                # Should not have checked completion rule
                if mock_cieu.called:
                    for call in mock_cieu.call_args_list:
                        assert call[1].get("rule_name") != "completion_requires_cieu_audit"


class TestPreCommitRequiresTest:
    """Test pre_commit_requires_test rule (CTO + eng-*)."""

    def test_commit_without_test_denied(self):
        """Git commit without prior test run should be DENIED."""
        config = {
            "agent_behavior_rules": {
                "cto": {"pre_commit_requires_test": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            # Reset session state
            from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
            _SESSION_TOOL_CALLS.clear()

            result = _check_behavior_rules(
                who="cto",
                tool_name="Bash",
                params={"command": "git commit -m 'fix bug'"}
            )
            assert result is not None
            assert result.allowed is False
            assert "without running tests" in result.reason

    def test_commit_with_test_allowed(self):
        """Git commit after test run should be ALLOWED."""
        config = {
            "agent_behavior_rules": {
                "cto": {"pre_commit_requires_test": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
            _SESSION_TOOL_CALLS.clear()

            # Simulate test run
            _check_behavior_rules(
                who="cto",
                tool_name="Bash",
                params={"command": "python -m pytest tests/"}
            )

            # Now commit should be allowed
            result = _check_behavior_rules(
                who="cto",
                tool_name="Bash",
                params={"command": "git commit -m 'fix bug'"}
            )
            assert result is None  # Allow

    def test_eng_kernel_commit_without_test_denied(self):
        """eng-kernel commit without test should be DENIED."""
        config = {
            "agent_behavior_rules": {
                "eng-kernel": {"pre_commit_requires_test": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            from ystar.adapters.boundary_enforcer import _SESSION_TOOL_CALLS
            _SESSION_TOOL_CALLS.clear()

            result = _check_behavior_rules(
                who="eng-kernel",
                tool_name="Bash",
                params={"command": "git commit -m 'add feature'"}
            )
            assert result is not None
            assert result.allowed is False


class TestSourceFirstFixes:
    """Test source_first_fixes rule (CTO + eng-*)."""

    def test_edit_site_packages_denied(self):
        """Editing site-packages should be DENIED."""
        config = {
            "agent_behavior_rules": {
                "cto": {"source_first_fixes": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="cto",
                tool_name="Edit",
                params={
                    "file_path": "/usr/local/lib/python3.11/site-packages/ystar/hook.py",
                    "old_string": "old",
                    "new_string": "new"
                }
            )
            assert result is not None
            assert result.allowed is False
            assert "source repository" in result.reason

    def test_edit_venv_denied(self):
        """Editing .venv should be DENIED."""
        config = {
            "agent_behavior_rules": {
                "cto": {"source_first_fixes": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="cto",
                tool_name="Write",
                params={
                    "file_path": ".venv/lib/python3.11/site-packages/ystar/hook.py",
                    "content": "new code"
                }
            )
            assert result is not None
            assert result.allowed is False

    def test_edit_source_repo_allowed(self):
        """Editing source repository should be ALLOWED."""
        config = {
            "agent_behavior_rules": {
                "cto": {"source_first_fixes": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="cto",
                tool_name="Edit",
                params={
                    "file_path": "/path/to/Y-star-gov/ystar/hook.py",
                    "old_string": "old",
                    "new_string": "new"
                }
            )
            assert result is None  # Allow


class TestBoardApprovalBeforePublish:
    """Test board_approval_before_publish rule (CMO, CSO)."""

    def test_outreach_without_approval_denied(self):
        """Writing to content/outreach/ without approval marker should be DENIED."""
        config = {
            "agent_behavior_rules": {
                "cmo": {"board_approval_before_publish": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="cmo",
                tool_name="Write",
                params={
                    "file_path": "content/outreach/linkedin_post.md",
                    "content": "Check out our new feature!"
                }
            )
            assert result is not None
            assert result.allowed is False
            assert "Board approval" in result.reason

    def test_outreach_with_approval_allowed(self):
        """Writing to content/outreach/ with approval marker should be ALLOWED."""
        config = {
            "agent_behavior_rules": {
                "cmo": {"board_approval_before_publish": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="cmo",
                tool_name="Write",
                params={
                    "file_path": "content/outreach/linkedin_post.md",
                    "content": "[BOARD_APPROVED]\n\nCheck out our new feature!"
                }
            )
            assert result is None  # Allow

    def test_non_outreach_path_allowed(self):
        """Writing to non-outreach paths should be ALLOWED without approval."""
        config = {
            "agent_behavior_rules": {
                "cmo": {"board_approval_before_publish": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            result = _check_behavior_rules(
                who="cmo",
                tool_name="Write",
                params={
                    "file_path": "content/drafts/ideas.md",
                    "content": "Working on new content idea..."
                }
            )
            assert result is None  # Allow


class TestContentLengthCheck:
    """Test content_length_check rule (CMO)."""

    def test_twitter_over_limit_warning(self):
        """Twitter content over 280 chars should trigger WARNING."""
        config = {
            "agent_behavior_rules": {
                "cmo": {"content_length_check": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                result = _check_behavior_rules(
                    who="cmo",
                    tool_name="Write",
                    params={
                        "file_path": "content/outreach/twitter/post1.md",
                        "content": "a" * 300  # Over 280 limit
                    }
                )
                assert result is None  # Don't block (WARNING only)
                # Should have recorded CIEU warning
                mock_cieu.assert_called_once()
                assert "content_length_check" in str(mock_cieu.call_args)

    def test_twitter_under_limit_no_warning(self):
        """Twitter content under 280 chars should not warn."""
        config = {
            "agent_behavior_rules": {
                "cmo": {"content_length_check": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                result = _check_behavior_rules(
                    who="cmo",
                    tool_name="Write",
                    params={
                        "file_path": "content/outreach/twitter/post1.md",
                        "content": "Short tweet"
                    }
                )
                assert result is None
                # Should not have recorded warning
                if mock_cieu.called:
                    for call in mock_cieu.call_args_list:
                        assert call[1].get("rule_name") != "content_length_check"


class TestRealConversationCountRequired:
    """Test real_conversation_count_required rule (CSO)."""

    def test_report_without_count_warning(self):
        """CSO report without conversation count should trigger WARNING."""
        config = {
            "agent_behavior_rules": {
                "cso": {"real_conversation_count_required": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                result = _check_behavior_rules(
                    who="cso",
                    tool_name="Write",
                    params={
                        "file_path": "reports/daily/2026-04-11.md",
                        "content": "Today I worked on sales strategy."
                    }
                )
                assert result is None  # Don't block (WARNING only)
                mock_cieu.assert_called_once()
                assert "real_conversation_count_required" in str(mock_cieu.call_args)

    def test_report_with_count_no_warning(self):
        """CSO report with conversation count should not warn."""
        config = {
            "agent_behavior_rules": {
                "cso": {"real_conversation_count_required": True}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                result = _check_behavior_rules(
                    who="cso",
                    tool_name="Write",
                    params={
                        "file_path": "reports/daily/2026-04-11.md",
                        "content": "Conversations: 3\nTalked to potential customers."
                    }
                )
                assert result is None
                # Should not have recorded warning
                if mock_cieu.called:
                    for call in mock_cieu.call_args_list:
                        assert call[1].get("rule_name") != "real_conversation_count_required"


class TestDirectiveDecomposeTimeout:
    """Test directive_decompose_timeout rule (CEO)."""

    def test_quick_decompose_no_warning(self):
        """Decomposing within timeout should not warn."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"directive_decompose_within_minutes": 10}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                from ystar.adapters.boundary_enforcer import _SESSION_START_TIME
                import ystar.adapters.boundary_enforcer as be
                be._SESSION_START_TIME = time.time()  # Reset session start

                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Write",
                    params={
                        "file_path": "DIRECTIVE_TRACKER.md",
                        "content": "New directive decomposition"
                    }
                )
                assert result is None
                # Should not have recorded warning
                if mock_cieu.called:
                    for call in mock_cieu.call_args_list:
                        assert call[1].get("rule_name") != "directive_decompose_timeout"

    def test_slow_decompose_warning(self):
        """Decomposing after timeout should trigger WARNING."""
        config = {
            "agent_behavior_rules": {
                "ceo": {"directive_decompose_within_minutes": 10}
            }
        }
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                import ystar.adapters.boundary_enforcer as be
                import time
                # Simulate session started 15 minutes ago
                be._SESSION_START_TIME = time.time() - (15 * 60)

                result = _check_behavior_rules(
                    who="ceo",
                    tool_name="Write",
                    params={
                        "file_path": "DIRECTIVE_TRACKER.md",
                        "content": "Late directive decomposition"
                    }
                )
                assert result is None  # Don't block (WARNING only)
                mock_cieu.assert_called_once()
                assert "directive_decompose_timeout" in str(mock_cieu.call_args)


class TestParallelDispatchRequired:
    """Test parallel_dispatch_required rule (CEO/CTO must dispatch engineers in parallel)."""

    def test_serial_dispatch_denied(self):
        """CEO dispatching 2 engineers serially (5s gap) → DENY"""
        config = {
            "agent_behavior_rules": {
                "ceo": {"parallel_dispatch_required": True}
            }
        }

        # Mock session start protocol to bypass boot check
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu"):
                with patch("ystar.adapters.boundary_enforcer._check_session_start_protocol_completed", return_value=None):
                    # First dispatch → allowed
                    result1 = _check_behavior_rules(
                        who="ceo",
                        tool_name="Agent",
                        params={"subagent_type": "eng-kernel"}
                    )
                    assert result1 is None  # Allow

                    # Wait 5 seconds (simulates serial dispatch)
                    time.sleep(5.1)

                    # Second dispatch → DENY (serial violation)
                    result2 = _check_behavior_rules(
                        who="ceo",
                        tool_name="Agent",
                        params={"subagent_type": "eng-platform"}
                    )
                    assert result2 is not None
                    assert result2.allowed is False
                    assert "parallel" in result2.reason.lower()
                    assert "same message batch" in result2.reason

    def test_parallel_dispatch_allowed(self):
        """CEO dispatching 2 engineers in same batch (<1s gap) → ALLOW"""
        config = {
            "agent_behavior_rules": {
                "ceo": {"parallel_dispatch_required": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu"):
                with patch("ystar.adapters.boundary_enforcer._check_session_start_protocol_completed", return_value=None):
                    # First dispatch
                    result1 = _check_behavior_rules(
                        who="ceo",
                        tool_name="Agent",
                        params={"subagent_type": "eng-kernel"}
                    )
                    assert result1 is None  # Allow

                    # Immediate second dispatch (<1s = same batch)
                    time.sleep(0.2)
                    result2 = _check_behavior_rules(
                        who="ceo",
                        tool_name="Agent",
                        params={"subagent_type": "eng-platform"}
                    )
                    assert result2 is None  # Allow (same batch)

    def test_large_gap_allowed(self):
        """CEO dispatching with >30s gap → ALLOW (different context)"""
        config = {
            "agent_behavior_rules": {
                "ceo": {"parallel_dispatch_required": True}
            }
        }

        # Note: This test would take 30s to run, so we mock the timing check instead
        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu"):
                with patch("ystar.adapters.boundary_enforcer._check_session_start_protocol_completed", return_value=None):
                    with patch("time.time") as mock_time:
                        # First dispatch at t=0
                        mock_time.return_value = 1000.0
                        result1 = _check_behavior_rules(
                            who="ceo",
                            tool_name="Agent",
                            params={"subagent_type": "eng-kernel"}
                        )
                        assert result1 is None

                        # Second dispatch at t=35s (>30s gap)
                        mock_time.return_value = 1035.0
                        result2 = _check_behavior_rules(
                            who="ceo",
                            tool_name="Agent",
                            params={"subagent_type": "eng-platform"}
                        )
                        assert result2 is None  # Allow (different battle)


class TestCEOSubstantiveResponseArticle11Trace:
    """Test CEO substantive response requires Article 11 trace (AMENDMENT-013)."""

    def test_ceo_write_report_without_l0_marker_warns(self):
        """CEO writing report without L0 marker should emit WARN."""
        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"article_11_always_on_substantive": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                with patch("ystar.adapters.boundary_enforcer._check_session_start_protocol_completed", return_value=None):
                    result = _check_behavior_rules(
                        who="ceo",
                        tool_name="Write",
                        params={
                            "file_path": "reports/strategic_plan.md",
                            "content": "We should decide to build this new feature. " * 50  # >500 chars
                        }
                    )

                    # Should not block (return None)
                    assert result is None
                    # But should have emitted CIEU warning
                    assert mock_cieu.called
                    call_args = mock_cieu.call_args[1]
                    assert call_args["rule_name"] == "ceo_substantive_response_requires_article_11_trace"
                    assert call_args["decision"] == "WARN"
                    assert call_args["passed"] is False

    def test_ceo_write_report_with_l0_marker_passes(self):
        """CEO writing report with L0 marker should pass."""
        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"article_11_always_on_substantive": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                with patch("ystar.adapters.boundary_enforcer._check_session_start_protocol_completed", return_value=None):
                    result = _check_behavior_rules(
                        who="ceo",
                        tool_name="Write",
                        params={
                            "file_path": "reports/strategic_plan.md",
                            "content": "L0 Intent: Build this feature. " + "Analysis follows. " * 50
                        }
                    )

                    assert result is None
                    assert mock_cieu.called
                    call_args = mock_cieu.call_args[1]
                    assert call_args["passed"] is True
                    assert call_args["decision"] == "PASS"

    def test_engineer_write_any_length_skipped(self):
        """Engineer writing reports should skip this check (CEO-only)."""
        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "eng-kernel": {"article_11_always_on_substantive": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                with patch("ystar.adapters.boundary_enforcer._check_session_start_protocol_completed", return_value=None):
                    result = _check_behavior_rules(
                        who="eng-kernel",
                        tool_name="Write",
                        params={
                            "file_path": "reports/technical_report.md",
                            "content": "We should design this architecture. " * 100
                        }
                    )

                    assert result is None
                    # Should not have triggered the rule (CEO-only)
                    if mock_cieu.called:
                        for call in mock_cieu.call_args_list:
                            assert call[1].get("rule_name") != "ceo_substantive_response_requires_article_11_trace"

    def test_ceo_trivial_response_skipped(self):
        """CEO trivial response (<500 chars, no strategic keywords) should skip check."""
        config = {
            "session_id": "test_session",
            "agent_behavior_rules": {
                "ceo": {"article_11_always_on_substantive": True}
            }
        }

        with patch("ystar.adapters.identity_detector._load_session_config", return_value=config):
            with patch("ystar.adapters.boundary_enforcer._record_behavior_rule_cieu") as mock_cieu:
                with patch("ystar.adapters.boundary_enforcer._check_session_start_protocol_completed", return_value=None):
                    result = _check_behavior_rules(
                        who="ceo",
                        tool_name="Write",
                        params={
                            "file_path": "reports/daily_log.md",
                            "content": "Completed task X today."  # Short, no strategic keywords
                        }
                    )

                    assert result is None
                    # Should not have triggered (not substantive)
                    if mock_cieu.called:
                        for call in mock_cieu.call_args_list:
                            assert call[1].get("rule_name") != "ceo_substantive_response_requires_article_11_trace"
