#!/usr/bin/env python3
"""
E2E Demo: RLE → Path A Bridge
==============================

Proves that ResidualLoopEngine (RLE) non-convergence triggers feed into
GovernanceLoop (Path A) as GovernanceSuggestions.

Steps:
  1. Create non-convergent task (target Y*=100, actual starts at 0, grows by 5 each iteration)
  2. RLE detects max_iterations exceeded
  3. RLE calls governance_suggestion_callback
  4. GovernanceLoop.observe_from_residual_loop() receives suggestion
  5. GovernanceLoop.tighten() merges RLE suggestion into result.governance_suggestions
  6. Assert: at least 1 RLE-sourced suggestion exists in result

Expected output:
  [RLE] ESCALATE_BOARD: session=test_session iterations=3
  [RLE→Path A] GovernanceSuggestion emitted (escalate)
  [Path A←RLE] GovernanceSuggestion received: rle_escalation trigger=max_iterations_exceeded
  [Path A←RLE] Merging 1 RLE suggestions
  ✅ Bridge verified: RLE → Path A suggestion count = 1
"""
import sys
import time
import logging
from typing import Any, Dict

# Add ystar to path
sys.path.insert(0, "/Users/haotianliu/.openclaw/workspace/Y-star-gov")

from ystar.governance.residual_loop_engine import ResidualLoopEngine
from ystar.governance.governance_loop import GovernanceLoop
from ystar.governance.cieu_store import CIEUStore
from ystar.governance.omission_store import OmissionStore
from ystar.governance.reporting import ReportEngine

# Enable logging
logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")


class MockAutonomyEngine:
    """Mock AutonomyEngine that does nothing."""
    def pull_next_action(self, agent_id: str):
        return None


def simulate_non_convergent_task(rle: ResidualLoopEngine, session_id: str, agent_id: str):
    """
    Simulate a task that never converges:
      Y* = 100 (target)
      Y_actual starts at 0, increases by 5 each iteration
      After max_iterations=3, still far from target → escalate
    """
    y_star = 100
    y_actual = 0

    for i in range(5):  # 5 iterations (more than max_iterations=3)
        y_actual += 5  # Slow progress
        event = {
            "session_id": session_id,
            "agent_id": agent_id,
            "event_type": "tool_use",
            "params": {
                "target_y_star": y_star,
                "y_actual": y_actual,
                "result": y_actual,
            },
        }
        print(f"   Iteration {i+1}: Y*={y_star}, Y_actual={y_actual}, Rt+1≈{abs(y_star - y_actual)}")
        rle.on_cieu_event(event)
        time.sleep(0.05)  # Small delay to simulate real execution


def main():
    print("=" * 70)
    print("E2E Demo: RLE → Path A Bridge")
    print("=" * 70)

    # 1. Setup stores
    cieu_store = CIEUStore()
    omission_store = OmissionStore()
    report_engine = ReportEngine(omission_store=omission_store, cieu_store=cieu_store)
    governance_loop = GovernanceLoop(report_engine=report_engine)

    # 2. Setup RLE with callback to GovernanceLoop
    mock_autonomy = MockAutonomyEngine()

    def rle_callback(suggestion_dict: Dict):
        """Bridge: RLE → GovernanceLoop"""
        governance_loop.observe_from_residual_loop(suggestion_dict)

    rle = ResidualLoopEngine(
        autonomy_engine=mock_autonomy,
        cieu_store=cieu_store,
        target_provider=lambda event: event.get("params", {}).get("target_y_star"),
        max_iterations=3,  # Low threshold to trigger escalation fast
        convergence_epsilon=5.0,
        damping_gamma=0.9,
        governance_suggestion_callback=rle_callback,  # KEY: wire callback
    )

    # 3. Simulate non-convergent task
    print("\n[DEMO] Simulating non-convergent task (Y*=100, slow growth)...")
    session_id = "test_session_rle_path_a"
    agent_id = "test_agent"
    simulate_non_convergent_task(rle, session_id, agent_id)

    # 4. Check GovernanceLoop received RLE suggestion
    print("\n[DEMO] Checking GovernanceLoop._rle_suggestions...")
    if governance_loop._rle_suggestions:
        print(f"✅ RLE suggestions buffered: {len(governance_loop._rle_suggestions)}")
        for sugg in governance_loop._rle_suggestions:
            print(f"   - {sugg.suggestion_type}: {sugg.rationale[:80]}")
    else:
        print("❌ No RLE suggestions received (bridge failed)")
        return 1

    # 5. Run GovernanceLoop.tighten() and verify merge
    print("\n[DEMO] Running GovernanceLoop.tighten()...")
    # Need at least one observation for tighten() to work
    governance_loop.set_baseline()
    governance_loop.observe_from_report_engine()

    result = governance_loop.tighten()

    # Check if RLE suggestions are in result.governance_suggestions
    rle_suggestions_in_result = [
        s for s in result.governance_suggestions
        if s.suggestion_type == "rle_escalation"
    ]

    print(f"\n[DEMO] GovernanceTightenResult.governance_suggestions count: {len(result.governance_suggestions)}")
    print(f"[DEMO] RLE-sourced suggestions in result: {len(rle_suggestions_in_result)}")

    if rle_suggestions_in_result:
        print("✅ Bridge verified: RLE → Path A suggestion merged")
        for s in rle_suggestions_in_result:
            print(f"   - target_rule_id: {s.target_rule_id}")
            print(f"   - rationale: {s.rationale[:100]}")
        return 0
    else:
        print("❌ Bridge broken: RLE suggestion not merged into tighten() result")
        return 1


if __name__ == "__main__":
    sys.exit(main())
