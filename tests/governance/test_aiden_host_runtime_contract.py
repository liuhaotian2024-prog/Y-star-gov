from __future__ import annotations

from pathlib import Path

from ystar.governance.aiden_host_runtime_contract import (
    REQUIRED_AUTONOMY_TIERS,
    REQUIRED_CAPABILITY_IDS,
    validate_aiden_host_runtime_cycle,
    validate_and_write_aiden_host_runtime_cycle,
)


def _valid_packet() -> dict:
    return {
        "host_runtime_id": "aiden_host_ceo_operating_daemon_v1",
        "session_id": "test_aiden_host_runtime",
        "mission_anchor": {
            "must_optimize_for": [
                "autonomous_value_discovery",
                "governed_value_creation",
                "residual_learning",
            ],
        },
        "first_principles_operating_model": {
            "principles": [
                "market pull before internal convenience",
                "safety enables autonomy",
                "Codex executes CEO orders only",
            ],
        },
        "existing_capability_orchestration_map": {
            "capabilities": [{"capability_id": item} for item in REQUIRED_CAPABILITY_IDS],
        },
        "autonomy_policy": {
            "tiers": [{"tier_id": item} for item in REQUIRED_AUTONOMY_TIERS],
        },
        "universal_control_gate": {
            "Y_star_gov_universal_control_decision": "ALLOW",
            "runtime_may_continue": True,
        },
        "value_discovery_cycle": {
            "market_strategy_decision": "ALLOW",
            "open_world_scan_performed": True,
            "selected_value_target": "AI security compliance first-cash pack",
        },
        "CEO_implementation_order": {
            "artifact_id": "CEOImplementationOrder",
            "order_id": "test_order",
            "executor_actor": "Codex",
        },
        "next_action_recommendation": {
            "action_id": "test_internal_codex_order",
            "route_type": "codex_executor_order",
            "autonomy_tier": "codex_executor_order_required",
            "external_action_candidate": False,
            "payment_related": False,
            "live_provider_execution_requested": False,
        },
        "truth_constraints": {
            "external_action_executed": False,
            "provider_action_executed": False,
            "customer_validation_claim": False,
            "pricing_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "paid_signal_claim": False,
            "L4_feedback_executed": False,
            "L5_revenue_loop_complete": False,
            "K9Audit_integration_claim": False,
            "live_provider_execution_claim": False,
        },
    }


def test_valid_host_runtime_cycle_allows() -> None:
    decision = validate_aiden_host_runtime_cycle(_valid_packet()).to_dict()
    assert decision["decision"] == "ALLOW"
    assert decision["navigation"]["codex_requires_CEOImplementationOrder"] is True


def test_missing_capability_requires_revision_with_correct_path() -> None:
    packet = _valid_packet()
    packet["existing_capability_orchestration_map"]["capabilities"] = [
        {"capability_id": "E110_labs_universal_operating_control_plane"}
    ]
    decision = validate_aiden_host_runtime_cycle(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert "wire" in " ".join(decision["correct_path"]) or "run" in " ".join(decision["correct_path"])


def test_external_action_without_owner_gate_escalates() -> None:
    packet = _valid_packet()
    packet["next_action_recommendation"].update(
        {
            "route_type": "owner_feedback",
            "external_action_candidate": True,
            "autonomy_tier": "autonomous_internal_low_risk",
        }
    )
    decision = validate_aiden_host_runtime_cycle(packet).to_dict()
    assert decision["decision"] == "ESCALATE"
    assert decision["requires_owner_decision"] is True


def test_payment_or_live_provider_execution_is_denied() -> None:
    packet = _valid_packet()
    packet["next_action_recommendation"]["payment_related"] = True
    decision = validate_aiden_host_runtime_cycle(packet).to_dict()
    assert decision["decision"] == "DENY"


def test_writes_cieustore_record(tmp_path: Path) -> None:
    db = tmp_path / "host_runtime.db"
    result = validate_and_write_aiden_host_runtime_cycle(
        _valid_packet(),
        cieu_db=str(db),
        session_id="test_aiden_host_runtime",
    )
    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["event_type"] == "AIDEN_HOST_RUNTIME_CYCLE_DECISION"
