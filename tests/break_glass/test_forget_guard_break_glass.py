"""
tests/break_glass/test_forget_guard_break_glass.py
===================================================
INC-2026-04-23 Item #9 — ForgetGuard CEO break-glass bypass tests.

Two break-glass mechanisms:
1. .k9_rescue_mode flag file: full bypass (return None)
2. 3+ consecutive DENYs in 5 min: downgrade deny -> warn (lock-death prevention)
"""
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from ystar.governance.forget_guard import (
    ForgetGuard,
    ForgetGuardRule,
    check_forget_violation,
    get_guard,
    BREAK_GLASS_FLAG,
    CONSECUTIVE_DENY_THRESHOLD,
    CONSECUTIVE_DENY_WINDOW_SECS,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_rules(tmp_path):
    """Create a minimal rules YAML with one deny rule for testing."""
    rules_yaml = tmp_path / "forget_guard_rules.yaml"
    rules_yaml.write_text(yaml.dump({
        "rules": [
            {
                "name": "test_deny_rule",
                "pattern": "ceo assigns code",
                "mode": "deny",
                "message": "CEO must not directly assign code tasks",
                "rationale": "Hierarchy violation",
            },
            {
                "name": "test_warn_rule",
                "pattern": "ceo writes readme",
                "mode": "warn",
                "message": "CEO should not write README files",
                "rationale": "Scope drift",
            },
        ]
    }))
    return rules_yaml


@pytest.fixture
def guard(tmp_rules, tmp_path):
    """ForgetGuard with tmp rules and tmp rescue_mode search dir."""
    return ForgetGuard(
        rules_path=tmp_rules,
        rescue_mode_search_dirs=[str(tmp_path)],
    )


@pytest.fixture
def deny_context():
    """Context that matches the test_deny_rule."""
    return {
        "agent_id": "ceo",
        "action_type": "task_assignment",
        "action_payload": "ceo assigns code task to eng-kernel",
        "target_agent": "eng-kernel",
    }


@pytest.fixture
def warn_context():
    """Context that matches the test_warn_rule."""
    return {
        "agent_id": "ceo",
        "action_type": "file_write",
        "action_payload": "ceo writes readme documentation",
        "target_agent": "",
    }


@pytest.fixture
def clean_context():
    """Context that matches no rules."""
    return {
        "agent_id": "ceo",
        "action_type": "read",
        "action_payload": "reading a file",
        "target_agent": "",
    }


# ── Test: baseline behavior (no break-glass) ────────────────────────────────

class TestBaselineBehavior:
    """Verify ForgetGuard works normally without break-glass triggers."""

    def test_deny_rule_fires(self, guard, deny_context):
        result = guard.check(deny_context)
        assert result is not None
        assert result["rule_name"] == "test_deny_rule"
        assert result["mode"] == "deny"
        assert result["break_glass_downgrade"] is False

    def test_warn_rule_fires(self, guard, warn_context):
        result = guard.check(warn_context)
        assert result is not None
        assert result["rule_name"] == "test_warn_rule"
        assert result["mode"] == "warn"
        assert result["break_glass_downgrade"] is False

    def test_clean_context_passes(self, guard, clean_context):
        result = guard.check(clean_context)
        assert result is None


# ── Test: .k9_rescue_mode flag bypass ────────────────────────────────────────

class TestRescueModeBypass:
    """Break-glass #1: .k9_rescue_mode flag file causes full bypass."""

    def test_rescue_mode_flag_bypasses_deny(self, guard, deny_context, tmp_path):
        # Without flag: deny fires
        result = guard.check(deny_context)
        assert result is not None
        assert result["mode"] == "deny"

        # Create flag
        (tmp_path / BREAK_GLASS_FLAG).touch()

        # With flag: full bypass (None)
        result = guard.check(deny_context)
        assert result is None

    def test_rescue_mode_flag_bypasses_warn(self, guard, warn_context, tmp_path):
        (tmp_path / BREAK_GLASS_FLAG).touch()
        result = guard.check(warn_context)
        assert result is None

    def test_rescue_mode_removal_restores_enforcement(self, guard, deny_context, tmp_path):
        flag_path = tmp_path / BREAK_GLASS_FLAG
        flag_path.touch()

        # Bypass active
        assert guard.check(deny_context) is None

        # Remove flag
        flag_path.unlink()

        # Enforcement restored
        result = guard.check(deny_context)
        assert result is not None
        assert result["mode"] == "deny"

    def test_rescue_mode_checks_multiple_dirs(self, tmp_rules, tmp_path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        g = ForgetGuard(
            rules_path=tmp_rules,
            rescue_mode_search_dirs=[str(dir1), str(dir2)],
        )
        ctx = {
            "agent_id": "ceo",
            "action_payload": "ceo assigns code task",
        }

        # No flag in either dir
        assert g.check(ctx) is not None

        # Flag in second dir
        (dir2 / BREAK_GLASS_FLAG).touch()
        assert g.check(ctx) is None


# ── Test: consecutive deny escalation ────────────────────────────────────────

class TestConsecutiveDenyEscalation:
    """Break-glass #2: 3+ consecutive DENYs in 5min -> deny downgraded to warn."""

    def test_first_deny_is_not_downgraded(self, guard, deny_context):
        result = guard.check(deny_context)
        assert result["mode"] == "deny"
        assert result["break_glass_downgrade"] is False

    def test_three_denies_triggers_downgrade(self, guard, deny_context):
        # First 3 denies accumulate
        for i in range(CONSECUTIVE_DENY_THRESHOLD):
            result = guard.check(deny_context)
            assert result["mode"] == "deny", f"Deny #{i+1} should still be deny"

        # 4th check: threshold reached, downgrade to warn
        result = guard.check(deny_context)
        assert result["mode"] == "warn"
        assert result["break_glass_downgrade"] is True

    def test_warn_rules_not_affected_by_deny_threshold(self, guard, warn_context, deny_context):
        # Accumulate denies
        for _ in range(CONSECUTIVE_DENY_THRESHOLD + 1):
            guard.check(deny_context)

        # Warn rule should still be warn (not affected by deny tracking)
        result = guard.check(warn_context)
        assert result["mode"] == "warn"
        assert result["break_glass_downgrade"] is False

    def test_deny_history_expires_after_window(self, guard, deny_context):
        # Accumulate denies with timestamps in the past
        expired_ts = time.time() - CONSECUTIVE_DENY_WINDOW_SECS - 10
        guard._deny_history["ceo"] = [
            (expired_ts, "test_deny_rule")
            for _ in range(CONSECUTIVE_DENY_THRESHOLD + 5)
        ]

        # Despite many old entries, they're expired — no downgrade
        result = guard.check(deny_context)
        assert result["mode"] == "deny"
        assert result["break_glass_downgrade"] is False

    def test_deny_history_per_agent(self, guard, deny_context):
        # Accumulate denies for different agent
        guard._deny_history["other-agent"] = [
            (time.time(), "test_deny_rule")
            for _ in range(CONSECUTIVE_DENY_THRESHOLD + 5)
        ]

        # CEO has no deny history — no downgrade
        result = guard.check(deny_context)
        assert result["mode"] == "deny"
        assert result["break_glass_downgrade"] is False

    def test_empty_agent_id_no_crash(self, guard):
        """Ensure break-glass logic doesn't crash on empty agent_id."""
        ctx = {
            "agent_id": "",
            "action_payload": "ceo assigns code task",
        }
        result = guard.check(ctx)
        # Should match rule but not crash on empty agent_id
        if result is not None:
            assert "break_glass_downgrade" in result


# ── Test: break-glass interaction ────────────────────────────────────────────

class TestBreakGlassInteraction:
    """Test interaction between rescue mode and consecutive deny."""

    def test_rescue_mode_trumps_deny_escalation(self, guard, deny_context, tmp_path):
        """Rescue mode is checked first — even with deny history, full bypass wins."""
        # Accumulate deny history
        for _ in range(CONSECUTIVE_DENY_THRESHOLD + 1):
            guard.check(deny_context)

        # Enable rescue mode
        (tmp_path / BREAK_GLASS_FLAG).touch()

        # Rescue mode wins — full bypass
        result = guard.check(deny_context)
        assert result is None


# ── Test: smoke import from ystar-company context ────────────────────────────

class TestImportSmoke:
    """Verify the module imports cleanly."""

    def test_forget_guard_class_importable(self):
        from ystar.governance.forget_guard import ForgetGuard
        assert ForgetGuard is not None

    def test_check_forget_violation_importable(self):
        from ystar.governance.forget_guard import check_forget_violation
        assert callable(check_forget_violation)

    def test_constants_exported(self):
        from ystar.governance.forget_guard import (
            BREAK_GLASS_FLAG,
            CONSECUTIVE_DENY_THRESHOLD,
            CONSECUTIVE_DENY_WINDOW_SECS,
        )
        assert BREAK_GLASS_FLAG == ".k9_rescue_mode"
        assert CONSECUTIVE_DENY_THRESHOLD == 3
        assert CONSECUTIVE_DENY_WINDOW_SECS == 300
