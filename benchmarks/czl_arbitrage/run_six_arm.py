"""
benchmarks/czl_arbitrage/run_six_arm.py — 6-arm × 3-scenario × 3-difficulty × N-trial harness

Productivity-arbitrage experiment: can a cheap LLM + CZL reach the same
output quality on indie-developer tasks (lint_fix / bug_fix / test_gen) as
Claude Opus 4.7 bare?

Arms:
  A   Claude Opus 4.7 bare       (1 prompt + 1 verify, no CZL loop)
  B1  Ollama gemma4:e4b bare     (1 prompt + 1 verify, no CZL loop)
  B2  Ollama gemma4:e4b + CZL    (full residual loop)
  C1  DeepSeek bare              (1 prompt + 1 verify, no CZL loop)
  C2  DeepSeek + CZL             (full residual loop)
  D2  MiniMax + CZL              (full residual loop)

Each trial:
  1. git reset --hard HEAD on the workspace (pristine fixture).
  2. Run the arm (bare or CZL) against the difficulty-graded fixture.
  3. Wall-clock around step 2 INCLUDING the final scenario.verify().
  4. Capture final per-file source contents for later semantic-judge scoring.
  5. Write one CSV row + one per-trial CIEU JSON.

No adversarial payloads. Task descriptions come from the fixture in
ystar.czl.scenarios.fixtures and read like a casual indie dev message.
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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Allow `python3 benchmarks/czl_arbitrage/run_six_arm.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ystar.czl import get_scenario, get_backend  # noqa: E402
from ystar.czl.loop import CZLRun, run_scenario  # noqa: E402
from ystar.czl.scenarios.fixtures import get_fixture, available as available_cells  # noqa: E402
import ystar.czl.scenarios  # noqa: E402, F401
import ystar.czl.backends   # noqa: E402, F401


# === arm registry ============================================================

ARMS: Dict[str, Dict[str, Any]] = {
    "A":  {"backend": "anthropic", "use_czl": False, "label": "claude-opus-4-7 bare"},
    "B1": {"backend": "ollama",    "use_czl": False, "label": "gemma4:e4b bare"},
    "B2": {"backend": "ollama",    "use_czl": True,  "label": "gemma4:e4b + CZL"},
    "C1": {"backend": "deepseek",  "use_czl": False, "label": "deepseek bare"},
    "C2": {"backend": "deepseek",  "use_czl": True,  "label": "deepseek + CZL"},
    "D2": {"backend": "minimax",   "use_czl": True,  "label": "minimax + CZL"},
}


# === fixture materialization ================================================
# All fixtures live in ystar.czl.scenarios.fixtures. We dispatch by (scenario, difficulty).

def materialize_for_cell(scenario: str, difficulty: str, workspace_dir: str) -> str:
    """Lay down the pristine baseline for (scenario, difficulty). Returns task description."""
    files, task = get_fixture(scenario, difficulty)
    os.makedirs(workspace_dir, exist_ok=True)
    for rel, content in files.items():
        full = os.path.join(workspace_dir, rel)
        os.makedirs(os.path.dirname(full) or workspace_dir, exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
    return task


# === git workspace control ==================================================

def git_init_baseline(workspace_dir: str) -> None:
    """Initialize a git repo and commit the pristine baseline as HEAD."""
    subprocess.run(["git", "init", "-q"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "config", "user.email", "bench@six-arm"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "config", "user.name", "six-arm-bench"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "add", "-A"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline fixture"], cwd=workspace_dir, check=True)


def git_reset_workspace(workspace_dir: str) -> None:
    """Force the workspace back to the baseline commit."""
    subprocess.run(["git", "reset", "--hard", "-q", "HEAD"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "clean", "-fdq"], cwd=workspace_dir, check=True)


# === per-trial CIEU log =====================================================

def _per_trial_log_dir(out_root: str) -> Path:
    p = Path(out_root) / "trial_cieu"
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_trial_cieu(out_root: str, record: Dict[str, Any]) -> None:
    p = _per_trial_log_dir(out_root) / f"{record['scenario']}_{record['difficulty']}_{record['arm']}_{record['trial']}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)


def _capture_workspace_files(workspace_dir: str) -> Dict[str, str]:
    """Snapshot all .py files in the workspace post-trial — feeds the semantic judge."""
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

def _final_metric_counts(violations: List[Any], workspace_dir: str) -> Dict[str, int]:
    """Count final ruff / mypy / pytest / invariant residuals — used by the CSV row.
    Runs each tool once at end-of-trial regardless of which verifiers fired."""
    out = {"final_ruff_errors": 0, "final_mypy_errors": 0,
           "final_pytest_failures": 0, "final_invariant_violations": 0}
    # ruff
    try:
        rp = subprocess.run(
            ["ruff", "check", "--output-format=concise", "."],
            cwd=workspace_dir, capture_output=True, text=True, timeout=30,
        )
        if rp.returncode != 0:
            out["final_ruff_errors"] = max(0, sum(1 for ln in rp.stdout.splitlines() if ln.strip() and ":" in ln))
    except Exception:
        pass
    # mypy
    try:
        mp = subprocess.run(
            ["mypy", "--show-error-codes", "--no-error-summary", "."],
            cwd=workspace_dir, capture_output=True, text=True, timeout=60,
        )
        if mp.returncode != 0:
            out["final_mypy_errors"] = sum(1 for ln in mp.stdout.splitlines() if ": error:" in ln)
    except Exception:
        pass
    # pytest
    try:
        pt = subprocess.run(
            ["pytest", "-q", "--tb=no", "--no-header"],
            cwd=workspace_dir, capture_output=True, text=True, timeout=120,
        )
        if pt.returncode != 0:
            import re as _re
            m = _re.search(r"(\d+) failed", pt.stdout or "")
            out["final_pytest_failures"] = int(m.group(1)) if m else 1
    except Exception:
        pass
    # v21 invariant count — use the verifier list count we already have
    out["final_invariant_violations"] = sum(1 for v in (violations or []) if not getattr(v, "passed", True))
    return out


def run_one_trial(
    *,
    arm_key: str,
    scenario_name: str,
    difficulty: str,
    task_description: str,
    workspace_dir: str,
    trial_idx: int,
    out_root: str,
) -> Dict[str, Any]:
    arm_cfg = ARMS[arm_key]
    scenario = get_scenario(scenario_name)
    backend = get_backend(arm_cfg["backend"])

    record: Dict[str, Any] = {
        "arm": arm_key,
        "arm_label": arm_cfg["label"],
        "scenario": scenario_name,
        "difficulty": difficulty,
        "trial": trial_idx,
        "backend": backend.name,
        "use_czl": arm_cfg["use_czl"],
        "converged": False,
        "iterations": 0,
        "wall_clock_seconds": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "final_ruff_errors": 0,
        "final_mypy_errors": 0,
        "final_pytest_failures": 0,
        "failure_reason": "",
        "post_state_files": {},
        "semantic_correctness_score": None,
    }

    if not backend.is_available():
        record["failure_reason"] = f"{backend.name} not configured"
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
            result = run_scenario(req)
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
        record["wall_clock_seconds"] = time.time() - t0
        record["traceback"] = traceback.format_exc()[-2000:]
        record["post_state_files"] = _capture_workspace_files(workspace_dir)
        write_trial_cieu(out_root, record)
        return record

    final_verifier_results = scenario.verify(workspace_dir, {})
    metrics = _final_metric_counts(final_verifier_results, workspace_dir)
    record.update(metrics)
    record["post_state_files"] = _capture_workspace_files(workspace_dir)
    record["wall_clock_seconds"] = time.time() - t0
    write_trial_cieu(out_root, record)
    return record


# === orchestrator ===========================================================

def run_cell_all_arms(
    scenario: str,
    difficulty: str,
    arms: List[str],
    trials: int,
    workspace_root: str,
    out_root: str,
) -> List[Dict[str, Any]]:
    """One (scenario, difficulty) cell: build workspace once, reset before each trial."""
    workspace_dir = os.path.abspath(os.path.join(workspace_root, f"{scenario}_{difficulty}"))
    if os.path.isdir(workspace_dir):
        shutil.rmtree(workspace_dir)
    os.makedirs(workspace_dir, exist_ok=True)
    task_description = materialize_for_cell(scenario, difficulty, workspace_dir)
    git_init_baseline(workspace_dir)

    records: List[Dict[str, Any]] = []
    for arm in arms:
        for t in range(trials):
            git_reset_workspace(workspace_dir)
            print(f"[bench] {scenario}/{difficulty} arm={arm} trial={t+1}/{trials}")
            rec = run_one_trial(
                arm_key=arm,
                scenario_name=scenario,
                difficulty=difficulty,
                task_description=task_description,
                workspace_dir=workspace_dir,
                trial_idx=t,
                out_root=out_root,
            )
            records.append(rec)
            time.sleep(1)
    return records


# === cross-tab reporting ====================================================

def _by(records: List[Dict[str, Any]], key: str) -> Dict[Any, List[Dict[str, Any]]]:
    out: Dict[Any, List[Dict[str, Any]]] = {}
    for r in records:
        out.setdefault(r[key], []).append(r)
    return out


def print_cross_tabs(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    print("\n" + "=" * 90)
    print("CROSS-TAB 1: result_class by arm × scenario  (C=converged S=silent_failure H=honest_refusal)")
    print("=" * 90)
    scenarios = sorted({r["scenario"] for r in records})
    arms = sorted({r["arm"] for r in records})
    header = "ARM  " + "".join(f"{s:>32}" for s in scenarios)
    print(header)
    for a in arms:
        cells = []
        for s in scenarios:
            cell = [r for r in records if r["arm"] == a and r["scenario"] == s]
            c = sum(1 for r in cell if r["result_class"] == "converged")
            si = sum(1 for r in cell if r["result_class"] == "silent_failure")
            h = sum(1 for r in cell if r["result_class"] == "honest_refusal")
            sk = sum(1 for r in cell if r["result_class"] == "skipped")
            cells.append(f"C={c} S={si} H={h} K={sk}")
        print(f"{a:4} " + "".join(f"{c:>32}" for c in cells))

    print("\n" + "=" * 90)
    print("CROSS-TAB 2: per-payload trip-rate by arm × scenario × payload")
    print("=" * 90)
    print(f"{'arm':5}{'scenario':24}{'payload':22}{'trip_rate':>12}")
    for a in arms:
        for s in scenarios:
            cell = [r for r in records if r["arm"] == a and r["scenario"] == s]
            if not cell:
                continue
            all_payloads = set()
            for r in cell:
                for p in r.get("adversarial_payloads_triggered") or []:
                    all_payloads.add(p)
            # also list payloads from the scenario class
            scen = get_scenario(SCENARIO_DISPATCH[s])
            for p in getattr(scen.__class__, "ADVERSARIAL_PAYLOADS", []):
                all_payloads.add(p["id"])
            for p in sorted(all_payloads):
                trips = sum(1 for r in cell if p in (r.get("adversarial_payloads_triggered") or []))
                rate = trips / len(cell) if cell else 0
                print(f"{a:5}{s:24}{p:22}{trips}/{len(cell)} ({rate*100:.0f}%)".rjust(12)[:90])

    print("\n" + "=" * 90)
    print("CROSS-TAB 3: cost ratio (A vs C2 / B2 / D2) — per scenario, converged trials only")
    print("=" * 90)
    summary: Dict[str, Any] = {"cost_ratio": {}, "wallclock": {}, "ablation": {}, "silent_rates": {}}
    for s in scenarios:
        a_cells = [r for r in records if r["arm"] == "A" and r["scenario"] == s and r["converged"]]
        a_mean = statistics.mean([r["cost_usd"] for r in a_cells]) if a_cells else 0.0
        for arm in ("B2", "C2", "D2"):
            x_cells = [r for r in records if r["arm"] == arm and r["scenario"] == s and r["converged"]]
            x_mean = statistics.mean([r["cost_usd"] for r in x_cells]) if x_cells else 0.0
            ratio = (a_mean / x_mean) if x_mean > 0 else (float("inf") if a_mean > 0 else 0.0)
            print(f"  {s:24} A=${a_mean:.5f}  {arm}=${x_mean:.5f}  ratio={ratio:.1f}x")
            summary["cost_ratio"].setdefault(s, {})[arm] = ratio

    print("\n" + "=" * 90)
    print("CROSS-TAB 4: wall-clock per arm per scenario  (mean / p90)")
    print("=" * 90)
    print(f"{'arm':5}{'scenario':24}{'n':>4}{'mean_s':>10}{'p90_s':>10}")
    for a in arms:
        for s in scenarios:
            cell = [r["wall_clock_seconds"] for r in records if r["arm"] == a and r["scenario"] == s]
            if not cell:
                continue
            mean = statistics.mean(cell)
            p90 = sorted(cell)[max(0, int(0.9 * len(cell)) - 1)]
            print(f"{a:5}{s:24}{len(cell):>4}{mean:>10.2f}{p90:>10.2f}")
            summary["wallclock"].setdefault(s, {})[a] = {"mean": mean, "p90": p90}

    print("\n" + "=" * 90)
    print("CROSS-TAB 5: CZL ablation contribution  (converged_rate_with_CZL - converged_rate_bare)")
    print("=" * 90)
    for s in scenarios:
        def conv_rate(arm: str) -> float:
            cell = [r for r in records if r["arm"] == arm and r["scenario"] == s]
            return (sum(1 for r in cell if r["converged"]) / len(cell)) if cell else 0.0
        for pair in (("B1", "B2"), ("C1", "C2")):
            bare, czl = pair
            delta = conv_rate(czl) - conv_rate(bare)
            print(f"  {s:24} {bare}->{czl}: {conv_rate(bare)*100:.0f}% -> {conv_rate(czl)*100:.0f}% (Δ={delta*100:+.0f} pp)")
            summary["ablation"].setdefault(s, {})[f"{bare}->{czl}"] = delta

    print("\n" + "=" * 90)
    print("CROSS-TAB 6: silent_failure rate — A (bare) vs CZL arms")
    print("=" * 90)
    for s in scenarios:
        def silent_rate(arm: str) -> float:
            cell = [r for r in records if r["arm"] == arm and r["scenario"] == s]
            return (sum(1 for r in cell if r["result_class"] == "silent_failure") / len(cell)) if cell else 0.0
        print(f"  {s:24}  A={silent_rate('A')*100:.0f}%  B2={silent_rate('B2')*100:.0f}%  C2={silent_rate('C2')*100:.0f}%  D2={silent_rate('D2')*100:.0f}%")
        summary["silent_rates"][s] = {a: silent_rate(a) for a in ("A", "B2", "C2", "D2")}
    print()
    return summary


def _write_records_csv(path: str, records: List[Dict[str, Any]]) -> None:
    """CSV writer robust to per-row key variance (e.g. traceback field on exceptions)."""
    if not records:
        with open(path, "w", newline="") as f:
            f.write("")
        return
    keys: List[str] = []
    for r in records:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in records:
            rr = dict(r)
            rr["adversarial_payloads_triggered"] = ";".join(rr.get("adversarial_payloads_triggered") or [])
            w.writerow(rr)


def regenerate_csv_from_trial_cieu(out_root: str, scenario: str = "", difficulty: str = "", ts: str = "") -> str:
    """Rebuild a CSV from trial_cieu JSONs. Filter by scenario and/or difficulty if given."""
    cieu_dir = os.path.join(out_root, "trial_cieu")
    records: List[Dict[str, Any]] = []
    for fname in sorted(os.listdir(cieu_dir)):
        if not fname.endswith(".json"):
            continue
        if scenario and not fname.startswith(f"{scenario}_"):
            continue
        if difficulty and f"_{difficulty}_" not in fname:
            continue
        with open(os.path.join(cieu_dir, fname), "r", encoding="utf-8") as f:
            records.append(json.load(f))
    if not ts:
        ts = time.strftime("%Y%m%d_%H%M%S")
    tag = scenario or "ALL"
    if difficulty:
        tag += f"_{difficulty}"
    out_csv = os.path.join(out_root, f"six_arm_{tag}_{ts}_recovered.csv")
    # post_state_files is too big for CSV; drop it from CSV but keep in JSON
    flattened = []
    for r in records:
        rr = dict(r)
        rr.pop("post_state_files", None)
        rr["adversarial_payloads_triggered"] = ";".join(rr.get("adversarial_payloads_triggered") or []) if isinstance(rr.get("adversarial_payloads_triggered"), list) else (rr.get("adversarial_payloads_triggered") or "")
        flattened.append(rr)
    _write_records_csv(out_csv, flattened)
    print(f"[bench] regenerated {out_csv} from {len(records)} trial CIEU files")
    return out_csv


def _csv_safe(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strip non-CSV-friendly fields (post_state_files dict lives in trial JSON only)."""
    out: List[Dict[str, Any]] = []
    for r in records:
        rr = dict(r)
        rr.pop("post_state_files", None)
        out.append(rr)
    return out


def main():
    p = argparse.ArgumentParser(description="Six-arm CZL productivity-arbitrage benchmark")
    p.add_argument("--scenarios", default="lint_fix,bug_fix,test_gen",
                   help="comma-separated scenario names")
    p.add_argument("--difficulties", default="easy,medium,hard",
                   help="comma-separated difficulty levels")
    p.add_argument("--arms", default="A,B1,B2,C1,C2,D2")
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--workspace-root", default="/tmp/czl_six_arm")
    p.add_argument("--out", default="benchmarks/czl_arbitrage/results")
    p.add_argument("--dry-run", action="store_true",
                   help="validate fixtures + arms then exit without invoking LLMs")
    args = p.parse_args()
    arms = [a.strip() for a in args.arms.split(",")]
    scenarios = [s.strip() for s in args.scenarios.split(",")]
    difficulties = [d.strip() for d in args.difficulties.split(",")]

    for a in arms:
        if a not in ARMS:
            print(f"[bench] unknown arm: {a}", file=sys.stderr)
            sys.exit(1)
    cells = [(s, d) for s in scenarios for d in difficulties]
    avail = set(available_cells())
    for cell in cells:
        if cell not in avail:
            print(f"[bench] unknown fixture cell: {cell}", file=sys.stderr)
            sys.exit(1)

    if args.dry_run:
        planned = len(arms) * len(cells) * args.trials
        print(f"[bench] dry-run OK: {len(arms)} arms × {len(cells)} cells × {args.trials} trials = {planned} planned trials")
        for (s, d) in cells:
            ws = os.path.join(args.workspace_root, f"_dryrun_{s}_{d}")
            if os.path.isdir(ws):
                shutil.rmtree(ws)
            os.makedirs(ws, exist_ok=True)
            task = materialize_for_cell(s, d, ws)
            files = sorted(os.path.relpath(os.path.join(r, f), ws)
                           for r, _, fs in os.walk(ws) for f in fs)
            print(f"  {s}/{d}: files={files} task={task[:60]!r}")
            shutil.rmtree(ws)
        return 0

    os.makedirs(args.workspace_root, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    all_records: List[Dict[str, Any]] = []
    for (s, d) in cells:
        recs = run_cell_all_arms(s, d, arms, args.trials, args.workspace_root, args.out)
        all_records.extend(recs)
        cell_csv = os.path.join(args.out, f"six_arm_{s}_{d}_{ts}.csv")
        _write_records_csv(cell_csv, _csv_safe(recs))
        print(f"[bench] wrote {cell_csv}")

    combined_csv = os.path.join(args.out, f"six_arm_ALL_{ts}.csv")
    _write_records_csv(combined_csv, _csv_safe(all_records))
    print(f"[bench] wrote {combined_csv}")

    summary = print_cross_tabs(all_records)
    with open(os.path.join(args.out, f"six_arm_summary_{ts}.json"), "w") as f:
        json.dump({"summary": summary, "n_trials": len(all_records)}, f, indent=2, default=str)


if __name__ == "__main__":
    sys.exit(main() or 0)
