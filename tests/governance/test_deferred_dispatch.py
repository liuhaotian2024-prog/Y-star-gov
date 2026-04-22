"""
Test suite for CEO/CTO deferred-dispatch promise orphan detection.

Board 2026-04-16 P0 directive: CEO exhibits systematic deferred-dispatch hypocrisy
("下波派 X", "next round spawn Y", "后续调起 Z") without follow-through Agent calls.

ForgetGuard rule `ceo_deferred_dispatch_promise_orphan` enforces:
- Deferred promise + no Agent call in same reply → violation
- Deferred promise + Agent call in same reply → compliant
- Promise with escape valve (task card / backlog / Board escalation) → compliant
- No promise language → skip

Ref: reports/cto/ceo_deferred_dispatch_root_cause_20260416.md
"""

import pytest
from ystar.governance.coordinator_audit import check_deferred_dispatch_orphan


class TestDeferredDispatchOrphan:
    """Test deferred-dispatch promise orphan detection."""

    def test_chinese_promise_no_agent_call_fires(self):
        """Chinese '下波派 Maya' without Agent call in actions → violation."""
        reply = "今晚先完成 F1, 下波派 Maya 处理 F2。"
        actions = ["Read", "Edit", "Bash"]  # No Agent call

        violation = check_deferred_dispatch_orphan(reply, actions)

        assert violation is not None, "Should detect '下波派 Maya' orphan"
        assert violation["violation"] is True
        assert "下波派" in violation["promise_phrase"]
        assert violation["expected_engineer"] == "Maya"
        assert "Agent" not in violation["actions_taken_after_promise"]

    def test_chinese_promise_with_agent_call_passes(self):
        """Chinese '下波派 Maya' WITH Agent call in actions → compliant."""
        reply = "今晚先完成 F1, 下波派 Maya 处理 F2。"
        actions = ["Read", "Edit", "Agent", "Bash"]  # Agent call present

        violation = check_deferred_dispatch_orphan(reply, actions)

        assert violation is None, "Should pass when Agent call present"

    def test_english_next_round_spawn_no_agent_fires(self):
        """English 'next round spawn Jordan' without Agent call → violation."""
        reply = "Wave 1 complete. Next round spawn Jordan for database migration."
        actions = ["Bash", "Read"]  # No Agent call

        violation = check_deferred_dispatch_orphan(reply, actions)

        assert violation is not None, "Should detect 'next round spawn' orphan"
        assert violation["violation"] is True
        assert "next round spawn" in violation["promise_phrase"].lower()
        assert violation["expected_engineer"] == "Jordan"

    def test_next_dispatch_via_cto_no_agent_fires(self):
        """'next dispatch via Ethan-CTO' without Agent call → violation."""
        reply = "Completing current tasks. Next dispatch via Ethan-CTO for coordination."
        actions = ["Edit", "Bash"]  # No Agent call

        violation = check_deferred_dispatch_orphan(reply, actions)

        assert violation is not None, "Should detect 'next dispatch via' orphan"
        assert violation["violation"] is True
        assert "next dispatch via" in violation["promise_phrase"].lower()
        assert violation["expected_engineer"] == "Ethan-CTO"

    def test_waiting_pattern_no_agent_fires(self):
        """Chinese '等 Ethan 完成测试再派 Ryan' without Agent call → violation."""
        reply = "F1 已落盘, 等 Ethan 完成测试再派 Ryan 做 F2。"
        actions = ["Read", "Write"]  # No Agent call

        violation = check_deferred_dispatch_orphan(reply, actions)

        assert violation is not None, "Should detect '等...完成...派' orphan"
        assert violation["violation"] is True
        assert "等" in violation["promise_phrase"]
        # Extract Ryan as expected engineer (heuristic captures last word after 派/spawn/调起)

    def test_escape_valve_task_card_passes(self):
        """Promise with task card creation → legitimate defer, no violation."""
        reply = "下波派 Maya 处理 F2 (写 .claude/tasks/eng-governance-042.md)"
        actions = ["Read", "Edit"]  # No Agent call BUT task card mentioned

        violation = check_deferred_dispatch_orphan(reply, actions)

        assert violation is None, "Should pass when task card escape valve used"

    def test_escape_valve_world_state_backlog_passes(self):
        """Promise with WORLD_STATE.md backlog mention → legitimate defer, no violation."""
        reply = "后续调起 Leo (已加入 WORLD_STATE.md § Backlog)"
        actions = ["Bash"]  # No Agent call BUT backlog mentioned

        violation = check_deferred_dispatch_orphan(reply, actions)

        assert violation is None, "Should pass when WORLD_STATE.md backlog escape valve used"

    def test_escape_valve_board_blocked_passes(self):
        """Promise with Board blocked mention → legitimate defer, no violation."""
        reply = "Next round spawn Ryan (Board blocked on license approval)"
        actions = ["Read"]  # No Agent call BUT Board escalation mentioned

        violation = check_deferred_dispatch_orphan(reply, actions)

        assert violation is None, "Should pass when Board escalation escape valve used"

    def test_no_promise_language_skips(self):
        """Short reply without deferred-promise language → skip."""
        reply = "F1 完成, 4/4 tests PASS, commit dedf11d7."
        actions = ["Bash", "Read"]

        violation = check_deferred_dispatch_orphan(reply, actions)

        assert violation is None, "Should skip when no promise language detected"

    def test_mixed_chinese_english_promise_fires(self):
        """Mixed language '后续 spawn Maya' without Agent call → violation."""
        reply = "Wave 1 shipped. 后续 spawn Maya for governance rules."
        actions = ["Edit", "Bash"]  # No Agent call

        violation = check_deferred_dispatch_orphan(reply, actions)

        assert violation is not None, "Should detect mixed-language orphan"
        assert violation["violation"] is True
        assert "spawn" in violation["promise_phrase"].lower()

    def test_multiple_promises_first_caught(self):
        """Multiple promises in single reply → catch first occurrence."""
        reply = "下波派 Maya 处理 F1, next round spawn Jordan 处理 F2."
        actions = ["Read"]  # No Agent call

        violation = check_deferred_dispatch_orphan(reply, actions)

        assert violation is not None, "Should detect at least one promise orphan"
        assert violation["violation"] is True
        # First match should be "下波派 Maya"
        assert "下波派" in violation["promise_phrase"]

    def test_promise_with_agent_call_elsewhere_in_actions_passes(self):
        """Promise with Agent call anywhere in session actions → compliant."""
        reply = "等 Ryan 完成测试再派 Leo"
        actions = ["Read", "Edit", "Agent", "Bash", "Write"]  # Agent present, not adjacent

        violation = check_deferred_dispatch_orphan(reply, actions)

        assert violation is None, "Should pass when Agent call exists in actions list"
