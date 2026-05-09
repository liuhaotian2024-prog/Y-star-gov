"""Runtime law for existing-capability recall and no-new-wheel enforcement.

This contract turns "do not rebuild existing systems" from an operator
preference into a deterministic governance gate. A CEO/Codex major action may
continue only after it proves full-system capability recall, reuse planning,
and CZL-style closure with Rt+1 = 0.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class NoNewWheelDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class NoNewWheelDecision:
    decision: NoNewWheelDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    navigation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "no_new_wheel_runtime_law_decision",
            "decision": self.decision.value,
            "passed": self.decision == NoNewWheelDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "navigation": dict(self.navigation),
        }


NO_NEW_WHEEL_RUNTIME_LAW_EVENT_TYPE = "NO_NEW_WHEEL_RUNTIME_LAW_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

REQUIRED_PACKET_FIELDS = (
    "runtime_law_id",
    "action_context",
    "repository_discovery",
    "capability_index_summary",
    "mandatory_capability_domains",
    "semantic_capability_matches",
    "reuse_plan",
    "no_new_wheel_proof",
    "CZL_closure",
    "truth_constraints",
)

REQUIRED_REPOS = {"bridge-labs", "Y-star-gov", "gov-mcp"}

DOMAIN_RULES: tuple[dict[str, Any], ...] = (
    {
        "domain_id": "czl_residual_loop_engine",
        "signals": ("residual", "failure", "rt+1", "r_t_plus_1", "czl", "goal", "target"),
        "correct_path": "reuse ystar/governance/residual_loop_engine.py and represent closure as Xt/U/Y*/Yt+1/Rt+1",
    },
    {
        "domain_id": "czl_message_protocol",
        "signals": ("codex", "executor", "dispatch", "receipt", "rt+1", "czl"),
        "correct_path": "reuse ystar/kernel/czl_protocol.py for dispatch/receipt 5-tuple validation",
    },
    {
        "domain_id": "cieu_prediction_delta",
        "signals": ("prediction", "delta", "residual", "learning", "brain"),
        "correct_path": "reuse ystar/governance/cieu_prediction_delta.py and docs/cieu_prediction_delta/schema_v0.md",
    },
    {
        "domain_id": "goal_tree_and_y_star_field",
        "signals": ("goal", "target", "y_star", "subgoal", "实现", "目标"),
        "correct_path": "reuse goal tree / Y* field validator before inventing target tracking",
    },
    {
        "domain_id": "ceo_doctrine_registry",
        "signals": ("doctrine", "operating model", "how to work", "能力", "方法论"),
        "correct_path": "reuse E91 CEO operating doctrine registry and invocation proof",
    },
    {
        "domain_id": "adaptive_governance_correct_path",
        "signals": ("governance", "correct_path", "deny", "导航", "治理"),
        "correct_path": "reuse E101 adaptive governance correct-path navigator",
    },
    {
        "domain_id": "ceo_implementation_order",
        "signals": ("codex", "executor", "implementation", "prompt", "实现"),
        "correct_path": "reuse E92 CEOImplementationOrder and CodexExecutionReceipt",
    },
    {
        "domain_id": "aiden_brain_runtime",
        "signals": ("brain", "大脑", "6d", "memory", "writeback", "learning"),
        "correct_path": "reuse Aiden brain runtime and E112 CIEU-backed brain learning candidate loop",
    },
    {
        "domain_id": "open_world_strategy_runtime",
        "signals": ("market", "strategy", "competitor", "pricing", "revenue", "赚钱", "战略", "竞品"),
        "correct_path": "reuse E108/E110 open-world strategy, freshness, competitor, math-model, and control-plane runtime",
    },
    {
        "domain_id": "gov_mcp_dry_run_boundary",
        "signals": ("provider", "tool", "external", "outbound", "dry-run", "live"),
        "correct_path": "reuse gov-mcp dry-run/no-send boundary before any provider/tool action",
    },
    {
        "domain_id": "cieu_store_formal_memory",
        "signals": ("cieu", "record", "memory", "evidence", "audit", "brain", "residual"),
        "correct_path": "reuse Y-star-gov CIEUStore.write_dict; do not create a parallel ledger",
    },
)

FORBIDDEN_TRUE_CLAIMS = (
    "recent_memory_sufficient",
    "prompt_summary_sufficient",
    "parallel_rebuild_allowed",
    "customer_validation_claim",
    "pricing_validation_claim",
    "revenue_claim",
    "payment_claim",
    "L5_revenue_loop_complete",
    "K9Audit_integration_claim",
    "live_provider_execution_claim",
)


def build_no_new_wheel_runtime_law_contract() -> dict[str, Any]:
    return {
        "contract_id": "no_new_wheel_runtime_law_v1",
        "event_type": NO_NEW_WHEEL_RUNTIME_LAW_EVENT_TYPE,
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        "required_packet_fields": list(REQUIRED_PACKET_FIELDS),
        "required_repos": sorted(REQUIRED_REPOS),
        "domain_rules": list(DOMAIN_RULES),
        "allow_condition": "full_system_capability_recall + mandatory reuse plan + CZL Rt+1=0",
    }


def required_domains_for_action_context(action_context: Mapping[str, Any]) -> list[str]:
    text = _text(action_context)
    required: list[str] = ["cieu_store_formal_memory", "adaptive_governance_correct_path"]
    for rule in DOMAIN_RULES:
        if any(signal.lower() in text for signal in rule["signals"]):
            required.append(str(rule["domain_id"]))
    return list(dict.fromkeys(required))


def validate_no_new_wheel_runtime_law_packet(packet: Mapping[str, Any]) -> NoNewWheelDecision:
    if not isinstance(packet, Mapping):
        return _deny("runtime law packet must be a mapping", "schema", ["packet_not_mapping"])

    missing_fields = [field for field in REQUIRED_PACKET_FIELDS if not _present(packet.get(field))]
    if missing_fields:
        return _revision(
            "no-new-wheel runtime law packet is missing required sections",
            "schema",
            [f"add {field}" for field in missing_fields],
        )

    forbidden = _forbidden_claim(packet)
    if forbidden:
        return _deny(f"forbidden bypass or overclaim present: {forbidden}", "truth_constraints", [forbidden])

    context = packet.get("action_context") if isinstance(packet.get("action_context"), Mapping) else {}
    expected_domains = required_domains_for_action_context(context)

    discovery = packet.get("repository_discovery") if isinstance(packet.get("repository_discovery"), Mapping) else {}
    repos_scanned = set(str(item) for item in discovery.get("repos_scanned", []) or [])
    if not REQUIRED_REPOS.issubset(repos_scanned):
        missing_repos = sorted(REQUIRED_REPOS - repos_scanned)
        return _revision(
            "full-system repository discovery must scan bridge-labs, Y-star-gov, and gov-mcp",
            "repository_discovery",
            [f"scan repo {repo}" for repo in missing_repos],
        )
    if discovery.get("full_system_scan_performed") is not True:
        return _revision(
            "full-system scan must be performed before implementation",
            "repository_discovery",
            ["run git ls-files / capability discovery for all three repos before code changes"],
        )
    if discovery.get("recent_memory_only") is True or discovery.get("prompt_summary_only") is True:
        return _deny(
            "recent memory or prompt summary cannot satisfy capability recall",
            "repository_discovery",
            ["recent_memory_or_prompt_summary_bypass"],
        )

    mandatory = [str(item) for item in packet.get("mandatory_capability_domains") or []]
    missing_mandatory = [domain for domain in expected_domains if domain not in mandatory]
    if missing_mandatory:
        return _revision(
            "action context implies mandatory capability domains that were not declared",
            "mandatory_capability_domains",
            [_correct_path_for(domain) for domain in missing_mandatory],
        )

    matches = packet.get("semantic_capability_matches")
    reuse_plan = packet.get("reuse_plan")
    if not isinstance(matches, list) or not isinstance(reuse_plan, list):
        return _revision(
            "semantic capability matches and reuse plan must be lists",
            "schema",
            ["build semantic_capability_matches and reuse_plan arrays from repository evidence"],
        )
    match_domains = {str(item.get("domain_id")) for item in matches if isinstance(item, Mapping)}
    plan_domains = {str(item.get("domain_id")) for item in reuse_plan if isinstance(item, Mapping)}
    missing_matches = [domain for domain in mandatory if domain not in match_domains]
    missing_plan = [domain for domain in mandatory if domain not in plan_domains]
    if missing_matches or missing_plan:
        return _revision(
            "mandatory domains must have both capability matches and reuse plan entries",
            "reuse_plan",
            [_correct_path_for(domain) for domain in sorted(set(missing_matches + missing_plan))],
        )

    for item in matches:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("runtime_status") or "") in {"deprecated", "quarantined", "stale"} and item.get("satisfies_mandatory_domain") is True:
            return _revision(
                "deprecated/quarantined/stale capability cannot satisfy a mandatory domain",
                "semantic_capability_matches",
                [_correct_path_for(str(item.get("domain_id")))],
            )
        if not item.get("source_paths"):
            return _revision(
                "capability match must include source_paths",
                "semantic_capability_matches",
                [f"add source evidence for domain {item.get('domain_id')}"],
            )

    for row in reuse_plan:
        if not isinstance(row, Mapping):
            continue
        if row.get("reuse_mode") in {"new_parallel_system", "rewrite_from_scratch"}:
            return _deny(
                "parallel rebuild is forbidden when canonical capability exists",
                "reuse_plan",
                [str(row.get("domain_id") or "unknown_domain")],
            )
        if row.get("will_reuse_existing_capability") is not True:
            return _revision(
                "reuse plan must explicitly reuse or extend existing capability",
                "reuse_plan",
                [_correct_path_for(str(row.get("domain_id") or "unknown_domain"))],
            )

    proof = packet.get("no_new_wheel_proof") if isinstance(packet.get("no_new_wheel_proof"), Mapping) else {}
    if proof.get("existing_capability_recall_completed") is not True or proof.get("all_mandatory_domains_satisfied") is not True:
        return _revision(
            "no-new-wheel proof must complete recall and satisfy all mandatory domains",
            "no_new_wheel_proof",
            ["rerun capability recall resolver until all mandatory domains are satisfied"],
        )
    if proof.get("parallel_rebuild_detected") is True:
        return _deny("parallel rebuild was detected", "no_new_wheel_proof", ["parallel_rebuild_detected"])

    czl = packet.get("CZL_closure") if isinstance(packet.get("CZL_closure"), Mapping) else {}
    missing_czl = [field for field in ("X_t", "U", "Y_star", "Y_t_plus_1", "R_t_plus_1") if field not in czl]
    if missing_czl:
        return _revision(
            "CZL closure must include the 5-tuple",
            "CZL_closure",
            [f"add CZL_closure.{field}" for field in missing_czl],
        )
    if czl.get("residual_loop_engine_path") != "ystar/governance/residual_loop_engine.py":
        return _revision(
            "CZL closure must bind to the existing ResidualLoopEngine",
            "CZL_closure",
            ["set residual_loop_engine_path to ystar/governance/residual_loop_engine.py"],
        )
    if _numeric(czl.get("R_t_plus_1")) != 0.0:
        return _revision(
            "runtime law closure is not complete until Rt+1 = 0",
            "CZL_closure",
            ["close missing capability reuse gaps", "rerun validation until R_t_plus_1 is 0"],
        )

    return NoNewWheelDecision(
        decision=NoNewWheelDecisionValue.ALLOW,
        reason="full-system existing-capability recall, reuse plan, and CZL Rt+1=0 closure satisfy no-new-wheel runtime law",
        navigation={
            "decision_mode": "allow_after_existing_capability_reuse",
            "next_allowed_action": "continue_with_reuse_or_extension_only",
            "parallel_rebuild_allowed": False,
            "recent_memory_sufficient": False,
        },
    )


def build_no_new_wheel_runtime_law_cieu_record(
    packet: Mapping[str, Any],
    decision: NoNewWheelDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, NoNewWheelDecision) else dict(decision)
    context = packet.get("action_context") if isinstance(packet.get("action_context"), Mapping) else {}
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(context.get("action_id") or "no_new_wheel_runtime_law"),
        "agent_id": "Aiden",
        "event_type": NO_NEW_WHEEL_RUNTIME_LAW_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "No-new-wheel runtime law decision",
        "contract_hash": "no-new-wheel-runtime-law-v1",
        "params": {
            "runtime_law_id": packet.get("runtime_law_id"),
            "operation_type": context.get("operation_type") or context.get("action_type"),
            "mandatory_capability_domains": list(packet.get("mandatory_capability_domains") or []),
            "R_t_plus_1": packet.get("CZL_closure", {}).get("R_t_plus_1")
            if isinstance(packet.get("CZL_closure"), Mapping)
            else None,
        },
        "result": {
            "decision": data.get("decision"),
            "reason": data.get("reason"),
            "correct_path": list(data.get("correct_path") or []),
            "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
        },
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "CIEUStore", "CZL"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": data.get("decision") == "ALLOW",
    }


def write_no_new_wheel_runtime_law_cieu_record(
    packet: Mapping[str, Any],
    decision: NoNewWheelDecision | Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    record = build_no_new_wheel_runtime_law_cieu_record(packet, decision, session_id=session_id)
    store = CIEUStore(cieu_db)
    written = store.write_dict(record)
    seal_result: dict[str, Any] = {}
    verify_result: dict[str, Any] = {}
    if seal_session:
        seal_result = store.seal_session(record["session_id"])
        verify_result = store.verify_session_seal(record["session_id"])
    return {
        "artifact_id": "no_new_wheel_runtime_law_cieu_write_result",
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


def validate_and_write_no_new_wheel_runtime_law_packet(
    packet: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
    seal_session: bool = False,
) -> dict[str, Any]:
    decision = validate_no_new_wheel_runtime_law_packet(packet)
    write_result = write_no_new_wheel_runtime_law_cieu_record(
        packet,
        decision,
        cieu_db=cieu_db,
        session_id=session_id,
        seal_session=seal_session,
    )
    return {
        "artifact_id": "no_new_wheel_runtime_law_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "CIEU_write_result": write_result,
        "formal_CIEU_log_written": write_result["formal_CIEU_log_written"],
        "formal_CIEU_log_status": write_result["formal_CIEU_log_status"],
        "validator_output_status": write_result["validator_output_status"],
    }


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> NoNewWheelDecision:
    path = [
        "stop implementation and repair no-new-wheel runtime law packet",
        "query existing capability index before writing new code",
        *correct_path,
    ]
    return NoNewWheelDecision(
        decision=NoNewWheelDecisionValue.REQUIRE_REVISION,
        reason=reason,
        failed_section=failed_section,
        correct_path=path,
        navigation={
            "decision_mode": "correct_path_navigation",
            "next_allowed_action": "capability_recall_and_reuse_repair_only",
            "correct_path": path,
        },
    )


def _deny(reason: str, failed_section: str, violations: list[str]) -> NoNewWheelDecision:
    return NoNewWheelDecision(
        decision=NoNewWheelDecisionValue.DENY,
        reason=reason,
        failed_section=failed_section,
        violations=violations,
        correct_path=["remove bypass/parallel rebuild/false claim", "return to full-system capability recall gate"],
        navigation={"decision_mode": "hard_stop", "next_allowed_action": "none_until_violation_removed"},
    )


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, (list, tuple, dict, set)):
        return True
    return True


def _forbidden_claim(packet: Mapping[str, Any]) -> str:
    truth = packet.get("truth_constraints") if isinstance(packet.get("truth_constraints"), Mapping) else {}
    proof = packet.get("no_new_wheel_proof") if isinstance(packet.get("no_new_wheel_proof"), Mapping) else {}
    for field in FORBIDDEN_TRUE_CLAIMS:
        if truth.get(field) is True or proof.get(field) is True:
            return field
    return ""


def _correct_path_for(domain_id: str) -> str:
    for rule in DOMAIN_RULES:
        if rule["domain_id"] == domain_id:
            return str(rule["correct_path"])
    return f"locate and reuse existing capability for {domain_id}; do not create a parallel system"


def _numeric(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")


def _text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(f"{key} {_text(item)}" for key, item in value.items()).lower()
    if isinstance(value, list):
        return " ".join(_text(item) for item in value).lower()
    return str(value or "").lower()


__all__ = [
    "DOMAIN_RULES",
    "FORMAL_CIEU_LOG_PATH",
    "NO_NEW_WHEEL_RUNTIME_LAW_EVENT_TYPE",
    "NoNewWheelDecision",
    "NoNewWheelDecisionValue",
    "build_no_new_wheel_runtime_law_cieu_record",
    "build_no_new_wheel_runtime_law_contract",
    "required_domains_for_action_context",
    "validate_and_write_no_new_wheel_runtime_law_packet",
    "validate_no_new_wheel_runtime_law_packet",
    "write_no_new_wheel_runtime_law_cieu_record",
]
