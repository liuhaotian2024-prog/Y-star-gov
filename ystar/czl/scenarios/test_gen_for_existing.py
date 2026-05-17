"""
ystar.czl.scenarios.test_gen_for_existing — v3 scenario #3

Indie task: write a complete pytest suite for an existing data_pipeline.py
module. Coverage ≥ 80%, includes edge cases and exception paths. The agent
may only create test_*.py files; the source data_pipeline.py is read-only.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import time
from typing import Any, Dict, List

from ystar.czl.scenarios.base import Scenario, PlanStep, ScenarioRegistry
from ystar.czl.verifiers.base import Verifier, VerifierResult
from ystar.czl.verifiers.contract_verifier import ContractConsistencyVerifier
from ystar.czl.verifiers.differential_verifier import DifferentialVerifier
from ystar.czl.verifiers.mutation_score_verifier import MutationScoreVerifier
from ystar.czl.verifiers.branch_coverage_verifier import BranchCoverageVerifier


# === workspace fixture =======================================================

BASELINE_FILES: Dict[str, str] = {
    "data_pipeline.py": (
        "import json\n"
        "\n"
        "\n"
        "class PipelineError(Exception):\n"
        "    pass\n"
        "\n"
        "\n"
        "class ValidationError(PipelineError):\n"
        "    pass\n"
        "\n"
        "\n"
        "def load_records(path):\n"
        "    \"\"\"Load JSON list-of-records from path. Raises FileNotFoundError, ValueError on bad JSON / non-list.\"\"\"\n"
        "    with open(path, 'r', encoding='utf-8') as f:\n"
        "        data = json.load(f)\n"
        "    if not isinstance(data, list):\n"
        "        raise ValueError(f'expected list, got {type(data).__name__}')\n"
        "    return data\n"
        "\n"
        "\n"
        "def validate_record(rec, schema):\n"
        "    \"\"\"schema = {field_name: type}; raises ValidationError if missing or wrong type.\"\"\"\n"
        "    for k, t in schema.items():\n"
        "        if k not in rec:\n"
        "            raise ValidationError(f'missing field: {k}')\n"
        "        if not isinstance(rec[k], t):\n"
        "            raise ValidationError(f'wrong type for {k}: got {type(rec[k]).__name__}, expected {t.__name__}')\n"
        "\n"
        "\n"
        "def normalize_email(email):\n"
        "    \"\"\"Lowercase + strip. Empty string raises ValueError.\"\"\"\n"
        "    s = email.strip().lower()\n"
        "    if not s:\n"
        "        raise ValueError('empty email')\n"
        "    return s\n"
        "\n"
        "\n"
        "def clean_records(records, schema):\n"
        "    \"\"\"Validate, normalize email, drop duplicates by email. Invalid records are skipped silently.\"\"\"\n"
        "    seen = set()\n"
        "    out = []\n"
        "    for rec in records:\n"
        "        try:\n"
        "            validate_record(rec, schema)\n"
        "        except ValidationError:\n"
        "            continue\n"
        "        try:\n"
        "            email = normalize_email(rec['email'])\n"
        "        except ValueError:\n"
        "            continue\n"
        "        if email in seen:\n"
        "            continue\n"
        "        seen.add(email)\n"
        "        rec_copy = dict(rec)\n"
        "        rec_copy['email'] = email\n"
        "        out.append(rec_copy)\n"
        "    return out\n"
        "\n"
        "\n"
        "def aggregate_by_domain(records):\n"
        "    \"\"\"Count records per email domain. Records must have 'email' key.\"\"\"\n"
        "    counts = {}\n"
        "    for rec in records:\n"
        "        email = rec['email']\n"
        "        domain = email.split('@', 1)[1] if '@' in email else 'unknown'\n"
        "        counts[domain] = counts.get(domain, 0) + 1\n"
        "    return counts\n"
        "\n"
        "\n"
        "def pipeline(path, schema):\n"
        "    \"\"\"End-to-end: load, clean, aggregate. Returns domain counts.\"\"\"\n"
        "    records = load_records(path)\n"
        "    cleaned = clean_records(records, schema)\n"
        "    return aggregate_by_domain(cleaned)\n"
    ),
}


TASK_DESCRIPTION = (
    "给 data_pipeline.py 写完整 pytest 测试套件。"
    "覆盖率 ≥ 80%。要包括 edge case 和异常路径。"
)


# === verifiers ===============================================================

class PytestPassVerifier(Verifier):
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


class Coverage80Verifier(Verifier):
    name = "coverage_80"

    def is_applicable(self, workspace_dir: str) -> bool:
        return os.path.isfile(os.path.join(workspace_dir, "data_pipeline.py"))

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        try:
            proc = subprocess.run(
                [
                    "pytest", "-q", "--tb=no", "--no-header",
                    "--cov=data_pipeline", "--cov-report=json:coverage.json",
                ],
                cwd=workspace_dir, capture_output=True, text=True, timeout=180,
            )
            cov_path = os.path.join(workspace_dir, "coverage.json")
            if not os.path.isfile(cov_path):
                return VerifierResult(verifier_name=self.name, passed=False,
                                      message="coverage report missing",
                                      details={"stdout": (proc.stdout or "")[-1000:]},
                                      elapsed_seconds=time.time() - t0)
            cov = json.loads(open(cov_path, "r", encoding="utf-8").read())
            pct = cov.get("totals", {}).get("percent_covered", 0.0)
            passed = pct >= 80.0
            return VerifierResult(
                verifier_name=self.name, passed=passed,
                message=f"coverage: {pct:.1f}% (need ≥80%)",
                details={"percent_covered": pct},
                elapsed_seconds=time.time() - t0,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(verifier_name=self.name, passed=False,
                                  message="coverage run timed out", elapsed_seconds=time.time() - t0)
        except Exception as e:
            return VerifierResult(verifier_name=self.name, passed=False,
                                  message=f"coverage check failed: {e}", elapsed_seconds=time.time() - t0)


class HasExceptionTestsVerifier(Verifier):
    """At least one test uses pytest.raises (or with-pytest.raises ctx)."""
    name = "has_exception_tests"

    def is_applicable(self, workspace_dir: str) -> bool:
        return True

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        n = 0
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
                n += body.count("pytest.raises")
        passed = n >= 1
        return VerifierResult(
            verifier_name=self.name, passed=passed,
            message=("≥1 pytest.raises found" if passed else "no pytest.raises found"),
            details={"pytest_raises_count": n},
            elapsed_seconds=time.time() - t0,
        )


# === scenario ================================================================

class TestGenForExistingScenario(Scenario):
    name = "test_generation_for_existing_code"
    description = "Write pytest tests for data_pipeline.py; coverage ≥ 80%; exception paths covered"
    default_max_iterations = 6

    # Captured per verify() call so the bench harness can inspect that
    # mutation_score only fires after inner verifiers all pass (Phase-4
    # checkpoint 4). Reset at the start of every verify().
    _last_verifier_call_order: List[str] = []

    def y_star_invariants(self) -> Dict[str, Any]:
        return {
            "invariant": [
                "all_pytest_tests_pass == True",
                "coverage_pct >= 80",
                "uses_pytest_raises == True",
                "mutation_score >= 0.7",
            ],
            "only_paths": ["./"],
            "deny": [".env", ".git/", "secrets"],
            # Phase-4 mutation-score gate metadata. _mutation_unconditional
            # intentionally omitted (defaults to False); production uses
            # selective git-diff to gate activation (which counts test-file
            # writes too, since model produces tests not source here).
            "_mutation_target_file": "data_pipeline.py",
            "_mutation_test_command": "python3.11 -m pytest -x -q --tb=no --no-header",
            "_mutation_target_wall_seconds": 10.0,
        }

    def plan(self, task_description: str, workspace_dir: str) -> List[PlanStep]:
        path = os.path.join(workspace_dir, "data_pipeline.py")
        body = open(path, "r", encoding="utf-8").read() if os.path.isfile(path) else "(missing)"
        existing_tests = sorted(
            os.path.relpath(os.path.join(r, f), workspace_dir)
            for r, _, fs in os.walk(workspace_dir) for f in fs
            if f.startswith("test_") and f.endswith(".py")
        )
        existing = "\n".join(f"- {p}" for p in existing_tests) or "(none yet)"
        return [PlanStep(
            step_id="write_tests",
            user_prompt=(
                f"## Task\n{task_description}\n\n"
                "## Source to test (read-only)\n"
                f"### data_pipeline.py\n```python\n{body}```\n\n"
                "## Existing test files\n"
                f"{existing}\n\n"
                "## Constraints (Y*)\n"
                "- Every test must pass under `pytest -q`\n"
                "- Combined coverage of data_pipeline.py must be ≥ 80% (use pytest-cov)\n"
                "- At least one test must use `pytest.raises` to exercise an exception path\n"
                "- Cover both happy and edge / error paths: missing fields, wrong types, empty inputs, duplicate emails, invalid JSON, missing files\n"
                "- Do NOT modify data_pipeline.py — only create or extend test_*.py files\n\n"
                "## Output format\n"
                "```edit test_data_pipeline.py\n"
                "<full new test file content>\n"
                "```\n"
                "(You can use pytest's tmp_path fixture for the file-loading tests.)\n"
            ),
            expected_action_types=["create_file", "edit_file"],
        )]

    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        """v3.2 verifier chain:

            pytest_pass -> coverage80 -> has_exception_tests
            -> contract_consistency -> differential   (the inner verifiers)
            -> [if all inner passed]  mutation_score + branch_coverage
                                       (parallel final gates)

        v3.1 → v3.2 change: branch_coverage is added as a SECOND parallel
        final gate alongside mutation_score. Both fire in the same iter
        when inner verifiers pass; either failure returns passed=False so
        CZL iterates with combined feedback. They are NOT serialised — at
        most one extra iter per failure, no cascade. This is the v3.2
        defense against the v3.1 sample where test_coverage_pct=100 but
        mutation_score=0.93 caused weak-test convergence on Sonnet's
        judgment band.
        """
        results: List[VerifierResult] = []
        call_order: List[str] = []

        inner = [
            PytestPassVerifier(),
            Coverage80Verifier(),
            HasExceptionTestsVerifier(),
            ContractConsistencyVerifier(),
            DifferentialVerifier(),
        ]
        for v in inner:
            if not v.is_applicable(workspace_dir):
                continue
            r = v.run(workspace_dir, contract)
            results.append(r)
            call_order.append(v.name)

        all_inner_passed = bool(results) and all(r.passed for r in results)

        if all_inner_passed:
            target_wall = float((contract or {}).get("_mutation_target_wall_seconds") or 10.0)
            final_gates = [
                MutationScoreVerifier(target_wall_seconds=target_wall, score_threshold=0.7),
                BranchCoverageVerifier(threshold=0.70),
            ]
            for fg in final_gates:
                applicable = (
                    fg.is_applicable(workspace_dir, contract)
                    if fg.name == "mutation_score"
                    else fg.is_applicable(workspace_dir, contract)
                )
                if applicable:
                    fr = fg.run(workspace_dir, contract)
                    results.append(fr)
                    call_order.append(fg.name)

        self._last_verifier_call_order = list(call_order)
        return results

    def apply_action(self, action: Dict[str, Any], workspace_dir: str) -> None:
        action_type = action.get("type", "") if isinstance(action, dict) else getattr(action, "type", "")
        payload = action.payload if hasattr(action, "payload") else action
        if action_type in ("edit_file", "create_file"):
            self._safe_write(workspace_dir, payload.get("path", ""), payload.get("content", ""))

    def _safe_write(self, workspace_dir: str, rel_path: str, content: str) -> None:
        full = os.path.abspath(os.path.join(workspace_dir, rel_path))
        ws_abs = os.path.abspath(workspace_dir)
        if not full.startswith(ws_abs + os.sep) and full != ws_abs:
            raise ValueError(f"Refusing to write outside workspace: {rel_path}")
        basename = os.path.basename(full)
        # Scenario inverts the usual rule: SOURCE is read-only, test_*.py / conftest are writable
        if not ((basename.startswith("test_") and basename.endswith(".py")) or basename == "conftest.py"):
            return
        if any(d in full for d in (".env", ".git", "secrets")):
            return
        os.makedirs(os.path.dirname(full) or workspace_dir, exist_ok=True)
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


ScenarioRegistry.register(TestGenForExistingScenario())
