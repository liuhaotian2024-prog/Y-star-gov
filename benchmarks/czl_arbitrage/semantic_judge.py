"""
Semantic-correctness judge: pair a candidate arm's converged trial output
against the canonical arm-A reference and score 0-1 via Claude Sonnet 4.6.

Why Sonnet 4.6 and not Opus 4.7:
  - This is a comparison task, not synthesis — Sonnet is enough
  - 1/5th the cost of Opus per call; we want lots of pair-evals cheap

Inputs:
  - A trial_cieu JSON for arm A (reference) with non-empty post_state_files
  - A trial_cieu JSON for the candidate arm with non-empty post_state_files

Output:
  - A float in [0, 1] plus the raw judge response text for audit

Sampling policy:
  - For each (scenario, difficulty, arm) cell we evaluate ONE pair:
    arm A trial 0 (converged) vs arm X trial 0 (converged).
  - If either side did not converge, the cell gets a None score.
  - Roughly 8 cells × 5 non-A arms = 40 calls per experiment. Well under
    the $0.50 cap at ~$0.005/call.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


JUDGE_MODEL = "anthropic/claude-sonnet-4-6"
# Estimated USD per call. Sonnet 4.6 is ~$3 in / $15 out per Mtok; a typical
# judge call is ~3k in, 5 out tokens, so ~$0.01. Conservative cap below.
JUDGE_CALL_COST_BUDGET_USD = 0.02
JUDGE_TOTAL_BUDGET_USD = 0.50


JUDGE_PROMPT_TEMPLATE = """比较 reference 实现和 candidate 实现是否在功能上等价：

Reference (Claude Opus 4.7 baseline):
{reference}

Candidate ({candidate_arm}):
{candidate}

请输出一个 0-1 分数：
1.0 = 功能完全等价
0.7-0.9 = 功能等价但风格/实现细节不同
0.4-0.6 = 部分等价，有一些功能差异
0.0-0.3 = 显著差异或功能错误
只输出一个数字，不要其他文字。"""


def _format_files(files: Dict[str, str]) -> str:
    """Render a dict of relative_path → content as fenced code blocks."""
    chunks: List[str] = []
    for rel in sorted(files.keys()):
        chunks.append(f"### {rel}\n```python\n{files[rel]}```")
    return "\n\n".join(chunks) if chunks else "(empty)"


@dataclass
class JudgeResult:
    score: Optional[float]
    raw_response: str
    cost_usd: float
    latency_seconds: float
    error: Optional[str] = None


def judge_pair(
    reference_files: Dict[str, str],
    candidate_files: Dict[str, str],
    candidate_arm_label: str,
) -> JudgeResult:
    """Make one Sonnet 4.6 judge call. Returns score (or None on failure)."""
    try:
        import litellm
    except ImportError:
        return JudgeResult(None, "", 0.0, 0.0, "litellm not installed")

    prompt = JUDGE_PROMPT_TEMPLATE.format(
        reference=_format_files(reference_files),
        candidate=_format_files(candidate_files),
        candidate_arm=candidate_arm_label,
    )
    t0 = time.time()
    try:
        r = litellm.completion(
            model=JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
        )
    except Exception as e:
        return JudgeResult(None, "", 0.0, time.time() - t0, f"{type(e).__name__}: {e}")

    text = (r.choices[0].message.content or "").strip()
    usage = getattr(r, "usage", None)
    in_tok = getattr(usage, "prompt_tokens", 0) if usage else 0
    out_tok = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = (in_tok / 1_000_000) * 3.0 + (out_tok / 1_000_000) * 15.0

    m = re.search(r"[01]\.?\d*", text)
    score: Optional[float] = None
    if m:
        try:
            v = float(m.group(0))
            if 0.0 <= v <= 1.0:
                score = v
        except ValueError:
            pass
    return JudgeResult(
        score=score,
        raw_response=text,
        cost_usd=cost,
        latency_seconds=time.time() - t0,
    )


def load_trial_cieu(out_root: str) -> List[Dict]:
    """Load all v2 trial CIEU JSONs. v2 records include difficulty + post_state_files."""
    cieu_dir = Path(out_root) / "trial_cieu"
    records: List[Dict] = []
    if not cieu_dir.exists():
        return records
    for fname in sorted(os.listdir(cieu_dir)):
        if not fname.endswith(".json"):
            continue
        full = cieu_dir / fname
        try:
            r = json.loads(full.read_text(encoding="utf-8"))
        except Exception:
            continue
        # only v2 records (have difficulty field)
        if "difficulty" not in r:
            continue
        records.append(r)
    return records


def pick_first_converged(records: List[Dict], scenario: str, difficulty: str, arm: str) -> Optional[Dict]:
    """First converged trial for the (scenario, difficulty, arm) cell."""
    for r in records:
        if (r.get("scenario") == scenario
                and r.get("difficulty") == difficulty
                and r.get("arm") == arm
                and r.get("converged")):
            return r
    return None


def judge_experiment(out_root: str) -> Dict:
    """One judge call per (scenario, difficulty, non-A arm) cell where BOTH A
    and the candidate produced a converged trial. Caps total spend at
    JUDGE_TOTAL_BUDGET_USD."""
    records = load_trial_cieu(out_root)
    if not records:
        return {"calls": 0, "errors": ["no v2 trial_cieu records on disk"]}

    cells = sorted({(r["scenario"], r["difficulty"]) for r in records})
    arms = sorted({r["arm"] for r in records})
    candidate_arms = [a for a in arms if a != "A"]

    results: List[Dict] = []
    total_cost = 0.0
    errors: List[str] = []
    for (s, d) in cells:
        ref_rec = pick_first_converged(records, s, d, "A")
        if ref_rec is None:
            errors.append(f"no converged A trial for {s}/{d} — skipping cell")
            continue
        ref_files = ref_rec.get("post_state_files", {})
        if not ref_files:
            errors.append(f"A trial for {s}/{d} has empty post_state_files — pre-v2 data, skipping")
            continue
        for arm in candidate_arms:
            cand_rec = pick_first_converged(records, s, d, arm)
            if cand_rec is None:
                results.append({"scenario": s, "difficulty": d, "arm": arm, "score": None, "reason": "did_not_converge"})
                continue
            cand_files = cand_rec.get("post_state_files", {})
            if not cand_files:
                results.append({"scenario": s, "difficulty": d, "arm": arm, "score": None, "reason": "no_post_state_files"})
                continue
            if total_cost + JUDGE_CALL_COST_BUDGET_USD > JUDGE_TOTAL_BUDGET_USD:
                errors.append(f"budget exceeded before judging {s}/{d}/{arm}; cap=${JUDGE_TOTAL_BUDGET_USD}")
                results.append({"scenario": s, "difficulty": d, "arm": arm, "score": None, "reason": "budget_exceeded"})
                continue
            jr = judge_pair(ref_files, cand_files, f"arm {arm}")
            total_cost += jr.cost_usd
            results.append({
                "scenario": s, "difficulty": d, "arm": arm,
                "score": jr.score,
                "raw_response": jr.raw_response,
                "cost_usd": jr.cost_usd,
                "latency_seconds": jr.latency_seconds,
                "error": jr.error,
            })

    return {
        "calls": len(results),
        "total_cost_usd": total_cost,
        "errors": errors,
        "results": results,
    }


def cross_tab_semantic_score(judge_output: Dict) -> Dict:
    """Aggregate into cross-tab: per (scenario, difficulty, arm) mean score."""
    if not judge_output or "results" not in judge_output:
        return {}
    table: Dict[str, Dict] = {}
    for r in judge_output["results"]:
        key = f"{r['scenario']}/{r['difficulty']}"
        table.setdefault(key, {})[r["arm"]] = r.get("score")
    return table


def print_cross_tab(judge_output: Dict) -> None:
    """7th cross-tab: semantic correctness score per arm per (scenario, difficulty)."""
    print()
    print("=" * 90)
    print("CROSS-TAB 7: semantic_correctness_score (judge: claude-sonnet-4-6) — A is the reference (=1.0)")
    print("=" * 90)
    table = cross_tab_semantic_score(judge_output)
    if not table:
        print("(no judge results)")
        return
    arms_seen = sorted({arm for cell in table.values() for arm in cell})
    header = f"{'cell':20}" + "".join(f"{a:>10}" for a in arms_seen)
    print(header)
    for cell in sorted(table.keys()):
        row = f"{cell:20}"
        for a in arms_seen:
            v = table[cell].get(a)
            row += f"{'  (skip)' if v is None else f'{v:>10.2f}':>10}"
        print(row)
    print(f"\nJudge calls: {judge_output['calls']}, total cost: ${judge_output['total_cost_usd']:.4f}")
    if judge_output["errors"]:
        print("Warnings:")
        for e in judge_output["errors"]:
            print(f"  - {e}")


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/czl_arbitrage/results"
    result = judge_experiment(out)
    print_cross_tab(result)
    Path(out).joinpath("semantic_judge_results.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    print(f"wrote {out}/semantic_judge_results.json")
