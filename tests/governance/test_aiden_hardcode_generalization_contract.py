from __future__ import annotations

from ystar.governance.aiden_hardcode_generalization_contract import (
    AIDEN_HARDCODE_GENERALIZATION_EVENT_TYPE,
    build_aiden_hardcode_generalization_cieu_record,
    validate_aiden_hardcode_generalization_packet,
)


def _valid_packet() -> dict:
    return {
        "action_context": {"action_id": "owner_answer::x", "action_type": "owner_readback", "test_mode": False},
        "owner_input": {"text": "Aiden，请推进这个战略问题。"},
        "owner_facing_answer": {
            "text": "我的判断：先转成行动包。",
            "language": "zh",
            "owner_readable": True,
            "content_judgment_first": True,
            "raw_machine_receipt_rendered_to_owner": False,
            "process_first": False,
        },
        "runtime_proof": {
            "runtime_path": "office/aiden_meeting_room/aiden_response_engine.py",
            "generation_mode": "runtime_generated_structured_output",
            "static_template_used": False,
        },
        "hardcode_audit": {
            "scan_id": "e144",
            "runtime_active_issue_specific_literals": [],
            "machine_receipt_leakage": False,
        },
        "generalization_proof": {
            "class_of_issue": "point_fix_without_generalization",
            "sibling_variants": [
                "machine_receipt_as_owner_answer",
                "static_route_as_strategy",
                "keyword_branch_as_understanding",
            ],
            "class_level_fix": "require feature extraction, evidence retrieval, and owner-facing answer integrity gate",
        },
    }


def test_valid_packet_allows():
    decision = validate_aiden_hardcode_generalization_packet(_valid_packet()).to_dict()
    assert decision["decision"] == "ALLOW"


def test_machine_receipt_requires_revision():
    packet = _valid_packet()
    packet["owner_facing_answer"]["raw_machine_receipt_rendered_to_owner"] = True
    decision = validate_aiden_hardcode_generalization_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "owner_facing_answer"


def test_static_template_requires_revision_in_non_test_runtime():
    packet = _valid_packet()
    packet["runtime_proof"]["static_template_used"] = True
    decision = validate_aiden_hardcode_generalization_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "runtime_proof"


def test_point_fix_only_requires_class_level_fix():
    packet = _valid_packet()
    packet["generalization_proof"]["point_fix_only"] = True
    decision = validate_aiden_hardcode_generalization_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert "point-fix-only" in decision["reason"]


def test_issue_specific_runtime_literal_requires_revision():
    packet = _valid_packet()
    packet["hardcode_audit"]["runtime_active_issue_specific_literals"] = ["x402 hardcoded route"]
    decision = validate_aiden_hardcode_generalization_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "hardcode_audit"


def test_false_revenue_claim_denies():
    packet = _valid_packet()
    packet["revenue_claim"] = True
    decision = validate_aiden_hardcode_generalization_packet(packet).to_dict()
    assert decision["decision"] == "DENY"


def test_cieu_record_uses_expected_event_type():
    decision = validate_aiden_hardcode_generalization_packet(_valid_packet())
    record = build_aiden_hardcode_generalization_cieu_record(_valid_packet(), decision)
    assert record["event_type"] == AIDEN_HARDCODE_GENERALIZATION_EVENT_TYPE
    assert record["cieu_tuple"]["R_plus_1"] == 0.0
