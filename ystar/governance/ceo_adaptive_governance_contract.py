from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

try:
    from ystar.governance.cieu_store import CIEUStore
except Exception:  # pragma: no cover - local standalone syntax check fallback
    CIEUStore = None  # type: ignore


class CEOAdaptiveGovernanceDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOAdaptiveGovernanceDecision:
    decision: CEOAdaptiveGovernanceDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    navigation: dict[str, Any] = field(default_factory=dict)
    requires_owner_decision: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_adaptive_governance_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOAdaptiveGovernanceDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "navigation": dict(self.navigation),
            "requires_owner_decision": self.requires_owner_decision,
        }


CEO_ADAPTIVE_GOVERNANCE_EVENT_TYPE = "CEO_ADAPTIVE_GOVERNANCE_DISCOVERY_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_RESULT_FIELDS = (
    "discovery_id",
    "action_context",
    "discovered_obligations",
    "required_obligations",
    "obligation_invocation_proof",
    "correct_path_navigator",
    "bypass_prevention",
)

FORBIDDEN_TRUE_CLAIMS = (
    "customer_validation_claim",
    "pricing_validation_claim",
    "revenue_claim",
    "payment_claim",
    "paid_signal_claim",
    "L5_revenue_loop_complete",
    "K9Audit_integration_claim",
    "live_provider_execution_claim",
)


def validate_ceo_adaptive_governance_result(result: Mapping[str, Any]) -> CEOAdaptiveGovernanceDecision:
    if not isinstance(result, Mapping):
        return _deny("adaptive governance result must be a mapping", "schema", ["result_not_mapping"])
    missing = [field for field in REQUIRED_RESULT_FIELDS if field not in result]
    if missing:
        return _revision(
            "adaptive governance discovery result is missing required fields",
            "schema",
            [f"add {field}" for field in missing],
        )
    forbidden = _forbidden_claim(result)
    if forbidden:
        return _deny(
            f"forbidden completion claim present: {forbidden}",
            "truth_constraints",
            [forbidden],
        )
    context = result.get("action_context")
    if not isinstance(context, Mapping):
        return _revision("action_context must be structured", "action_context", ["attach structured action_context"])

    required = _ids(result.get("required_obligations"))
    discovered = _ids(result.get("discovered_obligations"))
    proof = result.get("obligation_invocation_proof")
    if not isinstance(proof, Mapping):
        return _revision(
            "obligation_invocation_proof must be structured",
            "obligation_invocation_proof",
            ["attach satisfied_obligations and missing_obligations"],
        )
    satisfied = set(str(item) for item in proof.get("satisfied_obligations") or [])
    missing_required = [obligation for obligation in required if obligation not in satisfied]
    if missing_required:
        return _revision(
            "required adaptive governance obligations are not satisfied",
            "obligation_invocation_proof",
            [f"{obligation}: {_correct_path_for(obligation)}" for obligation in missing_required],
        )
    undiscovered_required = [obligation for obligation in required if obligation not in discovered]
    if undiscovered_required:
        return _revision(
            "required obligations were not discovered by the adaptive scanner",
            "discovered_obligations",
            [f"rediscover obligation {obligation} from action context and runtime artifact" for obligation in undiscovered_required],
        )
    if context.get("provider_tool_boundary") is True and "gov_mcp_dry_run_preflight" not in satisfied:
        return _revision(
            "provider/tool boundary requires gov-mcp dry-run preflight",
            "obligation_invocation_proof",
            ["run gov-mcp dry-run/no-send preflight and attach receipt metadata"],
        )
    if context.get("market_strategy_required") is True:
        for obligation in (
            "six_d_brain_review",
            "external_observation_or_staleness_boundary",
            "pricing_hypothesis_source_audit",
            "right_to_win_analysis",
            "strongest_validation_question",
        ):
            if obligation not in satisfied:
                return _revision(
                    f"market strategy requires {obligation}",
                    "obligation_invocation_proof",
                    [_correct_path_for(obligation)],
                )
    if context.get("owner_bound_external_action_requested") is True:
        return _escalate(
            "owner-bound external action requires owner decision before execution",
            "owner_decision_boundary",
            ["present owner decision packet; do not execute external action"],
        )
    return CEOAdaptiveGovernanceDecision(
        decision=CEOAdaptiveGovernanceDecisionValue.ALLOW,
        reason="adaptive governance discovery and obligation proof satisfy governance contract",
        navigation={"next_allowed_action": "continue_to_doctrine_gate_or_runtime_validation"},
    )


def build_ceo_adaptive_governance_cieu_record(
    result: Mapping[str, Any],
    decision: CEOAdaptiveGovernanceDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, CEOAdaptiveGovernanceDecision) else dict(decision)
    action_context = result.get("action_context") if isinstance(result.get("action_context"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(result.get("session_id") or result.get("discovery_id") or "ceo_adaptive_governance"),
        "agent_id": "bridge_labs_ceo",
        "event_type": CEO_ADAPTIVE_GOVERNANCE_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "CEO adaptive governance discovery and correct-path navigation decision",
        "contract_hash": "ceo-adaptive-governance-v1",
        "params": {
            "discovery_id": result.get("discovery_id"),
            "action_id": action_context.get("action_id"),
            "action_type": action_context.get("action_type"),
            "required_obligation_count": len(_ids(result.get("required_obligations"))),
            "satisfied_obligation_count": len((result.get("obligation_invocation_proof") or {}).get("satisfied_obligations") or []),
        },
        "result": {
            "decision": data.get("decision"),
            "reason": data.get("reason"),
            "correct_path": list(data.get("correct_path") or []),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": data.get("decision") == "ALLOW",
    }


def write_ceo_adaptive_governance_cieu_record(
    result: Mapping[str, Any],
    decision: CEOAdaptiveGovernanceDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    if CIEUStore is None:
        raise RuntimeError("CIEUStore is unavailable")
    record = build_ceo_adaptive_governance_cieu_record(result, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_adaptive_governance_cieu_write_result",
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


def validate_and_write_ceo_adaptive_governance_result(
    result: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_adaptive_governance_result(result)
    write_result = write_ceo_adaptive_governance_cieu_record(
        result,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_adaptive_governance_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> CEOAdaptiveGovernanceDecision:
    path = [
        "repair adaptive governance discovery before continuing runtime execution",
        "do not execute external/L4/L5/customer/revenue/payment/provider action while decision is REQUIRE_REVISION",
        *correct_path,
    ]
    return CEOAdaptiveGovernanceDecision(
        decision=CEOAdaptiveGovernanceDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=failed_section,
        correct_path=path,
        navigation={
            "decision_mode": "correct_path_navigation",
            "next_allowed_action": "repair_packet_only",
            "blocked_actions": ["external_execution", "provider_execution", "customer_or_revenue_claim"],
            "correct_path": path,
        },
    )


def _deny(reason: str, failed_section: str, violations: list[str]) -> CEOAdaptiveGovernanceDecision:
    return CEOAdaptiveGovernanceDecision(
        decision=CEOAdaptiveGovernanceDecisionValue.DENY,
        reason=reason,
        failed_section=failed_section,
        violations=violations,
        correct_path=[
            "remove the forbidden claim or bypass attempt",
            "return to adaptive governance discovery and owner-gated validation",
        ],
        navigation={"decision_mode": "hard_stop", "next_allowed_action": "none_until_claim_removed"},
    )


def _escalate(reason: str, failed_section: str, correct_path: list[str]) -> CEOAdaptiveGovernanceDecision:
    return CEOAdaptiveGovernanceDecision(
        decision=CEOAdaptiveGovernanceDecisionValue.ESCALATE,
        reason=reason,
        failed_section=failed_section,
        correct_path=correct_path,
        requires_owner_decision=True,
        navigation={"decision_mode": "owner_decision_required", "owner_decision_path": correct_path},
    )


def _ids(items: Any) -> list[str]:
    result = []
    for item in items or []:
        if isinstance(item, Mapping):
            value = item.get("obligation_id") or item.get("id")
        else:
            value = item
        if value:
            result.append(str(value))
    return result


def _forbidden_claim(result: Mapping[str, Any]) -> str:
    checks = result.get("truth_constraints") if isinstance(result.get("truth_constraints"), Mapping) else {}
    for field in FORBIDDEN_TRUE_CLAIMS:
        if checks.get(field) is True:
            return field
    proof = result.get("obligation_invocation_proof") if isinstance(result.get("obligation_invocation_proof"), Mapping) else {}
    for field in FORBIDDEN_TRUE_CLAIMS:
        if proof.get(field) is True:
            return field
    return ""


def _correct_path_for(obligation_id: str) -> str:
    paths = {
        "six_d_brain_review": "run the 6D brain review, attach brain_provenance and six_d_brain_review, then revalidate",
        "pricing_hypothesis_source_audit": "state price as hypothesis, attach source basis, non-claims, and falsification test",
        "right_to_win_analysis": "compare why Y*Bridge Labs is fit against alternatives and name weaknesses",
        "strongest_validation_question": "produce one owner-gated no-send willingness-to-pay question",
        "competitor_differentiation_map": "name competitors and alternatives, then choose the narrow wedge",
        "external_observation_or_staleness_boundary": "invoke public-read observation or mark evidence stale/insufficient",
        "gov_mcp_dry_run_preflight": "route provider/tool boundary through gov-mcp dry-run/no-send receipt",
        "ceo_implementation_order": "build CEOImplementationOrder before Codex prompt generation",
        "post_action_residual": "build post-action residual and CIEU learning candidate",
    }
    return paths.get(obligation_id, f"satisfy obligation {obligation_id} with evidence and rerun governance")


__all__ = [
    "CEO_ADAPTIVE_GOVERNANCE_EVENT_TYPE",
    "CEOAdaptiveGovernanceDecision",
    "CEOAdaptiveGovernanceDecisionValue",
    "build_ceo_adaptive_governance_cieu_record",
    "validate_and_write_ceo_adaptive_governance_result",
    "validate_ceo_adaptive_governance_result",
    "write_ceo_adaptive_governance_cieu_record",
]
