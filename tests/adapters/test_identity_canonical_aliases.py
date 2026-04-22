"""
Test canonical agent_id registry alias resolution.

Tests that full-form agent_ids (e.g., "Samantha-Secretary") resolve to
canonical short forms (e.g., "secretary") to eliminate AGENT_REGISTRY_K9_WARN
false positives.
"""
import json
from pathlib import Path

import pytest

from ystar.adapters.identity_detector import _map_agent_type

# Load canonical registry for integration test
REGISTRY_PATH = Path(__file__).parent.parent.parent.parent / "ystar-company" / "governance" / "agent_id_canonical.json"


def test_existing_staff_aliases():
    """Test that existing staff full-form names resolve."""
    assert _map_agent_type("Samantha-Secretary") == "secretary"
    assert _map_agent_type("Maya-Governance") == "eng-governance"
    assert _map_agent_type("Ryan-Platform") == "eng-platform"
    assert _map_agent_type("Ethan-CTO") == "cto"
    assert _map_agent_type("Leo-Kernel") == "eng-kernel"
    assert _map_agent_type("Jordan-Domains") == "eng-domains"


def test_new_engineer_aliases():
    """Test that new engineer full-form names resolve."""
    assert _map_agent_type("Alex-Security") == "eng-security"
    assert _map_agent_type("Priya-ML") == "eng-ml"
    assert _map_agent_type("Carlos-Performance") == "eng-perf"
    assert _map_agent_type("Elena-Compliance") == "eng-compliance"


def test_short_forms_passthrough():
    """Test that short forms pass through unchanged."""
    assert _map_agent_type("eng-platform") == "eng-platform"
    assert _map_agent_type("secretary") == "secretary"
    assert _map_agent_type("cto") == "cto"


def test_canonical_registry_has_aliases():
    """Integration test: verify registry file contains all aliases."""
    if not REGISTRY_PATH.exists():
        pytest.skip(f"Registry not found at {REGISTRY_PATH}")

    with open(REGISTRY_PATH, encoding="utf-8") as f:
        registry = json.load(f)

    aliases = registry.get("aliases", {})

    # Check existing staff aliases
    assert aliases.get("Samantha-Secretary") == "secretary"
    assert aliases.get("Maya-Governance") == "eng-governance"
    assert aliases.get("Ryan-Platform") == "eng-platform"

    # Check new engineer aliases
    assert aliases.get("Alex-Security") == "eng-security"
    assert aliases.get("Priya-ML") == "eng-ml"
    assert aliases.get("Carlos-Performance") == "eng-perf"
    assert aliases.get("Elena-Compliance") == "eng-compliance"


def test_canonical_registry_has_roles():
    """Integration test: verify registry file contains all role entries."""
    if not REGISTRY_PATH.exists():
        pytest.skip(f"Registry not found at {REGISTRY_PATH}")

    with open(REGISTRY_PATH, encoding="utf-8") as f:
        registry = json.load(f)

    roles = registry.get("roles", {})

    # Check new engineer roles
    assert "eng-data" in roles
    assert "eng-security" in roles
    assert "eng-ml" in roles
    assert "eng-perf" in roles
    assert "eng-compliance" in roles

    # Verify full names
    assert roles["eng-security"]["full_name"] == "Alex Kim"
    assert roles["eng-ml"]["full_name"] == "Priya Sharma"
    assert roles["eng-perf"]["full_name"] == "Carlos Mendez"
    assert roles["eng-compliance"]["full_name"] == "Elena Chen"
