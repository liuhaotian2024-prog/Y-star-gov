"""
ystar.czl.scenarios.test_gen_for_existing — v3.4 scenario #3

Indie task: write a complete pytest suite for an existing data_pipeline.py
module. Coverage ≥ 80%, includes edge cases and exception paths.

v3.4 changes vs v3.3:
  - T1: ADD-only protocol for small tier. plan() reads contract["model_tier"]
    and for small tier emits an `add_tests` prompt format (model emits new
    test functions only; apply_action merges into existing file by function
    name). Large/medium tier keeps the v3.3 `edit` (full-rewrite) format.
  - T2: English hints + raw traceback in every verifier's message_natural.
    No more Chinese paragraphs. Hint is a 1-2 sentence English line about
    what to fix; raw traceback / missing-line listing is preserved verbatim.
  - T3: Coverage80Verifier inherits simplified AdaptiveThresholdVerifier
    (no floor / no effective_threshold — real target = 0.80 is the gate;
    baseline iter-1 informational only).
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

from ystar.czl.scenarios.base import Scenario, PlanStep, ScenarioRegistry
from ystar.czl.verifiers.base import (
    Verifier, VerifierResult, AdaptiveThresholdVerifier, tier_compatible,
)
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


# === inline verifiers (v3.4: English hints in message_natural) ==============

class PytestPassVerifier(Verifier):
    name = "pytest"
    applies_to_tasks = ["test_generation_for_existing_code", "bug_fix_with_implicit_dependency"]
    min_model_capacity = "small"
    feedback_complexity = "low"

    def is_applicable(self, workspace_dir: str, contract: Optional[Dict[str, Any]] = None) -> bool:
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
                return VerifierResult(
                    verifier_name=self.name, passed=True,
                    message="pytest: all pass",
                    message_natural="pytest: all tests pass.\nHint: nothing to fix here.",
                    elapsed_seconds=time.time() - t0,
                )
            stdout = proc.stdout or ""
            # Extract the pytest --tb=short traceback verbatim (small models need raw signal)
            # and the FAILED summary lines.
            tb_match = re.search(r"={5,}\s*FAILURES\s*={5,}(.*?)(?:={5,}|short test summary)",
                                 stdout, re.DOTALL)
            traceback_block = tb_match.group(1).strip() if tb_match else stdout[-1500:]
            # Identify the dominant assertion-error pattern for the hint
            assertion_lines = [ln for ln in stdout.splitlines() if ln.lstrip().startswith("E   ")][:3]
            failure_pattern = ""
            if assertion_lines:
                if any("AssertionError" in ln and "==" in ln for ln in assertion_lines):
                    failure_pattern = " (assertion expects a different value than what the function returns)"
                elif any("TypeError" in ln for ln in assertion_lines):
                    failure_pattern = " (function called with wrong type or arity)"
                elif any("KeyError" in ln or "AttributeError" in ln for ln in assertion_lines):
                    failure_pattern = " (test references a key/attribute that doesn't exist)"
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="pytest: failures",
                message_natural=(
                    f"pytest: failures.\n\nTraceback:\n{traceback_block}\n\n"
                    f"Hint: Read the AssertionError carefully — the LEFT side is what your test "
                    f"computed, the RIGHT side is what you asserted equals it{failure_pattern}. "
                    f"Fix either the test's expected value OR the test setup so they agree."
                ),
                details={"stdout": stdout[-1500:]},
                elapsed_seconds=time.time() - t0,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="pytest timed out",
                message_natural="pytest: timed out.\nHint: a test has an infinite loop or unbounded input.",
                elapsed_seconds=time.time() - t0,
            )


class Coverage80Verifier(AdaptiveThresholdVerifier):
    """v3.4 T3: simplified — real target 0.80 is the only pass/fail; baseline
    informational only.
    """
    name = "coverage_80"
    applies_to_tasks = ["test_generation_for_existing_code"]
    min_model_capacity = "small"
    feedback_complexity = "low"

    def __init__(self, target: float = 0.80):
        AdaptiveThresholdVerifier.__init__(self, target_threshold=target)

    def is_applicable(self, workspace_dir: str, contract: Optional[Dict[str, Any]] = None) -> bool:
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
                return VerifierResult(
                    verifier_name=self.name, passed=False,
                    message="coverage report missing",
                    message_natural=(
                        "coverage_80: coverage report missing.\n"
                        "Hint: your test file is not being discovered by pytest — "
                        "check the file name starts with `test_` and contains `def test_*` functions."
                    ),
                    details={"stdout": (proc.stdout or "")[-1000:]},
                    elapsed_seconds=time.time() - t0,
                )
            cov = json.loads(open(cov_path, "r", encoding="utf-8").read())
            pct = cov.get("totals", {}).get("percent_covered", 0.0)
            missing_lines: List[Any] = []
            for fp, fdata in (cov.get("files") or {}).items():
                missing_lines.extend(fdata.get("missing_lines", [])[:12])
            passed_score, adaptive_msg = self.check_score(pct / 100.0)
            details = {
                "percent_covered": pct,
                "missing_lines": missing_lines[:20],
                "target_pct": self.target * 100.0,
                "baseline_iter1_pct": (self._calibration_score * 100.0) if self._calibration_score is not None else None,
                "call_count": self._call_count,
            }
            if passed_score:
                return VerifierResult(
                    verifier_name=self.name, passed=True,
                    message=f"coverage: {pct:.1f}% — {adaptive_msg}",
                    message_natural=(
                        f"coverage_80: {pct:.0f}% line coverage >= target {self.target*100:.0f}%.\n"
                        f"Hint: all lines exercised."
                    ),
                    details=details, elapsed_seconds=time.time() - t0,
                )
            # Build the English hint by inspecting which line numbers are missing
            target_lines_str = ", ".join(str(ln) for ln in missing_lines[:10])
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"coverage: {pct:.1f}% — {adaptive_msg}",
                message_natural=(
                    f"coverage_80: {pct:.0f}% line coverage; target {self.target*100:.0f}% "
                    f"(gap {self.target - pct/100:.2f}).\n"
                    f"Uncovered lines in data_pipeline.py: {target_lines_str}\n"
                    f"Hint: add a test that calls the function whose body spans those lines "
                    f"(open data_pipeline.py, find which `def` contains line {missing_lines[0] if missing_lines else '?'}, "
                    f"then write a test that exercises the branch covering those lines — "
                    f"often this is a try/except path or an `if` branch that's not yet tested)."
                ),
                details=details,
                elapsed_seconds=time.time() - t0,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="coverage run timed out",
                message_natural="coverage_80: timed out.\nHint: a test has an infinite loop.",
                elapsed_seconds=time.time() - t0,
            )
        except Exception as e:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"coverage check failed: {e}",
                message_natural=f"coverage_80: error {e}.\nHint: rerun.",
                elapsed_seconds=time.time() - t0,
            )


class HasExceptionTestsVerifier(Verifier):
    name = "has_exception_tests"
    applies_to_tasks = ["test_generation_for_existing_code"]
    min_model_capacity = "small"
    feedback_complexity = "low"

    def is_applicable(self, workspace_dir: str, contract: Optional[Dict[str, Any]] = None) -> bool:
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
                try:
                    body = open(os.path.join(root, f), "r", encoding="utf-8").read()
                except Exception:
                    continue
                n += body.count("pytest.raises")
        passed = n >= 1
        if passed:
            return VerifierResult(
                verifier_name=self.name, passed=True,
                message=f"has_exception_tests: {n} `pytest.raises` found",
                message_natural=(
                    f"has_exception_tests: {n} `pytest.raises` block(s) found.\n"
                    f"Hint: exception coverage is good."
                ),
                details={"pytest_raises_count": n},
                elapsed_seconds=time.time() - t0,
            )
        return VerifierResult(
            verifier_name=self.name, passed=False,
            message="has_exception_tests: no pytest.raises found",
            message_natural=(
                "has_exception_tests: no `with pytest.raises(...):` block found.\n"
                "Hint: add a test that asserts a function raises the expected exception, e.g.:\n"
                "  with pytest.raises(ValueError):\n"
                "      normalize_email('')\n"
                "Cover at least one error path (ValidationError on bad schema, ValueError on empty email)."
            ),
            details={"pytest_raises_count": n},
            elapsed_seconds=time.time() - t0,
        )


# === ADD-only parse helpers (v3.4 T1) =======================================

def _extract_test_functions(content: str) -> Dict[str, str]:
    """Given source code that may contain test_* function definitions
    (and maybe other top-level code), return {func_name: full_source} of
    each test_* function. Uses AST so it's robust to indentation.

    Returns dict in source-order via OrderedDict semantics (Python 3.7+).
    """
    out: Dict[str, str] = {}
    try:
        tree = ast.parse(content)
    except SyntaxError:
        # Try a relaxed pass: greedy regex for `def test_*(...):` blocks
        for m in re.finditer(r"^(def test_[A-Za-z0-9_]*\([^)]*\)(?:\s*->\s*[^:]+)?:.*?)(?=\n(?:def |class |@|$))",
                              content, flags=re.DOTALL | re.MULTILINE):
            body = m.group(1).rstrip()
            name_m = re.match(r"def (test_[A-Za-z0-9_]*)", body)
            if name_m:
                out[name_m.group(1)] = body + "\n"
        return out
    # AST pass: collect FunctionDef whose name starts with test_
    lines = content.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            start = node.lineno - 1
            end = getattr(node, "end_lineno", None) or _function_end_line(node, lines)
            src = "".join(lines[start:end])
            out[node.name] = src
    return out


def _function_end_line(node: ast.FunctionDef, lines: List[str]) -> int:
    """Fallback: walk to the next top-level token to find end line."""
    return node.lineno + 50  # safe-ish default


_ADD_TESTS_RE = re.compile(
    r"```(?P<kind>add_tests|append)\s+(?P<path>[^\n]+)\n(?P<body>.*?)```",
    re.DOTALL,
)


# === scenario ================================================================

class TestGenForExistingScenario(Scenario):
    name = "test_generation_for_existing_code"
    description = "Write pytest tests for data_pipeline.py; coverage ≥ 80%; exception paths covered"
    default_max_iterations = 6

    _last_verifier_call_order: List[str] = []

    def __init__(self) -> None:
        self._cached_pytest = PytestPassVerifier()
        self._cached_coverage80 = Coverage80Verifier(target=0.80)
        self._cached_has_exc = HasExceptionTestsVerifier()
        self._cached_contract = ContractConsistencyVerifier()
        self._cached_differential = DifferentialVerifier()
        self._cached_mutation = MutationScoreVerifier(score_threshold=0.7)
        self._cached_branch = BranchCoverageVerifier(threshold=0.70)
        self._last_trial_id: Optional[str] = None
        # v3.4 T1: latest model_tier seen via verify(), so plan() (called BEFORE
        # verify() at iter 1) can fall back to medium if no tier info yet —
        # but iter 2+ uses the cached tier from prior verify().
        self._last_model_tier: str = "medium"

    def _all_cached_verifiers(self) -> List[Verifier]:
        return [self._cached_pytest, self._cached_coverage80, self._cached_has_exc,
                self._cached_contract, self._cached_differential,
                self._cached_mutation, self._cached_branch]

    def _reset_if_new_trial(self, contract: Dict[str, Any]) -> None:
        tid = (contract or {}).get("trial_id")
        if tid is not None and tid != self._last_trial_id:
            for v in self._all_cached_verifiers():
                v.reset_for_trial()
            self._last_trial_id = tid

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
            "_mutation_target_file": "data_pipeline.py",
            "_mutation_test_command": "python3.11 -m pytest -x -q --tb=no --no-header",
            "_mutation_target_wall_seconds": 10.0,
        }

    def plan(self, task_description: str, workspace_dir: str,
             contract: Optional[Dict[str, Any]] = None) -> List[PlanStep]:
        """v3.4 T1: small tier gets ADD-only prompt; large/medium get full-rewrite."""
        contract = contract or {}
        model_tier = contract.get("model_tier", self._last_model_tier)
        # cache for next call
        self._last_model_tier = model_tier
        is_small = model_tier in ("small", "tiny", "local")

        path = os.path.join(workspace_dir, "data_pipeline.py")
        body = open(path, "r", encoding="utf-8").read() if os.path.isfile(path) else "(missing)"
        # Existing test functions (so the prompt tells small model what NOT to repeat)
        existing_test_funcs: List[str] = []
        existing_tests_content = ""
        for r, _, fs in os.walk(workspace_dir):
            for f in fs:
                if f.startswith("test_") and f.endswith(".py"):
                    fp = os.path.join(r, f)
                    try:
                        c = open(fp, "r", encoding="utf-8").read()
                    except Exception:
                        continue
                    existing_tests_content += c
                    existing_test_funcs.extend(_extract_test_functions(c).keys())

        if is_small:
            existing_listing = "\n".join(f"  - {n}" for n in existing_test_funcs) or "  (none yet)"
            user_prompt = (
                f"## Task\n{task_description}\n\n"
                "## Source to test (read-only)\n"
                f"### data_pipeline.py\n```python\n{body}```\n\n"
                "## Existing test functions in test_data_pipeline.py (DO NOT rewrite these)\n"
                f"{existing_listing}\n\n"
                "## Constraints (Y*)\n"
                "- Every test must pass under `pytest -q`\n"
                "- Combined coverage of data_pipeline.py must be >= 80% (use pytest-cov)\n"
                "- At least one test must use `pytest.raises` to exercise an exception path\n"
                "- Cover edge / error paths: missing fields, wrong types, empty inputs, "
                "duplicate emails, invalid JSON, missing files\n"
                "- Do NOT modify data_pipeline.py — only ADD new tests\n\n"
                "## Output format (ADD-only — IMPORTANT)\n"
                "Emit ONE block of NEW test functions only. Existing tests in "
                "test_data_pipeline.py are preserved automatically; do not repeat them. "
                "If a function name you emit already exists, it will REPLACE the existing "
                "one (so re-emit a function to fix it). Do NOT include `print(...)`, "
                "top-level `try/except`, or `if __name__ == '__main__'` blocks — only "
                "`def test_*(...)` functions and any `pytest` fixtures.\n\n"
                "```add_tests test_data_pipeline.py\n"
                "import pytest\n"
                "from data_pipeline import (load_records, validate_record, normalize_email, "
                "clean_records, aggregate_by_domain, pipeline, ValidationError, PipelineError)\n\n"
                "def test_<descriptive_name>():\n"
                "    # your test body — assert specific values\n"
                "    ...\n"
                "```\n"
            )
        else:
            existing_files = sorted(
                os.path.relpath(os.path.join(r, f), workspace_dir)
                for r, _, fs in os.walk(workspace_dir) for f in fs
                if f.startswith("test_") and f.endswith(".py")
            )
            existing = "\n".join(f"- {p}" for p in existing_files) or "(none yet)"
            user_prompt = (
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
            )

        return [PlanStep(
            step_id="write_tests",
            user_prompt=user_prompt,
            expected_action_types=["create_file", "edit_file", "add_tests_file"],
        )]

    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        contract = contract or {}
        self._reset_if_new_trial(contract)
        model_tier = contract.get("model_tier", "medium")
        self._last_model_tier = model_tier  # cache for plan() on iter 1 next trial

        results: List[VerifierResult] = []
        call_order: List[str] = []

        inner_candidates: List[Verifier] = [
            self._cached_pytest, self._cached_coverage80, self._cached_has_exc,
            self._cached_contract, self._cached_differential,
        ]
        inner = [v for v in inner_candidates if tier_compatible(v.min_model_capacity, model_tier)]
        for v in inner:
            try:
                applicable = v.is_applicable(workspace_dir, contract)
            except TypeError:
                applicable = v.is_applicable(workspace_dir)
            if not applicable:
                continue
            r = v.run(workspace_dir, contract)
            results.append(r)
            call_order.append(v.name)

        all_inner_passed = bool(results) and all(r.passed for r in results)

        if all_inner_passed:
            final_candidates: List[Verifier] = [self._cached_mutation, self._cached_branch]
            final_gates = [v for v in final_candidates
                           if tier_compatible(v.min_model_capacity, model_tier)]
            for fg in final_gates:
                try:
                    applicable = fg.is_applicable(workspace_dir, contract)
                except TypeError:
                    applicable = fg.is_applicable(workspace_dir)
                if applicable:
                    fr = fg.run(workspace_dir, contract)
                    results.append(fr)
                    call_order.append(fg.name)

        self._last_verifier_call_order = list(call_order)
        return results

    def apply_action(self, action: Any, workspace_dir: str) -> None:
        """v3.4 T1: handle `add_tests_file` (merge by function name into existing
        file) in addition to the v3.3 `edit_file` / `create_file`.
        """
        action_type = action.get("type", "") if isinstance(action, dict) else getattr(action, "type", "")
        payload = action.payload if hasattr(action, "payload") else action

        if action_type == "add_tests_file":
            self._merge_test_functions(workspace_dir,
                                        payload.get("path", ""),
                                        payload.get("content", ""))
            return
        if action_type in ("edit_file", "create_file"):
            self._safe_write(workspace_dir, payload.get("path", ""), payload.get("content", ""))

    def _merge_test_functions(self, workspace_dir: str, rel_path: str, content: str) -> None:
        """v3.4 T1 ADD-only merge.

        Read existing file (or create blank), parse existing test functions,
        parse the new content for test_* functions, then write OUT:
          (existing imports + fixtures) + (existing tests with names not in new) + (new tests)
        Functions in `content` whose names match existing get REPLACED.
        Top-level non-test code in `content` is dropped to prevent script-style pollution.
        """
        # Path-safety
        if not rel_path:
            rel_path = "test_data_pipeline.py"
        full = os.path.abspath(os.path.join(workspace_dir, rel_path))
        ws_abs = os.path.abspath(workspace_dir)
        if not full.startswith(ws_abs + os.sep) and full != ws_abs:
            raise ValueError(f"Refusing to write outside workspace: {rel_path}")
        basename = os.path.basename(full)
        if not (basename.startswith("test_") and basename.endswith(".py")):
            return  # ADD-only only applies to test files

        existing = ""
        if os.path.isfile(full):
            existing = open(full, "r", encoding="utf-8").read()

        # Extract imports / fixtures / helpers from the new content (anything that's
        # NOT a test function definition, NOT a script-style top-level statement)
        new_imports, new_fixtures, new_tests = _split_test_block(content)
        existing_imports, existing_fixtures, existing_tests = _split_test_block(existing)

        # Merge by function name: new takes precedence
        merged_tests = dict(existing_tests)
        merged_tests.update(new_tests)

        # Merge imports (dedupe by line text)
        all_imports_lines: List[str] = []
        seen_imports = set()
        for src in (existing_imports + "\n" + new_imports).splitlines():
            stripped = src.strip()
            if stripped and stripped not in seen_imports:
                all_imports_lines.append(src.rstrip())
                seen_imports.add(stripped)

        # Merge fixtures (by name — keep first-seen unless new replaces)
        merged_fixtures = dict(existing_fixtures)
        merged_fixtures.update(new_fixtures)

        out_pieces: List[str] = []
        if all_imports_lines:
            out_pieces.append("\n".join(all_imports_lines))
            out_pieces.append("")
        for name in merged_fixtures:
            out_pieces.append(merged_fixtures[name].rstrip())
            out_pieces.append("")
        for name in merged_tests:
            out_pieces.append(merged_tests[name].rstrip())
            out_pieces.append("")

        os.makedirs(os.path.dirname(full) or workspace_dir, exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write("\n".join(out_pieces) + "\n")

    def _safe_write(self, workspace_dir: str, rel_path: str, content: str) -> None:
        full = os.path.abspath(os.path.join(workspace_dir, rel_path))
        ws_abs = os.path.abspath(workspace_dir)
        if not full.startswith(ws_abs + os.sep) and full != ws_abs:
            raise ValueError(f"Refusing to write outside workspace: {rel_path}")
        basename = os.path.basename(full)
        if not ((basename.startswith("test_") and basename.endswith(".py")) or basename == "conftest.py"):
            return
        if any(d in full for d in (".env", ".git", "secrets")):
            return
        os.makedirs(os.path.dirname(full) or workspace_dir, exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)


def _split_test_block(content: str) -> tuple:
    """Split a Python source string into (imports_block, fixtures_dict,
    tests_dict). Drops top-level statements that are NOT imports, fixtures,
    or test_* functions (e.g. stray `print()` calls, top-level `try/except`).
    """
    if not content.strip():
        return ("", {}, {})
    try:
        tree = ast.parse(content)
    except SyntaxError:
        # Fall back: try just extracting test functions via regex
        return ("", {}, _extract_test_functions(content))

    lines = content.splitlines(keepends=True)
    import_lines: List[str] = []
    fixtures: Dict[str, str] = {}
    tests: Dict[str, str] = {}

    for node in tree.body:
        start = node.lineno - 1
        end = getattr(node, "end_lineno", None) or (node.lineno + 1)
        src = "".join(lines[start:end])
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            import_lines.append(src.rstrip())
        elif isinstance(node, ast.FunctionDef):
            # check if decorated as @pytest.fixture
            is_fixture = any(
                (isinstance(d, ast.Attribute) and d.attr == "fixture") or
                (isinstance(d, ast.Name) and d.id == "fixture") or
                (isinstance(d, ast.Call) and (
                    (isinstance(d.func, ast.Attribute) and d.func.attr == "fixture") or
                    (isinstance(d.func, ast.Name) and d.func.id == "fixture")
                ))
                for d in node.decorator_list
            )
            # Decorators are part of the function source — include them
            # by extending the start back to the topmost decorator's lineno.
            if node.decorator_list:
                start = node.decorator_list[0].lineno - 1
                src = "".join(lines[start:end])
            if is_fixture:
                fixtures[node.name] = src
            elif node.name.startswith("test_"):
                tests[node.name] = src
            # else: helper function — drop (encourages model to keep tests focused)
        # else: top-level Expr / Assign / If / Try / etc → DROPPED (defends
        # against the v3.3 sanity failure where gemma wrote top-level
        # `print()` + `try/except` blocks)

    return ("\n".join(import_lines), fixtures, tests)


def materialize_workspace(workspace_dir: str) -> str:
    os.makedirs(workspace_dir, exist_ok=True)
    for rel, content in BASELINE_FILES.items():
        full = os.path.join(workspace_dir, rel)
        os.makedirs(os.path.dirname(full) or workspace_dir, exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
    return TASK_DESCRIPTION


ScenarioRegistry.register(TestGenForExistingScenario())
