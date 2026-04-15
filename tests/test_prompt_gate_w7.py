"""
Test W7 Phase 2: Prompt Gate — Subgoal Coherence Check

Tests check_ceo_output_vs_subgoal() function.
"""
import json
import pytest
from pathlib import Path
from ystar.governance.narrative_coherence_detector import check_ceo_output_vs_subgoal


@pytest.fixture
def temp_subgoal_file(tmp_path):
    """Create a temporary .czl_subgoals.json file"""
    subgoal_file = tmp_path / ".czl_subgoals.json"
    subgoal_data = {
        "current_subgoal": {
            "id": "test-subgoal",
            "goal": "Implement Y* Schema v2 with artifact_persistence validation"
        },
        "y_star_criteria": [
            {
                "id": "W5",
                "artifact_persistence": ["commit_to_origin"],
                "freshness_policy": "never_deprecate"
            }
        ]
    }
    subgoal_file.write_text(json.dumps(subgoal_data, indent=2))
    return str(subgoal_file)


def test_aligned_reply(temp_subgoal_file):
    """Test that aligned reply has low drift score"""
    reply = """
    Implementing Y* Schema v2 now. Adding artifact_persistence validation
    to the contract_lifecycle.py module. This will prevent artifact loss.
    Committing changes to git.
    """
    result = check_ceo_output_vs_subgoal(reply, temp_subgoal_file)

    assert result["aligned"] is True
    assert result["drift_score"] < 0.5


def test_drifted_reply(temp_subgoal_file):
    """Test that drifted reply has high drift score"""
    reply = """
    Working on the marketing campaign now. Drafting blog posts and
    updating the website content. Need to schedule social media posts.
    """
    result = check_ceo_output_vs_subgoal(reply, temp_subgoal_file)

    assert result["aligned"] is False
    assert result["drift_score"] > 0.7
    assert len(result["warnings"]) > 0


def test_missing_commit_mention(temp_subgoal_file):
    """Test that missing commit mention triggers warning when artifact_persistence requires it"""
    reply = """
    Implemented Y* Schema v2 with artifact_persistence validation.
    Tests are passing. Ready to deploy.
    """
    result = check_ceo_output_vs_subgoal(reply, temp_subgoal_file)

    # Should warn about missing commit/git mention
    warnings = [w for w in result["warnings"] if "commit" in w.lower()]
    assert len(warnings) > 0


def test_nonexistent_subgoal_file():
    """Test handling of nonexistent .czl_subgoals.json"""
    result = check_ceo_output_vs_subgoal("Any reply text", "/nonexistent/file.json")

    assert result["drift_score"] == 0.5  # Unknown state
    assert len(result["warnings"]) > 0
    assert "not found" in result["warnings"][0]


def test_empty_current_subgoal(tmp_path):
    """Test handling of empty current_subgoal"""
    subgoal_file = tmp_path / ".czl_subgoals.json"
    subgoal_file.write_text(json.dumps({"current_subgoal": {}}))

    result = check_ceo_output_vs_subgoal("Any reply", str(subgoal_file))

    assert result["drift_score"] == 0.5
    assert any("No current_subgoal" in w for w in result["warnings"])


def test_malformed_json(tmp_path):
    """Test handling of malformed JSON"""
    subgoal_file = tmp_path / ".czl_subgoals.json"
    subgoal_file.write_text("{ invalid json }")

    result = check_ceo_output_vs_subgoal("Any reply", str(subgoal_file))

    assert result["drift_score"] == 0.5
    assert any("Cannot parse" in w for w in result["warnings"])


def test_partial_keyword_overlap(temp_subgoal_file):
    """Test partial keyword overlap results in moderate drift score"""
    reply = """
    Adding validation to contract_lifecycle.py schema artifact_persistence
    but focusing on a different aspect - the review workflow improvements.
    Committing to git.
    """
    result = check_ceo_output_vs_subgoal(reply, temp_subgoal_file)

    # Should have moderate drift (some overlap but not complete)
    assert result["drift_score"] < 0.5  # Good overlap with commit mention


def test_current_subgoal_captured(temp_subgoal_file):
    """Test that current_subgoal text is captured in result"""
    result = check_ceo_output_vs_subgoal("Any text", temp_subgoal_file)

    assert "Y* Schema v2" in result["current_subgoal"]
    assert "artifact_persistence" in result["current_subgoal"]
