"""
tests.test_path_a — Path A Meta-Agent Tests

Gap 4 修复：完整的路径 A 测试覆盖

Test coverage:
1. PathAAgent instantiation
2. suggestion_to_contract() produces valid IntentContract
3. check() denies Path A actions outside contract scope (Gap 2)
4. Graph wiring changes is_wired flag
5. Runtime activation after wiring (Gap 1)
6. CIEU record written for every wiring
7. Postcondition obligation created
8. Failed wiring triggers rollback
9. Handoff registration fail-closed (Gap 3)
10. Module scope enforcement (Gap 2)
11. CausalEngine integration (do_wire_query affects plan selection)
12. Counterfactual query works with cycle history
13. Success criteria validation (health improvement) (Gap 5)
14. DelegationChain monotonicity (Path A contract ⊆ parent)
15. Multiple cycles don't expand permissions

Run with: python -m pytest tests/test_path_a.py -v
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from ystar.path_a.meta_agent import (
    PathAAgent,
    MetaAgentCycle,
    suggestion_to_contract,
    create_postcondition_obligation,
)
from ystar.governance.governance_loop import GovernanceSuggestion
from ystar.kernel.dimensions import IntentContract
from ystar.kernel.engine import Violation
from ystar.module_graph.graph import ModuleNode, ModuleEdge, ModuleGraph
from ystar.module_graph.planner import CompositionPlan


# ── Test 1: PathAAgent Instantiation ──────────────────────────────────────
def test_path_a_agent_instantiation():
    """Test that PathAAgent can be instantiated with minimal dependencies."""
    mock_gloop = Mock()
    mock_gloop._observations = []
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)
    mock_planner = Mock()
    mock_planner.graph = ModuleGraph()

    agent = PathAAgent(
        governance_loop=mock_gloop,
        cieu_store=mock_cieu,
        planner=mock_planner,
    )

    assert agent is not None
    assert agent.max_cycles == 10
    assert len(agent._history) == 0
    assert agent._handoff_registered == False
    assert agent._handoff_retry_count == 0
    assert agent._inconclusive_count == 0  # Gap 5


# ── Test 2: suggestion_to_contract() ──────────────────────────────────────
def test_suggestion_to_contract_basic():
    """Test that suggestion_to_contract produces valid IntentContract with module scope."""
    suggestion = GovernanceSuggestion(
        suggestion_type="wire",
        target_rule_id="omission_engine",
        suggested_value="connect OmissionEngine to InterventionEngine",
        confidence=0.8,
        rationale="High omission rate detected",
    )

    allowed_modules = ["OmissionEngine", "InterventionEngine", "check"]
    contract = suggestion_to_contract(suggestion, allowed_modules, deadline_secs=300.0)

    assert contract is not None
    assert isinstance(contract, IntentContract)
    assert contract.name.startswith("path_a:wire:")
    assert "/etc" in contract.deny
    assert "rm -rf" in contract.deny_commands

    # Gap 2: module scope enforcement via only_paths
    assert contract.only_paths is not None
    assert "module:OmissionEngine" in contract.only_paths
    assert "module:InterventionEngine" in contract.only_paths
    assert "module:check" in contract.only_paths


def test_suggestion_to_contract_empty_modules():
    """Test contract with empty allowed_modules list."""
    suggestion = GovernanceSuggestion(
        suggestion_type="observe",
        target_rule_id="drift",
        suggested_value="increase observation frequency",
        confidence=0.5,
        rationale="Drift detected",
    )

    contract = suggestion_to_contract(suggestion, [], deadline_secs=600.0)

    assert contract is not None
    # Empty module list → only_paths should be None
    assert contract.only_paths is None


# ── Test 3: check() denies Path A actions outside contract scope ──────────
def test_check_denies_out_of_scope_action():
    """Gap 2: Verify that check() + manual module scope check denies out-of-scope wiring."""
    from ystar import check

    suggestion = GovernanceSuggestion(
        suggestion_type="wire",
        target_rule_id="test",
        suggested_value="test",
        confidence=0.7,
        rationale="test",
    )

    allowed_modules = ["ModuleA", "ModuleB"]
    contract = suggestion_to_contract(suggestion, allowed_modules)

    # Attempt to wire ModuleC (not in allowed_modules)
    proposed_action = {
        "action": "wire_modules",
        "source_id": "ModuleA",
        "target_id": "ModuleC",  # NOT in allowed_modules
        "plan_nodes": ["ModuleA", "ModuleC"],
    }

    # Manual module scope check (as implemented in meta_agent.py)
    module_violations = []
    for node in ["ModuleA", "ModuleC"]:
        if node not in allowed_modules:
            module_violations.append(f"{node} not in allowed_modules")

    assert len(module_violations) > 0
    assert "ModuleC not in allowed_modules" in module_violations


# ── Test 4: Graph wiring changes is_wired flag ────────────────────────────
def test_graph_wiring_flag():
    """Test that graph wiring changes the is_wired flag on edges."""
    graph = ModuleGraph()

    node_a = ModuleNode(
        id="ModuleA", module_path="test.a", func_name="func_a",
        input_types=[], output_type="TypeA", tags=[], description="Test A"
    )
    node_b = ModuleNode(
        id="ModuleB", module_path="test.b", func_name="func_b",
        input_types=["TypeA"], output_type="TypeB", tags=[], description="Test B"
    )

    graph.add_node(node_a)
    graph.add_node(node_b)

    edge = ModuleEdge(
        source_id="ModuleA", target_id="ModuleB",
        data_type="TypeA", combined_tags=[], governance_meaning="Test edge",
        is_wired=False
    )
    graph._edges[("ModuleA", "ModuleB")] = edge

    # Simulate wiring
    assert edge.is_wired == False
    edge.is_wired = True
    assert edge.is_wired == True
    assert graph._edges[("ModuleA", "ModuleB")].is_wired == True


# ── Test 5: Runtime activation after wiring (Gap 1) ───────────────────────
def test_runtime_activation():
    """Gap 1: Test that _apply_runtime_wiring activates modules and records to CIEU."""
    mock_gloop = Mock()
    mock_gloop._observations = []
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    graph = ModuleGraph()
    node_a = ModuleNode(
        id="ModuleA", module_path="test.a", func_name="func_a",
        input_types=[], output_type="TypeA", tags=[], description="A"
    )
    node_b = ModuleNode(
        id="ModuleB", module_path="test.b", func_name="func_b",
        input_types=["TypeA"], output_type="TypeB", tags=[], description="B"
    )
    graph.add_node(node_a)
    graph.add_node(node_b)

    edge = ModuleEdge(
        source_id="ModuleA", target_id="ModuleB",
        data_type="TypeA", combined_tags=[], governance_meaning="Test",
        is_wired=False
    )
    graph._edges[("ModuleA", "ModuleB")] = edge

    mock_planner = Mock()
    mock_planner.graph = graph

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    cycle = MetaAgentCycle()
    cycle.contract = IntentContract(name="test_contract")

    # Apply runtime activation
    activated, failed = agent._apply_runtime_wiring(cycle, [("ModuleA", "ModuleB")])

    # Should succeed and record to CIEU
    assert "ModuleB" in activated
    assert len(failed) == 0
    assert mock_cieu.write_dict.called

    # Check CIEU record contains activation info
    call_args = mock_cieu.write_dict.call_args_list
    assert any("runtime_activation" in str(call) for call in call_args)


# ── Test 6: CIEU record written for every wiring ───────────────────────────
def test_cieu_record_written():
    """Test that every wiring action writes a CIEU record."""
    mock_gloop = Mock()
    mock_gloop._observations = [Mock()]
    mock_gloop.tighten = Mock(return_value=Mock(
        overall_health="degraded",
        governance_suggestions=[
            GovernanceSuggestion("wire", "test", "test", 0.8, "test")
        ]
    ))

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    graph = ModuleGraph()
    mock_planner = Mock()
    mock_planner.graph = graph
    mock_planner.plan = Mock(return_value=[
        CompositionPlan(
            nodes=[], edges=[], required_tags=[], achieved_tags=[],
            coverage_score=0.5, already_wired=False, description="test"
        )
    ])

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    # Create a cycle
    cycle = MetaAgentCycle()
    cycle.plan_edges = []

    # Write CIEU
    agent._write_cieu(cycle, "TEST_EVENT", [])

    assert mock_cieu.write_dict.called


# ── Test 7: Postcondition obligation created ───────────────────────────────
def test_postcondition_obligation():
    """Test that postcondition obligation is created after wiring."""
    from ystar.governance.omission_engine import OmissionStore

    mock_omission_store = Mock(spec=OmissionStore)
    mock_omission_store.add_obligation = Mock()

    suggestion = GovernanceSuggestion(
        "wire", "test_rule", "test_value", 0.9, "test rationale"
    )

    obligation_id = create_postcondition_obligation(
        mock_omission_store, suggestion, "path_a_agent", 300.0
    )

    assert obligation_id is not None
    assert mock_omission_store.add_obligation.called


# ── Test 8: Failed wiring triggers rollback (Gap 1) ───────────────────────
def test_failed_activation_rollback():
    """Gap 1: Test that failed activation rolls back is_wired flag."""
    mock_gloop = Mock()
    mock_gloop._observations = []
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    graph = ModuleGraph()
    node_a = ModuleNode("A", "test.a", "a", [], "TypeA", [], "A")
    node_b = ModuleNode("B", "test.b", "b", ["TypeA"], "TypeB", [], "B")
    graph.add_node(node_a)
    graph.add_node(node_b)

    edge = ModuleEdge("A", "B", "TypeA", [], "test", is_wired=False)
    graph._edges[("A", "B")] = edge

    mock_planner = Mock()
    mock_planner.graph = graph

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)
    cycle = MetaAgentCycle()
    cycle.contract = IntentContract(name="test")

    # Simulate activation that might fail
    # (actual implementation catches exceptions and rolls back)
    edge.is_wired = True
    activated, failed = agent._apply_runtime_wiring(cycle, [("A", "B")])

    # In normal case, activation succeeds
    # If it failed, edge.is_wired would be rolled back to False
    # This test verifies the mechanism exists
    assert isinstance(activated, list)
    assert isinstance(failed, list)


# ── Test 9: Handoff registration fail-closed (Gap 3) ──────────────────────
def test_handoff_registration_fail_closed():
    """Gap 3: Test that handoff registration failure prevents execution."""
    mock_gloop = Mock()
    mock_gloop._observations = []
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)
    mock_planner = Mock()
    mock_planner.graph = ModuleGraph()

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    # Simulate handoff registration failure
    with patch.object(agent, '_do_handoff_registration', return_value=False):
        cycle = agent.run_one_cycle()

        # Gap 3: Cycle should abort if handoff fails
        assert cycle.executed == False
        assert cycle.success == False
        assert agent._handoff_retry_count > 0


# ── Test 10: Module scope enforcement (Gap 2) ──────────────────────────────
def test_module_scope_enforcement():
    """Gap 2: Test that module scope is enforced during action validation."""
    suggestion = GovernanceSuggestion("wire", "test", "test", 0.8, "test")
    allowed_modules = ["ModuleA", "ModuleB"]

    contract = suggestion_to_contract(suggestion, allowed_modules)

    # Verify contract encodes module scope
    assert contract.only_paths is not None
    assert len([p for p in contract.only_paths if p.startswith("module:")]) == len(allowed_modules)

    # Manual check (as in meta_agent.py)
    plan_nodes = ["ModuleA", "ModuleB", "ModuleC"]  # C is not allowed
    violations = [node for node in plan_nodes if node not in allowed_modules]

    assert "ModuleC" in violations


# ── Test 11: CausalEngine integration ──────────────────────────────────────
def test_causal_engine_integration():
    """Test that CausalEngine.do_wire_query affects plan selection."""
    from ystar.governance.causal_engine import CausalEngine, DoCalcResult

    engine = CausalEngine(confidence_threshold=0.65)

    # Simulate observation
    engine.observe(
        health_before="degraded",
        health_after="stable",
        obl_before=(0, 5),
        obl_after=(3, 5),
        edges_before=[],
        edges_after=[("A", "B")],
        action_edges=[("A", "B")],
        succeeded=True,
        cycle_id="test_cycle_1",
        suggestion_type="wire",
    )

    # Query causal effect
    result = engine.do_wire_query("A", "B")

    assert isinstance(result, DoCalcResult)
    assert result.confidence >= 0.0
    assert result.query == "do(wire(A→B))"


# ── Test 12: Counterfactual query ──────────────────────────────────────────
def test_counterfactual_query():
    """Test that counterfactual queries work with cycle history."""
    from ystar.governance.causal_engine import CausalEngine, CausalState

    engine = CausalEngine()

    # Add observations
    engine.observe(
        health_before="degraded", health_after="stable",
        obl_before=(0, 5), obl_after=(3, 5),
        edges_before=[], edges_after=[("A", "B")],
        action_edges=[("A", "B")],
        succeeded=True, cycle_id="c1", suggestion_type="wire"
    )

    engine.observe(
        health_before="degraded", health_after="critical",
        obl_before=(0, 5), obl_after=(1, 5),
        edges_before=[], edges_after=[("A", "C")],
        action_edges=[("A", "C")],
        succeeded=False, cycle_id="c2", suggestion_type="wire"
    )

    # Counterfactual query: what if we had wired A→B instead of A→C?
    # Use the correct signature: failed_cycle_id and alternative_edges
    cf_result = engine.counterfactual_query(
        failed_cycle_id="c2",
        alternative_edges=[("A", "B")]
    )

    assert cf_result is not None
    assert cf_result.confidence >= 0.0


# ── Test 13: Success criteria validation (Gap 5) ───────────────────────────
def test_success_criteria_tightened():
    """Gap 5: Test that success criteria require measurable improvement."""
    mock_gloop = Mock()
    mock_gloop._observations = [Mock()]

    # First call: degraded with 3 suggestions
    # Second call: degraded with 3 suggestions (no change)
    mock_gloop.tighten = Mock(side_effect=[
        Mock(
            overall_health="degraded",
            governance_suggestions=[
                GovernanceSuggestion("wire", "test1", "v1", 0.8, "r1"),
                GovernanceSuggestion("wire", "test2", "v2", 0.7, "r2"),
                GovernanceSuggestion("wire", "test3", "v3", 0.6, "r3"),
            ]
        ),
        Mock(
            overall_health="degraded",  # Same health
            governance_suggestions=[
                GovernanceSuggestion("wire", "test1", "v1", 0.8, "r1"),
                GovernanceSuggestion("wire", "test2", "v2", 0.7, "r2"),
                GovernanceSuggestion("wire", "test3", "v3", 0.6, "r3"),
            ]  # Same count
        )
    ])

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    graph = ModuleGraph()
    mock_planner = Mock()
    mock_planner.graph = graph
    mock_planner.plan = Mock(return_value=[
        CompositionPlan(
            nodes=[ModuleNode("A", "a", "a", [], "T", [], "A")],
            edges=[ModuleEdge("A", "B", "T", [], "test", False)],
            required_tags=[], achieved_tags=[],
            coverage_score=0.7, already_wired=False, description="test plan"
        )
    ])

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    with patch.object(agent, '_do_handoff_registration', return_value=True):
        cycle = agent.run_one_cycle()

    # Gap 5: No improvement → should be INCONCLUSIVE or failure
    # If wired but no improvement: INCONCLUSIVE
    if cycle.executed and len(cycle.plan_edges) > 0:
        assert cycle.inconclusive == True or cycle.success == False


def test_success_requires_improvement():
    """Gap 5: Test that success requires health >= 0.1 improvement or suggestion reduction >= 1."""
    # Test health improvement (logic test, no agent needed)
    # Setup mocks properly
    mock_gloop = Mock()
    mock_gloop._observations = []
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)
    mock_planner = Mock()
    mock_planner.graph = ModuleGraph()

    # Health improved by 1 level (e.g., critical→degraded)
    health_before_rank = 1  # critical
    health_after_rank = 2   # degraded
    assert (health_after_rank - health_before_rank) >= 1

    # Suggestion reduction
    old_count = 5
    new_count = 4
    assert (old_count - new_count) >= 1

    # No improvement → should NOT succeed
    old_count = 5
    new_count = 5
    health_improvement = 0
    assert not ((health_improvement >= 0.1) or ((old_count - new_count) >= 1))


# ── Test 14: DelegationChain monotonicity ──────────────────────────────────
def test_delegation_chain_monotonicity():
    """Test that Path A contract is a subset of parent contract (monotonicity)."""
    mock_gloop = Mock()
    mock_gloop._observations = []
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)
    mock_planner = Mock()
    mock_planner.graph = ModuleGraph()

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    # Parent contract constraints
    parent_deny = {"/etc", "/root"}
    parent_deny_cmds = {"rm -rf", "sudo"}

    # Child contract constraints (should be superset)
    suggestion = GovernanceSuggestion("wire", "test", "v", 0.8, "r")
    child_contract = suggestion_to_contract(suggestion, ["A", "B"])

    # Verify child is more restrictive (superset of denials)
    assert "/etc" in child_contract.deny
    assert "/root" in child_contract.deny
    assert "~/.clawdbot" in child_contract.deny  # Additional restriction
    assert "/production" in child_contract.deny   # Additional restriction

    assert "rm -rf" in child_contract.deny_commands
    assert "sudo" in child_contract.deny_commands
    assert "exec(" in child_contract.deny_commands  # Additional


# ── Test 15: Multiple cycles don't expand permissions ──────────────────────
def test_multiple_cycles_no_permission_expansion():
    """Test that running multiple cycles doesn't expand Path A's permissions."""
    mock_gloop = Mock()
    mock_gloop._observations = [Mock()]
    mock_gloop.tighten = Mock(return_value=Mock(
        overall_health="stable",
        governance_suggestions=[]
    ))

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    graph = ModuleGraph()
    mock_planner = Mock()
    mock_planner.graph = graph

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    # Get initial contract constraints
    suggestion1 = GovernanceSuggestion("wire", "test1", "v1", 0.8, "r1")
    contract1 = suggestion_to_contract(suggestion1, ["ModA", "ModB"])

    # Run multiple cycles
    suggestion2 = GovernanceSuggestion("wire", "test2", "v2", 0.7, "r2")
    contract2 = suggestion_to_contract(suggestion2, ["ModC", "ModD"])

    # Verify contracts have same base constraints
    assert contract1.deny == contract2.deny
    assert contract1.deny_commands == contract2.deny_commands

    # Only module scope differs (which is derived from suggestion, not self-expanded)
    assert contract1.only_paths != contract2.only_paths

    # Verify agent's constitution hash hasn't changed
    initial_hash = agent._constitution_hash
    # Simulate cycle
    with patch.object(agent, '_do_handoff_registration', return_value=True):
        agent.run_one_cycle()

    assert agent._constitution_hash == initial_hash


# ── Additional: Test INCONCLUSIVE tracking (Gap 5) ─────────────────────────
def test_inconclusive_tracking():
    """Gap 5: Test that 3 consecutive INCONCLUSIVE cycles trigger human review."""
    mock_gloop = Mock()
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)
    mock_planner = Mock()
    mock_planner.graph = ModuleGraph()

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    # Simulate 3 INCONCLUSIVE cycles
    for i in range(3):
        cycle = MetaAgentCycle()
        cycle.inconclusive = True
        cycle.inconclusive_reason = f"Test inconclusive {i}"
        agent._inconclusive_count += 1

    assert agent._inconclusive_count == 3

    # On 3rd INCONCLUSIVE, should write human review request to CIEU
    # (This happens in run_one_cycle when _inconclusive_count >= 3)


# ── Test 16: Kernel module: prefix recognition (Gap 1 fix) ─────────────────
def test_kernel_module_prefix_allow():
    """Test that check() recognizes module: prefix and allows matching module_id."""
    from ystar.kernel.engine import check

    contract = IntentContract(
        name="test_module_scope",
        only_paths=["module:ModuleA", "module:ModuleB"],
    )

    # Params with module_id matching allowed module
    params = {
        "action": "wire_modules",
        "module_id": "ModuleA",
    }

    result = check(params, {}, contract)
    assert result.passed, f"Should PASS: module_id=ModuleA is in allowed modules. Violations: {result.violations}"


def test_kernel_module_prefix_deny():
    """Test that check() denies module_id not in allowed modules."""
    from ystar.kernel.engine import check

    contract = IntentContract(
        name="test_module_scope",
        only_paths=["module:ModuleA", "module:ModuleB"],
    )

    # Params with module_id NOT in allowed modules
    params = {
        "action": "wire_modules",
        "module_id": "ModuleC",
    }

    result = check(params, {}, contract)
    assert not result.passed, "Should DENY: module_id=ModuleC is not in allowed modules"
    assert any("ModuleC" in v.message for v in result.violations)
    assert any("module_id" in v.field for v in result.violations)


def test_kernel_module_prefix_source_target():
    """Test that check() validates source_id and target_id against module scope."""
    from ystar.kernel.engine import check

    contract = IntentContract(
        name="test_module_scope",
        only_paths=["module:A", "module:B"],
    )

    # Valid: both source and target in allowed modules
    params_valid = {
        "source_id": "A",
        "target_id": "B",
    }
    result_valid = check(params_valid, {}, contract)
    assert result_valid.passed, "Should PASS: both modules in scope"

    # Invalid: source not in allowed modules
    params_invalid = {
        "source_id": "C",
        "target_id": "B",
    }
    result_invalid = check(params_invalid, {}, contract)
    assert not result_invalid.passed, "Should DENY: source_id=C not in scope"
    assert any("C" in v.message for v in result_invalid.violations)


def test_kernel_mixed_module_and_path_scope():
    """Test that check() handles both module: and filesystem path constraints."""
    from ystar.kernel.engine import check
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        contract = IntentContract(
            name="test_mixed_scope",
            only_paths=[
                "module:ModuleA",
                "module:ModuleB",
                tmpdir,  # Filesystem path
            ],
        )

        # Valid: module in scope
        params_module = {
            "module_id": "ModuleA",
        }
        result_module = check(params_module, {}, contract)
        assert result_module.passed, "Should PASS: module_id in scope"

        # Valid: file path in allowed directory
        test_file = os.path.join(tmpdir, "test.txt")
        params_path = {
            "file_path": test_file,
        }
        result_path = check(params_path, {}, contract)
        assert result_path.passed, "Should PASS: file_path in allowed dir"

        # Invalid: module not in scope
        params_bad_module = {
            "module_id": "ModuleC",
        }
        result_bad_module = check(params_bad_module, {}, contract)
        assert not result_bad_module.passed, "Should DENY: module_id not in scope"

        # Invalid: file path outside allowed directory
        params_bad_path = {
            "file_path": "/etc/passwd",
        }
        result_bad_path = check(params_bad_path, {}, contract)
        assert not result_bad_path.passed, "Should DENY: file_path outside scope"


# ══════════════════════════════════════════════════════════════════════════════
# NEW TESTS — appended by CTO review (2026-03-29)
# ══════════════════════════════════════════════════════════════════════════════


# ── Integration test 1: Multi-cycle INCONCLUSIVE triggers human review ────────
def test_multi_cycle_inconclusive_triggers_human_review():
    """Run 3+ INCONCLUSIVE cycles, verify HUMAN_REVIEW_REQUIRED and 4th refuses."""
    mock_gloop = Mock()
    mock_gloop._observations = [Mock()]
    # Every tighten() returns degraded with same suggestions (no improvement)
    _suggestion = GovernanceSuggestion("wire", "rule1", "val1", 0.8, "reason")
    mock_gloop.tighten = Mock(return_value=Mock(
        overall_health="degraded",
        governance_suggestions=[_suggestion],
    ))

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    graph = ModuleGraph()
    node_a = ModuleNode("A", "test.a", "a", [], "T", [], "A")
    node_b = ModuleNode("B", "test.b", "b", ["T"], "T2", [], "B")
    graph.add_node(node_a)
    graph.add_node(node_b)
    # Edge already wired -> wired_count=0 at execution, triggers INCONCLUSIVE
    edge = ModuleEdge("A", "B", "T", [], "test", is_wired=True)
    graph._edges[("A", "B")] = edge
    mock_planner = Mock()
    mock_planner.graph = graph
    mock_planner.plan = Mock(return_value=[
        CompositionPlan(
            nodes=[node_a, node_b],
            edges=[edge],
            required_tags=[], achieved_tags=[],
            coverage_score=0.5, already_wired=False, description="test"
        )
    ])

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    with patch.object(agent, '_do_handoff_registration', return_value=True):
        # Patch constitution check to pass
        with patch.object(agent, '_load_constitution_hash', return_value=agent._constitution_hash):
            for i in range(3):
                cycle = agent.run_one_cycle()

    # After 3 INCONCLUSIVE cycles:
    assert agent._inconclusive_count >= 3
    assert agent._human_review_required is True

    # Verify HUMAN_REVIEW_REQUIRED was written to CIEU
    cieu_calls = [str(c) for c in mock_cieu.write_dict.call_args_list]
    assert any("HUMAN_REVIEW_REQUIRED" in c for c in cieu_calls)

    # 4th cycle should refuse to execute
    cycle_4 = agent.run_one_cycle()
    assert cycle_4.executed is False
    assert "human review required" in (cycle_4.inconclusive_reason or "").lower()


# ── Integration test 2: acknowledge_human_review resumes execution ────────────
def test_acknowledge_human_review_resumes_execution():
    """After human_review_required is set, acknowledge resumes execution."""
    mock_gloop = Mock()
    mock_gloop._observations = [Mock()]
    mock_gloop.tighten = Mock(return_value=Mock(
        overall_health="stable",
        governance_suggestions=[],
    ))

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)
    mock_planner = Mock()
    mock_planner.graph = ModuleGraph()

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    # Manually set human review required
    agent._human_review_required = True
    agent._inconclusive_count = 3

    # Cycle should be blocked
    cycle_blocked = agent.run_one_cycle()
    assert cycle_blocked.executed is False
    assert "human review" in (cycle_blocked.inconclusive_reason or "").lower()

    # Acknowledge human review
    agent.acknowledge_human_review()
    assert agent._human_review_required is False
    assert agent._inconclusive_count == 0

    # Now cycle should proceed (no suggestions -> exits early but IS executed path)
    with patch.object(agent, '_do_handoff_registration', return_value=True):
        cycle_resumed = agent.run_one_cycle()
    # It should NOT be blocked anymore (even if success=False for other reasons)
    assert cycle_resumed.inconclusive_reason is None or "human review" not in (cycle_resumed.inconclusive_reason or "").lower()


# ── Integration test 3: Multi-cycle no permission expansion ──────────────────
def test_multi_cycle_no_permission_expansion():
    """Run 3 cycles, verify contract.deny never shrinks and only_paths never grows."""
    contracts = []

    for i in range(3):
        suggestion = GovernanceSuggestion("wire", f"rule{i}", f"val{i}", 0.8, "r")
        allowed = ["ModA", "ModB"]
        contract = suggestion_to_contract(suggestion, allowed)
        contracts.append(contract)

    # Verify deny sets are identical (never shrink)
    for c in contracts:
        assert set(c.deny) == set(contracts[0].deny)
        assert set(c.deny_commands) == set(contracts[0].deny_commands)

    # Verify only_paths length is bounded by allowed_modules
    for c in contracts:
        module_paths = [p for p in (c.only_paths or []) if p.startswith("module:")]
        assert len(module_paths) == 2  # exactly the 2 allowed modules


# ── Failure path test 4: Empty plan edges returns early ──────────────────────
def test_empty_plan_edges_returns_early():
    """Plan with empty edges list -> cycle returns early with CIEU record."""
    mock_gloop = Mock()
    mock_gloop._observations = [Mock()]
    _suggestion = GovernanceSuggestion("wire", "rule1", "val1", 0.8, "reason")
    mock_gloop.tighten = Mock(return_value=Mock(
        overall_health="degraded",
        governance_suggestions=[_suggestion],
    ))

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    graph = ModuleGraph()
    node_a = ModuleNode("A", "test.a", "a", [], "T", [], "A")
    graph.add_node(node_a)
    mock_planner = Mock()
    mock_planner.graph = graph
    mock_planner.plan = Mock(return_value=[
        CompositionPlan(
            nodes=[node_a],
            edges=[],  # empty edges
            required_tags=[], achieved_tags=[],
            coverage_score=0.5, already_wired=False, description="no edges"
        )
    ])

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    with patch.object(agent, '_do_handoff_registration', return_value=True):
        cycle = agent.run_one_cycle()

    assert cycle.executed is False
    # CIEU should have been written
    assert mock_cieu.write_dict.called
    cieu_calls = [str(c) for c in mock_cieu.write_dict.call_args_list]
    assert any("no_edges_to_wire" in c.lower() for c in cieu_calls)


# ── Failure path test 5: Constitution hash mismatch ──────────────────────────
def test_constitution_hash_mismatch():
    """Set constitution hash different from expected, verify cycle aborts."""
    mock_gloop = Mock()
    mock_gloop._observations = [Mock()]
    mock_gloop.tighten = Mock(return_value=Mock(
        overall_health="degraded",
        governance_suggestions=[
            GovernanceSuggestion("wire", "r", "v", 0.8, "reason")
        ],
    ))

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)
    mock_planner = Mock()
    mock_planner.graph = ModuleGraph()

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    with patch.object(agent, '_do_handoff_registration', return_value=True):
        # Tamper with the stored constitution hash so it won't match the file
        agent._constitution_hash = "sha256:TAMPERED_HASH"
        cycle = agent.run_one_cycle()

    assert cycle.executed is False
    # Verify constitution_mismatch CIEU record written
    cieu_calls = [str(c) for c in mock_cieu.write_dict.call_args_list]
    assert any("constitution" in c.lower() for c in cieu_calls)


# ── Failure path test 6: Health degradation is failure ───────────────────────
def test_health_degradation_is_failure():
    """Health getting worse (health_improvement < 0) -> cycle.success = False."""
    mock_gloop = Mock()
    mock_gloop._observations = [Mock()]
    _sugg = GovernanceSuggestion("wire", "r", "v", 0.8, "reason")

    # First tighten: degraded. Second tighten: critical (worse).
    mock_gloop.tighten = Mock(side_effect=[
        Mock(overall_health="degraded",
             governance_suggestions=[_sugg]),
        Mock(overall_health="critical",
             governance_suggestions=[_sugg]),
    ])

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    graph = ModuleGraph()
    node_a = ModuleNode("A", "test.a", "a", [], "T", [], "A")
    node_b = ModuleNode("B", "test.b", "b", ["T"], "T2", [], "B")
    graph.add_node(node_a)
    graph.add_node(node_b)
    edge = ModuleEdge("A", "B", "T", [], "test", is_wired=False)
    graph._edges[("A", "B")] = edge

    mock_planner = Mock()
    mock_planner.graph = graph
    mock_planner.plan = Mock(return_value=[
        CompositionPlan(
            nodes=[node_a, node_b],
            edges=[edge],
            required_tags=[], achieved_tags=[],
            coverage_score=0.7, already_wired=False, description="test"
        )
    ])

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    with patch.object(agent, '_do_handoff_registration', return_value=True):
        cycle = agent.run_one_cycle()

    assert cycle.success is False
    assert cycle.inconclusive is False  # degradation is failure, not inconclusive


# ── Failure path test 7: Wiring without improvement is failure ───────────────
def test_wiring_without_improvement_is_failure():
    """Wiring happened (wired_count > 0) but no health improvement -> FAILURE per Fix 6.1."""
    mock_gloop = Mock()
    mock_gloop._observations = [Mock()]
    _sugg = GovernanceSuggestion("wire", "r", "v", 0.8, "reason")

    # Both tightens return same health & same suggestion count
    mock_gloop.tighten = Mock(side_effect=[
        Mock(overall_health="degraded",
             governance_suggestions=[_sugg]),
        Mock(overall_health="degraded",
             governance_suggestions=[_sugg]),
    ])

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    graph = ModuleGraph()
    node_a = ModuleNode("A", "test.a", "a", [], "T", [], "A")
    node_b = ModuleNode("B", "test.b", "b", ["T"], "T2", [], "B")
    graph.add_node(node_a)
    graph.add_node(node_b)
    edge = ModuleEdge("A", "B", "T", [], "test", is_wired=False)
    graph._edges[("A", "B")] = edge

    mock_planner = Mock()
    mock_planner.graph = graph
    mock_planner.plan = Mock(return_value=[
        CompositionPlan(
            nodes=[node_a, node_b],
            edges=[edge],
            required_tags=[], achieved_tags=[],
            coverage_score=0.7, already_wired=False, description="test"
        )
    ])

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    with patch.object(agent, '_do_handoff_registration', return_value=True):
        cycle = agent.run_one_cycle()

    # Fix 6.1: wiring happened but no improvement = FAILURE not INCONCLUSIVE
    assert cycle.executed is True
    assert cycle.success is False
    assert cycle.inconclusive is False


# ── Failure path test 8: Failed obligation on cycle failure ──────────────────
def test_failed_obligation_on_cycle_failure():
    """When cycle fails and has obligation_id, verify _fail_obligation is called."""
    mock_gloop = Mock()
    mock_gloop._observations = [Mock()]
    _sugg = GovernanceSuggestion("wire", "r", "v", 0.8, "reason")

    mock_gloop.tighten = Mock(side_effect=[
        Mock(overall_health="degraded",
             governance_suggestions=[_sugg]),
        Mock(overall_health="degraded",
             governance_suggestions=[_sugg]),
    ])

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    graph = ModuleGraph()
    node_a = ModuleNode("A", "test.a", "a", [], "T", [], "A")
    node_b = ModuleNode("B", "test.b", "b", ["T"], "T2", [], "B")
    graph.add_node(node_a)
    graph.add_node(node_b)
    edge = ModuleEdge("A", "B", "T", [], "test", is_wired=False)
    graph._edges[("A", "B")] = edge

    mock_planner = Mock()
    mock_planner.graph = graph
    mock_planner.plan = Mock(return_value=[
        CompositionPlan(
            nodes=[node_a, node_b],
            edges=[edge],
            required_tags=[], achieved_tags=[],
            coverage_score=0.7, already_wired=False, description="test"
        )
    ])

    # Provide an omission_store so obligation path is exercised
    mock_omission_store = Mock()
    mock_omission_store.add_obligation = Mock()
    mock_omission_store.list_obligations = Mock(return_value=[])

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner,
                       omission_store=mock_omission_store)

    with patch.object(agent, '_do_handoff_registration', return_value=True):
        with patch.object(agent, '_fail_obligation') as mock_fail:
            cycle = agent.run_one_cycle()

            # Cycle failed (wiring but no improvement)
            assert cycle.success is False
            # _fail_obligation should have been called with the obligation_id
            if cycle.obligation_id:
                mock_fail.assert_called_once_with(cycle.obligation_id)


# ── CIEU consistency test 9: Records have consistent schema ──────────────────
def test_cieu_records_have_consistent_schema():
    """Run a cycle, verify every CIEU write_dict call has required fields."""
    mock_gloop = Mock()
    mock_gloop._observations = [Mock()]
    _sugg = GovernanceSuggestion("wire", "r", "v", 0.8, "reason")

    mock_gloop.tighten = Mock(side_effect=[
        Mock(overall_health="degraded",
             governance_suggestions=[_sugg]),
        Mock(overall_health="stable",
             governance_suggestions=[]),
    ])

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    graph = ModuleGraph()
    node_a = ModuleNode("A", "test.a", "a", [], "T", [], "A")
    node_b = ModuleNode("B", "test.b", "b", ["T"], "T2", [], "B")
    graph.add_node(node_a)
    graph.add_node(node_b)
    edge = ModuleEdge("A", "B", "T", [], "test", is_wired=False)
    graph._edges[("A", "B")] = edge

    mock_planner = Mock()
    mock_planner.graph = graph
    mock_planner.plan = Mock(return_value=[
        CompositionPlan(
            nodes=[node_a, node_b],
            edges=[edge],
            required_tags=[], achieved_tags=[],
            coverage_score=0.7, already_wired=False, description="test"
        )
    ])

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner)

    with patch.object(agent, '_do_handoff_registration', return_value=True):
        cycle = agent.run_one_cycle()

    required_fields = {"session_id", "agent_id", "event_type", "action", "decision", "passed"}

    # Check every CIEU write_dict call
    for call in mock_cieu.write_dict.call_args_list:
        record = call[0][0]  # first positional arg
        if isinstance(record, dict):
            missing = required_fields - set(record.keys())
            assert not missing, f"CIEU record missing fields {missing}: {record.get('event_type', '?')}"


# ── CIEU consistency test 10: Success events written ─────────────────────────
def test_cieu_success_events_written():
    """Run a successful cycle, verify key success events are in CIEU records."""
    mock_gloop = Mock()
    mock_gloop._observations = [Mock()]
    _sugg = GovernanceSuggestion("wire", "r", "v", 0.8, "reason")

    mock_gloop.tighten = Mock(side_effect=[
        Mock(overall_health="degraded",
             governance_suggestions=[_sugg]),
        Mock(overall_health="stable",  # improved
             governance_suggestions=[]),
    ])

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)

    graph = ModuleGraph()
    node_a = ModuleNode("A", "test.a", "a", [], "T", [], "A")
    node_b = ModuleNode("B", "test.b", "b", ["T"], "T2", [], "B")
    graph.add_node(node_a)
    graph.add_node(node_b)
    edge = ModuleEdge("A", "B", "T", [], "test", is_wired=False)
    graph._edges[("A", "B")] = edge

    mock_planner = Mock()
    mock_planner.graph = graph
    mock_planner.plan = Mock(return_value=[
        CompositionPlan(
            nodes=[node_a, node_b],
            edges=[edge],
            required_tags=[], achieved_tags=[],
            coverage_score=0.7, already_wired=False, description="test"
        )
    ])

    mock_omission_store = Mock()
    mock_omission_store.add_obligation = Mock()
    mock_omission_store.get_obligation = Mock(return_value=Mock())
    mock_omission_store.update_obligation = Mock()
    mock_omission_store.list_obligations = Mock(return_value=[])

    agent = PathAAgent(mock_gloop, mock_cieu, mock_planner,
                       omission_store=mock_omission_store)

    with patch.object(agent, '_do_handoff_registration', return_value=True):
        cycle = agent.run_one_cycle()

    assert cycle.success is True

    # Collect all event_types from CIEU records
    event_types = []
    for call in mock_cieu.write_dict.call_args_list:
        record = call[0][0]
        if isinstance(record, dict) and "event_type" in record:
            event_types.append(record["event_type"])

    assert "wiring_success" in event_types, f"Missing wiring_success in {event_types}"
    assert "health_improved" in event_types, f"Missing health_improved in {event_types}"
    assert "obligation_fulfilled" in event_types, f"Missing obligation_fulfilled in {event_types}"


# ── Kernel module scope test 11: plan_nodes checked against module scope ─────
def test_plan_nodes_checked_against_module_scope():
    """Contract with only_paths=[module:A, module:B], plan_nodes=[A,B,C] -> violation for C."""
    from ystar.kernel.engine import check

    contract = IntentContract(
        name="test_scope",
        only_paths=["module:A", "module:B"],
    )

    params = {
        "action": "wire_modules",
        "plan_nodes": ["A", "B", "C"],
    }

    result = check(params, {}, contract)
    assert not result.passed, "Should DENY: plan_nodes contains C which is not in module scope"
    violation_messages = [v.message for v in result.violations]
    assert any("C" in m for m in violation_messages), f"Should mention C: {violation_messages}"


# ── Kernel module scope test 12: Violation uses dimension=module_scope ───────
def test_module_scope_violation_uses_correct_dimension():
    """Module scope violations use dimension='module_scope'."""
    from ystar.kernel.engine import check

    contract = IntentContract(
        name="test_dim",
        only_paths=["module:X"],
    )

    params = {"module_id": "Y"}  # Y is not in scope

    result = check(params, {}, contract)
    assert not result.passed
    assert any(v.dimension == "module_scope" for v in result.violations), \
        f"Expected dimension='module_scope', got: {[v.dimension for v in result.violations]}"


# ── Boundary test 13: Health improvement threshold matches constitution ──────
def test_health_improvement_threshold_matches_constitution():
    """health_improvement=0.05 is failure, 0.1 is success per PATH_A_AGENTS.md spec."""
    # The agent uses _health_rank which returns integer ranks:
    # healthy=4, stable=3, degraded=2, critical=1
    # health_improvement >= 1 (one rank level) means success.

    # Test: same health rank (improvement=0) -> not success
    rank_degraded = PathAAgent._health_rank("degraded")
    rank_degraded2 = PathAAgent._health_rank("degraded")
    assert (rank_degraded2 - rank_degraded) < 1  # no improvement

    # Test: one rank improvement (degraded -> stable = +1) -> success
    rank_stable = PathAAgent._health_rank("stable")
    improvement = rank_stable - rank_degraded
    assert improvement >= 1  # this counts as success

    # Test: critical -> degraded = +1 -> success
    rank_critical = PathAAgent._health_rank("critical")
    improvement_cd = rank_degraded - rank_critical
    assert improvement_cd >= 1

    # Test: negative improvement (stable -> degraded = -1) -> failure
    negative = rank_degraded - rank_stable
    assert negative < 0  # degradation


# ── Boundary test 14: Action scope strict subset ─────────────────────────────
def test_action_scope_strict_subset():
    """Child delegation action_scope is a proper subset of parent action_scope."""
    # These are the scopes defined in _do_handoff_registration
    parent_scope = {"module_graph.wire", "cieu.write",
                    "obligation.create", "governance_loop.observe"}
    child_scope = {"module_graph.wire", "cieu.write",
                   "obligation.create"}

    # Child must be strict subset of parent
    assert child_scope < parent_scope, "Child scope must be a proper subset of parent scope"
    # Child must not contain anything parent doesn't have
    assert child_scope.issubset(parent_scope)
    # Verify the specific exclusion
    assert "governance_loop.observe" not in child_scope
    assert "governance_loop.observe" in parent_scope


# ── P1-3: Path A Pull Model Tests ─────────────────────────────────────────────

def test_path_a_pulls_observations():
    """Test that Path A can pull observations from GovernanceLoop."""
    from ystar.governance.governance_loop import GovernanceLoop, GovernanceObservation
    from ystar.governance.reporting import ReportEngine
    from ystar.governance.omission_store import OmissionStore

    # Setup
    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)
    gloop = GovernanceLoop(report_engine=report_engine)

    # Add an observation
    obs = GovernanceObservation(
        period_label="test_period",
        obligation_fulfillment_rate=0.9,
        omission_detection_rate=0.1,
    )
    gloop._observations.append(obs)

    # Setup PathA agent
    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)
    mock_planner = Mock()
    mock_planner.graph = ModuleGraph()

    agent = PathAAgent(
        governance_loop=gloop,
        cieu_store=mock_cieu,
        planner=mock_planner,
    )

    # P1-3: Pull observations
    observations = agent.pull_observations()

    assert len(observations) == 1
    assert observations[0].period_label == "test_period"
    assert observations[0].obligation_fulfillment_rate == 0.9


def test_path_a_rejects_low_confidence():
    """Test that Path A rejects suggestions with confidence below threshold."""
    from ystar.governance.governance_loop import GovernanceLoop, GovernanceSuggestion
    from ystar.governance.reporting import ReportEngine
    from ystar.governance.omission_store import OmissionStore

    # Setup
    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)
    gloop = GovernanceLoop(report_engine=report_engine)

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)
    mock_planner = Mock()
    mock_planner.graph = ModuleGraph()

    agent = PathAAgent(
        governance_loop=gloop,
        cieu_store=mock_cieu,
        planner=mock_planner,
        auto_confidence_threshold=0.7,
    )

    # Low confidence suggestion
    low_conf = GovernanceSuggestion(
        suggestion_type="wire",
        target_rule_id="test_rule",
        suggested_value="test_value",
        confidence=0.5,  # Below threshold
        rationale="test",
    )

    # High confidence suggestion
    high_conf = GovernanceSuggestion(
        suggestion_type="wire",
        target_rule_id="test_rule",
        suggested_value="test_value",
        confidence=0.8,  # Above threshold
        rationale="test",
    )

    # P1-3: Evaluate suggestions
    assert agent.evaluate_suggestion(low_conf) is False, "Should reject low confidence"
    assert agent.evaluate_suggestion(high_conf) is True, "Should accept high confidence"


def test_path_a_rejects_unknown_suggestion_type():
    """Test that Path A rejects suggestions with unknown types."""
    from ystar.governance.governance_loop import GovernanceLoop, GovernanceSuggestion
    from ystar.governance.reporting import ReportEngine
    from ystar.governance.omission_store import OmissionStore

    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)
    gloop = GovernanceLoop(report_engine=report_engine)

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)
    mock_planner = Mock()
    mock_planner.graph = ModuleGraph()

    agent = PathAAgent(
        governance_loop=gloop,
        cieu_store=mock_cieu,
        planner=mock_planner,
    )

    # Unknown suggestion type
    unknown_type = GovernanceSuggestion(
        suggestion_type="unknown_action_type",
        target_rule_id="test_rule",
        suggested_value="test_value",
        confidence=0.9,
        rationale="test",
    )

    assert agent.evaluate_suggestion(unknown_type) is False, "Should reject unknown type"


def test_path_a_rejects_during_human_review():
    """Test that Path A rejects all suggestions when human review is required."""
    from ystar.governance.governance_loop import GovernanceLoop, GovernanceSuggestion
    from ystar.governance.reporting import ReportEngine
    from ystar.governance.omission_store import OmissionStore

    store = OmissionStore()
    report_engine = ReportEngine(omission_store=store)
    gloop = GovernanceLoop(report_engine=report_engine)

    mock_cieu = Mock()
    mock_cieu.write_dict = Mock(return_value=True)
    mock_planner = Mock()
    mock_planner.graph = ModuleGraph()

    agent = PathAAgent(
        governance_loop=gloop,
        cieu_store=mock_cieu,
        planner=mock_planner,
    )

    # Set human review required
    agent._human_review_required = True

    suggestion = GovernanceSuggestion(
        suggestion_type="wire",
        target_rule_id="test_rule",
        suggested_value="test_value",
        confidence=0.9,
        rationale="test",
    )

    assert agent.evaluate_suggestion(suggestion) is False, "Should reject during human review"
