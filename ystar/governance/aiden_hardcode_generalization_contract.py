from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

try:
    from ystar.governance.cieu_store import CIEUStore
except Exception:  # pragma: no cover
    CIEUStore = None  # type: ignore


class AidenHardcodeGeneralizationDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class AidenHardcodeGeneralizationDecision:
    decision: AidenHardcodeGeneralizationDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "aiden_hardcode_generalization_decision",
            "decision": self.decision.value,
            "passed": self.decision == AidenHardcodeGeneralizationDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
        }


AIDEN_HARDCODE_GENERALIZATION_EVENT_TYPE = "AIDEN_HARDCODE_GENERALIZATION_DECISION"

REQUIRED_PACKET_FIELDS = (
    "action_context",
    "owner_input",
    "owner_facing_answer",
    "runtime_proof",
    "hardcode_audit",
    "generalization_proof",
)

FORBIDDEN_TRUE_CLAIMS = (
    "customer_validation_claim",
    "pricing_validation_claim",
    "revenue_claim",
    "payment_claim",
    "paid_signal_claim",
    "live_provider_execution_claim",
    "K9Audit_integration_claim",
)


def build_aiden_hardcode_generalization_contract() -> dict[str, Any]:
    return {
        "contract_id": "aiden_hardcode_generalization_contract_v1",
        "event_type": AIDEN_HARDCODE_GENERALIZATION_EVENT_TYPE,
        "purpose": "prevent point-fix/template/hardcoded runtime answers from masquerading as Aiden intelligence",
        "required_packet_fields": list(REQUIRED_PACKET_FIELDS),
        "decision_values": [item.value for item in AidenHardcodeGeneralizationDecisionValue],
    }


def validate_aiden_hardcode_generalization_packet(packet: Mapping[str, Any]) -> AidenHardcodeGeneralizationDecision:
    if not isinstance(packet, Mapping):
        return _deny("hardcode generalization packet must be a mapping", "schema", ["packet_not_mapping"])
    missing = [field for field in REQUIRED_PACKET_FIELDS if field not in packet]
    if missing:
        return _revision(
            "hardcode generalization packet is missing required fields",
            "schema",
            [f"add {field}" for field in missing],
        )
    forbidden = _forbidden_claim(packet)
    if forbidden:
        return _deny(
            f"forbidden completion claim present: {forbidden}",
            "truth_constraints",
            [forbidden],
        )
    context = packet.get("action_context")
    answer = packet.get("owner_facing_answer")
    audit = packet.get("hardcode_audit")
    proof = packet.get("generalization_proof")
    runtime = packet.get("runtime_proof")
    if not isinstance(context, Mapping):
        return _revision("action_context must be structured", "action_context", ["attach structured action_context"])
    if not isinstance(answer, Mapping):
        return _revision("owner_facing_answer must be structured", "owner_facing_answer", ["attach text, language, and owner_readable"])
    if not isinstance(audit, Mapping):
        return _revision("hardcode_audit must be structured", "hardcode_audit", ["attach scanned scope and runtime findings"])
    if not isinstance(proof, Mapping):
        return _revision("generalization_proof must be structured", "generalization_proof", ["attach class_of_issue and class_level_fix"])
    if not isinstance(runtime, Mapping):
        return _revision("runtime_proof must be structured", "runtime_proof", ["attach runtime path and generation mode"])

    if answer.get("raw_machine_receipt_rendered_to_owner") is True:
        return _revision(
            "machine receipt cannot be the owner-facing answer",
            "owner_facing_answer",
            ["translate runtime receipt into content judgment; keep proof in boundary section"],
        )
    if answer.get("process_first") is True and not answer.get("content_judgment_first"):
        return _revision(
            "owner-facing answer must lead with judgment, not process",
            "owner_facing_answer",
            ["start with decision content; move governance/provenance to the end"],
        )
    if runtime.get("static_template_used") is True and not context.get("test_mode"):
        return _revision(
            "static template cannot satisfy non-test Aiden intelligence",
            "runtime_proof",
            ["invoke retrieval/brain/strategy runtime or label output as fixture-only"],
        )
    if audit.get("runtime_active_issue_specific_literals"):
        return _revision(
            "runtime-active issue-specific literals require generalization or quarantine",
            "hardcode_audit",
            ["move issue-specific literals to fixture/report or derive them from retrieved evidence"],
        )
    if proof.get("point_fix_only") is True:
        return _revision(
            "point-fix-only repair is not sufficient",
            "generalization_proof",
            ["identify issue class, sibling variants, and class-level runtime fix"],
        )
    if not proof.get("class_of_issue"):
        return _revision(
            "generalization proof must name the issue class",
            "generalization_proof",
            ["add class_of_issue with scope and boundary"],
        )
    variants = proof.get("sibling_variants") or []
    if not isinstance(variants, list) or len(variants) < 3:
        return _revision(
            "generalization proof must enumerate sibling variants",
            "generalization_proof",
            ["list at least three sibling variants affected by the same issue class"],
        )
    if not proof.get("class_level_fix"):
        return _revision(
            "generalization proof must include class-level fix",
            "generalization_proof",
            ["add class_level_fix and affected_runtime_paths"],
        )
    return AidenHardcodeGeneralizationDecision(
        decision=AidenHardcodeGeneralizationDecisionValue.ALLOW,
        reason="hardcode generalization packet satisfies owner-facing and runtime anti-template governance",
    )


def build_aiden_hardcode_generalization_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenHardcodeGeneralizationDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, AidenHardcodeGeneralizationDecision) else dict(decision)
    context = packet.get("action_context") if isinstance(packet.get("action_context"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(packet.get("session_id") or "aiden_hardcode_generalization"),
        "agent_id": "Aiden",
        "event_type": AIDEN_HARDCODE_GENERALIZATION_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "Aiden hardcode generalization and anti-template governance decision",
        "contract_hash": "aiden-hardcode-generalization-v1",
        "params": {
            "action_id": context.get("action_id"),
            "action_type": context.get("action_type"),
            "generation_mode": (packet.get("runtime_proof") or {}).get("generation_mode")
            if isinstance(packet.get("runtime_proof"), Mapping)
            else None,
        },
        "result": {
            "decision": data.get("decision"),
            "reason": data.get("reason"),
            "failed_section": data.get("failed_section"),
            "correct_path": list(data.get("correct_path") or []),
        },
        "cieu_tuple": {
            "Y_star": "Aiden output must generalize beyond point fixes",
            "X": dict(context),
            "U": {"contract": "aiden_hardcode_generalization_contract_v1"},
            "Y_plus_1": data.get("decision"),
            "R_plus_1": 0.0 if data.get("decision") == "ALLOW" else 1.0,
        },
    }


def write_aiden_hardcode_generalization_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenHardcodeGeneralizationDecision | Mapping[str, Any],
    *,
    cieu_store: Any | None = None,
    db_path: str | None = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    record = build_aiden_hardcode_generalization_cieu_record(packet, decision, session_id=session_id)
    store = cieu_store
    if store is None:
        if CIEUStore is None:
            raise RuntimeError("CIEUStore unavailable")
        store = CIEUStore(db_path=db_path) if db_path else CIEUStore()
    store.write_dict(record)
    return {"write_status": "written", "event_type": AIDEN_HARDCODE_GENERALIZATION_EVENT_TYPE, "record": record}


def validate_and_write_aiden_hardcode_generalization_packet(
    packet: Mapping[str, Any],
    *,
    cieu_store: Any | None = None,
    db_path: str | None = None,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    decision = validate_aiden_hardcode_generalization_packet(packet)
    write = write_aiden_hardcode_generalization_cieu_record(
        packet,
        decision,
        cieu_store=cieu_store,
        db_path=db_path,
        session_id=session_id,
    )
    return {"decision": decision.to_dict(), "cieu_write": write}


def _revision(reason: str, section: str, correct_path: list[str]) -> AidenHardcodeGeneralizationDecision:
    return AidenHardcodeGeneralizationDecision(
        decision=AidenHardcodeGeneralizationDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=section,
        violations=[reason],
        correct_path=correct_path,
    )


def _deny(reason: str, section: str, violations: list[str]) -> AidenHardcodeGeneralizationDecision:
    return AidenHardcodeGeneralizationDecision(
        decision=AidenHardcodeGeneralizationDecisionValue.DENY,
        reason=reason,
        failed_section=section,
        violations=violations,
        correct_path=["remove false claim; preserve truth boundary; rerun validation"],
    )


def _forbidden_claim(packet: Mapping[str, Any]) -> str:
    for claim in FORBIDDEN_TRUE_CLAIMS:
        if packet.get(claim) is True:
            return claim
    return ""


__all__ = [
    "AIDEN_HARDCODE_GENERALIZATION_EVENT_TYPE",
    "AidenHardcodeGeneralizationDecision",
    "AidenHardcodeGeneralizationDecisionValue",
    "build_aiden_hardcode_generalization_contract",
    "build_aiden_hardcode_generalization_cieu_record",
    "validate_aiden_hardcode_generalization_packet",
    "validate_and_write_aiden_hardcode_generalization_packet",
    "write_aiden_hardcode_generalization_cieu_record",
]
