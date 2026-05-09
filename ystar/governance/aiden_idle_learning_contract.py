"""Deterministic governance for Aiden idle-time continuous learning.

The contract makes "learning while idle" a governed runtime behavior instead
of an unbounded background write loop. It allows local brain graph growth only
after the learning packet proves idle state, source-dated evidence,
freshness filtering, CIEU linkage, CZL closure, and no external side effects.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class AidenIdleLearningDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class AidenIdleLearningDecision:
    decision: AidenIdleLearningDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)
    requires_owner_decision: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "aiden_idle_learning_governance_decision",
            "decision": self.decision.value,
            "passed": self.decision == AidenIdleLearningDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "guidance": dict(self.guidance),
            "requires_owner_decision": self.requires_owner_decision,
        }


AIDEN_IDLE_LEARNING_CIEU_EVENT_TYPE = "AIDEN_IDLE_CONTINUOUS_LEARNING_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_PACKET_FIELDS = (
    "learning_cycle_id",
    "learning_mode",
    "trigger_context",
    "curriculum_domains",
    "source_date_policy",
    "evidence_items",
    "learning_quality_summary",
    "knowledge_graph_delta",
    "brain_write_policy",
    "CIEU_linkage",
    "CZL_closure",
    "extrapolation_gate",
    "truth_constraints",
)

REQUIRED_CURRICULUM_DOMAINS = {
    "ceo_judgment",
    "market_intelligence",
    "competitive_strategy",
    "product_strategy",
    "sales_and_distribution",
    "governance_and_risk",
    "technology_architecture",
    "failure_residual_learning",
    "classical_theory_canon",
    "peer_experience_corpus",
    "historical_case_corpus",
    "customer_contact_residuals",
}

ALLOWED_FRESHNESS_STATUSES = {
    "accepted_current",
    "accepted_recent",
    "accepted_evergreen_context",
}

REQUIRED_CONTENT_TYPE_POLICY_KEYS = {
    "classical_theory",
    "peer_experience",
    "historical_case",
    "operator_playbook",
    "customer_learning_methodology",
}

REQUIRED_EVIDENCE_DOMAINS = {
    "classical_theory_canon",
    "peer_experience_corpus",
    "historical_case_corpus",
    "customer_contact_residuals",
}

ALLOWED_WRITE_MODES = {
    "CIEU_backed_candidate_only",
    "isolated_test_brain_db_write",
    "governed_local_brain_db_write",
}

FORBIDDEN_TRUE_CLAIMS = (
    "external_action_executed",
    "provider_action_executed",
    "customer_validation_claim",
    "pricing_validation_claim",
    "revenue_claim",
    "payment_claim",
    "paid_signal_claim",
    "L4_feedback_executed",
    "L5_revenue_loop_complete",
    "K9Audit_integration_claim",
    "live_provider_execution_claim",
)


def build_aiden_idle_learning_contract() -> dict[str, Any]:
    return {
        "contract_id": "aiden_idle_continuous_learning_contract_v1",
        "event_type": AIDEN_IDLE_LEARNING_CIEU_EVENT_TYPE,
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "required_packet_fields": list(REQUIRED_PACKET_FIELDS),
        "required_curriculum_domains": sorted(REQUIRED_CURRICULUM_DOMAINS),
        "allowed_write_modes": sorted(ALLOWED_WRITE_MODES),
        "governance_style": "idle_state_checked_source_dated_CIEU_backed_brain_graph_growth",
    }


def validate_aiden_idle_learning_packet(packet: Mapping[str, Any]) -> AidenIdleLearningDecision:
    if not isinstance(packet, Mapping):
        return _deny("idle learning packet must be a mapping", "schema", ["packet_not_mapping"])

    missing = [field for field in REQUIRED_PACKET_FIELDS if field not in packet]
    if missing:
        return _revision(
            "idle learning packet is missing required sections",
            "schema",
            [f"add {field}" for field in missing],
        )

    forbidden = _forbidden_claim(packet)
    if forbidden:
        return _deny(f"forbidden idle-learning overclaim or side effect present: {forbidden}", "truth_constraints", [forbidden])
    extrapolation = _validate_extrapolation_gate(packet.get("extrapolation_gate"))
    if extrapolation:
        return extrapolation

    trigger = packet.get("trigger_context") if isinstance(packet.get("trigger_context"), Mapping) else {}
    if trigger.get("explicit_session_task_active") is True:
        return _revision(
            "idle learning cannot run while an explicit owner/session task is active",
            "trigger_context",
            [
                "pause idle learning",
                "finish the active session task first",
                "resume idle learning only after explicit_session_task_active=false",
            ],
        )
    if trigger.get("idle_state_verified") is not True:
        return _revision(
            "idle state must be verified before background learning",
            "trigger_context",
            ["run idle detector or session-state check before learning"],
        )

    if packet.get("learning_mode") not in {"idle_continuous_learning", "idle_learning_cycle"}:
        return _revision(
            "learning_mode must be an idle learning mode",
            "learning_mode",
            ["set learning_mode=idle_continuous_learning or idle_learning_cycle"],
        )

    domains = packet.get("curriculum_domains")
    if not isinstance(domains, list):
        return _revision("curriculum_domains must be a list", "curriculum_domains", ["emit structured domain rows"])
    domain_ids = {str(item.get("domain_id")) for item in domains if isinstance(item, Mapping)}
    missing_domains = sorted(REQUIRED_CURRICULUM_DOMAINS - domain_ids)
    if missing_domains:
        return _revision(
            "idle learning curriculum is too narrow for CEO knowledge-graph growth",
            "curriculum_domains",
            [f"include domain {domain_id}" for domain_id in missing_domains],
        )

    source_policy = packet.get("source_date_policy") if isinstance(packet.get("source_date_policy"), Mapping) else {}
    if source_policy.get("source_dates_required") is not True:
        return _revision(
            "source-date policy must require dated evidence",
            "source_date_policy",
            ["set source_dates_required=true", "reject undated and stale evidence before brain write"],
        )
    content_type_policy = source_policy.get("content_type_max_age_days") if isinstance(source_policy.get("content_type_max_age_days"), Mapping) else {}
    missing_content_policy = sorted(REQUIRED_CONTENT_TYPE_POLICY_KEYS - set(content_type_policy.keys()))
    if missing_content_policy:
        return _revision(
            "freshness policy must be content-type aware for durable theory, peer experience, cases, and customer-learning methodology",
            "source_date_policy",
            [f"add content_type_max_age_days.{key}" for key in missing_content_policy],
        )

    evidence_items = packet.get("evidence_items")
    if not isinstance(evidence_items, list) or len(evidence_items) < 8:
        return _revision(
            "idle learning needs at least eight accepted evidence items",
            "evidence_items",
            ["collect source-dated CEO/market/strategy/technology/governance evidence before writing brain"],
        )
    accepted_ids: set[str] = set()
    evidence_domains: set[str] = set()
    for item in evidence_items:
        if not isinstance(item, Mapping):
            return _revision("evidence item must be structured", "evidence_items", ["normalize evidence rows"])
        evidence_id = str(item.get("evidence_id") or "")
        freshness_status = str(item.get("freshness_status") or "")
        if not evidence_id:
            return _revision("evidence item is missing evidence_id", "evidence_items", ["add stable evidence_id"])
        if freshness_status not in ALLOWED_FRESHNESS_STATUSES:
            return _revision(
                "evidence item is not freshness-accepted",
                "evidence_items",
                [f"refresh or reject evidence {evidence_id}"],
            )
        if not item.get("source_url") or not item.get("source_date"):
            return _revision(
                "evidence item needs source_url and source_date",
                "evidence_items",
                [f"add source URL/date metadata or reject evidence {evidence_id}"],
            )
        content_type = str(item.get("content_type") or item.get("knowledge_content_type") or "").strip()
        if not content_type:
            return _revision(
                "evidence item needs content_type so freshness can distinguish market news from durable knowledge",
                "evidence_items",
                [f"add content_type for evidence {evidence_id}"],
            )
        quality = item.get("learning_quality") if isinstance(item.get("learning_quality"), Mapping) else {}
        score = quality.get("quality_score", item.get("quality_score"))
        if score is None:
            return _revision(
                "evidence item needs deterministic learning_quality score",
                "learning_quality_summary",
                [f"score learning quality before using evidence {evidence_id}"],
            )
        if float(score) < 0.6:
            return _revision(
                "low-quality evidence cannot feed idle brain learning",
                "learning_quality_summary",
                [f"replace or downgrade evidence {evidence_id}; minimum quality_score is 0.60"],
            )
        required_quality_dims = {
            "source_authority",
            "source_authority_basis",
            "freshness",
            "commercial_relevance",
            "novelty",
            "cross_source_support",
            "actionability",
            "source_url_depth",
            "claim_specificity",
            "current_signal_verifiability",
            "risk_of_staleness",
        }
        missing_quality_dims = sorted(required_quality_dims - set(quality.keys()))
        if missing_quality_dims:
            return _revision(
                "learning_quality score must expose all deterministic dimensions",
                "learning_quality_summary",
                [f"add learning_quality.{field}" for field in missing_quality_dims],
            )
        accepted_ids.add(evidence_id)
        evidence_domains.add(str(item.get("domain_id") or ""))

    missing_evidence_domains = sorted(REQUIRED_EVIDENCE_DOMAINS - evidence_domains)
    if missing_evidence_domains:
        return _revision(
            "idle learning must actually ingest durable theory, peer experience, historical cases, and customer-learning methodology evidence",
            "evidence_items",
            [f"add accepted evidence for domain {domain_id}" for domain_id in missing_evidence_domains],
        )

    quality_summary = packet.get("learning_quality_summary") if isinstance(packet.get("learning_quality_summary"), Mapping) else {}
    if quality_summary.get("learning_quality_gate_applied") is not True:
        return _revision(
            "learning quality gate must run before brain graph write",
            "learning_quality_summary",
            ["run deterministic learning quality scoring after freshness filtering"],
        )
    if float(quality_summary.get("average_quality_score") or 0.0) < 0.65:
        return _revision(
            "average learning quality is too low for durable brain growth",
            "learning_quality_summary",
            ["raise source authority, relevance, novelty, and cross-source support before writing brain"],
        )
    if quality_summary.get("low_quality_evidence_ids"):
        return _revision(
            "low-quality evidence must be rejected or kept out of knowledge graph delta",
            "learning_quality_summary",
            ["remove low_quality_evidence_ids from accepted evidence and graph delta"],
        )

    delta = packet.get("knowledge_graph_delta") if isinstance(packet.get("knowledge_graph_delta"), Mapping) else {}
    nodes = delta.get("nodes")
    edges = delta.get("edges")
    if not isinstance(nodes, list) or len(nodes) < 8:
        return _revision(
            "knowledge graph delta must add enough learning nodes",
            "knowledge_graph_delta",
            ["build node candidates from accepted evidence and curriculum domains"],
        )
    if not isinstance(edges, list) or len(edges) < 8:
        return _revision(
            "knowledge graph delta must connect learning nodes",
            "knowledge_graph_delta",
            ["connect new nodes to CEO/domain/strategy/failure hubs"],
        )
    node_ids = {str(node.get("node_id")) for node in nodes if isinstance(node, Mapping)}
    for node in nodes:
        if not isinstance(node, Mapping):
            return _revision("knowledge node must be structured", "knowledge_graph_delta", ["normalize node rows"])
        node_id = str(node.get("node_id") or "")
        refs = [str(ref) for ref in (node.get("source_evidence_ids") or []) if ref]
        if not node_id or not node.get("name") or not node.get("node_type"):
            return _revision("knowledge node needs node_id, name, and node_type", "knowledge_graph_delta", ["complete node schema"])
        if not refs:
            return _revision("knowledge node needs evidence refs", "knowledge_graph_delta", [f"attach evidence refs to node {node_id}"])
        missing_refs = [ref for ref in refs if ref not in accepted_ids]
        if missing_refs:
            return _revision(
                "knowledge node references evidence that was not accepted by freshness policy",
                "knowledge_graph_delta",
                [f"refresh or remove refs for node {node_id}: {', '.join(missing_refs)}"],
            )
        if float(node.get("learning_quality_score") or 0.0) < 0.6:
            return _revision(
                "knowledge node quality is too low for brain graph write",
                "knowledge_graph_delta",
                [f"raise or remove node {node_id}; minimum learning_quality_score is 0.60"],
            )
    for edge in edges:
        if not isinstance(edge, Mapping):
            return _revision("knowledge edge must be structured", "knowledge_graph_delta", ["normalize edge rows"])
        source = str(edge.get("source_id") or "")
        target = str(edge.get("target_id") or "")
        if source not in node_ids or target not in node_ids:
            return _revision(
                "knowledge edge must connect nodes in the same delta",
                "knowledge_graph_delta",
                [f"repair edge {source}->{target}"],
            )

    brain_policy = packet.get("brain_write_policy") if isinstance(packet.get("brain_write_policy"), Mapping) else {}
    write_mode = str(brain_policy.get("write_mode") or "")
    if write_mode not in ALLOWED_WRITE_MODES:
        return _revision(
            "brain write policy must use an allowed governed mode",
            "brain_write_policy",
            [f"set write_mode to one of {sorted(ALLOWED_WRITE_MODES)}"],
        )
    if brain_policy.get("automatic_direct_writeback") is True:
        return _deny(
            "automatic direct brain writeback is forbidden; use governed idle learning write only",
            "brain_write_policy",
            ["automatic_direct_writeback_true"],
        )
    if write_mode in {"isolated_test_brain_db_write", "governed_local_brain_db_write"}:
        if brain_policy.get("YstarGov_validation_required") is not True:
            return _revision(
                "brain graph write requires Y-star-gov validation before write",
                "brain_write_policy",
                ["set YstarGov_validation_required=true and validate packet before applying graph delta"],
            )
        if not brain_policy.get("target_brain_db"):
            return _revision("brain write target must be declared", "brain_write_policy", ["set target_brain_db"])
        if int(brain_policy.get("max_nodes_per_cycle") or 0) <= 0 or int(brain_policy.get("max_edges_per_cycle") or 0) <= 0:
            return _revision(
                "brain write policy needs per-cycle rate limits",
                "brain_write_policy",
                ["set max_nodes_per_cycle and max_edges_per_cycle"],
            )
    if write_mode == "governed_local_brain_db_write" and brain_policy.get("production_target") is True:
        if brain_policy.get("owner_explicit_production_write_approval") is not True:
            return AidenIdleLearningDecision(
                decision=AidenIdleLearningDecisionValue.ESCALATE,
                reason="production brain write is owner-bound and requires explicit approval before graph mutation",
                failed_section="brain_write_policy",
                violations=["production_brain_write_owner_approval_missing"],
                correct_path=[
                    "present production brain write preflight to owner",
                    "create and verify a timestamped brain.db backup",
                    "rerun with owner_explicit_production_write_approval=true only after approval",
                ],
                guidance={"next_allowed_action": "owner_visible_preflight_only"},
                requires_owner_decision=True,
            )
        backup_required_fields = [
            "pre_write_backup_path",
            "pre_write_backup_sha256",
            "pre_write_brain_db_sha256",
            "backup_created_at",
            "rollback_plan",
        ]
        missing_backup = [field for field in backup_required_fields if not brain_policy.get(field)]
        if missing_backup or brain_policy.get("backup_verified") is not True:
            return _revision(
                "approved production brain write requires verified backup and rollback metadata",
                "brain_write_policy",
                [f"add {field}" for field in missing_backup] + ["set backup_verified=true before production write"],
            )
    if brain_policy.get("production_brain_write_performed") is True:
        return _deny(
            "brain write was marked performed before validation/write proof",
            "brain_write_policy",
            ["pre_validation_brain_write_performed"],
        )

    linkage = packet.get("CIEU_linkage") if isinstance(packet.get("CIEU_linkage"), Mapping) else {}
    if linkage.get("target_event_type") != AIDEN_IDLE_LEARNING_CIEU_EVENT_TYPE:
        return _revision(
            "idle learning must target the formal Aiden idle learning CIEU event",
            "CIEU_linkage",
            [f"set target_event_type={AIDEN_IDLE_LEARNING_CIEU_EVENT_TYPE}"],
        )
    if linkage.get("formal_CIEU_log_path") != FORMAL_CIEU_LOG_PATH:
        return _revision(
            "idle learning must use CIEUStore.write_dict",
            "CIEU_linkage",
            ["use ystar.governance.cieu_store.CIEUStore.write_dict"],
        )

    czl = packet.get("CZL_closure") if isinstance(packet.get("CZL_closure"), Mapping) else {}
    if czl.get("uses_existing_CZL") is not True:
        return _revision(
            "idle learning must reuse existing CZL semantics",
            "CZL_closure",
            ["reuse ResidualLoopEngine/CZL tuple; do not invent a parallel residual model"],
        )
    r_t_plus_1 = czl.get("R_t_plus_1")
    if r_t_plus_1 is None or float(r_t_plus_1) != 0.0:
        return _revision(
            "idle learning requires CZL closure R_t_plus_1=0",
            "CZL_closure",
            ["close learning residuals before calling the cycle complete"],
        )

    return AidenIdleLearningDecision(
        decision=AidenIdleLearningDecisionValue.ALLOW,
        reason="idle learning packet satisfies governed source-dated brain graph growth requirements",
        correct_path=["write CIEU record first", "then apply graph delta only within declared brain_write_policy"],
        guidance={
            "next_allowed_action": "CIEU_record_then_governed_brain_graph_delta",
            "idle_learning_allowed": True,
            "external_action_allowed": False,
            "stale_or_undated_evidence_allowed": False,
        },
    )


def build_aiden_idle_learning_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenIdleLearningDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, AidenIdleLearningDecision) else dict(decision)
    delta = packet.get("knowledge_graph_delta") if isinstance(packet.get("knowledge_graph_delta"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(packet.get("learning_cycle_id") or "aiden_idle_learning"),
        "agent_id": "Aiden",
        "event_type": AIDEN_IDLE_LEARNING_CIEU_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "Aiden idle continuous learning and brain graph growth decision",
        "contract_hash": "aiden-idle-continuous-learning-contract-v1",
        "params": {
            "learning_cycle_id": packet.get("learning_cycle_id"),
            "learning_mode": packet.get("learning_mode"),
            "curriculum_domain_count": len(packet.get("curriculum_domains") or []),
            "evidence_count": len(packet.get("evidence_items") or []),
            "knowledge_node_count": len(delta.get("nodes") or []),
            "knowledge_edge_count": len(delta.get("edges") or []),
            "write_mode": packet.get("brain_write_policy", {}).get("write_mode")
            if isinstance(packet.get("brain_write_policy"), Mapping)
            else None,
        },
        "result": {
            "decision": data.get("decision"),
            "reason": data.get("reason"),
            "correct_path": list(data.get("correct_path") or []),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore", "Aiden-brain"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": data.get("decision") == "ALLOW",
    }


def write_aiden_idle_learning_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenIdleLearningDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    record = build_aiden_idle_learning_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "aiden_idle_learning_cieu_write_result",
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


def validate_and_write_aiden_idle_learning_packet(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_aiden_idle_learning_packet(packet)
    write_result = write_aiden_idle_learning_cieu_record(
        packet,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "aiden_idle_learning_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> AidenIdleLearningDecision:
    path = [
        "pause unsafe or incomplete idle learning",
        "repair the idle learning packet",
        *correct_path,
    ]
    return AidenIdleLearningDecision(
        decision=AidenIdleLearningDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=failed_section,
        correct_path=path,
        guidance={
            "decision_mode": "correct_path_navigation",
            "next_allowed_action": "repair_idle_learning_packet",
            "correct_path": path,
        },
    )


def _deny(reason: str, failed_section: str, violations: list[str]) -> AidenIdleLearningDecision:
    return AidenIdleLearningDecision(
        decision=AidenIdleLearningDecisionValue.DENY,
        reason=reason,
        failed_section=failed_section,
        violations=violations,
        correct_path=[
            "block idle learning cycle",
            "remove side effect or false claim",
            "rerun through governed source-dated learning contract",
        ],
        guidance={"decision_mode": "blocked", "next_allowed_action": "repair_then_resubmit"},
    )


def _validate_extrapolation_gate(value: Any) -> AidenIdleLearningDecision | None:
    if not isinstance(value, Mapping):
        return _revision(
            "idle learning must include class-level extrapolation gate",
            "extrapolation_gate",
            ["add class_of_issue, extrapolation_to_other_cases, proposed_class_level_fix, and evidence_refs"],
        )
    class_issue = value.get("class_of_issue") if isinstance(value.get("class_of_issue"), Mapping) else {}
    if not class_issue.get("issue_class_id") or not class_issue.get("generalization_boundary"):
        return _revision(
            "extrapolation gate needs class_of_issue and generalization boundary",
            "extrapolation_gate",
            ["identify the issue class before writing durable brain learning"],
        )
    cases = value.get("extrapolation_to_other_cases")
    if not isinstance(cases, list) or len(cases) < 3:
        return _revision(
            "extrapolation gate must list at least three same-class variants",
            "extrapolation_gate",
            ["list three other places this learning failure could recur"],
        )
    for case in cases:
        if not isinstance(case, Mapping) or not case.get("case_id") or not case.get("why_same_class") or not case.get("preventive_rule"):
            return _revision(
                "each extrapolated case needs case_id, why_same_class, and preventive_rule",
                "extrapolation_gate",
                ["turn observed residual into reusable preventive rule"],
            )
    class_fix = value.get("proposed_class_level_fix") if isinstance(value.get("proposed_class_level_fix"), Mapping) else {}
    if not class_fix.get("rule") or len(class_fix.get("affected_runtime_paths") or []) < 2:
        return _revision(
            "extrapolation gate needs a class-level fix across affected runtimes",
            "extrapolation_gate",
            ["add proposed_class_level_fix.rule and at least two affected_runtime_paths"],
        )
    if not value.get("evidence_refs"):
        return _revision(
            "extrapolation gate needs evidence refs",
            "extrapolation_gate",
            ["attach evidence refs that justify the class-level learning"],
        )
    if value.get("point_fix_only") is True:
        return _revision(
            "point-fix-only learning is not sufficient for durable brain growth",
            "extrapolation_gate",
            ["generalize the issue class before accepting brain learning"],
        )
    return None


def _forbidden_claim(packet: Mapping[str, Any]) -> str | None:
    truth = packet.get("truth_constraints") if isinstance(packet.get("truth_constraints"), Mapping) else {}
    for key in FORBIDDEN_TRUE_CLAIMS:
        if truth.get(key) is True:
            return key
    return None
