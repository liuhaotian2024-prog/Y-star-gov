# ARCH-17: Behavioral Governance and Shelf-Activation Architecture

## Section 0: Consolidation Notes

This is the **canonical** ARCH-17 specification, consolidated from three fragments on 2026-04-19:

1. **Phase-0 migration spec** (556 lines, `Y-star-gov/docs/arch/arch17_behavioral_governance_spec.md`) -- module-ownership classification, phased implementation plan, formal definitions. Used as base.
2. **Original spec** (451 lines, `ystar-company/docs/arch17_behavioral_governance_spec.md`) -- initial 7-category taxonomy + enforcement matrix. All content subsumed by this document.
3. **Shelf-activation spec** (390 lines, `ystar-company/knowledge/cto/arch17_behavioral_governance_spec.md`) -- CEO wisdom inventory, 5 activation channels, GWT/Hebbian mathematical model, 7 industry precedents. Merged into Sections 12-16 below.

Both redundant files have been replaced with 1-line stubs pointing here.

**ARCH-18 cross-reference**: Phases 2+ of shelf-activation (Sections 15-16) depend on ARCH-18 CIEU-as-Brain-Corpus (`knowledge/cto/arch18_cieu_brain_corpus.md`) for failure library extraction, causal chain analysis, and brain context generation. Wherever behavioral rules need historical decision data, ARCH-18's `M(E)` memory representation provides the retrieval substrate.

---

**Author**: Ethan Wright (CTO)
**Date**: 2026-04-18 (original) / 2026-04-19 (consolidated)
**Status**: SPEC (L1)
**Authority**: Board directive 2026-04-18
**Implementers**: Leo Chen (eng-kernel), Maya Patel (eng-governance), Ryan Park (eng-platform)

---

## 1. Problem Statement

Y*gov currently enforces **structural** governance: file permissions, agent identity, dispatch routing, session lifecycle. It does NOT enforce **behavioral** governance: cognitive discipline, communication quality, work habits, honesty signals.

30+ behavioral rules exist as MEMORY.md feedback entries. These are LLM-self-applied: the agent reads them at boot, promises to follow them, then degrades under pressure. This is structurally inevitable, not a willpower problem.

**Empirical evidence of regression (2026-04-18 Board-caught)**:
- CEO built new components that already existed (reinventing) -- violates `feedback_god_view_before_build.md`
- CEO produced activity without progress (performative busyness) -- violates `feedback_status_maturity_taxonomy.md`
- CEO postponed work without blocker (procrastination) -- violates `feedback_no_clock_out.md`
- CEO stated intent without executing -- violates `feedback_no_deferred_dispatch_promise.md`

**Root cause**: Self-enforcement has no backstop. When context window fills, cognitive load rises, or lock-death pressure mounts, self-enforcement is the first thing to degrade. Per `autonomy_degradation_root_cause_2026_04_13.md`, this is factor #1 (decision muscle atrophy) and factor #7 (no proactive-work hard constraint).

---

## 2. Taxonomy: 7 Behavioral Enforcement Categories

Classification of all 41 feedback memory files into enforceable categories.

### Category 1: PRE-OUTPUT DISCIPLINE
**Definition**: Rules governing the text Claude emits before it reaches the user/Board.

| Feedback File | Rule Summary |
|---|---|
| `feedback_aiden_authority_no_questions.md` | No choice questions; CEO decides and executes |
| `feedback_subagent_no_choice_question.md` | Iron Rule 0 propagates to sub-agent receipts |
| `feedback_ceo_reply_must_be_5tuple.md` | CEO replies to Board must be Y*/Xt/U/Yt+1/Rt+1 structured |
| `feedback_no_consultant_time_scales.md` | No "one week / 3 days" consultant time units internally |
| `feedback_methodology_no_human_time_grain.md` | Strip human cadence from imported frameworks |
| `feedback_status_maturity_taxonomy.md` | Every work item must carry L0-L5 maturity tag |
| `feedback_address_laoda.md` | Board-facing replies use proper addressing convention |
| `feedback_restart_quietude.md` | Post-boot: one line only, no governance dump |
| `feedback_close_stub_trigger.md` | No EOD stub while Board is online |
| `feedback_board_shell_marker.md` | Shell commands to Board must use marker format |
| `feedback_article11_framing.md` | Frame sub-agent dispatch as "Article 11", not passive waiting |

**Existing enforcement**: ForgetGuard `choice_question_to_board` (deny), postponement-language rules (deny). Stop hook scans for avoidance/choice patterns post-reply (warn only). `hook_ceo_pre_output.py` checks U-workflow signals on Write to external paths.

**Gap**: 5-tuple structure, L-tag presence, consultant time-scale language, and addressing convention have ZERO runtime enforcement. Self-applied only.

### Category 2: PRE-EXECUTION DISCIPLINE
**Definition**: Rules governing what must happen BEFORE an agent takes a significant step (build, create, dispatch).

| Feedback File | Rule Summary |
|---|---|
| `feedback_god_view_before_build.md` | Glob+Grep 4 repos before proposing new component |
| `feedback_ceo_ecosystem_view_required.md` | Ecosystem Dependency Map before any design dispatch |
| `feedback_testing_is_ceo_scope.md` | Testing is CEO scope, no Board approval needed |
| `feedback_no_defer_immediate_activation.md` | Changes effective immediately, no "next session" postponement |
| `feedback_cieu_5tuple_task_method.md` | Every task driven by 5-tuple until Rt+1=0 |
| `feedback_action_model_3component.md` | Every dispatch = backlog + K9 + AC (3-component) |

**Existing enforcement**: ForgetGuard `czl_dispatch_missing_5tuple` (deny). `task_dispatch_without_y_star` (deny, dry_run grace period).

**Gap**: "god view before build" has NO enforcement. An agent can Write a new file to `scripts/` without any pre-check that the capability already exists. This is today's highest-regression category.

### Category 3: DISPATCH DISCIPLINE
**Definition**: Rules governing how work is assigned to sub-agents / engineers.

| Feedback File | Rule Summary |
|---|---|
| `feedback_dispatch_via_cto.md` | Cross-engineer work must go through CTO |
| `feedback_use_whiteboard_not_direct_spawn.md` | Post to dispatch_board.json, not Agent spawn |
| `feedback_taskcard_not_dispatch.md` | Writing task card without Agent call is not dispatch |
| `feedback_explicit_git_op_prohibition.md` | Spawn prompts must include "no git commit/push" clause |
| `feedback_hi_agent_campaign_mechanism.md` | Dispatch must include BOOT CONTEXT block |
| `feedback_no_deferred_dispatch_promise.md` | "Next-round dispatch X" without same-turn Agent call = hollow promise |
| `feedback_cto_subagent_cannot_async_orchestrate.md` | CDP structural limitation: CTO cannot nest sub-sub-agents |

**Existing enforcement**: ForgetGuard `ceo_direct_engineer_dispatch` (deny), `ceo_skip_gov_dispatch` (deny). `hook_pretool_agent_dispatch.py` gates Agent tool calls.

**Gap**: Hollow dispatch promise detection, whiteboard-vs-direct-spawn enforcement, git-op prohibition in spawn payload, BOOT CONTEXT block presence check -- all unenforced.

### Category 4: RECEIPT/CLOSE DISCIPLINE
**Definition**: Rules governing how completed work is verified and marked done.

| Feedback File | Rule Summary |
|---|---|
| `feedback_subagent_receipt_empirical_verify.md` | Never trust self-reported Rt+1=0; verify artifacts on disk |
| `feedback_cmo_12layer_rt_loop.md` | CMO content must complete 12-layer + 5 counterfactual checks |
| `feedback_no_static_image_for_video.md` | Video task L4 must be real dynamic video |
| `feedback_rt1_0________lesson_default_is_production_mode.md` | Default is production mode |
| `feedback_rt1_0________lesson_production_mode_writes_to_real_m.md` | Production mode writes to real MEMORY |
| `feedback_team_enforce_asymmetry.md` | Format compliance != runtime enforcement; smoke-test gates |

**Existing enforcement**: ForgetGuard `czl_receipt_rt_not_zero` (deny). Stop hook `auto_validate_subagent_receipt` runs post-reply.

**Gap**: Empirical verification (ls/wc/pytest after sub-agent return) is self-applied. tool_uses=0 or duration<30s red-flag detection has no automatic trigger.

### Category 5: DELEGATION/IDENTITY DISCIPLINE
**Definition**: Rules governing who does what and agent identity boundaries.

| Feedback File | Rule Summary |
|---|---|
| `feedback_default_agent_is_ceo.md` | Default boot identity is CEO (Aiden) |
| `feedback_cto_owns_technical_modeling.md` | Technical arch decisions = CTO scope, not CEO |
| `feedback_daemon_cache_workaround.md` | Daemon caches stale agent identity; pkill+rm to fix |
| `feedback_self_heal_via_daemon_window.md` | Self-heal active_agent drift via daemon kill window |
| `feedback_subagent_registry_boot_only.md` | Agent registry only reloads at session boot |
| `feedback_no_clock_out.md` | CEO never "clocks out" unilaterally |

**Existing enforcement**: hook_wrapper.py checks `.ystar_active_agent` for file-write scope. `hook_session_start.py` sets identity at boot.

**Gap**: "CEO is doing CTO's work" (technical design, formal methods) has no enforcement. The delegation boundary between coordinator and engineer roles is structurally unenforced.

### Category 6: HONESTY/TRANSPARENCY DISCIPLINE
**Definition**: Rules governing truthful communication and disclosure.

| Feedback File | Rule Summary |
|---|---|
| `feedback_ai_disclosure_mandatory.md` | All external outreach must disclose AI authorship |
| `feedback_scenario_c_is_real_usp.md` | Don't overclaim governance evidence (Scenario A vs C) |
| `feedback_defer_vs_schedule_distinction.md` | Postponement (avoidance) vs scheduling (planning) must be distinguished |
| `feedback_break_glass_disable_project_hook.md` | Break-glass protocol for lock-death |

**Existing enforcement**: ForgetGuard postponement-language rule (deny) catches avoidance keywords but cannot distinguish avoidance from scheduling (known false-positive source).

**Gap**: AI disclosure in outbound content has NO enforcement. Overclaim detection (claiming L4 SHIPPED without live evidence) is partially covered by receipt validation but not systematically.

### Category 7: OPERATIONAL HYGIENE
**Definition**: Rules governing infrastructure discipline, boot protocol, and process integrity.

| Feedback File | Rule Summary |
|---|---|
| `feedback_boot_no_pipe.md` | Run governance_boot.sh directly, no pipes |

**Existing enforcement**: `governance_boot.sh` validates 5 E2E constraints. Session watchdog monitors health signals.

**Gap**: Minimal. Low priority for additional enforcement.

---

## 2.5 Module-Ownership Classification

Board directive (2026-04-18): Y*gov structurally divides governance into two modules --
"乱做事 deny" (Enforce/Boundary) and "该做的不做 nag" (OmissionEngine). Every behavioral rule
must be classified into exactly one of three module-ownership buckets.

**Bucket definitions**:
- **PURE ENFORCE (E)**: Caught at-attempt via deny decision. No "silence = violation" semantics. Enforced in `ystar/adapters/boundary_enforcer.py` or `ystar/adapters/hooks/stop_hook.py`. Owner: Leo Chen (eng-kernel), Ryan Park (eng-platform).
- **PURE OMISSION (O)**: Caught post-facto as missing required action. Enforced in `ystar/governance/omission_engine.py` via ObligationTrigger framework. Owner: Maya Patel (eng-governance).
- **HYBRID (H)**: Rule has both attempt-time deny AND post-turn must-do check. Requires coordination between Leo/Ryan (Enforce) and Maya (Omission).

### Industry Precedent for Module Separation

**NeMo Guardrails input-rail vs output-rail (NVIDIA, 2023)**: NeMo separates `input rails` (pre-LLM deny) from `output rails` (post-LLM scan). Our Enforce module maps to input rails, Stop hook to output rails. Omission has no NeMo equivalent -- NeMo cannot detect "what the LLM failed to do." Y*gov's structural advantage.
Reference: https://github.com/NVIDIA/NeMo-Guardrails

**OPA deny vs must-have policy patterns (CNCF, 2018+)**: OPA Rego distinguishes `deny` rules from `violation` rules in Gatekeeper. `deny` = PURE ENFORCE. `violation` (missing required property) = PURE OMISSION. `warn` = HYBRID.
Reference: https://www.openpolicyagent.org/docs/latest/policy-language/#rules

### Classification Table

| # | feedback_file | rule_summary | module | rationale |
|---|---|---|---|---|
| 1 | `feedback_aiden_authority_no_questions.md` | No choice questions | **H** | Deny at output + must-do to self-correct |
| 2 | `feedback_subagent_no_choice_question.md` | Iron Rule 0 to sub-agents | **E** | Dispatch-time prompt scan |
| 3 | `feedback_ceo_reply_must_be_5tuple.md` | 5-tuple structured replies | **O** | Post-turn must-do |
| 4 | `feedback_no_consultant_time_scales.md` | No consultant time units | **E** | Stop hook output scan |
| 5 | `feedback_methodology_no_human_time_grain.md` | Strip human cadence | **E** | Stop hook output scan |
| 6 | `feedback_status_maturity_taxonomy.md` | L0-L5 tag required | **O** | Absence = omission |
| 7 | `feedback_address_laoda.md` | Addressing convention | **E** | Stop hook regex |
| 8 | `feedback_restart_quietude.md` | Post-boot one line | **E** | Stop hook warn |
| 9 | `feedback_close_stub_trigger.md` | No EOD stub online | **E** | PreToolUse deny |
| 10 | `feedback_board_shell_marker.md` | Shell marker format | **E** | Stop hook scan |
| 11 | `feedback_article11_framing.md` | Article 11 framing | **E** | Stop hook scan |
| 12 | `feedback_god_view_before_build.md` | Glob+Grep before build | **O** | Post-facto must-do |
| 13 | `feedback_ceo_ecosystem_view_required.md` | Ecosystem map first | **O** | Post-facto must-do |
| 14 | `feedback_testing_is_ceo_scope.md` | Testing is CEO scope | **E** | Identity boundary |
| 15 | `feedback_no_postpone_immediate_activation.md` | Changes immediate | **E** | Stop hook + ForgetGuard |
| 16 | `feedback_cieu_5tuple_task_method.md` | 5-tuple task method | **O** | Task-start triggers must-do |
| 17 | `feedback_action_model_3component.md` | 3-component dispatch | **H** | Payload deny + activation verify |
| 18 | `feedback_dispatch_via_cto.md` | Work via CTO | **E** | PreToolUse deny (LIVE) |
| 19 | `feedback_use_whiteboard_not_direct_spawn.md` | Use dispatch_board | **E** | PreToolUse deny |
| 20 | `feedback_taskcard_not_dispatch.md` | Task card needs Agent call | **O** | Write triggers must-do |
| 21 | `feedback_explicit_git_op_prohibition.md` | Git-op in spawn prompt | **E** | PreToolUse deny |
| 22 | `feedback_hi_agent_campaign_mechanism.md` | BOOT CONTEXT required | **E** | PreToolUse deny |
| 23 | `feedback_no_hollow_dispatch_promise.md` | No hollow promises | **O** | Must-do for Agent call |
| 24 | `feedback_cto_subagent_cannot_async_orchestrate.md` | CDP limitation | **E** | Informational |
| 25 | `feedback_subagent_receipt_empirical_verify.md` | Verify artifacts | **O** | Verification must-do |
| 26 | `feedback_cmo_12layer_rt_loop.md` | 12-layer completion | **O** | Content must-do |
| 27 | `feedback_no_static_image_for_video.md` | Real dynamic video | **E** | PreToolUse deny |
| 28 | `feedback_rt1_0________lesson_default_is_production_mode.md` | Production mode | **E** | Informational |
| 29 | `feedback_rt1_0________lesson_production_mode_writes_to_real_m.md` | Real MEMORY writes | **E** | Informational |
| 30 | `feedback_team_enforce_asymmetry.md` | Smoke-test gates | **O** | Post-deploy must-do |
| 31 | `feedback_default_agent_is_ceo.md` | Default = CEO | **E** | Already implemented |
| 32 | `feedback_cto_owns_technical_modeling.md` | CTO scope | **O** | Delegation must-do |
| 33 | `feedback_daemon_cache_workaround.md` | Daemon cache | **E** | Operational |
| 34 | `feedback_self_heal_via_daemon_window.md` | Self-heal drift | **E** | Operational |
| 35 | `feedback_subagent_registry_boot_only.md` | Boot-only reload | **E** | Informational |
| 36 | `feedback_no_clock_out.md` | Never clock out | **E** | Stop hook + ForgetGuard |
| 37 | `feedback_ai_disclosure_mandatory.md` | AI disclosure | **E** | PreToolUse deny |
| 38 | `feedback_scenario_c_is_real_usp.md` | No overclaim | **E** | Stop hook warn |
| 39 | `feedback_postpone_vs_schedule_distinction.md` | Postpone vs schedule | **E** | ForgetGuard refinement |
| 40 | `feedback_break_glass_disable_project_hook.md` | Break-glass | **E** | Informational |
| 41 | `feedback_boot_no_pipe.md` | No pipe after boot | **E** | PreToolUse deny |

### Summary Counts

| Module | Count | Key Examples |
|---|---|---|
| **PURE ENFORCE (E)** | 28 | Choice question deny, git-op prohibition, AI disclosure, boot-no-pipe |
| **PURE OMISSION (O)** | 10 | Receipt verification, god-view-before-build, 5-tuple, hollow dispatch promise |
| **HYBRID (H)** | 3 | Choice question (deny + correction), 3-component dispatch |

---

## 2.6 Existing Module Capability Audit

Empirical audit of Y*gov source code (2026-04-18).

### Enforce Module
**LIVE**: PreToolUse deny/warn, write boundary, tool restriction, immutable paths, 9 behavior rules, Bash write extraction, CROBA injection.
**NOT YET**: Agent prompt payload scanning, tool-call-history state file.

### Omission Module
**LIVE**: Event-driven obligations, ObligationTrigger framework, time-based violation detection, soft/hard overdue, escalation, CIEU integration, restoration/cancellation, REDIRECT tracking (ARCH-11b), action-promise enforcement (ARCH-11c), live-reload scan.
**NOT YET**: Custom behavioral types (need OmissionType enum extension), Stop-to-Omission bridge.

### Stop Hook
**LIVE**: K9-RT warning injection, receipt validation, file path extraction.
**NOT YET**: Behavioral pattern scanning, post-reply CIEU behavioral events.

### Capability Gap Summary

| Need | Module | Status |
|---|---|---|
| Deny at attempt | Enforce (PreToolUse) | LIVE |
| Scan output text | Enforce (Stop hook) | LIVE infra, new detectors needed |
| Detect missing actions after N turns | Omission (scan) | LIVE infra, new types needed |
| Agent prompt payload scan | Enforce | NOT YET (Phase 1) |
| Post-reply to obligation creation | Hybrid | NOT YET (Phase 3) |

---

## 3. Enforcement Mechanism Matrix (Module-Ownership Amended)

| Category | Enforcement Point | Module | Engineer | Mechanism |
|---|---|---|---|---|
| **1. Pre-Output** | Stop hook reply scan | **Enforce** | Ryan Park | 4 new detectors: 5-tuple, L-tag, time-scale, addressing. HYBRID choice-question additionally creates omission (Phase 3). |
| **2. Pre-Execution** | Omission post-facto | **Omission** | Maya Patel | ObligationTrigger: Write for new file triggers ECOSYSTEM_SCAN_REQUIRED. Fulfilled by Glob/Grep evidence. |
| **3. Dispatch** | PreToolUse deny | **Enforce** | Leo Chen | Extend _check_behavior_rules(): scan prompt for git-op prohibition + BOOT CONTEXT. |
| **4. Receipt/Close** | Omission post-facto | **Omission** | Maya Patel | VERIFY_SUBAGENT_RECEIPT on Agent return. Verification tool call within 3 turns. |
| **5. Delegation** | Omission post-facto | **Omission** | Maya Patel | CEO formal-method content triggers DELEGATE_TO_CTO. 3/session = escalate. |
| **6. Honesty** | PreToolUse deny | **Enforce** | Leo Chen | Write to content/marketing/sales without AI disclosure = deny. |
| **7. Hygiene** | None additional | N/A | N/A | Existing boot + watchdog sufficient. |

---

## 4. Industry Precedent Scan

### 4.1 Constitutional AI (Anthropic, 2022)

**Reference**: Bai et al., "Constitutional AI: Harmlessness from AI Feedback," arXiv:2212.08073.

Constitutional AI embeds behavioral principles as training-time constraints. Our feedback memories ARE the constitution. The difference: CAI bakes rules into weights (pre-training); ARCH-17 enforces at runtime (hooks). Runtime enforcement is the only option when you cannot retrain the model.

**Applicable pattern**: The "critique then revise" loop maps to our Stop hook (post-emission scan) + CIEU event (critique record) + next-turn self-correction (revision). Stop hook should emit "suggested correction" text, mirroring the CAI revision step.

### 4.2 Guardrails AI / NeMo Guardrails (NVIDIA, 2023)

**Reference**: NVIDIA NeMo Guardrails, https://github.com/NVIDIA/NeMo-Guardrails, 2023.

Architecture: `input rails -> LLM -> output rails -> action rails`. Maps to our hooks: PreToolUse = input rail, Stop hook = output rail, OmissionEngine = missing "must-do" rail. NeMo's "canonical form" intermediate representation should inform our evolution from regex to semantic-level intent classifiers.

### 4.3 Open Policy Agent (OPA) / Rego (CNCF, 2018+)

**Reference**: OPA documentation, https://www.openpolicyagent.org/docs/latest/

Key insight: **policy-as-data separation**. Behavioral rules should be declared in YAML (`behavioral_rules.yaml`), not hardcoded in hook Python scripts. OPA's `allow/deny/undecided` three-valued logic maps well -- most behavioral rules should default to `undecided` (allow with CIEU audit trail) rather than `deny`.

### 4.4 Langfuse Eval / Tracing (2023+)

**Reference**: Langfuse documentation, https://langfuse.com/docs/scores/model-based-evals

Our Stop hook is architecturally identical to a Langfuse eval. Missing piece: structured scoring -- each behavioral violation should produce a numeric severity score feeding into an aggregate "behavioral health" metric alongside AC (Agent Capability).

### 4.5 LLM-as-Judge (Various, 2024+)

**Reference**: Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena," NeurIPS 2023.

Phase 3 only. For ambiguous cases where regex produces >20% false positive rate. Call local Gemma via Ollama, capped at 1 call per 5 minutes.

---

## 5. Prioritized Implementation Plan (Module-Aligned Phases)

Phases align to module boundaries per Board directive. Phase 1 = Enforce-only (lowest risk). Phase 2 = Omission-only. Phase 3 = Hybrid.

### Phase 1: Enforce Module Only (lowest risk)

**Module**: boundary_enforcer.py, stop_hook.py
**Engineers**: Leo Chen, Ryan Park

#### P1-A: Dispatch Payload Integrity Gate (PURE ENFORCE)
Rules #2,#18,#19,#21,#22. Extend _check_behavior_rules() for Agent tool. Scan prompt for git-op prohibition (deny), BOOT CONTEXT (deny), scope guard (warn). Assignee: Leo, 10-15 tool_uses.

#### P1-B: Pre-Output Quality Scan (PURE ENFORCE)
Rules #4,#5,#7,#8,#10,#11,#15,#36,#38. Extend stop_hook.py: time-scale, addressing, restart quietude, clock-out detectors. All WARN severity. Assignee: Ryan, 12-18 tool_uses.

#### P1-C: Honesty Gate (PURE ENFORCE)
Rule #37. Write to content/marketing/sales without AI disclosure marker = deny. Assignee: Leo, 5-8 tool_uses.

#### P1-D: Boot-No-Pipe Gate (PURE ENFORCE)
Rule #41. Bash with governance_boot.sh + pipe = deny. Assignee: Ryan, 3-5 tool_uses.

### Phase 2: Omission Module Only

**Module**: omission_engine.py, omission_models.py, obligation_triggers.py
**Engineer**: Maya Patel

#### P2-A: Receipt Verification (PURE OMISSION)
Rule #25. New OmissionType VERIFY_SUBAGENT_RECEIPT. ObligationTrigger on Agent return. 3-turn deadline. Assignee: Maya, 12-18 tool_uses.

#### P2-B: God View / Ecosystem Scan (PURE OMISSION)
Rules #12,#13. New OmissionType ECOSYSTEM_SCAN_REQUIRED. Trigger on Write to new scripts/*.py or ystar/**/*.py. Fulfilled by Glob+Grep evidence. Assignee: Maya, 10-15 tool_uses.

#### P2-C: Hollow Promise Detection (PURE OMISSION)
Rules #20,#23. New OmissionType DISPATCH_PROMISE_UNFULFILLED. Write to .claude/tasks/ triggers need for Agent call within 5 turns. Assignee: Maya, 8-12 tool_uses.

#### P2-D: 5-Tuple Method (PURE OMISSION)
Rules #3,#6,#16. New OmissionType STRUCTURED_REPLY_REQUIRED. Board message triggers need for 5-tuple reply. Assignee: Maya, 8-10 tool_uses.

#### P2-E: Delegation Boundary (PURE OMISSION)
Rule #32. New OmissionType DELEGATE_TO_CTO. CEO formal-method content triggers delegation need. 3/session = escalate. Assignee: Maya, 6-8 tool_uses.

### Phase 3: Hybrid Rules (both modules)

**Engineers**: Leo + Maya + Ryan. Requires Stop-to-Omission bridge.

#### P3-A: Choice Question Full Enforcement (HYBRID)
Rule #1. Enforce (LIVE): ForgetGuard + Stop hook. Omission (NEW): SELF_CORRECT_CHOICE_QUESTION within 1 turn. Ryan + Maya, 8-10 tool_uses.

#### P3-B: 3-Component Dispatch (HYBRID)
Rule #17. Enforce: payload scan. Omission: K9+AC activation tracking. Leo + Maya, 10-12 tool_uses.

#### P3-C: Semantic Upgrade (cross-cutting)
Replace highest-FP regex with local Gemma classifier.

---

## 6. Self-Reference Safety

All behavioral enforcement rules apply to ALL agents, not just CEO. Board explicit directive: "all team members' behavioral rules."

### Agent Scope Matrix

| Rule | CEO | CTO | Engineers | C-Suite |
|---|---|---|---|---|
| No choice questions | YES | YES | YES | YES |
| 5-tuple structured replies | YES (to Board) | YES (to CEO) | YES (to CTO/CEO) | YES (to CEO) |
| L-tag on status reports | YES | YES | YES | YES |
| God view before build | YES | YES (builds arch) | YES (creates files) | N/A |
| Dispatch payload integrity | YES (dispatches) | YES (dispatches) | N/A (receivers) | N/A |
| Receipt verification | YES (receives receipts) | YES (receives eng receipts) | N/A | N/A |
| AI disclosure | YES | YES | YES | YES |
| Git-op prohibition | N/A | N/A | YES (enforced ON them) | N/A |
| No procrastination language | YES | YES | YES | YES |

### CTO-Specific Rules
- CTO specs missing `## Formal Definitions` + `## Mathematical Model` sections: ForgetGuard `spec_missing_formal_section` (needs implementation)
- CTO must proactively install tools/skills without CEO dispatch

### Implementation Note
Hook scripts determine active agent from `.ystar_active_agent`. All behavioral rules must check this value and apply correct agent-scope filter via lookup table, not per-rule hardcoded checks.

---

## 7. Failure Mode Analysis

### F1: Rule fires but agent cannot comply (lock-death risk)
- State file `/tmp/ystar_pretool_state.json` append-only, last 50 tool calls. On corruption: fail-open + CIEU event.
- All DENY decisions include exact remediation steps.
- 3 consecutive denies on same target within 5 minutes: auto-downgrade to warn-only.
- Break-glass: Board disables via `jq '.hooks.PreToolUse=[]' .claude/settings.json`.

### F2: Rule fires with false positive (crying wolf)
- Phase 1-2 rules default to WARN except: choice questions, AI disclosure, git-op prohibition (DENY).
- `false_positive_rate` field per rule. Auto-demote to audit-only if FP >30% after 100 firings.
- Agent self-reports FP via `# FP: <rule_name>` comment; Stop hook records for rate calculation.

### F3: Enforcement creates perverse incentives (gaming)
- Phase 2: God View gate checks Glob results non-empty AND Read/Grep followed on result path.
- K9 audit: sample 5 random gate-pass instances per rule, check substantive compliance.

### F4: Behavioral + structural enforcement cascade (compound deny)
- Structural gates fire FIRST. If structural denies, behavioral gates skip (short-circuit).
- Maximum 1 deny message per tool call. Priority indicators: `[STRUCTURAL]` vs `[BEHAVIORAL]`.

### F5: Hook process crashes (silent failure)
- Behavioral engine: stdlib-only (`re`, `json`, `os`, `sqlite3`). Zero Y*gov import dependency.
- Session watchdog pings engine health every 30s. No response: `BEHAVIORAL_ENGINE_DOWN` + auto-restart.
- Boot smoke test: governance_boot.sh fires deliberate violation, verifies deny, cleans up.

### F6: Sub-agent has no behavioral enforcement
- Enforced at TWO parent-context points: dispatch-time payload scan + receipt-time verification.
- Sub-agents do NOT run behavioral hooks internally (Claude Code limitation).
- Receipt verification obligation (P1-C) ensures parent-context validation.

---

## 8. Behavioral Rule Schema

```yaml
# Schema for governance/behavioral_rules.yaml
rules:
  - name: string           # unique identifier
    category: enum          # pre_output | pre_execution | dispatch | receipt_close |
                            # delegation_identity | honesty | operational
    enforcement_point: enum # pre_tool_hook | stop_hook | omission | cieu_event |
                            # dispatch_broker
    severity: enum          # deny | warn | audit
    agent_scope: list       # [ceo, cto, eng-kernel, eng-governance, eng-platform,
                            #  eng-domains, cmo, cso, cfo, secretary]
    pattern: string         # regex or heuristic identifier
    pattern_type: enum      # regex | tool_sequence | content_scan | metadata_check
    message: string         # remediation message shown on fire
    evidence_file: string   # feedback memory file documenting the gap
    false_positive_rate: float  # tracked, auto-demote if >0.30
    created_at: datetime
    dry_run_until: datetime | null
    escalation_threshold: int | null  # N fires per session before auto-escalation
```

Extends ForgetGuard schema with: `category`, `enforcement_point`, `agent_scope`, `pattern_type`, `evidence_file`, `false_positive_rate`, `escalation_threshold`.

---

## 9. Formal Definitions

Let B = set of all behavioral rules {b_1, ..., b_n}.
Let A = set of all agent steps (tool calls + text emissions).
Let S = session state (tool call history, active agent, CIEU events).

**Enforcement predicate**:
```
enforce(b, a, s) = 
  DENY   if severity(b) = deny AND match(pattern(b), a, s) AND agent(s) in scope(b)
  WARN   if severity(b) = warn AND match(pattern(b), a, s) AND agent(s) in scope(b)  
  AUDIT  if severity(b) = audit AND match(pattern(b), a, s) AND agent(s) in scope(b)
  ALLOW  otherwise
```

**Short-circuit rule** (F4 mitigation):
```
For step a, if exists structural_rule r such that enforce(r, a, s) = DENY:
  skip all behavioral rules for a
  return DENY(r)
```

**Escalation predicate**:
```
escalate(b, s) = TRUE iff count({a in session(s) | enforce(b, a, s) = WARN}) >= threshold(b)
```

**Fail-open invariant**:
```
For all b in B, a in A, s in S:
  if state_corrupt(s) then enforce(b, a, s) = ALLOW AND emit(BEHAVIORAL_GATE_STATE_CORRUPT)
```

## 10. Mathematical Model

### Behavioral Health Score

Define BH(t) = behavioral health at session time t:

```
BH(t) = 1 - (sum over b in B of w(b) * v(b, t)) / (sum over b in B of w(b))
```

Where:
- w(b) = weight of rule b (deny=3, warn=2, audit=1)
- v(b, t) = violation count of rule b in window [t-W, t], capped at 1
- W = sliding window of last 20 tool calls

BH(t) ranges [0, 1]. Thresholds:
- BH >= 0.8: healthy (green)
- 0.5 <= BH < 0.8: degrading (yellow, emit BEHAVIORAL_HEALTH_DEGRADED)
- BH < 0.5: critical (red, emit BEHAVIORAL_HEALTH_CRITICAL, notify Board)

Combined health = 0.5 * AC + 0.5 * BH (integrates with session_watchdog.py AC score).

### False Positive Adaptation

```
FP_rate(b, t) = FP_count(b, [0, t]) / total_fires(b, [0, t])
```

Auto-demotion when FP_rate > 0.30 after min 10 fires:
```
severity(b) <- max(severity(b) - 1, audit)
emit(BEHAVIORAL_RULE_DEMOTED, {rule: b, fp_rate: FP_rate(b, t)})
```

---

## 11. Implementation Dependencies

### Files to Create (Phase 1)
1. `governance/behavioral_rules.yaml` -- rule declarations (Leo)
2. `ystar/governance/behavioral_engine.py` -- rule evaluation engine, stdlib-only (Leo)
3. Extensions to `scripts/hook_wrapper.py` -- pre-execution gate (Ryan)
4. Extensions to `scripts/hook_pretool_agent_dispatch.py` -- dispatch payload scan (Maya)
5. Extensions to `scripts/hook_stop_reply_scan.py` -- 4 new post-output detectors (Maya)
6. New omission type in `ystar/governance/omission_engine.py` -- receipt verification (Leo)
7. State tracker `/tmp/ystar_pretool_state.json` -- tool call history (Ryan)
8. Tests: `tests/governance/test_behavioral_engine.py` (all)

### Files to Modify (Phase 1)
1. `scripts/governance_boot.sh` -- add behavioral engine smoke test
2. `scripts/session_watchdog.py` -- integrate BH score
3. `ystar/governance/forget_guard_rules.yaml` -- add `coordinator_hollow_dispatch_promise` rule

### Cross-Repo Dependencies
- `Y-star-gov/ystar/governance/omission_engine.py` -- new obligation type
- `Y-star-gov/ystar/governance/forget_guard.py` -- new rule loading
- No K9Audit dependencies (read-only repo)

---

## 12. Shelf-Activation: Knowledge Inventory and Formal Model

*(Merged from shelf-activation spec, 2026-04-18)*

### 14.1 CEO Wisdom/Cognitive Files Inventory (Class B)

| Cat | Subdirectory | Count | Function | Key Files |
|-----|-------------|-------|----------|-----------|
| 8 | wisdom/meta/ | 24 | 6D identity, cognitive architecture, field theory | 6d_cognitive_architecture, aiden_laws_hierarchy, global_workspace_architecture, building_aiden, zhixing_heyi, field_vs_structure_duality, courage_generalized, autonomous_loop_algorithm |
| 9 | wisdom/paradigms/ | 7 | Meta-lessons from past failures | mechanism_over_discipline, identification_is_not_completion, whitelist_over_blacklist, extend_not_build, system5_not_operations, auditor_independence, hook_output_format_lesson |
| 10 | wisdom/self_knowledge/ | 8 | Constitutional CEO identity invariants | absolute_honesty_to_board, peak_state_vs_deformation, reactive_default, three_level_drive, z_axis_self_initiation, valve_discipline, fear_of_external, blind_spot_consensus_assumption |
| 11 | strategy/ | 7 | CEO strategic thinking artifacts | ceo_operating_manual_v0.1, day1_after_pip_install, enforce_inventory_20260416, mission_function_and_ceo_philosophy_20260416, phase1_foundation_proposal_20260416, STRAT-001_governance_moat_vs_bounty_speed_20260416, verification_service_spec |
| 12 | lessons/ | 16 | Failure-mode knowledge, post-mortems | autonomy_degradation_root_cause, governance_self_deadlock, posted_not_executed_hallucination, performance_misdiagnosis_daemon_vs_cache, industry_precedent_scan_first |

**Total**: 30 behavioral memories (Categories 1-7) + 62 wisdom files (Categories 8-12) = **92 governance-relevant knowledge units**.

### 14.2 Shelf-Activation Formal Model

Let K = {k_1, k_2, ..., k_92} be the set of all knowledge units.

Each k_i has:
- **topic_vector(k_i)**: semantic embedding of file content
- **trigger_set(k_i)**: conditions under which k_i is relevant
- **decay(k_i, t)**: relevance decay over session time t
- **activation_count(k_i)**: times k_i surfaced in a decision context

**Shelf ratio** S(t):
```
S(t) = |{k_i : activation_count(k_i) == 0}| / |K|
```

Current: S(t) ~ 0.95. Target: S(t) <= 0.30 for sessions > 10 tool_uses.

**Relevance match** R(k_i, ctx):
```
R(k_i, ctx) = cosine(embed(k_i), embed(ctx))
```

k_i **should fire** when R(k_i, ctx) >= 0.65. Shelf activation failure = should have fired but did not.

### 14.3 Retrieval as Attention (Global Workspace Theory)

Model decisions as a Global Workspace (Baars 1988) with N knowledge processes competing for the context-window spotlight:

```
For each decision point d_j:
  candidates = {k_i : R(k_i, ctx(d_j)) >= 0.65}
  top_k = argsort(R, descending)[:MAX_INJECT]
  inject(top_k) and broadcast to all processes
```

Maps to CEO's `global_workspace_architecture.md`: 5 parallel processes, winner broadcast to all.

### 14.4 Hebbian Reinforcement

Co-activated units strengthen:
```
weight(k_i, k_j) += alpha * activation(k_i) * activation(k_j)
```

Per `personal_neural_network_concept.md`: fire together, wire together.

### 14.5 Decay and Consolidation

```
relevance_boost(k_i, t) = base * exp(-lambda * sessions_since_last_activation)
```

If activation_count > theta over N sessions, permanent boost (long-term memory).

---

## 13. Shelf-Activation: Three-Layer Architecture

```
Layer 3: IDENTITY INVARIANTS (always-on, constitutional)
  Source: self_knowledge/ + aiden_laws_hierarchy
  Mechanism: governance_boot.sh injects at session start
  Analogy: CPU microcode -- never paged out

Layer 2: PARADIGM RAILS (trigger-activated, retrieval-based)
  Source: paradigms/ + lessons/ + high-relevance meta/
  Mechanism: pre-output hook RAG query, top-N injection
  Analogy: L2 cache -- fast on context match

Layer 1: STRATEGIC CONTEXT (on-demand, search-based)
  Source: strategy/ + remaining meta/
  Mechanism: autonomous loop pulls during idle
  Analogy: Main memory -- available not always cached
```

### WisdomIndex (built at boot)

```python
class WisdomIndex:
    def __init__(self, knowledge_dir):
        self.units = self._scan(knowledge_dir)
        self.embeddings = self._embed(self.units)
        self.activation_log = {}

    def query(self, context, top_k=3):
        scores = {k: cosine(embed(context), self.embeddings[k]) for k in self.units}
        return sorted(scores, key=scores.get, reverse=True)[:top_k]

    def shelf_ratio(self):
        activated = sum(1 for v in self.activation_log.values() if v > 0)
        return 1.0 - (activated / len(self.units))
```

### Pre-Output Wisdom Injector

```python
def wisdom_inject(reply_draft, context):
    relevant = wisdom_index.query(context, top_k=3)
    for k in relevant:
        wisdom_index.record_activation(k.id)
        emit_cieu("WISDOM_ACTIVATED", {"unit": k.id, "relevance": k.score})
    injection = [f"[WISDOM:{k.id}] {k.summary}" for k in relevant]
    return f"<!-- {injection} -->\n{reply_draft}"
```

### Paradigm Violation Detector

| Paradigm | Anti-pattern signals | Remedy |
|----------|---------------------|--------|
| identification_is_not_completion | "found X" without same-turn action | Must terminate in Action/Dispatch/Postpone-with-reason/WontFix |
| mechanism_over_discipline | "remember rule" / "next time careful" | Write hook/script not MEMORY rule |
| extend_not_build | "create new module" without precheck | Precheck 4 repos first |
| system5_not_operations | "I will manually" / "CEO writes code" | Dispatch to CTO/engineer |
| reactive_default | "waiting for Board" / "waiting for instructions" | Pull from ADE action queue |
| peak_state_deformation | "hurry to prove" / "rush to finish" | PAUSE -- feedback = information not attack |

6 paradigms, 16 total patterns. Emits CIEU `PARADIGM_VIOLATION_DETECTED`.

### Shelf Health Monitor

Every 15 tool_uses: compute shelf_ratio, emit `SHELF_HEALTH_CHECK`. If > 0.50, force-surface 3 cold units as thought prompts.

---

## 14. Shelf-Activation: Five Channels

### Channel 1: Boot-Time Constitutional Injection (Layer 3)

**Files**: absolute_honesty_to_board, aiden_laws_hierarchy, peak_state_vs_deformation, three_level_drive, reactive_default

**Mechanism**: governance_boot.sh reads 5 files into `.ystar_session_identity.json`. Always in session context.

**CIEU**: `IDENTITY_BLOCK_LOADED`. Missing = health score 0.

**Guarantee**: 100% activation by construction.

### Channel 2: Pre-Decision RAG Injection (Layer 2)

**Trigger**: tool_use in reply, reply > 200 tokens, or dispatch keywords.

**Mechanism**: pre-output hook queries WisdomIndex, injects top-3 one-line summaries.

**CIEU**: `WISDOM_ACTIVATED` per unit. Target: >= 70% relevant-context activation.

**ARCH-18 dependency**: When WisdomIndex query returns low-relevance results (all scores < 0.65), fall back to ARCH-18's failure library query (`cieu_brain_context.py`) to surface historically relevant CIEU patterns instead.

### Channel 3: Anti-Pattern Violation Detection (Layer 2)

**Mechanism**: regex scan of reply against PARADIGM_ANTI_PATTERNS registry (6 paradigms, 16 patterns). On match, inject remedy + `[PARADIGM_VIOLATION]` tag.

**CIEU**: `PARADIGM_VIOLATION_DETECTED`. Target: >= 90% detection rate.

### Channel 4: Periodic Cold-Unit Resurfacing (Layer 1)

**Mechanism**: every 15 tool_uses, if shelf_ratio > 0.50, sample 3 cold units as thought prompts.

**CIEU**: `SHELF_RESURFACING`. Target: shelf_ratio <= 0.30 by session end (>30 tool_uses).

### Channel 5: Decision-Gate Forced Read (Layer 3)

| Decision Type | Mandatory Reads | Gate |
|--------------|----------------|------|
| Dispatch sub-agent | system5_not_operations, dispatch_via_cto | Pre-dispatch hook |
| Create new component | extend_not_build, god_view_before_build | PreToolUse on new-path Write |
| Commit code | hook_output_format_lesson | Pre-commit hook |
| Reply to Board criticism | peak_state_vs_deformation, absolute_honesty | Pre-output on correction markers |
| Propose new agent/role | auditor_independence, ecosystem_view | Pre-dispatch on agent/role keywords |
| Close/complete task | identification_is_not_completion | Pre-output on done/shipped/completed |

**CIEU**: `DECISION_GATE_FIRED`. Target: 100% gate hit rate. No bypass.

**ARCH-18 dependency**: Decision gates for dispatch and close/complete should additionally query ARCH-18's per-brain context to inject relevant historical failure patterns.

### Embedding Infrastructure

Model: Gemma 2B via Ollama (localhost:11434). Fallback: TF-IDF/sklearn.
Index: `.ystar_wisdom_index.json`, rebuilt when source files change.
Latency: < 200ms per query.

### Integration Points

```
governance_boot.sh --> WisdomIndex build + Channel 1 identity load
hook_ceo_pre_output.py --> Channel 2 RAG + Channel 3 anti-pattern + Channel 5 gates
PostToolUse hook --> Channel 4 shelf health every 15 tool_uses
```

### Measurement Dashboard

| Metric | Target | Red Line |
|--------|--------|----------|
| shelf_ratio | <= 0.30 | > 0.70 |
| identity_loaded | 1.00 | < 1.00 |
| paradigm_activation | >= 0.70 | < 0.40 |
| violation_detection | >= 0.90 | < 0.60 |
| gate_hit_rate | 1.00 | < 1.00 |
| wisdom_diversity | >= 0.50 | < 0.20 |

### Board's Key Question Answered

> "How do we guarantee 6D Aiden files fire in at least X% of relevant decisions, measurable via CIEU?"

Channel 1: 100% for 5 identity files (by construction). Channel 5: 100% at high-stakes gates (by hook). Channel 3: ~90% anti-pattern detection (regex). Channel 2: ~70% contextual retrieval (embedding quality bound). Channel 4: shelf_ratio <= 0.30 (forced resurfacing).

Combined: >= 70% of 92 units surfaced per session (>30 tool_uses). Top-5 identity = 100%. 6 paradigm sets = 90%+. All measurable via CIEU counts, independently verifiable by K9.

---

## 15. Shelf-Activation: Implementation Phases

**Phase SA-1** (eng-platform): TF-IDF WisdomIndex + Channel 1 boot injection + CIEU events.
Accept: IDENTITY_BLOCK_LOADED fires; shelf_ratio computable.

**Phase SA-2** (eng-platform + eng-governance): Channel 3 anti-pattern + Channel 5 decision gates.
Accept: PARADIGM_VIOLATION_DETECTED on synthetic test; DECISION_GATE_FIRED before dispatch.

**Phase SA-3** (eng-kernel): Gemma embeddings + Channel 2 RAG + Channel 4 cold resurfacing + dashboard.
Accept: shelf_ratio <= 0.30; wisdom_activation_rate >= 0.70.
**ARCH-18 integration point**: Coordinate with ARCH-18 Phase 2 (Brain Context Generation) to share embedding infrastructure.

**Phase SA-4** (hardening): Hebbian cross-session weights, decay/consolidation, K9 audit integration.
Accept: activation patterns persist across sessions.

---

## 16. CEO Cognitive Architecture Mapping

| CEO Concept | Implementation |
|-------------|---------------|
| Global Workspace Theory | WisdomIndex competition + top-k broadcast |
| Personal Neural Network | Hebbian weights + spreading activation |
| Mechanism > Discipline | Hook enforcement not MEMORY rules |
| Field vs Structure duality | Wisdom = field, hooks = structure |
| Zhixing heyi | Must fire in behavior or not true knowledge |
| Identification != Completion | Anti-pattern prevents "discovered but not acted" |
| Autonomous Loop Algorithm | Channel 4 resurfacing during idle |
| Three-Level Drive | Channel 2 RAG pulls Level 3 mission knowledge |
| Peak State vs Deformation | Anti-pattern for stress deformation |
| Aiden Laws Hierarchy | Conflict resolution between wisdom files |
| Courage Generalized | Resurfacing: "Is this boundary real?" |
| Building Aiden | Shelf activation = cognitive architecture as infrastructure |

---

## 17. Non-Goals

1. **Not replacing ForgetGuard**: Behavioral rules extend ForgetGuard. ForgetGuard = text-pattern rules; behavioral engine = multi-signal rules (tool sequence, metadata, session state).
2. **Not training-time enforcement**: Cannot fine-tune Claude. All enforcement is runtime.
3. **Not blocking all behavioral violations**: Most rules are warn-level. Goal = audit trail + self-correction nudge.
4. **Not building a general-purpose policy engine**: Y*gov-specific. OPA/Rego patterns inform but we do not import OPA.
5. **Not LLM-as-judge in Phase 1**: Semantic classification via secondary LLM is Phase 3 only.

---

## 18. Success Metrics

| Metric | Baseline (pre-ARCH-17) | Target (post-Phase 1) |
|---|---|---|
| Board-caught behavioral regressions per session | ~4 (2026-04-18 data) | <=1 |
| Behavioral violations with CIEU audit trail | 0% (no detection) | >=80% produce CIEU event |
| False positive rate per rule | N/A | <20% after 50 firings |
| Lock-death incidents from behavioral gates | N/A | 0 (fail-open + 3-deny auto-downgrade) |
| BH score during normal operation | unmeasured | >=0.7 mean |
| Shelf ratio (wisdom files) | ~0.95 | <=0.30 (sessions >30 tool_uses) |
| Identity invariant load rate | unmeasured | 1.00 |
| Paradigm violation detection rate | unmeasured | >=0.90 |

---

## Appendix A: Full Wisdom File Inventory

**wisdom/meta/** (24): 17_meta_rules_from_practice, 6_philosophical_principles, 6d_cognitive_architecture, action_reflection_rhythm, aiden_laws_hierarchy, aiden_neural_network_subgoals, autonomous_loop_algorithm, blind_spot_check_20260417, building_aiden, capability_iteration_engine, ceo_workflow_enforcement_gap, courage_generalized, field_thought_experiments, field_vs_structure_duality, global_workspace_architecture, human_excellence_vs_ai_gap_analysis, persistence_is_architecture, personal_neural_network_concept, retrospective_sandbox_workflow, sandbox_16h_counterfactual_replay, self_as_software, self_vs_transcendence, u_action_workflow, zhixing_heyi

**wisdom/paradigms/** (7): auditor_independence, extend_not_build, hook_output_format_lesson, identification_is_not_completion, mechanism_over_discipline, system5_not_operations, whitelist_over_blacklist

**wisdom/self_knowledge/** (8): absolute_honesty_to_board, blind_spot_consensus_assumption, fear_of_external, peak_state_vs_deformation, reactive_default, three_level_drive, valve_discipline, z_axis_self_initiation

**strategy/** (7): ceo_operating_manual_v0.1, day1_after_pip_install, enforce_inventory_20260416, mission_function_and_ceo_philosophy_20260416, phase1_foundation_proposal_20260416, STRAT-001_governance_moat_vs_bounty_speed_20260416, verification_service_spec

**lessons/** (16): atomic_task_per_dispatch_2026_04_13, auto_codify_lessons, auto_codify_violations_2026_04_12, auto_memory_vs_ystar_governance_boundary_conflict, autonomy_degradation_root_cause_2026_04_13, ceo_write_scope_enforcement_2026_04_14, governance_self_deadlock_20260413, hard_constraint_completeness, industry_precedent_scan_first_20260418, innovation_preservation_guard_2026_04_13, performance_misdiagnosis_daemon_vs_cache_20260418, posted_not_executed_hallucination_20260418, public_x_engagement_policy_2026_04_13, session_2026_04_13_meta_drift, spec_to_impl_drift_20260413

---

*End of consolidated spec. Implementation dispatched via dispatch_board.json.*
