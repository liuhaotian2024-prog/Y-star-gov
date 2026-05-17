"""
ystar.czl.scenarios.generic — v3.3 C.3 fallback scenario.

When the TaskRouter finds no signal matching a known scenario, we fall
back to this Scenario. Its verify() chain runs only the most universal
checks (pytest pass + contract consistency); it does NOT impose any
scenario-specific verifier like mutation_score or signature_frozen.

Design: deliberately permissive. Better to converge a generic task than
to refuse the work because we don't have a scenario for it.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Dict, List, Optional

from ystar.czl.scenarios.base import Scenario, PlanStep, ScenarioRegistry
from ystar.czl.verifiers.base import Verifier, VerifierResult, tier_compatible
from ystar.czl.verifiers.contract_verifier import ContractConsistencyVerifier


class GenericPytestPassVerifier(Verifier):
    """Pytest passes if there ARE test files; otherwise auto-passes
    (generic task doesn't necessarily come with tests)."""
    name = "pytest"
    applies_to_tasks = ["all"]
    min_model_capacity = "small"
    feedback_complexity = "low"

    def is_applicable(self, workspace_dir: str, contract: Optional[Dict[str, Any]] = None) -> bool:
        return True

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        has_tests = any(
            f.startswith("test_") and f.endswith(".py")
            for _, _, files in os.walk(workspace_dir) for f in files
        )
        if not has_tests:
            return VerifierResult(
                verifier_name=self.name, passed=True,
                message="no tests in workspace — pytest skipped",
                message_natural="工作目录里没有 test_*.py, 跳过 pytest 检查.",
                elapsed_seconds=time.time() - t0,
            )
        try:
            proc = subprocess.run(
                ["pytest", "-q", "--tb=short", "--no-header"],
                cwd=workspace_dir, capture_output=True, text=True, timeout=120,
            )
            passed = proc.returncode == 0
            return VerifierResult(
                verifier_name=self.name, passed=passed,
                message=("pytest: all pass" if passed else "pytest: failures"),
                message_natural=("pytest 全部通过." if passed else
                                 "pytest 有失败:\n" + (proc.stdout or "")[-800:]),
                details={"stdout": (proc.stdout or "")[-1500:]},
                elapsed_seconds=time.time() - t0,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="pytest timed out", message_natural="pytest 超时.",
                elapsed_seconds=time.time() - t0,
            )


class GenericScenario(Scenario):
    name = "generic"
    description = "Fallback scenario when TaskRouter finds no specific signal match"
    default_max_iterations = 6

    def __init__(self) -> None:
        self._pytest = GenericPytestPassVerifier()
        self._contract = ContractConsistencyVerifier()

    def y_star_invariants(self) -> Dict[str, Any]:
        return {
            "invariant": [
                "all_pytest_tests_pass == True",
                "contract_consistency_clean == True",
            ],
            "only_paths": ["./"],
            "deny": [".env", ".git/", "secrets"],
        }

    def plan(self, task_description: str, workspace_dir: str) -> List[PlanStep]:
        existing = []
        for r, _, fs in os.walk(workspace_dir):
            for f in fs:
                if f.endswith(".py"):
                    existing.append(os.path.relpath(os.path.join(r, f), workspace_dir))
        existing.sort()
        file_listing = "\n".join(f"- {p}" for p in existing[:50]) or "(empty)"
        return [PlanStep(
            step_id="generic_edit",
            user_prompt=(
                f"## Task\n{task_description}\n\n"
                f"## Workspace files (.py)\n{file_listing}\n\n"
                "## Constraints (Y*)\n"
                "- Any test files in the workspace must still pass after your edits.\n"
                "- All function calls must remain internally consistent (no calling functions with the wrong arity).\n"
                "- Do NOT touch .env, .git/, or secrets.\n\n"
                "## Output format\n"
                "Emit one or more edit_file blocks:\n"
                "```edit <relative_path>\n"
                "<full new file content>\n"
                "```\n"
            ),
            expected_action_types=["edit_file", "create_file"],
        )]

    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        contract = contract or {}
        model_tier = contract.get("model_tier", "medium")
        verifiers = [self._pytest, self._contract]
        verifiers = [v for v in verifiers if tier_compatible(v.min_model_capacity, model_tier)]
        results: List[VerifierResult] = []
        for v in verifiers:
            try:
                applicable = v.is_applicable(workspace_dir, contract)
            except TypeError:
                applicable = v.is_applicable(workspace_dir)
            if applicable:
                results.append(v.run(workspace_dir, contract))
        return results

    def apply_action(self, action: Dict[str, Any], workspace_dir: str) -> None:
        action_type = action.get("type", "") if isinstance(action, dict) else getattr(action, "type", "")
        payload = action.payload if hasattr(action, "payload") else action
        if action_type in ("edit_file", "create_file"):
            self._safe_write(workspace_dir, payload.get("path", ""), payload.get("content", ""))

    def _safe_write(self, workspace_dir: str, rel_path: str, content: str) -> None:
        if not rel_path:
            return
        full = os.path.abspath(os.path.join(workspace_dir, rel_path))
        ws_abs = os.path.abspath(workspace_dir)
        if not full.startswith(ws_abs + os.sep) and full != ws_abs:
            raise ValueError(f"Refusing to write outside workspace: {rel_path}")
        if any(d in full for d in (".env", ".git", "secrets")):
            return
        os.makedirs(os.path.dirname(full) or workspace_dir, exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)


ScenarioRegistry.register(GenericScenario())
