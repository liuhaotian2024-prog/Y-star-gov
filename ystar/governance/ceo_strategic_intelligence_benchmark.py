"""Deterministic governance for CEO strategic intelligence benchmark output.

This module validates market-grounded strategy artifacts produced by
bridge-labs. It persists the benchmark decision through the existing
``CIEUStore.write_dict`` path and does not create a parallel ledger.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class CEOStrategicBenchmarkDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOStrategicBenchmarkDecision:
    decision: CEOStrategicBenchmarkDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_strategic_intelligence_benchmark_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOStrategicBenchmarkDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


CEO_STRATEGIC_BENCHMARK_CIEU_EVENT_TYPE = "CEO_STRATEGIC_INTELLIGENCE_BENCHMARK_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_STRATEGY_SECTIONS: tuple[str, ...] = (
    "internal_capability_map",
    "external_market_evidence_map",
    "route_candidates",
    "route_scoring",
    "selected_strategy",
    "do_not_pursue_list",
    "next_L4_feedback_owner_decision_packet",
    "CIEU_predictions",
    "post_strategy_residual_plan",
    "benchmark_result",
)

REQUIRED_CIEU_PREDICTION_FIELDS: tuple[str, ...] = (
    "X_t",
    "U_t",
    "Y_star_t",
    "expected_Y_t_plus_1",
    "predicted_R_t_plus_1",
    "residual_severity",
    "falsification_condition",
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


def validate_ceo_strategic_intelligence_strategy(
    strategy: Mapping[str, Any],
) -> CEOStrategicBenchmarkDecision:
    """Validate one CEO strategic intelligence benchmark/strategy artifact."""

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

    missing_sections = [section for section in REQUIRED_STRATEGY_SECTIONS if section not in strategy]
    if missing_sections:
        return _revision(
            "strategy artifact is missing required sections",
            strategy,
            "strategy_schema",
            missing_sections,
        )

    routes = _as_list(strategy.get("route_candidates"))
    if len(routes) < 5:
        return _revision(
            "at least five route candidates are required",
            strategy,
            "route_candidates",
            ["add at least five commercially distinct route candidates"],
        )

    scoring = _as_list(strategy.get("route_scoring"))
    if len(scoring) < 5:
        return _revision(
            "route scoring must cover at least five routes",
            strategy,
            "route_scoring",
            ["score each route against speed, pain, proof, readiness, friction, differentiation, trust, owner burden, validation step, and kill criteria"],
        )

    selected = strategy.get("selected_strategy")
    if not isinstance(selected, Mapping):
        return _revision(
            "selected_strategy must be structured",
            strategy,
            "selected_strategy",
            ["add selected_strategy with first-cash path, second-best path, why-this, why-not-others, falsification, 48h action, 7d action, and owner decision"],
        )
    for key in (
        "current_best_first_cash_path",
        "second_best_path",
        "why_this_path_now",
        "why_not_others",
        "what_evidence_could_falsify_it",
        "next_48h_action",
        "next_7d_action",
        "next_owner_decision_needed",
    ):
        if not _present(selected.get(key)):
            return _revision(
                f"selected_strategy.{key} is required",
                strategy,
                "selected_strategy",
                [f"fill selected_strategy.{key}"],
            )

    evidence = strategy.get("external_market_evidence_map")
    if not isinstance(evidence, Mapping):
        return _revision(
            "external_market_evidence_map must be structured",
            strategy,
            "external_market_evidence_map",
            ["declare external evidence freshness and include public-read evidence items"],
        )
    if not _present(evidence.get("freshness_status")):
        return _revision(
            "external evidence freshness must be declared",
            strategy,
            "external_market_evidence_map",
            ["set external_market_evidence_map.freshness_status"],
        )
    if len(_as_list(evidence.get("evidence_items"))) < 8:
        return _revision(
            "at least eight public-read evidence items are required for this benchmark",
            strategy,
            "external_market_evidence_map",
            ["attach at least eight public-read evidence items or explicitly mark the run as insufficient"],
        )

    l4_packet = strategy.get("next_L4_feedback_owner_decision_packet")
    if not isinstance(l4_packet, Mapping):
        return _revision(
            "next L4 feedback owner decision packet is required",
            strategy,
            "next_L4_feedback_owner_decision_packet",
            ["add no-send owner-decision packet for the next L4 feedback action"],
        )
    if l4_packet.get("no_send_default") is not True:
        return _decision(
            "DENY",
            "next L4 packet must default to no-send",
            strategy,
            "next_L4_feedback_owner_decision_packet",
            ["no_send_default_missing"],
        )
    if l4_packet.get("external_action_executed") is True or l4_packet.get("provider_action_executed") is True:
        return _decision(
            "DENY",
            "strategy artifact may not execute external/provider action",
            strategy,
            "next_L4_feedback_owner_decision_packet",
            ["external_execution_forbidden"],
        )
    if l4_packet.get("owner_decision_required") is not True:
        return _revision(
            "next L4 packet must be owner-decision gated",
            strategy,
            "next_L4_feedback_owner_decision_packet",
            ["set owner_decision_required=true and owner_approval_state=pending_owner_decision"],
        )

    predictions = _as_list(strategy.get("CIEU_predictions"))
    if not predictions:
        return _revision(
            "CIEU predictions are required",
            strategy,
            "CIEU_predictions",
            ["add future-verifiable CIEU predictions"],
        )
    for prediction in predictions:
        if not isinstance(prediction, Mapping):
            return _revision("CIEU prediction must be structured", strategy, "CIEU_predictions", [])
        missing = [field for field in REQUIRED_CIEU_PREDICTION_FIELDS if not _present(prediction.get(field))]
        if missing:
            return _revision(
                "CIEU prediction is missing required fields",
                strategy,
                "CIEU_predictions",
                [f"fill CIEU prediction fields: {', '.join(missing)}"],
            )

    benchmark = strategy.get("benchmark_result")
    if not isinstance(benchmark, Mapping):
        return _revision(
            "benchmark_result is required",
            strategy,
            "benchmark_result",
            ["run deterministic CEO strategic intelligence benchmark"],
        )
    if benchmark.get("benchmark_decision") == "DENY":
        return _decision(
            "DENY",
            "deterministic benchmark denied the strategy artifact",
            strategy,
            "benchmark_result",
            list(benchmark.get("failed_dimensions") or ["benchmark_failed"]),
        )
    if benchmark.get("pass") is not True:
        return _revision(
            "deterministic benchmark did not pass",
            strategy,
            "benchmark_result",
            list(benchmark.get("required_revisions") or ["repair failed benchmark dimensions"]),
        )

    if strategy.get("execute_L4_now") is True and str(l4_packet.get("owner_approval_state")) != "approved":
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
                "stop before L4 external feedback execution",
                "present owner decision packet",
                "rerun strategy governance after explicit owner approval",
            ],
            requires_owner_decision=True,
        )

    return _decision("ALLOW", "CEO strategic intelligence benchmark satisfies governance contract", strategy)


def build_ceo_strategic_benchmark_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOStrategicBenchmarkDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, CEOStrategicBenchmarkDecision) else dict(decision)
    decision_value = str(decision_data.get("decision") or "DENY")
    selected = strategy.get("selected_strategy") if isinstance(strategy.get("selected_strategy"), Mapping) else {}
    benchmark = strategy.get("benchmark_result") if isinstance(strategy.get("benchmark_result"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(strategy.get("session_id") or "e90_ceo_strategy_benchmark_session"),
        "agent_id": "bridge_labs_ceo",
        "event_type": CEO_STRATEGIC_BENCHMARK_CIEU_EVENT_TYPE,
        "decision": _decision_to_cieu_decision(decision_value),
        "passed": decision_value == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_value != "ALLOW",
        "drift_details": None if decision_value == "ALLOW" else decision_data.get("reason"),
        "task_description": "CEO strategic intelligence benchmark governance decision",
        "contract_hash": "ceo-strategic-intelligence-benchmark-v1",
        "params": {
            "strategy_run_id": strategy.get("strategy_run_id"),
            "route_count": len(_as_list(strategy.get("route_candidates"))),
            "external_evidence_count": len(_as_list((strategy.get("external_market_evidence_map") or {}).get("evidence_items") if isinstance(strategy.get("external_market_evidence_map"), Mapping) else [])),
            "external_evidence_freshness": (strategy.get("external_market_evidence_map") or {}).get("freshness_status") if isinstance(strategy.get("external_market_evidence_map"), Mapping) else None,
            "next_L4_no_send_default": (strategy.get("next_L4_feedback_owner_decision_packet") or {}).get("no_send_default") if isinstance(strategy.get("next_L4_feedback_owner_decision_packet"), Mapping) else None,
        },
        "result": {
            "decision": decision_value,
            "reason": decision_data.get("reason"),
            "selected_first_cash_path": selected.get("current_best_first_cash_path"),
            "second_best_path": selected.get("second_best_path"),
            "strategic_intelligence_score": benchmark.get("strategic_intelligence_score"),
            "failed_dimensions": list(benchmark.get("failed_dimensions") or []),
            "correct_path": list(decision_data.get("correct_path") or [])[:8],
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
            "no_customer_revenue_payment_claim": True,
        },
        "human_initiator": strategy.get("human_initiator") or "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_value == "ALLOW",
    }


def write_ceo_strategic_benchmark_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOStrategicBenchmarkDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    if not cieu_db:
        raise ValueError("cieu_db is required")
    record = build_ceo_strategic_benchmark_cieu_record(strategy, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_strategic_benchmark_formal_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "formal_CIEU_log_module": "ystar.governance.ceo_strategic_intelligence_benchmark",
        "formal_CIEU_log_function": "write_ceo_strategic_benchmark_cieu_record",
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_strategic_intelligence_strategy(
    strategy: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_strategic_intelligence_strategy(strategy)
    write_result = write_ceo_strategic_benchmark_cieu_record(
        strategy,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_strategic_benchmark_validate_and_write_result",
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
) -> CEOStrategicBenchmarkDecision:
    decision_value = CEOStrategicBenchmarkDecisionValue(value)
    provisional = CEOStrategicBenchmarkDecision(
        decision=decision_value,
        reason=reason,
        failed_section=failed_section,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
    )
    return CEOStrategicBenchmarkDecision(
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
) -> CEOStrategicBenchmarkDecision:
    correct_path = [
        "repair the CEO strategic intelligence artifact before accepting the strategy run",
        "do not execute L4/L5/customer/revenue/payment action while decision is REQUIRE_REVISION",
        "rerun validate_ceo_strategic_intelligence_strategy after repair",
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


def _validation_candidate(strategy: Mapping[str, Any], decision: CEOStrategicBenchmarkDecision) -> dict[str, Any]:
    return {
        "X_t": {
            "contract_id": "ceo_strategic_intelligence_benchmark_v1",
            "strategy_run_id": strategy.get("strategy_run_id"),
        },
        "U_t": "Y-star-gov deterministic CEO strategic intelligence benchmark validation",
        "Y_star_t": "CEO strategy must be evidence-bound, counterfactual, commercially sharp, and no-send gated",
        "Y_t_plus_1": {
            "decision": decision.decision.value,
            "reason": decision.reason,
            "failed_section": decision.failed_section,
            "correct_path": list(decision.correct_path),
        },
        "R_t_plus_1": "none" if decision.decision == CEOStrategicBenchmarkDecisionValue.ALLOW else decision.reason,
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
    "CEO_STRATEGIC_BENCHMARK_CIEU_EVENT_TYPE",
    "CEOStrategicBenchmarkDecision",
    "CEOStrategicBenchmarkDecisionValue",
    "build_ceo_strategic_benchmark_cieu_record",
    "validate_ceo_strategic_intelligence_strategy",
    "validate_and_write_ceo_strategic_intelligence_strategy",
    "write_ceo_strategic_benchmark_cieu_record",
]
