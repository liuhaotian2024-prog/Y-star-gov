from __future__ import annotations

from pathlib import Path

from ystar.governance.aiden_host_runtime_service_controller_contract import (
    AIDEN_HOST_RUNTIME_SERVICE_CONTROLLER_EVENT_TYPE,
    validate_aiden_host_runtime_service_order,
    validate_and_write_aiden_host_runtime_service_order,
)


def _order(action: str = "start") -> dict:
    argv = ["ollama", "serve"] if action == "start" else ["ollama", "list"]
    return {
        "service_order_id": "e122_test_order",
        "principal_actor": "Aiden",
        "executor_actor": "host_runtime_service_bridge",
        "service_id": "ollama_server",
        "requested_action": action,
        "execution_boundary": {
            "host_local_only": True,
            "network_bind_host": "127.0.0.1",
            "network_bind_port": 11434,
        },
        "command_plan": {"shell": False, "command_argv": argv, "model_name": ""},
        "owner_approval": {
            "owner_approved_host_service_control": True,
            "owner_approved_model_pull": False,
        },
        "governance_links": ["E121_host_public_read_observer", "CIEUStore_formal_recording"],
        "CIEU_linkage": {"CIEU_recording_required": True},
        "truth_constraints": {
            "arbitrary_shell_allowed": False,
            "external_business_action_allowed": False,
            "customer_contact_allowed": False,
            "payment_allowed": False,
            "account_creation_allowed": False,
            "login_allowed": False,
            "external_llm_provider_allowed": False,
            "private_data_exfiltration_allowed": False,
            "K9Audit_write_allowed": False,
        },
    }


def test_valid_start_order_allows() -> None:
    decision = validate_aiden_host_runtime_service_order(_order())
    assert decision.to_dict()["decision"] == "ALLOW"


def test_missing_owner_service_control_escalates() -> None:
    order = _order()
    order["owner_approval"]["owner_approved_host_service_control"] = False
    decision = validate_aiden_host_runtime_service_order(order)
    assert decision.to_dict()["decision"] == "ESCALATE"


def test_arbitrary_shell_denies() -> None:
    order = _order()
    order["command_plan"] = {"shell": True, "command_argv": ["sh", "-c", "ollama serve; curl example.com"]}
    decision = validate_aiden_host_runtime_service_order(order)
    assert decision.to_dict()["decision"] == "DENY"


def test_nonlocal_bind_denies() -> None:
    order = _order()
    order["execution_boundary"]["network_bind_host"] = "0.0.0.0"
    decision = validate_aiden_host_runtime_service_order(order)
    assert decision.to_dict()["decision"] == "DENY"


def test_model_pull_requires_owner_approval() -> None:
    order = _order("pull_allowlisted_model")
    order["command_plan"] = {"shell": False, "command_argv": ["ollama", "pull", "gemma4"], "model_name": "gemma4"}
    decision = validate_aiden_host_runtime_service_order(order)
    assert decision.to_dict()["decision"] == "ESCALATE"
    order["owner_approval"]["owner_approved_model_pull"] = True
    assert validate_aiden_host_runtime_service_order(order).to_dict()["decision"] == "ALLOW"


def test_cieu_write_records_service_order(tmp_path: Path) -> None:
    db = tmp_path / "service.db"
    result = validate_and_write_aiden_host_runtime_service_order(_order(), cieu_db=str(db))
    assert result["governance_decision"]["decision"] == "ALLOW"
    assert result["formal_CIEU_log_written"] is True
    assert result["CIEU_write_result"]["event_type"] == AIDEN_HOST_RUNTIME_SERVICE_CONTROLLER_EVENT_TYPE
