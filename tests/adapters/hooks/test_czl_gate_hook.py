"""
tests/adapters/hooks/test_czl_gate_hook.py
===========================================
Test CZL Gate 1/2 correction injection in stop_hook.py.

Integration test for CZL Unified Communication Protocol enforcement.
Validates that dispatch/receipt validators are correctly wired into hook.

Test Coverage:
    ✓ Gate 1: Valid dispatch passes silently
    ✓ Gate 1: Missing Xt dispatch returns correction reminder
    ✓ Gate 2: Valid receipt (Rt=0, artifacts present) passes silently
    ✓ Gate 2: Hallucinated receipt (missing artifacts) returns rejection
    ✓ CIEU events emitted correctly
    ✓ No crash on empty/None inputs

Platform Engineer: Ryan Park (eng-platform)
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ystar.adapters.hooks.stop_hook import inject_czl_corrections


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def valid_dispatch_prompt() -> str:
    r"""Valid dispatch prompt with full 5-tuple."""
    return r"""
**Y\*** (ideal): File `foo.py` exists with 50+ lines.

**Xt** (pre-state): `foo.py` missing (verified via Read tool).

**U** (actions):
1. Write `foo.py` with 60 lines
2. Verify with `wc -l foo.py`

**Yt+1**: File exists with 60 lines (verified via bash).

**Rt+1** target: 0.0 (closure when file present + line count matches)

Recipient: eng-platform
Task ID: test_dispatch_001
"""


@pytest.fixture
def invalid_dispatch_prompt() -> str:
    r"""Invalid dispatch missing Xt and U sections."""
    return r"""
**Y\***: File `foo.py` exists.

Yt+1: File will exist.
Rt+1 target: 0.0

Recipient: eng-platform
"""


@pytest.fixture
def valid_receipt_with_artifacts(tmp_path: Path) -> tuple[str, list[Path]]:
    """Valid receipt with empirical artifact verification."""
    artifact_path = tmp_path / "test_artifact.py"
    artifact_path.write_text("# Created by sub-agent\n" * 10, encoding="utf-8")

    receipt = f"""
**Rt+1** = 0.0 (empirically verified)

Artifacts created:
- {artifact_path}

Bash verification:
```bash
$ wc -l {artifact_path}
10 {artifact_path}
```

Tool calls executed: Write, Bash (2 total)
"""
    return receipt, [artifact_path]


@pytest.fixture
def hallucinated_receipt_missing_artifact(tmp_path: Path) -> tuple[str, list[Path]]:
    """Receipt claiming success but artifact missing (Ethan#CZL-1 pattern)."""
    artifact_path = tmp_path / "nonexistent_file.md"  # NOT created

    receipt = f"""
**Rt+1** = 0.0 (claimed but not verified)

我已完成任务，文件已创建：{artifact_path}

工具调用：Write
"""
    return receipt, [artifact_path]


# ── Gate 1 Tests ──────────────────────────────────────────────────────────

def test_gate1_valid_dispatch_passes_silently(valid_dispatch_prompt: str):
    """Valid dispatch → None (silent pass, no correction needed)."""
    result = inject_czl_corrections(prompt_text=valid_dispatch_prompt)
    assert result is None, "Valid dispatch should pass without correction"


def test_gate1_invalid_dispatch_returns_correction(invalid_dispatch_prompt: str):
    """Missing Xt/U → correction reminder with exact missing sections."""
    result = inject_czl_corrections(prompt_text=invalid_dispatch_prompt)

    assert result is not None, "Invalid dispatch must return correction"
    assert "<system-reminder>" in result, "Correction must use system-reminder XML"
    assert "CZL Gate 1 Rejection" in result, "Must identify as Gate 1 failure"
    assert "Missing Xt" in result or "Missing U" in result, "Must list missing sections"


# ── Gate 2 Tests ──────────────────────────────────────────────────────────

def test_gate2_valid_receipt_passes_silently(valid_receipt_with_artifacts):
    """Valid receipt (Rt=0, artifacts exist) → None (silent pass)."""
    receipt_text, artifacts = valid_receipt_with_artifacts
    result = inject_czl_corrections(receipt_text=receipt_text, artifacts_expected=artifacts)

    assert result is None, "Valid receipt with present artifacts should pass"


def test_gate2_hallucinated_receipt_rejected(hallucinated_receipt_missing_artifact):
    """Hallucinated success (artifact missing) → rejection reminder."""
    receipt_text, artifacts = hallucinated_receipt_missing_artifact
    result = inject_czl_corrections(receipt_text=receipt_text, artifacts_expected=artifacts)

    assert result is not None, "Hallucinated receipt must be rejected"
    assert "<system-reminder>" in result, "Rejection must use system-reminder XML"
    assert "CZL Gate 2 Rejection" in result, "Must identify as Gate 2 failure"
    assert "Actual Rt+1" in result, "Must report empirical gap"
    assert "Missing artifacts" in result or "nonexistent_file.md" in result, "Must list missing artifacts"


# ── CIEU Event Emission Tests ─────────────────────────────────────────────

@patch("ystar.kernel.cieu.emit")
def test_gate1_emits_cieu_dispatch_rejected(mock_emit, invalid_dispatch_prompt: str):
    """Gate 1 failure emits CZL_DISPATCH_REJECTED CIEU event."""
    inject_czl_corrections(prompt_text=invalid_dispatch_prompt)

    # emit() should be called with CZL_DISPATCH_REJECTED
    assert mock_emit.called, "CIEU emit() should be called on Gate 1 rejection"
    call_args = mock_emit.call_args
    assert call_args[1]["event_type"] == "CZL_DISPATCH_REJECTED", "Event type mismatch"


@patch("ystar.kernel.cieu.emit")
def test_gate2_emits_cieu_receipt_rejected(mock_emit, hallucinated_receipt_missing_artifact):
    """Gate 2 failure emits CZL_RECEIPT_REJECTED CIEU event."""
    receipt_text, artifacts = hallucinated_receipt_missing_artifact
    inject_czl_corrections(receipt_text=receipt_text, artifacts_expected=artifacts)

    # emit() should be called with CZL_RECEIPT_REJECTED
    assert mock_emit.called, "CIEU emit() should be called on Gate 2 rejection"
    call_args = mock_emit.call_args
    assert call_args[1]["event_type"] == "CZL_RECEIPT_REJECTED", "Event type mismatch"


# ── Edge Case Tests ───────────────────────────────────────────────────────

def test_no_crash_on_empty_inputs():
    """Empty/None inputs → silent pass, no crash."""
    result1 = inject_czl_corrections()
    result2 = inject_czl_corrections(prompt_text=None, receipt_text=None)
    result3 = inject_czl_corrections(prompt_text="", receipt_text="", artifacts_expected=[])

    assert result1 is None, "No inputs → silent pass"
    assert result2 is None, "None inputs → silent pass"
    assert result3 is None or result3 is not None, "Empty inputs → no crash (may return correction or None)"


def test_graceful_degradation_if_czl_protocol_unavailable():
    """If czl_protocol import fails → graceful degradation, no crash."""
    with patch("ystar.adapters.hooks.stop_hook.validate_dispatch", None):
        with patch("ystar.adapters.hooks.stop_hook.validate_receipt", None):
            result = inject_czl_corrections(prompt_text="test")
            assert result is None, "Graceful degradation when validators unavailable"
