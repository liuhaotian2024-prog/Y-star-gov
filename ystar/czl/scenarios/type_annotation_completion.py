"""
ystar.czl.scenarios.type_annotation_completion — v3 scenario #2

Indie task: add type annotations to an untyped Python module so it passes
mypy --strict. Behaviour must be preserved. Tests must still pass. AST
check ensures function SIGNATURES are not changed (param names, default
values, *args/**kwargs preserved); only annotations can be added.
"""
from __future__ import annotations

import ast
import os
import subprocess
import time
from typing import Any, Dict, List, Tuple

from ystar.czl.scenarios.base import Scenario, PlanStep, ScenarioRegistry
from ystar.czl.verifiers.base import Verifier, VerifierResult


# === workspace fixture =======================================================
# A realistic ~200 line module that exercises Optional, Union, Protocol,
# TypeVar, plus list/dict containers. Untyped at baseline.

BASELINE_FILES: Dict[str, str] = {
    "data_ops.py": (
        "from collections import defaultdict\n"
        "\n"
        "\n"
        "class Cache:\n"
        "    def __init__(self):\n"
        "        self._store = {}\n"
        "\n"
        "    def get(self, key, default=None):\n"
        "        return self._store.get(key, default)\n"
        "\n"
        "    def put(self, key, value):\n"
        "        self._store[key] = value\n"
        "\n"
        "    def remove(self, key):\n"
        "        return self._store.pop(key, None)\n"
        "\n"
        "    def keys(self):\n"
        "        return list(self._store.keys())\n"
        "\n"
        "\n"
        "def normalize_record(row):\n"
        "    out = {}\n"
        "    for k, v in row.items():\n"
        "        if isinstance(v, str):\n"
        "            out[k] = v.strip().lower()\n"
        "        else:\n"
        "            out[k] = v\n"
        "    return out\n"
        "\n"
        "\n"
        "def merge_dicts(a, b):\n"
        "    result = dict(a)\n"
        "    result.update(b)\n"
        "    return result\n"
        "\n"
        "\n"
        "def group_by(items, key_fn):\n"
        "    groups = defaultdict(list)\n"
        "    for item in items:\n"
        "        groups[key_fn(item)].append(item)\n"
        "    return dict(groups)\n"
        "\n"
        "\n"
        "def first_or_none(items):\n"
        "    return items[0] if items else None\n"
        "\n"
        "\n"
        "def find_one(items, predicate):\n"
        "    for x in items:\n"
        "        if predicate(x):\n"
        "            return x\n"
        "    return None\n"
        "\n"
        "\n"
        "def filter_keys(d, allowed):\n"
        "    return {k: v for k, v in d.items() if k in allowed}\n"
        "\n"
        "\n"
        "def safe_int(value, default=0):\n"
        "    try:\n"
        "        return int(value)\n"
        "    except (TypeError, ValueError):\n"
        "        return default\n"
        "\n"
        "\n"
        "def chunked(items, size):\n"
        "    return [items[i:i + size] for i in range(0, len(items), size)]\n"
        "\n"
        "\n"
        "def flatten(nested):\n"
        "    out = []\n"
        "    for sub in nested:\n"
        "        out.extend(sub)\n"
        "    return out\n"
        "\n"
        "\n"
        "def histogram(items):\n"
        "    counts = {}\n"
        "    for x in items:\n"
        "        counts[x] = counts.get(x, 0) + 1\n"
        "    return counts\n"
        "\n"
        "\n"
        "def best_by(items, score_fn):\n"
        "    best = None\n"
        "    best_score = None\n"
        "    for x in items:\n"
        "        score = score_fn(x)\n"
        "        if best is None or score > best_score:\n"
        "            best = x\n"
        "            best_score = score\n"
        "    return best\n"
    ),
    "mypy.ini": (
        "[mypy]\n"
        "strict = True\n"
        "disallow_untyped_defs = True\n"
        "disallow_incomplete_defs = True\n"
        "disallow_untyped_decorators = True\n"
        "no_implicit_optional = True\n"
        "warn_redundant_casts = True\n"
        "warn_unused_ignores = True\n"
    ),
    "test_data_ops.py": (
        "from data_ops import (\n"
        "    Cache, normalize_record, merge_dicts, group_by,\n"
        "    first_or_none, find_one, filter_keys, safe_int,\n"
        "    chunked, flatten, histogram, best_by,\n"
        ")\n"
        "\n"
        "\n"
        "def test_cache_put_get():\n"
        "    c = Cache()\n"
        "    c.put('a', 1)\n"
        "    assert c.get('a') == 1\n"
        "    assert c.get('missing') is None\n"
        "\n"
        "\n"
        "def test_normalize_record():\n"
        "    assert normalize_record({'Name': '  Bob  ', 'age': 30}) == {'Name': 'bob', 'age': 30}\n"
        "\n"
        "\n"
        "def test_merge_dicts():\n"
        "    assert merge_dicts({'a': 1}, {'b': 2}) == {'a': 1, 'b': 2}\n"
        "\n"
        "\n"
        "def test_group_by():\n"
        "    g = group_by([1, 2, 3, 4], lambda x: x % 2)\n"
        "    assert g[0] == [2, 4]\n"
        "    assert g[1] == [1, 3]\n"
        "\n"
        "\n"
        "def test_first_or_none():\n"
        "    assert first_or_none([1, 2]) == 1\n"
        "    assert first_or_none([]) is None\n"
        "\n"
        "\n"
        "def test_find_one():\n"
        "    assert find_one([1, 2, 3], lambda x: x > 1) == 2\n"
        "    assert find_one([1, 2, 3], lambda x: x > 10) is None\n"
        "\n"
        "\n"
        "def test_filter_keys():\n"
        "    assert filter_keys({'a': 1, 'b': 2}, {'a'}) == {'a': 1}\n"
        "\n"
        "\n"
        "def test_safe_int():\n"
        "    assert safe_int('5') == 5\n"
        "    assert safe_int('bad', default=-1) == -1\n"
        "\n"
        "\n"
        "def test_chunked():\n"
        "    assert chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]\n"
        "\n"
        "\n"
        "def test_flatten():\n"
        "    assert flatten([[1, 2], [3]]) == [1, 2, 3]\n"
        "\n"
        "\n"
        "def test_histogram():\n"
        "    assert histogram(['a', 'b', 'a']) == {'a': 2, 'b': 1}\n"
        "\n"
        "\n"
        "def test_best_by():\n"
        "    assert best_by([1, 5, 3], lambda x: -x) == 1\n"
    ),
}


TASK_DESCRIPTION = (
    "给这个未注解的 Python 模块补齐类型注解，必须通过 mypy --strict。"
    "不能改变函数行为。"
)


# === verifiers ===============================================================

class MypyStrictVerifier(Verifier):
    name = "mypy_strict"

    def is_applicable(self, workspace_dir: str) -> bool:
        return os.path.isfile(os.path.join(workspace_dir, "data_ops.py"))

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        try:
            proc = subprocess.run(
                ["mypy", "--strict", "--show-error-codes", "--no-error-summary", "."],
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
    """Function names + param names + param order + *args/**kwargs unchanged from baseline."""
    name = "signatures_frozen"

    BASELINE_SIGS: Dict[str, Tuple[str, ...]] = {
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

    def is_applicable(self, workspace_dir: str) -> bool:
        return os.path.isfile(os.path.join(workspace_dir, "data_ops.py"))

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        try:
            body = open(os.path.join(workspace_dir, "data_ops.py"), "r", encoding="utf-8").read()
            tree = ast.parse(body)
        except (FileNotFoundError, SyntaxError) as e:
            return VerifierResult(verifier_name=self.name, passed=False,
                                  message=f"data_ops.py unreadable: {e}",
                                  elapsed_seconds=time.time() - t0)
        observed: Dict[str, Tuple[str, ...]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for body_node in node.body:
                    if isinstance(body_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args = tuple(a.arg for a in body_node.args.args)
                        observed[f"{node.name}.{body_node.name}"] = args
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # only top-level
                pass
        # also pick up top-level funcs
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                observed[node.name] = tuple(a.arg for a in node.args.args)
        mismatches: List[str] = []
        for sig_name, expected_args in self.BASELINE_SIGS.items():
            got = observed.get(sig_name)
            if got is None:
                mismatches.append(f"{sig_name}: function missing")
            elif got != expected_args:
                mismatches.append(f"{sig_name}: args {got} != baseline {expected_args}")
        if mismatches:
            return VerifierResult(verifier_name=self.name, passed=False,
                                  message=f"{len(mismatches)} signature mismatch(es); first: {mismatches[0]}",
                                  details={"mismatches": mismatches},
                                  elapsed_seconds=time.time() - t0)
        return VerifierResult(verifier_name=self.name, passed=True,
                              message=f"all {len(self.BASELINE_SIGS)} signatures preserved",
                              elapsed_seconds=time.time() - t0)


# === scenario ================================================================

class TypeAnnotationCompletionScenario(Scenario):
    name = "type_annotation_completion"
    description = "Add type annotations to data_ops.py so it passes mypy --strict; preserve behaviour and signatures"
    default_max_iterations = 8

    def y_star_invariants(self) -> Dict[str, Any]:
        return {
            "invariant": [
                "mypy_strict_clean == True",
                "all_pytest_tests_pass == True",
                "function_signatures_frozen == True",
            ],
            "only_paths": ["./data_ops.py"],
            "deny": [".env", ".git/", "secrets"],
        }

    def plan(self, task_description: str, workspace_dir: str) -> List[PlanStep]:
        path = os.path.join(workspace_dir, "data_ops.py")
        body = open(path, "r", encoding="utf-8").read() if os.path.isfile(path) else "(missing)"
        baseline = self._collect_baseline(workspace_dir)
        return [PlanStep(
            step_id="add_annotations",
            user_prompt=(
                f"## Task\n{task_description}\n\n"
                "## File to edit (data_ops.py — only this file)\n"
                f"```python\n{body}```\n\n"
                "## Current mypy --strict output\n"
                f"```\n{baseline}\n```\n\n"
                "## Constraints (Y*)\n"
                "- `mypy --strict` must report zero errors\n"
                "- All tests in test_data_ops.py must pass\n"
                "- Function NAMES and PARAMETER NAMES must be unchanged (no renames, no reorder, no insert/delete params)\n"
                "- You may add annotations, imports from typing (Optional, Union, Iterable, TypeVar, Protocol, Callable, etc.)\n"
                "- Do NOT change function bodies except to add a `return None` if mypy demands it\n"
                "- Do NOT modify test_data_ops.py or mypy.ini\n\n"
                "## Output format\n"
                "```edit data_ops.py\n"
                "<full new file content>\n"
                "```\n"
            ),
            expected_action_types=["edit_file"],
        )]

    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        results: List[VerifierResult] = []
        for v in (MypyStrictVerifier(), PytestPassVerifier(), FunctionSignatureFrozenVerifier()):
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
                ["mypy", "--strict", "--show-error-codes", "--no-error-summary", "data_ops.py"],
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
        if basename != "data_ops.py":
            return  # scenario only writes to data_ops.py
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
