from __future__ import annotations

import sqlite3

from ystar.governance.aiden_agent_native_messenger_contract import (
    AIDEN_AGENT_NATIVE_MESSAGE_EVENT_TYPE,
    validate_aiden_agent_native_message_packet,
    validate_and_write_aiden_agent_native_message_packet,
)


def _valid_packet(message_kind: str = "human_to_agent") -> dict:
    return {
        "messenger_session_id": "test_e124_messenger",
        "thread": {
            "thread_id": "thread_owner_aiden",
            "thread_type": "direct",
            "title": "Owner and Aiden governed chat",
        },
        "participants": [
            {"participant_id": "owner", "display_name": "Owner", "participant_type": "human"},
            {"participant_id": "Aiden", "display_name": "Aiden", "participant_type": "agent"},
        ],
        "message": {
            "message_id": "msg_001",
            "created_at": "2026-05-09T12:00:00Z",
            "sender_id": "owner",
            "recipient_ids": ["Aiden"],
            "message_kind": message_kind,
            "human_readable_text": "Aiden, turn this conversation into a governed CEO meeting message.",
            "cieu_five_tuple": {
                "Y_star_t": "Owner intent becomes governed agent-native communication.",
                "X_t": {"current_context": "human asks Aiden inside local messenger"},
                "U_t": {"speech_act": "request", "actor": "owner", "intended_effect": "start governed meeting"},
                "Y_t_plus_1": "Aiden receives a local no-send governed message with CIEU trace.",
                "R_t_plus_1": "pending until Aiden responds",
                "residual_status": "planning_residual_pending",
            },
        },
        "model_orchestration": {
            "model_orchestration_required": True,
            "selected_model_id": "local_gemma4_e4b",
            "raw_prompt_only": False,
        },
        "delivery_boundary": {
            "local_messenger_only": True,
            "no_send_default": True,
            "external_delivery_executed": False,
            "provider_action_executed": False,
        },
        "CIEU_linkage": {
            "CIEU_recording_required": True,
            "target_event_type": AIDEN_AGENT_NATIVE_MESSAGE_EVENT_TYPE,
        },
        "truth_constraints": {
            "raw_natural_language_only_message": False,
            "missing_CIEU_five_tuple_allowed": False,
            "agent_message_without_model_orchestration": False,
            "external_delivery_executed": False,
            "external_agent_live_contact_executed": False,
            "payment_executed": False,
            "USDC_transfer_executed": False,
            "customer_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "K9Audit_write_claim": False,
            "hidden_chain_of_thought_stored": False,
            "CIEU_recording_bypassed": False,
        },
    }


def test_valid_human_to_agent_message_allows():
    decision = validate_aiden_agent_native_message_packet(_valid_packet())
    assert decision.to_dict()["decision"] == "ALLOW"


def test_missing_five_tuple_requires_revision():
    packet = _valid_packet()
    packet["message"]["cieu_five_tuple"].pop("R_t_plus_1")
    decision = validate_aiden_agent_native_message_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "message.cieu_five_tuple"


def test_agent_message_without_model_orchestration_requires_revision():
    packet = _valid_packet("agent_to_human")
    packet["message"]["sender_id"] = "Aiden"
    packet["message"]["recipient_ids"] = ["owner"]
    packet["model_orchestration"]["model_orchestration_required"] = False
    decision = validate_aiden_agent_native_message_packet(packet).to_dict()
    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "model_orchestration"


def test_wallet_payment_execution_denies():
    packet = _valid_packet("wallet_proposal")
    packet["message"]["wallet_proposal"] = {
        "proposal_only": True,
        "payment_executed": True,
        "USDC_transfer_executed": False,
    }
    decision = validate_aiden_agent_native_message_packet(packet).to_dict()
    assert decision["decision"] == "DENY"
    assert "payment_or_USDC_transfer_executed" in decision["violations"]


def test_external_agent_live_participant_escalates():
    packet = _valid_packet("external_agent_proposal")
    packet["participants"].append(
        {
            "participant_id": "external_agent_alpha",
            "display_name": "External Agent Alpha",
            "participant_type": "external_agent",
            "live_external_delivery_allowed": True,
        }
    )
    packet["message"]["recipient_ids"] = ["external_agent_alpha"]
    decision = validate_aiden_agent_native_message_packet(packet).to_dict()
    assert decision["decision"] == "ESCALATE"
    assert decision["guidance"]["requires_owner_decision"] is True


def test_write_cieustore_record(tmp_path):
    db = tmp_path / "e124_messages.db"
    result = validate_and_write_aiden_agent_native_message_packet(_valid_packet(), cieu_db=str(db))
    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT event_type, passed FROM cieu_events").fetchall()
    assert rows == [(AIDEN_AGENT_NATIVE_MESSAGE_EVENT_TYPE, 1)]
