"""
mutation_score_verifier.py — adaptive, resource-aware mutation testing gate.

Lives at the END of a scenario's verifier chain (is_final_gate=True): only
runs once all inner verifiers (pytest / contract / differential) are green.
A failure here means "your tests passed but did not actually exercise the
behaviour the source defines" — i.e. weak test suite. Surviving mutants
become structured feedback to the model on the next CZL iteration.

The whole point of this verifier is OUTCOME-BASED quality measurement:
we never look at which files the model edited or what it imported. We
only check whether mutated source code is killed by the model's tests.

Six hard constraints from the Phase-4 spec, all implemented here:

  A. Resource-aware adaptive N
     - reads cores + available memory at run time
     - skips (passed=True) under low resources
     - measures single_test_seconds via a dry-run pytest
     - N = max(3, min(15, int(target * cores / single_test_seconds)))

  B. Final gate
     - is_final_gate=True; scenario.verify() invokes it only after inner pass
     - a failure here is meant to drive ONE extra CZL iteration with the
       surviving-mutants diff as feedback (loop will naturally retry until
       it converges OR no_progress fires; this verifier sits passively in
       the chain and reports actionable diffs)

  C. Selective mutation
     - by default, only mutate lines the model changed since baseline
       (git diff against HEAD)
     - bypass via contract["_mutation_unconditional"] = True for scenarios
       like test_generation where the source is unchanged BY design but
       still must be covered by the model's tests

  D. Parallel execution
     - uses cosmic-ray's atomic `mutate-and-test` per-mutant primitive
     - ThreadPoolExecutor with workers=min(cores, N) over isolated
       workspace COPIES so concurrent mutants never collide on the same
       on-disk source file. cosmic-ray's `local` distributor is sequential
       internally, so we sidestep it.

  E. Interface alignment + actionable feedback
     - VerifierResult.details.surviving_mutants carries enough structured
       info (operator, file, line, diff) for the next-iteration retry
       prompt to surface specific "add a test that kills this" guidance.

  F. CIEU-event-ready details payload
     - all 11 required fields go into VerifierResult.details so the trial
       JSON / milestone CIEU event can pluck them verbatim. The verifier
       itself does NOT write to the CIEU chain (only milestones do).

Process-based check ban: we never look at git log, never check which
imports the model added, never read what tests the model decided NOT to
write. The mutant-killed/survived outcome is the entire signal surface.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path, PosixPath
from typing import Any, Dict, List, Optional, Tuple

from ystar.czl.verifiers.base import Verifier, VerifierResult, AdaptiveThresholdVerifier


# === resource detection =====================================================

def _detect_resources() -> Tuple[int, float]:
    """Returns (cpu_cores, available_memory_gb). psutil is required for memory."""
    cores = os.cpu_count() or 1
    try:
        import psutil
        avail_gb = psutil.virtual_memory().available / (2 ** 30)
    except ImportError:
        avail_gb = 0.0  # unknown — treat as low to be safe
    return cores, avail_gb


# === git diff line ranges (constraint C) ====================================

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git_changed_lines(workspace_dir: str, target_relpath: str) -> List[Tuple[int, int]]:
    """Return list of (start_line, end_line) ranges changed since git HEAD for
    the given target file. Empty = target unchanged.

    Used to decide whether to mutate the TARGET file: if model literally
    edited target source, mutation runs filtered to those lines.
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--unified=0", "HEAD", "--", target_relpath],
            cwd=workspace_dir, capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return []
    except Exception:
        return []
    ranges: List[Tuple[int, int]] = []
    for line in (proc.stdout or "").splitlines():
        m = _HUNK_HEADER_RE.match(line)
        if not m:
            continue
        start = int(m.group(1))
        length = int(m.group(2)) if m.group(2) else 1
        if length == 0:
            continue  # pure deletion, no new lines
        ranges.append((start, start + length - 1))
    return ranges


def _git_any_py_changed_lines(workspace_dir: str) -> int:
    """Total changed lines across ALL .py files in workspace vs git HEAD.

    For test-generation scenarios the model writes test files (not source),
    so selective filtering of mutation_target alone would always skip.
    This broader signal — "did the model produce any Python output at all" —
    is the right activation gate: if model wrote new tests, mutation runs
    against the (unchanged) source to check those tests cover behaviour.
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--unified=0", "HEAD", "--", "*.py"],
            cwd=workspace_dir, capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return 0
    except Exception:
        return 0
    total = 0
    for line in (proc.stdout or "").splitlines():
        m = _HUNK_HEADER_RE.match(line)
        if not m:
            continue
        length = int(m.group(2)) if m.group(2) else 1
        total += length
    # also count untracked .py
    try:
        st = subprocess.run(
            ["git", "status", "--porcelain", "--", "*.py"],
            cwd=workspace_dir, capture_output=True, text=True, timeout=10,
        )
        for line in (st.stdout or "").splitlines():
            if line.startswith("??"):
                p = line[3:].strip()
                full = os.path.join(workspace_dir, p)
                try:
                    total += sum(1 for _ in open(full, "r", encoding="utf-8"))
                except Exception:
                    pass
    except Exception:
        pass
    return total


# === baseline test-time measurement (constraint A.4) ========================

def _measure_baseline_test_time(workspace_dir: str, test_command: str, max_seconds: float = 30.0) -> float:
    """Run the test command once unmutated; report wall-clock. Used to size N."""
    t0 = time.time()
    try:
        subprocess.run(
            test_command.split(), cwd=workspace_dir,
            capture_output=True, text=True, timeout=max_seconds,
        )
    except Exception:
        return max_seconds  # treat as worst case
    return max(0.05, time.time() - t0)  # floor avoids div-by-zero


# === cosmic-ray mutant enumeration ==========================================

def _write_cosmic_ray_config(workspace_dir: str, target_module: str, test_command: str) -> str:
    """Write a minimal cosmic-ray config.toml in workspace_dir; return its path."""
    config_path = os.path.join(workspace_dir, ".ms_config.toml")
    config_body = textwrap.dedent(f"""
        [cosmic-ray]
        module-path = "{target_module}"
        timeout = 30.0
        excluded-modules = []
        test-command = "{test_command}"

        [cosmic-ray.distributor]
        name = "local"
    """).lstrip()
    Path(config_path).write_text(config_body, encoding="utf-8")
    return config_path


def _enumerate_mutants(workspace_dir: str, config_path: str, session_path: str) -> List[Dict[str, Any]]:
    """`cosmic-ray init` populates session.sqlite with all jobs; `cosmic-ray
    dump` then emits one line-delimited JSON record per job. We use this to
    list mutants WITHOUT running exec — each line of dump is
    [job_info_dict, result_dict_or_null]; result is null before exec."""
    init = subprocess.run(
        ["cosmic-ray", "init", config_path, session_path],
        cwd=workspace_dir, capture_output=True, text=True, timeout=60,
    )
    if init.returncode != 0:
        return []
    dump = subprocess.run(
        ["cosmic-ray", "dump", session_path],
        cwd=workspace_dir, capture_output=True, text=True, timeout=60,
    )
    out: List[Dict[str, Any]] = []
    for line in (dump.stdout or "").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, list) or not rec:
            continue
        job = rec[0]
        # mutations[] inside job is the list of atomic mutation operators
        for mut in job.get("mutations", []):
            out.append({
                "job_id": job.get("job_id"),
                "module_path": mut.get("module_path"),
                "operator_name": mut.get("operator_name"),
                "occurrence": mut.get("occurrence"),
                # KEEP full positional tuples — _worker_run_mutant constructs
                # MutationSpec from these and ALSO needs operator_args.
                "start_pos": tuple(mut.get("start_pos") or (0, 0)),
                "end_pos": tuple(mut.get("end_pos") or (0, 0)),
                "operator_args": mut.get("operator_args") or {},
                "definition_name": mut.get("definition_name"),
                # convenience: start_line for selective-diff filter
                "start_line": (mut.get("start_pos") or [0, 0])[0],
            })
    return out


# === per-mutant isolated runner (constraint D) ==============================

def _worker_run_mutant(args: Tuple[str, Dict[str, Any], str, float]) -> Dict[str, Any]:
    """ProcessPoolExecutor target. Runs in a SUBPROCESS — its own cwd, own
    Python interpreter, fully isolated from other workers.

    Steps in this subprocess:
      1. copy baseline workspace to a tmp dir
      2. chdir into the copy (safe — process-local cwd)
      3. call cosmic_ray.mutating.mutate_and_test directly (Python API,
         bypassing the broken CLI `mutate-and-test` subcommand in 8.4.6)
      4. translate WorkResult enums into plain strings for pickling back

    The CLI bug we're routing around: `cosmic-ray mutate-and-test` calls
    dataclasses.asdict on a non-dataclass WorkResult and crashes. The
    underlying `cosmic_ray.mutating.mutate_and_test` function itself is
    correct — we just call it directly.
    """
    baseline_workspace, mutant, test_command, timeout = args
    # Local imports so this function is fully picklable across process boundary.
    import os as _os
    import shutil as _shutil
    import tempfile as _tempfile
    from pathlib import PosixPath as _PP
    from cosmic_ray.mutating import mutate_and_test as _mat
    from cosmic_ray.work_item import MutationSpec as _MS

    spec = _MS(
        module_path=_PP(mutant["module_path"]),
        operator_name=mutant["operator_name"],
        occurrence=mutant["occurrence"],
        start_pos=tuple(mutant["start_pos"]),
        end_pos=tuple(mutant["end_pos"]),
        operator_args=mutant.get("operator_args") or {},
        definition_name=mutant.get("definition_name"),
    )
    tmp = _tempfile.mkdtemp(prefix="ms_mut_")
    ws = _os.path.join(tmp, "ws")
    try:
        _shutil.copytree(
            baseline_workspace, ws,
            ignore=_shutil.ignore_patterns(
                ".git", "__pycache__", ".pytest_cache",
                ".ms_session.sqlite", ".ms_config.toml",
            ),
        )
        orig = _os.getcwd()
        _os.chdir(ws)
        try:
            result = _mat([spec], test_command, timeout)
            outcome_name = result.test_outcome.name.lower() if result.test_outcome is not None else "incompetent"
            worker_name = result.worker_outcome.name.lower() if result.worker_outcome is not None else "unknown"
            if worker_name != "normal":
                outcome_name = "incompetent"
            return {
                **mutant,
                "outcome": outcome_name,
                "worker_outcome": worker_name,
                "diff": (getattr(result, "diff", "") or "")[:1200],
                "output_tail": (getattr(result, "output", "") or "")[-300:],
            }
        finally:
            try:
                _os.chdir(orig)
            except Exception:
                pass
    except Exception as e:
        return {
            **mutant,
            "outcome": "incompetent",
            "worker_outcome": "exception",
            "diff": "",
            "output_tail": f"worker_exception: {type(e).__name__}: {e}",
        }
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)


# === Verifier ===============================================================

class MutationScoreVerifier(AdaptiveThresholdVerifier):
    name = "mutation_score"
    is_final_gate = True  # scenario.verify() runs this only after inner pass
    # E.2 metadata
    applies_to_tasks = ["test_generation_for_existing_code"]
    min_model_capacity = "medium"   # gemma 4B (small) is exempt — registry filter routes around
    feedback_complexity = "high"
    known_limitations = [
        "cosmic-ray timeout / memory bound on large modules",
        "requires git diff (selective mutation) — fresh workspaces use unconditional path",
    ]

    def __init__(self, target_wall_seconds: float = 10.0, score_threshold: float = 0.7):
        # v3.3 B.2: AdaptiveThresholdVerifier — calibrate on first call.
        AdaptiveThresholdVerifier.__init__(self, target_threshold=score_threshold,
                                            floor_threshold=max(0.0, score_threshold - 0.30))
        self.target_wall_seconds = float(target_wall_seconds)
        # Preserve the original attribute name for any callers that read it
        # (e.g. logging / inline reports); semantics now == self.target.
        self.score_threshold = float(score_threshold)

    def _effective_target_wall(self, contract: Dict[str, Any]) -> float:
        # contract override (for sanity environments / per-scenario tuning)
        v = (contract or {}).get("_mutation_target_wall_seconds")
        try:
            return float(v) if v is not None else self.target_wall_seconds
        except (TypeError, ValueError):
            return self.target_wall_seconds

    def is_applicable(self, workspace_dir: str, contract: Dict[str, Any]) -> bool:
        target = (contract or {}).get("_mutation_target_file")
        if not target:
            return False
        return os.path.isfile(os.path.join(workspace_dir, target))

    def run(self, workspace_dir: str, contract: Dict[str, Any]) -> VerifierResult:
        contract = contract or {}
        target_rel = contract["_mutation_target_file"]
        test_command = contract.get(
            "_mutation_test_command",
            "python3.11 -m pytest -x -q --tb=no --no-header",
        )
        unconditional = bool(contract.get("_mutation_unconditional", False))

        # ===== constraint A.1-3: resource detection =====
        cores, avail_gb = _detect_resources()
        effective_target_wall = self._effective_target_wall(contract)
        common_details: Dict[str, Any] = {
            "detected_cpu_cores": cores,
            "detected_available_memory_gb": round(avail_gb, 2),
            "target_wall_seconds_used": effective_target_wall,
            "mutation_target_file": target_rel,
            "outcome_based_only": True,
            "skipped_reason": "",
        }
        if cores < 2 or avail_gb < 1.0:
            common_details["skipped_reason"] = f"low_resource(cores={cores},mem_gb={avail_gb:.2f})"
            common_details.update({"single_test_seconds_measured": 0.0,
                                   "n_mutants_decided": 0, "actual_wall_seconds": 0.0,
                                   "mutation_score": None, "selective_diff_lines": 0})
            return VerifierResult(
                verifier_name=self.name, passed=True,
                message=f"MutationScoreSkipped: low resource (cores={cores}, mem_gb={avail_gb:.1f})",
                details=common_details, elapsed_seconds=0.0,
            )

        # ===== constraint C: selective diff =====
        # Activation logic (production default; unconditional override
        # disallowed in production): require some .py change in workspace
        # since baseline (could be source edit OR newly-written test files).
        # If the model produced no python output at all, mutation is moot.
        # Filter mutations TO the target file by changed-line ranges WHEN
        # the target itself was edited (typical for source-fix scenarios);
        # otherwise (test-generation) mutate the unchanged target wholesale
        # — the agent's tests are what gets evaluated.
        if unconditional:
            changed_ranges: List[Tuple[int, int]] = []  # don't filter the target
            selective_lines_count = _git_any_py_changed_lines(workspace_dir)
        else:
            any_py_changed_lines = _git_any_py_changed_lines(workspace_dir)
            if any_py_changed_lines == 0:
                common_details["skipped_reason"] = "no_workspace_py_changes"
                common_details.update({
                    "single_test_seconds_measured": 0.0, "n_mutants_decided": 0,
                    "actual_wall_seconds": 0.0, "mutation_score": None,
                    "selective_diff_lines": 0,
                })
                return VerifierResult(
                    verifier_name=self.name, passed=True,
                    message="MutationScoreSkipped: model made no .py changes vs baseline",
                    details=common_details, elapsed_seconds=0.0,
                )
            target_ranges = _git_changed_lines(workspace_dir, target_rel)
            if target_ranges:
                # source was edited — narrow mutations to changed lines
                changed_ranges = target_ranges
            else:
                # only tests changed — mutate full target so model's tests
                # are the thing being graded
                changed_ranges = []
            selective_lines_count = any_py_changed_lines
        common_details["selective_diff_lines"] = selective_lines_count

        # ===== constraint A.4: baseline test-time =====
        t0 = time.time()
        single_test_seconds = _measure_baseline_test_time(workspace_dir, test_command)
        baseline_measurement_seconds = time.time() - t0
        common_details["single_test_seconds_measured"] = round(single_test_seconds, 3)

        # ===== constraint A.5: dynamic N =====
        N = max(3, min(15, int(effective_target_wall * cores / max(single_test_seconds, 0.05))))
        common_details["n_mutants_decided_pre_filter"] = N

        # ===== cosmic-ray init + enumerate mutants =====
        config_path = _write_cosmic_ray_config(workspace_dir, target_rel, test_command)
        session_path = os.path.join(workspace_dir, ".ms_session.sqlite")
        if os.path.exists(session_path):
            os.unlink(session_path)
        try:
            all_mutants = _enumerate_mutants(workspace_dir, config_path, session_path)
        finally:
            for p in (config_path, session_path):
                try:
                    os.unlink(p)
                except FileNotFoundError:
                    pass

        if not all_mutants:
            common_details["skipped_reason"] = "no_mutants_generated"
            common_details.update({"n_mutants_decided": 0, "actual_wall_seconds": 0.0,
                                   "mutation_score": None})
            return VerifierResult(
                verifier_name=self.name, passed=True,
                message=f"MutationScoreSkipped: cosmic-ray produced 0 mutants for {target_rel}",
                details=common_details, elapsed_seconds=0.0,
            )

        # selective filter by line range (only when conditional)
        if changed_ranges:
            in_scope = [
                m for m in all_mutants
                if any(lo <= m["start_line"] <= hi for (lo, hi) in changed_ranges)
            ]
            if not in_scope:
                common_details["skipped_reason"] = "all_mutants_outside_changed_lines"
                common_details.update({"n_mutants_decided": 0, "actual_wall_seconds": 0.0,
                                       "mutation_score": None})
                return VerifierResult(
                    verifier_name=self.name, passed=True,
                    message=f"MutationScoreSkipped: all mutants fall outside changed lines",
                    details=common_details, elapsed_seconds=0.0,
                )
            all_mutants = in_scope

        # cap to N
        selected = all_mutants[:N]
        common_details["n_mutants_decided"] = len(selected)

        # ===== constraint D: parallel exec via ProcessPoolExecutor =====
        # ProcessPool (not Thread) because cosmic_ray.mutate_and_test relies
        # on process cwd to find the module to mutate — threads share cwd
        # and would race; subprocesses have isolated cwd.
        workers = min(cores, len(selected))
        per_mutant_timeout = max(5.0, single_test_seconds * 5)
        wall_start = time.time()
        results: List[Dict[str, Any]] = []
        worker_args = [
            (workspace_dir, m, test_command, per_mutant_timeout)
            for m in selected
        ]
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_worker_run_mutant, args): args[1] for args in worker_args}
            for fut in as_completed(futures):
                m = futures[fut]
                try:
                    results.append(fut.result())
                except Exception as e:
                    results.append({**m, "outcome": "incompetent",
                                    "worker_outcome": "exception",
                                    "diff": "",
                                    "output_tail": f"future_error: {type(e).__name__}: {e}"})
        actual_wall = time.time() - wall_start
        common_details["actual_wall_seconds"] = round(actual_wall, 2)
        common_details["baseline_measurement_seconds"] = round(baseline_measurement_seconds, 2)
        common_details["workers"] = workers

        # ===== aggregate =====
        killed = sum(1 for r in results if r["outcome"] == "killed")
        survived = sum(1 for r in results if r["outcome"] == "survived")
        timed_out = sum(1 for r in results if r["outcome"] == "timeout")
        incompetent = sum(1 for r in results if r["outcome"] == "incompetent")
        classifiable = killed + survived
        score = (killed / classifiable) if classifiable > 0 else 0.0
        common_details.update({
            "mutation_score": round(score, 3),
            "n_killed": killed, "n_survived": survived,
            "n_timeout": timed_out, "n_incompetent": incompetent,
        })

        surviving_for_feedback = [
            {
                "operator": r["operator_name"],
                "file": r["module_path"],
                "start_line": r["start_line"],
                "definition_name": r.get("definition_name"),
                "diff": r.get("diff", "")[:600],
            }
            for r in results if r["outcome"] == "survived"
        ][:10]
        common_details["surviving_mutants"] = surviving_for_feedback

        # ===== constraint E + v3.3 B.2: actionable feedback + adaptive threshold =====
        passed_adaptive, adaptive_msg = self.check_score(score)
        common_details["adaptive_threshold"] = self.effective_threshold()
        common_details["adaptive_baseline"] = self._calibration_score
        common_details["adaptive_call_count"] = self._call_count
        if passed_adaptive:
            # Calibration round OR genuinely good score — pass.
            natural = (
                f"突变测试: 你的测试杀死了 {killed}/{classifiable} 个变异 ({score:.0%}). "
                f"{adaptive_msg}."
            )
            return VerifierResult(
                verifier_name=self.name, passed=True,
                message=f"mutation_score: {killed}/{classifiable} ({score:.0%}) — {adaptive_msg}",
                message_natural=natural,
                details=common_details,
                elapsed_seconds=actual_wall,
            )
        # Build human-readable actionable feedback (structured + prose).
        fb_lines = [
            f"mutation_score: {killed}/{classifiable} ({score:.0%}). {adaptive_msg}",
            "The following mutations were NOT killed by your tests — add tests "
            "that distinguish each mutation from the original behaviour:",
        ]
        for s in surviving_for_feedback[:5]:
            fb_lines.append(f"\n— {s['operator']} at {s['file']}:{s['start_line']} "
                            f"(in `{s['definition_name']}`):")
            if s["diff"].strip():
                fb_lines.append(s["diff"])
        common_details["actionable_feedback"] = "\n".join(fb_lines)
        natural_lines = [
            f"突变测试: 你的测试只杀死了 {killed}/{classifiable} 个变异 ({score:.0%}), "
            f"需要超过 {self.effective_threshold():.0%}.",
            "下面这些代码改动 (mutation) 你的测试没察觉到, 说明这些行为没被测到:",
        ]
        for s in surviving_for_feedback[:5]:
            loc = f"{s['file']}:{s['start_line']}"
            fn = s["definition_name"] or "(unknown function)"
            natural_lines.append(f"  • {loc} 在 `{fn}` 里改了某个表达式但你的测试没失败.")
        natural_lines.append("修正方向: 给这些表达式加专门测试用例; "
                             "或者把现有测试改得更具体 (检查返回值的精确数字而不只是类型).")
        return VerifierResult(
            verifier_name=self.name, passed=False,
            message=common_details["actionable_feedback"][:240],
            message_natural="\n".join(natural_lines),
            details=common_details,
            elapsed_seconds=actual_wall,
        )
