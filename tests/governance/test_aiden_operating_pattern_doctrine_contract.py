from __future__ import annotations

from ystar.governance.aiden_operating_pattern_doctrine_contract import (
    AIDEN_OPERATING_PATTERN_DOCTRINE_EVENT_TYPE,
    expected_patterns_for_action_context,
    validate_aiden_operating_pattern_invocation,
    validate_and_write_aiden_operating_pattern_invocation,
)


def _valid_packet() -> dict:
    context = {
        "action_id": "e119_operating_pattern_test",
        "action_type": "market_strategy_plus_brain_learning",
        "market_strategy_required": True,
        "codex_execution_required": True,
        "brain_write_related": True,
        "external_action_related": True,
        "self_governance_related": True,
    }
    invocations = [
        {
            "pattern_id": pattern_id,
            "invocation_status": "invoked",
            "output_summary": f"{pattern_id} was applied before action execution.",
            "evidence_refs": [f"test://{pattern_id}"],
            "runtime_governance_required": True,
        }
        for pattern_id in sorted(expected_patterns_for_action_context(context))
    ]
    return {
        "action_context": context,
        "pattern_invocations": invocations,
        "truth_constraints": {
            "recent_memory_only": False,
            "skipped_no_new_wheel": False,
            "raw_codex_prompt_without_order": False,
            "static_template_used_for_live_strategy": False,
            "direct_contract_mutation": False,
            "external_action_executed_without_owner_approval": False,
            "customer_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "K9Audit_integration_claim": False,
        },
    }


def test_valid_operating_pattern_packet_allows():
    decision = validate_aiden_operating_pattern_invocation(_valid_packet()).to_dict()

    assert decision["decision"] == "ALLOW"
    assert "no_new_wheel_preflight" in decision["guidance"]["expected_patterns"]
    assert "class_level_extrapolation_gate" in decision["guidance"]["expected_patterns"]


def test_missing_required_pattern_requires_revision():
    packet = _valid_packet()
    packet["pattern_invocations"] = [
        item for item in packet["pattern_invocations"] if item["pattern_id"] != "no_new_wheel_preflight"
    ]

    decision = validate_aiden_operating_pattern_invocation(packet).to_dict()

    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "pattern_invocations"
    assert any("no_new_wheel_preflight" in step for step in decision["correct_path"])


def test_raw_codex_prompt_without_order_denies():
    packet = _valid_packet()
    packet["truth_constraints"]["raw_codex_prompt_without_order"] = True

    decision = validate_aiden_operating_pattern_invocation(packet).to_dict()

    assert decision["decision"] == "DENY"
    assert decision["failed_section"] == "truth_constraints"


def test_operating_pattern_cieu_write(tmp_path):
    result = validate_and_write_aiden_operating_pattern_invocation(
        _valid_packet(),
        cieu_db=str(tmp_path / "patterns.db"),
        session_id="e119_operating_pattern_test",
        seal_session=False,
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["event_type"] == AIDEN_OPERATING_PATTERN_DOCTRINE_EVENT_TYPE
