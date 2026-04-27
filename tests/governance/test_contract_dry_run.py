from ystar.governance.contract_dry_run import (
    DryRunDecision,
    run_governance_contract_dry_run,
)


def valid_packet():
    return {
        "packet_id": "preu-1",
        "agent_id": "Aiden-CEO",
        "agent_capsule_ref": "agent_brains/Aiden-CEO",
        "task_id": "task-1",
        "y_star": {"summary": "ship safe governance dry-run"},
        "m_functor": {"summary": "align dry-run proof with governance safety"},
        "x_t_summary": "Pre-U and delta validators exist",
        "candidate_actions": [
            {
                "candidate_id": "u1",
                "u_summary": "add dry-run harness",
                "predicted_y_t1": "dry-run harness exists with tests",
                "predicted_r_t1": {"summary": "residual reduced"},
            }
        ],
        "selected_action": {
            "selected_candidate_id": "u1",
            "why_selected": "minimal scope closest to Rt+1 = 0",
        },
        "residual_minimization_rationale": "u1 connects existing validators without runtime execution",
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


def valid_outcome():
    return {
        "event_id": "delta-1",
        "recorded_at": "2026-04-27T00:00:00Z",
        "actual_y_t1": "dry-run harness exists with tests",
        "actual_r_t1": {"summary": "residual reduced"},
        "delta_summary": "prediction matched dry-run expectation",
        "residual_delta": {"direction": "reduced"},
        "delta_class": "matched",
        "learning_eligibility": {"eligible": False, "requires_curation": True},
        "cieu_event_ref": "dry-run://not-runtime-cieu",
        "validator_result_ref": "dry-run://validator/preu-1",
        "brain_writeback_policy": {
            "eligible_after_curation": False,
            "requires_curation": True,
            "automatic_direct_writeback": False,
        },
    }


def test_valid_packet_with_mock_outcome_passes():
    result = run_governance_contract_dry_run(valid_packet())

    assert result.dry_run_decision == DryRunDecision.PASS
    assert result.delta_validation_result is not None
    assert result.generated_delta_record["dry_run_only"] is True
    assert result.generated_delta_record["not_runtime_cieu"] is True


def test_valid_packet_with_supplied_valid_outcome_passes():
    result = run_governance_contract_dry_run(valid_packet(), valid_outcome())

    assert result.dry_run_decision == DryRunDecision.PASS
    assert result.delta_validation_result.passed is True


def test_invalid_pre_u_stops_before_delta_construction():
    packet = valid_packet()
    packet.pop("y_star")

    result = run_governance_contract_dry_run(packet)

    assert result.dry_run_decision == DryRunDecision.REQUIRE_REVISION
    assert result.delta_validation_result is None
    assert result.generated_delta_record is None


def test_selected_u_mismatch_stops_before_delta_construction():
    packet = valid_packet()
    packet["selected_action"]["selected_candidate_id"] = "missing"

    result = run_governance_contract_dry_run(packet)

    assert result.dry_run_decision == DryRunDecision.REQUIRE_REVISION
    assert result.delta_validation_result is None


def test_unsafe_automatic_brain_writeback_outcome_denies():
    outcome = valid_outcome()
    outcome["brain_writeback_policy"] = {
        "automatic_direct_writeback": True,
        "requires_curation": False,
    }

    result = run_governance_contract_dry_run(valid_packet(), outcome)

    assert result.dry_run_decision == DryRunDecision.DENY
    assert result.delta_validation_result is not None
    assert "CIEU-DELTA-WRITEBACK-POLICY" in result.delta_validation_result.failure_codes


def test_high_risk_packet_escalates():
    packet = valid_packet()
    packet["risk_tier"] = 3
    packet["governance_expectations"]["requires_high_risk_review"] = True

    result = run_governance_contract_dry_run(packet, valid_outcome())

    assert result.dry_run_decision == DryRunDecision.ESCALATE
    assert result.generated_delta_record is not None


def test_dry_run_result_confirms_non_execution():
    result = run_governance_contract_dry_run(valid_packet())

    assert result.non_execution_confirmation["selected_u_executed"] is False
    assert result.non_execution_confirmation["hook_called"] is False
    assert result.non_execution_confirmation["cieu_written"] is False
    assert result.non_execution_confirmation["db_read"] is False
    assert result.non_execution_confirmation["brain_or_memory_mutated"] is False
    assert result.non_execution_confirmation["external_system_called"] is False


def test_module_uses_standard_library_only():
    import ystar.governance.contract_dry_run as module

    assert "jsonschema" not in getattr(module, "__dict__", {})
