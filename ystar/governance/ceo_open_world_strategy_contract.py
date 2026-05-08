"""Governance contract for evidence-derived open-world CEO strategy search.

This contract closes the E104 loophole where a strategy could satisfy market
refresh checks while still drawing candidate routes from a closed preset list.
It requires explicit discovery proof: query expansion, evidence ingestion,
dynamic opportunity clusters, candidate derivation from those clusters, and a
selected route that can be traced back to public-read evidence.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class CEOOpenWorldStrategyDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class CEOOpenWorldStrategyDecision:
    decision: CEOOpenWorldStrategyDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    correct_path: list[str] = field(default_factory=list)
    requires_owner_decision: bool = False
    cieu_validation_record: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "ceo_open_world_strategy_decision",
            "decision": self.decision.value,
            "passed": self.decision == CEOOpenWorldStrategyDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "guidance": dict(self.guidance),
            "correct_path": list(self.correct_path),
            "requires_owner_decision": self.requires_owner_decision,
            "cieu_validation_record": dict(self.cieu_validation_record),
        }


CEO_OPEN_WORLD_STRATEGY_CIEU_EVENT_TYPE = "CEO_OPEN_WORLD_STRATEGY_DISCOVERY_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

BLOCKED_GENERATION_MODES: tuple[str, ...] = (
    "closed_route_preset",
    "hardcoded_route_list",
    "static_template",
    "deterministic_fixture",
)

ALLOWED_EVIDENCE_FEED_MODES: tuple[str, ...] = (
    "live_public_read_provider",
    "owner_supplied_public_read_snapshot",
    "codex_public_read_research_snapshot",
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


def build_ceo_open_world_strategy_contract() -> dict[str, Any]:
    return {
        "contract_id": "ceo_open_world_strategy_contract_v1",
        "event_type": CEO_OPEN_WORLD_STRATEGY_CIEU_EVENT_TYPE,
        "required_sections": [
            "open_world_discovery_proof",
            "external_market_evidence_map",
            "route_candidates",
            "route_scoring",
            "selected_strategy",
        ],
        "minimum_query_expansion_rounds": 3,
        "minimum_opportunity_clusters": 5,
        "minimum_unseeded_clusters": 1,
        "minimum_evidence_items": 10,
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "external_action_allowed": False,
        "live_provider_execution_allowed": False,
    }


def validate_ceo_open_world_strategy(
    strategy: Mapping[str, Any],
) -> CEOOpenWorldStrategyDecision:
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
            "open-world strategy may not execute external/provider action",
            strategy,
            "execution_boundary",
            ["external_or_provider_execution_forbidden"],
        )

    proof = strategy.get("open_world_discovery_proof")
    if not isinstance(proof, Mapping):
        return _revision(
            "open_world_discovery_proof is required",
            strategy,
            "open_world_discovery_proof",
            ["run evidence-derived open-world discovery before route selection"],
        )

    mode = str(proof.get("candidate_generation_mode") or strategy.get("generation_mode") or "")
    if mode in BLOCKED_GENERATION_MODES or proof.get("closed_route_preset_used") is True:
        return _revision(
            "closed route presets cannot satisfy open-world strategy",
            strategy,
            "candidate_generation_mode",
            ["derive candidates from evidence clusters; do not use hardcoded route lists"],
        )

    feed_mode = str(proof.get("evidence_feed_mode") or "")
    if feed_mode not in ALLOWED_EVIDENCE_FEED_MODES:
        return _revision(
            "open-world discovery needs a public-read evidence feed",
            strategy,
            "evidence_feed_mode",
            ["ingest live public-read provider output or an owner/Codex public-read evidence snapshot"],
        )

    evidence = strategy.get("external_market_evidence_map")
    if not isinstance(evidence, Mapping):
        return _revision(
            "external_market_evidence_map is required",
            strategy,
            "external_market_evidence_map",
            ["attach public-read evidence items"],
        )
    evidence_items = _as_list(evidence.get("evidence_items"))
    if len(evidence_items) < 10:
        return _revision(
            "open-world discovery needs at least ten public-read evidence items",
            strategy,
            "external_market_evidence_map",
            ["collect a broader public-read evidence feed before selecting strategy"],
        )
    evidence_ids = {str(item.get("evidence_id") or "") for item in evidence_items if isinstance(item, Mapping)}
    if "" in evidence_ids:
        return _revision(
            "every evidence item needs evidence_id",
            strategy,
            "external_market_evidence_map",
            ["add evidence_id to every evidence item"],
        )

    rounds = _as_list(proof.get("query_expansion_rounds"))
    if len(rounds) < 3:
        return _revision(
            "query expansion requires at least three rounds",
            strategy,
            "query_expansion_rounds",
            ["run at least three query expansion rounds from broad seeds to evidence-driven terms"],
        )
    for index, item in enumerate(rounds):
        if not isinstance(item, Mapping) or not _as_list(item.get("queries")):
            return _revision(
                "query expansion rounds must include queries",
                strategy,
                "query_expansion_rounds",
                [f"add queries to query_expansion_rounds[{index}]"],
            )

    clusters = _as_list(proof.get("opportunity_clusters"))
    if len(clusters) < 5:
        return _revision(
            "open-world discovery must produce at least five opportunity clusters",
            strategy,
            "opportunity_clusters",
            ["cluster the evidence feed into at least five materially different opportunity domains"],
        )
    cluster_ids = set()
    unseeded_count = 0
    for cluster in clusters:
        if not isinstance(cluster, Mapping):
            return _revision("opportunity clusters must be structured", strategy, "opportunity_clusters", [])
        cluster_id = str(cluster.get("cluster_id") or "")
        if not cluster_id:
            return _revision("cluster_id is required", strategy, "opportunity_clusters", ["add cluster_id"])
        cluster_ids.add(cluster_id)
        if cluster.get("discovered_from_prompt_seed") is False:
            unseeded_count += 1
        refs = {str(ref) for ref in _as_list(cluster.get("evidence_refs"))}
        if not refs or not refs <= evidence_ids:
            return _revision(
                "cluster evidence_refs must point to ingested evidence ids",
                strategy,
                "opportunity_clusters",
                [f"repair evidence refs for cluster {cluster_id}"],
            )
    if unseeded_count < 1:
        return _revision(
            "open-world discovery needs at least one unseeded cluster",
            strategy,
            "opportunity_clusters",
            ["keep repo-discovered or evidence-discovered categories that were not in the prompt seed list"],
        )

    candidates = _as_list(strategy.get("route_candidates"))
    if len(candidates) < 5:
        return _revision(
            "open-world strategy needs at least five route candidates",
            strategy,
            "route_candidates",
            ["derive at least five route candidates from opportunity clusters"],
        )
    candidate_ids = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            return _revision("route candidates must be structured", strategy, "route_candidates", [])
        candidate_id = str(candidate.get("route_id") or "")
        candidate_ids.add(candidate_id)
        source_clusters = {str(item) for item in _as_list(candidate.get("source_cluster_ids"))}
        if not source_clusters or not source_clusters <= cluster_ids:
            return _revision(
                "each route candidate must trace to source clusters",
                strategy,
                "route_candidates",
                [f"repair source_cluster_ids for candidate {candidate_id}"],
            )

    selected = strategy.get("selected_strategy")
    if not isinstance(selected, Mapping):
        return _revision("selected_strategy is required", strategy, "selected_strategy", [])
    selected_route = str(selected.get("selected_route_id") or "")
    if selected_route not in candidate_ids:
        return _revision(
            "selected route must be one of the evidence-derived candidates",
            strategy,
            "selected_strategy",
            ["select a route generated from opportunity clusters"],
        )

    scoring = _as_list(strategy.get("route_scoring"))
    scored_ids = {str(item.get("route_id") or "") for item in scoring if isinstance(item, Mapping)}
    if selected_route not in scored_ids:
        return _revision(
            "selected route must be scored",
            strategy,
            "route_scoring",
            ["score the selected evidence-derived route before selecting it"],
        )

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
    if strategy.get("execute_L4_now") is True and str(packet.get("owner_approval_state")) != "approved":
        return _decision(
            "ESCALATE",
            "complete open-world strategy attempts owner-bound L4 execution without approval",
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

    return _decision("ALLOW", "CEO open-world strategy discovery proof passed", strategy)


def build_ceo_open_world_strategy_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOOpenWorldStrategyDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    decision_data = decision.to_dict() if isinstance(decision, CEOOpenWorldStrategyDecision) else dict(decision)
    decision_value = str(decision_data.get("decision") or "DENY")
    proof = strategy.get("open_world_discovery_proof") if isinstance(strategy.get("open_world_discovery_proof"), Mapping) else {}
    selected = strategy.get("selected_strategy") if isinstance(strategy.get("selected_strategy"), Mapping) else {}
    evidence = strategy.get("external_market_evidence_map") if isinstance(strategy.get("external_market_evidence_map"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(strategy.get("session_id") or "e105_open_world_strategy_session"),
        "agent_id": "bridge_labs_ceo",
        "event_type": CEO_OPEN_WORLD_STRATEGY_CIEU_EVENT_TYPE,
        "decision": _decision_to_cieu_decision(decision_value),
        "passed": decision_value == "ALLOW",
        "violations": list(decision_data.get("violations") or []),
        "drift_detected": decision_value != "ALLOW",
        "drift_details": None if decision_value == "ALLOW" else decision_data.get("reason"),
        "task_description": "CEO open-world market discovery governance decision",
        "contract_hash": "ceo-open-world-strategy-v1",
        "params": {
            "strategy_run_id": strategy.get("strategy_run_id"),
            "selected_route_id": selected.get("selected_route_id"),
            "evidence_feed_mode": proof.get("evidence_feed_mode"),
            "candidate_generation_mode": proof.get("candidate_generation_mode"),
            "evidence_count": len(_as_list(evidence.get("evidence_items"))),
            "query_expansion_round_count": len(_as_list(proof.get("query_expansion_rounds"))),
            "cluster_count": len(_as_list(proof.get("opportunity_clusters"))),
            "closed_route_preset_used": proof.get("closed_route_preset_used"),
        },
        "result": {
            "decision": decision_value,
            "reason": decision_data.get("reason"),
            "selected_route_id": selected.get("selected_route_id"),
            "selected_first_cash_path": selected.get("current_best_first_cash_path"),
            "failed_section": decision_data.get("failed_section"),
            "correct_path": list(decision_data.get("correct_path") or [])[:10],
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
            "open_world_discovery_required": True,
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


def write_ceo_open_world_strategy_cieu_record(
    strategy: Mapping[str, Any],
    decision: CEOOpenWorldStrategyDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    if not cieu_db:
        raise ValueError("cieu_db is required")
    record = build_ceo_open_world_strategy_cieu_record(strategy, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "ceo_open_world_strategy_formal_cieu_write_result",
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "validator_output_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "formal_CIEU_log_module": "ystar.governance.ceo_open_world_strategy_contract",
        "formal_CIEU_log_function": "write_ceo_open_world_strategy_cieu_record",
        "cieu_db": cieu_db,
        "event_id": record["event_id"],
        "session_id": record["session_id"],
        "event_type": record["event_type"],
        "decision": record["decision"],
        "CIEU_record": record,
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def validate_and_write_ceo_open_world_strategy(
    strategy: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_ceo_open_world_strategy(strategy)
    write_result = write_ceo_open_world_strategy_cieu_record(
        strategy,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "ceo_open_world_strategy_validate_and_write_result",
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
) -> CEOOpenWorldStrategyDecision:
    decision_value = CEOOpenWorldStrategyDecisionValue(value)
    provisional = CEOOpenWorldStrategyDecision(
        decision=decision_value,
        reason=reason,
        failed_section=failed_section,
        violations=violations or [],
        guidance=guidance or {},
        correct_path=correct_path or [],
        requires_owner_decision=requires_owner_decision,
    )
    return CEOOpenWorldStrategyDecision(
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
) -> CEOOpenWorldStrategyDecision:
    correct_path = [
        "repair the CEO open-world discovery proof before accepting strategy selection",
        "do not execute L4/L5/customer/revenue/payment action while decision is REQUIRE_REVISION",
        "rerun validate_ceo_open_world_strategy after repair",
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


def _validation_candidate(strategy: Mapping[str, Any], decision: CEOOpenWorldStrategyDecision) -> dict[str, Any]:
    return {
        "X_t": {
            "contract_id": "ceo_open_world_strategy_contract_v1",
            "strategy_run_id": strategy.get("strategy_run_id"),
        },
        "U_t": "Y-star-gov deterministic CEO open-world discovery validation",
        "Y_star_t": "CEO route candidates must be derived from public-read evidence clusters, not a closed route preset",
        "Y_t_plus_1": {
            "decision": decision.decision.value,
            "reason": decision.reason,
            "failed_section": decision.failed_section,
            "correct_path": list(decision.correct_path),
        },
        "R_t_plus_1": "none" if decision.decision == CEOOpenWorldStrategyDecisionValue.ALLOW else decision.reason,
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
    "CEO_OPEN_WORLD_STRATEGY_CIEU_EVENT_TYPE",
    "CEOOpenWorldStrategyDecision",
    "CEOOpenWorldStrategyDecisionValue",
    "build_ceo_open_world_strategy_contract",
    "build_ceo_open_world_strategy_cieu_record",
    "validate_and_write_ceo_open_world_strategy",
    "validate_ceo_open_world_strategy",
    "write_ceo_open_world_strategy_cieu_record",
]
