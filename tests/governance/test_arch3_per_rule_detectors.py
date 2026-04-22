"""
Tests for CZL-ARCH-3: Per-rule detectors migrated to RouterRegistry.

Coverage:
  1. boundary_enforcer.py has zero sys.path.insert calls
  2. boundary_enforcer.py has zero imports from per_rule_detectors
  3. ystar.rules.per_rule_detectors exports 6 RouterRules
  4. Each detector function returns correct violation structure
  5. RouterRules integrate with RouterRegistry correctly
  6. register_builtin_rules() is idempotent
  7. Detector functions match expected payloads
  8. Detector functions skip non-matching payloads
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from ystar.governance.router_registry import (
    RouterRegistry,
    RouterResult,
    RouterRule,
    reset_default_registry,
)
from ystar.rules.per_rule_detectors import (
    ALL_DETECTOR_FUNCTIONS,
    RULES,
    register_builtin_rules,
    _detect_dispatch_missing_5tuple,
    _detect_receipt_rt_not_zero,
    _detect_charter_drift_mid_session,
    _detect_wave_scope_undeclared,
    _detect_subagent_unauthorized_git_op,
    _detect_realtime_artifact_archival,
)


# ── Test 1: boundary_enforcer.py has no reverse dependency ─────────────────

class TestBoundaryEnforcerClean:
    """Verify CZL-ARCH-3 removed all sys.path.insert and per_rule_detectors imports."""

    def test_no_sys_path_insert(self):
        """boundary_enforcer.py must have zero sys.path.insert calls."""
        be_path = Path(__file__).resolve().parent.parent.parent / "ystar" / "adapters" / "boundary_enforcer.py"
        content = be_path.read_text()
        # Only count actual code lines, not comments
        code_lines = [
            line for line in content.splitlines()
            if "sys.path.insert" in line and not line.strip().startswith("#")
        ]
        assert len(code_lines) == 0, (
            f"boundary_enforcer.py still has {len(code_lines)} sys.path.insert call(s): "
            f"{code_lines}"
        )

    def test_no_per_rule_detectors_import(self):
        """boundary_enforcer.py must not import from per_rule_detectors."""
        be_path = Path(__file__).resolve().parent.parent.parent / "ystar" / "adapters" / "boundary_enforcer.py"
        content = be_path.read_text()
        code_lines = [
            line for line in content.splitlines()
            if re.search(r"(from|import)\s+per_rule_detectors", line)
            and not line.strip().startswith("#")
        ]
        assert len(code_lines) == 0, (
            f"boundary_enforcer.py still imports per_rule_detectors: {code_lines}"
        )


# ── Test 2: RULES export structure ─────────────────────────────────────────

class TestRulesExport:
    def test_six_rules_exported(self):
        assert len(RULES) == 6

    def test_all_are_router_rules(self):
        for rule in RULES:
            assert isinstance(rule, RouterRule)

    def test_rule_ids_prefixed(self):
        for rule in RULES:
            assert rule.rule_id.startswith("builtin.per_rule."), (
                f"Rule {rule.rule_id} missing 'builtin.per_rule.' prefix"
            )

    def test_advisory_priority(self):
        for rule in RULES:
            assert rule.priority == 50, (
                f"Rule {rule.rule_id} has priority {rule.priority}, expected 50"
            )

    def test_metadata_has_phase(self):
        for rule in RULES:
            assert rule.metadata.get("phase") == "ARCH-3"


# ── Test 3: Detector functions ──────────────────────────────────────────────

class TestDetectorFunctions:
    def test_six_detector_functions(self):
        assert len(ALL_DETECTOR_FUNCTIONS) == 6

    def test_dispatch_missing_5tuple_detects(self):
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "cto",
                "instructions": "Do something without any 5-tuple sections.",
            },
        }
        result = _detect_dispatch_missing_5tuple(payload)
        assert result is not None
        assert result["violation_type"] == "CZL_DISPATCH_MISSING_5TUPLE"
        assert "Y*" in result["missing_sections"]

    def test_dispatch_missing_5tuple_passes_valid(self):
        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "cto",
                "instructions": "**Y*** contract. **Xt** state. **U** actions. **Yt+1** target. **Rt+1** gap.",
            },
        }
        result = _detect_dispatch_missing_5tuple(payload)
        assert result is None

    def test_dispatch_missing_5tuple_skips_non_agent(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        assert _detect_dispatch_missing_5tuple(payload) is None

    def test_receipt_rt_not_zero_detects(self):
        payload = {
            "tool_name": "SendMessage",
            "tool_input": {
                "content": "Task complete. Rt+1 = 0. Ship it.",
            },
        }
        result = _detect_receipt_rt_not_zero(payload)
        assert result is not None
        assert result["violation_type"] == "CZL_RECEIPT_RT_NOT_ZERO"

    def test_receipt_rt_not_zero_passes_with_evidence(self):
        payload = {
            "tool_name": "SendMessage",
            "tool_input": {
                "content": "Rt+1 = 0. pytest output shows 29 passed. ls -la confirms.",
            },
        }
        assert _detect_receipt_rt_not_zero(payload) is None

    def test_charter_drift_detects(self):
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/path/to/AGENTS.md"},
            "agent_id": "some-agent",
        }
        result = _detect_charter_drift_mid_session(payload)
        assert result is not None
        assert result["violation_type"] == "CHARTER_DRIFT_MID_SESSION"

    def test_charter_drift_allows_secretary(self):
        payload = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/path/to/AGENTS.md"},
            "agent_id": "Samantha-Secretary",
        }
        assert _detect_charter_drift_mid_session(payload) is None

    def test_subagent_git_detects_destructive(self):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard HEAD~1"},
            "agent_id": "eng-kernel",
        }
        result = _detect_subagent_unauthorized_git_op(payload)
        assert result is not None
        assert result["violation_type"] == "SUBAGENT_UNAUTHORIZED_GIT_OP"

    def test_subagent_git_allows_cto(self):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard HEAD~1"},
            "agent_id": "cto",
        }
        assert _detect_subagent_unauthorized_git_op(payload) is None

    def test_artifact_archival_detects(self):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "reports/ceo/status.md"},
        }
        result = _detect_realtime_artifact_archival(payload)
        assert result is not None
        assert result["violation_type"] == "ARTIFACT_ARCHIVAL_SCOPE_DETECTED"

    def test_artifact_archival_skips_src(self):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "src/main.py"},
        }
        assert _detect_realtime_artifact_archival(payload) is None


# ── Test 4: RouterRegistry integration ──────────────────────────────────────

class TestRegistryIntegration:
    def setup_method(self):
        reset_default_registry()

    def teardown_method(self):
        reset_default_registry()

    def test_register_builtin_rules_returns_count(self):
        count = register_builtin_rules()
        assert count == 6

    def test_register_builtin_rules_idempotent(self):
        count1 = register_builtin_rules()
        count2 = register_builtin_rules()
        assert count1 == 6
        assert count2 == 0  # All already registered

    def test_rules_match_agent_payload(self):
        register_builtin_rules()
        from ystar.governance.router_registry import get_default_registry
        reg = get_default_registry()

        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "eng-kernel",
                "instructions": "Do something.",
            },
            "agent_id": "ceo",
        }
        matches = reg.find_matching_rules(payload)
        rule_ids = [m.rule_id for m in matches]
        assert "builtin.per_rule.dispatch_missing_5tuple" in rule_ids

    def test_rules_return_allow(self):
        """Per-rule detectors are telemetry — they must ALLOW, not deny."""
        register_builtin_rules()
        from ystar.governance.router_registry import get_default_registry
        reg = get_default_registry()

        payload = {
            "tool_name": "Agent",
            "tool_input": {
                "subagent_type": "eng-kernel",
                "instructions": "No 5tuple here.",
            },
            "agent_id": "ceo",
        }
        matches = reg.find_matching_rules(payload)
        for rule in matches:
            result = reg.execute_rule(rule, payload)
            assert result.decision == "allow", (
                f"Rule {result.rule_id} returned {result.decision}, expected allow"
            )
