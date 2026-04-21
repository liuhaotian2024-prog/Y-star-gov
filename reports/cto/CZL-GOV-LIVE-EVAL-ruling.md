# CZL-GOV-LIVE-EVAL — CTO Architectural Ruling

**Author**: Ethan Wright (CTO)
**Date**: 2026-04-19
**In response to**: CEO spec `reports/ceo/governance/directive_liveness_evaluator_v1.md` (Aiden, 2026-04-19)
**Board authority**: 2026-04-19 — "以后如何可以被持续的智能的执行"
**Status**: RULING — answers Q1-Q4 + 2 supplementary items

---

## CIEU 5-Tuple

- **Y***: All 6 open items answered with concrete, implementable decisions backed by architectural rationale. Zero ambiguity for Maya's Phase 1 implementation.
- **Xt**: CEO spec has 4 explicit open questions (Section 7) + 2 implicit architectural unknowns (phase-ordering vs in-flight DISPATCH-EXEC/BRAIN-BIPARTITE work; retro-annotation scope bounding).
- **U**: Analyze router_registry.py API, OmissionEngine contract, ForgetGuard rule schema, dispatch_board.py data model, then rule on each item.
- **Yt+1**: Ruling document covers all 6 items; Maya can begin Phase 1 without blocking on CTO.
- **Rt+1**: 0

---

## Ruling 1: Y*gov Product Core vs Company Layer

**Decision**: Split placement. Primitives library + evaluator engine go in Y*gov product core. Directive annotation schema and retro-annotation tooling go in company layer.

**Rationale**:

The 3-component model (trigger/release/scope) and the 7 check primitives are *general-purpose governance machinery*. Any Y*gov customer deploying multi-agent systems will face the same stale-directive problem. The evaluator that composes primitives into a verdict is likewise reusable — it is the governance equivalent of a liveness probe, and every orchestrated system needs one.

However, the *specific directive annotations* (CZL-P2-PAUSE-20260418, etc.) and the retro-annotation campaign scripts are operational artifacts of Y* Bridge Labs. They reference our whiteboard, our dispatch_board.json, our specific agent IDs. Putting these in the product repo would leak company-internal state into a customer-facing package.

**Concrete placement**:

| Artifact | Repository | Path |
|---|---|---|
| `DirectiveLivenessEvaluator` class | Y-star-gov | `ystar/governance/directive_evaluator.py` |
| 7 check primitive functions | Y-star-gov | `ystar/governance/directive_primitives.py` |
| Directive annotation JSON schema | Y-star-gov | `ystar/governance/schemas/directive_v1.schema.json` |
| RouterRule detector+executor for directive-scoped enforcement | Y-star-gov | `ystar/governance/rules/directive_liveness_rule.py` (loadable via `router_registry.load_rules_dir()`) |
| Retro-annotation script (reads dispatch_board.json, writes annotations) | ystar-company | `scripts/retro_annotate_directives.py` |
| Company-specific directive annotation store | ystar-company | `governance/directives/` (one JSON per directive, or single SQLite — see Ruling 2) |
| `evaluate_blocks` subcommand extension | ystar-company | `scripts/dispatch_board.py` (new subcommand, calls product-core evaluator) |

**Integration contract**: The product-core evaluator takes a directive annotation dict + a primitives registry, returns a verdict. It does NOT know about dispatch_board.json or company-specific storage. The company layer passes directive data in, receives verdicts out. This follows the same Governance-Production separation pattern as OmissionEngine (product core) vs company-specific obligation rules.

---

## Ruling 2: Annotation Schema Storage

**Decision**: Phase 1 uses filesystem JSON (one `.json` file per directive in `governance/directives/`). Phase 2 migrates to a SQLite table `directives` in the existing `.ystar_cieu.db` database.

**Rationale against JSON-in-whiteboard-task-record**:

The CEO spec's lean toward SQLite for Phase 2+ is correct, but embedding annotations inside whiteboard task records (dispatch_board.json) is architecturally wrong for three reasons:

1. **Not all directives originate from whiteboard tasks.** FG rules, Board verbal commands, AGENTS.md constraints, governance/*.md pauses — these have no whiteboard task record. The storage must be directive-first, not task-first.

2. **Query patterns differ.** The whiteboard is FIFO-by-posted-at for engineer claim flow. Directive evaluation needs scope-pattern matching, release-condition correlation, and staleness sorting. Bolting these queries onto dispatch_board.json would warp its data model.

3. **Locking semantics conflict.** dispatch_board.py uses `fcntl.flock` for short FIFO mutations. Evaluator reads are side-effect-free and should not contend with engineer claim/complete write locks.

**Phase 1 filesystem layout** (`governance/directives/`):
```
governance/directives/
  CZL-P2-PAUSE-20260418.json
  CEO-DIR-LIVE-EVAL-20260419.json
  ...
```

Each file follows the schema from CEO spec Section 2, verbatim. The evaluator `glob`s the directory, loads each file, runs primitives. This is O(n) on directive count, which for our scale (estimated <50 active directives) is sub-millisecond.

**Phase 2 SQLite migration**: Add table `directives` to `.ystar_cieu.db` with columns: `directive_id TEXT PRIMARY KEY, issued_at TEXT, issued_by TEXT, trigger_json TEXT, release_json TEXT, scope_json TEXT, evaluator_json TEXT, raw_json TEXT, updated_at TEXT`. The evaluator switches from glob-load to `SELECT * FROM directives WHERE evaluator_json->>'verdict' != 'RELEASED'`. This enables cross-directive correlation (e.g., "which directives share a release condition?") and temporal queries. Migration script reads the JSON files, inserts rows, archives JSON to `governance/directives/archive/`.

**Why not SQLite from day one**: Phase 1 velocity. Filesystem JSON is debuggable with `cat`, diffable with `git`, and requires zero schema migration tooling. The evaluator engine accepts a `List[dict]` — it is storage-agnostic. Swapping the loader from "glob JSON files" to "SELECT from SQLite" is a 10-line change in the company-layer integration code, not a product-core change.

---

## Ruling 3: ForgetGuard Interaction

**Decision**: Parallel in Phase 1, selective ingest in Phase 2. FG rules are NOT directives in the general sense — they are a *subset* that can be modeled as directives, but forcing immediate unification would break FG's existing enforcement flow.

**Rationale**:

ForgetGuard rules and directives share structural similarity:
- FG `pattern` maps to directive `scope.pattern`
- FG `mode: deny` maps to directive liveness verdict `LIVE` producing a deny
- FG `dry_run_until` maps to directive `release.check` (time-based release)

But they differ in critical ways:

1. **Enforcement mechanism.** FG rules fire inside the hook's hot path on every tool call (latency-critical, <1ms detector budget). Directive liveness evaluation is a batch/scan operation (boot-time or subcommand-invoked). Merging them would either slow the hook or require the evaluator to run at hook frequency — both are unacceptable.

2. **Rule authorship.** FG rules are authored by governance engineers in YAML with regex patterns. Directives are authored by Board/CEO/CTO as structured JSON with semantic check primitives. Different authorship flows, different review processes.

3. **Lifecycle semantics.** FG rules are permanent constraints (hierarchy, no-choice-questions). Directives are temporal — they are *expected* to transition from LIVE to RELEASED. An FG rule that auto-releases would violate FG's design intent (detecting organizational amnesia is a permanent concern).

**Phase 1 (parallel)**: FG rules and directive evaluator operate independently. FG continues to fire in the hook. Directive evaluator fires on `evaluate_blocks` subcommand and boot-time scan. No coupling.

**Phase 2 (selective ingest)**: FG rules that have `dry_run_until` set (i.e., time-bounded FG rules like `enforcement_gap_persistent` and `task_dispatch_without_y_star`) are candidates for directive-model representation. The evaluator can ingest these as read-only directive proxies: it reads `forget_guard_rules.yaml`, synthesizes directive annotations for rules with `dry_run_until != null`, and evaluates their liveness alongside explicit directives. This gives a unified staleness view without touching FG's enforcement path.

FG rules with `dry_run_until: null` (permanent constraints) are excluded from directive ingest — they are axioms, not directives, and should never be evaluated for release.

**Implementation note for Maya**: In Phase 1, the `directive_primitives.py` module should export a `fg_rule_is_expired(rule_name: str) -> bool` primitive that reads `forget_guard_rules.yaml` and checks if `dry_run_until < now`. This lets directives *reference* FG state without coupling the engines.

---

## Ruling 4: LLM-Judge Role on AMBIGUOUS Cases

**Decision**: Acceptable under strict constraints. The evaluator must never use LLM judgment to override a deterministic check. LLM judgment is permitted only for the composition step when primitive results are insufficient to resolve a verdict.

**Constraints (all mandatory)**:

1. **Conservative default**: If no LLM is available (offline, timeout, error), the verdict MUST default to `LIVE`. A directive is assumed in-force until proven otherwise. This is the fail-safe-toward-caution principle from CEO spec Section 5.

2. **Audit trail**: Every LLM-judged verdict must emit a CIEU event of type `DIRECTIVE_LLM_JUDGMENT` containing:
   - `directive_id`
   - `primitive_results: Dict[str, bool]` (what the deterministic checks returned)
   - `llm_prompt` (the exact prompt sent to the model, for reproducibility)
   - `llm_response` (the raw model output)
   - `llm_verdict` (the model's conclusion: LIVE/RELEASED/AMBIGUOUS)
   - `final_verdict` (what the evaluator actually applied — may differ if human-ack overrides)
   - `model_id` (which model was used)
   - `timestamp`

3. **Scope limitation**: LLM judgment is only invoked when:
   - Exactly 1 of the 3 components (trigger/release/scope) evaluates to `ambiguous` via primitives, AND
   - The other 2 components are not both `resolved`/`met` (because if they are, the directive is already RELEASED without LLM help).
   - If 2+ components are ambiguous, the verdict is `AMBIGUOUS` with `requires_human_ack=true` — no LLM override.

4. **Human-ack gate for Board-issued directives**: Even if LLM concludes `RELEASED`, Board-issued directives require `requires_human_ack=true` unless the Board has explicitly opted out for that directive class. The LLM verdict is a *recommendation*, not a unilateral release. This is non-negotiable for constitutional and hierarchy-discipline directives.

5. **No LLM in Phase 1**: Phase 1 implements deterministic-only evaluation. LLM judgment is a Phase 2 addition, gated behind a feature flag (`directive_evaluator.llm_judge_enabled = false` by default). This lets us validate the primitive library's coverage before introducing probabilistic elements.

**Rationale**: The governance layer must be deterministic by default. Introducing LLM judgment without these constraints would create an audit gap — "the model decided this directive was stale" is not a defensible answer in a governance framework. The constraints ensure that LLM judgment is traceable, conservative, and overridable.

---

## Ruling 5: Phase-Ordering vs DISPATCH-EXEC and BRAIN-BIPARTITE

**Decision**: Directive Liveness Evaluator Phase 1 is independent of both DISPATCH-EXEC migration and BRAIN-BIPARTITE. Phase 2 router-rule integration has a dependency on ARCH-17 router_registry being stabilized, but that dependency is already met (router_registry.py is at L3 with full API).

**Ordering analysis**:

| Work stream | Dependency on LIVE-EVAL? | LIVE-EVAL dependency on it? |
|---|---|---|
| DISPATCH-EXEC (CZL-P2-b) | No — dispatch flow does not check directive liveness today | No — evaluator reads whiteboard state but does not modify dispatch flow |
| BRAIN-BIPARTITE (CZL-166) | No — brain fusion is CEO cognitive architecture, orthogonal to governance enforcement | No — evaluator does not use brain state |
| ARCH-17 router_registry (P2-a) | Phase 2 integration: evaluator registers a RouterRule with the registry | Phase 1: no dependency. Phase 2: router_registry.py API is stable (L3), no blocking risk |
| OmissionEngine | Phase 2: evaluator auto-closes obligations when directive releases | Phase 1: no dependency. Phase 2: OmissionEngine API (`ingest_event`) is stable |
| ForgetGuard | See Ruling 3 — parallel in Phase 1, selective ingest in Phase 2 | Phase 1: no dependency |

**Conclusion**: Phase 1 is clean to proceed immediately. No sequencing conflict. The `evaluate_blocks` subcommand and boot-time staleness report are self-contained additions that do not touch any in-flight migration surface.

Phase 2 router-rule integration should be sequenced *after* P2-a router_registry has at least one other rule registered and smoke-tested (so the registry's hot-path performance is validated). The directive liveness rule would register at priority 50 (advisory tier) — it is not a constitutional or workflow rule.

---

## Ruling 6: Retro-Annotation Scope Bounding

**Decision**: Phase 1 retro-annotation is bounded to exactly the directives that are *currently blocking or constraining active work*. This is NOT "annotate every historical directive ever issued."

**Bounded scope**:

1. **P2 pause family** (CZL-P2-PAUSE-20260418 and any sub-directives covering P2-b/c/d/e). These are the directives the CEO spec explicitly cites. 4 annotations maximum.

2. **Any Board-issued pauses in the last 7 days** that are referenced in `governance/dispatch_board.json` task records with `status=blocked` or `blocked_on` fields. Currently 0 tasks are blocked on the dispatch board, so this adds 0 annotations.

3. **Active FG rules with `dry_run_until` set** (time-bounded rules only, per Ruling 3). Currently 2 rules qualify: `enforcement_gap_persistent` (dry_run_until 2026-04-18) and `task_dispatch_without_y_star` (dry_run_until 2026-04-22). These get synthesized as directive annotations automatically, not manually retro-annotated.

**Total Phase 1 retro-annotation work**: 4 directive JSON files (the P2 pause family), written by hand or by `retro_annotate_directives.py` script. Estimated 3 tool uses for the script, 1 tool use per annotation verification. Budget: 7 tool uses total.

**What is explicitly out of scope for Phase 1**:
- Historical Board decisions from before 2026-04-12 (pre-AMENDMENT-004 era)
- AGENTS.md constitutional constraints (these are axioms, not temporal directives)
- Completed/archived campaign subgoals from `.czl_subgoals.json`
- Any directive that has already been informally superseded (if no one is blocked on it, there is no urgency to annotate it)

**Phase 2 retro-annotation expansion**: After Phase 1 validation, a one-time sweep of `governance/*.md` files to extract implicit directives (grep for "pause", "block", "ban", "prohibit", "pending", "until"). Each extracted candidate gets a directive annotation with `evaluator.verdict = "AMBIGUOUS"` and `requires_human_ack = true`. Board reviews the batch, confirms/rejects each. This is a bounded cleanup, not an ongoing obligation.

---

## Summary Table

| Item | Decision | Phase |
|---|---|---|
| Q1: Product vs Company | Split: engine in Y*gov, annotations in company | Phase 1 |
| Q2: Storage | Filesystem JSON Phase 1, SQLite Phase 2 | Phase 1/2 |
| Q3: ForgetGuard | Parallel Phase 1, selective ingest Phase 2 | Phase 1/2 |
| Q4: LLM-judge | Acceptable with 5 hard constraints; Phase 2 only | Phase 2 |
| Q5: Phase-ordering | No conflicts; Phase 1 proceeds immediately | Phase 1 |
| Q6: Retro-annotation | Bounded to 4 P2-pause directives; 7 tool uses | Phase 1 |

---

## Implementation Handoff to Maya (eng-governance)

Maya should begin Phase 1 by implementing in this order:

1. `ystar/governance/directive_primitives.py` — 7 check functions, all pure/deterministic, with unit tests.
2. `ystar/governance/schemas/directive_v1.schema.json` — JSON Schema for validation.
3. `ystar/governance/directive_evaluator.py` — `DirectiveLivenessEvaluator` class that loads annotations, runs primitives, returns verdicts.
4. Company-side: `governance/directives/` directory + 4 retro-annotation JSON files for P2 pause family.
5. Company-side: `scripts/dispatch_board.py` `evaluate_blocks` subcommand extension.
6. Company-side: `governance_boot.sh` staleness report line (count of directives with changed verdict since last eval).

Ryan (eng-platform) assists on item 5 (dispatch_board.py CLI extension) only.

Leo (eng-kernel) is not needed until Phase 2 router-rule integration.

**Scope guard for Maya**: Files in scope are `ystar/governance/directive_*.py`, `ystar/governance/schemas/`, and tests. No modifications to `router_registry.py`, `omission_engine.py`, `forget_guard.py`, or `forget_guard_rules.yaml` in Phase 1.
