"""
tests/test_provider_routing.py
Contract Provider agent-based routing tests (P1-2)

Tests resolve_for_agent() method which enables per-agent constitution routing
using delegation chains.
"""
import pytest
from ystar.kernel.contract_provider import ConstitutionProvider
from ystar.kernel.dimensions import (
    IntentContract, DelegationContract, DelegationChain
)


def make_test_link(principal, actor, constitution_ref="", **kwargs):
    """Helper to create a DelegationContract with constitution routing."""
    contract = IntentContract(deny=["/etc"], **kwargs)
    return DelegationContract(
        principal=principal,
        actor=actor,
        contract=contract,
        constitution_source_ref=constitution_ref,
    )


class TestResolveForAgent:
    """Test resolve_for_agent() routing logic."""

    def test_resolve_for_agent_with_chain_finds_actor(self, tmp_path):
        """When agent is in chain as actor, use its constitution_source_ref."""
        # Create a test constitution file
        ceo_constitution = tmp_path / "ceo_constitution.md"
        ceo_constitution.write_text("""
# CEO Constitution
## Intent Contracts
- function: approve_budget
  deny: ["/root", "production"]
""")

        # Build delegation chain with constitution routing
        chain = DelegationChain()
        chain.append(make_test_link(
            "board",
            "ceo",
            constitution_ref=str(ceo_constitution)
        ))
        chain.append(make_test_link(
            "ceo",
            "cfo",
            constitution_ref="cfo_constitution.md"
        ))

        provider = ConstitutionProvider()
        bundle = provider.resolve_for_agent("ceo", delegation_chain=chain)

        # Should have resolved to ceo_constitution.md
        assert bundle.source_hash
        assert bundle.source_ref == str(ceo_constitution)
        assert "/root" in bundle.contract.deny
        assert "production" in bundle.contract.deny

    def test_resolve_for_agent_with_chain_finds_principal(self, tmp_path):
        """When agent is in chain as principal, use its constitution_source_ref."""
        # Create test constitution
        cto_constitution = tmp_path / "cto_constitution.md"
        cto_constitution.write_text("""
# CTO Constitution
## Intent Contracts
- function: deploy_code
  deny: ["/etc", "production"]
""")

        chain = DelegationChain()
        chain.append(make_test_link(
            "ceo",
            "cto",
            constitution_ref=str(cto_constitution)
        ))
        chain.append(make_test_link(
            "cto",
            "engineer",
            constitution_ref="engineer_constitution.md"
        ))

        provider = ConstitutionProvider()
        # Look for cto as principal of the second link
        bundle = provider.resolve_for_agent("cto", delegation_chain=chain)

        assert bundle.source_hash
        assert bundle.source_ref == str(cto_constitution)
        assert "/etc" in bundle.contract.deny
        assert "production" in bundle.contract.deny

    def test_resolve_for_agent_fallback_when_not_in_chain(self, tmp_path):
        """When agent not in chain, use fallback_source_ref."""
        fallback_constitution = tmp_path / "fallback.md"
        fallback_constitution.write_text("""
# Fallback Constitution
## Intent Contracts
- function: generic_action
  deny: ["/etc"]
""")

        chain = DelegationChain()
        chain.append(make_test_link("board", "ceo"))

        provider = ConstitutionProvider()
        bundle = provider.resolve_for_agent(
            "unknown_agent",
            delegation_chain=chain,
            fallback_source_ref=str(fallback_constitution)
        )

        assert bundle.source_hash
        assert bundle.source_ref == str(fallback_constitution)
        assert "/etc" in bundle.contract.deny

    def test_resolve_for_agent_fallback_when_no_chain(self, tmp_path):
        """When no chain provided, use fallback_source_ref."""
        fallback_constitution = tmp_path / "fallback.md"
        fallback_constitution.write_text("""
# Fallback Constitution
## Intent Contracts
- function: default_action
  deny: ["/tmp"]
""")

        provider = ConstitutionProvider()
        bundle = provider.resolve_for_agent(
            "any_agent",
            delegation_chain=None,
            fallback_source_ref=str(fallback_constitution)
        )

        assert bundle.source_hash
        assert bundle.source_ref == str(fallback_constitution)
        assert "/tmp" in bundle.contract.deny

    def test_resolve_for_agent_no_fallback_raises(self):
        """When agent not found and no fallback, raise ValueError."""
        chain = DelegationChain()
        chain.append(make_test_link("board", "ceo"))

        provider = ConstitutionProvider()
        with pytest.raises(ValueError, match="not found in delegation chain"):
            provider.resolve_for_agent("unknown_agent", delegation_chain=chain)

    def test_resolve_for_agent_empty_chain_with_fallback(self, tmp_path):
        """Empty chain falls back to fallback_source_ref."""
        fallback_constitution = tmp_path / "empty_fallback.md"
        fallback_constitution.write_text("""
# Empty Chain Fallback
## Intent Contracts
- function: fallback_action
  deny: ["/dev"]
""")

        chain = DelegationChain()  # empty

        provider = ConstitutionProvider()
        bundle = provider.resolve_for_agent(
            "agent_x",
            delegation_chain=chain,
            fallback_source_ref=str(fallback_constitution)
        )

        assert bundle.source_hash
        assert bundle.source_ref == str(fallback_constitution)
        assert "/dev" in bundle.contract.deny

    def test_resolve_for_agent_caching(self, tmp_path):
        """Resolved constitutions are cached like resolve()."""
        constitution = tmp_path / "cached.md"
        constitution.write_text("""
# Cached Constitution
## Intent Contracts
- function: cached_action
  deny: ["/sys"]
""")

        chain = DelegationChain()
        chain.append(make_test_link(
            "board",
            "agent_a",
            constitution_ref=str(constitution)
        ))

        provider = ConstitutionProvider()
        bundle1 = provider.resolve_for_agent("agent_a", delegation_chain=chain)
        bundle2 = provider.resolve_for_agent("agent_a", delegation_chain=chain)

        # Should return same cached instance
        assert bundle1 is bundle2
        assert provider._cache[str(constitution)] is bundle1

    def test_resolve_for_agent_multi_link_chain(self, tmp_path):
        """In a multi-link chain, find the right agent."""
        ceo_const = tmp_path / "ceo.md"
        ceo_const.write_text("""
# CEO
## Intent Contracts
- function: ceo_action
  deny: ["/etc"]
""")

        cto_const = tmp_path / "cto.md"
        cto_const.write_text("""
# CTO
## Intent Contracts
- function: cto_action
  deny: ["/root"]
""")

        cfo_const = tmp_path / "cfo.md"
        cfo_const.write_text("""
# CFO
## Intent Contracts
- function: cfo_action
  deny: ["/var"]
""")

        chain = DelegationChain()
        chain.append(make_test_link("board", "ceo", str(ceo_const)))
        chain.append(make_test_link("ceo", "cto", str(cto_const)))
        chain.append(make_test_link("ceo", "cfo", str(cfo_const)))

        provider = ConstitutionProvider()

        # Test each agent
        ceo_bundle = provider.resolve_for_agent("ceo", delegation_chain=chain)
        assert ceo_bundle.source_ref == str(ceo_const)
        assert "/etc" in ceo_bundle.contract.deny

        cto_bundle = provider.resolve_for_agent("cto", delegation_chain=chain)
        assert cto_bundle.source_ref == str(cto_const)
        assert "/root" in cto_bundle.contract.deny

        cfo_bundle = provider.resolve_for_agent("cfo", delegation_chain=chain)
        assert cfo_bundle.source_ref == str(cfo_const)
        assert "/var" in cfo_bundle.contract.deny

    def test_resolve_for_agent_link_without_constitution_ref(self, tmp_path):
        """Link without constitution_source_ref should continue searching."""
        fallback = tmp_path / "fallback.md"
        fallback.write_text("""
# Fallback
## Intent Contracts
- function: fallback_action
  deny: []
""")

        chain = DelegationChain()
        # Link without constitution_source_ref (empty string)
        chain.append(make_test_link("board", "agent_a", constitution_ref=""))

        provider = ConstitutionProvider()
        bundle = provider.resolve_for_agent(
            "agent_a",
            delegation_chain=chain,
            fallback_source_ref=str(fallback)
        )

        # Should use fallback since link has empty constitution_source_ref
        assert bundle.source_ref == str(fallback)
        assert bundle.contract.deny == []  # fallback has empty deny list
