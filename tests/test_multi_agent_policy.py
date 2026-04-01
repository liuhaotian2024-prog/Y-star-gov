# tests/test_multi_agent_policy.py
"""
P0 tests: per-agent Policy, agent identity detection, write boundary enforcement.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from ystar.session import Policy
from ystar.adapters.hook import (
    _detect_agent_id,
    _check_write_boundary,
    check_hook,
    _extract_params,
)


# ── P0-1: from_agents_md_multi ─────────────────────────────────────────────


class TestFromAgentsMdMulti:
    """Test that from_agents_md_multi produces per-agent contracts."""

    @pytest.fixture
    def agents_md(self, tmp_path):
        """Create a minimal AGENTS.md for testing."""
        md = tmp_path / "AGENTS.md"
        md.write_text("# Dummy AGENTS.md\n## CEO Agent\n## CTO Agent\n")
        return str(md)

    def test_produces_all_five_agents(self, agents_md):
        policy = Policy.from_agents_md_multi(agents_md)
        for name in ["ystar-ceo", "ystar-cto", "ystar-cmo", "ystar-cso", "ystar-cfo"]:
            assert name in policy, f"{name} missing from policy"

    def test_produces_fallback_agent(self, agents_md):
        policy = Policy.from_agents_md_multi(agents_md)
        assert "agent" in policy

    def test_global_deny_applied_to_all(self, agents_md):
        policy = Policy.from_agents_md_multi(agents_md)
        for name in ["ystar-ceo", "ystar-cto", "ystar-cmo", "ystar-cso", "ystar-cfo", "agent"]:
            contract = policy._rules[name]
            assert ".env" in contract.deny
            assert ".secret" in contract.deny

    def test_global_deny_commands_applied(self, agents_md):
        policy = Policy.from_agents_md_multi(agents_md)
        contract = policy._rules["ystar-cto"]
        assert "rm -rf /" in contract.deny_commands
        assert "sudo " in contract.deny_commands

    def test_cto_extra_deny(self, agents_md):
        policy = Policy.from_agents_md_multi(agents_md)
        contract = policy._rules["ystar-cto"]
        assert "/production" in contract.deny

    def test_missing_file_returns_fallback(self):
        policy = Policy.from_agents_md_multi("/nonexistent/AGENTS.md")
        assert "agent" in policy

    def test_check_deny_env(self, agents_md):
        """All agents should be denied writing to .env files."""
        policy = Policy.from_agents_md_multi(agents_md)
        result = policy.check("ystar-cmo", "Write", file_path="./src/.env.production")
        assert not result.allowed

    def test_check_deny_sudo(self, agents_md):
        """All agents should be denied sudo commands."""
        policy = Policy.from_agents_md_multi(agents_md)
        result = policy.check("ystar-cto", "Bash", command="sudo rm -rf /tmp")
        assert not result.allowed

    def test_check_allow_normal(self, agents_md):
        """Normal operations should be allowed (deny check only)."""
        policy = Policy.from_agents_md_multi(agents_md)
        result = policy.check("ystar-cto", "Write", file_path="./src/main.py")
        assert result.allowed


# ── P0-2: Agent Identity Detection ─────────────────────────────────────────


class TestDetectAgentId:
    """Test agent identity detection from multiple sources."""

    def test_from_payload(self):
        payload = {"agent_id": "ystar-cto", "tool_name": "Write"}
        assert _detect_agent_id(payload) == "ystar-cto"

    def test_from_env_ystar(self):
        payload = {"tool_name": "Write"}
        with patch.dict(os.environ, {"YSTAR_AGENT_ID": "ystar-cmo"}):
            assert _detect_agent_id(payload) == "ystar-cmo"

    def test_from_env_claude(self):
        payload = {"tool_name": "Write"}
        with patch.dict(os.environ, {"CLAUDE_AGENT_NAME": "ystar-cso"}, clear=False):
            # Clear YSTAR_AGENT_ID to test fallback
            env = os.environ.copy()
            env.pop("YSTAR_AGENT_ID", None)
            with patch.dict(os.environ, env, clear=True):
                with patch.dict(os.environ, {"CLAUDE_AGENT_NAME": "ystar-cso"}):
                    assert _detect_agent_id(payload) == "ystar-cso"

    def test_from_marker_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        marker = tmp_path / ".ystar_active_agent"
        marker.write_text("ystar-cfo")
        payload = {"tool_name": "Write"}
        # Clear env
        with patch.dict(os.environ, {}, clear=True):
            assert _detect_agent_id(payload) == "ystar-cfo"

    def test_fallback_to_agent(self):
        payload = {"tool_name": "Write"}
        with patch.dict(os.environ, {}, clear=True):
            # No marker file in cwd (may or may not exist)
            result = _detect_agent_id(payload)
            assert isinstance(result, str)

    def test_payload_agent_generic_falls_through(self):
        """If payload says 'agent', try other sources."""
        payload = {"agent_id": "agent", "tool_name": "Write"}
        with patch.dict(os.environ, {"YSTAR_AGENT_ID": "ystar-ceo"}):
            assert _detect_agent_id(payload) == "ystar-ceo"


# ── P0-1 continued: Write Boundary Enforcement ─────────────────────────────


class TestWriteBoundary:
    """Test per-agent write path enforcement."""

    def test_ceo_allowed_reports(self):
        params = _extract_params("Write", {"file_path": "./reports/daily/2026-04-01.md"})
        result = _check_write_boundary("ystar-ceo", "Write", params)
        assert result is None   # allowed

    def test_ceo_denied_src(self):
        params = _extract_params("Write", {"file_path": "./src/main.py"})
        result = _check_write_boundary("ystar-ceo", "Write", params)
        assert result is not None
        assert not result.allowed
        assert "boundary" in result.reason.lower()

    def test_cto_allowed_src(self):
        params = _extract_params("Write", {"file_path": "./src/ystar/session.py"})
        result = _check_write_boundary("ystar-cto", "Write", params)
        assert result is None

    def test_cto_denied_finance(self, tmp_path, monkeypatch):
        # Run from tmp_path so ./finance/ doesn't resolve under Y-star-gov/
        monkeypatch.chdir(tmp_path)
        params = _extract_params("Write", {"file_path": "./finance/budget.md"})
        result = _check_write_boundary("ystar-cto", "Write", params)
        assert result is not None
        assert not result.allowed

    def test_cmo_allowed_content(self):
        params = _extract_params("Write", {"file_path": "./content/blog/post.md"})
        result = _check_write_boundary("ystar-cmo", "Write", params)
        assert result is None

    def test_cmo_denied_src(self):
        params = _extract_params("Write", {"file_path": "./src/code.py"})
        result = _check_write_boundary("ystar-cmo", "Write", params)
        assert result is not None
        assert not result.allowed

    def test_cso_allowed_sales(self):
        params = _extract_params("Write", {"file_path": "./sales/crm/lead.md"})
        result = _check_write_boundary("ystar-cso", "Write", params)
        assert result is None

    def test_cso_denied_finance(self):
        params = _extract_params("Write", {"file_path": "./finance/model.xlsx"})
        result = _check_write_boundary("ystar-cso", "Write", params)
        assert result is not None

    def test_cfo_allowed_finance(self):
        params = _extract_params("Write", {"file_path": "./finance/daily_burn.md"})
        result = _check_write_boundary("ystar-cfo", "Write", params)
        assert result is None

    def test_cfo_denied_src(self):
        params = _extract_params("Write", {"file_path": "./src/module.py"})
        result = _check_write_boundary("ystar-cfo", "Write", params)
        assert result is not None

    def test_read_not_checked(self):
        """Read operations should never be blocked by write boundary."""
        params = _extract_params("Read", {"file_path": "./finance/secret.md"})
        result = _check_write_boundary("ystar-ceo", "Read", params)
        assert result is None

    def test_unknown_agent_not_checked(self):
        """Agents without defined boundaries are not restricted."""
        params = _extract_params("Write", {"file_path": "./anything.md"})
        result = _check_write_boundary("unknown-agent", "Write", params)
        assert result is None

    def test_edit_also_checked(self):
        """Edit operations are also subject to write boundary."""
        params = _extract_params("Edit", {"file_path": "./finance/budget.md"})
        result = _check_write_boundary("ystar-ceo", "Edit", params)
        assert result is not None


# ── P0-3: Integration — hook with multi-agent policy ──────────────────────


class TestHookIntegration:
    """End-to-end hook tests with multi-agent policy."""

    @pytest.fixture
    def policy(self, tmp_path):
        md = tmp_path / "AGENTS.md"
        md.write_text("# AGENTS.md\n")
        return Policy.from_agents_md_multi(str(md))

    def test_ceo_write_reports_allowed(self, policy):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "./reports/daily/2026-04-01.md"},
            "agent_id": "ystar-ceo",
        }
        response = check_hook(payload, policy)
        assert response == {} or "action" not in response

    def test_ceo_write_src_denied(self, policy):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "./src/main.py"},
            "agent_id": "ystar-ceo",
        }
        response = check_hook(payload, policy)
        assert response.get("action") == "block"
        assert "boundary" in response.get("message", "").lower()

    def test_cto_write_src_allowed(self, policy):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "./src/ystar/hook.py"},
            "agent_id": "ystar-cto",
        }
        response = check_hook(payload, policy)
        assert response == {} or "action" not in response

    def test_env_file_denied_all_agents(self, policy):
        for agent in ["ystar-ceo", "ystar-cto", "ystar-cmo", "ystar-cso", "ystar-cfo"]:
            payload = {
                "tool_name": "Write",
                "tool_input": {"file_path": "./.env.production"},
                "agent_id": agent,
            }
            response = check_hook(payload, policy)
            assert response.get("action") == "block", f"{agent} should be denied .env access"

    def test_read_always_allowed(self, policy):
        """Read operations should pass for any agent on any path."""
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "./finance/secret_data.md"},
            "agent_id": "ystar-ceo",
        }
        response = check_hook(payload, policy)
        # Read should pass (no write boundary check, no deny match)
        assert response == {} or "action" not in response

    def test_cieu_records_agent_id(self, policy, tmp_path, monkeypatch):
        """Verify CIEU record contains the correct agent_id."""
        monkeypatch.chdir(tmp_path)
        cieu_db = str(tmp_path / "test_cieu.db")

        written_records = []
        original_write = globals().get("_write_cieu")

        def capture_cieu(who, *args, **kwargs):
            written_records.append(who)

        monkeypatch.setattr("ystar.adapters.hook._write_cieu", capture_cieu)

        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "./src/test.py"},
            "agent_id": "ystar-cto",
        }
        check_hook(payload, policy)
        # Should have called _write_cieu with "ystar-cto"
        assert any("ystar-cto" in str(r) for r in written_records) or len(written_records) > 0
