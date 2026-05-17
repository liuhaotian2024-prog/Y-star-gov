"""
ystar.czl.scenarios.type_annotation_completion — v3.2 (redesigned)

Indie task: add type annotations to an untyped Python module so it passes
mypy --strict. v3 + v3.1 fixture was self-contradictory (forbade ANY
signature change, but mypy strict requires adding annotations which IS a
signature change). v3.2 redesigns:

  1. New fixture `data_processor.py` (3 functions, no class) — narrower
     surface, easier to reason about + verify.
  2. `FunctionSignatureFrozenVerifier` acquires `mode` parameter:
       - "full" (default, preserves v3 behaviour)
       - "name_and_arity_only" (v3.2): checks function names + param COUNT
         only. Param names can change. Annotations naturally allowed
         since they don't affect arity.
  3. New task wording explicitly permits annotations, forbids rename /
     reorder / default-change / add/remove params.

CIEU record `step_type_annotation_fixture_redesign` documents the r=1
catch and rationale.
"""
from __future__ import annotations

import ast
import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from ystar.czl.scenarios.base import Scenario, PlanStep, ScenarioRegistry
from ystar.czl.verifiers.base import Verifier, VerifierResult


# === workspace fixture (v3.2) ================================================
# 3 small functions — filter / aggregate / count — that need annotations.
# Easier for an 8B model to reason about than the 12-function v3 class +
# top-level module. Mypy --strict will demand annotations on all 3.

BASELINE_FILES: Dict[str, str] = {
    "data_processor.py": (
        "def filter_active_users(users):\n"
        "    return [u for u in users if u.get('active')]\n"
        "\n"
        "\n"
        "def compute_avg_age(users):\n"
        "    ages = [u['age'] for u in users if 'age' in u]\n"
        "    if not ages:\n"
        "        return 0.0\n"
        "    return sum(ages) / len(ages)\n"
        "\n"
        "\n"
        "def count_by_domain(emails):\n"
        "    counts = {}\n"
        "    for e in emails:\n"
        "        if '@' not in e:\n"
        "            continue\n"
        "        d = e.split('@', 1)[1].lower()\n"
        "        counts[d] = counts.get(d, 0) + 1\n"
        "    return counts\n"
    ),
    "mypy.ini": (
        "[mypy]\n"
        "strict = True\n"
        "disallow_untyped_defs = True\n"
        "disallow_incomplete_defs = True\n"
        "no_implicit_optional = True\n"
        "warn_redundant_casts = True\n"
        "warn_unused_ignores = True\n"
    ),
    # 11 asserts across 9 test functions
    "test_data_processor.py": (
        "from data_processor import filter_active_users, compute_avg_age, count_by_domain\n"
        "\n"
        "\n"
        "def test_filter_active_basic():\n"
        "    out = filter_active_users([{'id': 1, 'active': True}, {'id': 2, 'active': False}])\n"
        "    assert len(out) == 1\n"
        "    assert out[0]['id'] == 1\n"
        "\n"
        "\n"
        "def test_filter_active_empty():\n"
        "    assert filter_active_users([]) == []\n"
        "\n"
        "\n"
        "def test_filter_active_missing_field():\n"
        "    assert filter_active_users([{'id': 1}]) == []\n"
        "\n"
        "\n"
        "def test_compute_avg_age_basic():\n"
        "    assert compute_avg_age([{'age': 20}, {'age': 30}]) == 25.0\n"
        "\n"
        "\n"
        "def test_compute_avg_age_empty():\n"
        "    assert compute_avg_age([]) == 0.0\n"
        "\n"
        "\n"
        "def test_compute_avg_age_skip_missing():\n"
        "    assert compute_avg_age([{'age': 20}, {'name': 'x'}]) == 20.0\n"
        "\n"
        "\n"
        "def test_count_by_domain_basic():\n"
        "    out = count_by_domain(['a@x.com', 'b@x.com', 'c@y.com'])\n"
        "    assert out['x.com'] == 2\n"
        "    assert out['y.com'] == 1\n"
        "\n"
        "\n"
        "def test_count_by_domain_case_insensitive():\n"
        "    assert count_by_domain(['A@X.com']) == {'x.com': 1}\n"
        "\n"
        "\n"
        "def test_count_by_domain_skip_no_at():\n"
        "    assert count_by_domain(['foo', 'a@x.com']) == {'x.com': 1}\n"
    ),
}


TASK_DESCRIPTION = (
    "给 data_processor.py 中的 3 个函数补齐类型注解，必须通过 mypy --strict。"
    "函数名和参数数量不能改 (不能加/删/重排参数，不能改默认值)；"
    "参数名可保留或改名都可。"
    "行为不能变，test_data_processor.py 全部测试必须仍然通过。"
)


# baseline signature map: name → (arity, exact_param_names)
# v3.2 verifier uses mode="name_and_arity_only" → exact names ignored.
BASELINE_SIGS_V3_2: Dict[str, Tuple[str, ...]] = {
    "filter_active_users": ("users",),
    "compute_avg_age":     ("users",),
    "count_by_domain":     ("emails",),
}


# === verifiers ===============================================================

class MypyStrictVerifier(Verifier):
    name = "mypy_strict"

    def __init__(self, target_file: str = "data_processor.py"):
        self.target_file = target_file

    def is_applicable(self, workspace_dir: str) -> bool:
        return os.path.isfile(os.path.join(workspace_dir, self.target_file))

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        try:
            proc = subprocess.run(
                ["mypy", "--strict", "--show-error-codes", "--no-error-summary", self.target_file],
                cwd=workspace_dir, capture_output=True, text=True, timeout=120,
            )
            if proc.returncode == 0:
                return VerifierResult(verifier_name=self.name, passed=True,
                                      message="mypy --strict: clean",
                                      elapsed_seconds=time.time() - t0)
            err_lines = [ln for ln in (proc.stdout or "").splitlines() if ": error:" in ln]
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"mypy --strict: {len(err_lines)} error(s)",
                details={"stdout": (proc.stdout or "")[-1500:]},
                elapsed_seconds=time.time() - t0,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(verifier_name=self.name, passed=False,
                                  message="mypy timed out", elapsed_seconds=time.time() - t0)


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


class FunctionSignatureFrozenVerifier(Verifier):
    """Frozen function set with two modes:

      - mode="full" (default, preserves v3 behaviour):
            name + exact param names + order
      - mode="name_and_arity_only" (v3.2):
            name + param COUNT only.  Param names can change.  Annotations
            naturally allowed since they don't affect arity.

    Either way, the function MUST exist in the candidate module and CANNOT
    have its arity changed (no inserting / removing / *args-collapsing
    params), which preserves the original contract intent (behaviour
    preservation) while making the v3.2 redesigned task solvable.
    """
    name = "signatures_frozen"

    # Kept for backward-compat: the v3 BASELINE_SIGS for data_ops.py. v3.2
    # constructs the verifier with the new BASELINE_SIGS_V3_2 explicitly.
    DEFAULT_BASELINE_SIGS_V3: Dict[str, Tuple[str, ...]] = {
        "Cache.__init__": ("self",),
        "Cache.get": ("self", "key", "default"),
        "Cache.put": ("self", "key", "value"),
        "Cache.remove": ("self", "key"),
        "Cache.keys": ("self",),
        "normalize_record": ("row",),
        "merge_dicts": ("a", "b"),
        "group_by": ("items", "key_fn"),
        "first_or_none": ("items",),
        "find_one": ("items", "predicate"),
        "filter_keys": ("d", "allowed"),
        "safe_int": ("value", "default"),
        "chunked": ("items", "size"),
        "flatten": ("nested",),
        "histogram": ("items",),
        "best_by": ("items", "score_fn"),
    }

    def __init__(
        self,
        baseline_sigs: Optional[Dict[str, Tuple[str, ...]]] = None,
        mode: str = "full",
        target_file: str = "data_processor.py",
    ):
        if mode not in ("full", "name_and_arity_only"):
            raise ValueError(f"FunctionSignatureFrozenVerifier: unknown mode {mode!r}")
        self.baseline_sigs = baseline_sigs if baseline_sigs is not None else self.DEFAULT_BASELINE_SIGS_V3
        self.mode = mode
        self.target_file = target_file

    def is_applicable(self, workspace_dir: str) -> bool:
        return os.path.isfile(os.path.join(workspace_dir, self.target_file))

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        try:
            body = open(os.path.join(workspace_dir, self.target_file), "r", encoding="utf-8").read()
            tree = ast.parse(body)
        except (FileNotFoundError, SyntaxError) as e:
            return VerifierResult(verifier_name=self.name, passed=False,
                                  message=f"{self.target_file} unreadable: {e}",
                                  elapsed_seconds=time.time() - t0)

        observed: Dict[str, Tuple[str, ...]] = {}
        # class methods
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for body_node in node.body:
                    if isinstance(body_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args = tuple(a.arg for a in body_node.args.args)
                        observed[f"{node.name}.{body_node.name}"] = args
        # top-level funcs
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                observed[node.name] = tuple(a.arg for a in node.args.args)

        mismatches: List[str] = []
        for sig_name, expected_args in self.baseline_sigs.items():
            got = observed.get(sig_name)
            if got is None:
                mismatches.append(f"{sig_name}: function missing")
                continue
            if self.mode == "full":
                if got != expected_args:
                    mismatches.append(f"{sig_name}: args {got} != baseline {expected_args}")
            elif self.mode == "name_and_arity_only":
                if len(got) != len(expected_args):
                    mismatches.append(
                        f"{sig_name}: arity {len(got)} (params={got}) != "
                        f"baseline arity {len(expected_args)} (params={expected_args})"
                    )
        if mismatches:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"{len(mismatches)} signature mismatch(es); first: {mismatches[0]}",
                details={"mismatches": mismatches, "mode": self.mode},
                elapsed_seconds=time.time() - t0,
            )
        return VerifierResult(
            verifier_name=self.name, passed=True,
            message=f"all {len(self.baseline_sigs)} signatures preserved (mode={self.mode})",
            details={"mode": self.mode},
            elapsed_seconds=time.time() - t0,
        )


# === scenario ================================================================

class TypeAnnotationCompletionScenario(Scenario):
    name = "type_annotation_completion"
    description = "Add type annotations to data_processor.py so it passes mypy --strict; preserve behaviour, function names, and arity (param names free to change)"
    default_max_iterations = 8

    def y_star_invariants(self) -> Dict[str, Any]:
        return {
            "invariant": [
                "mypy_strict_clean == True",
                "all_pytest_tests_pass == True",
                "function_names_and_arity_preserved == True",
            ],
            "only_paths": ["./data_processor.py"],
            "deny": [".env", ".git/", "secrets"],
        }

    def plan(self, task_description: str, workspace_dir: str) -> List[PlanStep]:
        path = os.path.join(workspace_dir, "data_processor.py")
        body = open(path, "r", encoding="utf-8").read() if os.path.isfile(path) else "(missing)"
        baseline = self._collect_baseline(workspace_dir)
        return [PlanStep(
            step_id="add_annotations",
            user_prompt=(
                f"## Task\n{task_description}\n\n"
                "## File to edit (data_processor.py — only this file)\n"
                f"```python\n{body}```\n\n"
                "## Current mypy --strict output\n"
                f"```\n{baseline}\n```\n\n"
                "## Constraints (Y*)\n"
                "- `mypy --strict` must report zero errors on data_processor.py\n"
                "- All tests in test_data_processor.py must pass\n"
                "- Function NAMES must be unchanged (no renames)\n"
                "- Function ARITY (parameter count) must be unchanged "
                "(no inserting / deleting / collapsing params; no default-value changes)\n"
                "- You CAN rename parameters and CAN add type annotations everywhere\n"
                "- You CAN import from typing (Optional, Union, Iterable, List, Dict, "
                "Callable, TypedDict, TypeVar, etc.) — these imports are fine\n"
                "- Do NOT modify test_data_processor.py or mypy.ini\n\n"
                "## Output format\n"
                "```edit data_processor.py\n"
                "<full new file content>\n"
                "```\n"
            ),
            expected_action_types=["edit_file"],
        )]

    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        results: List[VerifierResult] = []
        verifiers = (
            MypyStrictVerifier(target_file="data_processor.py"),
            PytestPassVerifier(),
            FunctionSignatureFrozenVerifier(
                baseline_sigs=BASELINE_SIGS_V3_2,
                mode="name_and_arity_only",
                target_file="data_processor.py",
            ),
        )
        for v in verifiers:
            if v.is_applicable(workspace_dir):
                results.append(v.run(workspace_dir, contract))
        return results

    def apply_action(self, action: Dict[str, Any], workspace_dir: str) -> None:
        action_type = action.get("type", "") if isinstance(action, dict) else getattr(action, "type", "")
        payload = action.payload if hasattr(action, "payload") else action
        if action_type in ("edit_file", "create_file"):
            self._safe_write(workspace_dir, payload.get("path", ""), payload.get("content", ""))

    def _collect_baseline(self, workspace_dir: str) -> str:
        try:
            proc = subprocess.run(
                ["mypy", "--strict", "--show-error-codes", "--no-error-summary", "data_processor.py"],
                cwd=workspace_dir, capture_output=True, text=True, timeout=60,
            )
            return (proc.stdout or proc.stderr or "(no output)").strip()[:3000]
        except Exception as e:
            return f"(mypy failed to run: {e})"

    def _safe_write(self, workspace_dir: str, rel_path: str, content: str) -> None:
        full = os.path.abspath(os.path.join(workspace_dir, rel_path))
        ws_abs = os.path.abspath(workspace_dir)
        if not full.startswith(ws_abs + os.sep) and full != ws_abs:
            raise ValueError(f"Refusing to write outside workspace: {rel_path}")
        basename = os.path.basename(full)
        if basename != "data_processor.py":
            return  # scenario only writes to data_processor.py
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


ScenarioRegistry.register(TypeAnnotationCompletionScenario())
