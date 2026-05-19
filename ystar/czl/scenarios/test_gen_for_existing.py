"""
ystar.czl.scenarios.test_gen_for_existing — scenario #3

Task: write a complete pytest suite for an existing data_pipeline.py
module. Coverage ≥ 80%, includes edge cases and exception paths.

The output protocol (declared via Scenario.output_protocol()) asks the
model to emit new or replacement test functions inside a single
```add_tests test_data_pipeline.py``` block; apply_action merges these
into the existing test file by function name, preserving passing tests.
Verifier messages carry both a structured `message` and a raw stdout tail
for the loop's reactive feedback formatter to render.
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
    Verifier, VerifierResult, AdaptiveThresholdVerifier,
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


# === Test-block parse helpers ===============================================

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
        # (v5.0: model-tier cache field removed with the local-model route.)

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

    def output_protocol(self) -> Dict[str, Any]:
        # IMPORTANT: instruction text must be BYTE-IDENTICAL to the v3.4
        # hardcoded narrative previously embedded in
        # ystar/czl/loop.py:_format_feedback_for_retry, so the protocol-fix
        # change is byte-equivalent to pre-fix behaviour for test_gen +
        # small tier. Any cosmetic edits to wording or punctuation must
        # be coordinated with the substrate non-regression contract.
        return {
            "file_name": "test_data_pipeline.py",
            "block_tag": "add_tests",
            "instruction": (
                "Output format: emit ONLY new or replacement test functions "
                "inside an ```add_tests test_data_pipeline.py block. Existing "
                "passing tests are preserved automatically. Do not include "
                "top-level print(), try/except, or `if __name__ == '__main__'` "
                "blocks. If a test you previously wrote needs fixing, emit a "
                "function with the SAME NAME and it will replace the old one."
            ),
            "preserves_existing": True,
        }

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
        """Prepend environment inventory + probe tool description, then a
        task / Y* / output-format block. The output protocol declares an
        `add_tests` block that the loop merges into existing tests by
        function name; passing tests are preserved unless re-emitted
        with byte-equivalent content.
        """
        contract = contract or {}

        from ystar.czl.inventory import WorkspaceInventory
        from ystar.czl.scenarios.base import render_environment_inventory
        inventory_section = render_environment_inventory(
            WorkspaceInventory.scan(workspace_dir)
        )

        path = os.path.join(workspace_dir, "data_pipeline.py")
        body = open(path, "r", encoding="utf-8").read() if os.path.isfile(path) else "(missing)"

        # Existing test functions: list them so the model knows which names
        # would replace if re-emitted.
        existing_test_funcs: List[str] = []
        for r, _, fs in os.walk(workspace_dir):
            for f in fs:
                if f.startswith("test_") and f.endswith(".py"):
                    fp = os.path.join(r, f)
                    try:
                        c = open(fp, "r", encoding="utf-8").read()
                    except Exception:
                        continue
                    _imports, _fixtures, _tests = _split_test_block(c)
                    existing_test_funcs.extend(_tests.keys())
        existing_listing = "\n".join(f"  - {n}" for n in existing_test_funcs) or "  (none yet)"

        user_prompt = (
            f"## Task\n{task_description}\n\n"
            "## Source to test (read-only)\n"
            f"### data_pipeline.py\n```python\n{body}```\n\n"
            f"## Existing test functions in test_data_pipeline.py (DO NOT rewrite these)\n"
            f"{existing_listing}\n\n"
            "## Constraints (Y*)\n"
            "- Every test must pass under `pytest -q`\n"
            "- Combined coverage of data_pipeline.py must be >= 80% (use pytest-cov)\n"
            "- At least one test must use `pytest.raises` to exercise an exception path\n"
            "- Cover edge / error paths: missing fields, wrong types, empty inputs, "
            "duplicate emails, invalid JSON, missing files\n"
            "- Do NOT modify data_pipeline.py — only add new tests\n\n"
            "## Output format\n"
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

        return [PlanStep(
            step_id="write_tests",
            user_prompt=inventory_section + "\n\n" + user_prompt,
            expected_action_types=["create_file", "edit_file", "add_tests_file", "probe_command"],
        )]

    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        contract = contract or {}
        self._reset_if_new_trial(contract)
        results: List[VerifierResult] = []
        call_order: List[str] = []

        inner_candidates: List[Verifier] = [
            self._cached_pytest, self._cached_coverage80, self._cached_has_exc,
            self._cached_contract, self._cached_differential,
        ]
        for v in inner_candidates:
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
            for fg in (self._cached_mutation, self._cached_branch):
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
            self._merge_test_functions(workspace_dir, rel_path,
                                        payload.get("content", ""), contract=contract)
            return
        # v5.0.4: bare ```python blocks land here as "python_block" — route to
        # the scenario's default test file.
        if action_type == "python_block":
            self._merge_test_functions(workspace_dir, "test_data_pipeline.py",
                                        payload.get("content", ""), contract=contract)
            return
        if action_type in ("edit_file", "create_file"):
            self._safe_write(workspace_dir, rel_path, payload.get("content", ""))

    # v5.0.1 / v5.0.2: focus_constraint hard-reject gate fully removed.
    # focus_constraint now flows ONLY through loop.py's
    # _render_focus_suggestion as a soft prompt-level pointer — never as
    # an apply-layer reject. The method that used to enforce the gate is
    # also deleted (no dead code that a future refactor could resurrect).

    def _workspace_module_names(self, workspace_dir: str) -> set:
        """v5.0.4: enumerate `.py` files in workspace as importable module
        names. Used by _merge_test_functions to filter hallucinated imports.
        """
        names = set()
        try:
            for f in os.listdir(workspace_dir):
                if f.endswith(".py") and not f.startswith("__"):
                    names.add(f[:-3])
        except OSError:
            pass
        return names

    def _workspace_function_names(self, workspace_dir: str) -> set:
        """v5.0.7: enumerate top-level FUNCTION + CLASS names from non-test
        workspace modules. Used by _merge_test_functions to reject tests
        whose bodies call undefined names (gemma hallucinations like
        `process_data`, `clean_data`, `normalize_record`).
        """
        names = set()
        try:
            for f in os.listdir(workspace_dir):
                if not f.endswith(".py") or f.startswith("test_") or f.startswith("__"):
                    continue
                try:
                    tree = ast.parse(open(os.path.join(workspace_dir, f),
                                          encoding="utf-8").read())
                except (OSError, SyntaxError):
                    continue
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        names.add(node.name)
        except OSError:
            pass
        return names

    def _merge_test_functions(self, workspace_dir: str, rel_path: str, content: str,
                                contract: Optional[Dict[str, Any]] = None) -> None:
        """Test-function merge.

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
                "reason": f"Test merge protocol applies only to test_*.py files. `{basename}` is not a test file — use ```add_tests test_data_pipeline.py block to add tests there.",
            })
            return

        existing = ""
        if os.path.isfile(full):
            existing = open(full, "r", encoding="utf-8").read()

        # Extract imports / fixtures / helpers from the new content (anything that's
        # NOT a test function definition, NOT a script-style top-level statement)
        new_imports, new_fixtures, new_tests = _split_test_block(content)
        existing_imports, existing_fixtures, existing_tests = _split_test_block(existing)

        # v5.0.7: validate new tests' bodies against workspace functions +
        # imports + builtins + pytest fixtures. Reject tests calling
        # undefined names (gemma's hallucinated `process_data` etc.).
        workspace_fns = self._workspace_function_names(workspace_dir)
        # Names imported in this iter's new content + existing imports
        imported_names = set()
        for line in (existing_imports + "\n" + new_imports).splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("from ") and " import " in s:
                imps = s.split(" import ", 1)[1]
                for piece in imps.split(","):
                    piece = piece.strip().split(" as ")[0].strip().rstrip("()")
                    if piece:
                        imported_names.add(piece)
            elif s.startswith("import "):
                rest = s[7:].strip()
                first = rest.split(",")[0].strip().split(" as ")[0].strip().split(".")[0]
                if first:
                    imported_names.add(first)
        # Pytest fixtures defined locally + existing test names (some
        # tests legitimately call helper test fns).
        fixture_names = set(existing_fixtures.keys()) | set(new_fixtures.keys())
        helper_names = set(existing_tests.keys())  # existing tests can be referenced
        allowed_call_names = workspace_fns | imported_names | fixture_names | helper_names

        # v5.2: workspace signatures for arity validation.
        workspace_sigs = _workspace_function_signatures(workspace_dir)
        validated_new_tests: Dict[str, str] = {}
        for tname, tsrc in new_tests.items():
            violations = _check_call_targets(tsrc, allowed_call_names, workspace_sigs)
            if violations:
                self._rejection_log.append({
                    "path": rel_path,
                    "reason": (
                        f"test `{tname}` has issues: {violations}. "
                        f"Workspace exports: {sorted(workspace_fns)}. "
                        f"Re-emit using ONLY these callables AND respect their signatures: "
                        + ", ".join(f"{n}({','.join(['_'] * sig[0])})" for n, sig in sorted(workspace_sigs.items())[:6])
                        + ". Common mistake: `clean_records(records)` is wrong — needs `clean_records(records, schema)`."
                    ),
                })
                continue  # drop this test from merge
            validated_new_tests[tname] = tsrc

        # v5.1 Task B: protect passing tests. If the model re-emits a test
        # that was passing in the prior iter, only accept the new version
        # if content is byte-equivalent. Different content → reject + log;
        # passing version preserved. This realises R_{t+1} as a structured
        # vector (passing dimensions are FIXED, only failing dimensions are
        # mutable).
        passing_test_names: Set[str] = set(
            (contract or {}).get("_passing_tests_last_iter") or set()
        )
        merged_tests = dict(existing_tests)
        for tname, new_src in validated_new_tests.items():
            if tname in passing_test_names:
                existing_src = existing_tests.get(tname, "")
                # Normalise whitespace before equality check — minor cosmetic
                # diffs (trailing newline, indent) shouldn't count as "changed"
                if _normalise_src(new_src) != _normalise_src(existing_src):
                    self._rejection_log.append({
                        "path": rel_path,
                        "reason": (
                            f"test `{tname}` was PASSING in the previous iter — "
                            f"your re-emitted version differs from the passing version, "
                            f"so the passing version was PRESERVED and your edit dropped. "
                            f"Focus edits on tests in the failing list, not on tests "
                            f"in the protected/passing set."
                        ),
                    })
                    continue  # keep existing (passing) version, drop new
            merged_tests[tname] = new_src

        # v5.0.4: filter new imports against workspace inventory + stdlib + pytest.
        # gemma 4B hallucinated `from data_processing import clean_data` (the
        # actual module is `data_pipeline` with `clean_records`). When such
        # imports land in the merged file, pytest collection fails → all
        # tests become 0 passing → dominance rollback → oscillation. Strip
        # imports that reference modules NOT in workspace; log rejection.
        workspace_modules = self._workspace_module_names(workspace_dir)
        stdlib_allowed = _STDLIB_ALLOWLIST  # module-level constant

        all_imports_lines: List[str] = []
        seen_imports = set()
        for src in (existing_imports + "\n" + new_imports).splitlines():
            stripped = src.strip()
            if not stripped or stripped in seen_imports:
                continue
            # Validate the import target
            top_module = _import_top_module(stripped)
            if top_module is not None and top_module not in workspace_modules and top_module not in stdlib_allowed:
                # Hallucinated module — log rejection so model sees it in feedback
                self._rejection_log.append({
                    "path": rel_path,
                    "reason": (
                        f"import `{stripped}` references module `{top_module}` which does NOT exist in workspace. "
                        f"Workspace modules: {sorted(workspace_modules)}. "
                        f"Stdlib + pytest allowed automatically. Re-emit using one of those."
                    ),
                })
                continue
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


# v5.0.4: stdlib + pytest allowlist for import validation. Hallucinated
# imports (e.g. gemma's `from data_processing import clean_data` when the
# real module is data_pipeline) get filtered at merge time → workspace
# stays collectible. Allowlist is conservative — common imports a test
# file legitimately uses.
_STDLIB_ALLOWLIST: set = {
    "pytest", "json", "os", "sys", "re", "math", "time", "datetime",
    "pathlib", "tempfile", "io", "collections", "typing", "functools",
    "itertools", "operator", "string", "copy", "decimal", "fractions",
    "random", "statistics", "abc", "dataclasses", "enum", "contextlib",
    "warnings", "unittest", "subprocess", "builtins",
}


# v5.0.7: pytest API names + commonly-imported stdlib callables that tests
# legitimately invoke. Combined with workspace function names + builtins +
# local variables, this forms the allowlist for _check_call_targets.
_PYTEST_API_NAMES: set = {
    "pytest", "raises", "fixture", "mark", "approx", "param", "skip",
    "xfail", "warns", "deprecated_call",
    # Common test fixtures provided by pytest:
    "tmp_path", "tmpdir", "monkeypatch", "capsys", "capfd", "caplog",
    "request", "recwarn",
}


def _workspace_function_signatures(workspace_dir: str) -> Dict[str, tuple]:
    """v5.2: extract (min_arity, max_arity, kw_names) per workspace function/class.
    Used to validate call arity at merge time so wrong-arity tests don't land.
    """
    sigs: Dict[str, tuple] = {}
    try:
        for f in os.listdir(workspace_dir):
            if not f.endswith(".py") or f.startswith("test_") or f.startswith("__"):
                continue
            try:
                tree = ast.parse(open(os.path.join(workspace_dir, f),
                                      encoding="utf-8").read())
            except (OSError, SyntaxError):
                continue
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    pos_args = list(node.args.args)
                    defaults = node.args.defaults
                    min_a = max(0, len(pos_args) - len(defaults))
                    max_a = 10_000 if node.args.vararg is not None else len(pos_args)
                    kw_names = {a.arg for a in node.args.kwonlyargs}
                    kw_names |= {a.arg for a in pos_args}
                    sigs[node.name] = (min_a, max_a, kw_names,
                                       node.args.kwarg is not None)
                elif isinstance(node, ast.ClassDef):
                    # Class is callable (constructor). Default to "0 or 1" — most
                    # classes accept up to a couple init args; permissive default.
                    sigs[node.name] = (0, 10_000, set(), True)
    except OSError:
        pass
    return sigs


def _check_call_targets(test_src: str, allowed_call_names: set,
                          workspace_signatures: Optional[Dict[str, tuple]] = None) -> List[str]:
    """AST-walk a test function body; return sorted list of bare-Name
    function-call targets that are not defined locally and not in
    `allowed_call_names`. Empty list = OK (no undefined-target calls).

    Catches hallucinated names like `clean_data(...)` / `process_data(...)`
    when those functions don't exist in workspace. Lets through legitimate
    calls to workspace functions, pytest fixtures, builtins, local vars.

    Only flags ast.Call nodes whose target is a bare Name (not
    attribute access — `foo.bar()` isn't flagged because we can't
    statically resolve foo).
    """
    import builtins as _builtins
    builtin_names = set(dir(_builtins))
    try:
        tree = ast.parse(test_src)
        fn_node = tree.body[0]
    except (SyntaxError, IndexError):
        return ["<unparseable>"]
    if not isinstance(fn_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []

    # Build local scope: function args + assignments + for/with/comp targets
    locals_seen: set = {a.arg for a in fn_node.args.args}
    if fn_node.args.vararg:
        locals_seen.add(fn_node.args.vararg.arg)
    if fn_node.args.kwarg:
        locals_seen.add(fn_node.args.kwarg.arg)
    for a in fn_node.args.kwonlyargs:
        locals_seen.add(a.arg)
    # Walk for further bindings
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                for sub in ast.walk(tgt):
                    if isinstance(sub, ast.Name):
                        locals_seen.add(sub.id)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            if isinstance(node.target, ast.Name):
                locals_seen.add(node.target.id)
        elif isinstance(node, ast.For):
            for sub in ast.walk(node.target):
                if isinstance(sub, ast.Name):
                    locals_seen.add(sub.id)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars:
                    for sub in ast.walk(item.optional_vars):
                        if isinstance(sub, ast.Name):
                            locals_seen.add(sub.id)
        elif isinstance(node, ast.Lambda):
            for a in node.args.args:
                locals_seen.add(a.arg)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in node.generators:
                for sub in ast.walk(gen.target):
                    if isinstance(sub, ast.Name):
                        locals_seen.add(sub.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node is not fn_node:
            # Nested def — its name is local
            locals_seen.add(node.name)

    undefined_calls: set = set()
    arity_violations: List[str] = []
    sigs = workspace_signatures or {}
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            recognised = (
                name in locals_seen
                or name in allowed_call_names
                or name in builtin_names
                or name in _PYTEST_API_NAMES
            )
            if not recognised:
                undefined_calls.add(name)
                continue
            # v5.2: arity check for known workspace functions
            sig = sigs.get(name)
            if sig is not None:
                min_a, max_a, kw_names_accepted, has_var_keyword = sig
                pos_args = sum(1 for a in node.args if not isinstance(a, ast.Starred))
                has_star = any(isinstance(a, ast.Starred) for a in node.args)
                has_double_star = any(kw.arg is None for kw in node.keywords)
                if not (has_star or has_double_star):
                    if pos_args < min_a or pos_args > max_a:
                        arity_violations.append(
                            f"{name}: passed {pos_args} positional args but signature accepts {min_a}-{max_a}"
                        )
                    else:
                        # Also flag unknown keyword names
                        if not has_var_keyword:
                            for kw in node.keywords:
                                if kw.arg and kw.arg not in kw_names_accepted:
                                    arity_violations.append(
                                        f"{name}: keyword `{kw.arg}` not accepted (only {sorted(kw_names_accepted)})"
                                    )
    # Surface arity violations alongside undefined_calls so caller treats
    # them as rejection-worthy.
    return sorted(undefined_calls) + sorted(set(arity_violations))


def _normalise_src(s: str) -> str:
    """v5.1: whitespace-normalised source for content-equality check.
    Strips trailing whitespace per line + leading/trailing blank lines.
    Cosmetic diffs (extra blank line, trailing space) don't count as
    "changed" when comparing a passing test's prior vs new version.
    """
    if not s:
        return ""
    lines = [ln.rstrip() for ln in s.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _import_top_module(import_line: str) -> str:
    """Extract the top-level module from `import X` or `from X.y import Z`.
    Returns None if the line is not an import statement.
    """
    s = import_line.strip()
    if s.startswith("from "):
        rest = s[5:].split(" import ")[0].strip()
        return rest.split(".")[0] if rest else None
    if s.startswith("import "):
        rest = s[7:].strip()
        first = rest.split(",")[0].split(" ")[0].strip()
        return first.split(".")[0] if first else None
    return None


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
