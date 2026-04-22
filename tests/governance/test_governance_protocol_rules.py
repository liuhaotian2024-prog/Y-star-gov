"""
Tests for CZL-P2-d: Governance Protocol Rules
================================================

Coverage: 10 governance protocols registered as RouterRules.
Each rule gets 1-2 tests verifying detector + executor behavior.

Rules tested:
  1. gov_atomic_dispatch — multi-deliverable detection
  2. gov_ceo_dispatch_self_check — CEO 3-question self-check
  3. gov_action_model_v2 — boot context check
  4. gov_tiered_routing — T1/T2/T3 routing
  5. gov_pre_build_gate — precheck before governance writes
  6. gov_reply_scan — 5-tuple requirement on dispatch/receipt replies
  7. gov_auto_commit_push — git ops validation
  8. gov_session_end_handoff — session end handoff invocation
  9. gov_subagent_boot_template — boot prompt template compliance
  10. gov_ceo_methodology — CEO methodology injection
"""
from __future__ import annotations

import re
import pytest

from ystar.governance.router_registry import (
    RouterRegistry,
    RouterResult,
    RouterRule,
)


# ═══════════════════════════════════════════════════════════════════════
# Detector + Executor implementations (inlined for test independence
# until governance_protocol_rules.py is deployed to ystar/governance/)
# ═══════════════════════════════════════════════════════════════════════

def _is_agent_tool_call(payload):
    return payload.get("hook_type") == "PreToolUse" and payload.get("tool_name") == "Agent"

def _is_ceo_agent(payload):
    return payload.get("agent_id", "").lower() in ("ceo", "aiden")

def _extract_agent_prompt(payload):
    ti = payload.get("tool_input", {})
    return ti.get("prompt", ti.get("message", ""))

def _count_deliverables_in_prompt(prompt):
    numbered = len(re.findall(r"(?:Task|任务)\s*\d+\s*:", prompt, re.IGNORECASE))
    if numbered > 1:
        return numbered
    bullets = len(re.findall(
        r"^\s*[-*]\s+(?:fix|write|create|build|add|update|修|写|建|加)",
        prompt, re.MULTILINE | re.IGNORECASE,
    ))
    if bullets > 1:
        return bullets
    return 1


# ── Payload helpers ────────────────────────────────────────────────────

def _agent_payload(prompt="do something", agent_id="ceo", **extra):
    p = {
        "hook_type": "PreToolUse",
        "tool_name": "Agent",
        "agent_id": agent_id,
        "tool_input": {"prompt": prompt},
    }
    p.update(extra)
    return p

def _bash_payload(command="ls", agent_id="ceo"):
    return {
        "hook_type": "PreToolUse",
        "tool_name": "Bash",
        "agent_id": agent_id,
        "tool_input": {"command": command},
    }

def _write_payload(file_path="/tmp/test.py", content="x=1", agent_id="eng-kernel"):
    return {
        "hook_type": "PreToolUse",
        "tool_name": "Write",
        "agent_id": agent_id,
        "tool_input": {"file_path": file_path, "content": content},
    }

def _stop_payload(reply_text=""):
    return {"hook_type": "Stop", "stop_text": reply_text, "agent_id": "ceo"}

def _session_end_payload(agent_id="ceo"):
    return {"hook_type": "SessionEnd", "agent_id": agent_id, "event_type": "session_end"}


# ═══════════════════════════════════════════════════════════════════════
# Rule 1: Atomic Dispatch
# ═══════════════════════════════════════════════════════════════════════

class TestAtomicDispatch:
    def _make_rule(self):
        def detector(p):
            return _is_agent_tool_call(p)
        def executor(p):
            prompt = _extract_agent_prompt(p)
            count = _count_deliverables_in_prompt(prompt)
            if count > 1:
                return RouterResult(
                    decision="inject",
                    injected_context=f"Multi-deliverable dispatch ({count} tasks)",
                    message=f"Multi-deliverable dispatch detected ({count} tasks)",
                )
            return RouterResult(decision="allow", message="Atomic dispatch OK")
        return RouterRule(rule_id="gov_atomic_dispatch", detector=detector, executor=executor, priority=200)

    def test_single_deliverable_allows(self):
        reg = RouterRegistry()
        reg.register_rule(self._make_rule())
        payload = _agent_payload("Fix the bug in engine.py")
        matches = reg.find_matching_rules(payload)
        assert len(matches) == 1
        result = reg.execute_rule(matches[0], payload)
        assert result.decision == "allow"

    def test_multi_deliverable_injects_warning(self):
        reg = RouterRegistry()
        reg.register_rule(self._make_rule())
        payload = _agent_payload("Task 1: fix engine.py\nTask 2: update tests\nTask 3: write docs")
        result = reg.execute_rule(self._make_rule(), payload)
        assert result.decision == "inject"
        assert "3" in result.injected_context


# ═══════════════════════════════════════════════════════════════════════
# Rule 2: CEO Dispatch Self-Check
# ═══════════════════════════════════════════════════════════════════════

class TestCEODispatchSelfCheck:
    def _make_rule(self):
        def detector(p):
            return _is_agent_tool_call(p) and _is_ceo_agent(p)
        def executor(p):
            prompt = _extract_agent_prompt(p)
            issues = []
            count = _count_deliverables_in_prompt(prompt)
            if count > 1:
                issues.append(f"Q1 FAIL: {count} deliverables")
            if not re.search(r"/Users/\S+", prompt):
                issues.append("Q3: Missing absolute file paths")
            if not re.search(r"(Rt\+1|success|criteria|pytest)", prompt, re.IGNORECASE):
                issues.append("Q3: Missing success criteria")
            if issues:
                return RouterResult(decision="inject", injected_context="\n".join(issues))
            return RouterResult(decision="allow")
        return RouterRule(rule_id="gov_ceo_dispatch_self_check", detector=detector, executor=executor, priority=210)

    def test_ceo_dispatch_detected(self):
        rule = self._make_rule()
        assert rule.detector(_agent_payload("test", agent_id="ceo")) is True
        assert rule.detector(_agent_payload("test", agent_id="eng-kernel")) is False

    def test_missing_paths_and_criteria_injects(self):
        rule = self._make_rule()
        result = rule.executor(_agent_payload("go fix stuff", agent_id="ceo"))
        assert result.decision == "inject"
        assert "absolute file paths" in result.injected_context
        assert "success criteria" in result.injected_context

    def test_complete_prompt_allows(self):
        rule = self._make_rule()
        prompt = "Fix /Users/haotianliu/test.py. Success criteria: pytest passes, Rt+1=0"
        result = rule.executor(_agent_payload(prompt, agent_id="ceo"))
        assert result.decision == "allow"


# ═══════════════════════════════════════════════════════════════════════
# Rule 3: Action Model v2
# ═══════════════════════════════════════════════════════════════════════

class TestActionModelV2:
    def _make_rule(self):
        def detector(p):
            return _is_agent_tool_call(p)
        def executor(p):
            prompt = _extract_agent_prompt(p)
            has_boot = bool(re.search(
                r"BOOT\s+CONTEXT|Phase\s+A|czl_subgoals|precheck_existing|git\s+log",
                prompt, re.IGNORECASE,
            ))
            if not has_boot and prompt:
                return RouterResult(
                    decision="inject",
                    injected_context="Action model v2 boot context missing",
                )
            return RouterResult(decision="allow")
        return RouterRule(rule_id="gov_action_model_v2", detector=detector, executor=executor, priority=190)

    def test_missing_boot_context_injects(self):
        rule = self._make_rule()
        result = rule.executor(_agent_payload("fix the thing"))
        assert result.decision == "inject"
        assert "boot context" in result.injected_context.lower()

    def test_with_boot_context_allows(self):
        rule = self._make_rule()
        result = rule.executor(_agent_payload("## BOOT CONTEXT\n1. Read .czl_subgoals.json"))
        assert result.decision == "allow"


# ═══════════════════════════════════════════════════════════════════════
# Rule 4: Tiered Routing
# ═══════════════════════════════════════════════════════════════════════

class TestTieredRouting:
    def _make_rule(self):
        def detector(p):
            return _is_agent_tool_call(p)
        def executor(p):
            ti = p.get("tool_input", {})
            agent_id = p.get("agent_id", "").lower()
            subagent = ti.get("subagent_type", "")
            estimated = ti.get("estimated_tool_uses", 15)
            if agent_id in ("ceo", "aiden") and subagent.startswith("eng-") and estimated > 15:
                return RouterResult(
                    decision="inject",
                    injected_context=f"Possible T2/T3 task ({estimated} tool_uses), route through CTO",
                )
            return RouterResult(decision="allow")
        return RouterRule(rule_id="gov_tiered_routing", detector=detector, executor=executor, priority=180)

    def test_ceo_direct_dispatch_high_tool_uses(self):
        rule = self._make_rule()
        payload = _agent_payload("do big thing", agent_id="ceo")
        payload["tool_input"]["subagent_type"] = "eng-kernel"
        payload["tool_input"]["estimated_tool_uses"] = 30
        result = rule.executor(payload)
        assert result.decision == "inject"
        assert "T2/T3" in result.injected_context

    def test_small_task_allows(self):
        rule = self._make_rule()
        payload = _agent_payload("fix typo", agent_id="ceo")
        payload["tool_input"]["subagent_type"] = "eng-kernel"
        payload["tool_input"]["estimated_tool_uses"] = 5
        result = rule.executor(payload)
        assert result.decision == "allow"


# ═══════════════════════════════════════════════════════════════════════
# Rule 5: Pre-Build Routing Gate
# ═══════════════════════════════════════════════════════════════════════

class TestPreBuildGate:
    def _make_rule(self):
        def detector(p):
            if p.get("hook_type") != "PreToolUse":
                return False
            if p.get("tool_name") not in ("Write", "Edit"):
                return False
            fp = p.get("tool_input", {}).get("file_path", "")
            return any(seg in fp for seg in ("governance/", "ystar/governance/", "ystar/adapters/"))
        def executor(p):
            fp = p.get("tool_input", {}).get("file_path", "")
            return RouterResult(
                decision="inject",
                injected_context=f"Pre-build gate: run precheck_existing.py before writing to {fp}",
            )
        return RouterRule(rule_id="gov_pre_build_gate", detector=detector, executor=executor, priority=170)

    def test_governance_write_detected(self):
        rule = self._make_rule()
        payload = _write_payload("/path/to/ystar/governance/new_rule.py")
        assert rule.detector(payload) is True
        result = rule.executor(payload)
        assert result.decision == "inject"
        assert "precheck_existing" in result.injected_context

    def test_non_governance_write_not_detected(self):
        rule = self._make_rule()
        payload = _write_payload("/path/to/tests/test_foo.py")
        assert rule.detector(payload) is False


# ═══════════════════════════════════════════════════════════════════════
# Rule 6: Reply Scan Detector
# ═══════════════════════════════════════════════════════════════════════

class TestReplyScan:
    def _make_rule(self):
        dispatch_re = re.compile(
            r"(派|调起|spawn|dispatch|executing|now running|delegating to)", re.IGNORECASE)
        artifact_re = re.compile(
            r"(shipped|landed|Rt\+1\s*=\s*\d|commit\s+[a-f0-9]{7,})", re.IGNORECASE)

        def detector(p):
            return p.get("hook_type") == "Stop"
        def executor(p):
            text = p.get("stop_text", "")
            if not text:
                return RouterResult(decision="allow")
            has_dispatch = bool(dispatch_re.search(text))
            has_artifact = bool(artifact_re.search(text))
            has_5tuple = all(re.search(pat, text) for pat in [r"\bY\*", r"\bXt\b", r"\bU\b", r"\bYt\+1\b", r"\bRt\+1\b"])
            if (has_dispatch or has_artifact) and not has_5tuple:
                return RouterResult(decision="inject", injected_context="Reply missing 5-tuple")
            return RouterResult(decision="allow")
        return RouterRule(rule_id="gov_reply_scan", detector=detector, executor=executor, priority=50)

    def test_dispatch_without_5tuple_injects(self):
        rule = self._make_rule()
        payload = _stop_payload("NOW dispatch Ryan to fix the bug")
        result = rule.executor(payload)
        assert result.decision == "inject"
        assert "5-tuple" in result.injected_context

    def test_reply_with_5tuple_allows(self):
        rule = self._make_rule()
        text = "dispatch done. Y* contract. Xt baseline. U actions. Yt+1 expected. Rt+1=0"
        payload = _stop_payload(text)
        result = rule.executor(payload)
        assert result.decision == "allow"


# ═══════════════════════════════════════════════════════════════════════
# Rule 7: Auto-Commit/Push Validate
# ═══════════════════════════════════════════════════════════════════════

class TestAutoCommitPush:
    def _make_rule(self):
        def detector(p):
            if p.get("hook_type") != "PreToolUse" or p.get("tool_name") != "Bash":
                return False
            cmd = p.get("tool_input", {}).get("command", "")
            return bool(re.search(r"\bgit\s+(commit|push)\b", cmd))
        def executor(p):
            cmd = p.get("tool_input", {}).get("command", "")
            issues = []
            if re.search(r"git\s+push\s+.*--force", cmd):
                issues.append("Force push requires Board approval")
            if re.search(r"git\s+add\s+[.-]A?\s*$", cmd):
                issues.append("Broad git add detected")
            if re.search(r"git\s+commit", cmd) and not re.search(r"-m\s+[\"']", cmd):
                issues.append("git commit without -m message")
            if issues:
                return RouterResult(decision="inject", injected_context="\n".join(issues))
            return RouterResult(decision="allow")
        return RouterRule(rule_id="gov_auto_commit_push", detector=detector, executor=executor, priority=300)

    def test_force_push_detected(self):
        rule = self._make_rule()
        payload = _bash_payload("git push origin main --force")
        assert rule.detector(payload) is True
        result = rule.executor(payload)
        assert result.decision == "inject"
        assert "Force push" in result.injected_context

    def test_normal_commit_allows(self):
        rule = self._make_rule()
        payload = _bash_payload("git commit -m 'feat: add rule'")
        result = rule.executor(payload)
        assert result.decision == "allow"


# ═══════════════════════════════════════════════════════════════════════
# Rule 8: Session End Handoff
# ═══════════════════════════════════════════════════════════════════════

class TestSessionEndHandoff:
    def _make_rule(self):
        def detector(p):
            return p.get("event_type") == "session_end" or p.get("hook_type") == "SessionEnd"
        def executor(p):
            agent_id = p.get("agent_id", "unknown")
            return RouterResult(
                decision="invoke",
                script="scripts/session_close_yml.py",
                args={"agent_id": agent_id},
                message=f"Session end handoff for {agent_id}",
            )
        return RouterRule(rule_id="gov_session_end_handoff", detector=detector, executor=executor, priority=100)

    def test_session_end_detected(self):
        rule = self._make_rule()
        assert rule.detector(_session_end_payload()) is True
        assert rule.detector(_agent_payload("test")) is False

    def test_invokes_handoff_script(self):
        rule = self._make_rule()
        result = rule.executor(_session_end_payload("eng-kernel"))
        assert result.decision == "invoke"
        assert "session_close" in result.script
        assert result.args["agent_id"] == "eng-kernel"


# ═══════════════════════════════════════════════════════════════════════
# Rule 9: Sub-Agent Boot Template
# ═══════════════════════════════════════════════════════════════════════

class TestSubagentBootTemplate:
    def _make_rule(self):
        required = {
            "BOOT CONTEXT": r"BOOT\s+CONTEXT",
            "Phase A": r"Phase\s+A",
            "No git ops": r"(?:no\s+git|禁止.*(?:commit|push))",
        }
        def detector(p):
            return _is_agent_tool_call(p)
        def executor(p):
            prompt = _extract_agent_prompt(p)
            if not prompt:
                return RouterResult(decision="allow")
            missing = [n for n, pat in required.items() if not re.search(pat, prompt, re.IGNORECASE)]
            if missing:
                return RouterResult(
                    decision="inject",
                    injected_context=f"Boot template missing: {', '.join(missing)}",
                )
            return RouterResult(decision="allow")
        return RouterRule(rule_id="gov_subagent_boot_template", detector=detector, executor=executor, priority=195)

    def test_missing_boot_context_injects(self):
        rule = self._make_rule()
        result = rule.executor(_agent_payload("just do it"))
        assert result.decision == "inject"
        assert "BOOT CONTEXT" in result.injected_context

    def test_complete_template_allows(self):
        rule = self._make_rule()
        prompt = "## BOOT CONTEXT\nPhase A steps...\nno git commit or push allowed"
        result = rule.executor(_agent_payload(prompt))
        assert result.decision == "allow"


# ═══════════════════════════════════════════════════════════════════════
# Rule 10: CEO Operating Methodology
# ═══════════════════════════════════════════════════════════════════════

class TestCEOMethodology:
    def _make_rule(self):
        def detector(p):
            if not _is_ceo_agent(p):
                return False
            if p.get("hook_type") != "PreToolUse":
                return False
            return p.get("tool_name") in ("Agent", "Write", "Edit")
        def executor(p):
            if p.get("tool_name") == "Agent":
                return RouterResult(
                    decision="inject",
                    injected_context="CEO METHODOLOGY: 5 primitives check",
                )
            return RouterResult(decision="allow")
        return RouterRule(rule_id="gov_ceo_methodology", detector=detector, executor=executor, priority=30)

    def test_ceo_agent_call_injects(self):
        rule = self._make_rule()
        payload = _agent_payload("dispatch engineer", agent_id="ceo")
        assert rule.detector(payload) is True
        result = rule.executor(payload)
        assert result.decision == "inject"
        assert "methodology" in result.injected_context.lower()

    def test_non_ceo_not_detected(self):
        rule = self._make_rule()
        payload = _agent_payload("dispatch engineer", agent_id="eng-kernel")
        assert rule.detector(payload) is False


# ═══════════════════════════════════════════════════════════════════════
# Integration: All 10 rules in a registry
# ═══════════════════════════════════════════════════════════════════════

class TestAllRulesRegistered:
    """Verify all 10 rules can be registered and routed correctly."""

    def _build_registry(self):
        reg = RouterRegistry()
        test_classes = [
            TestAtomicDispatch(),
            TestCEODispatchSelfCheck(),
            TestActionModelV2(),
            TestTieredRouting(),
            TestPreBuildGate(),
            TestReplyScan(),
            TestAutoCommitPush(),
            TestSessionEndHandoff(),
            TestSubagentBootTemplate(),
            TestCEOMethodology(),
        ]
        for tc in test_classes:
            reg.register_rule(tc._make_rule())
        return reg

    def test_all_10_registered(self):
        reg = self._build_registry()
        assert reg.rule_count == 10

    def test_agent_call_matches_multiple_rules(self):
        """CEO Agent call should match: atomic, ceo_self_check, action_model, tiered, boot_template, methodology."""
        reg = self._build_registry()
        payload = _agent_payload("do something", agent_id="ceo")
        matches = reg.find_matching_rules(payload)
        rule_ids = {m.rule_id for m in matches}
        assert "gov_atomic_dispatch" in rule_ids
        assert "gov_ceo_dispatch_self_check" in rule_ids
        assert "gov_action_model_v2" in rule_ids
        assert "gov_subagent_boot_template" in rule_ids
        assert "gov_ceo_methodology" in rule_ids

    def test_git_commit_matches_commit_rule(self):
        reg = self._build_registry()
        payload = _bash_payload("git commit -m 'test'")
        matches = reg.find_matching_rules(payload)
        rule_ids = {m.rule_id for m in matches}
        assert "gov_auto_commit_push" in rule_ids

    def test_stop_hook_matches_reply_scan(self):
        reg = self._build_registry()
        payload = _stop_payload("some reply")
        matches = reg.find_matching_rules(payload)
        rule_ids = {m.rule_id for m in matches}
        assert "gov_reply_scan" in rule_ids

    def test_session_end_matches_handoff(self):
        reg = self._build_registry()
        payload = _session_end_payload()
        matches = reg.find_matching_rules(payload)
        rule_ids = {m.rule_id for m in matches}
        assert "gov_session_end_handoff" in rule_ids

    def test_priority_ordering(self):
        reg = self._build_registry()
        rules = reg.all_rules()
        priorities = [r.priority for r in rules]
        assert priorities == sorted(priorities, reverse=True)
