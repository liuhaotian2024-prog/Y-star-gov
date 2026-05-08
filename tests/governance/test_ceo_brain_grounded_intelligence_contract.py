"""Tests for ceo_brain_grounded_intelligence_contract."""
from __future__ import annotations

import sqlite3

import pytest

from ystar.governance import (
    CEOBrainGroundedDecisionValue,
    CEO_BRAIN_GROUNDED_CIEU_EVENT_TYPE,
    validate_and_write_ceo_brain_grounded_intelligence_packet,
    validate_ceo_brain_grounded_intelligence_packet,
)


def _valid_packet(**overrides):
    """Build a minimal valid brain-grounded packet."""
    packet = {
        "artifact_id": "test_brain_grounded_packet",
        "intelligence_loop_id": "test_loop_001",
        "session_id": "test_session_001",
        "agent_id": "bridge_labs_ceo",
        "owner_intent": "test owner intent",
        "brain_provenance": {
            "brain_db": "/tmp/test_brain.db",
            "total_activations": 100,
            "unique_nodes": 25,
        },
        "stages": [
            {
                "stage_id": "test_stage",
                "input_summary": "input",
                "evidence_refs": ["brain://node_001: Test Wisdom"],
                "output_summary": "[brain-activated] Test Wisdom",
                "brain_activations": [
                    {"node_id": "node_001", "node_name": "Test Wisdom",
                     "file_path": "x.md", "activation_level": 1.5, "hop_distance": 0}
                ],
            }
        ],
        "selected_action": {
            "candidate_id": "c1",
            "description": "test action",
            "route_type": "internal_runtime",
        },
        "owner_approval_state": "not_required",
    }
    packet.update(overrides)
    return packet


# ── Positive path ────────────────────────────────────────────────────────


def test_valid_packet_passes():
    packet = _valid_packet()
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.ALLOW
    assert d.failed_field is None


def test_valid_packet_writes_cieu_record(tmp_path):
    packet = _valid_packet()
    db = tmp_path / "test.db"
    result = validate_and_write_ceo_brain_grounded_intelligence_packet(
        packet, cieu_db=str(db), session_id="test_sess"
    )
    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True

    # Inspect actual record
    c = sqlite3.connect(str(db))
    rows = c.execute("SELECT event_type, agent_id, decision FROM cieu_events").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == CEO_BRAIN_GROUNDED_CIEU_EVENT_TYPE
    assert rows[0][1] == "bridge_labs_ceo"
    assert rows[0][2] == "allow"


# ── Negative path: private chain-of-thought ──────────────────────────────


def test_chain_of_thought_denied():
    packet = _valid_packet(chain_of_thought="secret reasoning")
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.DENY


def test_private_reasoning_denied():
    packet = _valid_packet(private_reasoning="hidden")
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.DENY


# ── Negative path: bypass and overclaim ──────────────────────────────────


def test_bypass_attempt_denied():
    packet = _valid_packet(bypass_attempt=True)
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.DENY


def test_l5_revenue_overclaim_denied():
    packet = _valid_packet()
    packet["selected_action"]["description"] = "L5 revenue loop complete"
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.DENY
    assert "forbidden completion claim" in d.reason


def test_customer_validation_overclaim_denied():
    packet = _valid_packet(overclaim_boundary={"customer_validation_claim": True})
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.DENY


# ── Negative path: brain provenance requirements ─────────────────────────


def test_missing_brain_provenance_revises():
    packet = _valid_packet()
    del packet["brain_provenance"]
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.REQUIRE_REVISION


def test_insufficient_brain_activations_revises():
    packet = _valid_packet()
    packet["brain_provenance"]["total_activations"] = 2
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.REQUIRE_REVISION
    assert "insufficient activations" in d.reason


def test_insufficient_unique_nodes_revises():
    packet = _valid_packet()
    packet["brain_provenance"]["unique_nodes"] = 1
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.REQUIRE_REVISION
    assert "insufficient unique nodes" in d.reason


# ── Negative path: stage requirements ────────────────────────────────────


def test_stage_without_brain_activations_revises():
    packet = _valid_packet()
    packet["stages"][0]["brain_activations"] = []
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.REQUIRE_REVISION
    assert "no brain_activations" in d.reason


def test_stage_evidence_lacks_brain_citation_revises():
    packet = _valid_packet()
    packet["stages"][0]["evidence_refs"] = ["operations/something.md"]
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.REQUIRE_REVISION
    assert "brain://" in d.reason


# ── Negative path: selected action ───────────────────────────────────────


def test_missing_selected_action_revises():
    packet = _valid_packet()
    del packet["selected_action"]
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.REQUIRE_REVISION


def test_empty_selected_action_description_revises():
    packet = _valid_packet()
    packet["selected_action"]["description"] = ""
    d = validate_ceo_brain_grounded_intelligence_packet(packet)
    assert d.decision == CEOBrainGroundedDecisionValue.REQUIRE_REVISION
