"""
tests/break_glass/test_forget_guard_break_glass.py
===================================================
INC-2026-04-23 Item #9 -- ForgetGuard break-glass bypass tests.
INC-2026-04-24 Item #9 live-fire fix: cross-process persistence + hook-wire compat.
"""
import json
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

BLOCK_PATTERN = "deploy forbidden zone"
ADVISORY_PATTERN = "draft informal note"

@pytest.fixture
def tmp_rules(tmp_path):
    rules_yaml = tmp_path / "forget_guard_rules.yaml"
    rules_yaml.write_text(yaml.dump({
        "rules": [
            {
                "name": "test_block_rule",
                "pattern": BLOCK_PATTERN,
                "mode": "deny",
                "message": "Cannot deploy to forbidden zone",
                "rationale": "Security boundary violation",
            },
            {
                "name": "test_advisory_rule",
                "pattern": ADVISORY_PATTERN,
                "mode": "warn",
                "message": "Informal notes should be reviewed",
                "rationale": "Quality drift",
            },
        ]
    }))
    return rules_yaml

@pytest.fixture
def guard(tmp_rules, tmp_path):
    hist = str(tmp_path / ".fg_deny_history_test.json")
    return ForgetGuard(
        rules_path=tmp_rules,
        rescue_mode_search_dirs=[str(tmp_path)],
        deny_history_path=hist,
    )

@pytest.fixture
def block_context():
    return {
        "agent_id": "alpha",
        "action_type": "deployment",
        "action_payload": "deploy forbidden zone staging cluster",
        "target_agent": "beta",
    }

@pytest.fixture
def advisory_context():
    return {
        "agent_id": "alpha",
        "action_type": "file_write",
        "action_payload": "draft informal note on topic",
        "target_agent": "",
    }

@pytest.fixture
def clean_context():
    return {
        "agent_id": "alpha",
        "action_type": "read",
        "action_payload": "reading a harmless file",
        "target_agent": "",
    }

class TestBaselineBehavior:
    def test_block_rule_fires(self, guard, block_context):
        result = guard.check(block_context)
        assert result is not None
        assert result["rule_name"] == "test_block_rule"
        assert result["mode"] == "deny"
        assert result["break_glass_downgrade"] is False

    def test_advisory_rule_fires(self, guard, advisory_context):
        result = guard.check(advisory_context)
        assert result is not None
        assert result["rule_name"] == "test_advisory_rule"
        assert result["mode"] == "warn"
        assert result["break_glass_downgrade"] is False

    def test_clean_context_passes(self, guard, clean_context):
        result = guard.check(clean_context)
        assert result is None

    def test_alias_keys_present_on_block(self, guard, block_context):
        result = guard.check(block_context)
        assert result is not None
        assert result["mode"] == "deny"
        assert result["rule_name"] == "test_block_rule"
        assert result["action"] == "deny"
        assert result["rule_id"] == "test_block_rule"
        assert result["recipe"] == "Cannot deploy to forbidden zone"
        assert result["severity"] == "high"

    def test_alias_keys_present_on_advisory(self, guard, advisory_context):
        result = guard.check(advisory_context)
        assert result is not None
        assert result["action"] == "warn"
        assert result["severity"] == "low"

class TestRescueModeBypass:
    def test_rescue_mode_flag_bypasses_block(self, guard, block_context, tmp_path):
        result = guard.check(block_context)
        assert result is not None
        assert result["mode"] == "deny"
        (tmp_path / BREAK_GLASS_FLAG).touch()
        result = guard.check(block_context)
        assert result is None

    def test_rescue_mode_flag_bypasses_advisory(self, guard, advisory_context, tmp_path):
        (tmp_path / BREAK_GLASS_FLAG).touch()
        result = guard.check(advisory_context)
        assert result is None

    def test_rescue_mode_removal_restores_enforcement(self, guard, block_context, tmp_path):
        flag_path = tmp_path / BREAK_GLASS_FLAG
        flag_path.touch()
        assert guard.check(block_context) is None
        flag_path.unlink()
        result = guard.check(block_context)
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
            deny_history_path=str(tmp_path / ".deny_hist_multi.json"),
        )
        ctx = {"agent_id": "alpha", "action_payload": "deploy forbidden zone now"}
        assert g.check(ctx) is not None
        (dir2 / BREAK_GLASS_FLAG).touch()
        assert g.check(ctx) is None

class TestConsecutiveBlockEscalation:
    def test_first_block_is_not_downgraded(self, guard, block_context):
        result = guard.check(block_context)
        assert result["mode"] == "deny"
        assert result["break_glass_downgrade"] is False

    def test_three_blocks_triggers_downgrade(self, guard, block_context):
        for i in range(CONSECUTIVE_DENY_THRESHOLD):
            result = guard.check(block_context)
            assert result["mode"] == "deny", f"Block #{i+1} should still block"
        result = guard.check(block_context)
        assert result["mode"] == "warn"
        assert result["break_glass_downgrade"] is True

    def test_advisory_rules_not_affected_by_block_threshold(self, guard, advisory_context, block_context):
        for _ in range(CONSECUTIVE_DENY_THRESHOLD + 1):
            guard.check(block_context)
        result = guard.check(advisory_context)
        assert result["mode"] == "warn"
        assert result["break_glass_downgrade"] is False

    def test_block_history_expires_after_window(self, guard, block_context):
        expired_ts = time.time() - CONSECUTIVE_DENY_WINDOW_SECS - 10
        guard._deny_history["alpha"] = [
            (expired_ts, "test_block_rule")
            for _ in range(CONSECUTIVE_DENY_THRESHOLD + 5)
        ]
        result = guard.check(block_context)
        assert result["mode"] == "deny"
        assert result["break_glass_downgrade"] is False

    def test_block_history_per_agent(self, guard, block_context):
        guard._deny_history["other-agent"] = [
            (time.time(), "test_block_rule")
            for _ in range(CONSECUTIVE_DENY_THRESHOLD + 5)
        ]
        result = guard.check(block_context)
        assert result["mode"] == "deny"
        assert result["break_glass_downgrade"] is False

    def test_empty_agent_id_no_crash(self, guard):
        ctx = {"agent_id": "", "action_payload": "deploy forbidden zone"}
        result = guard.check(ctx)
        if result is not None:
            assert "break_glass_downgrade" in result

class TestCrossProcessPersistence:
    def test_history_persisted_to_file(self, tmp_rules, tmp_path, block_context):
        hist = str(tmp_path / ".fg_deny_hist_persist.json")
        g = ForgetGuard(
            rules_path=tmp_rules,
            rescue_mode_search_dirs=[str(tmp_path)],
            deny_history_path=hist,
        )
        result = g.check(block_context)
        assert result["mode"] == "deny"
        assert os.path.isfile(hist), "History file not written to disk"
        with open(hist) as f:
            raw = json.load(f)
        assert "alpha" in raw
        assert len(raw["alpha"]) == 1

    def test_new_instance_reads_persisted_history(self, tmp_rules, tmp_path, block_context):
        hist = str(tmp_path / ".fg_deny_hist_cross.json")
        for _ in range(CONSECUTIVE_DENY_THRESHOLD):
            g = ForgetGuard(
                rules_path=tmp_rules,
                rescue_mode_search_dirs=[str(tmp_path)],
                deny_history_path=hist,
            )
            result = g.check(block_context)
            assert result["mode"] == "deny"
        g2 = ForgetGuard(
            rules_path=tmp_rules,
            rescue_mode_search_dirs=[str(tmp_path)],
            deny_history_path=hist,
        )
        result = g2.check(block_context)
        assert result["mode"] == "warn", "Cross-process downgrade did not fire"
        assert result["break_glass_downgrade"] is True

    def test_expired_entries_pruned_on_load(self, tmp_rules, tmp_path, block_context):
        hist = str(tmp_path / ".fg_deny_hist_expire.json")
        expired_ts = time.time() - CONSECUTIVE_DENY_WINDOW_SECS - 60
        with open(hist, "w") as f:
            json.dump({"alpha": [[expired_ts, "test_block_rule"]] * (CONSECUTIVE_DENY_THRESHOLD + 5)}, f)
        g = ForgetGuard(
            rules_path=tmp_rules,
            rescue_mode_search_dirs=[str(tmp_path)],
            deny_history_path=hist,
        )
        result = g.check(block_context)
        assert result["mode"] == "deny", "Expired entries should not trigger downgrade"
        assert result["break_glass_downgrade"] is False

    def test_corrupted_file_fails_open(self, tmp_rules, tmp_path, block_context):
        hist = str(tmp_path / ".fg_deny_hist_corrupt.json")
        with open(hist, "w") as f:
            f.write("NOT VALID JSON {{{}")
        g = ForgetGuard(
            rules_path=tmp_rules,
            rescue_mode_search_dirs=[str(tmp_path)],
            deny_history_path=hist,
        )
        result = g.check(block_context)
        assert result is not None
        assert result["mode"] == "deny"

class TestHookWireContextKeys:
    def test_match_via_tool_input_dict(self, guard):
        ctx = {
            "agent_id": "alpha",
            "tool": "Bash",
            "tool_input": {"command": "deploy forbidden zone staging"},
        }
        result = guard.check(ctx)
        assert result is not None
        assert result["rule_name"] == "test_block_rule"

    def test_match_via_command_key(self, guard):
        ctx = {"agent_id": "alpha", "tool": "Bash", "command": "deploy forbidden zone"}
        result = guard.check(ctx)
        assert result is not None

    def test_match_via_file_path_key(self, guard):
        # file_path uses underscores; content key carries the payload text
        ctx = {"agent_id": "alpha", "tool": "Write", "file_path": "/tmp/output.py", "content": "deploy forbidden zone"}
        result = guard.check(ctx)
        assert result is not None

    def test_active_agent_alias(self, guard):
        ctx = {"active_agent": "alpha", "action_payload": "deploy forbidden zone"}
        result = guard.check(ctx)
        assert result is not None

class TestBreakGlassInteraction:
    def test_rescue_mode_trumps_escalation(self, guard, block_context, tmp_path):
        for _ in range(CONSECUTIVE_DENY_THRESHOLD + 1):
            guard.check(block_context)
        (tmp_path / BREAK_GLASS_FLAG).touch()
        result = guard.check(block_context)
        assert result is None

class TestImportSmoke:
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
