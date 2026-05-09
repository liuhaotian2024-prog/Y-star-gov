from __future__ import annotations

from ystar.governance.aiden_unknown_problem_learning_protocol_contract import (
    AIDEN_UNKNOWN_PROBLEM_LEARNING_EVENT_TYPE,
    validate_aiden_unknown_problem_learning_protocol,
    validate_and_write_aiden_unknown_problem_learning_protocol,
)


def _valid_packet() -> dict:
    return {
        "problem_context": {
            "problem_id": "unknown_market_or_operating_problem",
            "unknown_problem_statement": "Aiden faces a domain it has not previously modeled.",
            "action_boundary": "learn and plan only; no external action",
        },
        "knowledge_gap_diagnosis": {
            "known_unknowns": ["market structure", "buyer vocabulary", "incumbent alternatives"],
            "confidence_boundary": "must learn before selecting strategy",
        },
        "learning_objectives": [
            {"domain_id": "classical_theory_canon", "objective": "find durable decision models"},
            {"domain_id": "peer_experience_corpus", "objective": "learn founder/operator lessons"},
            {"domain_id": "historical_case_corpus", "objective": "learn success and failure cases"},
            {"domain_id": "current_market_evidence", "objective": "collect dated public market signals"},
            {"domain_id": "internal_capability_recall", "objective": "recall existing labs capabilities"},
            {"domain_id": "customer_contact_residuals", "objective": "prepare owner-gated future feedback learning"},
        ],
        "sensemaking_modes": ["buyer_pain_sense", "system_pressure_sense", "risk_smell", "anomaly_detection"],
        "thinking_modes": [
            "first_principles",
            "systems_thinking",
            "decision_theory",
            "adversarial_critique",
            "causal_zero_loop",
            "customer_empathy",
        ],
        "source_discovery_plan": [
            {"source_type": "brain_recall", "where": "aiden_brain.db"},
            {"source_type": "repo_capability_recall", "where": "E87R baseline and current repo"},
            {"source_type": "public_read_research", "where": "safe public-read provider"},
            {"source_type": "classical_theory", "where": "canonical books/papers"},
            {"source_type": "peer_experience", "where": "founder/operator interviews and playbooks"},
            {"source_type": "historical_case", "where": "success/failure case corpus"},
            {"source_type": "owner_or_L4_feedback_when_approved", "where": "owner-approved feedback only"},
        ],
        "tool_selection": [
            {"tool_id": "brain_activation"},
            {"tool_id": "repo_search"},
            {"tool_id": "public_read_provider"},
            {"tool_id": "Y_star_gov_validator"},
            {"tool_id": "CIEUStore"},
            {"tool_id": "CZL_residual_engine"},
        ],
        "knowledge_graph_methodology": {
            "node_types": ["theory", "case", "tool", "market_fact", "assumption", "residual"],
            "edge_types": ["supports", "contradicts", "generalizes", "falsifies", "requires_tool", "updates_strategy"],
            "content_type_freshness_policy_required": True,
            "production_brain_write_requires_owner_gate": True,
        },
        "governance_plan": {
            "operating_pattern_doctrine_required": True,
            "CIEU_recording_required": True,
        },
        "output_obligations": ["learning dossier", "knowledge graph delta", "CZL residual plan"],
        "truth_constraints": {
            "recent_memory_only": False,
            "external_action_executed": False,
            "customer_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "direct_brain_write_without_owner_gate": False,
            "direct_contract_mutation": False,
        },
    }


def test_valid_unknown_problem_learning_protocol_allows():
    decision = validate_aiden_unknown_problem_learning_protocol(_valid_packet()).to_dict()

    assert decision["decision"] == "ALLOW"
    assert "first_principles" in decision["guidance"]["required_thinking_modes"]


def test_missing_thinking_modes_requires_revision():
    packet = _valid_packet()
    packet["thinking_modes"] = ["first_principles"]

    decision = validate_aiden_unknown_problem_learning_protocol(packet).to_dict()

    assert decision["decision"] == "REQUIRE_REVISION"
    assert decision["failed_section"] == "thinking_modes"


def test_recent_memory_only_denies():
    packet = _valid_packet()
    packet["truth_constraints"]["recent_memory_only"] = True

    decision = validate_aiden_unknown_problem_learning_protocol(packet).to_dict()

    assert decision["decision"] == "DENY"


def test_unknown_problem_learning_cieu_write(tmp_path):
    result = validate_and_write_aiden_unknown_problem_learning_protocol(
        _valid_packet(),
        cieu_db=str(tmp_path / "unknown_learning.db"),
        session_id="e120_unknown_learning_test",
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["event_type"] == AIDEN_UNKNOWN_PROBLEM_LEARNING_EVENT_TYPE
