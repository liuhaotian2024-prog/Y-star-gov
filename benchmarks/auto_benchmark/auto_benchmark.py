"""auto_benchmark.py — long-running random scheduler comparing bare LLM vs
Trampoline-enhanced runs across 20 tasks × 3 models × 2 arms.

Run: nohup /opt/homebrew/bin/python3.11 benchmarks/auto_benchmark/auto_benchmark.py &

Budget cap $20 (API only — Ollama free). Inter-trial sleep 5s.
Rolling report /tmp/auto_benchmark_report.md every 10 trials.
CIEU events appended to .ystar_runtime_full_spectrum.cieu.jsonl:
  r=1 per trial, r=0 milestone per 10 trials.

Does NOT modify Trampoline code — uses public API only.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

# Force regex contract compilation to keep budget tight (Anthropic NL→contract
# would otherwise charge per Trampoline trial).
os.environ.setdefault("YSTAR_LLM_PROVIDER", "regex")

from benchmarks.auto_benchmark.tasks import TASKS  # noqa: E402

# Trampoline public API
from ystar.czl.loop import run_scenario, CZLRun, CZLResult  # noqa: E402
from ystar.czl.scenarios.base import Scenario, PlanStep  # noqa: E402
from ystar.czl.verifiers.base import VerifierResult  # noqa: E402
from ystar.czl.backends.base import Backend, BackendResponse, BackendAction  # noqa: E402
from ystar.czl.backends import (  # noqa: E402
    OllamaBackend, DeepSeekBackend, MiniMaxBackend,
)


# === paths & constants ======================================================

RESULTS_DIR = Path("/tmp/auto_benchmark_results")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
REPORT_PATH = Path("/tmp/auto_benchmark_report.md")
STATE_PATH = Path("/tmp/auto_benchmark_state.json")
LOG_PATH = Path("/tmp/auto_benchmark.log")
CIEU_PATH = REPO / ".ystar_runtime_full_spectrum.cieu.jsonl"

BUDGET_USD_CAP = 20.0
INTER_TRIAL_SLEEP_S = 5
MAX_TRAMPOLINE_ITERS = 30  # NOTE: RLE's internal cap is 50 (hardcoded), but
                            # no_progress_window=2 forces early halt to honor
                            # founder's 30-iter spirit + protect budget.
NO_PROGRESS_WINDOW = 2
ROLLING_REPORT_EVERY = 10
ADAPTIVE_CHECK_EVERY = 50

MODELS = ["gemma4", "deepseek", "minimax"]


# === code-block extraction ==================================================

_BLOCK_RE_TEMPLATES = {
    "python": [r"```python\s*\n(.*?)```", r"```py\s*\n(.*?)```", r"```\s*\n(.*?)```"],
    "sql":    [r"```sql\s*\n(.*?)```", r"```\s*\n(.*?)```"],
    "json":   [r"```json\s*\n(.*?)```", r"```\s*\n(.*?)```"],
    "text":   [r"```\s*\n(.*?)```"],
}


def extract_code_block(response: str, block_type: str) -> str:
    """Extract first code block of given type, fall back to raw response."""
    for pat in _BLOCK_RE_TEMPLATES.get(block_type, _BLOCK_RE_TEMPLATES["text"]):
        m = re.search(pat, response, flags=re.DOTALL)
        if m:
            return m.group(1).strip() + "\n"
    return response.strip() + "\n"


# === workspace setup ========================================================

def setup_workspace(task: Dict, base_dir: Path) -> Path:
    """Create workspace dir with task's initial files. Returns the dir."""
    ws = base_dir / f"ws_{task['task_id']}_{int(time.time()*1000)}"
    ws.mkdir(parents=True)
    for rel_path, content in task["workspace_files"].items():
        target = ws / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    # git init (Trampoline expects a git workspace)
    subprocess.run(["git", "init", "-q"], cwd=str(ws), check=False)
    subprocess.run(["git", "config", "user.email", "auto-bench@local"], cwd=str(ws), check=False)
    subprocess.run(["git", "config", "user.name", "auto-bench"], cwd=str(ws), check=False)
    subprocess.run(["git", "add", "-A"], cwd=str(ws), check=False)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(ws), check=False)
    return ws


def run_verifier(verifier_cmd: str, workspace_dir: Path, timeout: int = 60) -> Dict[str, Any]:
    """Run verifier shell command. Exit 0 = converged."""
    try:
        proc = subprocess.run(
            verifier_cmd, shell=True, cwd=str(workspace_dir),
            capture_output=True, text=True, timeout=timeout,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
            "converged": proc.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": "TIMEOUT", "converged": False}
    except Exception as exc:
        return {"exit_code": -2, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}", "converged": False}


# === Generic shell-verifier scenario for Trampoline arm =====================

class GenericShellScenario(Scenario):
    """Scenario wrapper for arbitrary task with single output file + shell verifier."""

    name = "auto_benchmark_generic"
    description = "Generic single-file LLM output + shell verifier"
    default_max_iterations = MAX_TRAMPOLINE_ITERS

    def __init__(self, task: Dict):
        self._task = task

    def y_star_invariants(self) -> Dict[str, Any]:
        return {"invariant": [f"{self._task['verifier_cmd']} exits 0"]}

    def system_prompt(self) -> str:
        return (
            "You are a senior software engineer. Emit only the requested code "
            "block. The verifier will run your output via an external tool. If "
            "you cannot meet the spec, say so honestly rather than producing "
            "code that fails."
        )

    def plan(self, task_description, workspace_dir, contract=None):
        prompt = (
            f"## Task\n{self._task['prompt']}\n\n"
            f"## Y* (success criterion)\n{self._task['y_star']}\n"
        )
        return [PlanStep(step_id="solve", user_prompt=prompt,
                          expected_action_types=["edit_file", "create_file"])]

    def verify(self, workspace_dir: str, contract: Dict[str, Any]) -> List[VerifierResult]:
        r = run_verifier(self._task["verifier_cmd"], Path(workspace_dir))
        return [VerifierResult(
            verifier_name="shell_verifier",
            passed=r["converged"],
            message=("converged" if r["converged"]
                     else f"exit={r['exit_code']}; stderr={r['stderr'][:200]}"),
            details={"stdout": (r["stdout"] + "\n--STDERR--\n" + r["stderr"])[:2000]},
        )]

    def apply_action(self, action, workspace_dir, contract=None):
        a = action if isinstance(action, dict) else getattr(action, "payload", {})
        atype = a.get("type") if isinstance(a, dict) else getattr(action, "type", "")
        # All actions normalised to: write self._task['output_file'] with extracted code
        content = ""
        if isinstance(a, dict):
            content = a.get("content", "")
        out_file = Path(workspace_dir) / self._task["output_file"]
        out_file.parent.mkdir(parents=True, exist_ok=True)
        # Try to extract a code block; if action already gave clean code, use it
        clean = extract_code_block(content, self._task["output_block_type"])
        out_file.write_text(clean)


# === backend instantiation ==================================================

def get_backend(model_key: str) -> Backend:
    if model_key == "gemma4":
        return OllamaBackend()
    if model_key == "deepseek":
        return DeepSeekBackend()
    if model_key == "minimax":
        return MiniMaxBackend()
    raise ValueError(f"unknown model {model_key}")


# === bare arm: one-shot LLM call ===========================================

def run_bare_arm(task: Dict, model_key: str) -> Dict[str, Any]:
    """Single call: build prompt → invoke backend → extract code → write →
    run verifier. No retries."""
    started = time.time()
    base = Path(tempfile.mkdtemp(prefix="autobench_bare_"))
    ws = setup_workspace(task, base)
    backend = get_backend(model_key)
    prompt = (
        f"## Task\n{task['prompt']}\n\n## Y*\n{task['y_star']}\n"
    )
    sys_prompt = (
        "You are a senior software engineer. Emit only the requested code "
        "block. If you cannot meet the spec, say so."
    )
    try:
        resp: BackendResponse = backend.invoke(
            system_prompt=sys_prompt,
            user_prompt=prompt,
            workspace_dir=str(ws),
            contract={"model_tier": getattr(backend, "model_capacity", "medium")},
        )
        raw = getattr(resp, "raw_text", "") or ""
        code = extract_code_block(raw, task["output_block_type"])
        out_path = ws / task["output_file"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(code)
        verif = run_verifier(task["verifier_cmd"], ws)
        cost = getattr(resp, "cost_usd", 0.0) or 0.0
        return {
            "arm": "bare",
            "converged": verif["converged"],
            "verifier_exit": verif["exit_code"],
            "verifier_stdout": verif["stdout"][:500],
            "verifier_stderr": verif["stderr"][:500],
            "cost_usd": cost,
            "duration_s": time.time() - started,
            "raw_response_len": len(raw),
            "extracted_code_len": len(code),
        }
    except Exception as exc:
        return {
            "arm": "bare",
            "converged": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-1000:],
            "cost_usd": 0.0,
            "duration_s": time.time() - started,
        }
    finally:
        shutil.rmtree(base, ignore_errors=True)


# === Trampoline arm ========================================================

def run_trampoline_arm(task: Dict, model_key: str) -> Dict[str, Any]:
    """Run CZL loop with the generic shell scenario, max 30 iter."""
    started = time.time()
    base = Path(tempfile.mkdtemp(prefix="autobench_tramp_"))
    ws = setup_workspace(task, base)
    backend = get_backend(model_key)
    scen = GenericShellScenario(task)
    request = CZLRun(
        task_description=task["prompt"],
        scenario=scen,
        backend=backend,
        workspace_dir=str(ws),
        max_iterations=MAX_TRAMPOLINE_ITERS,
        no_progress_window=NO_PROGRESS_WINDOW,
    )
    try:
        result: CZLResult = run_scenario(request)
        return {
            "arm": "trampoline",
            "converged": result.converged,
            "iterations": result.iterations,
            "final_residual": result.final_residual,
            "stopping_authority": result.stopping_authority,
            "failure_reason": result.failure_reason[:500],
            "cost_usd": result.total_cost_usd,
            "duration_s": time.time() - started,
            "iter_response_lens": [len(r) for r in result.iter_responses],
        }
    except Exception as exc:
        return {
            "arm": "trampoline",
            "converged": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-1000:],
            "cost_usd": 0.0,
            "duration_s": time.time() - started,
        }
    finally:
        shutil.rmtree(base, ignore_errors=True)


# === state + budget =========================================================

@dataclass
class BenchState:
    trial_idx: int = 0
    total_cost_usd: float = 0.0
    started_at: float = field(default_factory=time.time)
    cieu_head: str = ""
    cell_results: Dict[str, List[bool]] = field(default_factory=lambda: defaultdict(list))
    halt_reason: str = ""

    def cell_key(self, domain: str, model: str, arm: str) -> str:
        return f"{domain}|{model}|{arm}"

    def record(self, domain: str, model: str, arm: str, converged: bool, cost: float):
        # trial_idx increments ONCE per (bare+trampoline) pair — caller bumps it
        # explicitly between trials. Here we only accumulate cost + cell results.
        self.total_cost_usd += cost
        self.cell_results[self.cell_key(domain, model, arm)].append(converged)

    def save(self):
        STATE_PATH.write_text(json.dumps({
            "trial_idx": self.trial_idx,
            "total_cost_usd": self.total_cost_usd,
            "started_at": self.started_at,
            "cieu_head": self.cieu_head,
            "cell_results": dict(self.cell_results),
            "halt_reason": self.halt_reason,
        }))

    @classmethod
    def load(cls) -> "BenchState":
        if not STATE_PATH.exists():
            return cls()
        d = json.loads(STATE_PATH.read_text())
        s = cls()
        s.trial_idx = d.get("trial_idx", 0)
        s.total_cost_usd = d.get("total_cost_usd", 0.0)
        s.started_at = d.get("started_at", time.time())
        s.cieu_head = d.get("cieu_head", "")
        s.cell_results = defaultdict(list, {k: v for k, v in d.get("cell_results", {}).items()})
        s.halt_reason = d.get("halt_reason", "")
        return s


# === CIEU writes ============================================================

def _event_hash(prev_hash: str, payload: Dict) -> str:
    blob = (prev_hash + json.dumps(payload, sort_keys=True, ensure_ascii=False)).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _latest_cieu_head() -> str:
    try:
        with open(CIEU_PATH, "rb") as f:
            f.seek(-65536, 2) if f.seek(0, 2) > 65536 else f.seek(0)
            tail = f.read().decode("utf-8", errors="ignore")
        last = [ln for ln in tail.strip().splitlines() if ln.strip()]
        if not last:
            return ""
        return json.loads(last[-1]).get("event_hash", "")
    except Exception:
        return ""


def write_cieu(state: BenchState, milestone: str, y_star: str, actions: List[str],
                y_t1: str, r_t1: int, verify_cmd: str, verify_tail: str):
    prev = state.cieu_head or _latest_cieu_head()
    payload = {
        "ts": int(time.time()),
        "milestone_id": milestone,
        "y_star": y_star,
        "actions_taken": actions,
        "y_t_plus_1": y_t1,
        "r_t_plus_1": r_t1,
        "verify_command": verify_cmd,
        "verify_output_tail": verify_tail,
    }
    payload["prev_hash"] = prev
    payload["event_hash"] = _event_hash(prev, payload)
    with open(CIEU_PATH, "a") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    state.cieu_head = payload["event_hash"]


# === rolling report =========================================================

def write_rolling_report(state: BenchState, last_trial: Dict[str, Any]):
    lines = [
        f"# auto_benchmark rolling report — trial {state.trial_idx}",
        f"_generated {time.strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
        f"- trials completed: **{state.trial_idx}**",
        f"- total API cost: **${state.total_cost_usd:.4f}** (budget cap ${BUDGET_USD_CAP:.2f})",
        f"- wall clock since start: {int(time.time() - state.started_at)}s",
        f"- halt reason: {state.halt_reason or '(running)'}",
        "",
        "## convergence rate per (domain × model × arm)",
        "",
        "| domain | model | arm | trials | converged | rate |",
        "|---|---|---|---:|---:|---:|",
    ]
    for key in sorted(state.cell_results.keys()):
        domain, model, arm = key.split("|")
        results = state.cell_results[key]
        n = len(results)
        c = sum(1 for r in results if r)
        rate = (c / n * 100) if n else 0
        lines.append(f"| {domain} | {model} | {arm} | {n} | {c} | {rate:.0f}% |")

    # Value-add: bare vs trampoline per (domain, model) cell
    lines.append("")
    lines.append("## Trampoline value-add (+Trampoline vs bare, ≥10pp = positive)")
    lines.append("")
    lines.append("| domain | model | bare rate | trampoline rate | delta (pp) |")
    lines.append("|---|---|---:|---:|---:|")
    cells_seen = set()
    nonregression_violations = []
    for key in state.cell_results:
        domain, model, arm = key.split("|")
        if (domain, model) in cells_seen:
            continue
        cells_seen.add((domain, model))
        bare_key = state.cell_key(domain, model, "bare")
        tram_key = state.cell_key(domain, model, "trampoline")
        bare = state.cell_results.get(bare_key, [])
        tram = state.cell_results.get(tram_key, [])
        if not bare or not tram:
            continue
        br = sum(bare) / len(bare) * 100
        tr = sum(tram) / len(tram) * 100
        delta = tr - br
        marker = "  **+gain**" if delta >= 10 else ("  REGRESSION" if delta < 0 else "")
        if delta < 0:
            nonregression_violations.append(f"{domain}/{model}: bare={br:.0f}%, tramp={tr:.0f}%")
        lines.append(f"| {domain} | {model} | {br:.0f}% | {tr:.0f}% | {delta:+.0f}{marker} |")

    if nonregression_violations:
        lines.append("")
        lines.append("## ⚠ NON-REGRESSION VIOLATIONS")
        for v in nonregression_violations:
            lines.append(f"- {v}")

    lines.append("")
    lines.append(f"## last trial (idx {state.trial_idx})")
    lines.append("```")
    lines.append(json.dumps(last_trial, indent=2, default=str)[:2000])
    lines.append("```")
    REPORT_PATH.write_text("\n".join(lines))


# === adaptive task discovery (mark only — never auto-replace) ==============

def adaptive_check(state: BenchState) -> List[str]:
    """Return list of task_ids with zero discrimination (both arms 100% or 0%)."""
    candidates = []
    by_task = defaultdict(lambda: {"bare": [], "trampoline": []})
    # Note: cell_results is keyed by (domain, model, arm), not task. To check
    # per-task, we'd need to track per-task. For now flag domains that are
    # uniformly converged or uniformly failing across all (model, arm).
    for key, res in state.cell_results.items():
        domain, model, arm = key.split("|")
        by_task[domain][arm].extend(res)
    for d, bym in by_task.items():
        bare = bym["bare"]
        tram = bym["trampoline"]
        if not bare or not tram:
            continue
        if (all(bare) and all(tram)) or (not any(bare) and not any(tram)):
            candidates.append(f"domain={d}: bare={sum(bare)}/{len(bare)}, tramp={sum(tram)}/{len(tram)}")
    return candidates


# === main loop ==============================================================

def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


_HALT_FLAG = False


def _sig_handler(*a):
    global _HALT_FLAG
    _HALT_FLAG = True
    log(f"signal received → halting after current trial")


signal.signal(signal.SIGTERM, _sig_handler)
signal.signal(signal.SIGINT, _sig_handler)


def main(max_trials: Optional[int] = None):
    state = BenchState.load()
    log(f"auto_benchmark starting (resume trial_idx={state.trial_idx}, "
        f"cost=${state.total_cost_usd:.4f}, budget=${BUDGET_USD_CAP:.2f})")

    while not _HALT_FLAG:
        if state.total_cost_usd >= BUDGET_USD_CAP:
            state.halt_reason = f"budget_cap_${BUDGET_USD_CAP:.2f}_reached"
            log(state.halt_reason)
            break
        if max_trials is not None and state.trial_idx >= max_trials:
            state.halt_reason = f"max_trials={max_trials}_reached"
            log(state.halt_reason)
            break

        task = random.choice(TASKS)
        model = random.choice(MODELS)
        state.trial_idx += 1  # bump per (bare+tramp) pair
        log(f"trial {state.trial_idx}: task={task['task_id']} model={model}")

        # Run BOTH arms back-to-back
        bare_result = run_bare_arm(task, model)
        state.record(task["domain"], model, "bare",
                      bare_result.get("converged", False),
                      bare_result.get("cost_usd", 0.0))
        tramp_result = run_trampoline_arm(task, model)
        state.record(task["domain"], model, "trampoline",
                      tramp_result.get("converged", False),
                      tramp_result.get("cost_usd", 0.0))

        trial_record = {
            "trial_idx": state.trial_idx,
            "ts": int(time.time()),
            "task_id": task["task_id"],
            "domain": task["domain"],
            "model": model,
            "bare": bare_result,
            "trampoline": tramp_result,
        }
        out_path = RESULTS_DIR / f"trial_{state.trial_idx:05d}_{task['task_id']}_{model}.json"
        out_path.write_text(json.dumps(trial_record, indent=2, default=str))
        log(f"  bare converged={bare_result.get('converged')} cost=${bare_result.get('cost_usd', 0.0):.5f}; "
            f"tramp converged={tramp_result.get('converged')} cost=${tramp_result.get('cost_usd', 0.0):.5f}")

        # CIEU r=1 per trial
        write_cieu(
            state=state,
            milestone=f"auto_benchmark_trial_{state.trial_idx}",
            y_star=f"{task['domain']}/{model}: bare vs trampoline on {task['task_id']}",
            actions=[
                f"bare: converged={bare_result.get('converged')} cost=${bare_result.get('cost_usd',0):.5f}",
                f"trampoline: converged={tramp_result.get('converged')} cost=${tramp_result.get('cost_usd',0):.5f} iters={tramp_result.get('iterations','?')}",
            ],
            y_t1=f"trial_idx={state.trial_idx}; cumulative_cost=${state.total_cost_usd:.4f}",
            r_t1=1,
            verify_cmd=task["verifier_cmd"][:200],
            verify_tail=f"bare exit={bare_result.get('verifier_exit','?')}; tramp halted={tramp_result.get('stopping_authority','?')}",
        )

        state.save()

        # Rolling report every 10 trials
        if state.trial_idx % ROLLING_REPORT_EVERY == 0:
            write_rolling_report(state, trial_record)
            log(f"  rolling report written (trial {state.trial_idx})")
            # r=0 milestone every 10
            n_trials = state.trial_idx
            converged_bare = sum(sum(state.cell_results.get(state.cell_key(t["domain"], m, "bare"), [])) for t in TASKS for m in MODELS)
            converged_tramp = sum(sum(state.cell_results.get(state.cell_key(t["domain"], m, "trampoline"), [])) for t in TASKS for m in MODELS)
            write_cieu(
                state=state,
                milestone=f"auto_benchmark_milestone_{n_trials}_trials",
                y_star=f"{n_trials}-trial milestone: aggregate bare vs trampoline",
                actions=[f"cumulative trials: {n_trials}",
                          f"cumulative API cost: ${state.total_cost_usd:.4f}",
                          f"rolling report at {REPORT_PATH}"],
                y_t1=f"bare_total_converged={converged_bare}, trampoline_total_converged={converged_tramp}",
                r_t1=0,
                verify_cmd=f"cat {REPORT_PATH}",
                verify_tail=f"report file size: {REPORT_PATH.stat().st_size if REPORT_PATH.exists() else 0} bytes",
            )

        # Adaptive task discovery every 50
        if state.trial_idx % ADAPTIVE_CHECK_EVERY == 0:
            candidates = adaptive_check(state)
            if candidates:
                log(f"  adaptive: candidates_for_replacement = {candidates}")

        # Inter-trial sleep
        time.sleep(INTER_TRIAL_SLEEP_S)

    state.save()
    write_rolling_report(state, {"halt_reason": state.halt_reason})
    log(f"auto_benchmark halted: {state.halt_reason or 'signal'}")


if __name__ == "__main__":
    max_trials_arg = None
    if len(sys.argv) > 1 and sys.argv[1] == "--max-trials":
        max_trials_arg = int(sys.argv[2])
    main(max_trials=max_trials_arg)
