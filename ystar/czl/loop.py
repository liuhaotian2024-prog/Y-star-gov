"""
ystar.czl.loop — composition layer for the indie-facing CZL run

This file does NOT reimplement convergence. It composes existing pieces:

  ystar.kernel.nl_to_contract.translate_to_contract  ← user NL → IntentContract
  ystar.governance.contract_lifecycle.ContractDraft  ← Y* lifecycle
  ystar.governance.residual_loop_engine.ResidualLoopEngine  ← Rt+1 loop
  ystar.rules.auto_rewrite.auto_rewrite_executor    ← retry transformation
  ystar.adapters.boundary_enforcer                   ← hard action gate
  ystar.adapters.cieu_writer                         ← 5-tuple audit log

The product value-add is the *friction-first orchestration*: confidence-gated
auto-activation, backend abstraction, scenario plug-in, and an honest cost
report at the end. See docs/CZL_PRODUCT_DESIGN.md.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# === ystar imports (kept as-is, do NOT modify upstream) ===
from ystar.kernel.nl_to_contract import (
    translate_to_contract,
    diagnose_compilation,
)
from ystar.governance.contract_lifecycle import ContractDraft
from ystar.governance.residual_loop_engine import ResidualLoopEngine
from ystar.cieu.schema import generate_event_id, DECISION_ALLOW, DECISION_DENY

# === local types ===
from ystar.czl.scenarios.base import Scenario
from ystar.czl.backends.base import Backend
from ystar.czl.verifiers.base import VerifierResult


_log = logging.getLogger("ystar.czl.loop")


# Confidence thresholds — see docs/CZL_PRODUCT_DESIGN.md §6.1
# These are deliberately more permissive than ystar's default 0.7 because
# the indie use case has different risk profile (low-stakes coding tasks,
# user owns their own repo, undo is one command away).
CONF_AUTO_ACTIVATE = 0.85          # ≥ this: no UI shown at all
CONF_TOAST_DEFAULT_YES = 0.70       # 0.70 - 0.85: 5-second informational toast
TOAST_TIMEOUT_SECONDS = 5.0

# Fields with semantic-inversion risk — always show even on high confidence
INVERSION_RISK_FIELDS = {"invariant", "value_range", "optional_invariant"}


@dataclass
class CZLRun:
    """A single CZL run request — what the user asked for."""
    task_description: str                # natural-language goal
    scenario: Scenario                   # how to verify it
    backend: Backend                     # which LLM to call
    workspace_dir: str                   # where to run (working directory)
    max_iterations: int = 10
    strict: bool = False                 # if True, force human review on any ambiguity
    auto_undo_on_failure: bool = True    # stash diff before run, restorable
    run_id: str = field(default_factory=lambda: generate_event_id())


@dataclass
class CZLResult:
    """A single CZL run outcome — what got shipped (or why not)."""
    run_id: str
    converged: bool                       # Rt+1 == 0 at end?
    final_residual: float                 # last Rt+1 value
    iterations: int                       # how many U steps taken
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0          # backend-reported cost
    contract_dict: Dict[str, Any] = field(default_factory=dict)
    contract_confidence: float = 0.0
    contract_method: str = ""             # "llm" | "regex"
    cieu_events: List[Dict[str, Any]] = field(default_factory=list)
    final_verifier_report: Optional[Dict[str, Any]] = None
    failure_reason: str = ""              # filled if not converged
    duration_seconds: float = 0.0
    # Indie-facing copy: cost comparison string for stdout
    cost_summary_line: str = ""
    # Why the loop stopped. Explicit field so downstream tooling can
    # distinguish "shipped at Rt+1=0" from "ran out of iterations" from
    # other early-exit branches. Pre-v3 callers that only check `converged`
    # keep working; new callers can branch on this.
    halted_due_to: str = ""               # converged | max_iter_exhausted | user_rejected_contract | scenario_returned_empty_plan | exception

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        return d


# === toast UI hook ============================================================
# The actual terminal UI implementation lives in cli.py.
# Here we just take a callable so loop.py stays testable headlessly.

def _default_toast(prompt: str, timeout: float, default_yes: bool) -> bool:
    """Headless default — assume yes. CLI overrides this."""
    _log.info("CZL toast (headless): %s [default=yes]", prompt)
    return default_yes


# === public entry =============================================================

def run_scenario(
    request: CZLRun,
    toast_fn: Callable[[str, float, bool], bool] = _default_toast,
) -> CZLResult:
    """
    Execute one CZL run. This is the canonical entry point used by the CLI,
    the AgentSkill, and Python embedders.

    Flow:
      1. Compile NL task → IntentContract draft (LLM via nl_to_contract).
      2. Diagnose confidence → maybe show toast, maybe auto-activate.
      3. Stash workspace if auto_undo_on_failure.
      4. Spawn the scenario's plan; for each step:
           - call backend → tool actions
           - run scenario.verify() → list of VerifierResults
           - write CIEU event for each
           - if any violations: emit feedback via auto_rewrite and retry
      5. When Rt+1 == 0 OR max_iterations exceeded → stop.
      6. Return CZLResult with cost summary line ready for stdout.
    """
    started = time.time()
    result = CZLResult(run_id=request.run_id, converged=False, final_residual=float("inf"), iterations=0)

    # --- Step 1: compile NL → IntentContract -------------------------------
    contract_dict, method, confidence = translate_to_contract(
        request.task_description,
        api_call_fn=None,   # use real provider, configured via env
    )
    result.contract_dict = contract_dict
    result.contract_confidence = confidence
    result.contract_method = method

    # Augment contract with scenario-specific invariants (the Y* core)
    contract_dict = _merge_contract(contract_dict, request.scenario.y_star_invariants())

    # --- Step 2: confidence routing ----------------------------------------
    diag = diagnose_compilation(request.task_description, contract_dict)
    needs_inspection = _needs_user_inspection(
        confidence=confidence,
        contract_dict=contract_dict,
        diag=diag,
        strict=request.strict,
    )
    if needs_inspection:
        toast_text = _format_toast_text(contract_dict, confidence, method, diag)
        approved = toast_fn(toast_text, TOAST_TIMEOUT_SECONDS, default_yes=(not request.strict))
        if not approved:
            result.failure_reason = "user_rejected_contract"
            result.halted_due_to = "user_rejected_contract"
            result.duration_seconds = time.time() - started
            return result

    # --- Step 3: stash for undo --------------------------------------------
    stash_ref = None
    if request.auto_undo_on_failure:
        stash_ref = _git_stash_create(request.workspace_dir, request.run_id)

    # --- Step 4: the CZL loop ----------------------------------------------
    # NOTE: we wire ResidualLoopEngine here but in MVP we use a simpler
    # step-by-step driver, because indie tasks have explicit plan structure.
    # ResidualLoopEngine's autonomy_engine integration is reserved for
    # multi-agent setups where the next U is computed by another agent.
    last_violations: List[VerifierResult] = []
    feedback_block: str = ""

    # The loop drives Rt+1 to zero. Plan steps advance one-per-iteration until
    # we run out of distinct steps; further iterations re-attempt the final
    # step with accumulated verifier feedback. Most MVP scenarios emit a
    # single PlanStep — they rely entirely on this re-attempt behaviour for
    # convergence. See docs/CZL_PRODUCT_DESIGN.md §3.
    #
    # We re-call scenario.plan() each iteration so user_prompt reflects the
    # current workspace (post-edit) state — without this, small models keep
    # seeing the original file content even after they've changed it, and
    # get confused about what's already been done.
    for step_idx in range(request.max_iterations):
        plan_steps = request.scenario.plan(request.task_description, request.workspace_dir)
        if not plan_steps:
            result.failure_reason = "scenario_returned_empty_plan"
            result.halted_due_to = "scenario_returned_empty_plan"
            break
        step = plan_steps[min(step_idx, len(plan_steps) - 1)]
        result.iterations = step_idx + 1

        # 4a. ask the backend to produce the action for this step
        backend_response = request.backend.invoke(
            system_prompt=request.scenario.system_prompt(),
            user_prompt=step.user_prompt + ("\n\n" + feedback_block if feedback_block else ""),
            workspace_dir=request.workspace_dir,
            contract=contract_dict,
        )
        result.total_input_tokens += backend_response.input_tokens
        result.total_output_tokens += backend_response.output_tokens
        result.total_cost_usd += backend_response.cost_usd

        # 4b. apply the backend's proposed actions, gated by boundary_enforcer
        for action in backend_response.actions:
            cieu_event = _build_cieu_event(
                run_id=request.run_id,
                step_idx=step_idx,
                action=action,
                contract_dict=contract_dict,
                workspace_dir=request.workspace_dir,
            )
            allowed = _enforce_boundary(action, contract_dict)
            cieu_event["decision"] = DECISION_ALLOW if allowed else DECISION_DENY
            result.cieu_events.append(cieu_event)
            if allowed:
                request.scenario.apply_action(action, request.workspace_dir)

        # 4c. run scenario verifiers → compute Rt+1
        verifier_results = request.scenario.verify(request.workspace_dir, contract_dict)
        last_violations = [v for v in verifier_results if not v.passed]
        residual = float(len(last_violations))
        result.final_residual = residual

        if residual == 0.0:
            # converged — ship the current workspace as-is. The break here is
            # what stops the loop touching a known-good answer; downstream
            # consumers can rely on halted_due_to=="converged" to know the
            # post-state files reflect the converged iteration.
            result.converged = True
            result.halted_due_to = "converged"
            result.final_verifier_report = _summarize_verifiers(verifier_results)
            break

        # 4d. not converged — generate feedback via auto_rewrite-style logic
        feedback_block = _format_feedback_for_retry(last_violations)
        # (loop continues for next step)

    # --- Step 5: finalize ---------------------------------------------------
    if not result.converged:
        if not result.halted_due_to:
            result.halted_due_to = "max_iter_exhausted"
        result.failure_reason = (
            f"did_not_converge_after_{result.iterations}_iterations: "
            + "; ".join(v.message for v in last_violations[:5])
        )
        if stash_ref and request.auto_undo_on_failure:
            # leave the stash in place — user can `ystar czl undo` if they want
            _log.info("CZL did not converge; stash %s retained for undo.", stash_ref)

    result.duration_seconds = time.time() - started
    result.cost_summary_line = _format_cost_summary(result, request.backend)
    return result


# === helpers =================================================================

def _merge_contract(user_contract: Dict[str, Any], scenario_invariants: Dict[str, Any]) -> Dict[str, Any]:
    """Merge user-derived contract with scenario hard-coded invariants.
    Scenario invariants are non-negotiable (this is Y* core); user contract is additive.
    """
    merged = dict(user_contract)
    for key, val in scenario_invariants.items():
        if key in merged and isinstance(merged[key], list) and isinstance(val, list):
            merged[key] = list({*merged[key], *val})  # set union, preserves duplicates dedup
        else:
            merged[key] = val
    return merged


def _needs_user_inspection(
    *,
    confidence: float,
    contract_dict: Dict[str, Any],
    diag: Any,
    strict: bool,
) -> bool:
    """Decide whether to show the toast / approval UI.

    See docs/CZL_PRODUCT_DESIGN.md §6.1 for full table.
    """
    if strict:
        # strict mode → always inspect if confidence < ystar's stock 0.7 or ambiguities
        return diag.requires_human_review
    # default (indie) mode:
    if confidence < CONF_AUTO_ACTIVATE:
        return True
    # high confidence — but check inversion-risk fields
    for risky in INVERSION_RISK_FIELDS:
        if risky in contract_dict and contract_dict[risky]:
            return True
    return False


def _format_toast_text(contract: Dict[str, Any], conf: float, method: str, diag: Any) -> str:
    """One-line summary suitable for terminal toast."""
    fields_present = [k for k, v in contract.items() if v]
    summary = ", ".join(fields_present[:4])
    return (
        f"Closure understood your rules as: [{summary}]. "
        f"(via {method}, confidence {conf:.0%}). "
        f"Press ↓ for details, Enter to accept, or wait {TOAST_TIMEOUT_SECONDS:.0f}s for auto-accept."
    )


def _enforce_boundary(action: Dict[str, Any], contract: Dict[str, Any]) -> bool:
    """Delegate to ystar.adapters.boundary_enforcer if available, else permissive.
    Wrapped here so tests can stub it. Real wiring done in cli.py at startup.
    """
    # MVP: minimal in-line check; replace with adapters.boundary_enforcer.check()
    # once we have full action-format compatibility verified.
    deny = contract.get("deny", [])
    text_blob = json.dumps(action, default=str)
    for needle in deny:
        if needle in text_blob:
            return False
    return True


def _build_cieu_event(
    *,
    run_id: str,
    step_idx: int,
    action: Dict[str, Any],
    contract_dict: Dict[str, Any],
    workspace_dir: str,
) -> Dict[str, Any]:
    """Construct a CIEU event dict aligned with ystar.cieu.schema column constants.
    The actual DB insert is delegated to adapters.cieu_writer.
    """
    return {
        "event_id": generate_event_id(),
        "session_id": run_id,
        "agent_id": "ystar-czl",
        "event_type": action.get("type", "tool_use"),
        "task_description": f"czl_step_{step_idx}",
        "contract_hash": str(hash(json.dumps(contract_dict, sort_keys=True, default=str))),
        "params_json": json.dumps(action, default=str),
        "file_path": action.get("path", ""),
        "command": action.get("command", ""),
        "chain_depth": step_idx,
        "created_at": time.time(),
    }


def _format_feedback_for_retry(violations: List[VerifierResult]) -> str:
    """Compose the retry-feedback text block fed back to the LLM next iteration.

    Includes a tail of each failing verifier's stdout so the model sees the
    concrete failure (e.g. the pytest assertion line) — without this signal,
    small models cannot distinguish between competing valid fixes that
    differ only in test-observable behaviour.
    """
    if not violations:
        return ""
    lines = ["### Previous attempt did NOT converge. Address each issue:"]
    for v in violations[:10]:
        lines.append(f"- [{v.verifier_name}] {v.message}")
        if v.details:
            stdout_tail = (v.details.get("stdout") or "")[-1000:]
            if stdout_tail.strip():
                lines.append("  verifier output:")
                lines.append("  ```")
                for line in stdout_tail.strip().splitlines()[-25:]:
                    lines.append(f"  {line}")
                lines.append("  ```")
    lines.append("")
    lines.append(
        "Re-emit the full corrected content of any file that still has issues. "
        "Do not restart from scratch. If a pytest failure shows the test "
        "expects a specific type/value, your fix must produce that — the test "
        "is the spec, not the type annotation."
    )
    return "\n".join(lines)


def _summarize_verifiers(results: List[VerifierResult]) -> Dict[str, Any]:
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "by_verifier": {r.verifier_name: r.passed for r in results},
    }


def _format_cost_summary(result: CZLResult, backend: Backend) -> str:
    """The single most important line of marketing copy. See §6.4."""
    if not result.converged:
        return f"[czl] did not converge after {result.iterations} iterations (cost: ${result.total_cost_usd:.4f})"
    # estimate frontier-equivalent cost
    frontier_per_M_input = 5.00
    frontier_per_M_output = 25.00
    frontier_cost = (
        result.total_input_tokens / 1_000_000 * frontier_per_M_input
        + result.total_output_tokens / 1_000_000 * frontier_per_M_output
    )
    if result.total_cost_usd > 0 and frontier_cost > result.total_cost_usd:
        ratio = frontier_cost / max(result.total_cost_usd, 1e-9)
        return (
            f"[czl] converged in {result.iterations} iterations via {backend.name} → "
            f"cost ${result.total_cost_usd:.4f} (vs ~${frontier_cost:.4f} on Claude Opus, {ratio:.0f}× cheaper)"
        )
    elif result.total_cost_usd == 0:
        return (
            f"[czl] converged in {result.iterations} iterations via {backend.name} (local) → "
            f"cost $0.00 (would have been ~${frontier_cost:.4f} on Claude Opus)"
        )
    else:
        return f"[czl] converged in {result.iterations} iterations via {backend.name} → cost ${result.total_cost_usd:.4f}"


def _git_stash_create(workspace_dir: str, run_id: str) -> Optional[str]:
    """Best-effort: stash current working-tree changes so `ystar czl undo` works.
    Returns the stash ref or None if not a git repo.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "-C", workspace_dir, "stash", "push", "--include-untracked", "-m", f"czl-pre-run-{run_id}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and "No local changes" not in result.stdout:
            return f"czl-pre-run-{run_id}"
    except Exception as e:
        _log.warning("Could not create git stash for undo: %s", e)
    return None
