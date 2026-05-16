"""
benchmarks/czl_arbitrage/run_seven_arm.py — v3 seven-arm full-spectrum harness

Arms:
  A   Claude Opus 4.7 bare   (baseline)
  A2  Claude Opus 4.7 + CZL  (frontier + closure — hallucination remover)
  B1  gemma4:e4b bare
  B2  gemma4:e4b + CZL
  C1  deepseek-chat bare
  C2  deepseek-chat + CZL
  D2  minimax + CZL

Scenarios (4 single-fixture v3 scenarios — no difficulty grading):
  cross_file_refactor / type_annotation_completion /
  test_generation_for_existing_code / bug_fix_with_implicit_dependency

Per-trial we:
  1. git reset workspace
  2. run the arm (bare or CZL)
  3. wall-clock around invoke + final scenario.verify()
  4. capture post_state_files + per-trial objective_metrics
  5. write a v3 trial CIEU JSON to results/v3_trial_cieu/

Per-scenario, after all 35 trials (7 arms × 5):
  - run quality_assessment.run_quality_assessment (3 dimensions)
  - write per-scenario CSV + quality_assessment.json
  - the CIEU event MUST flag quality_assessment_completed=True AND
    a_vs_a2_judge_completed=True; otherwise r_t_plus_1 > 0

Total: 7 × 4 × 5 = 140 trials.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ystar.czl import get_scenario, get_backend  # noqa: E402
from ystar.czl.loop import CZLRun, run_scenario as run_czl_scenario  # noqa: E402
import ystar.czl.scenarios  # noqa: E402, F401  (registers all)
import ystar.czl.backends   # noqa: E402, F401

from benchmarks.czl_arbitrage.quality_assessment import (  # noqa: E402
    objective_metrics,
    run_quality_assessment,
)


# === arm registry ============================================================

ARMS: Dict[str, Dict[str, Any]] = {
    "A":  {"backend": "anthropic", "use_czl": False, "label": "claude-opus-4-7 bare"},
    "A2": {"backend": "anthropic", "use_czl": True,  "label": "claude-opus-4-7 + CZL"},
    "B1": {"backend": "ollama",    "use_czl": False, "label": "gemma4:e4b bare"},
    "B2": {"backend": "ollama",    "use_czl": True,  "label": "gemma4:e4b + CZL"},
    "C1": {"backend": "deepseek",  "use_czl": False, "label": "deepseek bare"},
    "C2": {"backend": "deepseek",  "use_czl": True,  "label": "deepseek + CZL"},
    "D2": {"backend": "minimax",   "use_czl": True,  "label": "minimax + CZL"},
}


# === scenario registry =======================================================
# Each scenario module exposes materialize_workspace(ws) -> task_description
# and has a registered Scenario instance accessible via get_scenario(name).
# `source_module` is for pytest-cov in objective_metrics (None when no
# meaningful source-under-test).

SCENARIOS: Dict[str, Dict[str, Optional[str]]] = {
    "cross_file_refactor": {
        "module": "ystar.czl.scenarios.cross_file_refactor",
        "source_module": None,
    },
    "type_annotation_completion": {
        "module": "ystar.czl.scenarios.type_annotation_completion",
        "source_module": "data_ops",
    },
    "test_generation_for_existing_code": {
        "module": "ystar.czl.scenarios.test_gen_for_existing",
        "source_module": "data_pipeline",
    },
    "bug_fix_with_implicit_dependency": {
        "module": "ystar.czl.scenarios.bug_fix_implicit_dep",
        "source_module": None,
    },
}


def materialize_for_scenario(scenario_name: str, workspace_dir: str) -> str:
    """Lay down the v3 scenario's fixture; returns task description."""
    cfg = SCENARIOS[scenario_name]
    import importlib
    mod = importlib.import_module(cfg["module"])  # type: ignore[arg-type]
    return mod.materialize_workspace(workspace_dir)


# === git workspace control ==================================================

def git_init_baseline(workspace_dir: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "config", "user.email", "bench@seven-arm"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "config", "user.name", "seven-arm-bench"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "v3 baseline"], cwd=workspace_dir, check=True)


def git_reset_workspace(workspace_dir: str) -> None:
    subprocess.run(["git", "reset", "--hard", "-q", "HEAD"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "clean", "-fdq"], cwd=workspace_dir, check=True)


# === per-trial CIEU log =====================================================

V3_TRIAL_DIR = "v3_trial_cieu"


def write_trial_cieu(out_root: str, record: Dict[str, Any]) -> None:
    d = Path(out_root) / V3_TRIAL_DIR
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{record['scenario']}_{record['arm']}_{record['trial']}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)


def _capture_workspace_files(workspace_dir: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for root, dirs, files in os.walk(workspace_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            full = os.path.join(root, fname)
            try:
                out[os.path.relpath(full, workspace_dir)] = open(full, "r", encoding="utf-8").read()
            except Exception:
                pass
    return out


# === one trial ==============================================================

def run_one_trial(
    *,
    arm_key: str,
    scenario_name: str,
    task_description: str,
    workspace_dir: str,
    trial_idx: int,
    out_root: str,
) -> Dict[str, Any]:
    arm_cfg = ARMS[arm_key]
    scenario = get_scenario(scenario_name)
    backend = get_backend(arm_cfg["backend"])
    source_module = SCENARIOS[scenario_name].get("source_module")

    record: Dict[str, Any] = {
        "arm": arm_key,
        "arm_label": arm_cfg["label"],
        "scenario": scenario_name,
        "trial": trial_idx,
        "backend": backend.name,
        "use_czl": arm_cfg["use_czl"],
        "converged": False,
        "iterations": 0,
        "wall_clock_seconds": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "failure_reason": "",
        "post_state_files": {},
        "objective_metrics": {},
    }

    if not backend.is_available():
        record["failure_reason"] = f"{backend.name} not configured"
        record["post_state_files"] = _capture_workspace_files(workspace_dir)
        write_trial_cieu(out_root, record)
        return record

    t0 = time.time()
    try:
        if arm_cfg["use_czl"]:
            req = CZLRun(
                task_description=task_description,
                scenario=scenario,
                backend=backend,
                workspace_dir=workspace_dir,
                max_iterations=8,
                strict=False,
                auto_undo_on_failure=False,
            )
            result = run_czl_scenario(req)
            record["converged"] = result.converged
            record["iterations"] = result.iterations
            record["input_tokens"] = result.total_input_tokens
            record["output_tokens"] = result.total_output_tokens
            record["cost_usd"] = result.total_cost_usd
            record["failure_reason"] = result.failure_reason
        else:
            plan_steps = scenario.plan(task_description, workspace_dir)
            first_prompt = plan_steps[0].user_prompt if plan_steps else task_description
            br = backend.invoke(
                system_prompt=scenario.system_prompt(),
                user_prompt=first_prompt,
                workspace_dir=workspace_dir,
                contract={},
            )
            for action in br.actions:
                scenario.apply_action(action, workspace_dir)
            verifier_results = scenario.verify(workspace_dir, {})
            violations = [v for v in verifier_results if not v.passed]
            record["iterations"] = 1
            record["input_tokens"] = br.input_tokens
            record["output_tokens"] = br.output_tokens
            record["cost_usd"] = br.cost_usd
            record["converged"] = not violations
            if violations:
                record["failure_reason"] = "; ".join(v.message for v in violations[:5])
    except Exception as exc:
        record["failure_reason"] = f"exception: {type(exc).__name__}: {exc}"[:500]
        record["traceback"] = traceback.format_exc()[-2000:]
        record["wall_clock_seconds"] = time.time() - t0
        record["post_state_files"] = _capture_workspace_files(workspace_dir)
        write_trial_cieu(out_root, record)
        return record

    record["wall_clock_seconds"] = time.time() - t0
    record["post_state_files"] = _capture_workspace_files(workspace_dir)
    # Dim 1 of quality_assessment is computed per-trial so each trial JSON
    # carries its own objective metrics; per-scenario summary aggregates.
    try:
        record["objective_metrics"] = objective_metrics(workspace_dir, source_module=source_module)
    except Exception as e:
        record["objective_metrics"] = {"error": f"{type(e).__name__}: {e}"}
    write_trial_cieu(out_root, record)
    return record


# === per-scenario runner ====================================================

def run_scenario_all_arms(
    scenario_name: str,
    arms: List[str],
    trials: int,
    workspace_root: str,
    out_root: str,
) -> Tuple[List[Dict[str, Any]], str]:
    workspace_dir = os.path.abspath(os.path.join(workspace_root, scenario_name))
    if os.path.isdir(workspace_dir):
        shutil.rmtree(workspace_dir)
    os.makedirs(workspace_dir, exist_ok=True)
    task_description = materialize_for_scenario(scenario_name, workspace_dir)
    git_init_baseline(workspace_dir)

    records: List[Dict[str, Any]] = []
    for arm in arms:
        for t in range(trials):
            git_reset_workspace(workspace_dir)
            print(f"[bench] {scenario_name} arm={arm} trial={t+1}/{trials}")
            rec = run_one_trial(
                arm_key=arm,
                scenario_name=scenario_name,
                task_description=task_description,
                workspace_dir=workspace_dir,
                trial_idx=t,
                out_root=out_root,
            )
            records.append(rec)
            time.sleep(0.5)
    return records, task_description


# === CSV writer (no post_state_files / objective_metrics dict in CSV) =======

def _write_records_csv(path: str, records: List[Dict[str, Any]]) -> None:
    if not records:
        Path(path).write_text("", encoding="utf-8")
        return
    flat: List[Dict[str, Any]] = []
    for r in records:
        rr = dict(r)
        rr.pop("post_state_files", None)
        rr.pop("traceback", None)
        # Flatten objective_metrics into top-level columns for CSV-readability.
        obj = rr.pop("objective_metrics", {}) or {}
        for k in ("cyclomatic_complexity_avg", "duplicated_lines_pct",
                  "test_coverage_pct", "mypy_strict_type_coverage_pct"):
            rr[f"obj_{k}"] = obj.get(k)
        flat.append(rr)
    keys: List[str] = []
    for r in flat:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in flat:
            w.writerow(r)


# === main =====================================================================

def main():
    p = argparse.ArgumentParser(description="v3 seven-arm full-spectrum benchmark")
    p.add_argument("--scenarios", default=",".join(SCENARIOS.keys()),
                   help="comma-separated scenario names")
    p.add_argument("--arms", default="A,A2,B1,B2,C1,C2,D2")
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--workspace-root", default="/tmp/czl_seven_arm")
    p.add_argument("--out", default="benchmarks/czl_arbitrage/results")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    arms = [a.strip() for a in args.arms.split(",")]
    scenarios = [s.strip() for s in args.scenarios.split(",")]
    for a in arms:
        if a not in ARMS:
            print(f"[bench] unknown arm: {a}", file=sys.stderr); sys.exit(1)
    for s in scenarios:
        if s not in SCENARIOS:
            print(f"[bench] unknown scenario: {s}", file=sys.stderr); sys.exit(1)

    if args.dry_run:
        planned = len(arms) * len(scenarios) * args.trials
        print(f"[bench] dry-run OK: {len(arms)} arms × {len(scenarios)} scenarios × {args.trials} trials = {planned} planned trials")
        for s in scenarios:
            ws = os.path.join(args.workspace_root, "_dryrun_" + s)
            if os.path.isdir(ws):
                shutil.rmtree(ws)
            os.makedirs(ws, exist_ok=True)
            task = materialize_for_scenario(s, ws)
            files = sorted(os.path.relpath(os.path.join(r, f), ws)
                           for r, _, fs in os.walk(ws) for f in fs)
            print(f"  {s}: files={files} task={task[:60]!r}")
            shutil.rmtree(ws)
        return 0

    os.makedirs(args.workspace_root, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    all_records: List[Dict[str, Any]] = []
    for s in scenarios:
        recs, task_desc = run_scenario_all_arms(s, arms, args.trials, args.workspace_root, args.out)
        all_records.extend(recs)
        scenario_csv = os.path.join(args.out, f"seven_arm_{s}_{ts}.csv")
        _write_records_csv(scenario_csv, recs)
        print(f"[bench] wrote {scenario_csv}")

        # quality_assessment hook — mandated per CZL self-protocol
        qa = run_quality_assessment(
            scenario=s, all_records=recs, out_root=args.out,
            task_description=task_desc,
            source_module=SCENARIOS[s].get("source_module"),
        )
        qa_path = os.path.join(args.out, f"seven_arm_{s}_{ts}_quality_assessment.json")
        Path(qa_path).write_text(json.dumps(qa, indent=2, default=str), encoding="utf-8")
        print(f"[bench] wrote {qa_path}")

    combined_csv = os.path.join(args.out, f"seven_arm_ALL_{ts}.csv")
    _write_records_csv(combined_csv, all_records)
    print(f"[bench] wrote {combined_csv}")


if __name__ == "__main__":
    sys.exit(main() or 0)
