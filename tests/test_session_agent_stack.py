"""
Tests for Layer 1 Identity Source of Truth (AMENDMENT-015 Phase 4).

Verifies:
- push_agent() / pop_agent() / current_agent() APIs
- Agent stack auto-restore on sub-agent exit
- Session config is single source of truth
"""
import json
import os
import tempfile
from pathlib import Path

import pytest

from ystar.session import (
    current_agent,
    push_agent,
    pop_agent,
    set_agent,
    check_agent_stack_timeout,
    load_session_config,
    save_session_config,
)


@pytest.fixture
def temp_session_config():
    """Create temporary session config file for isolated testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session_path = Path(tmpdir) / ".ystar_session.json"
        # Initialize with minimal config
        config = {
            "session_id": "test",
            "agent_id": "ceo",
            "agent_stack": ["ceo"]
        }
        with open(session_path, 'w') as f:
            json.dump(config, f)

        # Change to temp directory so APIs find the config
        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        yield session_path
        os.chdir(old_cwd)


def test_current_agent_reads_from_session_config(temp_session_config):
    """Verify current_agent() reads from .ystar_session.json."""
    agent = current_agent()
    assert agent == "ceo"


def test_current_agent_returns_stack_top(temp_session_config):
    """Verify current_agent() returns top of agent_stack."""
    config = load_session_config()
    config["agent_stack"] = ["ceo", "cto"]
    save_session_config(config)

    agent = current_agent()
    assert agent == "cto"


def test_push_agent_adds_to_stack(temp_session_config):
    """Verify push_agent() adds to stack and updates agent_id."""
    push_agent("cto")

    config = load_session_config()
    assert config["agent_stack"] == ["ceo", "cto"]
    assert config["agent_id"] == "cto"
    assert current_agent() == "cto"


def test_pop_agent_restores_previous(temp_session_config):
    """Verify pop_agent() restores previous agent."""
    push_agent("cto")
    push_agent("cfo")
    assert current_agent() == "cfo"

    restored = pop_agent()
    assert restored == "cto"
    assert current_agent() == "cto"

    config = load_session_config()
    assert config["agent_stack"] == ["ceo", "cto"]
    assert config["agent_id"] == "cto"


def test_pop_agent_preserves_root(temp_session_config):
    """Verify pop_agent() never removes the root agent."""
    assert current_agent() == "ceo"

    restored = pop_agent()
    assert restored == "ceo"
    assert current_agent() == "ceo"

    config = load_session_config()
    assert config["agent_stack"] == ["ceo"]


def test_set_agent_replaces_stack(temp_session_config):
    """Verify set_agent() replaces entire stack."""
    push_agent("cto")
    push_agent("cfo")
    assert current_agent() == "cfo"

    set_agent("eng-kernel")
    assert current_agent() == "eng-kernel"

    config = load_session_config()
    assert config["agent_stack"] == ["eng-kernel"]
    assert config["agent_id"] == "eng-kernel"


def test_agent_delegation_round_trip(temp_session_config):
    """Integration test: CEO → CTO → CFO, then pop back to CEO."""
    assert current_agent() == "ceo"

    push_agent("cto")
    assert current_agent() == "cto"

    push_agent("cfo")
    assert current_agent() == "cfo"

    pop_agent()
    assert current_agent() == "cto"

    pop_agent()
    assert current_agent() == "ceo"

    config = load_session_config()
    assert config["agent_stack"] == ["ceo"]


def test_session_config_fallback_without_stack(temp_session_config):
    """Verify fallback to legacy agent_id field if agent_stack missing."""
    config = load_session_config()
    # Remove agent_stack to simulate legacy config
    del config["agent_stack"]
    config["agent_id"] = "cto"
    save_session_config(config)

    agent = current_agent()
    assert agent == "cto"


def test_current_agent_fallback_without_config():
    """Verify fallback to 'agent' if no session config exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        # No .ystar_session.json file
        agent = current_agent()
        assert agent == "agent"
        os.chdir(old_cwd)


def test_check_agent_stack_timeout_no_op_for_root_only(temp_session_config):
    """Verify timeout check is no-op if only root agent in stack."""
    was_stale = check_agent_stack_timeout(timeout_seconds=1)
    assert was_stale is False

    config = load_session_config()
    assert config["agent_stack"] == ["ceo"]


def test_check_agent_stack_timeout_triggers_after_delay(temp_session_config):
    """Verify timeout auto-pops stale sub-agents."""
    import time

    push_agent("cto")
    push_agent("cfo")
    assert current_agent() == "cfo"

    # Manually set last_change to past
    config = load_session_config()
    config["agent_stack_last_change"] = time.time() - 400  # 400s ago
    save_session_config(config)

    was_stale = check_agent_stack_timeout(timeout_seconds=300)
    assert was_stale is True

    # Should reset to root agent
    assert current_agent() == "ceo"

    config = load_session_config()
    assert config["agent_stack"] == ["ceo"]


def test_push_agent_initializes_stack_from_legacy_agent_id(temp_session_config):
    """Verify push_agent() bootstraps stack from legacy agent_id if missing."""
    config = load_session_config()
    # Remove agent_stack to simulate legacy config
    del config["agent_stack"]
    config["agent_id"] = "cmo"
    save_session_config(config)

    push_agent("cto")

    config = load_session_config()
    # Stack should be bootstrapped from legacy agent_id
    assert config["agent_stack"] == ["cmo", "cto"]
    assert current_agent() == "cto"


def test_atomic_write_prevents_corruption(temp_session_config):
    """Verify save_session_config() uses atomic write."""
    config = load_session_config()
    config["test_field"] = "test_value"

    # save_session_config should write to .tmp then rename
    save_session_config(config)

    # Verify no .tmp file remains
    tmp_path = Path(".ystar_session.json.tmp")
    assert not tmp_path.exists()

    # Verify content is correct
    reloaded = load_session_config()
    assert reloaded["test_field"] == "test_value"
