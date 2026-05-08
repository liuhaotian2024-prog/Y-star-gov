"""Governance for CEO competitive intelligence and source freshness.

Global strategy is not acceptable unless the CEO proves who else is solving the
same buyer pain, how current the evidence is, and why the selected route can
win against alternatives. This contract turns that into a runtime gate.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class CEOCompetitiveIntelligenceDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOCompetitiveIntelligenceDecision:
    decision: CEOCompetitiveIntelligenceDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_competitive_intelligence_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOCompetitiveIntelligenceDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


CEO_COMPETITIVE_INTELLIGENCE_CIEU_EVENT_TYPE = "CEO_COMPETITIVE_INTELLIGENCE_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

MIN_SELECTED_ROUTE_COMPETITORS = 5
MIN_TOP_ROUTE_COMPETITORS = 3
MIN_TOP_ROUTES_ANALYZED = 3
MIN_CURRENT_SOURCE_REFS = 5

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


def build_ceo_competitive_intelligence_contract() -> dict[str, Any]:
    return {
        "contract_id": "ceo_competitive_intelligence_contract_v1",
        "event_type": CEO_COMPETITIVE_INTELLIGENCE_CIEU_EVENT_TYPE,
        "minimum_selected_route_competitors": MIN_SELECTED_ROUTE_COMPETITORS,
        "minimum_top_route_competitors": MIN_TOP_ROUTE_COMPETITORS,
        "minimum_top_routes_analyzed": MIN_TOP_ROUTES_ANALYZED,
        "minimum_current_source_refs": MIN_CURRENT_SOURCE_REFS,
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
    }


def validate_ceo_competitive_intelligence(strategy: Mapping[str, Any]) -> CEOCompetitiveIntelligenceDecision:
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
            "competitive intelligence may not execute external/provider actions",
            strategy,
            "execution_boundary",
            ["external_or_provider_execution_forbidden"],
        )

    intel = strategy.get("competitive_intelligence")
    if not isinstance(intel, Mapping):
        return _revision(
            "competitive_intelligence is required",
            strategy,
            "competitive_intelligence",
            ["run competitive intelligence before selecting a global first-cash route"],
        )

    if intel.get("latest_source_policy_enforced") is not True:
        return _revision(
            "latest source freshness policy must be enforced",
            strategy,
            "latest_source_policy",
            ["attach current/latest source refs and explain stale-source handling"],
        )
    if intel.get("competitor_scan_mode") in {"", "none", "static_assumption", "memory_only"}:
        return _revision(
            "competitor scan cannot be memory-only or static assumption",
            strategy,
            "competitor_scan_mode",
            ["use live public-read or owner-supplied current public-read competitor evidence"],
        )
    if intel.get("substitute_analysis_present") is not True or intel.get("why_us_vs_alternatives_present") is not True:
        return _revision(
            "substitute analysis and why-us-vs-alternatives are required",
            strategy,
            "competitive_synthesis",
            ["add substitutes, incumbent workflows, and why-us-vs-alternatives"],
        )

    current_sources = _as_list(intel.get("current_source_refs"))
    if len(current_sources) < MIN_CURRENT_SOURCE_REFS:
        return _revision(
            "not enough current/latest sources were cited",
            strategy,
            "current_source_refs",
            [f"attach at least {MIN_CURRENT_SOURCE_REFS} current public-read source refs"],
        )

    selected = str((strategy.get("selected_strategy") or {}).get("selected_route_id") or "")
    selected_analysis = intel.get("selected_route_competition")
    if not isinstance(selected_analysis, Mapping) or str(selected_analysis.get("route_id") or "") != selected:
        return _revision(
            "selected route competitive analysis is required",
            strategy,
            "selected_route_competition",
            ["analyze direct competitors and substitutes for the selected route"],
        )

    selected_competitors = _as_list(selected_analysis.get("competitors"))
    if len(selected_competitors) < MIN_SELECTED_ROUTE_COMPETITORS:
        return _revision(
            "selected route needs at least five competitors/substitutes",
            strategy,
            "selected_route_competition",
            [f"add at least {MIN_SELECTED_ROUTE_COMPETITORS} competitors or substitutes for selected route"],
        )
    for competitor in selected_competitors:
        problem = _competitor_problem(competitor)
        if problem:
            return _revision(problem, strategy, "selected_route_competition", [problem])

    top_routes = _as_list(intel.get("top_route_competition"))
    if len(top_routes) < MIN_TOP_ROUTES_ANALYZED:
        return _revision(
            "top route competition analysis must cover at least three routes",
            strategy,
            "top_route_competition",
            [f"analyze at least {MIN_TOP_ROUTES_ANALYZED} top routes"],
        )
    for route in top_routes[:MIN_TOP_ROUTES_ANALYZED]:
        competitors = _as_list(route.get("competitors") if isinstance(route, Mapping) else None)
        if len(competitors) < MIN_TOP_ROUTE_COMPETITORS:
            return _revision(
                "each top route needs at least three competitors/substitutes",
                strategy,
                "top_route_competition",
                [f"repair competitors for route {route.get('route_id') if isinstance(route, Mapping) else 'unknown'}"],
            )

    if selected_analysis.get("winner_risk_level") not in {"low", "medium", "high"}:
        return _revision(
            "winner risk level is required",
            strategy,
            "winner_risk_level",
            ["set winner_risk_level and explain the risk"],
        )
    if not _present(selected_analysis.get("why_we_can_win")):
        return _revision(
            "why_we_can_win is required",
            strategy,
            "why_we_can_win",
            ["explain why buyer should pick us over direct alternatives"],
        )
    if not _present(selected_analysis.get("why_we_might_lose")):
        return _revision(
            "why_we_might_lose is required",
            strategy,
            "why_we_might_lose",
            ["state reasons we might lose despite selecting this route"],
        )

    if strategy.get("execute_L4_now") is True:
        return _decision(
            "ESCALATE",
            "competitive intelligence strategy attempts owner-bound L4 execution",
            strategy,
            "owner_approval_gate",
            ["owner_decision_required"],
            guidance={
                "guidance_type": "owner_decision_required",
                "owner_decision_path": "present owner-gated no-send validation packet; do not execute outreach",
                "execution_allowed_before_owner_decision": False,
            },
            correct_path=[
                "stop before external execution",
                "present owner decision packet",
                "rerun governance after explicit owner approval",
            ],
            requires_owner_decision=True,
        )

    return _decision("ALLOW", "CEO competitive intelligence passed", strategy)


def build_ceo_competitive_intelligence_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOCompetitiveIntelligenceDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, CEOCompetitiveIntelligenceDecision) else dict(decision)
    decision_value = str(decision_data.get("decision") or "DENY")
    intel = strategy.get("competitive_intelligence") if isinstance(strategy.get("competitive_intelligence"), Mapping) else {}
    selected = strategy.get("selected_strategy") if isinstance(strategy.get("selected_strategy"), Mapping) else {}
    selected_comp = intel.get("selected_route_competition") if isinstance(intel.get("selected_route_competition"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(strategy.get("session_id") or "e109_competitive_intelligence"),
        "agent_id": "bridge_labs_ceo",
        "event_type": CEO_COMPETITIVE_INTELLIGENCE_CIEU_EVENT_TYPE,
        "decision": _decision_to_cieu_decision(decision_value),
        "passed": decision_value == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_value != "ALLOW",
        "drift_details": None if decision_value == "ALLOW" else decision_data.get("reason"),
        "task_description": "CEO competitive intelligence and source freshness governance decision",
        "contract_hash": "ceo-competitive-intelligence-v1",
        "params": {
            "strategy_run_id": strategy.get("strategy_run_id"),
            "selected_route_id": selected.get("selected_route_id"),
            "competitor_scan_mode": intel.get("competitor_scan_mode"),
            "current_source_count": len(_as_list(intel.get("current_source_refs"))),
            "selected_route_competitor_count": len(_as_list(selected_comp.get("competitors"))),
            "top_route_competition_count": len(_as_list(intel.get("top_route_competition"))),
        },
        "result": {
            "decision": decision_value,
            "reason": decision_data.get("reason"),
            "failed_section": decision_data.get("failed_section"),
            "correct_path": list(decision_data.get("correct_path") or [])[:10],
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
            "competitive_intelligence_required": True,
            "latest_source_policy_enforced": intel.get("latest_source_policy_enforced"),
            "no_external_action_executed": True,
        },
        "human_initiator": strategy.get("human_initiator") or "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_value == "ALLOW",
    }


def write_ceo_competitive_intelligence_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOCompetitiveIntelligenceDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    if not cieu_db:
        raise ValueError("cieu_db is required")
    record = build_ceo_competitive_intelligence_cieu_record(strategy, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_competitive_intelligence_formal_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "formal_CIEU_log_module": "ystar.governance.ceo_competitive_intelligence_contract",
        "formal_CIEU_log_function": "write_ceo_competitive_intelligence_cieu_record",
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_competitive_intelligence(
    strategy: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_competitive_intelligence(strategy)
    write_result = write_ceo_competitive_intelligence_cieu_record(
        strategy,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_competitive_intelligence_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _competitor_problem(competitor: Any) -> str:
    if not isinstance(competitor, Mapping):
        return "competitor row must be a mapping"
    required = ("competitor_name", "source_url", "source_date", "freshness_tier", "how_they_solve", "threat_level", "why_us_gap")
    for field in required:
        if not _present(competitor.get(field)):
            return f"competitor missing {field}"
    if competitor.get("freshness_tier") not in {"current_2026", "current_recent", "latest_available"}:
        return "competitor source freshness tier is not current"
    return ""


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
) -> CEOCompetitiveIntelligenceDecision:
    decision_value = CEOCompetitiveIntelligenceDecisionValue(value)
    provisional = CEOCompetitiveIntelligenceDecision(
        decision=decision_value,
        reason=reason,
        failed_section=failed_section,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
    )
    return CEOCompetitiveIntelligenceDecision(
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
) -> CEOCompetitiveIntelligenceDecision:
    correct_path = [
        "repair competitive intelligence before accepting the strategy",
        "do not present a first-cash path without current competitor and substitute analysis",
        "rerun validate_ceo_competitive_intelligence after repair",
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


def _validation_candidate(strategy: Mapping[str, Any], decision: CEOCompetitiveIntelligenceDecision) -> dict[str, Any]:
    return {
        "X_t": {
            "contract_id": "ceo_competitive_intelligence_contract_v1",
            "strategy_run_id": strategy.get("strategy_run_id"),
        },
        "U_t": "Y-star-gov deterministic CEO competitive intelligence validation",
        "Y_star_t": "CEO strategy must prove latest competitor, substitute, and why-us-vs-alternative analysis",
        "Y_t_plus_1": {
            "decision": decision.decision.value,
            "reason": decision.reason,
            "failed_section": decision.failed_section,
            "correct_path": list(decision.correct_path),
        },
        "R_t_plus_1": "none" if decision.decision == CEOCompetitiveIntelligenceDecisionValue.ALLOW else decision.reason,
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
    "CEO_COMPETITIVE_INTELLIGENCE_CIEU_EVENT_TYPE",
    "CEOCompetitiveIntelligenceDecision",
    "CEOCompetitiveIntelligenceDecisionValue",
    "build_ceo_competitive_intelligence_contract",
    "build_ceo_competitive_intelligence_cieu_record",
    "validate_and_write_ceo_competitive_intelligence",
    "validate_ceo_competitive_intelligence",
    "write_ceo_competitive_intelligence_cieu_record",
]
