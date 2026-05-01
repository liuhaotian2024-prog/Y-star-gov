from ystar.domains.company_runtime import (
    classify_m_triangle_alignment,
    mission_action_preflight,
    value_production_relevance,
)


def test_revenue_relevant_task_gets_high_value_relevance():
    result = value_production_relevance({"title": "first paid customer interview"})
    assert result["relevance"] == "HIGH"


def test_admin_ceremony_low_value_when_not_mission_bound():
    result = value_production_relevance({"title": "daily report cadence"})
    assert result["relevance"] == "LOW"


def test_m_triangle_alignment_detects_m3_revenue_task():
    result = classify_m_triangle_alignment({"title": "paid pilot customer feedback"})
    assert result["m3"] is True
    assert result["primary"] == "M-3 Value Production"


def test_mission_action_preflight_combines_permission_and_value():
    mission = {"mission_id": "m1", "allowed_permission_tier": 1, "research_budget": {"max_pages_read": 5}}
    result = mission_action_preflight(mission, {"action": "read-only research for first paid customer interview"})
    assert result["permission"]["decision"] == "ALLOW_INTERNAL"
    assert result["value_production_relevance"]["relevance"] == "HIGH"
    assert result["recommended_priority"] == "raise_if_no_m1_m2_incident"


def test_mission_action_preflight_flags_admin_burden():
    mission = {"mission_id": "m2", "allowed_permission_tier": 0}
    result = mission_action_preflight(mission, {"action": "daily report cadence"})
    assert result["admin_rule"]["decision"] == "ARCHIVE_LEGACY"
    assert result["recommended_priority"] == "simplify_or_archive"

