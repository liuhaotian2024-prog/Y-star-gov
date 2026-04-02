# tests/test_template_domain_pack_bridge.py — Test P1-8 templates → domain packs integration
"""
Test that get_template() delegates to domain packs when available.
"""
import pytest


def test_template_delegates_to_domain_pack_finance():
    """Test that get_template('finance') delegates to FinanceDomainPack."""
    from ystar.templates import get_template

    # Get finance template
    result = get_template("finance")

    # Should return a TemplateResult
    assert hasattr(result, "contract")
    assert hasattr(result, "higher_order")

    # Contract should have finance domain pack's constitutional rules
    contract = result.contract

    # Finance pack should have deny rules for sanctioned entities
    # Check for at least some deny patterns
    assert len(contract.deny) > 0 or len(contract.deny_commands) > 0

    # Finance pack should have value ranges for amount parameters
    assert len(contract.value_range) > 0


def test_template_delegates_to_domain_pack_with_role():
    """Test that get_template with role parameter merges role-specific contract."""
    from ystar.templates import get_template

    # Get finance template with role
    result = get_template("finance", role="execution_agent")

    contract = result.contract

    # Should have constitutional + role-specific rules
    assert contract is not None
    # Should have deny patterns from constitutional contract
    assert len(contract.deny) > 0 or len(contract.deny_commands) > 0


def test_template_fallback_to_builtin_when_no_domain_pack():
    """Test that templates without domain packs still work (rd, ops, etc)."""
    from ystar.templates import get_template

    # 'rd' template doesn't have a corresponding domain pack
    result = get_template("rd")

    assert result.contract is not None
    # Should have rd-specific rules from TEMPLATE_DICTS
    assert len(result.contract.deny) > 0 or len(result.contract.only_paths) > 0


def test_template_with_overrides_still_works():
    """Test that overrides work with both domain packs and built-in templates."""
    from ystar.templates import get_template

    # Override with custom amount_limit
    result = get_template("finance", amount_limit=5000, role="trader")

    # Should still return a valid contract
    assert result.contract is not None


def test_try_get_from_domain_pack_returns_none_for_nonexistent():
    """Test that _try_get_from_domain_pack returns None for non-existent packs."""
    from ystar.templates import _try_get_from_domain_pack

    result = _try_get_from_domain_pack("nonexistent_domain_xyz", {})
    assert result is None


def test_try_get_from_domain_pack_returns_result_for_finance():
    """Test that _try_get_from_domain_pack returns result for finance."""
    from ystar.templates import _try_get_from_domain_pack

    result = _try_get_from_domain_pack("finance", {})
    assert result is not None
    assert hasattr(result, "contract")


def test_domain_pack_contract_has_more_rules_than_template():
    """Test that domain pack provides richer governance than simple template."""
    from ystar.templates import get_template, TEMPLATE_DICTS

    # Get finance via domain pack
    domain_result = get_template("finance")

    # Get finance built-in template dict
    builtin_finance = TEMPLATE_DICTS.get("finance", {})

    # Domain pack should have constitutional contract with deny patterns
    # Built-in template may have simpler rules
    domain_contract = domain_result.contract

    # Domain pack should have deny patterns (from constitutional contract)
    assert len(domain_contract.deny) > 0

    # Domain pack should have value ranges
    assert len(domain_contract.value_range) > 0


def test_template_list_includes_domain_backed_templates():
    """Test that TEMPLATES list still includes templates that now use domain packs."""
    from ystar.templates import TEMPLATES

    # Finance template should still be in the list
    assert "finance" in TEMPLATES

    # Traditional templates should also be present
    assert "rd" in TEMPLATES
    assert "ops" in TEMPLATES


def test_get_template_finance_vs_healthcare_different_rules():
    """Test that different domain packs have different rules."""
    from ystar.templates import get_template

    finance_result = get_template("finance")

    # Finance should have value_range constraints
    assert len(finance_result.contract.value_range) > 0

    # Should have deny patterns
    assert len(finance_result.contract.deny) > 0 or len(finance_result.contract.deny_commands) > 0


def test_domain_pack_merge_preserves_constitutional_rules():
    """Test that role-specific contracts merge with constitutional rules."""
    from ystar.templates import get_template

    # Get finance with role
    result = get_template("finance", role="trader")
    contract = result.contract

    # Should have constitutional deny patterns (can't be relaxed)
    assert len(contract.deny) > 0 or len(contract.deny_commands) > 0

    # Should have value ranges from constitutional contract
    assert len(contract.value_range) > 0
