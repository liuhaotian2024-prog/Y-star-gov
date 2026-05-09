from __future__ import annotations

import sqlite3

from ystar.governance.aiden_self_governance_update_proposal_contract import (
    AIDEN_SELF_GOVERNANCE_UPDATE_PROPOSAL_EVENT_TYPE,
    AidenSelfGovernanceProposalDecisionValue,
    validate_aiden_self_governance_update_proposal,
    validate_and_write_aiden_self_governance_update_proposal,
)


def _valid_proposal() -> dict:
    return {
        "proposal_id": "e119_self_governance_proposal_point_fix_generalization",
        "source_residual": {
            "residual_id": "e119_point_fix_audit_loop_residual",
            "CZL_R_t_plus_1": 1.0,
            "learning_update": "point fixes need class-level extrapolation",
        },
        "class_of_issue": {
            "issue_class_id": "point_fix_without_generalization",
            "description": "the system patches named audit findings but fails to prevent same-class variants",
            "generalization_boundary": "strategy, learning, production brain write, and governance proposal flows",
        },
        "observed_point_failures": [
            {"failure_id": "homepage_public_signal_date", "evidence_ref": "E118 audit"},
            {"failure_id": "reused_dimension_evidence", "evidence_ref": "E117 audit"},
        ],
        "extrapolation_to_other_cases": [
            {
                "case_id": "single_source_learning_fact",
                "why_same_class": "field presence can hide weak corroboration",
                "preventive_rule": "require source-quality and corroboration semantics",
            },
            {
                "case_id": "owner_approval_boolean",
                "why_same_class": "boolean presence can hide missing owner-visible decision",
                "preventive_rule": "require explicit owner-visible preflight artifact",
            },
            {
                "case_id": "internal_right_to_win_claim",
                "why_same_class": "internal capability can masquerade as buyer-visible value",
                "preventive_rule": "require buyer-visible proof",
            },
        ],
        "current_contract_refs": [
            "ystar/governance/ceo_deep_strategic_intelligence_contract.py",
            "ystar/governance/aiden_idle_learning_contract.py",
        ],
        "proposed_contract_amendment": {
            "target_contract": "cross_runtime_extrapolation_gate",
            "proposed_rule": "major Aiden learning and strategy outputs must include class_of_issue, extrapolation_to_other_cases, and proposed_class_level_fix",
            "correct_path_navigation": "rerun with issue-class generalization before proceeding",
            "auto_apply": False,
        },
        "owner_review_policy": {
            "owner_explicit_approval_required": True,
            "proposal_only_until_approved": True,
        },
        "implementation_plan": [
            "validate proposal",
            "write CIEU record",
            "write pending owner-visible proposal artifact",
        ],
        "tests_required": [
            "missing extrapolation gate requires revision",
            "direct contract write attempt denies",
        ],
        "operating_pattern_doctrine_updates": {
            "status": "mechanized_as_runtime_obligations",
            "patterns_mechanized": [
                "full_repo_and_baseline_first",
                "no_new_wheel_preflight",
                "capability_utilization_sweep",
                "class_level_extrapolation_gate",
                "correct_path_navigation",
                "evidence_quality_and_freshness_gate",
                "regression_test_and_cieu_closure",
                "brain_provenance_required",
                "competitive_landscape_current_signal",
                "buyer_visible_value_translation",
                "residual_truth_scope_split",
                "CEOImplementationOrder_before_Codex_prompt",
                "CodexExecutionReceipt_return_path",
                "production_brain_write_owner_backup_gate",
                "learning_quality_scoring_v2",
            ],
        },
        "CIEU_linkage": {
            "target_event_type": AIDEN_SELF_GOVERNANCE_UPDATE_PROPOSAL_EVENT_TYPE,
            "formal_CIEU_log_path": "ystar.governance.cieu_store.CIEUStore.write_dict",
        },
        "truth_constraints": {
            "direct_contract_write_attempted": False,
            "contract_patch_applied": False,
            "external_action_executed": False,
            "customer_validation_claim": False,
            "revenue_claim": False,
            "payment_claim": False,
            "K9Audit_integration_claim": False,
            "live_provider_execution_claim": False,
        },
    }


def test_valid_self_governance_proposal_allows_for_owner_review():
    decision = validate_aiden_self_governance_update_proposal(_valid_proposal())

    assert decision.decision == AidenSelfGovernanceProposalDecisionValue.ALLOW
    assert decision.requires_owner_decision is True


def test_missing_extrapolation_requires_revision():
    proposal = _valid_proposal()
    proposal["extrapolation_to_other_cases"] = proposal["extrapolation_to_other_cases"][:1]

    decision = validate_aiden_self_governance_update_proposal(proposal)

    assert decision.decision == AidenSelfGovernanceProposalDecisionValue.REQUIRE_REVISION
    assert decision.failed_section == "extrapolation_to_other_cases"


def test_direct_contract_write_attempt_denies():
    proposal = _valid_proposal()
    proposal["truth_constraints"]["direct_contract_write_attempted"] = True

    decision = validate_aiden_self_governance_update_proposal(proposal)

    assert decision.decision == AidenSelfGovernanceProposalDecisionValue.DENY


def test_auto_apply_amendment_denies():
    proposal = _valid_proposal()
    proposal["proposed_contract_amendment"]["auto_apply"] = True

    decision = validate_aiden_self_governance_update_proposal(proposal)

    assert decision.decision == AidenSelfGovernanceProposalDecisionValue.DENY


def test_write_self_governance_proposal_cieustore_record(tmp_path):
    db = tmp_path / "self_governance.db"
    result = validate_and_write_aiden_self_governance_update_proposal(
        _valid_proposal(),
        cieu_db=str(db),
        session_id="e119_self_governance_test",
    )

    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT event_type, decision FROM cieu_events").fetchone()
    assert row == (AIDEN_SELF_GOVERNANCE_UPDATE_PROPOSAL_EVENT_TYPE, "ALLOW")
