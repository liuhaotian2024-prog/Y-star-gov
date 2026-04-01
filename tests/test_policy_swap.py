"""
tests.test_policy_swap — Policy Swap Behavioral Tests (R8)

Verify that swapping policies ACTUALLY changes agent behavior.
Each test: default policy -> run -> capture result.
           Swapped policy -> run -> capture result.
           Assert results DIFFER.

Run with: python -m pytest tests/test_policy_swap.py -v
"""
import pytest
from unittest.mock import Mock
from dataclasses import replace

from ystar.path_a.meta_agent import (
    PathAAgent,
    PathAPolicy,
    suggestion_to_contract,
)
from ystar.path_b.path_b_agent import (
    PathBAgent,
    PathBPolicy,
    ExternalObservation,
    ConstraintBudget,
    observation_to_constraint,
)
from ystar.governance.governance_loop import GovernanceSuggestion
from ystar.kernel.dimensions import IntentContract
from ystar.kernel.engine import Violation
from ystar.module_graph.graph import ModuleGraph


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_suggestion(**overrides):
    defaults = dict(
        target_rule_id="rule_1",
        suggestion_type="tighten",
        confidence=0.8,
        suggested_value="add /tmp to deny list",
    )
    defaults.update(overrides)
    return GovernanceSuggestion(**defaults)


def _make_violation(dimension="deny", actual="/etc/passwd", severity=0.9):
    return Violation(
        dimension=dimension,
        field="path",
        message=f"Attempted to access {actual}",
        actual=actual,
        constraint=f"{dimension}=['{actual}']",
        severity=severity,
    )


def _make_observation(agent_id="ext_agent", violations=None, severity=0.9):
    obs = ExternalObservation(
        agent_id=agent_id,
        action_type="file_read",
        params={"file_path": "/etc/passwd"},
    )
    obs.violations = violations or [_make_violation(severity=severity)]
    return obs


def _make_budget(agent_id="ext_agent"):
    return ConstraintBudget(agent_id=agent_id)


def _make_mock_cieu():
    mock = Mock()
    mock.write_dict = Mock(return_value=True)
    return mock


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: Path A — swap PathAPolicy with different forbidden_paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestPathAPolicySwap:

    def test_different_forbidden_paths_changes_contract(self):
        """Swapping default_forbidden_paths produces a different IntentContract."""
        suggestion = _make_suggestion()
        allowed = ["mod_a"]

        # Default policy
        default_policy = PathAPolicy()
        contract_default = suggestion_to_contract(
            suggestion, allowed, policy=default_policy,
        )

        # Swapped policy: different forbidden paths
        swapped_policy = PathAPolicy(
            default_forbidden_paths=["/custom_secret", "/vault"],
        )
        contract_swapped = suggestion_to_contract(
            suggestion, allowed, policy=swapped_policy,
        )

        # Contracts must differ in deny list
        assert contract_default.deny != contract_swapped.deny
        assert "/etc" in contract_default.deny
        assert "/custom_secret" in contract_swapped.deny
        assert "/etc" not in contract_swapped.deny

    def test_different_forbidden_commands_changes_contract(self):
        """Swapping default_forbidden_commands produces a different IntentContract."""
        suggestion = _make_suggestion()
        allowed = ["mod_a"]

        default_policy = PathAPolicy()
        contract_default = suggestion_to_contract(
            suggestion, allowed, policy=default_policy,
        )

        swapped_policy = PathAPolicy(
            default_forbidden_commands=["halt", "shutdown"],
        )
        contract_swapped = suggestion_to_contract(
            suggestion, allowed, policy=swapped_policy,
        )

        assert contract_default.deny_commands != contract_swapped.deny_commands
        assert "rm -rf" in contract_default.deny_commands
        assert "halt" in contract_swapped.deny_commands

    def test_different_deadline_changes_obligation(self):
        """Swapping default_deadline_secs changes the obligation timing."""
        suggestion = _make_suggestion()
        allowed = ["mod_a"]

        default_policy = PathAPolicy(default_deadline_secs=600.0)
        contract_default = suggestion_to_contract(
            suggestion, allowed, policy=default_policy,
        )

        swapped_policy = PathAPolicy(default_deadline_secs=60.0)
        contract_swapped = suggestion_to_contract(
            suggestion, allowed, policy=swapped_policy,
        )

        assert contract_default.obligation_timing["deadline_secs"] == 600.0
        assert contract_swapped.obligation_timing["deadline_secs"] == 60.0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Path B — swap confidence formula
# ═══════════════════════════════════════════════════════════════════════════════

class TestPathBConfidenceSwap:

    def test_different_confidence_formula_changes_constraint(self):
        """Swapping confidence_base/per_evidence changes constraint generation.

        With default (base=0.3, per=0.1): 1 evidence -> 0.4 confidence (below 0.65)
        With swapped (base=0.6, per=0.2): 1 evidence -> 0.8 confidence (above 0.65)
        """
        obs = _make_observation()
        budget = _make_budget()

        # Default policy: confidence = 0.3 + 1*0.1 = 0.4 < 0.65 threshold
        # With no prior history, cold-start applies only if severity >= 0.5
        # Use low severity to avoid cold-start bypass
        low_sev_obs = _make_observation(severity=0.3)
        default_policy = PathBPolicy()
        result_default = observation_to_constraint(
            low_sev_obs, [], budget, confidence_threshold=0.65,
            policy=default_policy,
        )

        # Swapped policy: confidence = 0.6 + 1*0.2 = 0.8 >= 0.65 threshold
        budget2 = _make_budget()
        swapped_policy = PathBPolicy(
            confidence_base=0.6,
            confidence_per_evidence=0.2,
            cold_start_min_severity=1.0,  # disable cold start
        )
        result_swapped = observation_to_constraint(
            low_sev_obs, [], budget2, confidence_threshold=0.65,
            policy=swapped_policy,
        )

        # Default should return None (low confidence, cold start disabled by low severity)
        # Swapped should return a constraint
        assert result_default is None
        assert result_swapped is not None

    def test_different_cost_formula_changes_budget_consumption(self):
        """Swapping constraint_cost changes budget consumption behavior."""
        obs = _make_observation(severity=0.9)
        history = [obs]  # provide history so cold-start doesn't apply

        # Default cost: 0.05 + 0.9 * 0.05 = 0.095
        budget1 = ConstraintBudget(agent_id="ext_agent", current_budget=0.09)
        default_policy = PathBPolicy()
        result_default = observation_to_constraint(
            obs, history, budget1, confidence_threshold=0.0,
            policy=default_policy,
        )
        # Budget too low for default cost (0.095), should return None
        assert result_default is None

        # Swapped: cost = 0.01 + 0.9 * 0.01 = 0.019
        budget2 = ConstraintBudget(agent_id="ext_agent", current_budget=0.09)
        swapped_policy = PathBPolicy(
            constraint_cost_base=0.01,
            constraint_cost_severity_factor=0.01,
        )
        result_swapped = observation_to_constraint(
            obs, history, budget2, confidence_threshold=0.0,
            policy=swapped_policy,
        )
        # Budget sufficient for swapped cost (0.019), should return constraint
        assert result_swapped is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Path B — swap escalation policy
# ═══════════════════════════════════════════════════════════════════════════════

class TestPathBEscalationSwap:

    def test_different_escalation_steps_changes_sequence(self):
        """Swapping escalation_steps produces different escalation actions."""
        mock_cieu = _make_mock_cieu()

        # Default escalation: warn -> downgrade -> freeze -> disconnect
        agent_default = PathBAgent(cieu_store=mock_cieu)
        obs = _make_observation(agent_id="test_agent")
        agent_default.observe(obs)
        agent_default._active_constraints["test_agent"] = IntentContract(
            name="test", deny=["/etc"],
        )
        result_default = agent_default.escalate_disconnect("test_agent")

        assert "warned" in result_default.details
        assert "downgraded" in result_default.details
        assert "frozen" in result_default.details
        assert "disconnected" in result_default.details

        # Swapped escalation: freeze -> disconnect only (skip warn and downgrade)
        swapped_policy = PathBPolicy(escalation_steps=["freeze", "disconnect"])
        agent_swapped = PathBAgent(cieu_store=_make_mock_cieu(), policy=swapped_policy)
        agent_swapped.observe(_make_observation(agent_id="test_agent2"))
        agent_swapped._active_constraints["test_agent2"] = IntentContract(
            name="test", deny=["/etc"],
        )
        result_swapped = agent_swapped.escalate_disconnect("test_agent2")

        assert "warned" not in result_swapped.details
        assert "downgraded" not in result_swapped.details
        assert "frozen" in result_swapped.details
        assert "disconnected" in result_swapped.details

    def test_soft_freeze_only_escalation(self):
        """Escalation with only freeze step does not disconnect."""
        swapped_policy = PathBPolicy(escalation_steps=["warn", "freeze"])
        agent = PathBAgent(cieu_store=_make_mock_cieu(), policy=swapped_policy)
        agent.observe(_make_observation(agent_id="test_agent"))
        result = agent.escalate_disconnect("test_agent")

        assert result.status == "frozen"
        assert "disconnected" not in result.details
        assert "frozen" in result.details


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: Path B — swap self-governance policy
# ═══════════════════════════════════════════════════════════════════════════════

class TestPathBSelfGovernanceSwap:

    def test_different_self_governance_deny_changes_contract(self):
        """Swapping self_governance_deny changes the self-governance contract used in run_one_cycle."""
        mock_cieu = _make_mock_cieu()

        # Default policy has ["/etc", "/root", "~/.clawdbot", "/production"]
        agent_default = PathBAgent(cieu_store=mock_cieu)
        assert "/etc" in agent_default.policy.self_governance_deny

        # Swapped: different deny list
        swapped_policy = PathBPolicy(
            self_governance_deny=["/custom_only"],
            self_governance_deny_commands=["custom_cmd"],
        )
        agent_swapped = PathBAgent(cieu_store=_make_mock_cieu(), policy=swapped_policy)

        assert agent_swapped.policy.self_governance_deny == ["/custom_only"]
        assert agent_swapped.policy.self_governance_deny_commands == ["custom_cmd"]
        assert "/etc" not in agent_swapped.policy.self_governance_deny

    def test_self_governance_used_in_cycle(self):
        """run_one_cycle uses policy's self-governance fields, not hardcoded values."""
        mock_cieu = _make_mock_cieu()

        # Create agent with custom self-governance that blocks "apply_external_constraint"
        # by putting agent_id pattern in deny
        custom_policy = PathBPolicy(
            self_governance_deny=["apply_external"],  # will match proposed_action
        )
        agent = PathBAgent(cieu_store=mock_cieu, policy=custom_policy)

        # Provide a violation to trigger constraint derivation
        obs = _make_observation(agent_id="ext_test", severity=0.9)
        agent.observe(obs)

        cycle = agent.run_one_cycle()

        # The self-governance check should have caught the deny pattern
        # (the proposed_action contains "apply_external_constraint" which matches "apply_external")
        # So constraint should NOT be applied
        assert cycle.applied == False
