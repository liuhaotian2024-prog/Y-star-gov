"""
test_forget_guard_none_safe.py
==============================
INC-2026-04-23 Item #3: Verify ForgetGuard does not crash when context
fields are None or tool_input has no file_path key.

Root cause: check_forget_violation() called with context dict whose values
could be None (e.g., file_path=None from payload.get("tool_input", {}).get("file_path")).
Pattern matching in _matches_pattern called .startswith() on None-valued fields.

Fix: Defensive `or ""` coercion on all context.get() calls in check() and
_matches_pattern(), plus `or ""` on pattern loading in _load_rules().
"""
import pytest
from pathlib import Path
from ystar.governance.forget_guard import (
    ForgetGuard,
    ForgetGuardRule,
    check_forget_violation,
)


def _make_guard_with_rules(rules, tmp_path):
    """Create ForgetGuard with specific rules using a temp YAML file."""
    import yaml
    rules_file = tmp_path / "test_rules.yaml"
    rules_data = {"rules": rules}
    rules_file.write_text(yaml.dump(rules_data, allow_unicode=True))
    # Pass rescue_mode_search_dirs=[] to avoid filesystem side effects
    return ForgetGuard(rules_path=rules_file, rescue_mode_search_dirs=[])


class TestForgetGuardNoneSafe:
    """Verify ForgetGuard handles None/missing fields without crash."""

    def test_check_empty_context(self):
        """tool_input={} -- no file_path key at all."""
        result = check_forget_violation({})
        # Should return None (no violation) without crashing
        assert result is None or isinstance(result, dict)

    def test_check_none_values(self):
        """All context values explicitly None."""
        ctx = {
            "agent_id": None,
            "action_type": None,
            "action_payload": None,
            "target_agent": None,
            "file_path": None,
            "command": None,
            "content": None,
            "tool": None,
            "tool_input": None,
            "active_agent": None,
        }
        # Must not crash
        result = check_forget_violation(ctx)
        assert result is None or isinstance(result, dict)

    def test_check_missing_keys(self):
        """Context dict with only some keys."""
        ctx = {"agent_id": "ceo"}
        result = check_forget_violation(ctx)
        assert result is None or isinstance(result, dict)

    def test_matches_pattern_none_pattern(self, tmp_path):
        """Rule with None pattern should not crash."""
        guard = _make_guard_with_rules([
            {
                "name": "test_null_pattern",
                "pattern": None,
                "mode": "warn",
                "message": "test",
                "rationale": "test",
                "created_at": "2026-04-23",
            }
        ], tmp_path)
        result = guard.check({
            "agent_id": "ceo",
            "action_type": "file_write",
            "action_payload": "some content",
        })
        # None/empty pattern should never match
        assert result is None

    def test_matches_pattern_empty_pattern(self, tmp_path):
        """Rule with empty string pattern should not crash."""
        guard = _make_guard_with_rules([
            {
                "name": "test_empty_pattern",
                "pattern": "",
                "mode": "warn",
                "message": "test",
                "rationale": "test",
                "created_at": "2026-04-23",
            }
        ], tmp_path)
        result = guard.check({
            "agent_id": "ceo",
            "action_type": "file_write",
            "action_payload": "some content",
        })
        # Empty pattern should never match
        assert result is None

    def test_matches_pattern_regex_with_none_context_values(self, tmp_path):
        """Regex pattern with None context values should not crash."""
        guard = _make_guard_with_rules([
            {
                "name": "test_regex",
                "pattern": "^test_regex_pattern",
                "mode": "warn",
                "message": "test",
                "rationale": "test",
                "created_at": "2026-04-23",
            }
        ], tmp_path)
        result = guard.check({
            "agent_id": None,
            "action_type": None,
            "action_payload": None,
            "target_agent": None,
        })
        assert result is None

    def test_load_rules_null_pattern_yaml(self, tmp_path):
        """YAML rule with pattern: null should load without crash
        and coerce pattern to empty string."""
        guard = _make_guard_with_rules([
            {
                "name": "null_pattern_rule",
                "pattern": None,
                "mode": "deny",
                "message": "test message",
                "rationale": "test rationale",
                "created_at": "2026-04-23",
            },
            {
                "name": "valid_pattern_rule",
                "pattern": "test_keyword_unique_xyz",
                "mode": "warn",
                "message": "test message 2",
                "rationale": "test rationale 2",
                "created_at": "2026-04-23",
            },
        ], tmp_path)
        # Should load both test rules (plus any secondary rules from company file)
        # Find our test rules by name
        null_rule = [r for r in guard.rules if r.name == "null_pattern_rule"]
        valid_rule = [r for r in guard.rules if r.name == "valid_pattern_rule"]
        assert len(null_rule) == 1, "null_pattern_rule should be loaded"
        assert len(valid_rule) == 1, "valid_pattern_rule should be loaded"
        # Null pattern should be coerced to empty string
        assert null_rule[0].pattern == ""
        # Valid pattern preserved
        assert valid_rule[0].pattern == "test_keyword_unique_xyz"

        # Check should not crash on null-pattern rule; our test rule should match
        result = guard.check({
            "agent_id": "test_agent",
            "action_payload": "test_keyword_unique_xyz match",
        })
        assert result is not None
        assert result["rule_name"] == "valid_pattern_rule"

    def test_schema_11_rule_no_keywords(self, tmp_path):
        """Schema 1.1 rule with no keywords should not crash."""
        guard = _make_guard_with_rules([
            {
                "id": "test_no_keywords_unique_xyz",
                "trigger": {
                    "tool": ["Bash"],
                    "conditions": [],
                },
                "action": "warn",
                "recipe": "test recipe",
                "description": "test description",
            }
        ], tmp_path)
        # Rule should load with empty pattern (plus any secondary rules)
        our_rule = [r for r in guard.rules if r.name == "test_no_keywords_unique_xyz"]
        assert len(our_rule) == 1
        assert our_rule[0].pattern == ""

        # Empty pattern never matches -- result should be None or from another rule
        # but must not crash
        result = guard.check({"agent_id": "test_unique_xyz", "action_payload": "something"})
        # Our empty-pattern rule should not match
        if result is not None:
            assert result["rule_name"] != "test_no_keywords_unique_xyz"


class TestForgetGuardHookIntegration:
    """Simulate hook_wrapper context shapes."""

    def test_hook_wrapper_context_shape(self):
        """Context dict shaped like hook_wrapper._fg_context."""
        ctx = {
            "tool": "Bash",
            "tool_input": {},
            "agent_id": "ceo",
            "active_agent": "ceo",
            "file_path": "",
            "command": "ls",
            "content": "",
        }
        result = check_forget_violation(ctx)
        assert result is None or isinstance(result, dict)

    def test_hook_wrapper_context_none_tool_input(self):
        """tool_input is None (edge case from malformed payload)."""
        ctx = {
            "tool": "Read",
            "tool_input": None,
            "agent_id": "ceo",
            "active_agent": "ceo",
            "file_path": None,
            "command": None,
            "content": None,
        }
        result = check_forget_violation(ctx)
        assert result is None or isinstance(result, dict)

    def test_hook_wrapper_context_no_file_path_key(self):
        """Simulate Bash tool with no file_path in tool_input."""
        ctx = {
            "tool": "Bash",
            "tool_input": {"command": "echo hello"},
            "agent_id": "eng-governance",
            "active_agent": "eng-governance",
            "command": "echo hello",
            "content": "",
        }
        # No file_path key at all -- must not crash
        result = check_forget_violation(ctx)
        assert result is None or isinstance(result, dict)
