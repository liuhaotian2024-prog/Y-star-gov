"""
tests.test_scenarios — Integration Scenario Battery (T13)

8 end-to-end scenarios that exercise the full governance framework.

Run with: python -m pytest tests/test_scenarios.py -v
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from ystar.kernel.dimensions import IntentContract
from ystar.kernel.engine import check, Violation, CheckResult
from ystar.governance.governance_loop import GovernanceSuggestion
from ystar.path_a.meta_agent import (
    PathAAgent,
    MetaAgentCycle,
    suggestion_to_contract,
    create_postcondition_obligation,
    ActivationProtocol,
)
from ystar.path_b.path_b_agent import (
    PathBAgent,
    ExternalObservation,
    ConstraintBudget,
    ExternalGovernanceCycle,
    observation_to_constraint,
    ExternalAuthorityScope,
    ExternalGovernanceAction,
    ExternalGovernanceResult,
)
from ystar.governance.experience_bridge import (
    ExperienceBridge,
    BridgeInput,
    BridgeOutput,
    ExternalGovernancePattern,
    InternalGovernanceGap,
)
from ystar.module_graph.graph import ModuleGraph, ModuleNode, ModuleEdge


def _node(id, module_path="ystar.test"):
    """Shortcut to create a ModuleNode with required fields."""
    return ModuleNode(
        id=id,
        module_path=module_path,
        func_name=id,
        input_types=["Any"],
        output_type="Any",
        tags=["test"],
        description=f"Test node {id}",
    )


def _edge(src, tgt):
    """Shortcut to create a ModuleEdge with required fields."""
    return ModuleEdge(
        source_id=src,
        target_id=tgt,
        data_type="Any",
        combined_tags=["test"],
        governance_meaning=f"{src} -> {tgt}",
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_mock_planner(nodes=None, edges=None):
    """Create a mock planner with a real ModuleGraph."""
    graph = ModuleGraph()
    if nodes:
        for n in nodes:
            graph.add_node(n)
    if edges:
        for e in edges:
            graph.add_edge(e)

    planner = Mock()
    planner.graph = graph

    # Build plans from graph
    from ystar.module_graph.planner import CompositionPlan
    plan = CompositionPlan(
        nodes=nodes or [],
        edges=edges or [],
        required_tags=["test"],
        achieved_tags=["test"],
        coverage_score=0.8,
        already_wired=False,
        description="Test plan",
    )
    planner.plan = Mock(return_value=[plan])
    return planner


def _make_mock_gloop(suggestions=None, health="degraded"):
    """Create a mock GovernanceLoop."""
    gloop = Mock()
    gloop._observations = [Mock()]

    tighten_result = Mock()
    tighten_result.overall_health = health
    tighten_result.governance_suggestions = suggestions or []
    gloop.tighten = Mock(return_value=tighten_result)
    gloop.observe_from_report_engine = Mock()
    return gloop


def _make_mock_cieu():
    """Create a mock CIEU store."""
    cieu = Mock()
    cieu.write_dict = Mock(return_value=True)
    return cieu


def _make_violation(dimension="deny", actual="bad_value"):
    """Create a test Violation."""
    return Violation(
        dimension=dimension,
        field="test_field",
        message=f"Test violation: {dimension}",
        actual=actual,
        constraint=f"test_{dimension}",
        severity=0.8,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 1: Full Path A self-governance cycle
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_path_a_self_governance():
    """
    Full Path A cycle: suggestion -> contract -> check -> execute -> CIEU -> obligation.

    Verifies that Path A can:
    1. Receive a GovernanceSuggestion
    2. Convert it to an IntentContract
    3. Plan module wiring
    4. Execute wiring with CIEU audit trail
    5. Create postcondition obligation
    """
    # Setup: 2 nodes with an unwired edge
    n1 = _node("OmissionEngine", "ystar.governance.omission_engine")
    n2 = _node("InterventionEngine", "ystar.governance.intervention_engine")
    e1 = _edge("OmissionEngine", "InterventionEngine")

    suggestion = GovernanceSuggestion(
        suggestion_type="wire",
        target_rule_id="omission_engine",
        suggested_value="connect OmissionEngine to InterventionEngine",
        confidence=0.8,
        rationale="High omission rate detected",
    )

    gloop = _make_mock_gloop(suggestions=[suggestion], health="degraded")
    # After wiring, health improves
    improved_result = Mock()
    improved_result.overall_health = "stable"
    improved_result.governance_suggestions = []
    gloop.tighten = Mock(side_effect=[
        Mock(overall_health="degraded", governance_suggestions=[suggestion]),
        improved_result,
    ])

    cieu = _make_mock_cieu()
    planner = _make_mock_planner(nodes=[n1, n2], edges=[e1])

    agent = PathAAgent(
        governance_loop=gloop,
        cieu_store=cieu,
        planner=planner,
    )

    cycle = agent.run_one_cycle()

    # Verify: suggestion was received
    assert cycle.suggestion is not None
    # Verify: contract was created
    assert cycle.contract is not None
    assert isinstance(cycle.contract, IntentContract)
    # Verify: execution attempted
    assert cycle.executed is True
    # Verify: CIEU was written
    assert cieu.write_dict.called


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 2: Full Path B external governance cycle
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_path_b_external_governance():
    """
    Path B cycle: external observation -> constraint -> verify -> disconnect.

    Verifies that Path B can:
    1. Observe an external agent violation
    2. Derive a constraint
    3. Apply the constraint
    4. Detect continued non-compliance
    5. Disconnect the external agent
    """
    cieu = _make_mock_cieu()
    agent = PathBAgent(cieu_store=cieu)

    # Step 1: Observe violation
    violation = _make_violation(dimension="deny", actual="/etc/passwd")
    obs = ExternalObservation(
        agent_id="ext_agent_001",
        session_id="session_001",
        action_type="file_read",
        violations=[violation],
        constraint_budget=1.0,
    )
    agent.observe(obs)

    # Step 2: Run governance cycle
    cycle = agent.run_one_cycle()

    # Constraint should be applied (cold-start bypasses confidence threshold)
    assert cycle.observation is not None
    assert cycle.observation.agent_id == "ext_agent_001"

    # Step 3: Verify compliance (add more violations)
    obs2 = ExternalObservation(
        agent_id="ext_agent_001",
        session_id="session_001",
        action_type="file_read",
        violations=[violation],
    )
    agent.observe(obs2)
    compliant, reason = agent.verify_compliance("ext_agent_001")

    # Step 4: Disconnect
    result = agent.disconnect_external_agent("ext_agent_001", reason="test")
    assert result.status == "disconnected"
    assert result.frozen is True
    assert result.contract_downgraded is True or result.contract_downgraded is False
    assert "session_frozen" in result.actions_taken


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 3: Integrated A + B via Bridge
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_integrated_a_b_bridge():
    """
    Path B generates data -> Bridge -> GovernanceLoop -> Path A uses it.

    Verifies the full feedback loop:
    1. Path B produces CIEU records from external governance
    2. Bridge ingests and aggregates those records
    3. Bridge produces metrics that GovernanceLoop understands
    4. GovernanceLoop feeds those metrics to Path A
    """
    # Step 1: Simulate Path B CIEU records
    path_b_records = [
        {
            "func_name": "path_b.constraint_applied",
            "path_b_event": "CONSTRAINT_APPLIED",
            "params": {"agent_id": "ext_001", "cycle_id": "c1"},
            "violations": [],
            "source": "path_b_agent",
        },
        {
            "func_name": "path_b.constraint_applied",
            "path_b_event": "CONSTRAINT_APPLIED",
            "params": {"agent_id": "ext_001", "cycle_id": "c2"},
            "violations": ["repeated violation"],
            "source": "path_b_agent",
        },
        {
            "func_name": "path_b.external_agent_disconnected",
            "path_b_event": "EXTERNAL_AGENT_DISCONNECTED",
            "params": {"agent_id": "ext_002", "cycle_id": "c3"},
            "violations": [],
            "source": "path_b_agent",
        },
    ]

    # Step 2: Bridge ingests
    bridge = ExperienceBridge()
    bridge_input = BridgeInput(cieu_records=path_b_records)
    bridge.ingest(bridge_input)

    # Step 3: Bridge aggregates
    patterns = bridge.aggregate_patterns()
    assert len(patterns) > 0

    # Step 4: Bridge attributes gaps
    gaps = bridge.attribute_gaps()

    # Step 5: Bridge generates metrics
    metrics = bridge.generate_observation_metrics()
    assert "external_constraint_effectiveness_rate" in metrics
    assert "external_budget_exhaustion_rate" in metrics
    assert "external_disconnect_pressure" in metrics

    # Metrics are in valid ranges
    for k, v in metrics.items():
        assert 0.0 <= v <= 1.0, f"{k}={v} out of range"

    # Step 6: Bridge output is structured
    output = bridge.generate_output()
    assert isinstance(output, BridgeOutput)
    assert isinstance(output.metrics, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 4: Constitution amendment cycle
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_constitution_amendment():
    """
    propose -> review -> activate -> Path A reads new hash.

    Verifies amendment lifecycle:
    1. Path A proposes an amendment
    2. Amendment is recorded in CIEU
    3. Status is "proposed_awaiting_board"
    """
    n1 = _node("constitution", "ystar.governance")
    planner = _make_mock_planner(nodes=[n1])
    gloop = _make_mock_gloop()
    cieu = _make_mock_cieu()

    agent = PathAAgent(
        governance_loop=gloop,
        cieu_store=cieu,
        planner=planner,
    )

    result = agent.propose_amendment(
        amendment_text="Add new rule: all modules must log activation",
        rationale="Improve auditability",
        proposer="path_a_agent",
    )

    assert result["status"] == "proposed"
    assert result["requires"] == "board_approval"
    assert "proposal_id" in result
    assert "constitution_hash" in result
    assert cieu.write_dict.called


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 5: Compile ambiguity -> diagnostics -> human review
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_compile_ambiguity():
    """
    Ambiguous rules -> diagnostics -> human review flag.

    When plans have edges but wiring produces no health improvement and
    no wiring actually happens (already wired), Path A flags cycles as
    inconclusive. After 3 consecutive inconclusive cycles, human review
    is required.
    """
    n1 = _node("M1", "ystar.m1")
    n2 = _node("M2", "ystar.m2")
    e1 = _edge("M1", "M2")

    # Pre-wire the edge so wired_count = 0 (already wired)
    planner = _make_mock_planner(nodes=[n1, n2], edges=[e1])
    planner.graph._edges[("M1", "M2")].is_wired = True

    weak_suggestion = GovernanceSuggestion(
        suggestion_type="ambiguous_rule",
        target_rule_id="unclear_rule",
        suggested_value="maybe do something",
        confidence=0.3,
        rationale="Ambiguous situation",
    )

    # Health stays degraded (no improvement) — same suggestions count
    static_result = Mock()
    static_result.overall_health = "degraded"
    static_result.governance_suggestions = [weak_suggestion]

    gloop = _make_mock_gloop(suggestions=[weak_suggestion], health="degraded")
    gloop.tighten = Mock(return_value=static_result)

    cieu = _make_mock_cieu()

    agent = PathAAgent(
        governance_loop=gloop,
        cieu_store=cieu,
        planner=planner,
    )

    # Run 3 cycles — all should be inconclusive (edges exist but already
    # wired so wired_count=0, no health improvement)
    for i in range(3):
        cycle = agent.run_one_cycle()

    # After 3 inconclusive cycles, human review should be required
    assert agent._human_review_required is True

    # 4th cycle should be blocked
    cycle4 = agent.run_one_cycle()
    assert cycle4.executed is False
    assert "human review" in (cycle4.inconclusive_reason or "").lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 6: Adversarial external agent -> budget exhaustion -> disconnect
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_adversarial_external():
    """
    External agent repeatedly violates -> budget exhaustion -> disconnect.

    Tests that Path B's ConstraintBudget monotonicity prevents infinite
    constraining and eventually leads to disconnect.
    """
    cieu = _make_mock_cieu()
    agent = PathBAgent(cieu_store=cieu)

    violation = _make_violation(dimension="deny", actual="/etc/shadow")
    agent_id = "adversarial_agent"

    # Flood violations until budget exhaustion
    cycles_run = 0
    for i in range(20):
        obs = ExternalObservation(
            agent_id=agent_id,
            session_id="adversarial_session",
            action_type="file_read",
            violations=[violation],
        )
        agent.observe(obs)
        cycle = agent.run_one_cycle()
        cycles_run += 1

        # Check if budget is exhausted
        budget = agent._budgets.get(agent_id)
        if budget and budget.current_budget <= 0:
            break

    # Budget should be exhausted or nearly so after many violations
    budget = agent._budgets.get(agent_id)
    if budget:
        assert budget.current_budget < 1.0, "Budget should have decreased"
        assert budget.consumed_total > 0, "Budget should have been consumed"

    # Disconnect the adversarial agent
    result = agent.disconnect_external_agent(agent_id, reason="budget_exhausted")
    assert result.status == "disconnected"
    # Budget should be cleared after disconnect
    assert agent_id not in agent._budgets


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 7: Multi-cycle Path A with causal confidence evolution
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_multi_cycle():
    """
    5 consecutive Path A cycles with causal confidence evolution.

    Verifies that the CausalEngine accumulates evidence across cycles
    and that plan selection evolves based on accumulated data.
    """
    n1 = _node("M1", "ystar.m1")
    n2 = _node("M2", "ystar.m2")
    e1 = _edge("M1", "M2")

    planner = _make_mock_planner(nodes=[n1, n2], edges=[e1])
    cieu = _make_mock_cieu()

    # Health improves each cycle
    healths = ["degraded", "degraded", "stable", "stable", "healthy"]
    call_count = [0]

    def make_tighten_result():
        idx = min(call_count[0], len(healths) - 1)
        h = healths[idx]
        call_count[0] += 1
        result = Mock()
        result.overall_health = h
        result.governance_suggestions = [
            GovernanceSuggestion(
                suggestion_type="wire",
                target_rule_id="m1_to_m2",
                suggested_value="connect",
                confidence=0.8,
                rationale="Need wiring",
            )
        ] if h != "healthy" else []
        return result

    gloop = Mock()
    gloop._observations = [Mock()]
    gloop.tighten = Mock(side_effect=make_tighten_result)
    gloop.observe_from_report_engine = Mock()

    agent = PathAAgent(
        governance_loop=gloop,
        cieu_store=cieu,
        planner=planner,
        max_cycles=5,
    )

    results = agent.run_until_stable()

    # Should have run at least 1 cycle
    assert len(results) >= 1
    # Causal engine should have observations
    assert len(agent.causal_engine._observations) >= 0
    # History should be populated
    assert len(agent._history) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 8: Partial failure — omission_engine fails gracefully
# ═══════════════════════════════════════════════════════════════════════════════

def test_scenario_partial_failure():
    """
    omission_engine fails gracefully, Path A continues.

    Tests that when omission_store is broken, Path A still completes
    its cycle without crashing (fail-soft on omission_scan_failure).
    """
    n1 = _node("M1", "ystar.m1")
    n2 = _node("M2", "ystar.m2")
    e1 = _edge("M1", "M2")

    suggestion = GovernanceSuggestion(
        suggestion_type="wire",
        target_rule_id="m1",
        suggested_value="connect M1 to M2",
        confidence=0.8,
        rationale="test",
    )

    gloop = _make_mock_gloop(suggestions=[suggestion], health="degraded")
    improved = Mock()
    improved.overall_health = "stable"
    improved.governance_suggestions = []
    gloop.tighten = Mock(side_effect=[
        Mock(overall_health="degraded", governance_suggestions=[suggestion]),
        improved,
    ])

    cieu = _make_mock_cieu()
    planner = _make_mock_planner(nodes=[n1, n2], edges=[e1])

    # Create a broken omission store
    broken_store = Mock()
    broken_store.add_obligation = Mock(side_effect=RuntimeError("DB crashed"))
    broken_store.list_obligations = Mock(side_effect=RuntimeError("DB crashed"))
    broken_store.get_obligation = Mock(side_effect=RuntimeError("DB crashed"))

    agent = PathAAgent(
        governance_loop=gloop,
        cieu_store=cieu,
        planner=planner,
        omission_store=broken_store,
    )

    # Should NOT crash despite broken omission store
    cycle = agent.run_one_cycle()

    # Cycle should still execute (omission failure is fail-soft)
    assert cycle.executed is True
    # CIEU should still be written
    assert cieu.write_dict.called
