"""Deterministic governance for refreshed CEO market strategy runs.

This contract turns the post-E100 critique into a runtime obligation. A CEO
strategy run is not allowed to treat old brain memory, a static evidence map,
or a recent chat summary as sufficient market intelligence. It must prove that
the strategy passed through seven explicit market-refresh gates and then write
the decision through the existing CIEUStore path.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class CEOMarketStrategyRefreshDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOMarketStrategyRefreshDecision:
    decision: CEOMarketStrategyRefreshDecisionValue
    reason: str
    failed_gate: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_market_strategy_refresh_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOMarketStrategyRefreshDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_gate": self.failed_gate,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


CEO_MARKET_STRATEGY_REFRESH_CIEU_EVENT_TYPE = "CEO_MARKET_STRATEGY_REFRESH_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_REFRESH_GATES: tuple[str, ...] = (
    "live_market_evidence_refresh_gate",
    "competitor_saturation_scan",
    "founder_market_fit_gate",
    "customer_visible_differentiation_gate",
    "price_hypothesis_source_audit",
    "strategy_residual_intake",
    "open_world_research_trigger",
)

REQUIRED_COMPETITORS: tuple[str, ...] = (
    "black_ore",
    "basis",
    "juno",
    "cpa_pilot",
    "aiwyn",
    "canopy",
    "karbon",
    "taxdome",
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


def build_ceo_market_strategy_refresh_contract() -> dict[str, Any]:
    return {
        "contract_id": "ceo_market_strategy_refresh_contract_v1",
        "event_type": CEO_MARKET_STRATEGY_REFRESH_CIEU_EVENT_TYPE,
        "required_gates": list(REQUIRED_REFRESH_GATES),
        "required_competitor_coverage": list(REQUIRED_COMPETITORS),
        "decision_semantics": ["ALLOW", "REQUIRE_REVISION", "DENY", "ESCALATE"],
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "external_action_allowed": False,
        "live_provider_execution_allowed": False,
    }


def validate_ceo_market_strategy_refresh(
    strategy: Mapping[str, Any],
) -> CEOMarketStrategyRefreshDecision:
    """Validate that a CEO strategy run used current market intelligence gates."""

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
            "market strategy refresh may not execute external/provider action",
            strategy,
            "execution_boundary",
            ["external_or_provider_execution_forbidden"],
        )

    gates = strategy.get("adaptive_market_governance_gates")
    if not isinstance(gates, Mapping):
        return _revision(
            "adaptive_market_governance_gates is required",
            strategy,
            "adaptive_market_governance_gates",
            [
                "run live market evidence refresh, competitor saturation, founder-market fit, "
                "customer-visible differentiation, price source audit, residual intake, and open-world search gates"
            ],
        )

    missing = [gate for gate in REQUIRED_REFRESH_GATES if gate not in gates]
    if missing:
        return _revision(
            "required market strategy refresh gates are missing",
            strategy,
            "adaptive_market_governance_gates",
            [f"add required gates: {', '.join(missing)}"],
        )

    for gate_id in REQUIRED_REFRESH_GATES:
        gate = gates.get(gate_id)
        if not isinstance(gate, Mapping):
            return _revision(
                "market refresh gate must be structured",
                strategy,
                gate_id,
                [f"replace {gate_id} with a structured gate record"],
            )
        if gate.get("gate_passed") is not True:
            return _revision(
                f"{gate_id} did not pass",
                strategy,
                gate_id,
                list(gate.get("correct_path") or [f"repair and rerun {gate_id}"]),
            )

    evidence_decision = _validate_live_market_evidence(strategy, gates["live_market_evidence_refresh_gate"])
    if evidence_decision is not None:
        return evidence_decision

    competitor_decision = _validate_competitor_saturation(gates["competitor_saturation_scan"])
    if competitor_decision is not None:
        return competitor_decision

    founder_decision = _validate_founder_market_fit(strategy, gates["founder_market_fit_gate"])
    if founder_decision is not None:
        return founder_decision

    differentiation_decision = _validate_customer_visible_differentiation(
        gates["customer_visible_differentiation_gate"]
    )
    if differentiation_decision is not None:
        return differentiation_decision

    price_decision = _validate_price_audit(gates["price_hypothesis_source_audit"])
    if price_decision is not None:
        return price_decision

    residual_decision = _validate_strategy_residual_intake(gates["strategy_residual_intake"])
    if residual_decision is not None:
        return residual_decision

    open_world_decision = _validate_open_world_search(strategy, gates["open_world_research_trigger"])
    if open_world_decision is not None:
        return open_world_decision

    packet = strategy.get("next_L4_feedback_owner_decision_packet")
    if not isinstance(packet, Mapping):
        return _revision(
            "next L4 owner decision packet is required",
            strategy,
            "next_L4_feedback_owner_decision_packet",
            ["prepare a no-send owner decision packet; do not contact anyone"],
        )
    if packet.get("no_send_default") is not True or packet.get("owner_decision_required") is not True:
        return _decision(
            "DENY",
            "next L4 packet must remain no-send and owner-decision gated",
            strategy,
            "next_L4_feedback_owner_decision_packet",
            ["l4_packet_not_owner_gated_no_send"],
        )
    if packet.get("external_action_executed") is True or packet.get("provider_action_executed") is True:
        return _decision(
            "DENY",
            "next L4 packet may not execute external/provider action",
            strategy,
            "next_L4_feedback_owner_decision_packet",
            ["external_execution_forbidden"],
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

    return _decision("ALLOW", "CEO market strategy refresh gates passed", strategy)


def build_ceo_market_strategy_refresh_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOMarketStrategyRefreshDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, CEOMarketStrategyRefreshDecision) else dict(decision)
    decision_value = str(decision_data.get("decision") or "DENY")
    selected = strategy.get("selected_strategy") if isinstance(strategy.get("selected_strategy"), Mapping) else {}
    gates = strategy.get("adaptive_market_governance_gates") if isinstance(strategy.get("adaptive_market_governance_gates"), Mapping) else {}
    evidence = strategy.get("external_market_evidence_map") if isinstance(strategy.get("external_market_evidence_map"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(strategy.get("session_id") or "e104_market_strategy_refresh_session"),
        "agent_id": "bridge_labs_ceo",
        "event_type": CEO_MARKET_STRATEGY_REFRESH_CIEU_EVENT_TYPE,
        "decision": _decision_to_cieu_decision(decision_value),
        "passed": decision_value == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_value != "ALLOW",
        "drift_details": None if decision_value == "ALLOW" else decision_data.get("reason"),
        "task_description": "CEO adaptive market strategy refresh governance decision",
        "contract_hash": "ceo-market-strategy-refresh-v1",
        "params": {
            "strategy_run_id": strategy.get("strategy_run_id"),
            "selected_route_id": selected.get("selected_route_id"),
            "external_evidence_count": len(_as_list(evidence.get("evidence_items"))),
            "external_evidence_freshness": evidence.get("freshness_status"),
            "required_gates": list(REQUIRED_REFRESH_GATES),
            "gate_count": len(gates),
            "competitor_count": len(_as_list((gates.get("competitor_saturation_scan") or {}).get("competitors")) if isinstance(gates.get("competitor_saturation_scan"), Mapping) else []),
        },
        "result": {
            "decision": decision_value,
            "reason": decision_data.get("reason"),
            "selected_route_id": selected.get("selected_route_id"),
            "selected_first_cash_path": selected.get("current_best_first_cash_path"),
            "failed_gate": decision_data.get("failed_gate"),
            "correct_path": list(decision_data.get("correct_path") or [])[:10],
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
            "market_refresh_gates_required": True,
            "no_external_action_executed": True,
            "no_customer_revenue_payment_claim": True,
        },
        "human_initiator": strategy.get("human_initiator") or "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_value == "ALLOW",
    }


def write_ceo_market_strategy_refresh_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOMarketStrategyRefreshDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    if not cieu_db:
        raise ValueError("cieu_db is required")
    record = build_ceo_market_strategy_refresh_cieu_record(strategy, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_market_strategy_refresh_formal_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "formal_CIEU_log_module": "ystar.governance.ceo_market_strategy_refresh_contract",
        "formal_CIEU_log_function": "write_ceo_market_strategy_refresh_cieu_record",
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_market_strategy_refresh(
    strategy: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_market_strategy_refresh(strategy)
    write_result = write_ceo_market_strategy_refresh_cieu_record(
        strategy,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_market_strategy_refresh_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _validate_live_market_evidence(
    strategy: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> CEOMarketStrategyRefreshDecision | None:
    evidence = strategy.get("external_market_evidence_map")
    if not isinstance(evidence, Mapping):
        return _revision(
            "external_market_evidence_map is required",
            strategy,
            "live_market_evidence_refresh_gate",
            ["attach current public-read evidence items"],
        )
    freshness = str(evidence.get("freshness_status") or gate.get("freshness_status") or "")
    if "2026-05-08" not in freshness and "current_public_read" not in freshness:
        return _revision(
            "external market evidence must declare current public-read freshness",
            strategy,
            "live_market_evidence_refresh_gate",
            ["refresh public-read evidence and set freshness_status with the run date"],
        )
    evidence_items = _as_list(evidence.get("evidence_items"))
    if len(evidence_items) < 10:
        return _revision(
            "at least ten current public-read evidence items are required",
            strategy,
            "live_market_evidence_refresh_gate",
            ["collect at least ten current public-read evidence items before strategy selection"],
        )
    missing_urls = [item for item in evidence_items if not isinstance(item, Mapping) or not _present(item.get("source_url"))]
    if missing_urls:
        return _revision(
            "each evidence item needs a source_url",
            strategy,
            "live_market_evidence_refresh_gate",
            ["attach source_url to every public-read evidence item"],
        )
    return None


def _validate_competitor_saturation(gate: Mapping[str, Any]) -> CEOMarketStrategyRefreshDecision | None:
    competitors = _as_list(gate.get("competitors"))
    competitor_ids = {str(item.get("competitor_id") or "").lower() for item in competitors if isinstance(item, Mapping)}
    missing = [item for item in REQUIRED_COMPETITORS if item not in competitor_ids]
    offshore_present = any("offshore" in item or "madras" in item for item in competitor_ids)
    if missing or not offshore_present:
        required = missing + ([] if offshore_present else ["offshore_or_madras_accountancy"])
        return _revision(
            "competitor saturation scan is missing high-signal CPA/offshore alternatives",
            gate,
            "competitor_saturation_scan",
            ["include competitor coverage: " + ", ".join(required)],
        )
    if str(gate.get("saturation_level") or "").lower() not in {"high", "very_high", "crowded"}:
        return _revision(
            "competitor saturation level must honestly mark CPA AI/workflow as crowded",
            gate,
            "competitor_saturation_scan",
            ["set saturation_level to high/very_high/crowded when CPA route is evaluated"],
        )
    return None


def _validate_founder_market_fit(
    strategy: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> CEOMarketStrategyRefreshDecision | None:
    selected = strategy.get("selected_strategy") if isinstance(strategy.get("selected_strategy"), Mapping) else {}
    selected_route = str(selected.get("selected_route_id") or strategy.get("selected_route_id") or "")
    if gate.get("founder_is_cpa") is True:
        return _revision(
            "founder-market fit gate must not claim the founder is CPA",
            strategy,
            "founder_market_fit_gate",
            ["record founder_is_cpa=false and score regulated accounting routes accordingly"],
        )
    route_scores = gate.get("route_fit_scores")
    if not isinstance(route_scores, Mapping) or selected_route not in route_scores:
        return _revision(
            "founder-market fit must score the selected route",
            strategy,
            "founder_market_fit_gate",
            ["score founder-market fit for every serious route candidate"],
        )
    if int(route_scores.get(selected_route) or 0) < 4:
        return _revision(
            "selected route has weak founder-market fit",
            strategy,
            "founder_market_fit_gate",
            ["select a route with founder-market fit >=4 or justify why owner approval should override"],
        )
    if int(route_scores.get("cpa_review_bottleneck_rescue") or 0) > 3:
        return _revision(
            "CPA route founder-market fit should be penalized unless CPA credentials exist",
            strategy,
            "founder_market_fit_gate",
            ["demote CPA review route or attach credible CPA-domain partner evidence"],
        )
    return None


def _validate_customer_visible_differentiation(
    gate: Mapping[str, Any],
) -> CEOMarketStrategyRefreshDecision | None:
    visible = _as_list(gate.get("visible_customer_outcomes"))
    if len(visible) < 3:
        return _revision(
            "customer-visible differentiation needs at least three visible outcomes",
            gate,
            "customer_visible_differentiation_gate",
            ["replace internal-only technology claims with buyer-visible outcomes"],
        )
    internal_only = str(gate.get("internal_only_claims_disallowed") or "").lower()
    if internal_only not in {"true", "yes", "1"} and gate.get("internal_only_claims_disallowed") is not True:
        return _revision(
            "internal-only technical claims cannot be the primary customer differentiation",
            gate,
            "customer_visible_differentiation_gate",
            ["mark internal_only_claims_disallowed=true and describe buyer-visible outcomes"],
        )
    return None


def _validate_price_audit(gate: Mapping[str, Any]) -> CEOMarketStrategyRefreshDecision | None:
    status = str(gate.get("validation_status") or "").lower()
    if status != "hypothesis_only_not_validated":
        return _revision(
            "price hypothesis must be marked as hypothesis only",
            gate,
            "price_hypothesis_source_audit",
            ["set validation_status=hypothesis_only_not_validated until real buyer evidence exists"],
        )
    if len(_as_list(gate.get("source_refs"))) < 2:
        return _revision(
            "price hypothesis requires source references",
            gate,
            "price_hypothesis_source_audit",
            ["attach at least two pricing or consulting analog source refs"],
        )
    return None


def _validate_strategy_residual_intake(gate: Mapping[str, Any]) -> CEOMarketStrategyRefreshDecision | None:
    residuals = _as_list(gate.get("residuals_ingested"))
    if not residuals:
        return _revision(
            "strategy residual intake is required",
            gate,
            "strategy_residual_intake",
            ["ingest the red-team residual that found stale market data and founder-market fit gaps"],
        )
    text = _text(gate)
    for phrase in ("competitor", "founder-market fit", "stale"):
        if phrase not in text:
            return _revision(
                "strategy residual intake must preserve competitor, founder-market fit, and stale-data lessons",
                gate,
                "strategy_residual_intake",
                ["record competitor saturation, founder-market fit, and stale market data lessons"],
            )
    return None


def _validate_open_world_search(
    strategy: Mapping[str, Any],
    gate: Mapping[str, Any],
) -> CEOMarketStrategyRefreshDecision | None:
    domains = _as_list(gate.get("domains_compared"))
    if len(domains) < 5:
        return _revision(
            "open-world strategy search must compare at least five domains",
            strategy,
            "open_world_research_trigger",
            ["compare at least five materially different domains before selecting a route"],
        )
    selected = strategy.get("selected_strategy") if isinstance(strategy.get("selected_strategy"), Mapping) else {}
    selected_route = str(selected.get("selected_route_id") or "")
    if not selected_route:
        return _revision(
            "selected strategy must include selected_route_id",
            strategy,
            "open_world_research_trigger",
            ["set selected_strategy.selected_route_id after open-world comparison"],
        )
    domain_ids = {str(item.get("route_id") or item.get("domain_id") or "") for item in domains if isinstance(item, Mapping)}
    if selected_route not in domain_ids:
        return _revision(
            "selected route must come from the open-world search comparison",
            strategy,
            "open_world_research_trigger",
            ["select only from domains/routes compared by the open-world search"],
        )
    return None


def _decision(
    value: str,
    reason: str,
    strategy: Mapping[str, Any],
    failed_gate: str | None = None,
    violations: list[str] | None = None,
    *,
    guidance: dict[str, Any] | None = None,
    correct_path: list[str] | None = None,
    requires_owner_decision: bool = False,
) -> CEOMarketStrategyRefreshDecision:
    decision_value = CEOMarketStrategyRefreshDecisionValue(value)
    provisional = CEOMarketStrategyRefreshDecision(
        decision=decision_value,
        reason=reason,
        failed_gate=failed_gate,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
    )
    return CEOMarketStrategyRefreshDecision(
        decision=decision_value,
        reason=reason,
        failed_gate=failed_gate,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
        cieu_validation_record=_validation_candidate(strategy, provisional),
    )


def _revision(
    reason: str,
    strategy: Mapping[str, Any],
    failed_gate: str,
    required_changes: list[str],
) -> CEOMarketStrategyRefreshDecision:
    correct_path = [
        "repair the CEO market strategy refresh artifact before accepting the strategy run",
        "do not execute L4/L5/customer/revenue/payment action while decision is REQUIRE_REVISION",
        "rerun validate_ceo_market_strategy_refresh after repair",
        *required_changes,
    ]
    return _decision(
        "REQUIRE_REVISION",
        reason,
        strategy,
        failed_gate,
        required_changes,
        guidance={
            "guidance_type": "require_revision",
            "failed_gate": failed_gate,
            "required_strategy_changes": required_changes,
            "correct_path": correct_path,
            "execution_allowed_before_revision": False,
            "revalidate_after_revision": True,
        },
        correct_path=correct_path,
    )


def _validation_candidate(
    strategy: Mapping[str, Any],
    decision: CEOMarketStrategyRefreshDecision,
) -> dict[str, Any]:
    return {
        "X_t": {
            "contract_id": "ceo_market_strategy_refresh_contract_v1",
            "strategy_run_id": strategy.get("strategy_run_id"),
        },
        "U_t": "Y-star-gov deterministic CEO market strategy refresh validation",
        "Y_star_t": "CEO strategy must refresh market evidence, saturation, founder fit, differentiation, pricing, residual, and open-world routes",
        "Y_t_plus_1": {
            "decision": decision.decision.value,
            "reason": decision.reason,
            "failed_gate": decision.failed_gate,
            "correct_path": list(decision.correct_path),
        },
        "R_t_plus_1": "none" if decision.decision == CEOMarketStrategyRefreshDecisionValue.ALLOW else decision.reason,
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
    "CEO_MARKET_STRATEGY_REFRESH_CIEU_EVENT_TYPE",
    "CEOMarketStrategyRefreshDecision",
    "CEOMarketStrategyRefreshDecisionValue",
    "build_ceo_market_strategy_refresh_contract",
    "build_ceo_market_strategy_refresh_cieu_record",
    "validate_and_write_ceo_market_strategy_refresh",
    "validate_ceo_market_strategy_refresh",
    "write_ceo_market_strategy_refresh_cieu_record",
]
