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


class TestForgetGuardSchemaV05:
    """Validate ForgetGuard rule YAML uses v0.5 structured-only schema.

    Replaces the prior `TestCZLRuleSchema` class which asserted that specific
    keyword-blacklist rules MUST exist in the YAML — those tests were locking
    in the wrong design (speech-suppression rules). The v0.5 schema forbids
    keyword/regex matching against payload text; CZL protocol validation
    (validate_dispatch / validate_receipt) is now invoked at the dispatch /
    return event boundary as a typed validator, not via text patterns in this
    YAML file.

    See ystar/governance/forget_guard.py module docstring for the full
    rationale on speech-vs-behavior governance.
    """

    def test_yaml_loads_via_engine(self):
        """The rules YAML must load through ForgetGuard without raising."""
        from ystar.governance.forget_guard import ForgetGuard
        guard = ForgetGuard()
        assert isinstance(guard.rules, list)
        assert len(guard.rules) >= 1, "Expected at least one structured rule"

    def test_no_pattern_field_anywhere(self):
        """No rule may contain a `pattern:` field (forbidden in v0.5)."""
        import yaml as _yaml
        yaml_path = Path(__file__).parent.parent.parent / "ystar" / "governance" / "forget_guard_rules.yaml"
        data = _yaml.safe_load(yaml_path.read_text()) or {}
        for r in data.get("rules") or []:
            name = r.get("name", "<unnamed>")
            assert "pattern" not in r, (
                f"Rule '{name}' contains forbidden `pattern:` field. "
                f"Keyword/regex matching against text is not allowed in v0.5. "
                f"Use `type: structured` + `conditions:` instead."
            )

    def test_all_rules_declare_structured_type(self):
        """Every rule must declare type: structured and have a conditions dict."""
        import yaml as _yaml
        yaml_path = Path(__file__).parent.parent.parent / "ystar" / "governance" / "forget_guard_rules.yaml"
        data = _yaml.safe_load(yaml_path.read_text()) or {}
        for r in data.get("rules") or []:
            name = r.get("name", "<unnamed>")
            assert r.get("type") == "structured", (
                f"Rule '{name}' missing `type: structured` declaration"
            )
            conds = r.get("conditions")
            assert isinstance(conds, dict) and conds, (
                f"Rule '{name}' missing or empty `conditions:` dict"
            )

    def test_loader_rejects_pattern_rule(self):
        """Schema enforcement: loader must raise on a rule with `pattern:`."""
        import tempfile, os
        from ystar.governance.forget_guard import ForgetGuard, ForgetGuardSchemaError
        bad_yaml = """rules:
  - name: bad_keyword_rule
    pattern: "明日 稍后"
    mode: deny
    message: "x"
"""
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(bad_yaml)
            bad_path = f.name
        try:
            try:
                ForgetGuard(rules_path=bad_path)
                assert False, "Loader should have raised ForgetGuardSchemaError"
            except ForgetGuardSchemaError as e:
                assert "forbidden `pattern` field" in str(e)
        finally:
            os.unlink(bad_path)

    def test_purged_keyword_rules_do_not_reappear(self):
        """Sanity: a sample of purged v0.42 rule names must not be present."""
        import yaml as _yaml
        yaml_path = Path(__file__).parent.parent.parent / "ystar" / "governance" / "forget_guard_rules.yaml"
        data = _yaml.safe_load(yaml_path.read_text()) or {}
        purged = {
            "ceo_direct_engineer_dispatch", "defer_language",
            "choice_question_to_board", "coordinator_summary_rt_audit",
            "charter_drift_mid_session", "methodology_hardcoded_cadence",
            "missing_l_tag", "czl_dispatch_missing_5tuple",
            "czl_receipt_rt_not_zero", "czl_termination_drift_reply_catch",
            "engineer_receipt_missing_8_module_header",
        }
        live = {r.get("name") for r in (data.get("rules") or [])}
        leaked = purged & live
        assert not leaked, (
            f"Purged keyword-blacklist rules reappeared in YAML: {leaked}. "
            f"These rules conflated speech with behavior and were removed in "
            f"the 2026-04-25 purge. They must not be re-added."
        )
