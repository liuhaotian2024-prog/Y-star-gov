"""
Tests for CZL-P2-a: RouterRegistry skeleton

Coverage:
  1. EnforceDecision has INVOKE, INJECT, AUTO_POST values
  2. RouterRule registration / dedup / update / unregister
  3. find_matching_rules: detector matching + priority sorting
  4. execute_rule: execution + error handling + chain depth guard
  5. execute_rules: multi-rule pipeline with stop_on_non_allow
  6. Stats and introspection
"""
from __future__ import annotations

import pytest

from ystar.domains.openclaw.adapter import EnforceDecision
from ystar.governance.router_registry import (
    RouterRule,
    RouterResult,
    RouterRegistry,
    get_default_registry,
    reset_default_registry,
)


# ── Test 1: EnforceDecision extended values ──────────────────────────────────

class TestEnforceDecisionExtended:
    def test_invoke_exists(self):
        assert EnforceDecision.INVOKE.value == "invoke"

    def test_inject_exists(self):
        assert EnforceDecision.INJECT.value == "inject"

    def test_auto_post_exists(self):
        assert EnforceDecision.AUTO_POST.value == "auto_post"

    def test_all_seven_decisions(self):
        values = {d.value for d in EnforceDecision}
        expected = {"allow", "deny", "escalate", "redirect", "invoke", "inject", "auto_post"}
        assert values == expected


# ── Test 2: RouterRule registration ──────────────────────────────────────────

class TestRegistration:
    def test_register_rule(self):
        reg = RouterRegistry()
        rule = RouterRule(
            rule_id="test_1",
            detector=lambda p: True,
            executor=lambda p: RouterResult(decision="allow"),
        )
        reg.register_rule(rule)
        assert reg.rule_count == 1
        assert reg.get_rule("test_1") is rule

    def test_duplicate_rule_id_raises(self):
        reg = RouterRegistry()
        rule = RouterRule(
            rule_id="dup",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
        )
        reg.register_rule(rule)
        with pytest.raises(ValueError, match="already registered"):
            reg.register_rule(rule)

    def test_update_rule_replaces(self):
        reg = RouterRegistry()
        rule1 = RouterRule(
            rule_id="r1",
            detector=lambda p: True,
            executor=lambda p: RouterResult(decision="allow"),
            priority=10,
        )
        rule2 = RouterRule(
            rule_id="r1",
            detector=lambda p: False,
            executor=lambda p: RouterResult(decision="deny"),
            priority=20,
        )
        reg.register_rule(rule1)
        reg.update_rule(rule2)
        assert reg.rule_count == 1
        assert reg.get_rule("r1").priority == 20

    def test_unregister_rule(self):
        reg = RouterRegistry()
        rule = RouterRule(
            rule_id="to_remove",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
        )
        reg.register_rule(rule)
        assert reg.unregister_rule("to_remove") is True
        assert reg.rule_count == 0
        assert reg.unregister_rule("nonexistent") is False

    def test_get_nonexistent_returns_none(self):
        reg = RouterRegistry()
        assert reg.get_rule("no_such_rule") is None


# ── Test 3: find_matching_rules ──────────────────────────────────────────────

class TestMatching:
    def test_basic_match(self):
        reg = RouterRegistry()
        reg.register_rule(RouterRule(
            rule_id="match_all",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
        ))
        reg.register_rule(RouterRule(
            rule_id="match_none",
            detector=lambda p: False,
            executor=lambda p: RouterResult(),
        ))
        matches = reg.find_matching_rules({"tool_name": "Write"})
        assert len(matches) == 1
        assert matches[0].rule_id == "match_all"

    def test_priority_ordering(self):
        reg = RouterRegistry()
        reg.register_rule(RouterRule(
            rule_id="low",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
            priority=10,
        ))
        reg.register_rule(RouterRule(
            rule_id="high",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
            priority=1000,
        ))
        reg.register_rule(RouterRule(
            rule_id="mid",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
            priority=100,
        ))
        matches = reg.find_matching_rules({})
        assert [m.rule_id for m in matches] == ["high", "mid", "low"]

    def test_disabled_rules_skipped(self):
        reg = RouterRegistry()
        reg.register_rule(RouterRule(
            rule_id="active",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
            enabled=True,
        ))
        reg.register_rule(RouterRule(
            rule_id="disabled",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
            enabled=False,
        ))
        matches = reg.find_matching_rules({})
        assert len(matches) == 1
        assert matches[0].rule_id == "active"

    def test_detector_exception_skips_rule(self):
        reg = RouterRegistry()
        reg.register_rule(RouterRule(
            rule_id="broken",
            detector=lambda p: 1/0,  # Will raise ZeroDivisionError
            executor=lambda p: RouterResult(),
        ))
        reg.register_rule(RouterRule(
            rule_id="working",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
        ))
        matches = reg.find_matching_rules({})
        assert len(matches) == 1
        assert matches[0].rule_id == "working"

    def test_payload_passed_to_detector(self):
        """Detector receives the full payload dict."""
        captured = {}

        def capture_detector(p):
            captured.update(p)
            return True

        reg = RouterRegistry()
        reg.register_rule(RouterRule(
            rule_id="capture",
            detector=capture_detector,
            executor=lambda p: RouterResult(),
        ))
        payload = {"tool_name": "Write", "file_path": "/tmp/test.py"}
        reg.find_matching_rules(payload)
        assert captured["tool_name"] == "Write"
        assert captured["file_path"] == "/tmp/test.py"


# ── Test 4: execute_rule ─────────────────────────────────────────────────────

class TestExecution:
    def test_basic_execution(self):
        reg = RouterRegistry()
        rule = RouterRule(
            rule_id="exec_test",
            detector=lambda p: True,
            executor=lambda p: RouterResult(
                decision="invoke",
                script="/path/to/script.py",
                message="invoked",
            ),
        )
        reg.register_rule(rule)
        result = reg.execute_rule(rule, {"tool_name": "Bash"})
        assert result.decision == "invoke"
        assert result.rule_id == "exec_test"
        assert result.script == "/path/to/script.py"
        assert result.execution_ms >= 0

    def test_executor_exception_returns_deny(self):
        reg = RouterRegistry()
        rule = RouterRule(
            rule_id="crash",
            detector=lambda p: True,
            executor=lambda p: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        reg.register_rule(rule)
        result = reg.execute_rule(rule, {})
        assert result.decision == "deny"
        assert "boom" in result.message
        assert result.rule_id == "crash"

    def test_chain_depth_guard(self):
        reg = RouterRegistry()
        reg._execution_depth = reg.MAX_CHAIN_DEPTH  # Simulate deep chain
        rule = RouterRule(
            rule_id="deep",
            detector=lambda p: True,
            executor=lambda p: RouterResult(decision="allow"),
        )
        reg.register_rule(rule)
        result = reg.execute_rule(rule, {})
        assert result.decision == "deny"
        assert "depth exceeded" in result.message
        # Depth should not have incremented further
        assert reg._execution_depth == reg.MAX_CHAIN_DEPTH

    def test_execution_depth_resets_after_success(self):
        reg = RouterRegistry()
        assert reg._execution_depth == 0
        rule = RouterRule(
            rule_id="normal",
            detector=lambda p: True,
            executor=lambda p: RouterResult(decision="allow"),
        )
        reg.register_rule(rule)
        reg.execute_rule(rule, {})
        assert reg._execution_depth == 0  # Reset after execution


# ── Test 5: execute_rules (pipeline) ─────────────────────────────────────────

class TestPipeline:
    def test_stop_on_non_allow(self):
        reg = RouterRegistry()
        executed = []

        def make_executor(name, decision):
            def executor(p):
                executed.append(name)
                return RouterResult(decision=decision, message=name)
            return executor

        reg.register_rule(RouterRule(
            rule_id="first",
            detector=lambda p: True,
            executor=make_executor("first", "allow"),
            priority=100,
        ))
        reg.register_rule(RouterRule(
            rule_id="blocker",
            detector=lambda p: True,
            executor=make_executor("blocker", "deny"),
            priority=50,
        ))
        reg.register_rule(RouterRule(
            rule_id="never_reached",
            detector=lambda p: True,
            executor=make_executor("never", "allow"),
            priority=10,
        ))

        results = reg.execute_rules({})
        assert len(results) == 2
        assert executed == ["first", "blocker"]
        assert results[0].decision == "allow"
        assert results[1].decision == "deny"

    def test_all_allow_executes_all(self):
        reg = RouterRegistry()
        reg.register_rule(RouterRule(
            rule_id="a",
            detector=lambda p: True,
            executor=lambda p: RouterResult(decision="allow"),
            priority=2,
        ))
        reg.register_rule(RouterRule(
            rule_id="b",
            detector=lambda p: True,
            executor=lambda p: RouterResult(decision="allow"),
            priority=1,
        ))
        results = reg.execute_rules({})
        assert len(results) == 2

    def test_no_matches_returns_empty(self):
        reg = RouterRegistry()
        reg.register_rule(RouterRule(
            rule_id="never",
            detector=lambda p: False,
            executor=lambda p: RouterResult(),
        ))
        results = reg.execute_rules({})
        assert results == []


# ── Test 6: Stats and introspection ──────────────────────────────────────────

class TestIntrospection:
    def test_stats(self):
        reg = RouterRegistry()
        reg.register_rule(RouterRule(
            rule_id="const",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
            priority=1000,
        ))
        reg.register_rule(RouterRule(
            rule_id="workflow",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
            priority=100,
        ))
        reg.register_rule(RouterRule(
            rule_id="disabled",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
            priority=50,
            enabled=False,
        ))
        stats = reg.stats()
        assert stats["total_rules"] == 3
        assert stats["enabled"] == 2
        assert stats["disabled"] == 1
        assert stats["priority_buckets"]["constitutional"] == 1
        assert stats["priority_buckets"]["workflow"] == 1
        assert stats["priority_buckets"]["advisory"] == 1

    def test_describe_rules(self):
        reg = RouterRegistry()
        reg.register_rule(RouterRule(
            rule_id="r1",
            detector=lambda p: True,
            executor=lambda p: RouterResult(),
            priority=100,
            metadata={"phase": "2-b"},
        ))
        desc = reg.describe_rules()
        assert len(desc) == 1
        assert desc[0]["rule_id"] == "r1"
        assert desc[0]["priority"] == 100
        assert desc[0]["metadata"]["phase"] == "2-b"


# ── Test 7: Default singleton ────────────────────────────────────────────────

class TestDefaultRegistry:
    def test_get_default_registry(self):
        reset_default_registry()
        reg = get_default_registry()
        assert isinstance(reg, RouterRegistry)
        assert get_default_registry() is reg  # Same instance

    def test_reset_default_registry(self):
        reset_default_registry()
        reg1 = get_default_registry()
        reset_default_registry()
        reg2 = get_default_registry()
        assert reg1 is not reg2


# ── Test 8: RouterResult data model ──────────────────────────────────────────

class TestRouterResult:
    def test_default_values(self):
        r = RouterResult()
        assert r.decision == "allow"
        assert r.message == ""
        assert r.script == ""
        assert r.args == {}
        assert r.injected_context == ""
        assert r.task_card is None

    def test_invoke_result(self):
        r = RouterResult(
            decision="invoke",
            script="/path/to/boot.py",
            args={"agent_id": "ceo"},
            message="Session boot invoked",
        )
        assert r.decision == "invoke"
        assert r.script == "/path/to/boot.py"
        assert r.args["agent_id"] == "ceo"

    def test_inject_result(self):
        r = RouterResult(
            decision="inject",
            injected_context="## SOP: Do X before Y\n\n...",
            message="Injected SOP for dispatch",
        )
        assert r.decision == "inject"
        assert "SOP" in r.injected_context

    def test_auto_post_result(self):
        card = {"atomic_id": "CZL-999", "scope": "tests/", "urgency": "P0"}
        r = RouterResult(
            decision="auto_post",
            task_card=card,
            message="Auto-posted task card",
        )
        assert r.decision == "auto_post"
        assert r.task_card["atomic_id"] == "CZL-999"
