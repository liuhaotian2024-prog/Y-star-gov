"""
branch_coverage_verifier.py — branch coverage gate (v3.4).

v3.4 changes vs v3.3:
  - T3: AdaptiveThresholdVerifier demoted to informational. Pass/fail uses
    real target (0.70). Baseline used only in the hint.
  - T2: message_natural is structured signal (missing branches) + 1-2
    sentence English hint. NO Chinese paragraphs.
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
    min_model_capacity = "small"
    feedback_complexity = "low"
    known_limitations = [
        "no branches in target → falls back to line coverage as the signal",
        "subprocess pytest under coverage requires `coverage` package present",
    ]

    def __init__(self, threshold: float = 0.70, timeout_seconds: float = 60.0):
        AdaptiveThresholdVerifier.__init__(self, target_threshold=threshold)
        self.threshold = float(threshold)
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
                message_natural=(
                    f"branch_coverage: coverage run timed out after {self.timeout_seconds}s.\n"
                    "Hint: your test suite likely has an infinite loop or extremely slow test — "
                    "narrow inputs so each test completes in <1s."
                ),
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
                message_natural="branch_coverage: coverage json export timed out.\nHint: rerun.",
                elapsed_seconds=time.time() - t0,
            )

        if not os.path.isfile(cov_json):
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="branch_coverage: coverage report missing",
                message_natural=(
                    "branch_coverage: coverage report missing.\n"
                    "Hint: your test file is probably not being discovered by pytest — "
                    "check it is named `test_*.py` and is in the same directory as the target."
                ),
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
                message_natural=f"branch_coverage: parse error ({e}).\nHint: rerun.",
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
        for fp, fdata in (cov.get("files") or {}).items():
            for br in (fdata.get("missing_branches") or []):
                missing_branches.append({"file": fp, "branch": br})

        # v3.4 T3: real-target pass/fail via simplified AdaptiveThresholdVerifier.
        passed_score, adaptive_msg = self.check_score(branch_pct / 100.0)
        details = {
            "branch_coverage_pct": branch_pct,
            "line_coverage_pct": round(line_pct, 1),
            "covered_branches": covered_branches,
            "total_branches": total_branches,
            "missing_branches": missing_branches[:20],
            "threshold_pct": self.threshold * 100.0,
            "baseline_iter1_pct": (self._calibration_score * 100.0) if self._calibration_score is not None else None,
            "call_count": self._call_count,
        }
        if passed_score:
            return VerifierResult(
                verifier_name=self.name, passed=True,
                message=f"branch_coverage: {branch_pct:.0f}% ({covered_branches}/{total_branches}) — {adaptive_msg}",
                message_natural=(
                    f"branch_coverage: {branch_pct:.0f}% "
                    f"({covered_branches}/{total_branches} branches) >= target {self.threshold*100:.0f}%.\n"
                    f"Hint: all if/else branches are exercised."
                ),
                details=details,
                elapsed_seconds=time.time() - t0,
            )
        # Identify if/else branches not taken — pick a sample for the English hint.
        # `missing_branches` entries are [src_line, dst_line] tuples where the
        # src is the conditional and dst is the not-taken successor.
        first_miss = missing_branches[0] if missing_branches else None
        hint_target = ""
        if first_miss and isinstance(first_miss.get("branch"), (list, tuple)) and len(first_miss["branch"]) == 2:
            src, dst = first_miss["branch"]
            hint_target = f" e.g. line {src} -> line {dst}"
        structured_feedback = (
            f"branch_coverage: {branch_pct:.0f}% ({covered_branches}/{total_branches}) "
            f"below target {self.threshold*100:.0f}% (gap {self.threshold - branch_pct/100:.2f}). "
            f"Missing branches:\n"
            + "\n".join(f"  - {os.path.basename(m['file'])}: branch {m['branch']}"
                       for m in missing_branches[:5])
        )
        details["actionable_feedback"] = structured_feedback
        natural_lines = [
            f"branch_coverage: {branch_pct:.0f}% "
            f"({covered_branches}/{total_branches} branches) below target {self.threshold*100:.0f}%; "
            f"gap {self.threshold - branch_pct/100:.2f}.",
            "Uncovered branches (one path of an if/else / for-else / try-except not exercised):",
        ]
        for m in missing_branches[:5]:
            fname = os.path.basename(m["file"])
            br = m["branch"]
            if isinstance(br, (list, tuple)) and len(br) == 2:
                natural_lines.append(f"  - {fname}: line {br[0]} -> line {br[1]} not taken")
            else:
                natural_lines.append(f"  - {fname}: branch {br}")
        natural_lines.append(
            f"Hint: add a test that triggers the OPPOSITE side of each `if` "
            f"or makes the `try` block raise (so the `except` runs){hint_target}."
        )
        return VerifierResult(
            verifier_name=self.name, passed=False,
            message=structured_feedback[:240],
            message_natural="\n".join(natural_lines),
            details=details,
            elapsed_seconds=time.time() - t0,
        )
