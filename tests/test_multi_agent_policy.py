# tests/test_multi_agent_policy.py
"""
Tests: per-agent Policy parsing, agent identity detection, write boundary enforcement.
All tests use generic role names (doctor/nurse/admin) to verify the mechanism
is universal and not coupled to any specific deployment.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ystar.session import Policy
from ystar.adapters.hook import (
    _detect_agent_id,
    _check_write_boundary,
    _load_write_paths_from_agents_md,
    _ensure_write_paths_loaded,
    _AGENT_WRITE_PATHS,
    check_hook,
    _extract_params,
)
import ystar.adapters.hook as hook_module


# ── Fixtures ──────────────────────────────────────────────────────────────

SAMPLE_AGENTS_MD = """# Test Governance Contract

## Absolute Prohibitions (All Agents)

### Forbidden Paths (Cannot Read or Write)
- .env, .secret
- /etc/, /root/

### Forbidden Commands
- rm -rf /
- sudo

## Doctor Agent (Diagnosis)

### Role
Diagnoses patients.

### Write Access
- ./patient_records/
- ./diagnosis/

### Read Access
- All directories

You absolutely cannot access: ./billing/, /admin_panel

## Nurse Agent (Care)

### Role
Provides patient care.

### Write Access
- ./care_logs/
- ./medication/

### Read Access
- All directories

## Admin Agent (Operations)

### Role
Manages operations.

### Write Access
- ./billing/
- ./reports/
- ./scheduling/

### Read Access
- All directories
"""


@pytest.fixture
def agents_md(tmp_path):
    md = tmp_path / "AGENTS.md"
    md.write_text(SAMPLE_AGENTS_MD)
    return str(md)


# ── from_agents_md_multi ──────────────────────────────────────────────────


class TestFromAgentsMdMulti:
    """Test dynamic multi-agent policy parsing from AGENTS.md."""

    def test_parses_all_agents(self, agents_md):
        policy = Policy.from_agents_md_multi(agents_md)
        assert "doctor" in policy
        assert "nurse" in policy
        assert "admin" in policy

    def test_produces_fallback(self, agents_md):
        policy = Policy.from_agents_md_multi(agents_md)
        assert "agent" in policy

    def test_global_deny_applied(self, agents_md):
        policy = Policy.from_agents_md_multi(agents_md)
        for name in ["doctor", "nurse", "admin", "agent"]:
            contract = policy._rules[name]
            assert ".env" in contract.deny or any(".env" in d for d in contract.deny)

    def test_global_deny_commands(self, agents_md):
        policy = Policy.from_agents_md_multi(agents_md)
        contract = policy._rules["doctor"]
        assert any("rm -rf" in cmd for cmd in contract.deny_commands)
        assert any("sudo" in cmd for cmd in contract.deny_commands)

    def test_agent_extra_deny(self, agents_md):
        """Doctor's 'cannot access' paths should be in deny."""
        policy = Policy.from_agents_md_multi(agents_md)
        contract = policy._rules["doctor"]
        deny_str = " ".join(contract.deny)
        assert "billing" in deny_str or "admin_panel" in deny_str

    def test_missing_file_returns_fallback(self):
        policy = Policy.from_agents_md_multi("/nonexistent/AGENTS.md")
        assert "agent" in policy

    def test_env_denied_for_all(self, agents_md):
        policy = Policy.from_agents_md_multi(agents_md)
        result = policy.check("nurse", "Write", file_path="./data/.env.production")
        assert not result.allowed

    def test_sudo_denied(self, agents_md):
        policy = Policy.from_agents_md_multi(agents_md)
        result = policy.check("doctor", "Bash", command="sudo rm -rf /tmp")
        assert not result.allowed

    def test_normal_action_allowed(self, agents_md):
        policy = Policy.from_agents_md_multi(agents_md)
        result = policy.check("doctor", "Write", file_path="./patient_records/p1.md")
        assert result.allowed


# ── Agent Identity Detection ──────────────────────────────────────────────


class TestDetectAgentId:

    def test_from_payload(self):
        assert _detect_agent_id({"agent_id": "doctor"}) == "doctor"

    def test_from_env_ystar(self):
        with patch.dict(os.environ, {"YSTAR_AGENT_ID": "nurse"}):
            assert _detect_agent_id({"tool_name": "Write"}) == "nurse"

    def test_from_marker_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".ystar_active_agent").write_text("admin")
        with patch.dict(os.environ, {}, clear=True):
            assert _detect_agent_id({"tool_name": "Write"}) == "admin"

    def test_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            result = _detect_agent_id({"tool_name": "Write"})
            assert isinstance(result, str)

    def test_generic_agent_falls_through(self):
        with patch.dict(os.environ, {"YSTAR_AGENT_ID": "doctor"}):
            assert _detect_agent_id({"agent_id": "agent"}) == "doctor"


# ── Write Boundary (Dynamic) ─────────────────────────────────────────────


class TestWriteBoundary:
    """Test write path enforcement using dynamically loaded paths."""

    @pytest.fixture(autouse=True)
    def setup_paths(self, tmp_path, monkeypatch):
        """Set up write paths from sample AGENTS.md."""
        monkeypatch.chdir(tmp_path)
        md = tmp_path / "AGENTS.md"
        md.write_text(SAMPLE_AGENTS_MD)

        # Reset and reload
        hook_module._WRITE_PATHS_LOADED = False
        hook_module._AGENT_WRITE_PATHS = {}
        hook_module._ensure_write_paths_loaded()

    def test_doctor_allowed_patient_records(self):
        params = _extract_params("Write", {"file_path": "./patient_records/p1.md"})
        result = _check_write_boundary("doctor", "Write", params)
        assert result is None  # allowed

    def test_doctor_denied_billing(self):
        params = _extract_params("Write", {"file_path": "./billing/invoice.md"})
        result = _check_write_boundary("doctor", "Write", params)
        assert result is not None
        assert not result.allowed

    def test_nurse_allowed_care_logs(self):
        params = _extract_params("Write", {"file_path": "./care_logs/today.md"})
        result = _check_write_boundary("nurse", "Write", params)
        assert result is None

    def test_nurse_denied_billing(self):
        params = _extract_params("Write", {"file_path": "./billing/invoice.md"})
        result = _check_write_boundary("nurse", "Write", params)
        assert result is not None

    def test_admin_allowed_billing(self):
        params = _extract_params("Write", {"file_path": "./billing/invoice.md"})
        result = _check_write_boundary("admin", "Write", params)
        assert result is None

    def test_admin_denied_patient_records(self):
        params = _extract_params("Write", {"file_path": "./patient_records/p1.md"})
        result = _check_write_boundary("admin", "Write", params)
        assert result is not None

    def test_read_not_checked(self):
        params = _extract_params("Read", {"file_path": "./billing/secret.md"})
        result = _check_write_boundary("doctor", "Read", params)
        assert result is None

    def test_unknown_agent_not_checked(self):
        params = _extract_params("Write", {"file_path": "./anything.md"})
        result = _check_write_boundary("unknown", "Write", params)
        assert result is None

    def test_edit_also_checked(self):
        params = _extract_params("Edit", {"file_path": "./billing/invoice.md"})
        result = _check_write_boundary("doctor", "Edit", params)
        assert result is not None


# ── Hook Integration ─────────────────────────────────────────────────────


class TestHookIntegration:

    @pytest.fixture
    def policy(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        md = tmp_path / "AGENTS.md"
        md.write_text(SAMPLE_AGENTS_MD)
        # Reset write paths
        hook_module._WRITE_PATHS_LOADED = False
        hook_module._AGENT_WRITE_PATHS = {}
        return Policy.from_agents_md_multi(str(md))

    def test_doctor_write_own_path_allowed(self, policy):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "./patient_records/p1.md"},
            "agent_id": "doctor",
        }
        response = check_hook(payload, policy)
        assert response == {} or "action" not in response

    def test_doctor_write_other_path_denied(self, policy):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "./billing/hack.md"},
            "agent_id": "doctor",
        }
        response = check_hook(payload, policy)
        assert response.get("action") == "block"

    def test_env_denied_all(self, policy):
        for agent in ["doctor", "nurse", "admin"]:
            payload = {
                "tool_name": "Write",
                "tool_input": {"file_path": "./.env.production"},
                "agent_id": agent,
            }
            response = check_hook(payload, policy)
            assert response.get("action") == "block", f"{agent} should be denied .env"

    def test_read_always_allowed(self, policy):
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "./billing/secret.md"},
            "agent_id": "doctor",
        }
        response = check_hook(payload, policy)
        assert response == {} or "action" not in response
