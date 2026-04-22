"""
Test behavior rules detection correctness (pre-CIEU emission layer).

P0.2 Atomic: Top 3 critical rules detection proof.
- czl_receipt_rt_not_zero (via czl_protocol.validate_receipt)
- subagent_tool_uses_claim_mismatch (via claim_mismatch.detect_tool_uses_mismatch)
- coordinator_summary_rt_audit (via coordinator_audit.check_summary_rt_drift)

Strategy: Test validators detect violations correctly. CIEU emission happens at harness layer.

Each test:
1. Call validator with data that should trigger detection
2. Assert validator returns correct violation dict
3. Verify all expected fields present
"""
import tempfile
from pathlib import Path
from ystar.kernel.czl_protocol import validate_receipt
from ystar.governance.claim_mismatch import detect_tool_uses_mismatch
from ystar.governance.coordinator_audit import check_summary_rt_drift


def test_czl_receipt_rt_not_zero_detection():
    """
    czl_receipt_rt_not_zero: validate_receipt should reject hallucinated Rt+1=0
    when artifacts don't exist.

    Criticality: Highest — prevents Ethan#CZL-1 zero-tool hallucination class.
    """
    # Create temp dir for test artifacts
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Receipt claims Rt+1=0 but file doesn't exist
        receipt = """
        Receipt 5-tuple:
        - Y*: File exists at test_artifact.md
        - Xt: No file
        - U: Write file
        - Yt+1: File exists with 100 lines
        - Rt+1=0.0

        Verification:
        ```bash
        ls -la test_artifact.md
        wc -l test_artifact.md
        ```
        """

        # Validate against non-existent artifact
        artifacts_expected = [tmppath / "test_artifact.md"]
        is_valid, gap = validate_receipt(receipt, artifacts_expected)

        # Should reject: file doesn't exist
        assert not is_valid, "validate_receipt should reject when artifact missing"
        assert gap > 0, f"Expected gap > 0 when artifact missing, got {gap}"

    # Test 2: Receipt with artifact present should pass
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        artifact = tmppath / "test_artifact.md"
        artifact.write_text("test content\n" * 10)

        receipt = """
        Receipt 5-tuple:
        - Y*: File exists
        - Xt: No file
        - U: Write file
        - Yt+1: File exists
        - Rt+1=0.0

        ```bash
        ls -la test_artifact.md
        -rw-r--r-- 1 user user 130 test_artifact.md
        wc -l test_artifact.md
        10 test_artifact.md
        ```
        """

        artifacts_expected = [artifact]
        is_valid, gap = validate_receipt(receipt, artifacts_expected)

        # Should pass: artifact exists + bash verification present
        assert is_valid, f"validate_receipt should pass when artifact exists, gap={gap}"
        assert gap == 0.0, f"Expected gap=0.0, got {gap}"


def test_subagent_tool_uses_claim_mismatch_detection():
    """
    subagent_tool_uses_claim_mismatch: detect_tool_uses_mismatch should flag
    receipts with tool_uses claim ≥2 diff from metadata.

    Criticality: E1 priority — catches hallucination (claim > actual)
    and omission (claim < actual).
    """
    # Test 1: Zero-tool hallucination (Ethan#CZL-1 class)
    receipt = "Receipt: Tool uses: 9 (completed all tasks)"
    metadata_tool_uses = 0

    result = detect_tool_uses_mismatch(receipt, metadata_tool_uses)

    assert result is not None, "Should detect zero-tool hallucination"
    assert result["claimed"] == 9
    assert result["actual"] == 0
    assert result["diff"] == 9
    assert result["severity"] == "zero_tool_hallucination", \
        f"Expected zero_tool_hallucination, got {result['severity']}"

    # Test 2: Regular hallucination (claim > actual)
    receipt = "Tool_uses: 13 (read, grep, write)"
    metadata_tool_uses = 5

    result = detect_tool_uses_mismatch(receipt, metadata_tool_uses)

    assert result is not None
    assert result["claimed"] == 13
    assert result["actual"] == 5
    assert result["diff"] == 8
    assert result["severity"] == "hallucination"

    # Test 3: Omission (claim < actual)
    receipt = "tool calls: 9"
    metadata_tool_uses = 22

    result = detect_tool_uses_mismatch(receipt, metadata_tool_uses)

    assert result is not None
    assert result["claimed"] == 9
    assert result["actual"] == 22
    assert result["diff"] == 13
    assert result["severity"] == "omission"

    # Test 4: Within threshold (diff < 2) should not trigger
    receipt = "tool uses: 10"
    metadata_tool_uses = 11

    result = detect_tool_uses_mismatch(receipt, metadata_tool_uses)

    assert result is None, "Should not trigger when diff < 2"


def test_coordinator_summary_rt_audit_detection():
    """
    coordinator_summary_rt_audit: check_summary_rt_drift should flag
    coordinator closure claims when unjustified pending tasks exist.

    Criticality: Meta-gate — prevents coordinator-level drift undetected by
    per-receipt validation.
    """
    # Test 1: Closure claim with unjustified pending tasks
    reply_text = "今晚 wave 完整收敛, all tasks green, shipping complete"
    taskstate = [
        {"id": "T1", "status": "pending", "description": "Fix installation bug"},
        {"id": "T2", "status": "pending", "description": "Write tests"},
        {"id": "T3", "status": "done", "description": "Completed task"},
        {"id": "T4", "status": "pending", "description": "defer Phase 2"},  # justified
    ]

    result = check_summary_rt_drift(reply_text, taskstate)

    assert result is not None, "Should detect closure claim with pending tasks"
    assert result["violation"] is True
    assert result["pending_count"] == 2, f"Expected 2 unjustified pending, got {result['pending_count']}"
    assert "T1" in result["unjustified_pending_ids"]
    assert "T2" in result["unjustified_pending_ids"]
    assert "T4" not in result["unjustified_pending_ids"], "T4 is justified (defer Phase 2)"

    # Test 2: Closure claim with all pending justified should not trigger
    reply_text = "wave shipped, all green"
    taskstate = [
        {"id": "T1", "status": "pending", "description": "defer Phase 2"},
        {"id": "T2", "status": "pending", "description": "Board-blocked payment"},
        {"id": "T3", "status": "done", "description": "Completed"},
    ]

    result = check_summary_rt_drift(reply_text, taskstate)

    assert result is None, "Should not trigger when all pending are justified"

    # Test 3: No closure language should not trigger
    reply_text = "Continuing work on remaining tasks"
    taskstate = [
        {"id": "T1", "status": "pending", "description": "Fix bug"},
    ]

    result = check_summary_rt_drift(reply_text, taskstate)

    assert result is None, "Should not trigger without closure language"
