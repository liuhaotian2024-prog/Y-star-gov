"""
Test suite for claim_mismatch.py — E1 tool_uses drift detector
Board 2026-04-16 P0 enforcement
"""

import pytest
from ystar.governance.claim_mismatch import detect_tool_uses_mismatch


def test_claim_matches_metadata_no_fire():
    """When claimed = metadata, no mismatch detected."""
    receipt = "Task complete. Y*: done. Xt: baseline. U: [1,2,3]. Yt+1: shipped. Rt+1: 0. tool_uses: 7"
    metadata = 7
    result = detect_tool_uses_mismatch(receipt, metadata)
    assert result is None, "Should not fire when claim matches metadata exactly"


def test_claim_within_1_diff_no_fire():
    """±1 margin allowed for counting ambiguity."""
    receipt = "Completed in tool_uses: 10"
    metadata = 11
    result = detect_tool_uses_mismatch(receipt, metadata)
    assert result is None, "Should not fire when diff < 2 (±1 margin)"


def test_hallucination_claim_exceeds_actual():
    """Claimed > actual, diff ≥2 → hallucination severity."""
    receipt = "Sub-agent return: tool_uses: 13 (Ryan C3 pattern)"
    metadata = 8  # diff = 5
    result = detect_tool_uses_mismatch(receipt, metadata)
    assert result is not None, "Should fire when diff ≥ 2"
    assert result["claimed"] == 13
    assert result["actual"] == 8
    assert result["diff"] == 5
    assert result["severity"] == "hallucination", "Claimed > actual = hallucination"


def test_omission_claim_below_actual():
    """Claimed < actual, diff ≥2 → omission severity."""
    receipt = "Finished work. Tool calls: 9"
    metadata = 22  # diff = 13 (Ryan B3 pattern)
    result = detect_tool_uses_mismatch(receipt, metadata)
    assert result is not None
    assert result["claimed"] == 9
    assert result["actual"] == 22
    assert result["diff"] == 13
    assert result["severity"] == "omission", "Claimed < actual = omission"


def test_zero_tool_hallucination_ethan_czl1_class():
    """Claimed > 0 but metadata = 0 → zero_tool_hallucination (Ethan#CZL-1 class)."""
    receipt = "Completed mission. Tool_uses: 9 (Ethan#CZL-1 pattern)"
    metadata = 0
    result = detect_tool_uses_mismatch(receipt, metadata)
    assert result is not None
    assert result["claimed"] == 9
    assert result["actual"] == 0
    assert result["diff"] == 9
    assert result["severity"] == "zero_tool_hallucination", "Ethan#CZL-1 class = most severe"


def test_chinese_regex_variant():
    """Chinese '工具调用：13' should be parsed correctly."""
    receipt = "任务完成。工具调用：15"
    metadata = 10  # diff = 5
    result = detect_tool_uses_mismatch(receipt, metadata)
    assert result is not None
    assert result["claimed"] == 15
    assert result["actual"] == 10
    assert result["diff"] == 5


def test_no_claim_in_receipt_skip():
    """If receipt doesn't mention tool_uses, skip enforcement (freeform receipts allowed for now)."""
    receipt = "Task done. All tests passed. Rt+1: 0."
    metadata = 12
    result = detect_tool_uses_mismatch(receipt, metadata)
    assert result is None, "Should skip when no tool_uses claim in receipt"


def test_hyphen_underscore_variants():
    """Regex should handle tool_uses, tool-uses, tool uses."""
    test_cases = [
        ("tool_uses: 5", 10),
        ("tool-uses: 5", 10),
        ("tool uses: 5", 10),
        ("tool calls: 5", 10),
    ]
    for receipt, metadata in test_cases:
        result = detect_tool_uses_mismatch(receipt, metadata)
        assert result is not None, f"Failed to parse: {receipt}"
        assert result["claimed"] == 5
        assert result["actual"] == 10
