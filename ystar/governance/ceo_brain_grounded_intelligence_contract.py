"""Governance contract for brain-grounded CEO intelligence packets.

Extends ceo_intelligence_loop_contract by REQUIRING that stage outputs cite
real activations from a CEO brain (aiden_brain.db). Hardcoded template
strings are no longer acceptable as a stage output_summary on the live path.

A brain-grounded packet must include:
  - brain_provenance: { brain_db, total_activations, unique_nodes }
  - each stage MUST have a non-empty 'brain_activations' list whose
    activated nodes appear at least once in evidence_refs as 'brain://...'
  - the packet must NOT contain hidden chain-of-thought
  - the packet must not over-claim L4/L5/customer/revenue completion

This contract is deterministic: no LLM judgment.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class CEOBrainGroundedDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOBrainGroundedDecision:
    decision: CEOBrainGroundedDecisionValue
    reason: str
    failed_field: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_brain_grounded_intelligence_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOBrainGroundedDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_field": self.failed_field,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


CEO_BRAIN_GROUNDED_CIEU_EVENT_TYPE = "CEO_BRAIN_GROUNDED_INTELLIGENCE_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_PACKET_FIELDS: tuple[str, ...] = (
    "artifact_id",
    "intelligence_loop_id",
    "session_id",
    "agent_id",
    "owner_intent",
    "brain_provenance",
    "stages",
    "selected_action",
    "owner_approval_state",
)

REQUIRED_BRAIN_PROVENANCE_FIELDS: tuple[str, ...] = (
    "brain_db",
    "total_activations",
    "unique_nodes",
)

REQUIRED_STAGE_FIELDS: tuple[str, ...] = (
    "stage_id",
    "input_summary",
    "evidence_refs",
    "output_summary",
    "brain_activations",
)

FORBIDDEN_PRIVATE_REASONING_KEYS: tuple[str, ...] = (
    "chain_of_thought",
    "hidden_chain_of_thought",
    "private_chain_of_thought",
    "private_reasoning",
    "raw_model_reasoning",
)

FORBIDDEN_COMPLETION_CLAIMS: tuple[str, ...] = (
    "customer_validation_claim",
    "revenue_claim",
    "payment_claim",
    "paid_signal_claim",
    "pricing_validation_claim",
    "L4_feedback_executed",
    "L5_revenue_loop_complete",
    "production_deployment_claim",
    "K9Audit_integration_claim",
)

MIN_BRAIN_ACTIVATIONS_PER_PACKET = 5
MIN_UNIQUE_NODES_PER_PACKET = 3


def validate_ceo_brain_grounded_intelligence_packet(
    packet: Mapping[str, Any],
) -> CEOBrainGroundedDecision:
    """Validate a brain-grounded CEO intelligence packet."""
    if not isinstance(packet, Mapping):
        return _decision("DENY", "packet must be a mapping", {}, "packet_schema")

    # Forbidden private reasoning keys
    for k in FORBIDDEN_PRIVATE_REASONING_KEYS:
        if k in packet:
            return _decision(
                "DENY",
                "private chain-of-thought must not be stored",
                packet,
                "private_reasoning_boundary",
                [k],
            )

    if packet.get("bypass_attempt") is True:
        return _decision(
            "DENY",
            "bypass_attempt is forbidden",
            packet,
            "bypass_policy",
            ["bypass_attempt"],
        )

    forbidden = _forbidden_claim(packet)
    if forbidden:
        return _decision(
            "DENY",
            f"forbidden completion claim present: {forbidden}",
            packet,
            "overclaim_boundary",
            [forbidden],
        )

    # Required top-level fields
    missing = [f for f in REQUIRED_PACKET_FIELDS if f not in packet]
    if missing:
        return _revision(
            "packet missing required fields",
            packet,
            "packet_schema",
            ["fill missing fields: " + ", ".join(missing)],
        )

    # Brain provenance
    bp = packet.get("brain_provenance")
    if not isinstance(bp, Mapping):
        return _revision(
            "brain_provenance must be a mapping",
            packet,
            "brain_provenance",
            ["attach brain_provenance with brain_db, total_activations, unique_nodes"],
        )
    bp_missing = [f for f in REQUIRED_BRAIN_PROVENANCE_FIELDS if f not in bp]
    if bp_missing:
        return _revision(
            "brain_provenance missing fields",
            packet,
            "brain_provenance",
            ["fill brain_provenance fields: " + ", ".join(bp_missing)],
        )

    total_act = bp.get("total_activations", 0)
    unique_nodes = bp.get("unique_nodes", 0)
    if not isinstance(total_act, int) or total_act < MIN_BRAIN_ACTIVATIONS_PER_PACKET:
        return _revision(
            f"brain provenance shows insufficient activations: {total_act} < {MIN_BRAIN_ACTIVATIONS_PER_PACKET}",
            packet,
            "brain_provenance",
            [f"perform at least {MIN_BRAIN_ACTIVATIONS_PER_PACKET} brain activations"],
        )
    if not isinstance(unique_nodes, int) or unique_nodes < MIN_UNIQUE_NODES_PER_PACKET:
        return _revision(
            f"brain provenance shows insufficient unique nodes: {unique_nodes} < {MIN_UNIQUE_NODES_PER_PACKET}",
            packet,
            "brain_provenance",
            [f"reach at least {MIN_UNIQUE_NODES_PER_PACKET} unique brain nodes across stages"],
        )

    # Stages
    stages = packet.get("stages")
    if not isinstance(stages, list) or not stages:
        return _revision(
            "stages must be a non-empty list",
            packet,
            "stages",
            ["attach intelligence stages list"],
        )

    for stage in stages:
        if not isinstance(stage, Mapping):
            return _revision(
                "stage must be a mapping",
                packet,
                "stages",
                ["replace stage entry with proper mapping"],
            )
        s_missing = [f for f in REQUIRED_STAGE_FIELDS if f not in stage]
        if s_missing:
            return _revision(
                f"stage {stage.get('stage_id', '?')} missing fields",
                packet,
                "stages",
                ["fill stage fields: " + ", ".join(s_missing)],
            )

        # brain_activations must be a non-empty list
        ba = stage.get("brain_activations")
        if not isinstance(ba, list) or not ba:
            return _revision(
                f"stage {stage.get('stage_id', '?')} has no brain_activations",
                packet,
                "stages",
                [
                    "every stage in a brain-grounded packet must record brain_activations",
                    "if brain returned no relevant nodes, do not use brain-grounded contract",
                ],
            )

        # evidence_refs must include at least one brain:// reference
        evidence_refs = stage.get("evidence_refs", [])
        if not any(
            isinstance(ref, str) and ref.startswith("brain://")
            for ref in evidence_refs
        ):
            return _revision(
                f"stage {stage.get('stage_id', '?')} evidence_refs lacks brain:// citation",
                packet,
                "stages",
                ["add brain://<node_id> citation to evidence_refs for each brain-activated stage"],
            )

    # Selected action must be a mapping
    sa = packet.get("selected_action")
    if not isinstance(sa, Mapping) or not sa.get("description"):
        return _revision(
            "selected_action must be a mapping with a description",
            packet,
            "selected_action",
            ["attach a selected_action with description and route_type"],
        )

    return _decision(
        "ALLOW",
        "brain-grounded CEO intelligence packet satisfies contract",
        packet,
    )


def build_ceo_brain_grounded_cieu_record(
    packet: Mapping[str, Any],
    decision: CEOBrainGroundedDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    """Build a CIEU record for a brain-grounded intelligence decision."""
    decision_data = (
        decision.to_dict()
        if isinstance(decision, CEOBrainGroundedDecision)
        else dict(decision)
    )
    decision_value = str(decision_data.get("decision") or "DENY")
    bp = packet.get("brain_provenance") if isinstance(packet.get("brain_provenance"), Mapping) else {}
    sa = packet.get("selected_action") if isinstance(packet.get("selected_action"), Mapping) else {}

    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(packet.get("session_id") or "ceo_brain_grounded_session"),
        "agent_id": str(packet.get("agent_id") or "bridge_labs_ceo"),
        "event_type": CEO_BRAIN_GROUNDED_CIEU_EVENT_TYPE,
        "decision": _decision_to_cieu_decision(decision_value),
        "passed": decision_value == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_value != "ALLOW",
        "drift_details": None if decision_value == "ALLOW" else decision_data.get("reason"),
        "task_description": "CEO brain-grounded intelligence packet decision",
        "contract_hash": "ceo-brain-grounded-intelligence-v1",
        "params": {
            "intelligence_loop_id": packet.get("intelligence_loop_id"),
            "owner_intent": str(packet.get("owner_intent") or "")[:300],
            "brain_db": bp.get("brain_db"),
            "total_brain_activations": bp.get("total_activations"),
            "unique_brain_nodes": bp.get("unique_nodes"),
            "stage_count": len(packet.get("stages", []) if isinstance(packet.get("stages"), list) else []),
            "selected_candidate_id": sa.get("candidate_id"),
            "private_chain_of_thought_stored": False,
        },
        "result": {
            "decision": decision_value,
            "reason": decision_data.get("reason"),
            "failed_field": decision_data.get("failed_field"),
            "selected_action_description": sa.get("description"),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": packet.get("human_initiator") or packet.get("owner_id"),
        "lineage_path": ["bridge-labs", "Y-star-gov", "aiden_brain", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_value == "ALLOW",
    }


def write_ceo_brain_grounded_cieu_record(
    packet: Mapping[str, Any],
    decision: CEOBrainGroundedDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    """Validate-already-decided + write CIEU record + optionally seal."""
    if not cieu_db:
        raise ValueError("cieu_db is required")
    record = build_ceo_brain_grounded_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_brain_grounded_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "written" if written else "duplicate_or_failed",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_brain_grounded_intelligence_packet(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    """Validate + write in one call."""
    decision = validate_ceo_brain_grounded_intelligence_packet(packet)
    write_result = write_ceo_brain_grounded_cieu_record(
        packet,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_brain_grounded_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
    }


# ── Helpers ──────────────────────────────────────────────────────────────


def _decision(
    value: str,
    reason: str,
    packet: Mapping[str, Any],
    failed_field: str | None = None,
    violations: list[str] | None = None,
) -> CEOBrainGroundedDecision:
    decision_value = CEOBrainGroundedDecisionValue(value)
    return CEOBrainGroundedDecision(
        decision=decision_value,
        reason=reason,
        failed_field=failed_field,
        violations=violations or [],
        guidance={
            "guidance_type": "deterministic_governance",
            "failed_field": failed_field,
        },
        correct_path=[],
        cieu_validation_record={
            "session_id": packet.get("session_id") if isinstance(packet, Mapping) else None,
            "decision": value,
            "reason": reason,
        },
    )


def _revision(
    reason: str,
    packet: Mapping[str, Any],
    failed_field: str,
    correct_path: list[str],
) -> CEOBrainGroundedDecision:
    return CEOBrainGroundedDecision(
        decision=CEOBrainGroundedDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_field=failed_field,
        violations=[],
        guidance={
            "guidance_type": "require_revision",
            "failed_field": failed_field,
            "correct_path": correct_path,
            "execution_allowed_before_revision": False,
        },
        correct_path=correct_path,
        cieu_validation_record={
            "session_id": packet.get("session_id") if isinstance(packet, Mapping) else None,
            "decision": "REQUIRE_REVISION",
            "reason": reason,
        },
    )


def _forbidden_claim(packet: Mapping[str, Any]) -> str:
    overclaim = packet.get("overclaim_boundary") or packet.get("truth_constraints") or {}
    if isinstance(overclaim, Mapping):
        for f in FORBIDDEN_COMPLETION_CLAIMS:
            if overclaim.get(f) is True:
                return f
    text = _text(packet)
    for phrase in (
        "l5 revenue loop complete",
        "customer validation complete",
        "paid signal achieved",
        "payment loop complete",
        "production deployment complete",
        "k9audit integration complete",
    ):
        if phrase in text:
            return phrase
    return ""


def _decision_to_cieu_decision(value: str) -> str:
    return {
        "ALLOW": "allow",
        "REQUIRE_REVISION": "rewrite",
        "DENY": "deny",
        "ESCALATE": "escalate",
    }.get(value, "deny")


def _text(value: Any) -> str:
    import json
    try:
        return json.dumps(value, default=str).lower()
    except Exception:
        return str(value).lower()


__all__ = [
    "CEO_BRAIN_GROUNDED_CIEU_EVENT_TYPE",
    "FORMAL_CIEU_LOG_PATH",
    "CEOBrainGroundedDecision",
    "CEOBrainGroundedDecisionValue",
    "MIN_BRAIN_ACTIVATIONS_PER_PACKET",
    "MIN_UNIQUE_NODES_PER_PACKET",
    "validate_ceo_brain_grounded_intelligence_packet",
    "build_ceo_brain_grounded_cieu_record",
    "write_ceo_brain_grounded_cieu_record",
    "validate_and_write_ceo_brain_grounded_intelligence_packet",
]
