"""
Test suite for coordinator_audit.py
Board 2026-04-16 P0 meta-fix — CEO/CTO closure claim validation.
"""

import pytest
from ystar.governance.coordinator_audit import (
    check_summary_rt_drift,
    check_wave_scope_declared,
    check_reply_5tuple_compliance,
)


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


# === Board 2026-04-16 hypocrisy fix: coordinator reply 5-tuple structure ===

class TestReply5TupleCompliance:
    """Test coordinator reply 5-tuple structure enforcement."""

    def test_short_reply_skips_check(self):
        """Replies ≤200 chars exempt from 5-tuple requirement."""
        short_reply = "老大，收到。正在跑 pytest。"
        result = check_reply_5tuple_compliance(short_reply)
        assert result is None, "Short reply should skip 5-tuple check"

    def test_long_reply_all_5_sections_present(self):
        """Reply >200 chars with all 5 sections passes."""
        compliant_reply = """
**Y\***: All tests pass + rule active.

**Xt**: coordinator_audit.py exists; forget_guard_rules.yaml has 18 rules.

**U**: (1) Read coordinator_audit.py (2) Read forget_guard_rules.yaml (3) Add check_reply_5tuple_compliance helper (4) Add YAML rule.

**Yt+1**: Helper + rule + test PASS + receipt pastes.

**Rt+1** = 1 if helper missing + 1 if rule missing + 1 if test fails. Target 0.
        """
        result = check_reply_5tuple_compliance(compliant_reply)
        assert result is None, "Compliant reply should pass"

    def test_long_reply_missing_sections_fires(self):
        """Reply >200 chars missing any of 5 sections triggers violation."""
        # Missing Xt and U sections
        partial_reply = """
老大，这是一个很长的回复，超过200字符。

**Y\***: 所有测试通过 + 规则生效。

**Yt+1**: Helper + rule + test PASS + receipt pastes.

**Rt+1** = 1 if helper missing + 1 if rule missing + 1 if test fails. Target 0.

这个回复缺少 Xt 和 U 部分，应该触发违规检测。ForgetGuard 会拦截这种纯散文回复。
        """
        result = check_reply_5tuple_compliance(partial_reply)
        assert result is not None, "Missing sections should trigger violation"
        assert result["violation"] is True
        assert "Xt" in result["missing_sections"]
        assert "U" in result["missing_sections"]
        assert result["char_count"] > 200

    def test_pure_prose_reply_fires_all_missing(self):
        """Pure prose reply >200 chars fires with all 5 sections missing."""
        prose_reply = """
老大，今晚的工作进展顺利。已经完成了以下任务：

1. Ryan 完成了 F2 emit-side canonical validation pattern [L4 SHIPPED]
2. Leo 完成了 charter_drift 检测器 [L3 TESTED]
3. Jordan 完成了 claim_mismatch 扩展 [L3 TESTED]

下一步计划：
- Maya 实装 coordinator_reply_missing_5tuple rule
- 完成 E1 + I1 全 wave 测试覆盖

所有 sub-agent receipts 已验证 Rt+1=0。Wave 完整收敛。
        """
        result = check_reply_5tuple_compliance(prose_reply)
        assert result is not None, "Prose reply should trigger violation"
        assert result["violation"] is True
        assert len(result["missing_sections"]) == 5  # All missing
        assert set(result["missing_sections"]) == {"Y*", "Xt", "U", "Yt+1", "Rt+1"}


class TestWaveScopeDeclared:
    """Test wave/batch closure scope declaration enforcement."""

    def test_wave_closure_without_taskid_list(self):
        """Wave + closure language without TaskID list → violation."""
        reply = "本批已全部 shipped，进入下一 wave。"
        result = check_wave_scope_declared(reply)
        assert result is not None
        assert result["violation"] is True
        assert result["wave_term"] in ["本批", "wave"]

    def test_wave_closure_with_taskid_list(self):
        """Wave + closure language WITH TaskID list → no violation."""
        reply = "Wave shipped: #123, #124, #125 all verified."
        result = check_wave_scope_declared(reply)
        assert result is None, "Explicit TaskID list should pass"
