"""
Test Y* Schema v2 — CZL Persistence Extension (W5, Phase 2)

Tests the three new mandatory fields:
- artifact_persistence
- freshness_policy
- owner_after_rt1
"""
import pytest
from ystar.governance.contract_lifecycle import validate_y_star_schema_v2


def test_valid_schema_v2():
    """Test that a valid v2 contract passes validation"""
    contract = {
        "artifact_persistence": ["commit_to_origin", "referenced_in_covenant"],
        "freshness_policy": "never_deprecate",
        "owner_after_rt1": "cto"
    }
    result = validate_y_star_schema_v2(contract)
    assert result["valid"] is True
    assert result["missing"] == []
    assert result["invalid"] == {}


def test_missing_artifact_persistence():
    """Test that missing artifact_persistence is caught"""
    contract = {
        "freshness_policy": "stale_at_7d",
        "owner_after_rt1": "ceo"
    }
    result = validate_y_star_schema_v2(contract)
    assert result["valid"] is False
    assert "artifact_persistence" in result["missing"]


def test_missing_freshness_policy():
    """Test that missing freshness_policy is caught"""
    contract = {
        "artifact_persistence": ["tagged_in_genesis"],
        "owner_after_rt1": "secretary"
    }
    result = validate_y_star_schema_v2(contract)
    assert result["valid"] is False
    assert "freshness_policy" in result["missing"]


def test_missing_owner_after_rt1():
    """Test that missing owner_after_rt1 is caught"""
    contract = {
        "artifact_persistence": ["commit_to_origin"],
        "freshness_policy": "tied_to_campaign"
    }
    result = validate_y_star_schema_v2(contract)
    assert result["valid"] is False
    assert "owner_after_rt1" in result["missing"]


def test_invalid_artifact_persistence_type():
    """Test that artifact_persistence must be a list"""
    contract = {
        "artifact_persistence": "commit_to_origin",  # Should be list
        "freshness_policy": "never_deprecate",
        "owner_after_rt1": "cto"
    }
    result = validate_y_star_schema_v2(contract)
    assert result["valid"] is False
    assert "artifact_persistence" in result["invalid"]


def test_invalid_artifact_persistence_values():
    """Test that artifact_persistence values must be from valid set"""
    contract = {
        "artifact_persistence": ["commit_to_origin", "invalid_method"],
        "freshness_policy": "never_deprecate",
        "owner_after_rt1": "cto"
    }
    result = validate_y_star_schema_v2(contract)
    assert result["valid"] is False
    assert "artifact_persistence" in result["invalid"]
    assert "invalid_method" in result["invalid"]["artifact_persistence"]


def test_invalid_freshness_policy():
    """Test that freshness_policy must be from valid set"""
    contract = {
        "artifact_persistence": ["commit_to_origin"],
        "freshness_policy": "invalid_policy",
        "owner_after_rt1": "cto"
    }
    result = validate_y_star_schema_v2(contract)
    assert result["valid"] is False
    assert "freshness_policy" in result["invalid"]


def test_invalid_owner_after_rt1():
    """Test that owner_after_rt1 must be a valid agent ID"""
    contract = {
        "artifact_persistence": ["commit_to_origin"],
        "freshness_policy": "never_deprecate",
        "owner_after_rt1": "invalid_agent"
    }
    result = validate_y_star_schema_v2(contract)
    assert result["valid"] is False
    assert "owner_after_rt1" in result["invalid"]


def test_multiple_missing_fields():
    """Test that all missing fields are reported"""
    contract = {}
    result = validate_y_star_schema_v2(contract)
    assert result["valid"] is False
    assert len(result["missing"]) == 3
    assert "artifact_persistence" in result["missing"]
    assert "freshness_policy" in result["missing"]
    assert "owner_after_rt1" in result["missing"]


def test_all_valid_artifact_persistence_options():
    """Test all valid artifact_persistence options"""
    contract = {
        "artifact_persistence": [
            "commit_to_origin",
            "referenced_in_covenant",
            "tagged_in_genesis",
            "none_ephemeral"
        ],
        "freshness_policy": "never_deprecate",
        "owner_after_rt1": "ceo"
    }
    result = validate_y_star_schema_v2(contract)
    assert result["valid"] is True


def test_all_valid_freshness_policies():
    """Test each valid freshness_policy option"""
    for policy in ["never_deprecate", "stale_at_7d", "stale_at_30d", "tied_to_campaign"]:
        contract = {
            "artifact_persistence": ["commit_to_origin"],
            "freshness_policy": policy,
            "owner_after_rt1": "cto"
        }
        result = validate_y_star_schema_v2(contract)
        assert result["valid"] is True, f"Policy '{policy}' should be valid"


def test_all_valid_agent_ids():
    """Test each valid agent ID"""
    for agent in ["ceo", "cto", "cmo", "cso", "cfo",
                  "eng-kernel", "eng-governance", "eng-platform", "eng-domains",
                  "secretary"]:
        contract = {
            "artifact_persistence": ["commit_to_origin"],
            "freshness_policy": "never_deprecate",
            "owner_after_rt1": agent
        }
        result = validate_y_star_schema_v2(contract)
        assert result["valid"] is True, f"Agent '{agent}' should be valid"
