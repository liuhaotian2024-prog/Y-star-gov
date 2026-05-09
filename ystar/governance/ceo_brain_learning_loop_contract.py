"""Governance contract for CIEU-backed CEO brain learning.

The contract deliberately keeps production brain mutation behind a governed
candidate path. New market facts, competitor evidence, and failure residuals
may become durable learning only after freshness filtering, CIEU recording, and
explicit write policy validation.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class CEOBrainLearningDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOBrainLearningDecision:
    decision: CEOBrainLearningDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    navigation: dict[str, Any] = field(default_factory=dict)
    requires_owner_decision: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_brain_learning_loop_governance_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOBrainLearningDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "navigation": dict(self.navigation),
            "requires_owner_decision": self.requires_owner_decision,
        }


CEO_BRAIN_LEARNING_LOOP_CIEU_EVENT_TYPE = "CEO_BRAIN_LEARNING_LOOP_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_PACKET_FIELDS = (
    "learning_loop_id",
    "source_runtime",
    "source_strategy_session_id",
    "freshness_policy",
    "evidence_freshness_report",
    "accepted_evidence_items",
    "rejected_evidence_items",
    "brain_mutation_candidates",
    "failure_residual_candidates",
    "brain_write_policy",
    "CIEU_linkage",
    "truth_constraints",
)

ALLOWED_ACCEPTED_STATUSES = {
    "accepted_current",
    "accepted_recent",
    "accepted_evergreen_context",
    "accepted_test_fixture_current",
}

FORBIDDEN_TRUE_CLAIMS = (
    "customer_validation_claim",
    "pricing_validation_claim",
    "revenue_claim",
    "payment_claim",
    "paid_signal_claim",
    "L4_feedback_executed",
    "L5_revenue_loop_complete",
    "K9Audit_integration_claim",
    "live_provider_execution_claim",
)


def build_ceo_brain_learning_loop_contract() -> dict[str, Any]:
    return {
        "contract_id": "ceo_brain_learning_loop_contract_v1",
        "event_type": CEO_BRAIN_LEARNING_LOOP_CIEU_EVENT_TYPE,
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "required_packet_fields": list(REQUIRED_PACKET_FIELDS),
        "governance_style": "freshness_filtered_CIEU_backed_candidate_learning",
        "production_brain_write_default": False,
    }


def validate_ceo_brain_learning_packet(packet: Mapping[str, Any]) -> CEOBrainLearningDecision:
    if not isinstance(packet, Mapping):
        return _deny("brain learning packet must be a mapping", "schema", ["packet_not_mapping"])

    missing_fields = [field for field in REQUIRED_PACKET_FIELDS if not _present(packet.get(field))]
    if missing_fields:
        return _revision(
            "brain learning packet is missing required sections",
            "schema",
            [f"add {field}" for field in missing_fields],
        )

    forbidden = _forbidden_claim(packet)
    if forbidden:
        return _deny(f"forbidden truth claim present: {forbidden}", "truth_constraints", [forbidden])

    policy = packet.get("brain_write_policy") if isinstance(packet.get("brain_write_policy"), Mapping) else {}
    if policy.get("automatic_direct_writeback") is True:
        return _deny(
            "automatic direct brain writeback is forbidden; route through CIEU-backed candidates first",
            "brain_write_policy",
            ["automatic_direct_writeback_true"],
        )
    if packet.get("production_brain_write_requested") is True or policy.get("production_brain_write_requested") is True:
        return _escalate(
            "production brain mutation requires an explicit owner-approved write boundary",
            "brain_write_policy",
            [
                "keep write_mode=CIEU_backed_candidate_only",
                "prepare owner decision packet before production brain mutation",
                "prove CIEU record and freshness filter before any write",
            ],
        )
    if policy.get("production_brain_write_performed") is True:
        return _deny(
            "production brain write was performed before governance approval",
            "brain_write_policy",
            ["production_brain_write_performed_without_approval"],
        )

    freshness = packet.get("evidence_freshness_report") if isinstance(packet.get("evidence_freshness_report"), Mapping) else {}
    if freshness.get("freshness_filter_applied") is not True:
        return _revision(
            "freshness filter must run before evidence can become brain learning",
            "evidence_freshness_report",
            ["run source-date/observed-date freshness filter", "reject stale or undated market evidence"],
        )
    if freshness.get("stale_evidence_used_for_brain_candidate") is True:
        return _deny(
            "stale evidence was used for a brain learning candidate",
            "evidence_freshness_report",
            ["stale_evidence_used_for_brain_candidate"],
        )

    accepted = packet.get("accepted_evidence_items")
    rejected = packet.get("rejected_evidence_items")
    candidates = packet.get("brain_mutation_candidates")
    residuals = packet.get("failure_residual_candidates")
    if not isinstance(accepted, list) or not isinstance(rejected, list) or not isinstance(candidates, list) or not isinstance(residuals, list):
        return _revision(
            "accepted/rejected evidence, brain candidates, and residual candidates must be lists",
            "schema",
            ["represent accepted_evidence_items, rejected_evidence_items, brain_mutation_candidates, and failure_residual_candidates as arrays"],
        )
    if not accepted:
        return _revision(
            "no fresh accepted evidence is available for brain learning",
            "accepted_evidence_items",
            ["refresh public-read scan with current sources", "do not write stale or undated facts into brain"],
        )
    if not candidates:
        return _revision(
            "fresh evidence must produce at least one brain mutation candidate",
            "brain_mutation_candidates",
            ["build CIEU-backed node/edge/residual candidates from accepted fresh evidence"],
        )

    accepted_by_id = {}
    for item in accepted:
        if not isinstance(item, Mapping):
            return _revision("accepted evidence item must be a mapping", "accepted_evidence_items", ["normalize accepted evidence rows"])
        evidence_id = str(item.get("evidence_id") or "")
        status = str(item.get("freshness_status") or "")
        if not evidence_id:
            return _revision("accepted evidence is missing evidence_id", "accepted_evidence_items", ["add stable evidence_id"])
        if status not in ALLOWED_ACCEPTED_STATUSES:
            return _revision(
                "accepted evidence must have a current/recent freshness status",
                "accepted_evidence_items",
                [f"reclassify or reject evidence {evidence_id}"],
            )
        if not item.get("source_url") or not (item.get("source_date") or item.get("observed_at")):
            return _revision(
                "accepted evidence must include source_url and source_date/observed_at",
                "accepted_evidence_items",
                [f"add source_url and date metadata or reject evidence {evidence_id}"],
            )
        accepted_by_id[evidence_id] = item

    for item in rejected:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("evidence_id") or "") in accepted_by_id:
            return _deny(
                "same evidence cannot be both accepted and rejected",
                "evidence_freshness_report",
                [str(item.get("evidence_id"))],
            )

    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            return _revision("brain mutation candidate must be a mapping", "brain_mutation_candidates", ["normalize candidate rows"])
        candidate_id = str(candidate.get("candidate_id") or "")
        refs = [str(ref) for ref in candidate.get("source_evidence_ids", []) if ref]
        if not candidate_id or not refs:
            return _revision(
                "brain mutation candidate needs candidate_id and source_evidence_ids",
                "brain_mutation_candidates",
                ["link every brain candidate to fresh evidence ids"],
            )
        missing_refs = [ref for ref in refs if ref not in accepted_by_id]
        if missing_refs:
            return _revision(
                "brain mutation candidate references evidence that was not accepted as fresh/current",
                "brain_mutation_candidates",
                [f"remove or refresh evidence refs: {', '.join(missing_refs)}"],
            )
        if candidate.get("production_brain_write_performed") is True:
            return _deny(
                "brain mutation candidate already performed production brain write",
                "brain_mutation_candidates",
                [candidate_id],
            )
        if candidate.get("write_mode") not in {"CIEU_backed_candidate_only", "test_db_only"}:
            return _revision(
                "brain mutation candidate must stay in candidate/test mode",
                "brain_mutation_candidates",
                [f"set write_mode for {candidate_id} to CIEU_backed_candidate_only"],
            )

    for residual in residuals:
        if not isinstance(residual, Mapping):
            return _revision("failure residual candidate must be a mapping", "failure_residual_candidates", ["normalize residual rows"])
        if not residual.get("residual_id") or not residual.get("learning_update"):
            return _revision(
                "failure residual candidates require residual_id and learning_update",
                "failure_residual_candidates",
                ["record what failed or was uncertain and how Aiden should update"],
            )

    linkage = packet.get("CIEU_linkage") if isinstance(packet.get("CIEU_linkage"), Mapping) else {}
    if not linkage.get("source_CIEU_event_ids") or not linkage.get("target_event_type"):
        return _revision(
            "brain learning must link back to prior CIEU evidence and declare target event type",
            "CIEU_linkage",
            ["link strategy/host runtime CIEU event ids before accepting learning candidates"],
        )

    return CEOBrainLearningDecision(
        decision=CEOBrainLearningDecisionValue.ALLOW,
        reason="freshness-filtered market facts, competitor evidence, and failure residuals are CIEU-backed brain learning candidates only",
        navigation={
            "decision_mode": "allow_candidate_learning_no_production_write",
            "next_allowed_action": "store_CIEU_backed_brain_learning_candidates",
            "production_brain_write_allowed": False,
            "stale_evidence_allowed": False,
        },
    )


def build_ceo_brain_learning_cieu_record(
    packet: Mapping[str, Any],
    decision: CEOBrainLearningDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, CEOBrainLearningDecision) else dict(decision)
    freshness = packet.get("evidence_freshness_report") if isinstance(packet.get("evidence_freshness_report"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(packet.get("source_strategy_session_id") or "ceo_brain_learning_loop"),
        "agent_id": "Aiden",
        "event_type": CEO_BRAIN_LEARNING_LOOP_CIEU_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "CEO CIEU-backed brain learning loop decision",
        "contract_hash": "ceo-brain-learning-loop-contract-v1",
        "params": {
            "learning_loop_id": packet.get("learning_loop_id"),
            "accepted_evidence_count": len(packet.get("accepted_evidence_items") or []),
            "rejected_evidence_count": len(packet.get("rejected_evidence_items") or []),
            "brain_mutation_candidate_count": len(packet.get("brain_mutation_candidates") or []),
            "freshness_filter_applied": freshness.get("freshness_filter_applied"),
        },
        "result": {
            "decision": data.get("decision"),
            "reason": data.get("reason"),
            "correct_path": list(data.get("correct_path") or []),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
            "production_brain_write_performed": False,
        },
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore", "Aiden-brain-candidate-queue"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": data.get("decision") == "ALLOW",
    }


def write_ceo_brain_learning_cieu_record(
    packet: Mapping[str, Any],
    decision: CEOBrainLearningDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    record = build_ceo_brain_learning_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_brain_learning_loop_cieu_write_result",
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


def validate_and_write_ceo_brain_learning_packet(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_brain_learning_packet(packet)
    write_result = write_ceo_brain_learning_cieu_record(
        packet,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_brain_learning_loop_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> CEOBrainLearningDecision:
    path = [
        "repair CEO brain learning packet before any brain learning persists",
        "do not write stale/undated market evidence into brain",
        *correct_path,
    ]
    return CEOBrainLearningDecision(
        decision=CEOBrainLearningDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=failed_section,
        correct_path=path,
        navigation={
            "decision_mode": "correct_path_navigation",
            "next_allowed_action": "repair_brain_learning_packet_only",
            "blocked_actions": ["production_brain_write", "external_execution", "customer_or_revenue_claim"],
            "correct_path": path,
        },
    )


def _deny(reason: str, failed_section: str, violations: list[str]) -> CEOBrainLearningDecision:
    return CEOBrainLearningDecision(
        decision=CEOBrainLearningDecisionValue.DENY,
        reason=reason,
        failed_section=failed_section,
        violations=violations,
        correct_path=["remove forbidden claim or unsafe brain write", "return to CIEU-backed learning candidate path"],
        navigation={"decision_mode": "hard_stop", "next_allowed_action": "none_until_violation_removed"},
    )


def _escalate(reason: str, failed_section: str, correct_path: list[str]) -> CEOBrainLearningDecision:
    return CEOBrainLearningDecision(
        decision=CEOBrainLearningDecisionValue.ESCALATE,
        reason=reason,
        failed_section=failed_section,
        correct_path=correct_path,
        requires_owner_decision=True,
        navigation={"decision_mode": "owner_decision_required", "owner_decision_path": correct_path},
    )


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, (list, tuple, dict, set)):
        return True
    return True


def _forbidden_claim(packet: Mapping[str, Any]) -> str:
    truth = packet.get("truth_constraints") if isinstance(packet.get("truth_constraints"), Mapping) else {}
    for field in FORBIDDEN_TRUE_CLAIMS:
        if truth.get(field) is True:
            return field
    return ""


__all__ = [
    "CEO_BRAIN_LEARNING_LOOP_CIEU_EVENT_TYPE",
    "CEOBrainLearningDecision",
    "CEOBrainLearningDecisionValue",
    "FORMAL_CIEU_LOG_PATH",
    "build_ceo_brain_learning_cieu_record",
    "build_ceo_brain_learning_loop_contract",
    "validate_and_write_ceo_brain_learning_packet",
    "validate_ceo_brain_learning_packet",
    "write_ceo_brain_learning_cieu_record",
]
