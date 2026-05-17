"""
ystar.czl.scenarios.test_gen_for_existing — v3.3 scenario #3

Indie task: write a complete pytest suite for an existing data_pipeline.py
module. Coverage ≥ 80%, includes edge cases and exception paths.

v3.3 changes:
  - B.2/B.3: Coverage80Verifier inherits AdaptiveThresholdVerifier;
    scenario caches verifier instances in __init__ and calls
    reset_for_trial() when contract["trial_id"] changes.
  - D.2: every inline verifier populates VerifierResult.message_natural
    (multi-line Chinese prose) for small-model audiences.
  - E.2: every verifier has applies_to_tasks / min_model_capacity /
    feedback_complexity / known_limitations.
  - E.3: verify() filters the verifier chain by `contract["model_tier"]`
    — verifiers whose min_model_capacity exceeds the model_tier are
    skipped. For gemma 4B (small), mutation_score (medium) is filtered
    out; branch_coverage (small) remains.
"""
from __future__ import annotations

import ast
import json
import os
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


# === inline verifiers (v3.3 with metadata + message_natural) ================

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
                    message_natural="pytest: 所有测试都通过.",
                    elapsed_seconds=time.time() - t0,
                )
            tb = (proc.stdout or "")[-1500:]
            # Extract failure summary lines for natural feedback
            fail_lines = [ln for ln in (proc.stdout or "").splitlines()
                          if " FAILED " in ln or "FAILED " in ln or ln.startswith("E  ")
                          or ln.lstrip().startswith("assert ")][:10]
            natural = "pytest: 测试运行失败.\n下面是失败的细节:\n" + "\n".join(f"  {ln}" for ln in fail_lines[:10])
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="pytest: failures",
                message_natural=natural,
                details={"stdout": tb},
                elapsed_seconds=time.time() - t0,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="pytest timed out",
                message_natural="pytest 超时了 (可能有死循环).",
                elapsed_seconds=time.time() - t0,
            )


class Coverage80Verifier(AdaptiveThresholdVerifier):
    """v3.3: now adaptive. target=0.80; floor=0.50. First call records
    baseline, subsequent calls require baseline + 0.10 (or target)."""
    name = "coverage_80"
    applies_to_tasks = ["test_generation_for_existing_code"]
    min_model_capacity = "small"
    feedback_complexity = "low"

    def __init__(self, target: float = 0.80):
        AdaptiveThresholdVerifier.__init__(self, target_threshold=target, floor_threshold=0.50)

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
                    message_natural="覆盖率报告没生成. 你的测试文件可能没被 pytest 发现, 或测试一上来就报错.",
                    details={"stdout": (proc.stdout or "")[-1000:]},
                    elapsed_seconds=time.time() - t0,
                )
            cov = json.loads(open(cov_path, "r", encoding="utf-8").read())
            pct = cov.get("totals", {}).get("percent_covered", 0.0)
            # Missing lines from coverage report
            missing_lines: List[Any] = []
            for fp, fdata in (cov.get("files") or {}).items():
                missing_lines.extend(fdata.get("missing_lines", [])[:10])
            passed_adaptive, adaptive_msg = self.check_score(pct / 100.0)
            details = {
                "percent_covered": pct,
                "missing_lines": missing_lines[:20],
                "adaptive_threshold_pct": self.effective_threshold() * 100.0,
                "adaptive_baseline": self._calibration_score,
                "adaptive_call_count": self._call_count,
            }
            if passed_adaptive:
                return VerifierResult(
                    verifier_name=self.name, passed=True,
                    message=f"coverage: {pct:.1f}% — {adaptive_msg}",
                    message_natural=f"行覆盖率 {pct:.0f}%. {adaptive_msg}.",
                    details=details, elapsed_seconds=time.time() - t0,
                )
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"coverage: {pct:.1f}% — {adaptive_msg}",
                message_natural=(
                    f"行覆盖率: {pct:.0f}% (需要 {self.effective_threshold()*100:.0f}%). "
                    f"下面这些行还没被任何测试执行到:\n"
                    + "\n".join(f"  data_pipeline.py 第 {ln} 行" for ln in missing_lines[:8])
                    + "\n修正方向: 给这些行写专门的 test_xxx 函数 (重点关注 try/except 分支 + edge case)."
                ),
                details=details,
                elapsed_seconds=time.time() - t0,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="coverage run timed out",
                message_natural="覆盖率测试运行超时.",
                elapsed_seconds=time.time() - t0,
            )
        except Exception as e:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"coverage check failed: {e}",
                message_natural=f"覆盖率检查异常: {e}",
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
        return VerifierResult(
            verifier_name=self.name, passed=passed,
            message=("≥1 pytest.raises found" if passed else "no pytest.raises found"),
            message_natural=(
                f"找到 {n} 个使用 `pytest.raises` 的异常路径测试."
                if passed
                else "测试里没有任何 `with pytest.raises(...)` 块. "
                     "请至少加一个测试: 用 `pytest.raises(ValueError)` 检查 normalize_email('') 会抛异常. "
                     "也建议覆盖 validate_record 缺字段 / 类型错的情况."
            ),
            details={"pytest_raises_count": n},
            elapsed_seconds=time.time() - t0,
        )


# === scenario ================================================================

class TestGenForExistingScenario(Scenario):
    name = "test_generation_for_existing_code"
    description = "Write pytest tests for data_pipeline.py; coverage ≥ 80%; exception paths covered"
    default_max_iterations = 6

    # v3.3 B.3: cached verifier instances. Live for the lifetime of the
    # singleton scenario; reset_for_trial called when trial_id changes.
    _last_verifier_call_order: List[str] = []

    def __init__(self) -> None:
        # Cache instances so AdaptiveThresholdVerifier subclasses retain
        # calibration state across iterations within one trial.
        self._cached_pytest = PytestPassVerifier()
        self._cached_coverage80 = Coverage80Verifier(target=0.80)
        self._cached_has_exc = HasExceptionTestsVerifier()
        self._cached_contract = ContractConsistencyVerifier()
        self._cached_differential = DifferentialVerifier()
        self._cached_mutation = MutationScoreVerifier(score_threshold=0.7)
        self._cached_branch = BranchCoverageVerifier(threshold=0.70)
        self._last_trial_id: Optional[str] = None

    # --- v3.3 helper for B.3 -------------------------------------------------
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
        """v3.3 verifier chain:

          pytest_pass → coverage80 → has_exception_tests
          → contract_consistency → differential   (inner)
          → [if all inner passed] {mutation_score, branch_coverage}
            (parallel final gates, filtered by model_tier)

        - B.3: cached verifier instances; reset_for_trial when trial_id changes.
        - E.3: chain composition filtered by model_tier — small tier
          (gemma 4B) skips mutation_score (min_capacity="medium"); branch_coverage
          (min_capacity="small") remains.
        - D.3: feedback layer chosen by loop.render_feedback_by_tier; we
          just emit results, the loop reads message_natural for small models.
        """
        contract = contract or {}
        self._reset_if_new_trial(contract)
        model_tier = contract.get("model_tier", "medium")

        results: List[VerifierResult] = []
        call_order: List[str] = []

        inner_candidates: List[Verifier] = [
            self._cached_pytest, self._cached_coverage80, self._cached_has_exc,
            self._cached_contract, self._cached_differential,
        ]
        # E.3 filter
        inner = [v for v in inner_candidates if tier_compatible(v.min_model_capacity, model_tier)]
        for v in inner:
            try:
                applicable = v.is_applicable(workspace_dir, contract)
            except TypeError:
                applicable = v.is_applicable(workspace_dir)  # legacy signature
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
