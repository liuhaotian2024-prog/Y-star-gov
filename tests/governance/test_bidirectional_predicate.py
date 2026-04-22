"""
Test bidirectional predicate fix (CZL-122):
coordinator_audit Y* detection + czl_protocol Stage 1 exemption + STRICTNESS_MAP.

Verifies:
1. coordinator_audit detects Y* in `**Y***` text correctly (was 1/10 FP, now 10/10 PASS)
2. Y*gov czl_protocol exempts short ack (was complained, now silent)
3. Y*gov czl_protocol respects STRICTNESS_MAP (CEO strict missing 1 → fire / sub-agent lenient 3+ → pass)
4. Round-trip: same dispatch text validated by both modules → consistent verdict
5. Y*gov czl_protocol still flags missing recipient/task_id (preserve original behavior)
6. coordinator_audit lenient mode 3+ labels passes (preserve current good behavior)
"""

import pytest
from ystar.governance.coordinator_audit import (
    validate_5tuple,
    check_reply_5tuple_compliance,
    _label_present,
)
from ystar.kernel.czl_protocol import validate_dispatch


# --- Test 1: coordinator_audit Y* asterisk collision fix ---

def test_coordinator_audit_detects_y_star_with_markdown_bold():
    """coordinator_audit._label_present handles **Y*** (raw asterisk) correctly."""
    # Before fix: naive regex r'\*\*Y\\\*+\*\*\s*:?\s+\S+' would miss **Y*** (only 3 asterisks)
    # After fix: dual-substring check ("**Y*" in text) or ("**Y\\*" in text) catches both
    text_raw_asterisk = "**Y***: Fix predicate bug"
    text_escaped_asterisk = "**Y\\***: Fix predicate bug"

    assert _label_present("Y*", text_raw_asterisk), "Failed to detect **Y*** (raw asterisk)"
    assert _label_present("Y*", text_escaped_asterisk), "Failed to detect **Y\\*** (escaped asterisk)"


def test_coordinator_audit_validate_5tuple_strict_passes_with_y_star():
    """coordinator_audit.validate_5tuple strict mode passes with all 5 labels including Y*."""
    receipt = """
**Y***: predicate accuracy 100%
**Xt**: coordinator_audit has Y* bug
**U**: [Edit coordinator_audit + czl_protocol, Write tests, Bash pytest]
**Yt+1**: Y* detection robust, 6/6 tests PASS
**Rt+1**: 0
"""
    passed, missing = validate_5tuple(receipt, strictness="strict")
    assert passed, f"validate_5tuple strict mode failed, missing: {missing}"
    assert missing == [], f"Expected no missing labels, got {missing}"


# --- Test 2: czl_protocol exempts short ack ---

def test_czl_protocol_exempts_short_ack():
    """czl_protocol.validate_dispatch returns [] (no issues) for short conversational ack."""
    short_ack_zh = "好的"
    short_ack_en = "OK"
    short_ack_medium = "Got it, will fix"

    issues_zh = validate_dispatch(short_ack_zh, agent_id="ceo")
    issues_en = validate_dispatch(short_ack_en, agent_id="ceo")
    issues_medium = validate_dispatch(short_ack_medium, agent_id="ceo")

    assert issues_zh == [], f"Expected [] for short ack (zh), got {issues_zh}"
    assert issues_en == [], f"Expected [] for short ack (en), got {issues_en}"
    assert issues_medium == [], f"Expected [] for medium ack, got {issues_medium}"


# --- Test 3: czl_protocol respects STRICTNESS_MAP ---

def test_czl_protocol_strictness_map_ceo_strict():
    """czl_protocol.validate_dispatch strict mode (CEO) fires on missing 1 label."""
    incomplete_ceo_dispatch = """
**Y***: Fix bug X
**Xt**: Bug exists
**U**: [Edit file.py, Bash pytest]
**Yt+1**: Bug fixed
# Missing Rt+1!
NOW 派 Ryan.
"""
    issues = validate_dispatch(incomplete_ceo_dispatch, agent_id="ceo")
    assert len(issues) > 0, f"Expected issues for strict CEO dispatch missing Rt+1, got {issues}"
    assert any("Rt+1" in issue for issue in issues), f"Expected Rt+1 issue, got {issues}"


def test_czl_protocol_strictness_map_engineer_lenient():
    """czl_protocol.validate_dispatch lenient mode (engineer) passes with ≥3 labels."""
    lenient_engineer_receipt = """
**Y***: Fix predicate bug
**Xt**: coordinator_audit has Y* FP
**U**: [Edit coordinator_audit, Write tests]
# Missing Yt+1, Rt+1 — but ≥3 labels present, lenient should pass
"""
    issues = validate_dispatch(lenient_engineer_receipt, agent_id="eng-governance")
    # Lenient mode: ≥3 labels → clear "Missing" issues, keep Warnings only
    missing_issues = [i for i in issues if i.startswith("Missing")]
    assert len(missing_issues) == 0, f"Expected lenient to pass with 3/5 labels, got {issues}"


# --- Test 4: Round-trip consistency ---

def test_round_trip_coordinator_audit_and_czl_protocol_consistent():
    """Same dispatch text validated by both modules → consistent verdict."""
    dispatch_text = """
**Y***: Fix bug
**Xt**: Bug exists
**U**: [Edit, Test]
**Yt+1**: Bug fixed
**Rt+1**: 0
NOW 派 Maya CZL-99.
"""
    # coordinator_audit check (strict)
    passed_coord, missing_coord = validate_5tuple(dispatch_text, strictness="strict")

    # czl_protocol check (strict, ceo agent_id)
    issues_czl = validate_dispatch(dispatch_text, agent_id="ceo")
    passed_czl = len([i for i in issues_czl if i.startswith("Missing")]) == 0

    # Both should agree (all 5 labels present → both pass)
    assert passed_coord == passed_czl, (
        f"Inconsistent verdict: coordinator_audit={passed_coord}, czl_protocol={passed_czl}"
    )


# --- Test 5: czl_protocol still flags missing recipient/task_id ---

def test_czl_protocol_flags_missing_recipient_task_id():
    """czl_protocol.validate_dispatch still warns on missing recipient/task_id (preserve original)."""
    dispatch_no_recipient = """
**Y***: Fix bug
**Xt**: Bug exists
**U**: [Edit file.py]
**Yt+1**: Bug fixed
**Rt+1**: 0
NOW 派 sub-agent fix bug.
"""
    issues = validate_dispatch(dispatch_no_recipient, agent_id="ceo")
    assert any("recipient" in issue.lower() for issue in issues), (
        f"Expected recipient warning, got {issues}"
    )
    assert any("task_id" in issue.lower() for issue in issues), (
        f"Expected task_id warning, got {issues}"
    )


# --- Test 6: coordinator_audit lenient mode 3+ labels passes ---

def test_coordinator_audit_lenient_mode_3_labels_passes():
    """coordinator_audit.validate_5tuple lenient mode passes with ≥3 labels."""
    receipt_3_labels = """
Y*: Fix bug
Xt: Bug exists
U: [Edit, Test]
# Missing Yt+1, Rt+1
"""
    passed, missing = validate_5tuple(receipt_3_labels, strictness="lenient")
    assert passed, f"Lenient mode should pass with 3/5 labels, got missing={missing}"
    assert missing == [], f"Expected no missing in lenient mode, got {missing}"
