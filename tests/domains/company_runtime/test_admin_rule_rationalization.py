from ystar.domains.company_runtime import (
    classify_admin_rule,
    is_mission_bound_obligation,
    should_archive_admin_rule,
)


def test_old_daily_report_rule_is_archive_unless_mission_bound():
    result = classify_admin_rule({"rule": "daily report every night for every agent"})
    assert result["decision"] == "SIMPLIFY_OR_ARCHIVE"
    assert result["action_class"] == "reporting_obligation"
    assert should_archive_admin_rule({"rule": "weekly report cadence"}) is True


def test_mission_bound_report_rule_can_remain_active():
    result = classify_admin_rule(
        {
            "rule": "weekly report for mission evidence",
            "mission_id": "mission_1",
            "m_triangle_alignment": "M-2 governability and M-3 value production",
        }
    )
    assert result["decision"] == "ALLOW_INTERNAL"
    assert result["action_class"] == "mission_bound_obligation"
    assert is_mission_bound_obligation({"mission_id": "mission_1"}) is True


def test_stale_legacy_directive_archives_by_default():
    result = classify_admin_rule({"rule": "old directive legacy LinkedIn posting schedule"})
    assert result["decision"] == "SIMPLIFY_OR_ARCHIVE"
    assert result["action_class"] == "stale_legacy_directive"


def test_owner_decision_required_admin_rule():
    result = classify_admin_rule({"rule": "patent filing reactivation", "owner_decision_needed": True})
    assert result["decision"] == "OWNER_DECISION_REQUIRED"


def test_iron_rule_zero_semantics_recommendation_plus_controls():
    result = classify_admin_rule(
        {
            "rule": "approval packet must include recommended default plus approve/reject/request_revision/hold controls",
            "mission_id": "mission_2",
            "m_triangle_alignment": "M-2 governability",
        }
    )
    assert result["decision"] == "ALLOW_INTERNAL"
