"""
Test suite for coordinator_audit.py
Board 2026-04-16 P0 meta-fix — CEO/CTO closure claim validation.
"""

import pytest
from ystar.governance.coordinator_audit import check_summary_rt_drift


def test_no_closure_claim_skips():
    """No closure language → skip (None)"""
    result = check_summary_rt_drift(
        reply_text="正在推进任务，进度良好...",
        taskstate=[{"id": "T1", "status": "pending", "description": "Fix bug"}]
    )
    assert result is None


def test_closure_claim_zero_pending_passes():
    """Closure claim + zero pending tasks → pass (None)"""
    result = check_summary_rt_drift(
        reply_text="今晚 wave 完整收敛，全部 done",
        taskstate=[]
    )
    assert result is None


def test_closure_claim_unjustified_pending_fires():
    """Closure claim + unjustified pending task → fire violation"""
    result = check_summary_rt_drift(
        reply_text="Wave 收敛，all green",
        taskstate=[{"id": "T1", "status": "pending", "description": "Fix bug"}]
    )
    assert result is not None
    assert result["violation"] is True
    assert result["pending_count"] == 1
    assert "T1" in result["unjustified_pending_ids"]
    assert "收敛" in result["claim_phrase"].lower() or "green" in result["claim_phrase"].lower()


def test_closure_claim_board_blocked_pending_passes():
    """Closure claim + Board-blocked pending task → pass (justified deferral)"""
    result = check_summary_rt_drift(
        reply_text="Wave 完整收敛，fully resolved",
        taskstate=[{"id": "T2", "status": "pending", "description": "Blocked by Board decision"}]
    )
    assert result is None


def test_closure_claim_mixed_pending_fires_once():
    """Closure claim + mixed (1 unjustified + 1 justified) → fire for unjustified only"""
    result = check_summary_rt_drift(
        reply_text="Landing complete, 所有任务完成",
        taskstate=[
            {"id": "T1", "status": "pending", "description": "Fix bug"},
            {"id": "T2", "status": "pending", "description": "defer Phase 2"},
        ]
    )
    assert result is not None
    assert result["violation"] is True
    assert result["pending_count"] == 1
    assert "T1" in result["unjustified_pending_ids"]
    assert "T2" not in result["unjustified_pending_ids"]


def test_closure_regex_variants():
    """Test multiple closure language variants (Chinese + English)"""
    test_cases = [
        "收敛",
        "complete",
        "全部 done",
        "wave shipped",
        "全部 verified",
        "all green",
        "fully resolved",
        "landing complete",
        "所有任务完成",
    ]
    for phrase in test_cases:
        result = check_summary_rt_drift(
            reply_text=f"今天进度: {phrase}",
            taskstate=[{"id": "T1", "status": "pending", "description": "Fix bug"}]
        )
        assert result is not None, f"Failed to detect closure phrase: {phrase}"
        assert result["violation"] is True


def test_defer_keywords_coverage():
    """Test all justified deferral keywords are recognized"""
    defer_keywords = [
        "defer",
        "Board-blocked",
        "pending Board",
        "Phase 2",
        "blocked by CEO",
        "awaiting Board",
        "Board approval required",
    ]
    for kw in defer_keywords:
        result = check_summary_rt_drift(
            reply_text="Wave 收敛，all done",
            taskstate=[{"id": "T1", "status": "pending", "description": f"Task {kw} decision"}]
        )
        assert result is None, f"Failed to recognize justified deferral keyword: {kw}"


def test_completed_status_ignored():
    """Completed tasks should not count as pending"""
    result = check_summary_rt_drift(
        reply_text="Wave 收敛，fully resolved",
        taskstate=[
            {"id": "T1", "status": "completed", "description": "Fix bug"},
            {"id": "T2", "status": "in_progress", "description": "defer Phase 2"},
        ]
    )
    assert result is None
