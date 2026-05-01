from ystar.domains.company_runtime import (
    classify_admin_rule,
    classify_stale_directive,
    is_mission_bound_obligation,
    should_archive_admin_rule,
)


def test_m_triangle_rule_keep_core():
    result = classify_admin_rule({"title": "M Triangle governs M-1 M-2 M-3"})
    assert result["decision"] == "KEEP_CORE"


def test_deterministic_enforcement_keep_core():
    result = classify_admin_rule({"rule_text": "deterministic enforcement and CIEU evidence are required"})
    assert result["decision"] == "KEEP_CORE"


def test_external_sending_requires_permission_tier():
    result = classify_admin_rule({"rule_text": "social post and send email require approval"})
    assert result["decision"] == "REPLACE_WITH_PERMISSION_TIER"


def test_daily_report_not_mission_bound_archived_or_simplified():
    result = classify_admin_rule({"title": "daily report", "rule_text": "must report every night"})
    assert result["decision"] == "ARCHIVE_LEGACY"
    assert should_archive_admin_rule({"title": "daily report", "rule_text": "must report every night"})
    autonomous = classify_admin_rule({"title": "daily autonomous report", "rule_text": "must report every night"})
    assert autonomous["decision"] == "ARCHIVE_LEGACY"


def test_mission_bound_report_is_simplified_active():
    result = classify_admin_rule({"title": "daily report", "mission_bound": True})
    assert result["decision"] == "SIMPLIFY_ACTIVE"
    assert is_mission_bound_obligation({"active_mission_id": "m1"}, {"mission_id": "m1"})


def test_old_content_calendar_archived_unless_reactivated():
    result = classify_admin_rule({"title": "old LinkedIn content calendar"})
    assert result["decision"] == "ARCHIVE_LEGACY"
    active = classify_admin_rule({"title": "old LinkedIn content calendar", "reactivated": True})
    assert active["decision"] == "SIMPLIFY_ACTIVE"


def test_old_enterprise_sales_owner_decision_required():
    result = classify_admin_rule({"title": "Enterprise Sales Phase 1 warm intro"})
    assert result["decision"] == "OWNER_DECISION_REQUIRED"


def test_stale_directive_classification():
    assert classify_stale_directive({"task": "old LinkedIn calendar"})["decision"] == "ARCHIVE_LEGACY"
    assert classify_stale_directive({"task": "old three-repo integration sprint"})["decision"] == "SUPERSEDED_BY_RUNTIME"
    assert classify_stale_directive({"task": "weekly report cadence"})["decision"] == "ADMIN_BURDEN"
