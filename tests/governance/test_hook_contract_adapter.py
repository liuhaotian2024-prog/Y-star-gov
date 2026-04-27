from copy import deepcopy

from ystar.governance.hook_contract_adapter import (
    HookAdapterDecision,
    run_hook_contract_dry_run,
)


def valid_envelope():
    return {
        "hook_event_id": "hook-1",
        "agent_id": "Aiden-CEO",
        "packet_id": "preu-1",
        "risk_tier": "normal",
        "declared_Y_star": {"summary": "ship hook contract dry-run adapter safely"},
        "Xt": {"summary": "governance dry-run harness exists"},
        "m_functor": {"summary": "align hook boundary with governance checks"},
        "candidate_U": [
            {
                "id": "u1",
                "action_type": "write_file",
                "description": "add hook adapter dry-run docs and tests",
                "predicted_Yt_plus_1": "adapter exists with tests",
                "predicted_Rt_plus_1": {"summary": "residual reduced"},
            }
        ],
        "selected_U_id": "u1",
        "why_min_residual": "u1 models the future hook boundary without runtime execution",
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
    }


def unsafe_mock_outcome():
    return {
        "event_id": "delta-unsafe",
        "recorded_at": "2026-04-27T00:00:00Z",
        "actual_y_t1": "adapter exists",
        "actual_r_t1": {"summary": "residual reduced"},
        "delta_summary": "unsafe writeback policy was requested",
        "residual_delta": {"direction": "reduced"},
        "delta_class": "matched",
        "learning_eligibility": {"eligible": True, "requires_curation": False},
        "cieu_event_ref": "dry-run://not-runtime-cieu",
        "validator_result_ref": "dry-run://validator/preu-1",
        "brain_writeback_policy": {
            "automatic_direct_writeback": True,
            "requires_curation": False,
        },
    }


def test_valid_envelope_returns_allow_execution_true():
    result = run_hook_contract_dry_run(valid_envelope())

    assert result.decision == HookAdapterDecision.ALLOW
    assert result.hook_decision_envelope["allow_execution"] is True
    assert result.hook_decision_envelope["dry_run_only"] is True
    assert result.dry_run_result is not None


def test_missing_declared_y_star_returns_require_revision_before_dry_run():
    envelope = valid_envelope()
    envelope.pop("declared_Y_star")

    result = run_hook_contract_dry_run(envelope)

    assert result.decision == HookAdapterDecision.REQUIRE_REVISION
    assert result.dry_run_result is None
    assert result.hook_decision_envelope["require_revision"] is True


def test_selected_u_id_mismatch_returns_require_revision():
    envelope = valid_envelope()
    envelope["selected_U_id"] = "missing"

    result = run_hook_contract_dry_run(envelope)

    assert result.decision == HookAdapterDecision.REQUIRE_REVISION
    assert result.hook_decision_envelope["allow_execution"] is False
    assert result.dry_run_result is not None


def test_high_risk_envelope_escalates():
    envelope = valid_envelope()
    envelope["risk_tier"] = 3
    envelope["governance_expectations"]["requires_high_risk_review"] = True

    result = run_hook_contract_dry_run(envelope)

    assert result.decision == HookAdapterDecision.ESCALATE
    assert result.hook_decision_envelope["escalate"] is True
    assert result.hook_decision_envelope["allow_execution"] is False


def test_unsafe_mock_outcome_denies():
    envelope = valid_envelope()
    envelope["mock_outcome"] = unsafe_mock_outcome()

    result = run_hook_contract_dry_run(envelope)

    assert result.decision == HookAdapterDecision.DENY
    assert result.hook_decision_envelope["deny"] is True
    assert result.hook_decision_envelope["allow_execution"] is False


def test_output_always_includes_dry_run_and_non_execution_flags():
    result = run_hook_contract_dry_run(valid_envelope())

    assert result.hook_decision_envelope["dry_run_only"] is True
    assert result.hook_decision_envelope["non_execution_confirmation"] is True


def test_adapter_does_not_mutate_input_envelope():
    envelope = valid_envelope()
    original = deepcopy(envelope)

    run_hook_contract_dry_run(envelope)

    assert envelope == original


def test_module_uses_standard_library_only():
    import ystar.governance.hook_contract_adapter as module

    assert "jsonschema" not in getattr(module, "__dict__", {})
