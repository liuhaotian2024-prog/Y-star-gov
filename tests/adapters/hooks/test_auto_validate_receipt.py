"""
tests/adapters/hooks/test_auto_validate_receipt.py
===================================================

Tests for E2: auto_validate_subagent_receipt() — generalized CZL Gate 2.

Test cases:
1. Receipt with valid artifact paths (all exist) → pass
2. Receipt with missing artifact paths → fail
3. Receipt with no extractable paths → "no_artifacts_to_check" status
4. CIEU emit verification (mocked CIEU store)
5. Graceful handling on empty input

Author: Ryan Park (eng-platform)
Created: 2026-04-16
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from ystar.adapters.hooks.stop_hook import (
    auto_validate_subagent_receipt,
    _extract_artifact_paths_from_prose,
)


# ── Test 1: Receipt with valid artifact paths (all exist) → pass ────────────

def test_auto_validate_receipt_valid_artifacts():
    """Receipt with valid paths (all artifacts exist on disk) should pass."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create test artifacts
        file1 = tmpdir_path / "output.py"
        file2 = tmpdir_path / "report.md"
        file1.write_text("# test file", encoding="utf-8")
        file2.write_text("# report", encoding="utf-8")

        # Mock receipt with bash verification
        receipt = f"""
        Task completed.

        **Yt+1**: Created {file1} and {file2}.
        **Rt+1**: 0

        Verification:
        ```bash
        ls -la {tmpdir}
        # Output: output.py  report.md

        wc -l {file1}
        # 1 {file1}
        ```
        """

        result = auto_validate_subagent_receipt(
            receipt_text=receipt,
            declared_artifacts=[file1, file2],
        )

        assert result["is_valid"] is True
        assert result["validation_status"] == "pass"
        assert len(result["missing_artifacts"]) == 0
        assert result["claimed_rt"] == 0.0
        assert result["actual_rt"] == 0.0


# ── Test 2: Receipt with missing artifact paths → fail ──────────────────────

def test_auto_validate_receipt_missing_artifacts():
    """Receipt claiming files that don't exist should fail validation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create only file1, NOT file2 (simulate hallucination)
        file1 = tmpdir_path / "exists.py"
        file2 = tmpdir_path / "missing.py"
        file1.write_text("# exists", encoding="utf-8")
        # file2 intentionally NOT created

        receipt = f"""
        Task completed.

        **Yt+1**: Created {file1} and {file2}.
        **Rt+1**: 0
        """

        result = auto_validate_subagent_receipt(
            receipt_text=receipt,
            declared_artifacts=[file1, file2],
        )

        assert result["is_valid"] is False
        assert result["validation_status"] == "fail"
        assert len(result["missing_artifacts"]) == 1
        assert file2 in result["missing_artifacts"]
        assert result["actual_rt"] >= 1.0  # Penalty for missing artifact


# ── Test 3: Receipt with no extractable paths → "no_artifacts_to_check" ─────

def test_auto_validate_receipt_no_artifacts():
    """Receipt with no file paths should return no_artifacts_to_check status."""
    receipt = """
    Task analyzed. No files created (this was a read-only analysis task).

    **Yt+1**: Analysis complete.
    **Rt+1**: 0
    """

    result = auto_validate_subagent_receipt(
        receipt_text=receipt,
        declared_artifacts=None,  # Auto-extract from prose
    )

    assert result["validation_status"] == "no_artifacts_to_check"
    assert result["is_valid"] is True  # Non-deliverable tasks pass
    assert len(result["missing_artifacts"]) == 0


# ── Test 4: CIEU emit verification (mocked) ──────────────────────────────────

@patch("ystar.adapters.hooks.stop_hook._emit_cieu_event")
def test_auto_validate_receipt_emits_cieu(mock_emit):
    """Validation should always emit CIEU RECEIPT_AUTO_VALIDATED event."""
    receipt = """
    No artifacts (analysis task).
    **Rt+1**: 0
    """

    auto_validate_subagent_receipt(
        receipt_text=receipt,
        declared_artifacts=None,
    )

    # Verify CIEU event was emitted
    mock_emit.assert_called_once()
    call_args = mock_emit.call_args
    assert call_args[0][0] == "RECEIPT_AUTO_VALIDATED"
    assert "validation_status" in call_args[0][1]


# ── Test 5: Graceful handling on empty input ─────────────────────────────────

def test_auto_validate_receipt_empty_input():
    """Empty receipt should not crash, should return no_artifacts_to_check."""
    result = auto_validate_subagent_receipt(
        receipt_text="",
        declared_artifacts=None,
    )

    assert result["validation_status"] == "no_artifacts_to_check"
    assert result["is_valid"] is True
    assert len(result["missing_artifacts"]) == 0


# ── Test 6: Prose extraction regex verification ─────────────────────────────

def test_extract_artifact_paths_from_prose():
    """_extract_artifact_paths_from_prose should correctly extract file paths."""
    receipt = """
    I wrote ystar/adapters/hooks/stop_hook.py and created tests/test_hook.py.
    Also landed docs/guide.md and shipped config.yaml.
    """

    paths = _extract_artifact_paths_from_prose(receipt)

    # Convert to strings for easier assertion
    path_strs = [str(p) for p in paths]

    assert "ystar/adapters/hooks/stop_hook.py" in path_strs
    assert "tests/test_hook.py" in path_strs
    assert "docs/guide.md" in path_strs
    assert "config.yaml" in path_strs
    assert len(paths) == 4


# ── Test 7: Claimed Rt vs actual Rt mismatch detection ──────────────────────

def test_auto_validate_receipt_rt_mismatch():
    """Receipt claiming Rt+1=0 but missing artifacts → actual_rt > claimed_rt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        missing_file = tmpdir_path / "hallucinated.py"
        # File intentionally NOT created

        receipt = f"""
        Task completed. Created {missing_file}.

        **Rt+1**: 0
        """

        result = auto_validate_subagent_receipt(
            receipt_text=receipt,
            declared_artifacts=[missing_file],
        )

        assert result["claimed_rt"] == 0.0
        assert result["actual_rt"] > 0.0  # Gap detected
        assert result["is_valid"] is False


# ── Test 8: Auto-emit RT_MEASUREMENT from 5-tuple receipt ────────────────────

def test_auto_validate_emits_rt_measurement():
    """Receipt with 5-tuple should auto-emit RT_MEASUREMENT CIEU event."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create test artifact
        file1 = tmpdir_path / "output.py"
        file1.write_text("# test", encoding="utf-8")

        # Receipt with full 5-tuple and proper bash verification
        receipt = f"""
        **Y***: File exists at {file1} with valid content
        **Xt**: No file existed
        **U**: (1) Created {file1} (2) Wrote content
        **Yt+1**: File exists with 1 line
        **Rt+1**: 0

        Verification:
        ```bash
        ls -la {tmpdir}
        # output.py

        wc -l {file1}
        #       1 {file1}
        ```
        """

        # Mock the emit_rt_measurement function to capture call
        from unittest.mock import patch
        with patch("ystar.kernel.rt_measurement.emit_rt_measurement") as mock_emit:
            result = auto_validate_subagent_receipt(
                receipt_text=receipt,
                declared_artifacts=[file1],
            )

            # Verify RT_MEASUREMENT was emitted
            assert mock_emit.call_count == 1
            call_kwargs = mock_emit.call_args.kwargs

            # Verify 5-tuple fields passed correctly
            assert "File exists" in call_kwargs["y_star"]
            assert "No file existed" in call_kwargs["x_t"]
            assert len(call_kwargs["u"]) == 2
            assert "Created" in call_kwargs["u"][0]
            assert "File exists with 1 line" in call_kwargs["y_t_plus_1"]
            assert call_kwargs["rt_value"] == 0.0  # actual_rt from validation
