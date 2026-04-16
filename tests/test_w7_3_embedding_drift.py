"""
W7.3 E2E Test: Embedding-based drift detection for narrative_coherence_detector.

Tests check_ceo_output_vs_subgoal with sentence-transformer semantic similarity.
Three gradient contrast pairs:
- perfect: drift < 0.3 (cosine > 0.7)
- partial: 0.3 ≤ drift ≤ 0.6 (0.4 ≤ cosine ≤ 0.7)
- off: drift > 0.7 (cosine < 0.3)
"""
import json
import tempfile
from pathlib import Path

import pytest

from ystar.governance.narrative_coherence_detector import check_ceo_output_vs_subgoal


@pytest.fixture
def temp_subgoal_file():
    """Create a temp subgoal file and return (file_path, cleanup_fn)."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = Path(f.name)
        yield temp_path
    temp_path.unlink(missing_ok=True)


def test_embedding_drift_perfect_match(temp_subgoal_file):
    """Perfect match: CEO output nearly identical to subgoal. Expect drift < 0.3."""
    subgoal_data = {
        "current_subgoal": {
            "goal": "Fix narrative_coherence_detector.py by adding sentence-transformer embedding similarity to prevent semantic drift"
        },
        "y_star_criteria": []
    }
    temp_subgoal_file.write_text(json.dumps(subgoal_data))

    reply_text = (
        "I've added sentence-transformer embedding similarity to narrative_coherence_detector.py. "
        "This prevents semantic drift by computing cosine similarity between goal and reply embeddings. "
        "The new algorithm uses all-MiniLM-L6-v2 model and combines keyword, TF-IDF, and embedding scores."
    )

    result = check_ceo_output_vs_subgoal(reply_text, str(temp_subgoal_file))

    assert result["aligned"] is True, f"Expected aligned=True for perfect match, got {result}"
    assert result["drift_score"] < 0.3, (
        f"Expected drift_score < 0.3 for perfect match, got {result['drift_score']:.3f}"
    )
    assert "narrative_coherence_detector" in result["current_subgoal"]


def test_embedding_drift_partial_match(temp_subgoal_file):
    """Partial match: CEO output mentions the goal but mixes in unrelated work. Expect 0.3 ≤ drift ≤ 0.6."""
    subgoal_data = {
        "current_subgoal": {
            "goal": "Add sentence-transformer embedding to narrative_coherence_detector for semantic drift detection"
        },
        "y_star_criteria": []
    }
    temp_subgoal_file.write_text(json.dumps(subgoal_data))

    # Reply mentions embedding and narrative_coherence_detector (on-topic)
    # BUT also discusses unrelated file operations (off-topic noise)
    reply_text = (
        "I've added embedding similarity to narrative_coherence_detector. "
        "Also updated file read permissions and fixed a typo in the documentation. "
        "The code now handles edge cases better."
    )

    result = check_ceo_output_vs_subgoal(reply_text, str(temp_subgoal_file))

    # Partial match: mentions goal keywords but diluted with unrelated work
    # Embedding should detect partial semantic overlap
    assert 0.3 <= result["drift_score"] <= 0.6, (
        f"Expected 0.3 ≤ drift_score ≤ 0.6 for partial match, got {result['drift_score']:.3f}"
    )


def test_embedding_drift_off_track(temp_subgoal_file):
    """Off-track: CEO output unrelated to subgoal. Expect drift > 0.7."""
    subgoal_data = {
        "current_subgoal": {
            "goal": "Add sentence-transformer embedding to narrative_coherence_detector.py for semantic drift detection"
        },
        "y_star_criteria": []
    }
    temp_subgoal_file.write_text(json.dumps(subgoal_data))

    reply_text = (
        "I've reviewed the marketing materials and updated the pricing model. "
        "The new tiered pricing structure includes a free tier for individual developers "
        "and an enterprise tier with custom SLAs. All changes are documented in the sales deck."
    )

    result = check_ceo_output_vs_subgoal(reply_text, str(temp_subgoal_file))

    assert result["aligned"] is False, f"Expected aligned=False for off-track, got {result}"
    assert result["drift_score"] > 0.7, (
        f"Expected drift_score > 0.7 for off-track, got {result['drift_score']:.3f}"
    )
    assert len(result["warnings"]) > 0, "Expected warnings for high drift"
