"""
Smoke test for W7.2 drift algorithm tuning.
Verifies hybrid keyword + TF-IDF scoring has correct gradient.
"""
import json
import tempfile
from pathlib import Path
from ystar.governance.narrative_coherence_detector import check_ceo_output_vs_subgoal


def test_drift_gradient():
    """Test 3 cases: on-topic (< 0.3), partial (0.3-0.6), off-topic (> 0.7)."""

    # Case 1: Perfect match (on-topic)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({
            "current_subgoal": {
                "goal": "R3 E2E CZL stress test",
                "y_star_criteria": []
            }
        }, f)
        subgoal_file = f.name

    try:
        # Case 1a: Perfect match (reply directly discusses R3 E2E CZL stress test)
        result = check_ceo_output_vs_subgoal(
            "Running R3 E2E CZL stress test now, testing all phases under load",
            subgoal_file=subgoal_file
        )
        drift_perfect = result["drift_score"]
        assert drift_perfect < 0.3, f"Perfect match should have drift < 0.3, got {drift_perfect}"

        # Case 2: Partial match (shares some keywords but different focus)
        result = check_ceo_output_vs_subgoal(
            "Working on R3 integration testing for CZL validation layer",
            subgoal_file=subgoal_file
        )
        drift_partial = result["drift_score"]
        assert 0.3 <= drift_partial <= 0.6, f"Partial match should have drift 0.3-0.6, got {drift_partial}"

        # Case 3: Off-topic
        result = check_ceo_output_vs_subgoal(
            "讨论 Q2 营销预算 LinkedIn content strategy social media ads",
            subgoal_file=subgoal_file
        )
        drift_offtopic = result["drift_score"]
        assert drift_offtopic > 0.7, f"Off-topic should have drift > 0.7, got {drift_offtopic}"

        # Verify no constant returns (all three should be different)
        assert drift_perfect != drift_partial != drift_offtopic, \
            f"Algorithm returns constant value: {drift_perfect}, {drift_partial}, {drift_offtopic}"

        print(f"✅ Drift gradient test passed:")
        print(f"   Perfect match: {drift_perfect:.3f} (< 0.3)")
        print(f"   Partial match: {drift_partial:.3f} (0.3-0.6)")
        print(f"   Off-topic: {drift_offtopic:.3f} (> 0.7)")

    finally:
        Path(subgoal_file).unlink(missing_ok=True)


if __name__ == "__main__":
    test_drift_gradient()
