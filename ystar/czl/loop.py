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
import os
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
from typing import Set  # for IterSnapshot


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
    # max_iterations now defaults to 50 (v3 spec); callers should pass an
    # explicit value rather than rely on this default in production. Trial
    # harnesses must accept it as a config/CLI param.
    max_iterations: int = 50
    # v5.0: trajectory-based early stop removed — oscillation halt is now
    # owned by ResidualLoopEngine.
    strict: bool = False                 # if True, force human review on any ambiguity
    auto_undo_on_failure: bool = True    # stash diff before run, restorable
    run_id: str = field(default_factory=lambda: generate_event_id())


@dataclass
class IterSnapshot:
    """v3.7: per-iter snapshot for dominance-based rollback ranking.

    `passing_tests` / `failing_tests` are sets of test identifiers
    (e.g. `test_data_pipeline.py::test_load_records_success`) extracted
    from the pytest verifier's per_test_status via
    ystar.czl.reflection.transitions.extract_test_status. Empty when no
    pytest verifier ran or per_test_status was unavailable; dominance
    semantics then degrade gracefully (no rollback fires).
    """
    iter_idx: int
    residual: float
    commit_sha: str
    passing_tests: Set[str]
    failing_tests: Set[str]


def dominates(a: "IterSnapshot", b: "IterSnapshot") -> bool:
    """v5.0.3 strict-superset-only dominance.

    a dominates b iff a.passing_tests is a STRICT SUPERSET of b.passing_tests
    (a passes everything b passes PLUS at least one more). Equal passing
    sets explicitly do NOT count as dominance.

    Why v3.7's iter_idx tie-break was removed:
      a re-emit-by-name protocol with merge-by-name means re-emitting the
      same N functions produces an IDENTICAL file blob. The v3.7 tie-break
      then fired every iter (passing_set unchanged, earlier iter
      "dominates" → rollback). The model made apparent progress (writes
      landed at apply layer), but rollback erased it because tie-break
      treated "identical state" as a dominance event.

    "Equivalent state" is not "better state". Removed.

    Empty passing sets on both sides → False (graceful degradation when
    pytest verifier didn't produce per_test_status).
    """
    if not a.passing_tests and not b.passing_tests:
        return False
    # set > set is strict superset in Python — exactly what we want.
    return a.passing_tests > b.passing_tests


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
    cost_summary_line: str = ""
    stopping_authority: str = ""
    halted_due_to: str = ""
    residual_trajectory: List[float] = field(default_factory=list)
    # v3.7 T2: full prompts the model saw per iter (system + user + feedback_block
    # incl. META). Stored so trial-level diagnostics can verify "did the model
    # actually see regression META at iter N?". Bench harness writes to trial JSON.
    iter_prompts: List[str] = field(default_factory=list)
    # v3.7 T1: per-iter snapshots for rollback diagnostics
    iter_snapshots: List[Dict[str, Any]] = field(default_factory=list)
    # v4.0 T4: per-iter probe executions (List[List[probe_result_dict]])
    iter_probes: List[List[Dict[str, Any]]] = field(default_factory=list)
    # v5.0.3: raw model response text per iter. Captures backend_response.raw_text
    # so trial diagnostics can answer "what did gemma actually output" — the
    # data we needed for v5.0.2 post-mortem and didn't have.
    iter_responses: List[str] = field(default_factory=list)
    # v5.2 telemetry: pre-action focus-constraint gate counts. Cumulative
    # across the whole run. `gate_denied_count` is the number of actions
    # that were hard-denied by the gate; `gate_soft_notes_count` is the
    # number that were allowed-with-advisory. `gate_per_field_denials`
    # tracks which FocusConstraint field name drove each denial so we can
    # see if any field is over-restrictive in practice.
    gate_denied_count: int = 0
    gate_soft_notes_count: int = 0
    gate_per_field_denials: Dict[str, int] = field(default_factory=dict)
    gate_denied_paths: List[str] = field(default_factory=list)  # diagnostic

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

    # v5.0: capability-tier injection removed — Trampoline targets only
    # frontier and cheap cloud APIs (both at or above "medium" capacity);
    # tier-conditioned coaching paths have been deleted.
    # v3.3 B.3: trial_id so scenarios know when to reset adaptive-threshold
    # verifiers' calibration state across trials. CZLRun.run_id is unique
    # per run, so re-use it as the trial_id.
    contract_dict["trial_id"] = request.run_id

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
            result.stopping_authority = "user_rejected_contract"
            result.halted_due_to = "user_rejected_contract"
            result.duration_seconds = time.time() - started
            return result

    # --- Step 3: stash for undo --------------------------------------------
    stash_ref = None
    if request.auto_undo_on_failure:
        stash_ref = _git_stash_create(request.workspace_dir, request.run_id)

    # --- Step 4: the CZL loop (v5.0 — RLE-driven) --------------------------
    # v5.0: ResidualLoopEngine is the closed-loop control authority. Every
    # iter constructs a structured ResidualState (the Y_{t+1} of CZL's CIEU
    # tuple), dispatches it to RLE via on_cieu_event, and reads RLE's
    # halt-event emission (CONVERGED / OSCILLATION / ESCALATE) to decide
    # whether to continue. RLE owns those decisions.
    last_violations: List[VerifierResult] = []
    feedback_block: str = ""

    from ystar.czl.residual import (
        ResidualState, build_residual_state, czl_distance_function,
        Y_STAR_ALL_PASS,
    )
    from ystar.czl.autonomy import CZLAutonomyEngine, FocusConstraint

    # In-memory halt-aware CIEU sink — captures RLE's emitted events so
    # the loop can read halt state without polling a real DB.
    class _HaltAwareSink:
        def __init__(self) -> None:
            self.events: List[Dict[str, Any]] = []

        def write_dict(self, ev: Dict[str, Any]) -> bool:
            self.events.append(ev)
            return True

        def latest_halt_event_type(self) -> Optional[str]:
            for ev in reversed(self.events):
                t = ev.get("event_type", "")
                if t in (
                    "RESIDUAL_LOOP_CONVERGED",
                    "RESIDUAL_LOOP_OSCILLATION",
                    "RESIDUAL_LOOP_ESCALATE",
                ):
                    return t
            return None

    _czl_autonomy = CZLAutonomyEngine()
    _czl_sink = _HaltAwareSink()
    _rle = ResidualLoopEngine(
        autonomy_engine=_czl_autonomy,
        cieu_store=_czl_sink,
        target_provider=lambda ev: ev.get("params", {}).get("target_y_star"),
        max_iterations=50,           # RLE's own max — generous; oscillation usually fires first
        convergence_epsilon=0.001,   # czl_distance_function returns 0.0 when no failures
        damping_gamma=0.95,
        distance_function=czl_distance_function,
    )

    # v5.0 Part B: wire OmissionEngine + InterventionEngine. Both use the
    # InMemoryOmissionStore + an explicit NullCIEUStore so this loop creates
    # ZERO SQLite side effects — `ls *.db` after a run must be empty.
    # NOTE the asymmetry between the two engines:
    #   - OmissionEngine treats `cieu_store=None` as the "no persistence"
    #     signal (its default sentinel is _DEFAULT_CIEU_STORE).
    #   - InterventionEngine, however, treats `cieu_store=None` as "fall back
    #     to a real SQLite CIEUStore at .ystar_cieu_intervention.db". To
    #     keep this loop side-effect-free we MUST pass an explicit
    #     NullCIEUStore() to InterventionEngine.
    from ystar.governance.omission_engine import OmissionEngine
    from ystar.governance.omission_store import InMemoryOmissionStore
    from ystar.governance.omission_models import GovernanceEvent, GEventType
    from ystar.governance.intervention_engine import InterventionEngine
    from ystar.governance.intervention_models import GateDecision
    from ystar.governance.cieu_store import NullCIEUStore
    from ystar.czl.coding_agent_pack import (
        CodingAgentEventType,
        TRAMPOLINE_GATING_POLICY,
        register_coding_agent_rules,
        register_post_declare_done_obligation,
    )

    _omission_store = InMemoryOmissionStore()
    _omission_engine = OmissionEngine(
        store=_omission_store,
        cieu_store=None,             # NullCIEUStore — no .ystar_cieu_omission.db
    )
    register_coding_agent_rules(_omission_engine.registry)
    _intervention_engine = InterventionEngine(
        omission_store=_omission_store,
        cieu_store=NullCIEUStore(),  # explicit no-op — no .ystar_cieu_intervention.db
        gating_policy=TRAMPOLINE_GATING_POLICY,
    )

    # actor_id has to be specific (not "agent" / "any") — the intervention
    # engine's constitutional rule rejects generic ids. Use the backend name
    # so the gating is bound to which model the loop is currently driving.
    _coding_actor_id = f"coding_agent.{getattr(request.backend, 'name', 'unknown')}"
    _coding_entity_id = f"coding_agent.{request.run_id}"

    # v5.2: pre-action gate state. Each iter, after action parsing and
    # before scenario.apply_action, the gate compares the agent's action
    # to the active FocusConstraint. Hard violations DENY; soft violations
    # log advisory notes. Always surface to the next-iter prompt (no silent
    # drops — v5.0.2 lesson).
    _gate_rejections: List[Dict[str, Any]] = []
    _gate_soft_notes: List[Dict[str, Any]] = []

    def _focus_constraint_gate(action: Any, fc: Optional["FocusConstraint"]) -> Tuple[str, str, Optional[str]]:
        """Compare a parsed action against the active FocusConstraint.

        Returns (decision, reason, field_violated):
          - decision: "allow" | "deny"
          - reason:   human-readable, structured for prompt rendering
          - field_violated: name of the FocusConstraint field that hard-denied,
                            or None on allow / soft / no-violation

        Pure structural / set comparison — NEVER calls an LLM (v5.2 design
        constraint #1). Iterates fc.enforcement.items() so future fields
        added to FocusConstraint pick up gating behaviour without code
        changes here (design constraint #2 + #3).
        """
        if fc is None:
            return ("allow", "", None)
        payload = action.payload if hasattr(action, "payload") else (
            action if isinstance(action, dict) else {})
        action_path = (payload or {}).get("path", "") or ""

        for field_name, level in fc.enforcement.items():
            if level == "off":
                continue
            field_value = getattr(fc, field_name, None)
            if not field_value:
                continue  # nothing to enforce on this field this iter

            violation_reason: Optional[str] = None
            if field_name == "allowed_files":
                # Pure set membership. action_path may be empty (e.g. bare
                # ```python block that the scenario routes internally) — in
                # that case we have no path to compare against, so we don't
                # flag a violation here. Scenarios needing stricter behaviour
                # can layer their own checks.
                if action_path and action_path not in field_value:
                    violation_reason = (
                        f"path {action_path!r} not in allowed_files "
                        f"{sorted(field_value)}"
                    )
            elif field_name == "target_cluster":
                tc_file = (field_value or {}).get("file")
                if tc_file and action_path and action_path != tc_file:
                    violation_reason = (
                        f"target_cluster locks focus on {tc_file!r} "
                        f"(file:line {tc_file}:{(field_value or {}).get('lineno', '?')}, "
                        f"{(field_value or {}).get('count', '?')} failures); "
                        f"action targeted {action_path!r}"
                    )
            # Future fields land here. The gate stays field-name-iterable.

            if violation_reason is None:
                continue

            if level == "hard":
                return ("deny", violation_reason, field_name)
            # soft: record advisory note, continue iterating other fields
            _gate_soft_notes.append({
                "path": action_path, "field": field_name,
                "reason": violation_reason,
                "rationale": fc.rationale,
            })
            result.gate_soft_notes_count += 1

        return ("allow", "", None)

    # Open the post-declare-done obligation. It must be fulfilled by either a
    # VERIFIER_PASSED or a generic COMPLETION_EVENT before we accept any
    # declare_done from the loop.
    register_post_declare_done_obligation(
        _omission_engine,
        session_id=request.run_id,
        actor_id=_coding_actor_id,
        entity_id=_coding_entity_id,
        due_within_secs=max(60.0, float(request.max_iterations) * 30.0),
    )

    def _emit_governance(event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """Emit one GovernanceEvent into the omission engine for this run."""
        try:
            _omission_engine.ingest_event(GovernanceEvent(
                event_type=event_type,
                entity_id=_coding_entity_id,
                actor_id=_coding_actor_id,
                payload=payload or {},
                source="czl.loop",
            ))
        except Exception as _exc:
            _log.debug("governance emit %s failed: %s", event_type, _exc)

    # Seed dispatch event so the stuck-after-dispatch rule has a trigger.
    _emit_governance(GEventType.TASK_DISPATCHED, {"task": request.task_description[:200]})
    # Track passing tests across iters for delta_from_prev (v3.6 reused)
    _prev_passing_tests: Optional[Set[str]] = None
    # Current focus_constraint flowed into next iter's contract
    _active_focus_constraint: Optional[FocusConstraint] = None

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
    # v3.5 T5: cross-iter ReflectionAnalyzer — cluster + repetition.
    # Lives for the lifetime of this CZLRun. After each verify(), we
    # record results into the analyzer, and analyze() yields a META block
    # that prepends to the next-iter feedback prompt.
    from ystar.czl.reflection import ReflectionAnalyzer
    reflection = ReflectionAnalyzer()

    # v5.0: dominance-based rollback enabled for ALL backends. v3.7 logic
    # originally gated it to small-tier only, but the cheap-API arbitrage
    # path (Phase 2 / DeepSeek / MiniMax) also needs rollback to catch the
    # "patch one place, break another" failure mode dominance detects.
    iter_snapshots_history: List[IterSnapshot] = []
    rollback_enabled = True
    # Ensure workspace is a git repo with an initial commit so we can
    # snapshot / rollback. Trial workspaces from run_seven_arm.py
    # already are git-initialized; this is the defensive path for
    # standalone runs.
    _ensure_git_initialised(request.workspace_dir)

    # v5.0: RLE owns halt decisions (convergence / oscillation / escalation).
    # request.max_iterations is INFORMATIONAL only — the actual cap is RLE's
    # max_iterations (set above when constructing _rle).
    # The loop body is wrapped in try/except so external backend crashes
    # (LiteLLM APIConnectionError, etc.) don't drop the in-flight CZLResult.
    # Partial iter_prompts / iter_responses / iter_snapshots are preserved.

    step_idx = -1
    try:
      while True:
        step_idx += 1
        # Pass contract to plan() so scenarios can read trial_id etc. Use
        # try/except for backwards compat with scenarios whose plan()
        # signature pre-dates the contract kwarg.
        try:
            plan_steps = request.scenario.plan(
                request.task_description, request.workspace_dir,
                contract=contract_dict,
            )
        except TypeError:
            plan_steps = request.scenario.plan(request.task_description, request.workspace_dir)
        if not plan_steps:
            result.failure_reason = "scenario_returned_empty_plan"
            result.stopping_authority = "scenario_returned_empty_plan"
            result.halted_due_to = "scenario_returned_empty_plan"
            break
        step = plan_steps[min(step_idx, len(plan_steps) - 1)]
        result.iterations = step_idx + 1

        # v3.7 T2: capture the full prompt the model sees this iter.
        # v4.0 T4: prepend prior iter's probe results so the model sees
        # what it observed last time. Order: probes → focus suggestion
        # (v5.0.1) → task prompt → feedback.
        probe_section = ""
        if step_idx > 0 and (step_idx - 1) < len(result.iter_probes) and result.iter_probes[step_idx - 1]:
            from ystar.czl.probe import render_probe_results_block
            probe_section = render_probe_results_block(
                step_idx - 1, result.iter_probes[step_idx - 1]
            ) + "\n\n"
        # v5.0.1 Task B: focus_constraint rendered as SOFT SUGGESTION
        # (no "must" / "only" / "forbidden" language). The model is free
        # to ignore it.
        focus_section = (
            _render_focus_suggestion(_active_focus_constraint) if _active_focus_constraint else ""
        )
        if focus_section:
            focus_section += "\n\n"
        composed_user_prompt = (
            probe_section
            + focus_section
            + step.user_prompt
            + ("\n\n" + feedback_block if feedback_block else "")
        )
        result.iter_prompts.append(
            f"=== SYSTEM (iter {step_idx}) ===\n{request.scenario.system_prompt()}\n\n"
            f"=== USER (iter {step_idx}) ===\n{composed_user_prompt}"
        )
        # 4a. ask the backend to produce the action for this step
        backend_response = request.backend.invoke(
            system_prompt=request.scenario.system_prompt(),
            user_prompt=composed_user_prompt,
            workspace_dir=request.workspace_dir,
            contract=contract_dict,
        )
        # v5.0.3: capture raw response so diagnostics can answer
        # "what did the model literally output?" (was missing in v5.0.2)
        result.iter_responses.append(backend_response.raw_text or "")
        # v5.0.4: detect two stuck-state patterns at response level so the
        # NEXT iter's feedback can nudge the model out:
        #   (a) no recognised action blocks (model output didn't parse)
        #   (b) byte-identical response to the previous iter (stuck loop)
        # These are signal-driven hints, not hard constraints.
        _no_actions_warning = ""
        _identical_warning = ""
        if not backend_response.actions:
            _no_actions_warning = (
                "**Your last output produced no recognised action blocks.** "
                "Wrap test functions in a code block with one of these openers:\n"
                "  - ```add_tests test_data_pipeline.py   (preferred — merges by function name)\n"
                "  - ```python                            (also accepted; targets the default test file)\n"
                "Bare prose / explanation outside a code block is invisible to the verifier."
            )
        if len(result.iter_responses) >= 2 and result.iter_responses[-1] == result.iter_responses[-2]:
            _identical_warning = (
                "**Your last 2 responses are byte-identical.** That guarantees the same "
                "verifier outcome. Try a DIFFERENT angle — e.g. if 1 test is failing, "
                "RE-EMIT that specific test function (same name) with corrected expected values, "
                "rather than adding more new tests."
            )
        result.total_input_tokens += backend_response.input_tokens
        result.total_output_tokens += backend_response.output_tokens
        result.total_cost_usd += backend_response.cost_usd

        # 4b. apply the backend's proposed actions, gated by boundary_enforcer.
        # v4.0 T4: probe_command actions are handled separately — they do
        # NOT touch workspace state; ProbeExecutor runs them and the
        # result is fed back to the next iter's prompt.
        this_iter_probes: List[Dict[str, Any]] = []
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
            if not allowed:
                continue
            action_type = getattr(action, "type", None) or (
                action.get("type") if isinstance(action, dict) else None
            )
            if action_type == "probe_command":
                # v4.0 T4: execute probe, capture for next iter's prompt
                from ystar.czl.probe import ProbeExecutor
                if "_probe_executor" not in dir(result):
                    pass  # lazy init below
                payload = action.payload if hasattr(action, "payload") else action
                cmd = (payload or {}).get("command", "")
                executor = ProbeExecutor(workspace_dir=request.workspace_dir)
                pr = executor.run(cmd)
                this_iter_probes.append(pr.to_dict())
            else:
                # v5.2: pre-action gate. Compare this action to the active
                # FocusConstraint (computed by CZLAutonomyEngine from prior
                # iter's residual) before applying. Hard violations DENY and
                # surface to next-iter prompt; soft violations record an
                # advisory note. The loop is the chokepoint — scenarios do
                # not need to know about focus constraints.
                _gate_decision, _gate_reason, _gate_field = _focus_constraint_gate(
                    action, _active_focus_constraint
                )
                if _gate_decision == "deny":
                    _denied_path = (action.payload.get("path", "") if hasattr(action, "payload")
                                     else (action.get("path", "") if isinstance(action, dict) else "")) or ""
                    _gate_rejections.append({
                        "path": _denied_path,
                        "field_violated": _gate_field,
                        "reason": _gate_reason,
                        "focus_constraint": _active_focus_constraint.to_dict()
                                              if _active_focus_constraint else None,
                    })
                    # v5.2 telemetry: surface gate decisions to CZLResult so
                    # callers can analyse over-restriction empirically.
                    result.gate_denied_count += 1
                    if _gate_field:
                        result.gate_per_field_denials[_gate_field] = (
                            result.gate_per_field_denials.get(_gate_field, 0) + 1
                        )
                    if _denied_path:
                        result.gate_denied_paths.append(_denied_path)
                    _log.info(
                        "CZL v5.2: focus-constraint gate DENIED action (field=%s): %s",
                        _gate_field, _gate_reason,
                    )
                    continue  # skip apply_action — but DO NOT silently drop
                # v5.2: gate allowed (or no fc) — pass contract so the
                # scenario can apply normally. The stale "scenario can
                # enforce" comment from v5.0 is gone; enforcement is loop-
                # level now (see _focus_constraint_gate above).
                try:
                    request.scenario.apply_action(
                        action, request.workspace_dir, contract=contract_dict
                    )
                except TypeError:
                    # Legacy scenarios with 2-arg apply_action — fallback
                    request.scenario.apply_action(action, request.workspace_dir)
                # Tell the omission engine the agent did productive work.
                _emit_governance(CodingAgentEventType.TOOL_USE, {
                    "action_type": getattr(action, "type", "unknown"),
                    "iteration": step_idx,
                })
        # Append this iter's probe results (always — even if empty) so
        # iter index aligns with result.iter_probes[step_idx].
        result.iter_probes.append(this_iter_probes)

        # 4c. run scenario verifiers → build structured Y_{t+1}
        verifier_results = request.scenario.verify(request.workspace_dir, contract_dict)
        last_violations = [v for v in verifier_results if not v.passed]

        # Surface verifier outcome to the omission engine.
        if verifier_results and not last_violations:
            _emit_governance(CodingAgentEventType.VERIFIER_PASSED, {
                "iteration": step_idx,
                "verifier_count": len(verifier_results),
            })
        else:
            _emit_governance(CodingAgentEventType.VERIFIER_FAILED, {
                "iteration": step_idx,
                "violation_count": len(last_violations),
            })

        # v5.0 Task A: build the structured ResidualState (Y_{t+1}).
        # Previous residual_trajectory captures the scalar Rt+1 only —
        # we keep it for diagnostics but RLE drives the halt decision
        # against the typed object.
        from ystar.czl.reflection.transitions import extract_test_status as _extract_status
        residual_state = build_residual_state(
            iteration=step_idx,
            verifier_results=verifier_results,
            prev_passing_tests=_prev_passing_tests,
            residual_history=list(result.residual_trajectory),
        )
        scalar_residual = czl_distance_function(Y_STAR_ALL_PASS, residual_state)
        # Emit residual + reduce-residual to the omission engine before we
        # mutate result.final_residual so we can compare against the prior
        # trajectory value cleanly.
        _emit_governance(CodingAgentEventType.RESIDUAL_REPORT, {
            "iteration": step_idx,
            "scalar_residual": scalar_residual,
        })
        if result.residual_trajectory and scalar_residual < result.residual_trajectory[-1] - 1e-9:
            _emit_governance(CodingAgentEventType.REDUCE_RESIDUAL, {
                "iteration": step_idx,
                "from": result.residual_trajectory[-1],
                "to": scalar_residual,
            })
        result.final_residual = scalar_residual
        result.residual_trajectory.append(scalar_residual)
        _czl_autonomy.observe(residual_state)

        # v3.7 T1: dominance-based rollback (small tier only).
        #
        # Replaces v3.4 "lowest residual count = best" with: rollback ONLY
        # when a historical snapshot STRICTLY DOMINATES the current one
        # (its passing-test set is a proper superset). When no snapshot
        # dominates, KEEP current state — gemma's progress is preserved,
        # and the v3.6 regression META can coach recovery of any
        # newly-failed tests.
        #
        # This composes correctly with v3.6 per-test tracking: a residual=2
        # iter that FIXES a hard test is not erased by a residual=1 iter
        # that lacks the hard fix, because dominance compares actual
        # passing-test SETS, not failing counts.
        if rollback_enabled:
            current_commit = _git_commit_iter(request.workspace_dir, step_idx, scalar_residual)
            # Extract per-test status from this iter's verifiers (pytest).
            from ystar.czl.reflection.transitions import extract_test_status
            test_status = extract_test_status(verifier_results)
            passing = {n for n, p in test_status.items() if p}
            failing = {n for n, p in test_status.items() if not p}
            current_snapshot = IterSnapshot(
                iter_idx=step_idx, residual=scalar_residual,
                commit_sha=(current_commit or ""),
                passing_tests=passing, failing_tests=failing,
            )
            iter_snapshots_history.append(current_snapshot)
            # Also expose for diagnostics:
            result.iter_snapshots.append({
                "iter_idx": step_idx, "residual": scalar_residual,
                "commit_sha": (current_commit or "")[:12],
                "passing_count": len(passing), "failing_count": len(failing),
                "passing_sample": sorted(passing)[:5],
                "failing_sample": sorted(failing)[:5],
            })

            # Find historical snapshots that dominate the current state.
            dominating = [s for s in iter_snapshots_history[:-1]
                          if dominates(s, current_snapshot)]
            if dominating:
                # Pick the MOST RECENT dominator — minimises how much
                # of the model's recent work we erase.
                target = max(dominating, key=lambda s: s.iter_idx)
                _log.warning(
                    "CZL T4 (v3.7): iter %d (residual=%.2f, %d passing) is DOMINATED by "
                    "iter %d (residual=%.2f, %d passing); rolling back workspace to %s",
                    step_idx, scalar_residual, len(passing),
                    target.iter_idx, target.residual, len(target.passing_tests),
                    (target.commit_sha or "")[:8],
                )
                _git_rollback_to(request.workspace_dir, target.commit_sha)
            else:
                _log.info(
                    "CZL T4 (v3.7): iter %d (residual=%.2f, %d passing) — no dominator "
                    "in history; KEEPING current state (regression META will coach if needed)",
                    step_idx, scalar_residual, len(passing),
                )

        # v5.0: dispatch to ResidualLoopEngine — the closed-loop authority.
        # RLE writes RESIDUAL_LOOP_CONVERGED / _OSCILLATION / _ESCALATE
        # to our in-memory sink; we read sink.latest_halt_event_type to
        # decide whether to halt. This is the architectural integration
        # the no_new_wheel_runtime_law contract requires.
        _rle_event = {
            "session_id": request.run_id,
            "agent_id": "czl-iterator",
            "event_type": "CZL_ITER_RESULT",
            "decision": "info",
            "params": {
                "target_y_star": Y_STAR_ALL_PASS,
                "y_actual": residual_state,
                "iteration_idx": step_idx,
            },
            "created_at": time.time(),
        }
        _rle.on_cieu_event(_rle_event)
        _halt = _czl_sink.latest_halt_event_type()

        # v5.0.1 fix: intervention machinery must fire on STUCK halts
        # (oscillation / escalate) — that's when an agent has failed and
        # the obligation rules in coding_agent_pack become diagnostic
        # evidence of WHY it stuck. Original v5.0 fired scan() only on
        # convergence, which is exactly backwards: a converged agent did
        # well and doesn't need stuck-loop intervention; the stuck agent
        # is the one we want to surface violations on.
        def _drain_violations_at_halt(authority_label: str) -> List[Any]:
            try:
                _scan_result = _omission_engine.scan()
                _intervention_engine.process_violations(_scan_result.violations)
                if _scan_result.violations:
                    _log.warning(
                        "CZL v5.0.1: at %s, omission scan surfaced %d violation(s): %s",
                        authority_label, len(_scan_result.violations),
                        [getattr(v, "omission_type", "?") for v in _scan_result.violations[:5]],
                    )
                return list(_scan_result.violations)
            except Exception as _exc:
                _log.debug("scan/process_violations at %s failed: %s",
                            authority_label, _exc)
                return []

        if _halt == "RESIDUAL_LOOP_CONVERGED":
            # Defensive: drain any pending violations before validating the
            # declare_done. A truly successful run will have none and the
            # gate passes; if any are pending, the gate DENY catches them.
            _drain_violations_at_halt("converged_pre_gate")
            _gate = _intervention_engine.gate_check(
                actor_id=_coding_actor_id,
                action_type=CodingAgentEventType.DECLARE_DONE,
                entity_id=_coding_entity_id,
            )
            if _gate.decision == GateDecision.DENY:
                result.stopping_authority = "completion_gate_denied"
                result.halted_due_to = "completion_gate_denied"
                result.failure_reason = (
                    f"declare_done gated by open obligation "
                    f"{_gate.blocking_omission_type} (obligation_id="
                    f"{_gate.blocking_obligation_id})"
                )
                _log.warning(
                    "CZL v5.0: RLE reported convergence but completion gate "
                    "DENIED declare_done (blocking_omission=%s); refusing to mark converged.",
                    _gate.blocking_omission_type,
                )
                break
            # Emit DECLARE_DONE so audit shows the gate-passed completion.
            _emit_governance(CodingAgentEventType.DECLARE_DONE, {
                "iteration": step_idx,
                "scalar_residual": scalar_residual,
            })
            result.converged = True
            result.stopping_authority = "converged"
            result.halted_due_to = "converged"
            result.final_verifier_report = _summarize_verifiers(verifier_results)
            break
        if _halt == "RESIDUAL_LOOP_OSCILLATION":
            _stuck_violations = _drain_violations_at_halt("rle_oscillation")
            result.stopping_authority = "rle_oscillation"
            result.halted_due_to = "rle_oscillation"
            if _stuck_violations:
                # Surface violation diagnostics so callers can see WHY the
                # agent got stuck, not just that it did.
                _vtypes = sorted({getattr(v, "omission_type", "?")
                                   for v in _stuck_violations})
                result.failure_reason = (
                    f"rle_oscillation at iter {step_idx} with "
                    f"{len(_stuck_violations)} obligation violation(s): "
                    f"{','.join(_vtypes)}"
                )
            _log.info(
                "CZL v5.0: RLE detected oscillation at iter %d (%d violation(s) surfaced)",
                step_idx, len(_stuck_violations),
            )
            break
        if _halt == "RESIDUAL_LOOP_ESCALATE":
            _stuck_violations = _drain_violations_at_halt("rle_escalate")
            result.stopping_authority = "rle_escalate"
            result.halted_due_to = "rle_escalate"
            if _stuck_violations:
                _vtypes = sorted({getattr(v, "omission_type", "?")
                                   for v in _stuck_violations})
                result.failure_reason = (
                    f"rle_escalate at iter {step_idx} with "
                    f"{len(_stuck_violations)} obligation violation(s): "
                    f"{','.join(_vtypes)}"
                )
            _log.warning(
                "CZL v5.0: RLE escalated after max_iterations at iter %d "
                "(%d violation(s) surfaced)",
                step_idx, len(_stuck_violations),
            )
            break

        # Pull next-action's focus_constraint from autonomy engine; the
        # loop respects it on the NEXT iter (plan/apply_action).
        _next_action = _czl_autonomy.pull_next_action("czl-agent")
        if _next_action is not None and _next_action.focus_constraint is not None:
            _active_focus_constraint = _next_action.focus_constraint
            # v5.2/v5.3: merge scenario override. Accepts two shapes:
            #   v5.2 flat: {field: level}
            #   v5.3 nested: {"enforcement": {field: level}, "forbidden_operations": {...}}
            try:
                _scen_override = request.scenario.focus_constraint_enforcement_override()
            except AttributeError:
                _scen_override = None
            if _scen_override:
                _enf_part = _scen_override.get("enforcement") if (
                    isinstance(_scen_override, dict) and "enforcement" in _scen_override
                ) else _scen_override   # v5.2 flat fallback
                if _enf_part:
                    _active_focus_constraint.enforcement = {
                        **_active_focus_constraint.enforcement, **_enf_part,
                    }
                # v5.3 scenario-domain fields:
                if isinstance(_scen_override, dict) and _scen_override.get("forbidden_operations"):
                    _active_focus_constraint.forbidden_operations = set(
                        tuple(t) if isinstance(t, list) else t
                        for t in _scen_override["forbidden_operations"]
                    )
            contract_dict["_focus_constraint"] = _active_focus_constraint.to_dict()

        # v5.0.2: drain any rejections recorded by scenario.apply_action this iter
        # and surface them in the next-iter feedback. Per founder principle "no
        # silent reject" — any write the scenario refused must be visible to the model.
        try:
            _iter_rejections = request.scenario.consume_rejections()
        except AttributeError:
            _iter_rejections = []
        if _iter_rejections:
            _rej_lines = ["\n\n## Writes from your last iter that were REJECTED",
                          "(your edit blocks targeted paths the scenario doesn't allow; "
                          "the verifier saw the PREVIOUS workspace state)\n"]
            for rj in _iter_rejections:
                _rej_lines.append(f"- `{rj['path']}`: {rj['reason']}")
            feedback_block = ("\n".join(_rej_lines) + "\n\n" + feedback_block) if feedback_block else "\n".join(_rej_lines)

        # v5.2: drain pre-action gate rejections + soft-violation advisory
        # notes from THIS iter; render into next-iter feedback so the agent
        # sees exactly which edits were blocked by focus-constraint
        # enforcement and why. Two separate sections so the agent can tell
        # gate-block from scenario-block.
        if _gate_rejections:
            _gate_lines = [
                "\n\n## ⛔ Pre-action gate blocked these edits (focus-constraint enforcement)",
                "(your edit was outside the residual-driven focus zone for this iter; "
                "satisfy the focus constraint or change angle.)\n",
            ]
            for gr in _gate_rejections:
                _gate_lines.append(
                    f"- `{gr['path']}`: {gr['reason']}"
                    + (f"\n  rationale: {gr['focus_constraint']['rationale']}"
                       if gr.get("focus_constraint") and gr["focus_constraint"].get("rationale") else "")
                )
            _gate_block_txt = "\n".join(_gate_lines)
            feedback_block = (_gate_block_txt + "\n\n" + feedback_block) if feedback_block else _gate_block_txt
            _gate_rejections.clear()
        if _gate_soft_notes:
            _note_lines = [
                "\n\n## ⚠ Pre-action gate soft notes (your edit landed off-focus but was allowed)",
            ]
            for sn in _gate_soft_notes:
                _note_lines.append(f"- `{sn['path']}`: {sn['reason']}")
            _soft_txt = "\n".join(_note_lines)
            feedback_block = (_soft_txt + "\n\n" + feedback_block) if feedback_block else _soft_txt
            _gate_soft_notes.clear()

        # v5.0.4: surface response-level signals before per-verifier feedback.
        _response_signals: List[str] = []
        if _no_actions_warning:
            _response_signals.append(_no_actions_warning)
        if _identical_warning:
            _response_signals.append(_identical_warning)
        # v5.0.5: when NameError dominates pytest failures, gemma is hallucinating
        # function names. Surface the ACTUAL workspace function names from the
        # inventory in a prominent feedback section so gemma stops inventing.
        # Signal-triggered: only fires when NameError is the dominant error type.
        _nameerror_hint = ""
        for v in last_violations:
            if v.verifier_name != "pytest":
                continue
            failures_meta = (v.details or {}).get("failures") or []
            if not failures_meta:
                continue
            n_nameerror = sum(1 for f in failures_meta if (f.get("error_type") or "").lower() == "nameerror")
            if n_nameerror >= max(3, len(failures_meta) // 2):
                # Inventory comes from scenario's last scan — re-scan here cheaply.
                try:
                    from ystar.czl.inventory import WorkspaceInventory
                    inv = WorkspaceInventory.scan(request.workspace_dir)
                    src = inv.get("source_interfaces") or {}
                    available_fns = []
                    for fname, info in src.items():
                        if isinstance(info, dict) and not info.get("error"):
                            for fn in (info.get("functions") or []):
                                available_fns.append(f"{fn.get('name')}{fn.get('signature','(?)')}")
                            for cls in (info.get("classes") or []):
                                available_fns.append(f"class {cls.get('name')}")
                    if available_fns:
                        _nameerror_hint = (
                            f"**{n_nameerror} of {len(failures_meta)} pytest failures are NameError.** "
                            "You are referencing names that DO NOT EXIST in the workspace. "
                            "The ONLY callables available from data_pipeline.py are:\n\n"
                            + "\n".join(f"  • {fn}" for fn in available_fns)
                            + "\n\nIf you used `process_data` / `clean_data` / `normalize_record` / `data_processing` — these do NOT exist. "
                            "Re-emit failing tests with the correct names from the list above (or delete them by re-emitting "
                            "the SAME function name with an empty body that doesn't reference invented names)."
                        )
                except Exception:
                    pass
                break  # one NameError hint per iter is enough
        if _nameerror_hint:
            _response_signals.append(_nameerror_hint)
        # update passing tracker for next iter's delta_from_prev + protection
        _curr_status = _extract_status(verifier_results)
        _prev_passing_tests = {n for n, p in _curr_status.items() if p}
        _curr_failing_tests = {n for n, p in _curr_status.items() if not p}
        # v5.1 Task B: extract BARE function names (strip "file.py::") and
        # plumb to contract so scenario.apply_action's merge can enforce
        # passing-test protection.
        _passing_bare_names = set()
        for full_id in _prev_passing_tests:
            bare = full_id.split("::", 1)[1] if "::" in full_id else full_id
            # Handle parametrised IDs like `test_X[case1]` → bare = `test_X`
            bare = bare.split("[", 1)[0]
            _passing_bare_names.add(bare)
        contract_dict["_passing_tests_last_iter"] = _passing_bare_names

        # 4d. not converged — generate feedback via auto_rewrite-style logic.
        reflection.record(step_idx, verifier_results)
        meta = reflection.analyze(iter_idx=step_idx)
        meta_text = meta.render() if not meta.is_empty() else ""
        # Pull scenario-declared output protocol — replaces v3.4 hardcoded
        # "add_tests test_data_pipeline.py" instruction with a scenario-
        # specific format hint. None = scenario opts out, no instruction.
        try:
            _scenario_protocol = request.scenario.output_protocol()
        except Exception:
            _scenario_protocol = None
        feedback_block = _format_feedback_for_retry(
            last_violations, meta_text=meta_text,
            output_protocol=_scenario_protocol,
        )

        # v5.1 Task A: PASSING TESTS + FAILING TESTS double-list at top of
        # feedback. The protection zone (passing names) tells the model
        # what NOT to touch; failing names tell it what to fix. Realises
        # R_{t+1} as a structured vector (passing dimensions vs failing
        # dimensions), not a scalar.
        _protection_section = ""
        if _passing_bare_names or _curr_failing_tests:
            lines = []
            if _passing_bare_names:
                lines.append("## ✅ Passing tests (PROTECTION ZONE — DO NOT MODIFY)")
                lines.append(
                    f"These {len(_passing_bare_names)} tests are PASSING. If you re-emit "
                    "any of them with DIFFERENT content, your new version will be REJECTED "
                    "and the passing version preserved. To make progress, edit ONLY the "
                    "failing tests below."
                )
                lines.append("")
                for n in sorted(_passing_bare_names)[:50]:
                    lines.append(f"  - {n}")
                if len(_passing_bare_names) > 50:
                    lines.append(f"  (+{len(_passing_bare_names) - 50} more)")
                lines.append("")
            if _curr_failing_tests:
                lines.append("## ⚠️ Failing tests (FIX ZONE — R_{t+1} > 0 here)")
                lines.append(
                    "Re-emit ONLY these test functions with corrected bodies. The protection "
                    "above means you don't need to touch any passing test."
                )
                lines.append("")
                failing_bare = set()
                for full in _curr_failing_tests:
                    bare = full.split("::", 1)[1] if "::" in full else full
                    bare = bare.split("[", 1)[0]
                    failing_bare.add(bare)
                for n in sorted(failing_bare)[:50]:
                    lines.append(f"  - {n}")
                if len(failing_bare) > 50:
                    lines.append(f"  (+{len(failing_bare) - 50} more)")
                lines.append("")
            _protection_section = "\n".join(lines)

        # v5.0.6 signal block (response-level nudges)
        if _response_signals:
            _signal_block = "## Output-level signal from last iter\n\n" + "\n\n".join(_response_signals)
            feedback_block = _signal_block + ("\n\n" + feedback_block if feedback_block else "")

        # v5.1 Task C: rejection log PROMINENT at the very top of feedback.
        # Drained earlier into _iter_rejections — render with explicit emoji
        # + reasons so the model can't miss them.
        if _iter_rejections:
            _rej_lines = ["## 🚫 Last iter rejections (these edits were DROPPED)",
                          "Trampoline refused these changes because they would have broken "
                          "passing tests or referenced undefined names. Read carefully — do "
                          "NOT retry the same edit.",
                          ""]
            for rj in _iter_rejections:
                _rej_lines.append(f"  - `{rj['path']}`: {rj['reason']}")
            _rej_block = "\n".join(_rej_lines)
            feedback_block = _rej_block + ("\n\n" + feedback_block if feedback_block else "")

        # Protection / fix-zone goes at the VERY TOP — most prominent.
        # Passing protection drives the model's edits.
        if _protection_section:
            feedback_block = _protection_section + ("\n\n" + feedback_block if feedback_block else "")

        # All halt decisions (convergence, oscillation, escalation) are owned
        # by ResidualLoopEngine above. This block intentionally empty.
        pass

    except Exception as _loop_exc:
        # v5.0.3: external infrastructure failure (e.g. Ollama GGML crash).
        # Preserve the partial CZLResult — iter_prompts, iter_responses,
        # iter_snapshots already populated up to this point. Fall through
        # to finalize.
        _log.warning(
            "CZL v5.0.3: loop exception at iter %d: %s: %s — preserving partial result",
            step_idx, type(_loop_exc).__name__, str(_loop_exc)[:200],
        )
        if not result.failure_reason:
            result.failure_reason = f"backend_exception: {type(_loop_exc).__name__}: {str(_loop_exc)[:300]}"
        result.stopping_authority = "backend_exception"
        result.halted_due_to = "backend_exception"

    # --- Step 5: finalize ---------------------------------------------------
    if not result.converged:
        if not result.stopping_authority:
            # Should be unreachable — the loop exits via RLE halt events
            # (converged / oscillation / escalate), scenario_empty, or
            # backend_exception. Defensive fallback.
            result.stopping_authority = "unknown_exit"
            result.halted_due_to = "unknown_exit"
        result.failure_reason = (
            f"did_not_converge_after_{result.iterations}_iterations "
            f"({result.stopping_authority}): "
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


def _render_focus_suggestion(focus_constraint: Any) -> str:
    """v5.0.1 Task B: render focus_constraint as a SOFT SUGGESTION block.

    Language deliberately uses 'suggestion', 'pointer', 'free to choose
    otherwise' — never 'must', 'only', 'forbidden'. The block conveys
    RLE's analysis of where the residual signal points; the model is
    free to ignore it.
    """
    if focus_constraint is None:
        return ""
    tc = getattr(focus_constraint, "target_cluster", None)
    af = getattr(focus_constraint, "allowed_files", None)
    rationale = getattr(focus_constraint, "rationale", "") or ""
    if not (tc or af or rationale):
        return ""
    lines = ["## Focus suggestion (from RLE residual analysis)"]
    lines.append("")
    lines.append(
        "Based on the structured R_{t+1} from the previous iter, the residual "
        "signal points at the following region. This is a SUGGESTION — you're "
        "free to choose a different angle if you see a better one."
    )
    if tc:
        lines.append("")
        lines.append(f"- **Pointer to cluster**: `{tc.get('file', '?')}:{tc.get('lineno', '?')}`"
                     + (f" ({tc.get('count', '?')} failures share this location)" if tc.get('count') else ""))
    if af:
        files_list = sorted(af) if isinstance(af, (list, set, tuple)) else [str(af)]
        lines.append(f"- **Files most relevant to the current residual**: {', '.join(files_list)}")
    if rationale:
        lines.append(f"- **Why this pointer**: {rationale}")
    lines.append("")
    lines.append(
        "Note: the loop will not reject your output if you edit elsewhere — "
        "the suggestion is informational. The verifier will judge whatever "
        "you produce."
    )
    return "\n".join(lines)


def _format_feedback_for_retry(violations: List[VerifierResult],
                                meta_text: str = "",
                                output_protocol: Optional[Dict[str, Any]] = None) -> str:
    """Compose the retry-feedback text block fed back to the LLM next iteration.

    Composition order:
      1. META block (cluster + regression cross-iter signals from
         ReflectionAnalyzer)
      2. Per-verifier: structured message + raw stdout tail.
      3. Retry instructions read from scenario.output_protocol() — NEVER
         hardcoded. If output_protocol is None, a generic fallback hint
         is emitted.

    v5.0: small-tier hint-synthesis path retired with the local-model route.
    """
    if not violations:
        return ""
    lines: List[str] = []
    if meta_text:
        lines.append(meta_text)
        lines.append("")
    lines.append("### Previous attempt did NOT converge. Address each issue:")
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
    # Scenario-declared output protocol drives the format instruction. No
    # hardcoded filenames or block tags here — read from scenario.
    if output_protocol and output_protocol.get("instruction"):
        lines.append(output_protocol["instruction"])
    else:
        lines.append(
            "Re-emit the full corrected content of any file that still has issues. "
            "Do not restart from scratch. If a verifier failure shows the test "
            "expects a specific type/value, your fix must produce that — the "
            "verifier is the spec."
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


# === v3.4 T4: git snapshot / rollback helpers ===============================

def _ensure_git_initialised(workspace_dir: str) -> None:
    """Defensive: if not a git repo, initialise + initial commit so the
    rollback path has a base. Bench workspaces are already initialised."""
    import subprocess
    git_dir = os.path.join(workspace_dir, ".git")
    if os.path.isdir(git_dir):
        return
    try:
        subprocess.run(["git", "init", "-q"], cwd=workspace_dir, timeout=10, check=False)
        # Configure dummy user for the per-iter commits (no global config required)
        subprocess.run(["git", "config", "user.email", "trampoline@local"], cwd=workspace_dir, timeout=5, check=False)
        subprocess.run(["git", "config", "user.name", "trampoline"], cwd=workspace_dir, timeout=5, check=False)
        subprocess.run(["git", "add", "-A"], cwd=workspace_dir, timeout=10, check=False)
        subprocess.run(["git", "commit", "-q", "-m", "trampoline initial baseline"],
                       cwd=workspace_dir, timeout=10, check=False)
    except Exception as e:
        _log.warning("CZL T4: could not init git workspace at %s: %s", workspace_dir, e)


import os  # for _ensure_git_initialised path check


def _git_commit_iter(workspace_dir: str, step_idx: int, residual: float) -> Optional[str]:
    """Commit workspace state after iter `step_idx`, return new commit sha or None."""
    import subprocess
    try:
        subprocess.run(["git", "add", "-A"], cwd=workspace_dir, timeout=10, check=False)
        # `--allow-empty` so iters that didn't actually change files still create a commit
        # (so we have a snapshot to roll back TO).
        msg = f"trampoline iter {step_idx} residual {int(residual)}"
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", msg],
                       cwd=workspace_dir, timeout=10, check=False)
        proc = subprocess.run(["git", "rev-parse", "HEAD"],
                              cwd=workspace_dir, capture_output=True, text=True, timeout=5)
        sha = (proc.stdout or "").strip() or None
        return sha
    except Exception as e:
        _log.warning("CZL T4: commit failed at iter %d: %s", step_idx, e)
        return None


def _git_rollback_to(workspace_dir: str, commit_sha: str) -> None:
    """Restore working tree to `commit_sha` — destructive checkout."""
    import subprocess
    try:
        # `checkout <sha> -- .` restores working tree to that commit's state.
        subprocess.run(["git", "checkout", "-q", commit_sha, "--", "."],
                       cwd=workspace_dir, timeout=15, check=False)
    except Exception as e:
        _log.warning("CZL T4: rollback to %s failed: %s", commit_sha[:8], e)


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
