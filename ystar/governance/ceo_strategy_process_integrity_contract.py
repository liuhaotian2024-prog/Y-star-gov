"""Governance for complete CEO strategy process integrity.

Open-world strategy is not just "not hardcoded." A CEO strategy run must also
prove it executed a full strategic process and audited recent-anchor bias. This
contract gives agents a correct path when they skip the real process instead of
silently accepting a polished but shallow strategy memo.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class CEOStrategyProcessIntegrityDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOStrategyProcessIntegrityDecision:
    decision: CEOStrategyProcessIntegrityDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_strategy_process_integrity_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOStrategyProcessIntegrityDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


CEO_STRATEGY_PROCESS_INTEGRITY_CIEU_EVENT_TYPE = "CEO_STRATEGY_PROCESS_INTEGRITY_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_STRATEGY_PHASES: tuple[str, ...] = (
    "owner_intent_restatement",
    "decision_question_framing",
    "blank_slate_opportunity_universe",
    "evidence_acquisition_plan",
    "query_expansion_log",
    "market_landscape_map",
    "competitor_saturation_by_cluster",
    "customer_segment_and_buyer_map",
    "business_model_options",
    "founder_market_fit_counterevidence",
    "route_generation_from_evidence_clusters",
    "counterfactual_route_comparison",
    "anchor_dependence_audit",
    "selected_strategy_thesis",
    "validation_experiment_design",
    "kill_criteria",
    "residual_learning_plan",
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
    "live_provider_execution_claim",
)


def build_ceo_strategy_process_integrity_contract() -> dict[str, Any]:
    return {
        "contract_id": "ceo_strategy_process_integrity_contract_v1",
        "event_type": CEO_STRATEGY_PROCESS_INTEGRITY_CIEU_EVENT_TYPE,
        "required_strategy_phases": list(REQUIRED_STRATEGY_PHASES),
        "minimum_opportunity_universe_count": 8,
        "minimum_counterfactual_route_count": 5,
        "minimum_customer_segments": 3,
        "minimum_business_model_options": 3,
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "external_action_allowed": False,
        "live_provider_execution_allowed": False,
    }


def validate_ceo_strategy_process_integrity(
    strategy: Mapping[str, Any],
) -> CEOStrategyProcessIntegrityDecision:
    if not isinstance(strategy, Mapping):
        return _decision("DENY", "strategy artifact must be a mapping", {}, "strategy_schema")

    forbidden = _forbidden_claim(strategy)
    if forbidden:
        return _decision(
            "DENY",
            f"forbidden completion claim present: {forbidden}",
            strategy,
            "overclaim_boundary",
            [forbidden],
        )

    if strategy.get("external_action_executed") is True or strategy.get("provider_action_executed") is True:
        return _decision(
            "DENY",
            "strategy process integrity run may not execute external/provider action",
            strategy,
            "execution_boundary",
            ["external_or_provider_execution_forbidden"],
        )

    proof = strategy.get("strategy_process_integrity_proof")
    if not isinstance(proof, Mapping):
        return _revision(
            "strategy_process_integrity_proof is required",
            strategy,
            "strategy_process_integrity_proof",
            ["run the full strategy process integrity pass before accepting the strategic conclusion"],
        )

    mode = str(proof.get("process_mode") or "")
    if mode in {"recent_memory_summary", "strategy_memo_only", "single_route_rationalization", "static_template"}:
        return _revision(
            "strategy process mode is not sufficient",
            strategy,
            "process_mode",
            ["rerun as full_strategy_process_with_anchor_audit"],
        )

    completed = set(str(item) for item in _as_list(proof.get("completed_phases")))
    missing = [phase for phase in REQUIRED_STRATEGY_PHASES if phase not in completed]
    if missing:
        return _revision(
            "strategy process is missing required phases",
            strategy,
            "completed_phases",
            ["complete missing phases: " + ", ".join(missing)],
        )

    if proof.get("recent_memory_only") is True or proof.get("recent_chat_summary_only") is True:
        return _revision(
            "recent memory or recent chat summary cannot satisfy CEO strategy",
            strategy,
            "recent_memory_boundary",
            ["rebuild strategy from brain provenance plus public-read evidence plus repo capability map"],
        )

    universe = _as_list(proof.get("opportunity_universe_scan"))
    if len(universe) < 8:
        return _revision(
            "blank-slate opportunity universe must include at least eight domains",
            strategy,
            "blank_slate_opportunity_universe",
            ["expand opportunity_universe_scan beyond the current favorite route"],
        )

    counterfactual = _as_list(proof.get("counterfactual_comparison"))
    if len(counterfactual) < 5:
        return _revision(
            "counterfactual comparison must include at least five routes",
            strategy,
            "counterfactual_route_comparison",
            ["compare at least five materially different routes with why-not decisions"],
        )
    for row in counterfactual:
        if not isinstance(row, Mapping) or not _present(row.get("why_not_selected")):
            return _revision(
                "each counterfactual route needs why_not_selected",
                strategy,
                "counterfactual_route_comparison",
                ["add why_not_selected to every compared route"],
            )

    customer_segments = _as_list(proof.get("customer_segment_and_buyer_map"))
    if len(customer_segments) < 3:
        return _revision(
            "strategy needs at least three customer/buyer segments",
            strategy,
            "customer_segment_and_buyer_map",
            ["map customer, buyer, urgent pain, budget owner, and adoption friction for at least three segments"],
        )

    business_models = _as_list(proof.get("business_model_options"))
    if len(business_models) < 3:
        return _revision(
            "strategy needs at least three business model options",
            strategy,
            "business_model_options",
            ["compare service sprint, productized service, and eventual software/tooling options"],
        )

    anchor = proof.get("anchor_dependence_audit")
    if not isinstance(anchor, Mapping):
        return _revision(
            "anchor_dependence_audit is required",
            strategy,
            "anchor_dependence_audit",
            ["audit prior selected routes and recent-memory anchors before final selection"],
        )
    if anchor.get("blank_slate_generation_before_anchor_review") is not True:
        return _revision(
            "route generation must happen before anchor review",
            strategy,
            "anchor_dependence_audit",
            ["generate opportunity universe before comparing against prior anchors"],
        )
    if anchor.get("anchor_penalty_applied") is not True:
        return _revision(
            "anchor penalty must be applied",
            strategy,
            "anchor_dependence_audit",
            ["apply explicit penalty or burden-of-proof to prior favorite routes"],
        )
    if anchor.get("selected_route_supported_without_anchor") is not True:
        return _revision(
            "selected route must be supported without relying on the prior anchor",
            strategy,
            "anchor_dependence_audit",
            ["attach independent evidence and counterfactual reasons for the selected route"],
        )

    validation = proof.get("validation_experiment_design")
    if not isinstance(validation, Mapping):
        return _revision(
            "validation_experiment_design is required",
            strategy,
            "validation_experiment_design",
            ["design a no-send owner-gated validation experiment"],
        )
    if validation.get("no_send_default") is not True or validation.get("owner_decision_required") is not True:
        return _decision(
            "DENY",
            "validation experiment must be no-send and owner-decision gated",
            strategy,
            "validation_experiment_design",
            ["validation_experiment_not_owner_gated"],
        )

    packet = strategy.get("next_L4_feedback_owner_decision_packet")
    if not isinstance(packet, Mapping) or packet.get("no_send_default") is not True:
        return _decision(
            "DENY",
            "next L4 packet must remain no-send",
            strategy,
            "next_L4_feedback_owner_decision_packet",
            ["l4_packet_not_no_send"],
        )

    if strategy.get("execute_L4_now") is True and str(packet.get("owner_approval_state")) != "approved":
        return _decision(
            "ESCALATE",
            "complete strategy attempts owner-bound L4 execution without approval",
            strategy,
            "owner_approval_gate",
            ["owner_decision_required"],
            guidance={
                "guidance_type": "owner_decision_required",
                "owner_decision_path": "submit next_L4_feedback_owner_decision_packet; do not send",
                "execution_allowed_before_owner_decision": False,
            },
            correct_path=[
                "stop before external feedback execution",
                "present owner decision packet",
                "rerun governance after explicit owner approval",
            ],
            requires_owner_decision=True,
        )

    return _decision("ALLOW", "CEO strategy process integrity proof passed", strategy)


def build_ceo_strategy_process_integrity_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOStrategyProcessIntegrityDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, CEOStrategyProcessIntegrityDecision) else dict(decision)
    decision_value = str(decision_data.get("decision") or "DENY")
    proof = strategy.get("strategy_process_integrity_proof") if isinstance(strategy.get("strategy_process_integrity_proof"), Mapping) else {}
    selected = strategy.get("selected_strategy") if isinstance(strategy.get("selected_strategy"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(strategy.get("session_id") or "e106_strategy_process_integrity_session"),
        "agent_id": "bridge_labs_ceo",
        "event_type": CEO_STRATEGY_PROCESS_INTEGRITY_CIEU_EVENT_TYPE,
        "decision": _decision_to_cieu_decision(decision_value),
        "passed": decision_value == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_value != "ALLOW",
        "drift_details": None if decision_value == "ALLOW" else decision_data.get("reason"),
        "task_description": "CEO full strategy process and anti-anchor governance decision",
        "contract_hash": "ceo-strategy-process-integrity-v1",
        "params": {
            "strategy_run_id": strategy.get("strategy_run_id"),
            "selected_route_id": selected.get("selected_route_id"),
            "completed_phase_count": len(_as_list(proof.get("completed_phases"))),
            "opportunity_universe_count": len(_as_list(proof.get("opportunity_universe_scan"))),
            "counterfactual_route_count": len(_as_list(proof.get("counterfactual_comparison"))),
            "recent_memory_only": proof.get("recent_memory_only"),
            "process_mode": proof.get("process_mode"),
        },
        "result": {
            "decision": decision_value,
            "reason": decision_data.get("reason"),
            "selected_route_id": selected.get("selected_route_id"),
            "selected_first_cash_path": selected.get("current_best_first_cash_path"),
            "failed_section": decision_data.get("failed_section"),
            "correct_path": list(decision_data.get("correct_path") or [])[:10],
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
            "strategy_process_integrity_required": True,
            "anti_anchor_audit_required": True,
            "no_external_action_executed": True,
        },
        "human_initiator": strategy.get("human_initiator") or "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_value == "ALLOW",
    }


def write_ceo_strategy_process_integrity_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOStrategyProcessIntegrityDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    if not cieu_db:
        raise ValueError("cieu_db is required")
    record = build_ceo_strategy_process_integrity_cieu_record(strategy, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_strategy_process_integrity_formal_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "formal_CIEU_log_module": "ystar.governance.ceo_strategy_process_integrity_contract",
        "formal_CIEU_log_function": "write_ceo_strategy_process_integrity_cieu_record",
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_strategy_process_integrity(
    strategy: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_strategy_process_integrity(strategy)
    write_result = write_ceo_strategy_process_integrity_cieu_record(
        strategy,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_strategy_process_integrity_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _decision(
    value: str,
    reason: str,
    strategy: Mapping[str, Any],
    failed_section: str | None = None,
    violations: list[str] | None = None,
    *,
    guidance: dict[str, Any] | None = None,
    correct_path: list[str] | None = None,
    requires_owner_decision: bool = False,
) -> CEOStrategyProcessIntegrityDecision:
    decision_value = CEOStrategyProcessIntegrityDecisionValue(value)
    provisional = CEOStrategyProcessIntegrityDecision(
        decision=decision_value,
        reason=reason,
        failed_section=failed_section,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
    )
    return CEOStrategyProcessIntegrityDecision(
        decision=decision_value,
        reason=reason,
        failed_section=failed_section,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
        cieu_validation_record=_validation_candidate(strategy, provisional),
    )


def _revision(
    reason: str,
    strategy: Mapping[str, Any],
    failed_section: str,
    required_changes: list[str],
) -> CEOStrategyProcessIntegrityDecision:
    correct_path = [
        "repair the CEO strategy process before accepting the strategic conclusion",
        "do not execute L4/L5/customer/revenue/payment action while decision is REQUIRE_REVISION",
        "rerun validate_ceo_strategy_process_integrity after repair",
        *required_changes,
    ]
    return _decision(
        "REQUIRE_REVISION",
        reason,
        strategy,
        failed_section,
        required_changes,
        guidance={
            "guidance_type": "require_revision",
            "failed_section": failed_section,
            "required_strategy_changes": required_changes,
            "correct_path": correct_path,
            "execution_allowed_before_revision": False,
            "revalidate_after_revision": True,
        },
        correct_path=correct_path,
    )


def _validation_candidate(strategy: Mapping[str, Any], decision: CEOStrategyProcessIntegrityDecision) -> dict[str, Any]:
    return {
        "X_t": {
            "contract_id": "ceo_strategy_process_integrity_contract_v1",
            "strategy_run_id": strategy.get("strategy_run_id"),
        },
        "U_t": "Y-star-gov deterministic CEO full strategy process validation",
        "Y_star_t": "CEO strategy must prove full process execution and anti-anchor audit, not just a plausible selected route",
        "Y_t_plus_1": {
            "decision": decision.decision.value,
            "reason": decision.reason,
            "failed_section": decision.failed_section,
            "correct_path": list(decision.correct_path),
        },
        "R_t_plus_1": "none" if decision.decision == CEOStrategyProcessIntegrityDecisionValue.ALLOW else decision.reason,
    }


def _forbidden_claim(strategy: Mapping[str, Any]) -> str:
    checks = strategy.get("overclaim_boundary") or strategy.get("truth_constraints") or {}
    if isinstance(checks, Mapping):
        for field in FORBIDDEN_COMPLETION_CLAIMS:
            if checks.get(field) is True:
                return field
    text = _text(strategy)
    for phrase in (
        "customer validation complete",
        "customer validation achieved",
        "revenue achieved",
        "paid signal achieved",
        "payment loop complete",
        "pricing validation complete",
        "l5 revenue loop complete",
        "l4 feedback executed",
        "k9audit integration complete",
        "live provider execution complete",
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
    }.get(value, "unknown")


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}):
        return []
    return [value]


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_text(item)}" for key, item in value.items()).lower()
    if isinstance(value, list):
        return " ".join(_text(item) for item in value).lower()
    return str(value or "").lower()


__all__ = [
    "CEO_STRATEGY_PROCESS_INTEGRITY_CIEU_EVENT_TYPE",
    "CEOStrategyProcessIntegrityDecision",
    "CEOStrategyProcessIntegrityDecisionValue",
    "REQUIRED_STRATEGY_PHASES",
    "build_ceo_strategy_process_integrity_contract",
    "build_ceo_strategy_process_integrity_cieu_record",
    "validate_and_write_ceo_strategy_process_integrity",
    "validate_ceo_strategy_process_integrity",
    "write_ceo_strategy_process_integrity_cieu_record",
]
