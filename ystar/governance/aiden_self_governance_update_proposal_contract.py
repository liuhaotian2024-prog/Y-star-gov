"""Governed Aiden self-governance update proposals.

Aiden may learn that a class of failures should become a future runtime rule,
but it must not directly mutate Y-star-gov contracts. This contract validates
proposal packets, writes CIEU evidence, and routes approved-looking proposals
to owner review rather than enforcement.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class AidenSelfGovernanceProposalDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class AidenSelfGovernanceProposalDecision:
    decision: AidenSelfGovernanceProposalDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    requires_owner_decision: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "aiden_self_governance_update_proposal_decision",
            "decision": self.decision.value,
            "passed": self.decision == AidenSelfGovernanceProposalDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "guidance": dict(self.guidance),
            "requires_owner_decision": self.requires_owner_decision,
        }


AIDEN_SELF_GOVERNANCE_UPDATE_PROPOSAL_EVENT_TYPE = "AIDEN_SELF_GOVERNANCE_UPDATE_PROPOSAL_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_PROPOSAL_FIELDS = (
    "proposal_id",
    "source_residual",
    "class_of_issue",
    "observed_point_failures",
    "extrapolation_to_other_cases",
    "current_contract_refs",
    "proposed_contract_amendment",
    "owner_review_policy",
    "implementation_plan",
    "tests_required",
    "operating_pattern_doctrine_updates",
    "CIEU_linkage",
    "truth_constraints",
)

FORBIDDEN_TRUE_CLAIMS = (
    "direct_contract_write_attempted",
    "contract_patch_applied",
    "external_action_executed",
    "provider_action_executed",
    "customer_validation_claim",
    "pricing_validation_claim",
    "revenue_claim",
    "payment_claim",
    "paid_signal_claim",
    "K9Audit_integration_claim",
    "live_provider_execution_claim",
)


def build_aiden_self_governance_update_proposal_contract() -> dict[str, Any]:
    return {
        "contract_id": "aiden_self_governance_update_proposal_contract_v1",
        "event_type": AIDEN_SELF_GOVERNANCE_UPDATE_PROPOSAL_EVENT_TYPE,
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "required_fields": list(REQUIRED_PROPOSAL_FIELDS),
        "proposal_scope": "owner_visible_proposal_only_no_direct_contract_mutation",
    }


def validate_aiden_self_governance_update_proposal(
    proposal: Mapping[str, Any],
) -> AidenSelfGovernanceProposalDecision:
    if not isinstance(proposal, Mapping):
        return _deny("self-governance proposal must be a mapping", "schema", ["proposal_not_mapping"])

    missing = [field for field in REQUIRED_PROPOSAL_FIELDS if field not in proposal]
    if missing:
        return _revision("self-governance proposal is missing required fields", "schema", [f"add {field}" for field in missing])

    forbidden = _forbidden_claim(proposal)
    if forbidden:
        return _deny(f"Aiden may not directly apply governance or overclaim: {forbidden}", "truth_constraints", [forbidden])

    class_issue = proposal.get("class_of_issue") if isinstance(proposal.get("class_of_issue"), Mapping) else {}
    if not class_issue.get("issue_class_id") or not class_issue.get("description") or not class_issue.get("generalization_boundary"):
        return _revision(
            "proposal must identify the issue class, not only a point failure",
            "class_of_issue",
            ["add issue_class_id, description, and generalization_boundary"],
        )

    failures = _as_list(proposal.get("observed_point_failures"))
    if len(failures) < 2:
        return _revision(
            "proposal needs at least two observed point failures or audit examples",
            "observed_point_failures",
            ["attach multiple observed failures before proposing a class-level rule"],
        )

    extrapolated = _as_list(proposal.get("extrapolation_to_other_cases"))
    if len(extrapolated) < 3:
        return _revision(
            "proposal must extrapolate to at least three future same-class cases",
            "extrapolation_to_other_cases",
            ["list three variants and a preventive rule for each"],
        )
    for case in extrapolated:
        if not isinstance(case, Mapping) or not case.get("case_id") or not case.get("why_same_class") or not case.get("preventive_rule"):
            return _revision(
                "each extrapolated case needs case_id, why_same_class, and preventive_rule",
                "extrapolation_to_other_cases",
                ["complete class-level extrapolation rows"],
            )

    amendment = proposal.get("proposed_contract_amendment") if isinstance(proposal.get("proposed_contract_amendment"), Mapping) else {}
    if not amendment.get("target_contract") or not amendment.get("proposed_rule") or not amendment.get("correct_path_navigation"):
        return _revision(
            "proposal needs target contract, proposed rule, and correct-path navigation",
            "proposed_contract_amendment",
            ["describe the owner-reviewable contract amendment without applying it"],
        )
    if amendment.get("auto_apply") is True:
        return _deny("self-governance proposals may not auto-apply contract amendments", "proposed_contract_amendment", ["auto_apply_true"])

    owner_policy = proposal.get("owner_review_policy") if isinstance(proposal.get("owner_review_policy"), Mapping) else {}
    if owner_policy.get("owner_explicit_approval_required") is not True:
        return _revision(
            "owner explicit approval is required before any governance amendment",
            "owner_review_policy",
            ["set owner_explicit_approval_required=true"],
        )

    if len(_as_list(proposal.get("tests_required"))) < 2:
        return _revision("proposal needs tests for the proposed governance change", "tests_required", ["add at least two tests"])

    patterns = proposal.get("operating_pattern_doctrine_updates") if isinstance(proposal.get("operating_pattern_doctrine_updates"), Mapping) else {}
    mechanized = _as_list(patterns.get("patterns_mechanized"))
    if patterns.get("status") != "mechanized_as_runtime_obligations" or len(mechanized) < 10:
        return _revision(
            "self-governance proposal must mechanize reusable success patterns, not only one-off repairs",
            "operating_pattern_doctrine_updates",
            ["add operating pattern registry updates and at least ten mechanized reusable patterns"],
        )
    required_patterns = {
        "no_new_wheel_preflight",
        "class_level_extrapolation_gate",
        "correct_path_navigation",
        "CEOImplementationOrder_before_Codex_prompt",
        "production_brain_write_owner_backup_gate",
    }
    missing_patterns = sorted(required_patterns - set(mechanized))
    if missing_patterns:
        return _revision(
            "core reusable operating patterns are missing from the mechanization plan",
            "operating_pattern_doctrine_updates",
            [f"mechanize {pattern_id}" for pattern_id in missing_patterns],
        )

    linkage = proposal.get("CIEU_linkage") if isinstance(proposal.get("CIEU_linkage"), Mapping) else {}
    if linkage.get("target_event_type") != AIDEN_SELF_GOVERNANCE_UPDATE_PROPOSAL_EVENT_TYPE:
        return _revision(
            "self-governance proposal must target its formal CIEU event",
            "CIEU_linkage",
            [f"set target_event_type={AIDEN_SELF_GOVERNANCE_UPDATE_PROPOSAL_EVENT_TYPE}"],
        )
    if linkage.get("formal_CIEU_log_path") != FORMAL_CIEU_LOG_PATH:
        return _revision("proposal must use CIEUStore.write_dict", "CIEU_linkage", ["use ystar.governance.cieu_store.CIEUStore.write_dict"])

    return AidenSelfGovernanceProposalDecision(
        decision=AidenSelfGovernanceProposalDecisionValue.ALLOW,
        reason="self-governance update proposal is valid for owner review; no contract mutation is authorized",
        correct_path=[
            "write proposal CIEU record",
            "write owner-visible pending proposal artifact",
            "wait for owner approval before generating any contract patch",
        ],
        guidance={"next_allowed_action": "owner_review_pending_proposal_only"},
        requires_owner_decision=True,
    )


def build_aiden_self_governance_update_proposal_cieu_record(
    proposal: Mapping[str, Any],
    decision: AidenSelfGovernanceProposalDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, AidenSelfGovernanceProposalDecision) else dict(decision)
    class_issue = proposal.get("class_of_issue") if isinstance(proposal.get("class_of_issue"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(proposal.get("proposal_id") or "aiden_self_governance_update_proposal"),
        "agent_id": "Aiden",
        "event_type": AIDEN_SELF_GOVERNANCE_UPDATE_PROPOSAL_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "Aiden self-governance update proposal validation",
        "contract_hash": "aiden-self-governance-update-proposal-v1",
        "params": {
            "proposal_id": proposal.get("proposal_id"),
            "issue_class_id": class_issue.get("issue_class_id"),
            "target_contract": (proposal.get("proposed_contract_amendment") or {}).get("target_contract") if isinstance(proposal.get("proposed_contract_amendment"), Mapping) else None,
        },
        "result": {
            "decision": data.get("decision"),
            "reason": data.get("reason"),
            "correct_path": list(data.get("correct_path") or []),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore", "owner-review"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": data.get("decision") == "ALLOW",
    }


def write_aiden_self_governance_update_proposal_cieu_record(
    proposal: Mapping[str, Any],
    decision: AidenSelfGovernanceProposalDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    record = build_aiden_self_governance_update_proposal_cieu_record(proposal, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "aiden_self_governance_update_proposal_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_aiden_self_governance_update_proposal(
    proposal: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_aiden_self_governance_update_proposal(proposal)
    write_result = write_aiden_self_governance_update_proposal_cieu_record(
        proposal,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "aiden_self_governance_update_proposal_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> AidenSelfGovernanceProposalDecision:
    path = ["repair self-governance proposal before owner review", *correct_path]
    return AidenSelfGovernanceProposalDecision(
        decision=AidenSelfGovernanceProposalDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=failed_section,
        correct_path=path,
        guidance={"decision_mode": "correct_path_navigation", "next_allowed_action": "repair_proposal_only"},
    )


def _deny(reason: str, failed_section: str, violations: list[str]) -> AidenSelfGovernanceProposalDecision:
    return AidenSelfGovernanceProposalDecision(
        decision=AidenSelfGovernanceProposalDecisionValue.DENY,
        reason=reason,
        failed_section=failed_section,
        violations=violations,
        correct_path=["block proposal", "remove direct mutation or false claim", "resubmit as owner-visible proposal only"],
        guidance={"decision_mode": "hard_stop", "next_allowed_action": "none_until_repaired"},
    )


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _forbidden_claim(proposal: Mapping[str, Any]) -> str | None:
    truth = proposal.get("truth_constraints") if isinstance(proposal.get("truth_constraints"), Mapping) else {}
    for key in FORBIDDEN_TRUE_CLAIMS:
        if truth.get(key) is True:
            return key
    amendment = proposal.get("proposed_contract_amendment") if isinstance(proposal.get("proposed_contract_amendment"), Mapping) else {}
    if amendment.get("auto_apply") is True:
        return "auto_apply"
    return None


__all__ = [
    "AIDEN_SELF_GOVERNANCE_UPDATE_PROPOSAL_EVENT_TYPE",
    "AidenSelfGovernanceProposalDecision",
    "AidenSelfGovernanceProposalDecisionValue",
    "build_aiden_self_governance_update_proposal_contract",
    "build_aiden_self_governance_update_proposal_cieu_record",
    "validate_aiden_self_governance_update_proposal",
    "validate_and_write_aiden_self_governance_update_proposal",
    "write_aiden_self_governance_update_proposal_cieu_record",
]
