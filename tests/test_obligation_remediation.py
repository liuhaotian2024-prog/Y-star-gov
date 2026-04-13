"""
tests/test_obligation_remediation.py — Obligation Remediation Coverage Tests
=============================================================================

Verifies that all 9 obligation types from contract.obligation_timing have
structured remediation payloads (AMENDMENT-012 extension, Jordan commit).

Context: governance_self_deadlock_20260413.md — CEO got hard-locked for 35 min
when directive_acknowledgement went overdue but had no remediation telling CEO
how to fix. This test prevents regression.
"""
import pytest
from ystar.governance.obligation_remediation import (
    OBLIGATION_REMEDIATION_MAP,
    get_obligation_remediation,
    get_obligation_remediation_safe,
)
from ystar.session import Remediation


# The 9 obligation types from .ystar_session.json contract.obligation_timing
REQUIRED_OBLIGATION_TYPES = [
    "directive_acknowledgement",
    "intent_declaration",
    "progress_update",
    "task_completion_report",
    "knowledge_update",
    "theory_library_daily",
    "autonomous_daily_report",
    "gemma_session_daily",
    "weekly_roadmap_audit",
]


class TestObligationRemediationCoverage:
    """Test that all 9 obligation types have remediation."""

    def test_all_9_obligation_types_have_remediation(self):
        """Every obligation type in contract.obligation_timing has remediation."""
        for obligation_type in REQUIRED_OBLIGATION_TYPES:
            assert obligation_type in OBLIGATION_REMEDIATION_MAP, (
                f"Obligation type '{obligation_type}' missing from OBLIGATION_REMEDIATION_MAP. "
                f"governance_self_deadlock_20260413.md: denials without remediation cause hard locks."
            )

    def test_get_obligation_remediation_returns_remediation_object(self):
        """get_obligation_remediation() returns Remediation for all 9 types."""
        for obligation_type in REQUIRED_OBLIGATION_TYPES:
            rem = get_obligation_remediation(obligation_type)
            assert isinstance(rem, Remediation), (
                f"get_obligation_remediation('{obligation_type}') returned {type(rem)}, expected Remediation"
            )

    def test_get_obligation_remediation_safe_returns_none_for_unknown(self):
        """get_obligation_remediation_safe() returns None for unknown types (graceful)."""
        rem = get_obligation_remediation_safe("nonexistent_obligation_type_xyz")
        assert rem is None

    def test_get_obligation_remediation_safe_returns_remediation_for_known(self):
        """get_obligation_remediation_safe() returns Remediation for known types."""
        rem = get_obligation_remediation_safe("directive_acknowledgement")
        assert isinstance(rem, Remediation)


class TestRemediationStructureQuality:
    """Test that remediations are actionable, not generic."""

    def test_directive_acknowledgement_has_executable_steps(self):
        """directive_acknowledgement remediation has concrete fix (not 'fulfill obligation')."""
        rem = get_obligation_remediation("directive_acknowledgement")

        # Must have executable Python command or specific next step
        assert any("python3" in step or "emit_event" in step for step in rem.correct_steps), (
            "directive_acknowledgement remediation must include executable emit_event command. "
            "Lesson: governance_self_deadlock_20260413.md — generic 'fulfill obligation' caused 35-min lock."
        )

        # Must NOT be generic
        assert not any("fulfill" in step.lower() and "obligation" in step.lower() for step in rem.correct_steps), (
            "Remediation should be specific, not generic 'fulfill obligation'"
        )

    def test_all_remediations_have_required_fields(self):
        """Every remediation has all required Remediation fields."""
        for obligation_type in REQUIRED_OBLIGATION_TYPES:
            rem = get_obligation_remediation(obligation_type)

            assert rem.wrong_action, f"{obligation_type}: wrong_action must be non-empty"
            assert rem.correct_steps, f"{obligation_type}: correct_steps must be non-empty list"
            assert rem.rule_name == obligation_type, f"{obligation_type}: rule_name must match obligation_type"
            assert rem.rule_context, f"{obligation_type}: rule_context must explain why this rule exists"

            # skill_ref should point to knowledge/ or be None (if constitutional)
            if rem.skill_ref:
                assert "knowledge/" in rem.skill_ref, (
                    f"{obligation_type}: skill_ref should point to knowledge/ path"
                )

    def test_all_remediations_have_context_not_just_commands(self):
        """Remediation includes 'why' context, not just 'how' commands."""
        for obligation_type in REQUIRED_OBLIGATION_TYPES:
            rem = get_obligation_remediation(obligation_type)

            # rule_context must be non-trivial (>20 chars, explains purpose)
            assert len(rem.rule_context) > 20, (
                f"{obligation_type}: rule_context too short, should explain purpose"
            )

            # Should explain consequence or purpose
            context_lower = rem.rule_context.lower()
            has_purpose = any(word in context_lower for word in [
                "prevent", "ensure", "avoid", "maintain", "guarantee", "enforce"
            ])
            assert has_purpose, (
                f"{obligation_type}: rule_context should explain purpose/consequence"
            )

    def test_correct_steps_are_executable_not_abstract(self):
        """correct_steps contain concrete commands/code, not abstract guidance."""
        for obligation_type in REQUIRED_OBLIGATION_TYPES:
            rem = get_obligation_remediation(obligation_type)

            # At least one step should have:
            # - A command (python3, bash, grep, etc.)
            # - A file path (knowledge/, reports/, scripts/)
            # - Or a concrete action verb (write, update, run, emit)

            has_concrete_step = False
            for step in rem.correct_steps:
                if any(marker in step for marker in [
                    "python3", "bash", "grep", "emit_event", "knowledge/", "reports/",
                    "scripts/", ".md", ".py", "write", "update", "run"
                ]):
                    has_concrete_step = True
                    break

            assert has_concrete_step, (
                f"{obligation_type}: correct_steps should include at least one concrete command/path/action. "
                f"Got: {rem.correct_steps[:2]}"
            )

    def test_lesson_ref_points_to_governance_self_deadlock_for_directive_ack(self):
        """directive_acknowledgement remediation cites the incident that motivated it."""
        rem = get_obligation_remediation("directive_acknowledgement")

        assert rem.lesson_ref is not None, (
            "directive_acknowledgement must cite governance_self_deadlock_20260413.md as lesson"
        )
        assert "governance_self_deadlock" in rem.lesson_ref or "20260413" in rem.lesson_ref, (
            f"directive_acknowledgement lesson_ref should point to governance_self_deadlock incident. "
            f"Got: {rem.lesson_ref}"
        )


class TestRemediationIntegrationReady:
    """Test that remediations are ready for InterventionEngine integration."""

    def test_remediation_serializable_for_hook_response(self):
        """Remediation can be converted to dict for hook denial responses."""
        rem = get_obligation_remediation("directive_acknowledgement")

        # Should have all fields accessible
        d = {
            "wrong_action": rem.wrong_action,
            "correct_steps": rem.correct_steps,
            "skill_ref": rem.skill_ref,
            "lesson_ref": rem.lesson_ref,
            "rule_name": rem.rule_name,
            "rule_context": rem.rule_context,
        }

        assert all(isinstance(v, (str, list, type(None))) for v in d.values()), (
            "All Remediation fields should be str/list/None for serialization"
        )

    def test_remediation_map_keys_match_obligation_timing_convention(self):
        """OBLIGATION_REMEDIATION_MAP keys use snake_case matching .ystar_session.json."""
        for key in OBLIGATION_REMEDIATION_MAP.keys():
            # Snake_case convention
            assert key.islower(), f"Obligation type key '{key}' should be lowercase snake_case"
            assert " " not in key, f"Obligation type key '{key}' should not have spaces"

            # No camelCase or PascalCase
            assert key == key.lower(), f"Obligation type key '{key}' should be lowercase"
