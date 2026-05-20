# Trampoline v5.2 — Focus-Constraint Hard Enforcement (design proposal, v2)

**Status**: proposal. No code, no commit. Founder reviews before any implementation.

**Author**: Claude Code, drafted on top of v5.0.1 substrate (commit `371d4e8`).

**Date**: 2026-05-19. **Supersedes**: the earlier "pre-action authorization" v5.2 draft, which framed the work as introducing a new mechanism modelled on AEGIS / OAP. That framing was wrong. CZL **already has** the residual-driven U_{t+1} machinery; the gap is enforcement strength, not architecture.

---

## 1. One factual correction before the design

Founder's Fact 2 says *"allowed_files 维度:HARD enforce ✅"*. This is **not true in the current code on `czl-v5-canonical-rewrite` HEAD**:

  - `ystar/czl/loop.py:511` carries a stale comment claiming `apply_action` enforces `focus_constraint.allowed_files`. The comment dates from v5.0.
  - But the actual enforcement code was deleted by v5.0.1 / v5.0.2.  See `ystar/czl/scenarios/test_gen_for_existing.py:726-733`, which states explicitly:

    > *"v5.0.1+ design correction: v5.0 added a hard-reject path that SILENTLY discarded writes outside focus_constraint.allowed_files. Combined with v3.7 dominance rollback, that locked gemma in place (48 iters at residual=1.5, passing=36, zero improvement). v5.0.1 / v5.0.2 **delete the hard-reject**. focus_constraint now flows ONLY through the prompt as a SUGGESTION ... The model is free to ignore it."*

So today **every** `FocusConstraint` field — `allowed_files`, `target_cluster`, `guidance_keys`, `rationale` — flows as soft suggestion text in the prompt. The agent can ignore any of them.

This **strengthens** founder's diagnosis (everything is soft, not just target_cluster) and adds a constraint v5.2 must respect: **whatever HARD enforcement we re-introduce must not regress the v5.0.2 failure mode** — silent drops that lock the agent in place with no feedback.

The remainder of this document is designed against that constraint.

---

## 2. What CZL already has (verified by grep + view)

| Component | Verified at | What it does |
|---|---|---|
| `FocusConstraint` dataclass | `ystar/czl/autonomy.py:39-53` | Fields: `allowed_files: Optional[Set[str]]`, `target_cluster: Optional[Dict[str, Any]]`, `guidance_keys: List[str]`, `rationale: str`. No `enforcement_level` field yet. |
| `CZLAutonomyEngine.compute_focus()` | `autonomy.py:94-153` | Pure derivation from `ResidualState`: cluster ≥ 2 → focus single file; else regression → focus first newly-failing test's file; else all failure files; else unrestricted. No LLM call. |
| `CZLAutonomyEngine.pull_next_action()` | `autonomy.py:156-180` | Returns `CZLAction` whose `description` carries the focus_constraint payload as JSON and `focus_constraint` attribute. Called by `RLE._compute_next_action`. |
| Loop pulls focus_constraint | `loop.py:745-750` | After RLE event, reads `_next_action.focus_constraint` into `_active_focus_constraint` and into `contract_dict["_focus_constraint"]`. |
| Soft rendering into prompt | `loop.py:424-431` + `_render_focus_suggestion()` at `loop.py:879+` | Renders allowed_files + target_cluster + rationale as `## Focus suggestion` section with deliberately-soft language ("free to choose otherwise"). |
| Existing rejection plumbing | `loop.py:752-765` + `scenario._rejection_log` | When the scenario's `apply_action` declines a write (e.g. AST validator caught a hallucinated call), it appends `{path, reason}` to its own `_rejection_log`. The loop drains via `consume_rejections()` and surfaces in the next-iter feedback under `"## Writes from your last iter that were REJECTED"`. **No silent drop.** |

The architectural plumbing is all there. **Only the gate that turns SOFT into HARD is missing.**

---

## 3. The fix: per-field-configurable enforcement

The mechanism is **a single new closure in `loop.py` that runs between action parsing and action application**. It does not import anything new, does not call any LLM, and does not introduce any new dependency.

It compares the agent's action against the active `FocusConstraint` field-by-field, using pure-code comparisons (set membership, string equality, AST). For each field that is violated, the closure either DENIES (and surfaces the violation through the existing rejection plumbing) or logs a soft note, controlled by a per-field enforcement level declared on the `FocusConstraint` itself.

### 3.1 FocusConstraint extension (Q4a)

Add **one** field to the dataclass:

```python
@dataclass
class FocusConstraint:
    allowed_files: Optional[Set[str]] = None
    target_cluster: Optional[Dict[str, Any]] = None
    guidance_keys: List[str] = field(default_factory=lambda: ["all"])
    rationale: str = ""

    # NEW in v5.2:
    enforcement: Dict[str, str] = field(default_factory=lambda: {
        "allowed_files":    "hard",   # default
        "target_cluster":   "soft",   # default
        "guidance_keys":    "off",    # informational only — not gate-checkable
    })
```

Values: `"hard"` (DENY on violation), `"soft"` (allow + log advisory), `"off"` (skip the field entirely).

Two implementation rules this dictionary respects:

  - **Per-field configurable** (Constraint #2 from founder). Each scenario can override its `FocusConstraint`'s `enforcement` dict to set whichever strength makes sense. A test-generation scenario can mark `target_cluster` as `"hard"` if it wants; a refactor scenario can mark `allowed_files` as `"soft"`.
  - **Forward-compatible**. New `FocusConstraint` fields added later (e.g. a future `target_function: str`) declare their default enforcement level in the same dictionary. The gate iterates whatever keys are present; nothing in the gate code is keyed on a specific field name as a hardcoded special case.

### 3.2 Default enforcement levels (Q4b)

| Field | Default | Why |
|---|---|---|
| `allowed_files` | **`hard`** | This is the field founder identified as the empirical anchor of "U_{t+1}" — it's the dimension where v5.0 used to hard-enforce, and the dimension whose violation is most observable (the agent literally wrote to the wrong file). The v5.0.2 failure mode (silent drop) is solved separately by the no-silent-reject contract in §3.6, not by demoting to soft. |
| `target_cluster` | **`soft`** | This is a single (file, lineno) tuple chosen by the autonomy engine when ≥2 failures cluster at the same location. It's a **hint** about where to look first — over-strict enforcement would block the agent from making any edit outside that file, even an unambiguously-correct one. Soft enforcement renders it as guidance the agent can override. |
| `guidance_keys` | **`off`** | `guidance_keys` is "which META block to surface in the prompt" — `cluster` / `regression` / `verifier_traceback` / `all`. It's a rendering preference, not an action constraint. There is nothing to enforce on an emitted action. |

These are **defaults**. Each scenario is free to override via the constraint's own `enforcement` dict.

### 3.3 Where the gate fires (Q4c)

In `ystar/czl/loop.py`, inside the `for action in backend_response.actions:` block at lines 483-518, **just before** the `else:` branch that calls `request.scenario.apply_action(...)`. Concretely between current lines 509 and 513.

That is the same spot referenced by the stale comment at line 511 — the comment becomes accurate again because v5.2 puts the enforcement back, but at the LOOP level (not the scenario level — see §3.7 for why).

The probe action branch (`action_type == "probe_command"`, line 499) is **unaffected**. Probes are inspection, not state changes; they have no path / file content to gate.

### 3.4 The gate's comparison logic (Q4d)

Pure Python, no external service, no LLM. The gate's sole job is to compare the agent's parsed action against `_active_focus_constraint`. Skeleton:

```python
def _focus_constraint_gate(action, fc):
    """Returns ("allow" | "deny", reason_text, focus_field_violated).
    Pure structural / set / AST comparison — never calls an LLM."""
    if fc is None:
        return ("allow", "", None)            # iter 0 / no constraint yet
    # extract action's target path
    payload = action.payload if hasattr(action, "payload") else (
        action if isinstance(action, dict) else {})
    action_path = payload.get("path") or ""

    for field_name, level in fc.enforcement.items():
        if level == "off":
            continue
        field_value = getattr(fc, field_name, None)
        if not field_value:
            continue   # nothing to compare against on this field

        if field_name == "allowed_files":
            # set membership — pure comparison.
            if action_path and action_path not in field_value:
                if level == "hard":
                    return ("deny",
                            f"path {action_path!r} not in allowed_files "
                            f"{sorted(field_value)}",
                            field_name)
                # soft: fall through to next field after recording a note

        elif field_name == "target_cluster":
            # cluster is {file, lineno, count}; check that action's path is the
            # cluster file. Line-level comparison would need parsed content;
            # for v5.2 we stay at the file level.
            tc_file = field_value.get("file")
            if tc_file and action_path and action_path != tc_file:
                if level == "hard":
                    return ("deny",
                            f"target_cluster locks focus on {tc_file}; "
                            f"action targeted {action_path}",
                            field_name)

        # future fields land here, picking up their own enforcement level
        # from fc.enforcement. The gate stays generic.

    return ("allow", "", None)
```

Properties:

  - **Constraint #1 honored** — no LLM call. Pure set / string comparison.
  - **Constraint #2 honored** — enforcement reads `fc.enforcement[field_name]`. No hardcoded `if field == 'allowed_files' then hard`.
  - **Constraint #3 honored** — no statement about what the agent "should" do, only how to compare a structured FocusConstraint to a structured action.

### 3.5 What the agent sees on deny (Q4e)

When the gate denies, the loop appends a structured entry to a new `_gate_rejections` list (parallel to the existing `_iter_rejections`):

```python
{
  "path":                action_path,
  "field_violated":      "allowed_files",     # or "target_cluster"
  "reason":              "path 'utils/x.py' not in allowed_files ['service_a.py', 'service_b.py']",
  "focus_constraint":    fc.to_dict(),         # full snapshot
}
```

The next-iter feedback section renders these prominently, following the same pattern v5.1 used for the existing rejection log. Section heading: `## ⛔ Pre-action gate blocked these edits (focus-constraint enforcement)`. Body lists each gate rejection with the path, reason, and the active `rationale` so the agent understands **why** the focus exists, not just **what** was blocked.

This is the contractual remediation for the v5.0.2 silent-drop failure mode: **every denial is surfaced verbatim**.

### 3.6 Integration with v5.0.1 `_iter_rejections` (Q4f)

Two parallel lists, rendered into the prompt in deterministic order:

  1. **Scenario-level rejections** — populated by scenario's `_rejection_log` (e.g. AST validator caught a hallucinated call name). Drained via `scenario.consume_rejections()`. Existing v5.1/v5.0.2 plumbing, unchanged.
  2. **Gate-level rejections** — populated by the new pre-action gate. Drained from a loop-local `_gate_rejections` list.

Both are emptied at the same point in the loop. Rendered as two separate sections so the agent can distinguish "your write was structurally bad" from "your write was off-focus":

```
## ⛔ Pre-action gate blocked these edits (focus-constraint enforcement)
- `utils/old_api.py`: path not in allowed_files ['service_a.py', 'service_b.py'].
  Rationale: "cluster of 3 failures at service_a.py:42 — focus on this single root before broadening".

## 🚫 Writes from your last iter that were REJECTED by the scenario
- `test_x.py`: test `test_foo` calls undefined `clean_data`.
```

No interaction between the two; they're additive sections in the next-iter prompt.

### 3.7 Why the gate lives in the loop, not in `scenario.apply_action`

v5.0 put hard-reject inside `scenario.apply_action` and that was the locus of the silent-drop bug. By moving the gate to the **loop** layer:

  - We get a single chokepoint for all scenarios — no scenario can accidentally skip the enforcement.
  - The decision is visible to the loop, which owns the `_gate_rejections` list and the next-iter feedback assembly.
  - The scenario's `apply_action` keeps its current contract: it either applies cleanly or logs to its own `_rejection_log`. Nothing about scenarios changes.
  - It mirrors the AWS Strands `BeforeToolCallEvent` shape — pre-action hook outside the tool implementation.

---

## 4. What this is NOT

(All three were considered and explicitly rejected.)

**Not a new mechanism.** No `BeforeToolCallEvent` introduction, no Gateway service, no policy DSL. The gate is ~20 lines of structural comparison plus a single new field on `FocusConstraint`. The full AEGIS / OAP pattern is overkill for what we need.

**Not LLM-mediated.** The comparison is `set.__contains__` and `str.__eq__`. There is no model call deciding "are these consistent?". The OAP paper's `0%` social-engineering result depends precisely on this — once you put a model in the gate, you've added an attackable surface. CZL stays at the structural layer.

**Not retroactive on past v5.0.2 decisions.** The hard-reject removal in v5.0.1/v5.0.2 was correct given the silent-drop bug. v5.2 re-introduces hard enforcement **only because** the rejection surfacing path now exists and is mandatory. The contract is: any future "hard-enforce" change MUST also wire surfacing.

---

## 5. Concrete integration plan

| Step | File | Change | LoC |
|---|---|---|---|
| 1 | `ystar/czl/autonomy.py` | Add `enforcement: Dict[str, str]` field with the three default keys. Update `to_dict()` to include it. | ~10 |
| 2 | `ystar/czl/loop.py` | Add `_focus_constraint_gate(action, fc)` closure inside `run_scenario` (~25 lines). Add `_gate_rejections: List[Dict] = []` list. Insert gate call between current lines 509-513, denying actions whose field violations are at `"hard"` level. Drain `_gate_rejections` into a new feedback section adjacent to the existing rejection section. | ~50 |
| 3 | `ystar/czl/loop.py` | Update the comment at line 511 from "scenario.apply_action **can** enforce" to "the loop-level gate (§v5.2) enforces" — the comment finally matches the implementation again. | ~3 |
| 4 | `tests/czl/scenarios/test_v5_2_focus_gate.py` | New file with at least 5 tests: (a) allow when no fc set, (b) deny on hard `allowed_files` violation + rejection rendered into next-iter prompt, (c) allow on soft violation + advisory note recorded, (d) per-field enforcement override (set `target_cluster: "hard"` for a scenario), (e) gate skipped for probe_command. | ~250 |
| 5 | `tests/czl/scenarios/test_v5_e2e_loop.py` | Spot-check: existing 7 e2e tests still pass unchanged. (Stub backend returns no actions, so the gate is a no-op for those tests — they should be byte-equivalent to current behaviour.) | 0 |

**Production-code LoC: ~60.** Founder's Claude.ai 60–100 estimate is in range.

**Test LoC: ~250.** Brings total to ~310 (Claude.ai's estimate is for production only).

---

## 6. Edge cases worth flagging up front

  - **Iter 0 has no `_active_focus_constraint`.** The autonomy engine hasn't observed any residual yet. Gate returns ALLOW unconditionally. Correct behaviour, no edge case.
  - **Probe actions.** `probe_command` is inspection; no path / no side effect. Gate skipped (matches the existing branch at loop.py:499).
  - **`action.payload["path"]` empty.** Some scenarios route bare `python_block` actions internally to `test_data_pipeline.py`. The gate's `allowed_files` check requires a `path`; when empty, the gate has nothing to compare and returns ALLOW. The scenario layer can opt into stricter behaviour by adding its own checks.
  - **First iter where focus_constraint becomes restrictive.** When iter 1's residual reveals a cluster, iter 2 gets a restrictive `allowed_files`. If iter 2's agent legitimately needs to touch another file, the gate denies, the rejection surfaces, and iter 3 can rebuild the agent's plan. This is the intended residual-driven adaptation — not a bug.
  - **Multiple actions in one iter.** Each action gates independently. Some can ALLOW and others DENY in the same iter. Workspace gets the allowed mutations; rejection list gets the denied ones. The agent sees both outcomes in iter N+1's prompt.
  - **`fc.allowed_files = set()` (empty set, not None).** Means "no files allowed". The gate denies any path-bearing action. Matches the dataclass semantics and is intentional — empty set is a strict "wait" signal.

---

## 7. Compatibility with everything else in v5.0.1

| v5.0.1 piece | Effect of v5.2 |
|---|---|
| `ResidualLoopEngine.on_cieu_event` | Unchanged. RLE still owns residual halt decisions. |
| `CZLAutonomyEngine.compute_focus` | Unchanged. Same derivation logic; only the dataclass picks up one new field. |
| `OmissionEngine` + `InterventionEngine` | Unchanged. The pre-action gate is **independent** of the omission / intervention path. It's enforcing a SCENARIO-level focus contract, not a GOVERNANCE-level obligation contract. The two co-exist: a scenario can be allowed by the focus gate AND denied by intervention's `DECLARE_DONE` gate at convergence. |
| `_iter_rejections` plumbing | Reused as the rendering template. `_gate_rejections` is a parallel list with its own section heading. |
| Scenario `apply_action` contract | Unchanged. The gate happens before `apply_action` is called; if the gate denies, `apply_action` is never invoked. Scenarios neither need to know about nor enforce focus constraints. |
| `request.scenario.consume_rejections()` | Unchanged. |
| The 9/9 existing e2e tests | Should remain green. The stub backend in `test_v5_e2e_loop.py` returns empty action lists, so the gate is a no-op in those tests. The `test_v5_1_stuck_loop.py` uses `_AlwaysFailScenario` with no apply_action effect, same no-op. |

---

## 8. Risks and non-goals

**Risk 1: false denials that lock the agent in.** This is the v5.0.2 failure mode. The mitigation is the mandatory surfacing in §3.5 — every denial appears in the agent's next prompt with the full focus_constraint snapshot. Combined with v5.0.1's RLE oscillation detection (now correctly wired post-fix), runs that get stuck still terminate.

**Risk 2: scenarios that need different defaults.** Some scenarios may want `allowed_files: "soft"` (e.g. exploratory refactor where the autonomy engine's file guess is noisy). They can override the per-field enforcement on their `FocusConstraint`. Risk is low because the override surface is one dict.

**Risk 3: future fields adding silent special-cases.** Mitigation: the gate iterates `fc.enforcement.items()` and never hardcodes a field name. Adding a new field requires adding a default enforcement entry; no other gate change.

**Non-goal A: agent-content semantic analysis.** We do not check whether the agent's emitted code is semantically correct against the cluster's failure. The pytest verifier does that. The gate is purely about WHERE the action lands.

**Non-goal B: full AEGIS / OAP audit chain.** No Ed25519 signatures, no separate Gateway service. The existing `result.iter_prompts` + `cieu_events` + `_gate_rejections` log is enough audit for Phase 1.

**Non-goal C: replacing intervention_engine's DECLARE_DONE gate.** v5.0.1's `gate_check(DECLARE_DONE)` keeps its role: it validates the *claim* of completion against open obligations. The focus-constraint gate validates the *direction* of each action against the residual-driven U_{t+1}. The two gates fire at different moments on different signals.

---

## 9. Test plan (for the eventual implementation)

**Unit-level**

  - `FocusConstraint.enforcement` defaults match §3.2 exactly.
  - `FocusConstraint.to_dict()` includes `enforcement`.

**Gate-closure level (mock CZLRun, no real backend)**

  1. `gate_returns_allow_when_fc_is_None` — iter 0 case.
  2. `gate_hard_denies_when_path_not_in_allowed_files` — exact deny path, reason text format checked.
  3. `gate_allows_when_path_in_allowed_files` — happy path.
  4. `gate_skips_off_fields` — set `allowed_files` enforcement to `"off"`, observe allow despite violation.
  5. `gate_soft_allows_with_advisory` — set to `"soft"`, observe allow plus advisory note recorded (does not appear in gate-rejection list).
  6. `gate_skips_probe_command` — probe action passes through unchanged.

**E2E (real CZLRun stub backend)**

  7. `gate_rejection_surfaces_in_next_iter_prompt` — drive 2 iters, iter 1 emits an out-of-bounds path, assert iter-2's user prompt contains the focus-constraint gate-rejection section with the iter-1 reason.
  8. `gate_with_scenario_override_hardens_target_cluster` — instantiate a scenario whose FocusConstraint default-enforcement override sets `target_cluster: "hard"`; verify hard-denial on file != cluster_file.

**Regression**

  9. All 9 existing tests in `tests/czl/scenarios/` pass unchanged.

---

## 10. Engineering footprint vs Claude.ai's 60–100 LoC estimate

  - `autonomy.py`: +10 LoC (one new field + to_dict update).
  - `loop.py`: +50 LoC (closure + insertion + rejection rendering + comment fix).
  - **Production total: ~60 LoC.** In the lower end of Claude.ai's 60–100 estimate.
  - Tests: ~250 LoC additional.

This is **much** smaller than the earlier draft's "330 LoC additive" because that draft was scaffolding a whole new pre-action authorization layer. The corrected design just toggles existing CZL machinery from soft to hard.

---

## 11. Open questions for the founder

  1. **§3.2 default levels** — keep `allowed_files: "hard"`, `target_cluster: "soft"`, `guidance_keys: "off"`? Or invert any of them?

  2. **Per-scenario overrides** — should v5.2 ship with concrete enforcement overrides for any of the existing scenarios (e.g. `test_gen_for_existing` adding `target_cluster: "hard"`)? Or leave all five at the dataclass defaults and tune later?

  3. **Empty `allowed_files` set semantics** — §6 says "empty set = strict wait". Confirm. Alternative: treat empty set as identical to `None` (= unrestricted).

  4. **First-iter behaviour** — gate is a no-op on iter 0 because `_active_focus_constraint` is None. Confirm this is desired (no constraint until residual has been observed).

  5. **Should we re-run `effective_cost_experiment` after v5.2 lands?** If yes, the experiment hypothesis to test is: "v5.2 reduces effective-cost-per-real-completion on hard scenarios because the agent stops wandering into off-focus files mid-loop." This is a sharper claim than the v5.0.1 experiment chased.

---

## 12. What I will NOT do until founder responds

  - No code changes to `autonomy.py`, `loop.py`, or any test file.
  - No git commits, no push.
  - No experiment re-runs.

This document exists as `docs/V5_2_DESIGN_PROPOSAL.md` for review. On approval (possibly with edits to the open-question answers), I'll implement against the agreed shape.

---

## Sources verified (links for founder cross-check)

  - `ystar/czl/autonomy.py:39-180` — FocusConstraint + CZLAutonomyEngine
  - `ystar/czl/loop.py:413-441` — focus_suggestion rendering into prompt
  - `ystar/czl/loop.py:483-518` — action iteration + scenario.apply_action call site
  - `ystar/czl/loop.py:745-750` — focus_constraint pull-from-autonomy and attach-to-contract
  - `ystar/czl/loop.py:752-765` — scenario rejection drain + render
  - `ystar/czl/scenarios/test_gen_for_existing.py:726-760` — the v5.0.2 hard-reject-removal post-mortem comment
  - `docs/arch/arch17_behavioral_governance_spec.md:75` — "Every task driven by 5-tuple until Rt+1=0"
  - `docs/CZL_PRODUCT_DESIGN.md:69` — "Rt+1 > 0 → next_action_inject" diagram
  - `ystar/governance/aiden_agent_native_messenger_contract.py:112` — `protocol: "natural_language_plus_CIEU_CZL_five_tuple"` (the CIEU=CZL five-tuple identity Fact 1 anchors on)
