"""
Test Predicate Merge — coordinator_audit 2-stage semantic upgrade (CZL-120)

Tests Stage 1 (is_dispatch_receipt) + Stage 2 (validate_5tuple) + composed function.
Per reply_scan_detector_methodology_v1.md + formal_methods_primer_v1.md §4.

Author: Maya Patel (eng-governance)
Date: 2026-04-16
Task: CZL-120 P0 atomic (RIGHT merge predicate methodology → coordinator_audit)
"""

import pytest
from ystar.governance.coordinator_audit import (
    is_dispatch_receipt,
    validate_5tuple,
    check_reply_5tuple_compliance
)


# === Stage 1: is_dispatch_receipt() Tests ===

def test_short_ack_exempt():
    """§2.4 short ack — exempt from 5-tuple (len <50 chars)."""
    reply = "好的"
    is_dispatch, reason = is_dispatch_receipt(reply, "ceo")
    assert is_dispatch is False, f"Short ack should be exempt, got reason={reason}"
    assert reason == "exempt:short_reply"


def test_long_prose_no_triggers_exempt():
    """§2.1-2.3 conversational prose — no action verbs/artifacts, exempt."""
    # Extended to >50 chars to avoid short_reply exempt (Chinese chars count correctly)
    reply = "明白，这个思路很清楚，我同意这个判断。没有任何文件路径或者 commit hash 或者行动动词。这段话确实比较长，超过五十个字符了吧。"
    is_dispatch, reason = is_dispatch_receipt(reply, "ceo")
    assert is_dispatch is False, f"Conversational prose should be exempt, got reason={reason}"
    assert reason == "exempt:conversational"


def test_action_verb_dispatch_trigger():
    """§1.1 action verb — dispatch trigger fires."""
    reply = "NOW 派 Ryan CZL-112 修复 coordinator_reply_missing_5tuple import 路径，≤8 tool_uses，禁 git commit。"
    is_dispatch, reason = is_dispatch_receipt(reply, "ceo")
    assert is_dispatch is True, f"Action verb '派' should trigger dispatch, got reason={reason}"
    assert "action_verb" in reason


def test_artifact_landing_trigger():
    """§1.2 artifact landing — commit hash + maturity tag trigger."""
    reply = "Maya CZL-111 forensic shipped (L3 VALIDATED), commit f00e91ac, 20/20 deliverables verified, Rt+1=1."
    is_dispatch, reason = is_dispatch_receipt(reply, "maya-governance")
    assert is_dispatch is True, f"Artifact markers should trigger dispatch, got reason={reason}"
    assert "artifact_landed" in reason


# === Stage 2: validate_5tuple() Tests ===

def test_strict_all_5_labels_present_pass():
    """§3.1 strict mode — all 5 labels present (CEO→Board)."""
    reply = r"""
**Y\***: Ryan CZL-112 claimed + completed Rt+1=0
**Xt**: import path broken
**U**: grep + edit + pytest
**Yt+1**: import path fixed, 6/6 tests PASS
**Rt+1**: 0
"""
    passed, missing = validate_5tuple(reply, strictness="strict")
    assert passed is True, f"All 5 labels present, should pass strict mode, missing={missing}"
    assert missing == []


def test_strict_missing_2_labels_fail():
    """§3.1 strict mode — missing Xt + Yt+1, should fail."""
    reply = r"""
**Y\***: Fix import bug
**U**: edited file
**Rt+1**: 0
"""
    passed, missing = validate_5tuple(reply, strictness="strict")
    assert passed is False, "Missing Xt/Yt+1 should fail strict mode"
    assert "Xt" in missing
    assert "Yt+1" in missing


def test_lenient_3_labels_present_pass():
    """§3.2 lenient mode — ≥3 labels present (sub-agent receipt)."""
    reply = """
Y*: Fix bug
Xt: broken
U: edit + test
"""
    passed, missing = validate_5tuple(reply, strictness="lenient")
    assert passed is True, f"3/5 labels present, should pass lenient mode, missing={missing}"


def test_lenient_2_labels_fail():
    """§3.2 lenient mode — only 2 labels, <3 threshold, should fail."""
    reply = """
Y*: Fix bug
Rt+1: 0
"""
    passed, missing = validate_5tuple(reply, strictness="lenient")
    assert passed is False, "Only 2/5 labels, should fail lenient mode (need ≥3)"
    assert "<3 labels found (2/5)" in missing[0]


# === Composed Function: check_reply_5tuple_compliance() Tests ===

def test_composed_short_ack_no_violation():
    """Composed: short ack → Stage 1 exempt → None (no violation)."""
    violation = check_reply_5tuple_compliance("好的", strictness="strict", agent_id="ceo")
    assert violation is None, "Short ack should not trigger violation"


def test_composed_dispatch_with_5tuple_no_violation():
    """Composed: dispatch trigger + strict 5-tuple present → None (compliant)."""
    reply = r"""
NOW 派 Ryan CZL-99 修复 X。

**Y\***: Ryan CZL-99 claimed + completed Rt+1=0
**Xt**: X broken
**U**: grep + edit + pytest
**Yt+1**: X fixed
**Rt+1**: 0
"""
    violation = check_reply_5tuple_compliance(reply, strictness="strict", agent_id="ceo")
    assert violation is None, "Dispatch with valid 5-tuple should not violate"


def test_composed_dispatch_missing_5tuple_violation():
    """Composed: dispatch trigger (action verb) + missing 5-tuple → violation."""
    # Extended to >50 chars to avoid short_reply exempt (original was 26 chars)
    reply = "NOW 派 Ryan CZL-99 修复 coordinator_reply_missing_5tuple import 路径，≤8 tool_uses，禁 git commit。这段话超过五十个字符了。"
    violation = check_reply_5tuple_compliance(reply, strictness="strict", agent_id="ceo")
    assert violation is not None, "Dispatch without 5-tuple should violate"
    assert violation["violation"] is True
    assert "action_verb" in violation["reason"]
    assert len(violation["missing_labels"]) == 5  # All labels missing


def test_composed_lenient_subagent_3_labels_pass():
    """Composed: sub-agent receipt, lenient mode, 3/5 labels → no violation."""
    reply = """
Shipped CZL-104 meta-meta audit.
Y*: Audit Maya deliverables
Xt: 20 items pending verify
U: re-verify 20 items, document 5 errors
Rt+1: 1 (test file pending)
"""
    violation = check_reply_5tuple_compliance(reply, strictness="lenient", agent_id="maya-governance")
    assert violation is None, "Sub-agent lenient with 4/5 labels should not violate"


def test_composed_lenient_subagent_2_labels_violation():
    """Composed: sub-agent receipt, lenient mode, 2/5 labels → violation."""
    reply = """
Shipped CZL-104 meta-meta audit.
Y*: Audit Maya deliverables
Rt+1: 1
"""
    violation = check_reply_5tuple_compliance(reply, strictness="lenient", agent_id="maya-governance")
    assert violation is not None, "Sub-agent lenient with <3 labels should violate"
    assert violation["violation"] is True
    assert violation["strictness"] == "lenient"
    assert "<3 labels found (2/5)" in violation["missing_labels"][0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
