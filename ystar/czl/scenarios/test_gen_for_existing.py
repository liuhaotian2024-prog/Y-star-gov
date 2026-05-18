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
            # v3.6: switch to `-v` so per-test outcomes are parseable for
            # TransitionTracker (`test_path::test_name STATUS`). `-q` and
            # `-v` are opposite verbosity; keep --tb=short for the short
            # traceback format.
            proc = subprocess.run(
                ["pytest", "-v", "--tb=short", "--no-header", "--color=no"],
                cwd=workspace_dir, capture_output=True, text=True, timeout=120,
            )
            stdout = proc.stdout or ""
            # v3.6: parse per-test outcomes so TransitionTracker can diff.
            from ystar.czl.reflection.transitions import parse_pytest_v_outcomes
            per_test_status = parse_pytest_v_outcomes(stdout)
            if proc.returncode == 0:
                return VerifierResult(
                    verifier_name=self.name, passed=True,
                    message=f"pytest: {sum(per_test_status.values())}/{len(per_test_status)} pass",
                    reason="all tests pass",
                    instruction="",
                    reference="pytest verifier",
                    details={"stdout": stdout[-3000:], "per_test_status": per_test_status},
                    elapsed_seconds=time.time() - t0,
                )
            # Parse failures with the v3.5 cluster module (reuse, don't reinvent)
            from ystar.czl.reflection.cluster import parse_pytest_failures
            failures = parse_pytest_failures(stdout)
            # Group by error type to surface the dominant family
            err_types: Dict[str, int] = {}
            for f in failures:
                et = f.get("error_type") or "Unknown"
                err_types[et] = err_types.get(et, 0) + 1
            # Build a single-line reason summarising the failure landscape
            reason_parts: List[str] = [f"{len(failures)} tests FAILED."]
            if failures:
                first = failures[0]
                reason_parts.append(
                    f"First: `{first['test_name']}` bottom-frame at "
                    f"{first['file']}:{first['lineno']} in `{first['function_name']}` — "
                    f"{first.get('error_type','?')}: {first.get('error_msg','')[:120]}"
                )
            if len(err_types) >= 1:
                top_err = max(err_types, key=lambda k: err_types[k])
                reason_parts.append(f"Dominant error type: {top_err} ({err_types[top_err]}/{len(failures)}).")
            reason = " ".join(reason_parts)

            # Build the 3-direction instruction. Templates by dominant error type.
            instruction = _pytest_instruction_for_error_type(
                err_types, failures
            )

            ref = "pytest verifier; rule: tests must run without raising and assertions must match"
            example = _pytest_example_for_error_type(err_types, failures)

            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"pytest: {len(failures)} failures (dominant {max(err_types, key=lambda k: err_types[k]) if err_types else '?'})",
                reason=reason,
                instruction=instruction,
                reference=ref,
                example=example,
                details={
                    "stdout": stdout[-5000:],
                    "failures": failures,
                    "per_test_status": per_test_status,   # v3.6: TransitionTracker uses this
                },
                elapsed_seconds=time.time() - t0,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="pytest timed out",
                reason="pytest run exceeded 120s — likely an infinite loop or unbounded input in a test",
                instruction=(
                    "Three possible directions:\n"
                    "  (A) Find the test that hangs (run pytest -x to stop at first failure) and narrow its input.\n"
                    "  (B) Add a smaller boundary input case before the large case.\n"
                    "  (C) If the test calls a recursive function, check the base case is hit."
                ),
                reference="pytest --timeout",
                elapsed_seconds=time.time() - t0,
            )


def _pytest_instruction_for_error_type(err_types: Dict[str, int],
                                        failures: List[Dict[str, Any]]) -> str:
    """v3.5 T2: build a WHY+3-DIRECTION instruction for the pytest verifier.

    Template by dominant error type. Mentions the bottom-frame file:lineno
    when failures share a frame (this is the cluster hint INLINE in
    instruction; the cluster META block separately surfaces it cross-
    failure).
    """
    if not failures:
        return ""
    top_err = max(err_types, key=lambda k: err_types[k])
    # Bottom-frame the model should look at first (most-common shared frame)
    frame_counts: Dict[tuple, int] = {}
    for f in failures:
        key = (f["file"], f["lineno"], f["function_name"])
        frame_counts[key] = frame_counts.get(key, 0) + 1
    shared = max(frame_counts, key=lambda k: frame_counts[k])
    shared_count = frame_counts[shared]
    shared_ref = f"{shared[0]}:{shared[1]} in `{shared[2]}`"

    if top_err == "TypeError":
        if shared_count >= 2:
            return (
                f"Three possible directions:\n"
                f"  (A) Fix the SHARED bottom-frame at {shared_ref} — change the "
                f"function/fixture so it handles the input types its callers pass "
                f"(if it's a fixture writing to a file, json.dumps the content first). "
                f"PREFERRED (single fix point closes {shared_count} failures).\n"
                f"  (B) Fix every call site to convert the input before passing.\n"
                f"  (C) Verify the function/fixture is meant to accept these types — "
                f"maybe the test setup is wrong."
            )
        return (
            f"Three possible directions:\n"
            f"  (A) Fix the type at the source: the function being called expects a "
            f"different type than what your test passes.\n"
            f"  (B) Fix the call site: convert your test data before passing it.\n"
            f"  (C) Verify the function signature: maybe you're calling the wrong "
            f"function with the same name."
        )
    if top_err == "AssertionError":
        return (
            f"Three possible directions:\n"
            f"  (A) The function returns the right value but your test's EXPECTED "
            f"value is wrong — recompute by hand what the function should produce "
            f"and fix the assert RIGHT-hand side.\n"
            f"  (B) The function is buggy — but you cannot modify it (source is "
            f"read-only). So this is unlikely; check (A) first.\n"
            f"  (C) The test setup (fixture or input) produces something different "
            f"than what you intended. Inspect the actual `result` vs the asserted "
            f"value: the AssertionError shows both sides."
        )
    if top_err in ("KeyError", "AttributeError"):
        return (
            f"Three possible directions:\n"
            f"  (A) The test references a key/attribute the function never sets. "
            f"Read the function source carefully — what fields DOES it return?\n"
            f"  (B) The test's input fixture is missing a required field.\n"
            f"  (C) The function raises this error intentionally and the test "
            f"should use `with pytest.raises({top_err}):` instead."
        )
    if top_err == "ValidationError":
        return (
            f"Three possible directions:\n"
            f"  (A) The test input doesn't match the expected schema — fix the input "
            f"to satisfy the schema.\n"
            f"  (B) The test is exercising an error path and should wrap in "
            f"`with pytest.raises(ValidationError):`.\n"
            f"  (C) Check the schema definition is what you intended."
        )
    # Generic fallback
    return (
        f"Three possible directions:\n"
        f"  (A) Look at {shared_ref} — this is where {shared_count} of {len(failures)} "
        f"failures point. Fix the issue at that single location.\n"
        f"  (B) If failures don't share a root, fix each test individually based on "
        f"its specific error message.\n"
        f"  (C) Check whether the test's expected behaviour matches what the source "
        f"function actually does — maybe the test is wrong, not the function."
    )


def _pytest_example_for_error_type(err_types: Dict[str, int],
                                     failures: List[Dict[str, Any]]) -> str:
    if not failures:
        return ""
    top_err = max(err_types, key=lambda k: err_types[k])
    if top_err == "TypeError" and "write() argument must be str" in (failures[0].get("error_msg") or ""):
        return (
            "Example fix for the fixture (direction A):\n"
            "```python\n"
            "import json\n"
            "@pytest.fixture\n"
            "def temp_json_file(tmp_path):\n"
            "    def _create_file(content):\n"
            "        path = tmp_path / 'test_data.json'\n"
            "        with open(path, 'w', encoding='utf-8') as f:\n"
            "            f.write(json.dumps(content))   # ← key change: serialise to JSON string\n"
            "        return str(path)\n"
            "    return _create_file\n"
            "```"
        )
    if top_err == "AssertionError":
        return (
            "Example fix (direction A):\n"
            "```python\n"
            "# Compute the EXPECTED value yourself, e.g. for clean_records:\n"
            "result = clean_records(records, schema)\n"
            "assert result == [{'name': 'Alice', 'email': 'alice@example.com'}]  # what clean_records actually returns\n"
            "```"
        )
    return ""


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
                    reason=f"line coverage {pct:.0f}% >= target {self.target*100:.0f}%",
                    instruction="",
                    reference="coverage.py --cov",
                    details=details, elapsed_seconds=time.time() - t0,
                )
            target_lines_str = ", ".join(str(ln) for ln in missing_lines[:10])
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"coverage: {pct:.1f}% — {adaptive_msg}",
                reason=(
                    f"line coverage is {pct:.0f}%, target is {self.target*100:.0f}% "
                    f"(gap {(self.target - pct/100)*100:.0f}pp). "
                    f"Uncovered lines in data_pipeline.py: {target_lines_str}."
                ),
                instruction=(
                    "Three possible directions:\n"
                    f"  (A) Add a new test that exercises the function containing the "
                    f"FIRST uncovered line ({missing_lines[0] if missing_lines else '?'}) — "
                    f"often these are try/except or `if` paths. PREFERRED for the first missing line.\n"
                    f"  (B) Extend an existing test to also call that path (e.g. pass an "
                    f"input that triggers the error branch).\n"
                    f"  (C) If a line is truly unreachable (dead code in source), note it — "
                    f"but you cannot modify data_pipeline.py."
                ),
                reference="coverage.py --cov data_pipeline; missing_lines from coverage json",
                example="",
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
                reason=f"{n} `pytest.raises` block(s) found",
                reference="exception path coverage rule",
                details={"pytest_raises_count": n},
                elapsed_seconds=time.time() - t0,
            )
        return VerifierResult(
            verifier_name=self.name, passed=False,
            message="has_exception_tests: no pytest.raises found",
            reason="no `with pytest.raises(...):` block in any test file",
            instruction=(
                "Three possible directions:\n"
                "  (A) Add a test for normalize_email('') — it raises ValueError. "
                "PREFERRED (smallest unit, single function).\n"
                "  (B) Add a test for validate_record with a missing field or wrong type — "
                "it raises ValidationError.\n"
                "  (C) Add a test for load_records with a non-list JSON or non-existent file — "
                "it raises ValueError or FileNotFoundError."
            ),
            reference="exception path coverage rule",
            example=(
                "Example (direction A):\n"
                "```python\n"
                "def test_normalize_email_empty_raises():\n"
                "    with pytest.raises(ValueError):\n"
                "        normalize_email('')\n"
                "```"
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

    def consume_rejections(self) -> List[Dict[str, str]]:
        """Return + clear the rejection log. Called by loop.py per iter."""
        out = list(self._rejection_log)
        self._rejection_log = []
        return out

    def __init__(self) -> None:
        # v5.0.2: per-instance rejection log (NOT class-level — avoid
        # mutable-default sharing). Any silent return from _safe_write
        # or _merge_test_functions appends here. The loop drains it
        # per iter and surfaces entries in the next-iter feedback.
        self._rejection_log: List[Dict[str, str]] = []
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
        """v3.4 T1: small tier gets ADD-only prompt; large/medium get full-rewrite.
        v4.0 T5: prepend environment inventory + probe tool description.
        """
        contract = contract or {}
        model_tier = contract.get("model_tier", self._last_model_tier)
        # cache for next call
        self._last_model_tier = model_tier
        is_small = model_tier in ("small", "tiny", "local")

        # v4.0 T5: environment inventory section at the very top.
        from ystar.czl.inventory import WorkspaceInventory
        from ystar.czl.scenarios.base import render_environment_inventory
        _inv = WorkspaceInventory.scan(workspace_dir)
        inventory_section = render_environment_inventory(_inv)

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

        # v4.0 T5: prepend inventory + probe tool description to the user_prompt
        return [PlanStep(
            step_id="write_tests",
            user_prompt=inventory_section + "\n\n" + user_prompt,
            expected_action_types=["create_file", "edit_file", "add_tests_file", "probe_command"],
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

    def apply_action(self, action: Any, workspace_dir: str,
                     contract: Optional[Dict[str, Any]] = None) -> None:
        """v3.4 T1: handle `add_tests_file` + v3.3 `edit_file` / `create_file`.

        v5.0.1+ design correction:
          v5.0 added a hard-reject path that SILENTLY discarded writes
          outside focus_constraint.allowed_files. Combined with v3.7
          dominance rollback, that locked gemma in place (48 iters at
          residual=1.5, passing=36, zero improvement). v5.0.1 / v5.0.2
          delete the hard-reject. focus_constraint now flows ONLY through
          the prompt as a SUGGESTION (see loop.py _render_focus_suggestion).
          The model is free to ignore it.

          INVARIANT (do not regress in future v5.x): apply_action must
          never silently discard model output. Any rejection MUST be
          logged to self._rejection_log so loop.py can surface it in
          next-iter feedback. This block enforces that contract.
        """
        action_type = action.get("type", "") if isinstance(action, dict) else getattr(action, "type", "")
        payload = action.payload if hasattr(action, "payload") else action
        rel_path = payload.get("path", "")
        if action_type == "add_tests_file":
            self._merge_test_functions(workspace_dir, rel_path, payload.get("content", ""))
            return
        # v5.0.4: bare ```python blocks land here as "python_block" — route to
        # the scenario's default test file. This rescues gemma 4B's natural
        # markdown style without forcing the model to remember the
        # ```add_tests test_data_pipeline.py syntax.
        if action_type == "python_block":
            self._merge_test_functions(workspace_dir, "test_data_pipeline.py",
                                        payload.get("content", ""))
            return
        if action_type in ("edit_file", "create_file"):
            self._safe_write(workspace_dir, rel_path, payload.get("content", ""))

    # v5.0.1 / v5.0.2: focus_constraint hard-reject gate fully removed.
    # focus_constraint now flows ONLY through loop.py's
    # _render_focus_suggestion as a soft prompt-level pointer — never as
    # an apply-layer reject. The method that used to enforce the gate is
    # also deleted (no dead code that a future refactor could resurrect).

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
            self._rejection_log.append({
                "path": rel_path,
                "reason": "path escapes workspace_dir",
            })
            return
        basename = os.path.basename(full)
        if not (basename.startswith("test_") and basename.endswith(".py")):
            # v5.0.2: log rejection so model sees feedback instead of silent drop.
            self._rejection_log.append({
                "path": rel_path,
                "reason": f"ADD-only protocol applies only to test_*.py files. `{basename}` is not a test file — use ```add_tests test_data_pipeline.py block to add tests there.",
            })
            return

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
        """v5.0.2: any rejection is logged to self._rejection_log so loop.py
        can surface it in next-iter feedback. NO silent returns.
        """
        full = os.path.abspath(os.path.join(workspace_dir, rel_path))
        ws_abs = os.path.abspath(workspace_dir)
        if not full.startswith(ws_abs + os.sep) and full != ws_abs:
            self._rejection_log.append({
                "path": rel_path,
                "reason": "path escapes workspace_dir",
            })
            return
        basename = os.path.basename(full)
        if not ((basename.startswith("test_") and basename.endswith(".py")) or basename == "conftest.py"):
            self._rejection_log.append({
                "path": rel_path,
                "reason": f"test_generation_for_existing_code scenario invariant: source files are READ-ONLY. Only test_*.py and conftest.py files are writable. `{basename}` is a source file — to fix behaviour change your TESTS, not the source.",
            })
            return
        if any(d in full for d in (".env", ".git", "secrets")):
            self._rejection_log.append({
                "path": rel_path,
                "reason": "writes to .env / .git / secrets paths are forbidden",
            })
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
