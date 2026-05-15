"""
benchmarks/czl_arbitrage/run_three_arm.py — A/B/C benchmark orchestrator

For ONE scenario, ONE workspace, run N trials per arm:

  ARM A: frontier baseline (no CZL)     — anthropic | openai
  ARM B: local zero-cost (with CZL)     — ollama
  ARM C: cheap API (with CZL)           — deepseek | minimax | qwen | kimi

Output: a CSV + summary table proving (or disproving) the arbitrage thesis.

This is the file that produces the data backing the README hero claim. It is
intentionally simple — no fancy stats, just averaged metrics across trials.
Statistical refinement (CIs, power analysis) can wait for v0.2.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

# Ensure local ystar imports work even before pip install
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ystar.czl import get_scenario, get_backend  # noqa: E402
from ystar.czl.loop import CZLRun, run_scenario  # noqa: E402
import ystar.czl.scenarios  # noqa: E402, F401
import ystar.czl.backends   # noqa: E402, F401


ARM_DEFAULTS = {
    "A": {"backend": "anthropic", "use_czl": False, "label": "frontier baseline"},
    "B": {"backend": "ollama",    "use_czl": True,  "label": "local + CZL"},
    "C": {"backend": "deepseek",  "use_czl": True,  "label": "cheap API + CZL"},
}


def run_one_trial(
    arm_key: str,
    arm_config: dict,
    scenario_name: str,
    workspace_dir: str,
    task_description: str,
    trial_idx: int,
) -> dict:
    """Run a single trial in one arm. Returns a flat record dict for CSV."""
    scenario = get_scenario(scenario_name)
    backend = get_backend(arm_config["backend"])
    if not backend.is_available():
        return {
            "arm": arm_key, "trial": trial_idx, "scenario": scenario_name,
            "backend": backend.name, "converged": False,
            "failure_reason": f"{backend.name} not configured (missing API key or service down)",
        }

    if arm_config["use_czl"]:
        request = CZLRun(
            task_description=task_description,
            scenario=scenario,
            backend=backend,
            workspace_dir=workspace_dir,
            max_iterations=8,
            strict=False,
            auto_undo_on_failure=False,   # benchmark mode — leave artifacts for analysis
        )
        result = run_scenario(request)
    else:
        # ARM A: no CZL retry loop — give the frontier model the same
        # well-formed first-iteration prompt the scenario hands to arms B/C
        # (file list + content + current verifier output), then verify ONCE.
        # Without sharing the prompt shape, arm A is artificially handicapped
        # — its raw task line ("fix all ruff and mypy errors") gives Opus no
        # workspace context and it returns prose instead of edit blocks.
        plan_steps = scenario.plan(task_description, workspace_dir)
        first_step_prompt = plan_steps[0].user_prompt if plan_steps else task_description
        backend_response = backend.invoke(
            system_prompt=scenario.system_prompt(),
            user_prompt=first_step_prompt,
            workspace_dir=workspace_dir,
            contract={},
        )
        # apply actions
        for action in backend_response.actions:
            scenario.apply_action(action, workspace_dir)
        # verify once
        verifier_results = scenario.verify(workspace_dir, {})
        violations = [v for v in verifier_results if not v.passed]
        result = type("FakeResult", (), {
            "converged": len(violations) == 0,
            "iterations": 1,
            "total_input_tokens": backend_response.input_tokens,
            "total_output_tokens": backend_response.output_tokens,
            "total_cost_usd": backend_response.cost_usd,
            "final_residual": float(len(violations)),
            "duration_seconds": 0.0,
            "failure_reason": "" if not violations else f"violations: {[v.message for v in violations[:3]]}",
        })()

    return {
        "arm": arm_key,
        "arm_label": arm_config["label"],
        "trial": trial_idx,
        "scenario": scenario_name,
        "backend": backend.name,
        "use_czl": arm_config["use_czl"],
        "converged": result.converged,
        "iterations": result.iterations,
        "input_tokens": result.total_input_tokens,
        "output_tokens": result.total_output_tokens,
        "cost_usd": result.total_cost_usd,
        "final_residual": result.final_residual,
        "duration_s": result.duration_seconds,
        "failure_reason": getattr(result, "failure_reason", ""),
    }


def summarize(records: list[dict]) -> dict:
    """Group records by arm, compute mean/median metrics for the summary table."""
    by_arm: dict[str, list[dict]] = {}
    for r in records:
        by_arm.setdefault(r["arm"], []).append(r)

    summary: dict[str, dict] = {}
    for arm, rs in by_arm.items():
        n = len(rs)
        converged = [r for r in rs if r.get("converged")]
        summary[arm] = {
            "n_trials": n,
            "n_converged": len(converged),
            "convergence_rate": len(converged) / n if n else 0,
            "mean_iterations": statistics.mean([r.get("iterations") or 0 for r in rs]) if rs else 0,
            "mean_cost_usd": statistics.mean([r.get("cost_usd") or 0.0 for r in rs]) if rs else 0,
            "mean_duration_s": statistics.mean([r.get("duration_s") or 0.0 for r in rs]) if rs else 0,
            "total_cost_usd": sum((r.get("cost_usd") or 0.0) for r in rs),
        }
    return summary


def print_summary_table(summary: dict) -> None:
    print()
    print("=" * 80)
    print("THREE-ARM BENCHMARK SUMMARY")
    print("=" * 80)
    print(f"{'ARM':6}{'n':>4}{'converged':>12}{'iters':>8}{'cost ($)':>12}{'duration (s)':>16}")
    print("-" * 80)
    for arm in sorted(summary.keys()):
        s = summary[arm]
        conv_str = f"{s['n_converged']}/{s['n_trials']} ({100*s['convergence_rate']:.0f}%)"
        print(
            f"{arm:6}{s['n_trials']:>4}{conv_str:>14}"
            f"{s['mean_iterations']:>8.1f}{s['mean_cost_usd']:>12.4f}{s['mean_duration_s']:>16.1f}"
        )
    print("=" * 80)

    # arbitrage statement (the headline)
    if "A" in summary and "C" in summary:
        a = summary["A"]
        c = summary["C"]
        if c["mean_cost_usd"] > 0 and a["mean_cost_usd"] > 0:
            cost_ratio = a["mean_cost_usd"] / c["mean_cost_usd"]
            quality_ratio = c["convergence_rate"] / max(a["convergence_rate"], 1e-9)
            print()
            print(f"ARBITRAGE OUTCOME (arm A vs arm C):")
            print(f"  Cost ratio:     C is {cost_ratio:.0f}× cheaper than A")
            print(f"  Quality ratio:  C reaches {100*quality_ratio:.0f}% of A's convergence rate")
            print(f"  Hero claim hit: {'YES' if quality_ratio >= 0.9 and cost_ratio >= 20 else 'no — refine and retry'}")
    print()


def main():
    p = argparse.ArgumentParser(description="CZL three-arm benchmark")
    p.add_argument("--scenario", "-s", required=True)
    p.add_argument("--workspace", "-w", default=".")
    p.add_argument("--task", "-t", required=True)
    p.add_argument("--arms", default="A,B,C")
    p.add_argument("--trials", type=int, default=10)
    p.add_argument("--out", default="benchmarks/czl_arbitrage/results")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    arms = [a.strip() for a in args.arms.split(",")]

    # Snapshot the pristine workspace once. Each trial restores from this
    # snapshot before running, so trials are independent samples — without
    # this, trial 2/3 would see the already-fixed output from trial 1 and
    # report a fake "instant convergence".
    workspace_abs = os.path.abspath(args.workspace)
    snapshot = tempfile.mkdtemp(prefix="czl_bench_snap_")
    shutil.rmtree(snapshot)
    shutil.copytree(workspace_abs, snapshot,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    print(f"[bench] snapshotted pristine workspace -> {snapshot}")

    def reset_workspace() -> None:
        if os.path.isdir(workspace_abs):
            shutil.rmtree(workspace_abs)
        shutil.copytree(snapshot, workspace_abs)

    records: list[dict] = []
    for arm in arms:
        if arm not in ARM_DEFAULTS:
            print(f"[bench] unknown arm '{arm}', skipping")
            continue
        for t in range(args.trials):
            reset_workspace()
            print(f"[bench] arm={arm} trial={t+1}/{args.trials} (workspace reset from snapshot)")
            rec = run_one_trial(arm, ARM_DEFAULTS[arm], args.scenario, workspace_abs, args.task, t)
            records.append(rec)
            time.sleep(1)  # be polite to APIs

    # write CSV
    ts = time.strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(args.out, f"{args.scenario}_{ts}.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0].keys()) if records else [])
        writer.writeheader()
        writer.writerows(records)
    print(f"[bench] wrote {csv_path}")

    # summary
    summary = summarize(records)
    print_summary_table(summary)
    with open(os.path.join(args.out, f"{args.scenario}_{ts}_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
