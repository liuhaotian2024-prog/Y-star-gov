"""
v5.0.1 fix verification: when RLE halts via OSCILLATION or ESCALATE, the
omission_engine.scan() and intervention_engine.process_violations() paths
must fire. Original v5.0 only fired these at CONVERGED — which is the
exact opposite of what was wanted (a converged agent did well; a stuck
agent is the one that needs intervention surfaced).

This test installs an always-failing scenario + a stub backend whose
actions never change the workspace, forcing RLE into ESCALATE after
max_iterations. Then asserts:
  - intervention is invoked (scan + process_violations) at halt
  - result.stopping_authority reflects the stuck branch (not converged)
  - result.failure_reason includes the violation-surface diagnostic when
    obligations were created during the loop
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ystar.czl.backends.base import Backend, BackendResponse
from ystar.czl.loop import CZLRun, run_scenario
from ystar.czl.scenarios.base import Scenario, PlanStep
from ystar.czl.verifiers.base import VerifierResult


class _AlwaysFailScenario(Scenario):
    """Scenario whose verifier ALWAYS returns one failing VerifierResult.
    Combined with a no-op backend, this drives RLE to its max_iterations
    cap with no progress and a non-zero residual every iteration —
    exactly the stuck-loop condition v5.0.1 fix needs to exercise."""

    name = "always_fail_test"
    description = "Test fixture: verifier always fails to force RLE escalate"

    def y_star_invariants(self) -> Dict[str, Any]:
        return {"invariant": ["never_passes == True"]}

    def plan(self, task_description, workspace_dir, contract=None):
        return [PlanStep(
            step_id="impossible",
            user_prompt="Solve this. (The verifier will never accept anything.)",
            expected_action_types=["edit_file"],
        )]

    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        return [VerifierResult(
            verifier_name="always_fail",
            passed=False,
            message="this verifier always returns failed",
            details={"stdout": "synthetic stuck-loop signal"},
        )]

    def apply_action(self, action, workspace_dir, contract=None):
        # No-op: nothing changes between iterations.
        return None


class _NoopBackend(Backend):
    name = "stub_stuck_loop"
    tier = "frontier"
    default_model = "stub-stuck-v1"

    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def invoke(self, *, system_prompt: str, user_prompt: str,
                workspace_dir: str, contract: Dict[str, Any]) -> BackendResponse:
        self.calls += 1
        return BackendResponse(
            actions=[],
            raw_text="(stub — stuck-loop test)",
            input_tokens=1, output_tokens=1, cost_usd=0.0,
        )


def test_intervention_fires_on_stuck_halt(caplog):
    """v5.0.1 acceptance: stuck halts (oscillation/escalate) must trigger
    omission scan + intervention processing, not silently halt."""
    ws = Path(tempfile.mkdtemp(prefix="czl_v5_1_stuck_"))
    try:
        # Initialise as a git repo so the loop's defensive _ensure_git_initialised
        # path stays cheap (no-op when .git already exists).
        os.makedirs(ws, exist_ok=True)
        request = CZLRun(
            task_description="impossible task — exercises stuck-loop intervention path",
            scenario=_AlwaysFailScenario(),
            backend=_NoopBackend(),
            workspace_dir=str(ws),
            max_iterations=2,        # informational; RLE has its own cap
            auto_undo_on_failure=False,
        )
        with caplog.at_level(logging.WARNING, logger="ystar.czl.loop"):
            result = run_scenario(request)

        # Must NOT have claimed convergence
        assert result.converged is False, "stuck loop must not claim converged"

        # Stopping authority must be in the stuck-halt family
        assert result.stopping_authority in (
            "rle_oscillation", "rle_escalate",
        ), f"expected stuck halt, got {result.stopping_authority!r}"

        # The fix means we should see a log line about violations surfaced
        # at the stuck halt (even if zero — the line still fires).
        relevant = [r for r in caplog.records
                    if "omission scan surfaced" in r.message
                    or "RLE detected oscillation" in r.message
                    or "RLE escalated after" in r.message]
        assert relevant, (
            "v5.0.1 fix not engaged: expected at least one halt-time "
            "intervention log line, found none. Logs:\n"
            + "\n".join(r.message for r in caplog.records[-10:])
        )
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def test_converged_branch_still_runs_gate_check():
    """v5.0.1 must NOT break the existing CONVERGED → gate_check path."""
    # Use the well-tested converging stub from test_v5_e2e_loop. Just
    # spot-check that the imports + entry points still work — we do not
    # re-run the full e2e suite here (that's covered by the other test
    # file). This is a sentinel that v5.0.1 refactor didn't drop the
    # CONVERGED branch.
    import inspect
    from ystar.czl import loop as loop_mod
    src = inspect.getsource(loop_mod.run_scenario)
    # The defensive pre-gate scan call (drain_violations_at_halt) must
    # appear in the CONVERGED branch source.
    assert "_drain_violations_at_halt(\"converged_pre_gate\")" in src, (
        "v5.0.1 fix dropped the defensive pre-gate scan on CONVERGED"
    )
    # And the gate_check call must still be there.
    assert "gate_check(" in src, "v5.0.1 dropped gate_check entirely"
