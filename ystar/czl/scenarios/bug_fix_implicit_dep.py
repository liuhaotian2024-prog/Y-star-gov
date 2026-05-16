"""
ystar.czl.scenarios.bug_fix_implicit_dep — v3 scenario #4

Indie task: a failing test in test_user_service.py. The user thinks it's
a user_service bug — but the actual bug lives in session_manager.py
(logout sets the slot to None instead of deleting it; online_count then
over-reports). The agent has to trace the implicit dependency and fix
the right file.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Dict, List

from ystar.czl.scenarios.base import Scenario, PlanStep, ScenarioRegistry
from ystar.czl.verifiers.base import Verifier, VerifierResult


# === workspace fixture =======================================================

BASELINE_FILES: Dict[str, str] = {
    "session_manager.py": (
        "from typing import Optional\n"
        "\n"
        "\n"
        "class SessionManager:\n"
        "    \"\"\"Tracks active sessions: session_id -> user_id.\"\"\"\n"
        "\n"
        "    def __init__(self) -> None:\n"
        "        self._sessions: dict = {}\n"
        "\n"
        "    def login(self, session_id: str, user_id: int) -> None:\n"
        "        self._sessions[session_id] = user_id\n"
        "\n"
        "    def logout(self, session_id: str) -> bool:\n"
        "        \"\"\"Return True iff a session existed before this call.\"\"\"\n"
        "        if session_id in self._sessions:\n"
        "            # BUG: should delete; setting to None leaves a ghost slot.\n"
        "            self._sessions[session_id] = None\n"
        "            return True\n"
        "        return False\n"
        "\n"
        "    def get_user(self, session_id: str) -> Optional[int]:\n"
        "        return self._sessions.get(session_id)\n"
        "\n"
        "    def active_session_count(self) -> int:\n"
        "        return len(self._sessions)\n"
    ),
    "user_service.py": (
        "from typing import Optional\n"
        "\n"
        "from session_manager import SessionManager\n"
        "\n"
        "\n"
        "class UserService:\n"
        "    def __init__(self, session_mgr: SessionManager) -> None:\n"
        "        self.sessions = session_mgr\n"
        "\n"
        "    def login_user(self, session_id: str, user_id: int) -> None:\n"
        "        self.sessions.login(session_id, user_id)\n"
        "\n"
        "    def logout_user(self, session_id: str) -> bool:\n"
        "        return self.sessions.logout(session_id)\n"
        "\n"
        "    def current_user(self, session_id: str) -> Optional[int]:\n"
        "        return self.sessions.get_user(session_id)\n"
        "\n"
        "    def online_count(self) -> int:\n"
        "        return self.sessions.active_session_count()\n"
    ),
    "test_user_service.py": (
        "from session_manager import SessionManager\n"
        "from user_service import UserService\n"
        "\n"
        "\n"
        "def _make():\n"
        "    return UserService(SessionManager())\n"
        "\n"
        "\n"
        "def test_login_then_current_user():\n"
        "    svc = _make()\n"
        "    svc.login_user('s1', 42)\n"
        "    assert svc.current_user('s1') == 42\n"
        "\n"
        "\n"
        "def test_logout_clears_current_user():\n"
        "    svc = _make()\n"
        "    svc.login_user('s1', 42)\n"
        "    svc.logout_user('s1')\n"
        "    assert svc.current_user('s1') is None\n"
        "\n"
        "\n"
        "def test_online_count_decreases_on_logout():\n"
        "    svc = _make()\n"
        "    svc.login_user('s1', 42)\n"
        "    svc.login_user('s2', 43)\n"
        "    assert svc.online_count() == 2\n"
        "    svc.logout_user('s1')\n"
        "    assert svc.online_count() == 1\n"
        "\n"
        "\n"
        "def test_logout_returns_true_first_time_false_after():\n"
        "    svc = _make()\n"
        "    svc.login_user('s1', 42)\n"
        "    assert svc.logout_user('s1') is True\n"
        "    assert svc.logout_user('s1') is False\n"
    ),
}


TASK_DESCRIPTION = (
    "test_user_service.py 在挂。修 user_service.py 让测试通过。"
    "这个 bug 跟 session 状态有关，可能影响多个测试。"
)


# === verifiers ===============================================================

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
            return VerifierResult(verifier_name=self.name, passed=False,
                                  message="pytest: failures",
                                  details={"stdout": (proc.stdout or "")[-1500:]},
                                  elapsed_seconds=time.time() - t0)
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
                              message="test files unchanged",
                              elapsed_seconds=time.time() - t0)


# === scenario ================================================================

class BugFixImplicitDepScenario(Scenario):
    name = "bug_fix_with_implicit_dependency"
    description = "A failing test in test_user_service.py — bug lives in session_manager, not user_service"
    default_max_iterations = 8

    def y_star_invariants(self) -> Dict[str, Any]:
        return {
            "invariant": [
                "all_pytest_tests_pass == True",
                "test_files_unchanged == True",
            ],
            "only_paths": ["./"],
            "deny": [".env", ".git/", "secrets"],
        }

    def plan(self, task_description: str, workspace_dir: str) -> List[PlanStep]:
        source_files = self._list_workspace_source_files(workspace_dir)
        file_blocks = self._render_file_blocks(workspace_dir, source_files)
        failures = self._collect_test_failures(workspace_dir)
        files_listing = "\n".join(f"- {p}" for p in source_files)
        return [PlanStep(
            step_id="fix_implicit_dep_bug",
            user_prompt=(
                f"## Task\n{task_description}\n\n"
                "## Editable source files (tests are READ-ONLY)\n"
                f"{files_listing}\n\n"
                "## Current source content\n"
                f"{file_blocks}\n\n"
                "## Current pytest failures (these are the spec)\n"
                f"```\n{failures}\n```\n\n"
                "## Constraints (Y*)\n"
                "- All currently-failing tests must pass after your changes\n"
                "- All currently-passing tests must STILL pass\n"
                "- Do NOT modify test_user_service.py (or any test_*.py)\n"
                "- The task hint mentions session state — read both source files; the bug may not be in the file the test names\n"
                "- Do NOT add `pytest.skip` / `pytest.xfail` / `except: pass` to make tests \"pass\"\n\n"
                "## Output format\n"
                "```edit <relative_path>\n"
                "<full new file content>\n"
                "```\n"
            ),
            expected_action_types=["edit_file"],
        )]

    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        results: List[VerifierResult] = []
        for v in (PytestPassVerifier(), TestFilesUnchangedVerifier()):
            if v.is_applicable(workspace_dir):
                results.append(v.run(workspace_dir, contract))
        return results

    def apply_action(self, action: Dict[str, Any], workspace_dir: str) -> None:
        action_type = action.get("type", "") if isinstance(action, dict) else getattr(action, "type", "")
        payload = action.payload if hasattr(action, "payload") else action
        if action_type in ("edit_file", "create_file"):
            self._safe_write(workspace_dir, payload.get("path", ""), payload.get("content", ""))

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

    def _collect_test_failures(self, workspace_dir: str) -> str:
        try:
            proc = subprocess.run(
                ["pytest", "-q", "--tb=short", "--no-header"],
                cwd=workspace_dir, capture_output=True, text=True, timeout=60,
            )
            tail = (proc.stdout or "").splitlines()
            return "\n".join(tail[-50:]) or "(no output)"
        except Exception as e:
            return f"(pytest failed to run: {e})"

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
        if not os.path.exists(full):  # do not let agent invent new sources to bypass the bug
            return
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


ScenarioRegistry.register(BugFixImplicitDepScenario())
