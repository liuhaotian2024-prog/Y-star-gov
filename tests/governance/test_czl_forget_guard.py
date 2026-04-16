"""
tests/governance/test_czl_forget_guard.py
==========================================

CZL Protocol ForgetGuard integration tests.
Validates Gate 1 (dispatch) and Gate 2 (receipt) rules fire correctly.

Phase B2 of CZL enforcement — rule-level testing before live dogfood.
Leo#3 SPINE parser validation complete (16/16 pytest), now wiring into ForgetGuard.

Author: Maya Patel (eng-governance)
Date: 2026-04-16
"""
from pathlib import Path

import pytest

from ystar.kernel.czl_protocol import validate_dispatch, validate_receipt


class TestCZLDispatchGate1:
    """Gate 1: Pre-validator blocks invalid dispatch prompts."""

    def test_valid_dispatch_passes(self):
        """Valid dispatch with all 5-tuple sections should return empty issues."""
        valid_prompt = """
        Task: Fix governance loop bug

        **Y*** (ideal): governance_loop.py imports resolve to correct modules, pytest 12/12 PASS
        **Xt** (pre-state): Read governance_loop.py shows import error at line 42 (measured via Read tool)
        **U** (actions):
        1. Read governance_loop.py lines 40-50
        2. Edit line 42 to fix import path
        3. Run pytest tests/governance/test_governance_loop.py
        4. Bash: git add + commit with [L3 TESTED] tag
        **Yt+1** (post-state): pytest 12/12 PASS output in receipt
        **Rt+1** target: 0.0 (all U steps complete + pytest paste)

        recipient: eng-governance
        task_id: maya_task_governance_loop_fix_001
        """
        issues = validate_dispatch(valid_prompt)
        assert issues == [], f"Valid dispatch should have no issues, got: {issues}"

    def test_missing_xt_rejected(self):
        """Dispatch missing Xt pre-state should be rejected."""
        missing_xt_prompt = """
        **Y*** (ideal): governance_loop.py fixed
        **U** (actions): 1. Fix bug
        **Yt+1**: Fixed
        **Rt+1**: 0
        """
        issues = validate_dispatch(missing_xt_prompt)
        assert any("Missing Xt" in issue for issue in issues), \
            f"Should detect missing Xt, got issues: {issues}"

    def test_speculation_in_xt_rejected(self):
        """Xt containing speculation markers (印象/should/probably) should be rejected."""
        speculation_prompt = """
        **Y***: Code works
        **Xt**: 应该有个bug在那里 (印象)
        **U**: 1. Fix it
        **Yt+1**: Fixed
        **Rt+1**: 0
        """
        issues = validate_dispatch(speculation_prompt)
        assert any("speculation" in issue.lower() for issue in issues), \
            f"Should detect speculation in Xt, got: {issues}"

    def test_atomic_dispatch_violation_rejected(self):
        """Dispatch estimating >15 tool_uses violates atomic dispatch principle."""
        oversize_prompt = """
        **Y***: Huge refactor
        **Xt**: Read 50 files, all need changes
        **U** (>20 tool_uses estimate):
        1-20. Edit many files...
        **Yt+1**: All fixed
        **Rt+1**: 0
        """
        issues = validate_dispatch(oversize_prompt)
        assert any("atomic dispatch" in issue.lower() for issue in issues), \
            f"Should reject >15 tool_uses, got: {issues}"


class TestCZLReceiptGate2:
    """Gate 2: Post-validator rejects hallucinated receipts via empirical checks."""

    def test_valid_receipt_passes(self, tmp_path: Path):
        """Receipt with existing artifacts + bash output should validate."""
        # Create expected artifact
        test_file = tmp_path / "test_output.txt"
        test_file.write_text("test content")

        valid_receipt = """
        **Y***: File created
        **Xt**: File did not exist
        **U**: 1. Write test_output.txt
        **Yt+1**: File exists with content
        **Rt+1**: 0.0

        Bash verification:
        ```bash
        $ ls -la test_output.txt
        -rw-r--r-- 1 user user 13 Apr 16 02:00 test_output.txt
        $ wc -l test_output.txt
        1 test_output.txt
        ```
        """
        is_valid, gap = validate_receipt(
            valid_receipt,
            artifacts_expected=[test_file],
        )
        assert is_valid, f"Valid receipt should pass, gap={gap}"
        assert gap == 0.0, f"Expected gap=0.0 for valid receipt, got {gap}"

    def test_hallucinated_artifact_rejected(self, tmp_path: Path):
        """Receipt claiming Rt+1=0 but artifact missing should be rejected."""
        nonexistent_file = tmp_path / "hallucinated.txt"

        hallucinated_receipt = """
        **Rt+1**: 0.0

        Done! File created successfully.
        """
        is_valid, gap = validate_receipt(
            hallucinated_receipt,
            artifacts_expected=[nonexistent_file],
        )
        assert not is_valid, "Hallucinated receipt should fail validation"
        assert gap >= 1.0, f"Missing artifact should add ≥1.0 to gap, got {gap}"

    def test_zero_tool_hallucination_rejected(self):
        """Receipt claiming 'done' without any tool evidence should instant-reject."""
        zero_tool_receipt = """
        **Rt+1**: 0.0

        我已完成所有任务。
        """
        is_valid, gap = validate_receipt(
            zero_tool_receipt,
            artifacts_expected=[],  # Even with no artifacts expected
        )
        assert not is_valid, "Zero-tool hallucination should fail"
        assert gap >= 5.0, f"Zero-tool pattern should add ≥5.0 gap, got {gap}"

    def test_pytest_count_mismatch_rejected(self):
        """Receipt with fewer pytest passes than expected should be rejected."""
        receipt_low_pass_count = """
        **Rt+1**: 0.0

        pytest output:
        3 passed in 0.5s
        """
        is_valid, gap = validate_receipt(
            receipt_low_pass_count,
            artifacts_expected=[],
            tests_expected={"pytest": 6},  # Expect 6, got only 3
        )
        assert not is_valid, "Low pytest count should fail validation"
        assert gap >= 1.0, f"Test count mismatch should add ≥1.0 gap, got {gap}"

    def test_missing_bash_verification_rejected(self):
        """Receipt without bash verification output should be rejected."""
        no_bash_receipt = """
        **Rt+1**: 0.0

        Task completed successfully.
        """
        is_valid, gap = validate_receipt(
            no_bash_receipt,
            artifacts_expected=[],
        )
        assert not is_valid, "Receipt without bash verification should fail"
        assert gap >= 1.0, f"Missing bash output should add ≥1.0 gap, got {gap}"


class TestCZLRuleSchema:
    """Validate ForgetGuard rule YAML schema matches czl_protocol."""

    def test_czl_rules_exist_in_yaml(self):
        """Both czl_dispatch_missing_5tuple and czl_receipt_rt_not_zero must exist."""
        yaml_path = Path(__file__).parent.parent.parent / "ystar" / "governance" / "forget_guard_rules.yaml"
        assert yaml_path.exists(), f"ForgetGuard rules YAML not found: {yaml_path}"

        yaml_content = yaml_path.read_text()
        assert "czl_dispatch_missing_5tuple" in yaml_content, \
            "Missing czl_dispatch_missing_5tuple rule in ForgetGuard YAML"
        assert "czl_receipt_rt_not_zero" in yaml_content, \
            "Missing czl_receipt_rt_not_zero rule in ForgetGuard YAML"

    def test_czl_rules_have_deny_action(self):
        """CZL rules must use action: deny (not warn)."""
        yaml_path = Path(__file__).parent.parent.parent / "ystar" / "governance" / "forget_guard_rules.yaml"
        yaml_content = yaml_path.read_text()

        # Extract czl_dispatch rule section
        dispatch_section_start = yaml_content.find("czl_dispatch_missing_5tuple")
        receipt_section_start = yaml_content.find("czl_receipt_rt_not_zero")
        assert dispatch_section_start != -1 and receipt_section_start != -1, \
            "CZL rule sections not found in YAML"

        dispatch_section = yaml_content[dispatch_section_start:dispatch_section_start + 500]
        receipt_section = yaml_content[receipt_section_start:receipt_section_start + 500]

        assert "mode: deny" in dispatch_section, \
            "czl_dispatch_missing_5tuple must have mode: deny"
        assert "mode: deny" in receipt_section, \
            "czl_receipt_rt_not_zero must have mode: deny"

    def test_czl_rules_call_validators(self):
        """CZL rules should reference czl_protocol validators."""
        yaml_path = Path(__file__).parent.parent.parent / "ystar" / "governance" / "forget_guard_rules.yaml"
        yaml_content = yaml_path.read_text()

        assert "czl_protocol.validate_dispatch" in yaml_content, \
            "czl_dispatch rule should call validate_dispatch"
        assert "czl_protocol.validate_receipt" in yaml_content, \
            "czl_receipt rule should call validate_receipt"
