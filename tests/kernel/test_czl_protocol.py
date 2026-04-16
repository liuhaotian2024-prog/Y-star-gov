"""
tests.kernel.test_czl_protocol — CZL Protocol validators test suite
===================================================================

Tests Gate 1 (dispatch validator) + Gate 2 (receipt validator empirical checks)
+ auto-fill parser for legacy tasks.

Includes Ethan#CZL-1 hallucination failure mode (receipt declares Rt+1=0 but
artifact missing → validate_receipt must return (False, >0)).

Author: Leo Chen (eng-kernel)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ystar.kernel.czl_protocol import (
    CZLMessageEnvelope,
    parse_legacy_task_to_envelope,
    validate_dispatch,
    validate_receipt,
)


# ============================================================================
# Gate 1: Dispatch Pre-Validator Tests
# ============================================================================


def test_validate_dispatch_happy_path():
    """Valid dispatch with all 5-tuple fields passes Gate 1."""
    prompt = """
=== CIEU 5-tuple dispatch ===

**Y***: kernel正确性 + test覆盖≥12 assertions
**Xt**: czl_protocol.py exists 13366 bytes, test_czl_protocol.py missing
**U**:
1. Read czl_protocol.py
2. Write test_czl_protocol.py with 12 assertions
3. pytest -v
**Yt+1**: Both files exist, all tests green
**Rt+1**: target = 0.0

Recipient: eng-kernel
Task ID: W29.3_czl_test
"""
    issues = validate_dispatch(prompt)
    assert issues == [], f"Expected no issues, got {issues}"


def test_validate_dispatch_missing_y_star():
    """Dispatch missing Y* fails Gate 1."""
    prompt = """
**Xt**: some state
**U**: some actions
**Yt+1**: some outcome
**Rt+1**: target = 0.0
"""
    issues = validate_dispatch(prompt)
    assert any("Y*" in issue for issue in issues), f"Expected Y* issue, got {issues}"


def test_validate_dispatch_xt_speculation_markers():
    """Xt containing speculation markers fails Gate 1."""
    prompt_zh = """
**Y***: Fix bug
**Xt**: 印象中文件应该存在
**U**: Fix it
**Yt+1**: Fixed
**Rt+1**: 0.0
"""
    issues = validate_dispatch(prompt_zh)
    assert any("speculation" in issue.lower() for issue in issues), f"Expected speculation issue, got {issues}"

    prompt_en = """
**Y***: Fix bug
**Xt**: The file should probably exist
**U**: Fix it
**Yt+1**: Fixed
**Rt+1**: 0.0
"""
    issues = validate_dispatch(prompt_en)
    assert any("speculation" in issue.lower() for issue in issues), f"Expected speculation issue, got {issues}"


def test_validate_dispatch_u_exceeds_atomic_limit():
    """U with >15 tool_uses estimate fails Gate 1."""
    prompt = """
**Y***: Big refactor
**Xt**: measured state
**U**:
This will need >15 tool_uses to complete, maybe 20 iterations
**Yt+1**: Refactored
**Rt+1**: 0.0
"""
    issues = validate_dispatch(prompt)
    assert any("atomic dispatch" in issue.lower() for issue in issues), f"Expected atomic violation, got {issues}"


def test_validate_dispatch_missing_recipient():
    """Dispatch without explicit recipient gets warning."""
    prompt = """
**Y***: Do something
**Xt**: state
**U**: actions
**Yt+1**: done
**Rt+1**: 0.0
"""
    issues = validate_dispatch(prompt)
    assert any("recipient" in issue.lower() for issue in issues), f"Expected recipient warning, got {issues}"


# ============================================================================
# Gate 2: Receipt Post-Validator Tests (Empirical Verification)
# ============================================================================


def test_validate_receipt_happy_path_artifact_exists():
    """Receipt declaring Rt+1=0 with existing artifacts passes Gate 2."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create artifact file
        artifact_path = Path(tmpdir) / "output.txt"
        artifact_path.write_text("completed work")

        receipt = """
**Y***: Create output.txt
**Xt**: output.txt does not exist
**U**: 1. Write output.txt
**Yt+1**: output.txt exists with content
**Rt+1** = 0.0

Verification:
```bash
ls -la output.txt
wc -l output.txt
```
"""
        is_valid, gap = validate_receipt(receipt, [artifact_path])
        assert is_valid, f"Expected valid receipt, got gap={gap}"
        assert gap == 0.0, f"Expected gap=0.0, got {gap}"


def test_validate_receipt_ethan_czl1_hallucination():
    """Receipt declares Rt+1=0 but artifact missing → Gate 2 REJECTS (Ethan#CZL-1 failure mode)."""
    nonexistent_path = Path("/tmp/nonexistent_czl_hallucination_test_12345.md")
    assert not nonexistent_path.exists(), "Test setup: artifact must not exist"

    receipt = """
**Y***: Create governance/czl_unified_communication_protocol_v1.md
**Xt**: File does not exist
**U**: 1. Write the spec
**Yt+1**: File exists ≥200 lines
**Rt+1** = 0.0

Done! Spec shipped.
"""
    is_valid, gap = validate_receipt(receipt, [nonexistent_path])
    assert not is_valid, "Expected rejection for missing artifact"
    assert gap >= 1.0, f"Expected gap ≥1.0 for missing artifact, got {gap}"


def test_validate_receipt_zero_tool_hallucination():
    """Receipt claims 'done' but no tool evidence → instant reject with gap=5.0."""
    receipt = """
**Rt+1** = 0.0

我已完成任务！
"""
    is_valid, gap = validate_receipt(receipt, [])
    assert not is_valid, "Expected rejection for zero-tool hallucination"
    assert gap >= 5.0, f"Expected gap ≥5.0 for hallucination, got {gap}"


def test_validate_receipt_pytest_output_verification():
    """Receipt with pytest output matching expected pass count passes Gate 2."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_path = Path(tmpdir) / "test.py"
        artifact_path.write_text("def test_foo(): pass")

        receipt = """
**Rt+1** = 0.0

```bash
pytest test.py -v
ls -la test.py
```
Output:
test.py::test_foo PASSED
6 passed in 0.42s
-rw-r--r-- 1 user user 42 Apr 16 test.py
"""
        is_valid, gap = validate_receipt(
            receipt,
            [artifact_path],
            tests_expected={"pytest": 6},
        )
        assert is_valid, f"Expected valid with pytest output, got gap={gap}"
        assert gap == 0.0, f"Expected gap=0.0, got {gap}"


def test_validate_receipt_pytest_insufficient_pass_count():
    """Receipt with fewer pytest passes than expected fails Gate 2."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_path = Path(tmpdir) / "test.py"
        artifact_path.write_text("def test_foo(): pass")

        receipt = """
**Rt+1** = 0.0

```bash
pytest test.py -v
```
Output:
test.py::test_foo PASSED
3 passed in 0.42s
"""
        is_valid, gap = validate_receipt(
            receipt,
            [artifact_path],
            tests_expected={"pytest": 6},
        )
        assert not is_valid, "Expected rejection for insufficient test passes"
        assert gap >= 1.0, f"Expected gap ≥1.0, got {gap}"


def test_validate_receipt_no_bash_verification():
    """Receipt without bash verification output fails Gate 2."""
    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_path = Path(tmpdir) / "output.txt"
        artifact_path.write_text("content")

        receipt = """
**Rt+1** = 0.0

Task completed successfully.
"""
        is_valid, gap = validate_receipt(receipt, [artifact_path])
        assert not is_valid, "Expected rejection for missing bash verification"
        assert gap >= 1.0, f"Expected gap ≥1.0 for missing verification, got {gap}"


# ============================================================================
# Auto-Fill Parser Tests
# ============================================================================


def test_parse_legacy_task_happy_path():
    """Well-structured legacy task parses with low confidence."""
    task_text = """
## Task: Implement CZL parser

**Context**: Legacy tasks lack 5-tuple structure

**Acceptance Criteria**:
- czl_protocol.py exists with 4 callables
- Tests pass ≥12 assertions

Actions:
1. Read spec
2. Write code
3. Write tests
4. Verify
"""
    envelope, low_conf = parse_legacy_task_to_envelope(
        task_text,
        task_id="W29.3",
        recipient="eng-kernel",
    )

    assert envelope["task_id"] == "W29.3"
    assert envelope["recipient"] == "eng-kernel"
    assert envelope["message_type"] == "dispatch"
    assert "czl_protocol.py" in envelope["y_star"]
    assert len(envelope["u"]) == 4, f"Expected 4 actions, got {len(envelope['u'])}"
    assert len(low_conf) == 0, f"Expected no low-confidence fields, got {low_conf}"


def test_parse_legacy_task_missing_acceptance_criteria():
    """Legacy task without Acceptance Criteria flags Y* as low-confidence."""
    task_text = """
Just fix the bug in the parser.
"""
    envelope, low_conf = parse_legacy_task_to_envelope(
        task_text,
        task_id="bugfix_1",
        recipient="eng-kernel",
    )

    assert "y_star" in low_conf, f"Expected y_star in low_conf, got {low_conf}"
    # Auto-fill uses first line + "completed with tests passing"
    assert "just fix the bug" in envelope["y_star"].lower()


def test_parse_legacy_task_no_context():
    """Legacy task without Context section flags Xt as low-confidence."""
    task_text = """
## Task: Implement feature X

**Acceptance Criteria**: Feature X works

Do the work.
"""
    envelope, low_conf = parse_legacy_task_to_envelope(
        task_text,
        task_id="feature_x",
        recipient="eng-platform",
    )

    assert "x_t" in low_conf, f"Expected x_t in low_conf, got {low_conf}"
    assert "Not measured" in envelope["x_t"]


def test_parse_legacy_task_sparse_text_flags_all():
    """Task with <50 chars flags all fields as low-confidence."""
    task_text = "Fix it"
    envelope, low_conf = parse_legacy_task_to_envelope(
        task_text,
        task_id="sparse",
        recipient="eng-governance",
    )

    assert "y_star" in low_conf
    assert "x_t" in low_conf
    assert "u" in low_conf
    assert "y_t_plus_1" in low_conf


def test_parse_legacy_task_role_tags_autofill():
    """Auto-fill parser sets role_tags with producer=ceo, executor=recipient."""
    task_text = """
## Task: Test role tags

**Acceptance Criteria**: Role tags correct
"""
    envelope, low_conf = parse_legacy_task_to_envelope(
        task_text,
        task_id="role_test",
        recipient="eng-domains",
    )

    assert envelope["role_tags"]["producer"] == "ceo"
    assert envelope["role_tags"]["executor"] == "eng-domains"
    assert envelope["role_tags"]["governed"] == "eng-domains"
