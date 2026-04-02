"""
Tests for contract status integration in engine.check().

P2-1: effective_status() integration - expired/stale contracts produce
violations but don't block execution.
"""
import time
import pytest
from ystar.kernel.dimensions import IntentContract
from ystar.kernel.engine import check, CheckResult


def test_expired_contract_produces_violation():
    """Expired contract should produce warning-level violation (severity=0.6)."""
    contract = IntentContract(
        status="confirmed",
        confirmed_by="test_user",
        confirmed_at=time.time() - 3600,  # confirmed 1 hour ago
        valid_until=time.time() - 1800,  # expired 30 minutes ago
        deny=["test"],  # some constraint to make it non-empty
    )

    result = check(
        params={"test_param": "value"},
        result=None,
        contract=contract,
    )

    # Should NOT block execution (passed may be True if no other violations)
    # But must contain a contract_status violation
    status_violations = [v for v in result.violations if v.dimension == "contract_status"]
    assert len(status_violations) == 1, "Expected exactly one contract_status violation"

    v = status_violations[0]
    assert v.actual == "expired"
    assert v.severity == 0.6
    assert "expired" in v.message.lower()
    assert v.field == "contract"


def test_stale_contract_produces_violation():
    """Stale contract should produce info-level violation (severity=0.3)."""
    # Create a contract with legitimacy decay configured to make it stale
    contract = IntentContract(
        status="confirmed",
        confirmed_by="test_user",
        confirmed_at=time.time() - 365 * 24 * 3600,  # confirmed 1 year ago
        legitimacy_decay={
            "half_life_days": 90,
            "minimum_score": 0.3,
        },
        deny=["test"],  # some constraint
    )

    # Verify it's actually stale
    assert contract.effective_status() == "stale", "Contract should be stale due to decay"

    result = check(
        params={"test_param": "value"},
        result=None,
        contract=contract,
    )

    # Should NOT block execution
    # But must contain a contract_status violation
    status_violations = [v for v in result.violations if v.dimension == "contract_status"]
    assert len(status_violations) == 1, "Expected exactly one contract_status violation"

    v = status_violations[0]
    assert v.actual == "stale"
    assert v.severity == 0.3
    assert "stale" in v.message.lower() or "decay" in v.message.lower()
    assert v.field == "contract"


def test_active_contract_no_status_violation():
    """Active (confirmed, not expired, not stale) contract should produce no status violations."""
    contract = IntentContract(
        status="confirmed",
        confirmed_by="test_user",
        confirmed_at=time.time() - 60,  # confirmed 1 minute ago
        valid_until=time.time() + 3600,  # expires in 1 hour
        deny=["test"],  # some constraint
    )

    assert contract.effective_status() == "confirmed", "Contract should be confirmed/active"

    result = check(
        params={"test_param": "value"},
        result=None,
        contract=contract,
    )

    # Should have NO contract_status violations
    status_violations = [v for v in result.violations if v.dimension == "contract_status"]
    assert len(status_violations) == 0, "Active contract should not produce status violations"


def test_draft_contract_still_blocked():
    """Draft contracts should still be blocked with legitimacy violation (not contract_status)."""
    contract = IntentContract(
        status="draft",
        deny=["test"],  # some constraint
    )

    assert contract.effective_status() == "draft"

    result = check(
        params={"test_param": "value"},
        result=None,
        contract=contract,
    )

    # Should be BLOCKED (passed=False)
    assert result.passed is False, "Draft contract should be blocked"

    # Should have legitimacy violation, NOT contract_status
    legitimacy_violations = [v for v in result.violations if v.dimension == "legitimacy"]
    assert len(legitimacy_violations) == 1, "Expected legitimacy violation for draft contract"

    status_violations = [v for v in result.violations if v.dimension == "contract_status"]
    assert len(status_violations) == 0, "Draft should use legitimacy dimension, not contract_status"

    v = legitimacy_violations[0]
    assert v.actual == "draft"
    assert v.severity == 1.0
