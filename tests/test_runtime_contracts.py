"""
tests/test_runtime_contracts.py -- Runtime constraint file I/O tests

Covers:
  - load_runtime_deny / load_runtime_relax (file read)
  - write_runtime_deny / write_runtime_relax (file write + validation)
  - merge_contracts (three-layer merge)
  - Monotonicity enforcement
  - Quality threshold enforcement
"""
import json
import os
import pytest
from unittest.mock import MagicMock

from ystar.kernel.dimensions import IntentContract
from ystar.adapters.runtime_contracts import (
    load_runtime_deny,
    load_runtime_relax,
    write_runtime_deny,
    write_runtime_relax,
    merge_contracts,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


def _session_contract() -> IntentContract:
    """A baseline session contract that deny/relax must respect."""
    return IntentContract(
        deny=["/etc", "/production"],
        deny_commands=["rm -rf", "sudo"],
        only_paths=["/workspace"],
    )


def _make_cieu_mock():
    """A mock CIEU store that records write() calls."""
    store = MagicMock()
    store.write = MagicMock()
    return store


# ── Load tests ────────────────────────────────────────────────────────────


class TestLoadRuntimeDeny:

    def test_returns_none_when_no_file(self, tmp_path):
        result = load_runtime_deny(str(tmp_path))
        assert result is None

    def test_loads_valid_file(self, tmp_path):
        data = {"deny": ["/etc", "/production", "/staging"],
                "deny_commands": ["rm -rf", "sudo"]}
        (tmp_path / ".ystar_runtime_deny.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        result = load_runtime_deny(str(tmp_path))
        assert result is not None
        assert "/staging" in result.deny
        assert "/etc" in result.deny

    def test_returns_none_on_invalid_json(self, tmp_path):
        (tmp_path / ".ystar_runtime_deny.json").write_text(
            "not valid json", encoding="utf-8"
        )
        result = load_runtime_deny(str(tmp_path))
        assert result is None

    def test_loads_empty_contract(self, tmp_path):
        (tmp_path / ".ystar_runtime_deny.json").write_text(
            json.dumps({}), encoding="utf-8"
        )
        result = load_runtime_deny(str(tmp_path))
        assert result is not None
        assert result.deny == []


class TestLoadRuntimeRelax:

    def test_returns_none_when_no_file(self, tmp_path):
        result = load_runtime_relax(str(tmp_path))
        assert result is None

    def test_loads_valid_file(self, tmp_path):
        data = {"deny": ["/etc"], "only_paths": ["/workspace"]}
        (tmp_path / ".ystar_runtime_relax.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        result = load_runtime_relax(str(tmp_path))
        assert result is not None
        assert "/etc" in result.deny


# ── Write tests ───────────────────────────────────────────────────────────


class TestWriteRuntimeDeny:

    def test_write_valid_deny(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        session = _session_contract()
        # A stricter contract (superset of deny rules, subset of paths)
        contract = IntentContract(
            deny=["/etc", "/production", "/staging"],
            deny_commands=["rm -rf", "sudo", "dd"],
            only_paths=["/workspace"],
        )
        cieu = _make_cieu_mock()
        result = write_runtime_deny(contract, session, cieu, "agent1")

        assert result is True
        assert (tmp_path / ".ystar_runtime_deny.json").exists()
        cieu.write.assert_called_once()
        event = cieu.write.call_args[0][0]
        assert event["event_type"] == "runtime_deny_applied"

    def test_reject_looser_deny(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        session = _session_contract()
        # This contract DROPS /production from deny -- violates monotonicity
        contract = IntentContract(
            deny=["/etc"],  # missing /production
            deny_commands=["rm -rf", "sudo"],
            only_paths=["/workspace"],
        )
        cieu = _make_cieu_mock()
        result = write_runtime_deny(contract, session, cieu, "agent1")

        assert result is False
        assert not (tmp_path / ".ystar_runtime_deny.json").exists()
        cieu.write.assert_called_once()
        event = cieu.write.call_args[0][0]
        assert event["event_type"] == "runtime_deny_rejected"

    def test_write_with_none_cieu(self, tmp_path, monkeypatch):
        """write_runtime_deny should still work with cieu_store=None."""
        monkeypatch.chdir(tmp_path)
        session = _session_contract()
        contract = IntentContract(
            deny=["/etc", "/production"],
            deny_commands=["rm -rf", "sudo"],
            only_paths=["/workspace"],
        )
        result = write_runtime_deny(contract, session, None, "agent1")
        assert result is True
        assert (tmp_path / ".ystar_runtime_deny.json").exists()


class TestWriteRuntimeRelax:

    def test_write_valid_relax(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        session = _session_contract()
        # A contract that stays within session boundaries
        contract = IntentContract(
            deny=["/etc", "/production"],
            deny_commands=["rm -rf", "sudo"],
            only_paths=["/workspace"],
        )
        cieu = _make_cieu_mock()
        result = write_runtime_relax(contract, session, 0.80, cieu, "agent1")

        assert result is True
        assert (tmp_path / ".ystar_runtime_relax.json").exists()
        cieu.write.assert_called_once()
        event = cieu.write.call_args[0][0]
        assert event["event_type"] == "runtime_relax_applied"

    def test_reject_low_quality(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        session = _session_contract()
        contract = IntentContract(
            deny=["/etc", "/production"],
            deny_commands=["rm -rf", "sudo"],
            only_paths=["/workspace"],
        )
        cieu = _make_cieu_mock()
        result = write_runtime_relax(contract, session, 0.50, cieu, "agent1")

        assert result is False
        assert not (tmp_path / ".ystar_runtime_relax.json").exists()

    def test_reject_exceeds_boundary(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        session = _session_contract()
        # Drops /production from deny -- exceeds session boundary
        contract = IntentContract(
            deny=["/etc"],
            deny_commands=["rm -rf", "sudo"],
            only_paths=["/workspace"],
        )
        cieu = _make_cieu_mock()
        result = write_runtime_relax(contract, session, 0.90, cieu, "agent1")

        assert result is False

    def test_threshold_boundary(self, tmp_path, monkeypatch):
        """Quality score exactly at 0.65 should pass."""
        monkeypatch.chdir(tmp_path)
        session = _session_contract()
        contract = IntentContract(
            deny=["/etc", "/production"],
            deny_commands=["rm -rf", "sudo"],
            only_paths=["/workspace"],
        )
        cieu = _make_cieu_mock()
        result = write_runtime_relax(contract, session, 0.65, cieu, "agent1")
        assert result is True

    def test_threshold_just_below(self, tmp_path, monkeypatch):
        """Quality score at 0.649 should fail."""
        monkeypatch.chdir(tmp_path)
        session = _session_contract()
        contract = IntentContract(
            deny=["/etc", "/production"],
            deny_commands=["rm -rf", "sudo"],
            only_paths=["/workspace"],
        )
        cieu = _make_cieu_mock()
        result = write_runtime_relax(contract, session, 0.649, cieu, "agent1")
        assert result is False


# ── Merge tests ───────────────────────────────────────────────────────────


class TestMergeContracts:

    def test_no_overrides_returns_session(self):
        session = _session_contract()
        result = merge_contracts(session, None, None)
        assert result.deny == session.deny
        assert result.deny_commands == session.deny_commands

    def test_deny_tightens(self):
        session = _session_contract()
        deny = IntentContract(
            deny=["/staging"],
            deny_commands=["curl"],
        )
        result = merge_contracts(session, deny, None)
        # Should have both session deny AND the additional deny
        assert "/etc" in result.deny
        assert "/production" in result.deny
        assert "/staging" in result.deny
        # deny_commands should be merged too
        assert "rm -rf" in result.deny_commands
        assert "curl" in result.deny_commands

    def test_relax_alone_returns_session(self):
        """Relax without deny should still return session (placeholder behavior)."""
        session = _session_contract()
        relax = IntentContract(deny=["/etc", "/production"])
        result = merge_contracts(session, None, relax)
        # Placeholder: relax is not yet applied, so session unchanged
        assert result.deny == session.deny

    def test_deny_and_relax(self):
        """With both deny and relax, deny should be applied (relax is placeholder)."""
        session = _session_contract()
        deny = IntentContract(deny=["/staging"])
        relax = IntentContract(deny=["/etc", "/production"])
        result = merge_contracts(session, deny, relax)
        assert "/staging" in result.deny
        assert "/etc" in result.deny
