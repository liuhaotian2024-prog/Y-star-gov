# Trampoline v5.3 — Sub-File Granularity + Mid-Loop Sync Intervention + Per-Trial Audit

**Status**: proposal. No code, no commit. Founder reviews before any implementation.

**Author**: Claude Code, drafted on top of v5.2.1 substrate (commit `1d5dc60`).

**Date**: 2026-05-19. **Builds on**: `docs/V5_2_DESIGN_PROPOSAL.md`. v5.3 fills three gaps v5.2 didn't close.

---

## 1. What v5.2 didn't actually do

Verified by grep:

| Gap | Where it shows in code today | Effect |
|---|---|---|
| **omission/intervention scan only at RLE halt** | `loop.py` — `_drain_violations_at_halt` is called inside the three `if _halt == ...` branches at L795/L804/L823. No call site exists between action-apply and verify. | Mid-iter agent behaviour is invisible to the obligation engine until the loop is already halting. 72-trial run had 0 gate denials precisely because the gate's only signal source (intervention pulses) is built from scans that never fire mid-iter. |
| **`compute_focus` outputs file-level only** | `autonomy.py:94-153`. Returns `allowed_files: Set[str]` + `target_cluster: Dict[file,lineno,count]`. No function, test-case, or operation-type granularity. | U_{t+1} precision = "edit somewhere in file X". Agent can write garbage in X and pass the gate. Hard-deny never triggers because the only thing the gate compares is `action.payload['path'] vs allowed_files`. |
| **`_focus_constraint_gate` only knows file paths** | `loop.py:380-460`. Iterates `fc.enforcement.items()` and on each known field compares `action_path` to the field's value. The field set is hard-coded inside the closure (`allowed_files` + `target_cluster`). No sub-file semantics. | Sub-file Ut+1 has no surface in the gate logic. Founder's "Ut+1 = f(Rt+1)" contract is broken at the gate. |
| **CIEU log writes to one global SQLite DB** | `OmissionEngine.__init__` defaults `cieu_store` to `CIEUStore(db_path=".ystar_cieu_omission.db")` (omission_engine.py:135). Our v5.0.1 wiring passes `cieu_store=None` for omission (NullCIEUStore) and an explicit `NullCIEUStore()` for intervention. Net effect: **NO events get persisted at all** during the experiment. Per-trial diagnostics are impossible. | The 72-trial dataset has 0 CIEU rows. The `result.cieu_events` list captures scenario.apply_action attempts only (loop.py:563), not RLE / autonomy / gate / omission events. Founder is correct: "事件链混在一起 → 无法事后因果归因". v5.2.1 actually made this worse — we deliberately silenced persistence to avoid `.db` side-effects in tests. |

This document describes three additive changes that close all three gaps without disturbing the v5.0.1/v5.2 fixes that did work.

---

## 2. Existing parsers we re-use (no new LLM, no new heuristic)

The data we need for sub-file granularity is **already extracted** by code on disk. v5.3 adds NO new parser. It plumbs existing outputs into the FocusConstraint and the gate.

| Producer | Output structure (already in code) | Where v5.3 consumes it |
|---|---|---|
| `ystar/czl/reflection/cluster.py::parse_pytest_failures` | `[{test_name, file, lineno, function_name, error_type, error_msg}, ...]` — `function_name` is **the bottom-frame function**, i.e. the deepest call in the traceback. For a test that fails inside `clean_records()`, this is `"clean_records"`. | `compute_focus` collects these into `target_functions`. |
| `ystar/czl/reflection/transitions.py::extract_test_status` | `{test_full_id: bool}` where `test_full_id` is `"test_data_pipeline.py::test_normalize_email_lowers_case"`. | `compute_focus` collects FAILING entries into `target_test_cases`. (already used today for `delta_from_prev.newly_failing`) |
| `ResidualState.failure_locations` | `[FailureLocation(file, lineno, kind, detail), ...]`. `kind` is one of `"test_failure"|"missing_line"|"missing_branch"|"surviving_mutant"|"contract_mismatch"`. | `compute_focus` already uses for `allowed_files`. v5.3 extends to derive `target_functions` from `test_failure` locations whose `detail` includes function name. |
| `ResidualState.delta_from_prev.newly_failing` | `[test_name, ...]` — tests that PASSED prior iter, FAILING this iter. | `compute_focus` uses for `target_test_cases` regression case (already partially used). |
| `BackendAction.payload["content"]` | The raw code body the agent emitted (e.g. inside an `add_tests test_data_pipeline.py` block). | New helper `_extract_action_targets()` AST-parses this for `def test_X` declarations (sub-file granularity on what the agent's action *contains*, not just where it lands). |

Result: v5.3's sub-file granularity is **pure data-flow plumbing** of parsers that already exist. No new heuristics.

---

## 3. Proposed v5.3 architecture

### 3.1 FocusConstraint extension (sub-file fields + extended enforcement)

```python
@dataclass
class FocusConstraint:
    # v5.0/v5.2 fields (unchanged)
    allowed_files: Optional[Set[str]] = None
    target_cluster: Optional[Dict[str, Any]] = None
    guidance_keys: List[str] = field(default_factory=lambda: ["all"])
    rationale: str = ""

    # v5.3 NEW: sub-file granularity
    target_functions: Optional[Set[str]] = None        # functions the agent should change
    target_test_cases: Optional[Set[str]] = None       # test_name strings that should pass
    forbidden_operations: Optional[Set[Tuple[str, str]]] = None
        # set of (action_type, target_pattern). e.g. ("edit_file", "data_pipeline.py")
        # — agent must NOT issue this combination.

    # v5.2 enforcement dict, extended to cover the three new fields
    enforcement: Dict[str, str] = field(default_factory=lambda: {
        # v5.2 defaults (unchanged)
        "allowed_files":         "hard",
        "target_cluster":        "soft",
        "guidance_keys":         "off",
        # v5.3 defaults
        "target_functions":      "soft",   # hint; agent has freedom to refactor
        "target_test_cases":     "soft",   # hint; agent may add adjacent tests
        "forbidden_operations":  "hard",   # explicit deny-list — always hard
    })
```

`enforcement` rules unchanged from v5.2: `"hard"` denies, `"soft"` logs advisory, `"off"` skips. Scenarios still override via `Scenario.focus_constraint_enforcement_override()`.

### 3.2 `compute_focus` extension (autonomy.py)

Add field derivation **after** the existing allowed_files / target_cluster logic. All new fields are derived from data already in `ResidualState`:

```python
def compute_focus(self) -> FocusConstraint:
    fc = FocusConstraint()
    r = self._latest_residual
    if r is None or not r.failed_verifiers:
        return fc

    # existing v5.0 logic — allowed_files + target_cluster (unchanged) ...
    # [40 lines unchanged]

    # v5.3 sub-file additions (all pure dict/set comprehensions, no LLM):
    #
    # target_test_cases: tests currently failing OR newly-failing this iter.
    test_cases: Set[str] = set()
    # 1. from failure_locations where kind == "test_failure"
    for loc in r.failure_locations:
        if loc.kind == "test_failure" and "::" in loc.detail:
            # detail format from build_residual_state: "test_X [error_type]"
            # combined with loc.file gives us the full test id.
            tname = loc.detail.split(" [", 1)[0]
            if tname:
                test_cases.add(f"{loc.file}::{tname}")
    # 2. from delta_from_prev: regression tests get higher priority
    for t in r.delta_from_prev.newly_failing:
        test_cases.add(t)
    if test_cases:
        fc.target_test_cases = test_cases

    # target_functions: bottom-frame function names from pytest failures.
    # parse_pytest_failures already extracts this; we just need to keep
    # it. Plumb through by storing function_name on FailureLocation.
    fns: Set[str] = set()
    for loc in r.failure_locations:
        # FailureLocation.detail today carries "test_X [error_type]"; we
        # extend the build_residual_state to ALSO stash function_name
        # (the bottom-frame function from parse_pytest_failures, which
        # is already captured but discarded). Field name TBD — see §3.3.
        fn = getattr(loc, "bottom_function", None)
        if fn:
            fns.add(fn)
    if fns:
        fc.target_functions = fns

    # forbidden_operations: empty by default — scenario populates via override
    # (see §3.5).
    # rationale appended with sub-file detail
    if fc.target_functions:
        fc.rationale = (fc.rationale + " ; "
                        + f"focus functions: {sorted(fc.target_functions)[:5]}").lstrip(" ;")
    return fc
```

### 3.3 Minor `FailureLocation` extension (residual.py)

`parse_pytest_failures` already returns `function_name`; `build_residual_state` (residual.py:170-177) currently drops it into the `detail` string. Add it as a structured field on `FailureLocation`:

```python
@dataclass
class FailureLocation:
    file: str
    lineno: int
    kind: str
    detail: str = ""
    # v5.3 NEW: structured bottom-frame function name (from pytest parser).
    # None for non-pytest verifiers (missing_line, contract_mismatch, etc.).
    bottom_function: Optional[str] = None
```

Update build_residual_state line 177 to set this. ~3 LoC.

### 3.4 `_focus_constraint_gate` extension (loop.py) — sub-file comparison

Today the gate iterates `fc.enforcement.items()` and only knows how to handle `allowed_files` + `target_cluster`. v5.3 keeps this loop structure (per founder constraint #2: no hardcoded field handling), and adds handlers for the three new fields:

```python
def _focus_constraint_gate(action, fc):
    if fc is None: return ("allow", "", None)
    payload = action.payload if hasattr(action, "payload") else (
        action if isinstance(action, dict) else {})
    action_path = (payload or {}).get("path", "") or ""
    action_type = getattr(action, "type", None) or (payload.get("type") if payload else None) or ""
    action_content = (payload or {}).get("content", "") or ""

    # AST-extract sub-file targets from action_content. Pure-Python
    # comparison data — no LLM. Returns dict of {functions: set, tests: set}.
    action_targets = _extract_action_targets(action_content)

    for field_name, level in fc.enforcement.items():
        if level == "off":
            continue
        field_value = getattr(fc, field_name, None)
        if not field_value:
            continue

        violation_reason = None
        if field_name == "allowed_files":
            if action_path and action_path not in field_value:
                violation_reason = f"path {action_path!r} not in allowed_files {sorted(field_value)}"
        elif field_name == "target_cluster":
            tc_file = (field_value or {}).get("file")
            if tc_file and action_path and action_path != tc_file:
                violation_reason = (
                    f"target_cluster locks focus on {tc_file!r}; "
                    f"action targeted {action_path!r}"
                )
        # v5.3 NEW field handlers ↓
        elif field_name == "target_functions":
            # Soft default: at least ONE of the agent's emitted function names
            # must overlap with target_functions. Empty overlap on a non-empty
            # field_value = miss.
            agent_fns = action_targets.get("functions", set())
            if agent_fns and field_value and not (agent_fns & field_value):
                violation_reason = (
                    f"agent edited functions {sorted(agent_fns)} but none "
                    f"overlap with target_functions {sorted(field_value)}"
                )
        elif field_name == "target_test_cases":
            agent_tests = action_targets.get("test_cases", set())
            # Compare bare names (strip "file::" prefix from fc side for compat)
            target_bare = {t.split("::", 1)[1] if "::" in t else t for t in field_value}
            if agent_tests and target_bare and not (agent_tests & target_bare):
                violation_reason = (
                    f"agent emitted tests {sorted(agent_tests)} but none "
                    f"overlap with target_test_cases {sorted(target_bare)}"
                )
        elif field_name == "forbidden_operations":
            # field_value is Set[Tuple[str, str]] — (action_type, target_pattern)
            for (forbidden_type, target_pat) in field_value:
                if action_type == forbidden_type:
                    # target_pat is a literal substring of action_path
                    if not target_pat or target_pat in action_path:
                        violation_reason = (
                            f"forbidden_operations contains "
                            f"({forbidden_type!r}, {target_pat!r}); "
                            f"action matched"
                        )
                        break

        if violation_reason is None:
            continue
        if level == "hard":
            return ("deny", violation_reason, field_name)
        _gate_soft_notes.append({
            "path": action_path, "field": field_name,
            "reason": violation_reason, "rationale": fc.rationale,
        })
        result.gate_soft_notes_count += 1

    return ("allow", "", None)
```

The `_extract_action_targets(content)` helper is a thin wrapper around `ast.parse`:

```python
def _extract_action_targets(content: str) -> Dict[str, Set[str]]:
    """AST-parse code body, return {functions: set, test_cases: set}.
    Pure stdlib. test_cases = function names starting with "test_".
    Returns empty sets if content is empty / unparseable."""
    out = {"functions": set(), "test_cases": set()}
    if not content or not content.strip():
        return out
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out["functions"].add(node.name)
            if node.name.startswith("test_"):
                out["test_cases"].add(node.name)
    return out
```

Constraint #1 (no LLM) honored — `ast.parse` + set operations only.
Constraint #2 (no hardcoded field name special cases) — the field handler dispatch sits inside the same `for field_name, level in fc.enforcement.items():` loop and is **the only** place where field semantics live. Adding a new field still requires a handler here, but the dispatch is data-driven on `enforcement.items()`, not on if-chains over scenario IDs.

### 3.5 Per-scenario override extension (forbidden_operations)

`Scenario.focus_constraint_enforcement_override()` already returns `Dict[str, str]` for enforcement levels. v5.3 extends it to **also** carry field values that are scenario-specific knowledge (not residual-derived):

```python
def focus_constraint_override(self) -> Dict[str, Any]:
    """v5.3: extension of v5.2 enforcement-only override.

    Return shape (all keys optional):
      {
        "enforcement":  Dict[str, str],
        "forbidden_operations":  Set[Tuple[str, str]],   # scenario-declared
        "source_files":  Set[str],                        # used by gate to
                                                          # interpret forbidden_operations
      }

    Loop merges into the autonomy-engine-computed FocusConstraint before
    each iter's gate check. Scenarios that don't need this stay returning
    a dict with only the v5.2 "enforcement" key (backwards compat).
    """
    return {}
```

For TestGenForExistingScenario:

```python
def focus_constraint_override(self) -> Dict[str, Any]:
    return {
        "enforcement": {
            "allowed_files": "soft",            # v5.2 soft (source file gets included)
            "forbidden_operations": "hard",     # v5.3 new — strict
        },
        "forbidden_operations": {
            ("edit_file", "data_pipeline.py"),   # source under test is read-only
            ("create_file", "data_pipeline.py"),
        },
    }
```

The scenario declares "agent must not write to source-under-test". This is **scenario-domain knowledge** that the residual cannot derive. Hard-coded in the test_gen scenario class, but **not** hard-coded inside the gate or autonomy engine. Constraint #3 honored (no `if scenario == X` in the gate path).

### 3.6 Mid-loop intervention (`omission_engine.scan()` per-iter)

Today the loop calls `_drain_violations_at_halt(...)` only inside the three RLE halt branches. v5.3 adds a per-iter scan **after** `apply_action` finishes processing the current iter's actions but **before** `scenario.verify()` runs. This gives the omission engine a chance to materialise obligations into violations against the agent's just-completed action set.

Insertion point: `loop.py` between `result.iter_probes.append(this_iter_probes)` and `verifier_results = request.scenario.verify(...)`.

```python
# v5.3: mid-loop intervention. Materialise any obligation violations
# that became overdue during this iter's action processing so the
# intervention engine's gate has fresh signal before next iter.
try:
    _midloop_scan = _omission_engine.scan()
    if _midloop_scan.violations:
        _intervention_engine.process_violations(_midloop_scan.violations)
        _log.info(
            "CZL v5.3: mid-loop scan surfaced %d violation(s) at iter %d",
            len(_midloop_scan.violations), step_idx,
        )
except Exception as _exc:
    _log.debug("mid-loop scan failed at iter %d: %s", step_idx, _exc)
```

The intervention pulses generated mid-loop are what the focus_constraint_gate on **the next iter** consults via `intervention_engine.gate_check(...)` — but wait, the existing v5.2 gate doesn't call gate_check at all per-action; it does its own structural comparison. So we have two distinct gating layers:

  - **Focus gate** (sub-file structural comparison) — already per-action in v5.2; v5.3 just adds sub-file fields.
  - **Intervention gate** (obligation-aware) — currently only at DECLARE_DONE. v5.3 *could* also call this per-action, but founder's spec asks for *mid-loop scan*, not *intervention gate per action*. Conservative: do the scan; let v5.4+ add per-action intervention gate if telemetry shows it's needed.

### 3.7 Per-trial CIEU log

Founder's diagnosis #4: "CIEU log 存在 .ystar_cieu_*.db 全局数据库 → 72 个 trial 混在一起". v5.3 adds a per-run CIEU sink that writes to a JSONL file the harness names.

Two design pieces:

**(a) `loop.py` collects every governance event** that the run emits — currently only `_emit_governance(...)` writes to `_omission_engine.ingest_event`, but those events never reach `result.cieu_events`. v5.3 makes them mirror into a new `result.governance_events` list on the CZLResult dataclass:

```python
def _emit_governance(event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    ev = GovernanceEvent(
        event_type=event_type,
        entity_id=_coding_entity_id,
        actor_id=_coding_actor_id,
        payload=payload or {},
        source="czl.loop",
    )
    try:
        _omission_engine.ingest_event(ev)
    except Exception as _exc:
        _log.debug("governance emit %s failed: %s", event_type, _exc)
    # v5.3: also append to result.governance_events for per-trial audit.
    result.governance_events.append(ev.to_dict())
```

Also mirror gate decisions, focus_constraint snapshots, and RLE halt events into the same list.

**(b) `benchmarks/effective_cost/run_experiment.py` writes per-trial JSONL** after each trial:

```python
log_path = Path("results/effective_cost_experiment_v1/cieu_logs") / \
           f"trial_{trial_idx:03d}_{model_id}_{scenario_id}_{arm}.jsonl"
log_path.parent.mkdir(parents=True, exist_ok=True)
with open(log_path, "w") as f:
    for ev in result.governance_events:
        f.write(json.dumps(ev, default=str) + "\n")
```

Per-trial file count: 72 trials × 2 files (one per arm — but trampoline arm produces governance events; baseline arm doesn't go through run_scenario so it gets an empty file or skipped). Disk: ~hundreds of KB total.

---

## 4. Hard-acceptance verification (founder spec)

### 4.1 Deliberately-off test (single, fast)

`tests/czl/scenarios/test_v53_mid_loop_intervention.py::test_gate_denies_source_file_edit_for_test_gen`:

  - Materialise a TestGenForExistingScenario workspace.
  - Set up a stub backend that, on iter 1, returns an action with `type="edit_file"` and `payload["path"]="data_pipeline.py"` (the source-under-test — forbidden).
  - Run 2 iters.
  - Assert:
    - `result.gate_denied_count >= 1`
    - the gate-rejection's `field_violated == "forbidden_operations"`
    - the rejection reason includes `("edit_file", "data_pipeline.py")` literal
    - the result's `governance_events` list contains the gate-deny event
    - the iter-2 user prompt contains the structured rejection diagnostic

### 4.2 Sub-file granularity unit tests

`test_compute_focus_extracts_target_functions_from_pytest_failure`:
  - Build a `ResidualState` with a `failure_locations` entry having `bottom_function="clean_records"`.
  - Call `CZLAutonomyEngine.compute_focus()`.
  - Assert `fc.target_functions == {"clean_records"}`.

`test_compute_focus_extracts_target_test_cases_from_regression`:
  - Build a ResidualState with `delta_from_prev.newly_failing = ["test_X"]`.
  - Assert `fc.target_test_cases == {"test_X"}`.

`test_extract_action_targets_ast_parse`:
  - Pass code `"def test_foo(): pass\ndef bar(): pass"`.
  - Assert `_extract_action_targets` returns `{"functions": {"test_foo","bar"}, "test_cases": {"test_foo"}}`.

### 4.3 Mid-loop scan unit test

`test_mid_loop_scan_surfaces_violations_before_halt`:
  - Build a synthetic run that has an obligation overdue by iter 2.
  - Assert log message `"CZL v5.3: mid-loop scan surfaced N violation(s) at iter 2"`.
  - Assert `intervention_engine.pulse_store` has at least 1 pulse after iter 2.

### 4.4 72-trial re-run acceptance

After v5.3 lands:

  - **Gate must fire**: at least one of (a) ≥1/3 of trampoline trials have `gate_denied_count > 0`, or (b) CIEU log evidence shows the gate evaluated correctly but no agent deviated. Founder accepts either, but (b) requires the per-trial CIEU log to actually exist (§3.7).
  - **No verified-rate regression**: aggregate Trampoline verified ≥ 97% (v5.2 baseline).
  - **No more than +20% aggregate cost**: aggregate Trampoline cost ≤ $1.85 (v5.2 was $1.54).
  - All 17 existing `tests/czl/` plus the new v5.3 tests pass.

---

## 5. Risks + non-goals

**Risk 1: `target_functions: soft` default is too permissive.**
The bottom-frame function from pytest can be ANY function in the call stack — sometimes a stdlib helper. If the gate hard-denied on this, false positives would spike. Mitigation: soft by default, scenarios can hard-enforce via override.

**Risk 2: `forbidden_operations` as `Set[Tuple[str, str]]` becomes unwieldy if many patterns.**
For test_gen, 2-3 entries. For more complex scenarios, could grow. Mitigation: keep set semantics; if it grows past ~10 entries per scenario, revisit with a domain-specific override structure.

**Risk 3: Mid-loop scan latency.**
`omission_engine.scan()` walks `store.list_obligations()`. With InMemoryOmissionStore and ~5 obligations per run, this is sub-ms. With persistent SQLite (future Phase-2 ops mode), could be tens of ms. v5.3 stays at InMemory.

**Risk 4: Per-trial CIEU log disk usage.**
72 trials × ~50 events each × ~200 bytes per event = ~700 KB. Negligible. Tests check no `.db` side-effects only (the new JSONL files are in `results/`, not workspace).

**Non-goal A: Per-action intervention gate.**
v5.3 adds mid-loop scan but doesn't call `intervention_engine.gate_check(...)` per-action. The focus gate (structural) is per-action; the intervention gate (obligation-aware) remains halt-time. If telemetry from v5.3 shows obligations escape into stuck-loop territory before halt, v5.4 adds intervention per-action.

**Non-goal B: Replacing `parse_pytest_failures`.**
We re-use it verbatim. No new pytest parser.

**Non-goal C: LLM-based "is the agent's action consistent with U_{t+1}?" check.**
Founder constraint #1 — pure structural comparison.

---

## 6. Engineering footprint (verified estimate)

| File | Change | LoC |
|---|---|---|
| `ystar/czl/autonomy.py` | FocusConstraint: +3 fields + 3 enforcement defaults. compute_focus: +20 LoC for sub-file derivation. | ~30 |
| `ystar/czl/residual.py` | FailureLocation: +1 field `bottom_function`. build_residual_state: +1 LoC to populate it from parse_pytest_failures. | ~3 |
| `ystar/czl/loop.py` | `_focus_constraint_gate`: +50 LoC (handlers for 3 new fields + AST helper). Mid-loop scan: +12 LoC. `_emit_governance` mirror to result.governance_events: +2 LoC. CZLResult.governance_events: +1 field. | ~70 |
| `ystar/czl/scenarios/base.py` | `focus_constraint_override`: signature change `Dict[str, str]` → `Dict[str, Any]` (still backwards compat). | ~5 |
| `ystar/czl/scenarios/test_gen_for_existing.py` | Update override to include `forbidden_operations` for source file edits. | ~10 |
| `tests/czl/scenarios/test_v53_mid_loop_intervention.py` | NEW file with 5+ tests covering §4.1-4.3. | ~250 |
| `benchmarks/effective_cost/run_experiment.py` | Per-trial CIEU JSONL write. | ~15 |
| **Total** | | **~380 LoC** (200-300 estimate + tests) |

Production code: ~130 LoC.
Tests: ~250 LoC.

Founder estimate "200-300 LoC additive" is in range when counting production only.

---

## 7. Open questions for the founder

  1. **`target_functions` default = soft. Confirm**, or should test_gen override it to hard? My recommendation: keep soft; the bottom-frame function from pytest can be a stdlib helper (e.g. `dict.__contains__`), and hard-denying on stdlib would block all action.

  2. **`forbidden_operations` for cross_file_refactor / lint_fix.** v5.3 ships with the test_gen override only. Should we declare forbidden ops for the other two scenarios too? My recommendation: hold off until telemetry shows they need it. The override interface is in place; adding later is one-line.

  3. **Per-trial CIEU log → push to git?** Adds ~700 KB to the repo per experiment run. Recommendation: yes, commit alongside `raw_trials.csv` so the experiment is reproducible end-to-end. Alternative: `.gitignore` the `cieu_logs/` subdir.

  4. **Baseline arm CIEU log.** Baseline arm doesn't go through `run_scenario`; it has no loop, no scan, no gate. The per-trial log will be empty/absent for baseline trials. Confirm OK — the per-trial log is meaningful for trampoline arm only. (Founder's spec said "every trial", so I'd write an empty placeholder file to keep file count consistent.)

  5. **The `test_compute_focus_extracts_target_functions` test depends on FailureLocation.bottom_function being populated.** This requires the residual.py extension (§3.3). Confirm we should land that 3-LoC change as part of v5.3 rather than a separate substrate-touching commit.

---

## 8. What I will NOT do until founder responds

  - No code changes to autonomy.py, residual.py, loop.py, base.py, test_gen_for_existing.py.
  - No git commits, no push.
  - No experiment re-runs.

This document exists as `docs/V5_3_DESIGN_PROPOSAL.md` for review. On approval (possibly with edits to the open-question answers), I'll implement against the agreed shape, run the v5.3 test suite, run the deliberately-off acceptance test, run the 72-trial re-run, and only then commit.

---

## Sources verified

  - `ystar/czl/autonomy.py:39-180` — FocusConstraint + compute_focus current shape
  - `ystar/czl/loop.py:347-455` — `_focus_constraint_gate` current closure
  - `ystar/czl/loop.py:563-602` — per-action apply + iter probes accumulation
  - `ystar/czl/loop.py:773-843` — _drain_violations_at_halt only inside halt branches
  - `ystar/czl/residual.py:31-234` — ResidualState + build_residual_state + FailureLocation
  - `ystar/czl/reflection/cluster.py:61` — parse_pytest_failures returns `function_name`
  - `ystar/czl/reflection/transitions.py:43-64` — parse_pytest_v_outcomes + extract_test_status
  - `ystar/czl/backends/base.py:281-341` — _parse_actions_from_text + BackendAction shape
  - `ystar/governance/omission_engine.py:135` — default cieu_store path
  - `ystar/governance/residual_loop_engine.py:114-180` — on_cieu_event flow
