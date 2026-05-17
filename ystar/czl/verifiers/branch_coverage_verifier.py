"""
branch_coverage_verifier.py — adaptive branch coverage gate (v3.3).

v3.3 changes:
  - B.2: inherits AdaptiveThresholdVerifier — calibration round on first
    call records the baseline; iter 2+ requires baseline+0.10 or target,
    whichever is easier. Floor = target - 0.30.
  - D.2: VerifierResult.message_natural populated (prose for small models).
  - E.2: class metadata set.

Activates when contract dict has `_mutation_target_file` (same activation
surface as MutationScoreVerifier — they're both test-generation final
gates). Threshold target = 0.70 (70% branch coverage).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any, Dict, List, Optional

from ystar.czl.verifiers.base import Verifier, VerifierResult, AdaptiveThresholdVerifier


class BranchCoverageVerifier(AdaptiveThresholdVerifier):
    name = "branch_coverage"
    is_final_gate = True
    # E.2 metadata
    applies_to_tasks = ["test_generation_for_existing_code"]
    min_model_capacity = "small"  # branch-coverage is cheap, every tier can target it
    feedback_complexity = "low"
    known_limitations = [
        "no branches in target → falls back to line coverage as the signal",
        "subprocess pytest under coverage requires `coverage` package present",
    ]

    def __init__(self, threshold: float = 0.70, timeout_seconds: float = 60.0):
        AdaptiveThresholdVerifier.__init__(self, target_threshold=threshold,
                                            floor_threshold=max(0.0, threshold - 0.30))
        self.threshold = float(threshold)  # preserved attr for log readers
        self.timeout_seconds = float(timeout_seconds)

    def is_applicable(self, workspace_dir: str, contract: Optional[Dict[str, Any]] = None) -> bool:
        target = (contract or {}).get("_mutation_target_file")
        if not target:
            return False
        if not os.path.isfile(os.path.join(workspace_dir, target)):
            return False
        for root, _, files in os.walk(workspace_dir):
            if any(f.startswith("test_") and f.endswith(".py") for f in files):
                return True
        return False

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        target_rel = contract["_mutation_target_file"]
        cov_json = os.path.join(workspace_dir, ".branchcov.json")
        for f in (".coverage", cov_json):
            try:
                os.unlink(os.path.join(workspace_dir, f))
            except FileNotFoundError:
                pass

        source_dir = os.path.dirname(target_rel) or "."
        try:
            run_proc = subprocess.run(
                ["python3.11", "-m", "coverage", "run", "--branch",
                 f"--source={source_dir}",
                 "-m", "pytest", "-x", "-q", "--tb=no", "--no-header"],
                cwd=workspace_dir, capture_output=True, text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"branch_coverage: coverage run timed out after {self.timeout_seconds}s",
                message_natural=f"覆盖率检查超时 ({self.timeout_seconds}s). 你的测试可能有死循环或太慢.",
                elapsed_seconds=time.time() - t0,
            )

        try:
            report_proc = subprocess.run(
                ["python3.11", "-m", "coverage", "json",
                 f"--include={target_rel}", "-o", cov_json],
                cwd=workspace_dir, capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="branch_coverage: coverage json export timed out",
                message_natural="覆盖率导出超时.",
                elapsed_seconds=time.time() - t0,
            )

        if not os.path.isfile(cov_json):
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="branch_coverage: coverage report missing",
                message_natural="覆盖率报告没生成. 可能是你的测试根本没运行 — 检查 test 文件是否能被 pytest 发现.",
                details={"run_stdout": (run_proc.stdout or "")[-500:],
                         "report_stdout": (report_proc.stdout or "")[-500:]},
                elapsed_seconds=time.time() - t0,
            )

        try:
            cov = json.loads(open(cov_json, "r", encoding="utf-8").read())
        except Exception as e:
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message=f"branch_coverage: could not parse json ({e})",
                message_natural=f"覆盖率报告解析失败: {e}",
                elapsed_seconds=time.time() - t0,
            )
        finally:
            try:
                os.unlink(cov_json)
            except FileNotFoundError:
                pass

        totals = cov.get("totals", {})
        covered_branches = totals.get("covered_branches", 0)
        total_branches = totals.get("num_branches", 0)
        line_pct = totals.get("percent_covered", 0.0)
        if total_branches > 0:
            branch_pct = round(100.0 * covered_branches / total_branches, 1)
        else:
            branch_pct = line_pct

        missing_branches: List[Any] = []
        files = cov.get("files") or {}
        for fp, fdata in files.items():
            for br in (fdata.get("missing_branches") or []):
                missing_branches.append({"file": fp, "branch": br})

        # v3.3 B.2: adaptive threshold via base class.
        passed_adaptive, adaptive_msg = self.check_score(branch_pct / 100.0)
        details = {
            "branch_coverage_pct": branch_pct,
            "line_coverage_pct": round(line_pct, 1),
            "covered_branches": covered_branches,
            "total_branches": total_branches,
            "missing_branches": missing_branches[:20],
            "threshold_pct": self.threshold * 100.0,
            "adaptive_threshold_pct": self.effective_threshold() * 100.0,
            "adaptive_baseline": self._calibration_score,
            "adaptive_call_count": self._call_count,
        }
        if passed_adaptive:
            natural = (
                f"分支覆盖率 {branch_pct:.0f}% ({covered_branches}/{total_branches} 分支被测试覆盖). "
                f"{adaptive_msg}."
            )
            return VerifierResult(
                verifier_name=self.name, passed=True,
                message=f"branch_coverage: {branch_pct:.0f}% ({covered_branches}/{total_branches}) — {adaptive_msg}",
                message_natural=natural,
                details=details,
                elapsed_seconds=time.time() - t0,
            )
        # Structured feedback (large model)
        structured_feedback = (
            f"branch_coverage: {branch_pct:.0f}% ({covered_branches}/{total_branches}) below "
            f"adaptive threshold {self.effective_threshold()*100:.0f}%. Missing branches:\n"
            + "\n".join(f"  - {m['file']}: branch {m['branch']}" for m in missing_branches[:5])
        )
        details["actionable_feedback"] = structured_feedback
        # Natural feedback (small model)
        natural_lines = [
            f"分支覆盖率: {branch_pct:.0f}% (只覆盖了 {covered_branches}/{total_branches} 分支), "
            f"需要 {self.effective_threshold()*100:.0f}%.",
            "下面这些分支 (if/else 的某一条路径) 没被你的测试覆盖到:",
        ]
        for m in missing_branches[:5]:
            fname = os.path.basename(m["file"])
            br = m["branch"]
            if isinstance(br, (list, tuple)) and len(br) == 2:
                natural_lines.append(f"  • {fname}: 从第 {br[0]} 行跳到第 {br[1]} 行的那条路径")
            else:
                natural_lines.append(f"  • {fname}: 分支 {br}")
        natural_lines.append("修正方向: 给这些分支专门加一两个测试用例 (比如 if 条件不满足时的情况).")
        return VerifierResult(
            verifier_name=self.name, passed=False,
            message=structured_feedback[:240],
            message_natural="\n".join(natural_lines),
            details=details,
            elapsed_seconds=time.time() - t0,
        )
