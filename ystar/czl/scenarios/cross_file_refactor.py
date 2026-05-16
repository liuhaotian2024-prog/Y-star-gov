"""
ystar.czl.scenarios.cross_file_refactor — v3 scenario #1

Indie task: replace deprecated function `foo()` with `bar()` across the
codebase. Foo() is called in 8 places across 5 caller files plus its own
definition in utils/old_api.py; 2 of those calls live inside f-strings.

The agent must edit source freely, leave test files untouched, end up with
zero `foo(` occurrences (excluding comments), and keep tests passing.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Any, Dict, List

from ystar.czl.scenarios.base import Scenario, PlanStep, ScenarioRegistry
from ystar.czl.verifiers.base import Verifier, VerifierResult


# === workspace fixture =======================================================

BASELINE_FILES: Dict[str, str] = {
    "utils/__init__.py": "",
    "utils/old_api.py": (
        '"""Deprecated: foo() is the old name; bar() is the new one."""\n'
        "\n"
        "\n"
        "def foo(x: int) -> int:\n"
        "    return bar(x)\n"
        "\n"
        "\n"
        "def bar(x: int) -> int:\n"
        "    return x * 2\n"
    ),
    "service_a.py": (
        "from utils.old_api import foo\n"
        "\n"
        "\n"
        "def compute_a(n: int) -> int:\n"
        "    return foo(n) + 1\n"
    ),
    "service_b.py": (
        "from utils.old_api import foo\n"
        "\n"
        "\n"
        "def compute_b(n: int) -> str:\n"
        "    result = foo(n)\n"
        "    return f\"calling foo({n}) returned {result}\"\n"
    ),
    "service_c.py": (
        "from utils.old_api import foo\n"
        "\n"
        "\n"
        "def describe_c(n: int) -> str:\n"
        "    return f\"after foo({n}) we get {foo(n)}\"\n"
    ),
    "service_d.py": (
        "from utils.old_api import foo\n"
        "\n"
        "\n"
        "def compute_d(n: int) -> int:\n"
        "    return foo(n) - 1\n"
    ),
    "service_e.py": (
        "from utils.old_api import foo\n"
        "\n"
        "\n"
        "def compute_e(n: int) -> int:\n"
        "    intermediate = foo(n)\n"
        "    return foo(intermediate)\n"
    ),
    "test_services.py": (
        "from service_a import compute_a\n"
        "from service_b import compute_b\n"
        "from service_c import describe_c\n"
        "from service_d import compute_d\n"
        "from service_e import compute_e\n"
        "\n"
        "\n"
        "def test_compute_a():\n"
        "    assert compute_a(3) == 7\n"
        "\n"
        "\n"
        "def test_compute_b():\n"
        "    s = compute_b(3)\n"
        "    assert '6' in s and '3' in s\n"
        "\n"
        "\n"
        "def test_describe_c():\n"
        "    s = describe_c(4)\n"
        "    assert '8' in s and '4' in s\n"
        "\n"
        "\n"
        "def test_compute_d():\n"
        "    assert compute_d(5) == 9\n"
        "\n"
        "\n"
        "def test_compute_e():\n"
        "    assert compute_e(2) == 8\n"
    ),
}

TASK_DESCRIPTION = (
    "把 utils/old_api.py 里的 deprecated 函数 foo() 在整个 codebase "
    "替换成 bar()。所有调用点都要更新，包括 f-string 里的引用。"
    "所有测试必须仍然通过。"
)


# === verifiers ===============================================================

class NoFooCallsVerifier(Verifier):
    """ripgrep-equivalent: zero `foo(` occurrences in source (excluding comments)."""
    name = "no_foo_calls"

    def is_applicable(self, workspace_dir: str) -> bool:
        return True

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        offending: List[str] = []
        for root, dirs, files in os.walk(workspace_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                # Tests can mention foo only if they're comments — we don't
                # block tests here because TestFilesUnchangedVerifier already
                # rules out edits; foo in original tests was zero.
                full = os.path.join(root, fname)
                try:
                    body = open(full, "r", encoding="utf-8").read()
                except Exception:
                    continue
                for lineno, line in enumerate(body.splitlines(), 1):
                    stripped = line.split("#", 1)[0]  # strip line comments
                    # also skip docstrings — heuristic: lines inside triple-quoted blocks
                    # we just look for the literal pattern foo(
                    if re.search(r"\bfoo\(", stripped):
                        rel = os.path.relpath(full, workspace_dir)
                        offending.append(f"{rel}:{lineno}: {line.rstrip()[:80]}")
        if offending:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"foo() still called {len(offending)} place(s); first: {offending[0]}",
                details={"all": offending[:20]},
                elapsed_seconds=time.time() - t0,
            )
        return VerifierResult(
            verifier_name=self.name, passed=True,
            message="no foo() calls remain",
            elapsed_seconds=time.time() - t0,
        )


class PytestPassVerifier(Verifier):
    name = "pytest"

    def is_applicable(self, workspace_dir: str) -> bool:
        return True

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        try:
            proc = subprocess.run(
                ["pytest", "-q", "--tb=short", "--no-header"],
                cwd=workspace_dir, capture_output=True, text=True, timeout=120,
            )
            if proc.returncode == 0:
                return VerifierResult(verifier_name=self.name, passed=True,
                                      message="pytest: all pass",
                                      elapsed_seconds=time.time() - t0)
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="pytest: failures present",
                details={"stdout": (proc.stdout or "")[-1500:]},
                elapsed_seconds=time.time() - t0,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(verifier_name=self.name, passed=False,
                                  message="pytest timed out", elapsed_seconds=time.time() - t0)


class TestFilesUnchangedVerifier(Verifier):
    name = "test_files_unchanged"

    def is_applicable(self, workspace_dir: str) -> bool:
        return os.path.isdir(os.path.join(workspace_dir, ".git"))

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        proc = subprocess.run(["git", "status", "--porcelain"],
                              cwd=workspace_dir, capture_output=True, text=True, timeout=10)
        offending: List[str] = []
        for line in proc.stdout.splitlines():
            p = line[3:].split("->")[-1].strip() if len(line) > 3 else ""
            bn = os.path.basename(p)
            if (bn.startswith("test_") and bn.endswith(".py")) or bn == "conftest.py" or "/tests/" in ("/" + p):
                offending.append(p)
        if offending:
            return VerifierResult(verifier_name=self.name, passed=False,
                                  message=f"test files modified: {offending[:5]}",
                                  details={"offending": offending},
                                  elapsed_seconds=time.time() - t0)
        return VerifierResult(verifier_name=self.name, passed=True,
                              message="test files unchanged", elapsed_seconds=time.time() - t0)


# === scenario ================================================================

class CrossFileRefactorScenario(Scenario):
    name = "cross_file_refactor"
    description = "Rename deprecated foo() → bar() across multiple files including f-strings"
    default_max_iterations = 8

    def y_star_invariants(self) -> Dict[str, Any]:
        return {
            "invariant": [
                "no_foo_calls_remain == True",
                "all_pytest_tests_pass == True",
                "test_files_unchanged == True",
            ],
            "only_paths": ["./"],
            "deny": [".env", ".git/", "secrets"],
        }

    def plan(self, task_description: str, workspace_dir: str) -> List[PlanStep]:
        source_files = self._list_workspace_source_files(workspace_dir)
        file_blocks = self._render_file_blocks(workspace_dir, source_files)
        files_listing = "\n".join(f"- {p}" for p in source_files)
        baseline = self._collect_baseline(workspace_dir)
        return [PlanStep(
            step_id="rename_foo_to_bar",
            user_prompt=(
                f"## Task\n{task_description}\n\n"
                "## Editable source files (test files are READ-ONLY)\n"
                f"{files_listing}\n\n"
                "## Current source content\n"
                f"{file_blocks}\n\n"
                "## Current state of `foo(` occurrences across the workspace\n"
                f"```\n{baseline}\n```\n\n"
                "## Constraints (Y*)\n"
                "- After your changes, `foo(` must NOT appear in any non-comment source line\n"
                "- Update every call site — including those inside f-strings (`f\"... foo({x}) ...\"`)\n"
                "- Remove the deprecated `def foo(...)` from utils/old_api.py (keep `def bar`)\n"
                "- All tests in test_services.py must still pass\n"
                "- Do NOT modify test_services.py or any test_*.py file\n"
                "- Behaviour must be preserved — bar(x) returns the same value foo(x) used to return\n\n"
                "## Output format\n"
                "For each file you change, emit one fenced block with EXACT path + COMPLETE content:\n\n"
                "```edit <relative_path>\n"
                "<full new file content>\n"
                "```\n"
            ),
            expected_action_types=["edit_file"],
        )]

    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        results: List[VerifierResult] = []
        for v in (NoFooCallsVerifier(), PytestPassVerifier(), TestFilesUnchangedVerifier()):
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

    def _collect_baseline(self, workspace_dir: str) -> str:
        try:
            proc = subprocess.run(
                ["grep", "-rn", "--include=*.py", "foo(", "."],
                cwd=workspace_dir, capture_output=True, text=True, timeout=10,
            )
            return (proc.stdout or "(no matches)").strip()
        except Exception as e:
            return f"(grep failed: {e})"

    def _render_file_blocks(self, workspace_dir: str, rel_paths: List[str]) -> str:
        chunks: List[str] = []
        for rel in rel_paths:
            full = os.path.join(workspace_dir, rel)
            try:
                body = open(full, "r", encoding="utf-8").read()
            except Exception as e:
                body = f"(could not read: {e})"
            chunks.append(f"### {rel}\n```python\n{body}```")
        return "\n\n".join(chunks)

    def _safe_write(self, workspace_dir: str, rel_path: str, content: str) -> None:
        full = os.path.abspath(os.path.join(workspace_dir, rel_path))
        ws_abs = os.path.abspath(workspace_dir)
        if not full.startswith(ws_abs + os.sep) and full != ws_abs:
            raise ValueError(f"Refusing to write outside workspace: {rel_path}")
        basename = os.path.basename(full)
        if (basename.startswith("test_") and basename.endswith(".py")) or basename == "conftest.py":
            return
        if any(d in full for d in (".env", ".git", "secrets")):
            return
        # Allow create-new: agent may add a new module if it wants to factor;
        # but most reasonable solutions just edit existing files.
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)


def materialize_workspace(workspace_dir: str) -> str:
    os.makedirs(workspace_dir, exist_ok=True)
    for rel, content in BASELINE_FILES.items():
        full = os.path.join(workspace_dir, rel)
        os.makedirs(os.path.dirname(full) or workspace_dir, exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
    return TASK_DESCRIPTION


ScenarioRegistry.register(CrossFileRefactorScenario())
