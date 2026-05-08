from __future__ import annotations

import sqlite3
from pathlib import Path

from ystar.governance.labs_universal_operating_control_contract import (
    required_capabilities_for_operation_context,
    validate_and_write_labs_universal_control_packet,
    validate_labs_universal_control_packet,
)


def _context(**overrides):
    context = {
        "operation_id": "test_strategy_operation",
        "actor": "Aiden",
        "operation_type": "strategic_market_analysis",
        "market_strategy_required": True,
        "provider_tool_boundary": False,
        "codex_prompt_generation": False,
        "external_action_executed": False,
        "provider_action_executed": False,
    }
    context.update(overrides)
    return context


def _packet(context=None, *, drop=(), plan_overrides=None):
    ctx = context or _context()
    required = required_capabilities_for_operation_context(ctx)
    overrides = plan_overrides or {}
    plan = []
    for capability in required:
        row = {
            "capability_id": capability,
            "owner_repo": "bridge-labs" if capability != "Y_star_gov_runtime_validation" else "Y-star-gov",
            "runtime_status": "runtime_active",
            "satisfied": True,
            "satisfied_by": "runtime_invocation",
            "invocation_mode": "runtime_invocation",
            "correct_path": f"satisfy {capability}",
        }
        row.update(overrides.get(capability, {}))
        plan.append(row)
    return {
        "control_plane_id": "labs_universal_operating_control_plane_v1",
        "operation_context": ctx,
        "operation_classification": {
            "operation_type": ctx["operation_type"],
            "risk_tier": "controlled_internal_runtime",
        },
        "required_capabilities": [{"capability_id": item, "mandatory": True} for item in required if item not in drop],
        "capability_invocation_plan": [row for row in plan if row["capability_id"] not in drop],
        "correct_path_navigator": {
            "navigator_id": "test_navigator",
            "steps": [],
        },
        "bypass_prevention": {
            "universal_control_plane_required": True,
            "raw_prompt_or_recent_memory_sufficient": False,
        },
        "truth_constraints": {
            "customer_validation_claim": False,
            "pricing_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "live_provider_execution_claim": False,
        },
    }


def test_strategy_operation_requires_brain_live_scan_competition_and_freshness():
    context = _context()
    required = required_capabilities_for_operation_context(context)

    assert "six_d_brain_provenance" in required
    assert "live_public_read_open_world_scan" in required
    assert "competitive_intelligence_current_sources" in required
    assert "founder_market_fit_and_right_to_win" in required
    assert "latest_source_freshness_policy" in required


def test_valid_strategy_packet_allows():
    decision = validate_labs_universal_control_packet(_packet())

    assert decision.to_dict()["decision"] == "ALLOW"


def test_missing_competitive_intelligence_requires_revision_with_correct_path():
    decision = validate_labs_universal_control_packet(_packet(drop={"competitive_intelligence_current_sources"}))
    data = decision.to_dict()

    assert data["decision"] == "REQUIRE_REVISION"
    assert "competitor" in " ".join(data["correct_path"]).lower()


def test_static_competitor_scan_cannot_satisfy_market_strategy():
    decision = validate_labs_universal_control_packet(
        _packet(
            plan_overrides={
                "competitive_intelligence_current_sources": {
                    "satisfied_by": "static_evidence_map",
                    "invocation_mode": "static_evidence_map",
                }
            }
        )
    )

    assert decision.to_dict()["decision"] == "REQUIRE_REVISION"


def test_codex_prompt_generation_requires_ceo_implementation_order():
    context = _context(
        operation_id="codex_prompt",
        operation_type="codex_executor_handoff",
        market_strategy_required=False,
        codex_prompt_generation=True,
    )
    decision = validate_labs_universal_control_packet(_packet(context, drop={"CEOImplementationOrder"}))

    assert decision.to_dict()["decision"] == "REQUIRE_REVISION"
    assert "CEOImplementationOrder" in " ".join(decision.to_dict()["correct_path"])


def test_external_execution_claim_denies():
    packet = _packet()
    packet["truth_constraints"]["revenue_claim"] = True

    assert validate_labs_universal_control_packet(packet).to_dict()["decision"] == "DENY"


def test_owner_bound_external_action_escalates():
    packet = _packet(_context(owner_bound_external_action_requested=True))

    assert validate_labs_universal_control_packet(packet).to_dict()["decision"] == "ESCALATE"


def test_validate_and_write_records_to_cieustore(tmp_path: Path):
    result = validate_and_write_labs_universal_control_packet(
        _packet(),
        cieu_db=str(tmp_path / "labs_control.db"),
        session_id="labs_control_test",
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    con = sqlite3.connect(tmp_path / "labs_control.db")
    count = con.execute("select count(*) from cieu_events").fetchone()[0]
    con.close()
    assert count == 1
