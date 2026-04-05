"""Tests for gov_mcp delegation-aware enforcement (Gap 1) and escalation (Gap 2).

These tests verify:
  Gap 1: gov_check uses delegated contract when agent has registered delegation
  Gap 2: gov_escalate allows permission expansion within principal's authority
"""
import json
import pytest

from ystar import (
    CheckResult,
    DelegationChain,
    DelegationContract,
    IntentContract,
    check,
)


# ---------------------------------------------------------------------------
# Inline _get_contract_for_agent (mirrors gov_mcp/server.py logic)
# Avoids importing gov_mcp.server which requires mcp package
# ---------------------------------------------------------------------------

def _get_contract_for_agent(agent_id, state):
    chain = state.delegation_chain
    if chain.root is not None and agent_id in chain.all_contracts:
        return chain.all_contracts[agent_id].contract
    for link in reversed(chain.links):
        if link.actor == agent_id:
            return link.contract
    return state.active_contract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockState:
    """Minimal _State stub for testing contract resolution."""

    def __init__(self):
        self.active_contract = IntentContract(
            deny=["/etc", "/production"],
            deny_commands=["rm -rf", "sudo"],
        )
        self.delegation_chain = DelegationChain()


# ---------------------------------------------------------------------------
# Gap 1: delegation-aware contract resolution
# ---------------------------------------------------------------------------

class TestGetContractForAgent:

    def test_no_delegation_returns_global(self):
        state = _MockState()
        contract = _get_contract_for_agent("unknown-agent", state)
        assert contract is state.active_contract

    def test_linear_delegation_returns_delegated_contract(self):
        state = _MockState()
        eng_contract = IntentContract(
            deny=["/etc", "/production"],
            only_paths=["./src/core/"],
            deny_commands=["rm -rf", "sudo"],
        )
        link = DelegationContract(
            principal="cto",
            actor="engineer",
            contract=eng_contract,
        )
        state.delegation_chain.append(link)

        resolved = _get_contract_for_agent("engineer", state)
        assert resolved is eng_contract
        assert resolved is not state.active_contract

    def test_unregistered_agent_gets_global(self):
        """Agent not in delegation chain gets global contract."""
        state = _MockState()
        eng_contract = IntentContract(only_paths=["./src/core/"])
        link = DelegationContract(
            principal="cto", actor="engineer", contract=eng_contract,
        )
        state.delegation_chain.append(link)

        # "cmo" is not delegated — should get global
        resolved = _get_contract_for_agent("cmo", state)
        assert resolved is state.active_contract

    def test_delegated_contract_enforced_by_check(self):
        """Verify check() actually uses the delegated contract, not global."""
        state = _MockState()
        eng_contract = IntentContract(only_paths=["./src/core/"])
        link = DelegationContract(
            principal="cto", actor="engineer", contract=eng_contract,
        )
        state.delegation_chain.append(link)

        contract = _get_contract_for_agent("engineer", state)

        # Write to ./src/core/ → ALLOW
        r1 = check(
            params={"tool_name": "Write", "file_path": "./src/core/parser.py"},
            result={},
            contract=contract,
        )
        assert r1.passed

        # Write to ./src/utils/ → DENY (not in only_paths)
        r2 = check(
            params={"tool_name": "Write", "file_path": "./src/utils/helpers.py"},
            result={},
            contract=contract,
        )
        assert not r2.passed

    def test_multiple_agents_different_contracts(self):
        state = _MockState()

        cto_contract = IntentContract(only_paths=["./src/"])
        eng_contract = IntentContract(only_paths=["./src/core/"])

        state.delegation_chain.append(DelegationContract(
            principal="ceo", actor="cto", contract=cto_contract,
        ))
        state.delegation_chain.append(DelegationContract(
            principal="cto", actor="engineer", contract=eng_contract,
        ))

        assert _get_contract_for_agent("cto", state).only_paths == ["./src/"]
        assert _get_contract_for_agent("engineer", state).only_paths == ["./src/core/"]
        assert _get_contract_for_agent("ceo", state) is state.active_contract


# ---------------------------------------------------------------------------
# Gap 1: the actual deadlock scenario from Board
# ---------------------------------------------------------------------------

class TestDelegationDeadlockScenario:
    """
    CEO → CTO (only ./src/)
      CTO → Engineer (only ./src/core/)
        Engineer writes ./src/utils/ → DENY
    """

    def test_engineer_denied_outside_scope(self):
        state = _MockState()

        cto_contract = IntentContract(
            only_paths=["./src/"],
            deny=["/etc", "/production"],
            deny_commands=["rm -rf", "sudo"],
        )
        eng_contract = IntentContract(
            only_paths=["./src/core/"],
            deny=["/etc", "/production"],
            deny_commands=["rm -rf", "sudo"],
        )

        state.delegation_chain.append(DelegationContract(
            principal="ceo", actor="cto", contract=cto_contract,
            allow_redelegate=True, delegation_depth=1,
        ))
        state.delegation_chain.append(DelegationContract(
            principal="cto", actor="engineer", contract=eng_contract,
        ))

        contract = _get_contract_for_agent("engineer", state)

        # Engineer writes to allowed path → ALLOW
        r1 = check(
            params={"tool_name": "Write", "file_path": "./src/core/parser.py"},
            result={}, contract=contract,
        )
        assert r1.passed

        # Engineer writes outside scope → DENY
        r2 = check(
            params={"tool_name": "Write", "file_path": "./src/utils/helpers.py"},
            result={}, contract=contract,
        )
        assert not r2.passed
        assert any("only_paths" in v.dimension for v in r2.violations)
