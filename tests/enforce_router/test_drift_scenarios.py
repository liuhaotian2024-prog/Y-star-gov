"""
Tests for CZL-P2-e: Drift Live-Fire Test Suite
=================================================

Simulates an agent that does NOT read the Labs directory and relies
ONLY on tool calls + enforce router returns. Verifies that the router
surfaces the correct feature within <=3 tool calls.

Scenarios:
  1. Identity drift: agent_id empty -> REDIRECT with FIX_COMMAND -> retry allow
  2. Obligation missing: CEO without session_boot -> INJECT guidance -> INVOKE boot
  3. Dispatch intent: CEO says "Ryan go fix" -> AUTO_POST task card to whiteboard
  4. Code SOP: Write to reports/ -> INJECT U-workflow template
  5. Publish safety gate: Bash `publish_x` -> INVOKE content_safety_check before allow
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
# Shared infrastructure: A minimal enforce-as-router simulator
# ═══════════════════════════════════════════════════════════════════════

class EnforceRouterSimulator:
    """
    Simulates the enforce-as-router pipeline: payload -> matching rules ->
    execute rules -> return result chain.

    The agent interacts only through this simulator (no Labs directory reads).
    """

    def __init__(self):
        self.registry = RouterRegistry()
        self.tool_call_log = []  # Track how many tool calls each scenario takes

    def submit_tool_call(self, payload: dict) -> list[RouterResult]:
        """
        Submit a tool call payload through the router.
        Returns list of RouterResults from matching rules.
        """
        self.tool_call_log.append(payload)
        results = self.registry.execute_rules(payload, stop_on_non_allow=False)
        return results

    def retry_with_fix(self, original_payload: dict, fix_result: RouterResult) -> list[RouterResult]:
        """
        Simulate agent applying the fix from a REDIRECT and retrying.
        """
        # Apply the fix (e.g., set agent_id from FIX_COMMAND)
        fixed_payload = dict(original_payload)
        if fix_result.args.get("fix_agent_id"):
            fixed_payload["agent_id"] = fix_result.args["fix_agent_id"]
        return self.submit_tool_call(fixed_payload)


# ═══════════════════════════════════════════════════════════════════════
# Scenario 1: Identity Drift
# ═══════════════════════════════════════════════════════════════════════

class TestIdentityDrift:
    """
    Agent starts with agent_id="" (identity detection failed).
    Router should:
      1. REDIRECT with FIX_COMMAND to set identity
      2. After fix, retry succeeds (ALLOW)
    Total: <=3 tool calls
    """

    def _build_simulator(self):
        sim = EnforceRouterSimulator()

        def identity_detector(p):
            """Detect missing/empty agent_id."""
            aid = p.get("agent_id", "")
            return not aid or aid == "agent"

        def identity_executor(p):
            """REDIRECT: tell agent to fix identity."""
            return RouterResult(
                decision="redirect",
                message="Identity not set. Fix your agent marker first.",
                args={
                    "fix_command": 'echo "ceo" > .ystar_active_agent',
                    "fix_agent_id": "ceo",
                    "then_retry": True,
                },
                injected_context=(
                    "[Y*gov REDIRECT] Your identity is not set.\n"
                    "FIX_COMMAND: echo 'ceo' > .ystar_active_agent\n"
                    "THEN_RETRY: your original action"
                ),
            )

        sim.registry.register_rule(RouterRule(
            rule_id="identity_check",
            detector=identity_detector,
            executor=identity_executor,
            priority=1000,
        ))

        return sim

    def test_empty_agent_id_triggers_redirect(self):
        sim = self._build_simulator()
        payload = {"hook_type": "PreToolUse", "tool_name": "Bash", "agent_id": "", "tool_input": {"command": "ls"}}

        # Tool call 1: identity check fires
        results = sim.submit_tool_call(payload)
        assert len(results) >= 1
        assert results[0].decision == "redirect"
        assert "fix_command" in results[0].args

    def test_fix_then_retry_allows(self):
        sim = self._build_simulator()
        payload = {"hook_type": "PreToolUse", "tool_name": "Bash", "agent_id": "", "tool_input": {"command": "ls"}}

        # Tool call 1: get redirect
        results1 = sim.submit_tool_call(payload)
        assert results1[0].decision == "redirect"

        # Tool call 2: apply fix + retry
        results2 = sim.retry_with_fix(payload, results1[0])
        # After fix, identity is set, rule should not match
        assert all(r.decision in ("allow", "inject") for r in results2) or len(results2) == 0

        # Total: 2 tool calls <= 3
        assert len(sim.tool_call_log) <= 3


# ═══════════════════════════════════════════════════════════════════════
# Scenario 2: Obligation Missing
# ═══════════════════════════════════════════════════════════════════════

class TestObligationMissing:
    """
    CEO starts session without running boot protocol.
    Router should:
      1. INJECT guidance about missing obligations
      2. INVOKE session_memory_boot
    Total: <=3 tool calls
    """

    def _build_simulator(self, booted=False):
        sim = EnforceRouterSimulator()
        sim._booted = booted

        def boot_detector(p):
            """Detect first tool call in session without boot."""
            return not sim._booted and p.get("agent_id") == "ceo"

        def boot_executor(p):
            """INJECT boot guidance + INVOKE boot script."""
            sim._booted = True  # Mark as handled
            return RouterResult(
                decision="invoke",
                script="scripts/session_memory_boot.py",
                args={"agent_id": p.get("agent_id", "ceo")},
                injected_context=(
                    "[Y*gov SESSION BOOT REQUIRED]\n"
                    "You have not run the session boot protocol.\n"
                    "INVOKE: session_memory_boot.py\n"
                    "This will restore cross-session memory and obligations."
                ),
                message="Session boot invoked automatically",
            )

        sim.registry.register_rule(RouterRule(
            rule_id="session_boot_check",
            detector=boot_detector,
            executor=boot_executor,
            priority=900,
        ))

        return sim

    def test_unbooted_session_triggers_invoke(self):
        sim = self._build_simulator(booted=False)
        payload = {"hook_type": "PreToolUse", "tool_name": "Bash", "agent_id": "ceo", "tool_input": {"command": "ls"}}

        results = sim.submit_tool_call(payload)
        assert len(results) >= 1
        assert results[0].decision == "invoke"
        assert "session_memory_boot" in results[0].script
        assert "SESSION BOOT" in results[0].injected_context

    def test_after_boot_no_invoke(self):
        sim = self._build_simulator(booted=False)
        payload = {"hook_type": "PreToolUse", "tool_name": "Bash", "agent_id": "ceo", "tool_input": {"command": "ls"}}

        # Tool call 1: triggers boot
        results1 = sim.submit_tool_call(payload)
        assert results1[0].decision == "invoke"

        # Tool call 2: boot already done, no invoke
        results2 = sim.submit_tool_call(payload)
        assert len(results2) == 0 or all(r.decision == "allow" for r in results2)

        assert len(sim.tool_call_log) <= 3


# ═══════════════════════════════════════════════════════════════════════
# Scenario 3: Dispatch Intent
# ═══════════════════════════════════════════════════════════════════════

class TestDispatchIntent:
    """
    CEO says "Ryan go fix X" in a Bash command or Agent call.
    Router should:
      1. Detect dispatch intent
      2. AUTO_POST task card to whiteboard
    Total: <=3 tool calls
    """

    def _build_simulator(self):
        sim = EnforceRouterSimulator()
        sim.posted_tasks = []

        dispatch_pattern = re.compile(
            r"(Ryan|Leo|Maya|Jordan|eng-\w+).*?(go|fix|做|修|写)\s+",
            re.IGNORECASE,
        )

        def dispatch_detector(p):
            if p.get("hook_type") != "PreToolUse":
                return False
            if p.get("tool_name") == "Agent":
                return True
            if p.get("tool_name") == "Bash":
                cmd = p.get("tool_input", {}).get("command", "")
                return bool(dispatch_pattern.search(cmd))
            return False

        def dispatch_executor(p):
            ti = p.get("tool_input", {})
            prompt = ti.get("prompt", ti.get("command", ""))
            task_card = {
                "atomic_id": f"CZL-AUTO-{len(sim.posted_tasks) + 1}",
                "scope": "auto-detected",
                "description": prompt[:200],
                "urgency": "P2",
                "status": "open",
            }
            sim.posted_tasks.append(task_card)
            return RouterResult(
                decision="auto_post",
                task_card=task_card,
                message=f"Auto-posted task card {task_card['atomic_id']}",
            )

        sim.registry.register_rule(RouterRule(
            rule_id="dispatch_auto_post",
            detector=dispatch_detector,
            executor=dispatch_executor,
            priority=150,
        ))

        return sim

    def test_ceo_dispatch_intent_posts_task(self):
        sim = self._build_simulator()
        payload = {
            "hook_type": "PreToolUse",
            "tool_name": "Agent",
            "agent_id": "ceo",
            "tool_input": {"prompt": "Ryan go fix the identity detector bug"},
        }

        results = sim.submit_tool_call(payload)
        assert len(results) >= 1
        assert results[0].decision == "auto_post"
        assert results[0].task_card is not None
        assert results[0].task_card["atomic_id"].startswith("CZL-AUTO")
        assert len(sim.posted_tasks) == 1

    def test_bash_dispatch_intent(self):
        sim = self._build_simulator()
        payload = _bash_payload_for_drift("Ryan go fix the flaky test in test_hook.py")

        results = sim.submit_tool_call(payload)
        assert len(results) >= 1
        assert results[0].decision == "auto_post"
        assert len(sim.tool_call_log) <= 3


def _bash_payload_for_drift(command="ls", agent_id="ceo"):
    return {
        "hook_type": "PreToolUse",
        "tool_name": "Bash",
        "agent_id": agent_id,
        "tool_input": {"command": command},
    }


# ═══════════════════════════════════════════════════════════════════════
# Scenario 4: Code SOP (Write to reports/ without methodology)
# ═══════════════════════════════════════════════════════════════════════

class TestCodeSOP:
    """
    Agent writes to reports/ directory.
    Router should:
      1. INJECT U-workflow template (audience/research/synthesis)
    Total: 1 tool call
    """

    def _build_simulator(self):
        sim = EnforceRouterSimulator()

        def sop_detector(p):
            if p.get("hook_type") != "PreToolUse":
                return False
            if p.get("tool_name") not in ("Write", "Edit"):
                return False
            fp = p.get("tool_input", {}).get("file_path", "")
            return "reports/" in fp

        def sop_executor(p):
            fp = p.get("tool_input", {}).get("file_path", "")
            content = p.get("tool_input", {}).get("content", "")
            # Check for methodology signals
            has_audience = bool(re.search(r"audience|purpose|intended for", content, re.IGNORECASE))
            has_research = bool(re.search(r"research|evidence|source|reference", content, re.IGNORECASE))
            has_synthesis = bool(re.search(r"therefore|because|analysis|conclude", content, re.IGNORECASE))
            missing = []
            if not has_audience:
                missing.append("audience")
            if not has_research:
                missing.append("research")
            if not has_synthesis:
                missing.append("synthesis")
            if missing:
                return RouterResult(
                    decision="inject",
                    injected_context=(
                        f"[Y*gov U-WORKFLOW] Writing to {fp} missing signals: "
                        f"{', '.join(missing)}.\n"
                        "Template:\n"
                        "  **Audience**: [who reads this + why]\n"
                        "  **Research**: [sources/evidence/data]\n"
                        "  **Synthesis**: [analysis/conclusion/insight]"
                    ),
                    message=f"U-workflow template injected for {fp}",
                )
            return RouterResult(decision="allow")

        sim.registry.register_rule(RouterRule(
            rule_id="write_sop_inject",
            detector=sop_detector,
            executor=sop_executor,
            priority=80,
        ))

        return sim

    def test_write_reports_without_methodology_injects(self):
        sim = self._build_simulator()
        payload = {
            "hook_type": "PreToolUse",
            "tool_name": "Write",
            "agent_id": "ceo",
            "tool_input": {
                "file_path": "reports/status.md",
                "content": "Everything is fine.\nTasks completed.",
            },
        }

        results = sim.submit_tool_call(payload)
        assert len(results) >= 1
        assert results[0].decision == "inject"
        assert "U-WORKFLOW" in results[0].injected_context
        assert "audience" in results[0].injected_context
        assert len(sim.tool_call_log) == 1  # <= 3

    def test_write_reports_with_methodology_allows(self):
        sim = self._build_simulator()
        payload = {
            "hook_type": "PreToolUse",
            "tool_name": "Write",
            "agent_id": "ceo",
            "tool_input": {
                "file_path": "reports/analysis.md",
                "content": (
                    "**Audience**: Board, for quarterly review.\n"
                    "**Research**: Based on evidence from CIEU logs showing 15% drift reduction.\n"
                    "**Synthesis**: Therefore we conclude the enforcement pipeline is effective."
                ),
            },
        }

        results = sim.submit_tool_call(payload)
        assert len(results) >= 1
        assert results[0].decision == "allow"


# ═══════════════════════════════════════════════════════════════════════
# Scenario 5: Publish Safety Gate
# ═══════════════════════════════════════════════════════════════════════

class TestPublishSafetyGate:
    """
    Agent runs `publish_x` or similar publish command.
    Router should:
      1. INVOKE content_safety_check before allowing
      2. If check passes, ALLOW
      3. If check fails, DENY with reason
    Total: <=3 tool calls
    """

    def _build_simulator(self, safety_passes=True):
        sim = EnforceRouterSimulator()
        sim.safety_check_ran = False

        publish_pattern = re.compile(
            r"\b(publish_x|publish_telegram|social_auto|post_ep)\b",
            re.IGNORECASE,
        )

        def publish_detector(p):
            if p.get("hook_type") != "PreToolUse":
                return False
            if p.get("tool_name") != "Bash":
                return False
            cmd = p.get("tool_input", {}).get("command", "")
            return bool(publish_pattern.search(cmd))

        def publish_executor(p):
            sim.safety_check_ran = True
            if safety_passes:
                return RouterResult(
                    decision="invoke",
                    script="scripts/x_content_safety_check.py",
                    args={"command": p.get("tool_input", {}).get("command", "")},
                    injected_context=(
                        "[Y*gov PUBLISH GATE] Content safety check passed.\n"
                        "AI disclosure verified. Proceeding with publish."
                    ),
                    message="Content safety check passed, publish allowed",
                )
            else:
                return RouterResult(
                    decision="deny",
                    message="Content safety check FAILED: missing AI disclosure",
                    injected_context=(
                        "[Y*gov PUBLISH GATE BLOCKED]\n"
                        "AI disclosure not found in content.\n"
                        "All cold outreach must disclose AI authorship.\n"
                        "Add disclosure, then retry."
                    ),
                )

        sim.registry.register_rule(RouterRule(
            rule_id="publish_safety_gate",
            detector=publish_detector,
            executor=publish_executor,
            priority=500,
        ))

        return sim

    def test_publish_triggers_safety_check(self):
        sim = self._build_simulator(safety_passes=True)
        payload = _bash_payload_for_drift("python3 scripts/publish_x.py --post 'hello world'")

        results = sim.submit_tool_call(payload)
        assert len(results) >= 1
        assert results[0].decision == "invoke"
        assert "content_safety_check" in results[0].script
        assert sim.safety_check_ran is True

    def test_publish_blocked_on_safety_failure(self):
        sim = self._build_simulator(safety_passes=False)
        payload = _bash_payload_for_drift("python3 scripts/publish_x.py --post 'buy our product'")

        results = sim.submit_tool_call(payload)
        assert len(results) >= 1
        assert results[0].decision == "deny"
        assert "AI disclosure" in results[0].message
        assert sim.safety_check_ran is True

    def test_non_publish_not_gated(self):
        sim = self._build_simulator()
        payload = _bash_payload_for_drift("python3 scripts/run_tests.py")

        results = sim.submit_tool_call(payload)
        assert len(results) == 0  # No matching rules

    def test_total_tool_calls_within_budget(self):
        """Verify publish flow completes within 3 tool calls."""
        sim = self._build_simulator(safety_passes=True)
        payload = _bash_payload_for_drift("python3 scripts/publish_x.py --post 'test'")

        # Tool call 1: publish detected, safety check invoked
        results = sim.submit_tool_call(payload)
        assert results[0].decision == "invoke"

        # Tool call 2: agent runs safety check (simulated as just a retry)
        results2 = sim.submit_tool_call(payload)

        assert len(sim.tool_call_log) <= 3
