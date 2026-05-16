"""
Three-dimensional quality assessment for v3 seven-arm experiment.

Dimension 1 — objective metrics:
  - cyclomatic_complexity_avg (radon cc)
  - duplicated_lines_pct (simple identical-line duplicate detector)
  - test_coverage_pct (pytest-cov, when source-under-test is known)
  - mypy_strict_type_coverage_pct (AST: annotated arg / return ratio)

Dimension 2 — Sonnet 4.6 judge:
  - 4-dim ordinary judge (functional_equivalence, readability_delta,
    style_conformance, defensive_quality) per (cell × non-A arm) converged
    candidate trial vs arm A reference trial
  - 3-dim A-vs-A2 专项 judge (hallucinated_completeness,
    silent_omission_count, over_engineering_score)

Dimension 3 — anonymized outputs for human blind review:
  - results/anonymized_outputs/<scenario>/<trial_id>.py with no arm label
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# --- Dimension 1: objective metrics --------------------------------------------

def _iter_py_files(workspace_dir: str, include_tests: bool = False) -> List[str]:
    out: List[str] = []
    for root, dirs, files in os.walk(workspace_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for f in files:
            if not f.endswith(".py"):
                continue
            if not include_tests and (f.startswith("test_") or f == "conftest.py"):
                continue
            out.append(os.path.join(root, f))
    return out


def cyclomatic_complexity_avg(workspace_dir: str) -> Optional[float]:
    """Mean function complexity per radon cc, source only (exclude tests)."""
    try:
        from radon.complexity import cc_visit
    except ImportError:
        return None
    complexities: List[int] = []
    for p in _iter_py_files(workspace_dir, include_tests=False):
        try:
            src = open(p, "r", encoding="utf-8").read()
            for fn in cc_visit(src):
                complexities.append(fn.complexity)
        except Exception:
            continue
    if not complexities:
        return 0.0
    return round(statistics.mean(complexities), 2)


def duplicated_lines_pct(workspace_dir: str) -> Optional[float]:
    """Fraction of non-trivial source lines that appear at least twice."""
    lines: List[str] = []
    for p in _iter_py_files(workspace_dir, include_tests=False):
        try:
            for ln in open(p, "r", encoding="utf-8").readlines():
                stripped = ln.strip()
                if len(stripped) < 6 or stripped.startswith("#"):
                    continue
                lines.append(stripped)
        except Exception:
            continue
    if not lines:
        return 0.0
    counts: Dict[str, int] = {}
    for ln in lines:
        counts[ln] = counts.get(ln, 0) + 1
    dup = sum(c for c in counts.values() if c > 1)
    return round(100.0 * dup / len(lines), 1)


def test_coverage_pct(workspace_dir: str, source_module: Optional[str] = None) -> Optional[float]:
    """Run pytest-cov over `source_module` and parse percent_covered.
    If source_module is None, omits --cov flag (returns None)."""
    if source_module is None:
        return None
    cov_json = os.path.join(workspace_dir, ".cov_quality.json")
    try:
        subprocess.run(
            ["pytest", "-q", "--tb=no", "--no-header",
             f"--cov={source_module}", f"--cov-report=json:{cov_json}"],
            cwd=workspace_dir, capture_output=True, text=True, timeout=180,
        )
        if not os.path.isfile(cov_json):
            return None
        data = json.loads(open(cov_json, "r", encoding="utf-8").read())
        pct = data.get("totals", {}).get("percent_covered")
        return round(pct, 1) if pct is not None else None
    except Exception:
        return None
    finally:
        try:
            os.unlink(cov_json)
        except FileNotFoundError:
            pass


def mypy_strict_type_coverage_pct(workspace_dir: str) -> Optional[float]:
    """Fraction of (function-def params + return) AST nodes that carry an annotation.
    Counted across source .py files only (exclude tests)."""
    total = 0
    annotated = 0
    for p in _iter_py_files(workspace_dir, include_tests=False):
        try:
            tree = ast.parse(open(p, "r", encoding="utf-8").read())
        except (SyntaxError, FileNotFoundError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # return
                total += 1
                if node.returns is not None:
                    annotated += 1
                # args (excluding *args/**kwargs name-only; include self/cls too — neutral)
                for arg in node.args.args:
                    total += 1
                    if arg.annotation is not None:
                        annotated += 1
    if total == 0:
        return 0.0
    return round(100.0 * annotated / total, 1)


def objective_metrics(workspace_dir: str, source_module: Optional[str] = None) -> Dict[str, Optional[float]]:
    return {
        "cyclomatic_complexity_avg": cyclomatic_complexity_avg(workspace_dir),
        "duplicated_lines_pct": duplicated_lines_pct(workspace_dir),
        "test_coverage_pct": test_coverage_pct(workspace_dir, source_module),
        "mypy_strict_type_coverage_pct": mypy_strict_type_coverage_pct(workspace_dir),
    }


# --- Dimension 2: Sonnet 4.6 judge --------------------------------------------

JUDGE_MODEL = "anthropic/claude-sonnet-4-6"
PER_CALL_BUDGET_CAP_USD = 0.03
TOTAL_BUDGET_CAP_USD = 5.0  # safety net; user spec budget is $45 overall


JUDGE_4DIM_TEMPLATE = """对比这两段实现：

Reference (Claude Opus 4.7):
{reference}

Candidate ({candidate_arm}):
{candidate}

task: {task_description}

输出 JSON: {{"functional_equivalence": <0-1>, "readability_delta": <-1 to +1>, "style_conformance": <0-1>, "defensive_quality": <0-1>}}
只输出 JSON。"""


JUDGE_A_VS_A2_TEMPLATE = """这是 Claude Opus 4.7 对同一任务两次输出的对比。请逐条检查 task 描述里的每个子需求，标记哪些在 reference 输出里被声称完成但实际未实现 / 未测试。

Reference (A: bare Opus, may contain hallucinated completion):
{arm_A_code}

Treatment (A2: Opus + Trampoline, verified output):
{arm_A2_code}

task: {task_description}

输出 JSON:
{{
  "hallucinated_completeness_A": <0-1>,
  "hallucinated_completeness_A2": <0-1>,
  "silent_omission_count_A": <int>,
  "silent_omission_count_A2": <int>,
  "over_engineering_score_A": <0-1>,
  "over_engineering_score_A2": <0-1>,
  "notes": "<最多 2 句话说明关键差异>"
}}
只输出 JSON。"""


def _format_files(files: Dict[str, str]) -> str:
    chunks: List[str] = []
    for rel in sorted(files.keys()):
        chunks.append(f"### {rel}\n```python\n{files[rel]}```")
    return "\n\n".join(chunks) if chunks else "(empty)"


def _parse_json_response(text: str) -> Optional[Dict[str, Any]]:
    """Pull a JSON object out of `text`, tolerating ```json``` fences and leading prose."""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    # Look for first {...}
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m is None:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _sonnet_call(prompt: str, max_tokens: int = 400) -> Dict[str, Any]:
    try:
        import litellm
    except ImportError:
        return {"text": "", "cost_usd": 0.0, "error": "litellm not installed"}
    t0 = time.time()
    try:
        r = litellm.completion(
            model=JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
    except Exception as e:
        return {"text": "", "cost_usd": 0.0, "error": f"{type(e).__name__}: {e}"}
    text = (r.choices[0].message.content or "").strip()
    usage = getattr(r, "usage", None)
    in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
    out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = (in_tok / 1_000_000) * 3.0 + (out_tok / 1_000_000) * 15.0
    return {"text": text, "cost_usd": cost, "latency_seconds": time.time() - t0}


def sonnet_judge_4dim(
    reference_files: Dict[str, str],
    candidate_files: Dict[str, str],
    candidate_arm: str,
    task_description: str,
) -> Dict[str, Any]:
    prompt = JUDGE_4DIM_TEMPLATE.format(
        reference=_format_files(reference_files),
        candidate=_format_files(candidate_files),
        candidate_arm=candidate_arm,
        task_description=task_description,
    )
    raw = _sonnet_call(prompt, max_tokens=200)
    parsed = _parse_json_response(raw["text"])
    return {
        "scores": parsed,
        "raw_response": raw["text"],
        "cost_usd": raw["cost_usd"],
        "latency_seconds": raw.get("latency_seconds"),
        "error": raw.get("error"),
    }


def sonnet_judge_a_vs_a2(
    arm_A_files: Dict[str, str],
    arm_A2_files: Dict[str, str],
    task_description: str,
) -> Dict[str, Any]:
    prompt = JUDGE_A_VS_A2_TEMPLATE.format(
        arm_A_code=_format_files(arm_A_files),
        arm_A2_code=_format_files(arm_A2_files),
        task_description=task_description,
    )
    raw = _sonnet_call(prompt, max_tokens=400)
    parsed = _parse_json_response(raw["text"])
    return {
        "scores": parsed,
        "raw_response": raw["text"],
        "cost_usd": raw["cost_usd"],
        "latency_seconds": raw.get("latency_seconds"),
        "error": raw.get("error"),
    }


# --- Dimension 3: anonymized outputs ------------------------------------------

def anonymize_trial_outputs(records: List[Dict[str, Any]], out_root: str) -> int:
    """Write each trial's post_state_files concatenated into a single .py blob
    at results/anonymized_outputs/<scenario>/<trial_id>.py — no arm label."""
    anon_dir = Path(out_root) / "anonymized_outputs"
    n = 0
    for r in records:
        scenario = r.get("scenario", "unknown")
        trial_id = _trial_id_for(r)
        files = r.get("post_state_files") or {}
        if not files:
            continue
        d = anon_dir / scenario
        d.mkdir(parents=True, exist_ok=True)
        body = "\n\n".join(f"# === {rel} ===\n{content}" for rel, content in sorted(files.items()))
        path = d / f"{trial_id}.py"
        path.write_text(f"# trial_id: {trial_id}\n# (arm name redacted for blind review)\n\n{body}",
                        encoding="utf-8")
        n += 1
    return n


def _trial_id_for(record: Dict[str, Any]) -> str:
    """Stable hash of (scenario + arm + trial) for blind review."""
    raw = f"{record.get('scenario')}-{record.get('arm')}-{record.get('trial')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


# --- Top-level orchestration --------------------------------------------------

def run_quality_assessment(
    scenario: str,
    all_records: List[Dict[str, Any]],
    out_root: str,
    task_description: str,
    source_module: Optional[str] = None,
) -> Dict[str, Any]:
    """For a single scenario's record set, run all 3 dimensions.

    Returns a dict to be written into the per-scenario quality_assessment.json.
    """
    scenario_records = [r for r in all_records if r.get("scenario") == scenario]
    # Dimension 1: objective per-trial metrics live in trial JSONs (computed at
    # trial time by run_seven_arm via the trial loop). Here we summarize.
    obj_summary: Dict[str, Dict[str, Optional[float]]] = {}
    for r in scenario_records:
        if r.get("converged"):
            arm = r["arm"]
            obj = r.get("objective_metrics") or {}
            obj_summary.setdefault(arm, {})
            for k, v in obj.items():
                if v is None:
                    continue
                obj_summary[arm].setdefault(k, []).append(v)  # type: ignore[arg-type]
    obj_means: Dict[str, Dict[str, float]] = {}
    for arm, metrics in obj_summary.items():
        obj_means[arm] = {k: round(statistics.mean(vs), 2) for k, vs in metrics.items() if vs}

    # Reference for judge: first converged A trial (its workspace files)
    a_converged = [r for r in scenario_records if r["arm"] == "A" and r.get("converged")]
    ref = a_converged[0]["post_state_files"] if a_converged else None

    # Dimension 2a: 4-dim judge — first converged trial per non-A arm
    four_dim_results: List[Dict[str, Any]] = []
    total_judge_cost = 0.0
    if ref:
        for arm in ("B1", "B2", "C1", "C2", "D2"):
            cand = [r for r in scenario_records if r["arm"] == arm and r.get("converged")]
            if not cand:
                four_dim_results.append({"arm": arm, "scores": None, "reason": "did_not_converge"})
                continue
            if total_judge_cost + PER_CALL_BUDGET_CAP_USD > TOTAL_BUDGET_CAP_USD:
                four_dim_results.append({"arm": arm, "scores": None, "reason": "budget_exceeded"})
                continue
            jr = sonnet_judge_4dim(ref, cand[0]["post_state_files"], f"arm {arm}", task_description)
            total_judge_cost += jr.get("cost_usd") or 0.0
            four_dim_results.append({"arm": arm, **jr})

    # Dimension 2b: A vs A2 专项 — first converged A vs first converged A2
    a_vs_a2_results: Dict[str, Any] = {"scores": None, "reason": "no_a_or_a2_converged"}
    a2_converged = [r for r in scenario_records if r["arm"] == "A2" and r.get("converged")]
    if ref and a2_converged and total_judge_cost + PER_CALL_BUDGET_CAP_USD <= TOTAL_BUDGET_CAP_USD:
        jr = sonnet_judge_a_vs_a2(ref, a2_converged[0]["post_state_files"], task_description)
        total_judge_cost += jr.get("cost_usd") or 0.0
        a_vs_a2_results = jr

    # Dimension 3: anonymize all trials
    n_anon = anonymize_trial_outputs(scenario_records, out_root)

    return {
        "scenario": scenario,
        "n_records": len(scenario_records),
        "objective_means_by_arm": obj_means,
        "four_dim_judge": four_dim_results,
        "a_vs_a2_judge": a_vs_a2_results,
        "n_anonymized": n_anon,
        "total_judge_cost_usd": round(total_judge_cost, 4),
    }


if __name__ == "__main__":
    print("quality_assessment module loaded.")
    print("functions: objective_metrics, sonnet_judge_4dim, sonnet_judge_a_vs_a2, "
          "anonymize_trial_outputs, run_quality_assessment")
