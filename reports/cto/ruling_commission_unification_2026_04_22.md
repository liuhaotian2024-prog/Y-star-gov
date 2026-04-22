# CTO Ruling: Commission Infrastructure Unification — 2026-04-22

**CZL-159 Header**
- Y*: Single commission engine (forget_guard) wired into hook_wrapper, all rules in one YAML, G-1..G-4 as YAML entries not new hooks
- Xt: 3-way fragmentation — 25 Python hardcoded in boundary_enforcer.py (LIVE), 32 YAML in forget_guard_rules.yaml (DEAD — hook_wrapper has 0 references), 4 YAML in scripts/behavior_gov_rules.yaml (duplicate, never integrated)
- U: 1 ruling + 3 dispatch cards + 3 OmissionEngine obligations
- Yt+1: unified commission pipeline where new governance rule = YAML entry, not code commit
- Rt+1: 0 when checkpoint echoed + 3 cards on board + 3 obligations in omission DB

---

## Part A — Unification Decision

### Canonical schema: forget_guard_rules.yaml schema 1.1

Rationale: forget_guard_rules.yaml has the most mature schema (schema_version 1.1) with:
- Typed triggers (tool list + conditions with path_match, content_contains, content_missing, active_agent_equals)
- Logic operators (AND/OR at both rule and condition level)
- Action vocabulary (warn/deny/audit)
- Recipe templates with variable substitution
- CIEU event emission per rule
- Severity classification
- Whitelist corpus references
- Validation blocks (python_validator, cieu_events_exist, incomplete_sequence)
- Status lifecycle (enabled/retired with metadata)

This schema subsumes everything behavior_gov_rules.yaml expresses.

### Engine to wire: forget_guard engine

The forget_guard evaluation engine in Y-star-gov's ystar.governance module must be imported into `scripts/hook_wrapper.py` and invoked on every PreToolUse event, after the existing boundary_enforcer check. The engine reads forget_guard_rules.yaml, evaluates conditions against the tool call context, and returns allow/warn/deny.

### behavior_gov_engine.py: DEPRECATED

`scripts/behavior_gov_engine.py` and `scripts/behavior_gov_rules.yaml` are deprecated effective this ruling. Their 4 handler types (DeadlineCheck, FrequencyCheck, StatePresenceCheck, ToolCountCheck) will be migrated into forget_guard_rules.yaml as schema 1.1 entries in Step 2 below. After migration, both files are deleted.

Migration mapping for the 4 behavior_gov_rules:
| behavior_gov_rules rule_id | forget_guard equivalent | Notes |
|---|---|---|
| omission_overdue_block | New FG rule with validation.type=python_validator calling omission deadline check | DeadlineCheck handler logic becomes a python_validator |
| goal_level_directive_untouched | New FG rule with validation.type=cieu_events_exist | FrequencyCheck maps to existing FG validation pattern |
| stop_after_short_session_moral_licensing | New FG rule with validation.type=python_validator | StatePresenceCheck maps to python_validator |
| skill_retrieval_not_invoked_before_new_build | New FG rule with validation.type=python_validator checking tool history | ToolCountCheck maps to python_validator |

---

## Part B — G-1..G-4 as forget_guard YAML Entries

These are NOT new hooks. They are YAML entries added to `governance/forget_guard_rules.yaml` conforming to schema 1.1. They will become LIVE only after Step 1 (forget_guard wired to hook_wrapper).

### G-1: Board-facing claim must have artifact reference

```yaml
- id: board_claim_needs_artifact
  enabled: true
  description: >
    Board-facing completion claim must reference a verifiable artifact
    (commit hash, file path, test output, grep result). Prevents hallucinated
    receipts. Board 2026-04-22 honesty guardrail.
  last_reviewed: '2026-04-22'
  reviewer: CTO
  trigger:
    tool:
    - Write
    - Edit
    logic: AND
    conditions:
    - type: path_match
      pattern: ^(reports/ceo/board|reports/ceo/.*brief|memory/session_handoff)
      context: file_path
    - type: content_contains
      keywords:
      - closed
      - done
      - shipped
      - completed
      - 处理
      - 完成
      - resolved
      - fixed
      - Rt+1=0
    - type: content_missing
      pattern: (commit [0-9a-f]{7}|[0-9a-f]{8,40}|pytest.*pass|grep.*\||ls -|wc -l|\.py|\.md|\.yaml)
  action: warn
  recipe: |
    Board-facing claim contains completion language but no artifact reference.

    Required: include at least one of:
    - commit hash (e.g. commit a1b2c3d)
    - file path (e.g. reports/cto/ruling_xyz.md)
    - test output (e.g. pytest 86 passed)
    - verification command output

    Without artifact reference, this claim is unverifiable.
    Ref: commission_infra_root_cause_2026_04_22.md G-1
  cieu_event: BOARD_CLAIM_NO_ARTIFACT
  severity: medium
```

### G-2: CEO claim emit CIEU audit event

```yaml
- id: ceo_claim_audit_event
  enabled: true
  description: >
    Every CEO claim to Board emits a CIEU audit event for tamper-evident
    record. Enables post-hoc verification of what was claimed vs reality.
    Board 2026-04-22 honesty guardrail.
  last_reviewed: '2026-04-22'
  reviewer: CTO
  trigger:
    tool:
    - Write
    - Edit
    logic: AND
    conditions:
    - type: active_agent_equals
      value: ceo
    - type: path_match
      pattern: ^(reports/ceo/board|reports/ceo/.*brief|memory/session_handoff)
      context: file_path
    - type: content_contains
      keywords:
      - closed
      - done
      - shipped
      - completed
      - 处理
      - 完成
      - Rt+1
  action: audit
  recipe: |
    CEO claim to Board detected. CIEU audit event emitted automatically.
    This creates tamper-evident record of the claim for post-hoc verification.
    No action required — this is informational.
    Ref: commission_infra_root_cause_2026_04_22.md G-2
  cieu_event: CEO_CLAIM_TO_BOARD
  severity: low
```

### G-3: Board directive auto-track (Omission side)

G-3 is an omission-side rule, not commission. It tracks Board directives that have not received progress events. This maps to the existing behavior_gov_rules `goal_level_directive_untouched` pattern. It belongs in the unified YAML but uses the omission validation type:

```yaml
- id: board_directive_auto_track
  enabled: true
  description: >
    Board directive (detected via UserPromptSubmit containing imperative
    keywords) auto-registers as OmissionEngine obligation with deadline.
    Fires on the detection event, not on tool calls. Board 2026-04-22.
  last_reviewed: '2026-04-22'
  reviewer: CTO
  trigger:
    event_source: cieu
    conditions:
    - type: event_type_equals
      value: USER_PROMPT_SUBMIT
    - type: content_contains
      keywords:
      - 告诉
      - 必须
      - deadline
      - P0
      - directive
      - 指令
      - immediately
      - 立刻
  action: audit
  recipe: |
    Board directive detected. Auto-registering OmissionEngine obligation.
    Actor: current active agent. Deadline: 7 days (default, adjustable by
    explicit deadline in directive text).
    Track via: python3 scripts/omission_status.py --entity DIRECTIVE-{hash}
    Ref: commission_infra_root_cause_2026_04_22.md G-3
  cieu_event: DIRECTIVE_POSTED
  severity: medium
```

### G-4: Reply pre-write verification reminder

```yaml
- id: reply_pre_write_verify
  enabled: true
  description: >
    Before writing to Board-facing paths, inject reminder to verify
    claims with tool_use evidence. Prevents write-before-verify pattern.
    Board 2026-04-22 honesty guardrail.
  last_reviewed: '2026-04-22'
  reviewer: CTO
  trigger:
    tool:
    - Write
    - Edit
    logic: AND
    conditions:
    - type: active_agent_equals
      value: ceo
    - type: path_match
      pattern: ^(reports/ceo/board|memory/session_handoff|reports/ceo/.*brief)
      context: file_path
  action: warn
  recipe: |
    Pre-write verification reminder for Board-facing output.

    Before finalizing this write, confirm:
    1. Every "done/shipped/closed" claim has a tool_use verify (ls, pytest, grep)
    2. Every commit reference is a real hash (not fabricated)
    3. Every test count matches actual pytest output from this session
    4. Rt+1 claim is backed by empirical delta, not impression

    This is a pre-write checkpoint, not a block.
    Ref: commission_infra_root_cause_2026_04_22.md G-4
  cieu_event: REPLY_PRE_WRITE_VERIFY
  severity: low
```

---

## Part C — Three Engineering Steps + Dispatch Cards

### Step 1: Wire forget_guard engine into hook_wrapper.py (Ryan Park, eng-platform)

**Dispatch card**: CZL-COMMISSION-UNIFY-STEP-1
**Actor**: Ryan Park (eng-platform)
**Deadline**: 2026-04-29 (7 days)
**Priority**: P0

**Scope**: `scripts/hook_wrapper.py`, `governance/forget_guard_rules.yaml`

**Spec**:
1. Import forget_guard evaluation engine from `ystar.governance` (or equivalent module that reads schema 1.1 YAML and evaluates rules against tool context)
2. In the PreToolUse handler of hook_wrapper.py, after existing boundary_enforcer checks, call `forget_guard.evaluate(tool_name, tool_input, agent_id, session_context)`
3. If any rule returns `deny` -> block tool call, return the rule's recipe as the block message, emit the rule's cieu_event
4. If any rule returns `warn` -> log CIEU event with the rule's cieu_event type, continue allowing the tool call
5. If any rule returns `audit` -> emit CIEU event silently, continue allowing the tool call
6. Handle import failures gracefully: if forget_guard engine cannot be imported, log a CIEU WARNING event and allow the tool call (fail-open, not fail-closed, to avoid lock-death)

**Acceptance criteria**:
- `grep -c "forget_guard" scripts/hook_wrapper.py` returns >= 3
- Live-fire test: deliberately trigger one of the 32 YAML rules (e.g. write a completion claim without L-tag to trigger `missing_l_tag`), verify CIEU event is emitted with correct event_type
- All existing boundary_enforcer checks still fire (no regression)
- `pytest tests/adapters/ -q` passes

### Step 2: Unify behavior_gov_rules.yaml into forget_guard_rules.yaml (Maya Patel, eng-governance)

**Dispatch card**: CZL-COMMISSION-UNIFY-STEP-2
**Actor**: Maya Patel (eng-governance)
**Deadline**: 2026-05-06 (14 days)
**Priority**: P1

**Scope**: `governance/forget_guard_rules.yaml`, `scripts/behavior_gov_rules.yaml`, `scripts/behavior_gov_engine.py`

**Spec**:
1. Migrate the 4 rules from `scripts/behavior_gov_rules.yaml` into `governance/forget_guard_rules.yaml` using schema 1.1 syntax (see Part A migration mapping table)
2. Add G-1, G-2, G-3, G-4 YAML entries from Part B above into `governance/forget_guard_rules.yaml`
3. After migration, add deprecation header to `scripts/behavior_gov_rules.yaml`: `# DEPRECATED: migrated to governance/forget_guard_rules.yaml — see ruling_commission_unification_2026_04_22.md`
4. Add deprecation header to `scripts/behavior_gov_engine.py`: same message
5. Verify: `wc -l governance/forget_guard_rules.yaml` shows growth by approximately 100-140 lines (4 migrated + 4 new G-rules)
6. Verify: forget_guard engine handles the new validation types (python_validator for DeadlineCheck/StatePresenceCheck/ToolCountCheck patterns)

**Acceptance criteria**:
- Single YAML file contains all commission + omission-detection rules (40+ rules total)
- `scripts/behavior_gov_rules.yaml` has deprecation header
- `scripts/behavior_gov_engine.py` has deprecation header
- Live-fire: trigger G-1 (write Board claim without artifact) -> verify warn + CIEU event

**Dependency**: Step 1 must be complete (forget_guard wired) before G-rules can fire.

### Step 3: Migrate boundary_enforcer.py Python rules to YAML (Maya + Ryan, joint)

**Dispatch card**: CZL-COMMISSION-UNIFY-STEP-3
**Actor**: Maya Patel + Ryan Park (joint)
**Deadline**: 2026-05-20 (28 days)
**Priority**: P2

**Scope**: `scripts/boundary_enforcer.py`, `governance/forget_guard_rules.yaml`, `tests/adapters/`

**Spec**:
1. Inventory all 25 `_check_*` functions in boundary_enforcer.py
2. For each function, determine if its logic is expressible as a forget_guard YAML rule (trigger + conditions + action + recipe)
3. If YAML-expressible: write the YAML entry, add pytest regression test, delete the Python function and its call site
4. If NOT YAML-expressible (requires custom Python logic like CIEU queries, complex state comparisons, multi-step validation): keep as Python, document why in a comment block at the function definition
5. Expected migration rate: 18-22 of 25 are YAML-expressible; 3-7 require Python
6. Post-migration: boundary_enforcer.py should be <= 800 lines (down from current ~2639)

**Acceptance criteria**:
- boundary_enforcer.py <= 800 lines
- All 25 original rules still fire (via YAML or residual Python)
- `pytest tests/adapters/ -q` passes with 0 failures
- Each migrated rule has a corresponding pytest test
- Remaining Python rules have inline documentation explaining why YAML migration is not feasible

**Dependency**: Steps 1 and 2 must be complete.

---

## Part D — Echo Checkpoints

After all three dispatch cards are posted and all three obligations are registered:

`[CHECKPOINT UNIFICATION] ruling + 3 cards + 3 obligations done`

Verification commands:
```bash
# Verify 3 cards on board
python3 scripts/dispatch_board.py pending

# Verify 3 obligations in omission DB
sqlite3 .ystar_cieu_omission.db "SELECT obligation_id, actor_id, status, notes FROM obligations WHERE obligation_id LIKE 'CZL-COMMISSION-UNIFY%';"
```

---

## Formal Definitions

Let R = set of all governance rules currently in production.
Let R_py = {r in R : r is hardcoded in boundary_enforcer.py} (|R_py| = 25)
Let R_fg = {r in R : r is in forget_guard_rules.yaml} (|R_fg| = 32, but DEAD)
Let R_bg = {r in R : r is in behavior_gov_rules.yaml} (|R_bg| = 4)
Let R_new = {G-1, G-2, G-3, G-4}

Pre-condition: R_fg intersection hook_wrapper.py = empty (dead code)
Post-condition Step 1: R_fg intersection hook_wrapper.py = R_fg (all 32 LIVE)
Post-condition Step 2: R_fg' = R_fg union R_bg union R_new, |R_fg'| >= 40; R_bg = deprecated
Post-condition Step 3: R_fg'' = R_fg' union migrate(R_py); |R_py_residual| <= 7; boundary_enforcer.py <= 800 LOC

Invariant (all steps): forall r in R, r fires on deliberate violation (testable via live-fire)

## Mathematical Model

Commission coverage C(t) = |{r in R : r is wired AND fires on violation}| / |R|

- C(t=now) = 25 / (25+32+4+4) = 25/65 = 0.385
- C(t=Step1) = (25+32) / 65 = 57/65 = 0.877
- C(t=Step2) = (25+32+4+4) / 65 = 65/65 = 1.0 (full coverage, but dual-engine)
- C(t=Step3) = 65/65 = 1.0 (single engine, YAML-first)

Risk: Step 3 is highest risk (refactoring 25 live Python functions). Mitigated by: incremental migration (one function at a time), regression tests per function, residual Python for complex rules.
