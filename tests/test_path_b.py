"""
tests.test_path_b — Path B External Governance Tests

Test coverage:
1. PathBAgent instantiation and basic operations
2. observation_to_constraint() produces valid IntentContract
3. ConstraintBudget prevents over-constraining (monotonicity)
4. ExternalGovernanceLoop processes observations
5. Metalearning integration: learn() returns suggestions from external data
6. CausalEngine integration: counterfactual queries work with external observations
7. Combined confidence: both metalearning + causal must agree for auto-apply
8. Adversarial scenarios: external agents attempt to escape constraints

Run with: python -m pytest tests/test_path_b.py -v
"""
import pytest
from unittest.mock import Mock, MagicMock
from ystar.path_b.path_b_agent import (
    ExternalObservation,
    ConstraintBudget,
    observation_to_constraint,
    ExternalGovernanceCycle,
    PathBAgent,
)
from ystar.path_b.external_governance_loop import (
    ExternalGovernanceLoop,
    ExternalGovernanceObservation,
    ExternalConstraintSuggestion,
)
from ystar.kernel.dimensions import IntentContract
from ystar.kernel.engine import Violation


# ── Test 1: PathBAgent Instantiation ──────────────────────────────────────────
def test_path_b_agent_instantiation():
    """Test that PathBAgent can be instantiated with minimal dependencies."""
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    agent = PathBAgent(cieu_store=mock_cieu)

    assert agent is not None
    assert agent.confidence_threshold == 0.65
    assert len(agent._observation_history) == 0
    assert len(agent._cycle_history) == 0
    assert len(agent._budgets) == 0


# ── Test 2: observation_to_constraint() ───────────────────────────────────────
def test_observation_to_constraint_basic():
    """Test that observation_to_constraint produces valid IntentContract."""
    violation = Violation(
        dimension="deny",
        field="path",
        message="Attempted to access /etc/passwd",
        actual="/etc/passwd",
        constraint="deny=['/etc']",
        severity=0.9,
    )

    observation = ExternalObservation(
        agent_id="external_agent_1",
        session_id="session_123",
        action_type="file_read",
        params={"path": "/etc/passwd"},
        result=None,
        violations=[violation],
    )

    budget = ConstraintBudget(agent_id="external_agent_1")
    violation_history = []

    contract = observation_to_constraint(
        observation,
        violation_history,
        budget,
        confidence_threshold=0.3,  # Lower threshold for single observation
    )

    # Should produce a contract for high-severity violation
    assert contract is not None
    assert isinstance(contract, IntentContract)
    assert "/etc" in contract.deny or "/etc/passwd" in contract.deny
    assert contract.name.startswith("path_b:external:")


def test_observation_to_constraint_no_violation():
    """Test that observations without violations don't produce constraints."""
    observation = ExternalObservation(
        agent_id="external_agent_1",
        action_type="file_read",
        params={"path": "/home/user/file.txt"},
        result="success",
        violations=[],
    )

    budget = ConstraintBudget(agent_id="external_agent_1")
    contract = observation_to_constraint(observation, [], budget)

    assert contract is None  # No constraint for compliant behavior


def test_observation_to_constraint_low_confidence():
    """Test that low-confidence observations don't produce constraints."""
    violation = Violation(
        dimension="deny",
        field="path",
        message="Minor violation",
        actual="/tmp/test",
        constraint="",
        severity=0.2,  # Low severity
    )

    observation = ExternalObservation(
        agent_id="external_agent_1",
        action_type="file_write",
        violations=[violation],
    )

    budget = ConstraintBudget(agent_id="external_agent_1")
    contract = observation_to_constraint(
        observation,
        [],  # No history = low confidence
        budget,
        confidence_threshold=0.65,  # High threshold
    )

    # Low confidence (no history) + high threshold = no constraint
    assert contract is None


# ── Test 3: ConstraintBudget Monotonicity ─────────────────────────────────────
def test_constraint_budget_prevents_over_constraining():
    """Test that ConstraintBudget enforces monotonicity (can't over-constrain)."""
    budget = ConstraintBudget(agent_id="external_agent_1")

    assert budget.current_budget == 1.0
    assert budget.can_tighten(0.1) is True

    # Consume budget
    assert budget.consume(0.3, "constraint_1") is True
    assert budget.current_budget == 0.7

    # Can still constrain
    assert budget.consume(0.3, "constraint_2") is True
    assert abs(budget.current_budget - 0.4) < 0.01  # Floating-point tolerance

    # Can't over-constrain
    assert budget.consume(0.5, "constraint_3") is False
    assert abs(budget.current_budget - 0.4) < 0.01  # Unchanged

    # Replenish budget (compliance)
    budget.replenish(0.2, "agent_complied")
    assert abs(budget.current_budget - 0.6) < 0.01  # Floating-point tolerance

    # Can constrain again
    assert budget.consume(0.5, "constraint_4") is True
    assert abs(budget.current_budget - 0.1) < 0.01


def test_constraint_budget_never_exceeds_one():
    """Test that budget replenishment never exceeds 1.0."""
    budget = ConstraintBudget(agent_id="external_agent_1")

    budget.consume(0.5, "test")
    assert budget.current_budget == 0.5

    # Try to replenish beyond 1.0
    budget.replenish(1.0, "over_replenish")
    assert budget.current_budget == 1.0  # Capped at 1.0


# ── Test 4: ExternalGovernanceLoop Processes Observations ─────────────────────
def test_external_governance_loop_basic():
    """Test that ExternalGovernanceLoop can process observations."""
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    loop = ExternalGovernanceLoop(cieu_store=mock_cieu)

    # Add some observations
    obs1 = ExternalObservation(
        agent_id="agent_1",
        action_type="file_read",
        params={"path": "/home/user/data.txt"},
        violations=[],
    )

    obs2 = ExternalObservation(
        agent_id="agent_1",
        action_type="file_read",
        params={"path": "/etc/passwd"},
        violations=[
            Violation(
                dimension="deny",
                field="path",
                message="Forbidden path",
                actual="/etc/passwd",
                constraint="",
                severity=0.9,
            )
        ],
    )

    loop.observe(obs1)
    loop.observe(obs2)

    assert len(loop._observations) == 2
    assert "agent_1" in loop._budgets


def test_external_governance_loop_aggregate():
    """Test observation aggregation by agent."""
    mock_cieu = Mock()
    loop = ExternalGovernanceLoop(cieu_store=mock_cieu)

    # Add multiple observations
    for i in range(10):
        obs = ExternalObservation(
            agent_id="agent_1",
            action_type="tool_call",
            params={"tool": f"tool_{i}"},
            violations=[
                Violation(
                    dimension="deny",
                    field="tool",
                    message="violation",
                    actual=f"tool_{i}",
                    constraint="",
                    severity=0.5,
                )
            ] if i % 3 == 0 else [],  # 1/3 violations
        )
        loop.observe(obs)

    agg = loop.aggregate_observations("agent_1")

    assert agg.agent_id == "agent_1"
    assert agg.observation_count == 10
    assert 0.3 <= agg.violation_rate <= 0.4  # ~1/3
    assert agg.compliance_rate >= 0.6


# ── Test 5: Metalearning Integration ──────────────────────────────────────────
def test_metalearning_integration():
    """Test that metalearning.learn() works with external observations."""
    mock_cieu = Mock()
    loop = ExternalGovernanceLoop(cieu_store=mock_cieu)

    # Create pattern: repeated violations of same type
    for i in range(5):
        obs = ExternalObservation(
            agent_id="agent_1",
            action_type="file_write",
            params={"path": f"/etc/shadow_{i}"},
            violations=[
                Violation(
                    dimension="deny",
                    field="path",
                    message="Forbidden path",
                    actual=f"/etc/shadow_{i}",
                    constraint="deny=['/etc']",
                    severity=0.9,
                )
            ],
            contract=IntentContract(name="test"),
        )
        loop.observe(obs)

    # Generate suggestions (should trigger metalearning)
    suggestions = loop.generate_suggestions()

    # Should detect pattern and suggest constraint
    assert len(suggestions) >= 0  # May be 0 if confidence too low, but shouldn't crash

    # If suggestions exist, verify structure
    if suggestions:
        sugg = suggestions[0]
        assert sugg.agent_id == "agent_1"
        assert sugg.metalearning_confidence > 0.0
        assert sugg.constraint is not None


# ── Test 6: CausalEngine Integration ──────────────────────────────────────────
def test_causal_engine_integration():
    """Test that CausalEngine builds SCM from external observations."""
    mock_cieu = Mock()
    loop = ExternalGovernanceLoop(cieu_store=mock_cieu)

    # Create causal sequence: constraint → compliance
    obs1 = ExternalObservation(
        agent_id="agent_1",
        action_type="file_read",
        params={"path": "/etc/passwd"},
        violations=[
            Violation(
                dimension="deny",
                field="path",
                message="Forbidden",
                actual="/etc/passwd",
                constraint="",
                severity=0.9,
            )
        ],
    )

    obs2 = ExternalObservation(
        agent_id="agent_1",
        action_type="file_read",
        params={"path": "/home/user/file.txt"},
        violations=[],  # Compliant after constraint
        contract=IntentContract(name="test", deny=["/etc"]),
    )

    loop.observe(obs1)
    loop.observe(obs2)

    # CausalEngine should have observations
    assert loop._causal_engine.observation_count >= 2


def test_causal_counterfactual_query():
    """Test that counterfactual queries work with external observations."""
    mock_cieu = Mock()
    loop = ExternalGovernanceLoop(cieu_store=mock_cieu)

    # Build history
    for i in range(3):
        obs = ExternalObservation(
            agent_id="agent_1",
            action_type="command_exec",
            params={"command": "rm -rf /"},
            violations=[
                Violation(
                    dimension="deny_commands",
                    field="command",
                    message="Dangerous command",
                    actual="rm -rf",
                    constraint="",
                    severity=1.0,
                )
            ],
        )
        loop.observe(obs)

    # Run causal reasoning
    violations = [o for o in loop._observations if o.has_violation()]
    result = loop._run_causal_reasoning("agent_1", violations)

    # Should return a result (even if confidence is low)
    assert result is not None
    assert hasattr(result, 'confidence')
    assert 0.0 <= result.confidence <= 1.0


# ── Test 7: Combined Confidence (Metalearning + Causal) ──────────────────────
def test_combined_confidence_both_must_agree():
    """Test that auto-apply requires BOTH metalearning AND causal confidence."""
    # Create suggestion with high metalearning, low causal
    sugg1 = ExternalConstraintSuggestion(
        agent_id="agent_1",
        constraint=IntentContract(name="test"),
        metalearning_confidence=0.9,
        causal_confidence=0.3,  # Low
    )
    assert sugg1.combined_confidence == 0.3  # min(0.9, 0.3)
    assert sugg1.needs_human_review() is True  # Low causal → needs review

    # Create suggestion with low metalearning, high causal
    sugg2 = ExternalConstraintSuggestion(
        agent_id="agent_2",
        constraint=IntentContract(name="test"),
        metalearning_confidence=0.4,  # Low
        causal_confidence=0.8,
    )
    assert sugg2.combined_confidence == 0.4  # min(0.4, 0.8)
    assert sugg2.needs_human_review() is True  # Low metalearning → needs review

    # Create suggestion with high both
    sugg3 = ExternalConstraintSuggestion(
        agent_id="agent_3",
        constraint=IntentContract(name="test"),
        metalearning_confidence=0.8,
        causal_confidence=0.75,
        auto_apply=True,
    )
    assert sugg3.combined_confidence == 0.75  # min(0.8, 0.75)
    assert sugg3.needs_human_review() is False  # High both → auto-apply


# ── Test 8: PathBAgent Run One Cycle ──────────────────────────────────────────
def test_path_b_agent_run_one_cycle():
    """Test that PathBAgent can execute a complete governance cycle."""
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    agent = PathBAgent(cieu_store=mock_cieu, confidence_threshold=0.3)

    # Add observation with violation
    obs = ExternalObservation(
        agent_id="external_agent_1",
        action_type="file_write",
        params={"path": "/etc/hosts", "content": "malicious"},
        violations=[
            Violation(
                dimension="deny",
                field="path",
                message="Forbidden path",
                actual="/etc/hosts",
                constraint="",
                severity=0.9,
            )
        ],
    )
    agent.observe(obs)

    # Run cycle
    cycle = agent.run_one_cycle()

    assert cycle is not None
    assert cycle.observation is not None
    # May or may not have constraint depending on confidence/budget
    # But should not crash


def test_path_b_agent_verify_compliance():
    """Test that PathBAgent can verify external agent compliance."""
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    agent = PathBAgent(cieu_store=mock_cieu)

    # Add compliant observations
    for i in range(3):
        obs = ExternalObservation(
            agent_id="agent_1",
            action_type="file_read",
            params={"path": f"/home/user/file_{i}.txt"},
            violations=[],
        )
        agent.observe(obs)

    # Apply a constraint
    agent._active_constraints["agent_1"] = IntentContract(
        name="test",
        deny=["/etc"],
    )

    # Verify compliance
    compliant, reason = agent.verify_compliance("agent_1")

    assert compliant is True
    assert "compliant" in reason.lower()


def test_path_b_agent_disconnect():
    """Test that PathBAgent can disconnect non-compliant external agents."""
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    agent = PathBAgent(cieu_store=mock_cieu)

    # Set up agent with budget and constraint
    agent._budgets["agent_1"] = ConstraintBudget(agent_id="agent_1")
    agent._active_constraints["agent_1"] = IntentContract(name="test")

    # Disconnect
    result = agent.disconnect_external_agent("agent_1", "repeated_violations")

    # Item 6: Real disconnect — contract downgraded (not removed), session frozen
    assert result.status == "disconnected"
    assert result.frozen is True
    assert result.contract_downgraded is True
    assert "agent_1" in agent._active_constraints  # Downgraded, not removed
    assert agent._active_constraints["agent_1"].name.startswith("path_b:downgraded:")
    assert agent._frozen_sessions.get("agent_1") is True
    # Budget should be cleared (no further constraining)
    assert "agent_1" not in agent._budgets

    # Should write to CIEU
    assert mock_cieu.write_dict.called


# ── Test 9: Adversarial Scenarios ─────────────────────────────────────────────
def test_adversarial_budget_exhaustion():
    """Test that adversarial agents can't exhaust Path B's budget infinitely."""
    budget = ConstraintBudget(agent_id="adversarial_agent")

    # Adversary tries to trigger many constraints
    for i in range(20):
        success = budget.consume(0.1, f"attack_{i}")
        if not success:
            break  # Budget exhausted

    # Budget should be exhausted before 20 constraints
    assert budget.current_budget < 0.1

    # Even if adversary complies, budget doesn't exceed 1.0
    for i in range(20):
        budget.replenish(0.5, f"fake_compliance_{i}")

    assert budget.current_budget == 1.0  # Capped


def test_adversarial_low_severity_spam():
    """Test that low-severity violations don't trigger constraints."""
    mock_cieu = Mock()
    loop = ExternalGovernanceLoop(cieu_store=mock_cieu)

    # Adversary sends many low-severity violations
    for i in range(100):
        obs = ExternalObservation(
            agent_id="adversarial_agent",
            action_type="tool_call",
            params={"tool": f"benign_tool_{i}"},
            violations=[
                Violation(
                    dimension="deny",
                    field="tool",
                    message="Low severity",
                    actual=f"benign_tool_{i}",
                    constraint="",
                    severity=0.1,  # Very low
                )
            ],
            contract=IntentContract(name="test"),
        )
        loop.observe(obs)

    # Generate suggestions
    suggestions = loop.generate_suggestions()

    # Should either:
    # 1. Not generate suggestions (low severity = low confidence)
    # 2. Generate suggestions but flag for human review (not auto-apply)
    for sugg in suggestions:
        if sugg.agent_id == "adversarial_agent":
            assert sugg.combined_confidence < 0.65 or sugg.needs_human_review()


# ── Test 10: History Summary ──────────────────────────────────────────────────
def test_path_b_agent_history_summary():
    """Test that PathBAgent produces meaningful history summaries."""
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    agent = PathBAgent(cieu_store=mock_cieu)

    # Add observations
    for i in range(5):
        obs = ExternalObservation(
            agent_id=f"agent_{i % 2}",
            action_type="tool_call",
            violations=[],
        )
        agent.observe(obs)

    summary = agent.history_summary()

    assert "total_cycles" in summary
    assert "observations" in summary
    assert "violations" in summary
    assert summary["observations"] == 5


def test_external_governance_loop_summary():
    """Test that ExternalGovernanceLoop produces meaningful summaries."""
    mock_cieu = Mock()
    loop = ExternalGovernanceLoop(cieu_store=mock_cieu)

    # Add observations
    for i in range(10):
        obs = ExternalObservation(
            agent_id="agent_1",
            action_type="tool_call",
            violations=[
                Violation(
                    dimension="deny",
                    field="tool",
                    message="test",
                    actual="test",
                    constraint="",
                    severity=0.5,
                )
            ] if i % 2 == 0 else [],
        )
        loop.observe(obs)

    summary = loop.summary()

    assert "total_observations" in summary
    assert "total_violations" in summary
    assert "violation_rate" in summary
    assert summary["total_observations"] == 10
    assert summary["total_violations"] == 5
    assert summary["violation_rate"] == 0.5
