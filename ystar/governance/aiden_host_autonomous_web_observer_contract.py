"""Governance for Aiden host-local autonomous public-read observation.

The contract allows Aiden to look at the public web from the owner host, but
only as a read-only observation behavior. It must not become outreach,
scraping of private data, form submission, payment, or an ungoverned local LLM
runtime.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class AidenHostWebObserverDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class AidenHostWebObserverDecision:
    decision: AidenHostWebObserverDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "aiden_host_autonomous_web_observer_decision",
            "decision": self.decision.value,
            "passed": self.decision == AidenHostWebObserverDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "guidance": dict(self.guidance),
        }


AIDEN_HOST_AUTONOMOUS_WEB_OBSERVER_EVENT_TYPE = "AIDEN_HOST_AUTONOMOUS_WEB_OBSERVER_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_PACKET_SECTIONS = (
    "observer_cycle_id",
    "execution_boundary",
    "query_frontier",
    "public_read_policy",
    "source_date_policy",
    "evidence_items",
    "learning_quality_summary",
    "knowledge_graph_update_plan",
    "local_gemma_runtime",
    "governance_chain",
    "CIEU_linkage",
    "truth_constraints",
)

FORBIDDEN_TRUE_CLAIMS = (
    "login_attempted",
    "form_submitted",
    "message_sent",
    "payment_attempted",
    "external_action_executed",
    "provider_action_executed",
    "scraped_private_data",
    "customer_validation_claim",
    "revenue_claim",
    "payment_claim",
    "live_provider_execution_claim",
    "K9Audit_integration_claim",
    "raw_unvalidated_codex_prompt_used",
    "external_llm_provider_used_for_local_gemma",
)

REQUIRED_GOVERNANCE_LINKS = {
    "E112_content_type_freshness_filter",
    "E119_operating_pattern_doctrine",
    "E120_unknown_problem_learning_protocol",
    "CIEUStore_formal_recording",
}


def build_aiden_host_autonomous_web_observer_contract() -> dict[str, Any]:
    return {
        "contract_id": "aiden_host_autonomous_web_observer_contract_v1",
        "event_type": AIDEN_HOST_AUTONOMOUS_WEB_OBSERVER_EVENT_TYPE,
        "allowed_behavior": "host-local public-read observation only",
        "forbidden_true_claims": list(FORBIDDEN_TRUE_CLAIMS),
        "required_governance_links": sorted(REQUIRED_GOVERNANCE_LINKS),
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
    }


def validate_aiden_host_autonomous_web_observer_packet(
    packet: Mapping[str, Any],
) -> AidenHostWebObserverDecision:
    if not isinstance(packet, Mapping):
        return _deny("Aiden host web observer packet must be a mapping", "schema", ["packet_not_mapping"])

    missing = [field for field in REQUIRED_PACKET_SECTIONS if field not in packet]
    if missing:
        return _revision(
            "Aiden host web observer packet is missing required sections",
            "schema",
            [f"add {field}" for field in missing],
        )

    truth = _mapping(packet.get("truth_constraints"))
    forbidden = [key for key in FORBIDDEN_TRUE_CLAIMS if truth.get(key) is True]
    if forbidden:
        return _deny(
            "Aiden host web observation attempted external action, overclaim, or private/runtime bypass",
            "truth_constraints",
            forbidden,
        )

    boundary_decision = _validate_execution_boundary(_mapping(packet.get("execution_boundary")))
    if boundary_decision:
        return boundary_decision

    policy_decision = _validate_public_read_policy(_mapping(packet.get("public_read_policy")))
    if policy_decision:
        return policy_decision

    frontier_decision = _validate_query_frontier(_mapping(packet.get("query_frontier")))
    if frontier_decision:
        return frontier_decision

    evidence_decision = _validate_evidence_items(packet.get("evidence_items"))
    if evidence_decision:
        return evidence_decision

    quality = _mapping(packet.get("learning_quality_summary"))
    if quality.get("learning_quality_gate_applied") is not True:
        return _revision(
            "autonomous public-read evidence must pass the learning quality gate",
            "learning_quality_summary",
            ["run E117/E118 learning quality scoring before durable use"],
        )
    if float(quality.get("average_quality_score") or 0.0) < 0.65:
        return _revision(
            "average learning quality score is below durable observation threshold",
            "learning_quality_summary",
            ["collect higher-authority, source-dated, corroborated public evidence"],
        )

    graph = _mapping(packet.get("knowledge_graph_update_plan"))
    if graph.get("production_brain_write_requires_owner_gate") is not True:
        return _revision(
            "autonomous web observation cannot directly mutate production brain without owner gate",
            "knowledge_graph_update_plan",
            ["set production_brain_write_requires_owner_gate=true and route through E118"],
        )
    if len(_list(graph.get("candidate_node_types"))) < 5 or len(_list(graph.get("candidate_edge_types"))) < 5:
        return _revision(
            "knowledge graph update plan needs rich node and edge schemas",
            "knowledge_graph_update_plan",
            ["add typed nodes/edges for facts, competitors, theories, cases, assumptions, and residuals"],
        )

    local_llm_decision = _validate_local_gemma_runtime(_mapping(packet.get("local_gemma_runtime")))
    if local_llm_decision:
        return local_llm_decision

    governance = _mapping(packet.get("governance_chain"))
    links = set(_list(governance.get("governance_links")))
    missing_links = sorted(REQUIRED_GOVERNANCE_LINKS - links)
    if missing_links:
        return _revision(
            "autonomous web observation is missing governance-chain links",
            "governance_chain",
            [f"add governance link {link}" for link in missing_links],
        )

    cieu = _mapping(packet.get("CIEU_linkage"))
    if cieu.get("CIEU_recording_required") is not True:
        return _revision(
            "autonomous web observation must be CIEU recorded",
            "CIEU_linkage",
            ["set CIEU_recording_required=true and write the formal record"],
        )

    return AidenHostWebObserverDecision(
        decision=AidenHostWebObserverDecisionValue.ALLOW,
        reason="Aiden host autonomous web observation is public-read-only, source-dated, quality-gated, and governed",
        correct_path=["allow Aiden to observe public web evidence within the declared host-local no-side-effect boundary"],
        guidance={
            "public_read_only": True,
            "local_gemma": _mapping(packet.get("local_gemma_runtime")).get("status"),
            "accepted_evidence_count": len(_list(packet.get("evidence_items"))),
        },
    )


def build_aiden_host_autonomous_web_observer_cieu_record(
    packet: Mapping[str, Any],
    decision: AidenHostWebObserverDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, AidenHostWebObserverDecision) else dict(decision)
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(packet.get("observer_cycle_id") or "aiden_host_autonomous_web_observer"),
        "agent_id": "Aiden",
        "event_type": AIDEN_HOST_AUTONOMOUS_WEB_OBSERVER_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "Aiden host-local autonomous public-read observation validation",
        "contract_hash": "aiden-host-autonomous-web-observer-v1",
        "params": {
            "observer_cycle_id": packet.get("observer_cycle_id"),
            "evidence_count": len(_list(packet.get("evidence_items"))),
        },
        "result": {
            "decision": data.get("decision"),
            "reason": data.get("reason"),
            "correct_path": list(data.get("correct_path") or []),
            "guidance": dict(data.get("guidance") or {}),
        },
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "host-public-read", "Y-star-gov", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": data.get("decision") == "ALLOW",
    }


def write_aiden_host_autonomous_web_observer_cieu_record(
    record: Mapping[str, Any],
    *,
    cieu_db: str,
) -> bool:
    return bool(CIEUStore(cieu_db).write_dict(dict(record)))


def validate_and_write_aiden_host_autonomous_web_observer_packet(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_aiden_host_autonomous_web_observer_packet(packet)
    record = build_aiden_host_autonomous_web_observer_cieu_record(packet, decision, session_id=session_id)
    written = write_aiden_host_autonomous_web_observer_cieu_record(record, cieu_db=cieu_db)
    store = CIEUStore(cieu_db)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "aiden_host_autonomous_web_observer_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "CIEU_write_result": {"event_type": record["event_type"], "event_id": record["event_id"], "CIEU_record": record},
        "seal_result": seal_result,
        "verify_result": verify_result,
    }


def _validate_execution_boundary(boundary: Mapping[str, Any]) -> AidenHostWebObserverDecision | None:
    if boundary.get("runs_on_owner_host") is not True:
        return _revision(
            "Aiden web observation must declare host-local execution",
            "execution_boundary",
            ["set runs_on_owner_host=true when executed from the Mac host"],
        )
    if boundary.get("sandbox_restricted") is True and boundary.get("host_public_read_bridge") is not True:
        return _revision(
            "sandbox-only execution cannot claim autonomous host web visibility",
            "execution_boundary",
            ["use host_public_read_bridge=true or run the observer on the owner Mac"],
        )
    if boundary.get("external_side_effect_allowed") is True:
        return _deny(
            "host web observer cannot allow external side effects",
            "execution_boundary",
            ["external_side_effect_allowed"],
        )
    return None


def _validate_public_read_policy(policy: Mapping[str, Any]) -> AidenHostWebObserverDecision | None:
    if policy.get("public_read_only") is not True:
        return _revision(
            "Aiden web observation must be public-read-only",
            "public_read_policy",
            ["set public_read_only=true and reject login/form/contact/payment operations"],
        )
    methods = {str(method).upper() for method in _list(policy.get("allowed_http_methods"))}
    if not methods or methods - {"GET", "HEAD"}:
        return _deny(
            "public-read observer attempted a non-read HTTP method",
            "public_read_policy",
            sorted(methods - {"GET", "HEAD"}) or ["missing_allowed_http_methods"],
        )
    forbidden_flags = (
        "login_allowed",
        "form_submission_allowed",
        "contact_allowed",
        "payment_allowed",
        "account_creation_allowed",
        "private_data_collection_allowed",
    )
    active = [flag for flag in forbidden_flags if policy.get(flag) is True]
    if active:
        return _deny("public-read policy enables forbidden external behavior", "public_read_policy", active)
    return None


def _validate_query_frontier(frontier: Mapping[str, Any]) -> AidenHostWebObserverDecision | None:
    rounds = _list(frontier.get("rounds"))
    domains = _list(frontier.get("domain_hypotheses"))
    if int(frontier.get("round_count") or len(rounds)) < 3:
        return _revision(
            "autonomous web observation needs at least three discovery rounds",
            "query_frontier",
            ["run broad scan, expansion scan, and contradiction/competitor scan"],
        )
    if len(domains) < 8:
        return _revision(
            "autonomous world observation is too narrow",
            "query_frontier",
            ["cover at least eight diverse market/knowledge domains"],
        )
    if frontier.get("recent_memory_anchor_removed") is not True:
        return _revision(
            "query frontier must remove recent-memory anchoring",
            "query_frontier",
            ["set recent_memory_anchor_removed=true and generate open-world alternatives"],
        )
    return None


def _validate_evidence_items(evidence: Any) -> AidenHostWebObserverDecision | None:
    rows = _list(evidence)
    if len(rows) < 12:
        return _revision(
            "autonomous web observation needs enough accepted source-dated evidence",
            "evidence_items",
            ["collect at least 12 accepted source-dated public-read evidence items"],
        )
    domains = {str(row.get("domain_id") or "") for row in rows if isinstance(row, Mapping)}
    if len(domains) < 6:
        return _revision(
            "accepted evidence is too domain-narrow",
            "evidence_items",
            ["collect evidence from at least six distinct domains"],
        )
    for row in rows:
        if not isinstance(row, Mapping):
            return _revision("each evidence item must be a mapping", "evidence_items", ["complete evidence rows"])
        if not row.get("source_url") or not row.get("source_date"):
            return _revision(
                "accepted evidence items must have source_url and source_date",
                "evidence_items",
                ["drop undated rows to CIEU context only; do not use them as durable facts"],
            )
        if str(row.get("freshness_status") or "").startswith("rejected"):
            return _revision(
                "rejected stale/undated evidence cannot satisfy autonomous observation",
                "evidence_items",
                ["only include accepted freshness rows in durable evidence_items"],
            )
    return None


def _validate_local_gemma_runtime(runtime: Mapping[str, Any]) -> AidenHostWebObserverDecision | None:
    if runtime.get("external_provider_api_used") is True:
        return _deny(
            "local Gemma mode cannot use an external LLM provider API",
            "local_gemma_runtime",
            ["external_provider_api_used"],
        )
    if runtime.get("private_data_exfiltration_allowed") is True:
        return _deny(
            "local Gemma runtime cannot allow private-data exfiltration",
            "local_gemma_runtime",
            ["private_data_exfiltration_allowed"],
        )
    if runtime.get("requested") is not True:
        return None
    if runtime.get("available") is not True:
        return _revision(
            "local Gemma runtime is requested but not available on host",
            "local_gemma_runtime",
            [
                "install/start Ollama on the Mac host",
                "pull a Gemma4-compatible local model",
                "rerun local Gemma probe before enabling Gemma-backed Aiden reasoning",
            ],
        )
    host = str(runtime.get("runtime_host") or "")
    if host not in {"127.0.0.1", "localhost", "host-local"}:
        return _deny(
            "Gemma runtime must be local-only",
            "local_gemma_runtime",
            [f"runtime_host={host or 'missing'}"],
        )
    model = str(runtime.get("model_name") or "").lower()
    if "gemma" not in model:
        return _revision(
            "Gemma runtime proof must name a Gemma model",
            "local_gemma_runtime",
            ["use gemma4 or a declared Gemma-compatible local fallback"],
        )
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> AidenHostWebObserverDecision:
    return AidenHostWebObserverDecision(
        decision=AidenHostWebObserverDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=failed_section,
        correct_path=correct_path,
    )


def _deny(reason: str, failed_section: str, violations: list[str]) -> AidenHostWebObserverDecision:
    return AidenHostWebObserverDecision(
        decision=AidenHostWebObserverDecisionValue.DENY,
        reason=reason,
        failed_section=failed_section,
        violations=violations,
        correct_path=["remove the forbidden behavior and reroute through governed public-read-only observation"],
    )


__all__ = [
    "AIDEN_HOST_AUTONOMOUS_WEB_OBSERVER_EVENT_TYPE",
    "AidenHostWebObserverDecision",
    "AidenHostWebObserverDecisionValue",
    "build_aiden_host_autonomous_web_observer_contract",
    "build_aiden_host_autonomous_web_observer_cieu_record",
    "validate_aiden_host_autonomous_web_observer_packet",
    "validate_and_write_aiden_host_autonomous_web_observer_packet",
    "write_aiden_host_autonomous_web_observer_cieu_record",
]
