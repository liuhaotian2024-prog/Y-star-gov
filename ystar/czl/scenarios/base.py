"""
ystar.czl.scenarios.base — Scenario ABC and pluggable registry

A Scenario is a self-contained pluggable description of an indie-developer task.
It is intentionally NOT subclassed from ystar.integrations.base.EventStreamConnector
because Scenarios are batch-oriented (one task → one result) rather than
streaming-oriented. They share *spirit* but not interface.

Each Scenario tells the loop:
  1. What `y_star_invariants()` mean "done"
  2. What `plan()` of steps the agent should take
  3. How to `verify()` outcome against the invariants (calls external tools)
  4. How to `apply_action()` to the workspace (write files, run commands, ...)
  5. What `system_prompt()` to pass to the LLM backend

The Scenario does NOT know which backend will run, which verifier framework
will judge, or how the loop drives it. That separation is what makes the
arbitrage thesis testable across backends.

Third-party packages can register their own scenarios via:

    # in their setup.cfg / pyproject.toml:
    [project.entry-points."ystar.czl.scenarios"]
    my_scenario = "my_pkg.scenarios:MyScenario"

The registry auto-discovers them at import time.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ystar.czl.verifiers.base import VerifierResult


@dataclass
class PlanStep:
    """One step in a scenario plan — concrete user-side prompt for the LLM."""
    step_id: str
    user_prompt: str
    expected_action_types: List[str] = field(default_factory=list)  # e.g. ["edit_file", "run_test"]


class Scenario(ABC):
    """
    Abstract base for a CZL scenario.

    Implementers MUST override:
      - name (class attribute)
      - description (class attribute)
      - y_star_invariants()
      - plan()
      - verify()
      - apply_action()

    They MAY override system_prompt() if the default is insufficient.
    """

    # === class metadata (override these) =====================================
    name: str = ""              # short identifier, used in CLI and registry
    description: str = ""       # one-line human description
    default_max_iterations: int = 10

    # === core interface =====================================================
    @abstractmethod
    def y_star_invariants(self) -> Dict[str, Any]:
        """
        Return the Y* invariant fields to merge into the IntentContract.

        Format must match ystar.kernel.dimensions.IntentContract schema, e.g.:

            {
                "invariant": [
                    "ruff_errors_after == 0",
                    "mypy_errors_after == 0",
                    "all_tests_still_pass == True",
                ],
                "only_paths": ["./src/", "./tests/"],
                "deny": [".env", "secret_key"],
            }

        These are NON-NEGOTIABLE — they are the scenario's spec. User-provided
        NL rules ADD to these but cannot remove them.
        """
        ...

    @abstractmethod
    def plan(self, task_description: str, workspace_dir: str) -> List[PlanStep]:
        """
        Generate the ordered list of steps to attempt for this task.

        A simple scenario might be a single step ("write the fix and prove it").
        A complex one might be several ("read the failing test, then propose fix,
        then run tests, then expand to edge cases").

        Each step's user_prompt is fed to the backend LLM.
        """
        ...

    @abstractmethod
    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        """
        Run all relevant external verifiers (pytest, ruff, mypy, ...) and
        return their results. Each VerifierResult.passed contributes to Rt+1.

        Rt+1 = sum(1 for r in results if not r.passed)

        This is the SOLE source of truth for "did the task succeed". No LLM
        self-assessment, no heuristic — only external tool output.
        """
        ...

    @abstractmethod
    def apply_action(self, action: Dict[str, Any], workspace_dir: str) -> None:
        """
        Apply one LLM-proposed action to the workspace. Actions are
        dict-shaped, e.g.:

            {"type": "edit_file", "path": "src/foo.py", "content": "..."}
            {"type": "run_command", "command": "pytest tests/test_foo.py"}
            {"type": "create_file", "path": "tests/test_new.py", "content": "..."}

        Implementations should be defensive: validate path is under
        workspace_dir, refuse to overwrite gitignored files, etc.
        """
        ...

    # === optional overrides =================================================
    def system_prompt(self) -> str:
        """
        Default system prompt — usable for many scenarios. Override if the
        scenario needs domain-specific framing (e.g. "you are a database
        migration generator").

        The default deliberately does NOT mention "safety" or "rules" — it
        frames the task as a quality-spec satisfaction problem, consistent
        with the arbitrage positioning.
        """
        return (
            "You are a senior software engineer completing one specific task. "
            "The task has a precise quality specification (passed as part of "
            "the user prompt). Your output will be evaluated by external CI "
            "tools (pytest, ruff, mypy, etc.) — only output that passes those "
            "tools counts as complete. If you cannot meet the spec, say so "
            "honestly rather than producing code that looks right but fails "
            "external verification. Do not modify test files unless explicitly "
            "instructed. Make minimum-scope changes."
        )

    def __repr__(self) -> str:
        return f"<Scenario {self.name}>"


# === registry ================================================================

class ScenarioRegistry:
    """
    Class-level registry of all Scenarios. Auto-populated by:
      1. Built-in scenarios in this package (eager import below).
      2. Third-party packages declaring entry_points["ystar.czl.scenarios"].
    """
    _registry: Dict[str, "Scenario"] = {}
    _entry_points_loaded: bool = False

    @classmethod
    def register(cls, scenario: Scenario) -> None:
        if not scenario.name:
            raise ValueError(f"Scenario {scenario!r} must define `name`")
        if scenario.name in cls._registry:
            raise ValueError(f"Scenario name collision: '{scenario.name}'")
        cls._registry[scenario.name] = scenario

    @classmethod
    def get(cls, name: str) -> Scenario:
        cls._lazy_load_entry_points()
        if name not in cls._registry:
            raise KeyError(
                f"No scenario named '{name}'. Available: {sorted(cls._registry.keys())}"
            )
        return cls._registry[name]

    @classmethod
    def list(cls) -> List[str]:
        cls._lazy_load_entry_points()
        return sorted(cls._registry.keys())

    @classmethod
    def _lazy_load_entry_points(cls) -> None:
        if cls._entry_points_loaded:
            return
        cls._entry_points_loaded = True
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group="ystar.czl.scenarios")
            for ep in eps:
                try:
                    scenario_cls = ep.load()
                    instance = scenario_cls() if isinstance(scenario_cls, type) else scenario_cls
                    cls.register(instance)
                except Exception as e:
                    import logging
                    logging.getLogger("ystar.czl").warning(
                        "Failed to load third-party scenario %s: %s", ep.name, e
                    )
        except Exception:
            # entry_points API may differ on older Python; non-fatal
            pass
