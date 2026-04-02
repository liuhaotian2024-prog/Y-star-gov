# Layer: Foundation (Test)
"""
Test obligation timing dimension in engine.

Task #5: Verify that obligation timing violations are detected and within-limit calls pass.
"""
from ystar.kernel.dimensions import IntentContract
from ystar.kernel.engine import check


def test_obligation_timing_violation():
    """Verify that exceeding obligation timing produces violation."""
    contract = IntentContract(
        name="complete_task",
        obligation_timing={
            "code_review": 3600,  # 1 hour
            "bug_fix": 7200,      # 2 hours
        }
    )

    # Simulate a code review that took 2 hours (exceeds 1 hour limit)
    params = {
        "obligation_type": "code_review",
        "elapsed_seconds": 7200,  # 2 hours
    }
    result = None

    check_result = check(params, result, contract)

    # Should have violation
    assert not check_result.passed
    assert len(check_result.violations) == 1

    violation = check_result.violations[0]
    assert violation.dimension == "obligation_timing"
    assert "code_review" in violation.message
    assert "7200" in violation.message or "7200.0" in violation.message
    assert violation.severity == 0.9


def test_obligation_timing_within_limit():
    """Verify that staying within obligation timing passes."""
    contract = IntentContract(
        name="complete_task",
        obligation_timing={
            "code_review": 3600,  # 1 hour
            "bug_fix": 7200,      # 2 hours
        }
    )

    # Simulate a code review that took 30 minutes (within 1 hour limit)
    params = {
        "obligation_type": "code_review",
        "elapsed_seconds": 1800,  # 30 minutes
    }
    result = None

    check_result = check(params, result, contract)

    # Should pass
    assert check_result.passed
    assert len(check_result.violations) == 0


def test_obligation_timing_no_params_skips():
    """Verify that missing obligation_type or elapsed_seconds skips check."""
    contract = IntentContract(
        name="complete_task",
        obligation_timing={
            "code_review": 3600,
        }
    )

    # Test 1: No obligation_type
    params1 = {
        "elapsed_seconds": 7200,
    }
    result1 = check(params1, None, contract)
    assert result1.passed  # No violation when obligation_type missing

    # Test 2: No elapsed_seconds
    params2 = {
        "obligation_type": "code_review",
    }
    result2 = check(params2, None, contract)
    assert result2.passed  # No violation when elapsed_seconds missing

    # Test 3: Empty params
    params3 = {}
    result3 = check(params3, None, contract)
    assert result3.passed  # No violation when both missing
