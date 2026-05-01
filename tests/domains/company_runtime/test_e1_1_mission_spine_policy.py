from ystar.domains.company_runtime import (
    classify_admin_rule,
    classify_company_action,
    mission_action_preflight,
    mission_permission_check,
)


def test_m3_mission_ranks_above_admin_ceremony():
    mission = {"mission_id": "m1", "allowed_permission_tier": 1, "research_budget": {"max_pages_read": 5}}
    revenue = mission_action_preflight(mission, {"action": "read-only research for first paid customer interview"})
    admin = mission_action_preflight(mission, {"action": "daily report cadence"})
    assert revenue["recommended_priority"] == "raise_if_no_m1_m2_incident"
    assert admin["recommended_priority"] == "simplify_or_archive"


def test_old_content_calendar_archival_unless_reactivated():
    assert classify_admin_rule({"title": "old HN LinkedIn content calendar"})["decision"] == "ARCHIVE_LEGACY"
    assert classify_admin_rule({"title": "old HN LinkedIn content calendar", "reactivated": True})["decision"] == "SIMPLIFY_ACTIVE"


def test_read_only_research_allowed_with_budget():
    mission = {"mission_id": "m2", "allowed_permission_tier": 1, "research_budget": {"max_search_queries": 5}}
    result = mission_permission_check(mission, {"action": "read-only research public page search"})
    assert result["decision"] == "ALLOW_INTERNAL"


def test_customer_contact_requires_approval_and_core_writeback_review_gated():
    contact = classify_company_action({"action": "contact customer by email"})
    writeback = classify_company_action({"action": "core writeback to brain memory"})
    assert contact["decision"] == "NEEDS_OWNER_APPROVAL"
    assert writeback["decision"] == "REVIEW_GATED"


def test_mission_bound_report_can_be_active_non_mission_report_archived():
    active = classify_admin_rule({"title": "daily report", "mission_bound": True})
    archived = classify_admin_rule({"title": "daily report"})
    assert active["decision"] == "SIMPLIFY_ACTIVE"
    assert archived["decision"] == "ARCHIVE_LEGACY"


def test_mission_spine_preflight_never_executes_action():
    mission = {"mission_id": "m3", "allowed_permission_tier": 1, "research_budget": {"max_pages_read": 5}}
    result = mission_action_preflight(mission, {"action": "contact customer by email"})
    assert result["executes_action"] is False
    assert result["permission"]["executes_action"] is False
