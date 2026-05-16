"""
v2-aware cross-tab reporter for the productivity-arbitrage experiment.

Loads all trial CIEU JSONs (v2 records have `difficulty` and `converged` fields,
no `result_class` field), prints 6 cross-tabs, runs the semantic judge for the
7th cross-tab, and writes a combined summary JSON.

This module is standalone — does not touch run_six_arm.py's legacy v1
print_cross_tabs (which still references the v1 result_class schema).
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from benchmarks.czl_arbitrage.semantic_judge import (  # noqa: E402
    judge_experiment, print_cross_tab as print_semantic_cross_tab,
)


def load_v2_records(out_root: str) -> List[Dict[str, Any]]:
    cieu_dir = Path(out_root) / "trial_cieu"
    records: List[Dict[str, Any]] = []
    if not cieu_dir.exists():
        return records
    for fname in sorted(os.listdir(cieu_dir)):
        if not fname.endswith(".json"):
            continue
        try:
            r = json.loads((cieu_dir / fname).read_text(encoding="utf-8"))
        except Exception:
            continue
        if "difficulty" not in r:  # filter to v2 only
            continue
        records.append(r)
    return records


def _cell_records(records: List[Dict[str, Any]], scenario: str, difficulty: str, arm: str) -> List[Dict[str, Any]]:
    return [r for r in records if r["scenario"] == scenario and r["difficulty"] == difficulty and r["arm"] == arm]


def _arms(records: List[Dict[str, Any]]) -> List[str]:
    return sorted({r["arm"] for r in records})


def _cells(records: List[Dict[str, Any]]) -> List[tuple]:
    return sorted({(r["scenario"], r["difficulty"]) for r in records})


def print_table_1_convergence(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    print("\n" + "=" * 110)
    print("CROSS-TAB 1: convergence rate (converged/total) by arm × (scenario, difficulty)")
    print("=" * 110)
    cells = _cells(records)
    arms = _arms(records)
    cell_headers = [f"{s[:8]}/{d[:3]}" for (s, d) in cells]
    header = f"{'arm':5}" + "".join(f"{h:>13}" for h in cell_headers)
    print(header)
    summary: Dict[str, Any] = {}
    for a in arms:
        row = f"{a:5}"
        for (s, d) in cells:
            cell = _cell_records(records, s, d, a)
            conv = sum(1 for r in cell if r.get("converged"))
            row += f"{conv}/{len(cell)} ({100*conv/max(len(cell),1):3.0f}%)".rjust(13)
            summary.setdefault(a, {})[f"{s}/{d}"] = {"converged": conv, "total": len(cell)}
        print(row)
    return summary


def print_table_2_cost(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    print("\n" + "=" * 110)
    print("CROSS-TAB 2: mean cost per CONVERGED trial (USD) by arm × cell, plus C2/A and D2/A ratios")
    print("=" * 110)
    cells = _cells(records)
    arms = _arms(records)
    print(f"{'cell':24}" + "".join(f"{a:>11}" for a in arms) + f"{'C2/A':>9}{'D2/A':>9}{'B2/A':>9}")
    summary: Dict[str, Any] = {}
    for (s, d) in cells:
        label = f"{s}/{d}"
        row = f"{label:24}"
        means: Dict[str, float] = {}
        for a in arms:
            cell = [r for r in _cell_records(records, s, d, a) if r.get("converged")]
            mean = statistics.mean([r["cost_usd"] for r in cell]) if cell else 0.0
            means[a] = mean
            row += f"${mean:>10.5f}"
        a_mean = means.get("A", 0.0)
        for ratio_arm in ("C2", "D2", "B2"):
            x = means.get(ratio_arm, 0.0)
            r = (a_mean / x) if x > 0 else (float("inf") if a_mean > 0 else 0.0)
            row += f"{r:>9.1f}x" if r != float("inf") else f"{'inf':>9}"
        summary[label] = {"means": means, "C2/A": (a_mean / means["C2"]) if means.get("C2", 0) > 0 else None,
                          "D2/A": (a_mean / means["D2"]) if means.get("D2", 0) > 0 else None}
        print(row)
    return summary


def print_table_3_walltime(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    print("\n" + "=" * 110)
    print("CROSS-TAB 3: mean wall-clock seconds per trial by arm × cell")
    print("=" * 110)
    cells = _cells(records)
    arms = _arms(records)
    print(f"{'cell':24}" + "".join(f"{a:>11}" for a in arms))
    summary: Dict[str, Any] = {}
    for (s, d) in cells:
        label = f"{s}/{d}"
        row = f"{label:24}"
        for a in arms:
            cell = _cell_records(records, s, d, a)
            mean = statistics.mean([r["wall_clock_seconds"] for r in cell]) if cell else 0.0
            row += f"{mean:>11.1f}"
            summary.setdefault(label, {})[a] = mean
        print(row)
    return summary


def print_table_4_ablation(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    print("\n" + "=" * 110)
    print("CROSS-TAB 4: CZL ablation (converged rate with CZL - without) per cell")
    print("=" * 110)
    print(f"{'cell':24}{'B1->B2 delta pp':>22}{'C1->C2 delta pp':>22}")
    summary: Dict[str, Any] = {}
    cells = _cells(records)
    for (s, d) in cells:
        label = f"{s}/{d}"
        def rate(arm):
            cell = _cell_records(records, s, d, arm)
            return (sum(1 for r in cell if r.get("converged")) / len(cell)) if cell else 0.0
        b_delta = (rate("B2") - rate("B1")) * 100
        c_delta = (rate("C2") - rate("C1")) * 100
        print(f"{label:24}{b_delta:>+22.0f}{c_delta:>+22.0f}")
        summary[label] = {"B1->B2": b_delta, "C1->C2": c_delta}
    return summary


def print_table_5_non_converged(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    print("\n" + "=" * 110)
    print("CROSS-TAB 5: non-converged rate by arm × cell (3 sub-causes: api_error / exception / verifier_unsatisfied)")
    print("=" * 110)
    cells = _cells(records)
    arms = _arms(records)
    print(f"{'cell':24}" + "".join(f"{a:>11}" for a in arms))
    summary: Dict[str, Any] = {}
    for (s, d) in cells:
        label = f"{s}/{d}"
        row = f"{label:24}"
        for a in arms:
            cell = _cell_records(records, s, d, a)
            nc = [r for r in cell if not r.get("converged")]
            row += f"{len(nc)}/{len(cell)}".rjust(11)
            summary.setdefault(label, {})[a] = {"non_converged": len(nc), "total": len(cell)}
        print(row)
    return summary


def print_table_6_iterations(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    print("\n" + "=" * 110)
    print("CROSS-TAB 6: mean iterations (CZL loop rounds) for CZL arms B2/C2/D2, by cell")
    print("=" * 110)
    cells = _cells(records)
    czl_arms = [a for a in _arms(records) if a in ("B2", "C2", "D2")]
    print(f"{'cell':24}" + "".join(f"{a:>11}" for a in czl_arms))
    summary: Dict[str, Any] = {}
    for (s, d) in cells:
        label = f"{s}/{d}"
        row = f"{label:24}"
        for a in czl_arms:
            cell = _cell_records(records, s, d, a)
            mean = statistics.mean([r.get("iterations") or 0 for r in cell]) if cell else 0.0
            row += f"{mean:>11.2f}"
            summary.setdefault(label, {})[a] = mean
        print(row)
    return summary


def run_all(out_root: str) -> Dict[str, Any]:
    records = load_v2_records(out_root)
    print(f"loaded {len(records)} v2 trial records — "
          f"{len(_cells(records))} cells × {len(_arms(records))} arms × n=3 trials")
    summary: Dict[str, Any] = {
        "n_trials": len(records),
        "n_cells": len(_cells(records)),
        "n_arms": len(_arms(records)),
        "tables": {},
    }
    summary["tables"]["1_convergence"] = print_table_1_convergence(records)
    summary["tables"]["2_cost"] = print_table_2_cost(records)
    summary["tables"]["3_walltime"] = print_table_3_walltime(records)
    summary["tables"]["4_ablation"] = print_table_4_ablation(records)
    summary["tables"]["5_non_converged"] = print_table_5_non_converged(records)
    summary["tables"]["6_iterations"] = print_table_6_iterations(records)

    print("\n>> running semantic judge for CROSS-TAB 7 (claude-sonnet-4-6 pairs vs arm A) ...")
    judge_out = judge_experiment(out_root)
    print_semantic_cross_tab(judge_out)
    summary["tables"]["7_semantic_judge"] = judge_out

    return summary


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/czl_arbitrage/results"
    summary = run_all(out)
    Path(out).joinpath("v2_FINAL_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nwrote {out}/v2_FINAL_summary.json")
