from ystar.domains.company_runtime import (
    CompanyActionDecision,
    classify_company_action,
    requires_owner_approval,
)
from ystar.domains.company_runtime.permission_tiers import TIER_REGISTRY


def test_permission_tiers_exist():
    assert set(TIER_REGISTRY) == {0, 1, 2, 3, 4}
    assert TIER_REGISTRY[0].requires_owner_approval is False
    assert TIER_REGISTRY[1].requires_budget is True
    assert TIER_REGISTRY[4].requires_owner_approval is True


def test_internal_action_allowed():
    result = classify_company_action({"action": "internal analysis and local strategy brief"})
    assert result["decision"] == CompanyActionDecision.ALLOW_INTERNAL.value
    assert requires_owner_approval({"action": "internal analysis"}) is False


def test_external_contact_requires_approval():
    result = classify_company_action({"action": "send email to customer"})
    assert result["decision"] == CompanyActionDecision.NEEDS_OWNER_APPROVAL.value
    assert requires_owner_approval({"action": "customer contact"}) is True


def test_high_risk_actions_block_or_review_gate():
    assert classify_company_action({"action": "process payment"})["decision"] == CompanyActionDecision.BLOCKED.value
    assert classify_company_action({"action": "core memory writeback"})["decision"] == CompanyActionDecision.REVIEW_GATED.value
