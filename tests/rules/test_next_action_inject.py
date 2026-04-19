"""
Tests for ystar.rules.next_action_inject — CZL-ARCH-8
======================================================

3 tests:
  1. Open/claimed task exists → returns NEXT hint (decision=inject)
  2. No tasks → returns empty (decision=allow)
  3. Rule registers in RouterRegistry and is found by find_matching_rules
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ystar.governance.router_registry import (
    RouterRegistry,
    get_default_registry,
    reset_default_registry,
)
from ystar.rules.next_action_inject import (
    next_action_inject_rule,
    register_next_action_rule,
    _next_action_detector,
    _next_action_executor,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset the default registry before and after each test."""
    reset_default_registry()
    yield
    reset_default_registry()


def _make_board_file(tasks: list) -> str:
    """Write a temporary dispatch_board.json and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8",
    )
    json.dump({"tasks": tasks}, tmp)
    tmp.close()
    return tmp.name


# ──────────────────────────────────────────────────────────────────────
# Test 1: claimed/open task → inject hint
# ──────────────────────────────────────────────────────────────────────

class TestOpenTaskReturnsNextHint:
    def test_claimed_task_injects_hint(self):
        board_path = _make_board_file([
            {
                "atomic_id": "CZL-42",
                "status": "claimed",
                "claimed_by": "eng-kernel",
                "scope": "ystar/kernel/",
                "description": "Fix compiler edge case",
            }
        ])
        payload = {
            "tool_name": "Bash",
            "decision": "allow",
            "agent_id": "eng-kernel",
            "dispatch_board_path": board_path,
        }
        assert _next_action_detector(payload) is True
        result = _next_action_executor(payload)
        assert result.decision == "inject"
        assert "CZL-42" in result.injected_context
        assert "resume claimed task" in result.injected_context
        Path(board_path).unlink()

    def test_open_task_injects_claim_hint(self):
        board_path = _make_board_file([
            {
                "atomic_id": "CZL-99",
                "status": "open",
                "urgency": "P0",
                "scope": "ystar/rules/",
            }
        ])
        payload = {
            "tool_name": "Edit",
            "decision": "allow",
            "agent_id": "eng-kernel",
            "dispatch_board_path": board_path,
        }
        result = _next_action_executor(payload)
        assert result.decision == "inject"
        assert "CZL-99" in result.injected_context
        assert "claim open task" in result.injected_context
        Path(board_path).unlink()


# ──────────────────────────────────────────────────────────────────────
# Test 2: no tasks → allow (no injection)
# ──────────────────────────────────────────────────────────────────────

class TestNoTaskReturnsEmpty:
    def test_empty_board_returns_allow(self):
        board_path = _make_board_file([])
        payload = {
            "tool_name": "Write",
            "decision": "allow",
            "agent_id": "eng-kernel",
            "dispatch_board_path": board_path,
        }
        result = _next_action_executor(payload)
        assert result.decision == "allow"
        assert result.injected_context == ""
        Path(board_path).unlink()

    def test_nonexistent_board_returns_allow(self):
        payload = {
            "tool_name": "Bash",
            "decision": "allow",
            "agent_id": "eng-kernel",
            "dispatch_board_path": "/tmp/nonexistent_board_xyz.json",
        }
        result = _next_action_executor(payload)
        assert result.decision == "allow"

    def test_detector_rejects_non_allow_decision(self):
        payload = {"tool_name": "Bash", "decision": "deny"}
        assert _next_action_detector(payload) is False

    def test_detector_rejects_unknown_tool(self):
        payload = {"tool_name": "Agent", "decision": "allow"}
        assert _next_action_detector(payload) is False


# ──────────────────────────────────────────────────────────────────────
# Test 3: registry integration — register + find_matching_rules
# ──────────────────────────────────────────────────────────────────────

class TestRegistryIntegration:
    def test_register_and_find_matching(self):
        registry = get_default_registry()
        assert register_next_action_rule(registry) is True

        # Should be findable
        board_path = _make_board_file([
            {"atomic_id": "CZL-1", "status": "open", "urgency": "P1", "scope": "test"},
        ])
        payload = {
            "tool_name": "Bash",
            "decision": "allow",
            "agent_id": "eng-kernel",
            "dispatch_board_path": board_path,
        }
        matches = registry.find_matching_rules(payload)
        assert len(matches) == 1
        assert matches[0].rule_id == "builtin.next_action_inject"
        assert matches[0].priority == 50

        # Execute
        result = registry.execute_rule(matches[0], payload)
        assert result.decision == "inject"
        assert result.rule_id == "builtin.next_action_inject"
        Path(board_path).unlink()

    def test_double_register_returns_false(self):
        registry = get_default_registry()
        assert register_next_action_rule(registry) is True
        assert register_next_action_rule(registry) is False
