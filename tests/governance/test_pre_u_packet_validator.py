from ystar.governance.pre_u_packet_validator import (
    ValidationDecision,
    validate_pre_u_packet,
)


def valid_packet():
    return {
        "packet_id": "preu-1",
        "agent_id": "Aiden-CEO",
        "agent_capsule_ref": "agent_brains/Aiden-CEO",
        "task_id": "task-1",
        "y_star": {"summary": "ship a safe validator skeleton"},
        "m_functor": {"summary": "align governance readiness with mission"},
        "x_t_summary": "docs-only spec exists; skeleton not implemented yet",
        "candidate_actions": [
            {
                "candidate_id": "u1",
                "u_summary": "add deterministic skeleton",
                "predicted_y_t1": "tests pass with no runtime integration",
                "predicted_r_t1": {"summary": "residual reduced", "estimated_distance_to_zero": 0},
            }
        ],
        "selected_action": {
            "selected_candidate_id": "u1",
            "why_selected": "closest to Rt+1 = 0 with minimal scope",
        },
        "residual_minimization_rationale": "u1 closes the implementation gap without adding runtime hooks",
        "governance_expectations": {
            "requires_y_star_validation": True,
            "requires_m_functor_validation": True,
            "requires_scope_validation": True,
            "requires_high_risk_review": False,
        },
        "cieu_link_policy": {
            "should_emit_pre_action_event": True,
            "should_emit_post_action_event": True,
            "compare_predicted_vs_actual": True,
        },
        "packet_status": "ready_for_validation",
        "risk_tier": 1,
    }


def codes(result):
    return {issue.code for issue in result.issues}


def test_valid_packet_allows():
    result = validate_pre_u_packet(valid_packet())

    assert result.passed is True
    assert result.decision == ValidationDecision.ALLOW
    assert result.validation_status == "valid"
    assert result.failure_codes == []


def test_missing_y_star_requires_revision():
    packet = valid_packet()
    packet.pop("y_star")

    result = validate_pre_u_packet(packet)

    assert result.passed is False
    assert result.decision == ValidationDecision.REQUIRE_REVISION
    assert "PREU-Y-STAR" in codes(result)


def test_missing_candidate_actions_denies():
    packet = valid_packet()
    packet["candidate_actions"] = []

    result = validate_pre_u_packet(packet)

    assert result.decision == ValidationDecision.DENY
    assert "PREU-CANDIDATES" in codes(result)


def test_selected_action_must_reference_candidate():
    packet = valid_packet()
    packet["selected_action"]["selected_candidate_id"] = "missing"

    result = validate_pre_u_packet(packet)

    assert result.decision == ValidationDecision.DENY
    assert "PREU-SELECTED-U" in codes(result)


def test_missing_predicted_residual_denies():
    packet = valid_packet()
    packet["candidate_actions"][0].pop("predicted_r_t1")

    result = validate_pre_u_packet(packet)

    assert result.decision == ValidationDecision.DENY
    assert "PREU-PREDICTED-R" in codes(result)


def test_missing_cieu_link_policy_requires_revision():
    packet = valid_packet()
    packet.pop("cieu_link_policy")

    result = validate_pre_u_packet(packet)

    assert result.decision == ValidationDecision.REQUIRE_REVISION
    assert "PREU-CIEU-LINK" in codes(result)


def test_high_risk_packet_requires_escalation():
    packet = valid_packet()
    packet["risk_tier"] = 3
    packet["governance_expectations"]["requires_high_risk_review"] = True

    result = validate_pre_u_packet(packet)

    assert result.passed is False
    assert result.decision == ValidationDecision.ESCALATE
    assert "PREU-RISK-TIER" in codes(result)


def test_validator_uses_standard_library_only():
    import ystar.governance.pre_u_packet_validator as module

    assert "jsonschema" not in getattr(module, "__dict__", {})
