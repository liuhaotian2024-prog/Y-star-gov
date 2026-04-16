"""
Test Suite: Coordinator Audit Hook Injection (CZL Meta-Gate)

Validates inject_coordinator_audit_warning() behavior:
  - Clean reply (no closure claim) → silent pass
  - Drift reply (closure claim + unjustified pending) → warning + CIEU event
  - No taskstate provided → graceful skip
  - Regex variants (Chinese + English closure phrases)

Platform Engineer: Ryan Park (eng-platform)
Version: 1.0
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from ystar.adapters.hooks.stop_hook import inject_coordinator_audit_warning


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def clean_reply():
    """Reply without closure language."""
    return "Dispatched 3 sub-agents to fix bugs. Working on remaining items."


@pytest.fixture
def drift_reply_chinese():
    """Reply with Chinese closure claim."""
    return "今晚 wave 完整收敛，所有任务已完成。"


@pytest.fixture
def drift_reply_english():
    """Reply with English closure claim."""
    return "Wave is fully resolved and all green. Landing complete."


@pytest.fixture
def unjustified_pending_tasks():
    """Task list with unjustified pending items."""
    return [
        {"id": "T1", "status": "pending", "description": "Fix bug in hook.py"},
        {"id": "T2", "status": "pending", "description": "Add test coverage"},
        {"id": "T3", "status": "done", "description": "Update CLAUDE.md"},
    ]


@pytest.fixture
def justified_pending_tasks():
    """Task list with justified deferral."""
    return [
        {"id": "T1", "status": "pending", "description": "defer Phase 2 (Board approval required)"},
        {"id": "T2", "status": "done", "description": "Ship hotfix"},
    ]


# ── Test Cases ────────────────────────────────────────────────────────────

def test_clean_reply_no_injection(clean_reply, unjustified_pending_tasks):
    """
    Test 1: Clean reply (no closure language) should NOT inject warning.
    """
    result = inject_coordinator_audit_warning(clean_reply, unjustified_pending_tasks)
    assert result is None, "Expected silent pass for clean reply"


@patch("ystar.adapters.hooks.stop_hook._emit_cieu_event")
def test_drift_reply_chinese_injects_warning(
    mock_emit,
    drift_reply_chinese,
    unjustified_pending_tasks,
):
    """
    Test 2: Drift reply (Chinese closure claim + unjustified pending) should:
      - Return <system-reminder> warning block
      - Emit COORDINATOR_SUMMARY_DRIFT_DETECTED CIEU event
    """
    result = inject_coordinator_audit_warning(drift_reply_chinese, unjustified_pending_tasks)

    # Assert warning XML returned
    assert result is not None, "Expected warning for drift reply"
    assert "⚠️ CZL Meta-Gate Violation" in result
    assert "收敛" in result  # Should capture the claim phrase
    assert "2 pending task(s)" in result  # Should count unjustified (T1, T2 — T3 is done)
    assert "T1, T2" in result  # Should list unjustified IDs

    # Assert CIEU event emitted
    mock_emit.assert_called_once_with(
        "COORDINATOR_SUMMARY_DRIFT_DETECTED",
        {
            "claim_phrase": "收敛",
            "pending_count": 2,
            "unjustified_pending_ids": ["T1", "T2"],
            "reply_length": len(drift_reply_chinese),
        },
    )


@patch("ystar.adapters.hooks.stop_hook._emit_cieu_event")
def test_drift_reply_english_injects_warning(
    mock_emit,
    drift_reply_english,
    unjustified_pending_tasks,
):
    """
    Test 3: Drift reply (English closure claim + unjustified pending) should inject warning.
    """
    result = inject_coordinator_audit_warning(drift_reply_english, unjustified_pending_tasks)

    assert result is not None
    assert "⚠️ CZL Meta-Gate Violation" in result
    # Regex should match one of: "fully resolved" or "all green" or "Landing complete"
    assert any(phrase in result for phrase in ["fully resolved", "all green", "complete"])
    assert "2 pending task(s)" in result


def test_no_taskstate_graceful_skip(drift_reply_chinese):
    """
    Test 4: No taskstate provided should gracefully skip validation.
    """
    result = inject_coordinator_audit_warning(drift_reply_chinese, taskstate=None)
    assert result is None, "Expected graceful skip when taskstate is None"


@patch("ystar.adapters.hooks.stop_hook._emit_cieu_event")
def test_justified_pending_no_violation(
    mock_emit,
    drift_reply_chinese,
    justified_pending_tasks,
):
    """
    Test 5: Closure claim with justified deferral should NOT trigger warning.
    """
    result = inject_coordinator_audit_warning(drift_reply_chinese, justified_pending_tasks)
    assert result is None, "Expected silent pass for justified deferral"
    mock_emit.assert_not_called()


def test_regex_variant_wave_shipped():
    """
    Test 6: Regex should match "wave shipped" variant.
    """
    reply = "This wave shipped successfully!"
    taskstate = [{"id": "T1", "status": "pending", "description": "Bug fix"}]

    result = inject_coordinator_audit_warning(reply, taskstate)
    assert result is not None
    assert "shipped" in result.lower()


def test_regex_variant_all_done():
    """
    Test 7: Regex should match "全部 done" variant.
    """
    reply = "今天全部 done，可以收工了。"
    taskstate = [{"id": "T1", "status": "pending", "description": "Test writing"}]

    result = inject_coordinator_audit_warning(reply, taskstate)
    assert result is not None
    assert "done" in result.lower()


def test_empty_taskstate_no_violation():
    """
    Test 8: Empty taskstate (all tasks done) should NOT trigger violation.
    """
    reply = "Wave 完整收敛，所有任务已完成。"
    taskstate = []

    result = inject_coordinator_audit_warning(reply, taskstate)
    assert result is None, "Expected silent pass for empty taskstate"


# ── Edge Cases ────────────────────────────────────────────────────────────

def test_large_unjustified_pending_truncates():
    """
    Test 9: Large number of unjustified pending should truncate ID list in warning.
    """
    reply = "All green, landing complete."
    taskstate = [
        {"id": f"T{i}", "status": "pending", "description": f"Task {i}"}
        for i in range(10)
    ]

    result = inject_coordinator_audit_warning(reply, taskstate)
    assert result is not None
    # Should show first 5 IDs + ellipsis
    assert "T0, T1, T2, T3, T4... (+ 5 more)" in result


def test_mixed_status_only_counts_pending():
    """
    Test 10: Should only count unjustified pending, not done/in-progress.
    """
    reply = "Wave 收敛完成。"
    taskstate = [
        {"id": "T1", "status": "done", "description": "Shipped"},
        {"id": "T2", "status": "pending", "description": "Needs fix"},
        {"id": "T3", "status": "in-progress", "description": "Leo working on it"},
    ]

    result = inject_coordinator_audit_warning(reply, taskstate)
    assert result is not None
    assert "1 pending task(s)" in result  # Only T2 is pending and unjustified
    assert "T2" in result
