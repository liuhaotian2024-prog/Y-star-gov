"""Governance for market-first CEO strategy math models.

This contract prevents CEO strategy from being ranked by arbitrary local
weights or internal-capability comfort. It requires a structured mathematical
model grounded in recognized decision-analysis and strategy frameworks, then
records the decision in CIEUStore.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class CEOStrategyMathModelDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOStrategyMathModelDecision:
    decision: CEOStrategyMathModelDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_strategy_math_model_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOStrategyMathModelDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


CEO_STRATEGY_MATH_MODEL_CIEU_EVENT_TYPE = "CEO_STRATEGY_MATH_MODEL_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_SOURCE_KEYS: tuple[str, ...] = (
    "multi_attribute_utility",
    "analytic_hierarchy_process",
    "expected_utility",
    "value_of_information",
    "competitive_forces",
    "adoption_diffusion",
    "business_model_canvas",
    "product_market_fit_measurement",
    "rice_prioritization",
)

REQUIRED_PARAMETER_KEYS: tuple[str, ...] = (
    "price_midpoint_usd",
    "market_pull_probability",
    "willingness_to_pay_probability",
    "distribution_access_probability",
    "trust_access_probability",
    "delivery_success_probability",
    "time_to_first_signal_days",
    "validation_cost_usd",
    "competition_penalty",
    "regulatory_penalty",
    "uncertainty_penalty",
    "internal_capability_feasibility",
    "evsi_usd",
)

REQUIRED_ROUTE_SCORE_FIELDS: tuple[str, ...] = (
    "route_id",
    "expected_first_cash_value_usd",
    "market_pull_probability",
    "willingness_to_pay_probability",
    "distribution_access_probability",
    "trust_access_probability",
    "delivery_success_probability",
    "time_to_first_signal_days",
    "validation_cost_usd",
    "competition_penalty",
    "regulatory_penalty",
    "uncertainty_penalty",
    "internal_capability_feasibility",
    "market_first_score",
    "evsi_usd",
    "evidence_refs",
    "math_model_decision_basis",
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


def build_ceo_strategy_math_model_contract() -> dict[str, Any]:
    return {
        "contract_id": "ceo_strategy_math_model_contract_v1",
        "event_type": CEO_STRATEGY_MATH_MODEL_CIEU_EVENT_TYPE,
        "required_source_keys": list(REQUIRED_SOURCE_KEYS),
        "required_parameter_keys": list(REQUIRED_PARAMETER_KEYS),
        "required_route_score_fields": list(REQUIRED_ROUTE_SCORE_FIELDS),
        "minimum_route_math_scores": 5,
        "internal_capability_role": "feasibility_multiplier_not_primary_selector",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "external_action_allowed": False,
        "live_provider_execution_allowed": False,
    }


def validate_ceo_strategy_math_model(strategy: Mapping[str, Any]) -> CEOStrategyMathModelDecision:
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
            "strategy math model run may not execute external/provider action",
            strategy,
            "execution_boundary",
            ["external_or_provider_execution_forbidden"],
        )

    model = strategy.get("strategy_math_model")
    if not isinstance(model, Mapping):
        return _revision(
            "strategy_math_model is required",
            strategy,
            "strategy_math_model",
            ["build the market-first mathematical model before accepting the strategy"],
        )

    if str(model.get("generation_mode") or "") in {"static_template", "recent_memory_summary", "arbitrary_weights"}:
        return _revision(
            "strategy math model cannot be static, recent-memory-only, or arbitrary-weight based",
            strategy,
            "generation_mode",
            ["derive parameters from source-backed model families and current evidence"],
        )

    role = str(model.get("internal_capability_role") or "")
    if role != "feasibility_multiplier_not_primary_selector":
        return _revision(
            "internal capability must be a feasibility multiplier, not the primary selector",
            strategy,
            "internal_capability_role",
            ["set internal_capability_role to feasibility_multiplier_not_primary_selector"],
        )

    primary_selector = str(model.get("primary_selector") or "").lower()
    if primary_selector in {"internal_capability_fit", "founder_fit", "repo_capability_fit"}:
        return _decision(
            "DENY",
            "internal capability cannot be the primary strategy selector",
            strategy,
            "primary_selector",
            ["internal_capability_as_primary_selector"],
        )

    source_map = strategy.get("mathematical_source_map") or model.get("mathematical_source_map")
    if not isinstance(source_map, Mapping):
        return _revision(
            "mathematical_source_map is required",
            strategy,
            "mathematical_source_map",
            ["attach canonical source-backed model references and their role in the scoring function"],
        )
    missing_sources = [key for key in REQUIRED_SOURCE_KEYS if key not in source_map]
    if missing_sources:
        return _revision(
            "mathematical source map is missing required model families",
            strategy,
            "mathematical_source_map",
            ["add missing source keys: " + ", ".join(missing_sources)],
        )
    for key in REQUIRED_SOURCE_KEYS:
        source = source_map.get(key)
        if not isinstance(source, Mapping) or not _present(source.get("source_url")) or not _present(source.get("model_role")):
            return _revision(
                "each mathematical source needs source_url and model_role",
                strategy,
                "mathematical_source_map",
                [f"repair source mapping for {key}"],
            )

    registry = strategy.get("parameter_registry") or model.get("parameter_registry")
    if not isinstance(registry, Mapping):
        return _revision(
            "parameter_registry is required",
            strategy,
            "parameter_registry",
            ["define every model parameter with source family, calibration status, and allowed range"],
        )
    missing_params = [key for key in REQUIRED_PARAMETER_KEYS if key not in registry]
    if missing_params:
        return _revision(
            "parameter registry is missing required parameters",
            strategy,
            "parameter_registry",
            ["add missing parameters: " + ", ".join(missing_params)],
        )
    for key in REQUIRED_PARAMETER_KEYS:
        param = registry.get(key)
        if not isinstance(param, Mapping) or not _present(param.get("definition")) or not _present(param.get("source_family")):
            return _revision(
                "each parameter needs definition and source_family",
                strategy,
                "parameter_registry",
                [f"repair parameter definition for {key}"],
            )
        if str(param.get("calibration_status") or "") in {"", "arbitrary", "unknown"}:
            return _revision(
                "parameters cannot have arbitrary/unknown calibration status",
                strategy,
                "parameter_registry",
                [f"mark {key} as evidence_derived, prior_estimate, or requires_validation"],
            )

    route_scores = _as_list(strategy.get("route_math_scores") or strategy.get("mathematical_route_ranking"))
    if len(route_scores) < 5:
        return _revision(
            "strategy must score at least five routes with the math model",
            strategy,
            "route_math_scores",
            ["score at least five materially different routes"],
        )
    for row in route_scores:
        if not isinstance(row, Mapping):
            return _revision("route_math_scores rows must be mappings", strategy, "route_math_scores", ["repair route rows"])
        missing = [field for field in REQUIRED_ROUTE_SCORE_FIELDS if field not in row]
        if missing:
            return _revision(
                "route math score is missing required fields",
                strategy,
                "route_math_scores",
                [f"route {row.get('route_id')} missing: " + ", ".join(missing)],
            )
        if not _as_list(row.get("evidence_refs")):
            return _revision(
                "each scored route must include evidence refs",
                strategy,
                "route_math_scores",
                [f"add evidence_refs for {row.get('route_id')}"],
            )
        if _number(row.get("market_first_score")) is None:
            return _revision(
                "market_first_score must be numeric",
                strategy,
                "route_math_scores",
                [f"repair numeric score for {row.get('route_id')}"],
            )

    sorted_scores = sorted(route_scores, key=lambda item: float(item.get("market_first_score") or 0), reverse=True)
    selected = strategy.get("selected_strategy") if isinstance(strategy.get("selected_strategy"), Mapping) else {}
    selected_route = str(selected.get("selected_route_id") or "")
    if not selected_route:
        return _revision(
            "selected_strategy.selected_route_id is required",
            strategy,
            "selected_strategy",
            ["select the top mathematical route or attach override justification"],
        )
    top_route = str(sorted_scores[0].get("route_id") or "")
    if selected_route != top_route and not _present(selected.get("math_model_override_justification")):
        return _revision(
            "selected route must match top math score unless an override is justified",
            strategy,
            "selected_strategy",
            [f"select {top_route} or add math_model_override_justification"],
        )

    validation = strategy.get("validation_experiment_design") or model.get("validation_experiment_design")
    if not isinstance(validation, Mapping):
        return _revision(
            "validation_experiment_design is required",
            strategy,
            "validation_experiment_design",
            ["design the next EVSI/VOI-ranked no-send validation experiment"],
        )
    if validation.get("no_send_default") is not True or validation.get("owner_decision_required") is not True:
        return _decision(
            "DENY",
            "validation experiment must be no-send and owner-decision gated",
            strategy,
            "validation_experiment_design",
            ["validation_experiment_not_owner_gated"],
        )
    if _number(validation.get("expected_value_of_sample_information_usd")) is None:
        return _revision(
            "validation experiment must include expected value of sample information",
            strategy,
            "validation_experiment_design",
            ["compute expected_value_of_sample_information_usd for the next test"],
        )

    if strategy.get("execute_L4_now") is True:
        return _decision(
            "ESCALATE",
            "math-ranked strategy attempts owner-bound external execution",
            strategy,
            "owner_approval_gate",
            ["owner_decision_required"],
            guidance={
                "guidance_type": "owner_decision_required",
                "owner_decision_path": "submit the no-send validation packet; do not execute outreach",
                "execution_allowed_before_owner_decision": False,
            },
            correct_path=[
                "stop before external execution",
                "present owner decision packet",
                "rerun governance after explicit owner approval",
            ],
            requires_owner_decision=True,
        )

    return _decision("ALLOW", "CEO strategy math model passed", strategy)


def build_ceo_strategy_math_model_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOStrategyMathModelDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, CEOStrategyMathModelDecision) else dict(decision)
    decision_value = str(decision_data.get("decision") or "DENY")
    model = strategy.get("strategy_math_model") if isinstance(strategy.get("strategy_math_model"), Mapping) else {}
    selected = strategy.get("selected_strategy") if isinstance(strategy.get("selected_strategy"), Mapping) else {}
    route_scores = _as_list(strategy.get("route_math_scores") or strategy.get("mathematical_route_ranking"))
    top = sorted(route_scores, key=lambda item: float(item.get("market_first_score") or 0), reverse=True)[0] if route_scores else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(strategy.get("session_id") or "e107_strategy_math_model_session"),
        "agent_id": "bridge_labs_ceo",
        "event_type": CEO_STRATEGY_MATH_MODEL_CIEU_EVENT_TYPE,
        "decision": _decision_to_cieu_decision(decision_value),
        "passed": decision_value == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_value != "ALLOW",
        "drift_details": None if decision_value == "ALLOW" else decision_data.get("reason"),
        "task_description": "CEO market-first strategy mathematical model governance decision",
        "contract_hash": "ceo-strategy-math-model-v1",
        "params": {
            "strategy_run_id": strategy.get("strategy_run_id"),
            "model_id": model.get("model_id"),
            "model_version": model.get("model_version"),
            "internal_capability_role": model.get("internal_capability_role"),
            "route_count": len(route_scores),
            "top_route_id": top.get("route_id"),
            "selected_route_id": selected.get("selected_route_id"),
        },
        "result": {
            "decision": decision_value,
            "reason": decision_data.get("reason"),
            "failed_section": decision_data.get("failed_section"),
            "correct_path": list(decision_data.get("correct_path") or [])[:10],
            "selected_route_id": selected.get("selected_route_id"),
            "top_route_id": top.get("route_id"),
            "top_market_first_score": top.get("market_first_score"),
            "top_evsi_usd": top.get("evsi_usd"),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
            "market_first_math_model_required": True,
            "internal_capability_not_primary_selector": True,
            "no_external_action_executed": True,
        },
        "human_initiator": strategy.get("human_initiator") or "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_value == "ALLOW",
    }


def write_ceo_strategy_math_model_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOStrategyMathModelDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    if not cieu_db:
        raise ValueError("cieu_db is required")
    record = build_ceo_strategy_math_model_cieu_record(strategy, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_strategy_math_model_formal_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "formal_CIEU_log_module": "ystar.governance.ceo_strategy_math_model_contract",
        "formal_CIEU_log_function": "write_ceo_strategy_math_model_cieu_record",
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_strategy_math_model(
    strategy: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_strategy_math_model(strategy)
    write_result = write_ceo_strategy_math_model_cieu_record(
        strategy,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_strategy_math_model_validate_and_write_result",
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
) -> CEOStrategyMathModelDecision:
    decision_value = CEOStrategyMathModelDecisionValue(value)
    provisional = CEOStrategyMathModelDecision(
        decision=decision_value,
        reason=reason,
        failed_section=failed_section,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
    )
    return CEOStrategyMathModelDecision(
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
) -> CEOStrategyMathModelDecision:
    correct_path = [
        "repair the CEO strategy math model before accepting the strategic conclusion",
        "do not execute L4/L5/customer/revenue/payment action while decision is REQUIRE_REVISION",
        "rerun validate_ceo_strategy_math_model after repair",
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


def _validation_candidate(strategy: Mapping[str, Any], decision: CEOStrategyMathModelDecision) -> dict[str, Any]:
    return {
        "X_t": {
            "contract_id": "ceo_strategy_math_model_contract_v1",
            "strategy_run_id": strategy.get("strategy_run_id"),
        },
        "U_t": "Y-star-gov deterministic CEO market-first strategy math validation",
        "Y_star_t": (
            "CEO strategy must use source-backed decision-analysis math and treat internal capability "
            "as feasibility, not as the primary selector"
        ),
        "Y_t_plus_1": {
            "decision": decision.decision.value,
            "reason": decision.reason,
            "failed_section": decision.failed_section,
            "correct_path": list(decision.correct_path),
        },
        "R_t_plus_1": "none" if decision.decision == CEOStrategyMathModelDecisionValue.ALLOW else decision.reason,
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


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_text(item)}" for key, item in value.items()).lower()
    if isinstance(value, list):
        return " ".join(_text(item) for item in value).lower()
    return str(value or "").lower()


__all__ = [
    "CEO_STRATEGY_MATH_MODEL_CIEU_EVENT_TYPE",
    "CEOStrategyMathModelDecision",
    "CEOStrategyMathModelDecisionValue",
    "REQUIRED_PARAMETER_KEYS",
    "REQUIRED_ROUTE_SCORE_FIELDS",
    "REQUIRED_SOURCE_KEYS",
    "build_ceo_strategy_math_model_contract",
    "build_ceo_strategy_math_model_cieu_record",
    "validate_and_write_ceo_strategy_math_model",
    "validate_ceo_strategy_math_model",
    "write_ceo_strategy_math_model_cieu_record",
]
