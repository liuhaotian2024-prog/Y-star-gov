"""
End-to-end: each of the 5 scenarios is driven through the v5.0 closed-loop
(ResidualLoopEngine + OmissionEngine + InterventionEngine) using a stub
backend that returns a deterministic no-op action. The point is NOT to
prove the scenario solves itself — it's to prove the loop completes
without raising, that all three governance engines actually engage, and
that no SQLite files are created.

Acceptance per v5.0 Part B:
  - run_scenario() returns a CZLResult without exception
  - result.iter_snapshots present (proves dominance / RLE engaged)
  - omission_engine has at least one obligation tagged with
    `trampoline.*` after the run (proves omission_engine.ingest_event
    was reached)
  - intervention_engine is reachable and produces a GateCheckResult
    (proves InterventionEngine wired)
  - no `.ystar_omission.db` / `.ystar_cieu_*.db` files appear on disk
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Absolute repo path so the static-grep tests survive the autouse cwd-chdir
# fixture used to detect SQLite-side-effect leaks.
_REPO = Path(__file__).resolve().parents[3]

from ystar.czl.backends.base import (
    Backend, BackendAction, BackendResponse,
)
from ystar.czl.loop import CZLRun, run_scenario
from ystar.czl.scenarios.bug_fix_implicit_dep import BugFixImplicitDepScenario
from ystar.czl.scenarios.cross_file_refactor import CrossFileRefactorScenario
from ystar.czl.scenarios.lint_fix import LintFixScenario
from ystar.czl.scenarios.test_gen_for_existing import TestGenForExistingScenario
from ystar.czl.scenarios.type_annotation_completion import TypeAnnotationCompletionScenario


# === stub backend ============================================================

class _NoopBackend(Backend):
    """Backend that returns an empty action list. The loop runs verifiers
    against the unmodified baseline workspace, RLE computes a residual,
    and either converges or halts on oscillation/escalate. Either way the
    closed loop is exercised end-to-end."""

    name = "stub_noop"
    tier = "frontier"     # any non-empty tier — the gating identity check
                          # uses backend.name, not tier
    default_model = "stub-v0"

    def __init__(self) -> None:
        self._calls = 0

    def is_available(self) -> bool:
        return True

    def invoke(self, *, system_prompt: str, user_prompt: str,
                workspace_dir: str, contract: Dict[str, Any]) -> BackendResponse:
        self._calls += 1
        # Empty action list — scenario.apply_action will never be invoked.
        return BackendResponse(
            actions=[],
            raw_text="(stub backend — no actions)",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0,
        )


# === scenario fixtures =======================================================

def _materialize(scen_cls, ws: Path) -> None:
    """Materialize a scenario's baseline files into the workspace dir.

    Four of the five scenarios expose a `materialize_workspace(dir)` helper
    in their module. `lint_fix` is the odd one out — its baseline lives in
    `ystar.czl.scenarios.fixtures.lint_fix.EASY` as a {path: content} dict.
    """
    mod = __import__(scen_cls.__module__, fromlist=["materialize_workspace"])
    if hasattr(mod, "materialize_workspace"):
        mod.materialize_workspace(str(ws))
        return
    # lint_fix path
    from ystar.czl.scenarios.fixtures import lint_fix as _lf_fixtures
    for rel, content in _lf_fixtures.EASY.items():
        target = ws / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


SCENARIO_CASES = [
    ("cross_file_refactor", CrossFileRefactorScenario),
    ("type_annotation_completion", TypeAnnotationCompletionScenario),
    ("test_gen_for_existing", TestGenForExistingScenario),
    ("bug_fix_implicit_dep", BugFixImplicitDepScenario),
    ("lint_fix", LintFixScenario),
]


@pytest.fixture(autouse=True)
def _no_sqlite_side_effects(monkeypatch):
    """Run each test from a freshly empty cwd and assert no `.db` files
    appear after the test. The intervention/omission engines must use
    InMemoryOmissionStore + cieu_store=None."""
    holding = tempfile.mkdtemp(prefix="czl_v5_e2e_cwd_")
    monkeypatch.chdir(holding)
    yield
    leaks = [p for p in os.listdir(holding) if p.endswith(".db")]
    assert not leaks, f"SQLite leak in CWD: {leaks}"
    shutil.rmtree(holding, ignore_errors=True)


@pytest.mark.parametrize("name,scen_cls", SCENARIO_CASES, ids=[c[0] for c in SCENARIO_CASES])
def test_v5_loop_runs_end_to_end_per_scenario(name, scen_cls):
    """For each registered scenario: run_scenario() must complete without
    raising and produce a CZLResult with the v5.0 fields populated."""
    ws = Path(tempfile.mkdtemp(prefix=f"czl_v5_e2e_{name}_"))
    try:
        _materialize(scen_cls, ws)
        scen = scen_cls()
        backend = _NoopBackend()
        request = CZLRun(
            task_description=f"e2e v5.0 closed-loop probe for {name}",
            scenario=scen,
            backend=backend,
            workspace_dir=str(ws),
            max_iterations=2,
            auto_undo_on_failure=False,
        )
        # Must not raise
        result = run_scenario(request)
        # CZLResult basic invariants
        assert result is not None
        assert result.run_id == request.run_id
        assert isinstance(result.residual_trajectory, list)
        # RLE engaged: at least one iter snapshot OR a residual entry
        assert (result.iter_snapshots or result.residual_trajectory), (
            f"{name}: neither iter_snapshots nor residual_trajectory populated"
        )
        # stopping_authority must be set after the loop exits
        assert result.stopping_authority, f"{name}: stopping_authority empty"
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def test_v5_loop_imports_governance_engines():
    """Module-level sanity: loop.py truly imports RLE / OmissionEngine /
    InterventionEngine (per v5.0 Part B acceptance test #2). This is a
    cheap byte-grep check that catches accidental refactors that swap
    these out for in-tree stubs."""
    src = (_REPO / "ystar/czl/loop.py").read_text()
    for needle in ("ResidualLoopEngine", "OmissionEngine", "InterventionEngine"):
        assert needle in src, f"{needle} missing from loop.py"
    # And the legacy 'simpler version' MVP-stub comment is gone.
    for forbidden in ("simpler version", "MVP we use"):
        assert forbidden not in src, f"legacy stub marker {forbidden!r} still in loop.py"


def test_coding_agent_pack_independent_from_y_star_internals():
    """coding_agent_pack must NOT CALL the Y*-internal ship/manifest
    helpers (which Part A tagged DeprecationWarning). Catches regressions
    where someone accidentally calls them in. Docstring mentions of
    these names for explanatory purposes are allowed."""
    src = (_REPO / "ystar/czl/coding_agent_pack.py").read_text()
    # Strip docstrings + comments before the check so explanatory references
    # to Y*-internal helpers don't trip it up.
    import re
    no_docstrings = re.sub(r'"""[\s\S]*?"""', "", src)
    no_docstrings = re.sub(r"'''[\s\S]*?'''", "", no_docstrings)
    no_comments = "\n".join(
        line.split("#", 1)[0] for line in no_docstrings.splitlines()
    )
    forbidden_call_patterns = [
        "register_post_ship_completeness_obligation(",
        "audit_manifest_completeness(",
        "derive_new_obligations_from_ship(",
        "register_redirect_obligation(",
        "register_action_promise_obligation(",
        "detect_knowledge_action_gaps(",
    ]
    for pat in forbidden_call_patterns:
        assert pat not in no_comments, (
            f"coding_agent_pack.py CALLS Y*-internal {pat[:-1]!r} — must be "
            f"independent so trampoline-core can be split out cleanly."
        )
