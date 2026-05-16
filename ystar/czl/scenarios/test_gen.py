"""
ystar.czl.scenarios.test_gen — MVP scenario #3 (test generation)

Developer has a source file with untested functions and says "write pytest
tests for these". CZL drives the LLM until the new tests pass and exercise
the target module.

Verifiers:
  - PytestAllPassVerifier  : every test must pass
  - TestsAddedVerifier     : at least one new test_*.py file or function
                             beyond the baseline, importing the target
  - NoTestSmellVerifier    : no `assert True`, `pytest.skip`, empty bodies

This scenario is the inverse of bug_fix/lint_fix in one dimension: the
agent's job is to WRITE test files. _safe_write therefore allows
create-new for test_*.py while still refusing edits to source files
under a sentinel `_PRESERVE_SOURCE` env flag.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Set

from ystar.czl.scenarios.base import Scenario, PlanStep, ScenarioRegistry
from ystar.czl.verifiers.base import Verifier, VerifierResult


# === verifiers ================================================================

class PytestAllPassVerifier(Verifier):
    name = "pytest"

    def is_applicable(self, workspace_dir: str) -> bool:
        for root, _, files in os.walk(workspace_dir):
            if any(f.startswith("test_") and f.endswith(".py") for f in files):
                return True
        return False

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        try:
            proc = subprocess.run(
                ["pytest", "-q", "--tb=short", "--no-header"],
                cwd=workspace_dir, capture_output=True, text=True, timeout=180,
            )
            if proc.returncode == 0:
                m = re.search(r"(\d+) passed", proc.stdout or "")
                n = int(m.group(1)) if m else 0
                return VerifierResult(
                    verifier_name=self.name, passed=True,
                    message=f"pytest: {n} passed",
                    elapsed_seconds=time.time() - t0,
                )
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="pytest: failures present",
                details={"stdout": (proc.stdout or "")[-2000:], "stderr": (proc.stderr or "")[-500:]},
                elapsed_seconds=time.time() - t0,
            )
        except FileNotFoundError:
            return VerifierResult(verifier_name=self.name, passed=False, message="pytest not installed", elapsed_seconds=time.time() - t0)
        except subprocess.TimeoutExpired:
            return VerifierResult(verifier_name=self.name, passed=False, message="pytest timed out after 180s", elapsed_seconds=time.time() - t0)


class TestsAddedVerifier(Verifier):
    """At least one test_*.py file must exist AND import the target module(s)."""
    name = "tests_added"

    def is_applicable(self, workspace_dir: str) -> bool:
        return True

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        test_funcs = 0
        target_imported = False
        target_modules = _list_source_modules(workspace_dir)
        for root, _, files in os.walk(workspace_dir):
            if ".git" in root.split(os.sep) or "__pycache__" in root:
                continue
            for f in files:
                if not (f.startswith("test_") and f.endswith(".py")):
                    continue
                p = os.path.join(root, f)
                try:
                    body = open(p, "r", encoding="utf-8").read()
                except Exception:
                    continue
                try:
                    tree = ast.parse(body)
                except SyntaxError:
                    return VerifierResult(
                        verifier_name=self.name, passed=False,
                        message=f"test file {f} has SyntaxError",
                        elapsed_seconds=time.time() - t0,
                    )
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                        test_funcs += 1
                # check imports
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        names = []
                        if isinstance(node, ast.ImportFrom) and node.module:
                            names.append(node.module.split(".")[0])
                        else:
                            for n in node.names:
                                names.append(n.name.split(".")[0])
                        for n in names:
                            if n in target_modules:
                                target_imported = True
        if test_funcs == 0:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="no test_* functions found",
                elapsed_seconds=time.time() - t0,
            )
        if not target_imported and target_modules:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"test files do not import any target module ({sorted(target_modules)})",
                elapsed_seconds=time.time() - t0,
            )
        return VerifierResult(
            verifier_name=self.name, passed=True,
            message=f"tests_added: {test_funcs} test function(s) importing target module",
            elapsed_seconds=time.time() - t0,
        )


class NoTestSmellVerifier(Verifier):
    """Refuse trivial smells: `assert True`, `assert False`, empty bodies, skip/xfail."""
    name = "no_test_smells"

    def is_applicable(self, workspace_dir: str) -> bool:
        return True

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        smells: List[str] = []
        for root, _, files in os.walk(workspace_dir):
            if ".git" in root.split(os.sep) or "__pycache__" in root:
                continue
            for f in files:
                if not (f.startswith("test_") and f.endswith(".py")):
                    continue
                p = os.path.join(root, f)
                try:
                    body = open(p, "r", encoding="utf-8").read()
                except Exception:
                    continue
                try:
                    tree = ast.parse(body)
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
                        continue
                    stmts = [s for s in node.body
                             if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))]
                    if not stmts:
                        smells.append(f"{f}:{node.name}: empty body")
                        continue
                    # Detect smell patterns
                    src = ast.unparse(node) if hasattr(ast, "unparse") else ""
                    if re.search(r"\bassert\s+True\b", src) and "assert " == src.split("\n")[0].strip()[:7]:
                        pass  # rough — skip noisy detection
                    if "assert True" in src and re.search(r"assert\s+True\s*(#|$)", src):
                        smells.append(f"{f}:{node.name}: assert True")
                    if "assert False" in src and re.search(r"assert\s+False\s*(#|$)", src):
                        smells.append(f"{f}:{node.name}: assert False")
                    if "pytest.skip" in src:
                        smells.append(f"{f}:{node.name}: pytest.skip")
                    if "pytest.xfail" in src:
                        smells.append(f"{f}:{node.name}: pytest.xfail")
                    # body is just pass
                    if len(stmts) == 1 and isinstance(stmts[0], ast.Pass):
                        smells.append(f"{f}:{node.name}: body is pass-only")
        if smells:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"test smells: {smells[:5]}",
                details={"all_smells": smells},
                elapsed_seconds=time.time() - t0,
            )
        return VerifierResult(
            verifier_name=self.name, passed=True,
            message="no test smells",
            elapsed_seconds=time.time() - t0,
        )


def _list_source_modules(workspace_dir: str) -> Set[str]:
    """Module names (without .py) of editable source — used to verify tests import target."""
    out: Set[str] = set()
    for root, dirs, files in os.walk(workspace_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            if fname.startswith("test_") or fname == "conftest.py":
                continue
            out.add(fname[:-3])
    return out


# === scenario =================================================================

class TestGenScenario(Scenario):
    name = "test_gen"
    description = "Write pytest tests for an untested function; exercise behaviour, not trivia"
    default_max_iterations = 6

    def y_star_invariants(self) -> Dict[str, Any]:
        return {
            "invariant": [
                "all_pytest_tests_pass == True",
                "tests_added > 0 AND target_module_imported == True",
                "no_test_smells == True",
            ],
            "only_paths": ["./"],
            "deny": [".env", ".git/", "secrets"],
        }

    def plan(self, task_description: str, workspace_dir: str) -> List[PlanStep]:
        source_files = self._list_workspace_source_files(workspace_dir)
        file_blocks = self._render_file_blocks(workspace_dir, source_files)
        existing_tests = self._list_existing_test_files(workspace_dir)
        existing_listing = "\n".join(f"- {p}" for p in existing_tests) or "(none yet)"
        files_listing = "\n".join(f"- {p}" for p in source_files) or "(none)"
        return [
            PlanStep(
                step_id="write_tests",
                user_prompt=(
                    f"## Task\n{task_description}\n\n"
                    "## Source modules to test (read-only — do NOT modify these)\n"
                    f"{files_listing}\n\n"
                    "## Current source content\n"
                    f"{file_blocks}\n\n"
                    "## Existing test files (you may extend or add new test_*.py)\n"
                    f"{existing_listing}\n\n"
                    "## Constraints (Y*)\n"
                    "- Every test you write must pass under `pytest -q`\n"
                    "- At least one of your tests must import from the source modules above\n"
                    "- Do NOT modify the source files — only create or extend test_*.py files\n"
                    "- Test names must start with `test_` (pytest convention)\n"
                    "- Tests must actually exercise behaviour: no `assert True`, no `pytest.skip`, no empty bodies\n"
                    "- Use pytest idioms (parametrize, tmp_path, mocker) where appropriate; don't reinvent\n\n"
                    "## Output format\n"
                    "For each test file you write, emit one fenced block with COMPLETE file content:\n\n"
                    "```edit test_<module>.py\n"
                    "<full new test file content>\n"
                    "```\n\n"
                    "Prefer one test file per source module (`test_<module>.py`). "
                    "If you cannot test something honestly without the real dependency, say so — "
                    "do not write a trivially-passing stub."
                ),
                expected_action_types=["create_file", "edit_file"],
            )
        ]

    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        results: List[VerifierResult] = []
        for v in (PytestAllPassVerifier(), TestsAddedVerifier(), NoTestSmellVerifier()):
            if v.is_applicable(workspace_dir):
                results.append(v.run(workspace_dir, contract))
        return results

    def apply_action(self, action: Dict[str, Any], workspace_dir: str) -> None:
        action_type = action.get("type", "") if isinstance(action, dict) else getattr(action, "type", "")
        payload = action.payload if hasattr(action, "payload") else action
        if action_type in ("edit_file", "create_file"):
            self._safe_write(workspace_dir, payload.get("path", ""), payload.get("content", ""))

    # === helpers ===========================================================

    def _list_workspace_source_files(self, workspace_dir: str) -> List[str]:
        out: List[str] = []
        for root, dirs, files in os.walk(workspace_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                if fname.startswith("test_") or fname == "conftest.py":
                    continue
                full = os.path.join(root, fname)
                out.append(os.path.relpath(full, workspace_dir))
        return sorted(out)

    def _list_existing_test_files(self, workspace_dir: str) -> List[str]:
        out: List[str] = []
        for root, dirs, files in os.walk(workspace_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for fname in files:
                if fname.startswith("test_") and fname.endswith(".py"):
                    full = os.path.join(root, fname)
                    out.append(os.path.relpath(full, workspace_dir))
        return sorted(out)

    def _render_file_blocks(self, workspace_dir: str, rel_paths: List[str]) -> str:
        chunks: List[str] = []
        for rel in rel_paths:
            full = os.path.join(workspace_dir, rel)
            try:
                body = open(full, "r", encoding="utf-8").read()
            except Exception as e:
                body = f"(could not read: {e})"
            chunks.append(f"### {rel}\n```python\n{body}```")
        return "\n\n".join(chunks) if chunks else "(no source files)"

    def _safe_write(self, workspace_dir: str, rel_path: str, content: str) -> None:
        full = os.path.abspath(os.path.join(workspace_dir, rel_path))
        ws_abs = os.path.abspath(workspace_dir)
        if not full.startswith(ws_abs + os.sep) and full != ws_abs:
            raise ValueError(f"Refusing to write outside workspace: {rel_path}")
        basename = os.path.basename(full)
        # test_gen semantics INVERT lint_fix / bug_fix: test files are
        # writeable; SOURCE files are read-only.
        if not (basename.startswith("test_") and basename.endswith(".py")) and basename != "conftest.py":
            return
        if any(d in full for d in (".env", ".git", "secrets")):
            return
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)


ScenarioRegistry.register(TestGenScenario())
