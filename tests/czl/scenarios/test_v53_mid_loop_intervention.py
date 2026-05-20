"""v5.3 hard acceptance: sub-file granularity + mid-loop intervention.

Tests (per design doc §4):
  - 4.1 deliberately-off: stub backend writes to source-under-test → gate
        denies with field_violated == "forbidden_operations".
  - 4.2 sub-file extraction: compute_focus populates target_functions /
        target_test_cases from ResidualState.
  - 4.3 mid-loop scan: mid-iter scan call fires + governance event
        captured into result.governance_events.
"""
from __future__ import annotations
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ystar.czl.autonomy import CZLAutonomyEngine, FocusConstraint
from ystar.czl.backends.base import Backend, BackendAction, BackendResponse
from ystar.czl.loop import CZLRun, run_scenario, _extract_action_targets
from ystar.czl.residual import (
    ResidualState, FailureLocation, FailedVerifier, TestDelta,
)
from ystar.czl.scenarios.test_gen_for_existing import (
    TestGenForExistingScenario, materialize_workspace, TASK_DESCRIPTION,
)


# ────────────────────────────────────────────────────────────────────────────
# 4.2 sub-file extraction
# ────────────────────────────────────────────────────────────────────────────

def test_compute_focus_extracts_target_functions_from_pytest_failure():
    """v5.3 §3.2: target_functions ← FailureLocation.bottom_function."""
    engine = CZLAutonomyEngine()
    rs = ResidualState(
        iteration=1,
        failed_verifiers=[FailedVerifier(name="pytest", category="test", message="fail")],
        failure_locations=[
            FailureLocation(file="test_data_pipeline.py", lineno=10,
                            kind="test_failure", detail="test_foo [AssertionError]",
                            bottom_function="clean_records"),
            FailureLocation(file="test_data_pipeline.py", lineno=22,
                            kind="test_failure", detail="test_bar [TypeError]",
                            bottom_function="normalize_email"),
        ],
        delta_from_prev=TestDelta(),
    )
    engine.observe(rs)
    action = engine.pull_next_action("agent")
    assert action is not None
    fc = action.focus_constraint
    assert fc.target_functions == {"clean_records", "normalize_email"}


def test_compute_focus_extracts_target_test_cases_from_regression():
    """v5.3 §3.2: target_test_cases ← newly_failing ∪ still_failing."""
    engine = CZLAutonomyEngine()
    rs = ResidualState(
        iteration=2,
        failed_verifiers=[FailedVerifier(name="pytest", category="test", message="fail")],
        failure_locations=[
            FailureLocation(file="t.py", lineno=1, kind="test_failure", detail="x"),
        ],
        delta_from_prev=TestDelta(
            newly_failing=["test_data_pipeline.py::test_was_passing_now_fails"],
            still_failing=["test_data_pipeline.py::test_chronic"],
        ),
    )
    engine.observe(rs)
    fc = engine.pull_next_action("agent").focus_constraint
    assert fc.target_test_cases is not None
    assert "test_data_pipeline.py::test_was_passing_now_fails" in fc.target_test_cases
    assert "test_data_pipeline.py::test_chronic" in fc.target_test_cases


def test_extract_action_targets_ast_parse():
    """v5.3 §3.4: AST helper extracts function names + test_ names."""
    code = (
        "import pytest\n"
        "def helper(x):\n    return x\n"
        "def test_alpha():\n    assert True\n"
        "def test_beta(tmp_path):\n    pass\n"
    )
    out = _extract_action_targets(code)
    assert out["functions"] == {"helper", "test_alpha", "test_beta"}
    assert out["test_cases"] == {"test_alpha", "test_beta"}


def test_extract_action_targets_unparseable():
    """Unparseable / empty content returns empty sets, not exception."""
    assert _extract_action_targets("")["functions"] == set()
    assert _extract_action_targets("def broken(:")["test_cases"] == set()


# ────────────────────────────────────────────────────────────────────────────
# 4.1 deliberately-off acceptance: gate hard-denies forbidden_operations
# ────────────────────────────────────────────────────────────────────────────

class _ForbiddenEditBackend(Backend):
    """Emits an edit_file action targeting data_pipeline.py — the
    READ-ONLY source under test for TestGenForExistingScenario. Gate
    should hard-deny on forbidden_operations."""
    name = "v53_forbid_test_backend"
    tier = "frontier"
    default_model = "v53-forbid"

    def __init__(self): self.calls = 0
    def is_available(self): return True
    def invoke(self, *, system_prompt, user_prompt, workspace_dir, contract):
        self.calls += 1
        return BackendResponse(
            actions=[BackendAction(
                type="edit_file",
                payload={"path": "data_pipeline.py", "content": "# unauthorized edit\n"},
            )],
            raw_text="```edit data_pipeline.py\n# unauthorized edit\n```",
            input_tokens=10, output_tokens=10, cost_usd=0.0,
        )


def test_gate_hard_denies_forbidden_operation_on_source_file(monkeypatch):
    """v5.3 hard acceptance: test_gen scenario declares
    forbidden_operations={(edit_file, data_pipeline.py)}. Agent that
    emits this action must be DENIED + reason mentions forbidden_operations."""
    # Force compute_focus to return a non-empty FC so the gate has
    # something to check. We craft a FC with the scenario's
    # forbidden_operations populated (the loop merges scenario override).
    from ystar.czl.autonomy import CZLAutonomyEngine
    monkeypatch.setattr(
        CZLAutonomyEngine, "compute_focus",
        lambda self: FocusConstraint(
            allowed_files={"data_pipeline.py"},   # cluster-derived to source
            rationale="synthetic cluster on source",
        ),
    )

    ws = Path(tempfile.mkdtemp(prefix="czl_v53_forbid_"))
    try:
        materialize_workspace(str(ws))
        scen = TestGenForExistingScenario()
        result = run_scenario(CZLRun(
            task_description=TASK_DESCRIPTION,
            scenario=scen,
            backend=_ForbiddenEditBackend(),
            workspace_dir=str(ws),
            max_iterations=2,
            auto_undo_on_failure=False,
        ))
        # Gate must have denied at least one action.
        assert result.gate_denied_count >= 1, (
            f"v5.3 forbidden_operations gate did not deny — "
            f"gate_denied_count={result.gate_denied_count}, "
            f"per_field={result.gate_per_field_denials}"
        )
        # And the denial must be on the forbidden_operations field.
        assert "forbidden_operations" in result.gate_per_field_denials, (
            f"expected forbidden_operations denial; got {result.gate_per_field_denials}"
        )
        # And data_pipeline.py must be in denied paths.
        assert "data_pipeline.py" in result.gate_denied_paths
        # Governance event log must record the gate decision.
        gate_events = [e for e in result.governance_events
                       if e.get("event_type") == "focus_gate_deny"]
        assert len(gate_events) >= 1
        assert gate_events[0]["field_violated"] == "forbidden_operations"
    finally:
        shutil.rmtree(ws, ignore_errors=True)


# ────────────────────────────────────────────────────────────────────────────
# 4.3 mid-loop scan + governance log audit
# ────────────────────────────────────────────────────────────────────────────

def test_governance_events_populated_in_result():
    """v5.3 §3.7: result.governance_events is non-empty after a real run.
    Includes TASK_DISPATCHED at minimum + per-iter residual snapshots."""
    from ystar.czl.scenarios.base import Scenario, PlanStep
    from ystar.czl.verifiers.base import VerifierResult

    class _AlwaysFail(Scenario):
        name = "v53_always_fail"
        def y_star_invariants(self): return {"invariant": []}
        def plan(self, t, w, contract=None):
            return [PlanStep(step_id="x", user_prompt="x")]
        def verify(self, w, c):
            return [VerifierResult(verifier_name="x", passed=False, message="fail",
                                    details={"stdout": ""})]
        def apply_action(self, a, w, contract=None): return None

    class _NoopBackend(Backend):
        name = "v53_noop"; tier = "frontier"; default_model = "x"
        def is_available(self): return True
        def invoke(self, **kw): return BackendResponse(actions=[], raw_text="",
                                                       input_tokens=1, output_tokens=1, cost_usd=0.0)

    ws = Path(tempfile.mkdtemp(prefix="czl_v53_gov_"))
    try:
        result = run_scenario(CZLRun(
            task_description="v5.3 audit log",
            scenario=_AlwaysFail(), backend=_NoopBackend(),
            workspace_dir=str(ws), max_iterations=2,
            auto_undo_on_failure=False,
        ))
        assert result.governance_events, "no governance events captured"
        types = {e.get("event_type") for e in result.governance_events}
        assert "task_dispatched" in types or "iter_residual" in types
        # At least one RLE halt-event should show up
        halts = {"RESIDUAL_LOOP_CONVERGED", "RESIDUAL_LOOP_OSCILLATION",
                 "RESIDUAL_LOOP_ESCALATE"}
        assert types & halts, (
            f"no RLE halt event in governance_events; got types: {types}"
        )
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def test_mid_loop_scan_runs_without_exception_in_real_iter():
    """v5.3 §3.6: mid-loop scan executes inside the iter body, doesn't
    raise. Uses a scenario whose verifier returns one failing result so
    the loop iterates at least once."""
    from ystar.czl.scenarios.base import Scenario, PlanStep
    from ystar.czl.verifiers.base import VerifierResult

    class _OneFail(Scenario):
        name = "v53_one_fail"
        def y_star_invariants(self): return {"invariant": []}
        def plan(self, t, w, contract=None):
            return [PlanStep(step_id="x", user_prompt="x")]
        def verify(self, w, c):
            return [VerifierResult(verifier_name="x", passed=False, message="fail",
                                    details={"stdout": ""})]
        def apply_action(self, a, w, contract=None): return None

    class _Noop(Backend):
        name = "v53_noop2"; tier = "frontier"; default_model = "x"
        def is_available(self): return True
        def invoke(self, **kw): return BackendResponse(actions=[], raw_text="",
                                                       input_tokens=1, output_tokens=1, cost_usd=0.0)

    ws = Path(tempfile.mkdtemp(prefix="czl_v53_midscan_"))
    try:
        # Must not raise:
        result = run_scenario(CZLRun(
            task_description="v5.3 mid-loop scan",
            scenario=_OneFail(), backend=_Noop(),
            workspace_dir=str(ws), max_iterations=2,
            auto_undo_on_failure=False,
        ))
        # Loop must have iterated at least once
        assert result.iterations >= 1
    finally:
        shutil.rmtree(ws, ignore_errors=True)
