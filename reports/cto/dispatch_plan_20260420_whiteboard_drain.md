Audience: CEO (Aiden) for immediate spawn dispatch + eng-kernel (Leo), eng-platform (Ryan), eng-governance (Maya) for implementation reference
Research basis: CTO rulings (CZL-AUTO-COMMIT-PUSH-ruling.md, CZL-BRAIN-3LOOP-FINAL-ruling.md, CZL-BRAIN-BIPARTITE-P2-ALGO-ruling.md, CZL-BRAIN-AUTO-INGEST-ruling.md) + scripts/.pending_spawns.jsonl full prompt_hints + .czl_subgoals.json campaign state + dispatch_board 8 pending P0/P1 tasks
Synthesis: 8 whiteboard tasks map to 7 engineer spawns across 3 waves (CZL-ESCAPE-SEMANTIC-REVERSAL merges into CZL-BIPARTITE-LOADER-IMPL; CEO spec update is self-serve). Ryan sequenced (3 tasks serial), Leo sequenced (3 tasks serial), Maya parallel-capable (2 tasks). Each skeleton is copy-paste spawn-ready.
Purpose: CEO reads this file and spawns Wave 1 (3 parallel) immediately, then Waves 2-3 after receipt verification, with zero ambiguity on engineer assignment, scope, or success criteria.

# Dispatch Plan: 8-Task Whiteboard Drain (2026-04-20)

**Author**: Ethan Wright (CTO)
**Date**: 2026-04-20
**Status**: DISPATCH PLAN ISSUED — CEO spawns per skeletons below

---

## Receipt (5-tuple)

- **Y***: All 8 pending whiteboard tasks assigned to engineers with dependency ordering, concurrency plan, and spawn-ready prompt skeletons. CEO reads this file and spawns without ambiguity.
- **Xt**: 8 tasks sitting on dispatch board (2 P0, 6 P1). CTO rulings exist for AUTO-COMMIT-PUSH, BRAIN-3LOOP-FINAL, BRAIN-AUTO-INGEST, BRAIN-BIPARTITE-P2-ALGO. One task (CZL-ESCAPE-SEMANTIC-REVERSAL) routed to fictional `eng-cto-triage` — needs re-routing.
- **U**: (1) Read all pending_spawns.jsonl prompt_hints, (2) cross-referenced with existing CTO rulings, (3) determined engineer assignments per scope+competency, (4) built dependency DAG, (5) wrote prompt skeletons.
- **Yt+1**: CEO has actionable dispatch file; first wave spawnable immediately.
- **Rt+1**: 0 — all 8 covered, no ambiguity, no choice questions.

---

## Task Triage Summary

### Re-routing Decisions

| atomic_id | Original routed_to | Corrected Assignment | Rationale |
|---|---|---|---|
| CZL-ESCAPE-SEMANTIC-REVERSAL | eng-cto-triage (fictional) | **Split: CEO spec update (CEO-owned, no spawn) + Leo-Kernel for loader semantics** | CTO ruling H.7 already covers the architectural decision. CEO updates own spec Sections 3.2+3.4 (no engineer needed). Leo implements the pre/post-hook split in cieu_bipartite_learner.py — this is subsumed by CZL-BIPARTITE-LOADER-IMPL which already includes H.7 escape reversal in its prompt_hint. **MERGE into CZL-BIPARTITE-LOADER-IMPL.** Separate card unnecessary. |
| CZL-CHARTER-FLOW-RULE-PILOT | eng-governance | **Maya-Governance** | Correct. Rule-based router is governance scope. |
| CZL-BRAIN-AUTO-EXTRACT-EDGES | eng-governance | **Leo-Kernel (semantic extraction) + Ryan-Platform (hook/scheduler)** | Prompt_hint says both. Leo owns entity/relation extraction logic; Ryan wires into session boundaries. But this task is **GATED** on Leo#2 add_node fix + Ethan Q8 access_count fix — both already shipped. Unblocked. Primary owner: Leo-Kernel. |

### Merge/Cancel Decisions

| atomic_id | Decision | Rationale |
|---|---|---|
| CZL-ESCAPE-SEMANTIC-REVERSAL | **MERGE into CZL-BIPARTITE-LOADER-IMPL** | The bipartite loader implementation card already includes H.7 escape reversal (pre-hook +0.6, post-hook -0.3, PRE_HOOK_CUTOFF constant, batch composition changes). Spawning a separate task for the same code changes would create conflicting edits to cieu_bipartite_learner.py. CEO spec update is CEO's own work, not an engineer task. Net: 8 tasks become 7 engineer spawns. |

---

## Dependency DAG

```
Phase 0 (Independent, spawn immediately):
  CZL-AUTO-COMMIT-PUSH-CADENCE  [Ryan-Platform, P0]
  CZL-CHARTER-FLOW-RULE-PILOT   [Maya-Governance, P1]

Phase 1 (Independent, spawn immediately or after Phase 0 if concurrency cap hit):
  CZL-BRAIN-3LOOP-LIVE           [Ryan-Platform, P0]  <- WARNING: Ryan has 2 tasks
  CZL-BRAIN-L2-WRITEBACK-IMPL    [Leo-Kernel, P1]     <- L2 Hebbian module
  CZL-DOMINANCE-MONITOR          [Maya-Governance, P1] <- after CHARTER if serial

Phase 2 (Depends on Phase 1):
  CZL-BIPARTITE-LOADER-IMPL      [Leo-Kernel, P1]     <- depends on L2 Hebbian being live
  CZL-BRAIN-AUTO-EXTRACT-EDGES   [Leo-Kernel, P1]     <- depends on add_node fix (SHIPPED)

Phase 2b (Independent but lower priority):
  (CEO spec update for ESCAPE-SEMANTIC-REVERSAL -- CEO does this, no spawn needed)
```

### Ryan Overload Analysis

Ryan has 3 tasks (AUTO-COMMIT-PUSH P0, BRAIN-3LOOP-LIVE P0, BRAIN-L2-WRITEBACK-IMPL P1-platform-wire portion). This is too many concurrent tasks.

**Resolution**: Sequence Ryan's work:
1. **First**: CZL-AUTO-COMMIT-PUSH-CADENCE (P0, self-contained, CTO ruling fully specifies 7-item checklist)
2. **Second**: CZL-BRAIN-3LOOP-LIVE (P0, hook wiring — the platform integration of L1/L2/L3)
3. **Third**: CZL-BRAIN-L2-WRITEBACK-IMPL platform wire (P1, after Leo ships the Hebbian module)

Leo has 3 tasks sequentially: L2-WRITEBACK first, then BIPARTITE-LOADER, then AUTO-EXTRACT-EDGES.

Maya has 2 tasks in parallel-capable: CHARTER-FLOW-RULE-PILOT and DOMINANCE-MONITOR.

---

## Concurrency Plan

Session age ~15min, concurrency cap allows 3 parallel spawns.

**Wave 1 (spawn immediately, 3 parallel)**:
1. Ryan-Platform: CZL-AUTO-COMMIT-PUSH-CADENCE (P0)
2. Leo-Kernel: CZL-BRAIN-L2-WRITEBACK-IMPL (P1, Leo's portion: Hebbian module)
3. Maya-Governance: CZL-CHARTER-FLOW-RULE-PILOT (P1)

**Wave 2 (after Wave 1 returns, 2-3 parallel)**:
4. Ryan-Platform: CZL-BRAIN-3LOOP-LIVE (P0, hook wiring for all 3 loops)
5. Maya-Governance: CZL-DOMINANCE-MONITOR (P1)
6. Leo-Kernel: CZL-BIPARTITE-LOADER-IMPL (P1, includes ESCAPE-SEMANTIC-REVERSAL)

**Wave 3 (after Wave 2 returns)**:
7. Leo-Kernel: CZL-BRAIN-AUTO-EXTRACT-EDGES (P1)

---

## Sub-Agent Type Mapping

| Task | Sub-Agent (from .claude/agents/) |
|---|---|
| CZL-AUTO-COMMIT-PUSH-CADENCE | eng-platform |
| CZL-BRAIN-3LOOP-LIVE | eng-platform |
| CZL-BRAIN-L2-WRITEBACK-IMPL | eng-kernel |
| CZL-BIPARTITE-LOADER-IMPL | eng-kernel |
| CZL-DOMINANCE-MONITOR | eng-governance |
| CZL-CHARTER-FLOW-RULE-PILOT | eng-governance |
| CZL-BRAIN-AUTO-EXTRACT-EDGES | eng-kernel |

---

## Prompt Skeletons

### SKELETON 1: CZL-AUTO-COMMIT-PUSH-CADENCE (Ryan-Platform, P0)

```
== BOOT CONTEXT (mandatory) ==
1. Read: /Users/haotianliu/.openclaw/workspace/ystar-company/.czl_subgoals.json
2. Run: git log --oneline -10
3. Run: python3.11 /Users/haotianliu/.openclaw/workspace/ystar-company/scripts/precheck_existing.py (if exists)

== TASK ==
atomic_id: CZL-AUTO-COMMIT-PUSH-CADENCE
Priority: P0
Engineer: Ryan Park (eng-platform)
CTO Ruling: /Users/haotianliu/.openclaw/workspace/Y-star-gov/reports/cto/CZL-AUTO-COMMIT-PUSH-ruling.md

== SCOPE (files you may create or edit -- NOTHING else) ==
- scripts/auto_commit_push.py (NEW, ~150 LOC)
- scripts/session_state_flush.py (NEW, ~60 LOC)
- scripts/session_close_yml.py (EDIT: add state flush call after secretary_curate block)
- scripts/governance_boot.sh (EDIT: add state flush call after ALL SYSTEMS GO)
- scripts/hook_stop_reply_scan.py (EDIT: add 25-min cadence check function)
- .ystar_autocommit_scope.json (NEW: externalized include/exclude globs)
- tests/platform/test_auto_commit_push.py (NEW: 4+ test cases)

== DEPENDENCIES ==
None. This task is self-contained.

== SUCCESS CRITERIA ==
- [ ] auto_commit_push.py exists, reads .ystar_active_agent, runs 6 safety gates, stages per include/exclude, commits with template, pushes if authorized, writes .ystar_push_pending if not
- [ ] session_state_flush.py exists, orchestrates brain_ingest + auto_commit_push, emits SESSION_STATE_FLUSH CIEU event
- [ ] session_close_yml.py calls session_state_flush.py --mode close
- [ ] governance_boot.sh calls session_state_flush.py --mode boot
- [ ] hook_stop_reply_scan.py has cadence check (25-min threshold, fires auto_commit_push)
- [ ] test_auto_commit_push.py has 4+ test cases (gate abort, exclude .env, eng no-push, cadence trigger)
- [ ] All tests pass: python -m pytest tests/platform/test_auto_commit_push.py -v

== HARD CONSTRAINTS ==
- NO git commit, NO git push, NO git add, NO git reset
- NO choice questions -- pick and execute, report result
- Follow CTO ruling exactly (all 7 implementation items in Section 7)
- Do NOT modify files outside scope list above

== RECEIPT FORMAT (mandatory) ==
Return a 5-tuple receipt:
- Y*: [restate the goal]
- Xt: [what existed before you started]
- U: [what you did, step by step]
- Yt+1: [what exists now]
- Rt+1: [honest gap -- 0 if all success criteria met, >0 with specific unmet items]
```

### SKELETON 2: CZL-BRAIN-L2-WRITEBACK-IMPL (Leo-Kernel, P1)

```
== BOOT CONTEXT (mandatory) ==
1. Read: /Users/haotianliu/.openclaw/workspace/ystar-company/.czl_subgoals.json
2. Run: git log --oneline -10
3. Run: python3.11 /Users/haotianliu/.openclaw/workspace/ystar-company/scripts/precheck_existing.py (if exists)

== TASK ==
atomic_id: CZL-BRAIN-L2-WRITEBACK-IMPL
Priority: P1
Engineer: Leo Chen (eng-kernel)
CTO Ruling: /Users/haotianliu/.openclaw/workspace/Y-star-gov/reports/cto/CZL-BRAIN-3LOOP-FINAL-ruling.md (Points 6, 8, 9, 10)

== SCOPE (files you may create or edit -- NOTHING else) ==
- scripts/hook_ceo_post_output_brain_writeback.py (NEW: outcome-weighted Hebbian module)

== IMPLEMENTATION SPEC ==
Per CEO v2 Section 3.3 + CTO ruling Points 6+8+9+10:
- Negative outcome within OUTCOME_WINDOW_SECONDS=900: w_AB = max(0, w_AB - 0.15 * r_A * r_B)
- Positive/neutral outcome: w_AB = min(1.0, w_AB + 0.10 * r_A * r_B)
- Exclude provenance='system:brain' per CTO Q6 self-ref guard
- Emit BRAIN_HEBBIAN_UPDATE_POSITIVE and BRAIN_HEBBIAN_DECAY CIEU events
- Warm-start silence: suppress L2 when activation_log < 5000 rows, emit BRAIN_WARMUP_PENDING
- Within-session Hebbian only (no cross-session aggregation)

== DEPENDENCIES ==
- aiden_brain.py must be importable (EXISTS, confirmed)
- .ystar_cieu.db must be accessible (EXISTS, confirmed)

== SUCCESS CRITERIA ==
- [ ] hook_ceo_post_output_brain_writeback.py exists with Hebbian update logic
- [ ] OUTCOME_WINDOW_SECONDS = 900 as module constant (not hardcoded in logic)
- [ ] Self-ref guard excludes provenance='system:brain'
- [ ] Warm-start suppression when activation_log < 5000
- [ ] CIEU events emitted: BRAIN_HEBBIAN_UPDATE_POSITIVE, BRAIN_HEBBIAN_DECAY, BRAIN_WARMUP_PENDING
- [ ] Module can be imported without errors: python3 -c "import scripts.hook_ceo_post_output_brain_writeback"

== HARD CONSTRAINTS ==
- NO git commit, NO git push, NO git add, NO git reset
- NO choice questions -- pick and execute, report result
- Do NOT modify files outside scope list above
- Do NOT wire this into settings.json hooks (Ryan does that in CZL-BRAIN-3LOOP-LIVE)

== RECEIPT FORMAT (mandatory) ==
Return a 5-tuple receipt:
- Y*: [restate the goal]
- Xt: [what existed before you started]
- U: [what you did, step by step]
- Yt+1: [what exists now]
- Rt+1: [honest gap -- 0 if all success criteria met, >0 with specific unmet items]
```

### SKELETON 3: CZL-CHARTER-FLOW-RULE-PILOT (Maya-Governance, P1)

```
== BOOT CONTEXT (mandatory) ==
1. Read: /Users/haotianliu/.openclaw/workspace/ystar-company/.czl_subgoals.json
2. Run: git log --oneline -10
3. Run: python3.11 /Users/haotianliu/.openclaw/workspace/ystar-company/scripts/precheck_existing.py (if exists)

== TASK ==
atomic_id: CZL-CHARTER-FLOW-RULE-PILOT
Priority: P1
Engineer: Maya Patel (eng-governance)

== SCOPE (files you may create or edit -- NOTHING else) ==
- Y-star-gov/ystar/governance/rules/charter_amendment_flow.rule.yaml (NEW)
- Y-star-gov/ystar/governance/router_registry.py (EDIT: register new rule)
- tests/enforce_router/test_charter_flow_rule.py (NEW)

== IMPLEMENTATION SPEC ==
Proof-of-concept: migrate BOARD_CHARTER_AMENDMENTS.md header flow to an enforce-router rule.
- Detector: Agent call OR Edit/Write tool targeting AGENTS.md where actor != secretary
- Executor: REDIRECT with fix_command='spawn Samantha-Secretary with charter amendment payload'
- INJECT BOARD_CHARTER_AMENDMENTS.md header content as context
- Live-fire smoke test: CEO simulates wrong-role AGENTS.md edit -> expect CIEU event CHARTER_FLOW_REDIRECT + correct fix_command returned

== DEPENDENCIES ==
None. This is a standalone pilot.

== SUCCESS CRITERIA ==
- [ ] charter_amendment_flow.rule.yaml exists with detector + executor config
- [ ] router_registry.py updated to load the new rule
- [ ] test_charter_flow_rule.py has smoke test (wrong-role edit -> REDIRECT + fix_command)
- [ ] All tests pass: python -m pytest tests/enforce_router/test_charter_flow_rule.py -v
- [ ] Post-completion: write follow-up task card listing next 5 migration targets (write to stdout in receipt, do NOT create dispatch_board entries)

== HARD CONSTRAINTS ==
- NO git commit, NO git push, NO git add, NO git reset
- NO choice questions -- pick and execute, report result
- Do NOT modify files outside scope list above
- This is a PILOT -- do not attempt to migrate all 39 protocols, only the charter amendment flow

== RECEIPT FORMAT (mandatory) ==
Return a 5-tuple receipt:
- Y*: [restate the goal]
- Xt: [what existed before you started]
- U: [what you did, step by step]
- Yt+1: [what exists now]
- Rt+1: [honest gap -- 0 if all success criteria met, >0 with specific unmet items]
```

### SKELETON 4: CZL-BRAIN-3LOOP-LIVE (Ryan-Platform, P0)

```
== BOOT CONTEXT (mandatory) ==
1. Read: /Users/haotianliu/.openclaw/workspace/ystar-company/.czl_subgoals.json
2. Run: git log --oneline -10
3. Run: python3.11 /Users/haotianliu/.openclaw/workspace/ystar-company/scripts/precheck_existing.py (if exists)

== TASK ==
atomic_id: CZL-BRAIN-3LOOP-LIVE
Priority: P0
Engineer: Ryan Park (eng-platform)
CTO Ruling: /Users/haotianliu/.openclaw/workspace/Y-star-gov/reports/cto/CZL-BRAIN-3LOOP-FINAL-ruling.md

== SCOPE (files you may create or edit -- NOTHING else) ==
- scripts/hook_ceo_pre_output_brain_query.py (EDIT: wire L1 on UserPromptSubmit + PostToolUse with 120s+overlap guard)
- .claude/settings.json (EDIT: register L1 hook on UserPromptSubmit, L2 hook on PostToolUse(Agent)+PostToolUse(Stop))
- scripts/session_close_yml.py (EDIT: add dream trigger on session close)
- scripts/aiden_dream.py (EDIT: activate scheduling -- currently exists but inactive)

== IMPLEMENTATION SPEC ==
Per CTO 3LOOP-FINAL ruling:
- Loop 1 (L1): hook_ceo_pre_output_brain_query.py fires on UserPromptSubmit. Also fires on PostToolUse with self-throttle guard (>120s since last query AND <20% scope overlap with prior top-k).
- Loop 2 (L2): hook_ceo_post_output_brain_writeback.py (built by Leo in separate task) wired on PostToolUse(Agent) + PostToolUse(Stop). Build async co-activation queue with 30s drain cycle.
- Loop 3 (L3): aiden_dream.py fires on Board offline >= 4h OR session close. Add idempotency guard.
- Register all hooks in .claude/settings.json hooks array.
- Measure learning-lag KPI: target < 5s for Hebbian sync path.

== DEPENDENCIES ==
- CZL-BRAIN-L2-WRITEBACK-IMPL must be complete (Leo ships the module, Ryan wires it)
- hook_ceo_pre_output_brain_query.py must exist (EXISTS, confirmed)
- aiden_dream.py must exist (EXISTS, confirmed)

== SUCCESS CRITERIA ==
- [ ] L1 fires on UserPromptSubmit (verify via CIEU event BRAIN_L1_QUERY)
- [ ] L1 re-injection fires on PostToolUse with 120s+overlap guard
- [ ] L2 hook registered on PostToolUse(Agent) and PostToolUse(Stop)
- [ ] L3 dream fires on session close (verify via session_close_yml.py call)
- [ ] settings.json updated with all hook registrations
- [ ] Async co-activation queue with 30s drain cycle exists
- [ ] No import errors: python3 -c "import scripts.hook_ceo_pre_output_brain_query"

== HARD CONSTRAINTS ==
- NO git commit, NO git push, NO git add, NO git reset
- NO choice questions -- pick and execute, report result
- Do NOT modify files outside scope list above
- L2 hook module is Leo's deliverable -- if it does not exist yet, wire a stub import with try/except and log BRAIN_L2_NOT_AVAILABLE

== RECEIPT FORMAT (mandatory) ==
Return a 5-tuple receipt:
- Y*: [restate the goal]
- Xt: [what existed before you started]
- U: [what you did, step by step]
- Yt+1: [what exists now]
- Rt+1: [honest gap -- 0 if all success criteria met, >0 with specific unmet items]
```

### SKELETON 5: CZL-DOMINANCE-MONITOR (Maya-Governance, P1)

```
== BOOT CONTEXT (mandatory) ==
1. Read: /Users/haotianliu/.openclaw/workspace/ystar-company/.czl_subgoals.json
2. Run: git log --oneline -10
3. Run: python3.11 /Users/haotianliu/.openclaw/workspace/ystar-company/scripts/precheck_existing.py (if exists)

== TASK ==
atomic_id: CZL-DOMINANCE-MONITOR
Priority: P1
Engineer: Maya Patel (eng-governance)
CTO Ruling: /Users/haotianliu/.openclaw/workspace/Y-star-gov/reports/cto/CZL-BRAIN-3LOOP-FINAL-ruling.md (Point 7)

== SCOPE (files you may create or edit -- NOTHING else) ==
- scripts/brain_dominance_monitor.py (NEW: DominanceTracker class)
- scripts/hook_ceo_pre_output_brain_query.py (EDIT: integrate monitor after L1 returns top-k, before injection)
- scripts/session_close_yml.py (EDIT: add boot-report integration if >3 alerts in 30 days)

== IMPLEMENTATION SPEC ==
Per CEO v2 Section 4 + CTO ruling Point 7:
- DominanceTracker class with sliding window of last 100 L1 queries
- Per query: compute fraction of last 100 where node X was top-1
- If X exceeds 10%: emit BRAIN_NODE_DOMINANCE_WARNING (node_id, frequency)
- If X exceeds 20%: emit BRAIN_NODE_DOMINANCE_ALERT + reduce X effective weight by 50% in next 50 queries (transient suppression)
- Store query history in aiden_brain.db dominance_log table (query_id, top1_node_id, timestamp)
- Report to CEO via next boot report if >3 alerts in 30 days

== DEPENDENCIES ==
- hook_ceo_pre_output_brain_query.py must exist (EXISTS, confirmed)
- aiden_brain.db must be accessible (EXISTS, confirmed)

== SUCCESS CRITERIA ==
- [ ] brain_dominance_monitor.py exists with DominanceTracker class
- [ ] dominance_log table created in aiden_brain.db
- [ ] 10% threshold -> BRAIN_NODE_DOMINANCE_WARNING CIEU event
- [ ] 20% threshold -> BRAIN_NODE_DOMINANCE_ALERT + 50% weight suppression for 50 queries
- [ ] Integration into hook_ceo_pre_output_brain_query.py call path
- [ ] Test: inject 100 synthetic queries with 15 hitting same node -> warning fires
- [ ] Test: inject 100 synthetic queries with 25 hitting same node -> alert fires + suppression applied
- [ ] Module importable: python3 -c "import scripts.brain_dominance_monitor"

== HARD CONSTRAINTS ==
- NO git commit, NO git push, NO git add, NO git reset
- NO choice questions -- pick and execute, report result
- Do NOT modify files outside scope list above
- Use sliding window (last 100 queries), NOT time-based window

== RECEIPT FORMAT (mandatory) ==
Return a 5-tuple receipt:
- Y*: [restate the goal]
- Xt: [what existed before you started]
- U: [what you did, step by step]
- Yt+1: [what exists now]
- Rt+1: [honest gap -- 0 if all success criteria met, >0 with specific unmet items]
```

### SKELETON 6: CZL-BIPARTITE-LOADER-IMPL (Leo-Kernel, P1) [INCLUDES CZL-ESCAPE-SEMANTIC-REVERSAL]

```
== BOOT CONTEXT (mandatory) ==
1. Read: /Users/haotianliu/.openclaw/workspace/ystar-company/.czl_subgoals.json
2. Run: git log --oneline -10
3. Run: python3.11 /Users/haotianliu/.openclaw/workspace/ystar-company/scripts/precheck_existing.py (if exists)

== TASK ==
atomic_id: CZL-BIPARTITE-LOADER-IMPL (absorbs CZL-ESCAPE-SEMANTIC-REVERSAL)
Priority: P1
Engineer: Leo Chen (eng-kernel)
CTO Ruling: /Users/haotianliu/.openclaw/workspace/Y-star-gov/reports/cto/CZL-BRAIN-BIPARTITE-P2-ALGO-ruling.md (H.1-H.7, especially H.7 escape reversal)

== SCOPE (files you may create or edit -- NOTHING else) ==
- scripts/cieu_bipartite_learner.py (NEW: full Phase 2 bipartite learner implementation)
- scripts/aiden_brain.py (EDIT: add node_checkpoints table if not exists)

== IMPLEMENTATION SPEC ==
Per CTO P2-ALGO ruling, implement all 7 sections:
- H.1: LAMBDA_CONTRASTIVE = 0.5 fixed, module constant
- H.2: RADIUS_MULTIPLIER = 0.5, diagnostic assertion (median relevance >= 20), emit BIPARTITE_RADIUS_DIAGNOSTIC
- H.3: Checkpoints in aiden_brain.db node_checkpoints table, retain last 20
- H.4: Time-based held-out (last 7 days), NO cieu_holdout table
- H.5: Leo delta-from-old formula (supersedes CEO original)
- H.6: REWRITE gate excluded -- 3-condition gate, corpus >= 50, emit BIPARTITE_REWRITE_GATE_CLOSED
- H.7: ESCAPE SEMANTIC REVERSAL -- pre-hook escape +0.6 positive, post-hook escape -0.3 negative, PRE_HOOK_CUTOFF constant, 5% floor uses post-hook first then backfill pre-hook at -0.1

Uses normalizer v3 training_eligible field.

== DEPENDENCIES ==
- CZL-BRAIN-L2-WRITEBACK-IMPL should be complete (provides co-activation data for training)
- cieu_decision_normalizer.py must exist with training_eligible field (EXISTS, confirmed)
- aiden_brain.db must be accessible (EXISTS, confirmed)

== SUCCESS CRITERIA ==
- [ ] cieu_bipartite_learner.py exists with full H.1-H.7 implementation
- [ ] node_checkpoints table created, retention policy (keep last 20)
- [ ] Run 1 pass on current CIEU corpus successfully (no assertion fires)
- [ ] KL divergence computed on 7-day held-out
- [ ] Checkpoint saved after pass
- [ ] Pre-hook escape events get weight +0.6
- [ ] Post-hook escape events get weight -0.3
- [ ] Escape oversampling floor: post-hook first, backfill pre-hook at -0.1
- [ ] BIPARTITE_RADIUS_DIAGNOSTIC + BIPARTITE_REWRITE_GATE_CLOSED CIEU events emitted
- [ ] Module importable: python3 -c "import scripts.cieu_bipartite_learner"

== HARD CONSTRAINTS ==
- NO git commit, NO git push, NO git add, NO git reset
- NO choice questions -- pick and execute, report result
- Do NOT modify files outside scope list above
- Do NOT create cieu_holdout table (Phase 2 uses time-based holdout)
- Do NOT make lambda adaptive (fixed at 0.5)

== RECEIPT FORMAT (mandatory) ==
Return a 5-tuple receipt:
- Y*: [restate the goal]
- Xt: [what existed before you started]
- U: [what you did, step by step]
- Yt+1: [what exists now]
- Rt+1: [honest gap -- 0 if all success criteria met, >0 with specific unmet items]
```

### SKELETON 7: CZL-BRAIN-AUTO-EXTRACT-EDGES (Leo-Kernel, P1)

```
== BOOT CONTEXT (mandatory) ==
1. Read: /Users/haotianliu/.openclaw/workspace/ystar-company/.czl_subgoals.json
2. Run: git log --oneline -10
3. Run: python3.11 /Users/haotianliu/.openclaw/workspace/ystar-company/scripts/precheck_existing.py (if exists)

== TASK ==
atomic_id: CZL-BRAIN-AUTO-EXTRACT-EDGES
Priority: P1
Engineer: Leo Chen (eng-kernel)
CTO Ruling: /Users/haotianliu/.openclaw/workspace/Y-star-gov/reports/cto/CZL-BRAIN-AUTO-INGEST-ruling.md (Section 2: Leo scope)

== SCOPE (files you may create or edit -- NOTHING else) ==
- Y-star-gov/ystar/governance/cieu_to_graph_extractor.py (NEW: entity/relation extraction from CIEU events)
- scripts/aiden_import.py (EDIT: integrate graph extractor into import pipeline)
- scripts/session_close_yml.py (EDIT: call graph extractor at session close boundary)

== IMPLEMENTATION SPEC ==
Per Board 2026-04-19 directive + CTO ingest ruling:
- Auto-extract 6 entity types: Agent, Rule, File, Tool, Command, Session
- Auto-extract 6 relation types: triggered_rule, touches_file, dispatches_to, blocked_by, co_touched_with, co_fired_with
- Frequency thresholds: entity >= 3 occurrences, edge >= 2
- Rare-tail: keep in separate staging table (not in main nodes/edges)
- Hebbian seeding: co-occurrence count becomes initial edge weight (capped 0.3)
- Integrate into session boundary ingest pipeline (extends scan from files-only to files+CIEU)

== DEPENDENCIES ==
- add_node ON CONFLICT fix (SHIPPED, confirmed)
- aiden_brain.db accessible (EXISTS, confirmed)
- .ystar_cieu.db accessible (EXISTS, confirmed)

== SUCCESS CRITERIA ==
- [ ] cieu_to_graph_extractor.py exists with extract_entities() and extract_relations() functions
- [ ] 6 entity types extracted from CIEU events
- [ ] 6 relation types extracted from CIEU events
- [ ] Frequency thresholds enforced (entity >= 3, edge >= 2)
- [ ] Staging table for rare-tail entities/edges
- [ ] Hebbian seeding: co-occurrence -> initial weight (capped 0.3)
- [ ] Integration into aiden_import.py pipeline
- [ ] Session close boundary trigger in session_close_yml.py
- [ ] Run on current CIEU corpus: entities extracted > 0, edges extracted > 0
- [ ] Module importable: python3 -c "from ystar.governance.cieu_to_graph_extractor import extract_entities"

== HARD CONSTRAINTS ==
- NO git commit, NO git push, NO git add, NO git reset
- NO choice questions -- pick and execute, report result
- Do NOT modify files outside scope list above
- Initial edge weights capped at 0.3 -- manual curation still bounded
- Rare-tail goes to staging, NOT main nodes/edges tables

== RECEIPT FORMAT (mandatory) ==
Return a 5-tuple receipt:
- Y*: [restate the goal]
- Xt: [what existed before you started]
- U: [what you did, step by step]
- Yt+1: [what exists now]
- Rt+1: [honest gap -- 0 if all success criteria met, >0 with specific unmet items]
```

---

## Quick-Reference Spawn Table for CEO

| Wave | Task | Sub-Agent File | Priority | Skeleton # |
|---|---|---|---|---|
| 1 | CZL-AUTO-COMMIT-PUSH-CADENCE | .claude/agents/eng-platform.md | P0 | 1 |
| 1 | CZL-BRAIN-L2-WRITEBACK-IMPL | .claude/agents/eng-kernel.md | P1 | 2 |
| 1 | CZL-CHARTER-FLOW-RULE-PILOT | .claude/agents/eng-governance.md | P1 | 3 |
| 2 | CZL-BRAIN-3LOOP-LIVE | .claude/agents/eng-platform.md | P0 | 4 |
| 2 | CZL-DOMINANCE-MONITOR | .claude/agents/eng-governance.md | P1 | 5 |
| 2 | CZL-BIPARTITE-LOADER-IMPL | .claude/agents/eng-kernel.md | P1 | 6 |
| 3 | CZL-BRAIN-AUTO-EXTRACT-EDGES | .claude/agents/eng-kernel.md | P1 | 7 |
| -- | CZL-ESCAPE-SEMANTIC-REVERSAL (CEO spec update) | N/A (CEO self-serve) | P1 | N/A |

**CEO action for each spawn**: Copy skeleton from this file, paste as Agent tool prompt. BOOT CONTEXT block is already included in each skeleton -- CEO does NOT need to add anything. Just spawn.

---

## Cross-References

- CTO Ruling (auto-commit): `Y-star-gov/reports/cto/CZL-AUTO-COMMIT-PUSH-ruling.md`
- CTO Ruling (3-loop): `Y-star-gov/reports/cto/CZL-BRAIN-3LOOP-FINAL-ruling.md`
- CTO Ruling (bipartite P2): `Y-star-gov/reports/cto/CZL-BRAIN-BIPARTITE-P2-ALGO-ruling.md`
- CTO Ruling (auto-ingest): `Y-star-gov/reports/cto/CZL-BRAIN-AUTO-INGEST-ruling.md`
- Pending spawns detail: `scripts/.pending_spawns.jsonl`
- Sub-agent definitions: `.claude/agents/eng-{kernel,platform,governance}.md`

---

*This dispatch plan is binding. CEO spawns Wave 1 immediately, Waves 2-3 sequentially after receipt verification. CZL-ESCAPE-SEMANTIC-REVERSAL is CEO's own spec update (Sections 3.2+3.4 of cieu_bipartite_learning_v1.md) -- no engineer spawn needed.*
