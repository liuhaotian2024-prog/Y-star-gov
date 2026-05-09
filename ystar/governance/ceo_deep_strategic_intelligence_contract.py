"""Deterministic governance for deep CEO strategic intelligence dossiers.

The contract deliberately governs structured cognition outputs, not hidden
chain-of-thought. It turns "high intelligence" from an aspiration into a
runtime obligation: a CEO strategy cannot pass unless it contains concrete
buyer, product, competitive, economic, causal, and learning structure.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

from ystar.governance.cieu_store import CIEUStore


class CEODeepStrategicDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEODeepStrategicDecision:
    decision: CEODeepStrategicDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    requires_owner_decision: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_deep_strategic_intelligence_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEODeepStrategicDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "guidance": dict(self.guidance),
            "requires_owner_decision": self.requires_owner_decision,
        }


CEO_DEEP_STRATEGIC_INTELLIGENCE_EVENT_TYPE = "CEO_DEEP_STRATEGIC_INTELLIGENCE_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_SECTIONS = (
    "dossier_id",
    "generation_mode",
    "source_runtime",
    "strategic_question_reframe",
    "deep_reasoning_dimensions",
    "market_map",
    "selected_route_thesis",
    "customer_and_buyer_model",
    "competitive_landscape",
    "right_to_win_and_right_to_lose",
    "product_shape",
    "pricing_and_value_capture",
    "distribution_and_first_10_buyers",
    "causal_zero_loop_model",
    "assumption_registry",
    "experiment_design",
    "post_action_residual_learning_plan",
    "CIEU_predictions",
    "no_overclaim_boundary",
)

REQUIRED_DEEP_DIMENSIONS = (
    "strategic_question_reframe",
    "jobs_to_be_done",
    "buyer_pain_and_trigger_events",
    "budget_owner_and_procurement",
    "competitive_landscape",
    "substitute_and_status_quo",
    "founder_market_fit_and_right_to_win",
    "product_shape_and_delivery_model",
    "pricing_and_value_capture",
    "distribution_and_first_10_buyers",
    "risk_regulatory_trust",
    "causal_zero_loop_residual_model",
    "experiment_and_kill_criteria",
    "memory_and_learning_update",
)

FORBIDDEN_CLAIMS = (
    "customer_validation_claim",
    "revenue_claim",
    "payment_claim",
    "paid_signal_claim",
    "pricing_validation_claim",
    "L4_feedback_executed",
    "L5_revenue_loop_complete",
    "K9Audit_integration_claim",
    "live_provider_execution_claim",
)


def validate_ceo_deep_strategic_intelligence_dossier(
    dossier: Mapping[str, Any],
) -> CEODeepStrategicDecision:
    if not isinstance(dossier, Mapping):
        return _deny("deep strategy dossier must be a mapping", "dossier_schema", ["not_mapping"])

    forbidden = _find_forbidden_claim(dossier)
    if forbidden:
        return _deny(f"forbidden strategy overclaim present: {forbidden}", "no_overclaim_boundary", [forbidden])

    missing = [section for section in REQUIRED_SECTIONS if section not in dossier]
    if missing:
        return _revision("deep strategy dossier is missing required sections", "dossier_schema", [f"add {section}" for section in missing])

    mode = str(dossier.get("generation_mode") or "")
    if mode in {"static_template", "deterministic_fixture", "recent_memory_only"}:
        return _revision(
            "static/recent-memory generation cannot satisfy deep CEO strategy",
            "generation_mode",
            ["rerun through brain-grounded, public-evidence-backed, capability-utilized runtime generation"],
        )

    dimensions = _as_list(dossier.get("deep_reasoning_dimensions"))
    dimension_ids = {str(item.get("dimension_id")) for item in dimensions if isinstance(item, Mapping)}
    missing_dimensions = [item for item in REQUIRED_DEEP_DIMENSIONS if item not in dimension_ids]
    if missing_dimensions:
        return _revision(
            "deep reasoning dimensions are incomplete",
            "deep_reasoning_dimensions",
            [f"complete dimension {item}" for item in missing_dimensions],
        )
    for item in dimensions:
        if not isinstance(item, Mapping):
            return _revision("deep reasoning dimension must be structured", "deep_reasoning_dimensions", [])
        if not _present(item.get("conclusion")) or not _as_list(item.get("evidence_refs")) or not _present(item.get("uncertainty")):
            return _revision(
                "each deep reasoning dimension needs conclusion, evidence_refs, and uncertainty",
                "deep_reasoning_dimensions",
                ["attach structured output, cited evidence, and uncertainty for every dimension"],
            )
    diversity_decision = _validate_dimension_evidence_diversity(dimensions)
    if diversity_decision:
        return diversity_decision

    market_map = dossier.get("market_map")
    if not isinstance(market_map, Mapping):
        return _revision("market_map must be structured", "market_map", [])
    domains = _as_list(market_map.get("domains_analyzed"))
    if len(domains) < 5:
        return _revision("market_map must analyze at least five domains", "market_map", ["compare at least five non-identical opportunity domains"])
    source_coverage = market_map.get("source_date_coverage")
    if not isinstance(source_coverage, Mapping) or int(source_coverage.get("dated_count") or 0) < 8:
        return _revision("market_map needs enough source-dated evidence", "market_map", ["include source-dated evidence and reject stale/undated rows"])

    product = dossier.get("product_shape")
    if not isinstance(product, Mapping):
        return _revision("product_shape must be structured", "product_shape", [])
    if len(_as_list(product.get("buyer_visible_deliverables"))) < 5:
        return _revision("product_shape must include at least five buyer-visible deliverables", "product_shape", ["define the concrete package, not a vague workflow"])

    competitors = _as_list(dossier.get("competitive_landscape", {}).get("competitors_and_substitutes") if isinstance(dossier.get("competitive_landscape"), Mapping) else [])
    if len(competitors) < 5:
        return _revision("competitive landscape must include at least five competitors/substitutes", "competitive_landscape", ["add direct competitors, substitutes, incumbents, and status quo"])
    for competitor in competitors:
        if not isinstance(competitor, Mapping):
            return _revision("competitor rows must be structured", "competitive_landscape", [])
        if "example.com" in str(competitor.get("source_url") or ""):
            return _revision("placeholder competitor sources are not allowed", "competitive_landscape", ["replace placeholder source URLs with real public evidence"])
        if not _competitor_has_current_signal(competitor):
            return _revision(
                "competitor rows require source-date, funding-date, or public-signal date",
                "competitive_landscape",
                ["attach source_date/latest_funding_date/public_signal_date/observed_at for every competitor"],
            )
        if _is_plain_homepage_url(str(competitor.get("source_url") or "")) and not competitor.get("public_signal_date"):
            return _revision(
                "plain competitor homepages need an explicit current public_signal_date",
                "competitive_landscape",
                ["add current public_signal_date or replace homepage with a dated competitor evidence URL"],
            )

    right_to_win = dossier.get("right_to_win_and_right_to_lose")
    if not isinstance(right_to_win, Mapping):
        return _revision("right_to_win_and_right_to_lose must be structured", "right_to_win_and_right_to_lose", [])
    if len(_as_list(right_to_win.get("right_to_win_assets"))) < 5 or len(_as_list(right_to_win.get("right_to_lose_risks"))) < 3:
        return _revision(
            "right-to-win needs both strengths and weaknesses",
            "right_to_win_and_right_to_lose",
            ["list at least five specific strengths and three specific risks"],
        )
    market_visible = _as_list(right_to_win.get("market_visible_right_to_win_assets"))
    if len(market_visible) < 4:
        return _revision(
            "right-to-win must include buyer-visible proof, not only internal technology assets",
            "right_to_win_and_right_to_lose",
            ["add at least four market_visible_right_to_win_assets with buyer_visible_proof and evidence_refs"],
        )
    for item in market_visible:
        if not isinstance(item, Mapping):
            return _revision("market-visible right-to-win rows must be structured", "right_to_win_and_right_to_lose", [])
        if not _present(item.get("buyer_visible_proof")) or not _as_list(item.get("evidence_refs")) or not _present(item.get("why_buyer_cares")):
            return _revision(
                "market-visible right-to-win rows need proof, evidence_refs, and why_buyer_cares",
                "right_to_win_and_right_to_lose",
                ["turn internal assets into buyer-visible proof points"],
            )

    assumptions = _as_list(dossier.get("assumption_registry"))
    if len(assumptions) < 5:
        return _revision("at least five explicit assumptions are required", "assumption_registry", ["add assumptions with tests and falsification conditions"])
    for assumption in assumptions:
        if not isinstance(assumption, Mapping) or not _present(assumption.get("falsification_condition")) or not _present(assumption.get("test_method")):
            return _revision("each assumption needs test_method and falsification_condition", "assumption_registry", [])

    czl = dossier.get("causal_zero_loop_model")
    if not isinstance(czl, Mapping):
        return _revision("causal_zero_loop_model must be structured", "causal_zero_loop_model", [])
    r_t_plus_1 = czl.get("R_t_plus_1")
    if r_t_plus_1 is None or float(r_t_plus_1) != 0.0:
        return _revision("CZL closure requires R_t_plus_1=0", "causal_zero_loop_model", ["close the residual loop before calling the strategy complete"])
    residual_truth = czl.get("residual_truth_status") if isinstance(czl.get("residual_truth_status"), Mapping) else {}
    if residual_truth.get("real_market_residual_closed") is True and _no_real_feedback_claimed(dossier):
        return _deny(
            "real market residual cannot be claimed closed without real feedback/customer evidence",
            "causal_zero_loop_model",
            ["false_real_market_residual_closure"],
        )
    if residual_truth.get("closure_scope") != "planning_residual_closed_real_market_residual_pending":
        return _revision(
            "CZL closure must distinguish planning residual from real market residual",
            "causal_zero_loop_model",
            ["set residual_truth_status.closure_scope=planning_residual_closed_real_market_residual_pending"],
        )

    experiment = dossier.get("experiment_design")
    if not isinstance(experiment, Mapping):
        return _revision("experiment_design must be structured", "experiment_design", [])
    if experiment.get("external_action_executed") is True or experiment.get("provider_action_executed") is True:
        return _deny("deep strategy may not execute external/provider action", "experiment_design", ["external_action_executed"])
    if experiment.get("owner_decision_required") is True:
        return CEODeepStrategicDecision(
            decision=CEODeepStrategicDecisionValue.ALLOW,
            reason="deep strategic dossier is complete; next external feedback remains owner-gated no-send",
            failed_section=None,
            correct_path=["prepare owner decision packet; do not send external action without approval"],
            guidance={"next_allowed_action": "owner_decision_packet_or_internal_artifact_only"},
            requires_owner_decision=True,
        )

    return CEODeepStrategicDecision(
        decision=CEODeepStrategicDecisionValue.ALLOW,
        reason="deep strategic dossier satisfies structured intelligence requirements",
        correct_path=["proceed only through governed runtime and no-send boundary"],
        guidance={"next_allowed_action": "governed_internal_strategy_artifact"},
    )


def build_ceo_deep_strategic_intelligence_cieu_record(
    dossier: Mapping[str, Any],
    decision: CEODeepStrategicDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision)
    selected = dossier.get("selected_route_thesis") if isinstance(dossier.get("selected_route_thesis"), Mapping) else {}
    return {
        "event_id": str(uuid.uuid4()),
        "session_id": session_id or str(dossier.get("dossier_id") or "ceo_deep_strategy_session"),
        "ts": time.time(),
        "event_type": CEO_DEEP_STRATEGIC_INTELLIGENCE_EVENT_TYPE,
        "decision": data.get("decision"),
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "CEO deep strategic intelligence dossier decision",
        "contract_hash": "ceo-deep-strategic-intelligence-v1",
        "params": {
            "dossier_id": dossier.get("dossier_id"),
            "generation_mode": dossier.get("generation_mode"),
            "selected_route_id": selected.get("selected_route_id"),
            "product_name": dossier.get("product_shape", {}).get("product_name") if isinstance(dossier.get("product_shape"), Mapping) else None,
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


def write_ceo_deep_strategic_intelligence_cieu_record(
    dossier: Mapping[str, Any],
    decision: CEODeepStrategicDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    record = build_ceo_deep_strategic_intelligence_cieu_record(dossier, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_deep_strategic_intelligence_cieu_write_result",
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


def validate_and_write_ceo_deep_strategic_intelligence_dossier(
    dossier: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_deep_strategic_intelligence_dossier(dossier)
    write_result = write_ceo_deep_strategic_intelligence_cieu_record(
        dossier,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_deep_strategic_intelligence_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _revision(reason: str, section: str, correct_path: list[str]) -> CEODeepStrategicDecision:
    path = [
        "stop shallow strategy output",
        "rerun deep strategic intelligence dossier builder",
        *correct_path,
    ]
    return CEODeepStrategicDecision(
        decision=CEODeepStrategicDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=section,
        correct_path=path,
        guidance={"next_allowed_action": "repair_deep_strategy_dossier", "correct_path": path},
    )


def _validate_dimension_evidence_diversity(dimensions: list[Any]) -> CEODeepStrategicDecision | None:
    ref_sets = []
    all_refs: list[str] = []
    for item in dimensions:
        if not isinstance(item, Mapping):
            continue
        refs = {str(ref) for ref in _as_list(item.get("evidence_refs")) if str(ref)}
        ref_sets.append(tuple(sorted(refs)))
        all_refs.extend(sorted(refs))
    if len(set(all_refs)) < 12:
        return _revision(
            "deep strategy evidence is too narrow across dimensions",
            "deep_reasoning_dimensions",
            ["use at least twelve distinct evidence refs across the deep strategy dossier"],
        )
    repeated = Counter(ref_sets)
    if repeated and repeated.most_common(1)[0][1] >= 6:
        return _revision(
            "too many deep reasoning dimensions reuse the identical evidence set",
            "deep_reasoning_dimensions",
            ["give each strategic dimension dimension-specific evidence instead of copying the same refs"],
        )
    ref_counts = Counter(all_refs)
    dimension_specific_count = 0
    for refs in ref_sets:
        if any(ref_counts[ref] <= 3 for ref in refs):
            dimension_specific_count += 1
    if dimension_specific_count < 8:
        return _revision(
            "too few dimensions have dimension-specific evidence",
            "deep_reasoning_dimensions",
            ["at least eight dimensions need evidence not reused everywhere"],
        )
    return None


def _competitor_has_current_signal(competitor: Mapping[str, Any]) -> bool:
    return any(
        _present(competitor.get(field))
        for field in ("source_date", "latest_funding_date", "public_signal_date", "observed_at", "updated_at")
    )


def _is_plain_homepage_url(url: str) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return parsed.path in {"", "/"}


def _no_real_feedback_claimed(dossier: Mapping[str, Any]) -> bool:
    boundary = dossier.get("no_overclaim_boundary") if isinstance(dossier.get("no_overclaim_boundary"), Mapping) else {}
    return not any(
        boundary.get(key) is True
        for key in ("customer_validation_claim", "revenue_claim", "payment_claim", "paid_signal_claim", "pricing_validation_claim", "L4_feedback_executed")
    )


def _deny(reason: str, section: str, violations: list[str]) -> CEODeepStrategicDecision:
    return CEODeepStrategicDecision(
        decision=CEODeepStrategicDecisionValue.DENY,
        reason=reason,
        failed_section=section,
        violations=violations,
        correct_path=["block execution", "remove overclaim or unsafe action", "rerun governed strategy"],
        guidance={"next_allowed_action": "blocked_until_repaired"},
    )


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _find_forbidden_claim(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in FORBIDDEN_CLAIMS and item:
                return str(key)
            found = _find_forbidden_claim(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_forbidden_claim(item)
            if found:
                return found
    elif isinstance(value, str):
        text = value.lower()
        for claim in FORBIDDEN_CLAIMS:
            if claim.lower() in text:
                return claim
    return None


__all__ = [
    "CEO_DEEP_STRATEGIC_INTELLIGENCE_EVENT_TYPE",
    "CEODeepStrategicDecision",
    "CEODeepStrategicDecisionValue",
    "build_ceo_deep_strategic_intelligence_cieu_record",
    "validate_and_write_ceo_deep_strategic_intelligence_dossier",
    "validate_ceo_deep_strategic_intelligence_dossier",
    "write_ceo_deep_strategic_intelligence_cieu_record",
]
