"""
Claim vs Metadata Mismatch Detector
E1 priority enforcement — Sub-agent receipt tool_uses claim validation.

Board 2026-04-16 P0: Ryan C3 (claim 13, metadata 38, diff 25), Ryan C2 (claim 14, metadata 24, diff 10),
Ryan B3 (claim 9, metadata 22, diff 13), Ethan#CZL-1 (claim 9, metadata 0).

Usage:
    result = detect_tool_uses_mismatch(receipt_text, metadata_tool_uses)
    if result:
        # Fire ForgetGuard warn/deny with result dict
"""

import re
from typing import Optional


def detect_tool_uses_mismatch(
    receipt_text: str,
    metadata_tool_uses: int
) -> Optional[dict]:
    """
    Detect mismatch between sub-agent receipt claim and actual tool_uses metadata.

    Args:
        receipt_text: Sub-agent return message (5-tuple receipt or freeform)
        metadata_tool_uses: Actual tool_uses count from MCP/Agent metadata

    Returns:
        dict with {claimed, actual, diff, severity} if diff ≥ 2, else None

    Severity levels:
        - "hallucination": claimed > actual (agent inflated work)
        - "omission": claimed < actual (agent underreported work)
        - "zero_tool_hallucination": claimed > 0 and actual = 0 (Ethan#CZL-1 class)
    """
    # Regex patterns for tool_uses claim (English + Chinese)
    # Matches: "tool_uses: 13", "tool calls: 9", "工具调用：13", "tool-uses: 7"
    patterns = [
        r"tool[_ -]?uses?\s*[:：]\s*(\d+)",
        r"tool[_ -]?calls?\s*[:：]\s*(\d+)",
        r"工具调用\s*[:：]\s*(\d+)",
    ]

    claimed = None
    for pattern in patterns:
        match = re.search(pattern, receipt_text, re.IGNORECASE)
        if match:
            claimed = int(match.group(1))
            break

    # No claim found in receipt → skip (not enforced for freeform receipts yet)
    if claimed is None:
        return None

    diff = abs(claimed - metadata_tool_uses)

    # Threshold: diff < 2 → no fire (allow ±1 margin for counting ambiguity)
    if diff < 2:
        return None

    # Determine severity
    if claimed > 0 and metadata_tool_uses == 0:
        severity = "zero_tool_hallucination"  # Ethan#CZL-1 class
    elif claimed > metadata_tool_uses:
        severity = "hallucination"  # Agent inflated work
    else:
        severity = "omission"  # Agent underreported work

    return {
        "claimed": claimed,
        "actual": metadata_tool_uses,
        "diff": diff,
        "severity": severity,
    }
