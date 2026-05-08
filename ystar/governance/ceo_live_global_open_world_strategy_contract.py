"""Governance for live global open-world CEO market discovery.

This contract closes the gap between "evidence-derived from a stored snapshot"
and a real open-world market scan. If an owner asks for the easiest global
money path, the CEO must prove a live public-read search across non-adjacent
markets before ranking strategy.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class CEOLiveGlobalOpenWorldDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOLiveGlobalOpenWorldDecision:
    decision: CEOLiveGlobalOpenWorldDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_live_global_open_world_strategy_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOLiveGlobalOpenWorldDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


CEO_LIVE_GLOBAL_OPEN_WORLD_CIEU_EVENT_TYPE = "CEO_LIVE_GLOBAL_OPEN_WORLD_STRATEGY_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

MIN_SCAN_DOMAINS = 12
MIN_EVIDENCE_ITEMS = 24
MIN_OPPORTUNITY_CLUSTERS = 10
MIN_ROUTE_CANDIDATES = 10
MIN_QUERY_ROUNDS = 4
MIN_NON_ADJACENT_DOMAINS = 8

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


def build_ceo_live_global_open_world_strategy_contract() -> dict[str, Any]:
    return {
        "contract_id": "ceo_live_global_open_world_strategy_contract_v1",
        "event_type": CEO_LIVE_GLOBAL_OPEN_WORLD_CIEU_EVENT_TYPE,
        "minimum_scan_domains": MIN_SCAN_DOMAINS,
        "minimum_evidence_items": MIN_EVIDENCE_ITEMS,
        "minimum_opportunity_clusters": MIN_OPPORTUNITY_CLUSTERS,
        "minimum_route_candidates": MIN_ROUTE_CANDIDATES,
        "minimum_query_rounds": MIN_QUERY_ROUNDS,
        "minimum_non_adjacent_domains": MIN_NON_ADJACENT_DOMAINS,
        "snapshot_evidence_sufficient": False,
        "fixed_candidate_list_sufficient": False,
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
    }


def validate_ceo_live_global_open_world_strategy(
    strategy: Mapping[str, Any],
) -> CEOLiveGlobalOpenWorldDecision:
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
            "live global public-read strategy may not execute external/provider actions",
            strategy,
            "execution_boundary",
            ["external_or_provider_execution_forbidden"],
        )

    scan = strategy.get("live_global_open_world_scan")
    if not isinstance(scan, Mapping):
        return _revision(
            "live_global_open_world_scan is required",
            strategy,
            "live_global_open_world_scan",
            ["run live public-read global discovery before answering global strategy questions"],
        )

    scan_mode = str(scan.get("scan_mode") or "")
    if scan_mode in {"", "snapshot", "static_snapshot", "codex_public_read_research_snapshot", "curated_snapshot"}:
        return _revision(
            "snapshot evidence cannot satisfy live global open-world strategy",
            strategy,
            "scan_mode",
            ["use live_public_read_network, codex_live_public_read_web, or owner_supplied_live_public_read evidence"],
        )
    if scan.get("live_public_read_performed") is not True:
        return _revision(
            "live public-read scan proof is required",
            strategy,
            "live_public_read_performed",
            ["execute or attach a live public-read scan with query/result provenance"],
        )
    if str(scan.get("provider_status") or "") not in {"success", "partial_success_with_minimum_coverage"}:
        return _revision(
            "live public-read provider did not reach minimum coverage",
            strategy,
            "provider_status",
            ["rerun provider or attach owner-supplied live public-read evidence until coverage thresholds pass"],
        )

    domains = _as_list(scan.get("scan_domains"))
    if len(domains) < MIN_SCAN_DOMAINS:
        return _revision(
            "global scan must cover at least twelve non-trivial domains",
            strategy,
            "scan_domains",
            [f"expand scan_domains to at least {MIN_SCAN_DOMAINS}"],
        )

    non_adjacent = [domain for domain in domains if isinstance(domain, Mapping) and domain.get("adjacent_to_prior_anchor") is False]
    if len(non_adjacent) < MIN_NON_ADJACENT_DOMAINS:
        return _revision(
            "global scan must include non-adjacent domains beyond prior anchors",
            strategy,
            "scan_domains",
            [f"include at least {MIN_NON_ADJACENT_DOMAINS} domains not adjacent to AI-agent/CPA/tariff anchors"],
        )

    query_rounds = _as_list(scan.get("query_expansion_rounds"))
    if len(query_rounds) < MIN_QUERY_ROUNDS:
        return _revision(
            "query expansion must run at least four rounds",
            strategy,
            "query_expansion_rounds",
            [f"run at least {MIN_QUERY_ROUNDS} query expansion rounds"],
        )
    for row in query_rounds:
        if not isinstance(row, Mapping) or not _as_list(row.get("queries")):
            return _revision(
                "each query round must include concrete queries",
                strategy,
                "query_expansion_rounds",
                ["attach queries for each expansion round"],
            )

    evidence = _as_list(scan.get("evidence_items") or strategy.get("external_market_evidence_map", {}).get("evidence_items"))
    if len(evidence) < MIN_EVIDENCE_ITEMS:
        return _revision(
            "live global scan needs more evidence items",
            strategy,
            "evidence_items",
            [f"collect at least {MIN_EVIDENCE_ITEMS} public-read evidence items"],
        )
    for item in evidence:
        if not isinstance(item, Mapping) or not _present(item.get("source_url")) or not _present(item.get("observed_at")):
            return _revision(
                "each evidence item needs source_url and observed_at",
                strategy,
                "evidence_items",
                ["repair evidence provenance with source_url and observed_at"],
            )

    clusters = _as_list(scan.get("opportunity_clusters") or strategy.get("opportunity_clusters"))
    if len(clusters) < MIN_OPPORTUNITY_CLUSTERS:
        return _revision(
            "global scan must produce at least ten opportunity clusters",
            strategy,
            "opportunity_clusters",
            [f"derive at least {MIN_OPPORTUNITY_CLUSTERS} clusters from live evidence"],
        )
    if any(isinstance(cluster, Mapping) and cluster.get("derived_from_fixed_candidate_list") is True for cluster in clusters):
        return _decision(
            "DENY",
            "fixed candidate list cannot masquerade as global open-world clusters",
            strategy,
            "opportunity_clusters",
            ["fixed_candidate_list_used"],
        )

    candidates = _as_list(strategy.get("route_candidates"))
    if len(candidates) < MIN_ROUTE_CANDIDATES:
        return _revision(
            "global open-world strategy must generate at least ten route candidates",
            strategy,
            "route_candidates",
            [f"generate at least {MIN_ROUTE_CANDIDATES} route candidates from clusters"],
        )
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            return _revision("route candidates must be mappings", strategy, "route_candidates", ["repair candidate rows"])
        if not _as_list(candidate.get("source_cluster_ids")) or not _as_list(candidate.get("evidence_refs")):
            return _revision(
                "each route candidate must link to cluster ids and evidence refs",
                strategy,
                "route_candidates",
                [f"repair provenance for {candidate.get('route_id')}"],
            )
        if candidate.get("candidate_source") in {"fixed_preset", "prior_anchor_clone", "static_template"}:
            return _decision(
                "DENY",
                "fixed preset candidates cannot satisfy global open-world strategy",
                strategy,
                "route_candidates",
                ["fixed_preset_candidate_used"],
            )

    anchor = scan.get("anchor_proximity_audit")
    if not isinstance(anchor, Mapping):
        return _revision(
            "anchor_proximity_audit is required",
            strategy,
            "anchor_proximity_audit",
            ["audit whether selected route is just a near-neighbor of prior anchors"],
        )
    if anchor.get("globally_ranked_against_non_adjacent_domains") is not True:
        return _revision(
            "selected route must be ranked against non-adjacent global domains",
            strategy,
            "anchor_proximity_audit",
            ["rank selected route against non-adjacent global domains before accepting it"],
        )
    if anchor.get("selected_route_is_prior_anchor_clone") is True:
        return _decision(
            "DENY",
            "selected route is a prior anchor clone",
            strategy,
            "anchor_proximity_audit",
            ["prior_anchor_clone_selected"],
        )

    if strategy.get("execute_L4_now") is True:
        return _decision(
            "ESCALATE",
            "complete strategy attempts owner-bound L4 execution",
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

    return _decision("ALLOW", "live global open-world strategy scan passed", strategy)


def build_ceo_live_global_open_world_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOLiveGlobalOpenWorldDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, CEOLiveGlobalOpenWorldDecision) else dict(decision)
    decision_value = str(decision_data.get("decision") or "DENY")
    scan = strategy.get("live_global_open_world_scan") if isinstance(strategy.get("live_global_open_world_scan"), Mapping) else {}
    selected = strategy.get("selected_strategy") if isinstance(strategy.get("selected_strategy"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(strategy.get("session_id") or "e108_live_global_open_world_strategy"),
        "agent_id": "bridge_labs_ceo",
        "event_type": CEO_LIVE_GLOBAL_OPEN_WORLD_CIEU_EVENT_TYPE,
        "decision": _decision_to_cieu_decision(decision_value),
        "passed": decision_value == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_value != "ALLOW",
        "drift_details": None if decision_value == "ALLOW" else decision_data.get("reason"),
        "task_description": "CEO live global open-world market discovery governance decision",
        "contract_hash": "ceo-live-global-open-world-strategy-v1",
        "params": {
            "strategy_run_id": strategy.get("strategy_run_id"),
            "scan_mode": scan.get("scan_mode"),
            "provider_status": scan.get("provider_status"),
            "scan_domain_count": len(_as_list(scan.get("scan_domains"))),
            "evidence_count": len(_as_list(scan.get("evidence_items"))),
            "cluster_count": len(_as_list(scan.get("opportunity_clusters"))),
            "route_candidate_count": len(_as_list(strategy.get("route_candidates"))),
            "selected_route_id": selected.get("selected_route_id"),
        },
        "result": {
            "decision": decision_value,
            "reason": decision_data.get("reason"),
            "failed_section": decision_data.get("failed_section"),
            "correct_path": list(decision_data.get("correct_path") or [])[:10],
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
            "live_global_public_read_required": True,
            "snapshot_evidence_sufficient": False,
            "fixed_candidate_list_sufficient": False,
            "no_external_action_executed": True,
        },
        "human_initiator": strategy.get("human_initiator") or "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": decision_value == "ALLOW",
    }


def write_ceo_live_global_open_world_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOLiveGlobalOpenWorldDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    if not cieu_db:
        raise ValueError("cieu_db is required")
    record = build_ceo_live_global_open_world_cieu_record(strategy, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_live_global_open_world_formal_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "formal_CIEU_log_module": "ystar.governance.ceo_live_global_open_world_strategy_contract",
        "formal_CIEU_log_function": "write_ceo_live_global_open_world_cieu_record",
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_live_global_open_world_strategy(
    strategy: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_live_global_open_world_strategy(strategy)
    write_result = write_ceo_live_global_open_world_cieu_record(
        strategy,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_live_global_open_world_validate_and_write_result",
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
) -> CEOLiveGlobalOpenWorldDecision:
    decision_value = CEOLiveGlobalOpenWorldDecisionValue(value)
    provisional = CEOLiveGlobalOpenWorldDecision(
        decision=decision_value,
        reason=reason,
        failed_section=failed_section,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
    )
    return CEOLiveGlobalOpenWorldDecision(
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
) -> CEOLiveGlobalOpenWorldDecision:
    correct_path = [
        "repair live global open-world discovery before accepting the strategy",
        "do not answer global first-cash strategy from snapshot evidence or fixed candidates",
        "rerun validate_ceo_live_global_open_world_strategy after repair",
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


def _validation_candidate(strategy: Mapping[str, Any], decision: CEOLiveGlobalOpenWorldDecision) -> dict[str, Any]:
    return {
        "X_t": {
            "contract_id": "ceo_live_global_open_world_strategy_contract_v1",
            "strategy_run_id": strategy.get("strategy_run_id"),
        },
        "U_t": "Y-star-gov deterministic live global open-world strategy validation",
        "Y_star_t": "CEO global first-cash strategy must come from live public-read global discovery, not snapshots or anchors",
        "Y_t_plus_1": {
            "decision": decision.decision.value,
            "reason": decision.reason,
            "failed_section": decision.failed_section,
            "correct_path": list(decision.correct_path),
        },
        "R_t_plus_1": "none" if decision.decision == CEOLiveGlobalOpenWorldDecisionValue.ALLOW else decision.reason,
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
    "CEO_LIVE_GLOBAL_OPEN_WORLD_CIEU_EVENT_TYPE",
    "CEOLiveGlobalOpenWorldDecision",
    "CEOLiveGlobalOpenWorldDecisionValue",
    "build_ceo_live_global_open_world_strategy_contract",
    "build_ceo_live_global_open_world_cieu_record",
    "validate_and_write_ceo_live_global_open_world_strategy",
    "validate_ceo_live_global_open_world_strategy",
    "write_ceo_live_global_open_world_cieu_record",
]
