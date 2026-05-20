# Trampoline v5.2 — Pre-Action Authorization (design proposal)

**Status**: proposal. No code, no commit. Founder reviews before any implementation.

**Author**: Claude Code (drafted under v5.0.1 substrate, commit `371d4e8`).

**Date**: 2026-05-19.

---

## 1. The diagnosis: v5.0.1 is post-hoc, not pre-action

What we built in v5.0 + v5.0.1:

  - `OmissionEngine` ingests `GovernanceEvent`s as the loop emits them, creates
    obligations, lets them age into violations.
  - `InterventionEngine.process_violations` materialises violations into
    intervention pulses.
  - `InterventionEngine.gate_check(actor, action_type)` evaluates whether an
    action should be allowed given the actor's open obligations.

What v5.0.1 actually wires up in `ystar/czl/loop.py`:

  - `gate_check` is called **once**, on `DECLARE_DONE`, at convergence-attempt time.
  - `scan + process_violations` is called at every RLE halt event (converged /
    oscillation / escalate).

What this means in practice:

  - The loop runs to completion. RLE caps it. Only THEN do we look at whether
    any obligations are open. If they are, the convergence claim is blocked.
  - **No mid-iteration block of any tool_use.** An agent that's about to issue
    a destructive `edit_file` is never asked "should this be allowed?" until
    after the work is done.

This is **post-hoc monitoring**, not a runtime guardrail. Comparable to a
firewall that audits packets after delivery.

The 2025-2026 frontier of agent-safety research moved past this. Two examples
the founder pointed at are real and directly relevant:

  - **AEGIS** (Yuan, Su, Zhao — arxiv 2603.12621, March 2026). *No Tool Call
    Left Unchecked — A Pre-Execution Firewall and Audit Layer for AI Agents.*
    Sits on the tool-execution path. Three-stage synchronous pipeline (deep
    string extraction → content risk scan → policy validation). Blocks 100%
    of 48 attack instances in their test suite, 1.2% false positives on 500
    benign calls, **8.3 ms median latency** across 1,000 interceptions.
    Supports 14 agent frameworks across Python/JS/Go.

  - **OAP / Open Agent Passport** (Uchibeke — arxiv 2603.20953, March 2026).
    *Before the Tool Call: Deterministic Pre-Action Authorization for
    Autonomous AI Agents.* Synchronous interception, declarative policy,
    cryptographically signed audit. **53 ms median enforcement latency.**
    Adversarial testing across 1,151 sessions: social engineering attacks
    succeeded **74.6%** under a permissive policy and **0%** across 879
    attempts under the restrictive OAP policy.

The named Python frameworks each ship the same pattern as production API:

  - **AWS Strands** (`strands-agents/sdk-python`). `BeforeToolCallEvent` is a
    `@dataclass` with `selected_tool`, `tool_use`, `invocation_state`, and a
    mutable `cancel_tool: bool | str = False`. A hook sets `cancel_tool =
    "Read-only access."` and the tool is replaced with an error result before
    execution. Synchronous, in-process, no external call. There is also an
    `AfterToolCallEvent` with `retry: bool = False` for re-invocation.

  - **LangGraph**. `interrupt()` inside a node pauses the graph at that point,
    snapshots state via the checkpointer, and resumes after external input.
    Synchronous BSP semantics — "a single slow node blocks the entire
    superstep" — but the durability layer means a long pause doesn't lose
    work. Best fit for human-in-the-loop, can also be machine-gated.

  - **AutoGen**. `register_reply()` lets you register reply handlers that
    intercept the message chain before LLM is called. Not exactly pre-tool,
    but it's the same pattern: a synchronous chain of inspectors that can
    short-circuit.

The shared structure across all five: **the hook is synchronous, in-process,
gets the proposed action as data, can return ALLOW / BLOCK / REDIRECT, and
the framework respects the verdict before any side-effect runs**.

We do not do this. We should.

---

## 2. The proposed v5.2 architecture

```
                ┌─────────────────────────────────────────────┐
                │            backend.invoke()                 │
                │  (LLM produces BackendResponse with actions)│
                └─────────────────────┬───────────────────────┘
                                      │
                                      ▼
                  ┌──────────────────────────────────────┐
                  │     for action in response.actions:  │
                  └─────────────────────┬────────────────┘
                                        │
                                        ▼
                  ╔════════════════════════════════════════╗
                  ║   pre_action_gate(action)              ║
                  ║   (NEW in v5.2 — synchronous)          ║
                  ║                                        ║
                  ║   1. omission_engine.scan()            ║
                  ║      (materialise newly-overdue        ║
                  ║       obligations into violations)     ║
                  ║   2. intervention_engine.process_      ║
                  ║      violations(violations)            ║
                  ║      (build pulses for hard_overdue)   ║
                  ║   3. intervention_engine.gate_check(   ║
                  ║      actor, action_type, entity)       ║
                  ║      → GateDecision.{ALLOW,DENY,       ║
                  ║                       REDIRECT}        ║
                  ╚════════════════════════════════════════╝
                                        │
                  ┌─────────────────────┼─────────────────────┐
                  │                     │                     │
                  ▼                     ▼                     ▼
            ALLOW → execute     DENY → skip          REDIRECT → skip
            apply_action        + record block       + record suggested
                                  reason into          alternative into
                                  feedback             feedback
                                        │                     │
                                        └─────────┬───────────┘
                                                  ▼
                  ┌──────────────────────────────────────────┐
                  │ build next-iter feedback so the LLM sees │
                  │ exactly which actions were blocked, why, │
                  │ and what to do instead.                  │
                  └─────────────────────┬────────────────────┘
                                        ▼
                  ┌──────────────────────────────────────────┐
                  │     scenario.verify() (unchanged)        │
                  └─────────────────────┬────────────────────┘
                                        ▼
                  ┌──────────────────────────────────────────┐
                  │     RLE.on_cieu_event (unchanged)        │
                  │     scan + intervention at halts         │
                  │     (kept as v5.0.1 defensive layer)     │
                  └──────────────────────────────────────────┘
```

The new layer is **between LLM response parsing and `scenario.apply_action`**.
Everything else stays.

---

## 3. Where the hook lives in our code

`ystar/czl/loop.py`. Current iter body (simplified):

```python
backend_response = request.backend.invoke(...)
for action in backend_response.actions:
    if isinstance(action, BackendAction) and action.type == "probe_command":
        # run probe…
    else:
        request.scenario.apply_action(action, request.workspace_dir, contract=contract_dict)
        _emit_governance(CodingAgentEventType.TOOL_USE, {...})
```

Proposed v5.2 (sketch):

```python
backend_response = request.backend.invoke(...)
for action in backend_response.actions:
    action_type_str = _action_type_to_governance_string(action)
    gate = pre_action_gate(action_type_str)   # NEW
    if gate.decision == GateDecision.DENY:
        _record_action_blocked(action, gate)
        continue                              # SKIP execution
    if gate.decision == GateDecision.REDIRECT:
        _record_action_redirected(action, gate)
        continue                              # SKIP and surface alternative
    # GateDecision.ALLOW — execute as before:
    if isinstance(action, BackendAction) and action.type == "probe_command":
        # run probe…
    else:
        request.scenario.apply_action(action, request.workspace_dir, contract=contract_dict)
        _emit_governance(CodingAgentEventType.TOOL_USE, {...})
```

Where `pre_action_gate` is:

```python
def pre_action_gate(action_type_str: str) -> GateCheckResult:
    # 1) materialise any newly-overdue obligations
    scan_result = _omission_engine.scan()
    if scan_result.violations:
        _intervention_engine.process_violations(scan_result.violations)
    # 2) ask the gate
    return _intervention_engine.gate_check(
        actor_id=_coding_actor_id,
        action_type=action_type_str,
        entity_id=_coding_entity_id,
    )
```

This is **identical in shape** to `BeforeToolCallEvent` in AWS Strands: a
synchronous hook that sees the action, returns a decision, and the framework
respects it before any side effect.

---

## 4. What signals the synchronous evaluation reads

The gate looks at three layers, in order:

  1. **Active obligations** — `omission_engine.scan()` returns the current
     violations. Built from the three coding-agent rules already in
     `ystar/czl/coding_agent_pack.py`:
       - `trampoline.stuck_after_dispatch` (silent agent)
       - `trampoline.fake_declare_done`
       - `trampoline.residual_stuck`

  2. **Active intervention pulses** — `intervention_engine.pulse_store`
     tracks who has HARD_OVERDUE obligations. The gate consults this
     internally.

  3. **Gating policy** — `TRAMPOLINE_GATING_POLICY` declares which action
     types are `fulfillment` (always allowed) and which are `high_risk`
     (blocked when pulse is active). Defined in `coding_agent_pack.py`.

Importantly: **R_{t+1} itself is NOT a direct gate signal.** The gate consults
obligations and pulses; obligations are CREATED by events (including
`RESIDUAL_REPORT` → `_residual_stuck_rule`); the residual trajectory feeds
into obligation creation indirectly. Keeping R out of the gate's direct read
path keeps the gate cheap and gives RLE a single authority over residual
semantics. This matches the OAP separation of concerns: declarative policy
on top of state, not embedded into one engine.

---

## 5. How blocked actions feed back into agent context

This is the part the cited papers handle less explicitly than the Python
frameworks do.

**AWS Strands** model: when `cancel_tool` is set, the tool result becomes an
error message saying "this tool was cancelled because X". That error is
visible to the agent on the next turn. Result: the agent literally sees
*"your edit_file call was rejected with reason: REQUIRED_STATUS_UPDATE
obligation overdue"* and can plan accordingly.

We already have the plumbing for this in v5.1's caller-side feedback
sections in `loop.py`:

```python
# v5.1 Task C: rejection log PROMINENT at the very top of feedback.
if _iter_rejections:
    _rej_lines = ["## 🚫 Last iter rejections (these edits were DROPPED)",
                  "Trampoline refused these changes because they would have broken "
                  "passing tests or referenced undefined names. Read carefully — do "
                  "NOT retry the same edit.",
                  ""]
    for rj in _iter_rejections:
        _rej_lines.append(f"  - `{rj['path']}`: {rj['reason']}")
```

v5.2 extends this: a parallel `_iter_blocked_actions` list, populated by
`_record_action_blocked`, with entries like:

```python
{
  "action_type": "edit_file",
  "action_summary": "edit_file path=src/foo.py len=842",
  "decision": "DENY",
  "blocking_obligation_id": "trampoline.post_declare_done.abc123",
  "blocking_omission_type": "post_ship_completeness",
  "suggested_action": "fulfil the open obligation first",
}
```

Rendered as a feedback section labelled `"## ⛔ Pre-action gate blocked these
edits"` and prepended to the user prompt the same way the v5.1 rejection log
is. The LLM reads it and adjusts on the next iter.

Crucially: **a blocked action is not a silent drop.** The agent sees exactly
why and what to do instead. This is the "no silent reject" principle we
already enforce for AST validator rejections.

---

## 6. Policy decisions — what to actually gate

The gating policy lives in `coding_agent_pack.TRAMPOLINE_GATING_POLICY`.
Right now its `high_risk` set is `{DECLARE_DONE}`. For pre-action
authorization to actually do anything, the set has to grow. There are three
viable settings; the right choice is a product call:

**Setting A — DECLARE_DONE only (status quo).** No new gating. The "pre-action
gate" still runs per-action but always returns ALLOW for everything except
DECLARE_DONE. Effectively v5.2 collapses back to v5.0.1 behaviour. Worst case:
zero improvement on stuck loops.

**Setting B — Add `edit_file` / `add_tests_file` / `create_file` to
high_risk.** When an actor has a HARD_OVERDUE obligation, code-write actions
are blocked. The agent has to satisfy the obligation (e.g. produce a
`REDUCE_RESIDUAL` event) before it can write again. Mid-loop cost ceiling
becomes real because a stuck agent gets blocked from doing more useless
writes. Risk: false positives if `due_within_secs` is too aggressive — a
legitimately-slow agent could get blocked.

**Setting C — Block conditionally on rule severity.** Use the existing
`Severity.HIGH` / `Severity.MEDIUM` markers in the rule definitions:
HIGH-severity obligation overdue → block code-write actions; MEDIUM-severity
→ only block DECLARE_DONE. This gives finer-grained control and matches the
"INTERRUPT_GATE" pulse level the InterventionEngine already supports.

**Recommendation: Setting C.** It re-uses existing severity machinery,
doesn't introduce new vocabulary, and gives us a tunable knob between "no
op" and "block everything when stuck". We'd ship with conservative thresholds
and adjust after telemetry.

---

## 7. Integration with v5.0.1 engines

The proposal is **strictly additive** to v5.0.1:

  - `omission_engine` — no change to API. Just called per-iter instead of
    only at halt. Same registry, same store, same rules.
  - `intervention_engine` — no change to API. Just called per-action
    instead of only at convergence. Same gating policy mechanism.
  - `coding_agent_pack` — extend `TRAMPOLINE_GATING_POLICY.high_risk` per
    Setting C. Possibly add a per-rule severity override.
  - `loop.py` — add `pre_action_gate()` closure + action-skip path + new
    feedback section. Keep all existing halt-time scan/process logic
    (defensive: catches any obligation that escaped per-iter scan).
  - `ResidualLoopEngine` — no change. RLE keeps owning the residual halt
    decision. The gate is a parallel concern.

**Nothing in v5.0.1 stops working.** All 9 e2e tests should still pass. New
tests get added for the gate's three decisions (ALLOW / DENY / REDIRECT) and
the block-feedback rendering.

---

## 8. Risks + non-goals

**Risk 1: false positives blocking legitimate work.** A poorly-tuned
`due_within_secs` could block a slow-but-honest agent. Mitigation: ship
conservative defaults, surface block events in trial JSON for post-hoc
review, allow per-scenario policy overrides.

**Risk 2: block-loop deadlock.** If the LLM keeps re-emitting the same
blocked action because it doesn't understand the feedback, we burn cost
without progress. Mitigation: the v5.0.1 RLE oscillation detection catches
this; the loop halts.

**Risk 3: latency.** AEGIS reports 8.3 ms, OAP 53 ms — those include
external policy services. Our gate is in-process: scan() iterates pending
obligations (~tens of items in our scale), gate_check() reads pulse_store
(also tens of items). Expected sub-millisecond per call. Will measure.

**Risk 4: cross-scenario policy contamination.** TRAMPOLINE_GATING_POLICY is
module-level. If we add `edit_file` to high_risk it affects every Trampoline
run. Mitigation: per-CZLRun policy override, defaulting to the module-level
constant.

**Risk 5: the cost story is unchanged.** v5.2 catches stuck loops earlier
than RLE's 50-iter cap and saves the marginal cost, BUT if the rules
themselves don't fire correctly (e.g. `due_within_secs=180` for
`_residual_stuck_rule` only triggers after ~3 iters), the cost ceiling moves
from 50× to 3×, not to 1×. To get truly tight cost control we'd also need
to tighten the rule timings — that's a separate tuning pass.

**Non-goal 1: replacing RLE.** RLE keeps its role as the closed-loop control
authority over residual. We're not putting residual into the gate.

**Non-goal 2: full AEGIS-style content scanning.** AEGIS does "deep string
extraction" on tool arguments and runs regex-based risk patterns. That's
useful for security agents; for code-completion agents it's overkill.
v5.2 stays at the obligation/policy layer.

**Non-goal 3: cryptographic audit chain.** OAP's Ed25519 signature line is
real and useful; not in scope for v5.2. Our CIEU jsonl already has SHA-256
prev_hash chaining as audit. Crypto signatures can come later.

---

## 9. Test plan

New tests under `tests/czl/scenarios/test_v5_2_pre_action_gate.py`:

  1. `test_gate_allows_when_no_obligations_overdue` — clean run, all actions
     execute.
  2. `test_gate_denies_when_obligation_hard_overdue` — set up a synthetic
     obligation past `effective_due_at`, run iter, assert action skipped
     and block reason captured in `_iter_blocked_actions`.
  3. `test_blocked_action_appears_in_next_iter_feedback` — run two iters,
     assert iter-2 user prompt contains the "## ⛔ Pre-action gate blocked"
     section with the iter-1 block reason.
  4. `test_gate_redirect_records_suggested_action` — same as deny but with
     REDIRECT decision; suggested_action surfaces in feedback.
  5. `test_per_action_gate_does_not_call_external_service` — assert latency
     under 5 ms per gate_check call.
  6. `test_v5_0_1_e2e_still_passes` — re-run the existing 7-test e2e suite
     unchanged.
  7. `test_v5_1_stuck_loop_still_passes` — synthetic stuck-loop test from
     v5.0.1 unchanged.

Acceptance: 7/7 v5.2 new + 9/9 v5.0.1 existing all green.

---

## 10. Code-impact estimate

| File | Change | LoC |
|------|--------|-----|
| `ystar/czl/loop.py` | add `pre_action_gate()` closure + per-action call site + `_iter_blocked_actions` plumbing + new feedback section | ~50 |
| `ystar/czl/coding_agent_pack.py` | extend `TRAMPOLINE_GATING_POLICY` (Setting C); add per-rule severity helper | ~20 |
| `tests/czl/scenarios/test_v5_2_pre_action_gate.py` | new 7 tests | ~250 |
| `ystar/czl/__init__.py` or wherever the per-CZLRun policy override hook lives | small surface for callers to pass a custom GatingPolicy | ~10 |

Total: ~330 LoC additive. No deletions in v5.0.1 substrate.

---

## 11. Open questions for the founder

1. **Policy setting** — A / B / C from §6. I recommend C. Confirm before
   I write code.

2. **Per-CZLRun policy override** — should `CZLRun` grow an optional
   `gating_policy: GatingPolicy | None` field so individual runs can opt out
   of pre-action gating for experiments? Or is the module-level constant
   always-on enforcement? Affects both architecture and tests.

3. **Cost-ceiling target** — what's the right `due_within_secs` for
   `_residual_stuck_rule` if the goal is "cap stuck loops at N iters"?
   Currently 180s ≈ 3 iters at cheap-API speed. If we want a 2-iter cap,
   it's ~120s. This is a tuning call after Setting C lands.

4. **Per-scenario policy** — some scenarios (e.g. `cross_file_refactor`) may
   want stricter gating than others (e.g. `lint_fix`). Should v5.2 ship with
   per-scenario `GatingPolicy` overrides or stay one-size-fits-all? Adds
   complexity but matches reality.

5. **Audit/telemetry** — should v5.2 write a per-trial JSON record of every
   gate decision (allow / deny / redirect) so we can analyse policy fit
   post-hoc? This is the OAP "cryptographically signed audit record" minus
   the crypto. Cheap to add; expensive to retrofit.

6. **Phase-1 launch implication** — if v5.2 lands and the
   `effective_cost_experiment_v1` re-runs, what's the new hero claim we want
   to be able to make? Something like *"Trampoline blocks N% of pre-action
   policy-violating tool calls before they execute, surfacing the violation
   reason back to the agent within 1 ms"*? Confirm so I can wire the
   experiment harness to capture the right metric.

---

## 12. What I will NOT do until founder responds

  - No code changes to `loop.py`, `coding_agent_pack.py`, or any test file
  - No git commits, no push, no branch creation
  - No experiment re-runs

The proposal sits as `docs/V5_2_DESIGN_PROPOSAL.md` for review. On approval
(possibly with edits to the policy / open-questions answers), I'll
implement against the agreed shape.

---

**Sources referenced (links for founder verification):**

  - AEGIS — *No Tool Call Left Unchecked: A Pre-Execution Firewall and Audit
    Layer for AI Agents.* arxiv.org/abs/2603.12621
  - OAP — *Before the Tool Call: Deterministic Pre-Action Authorization for
    Autonomous AI Agents.* arxiv.org/abs/2603.20953
  - AWS Strands `BeforeToolCallEvent` definition:
    github.com/strands-agents/sdk-python/blob/main/src/strands/hooks/events.py
  - LangGraph `interrupt()` and synchronous BSP semantics:
    docs.langchain.com/oss/python/langgraph/interrupts
