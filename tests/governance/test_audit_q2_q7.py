"""
Test Q2 (multi_task_dispatch_disguise) and Q7 (task_card_without_spawn) ForgetGuard rules.

Universal audit batch (Board 2026-04-16):
- Q2: deny multi-task disguise (≥2 deliverable verbs or enumerated tasks)
- Q7: warn task card reference without spawn instruction

Ref: ystar/governance/forget_guard_rules.yaml lines 213-246
"""
import pytest
import yaml
from pathlib import Path

from ystar.governance.forget_guard import ForgetGuard


RULES_PATH = Path(__file__).resolve().parents[2] / "ystar" / "governance" / "forget_guard_rules.yaml"


def _q2_q7_rules_present() -> bool:
    """Q2/Q7 were retired from ForgetGuard v0.5 structured runtime rules.

    This legacy test module only applies to snapshots where those rules still
    exist in forget_guard_rules.yaml. Current v0.5 ForgetGuard no longer scans
    free-text action_payload for multi-task/task-card patterns.
    """
    if not RULES_PATH.exists():
        return False
    data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}
    names = {r.get("name") for r in data.get("rules", [])}
    return {
        "multi_task_dispatch_disguise",
        "task_card_without_spawn",
    }.issubset(names)


pytestmark = pytest.mark.skipif(
    not _q2_q7_rules_present(),
    reason="Q2/Q7 retired from ForgetGuard v0.5 structured-only runtime rules.",
)


@pytest.fixture
def forget_guard():
    """Initialize ForgetGuard with Q2/Q7 rules."""
    return ForgetGuard()


class TestQ2MultiTaskDispatchDisguise:
    """Test multi_task_dispatch_disguise rule (deny mode, dry_run_until 2026-04-18)."""

    def test_q2_fire_multiple_deliverable_verbs(self, forget_guard):
        """Q2 fires: Agent prompt contains ≥2 distinct deliverable verbs."""
        agent_prompt = """
        Sub-agent, implement the following:
        1. Write test_foo.py with 3 test cases
        2. Write test_bar.py with 2 test cases
        Return receipt with 5-tuple.
        """
        violation = forget_guard.check({
            "agent_id": "coordinator",
            "action_type": "agent_tool_prompt",
            "action_payload": agent_prompt,
        })
        # Dry-run mode: should return violation with in_grace_period=True
        assert violation is not None
        assert violation["rule_name"] == "multi_task_dispatch_disguise"
        assert violation["in_grace_period"] is True  # dry_run_until 2026-04-18

    def test_q2_fire_enumerated_task_pattern(self, forget_guard):
        """Q2 fires: Agent prompt contains enumerated task list (Task 1:, Task 2:)."""
        agent_prompt = """
        Sub-agent, P0 enforce:
        Task 1: Add OmissionEngine baseline pulse verification
        Task 2: Add InterventionEngine chaos test
        Task 3: Wire GovernanceLoop baseline bridge
        Single atomic dispatch, return 5-tuple.
        """
        violation = forget_guard.check({
            "agent_id": "coordinator",
            "action_type": "agent_tool_prompt",
            "action_payload": agent_prompt,
        })
        assert violation is not None
        assert violation["rule_name"] == "multi_task_dispatch_disguise"

    def test_q2_no_fire_single_deliverable_with_scope(self, forget_guard):
        """Q2 no-fire: Single deliverable with scope guard prose remains warn-only."""
        agent_prompt = """
        Sub-agent, P0 enforce:
        Write comprehensive test suite for CausalEngine including:
        - Baseline pulse chain verification
        - Edge case handling
        - Error recovery
        Return receipt with 5-tuple. Atomic dispatch ≤15 tool_uses.
        """
        violation = forget_guard.check({
            "agent_id": "coordinator",
            "action_type": "agent_tool_prompt",
            "action_payload": agent_prompt,
        })
        # Single "Write" verb + scope prose = no multi-task pattern match
        assert violation is None or violation["rule_name"] != "multi_task_dispatch_disguise"

    def test_q2_no_fire_single_task(self, forget_guard):
        """Q2 no-fire: Single task dispatch without enumeration."""
        agent_prompt = """
        Sub-agent, implement baseline CIEU event consumer in GovernanceLoop.
        Return receipt with 5-tuple, atomic ≤15 tool_uses.
        """
        violation = forget_guard.check({
            "agent_id": "coordinator",
            "action_type": "agent_tool_prompt",
            "action_payload": agent_prompt,
        })
        assert violation is None or violation["rule_name"] != "multi_task_dispatch_disguise"


class TestQ7TaskCardWithoutSpawn:
    """Test task_card_without_spawn rule (warn mode, dry_run_until 2026-04-18)."""

    def test_q7_fire_task_card_ref_no_spawn(self, forget_guard):
        """Q7 fires: Agent prompt references task card but lacks spawn instruction."""
        agent_prompt = """
        I'll write the task card to .claude/tasks/baseline-bridge.md
        and it will be executed next session.
        """
        violation = forget_guard.check({
            "agent_id": "coordinator",
            "action_type": "agent_tool_prompt",
            "action_payload": agent_prompt,
        })
        assert violation is not None
        assert violation["rule_name"] == "task_card_without_spawn"
        assert violation["in_grace_period"] is True  # dry_run_until 2026-04-18

    def test_q7_fire_task_card_keyword_no_spawn(self, forget_guard):
        """Q7 fires: 'task card' keyword without spawn."""
        agent_prompt = """
        Writing task card for baseline bridge implementation.
        File: .claude/tasks/baseline-bridge.md
        """
        violation = forget_guard.check({
            "agent_id": "coordinator",
            "action_type": "agent_tool_prompt",
            "action_payload": agent_prompt,
        })
        assert violation is not None
        assert violation["rule_name"] == "task_card_without_spawn"

    def test_q7_no_fire_task_card_with_spawn(self, forget_guard):
        """Q7 no-fire: Task card reference WITH explicit spawn instruction."""
        agent_prompt = """
        Writing task card to .claude/tasks/omission-test.md.
        Spawn sub-agent to execute this task card immediately.
        [DISPATCH:gov-token-abc123]
        """
        violation = forget_guard.check({
            "agent_id": "coordinator",
            "action_type": "agent_tool_prompt",
            "action_payload": agent_prompt,
        })
        # 'spawn' keyword present → no violation
        assert violation is None or violation["rule_name"] != "task_card_without_spawn"

    def test_q7_no_fire_subagent_type_present(self, forget_guard):
        """Q7 no-fire: Agent call with subagent_type parameter."""
        agent_prompt = """
        Task card: .claude/tasks/feature-f3.md
        Agent tool: subagent_type=worker, prompt includes task card path.
        """
        violation = forget_guard.check({
            "agent_id": "coordinator",
            "action_type": "agent_tool_prompt",
            "action_payload": agent_prompt,
        })
        # 'subagent_type' keyword present → no violation
        assert violation is None or violation["rule_name"] != "task_card_without_spawn"


class TestQ2Q7Integration:
    """Integration tests: Q2 + Q7 in same scan (correlated batch)."""

    def test_multi_task_card_write_no_spawn(self, forget_guard):
        """Both Q2 + Q7 fire: multi-task + task card without spawn."""
        agent_prompt = """
        Write task card 1: .claude/tasks/baseline-pulse.md
        Write task card 2: .claude/tasks/omission-test.md
        Engineers will pick these up later.
        """
        # ForgetGuard.check() returns single violation (first match)
        # Need to check both rules separately
        violation_q2 = forget_guard.check({
            "agent_id": "ceo",
            "action_type": "agent_tool_prompt",
            "action_payload": agent_prompt,
        })
        # Q2 should fire (multi Write verbs)
        assert violation_q2 is not None
        assert violation_q2["rule_name"] in ["multi_task_dispatch_disguise", "task_card_without_spawn"]

    def test_single_task_card_with_spawn_clean(self, forget_guard):
        """Neither Q2 nor Q7 fire: atomic dispatch + spawn instruction."""
        agent_prompt = """
        Write .claude/tasks/causal-test.md with deliverable Y*.
        Spawn sub-agent to execute task card immediately.
        [DISPATCH:gov-token-xyz789]
        Receipt 5-tuple required.
        """
        violation = forget_guard.check({
            "agent_id": "coordinator",
            "action_type": "agent_tool_prompt",
            "action_payload": agent_prompt,
        })
        # Neither Q2 (single Write verb) nor Q7 (spawn present) should fire
        assert violation is None or violation["rule_name"] not in [
            "multi_task_dispatch_disguise",
            "task_card_without_spawn"
        ]
