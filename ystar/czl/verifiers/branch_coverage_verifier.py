"""
branch_coverage_verifier.py — outcome-based branch coverage gate.

A pytest+coverage subprocess wrapper. Activates when contract dict has
`_mutation_target_file` (same activation surface as MutationScoreVerifier
— they're both test-generation gates and live as parallel final gates).

Coverage line vs branch: branch is the stricter signal — captures
"agent's tests exercised both sides of every if/while/for" rather than
"agent's tests executed every line at least once". v3.1 showed
test_coverage_pct (line) saturated at 100% on cells where mutation_score
was still 0.93 — line coverage was a weak quality signal. Branch
coverage catches the gap.

Threshold: 0.70 (70%). Below → r=1 with surviving-branch detail in
VerifierResult.details. Like MutationScoreVerifier, is_final_gate=True
so it only fires after inner verifiers pass.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ystar.czl.verifiers.base import Verifier, VerifierResult


class BranchCoverageVerifier(Verifier):
    name = "branch_coverage"
    is_final_gate = True

    def __init__(self, threshold: float = 0.70, timeout_seconds: float = 60.0):
        self.threshold = float(threshold)
        self.timeout_seconds = float(timeout_seconds)

    def is_applicable(self, workspace_dir: str, contract: Dict[str, Any]) -> bool:
        target = (contract or {}).get("_mutation_target_file")
        if not target:
            return False
        if not os.path.isfile(os.path.join(workspace_dir, target)):
            return False
        # require at least one test_*.py in workspace
        for root, _, files in os.walk(workspace_dir):
            if any(f.startswith("test_") and f.endswith(".py") for f in files):
                return True
        return False

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        t0 = time.time()
        target_rel = contract["_mutation_target_file"]
        cov_json = os.path.join(workspace_dir, ".branchcov.json")
        # remove stale .coverage to avoid carrying state across CZL iters
        for f in (".coverage", cov_json):
            try:
                os.unlink(os.path.join(workspace_dir, f))
            except FileNotFoundError:
                pass

        # Run pytest under coverage with --branch
        # Note: --source=<file> doesn't work for non-package files; use --source=. and filter via include
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
                elapsed_seconds=time.time() - t0,
            )

        if not os.path.isfile(cov_json):
            return VerifierResult(
                verifier_name=self.name, passed=False,
                message="branch_coverage: coverage report missing",
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
                elapsed_seconds=time.time() - t0,
            )
        finally:
            try:
                os.unlink(cov_json)
            except FileNotFoundError:
                pass

        # Aggregate from totals
        totals = cov.get("totals", {})
        covered_branches = totals.get("covered_branches", 0)
        total_branches = totals.get("num_branches", 0)
        line_pct = totals.get("percent_covered", 0.0)
        # branch percent: covered / total (some files have 0 branches)
        if total_branches > 0:
            branch_pct = round(100.0 * covered_branches / total_branches, 1)
        else:
            # No branches in target → fall back to line coverage as the signal
            branch_pct = line_pct

        # Identify missing branch ranges per target file
        missing_branches: List[Any] = []
        files = cov.get("files") or {}
        for fp, fdata in files.items():
            for br in (fdata.get("missing_branches") or []):
                missing_branches.append({"file": fp, "branch": br})

        passed = branch_pct >= (self.threshold * 100.0)
        details = {
            "branch_coverage_pct": branch_pct,
            "line_coverage_pct": round(line_pct, 1),
            "covered_branches": covered_branches,
            "total_branches": total_branches,
            "missing_branches": missing_branches[:20],
            "threshold_pct": self.threshold * 100.0,
        }
        if passed:
            return VerifierResult(
                verifier_name=self.name, passed=True,
                message=f"branch_coverage: {branch_pct:.0f}% (covered {covered_branches}/{total_branches}) ≥ threshold {self.threshold*100:.0f}%",
                details=details,
                elapsed_seconds=time.time() - t0,
            )
        feedback = (
            f"branch_coverage: {branch_pct:.0f}% (covered {covered_branches}/{total_branches}) "
            f"below {self.threshold*100:.0f}%. Missing branches:\n"
            + "\n".join(f"  - {m['file']}: branch {m['branch']}" for m in missing_branches[:5])
        )
        details["actionable_feedback"] = feedback
        return VerifierResult(
            verifier_name=self.name, passed=False,
            message=feedback[:240],
            details=details,
            elapsed_seconds=time.time() - t0,
        )
