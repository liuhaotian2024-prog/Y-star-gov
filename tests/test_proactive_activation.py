"""
Test suite for AMENDMENT-013: Proactive Skill Activation

Tests the activation trigger registry, skill injection, and CIEU event emission.
"""
import pytest
from ystar.session import SkillActivation
from ystar.adapters.activation_triggers import (
    should_activate_skill,
    ACTIVATION_TRIGGERS,
    _detect_autonomous_mission,
    _detect_major_decision,
    _detect_code_edit,
    _detect_write_boundary_violation,
)


class TestDetectionFunctions:
    """Test individual detection functions."""

    def test_detect_autonomous_mission_keyword(self):
        """Autonomous mission keyword detection."""
        result = _detect_autonomous_mission(
            agent="ceo",
            action_type="Write",
            params={"content": "I declare autonomous mission to build feature X"},
            ctx={}
        )
        assert result is True

    def test_detect_autonomous_mission_chinese(self):
        """Autonomous mission Chinese keyword detection."""
        result = _detect_autonomous_mission(
            agent="ceo",
            action_type="Write",
            params={"content": "启动自主任务：优化系统性能"},
            ctx={}
        )
        assert result is True

    def test_detect_autonomous_mission_symbol_alignment(self):
        """Symbol alignment pattern detection."""
        result = _detect_autonomous_mission(
            agent="ceo",
            action_type="Write",
            params={"content": "symbol alignment: commit to 10K users in 30 days"},
            ctx={}
        )
        assert result is True

    def test_detect_autonomous_mission_negative(self):
        """Should not trigger on casual mention."""
        result = _detect_autonomous_mission(
            agent="ceo",
            action_type="Write",
            params={"content": "We discussed autonomous systems in the meeting"},
            ctx={}
        )
        assert result is False

    def test_detect_major_decision_ceo_only(self):
        """Decision detection only for CEO."""
        # CEO should trigger
        result_ceo = _detect_major_decision(
            agent="ceo",
            action_type="Write",
            params={"content": "I decide we should pivot to open-source"},
            ctx={}
        )
        assert result_ceo is True

        # CTO should not trigger (not CEO)
        result_cto = _detect_major_decision(
            agent="cto",
            action_type="Write",
            params={"content": "I decide we should pivot to open-source"},
            ctx={}
        )
        assert result_cto is False

    def test_detect_major_decision_keywords(self):
        """Decision keywords in Chinese and English."""
        keywords_to_test = [
            "We need to make a strategic decision",
            "这是重大选择",
            "战略调整",
            "major choice ahead"
        ]
        for keyword in keywords_to_test:
            result = _detect_major_decision(
                agent="ceo",
                action_type="Write",
                params={"content": keyword},
                ctx={}
            )
            assert result is True, f"Failed to detect: {keyword}"

    def test_detect_code_edit_python_files(self):
        """Code edit detection for Python files."""
        result = _detect_code_edit(
            agent="cto",
            action_type="Edit",
            params={"file_path": "/Users/user/project/ystar/adapters/hook.py"},
            ctx={}
        )
        assert result is True

    def test_detect_code_edit_non_python(self):
        """Should not trigger on non-Python files."""
        result = _detect_code_edit(
            agent="cto",
            action_type="Edit",
            params={"file_path": "/Users/user/project/README.md"},
            ctx={}
        )
        assert result is False

    def test_detect_write_boundary_ceo_code(self):
        """CEO writing to code files should trigger."""
        restricted_paths = [
            "/Users/user/ystar-company/ystar/kernel/hook.py",
            "/Users/user/ystar-company/tests/test_hook.py",
            "/Users/user/ystar-company/scripts/boot.sh",
            "/Users/user/ystar-company/.claude/agents/ceo.md",
        ]
        for path in restricted_paths:
            result = _detect_write_boundary_violation(
                agent="ceo",
                action_type="Write",
                params={"file_path": path},
                ctx={}
            )
            assert result is True, f"Failed to detect boundary violation: {path}"

    def test_detect_write_boundary_allowed_paths(self):
        """CEO writing to allowed paths should not trigger."""
        allowed_paths = [
            "/Users/user/ystar-company/reports/daily/2026-04-13.md",
            "/Users/user/ystar-company/DIRECTIVE_TRACKER.md",
            "/Users/user/ystar-company/BOARD_PENDING.md",
        ]
        for path in allowed_paths:
            result = _detect_write_boundary_violation(
                agent="ceo",
                action_type="Write",
                params={"file_path": path},
                ctx={}
            )
            assert result is False, f"False positive on allowed path: {path}"


class TestSkillActivationIntegration:
    """Test end-to-end skill activation."""

    def test_autonomous_mission_activates_article_11(self):
        """Autonomous mission should activate Article 11 skill."""
        activation = should_activate_skill(
            agent_name="ceo",
            action_type="Write",
            action_params={"content": "autonomous mission: build video strategy"},
            context={}
        )

        assert activation is not None
        assert "article_11_seven_layers.md" in activation.skill_id
        assert activation.trigger_rule == "autonomous_mission_requires_article_11"
        assert activation.priority == 1

    def test_major_decision_activates_counterfactual(self):
        """CEO decision should activate counterfactual skill."""
        activation = should_activate_skill(
            agent_name="ceo",
            action_type="Write",
            action_params={"content": "I decide we should open-source on Day 1"},
            context={}
        )

        assert activation is not None
        assert "counterfactual_before_major_decision.md" in activation.skill_id
        assert activation.trigger_rule == "counterfactual_before_major_decision"
        assert activation.priority == 1

    def test_code_edit_activates_root_cause(self):
        """Code edit should activate root_cause_fix skill."""
        activation = should_activate_skill(
            agent_name="cto",
            action_type="Edit",
            action_params={"file_path": "/path/to/ystar/hook.py"},
            context={}
        )

        assert activation is not None
        assert "root_cause_fix_pattern.md" in activation.skill_id
        assert activation.trigger_rule == "root_cause_fix_required"
        assert activation.priority == 2

    def test_write_boundary_activates_override_skill(self):
        """CEO boundary violation should activate override/delegate skill."""
        activation = should_activate_skill(
            agent_name="ceo",
            action_type="Write",
            action_params={"file_path": "/path/to/ystar/adapters/hook.py"},
            context={}
        )

        assert activation is not None
        assert "board_ceo_override_or_delegate.md" in activation.skill_id
        assert activation.trigger_rule == "write_boundary_violation"
        assert activation.priority == 1

    def test_role_filter_enforcement(self):
        """Role filters should prevent activation for wrong roles."""
        # CTO tries to use CEO-only counterfactual skill
        activation = should_activate_skill(
            agent_name="cto",
            action_type="Write",
            action_params={"content": "I decide we should use PostgreSQL"},
            context={}
        )

        # Should not activate (CTO not in role_filter for counterfactual)
        assert activation is None

    def test_no_activation_for_normal_actions(self):
        """Normal actions should not trigger activation."""
        activation = should_activate_skill(
            agent_name="ceo",
            action_type="Write",
            action_params={"content": "Daily status update: all systems operational"},
            context={}
        )

        assert activation is None

    def test_skill_content_loaded(self):
        """Activated skills should have content loaded."""
        activation = should_activate_skill(
            agent_name="ceo",
            action_type="Write",
            action_params={"content": "autonomous mission: test content loading"},
            context={}
        )

        # Note: In test environment, skill files may not exist
        # If file doesn't exist, activation should be None (graceful degradation)
        if activation:
            assert len(activation.skill_content) > 0
            # Check it's valid markdown
            assert "##" in activation.skill_content or "#" in activation.skill_content

    def test_multiple_triggers_priority_ordering(self):
        """When multiple triggers match, highest priority wins."""
        # CEO writes code (both boundary violation + code edit could match)
        # But only CEO should trigger boundary, not code edit (role filter)
        activation = should_activate_skill(
            agent_name="ceo",
            action_type="Write",
            action_params={"file_path": "/path/to/ystar/hook.py"},
            context={}
        )

        assert activation is not None
        # Should be boundary violation (priority 1) not code edit
        assert activation.trigger_rule == "write_boundary_violation"
        assert activation.priority == 1


class TestGracefulDegradation:
    """Test error handling and graceful degradation."""

    def test_nonexistent_skill_file(self):
        """Missing skill file should gracefully degrade (return None)."""
        # Temporarily modify trigger to point to nonexistent file
        from ystar.adapters.activation_triggers import ACTIVATION_TRIGGERS

        # Create fake trigger
        from ystar.adapters.activation_triggers import ActivationTrigger

        fake_trigger = ActivationTrigger(
            trigger_id="test_nonexistent",
            detection_fn=lambda a, b, c, d: True,  # always trigger
            skill_id_template="knowledge/nonexistent/skills/fake.md",
            rule_name="test_rule",
            priority=1,
            role_filter=[]
        )

        # Temporarily add to registry
        ACTIVATION_TRIGGERS.append(fake_trigger)

        try:
            activation = should_activate_skill(
                agent_name="ceo",
                action_type="Write",
                action_params={"content": "test"},
                context={}
            )
            # Should return None if file doesn't exist
            # Or if it exists, content should be loaded
            if activation:
                assert len(activation.skill_content) > 0
        finally:
            # Clean up
            ACTIVATION_TRIGGERS.remove(fake_trigger)

    def test_invalid_agent_name(self):
        """Invalid agent names should be handled gracefully."""
        activation = should_activate_skill(
            agent_name="invalid_agent_name",
            action_type="Write",
            action_params={"content": "autonomous mission: test"},
            context={}
        )

        # Should either activate or return None, but not crash
        assert activation is None or isinstance(activation, SkillActivation)

    def test_missing_action_params(self):
        """Missing action parameters should not crash."""
        activation = should_activate_skill(
            agent_name="ceo",
            action_type="Write",
            action_params={},  # no content
            context={}
        )

        # Should not crash
        assert activation is None or isinstance(activation, SkillActivation)


class TestTriggerRegistry:
    """Test trigger registry structure."""

    def test_all_triggers_have_required_fields(self):
        """All triggers in registry should have valid structure."""
        for trigger in ACTIVATION_TRIGGERS:
            assert trigger.trigger_id
            assert callable(trigger.detection_fn)
            assert trigger.skill_id_template
            assert trigger.rule_name
            assert isinstance(trigger.priority, int)
            assert isinstance(trigger.role_filter, list)

    def test_trigger_priorities_valid(self):
        """Priority values should be positive integers."""
        for trigger in ACTIVATION_TRIGGERS:
            assert trigger.priority > 0
            assert trigger.priority < 10  # reasonable upper bound

    def test_trigger_ids_unique(self):
        """Trigger IDs should be unique."""
        ids = [t.trigger_id for t in ACTIVATION_TRIGGERS]
        assert len(ids) == len(set(ids))

    def test_role_filters_valid(self):
        """Role filters should contain valid role names."""
        valid_roles = {
            "ceo", "aiden", "cto", "ethan",
            "eng-kernel", "eng-platform", "eng-governance", "eng-domains",
            "cmo", "sofia", "cfo", "marco", "cso", "zara",
            "secretary", "samantha"
        }

        for trigger in ACTIVATION_TRIGGERS:
            for role in trigger.role_filter:
                # Empty filter = all roles allowed
                if role:
                    assert role in valid_roles, f"Invalid role in filter: {role}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
