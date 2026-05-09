"""Governance for host-local runtime service control.

Aiden may need local services such as Ollama/Gemma to create long-term value.
This contract makes that possible without granting arbitrary terminal access:
only structured, allowlisted service orders may reach the host bridge.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional

from ystar.governance.cieu_store import CIEUStore


class AidenHostRuntimeServiceDecisionValue(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class AidenHostRuntimeServiceDecision:
    decision: AidenHostRuntimeServiceDecisionValue
    reason: str
    failed_section: Optional[str] = None
    violations: list[str] = field(default_factory=list)
    correct_path: list[str] = field(default_factory=list)
    guidance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "aiden_host_runtime_service_controller_decision",
            "decision": self.decision.value,
            "passed": self.decision == AidenHostRuntimeServiceDecisionValue.ALLOW,
            "reason": self.reason,
            "failed_section": self.failed_section,
            "violations": list(self.violations),
            "correct_path": list(self.correct_path),
            "guidance": dict(self.guidance),
        }


AIDEN_HOST_RUNTIME_SERVICE_CONTROLLER_EVENT_TYPE = "AIDEN_HOST_RUNTIME_SERVICE_CONTROLLER_DECISION"
FORMAL_CIEU_LOG_PATH = "ystar.governance.cieu_store.CIEUStore.write_dict"

ALLOWED_SERVICES = {"ollama_server"}
ALLOWED_ACTIONS = {
    "health_check",
    "start",
    "stop",
    "probe_models",
    "pull_allowlisted_model",
    "smoke_test_generate",
}
ALLOWED_MODELS = {"gemma4", "gemma4:e4b", "gemma4:latest", "gemma3", "gemma3:latest", "ystar-gemma"}
FORBIDDEN_TRUE_CLAIMS = (
    "arbitrary_shell_allowed",
    "external_business_action_allowed",
    "customer_contact_allowed",
    "payment_allowed",
    "account_creation_allowed",
    "login_allowed",
    "external_llm_provider_allowed",
    "private_data_exfiltration_allowed",
    "K9Audit_write_allowed",
)


def build_aiden_host_runtime_service_controller_contract() -> dict[str, Any]:
    return {
        "contract_id": "aiden_host_runtime_service_controller_contract_v1",
        "event_type": AIDEN_HOST_RUNTIME_SERVICE_CONTROLLER_EVENT_TYPE,
        "allowed_services": sorted(ALLOWED_SERVICES),
        "allowed_actions": sorted(ALLOWED_ACTIONS),
        "allowed_models": sorted(ALLOWED_MODELS),
        "formal_CIEU_log_path": FORMAL_CIEU_LOG_PATH,
    }


def validate_aiden_host_runtime_service_order(order: Mapping[str, Any]) -> AidenHostRuntimeServiceDecision:
    if not isinstance(order, Mapping):
        return _deny("host runtime service order must be a mapping", "schema", ["order_not_mapping"])

    required = (
        "service_order_id",
        "principal_actor",
        "executor_actor",
        "service_id",
        "requested_action",
        "execution_boundary",
        "command_plan",
        "owner_approval",
        "governance_links",
        "CIEU_linkage",
        "truth_constraints",
    )
    missing = [field for field in required if field not in order]
    if missing:
        return _revision("host runtime service order is missing required sections", "schema", [f"add {field}" for field in missing])

    if order.get("principal_actor") != "Aiden":
        return _revision("service principal must be Aiden", "principal_actor", ["set principal_actor=Aiden"])
    if order.get("executor_actor") != "host_runtime_service_bridge":
        return _revision("service executor must be the host runtime service bridge", "executor_actor", ["set executor_actor=host_runtime_service_bridge"])

    truth = _mapping(order.get("truth_constraints"))
    forbidden = [key for key in FORBIDDEN_TRUE_CLAIMS if truth.get(key) is True]
    if forbidden:
        return _deny("host runtime order contains forbidden side-effect scope", "truth_constraints", forbidden)

    service_id = str(order.get("service_id") or "")
    action = str(order.get("requested_action") or "")
    if service_id not in ALLOWED_SERVICES:
        return _deny("service is not in the host runtime allowlist", "service_id", [service_id or "missing_service_id"])
    if action not in ALLOWED_ACTIONS:
        return _deny("requested action is not in the host runtime allowlist", "requested_action", [action or "missing_action"])

    boundary = _mapping(order.get("execution_boundary"))
    if boundary.get("host_local_only") is not True:
        return _revision("host service control must be host-local only", "execution_boundary", ["set host_local_only=true"])
    if str(boundary.get("network_bind_host") or "") not in {"127.0.0.1", "localhost"}:
        return _deny("service may only bind localhost", "execution_boundary", [str(boundary.get("network_bind_host") or "missing_host")])
    if int(boundary.get("network_bind_port") or 0) != 11434:
        return _deny("Ollama service may only use localhost port 11434", "execution_boundary", [str(boundary.get("network_bind_port") or "missing_port")])

    owner = _mapping(order.get("owner_approval"))
    if owner.get("owner_approved_host_service_control") is not True:
        return _escalate(
            "starting/stopping host services requires owner-approved service-control boundary",
            "owner_approval",
            ["owner must approve host service controller before execution"],
        )
    if action == "pull_allowlisted_model" and owner.get("owner_approved_model_pull") is not True:
        return _escalate(
            "model downloads require owner approval because they use network, disk, and time",
            "owner_approval",
            ["set owner_approved_model_pull=true only after reviewing model and resource impact"],
        )

    command_decision = _validate_command_plan(_mapping(order.get("command_plan")), action=action)
    if command_decision:
        return command_decision

    links = set(_list(order.get("governance_links")))
    missing_links = sorted({"E121_host_public_read_observer", "CIEUStore_formal_recording"} - links)
    if missing_links:
        return _revision("service order is missing governance links", "governance_links", [f"add {link}" for link in missing_links])

    cieu = _mapping(order.get("CIEU_linkage"))
    if cieu.get("CIEU_recording_required") is not True:
        return _revision("host service order must be CIEU recorded before execution", "CIEU_linkage", ["set CIEU_recording_required=true"])

    return AidenHostRuntimeServiceDecision(
        decision=AidenHostRuntimeServiceDecisionValue.ALLOW,
        reason="host runtime service order is allowlisted, local-only, owner-approved, and governed",
        correct_path=["write service bridge job and let host_runtime_service_bridge execute the allowlisted action"],
        guidance={"service_id": service_id, "requested_action": action},
    )


def build_aiden_host_runtime_service_cieu_record(
    order: Mapping[str, Any],
    decision: AidenHostRuntimeServiceDecision | Mapping[str, Any],
    *,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    data = decision.to_dict() if isinstance(decision, AidenHostRuntimeServiceDecision) else dict(decision)
    return {
        "event_id": str(uuid.uuid4()),
        "seq_global": int(time.time() * 1_000_000),
        "created_at": time.time(),
        "session_id": session_id or str(order.get("service_order_id") or "aiden_host_runtime_service_controller"),
        "agent_id": "Aiden",
        "event_type": AIDEN_HOST_RUNTIME_SERVICE_CONTROLLER_EVENT_TYPE,
        "decision": "ALLOW" if data.get("decision") == "ALLOW" else "DENY",
        "passed": data.get("decision") == "ALLOW",
        "violations": list(data.get("violations") or []),
        "drift_detected": data.get("decision") != "ALLOW",
        "drift_details": None if data.get("decision") == "ALLOW" else data.get("reason"),
        "task_description": "Aiden host runtime service order validation",
        "contract_hash": "aiden-host-runtime-service-controller-v1",
        "params": {"service_id": order.get("service_id"), "requested_action": order.get("requested_action")},
        "result": {"decision": data.get("decision"), "reason": data.get("reason"), "correct_path": list(data.get("correct_path") or [])},
        "human_initiator": "owner",
        "lineage_path": ["bridge-labs", "Y-star-gov", "host-runtime-service-bridge", "CIEUStore"],
        "evidence_grade": "governance",
        "m_functor": "M-2b",
        "m_weight": 1.0,
        "y_star_validator_pass": data.get("decision") == "ALLOW",
    }


def validate_and_write_aiden_host_runtime_service_order(
    order: Mapping[str, Any],
    *,
    cieu_db: str,
    session_id: Optional[str] = None,
) -> dict[str, Any]:
    decision = validate_aiden_host_runtime_service_order(order)
    record = build_aiden_host_runtime_service_cieu_record(order, decision, session_id=session_id)
    written = CIEUStore(cieu_db).write_dict(record)
    return {
        "artifact_id": "aiden_host_runtime_service_order_validate_and_write_result",
        "governance_decision": decision.to_dict(),
        "formal_CIEU_log_written": bool(written),
        "formal_CIEU_log_status": "formal_CIEU_record_written" if written else "formal_CIEU_record_duplicate_existing",
        "CIEU_write_result": {"event_type": record["event_type"], "event_id": record["event_id"], "CIEU_record": record},
    }


def _validate_command_plan(command_plan: Mapping[str, Any], *, action: str) -> AidenHostRuntimeServiceDecision | None:
    argv = [str(part) for part in _list(command_plan.get("command_argv"))]
    if not argv:
        return _revision("command_plan.command_argv is required", "command_plan", ["provide non-shell argv list"])
    if command_plan.get("shell") is True or any(part in {";", "&&", "||", "|", ">", "<", "`"} for part in argv):
        return _deny("host service bridge forbids shell command strings/operators", "command_plan", argv)
    executable = argv[0]
    if executable not in {"ollama", "/opt/homebrew/bin/ollama"}:
        return _deny("only Ollama executable is allowed for current service controller", "command_plan", [executable])
    subcommand = argv[1] if len(argv) > 1 else ""
    allowed_by_action = {
        "health_check": {"list", "--version"},
        "probe_models": {"list"},
        "start": {"serve"},
        "stop": {"service-stop"},
        "pull_allowlisted_model": {"pull"},
        "smoke_test_generate": {"run"},
    }
    if subcommand not in allowed_by_action.get(action, set()):
        return _deny("Ollama command does not match requested action", "command_plan", [f"{action}:{subcommand}"])
    if action in {"pull_allowlisted_model", "smoke_test_generate"}:
        model = str(command_plan.get("model_name") or (argv[2] if len(argv) > 2 else ""))
        if model not in ALLOWED_MODELS:
            return _deny("model is not allowlisted for local Gemma runtime", "command_plan", [model or "missing_model"])
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _revision(reason: str, failed_section: str, correct_path: list[str]) -> AidenHostRuntimeServiceDecision:
    return AidenHostRuntimeServiceDecision(AidenHostRuntimeServiceDecisionValue.REQUIRE_REVISION, reason, failed_section, correct_path=correct_path)


def _deny(reason: str, failed_section: str, violations: list[str]) -> AidenHostRuntimeServiceDecision:
    return AidenHostRuntimeServiceDecision(AidenHostRuntimeServiceDecisionValue.DENY, reason, failed_section, violations=violations, correct_path=["remove forbidden command/scope and rebuild an allowlisted service order"])


def _escalate(reason: str, failed_section: str, correct_path: list[str]) -> AidenHostRuntimeServiceDecision:
    return AidenHostRuntimeServiceDecision(AidenHostRuntimeServiceDecisionValue.ESCALATE, reason, failed_section, correct_path=correct_path)


__all__ = [
    "AIDEN_HOST_RUNTIME_SERVICE_CONTROLLER_EVENT_TYPE",
    "AidenHostRuntimeServiceDecision",
    "AidenHostRuntimeServiceDecisionValue",
    "build_aiden_host_runtime_service_controller_contract",
    "validate_aiden_host_runtime_service_order",
    "validate_and_write_aiden_host_runtime_service_order",
    "build_aiden_host_runtime_service_cieu_record",
]
