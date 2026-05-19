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
from typing import Any, Dict, List, Optional

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
    def plan(self, task_description: str, workspace_dir: str,
             contract: Optional[Dict[str, Any]] = None) -> List[PlanStep]:
        """
        Generate the ordered list of steps to attempt for this task.

        v3.4: `contract` kwarg is now passed by loop.py so scenarios can
        read trial-scoped fields. Existing scenarios that ignore the kwarg
        keep working.

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
    def output_protocol(self) -> Optional[Dict[str, Any]]:
        """Declare the scenario's output protocol so the loop's reactive
        feedback can render scenario-correct format instructions instead of
        hard-coding strings.

        Return None to opt out (the feedback formatter will skip the
        instruction line). Return a dict with at least:

          {
            "file_name":  str,   # primary output file the scenario consumes
            "block_tag":  str,   # code-fence tag the model should emit
                                 # (e.g. "add_tests", "python", "sql",
                                 # "replace_file")
            "instruction": str,  # 1-3 sentences shown to small-tier models
                                 # in retry feedback. Describes the format,
                                 # not the content.
          }

        Optional fields:
          - "preserves_existing": bool, hint for callers
          - "extra": dict, arbitrary scenario metadata

        Adaptive, non-hardcoded principle: the feedback formatter MUST NOT
        embed scenario-specific filenames or block tags in its source.
        """
        return None

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


# === v4.0 T5: environment inventory prompt helper ============================
# Pure render of WorkspaceInventory.scan() output. No recommendations. No
# scenario-specific bias. The model reads facts and decides what to do.

def render_environment_inventory(inventory: Dict[str, Any]) -> str:
    """Render a fact-only environment section, plus a universal `probe`
    tool description. Used by scenario.plan() — prepended to user_prompt.
    """
    lines: List[str] = ["## Environment inventory (auto-discovered, no recommendations)", ""]

    # Files
    files = inventory.get("files") or []
    lines.append("### Files in workspace")
    if files:
        for f in files:
            lines.append(f"  - {f}")
    else:
        lines.append("  (none)")

    # Interpreters
    interps = inventory.get("interpreters") or {}
    lines.append("")
    lines.append("### Commands available on this system")
    if interps:
        for cmd, path in sorted(interps.items()):
            lines.append(f"  - {cmd}  ({path})")
    else:
        lines.append("  (none detected)")

    # Source interfaces
    src = inventory.get("source_interfaces") or {}
    if src:
        lines.append("")
        lines.append("### Source code interfaces (auto-extracted from AST)")
        for filename, info in src.items():
            if isinstance(info, dict) and "error" in info:
                continue
            lines.append("")
            lines.append(f"  {filename}:")
            for fn in (info.get("functions") or []):
                lines.append(f"    - {fn['name']}{fn.get('signature', '(?)')}")
                doc = fn.get("docstring_first_line")
                if doc:
                    lines.append(f"      doc: {doc}")
            for cls in (info.get("classes") or []):
                lines.append(f"    - class {cls['name']}")

    # Probe tool description — generic, no recommendations.
    lines.append("")
    lines.append("### Probe tool")
    lines.append("")
    lines.append(
        "You can execute any shell command in the workspace before writing code. "
        "This is faster and more reliable than guessing what a function returns "
        "or how a tool behaves. Use the probe block format:"
    )
    lines.append("")
    lines.append("```probe")
    lines.append("{any shell command here}")
    lines.append("```")
    lines.append("")
    lines.append("Examples (these are not recommendations — they show the format):")
    lines.append("")
    lines.append("```probe")
    lines.append('python3.11 -c "from data_pipeline import aggregate_by_domain; '
                 'print(repr(aggregate_by_domain([{\'email\':\'a@x.com\'}])))"')
    lines.append("```")
    lines.append("")
    lines.append("```probe")
    lines.append("pytest test_data_pipeline.py::test_specific -v --tb=short")
    lines.append("```")
    lines.append("")
    lines.append("```probe")
    lines.append("ls -la")
    lines.append("cat data_pipeline.py | head -30")
    lines.append("```")
    lines.append("")
    lines.append(
        "After your probe block(s), write code in the normal output block "
        "(```add_tests``` for test_generation, ```edit``` for other scenarios). "
        "You may probe multiple times across multiple iters — there's no per-iter "
        "limit. Probe whenever you're unsure about anything."
    )
    return "\n".join(lines)


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
