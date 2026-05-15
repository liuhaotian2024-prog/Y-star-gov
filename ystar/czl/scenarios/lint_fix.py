"""
ystar.czl.scenarios.lint_fix — MVP scenario #1

The "demo from the README" task: developer has a file with ruff/mypy errors,
says "fix these without breaking my tests". CZL drives the LLM in a loop
until ruff/mypy report zero issues AND all tests still pass.

This scenario is intentionally simple — it's the cheapest way to demonstrate
the arbitrage thesis: cheap-API output reaches Claude-grade quality because
external CI tools force convergence.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Dict, List

from ystar.czl.scenarios.base import Scenario, PlanStep, ScenarioRegistry
from ystar.czl.verifiers.base import Verifier, VerifierResult


# === verifier wrappers ========================================================
# These wrap ruff / mypy / pytest as subprocesses. Real production code would
# pull these into ystar/czl/verifiers/*.py, but for the MVP first scenario
# we co-locate to keep the example self-contained and easy to read.

class RuffVerifier(Verifier):
    name = "ruff"

    def is_applicable(self, workspace_dir: str) -> bool:
        for root, _, files in os.walk(workspace_dir):
            if any(f.endswith(".py") for f in files):
                return True
        return False

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        started = time.time()
        try:
            proc = subprocess.run(
                ["ruff", "check", "--output-format=json", "."],
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            elapsed = time.time() - started
            if proc.returncode == 0:
                return VerifierResult(
                    verifier_name=self.name,
                    passed=True,
                    message="ruff: 0 issues",
                    details={"stdout": proc.stdout[:1000]},
                    elapsed_seconds=elapsed,
                )
            # Issues found — try to parse for clearer message
            import json
            try:
                issues = json.loads(proc.stdout)
                first = issues[0] if issues else {}
                msg = f"ruff: {len(issues)} issue(s); first: {first.get('code', '?')} {first.get('message', '')[:80]}"
            except Exception:
                msg = f"ruff: failed with rc={proc.returncode}; {proc.stdout[:200]}"
            return VerifierResult(
                verifier_name=self.name,
                passed=False,
                message=msg,
                details={"stdout": proc.stdout, "stderr": proc.stderr},
                elapsed_seconds=elapsed,
            )
        except FileNotFoundError:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="ruff not installed (pip install ruff)",
                elapsed_seconds=time.time() - started,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="ruff timed out after 60s",
                elapsed_seconds=time.time() - started,
            )


class MypyVerifier(Verifier):
    name = "mypy"

    def is_applicable(self, workspace_dir: str) -> bool:
        for root, _, files in os.walk(workspace_dir):
            if any(f.endswith(".py") for f in files):
                return True
        return False

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        started = time.time()
        try:
            proc = subprocess.run(
                ["mypy", "--show-error-codes", "--no-error-summary", "."],
                cwd=workspace_dir, capture_output=True, text=True, timeout=120,
            )
            elapsed = time.time() - started
            # mypy returns 0 if no errors, nonzero otherwise
            if proc.returncode == 0:
                return VerifierResult(
                    verifier_name=self.name, passed=True,
                    message="mypy: 0 errors",
                    elapsed_seconds=elapsed,
                )
            err_lines = [l for l in proc.stdout.splitlines() if ": error:" in l]
            msg = f"mypy: {len(err_lines)} error(s)"
            if err_lines:
                msg += f"; first: {err_lines[0][:120]}"
            return VerifierResult(
                verifier_name=self.name, passed=False, message=msg,
                details={"stdout": proc.stdout, "stderr": proc.stderr},
                elapsed_seconds=elapsed,
            )
        except FileNotFoundError:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="mypy not installed (pip install mypy)",
                elapsed_seconds=time.time() - started,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="mypy timed out after 120s",
                elapsed_seconds=time.time() - started,
            )


class PytestVerifier(Verifier):
    """Run existing tests — they must STILL pass after lint fix."""
    name = "pytest_unchanged"

    def is_applicable(self, workspace_dir: str) -> bool:
        # Look for tests dir or test_*.py files
        if os.path.isdir(os.path.join(workspace_dir, "tests")):
            return True
        for root, _, files in os.walk(workspace_dir):
            if any(f.startswith("test_") and f.endswith(".py") for f in files):
                return True
        return False

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        started = time.time()
        try:
            proc = subprocess.run(
                ["pytest", "-q", "--tb=no", "--no-header"],
                cwd=workspace_dir, capture_output=True, text=True, timeout=300,
            )
            elapsed = time.time() - started
            if proc.returncode == 0:
                return VerifierResult(
                    verifier_name=self.name, passed=True,
                    message="pytest: all tests pass",
                    elapsed_seconds=elapsed,
                )
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"pytest: failures detected (rc={proc.returncode})",
                details={"stdout": proc.stdout[-2000:], "stderr": proc.stderr[-500:]},
                elapsed_seconds=elapsed,
            )
        except FileNotFoundError:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="pytest not installed",
                elapsed_seconds=time.time() - started,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="pytest timed out after 300s",
                elapsed_seconds=time.time() - started,
            )


# === the scenario itself ======================================================

class LintFixScenario(Scenario):
    name = "lint_fix"
    description = "Fix ruff and mypy errors in workspace without breaking tests"
    default_max_iterations = 6

    def y_star_invariants(self) -> Dict[str, Any]:
        return {
            "invariant": [
                "ruff_errors_after == 0",
                "mypy_errors_after == 0",
                "all_tests_still_pass == True",
            ],
            "only_paths": ["./"],   # default — scenario will narrow if user specifies
            "deny": [".env", ".git/", "secrets"],
        }

    def plan(self, task_description: str, workspace_dir: str) -> List[PlanStep]:
        # Enumerate the actual Python files in the workspace and the actual
        # current ruff/mypy output. Small models hallucinate filenames when
        # given a vague task; giving them the exact file list + verifier
        # output keeps their edits scoped.
        existing_files = self._list_workspace_py_files(workspace_dir)
        baseline = self._collect_baseline_violations(workspace_dir)

        files_listing = "\n".join(f"- {p}" for p in existing_files) or "(none)"
        return [
            PlanStep(
                step_id="fix_lint_and_type",
                user_prompt=(
                    f"## Task\n{task_description}\n\n"
                    "## Existing files in this workspace (edit ONLY these — "
                    "do NOT invent new paths or directories)\n"
                    f"{files_listing}\n\n"
                    "## Current ruff/mypy/pytest output to address\n"
                    f"```\n{baseline}\n```\n\n"
                    "## Constraints (Y*)\n"
                    "- ruff check must report 0 issues after your changes\n"
                    "- mypy must report 0 errors after your changes\n"
                    "- ALL existing tests must still pass\n"
                    "- Do NOT modify test files (anything matching `test_*.py`)\n"
                    "- Do NOT create new files or directories — only edit the files listed above\n"
                    "- Make minimum-scope edits — fix only what ruff/mypy flag\n\n"
                    "## Output format\n"
                    "For each file you change, emit one fenced block using the EXACT path from the list above:\n\n"
                    "```edit <relative_path>\n"
                    "<full new file content>\n"
                    "```\n\n"
                    "If you cannot achieve all constraints, say so honestly — "
                    "do NOT silently leave issues unfixed and claim done."
                ),
                expected_action_types=["edit_file"],
            )
        ]

    def _list_workspace_py_files(self, workspace_dir: str) -> List[str]:
        """Relative paths of .py files in workspace, excluding caches/tests/hidden."""
        out: List[str] = []
        for root, dirs, files in os.walk(workspace_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                if fname.startswith("test_"):
                    continue
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, workspace_dir)
                out.append(rel)
        return sorted(out)

    def _collect_baseline_violations(self, workspace_dir: str) -> str:
        """Compact text summary of the current ruff/mypy state, for the prompt."""
        lines: List[str] = []
        try:
            proc = subprocess.run(
                ["ruff", "check", "--output-format=concise", "."],
                cwd=workspace_dir, capture_output=True, text=True, timeout=30,
            )
            ruff_out = (proc.stdout or proc.stderr or "").strip()
            lines.append("[ruff]")
            lines.append(ruff_out or "(no output)")
        except Exception as e:
            lines.append(f"[ruff] could not run: {e}")
        try:
            proc = subprocess.run(
                ["mypy", "--show-error-codes", "--no-error-summary", "."],
                cwd=workspace_dir, capture_output=True, text=True, timeout=60,
            )
            mypy_out = (proc.stdout or proc.stderr or "").strip()
            lines.append("[mypy]")
            lines.append(mypy_out or "(no output)")
        except Exception as e:
            lines.append(f"[mypy] could not run: {e}")
        return "\n".join(lines)

    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        results: List[VerifierResult] = []
        for v in (RuffVerifier(), MypyVerifier(), PytestVerifier()):
            if v.is_applicable(workspace_dir):
                results.append(v.run(workspace_dir, contract))
        return results

    def apply_action(self, action: Dict[str, Any], workspace_dir: str) -> None:
        action_type = action.get("type", "") if isinstance(action, dict) else getattr(action, "type", "")
        # accept both dict and BackendAction
        if hasattr(action, "payload"):
            payload = action.payload
        else:
            payload = action

        if action_type == "edit_file" or action_type == "create_file":
            path = payload.get("path", "")
            content = payload.get("content", "")
            self._safe_write(workspace_dir, path, content)
        # other action types intentionally ignored for this scenario
        # (no run_command on user files during lint fix)

    def _safe_write(self, workspace_dir: str, rel_path: str, content: str) -> None:
        # Defensive: refuse paths trying to escape workspace
        full_path = os.path.abspath(os.path.join(workspace_dir, rel_path))
        ws_abs = os.path.abspath(workspace_dir)
        if not full_path.startswith(ws_abs + os.sep) and full_path != ws_abs:
            raise ValueError(f"Refusing to write outside workspace: {rel_path}")
        # Refuse to touch test files (Y* hard rule)
        basename = os.path.basename(full_path)
        if basename.startswith("test_") or full_path.replace("\\", "/").endswith("/tests"):
            # block test-file edits; if the LLM tries to "fix" a test, we want CZL
            # to see that as a non-converging attempt, not allow it through
            return
        # Refuse anything in deny list
        denied = (".env", ".git", "secrets")
        if any(d in full_path for d in denied):
            return
        # Lint-fix semantics: edit existing files only. Refusing to create new
        # files prevents small models from "fixing" issues by inventing new
        # modules in subdirectories that then introduce more violations.
        if not os.path.exists(full_path):
            return
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)


# Register on import
ScenarioRegistry.register(LintFixScenario())
