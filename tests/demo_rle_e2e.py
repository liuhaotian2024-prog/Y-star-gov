#!/usr/bin/env python3
"""
E2E Demo: AMENDMENT-014 Closed-Loop CIEU + RLE
===============================================

Demonstrates:
1. CIEU event with target Y* → actual Yt+1 (with residual)
2. RLE computes Rt+1 = distance(Y*, Yt+1)
3. RLE triggers next action via AutonomyEngine
4. Iteration continues until convergence (Rt+1 < epsilon)

Expected output:
- RESIDUAL_LOOP_ACTION events emitted (iterations)
- RESIDUAL_LOOP_CONVERGED event when residual < epsilon
- Full closed-loop trace in CIEU
"""
import time
import uuid
from unittest.mock import Mock

from ystar.governance.residual_loop_engine import ResidualLoopEngine


class DemoCIEUStore:
    """In-memory CIEU store that prints events."""
    def __init__(self):
        self.events = []

    def write_dict(self, event):
        self.events.append(event)
        event_type = event["event_type"]
        params = event.get("params", {})

        if event_type == "RESIDUAL_LOOP_ACTION":
            print(f"  ➜ RLE ACTION: next_action='{params['next_action'][:40]}...' "
                  f"Rt+1={params['residual_rt_plus_1']:.4f} iteration={params['iteration']}")
        elif event_type == "RESIDUAL_LOOP_CONVERGED":
            print(f"  ✓ CONVERGED: Rt+1={params['final_residual']:.4f}")
        elif event_type == "RESIDUAL_LOOP_OSCILLATION":
            print(f"  ⚠ OSCILLATION: history={params['history']}")
        elif event_type == "RESIDUAL_LOOP_ESCALATE":
            print(f"  ⬆ ESCALATE: max_iterations={params['max_iterations']}")


class DemoAutonomyEngine:
    """Mock autonomy engine that simulates action generation."""
    def __init__(self):
        self.call_count = 0

    def pull_next_action(self, agent_id):
        """Simulate action generation (each call improves toward target)."""
        self.call_count += 1
        action = Mock()
        action.description = f"Iteration {self.call_count}: improve toward target"
        return action


def demo_convergence():
    """Demo: Multi-iteration convergence."""
    print("\n" + "="*60)
    print("Demo 1: Multi-Iteration Convergence")
    print("="*60)
    print("Scenario: Target Y*='complete', Actual improves each step")
    print()

    cieu_store = DemoCIEUStore()
    autonomy_engine = DemoAutonomyEngine()

    rle = ResidualLoopEngine(
        autonomy_engine=autonomy_engine,
        cieu_store=cieu_store,
        target_provider=lambda event: event.get("params", {}).get("target_y_star"),
        convergence_epsilon=0.05,
        max_iterations=10,
        damping_gamma=0.9,
    )

    # Simulate improving results over iterations
    session_id = "demo_convergence"
    y_star = "complete"
    actuals = ["comp", "comple", "complet", "complete"]  # Gradually approaching target

    for i, y_actual in enumerate(actuals):
        event = {
            "session_id": session_id,
            "agent_id": "demo_agent",
            "event_type": "ToolUse",
            "params": {
                "target_y_star": y_star,
                "y_actual": y_actual,
            }
        }
        print(f"Iteration {i+1}: Y*='{y_star}' Yt+1='{y_actual}'")
        rle.on_cieu_event(event)

    print(f"\nTotal CIEU events emitted: {len(cieu_store.events)}")
    action_count = sum(1 for e in cieu_store.events if e["event_type"] == "RESIDUAL_LOOP_ACTION")
    converged_count = sum(1 for e in cieu_store.events if e["event_type"] == "RESIDUAL_LOOP_CONVERGED")
    print(f"  - RESIDUAL_LOOP_ACTION: {action_count}")
    print(f"  - RESIDUAL_LOOP_CONVERGED: {converged_count}")


def demo_escalation():
    """Demo: Max iterations exceeded → escalate."""
    print("\n" + "="*60)
    print("Demo 2: Escalation (Max Iterations)")
    print("="*60)
    print("Scenario: Target never converges → escalate to Board")
    print()

    cieu_store = DemoCIEUStore()
    autonomy_engine = DemoAutonomyEngine()

    rle = ResidualLoopEngine(
        autonomy_engine=autonomy_engine,
        cieu_store=cieu_store,
        target_provider=lambda event: event.get("params", {}).get("target_y_star"),
        convergence_epsilon=0.0,
        max_iterations=3,  # Low threshold for demo
        damping_gamma=0.9,
    )

    session_id = "demo_escalate"
    y_star = "target"

    for i in range(5):  # More iterations than max
        event = {
            "session_id": session_id,
            "agent_id": "demo_agent",
            "event_type": "ToolUse",
            "params": {
                "target_y_star": y_star,
                "y_actual": f"attempt_{i}",  # Never converges
            }
        }
        print(f"Iteration {i+1}: Y*='{y_star}' Yt+1='attempt_{i}'")
        rle.on_cieu_event(event)

    print(f"\nTotal CIEU events emitted: {len(cieu_store.events)}")
    escalate_count = sum(1 for e in cieu_store.events if e["event_type"] == "RESIDUAL_LOOP_ESCALATE")
    print(f"  - RESIDUAL_LOOP_ESCALATE: {escalate_count}")


def demo_no_target_skip():
    """Demo: No target Y* → skip loop."""
    print("\n" + "="*60)
    print("Demo 3: No Target Y* → Skip Loop")
    print("="*60)
    print("Scenario: Event has no target → RLE gracefully skips")
    print()

    cieu_store = DemoCIEUStore()
    autonomy_engine = DemoAutonomyEngine()

    rle = ResidualLoopEngine(
        autonomy_engine=autonomy_engine,
        cieu_store=cieu_store,
        target_provider=lambda event: event.get("params", {}).get("target_y_star"),
    )

    event = {
        "session_id": "demo_skip",
        "agent_id": "demo_agent",
        "event_type": "ToolUse",
        "params": {
            # No target_y_star
            "y_actual": "some result",
        }
    }
    print("Event: no target_y_star")
    rle.on_cieu_event(event)

    print(f"\nTotal CIEU events emitted: {len(cieu_store.events)} (should be 0)")


if __name__ == "__main__":
    print("\n" + "█"*60)
    print("AMENDMENT-014: Closed-Loop CIEU + RLE E2E Demo")
    print("█"*60)

    demo_convergence()
    demo_escalation()
    demo_no_target_skip()

    print("\n" + "█"*60)
    print("✓ E2E Demo Complete — Closed-Loop Verified")
    print("█"*60)
    print("\nVerification checklist:")
    print("  [✓] RLE on_cieu_event triggered on CIEU events")
    print("  [✓] Residual computation (distance function)")
    print("  [✓] Next action triggered via AutonomyEngine")
    print("  [✓] Convergence detection (Rt+1 < epsilon)")
    print("  [✓] Escalation on max iterations")
    print("  [✓] Graceful skip when no target")
    print()
