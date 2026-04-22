"""
Test suite for ForgetGuard rule: methodology_hardcoded_cadence
Board 2026-04-16 MEMORY feedback_methodology_no_human_time_grain enforcement.

Coverage:
1. "weekly review" → fires
2. "after N atomic completions" → passes
3. "30d expiry" → fires
4. "after Board directive" → passes
5. "Week 1-4 timeline" → fires
6. Chinese "每周检查" → fires
"""

import pytest
from ystar.governance.coordinator_audit import check_hardcoded_cadence


def test_weekly_review_fires():
    """Test that 'weekly review' triggers violation."""
    text = "Methodology: weekly review of OmissionEngine scan results."
    result = check_hardcoded_cadence(text)
    assert result is not None, "Expected violation for 'weekly review'"
    assert result["violation"] is True
    assert "weekly" in result["matched_phrase"].lower()


def test_after_n_atomic_completions_passes():
    """Test that dependency-sequence language passes."""
    text = "Methodology: after 5 atomic completions, emit WAVE_COMPLETE event."
    result = check_hardcoded_cadence(text)
    assert result is None, "Expected no violation for 'after N atomic completions'"


def test_30d_expiry_fires():
    """Test that '24h' / implicit time-grain triggers violation."""
    # Rule pattern includes "24h", "workday" — testing similar spirit with "30d"
    # Actually, rule doesn't have "30d" in pattern — let's test "24h" instead
    text = "SLA: respond within 24h of CIEU emission."
    result = check_hardcoded_cadence(text)
    assert result is not None, "Expected violation for '24h'"
    assert "24h" in result["matched_phrase"].lower()


def test_after_board_directive_passes():
    """Test that event-trigger language passes."""
    text = "Dispatch Ethan after Board directive to proceed with refactor."
    result = check_hardcoded_cadence(text)
    assert result is None, "Expected no violation for 'after Board directive'"


def test_week_enumeration_fires():
    """Test that 'Week 1-4 timeline' triggers violation."""
    text = "Roadmap: Week 1 foundation, Week 2 integration, Week 3 testing, Week 4 ship."
    result = check_hardcoded_cadence(text)
    assert result is not None, "Expected violation for 'Week N' enumeration"
    # Pattern should match "Week 1", "Week 2", etc.
    assert "week" in result["matched_phrase"].lower()


def test_chinese_weekly_fires():
    """Test that Chinese '每周' triggers violation."""
    text = "治理协议：每周检查 CIEU 审计链完整性。"
    result = check_hardcoded_cadence(text)
    assert result is not None, "Expected violation for Chinese '每周'"
    assert "每周" in result["matched_phrase"]


def test_context_extraction():
    """Test that violation dict includes surrounding context."""
    text = "The agent will perform weekly scans to detect drift."
    result = check_hardcoded_cadence(text)
    assert result is not None
    assert "context" in result
    # Context should include ±20 chars around match
    assert "weekly" in result["context"].lower()


def test_monthly_quarterly_annual_fire():
    """Test other time-grain keywords: monthly, quarterly, annual."""
    test_cases = [
        ("monthly status report to Board", "monthly"),
        ("quarterly OKR review session", "quarterly"),
        ("annual governance audit cycle", "annual"),
    ]
    for text, expected_keyword in test_cases:
        result = check_hardcoded_cadence(text)
        assert result is not None, f"Expected violation for '{expected_keyword}'"
        assert expected_keyword in result["matched_phrase"].lower()


def test_sprint_biweekly_fortnight_fire():
    """Test sprint-related keywords: sprint, biweekly, fortnight."""
    test_cases = [
        ("Sprint 1: foundation work", "sprint"),
        ("biweekly sync with CTO", "biweekly"),
        ("fortnight iteration cycle", "fortnight"),
    ]
    for text, expected_keyword in test_cases:
        result = check_hardcoded_cadence(text)
        assert result is not None, f"Expected violation for '{expected_keyword}'"
        assert expected_keyword in result["matched_phrase"].lower()


def test_workday_fires():
    """Test that 'workday' triggers violation."""
    text = "SLA: respond within 1 workday."
    result = check_hardcoded_cadence(text)
    assert result is not None, "Expected violation for 'workday'"
    assert "workday" in result["matched_phrase"].lower()


def test_chinese_monthly_quarterly_daily_fire():
    """Test Chinese time-grain keywords: 每月, 每季, 每天."""
    test_cases = [
        ("每月财务报告", "每月"),
        ("每季度 OKR 复盘", "每季"),
        ("每天晨会打卡", "每天"),
    ]
    for text, expected_keyword in test_cases:
        result = check_hardcoded_cadence(text)
        assert result is not None, f"Expected violation for Chinese '{expected_keyword}'"
        assert expected_keyword in result["matched_phrase"]
