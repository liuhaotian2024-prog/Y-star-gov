from ystar.domains.company_runtime import mission_permission_check


def test_tier1_readonly_research_requires_budget():
    mission = {"mission_id": "m1", "allowed_permission_tier": 1, "owner_goal": "research market"}
    result = mission_permission_check(mission, {"action": "read-only research public page search"})
    assert result["missing_budget"] is True
    assert result["decision"] == "NEEDS_OWNER_APPROVAL"


def test_tier1_readonly_research_with_budget_allowed():
    mission = {
        "mission_id": "m1",
        "allowed_permission_tier": 1,
        "owner_goal": "research market",
        "research_budget": {"max_search_queries": 5, "max_pages_read": 10},
    }
    result = mission_permission_check(mission, {"action": "read-only research public page search"})
    assert result["missing_budget"] is False
    assert result["decision"] == "ALLOW_INTERNAL"


def test_mission_forbidden_action_blocks():
    mission = {
        "mission_id": "m2",
        "allowed_permission_tier": 2,
        "forbidden_action_classes": ["publication"],
    }
    result = mission_permission_check(mission, {"action": "publication draft execution"})
    assert result["decision"] == "BLOCKED"


def test_external_action_builds_escalation():
    mission = {"mission_id": "m3", "allowed_permission_tier": 2}
    result = mission_permission_check(mission, {"action": "send message to selected founder"})
    assert result["decision"] == "NEEDS_OWNER_APPROVAL"
    assert result["escalation"]["executes_action"] is False
