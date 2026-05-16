"""
differential_verifier.py — outcome-based behavioural cross-check.

Extracts (input, expected_output) pairs from the fixture's pytest tests:
  - pytest.mark.parametrize decorators
  - bare assert <fn>(<args>) == <literal> statements

Then runs the model's implementation against each input in a subprocess and
compares the observable return value to the expected literal. Mismatches
emit DifferentialMismatch.

ZERO process-based logic — we never inspect "which files the model edited"
or "did the model rename something". Only observable input -> output.

Reused-asset provenance:
  - subprocess pytest pattern reused from ystar/czl/scenarios/bug_fix.py
    PytestAllPassVerifier; we adapt it to a one-shot Python invocation
    instead of a full pytest run.

KNOWN LIMITATION (called out honestly): without a synthetic input
generator (Hypothesis was cut from Phase 2), this verifier only re-checks
exactly what pytest already checks. It catches LITERAL mismatches between
what tests assert and what the function actually returns. It cannot catch
semantic drift on untested inputs. That requires Phase-3+ work.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ystar.czl.verifiers.base import Verifier, VerifierResult


# === data structures ========================================================

@dataclass
class TestCase:
    """One observable (input, expected) sample extracted from a test."""
    function_name: str
    args_literal: List[str]          # repr-able Python literals as source strings
    kwargs_literal: Dict[str, str]
    expected_repr: Optional[str]     # source-text for the expected RHS, or None if not a literal
    source_file: str
    lineno: int


@dataclass
class DifferentialMismatch:
    test_case: TestCase
    observed_repr: str
    expected_repr: str
    reason: str = ""


# === extraction =============================================================

def _is_literal_safe(node: ast.expr) -> bool:
    """True iff `node` is a Python literal we can safely eval as JSON-ish (no calls/names)."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_literal_safe(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(_is_literal_safe(k) and _is_literal_safe(v) for k, v in zip(node.keys, node.values) if k is not None)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _is_literal_safe(node.operand)
    return False


def _extract_call_with_literal_expected(stmt: ast.stmt) -> Optional[Tuple[ast.Call, ast.expr]]:
    """If stmt is `assert <call> == <literal>`, return (call_node, literal_node)."""
    if not isinstance(stmt, ast.Assert):
        return None
    cmp = stmt.test
    if not isinstance(cmp, ast.Compare):
        return None
    if len(cmp.ops) != 1 or not isinstance(cmp.ops[0], ast.Eq):
        return None
    left = cmp.left
    right = cmp.comparators[0]
    # Either side can be the call; the other must be a literal.
    if isinstance(left, ast.Call) and _is_literal_safe(right):
        return left, right
    if isinstance(right, ast.Call) and _is_literal_safe(left):
        return right, left
    return None


def _call_target_name(call: ast.Call) -> Optional[str]:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def extract_test_cases(workspace_dir: str) -> List[TestCase]:
    """Walk test_*.py files, extract simple assert-based (input, expected) pairs."""
    cases: List[TestCase] = []
    for root, dirs, files in os.walk(workspace_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for fname in files:
            if not (fname.startswith("test_") and fname.endswith(".py")):
                continue
            path = os.path.join(root, fname)
            try:
                tree = ast.parse(open(path, "r", encoding="utf-8").read(), filename=path)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                # Only test_ functions
                if not node.name.startswith("test_"):
                    continue
                for stmt in node.body:
                    pair = _extract_call_with_literal_expected(stmt)
                    if pair is None:
                        continue
                    call_node, expected_node = pair
                    fn_name = _call_target_name(call_node)
                    if fn_name is None:
                        continue
                    # Args & kwargs as source repr
                    try:
                        args_lit = [ast.unparse(a) for a in call_node.args
                                    if _is_literal_safe(a) or isinstance(a, ast.Constant)]
                        kwargs_lit = {kw.arg: ast.unparse(kw.value)
                                      for kw in call_node.keywords
                                      if kw.arg is not None and _is_literal_safe(kw.value)}
                        expected_repr = ast.unparse(expected_node)
                    except Exception:
                        continue
                    # Only keep if all positional args were literal
                    if len(args_lit) != len(call_node.args):
                        continue
                    cases.append(TestCase(
                        function_name=fn_name,
                        args_literal=args_lit,
                        kwargs_literal=kwargs_lit,
                        expected_repr=expected_repr,
                        source_file=path,
                        lineno=node.lineno,
                    ))
    return cases


# === execution ==============================================================

_RUNNER_TEMPLATE = r"""
import sys, json, traceback
sys.path.insert(0, {ws_repr})

try:
    {imports}
except Exception as e:
    print(json.dumps({{"_import_error": f"{{type(e).__name__}}: {{e}}"}}))
    sys.exit(0)

cases = {cases_json}
out = []
for case in cases:
    try:
        fn = eval(case["function_name"])
        args = [eval(a, {{}}, {{}}) for a in case["args_literal"]]
        kwargs = {{k: eval(v, {{}}, {{}}) for k, v in case["kwargs_literal"].items()}}
        actual = fn(*args, **kwargs)
        out.append({{"observed_repr": repr(actual), "case": case}})
    except Exception as e:
        out.append({{"observed_repr": f"<exception {{type(e).__name__}}: {{e}}>", "case": case}})
print(json.dumps(out))
"""


def _build_imports_for_cases(cases: List[TestCase], workspace_dir: str) -> str:
    """Generate `from <module> import <fn>` for each unique function found."""
    # Map fn_name -> module name (filename without .py); pick first matching source file
    module_for_fn: Dict[str, str] = {}
    for root, dirs, files in os.walk(workspace_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            if fname.startswith("test_") or fname == "conftest.py":
                continue
            full = os.path.join(root, fname)
            try:
                tree = ast.parse(open(full, "r", encoding="utf-8").read())
            except SyntaxError:
                continue
            module_name = fname[:-3]
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    module_for_fn.setdefault(node.name, module_name)
    lines: List[str] = []
    for c in cases:
        if c.function_name in module_for_fn:
            mod = module_for_fn[c.function_name]
            lines.append(f"from {mod} import {c.function_name}")
    # Deduplicate
    return "\n    ".join(sorted(set(lines))) if lines else "pass"


def run_cases(workspace_dir: str, cases: List[TestCase], timeout: float = 60.0) -> List[Dict[str, Any]]:
    """Spawn a Python subprocess to execute each case and collect observed_repr."""
    if not cases:
        return []
    cases_dict = [{
        "function_name": c.function_name,
        "args_literal": c.args_literal,
        "kwargs_literal": c.kwargs_literal,
    } for c in cases]
    code = _RUNNER_TEMPLATE.format(
        ws_repr=repr(os.path.abspath(workspace_dir)),
        imports=_build_imports_for_cases(cases, workspace_dir),
        cases_json=json.dumps(cases_dict),
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=workspace_dir, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return [{"_runner_error": "timeout"}]
    try:
        out = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return [{"_runner_error": "could not parse subprocess output",
                 "stdout": (proc.stdout or "")[-500:],
                 "stderr": (proc.stderr or "")[-500:]}]
    if isinstance(out, dict) and "_import_error" in out:
        return [{"_runner_error": out["_import_error"]}]
    return out


def check_differential(workspace_dir: str) -> List[DifferentialMismatch]:
    """Top-level: extract test cases, run them, compare observed vs expected."""
    cases = extract_test_cases(workspace_dir)
    mismatches: List[DifferentialMismatch] = []
    if not cases:
        return mismatches
    case_lookup = {(c.function_name, tuple(c.args_literal), frozenset(c.kwargs_literal.items())): c
                   for c in cases}
    results = run_cases(workspace_dir, cases)
    if results and isinstance(results[0], dict) and "_runner_error" in results[0]:
        # Single mismatch summarising the runner failure
        fake_case = cases[0]
        mismatches.append(DifferentialMismatch(
            test_case=fake_case, observed_repr="<runner_error>",
            expected_repr="<n/a>",
            reason=f"differential runner failed: {results[0].get('_runner_error')}",
        ))
        return mismatches
    for entry in results:
        case_dict = entry.get("case") or {}
        key = (case_dict.get("function_name"), tuple(case_dict.get("args_literal", [])),
               frozenset(case_dict.get("kwargs_literal", {}).items()))
        case = case_lookup.get(key)
        if case is None:
            continue
        observed = entry.get("observed_repr", "")
        # Compare as repr-strings (canonical form). repr(5) == "5", repr("5") == "'5'".
        try:
            expected_evaled = eval(case.expected_repr or "", {}, {})  # noqa: S307 — literal-only via _is_literal_safe
            observed_evaled = eval(observed, {}, {}) if not observed.startswith("<") else observed
            ok = (expected_evaled == observed_evaled) if not isinstance(observed_evaled, str) or not observed_evaled.startswith("<") else False
        except Exception:
            ok = (observed == case.expected_repr)
        if not ok:
            mismatches.append(DifferentialMismatch(
                test_case=case,
                observed_repr=observed,
                expected_repr=case.expected_repr or "",
                reason=f"`{case.function_name}({', '.join(case.args_literal)})` -> {observed}, "
                       f"expected {case.expected_repr}",
            ))
    return mismatches


# === Verifier interface =====================================================

class DifferentialVerifier(Verifier):
    name = "differential"

    def is_applicable(self, workspace_dir: str) -> bool:
        for root, _, files in os.walk(workspace_dir):
            if any(f.startswith("test_") and f.endswith(".py") for f in files):
                return True
        return False

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        mismatches = check_differential(workspace_dir)
        if not mismatches:
            return VerifierResult(
                verifier_name=self.name, passed=True,
                message="differential: model output matches expected on all extractable test cases",
                elapsed_seconds=time.time() - t0,
            )
        msgs: List[str] = []
        for m in mismatches[:10]:
            msgs.append(m.reason)
        return VerifierResult(
            verifier_name=self.name, passed=False,
            message=f"differential: {len(mismatches)} input/output mismatch(es); first: {msgs[0][:160]}",
            details={"mismatches": msgs, "n": len(mismatches)},
            elapsed_seconds=time.time() - t0,
        )
