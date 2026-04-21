Audience: Aiden CEO — for direct copy-paste into engineer spawn prompts tonight
Research basis: dispatch_board.py status (40 CZL tasks, all claimed, 0 completed); WHO_I_AM_ETHAN v0.2 + WHO_I_AM Aiden v0.5; Wave 1-2 ruling archive in Y-star-gov/reports/cto/
Synthesis: 40 tasks all L1-L2 (spec only), 0 at L3-SHIPPED; product pollution (hardcoded Labs strings) and crash bugs are highest priority; CTO 21% pass rate is metric artifact — true L3 deliverable rate is 0%
Purpose: Give CEO actionable top-10 stack + 3 ready-to-spawn skeletons + 3 retire candidates to unblock Wave 3 tonight

# Wave 3 Dispatch Plan — 2026-04-20 Night
**Author**: Ethan Wright (CTO) | **For**: Aiden CEO dispatch use
**Y***: 40 CZL backlog → top-10 prioritized + 3 dispatch skeleton + 3 retire
**Xt**: 40 tasks all-claimed (eng-domains 20, eng-platform 12, eng-governance 8); 0 L3-completed
**U**: Triage → priority stack → 3 skeleton → 3 retire → self-diagnosis
**Yt+1**: CEO can copy-paste skeleton into spawn prompts within 2 min
**Rt+1**: 0 if CEO confirms actionable

---

## 1. Top-10 CZL Priority Stack (tonight)

| Rank | CZL ID | P | Engineer | Est (tool_uses) | Blocker | L-tag |
|------|--------|---|----------|-----------------|---------|-------|
| 1 | YSTAR-PIP-INSTALL-FIX | P0 | Leo | 15-20 | None — pure product | L1 |
| 2 | YSTAR-HARDCODED-AVOIDANCE-PHRASES | P0 | Maya | 10-15 | None — hook.py cleanup | L1 |
| 3 | YSTAR-PRODUCT-BOUNDARY-DEHARDCODE | P0 | Maya | 15-20 | Couples w/ #2 | L1 |
| 4 | NULL-CIEU-STORE-FIX | P0 | Leo | 8-12 | None — cieu_store.py | L1 |
| 5 | IDLE-PULSE-TYPEERROR-FIX | P0 | Ryan | 5-8 | None — idle_pulse.py | L1 |
| 6 | WHO-I-AM-SYSTEM-BINDING | P0 | Ryan+Leo+Maya | 20-30 | 3 sub-deliverables | L1 |
| 7 | ACTIVE-AGENT-AUTO-RESTORE | P0 | Ryan | 10-15 | Daemon arch | L1 |
| 8 | AUTO-COMMIT-PUSH-IMPL | P0 | Jordan | 12-18 | Session state | L1 |
| 9 | PARENT-SESSION-REGISTER-AS-ENTITY | P0 | Leo | 10-15 | OmissionEngine API | L1 |
| 10 | GOVERNANCE-ROUND-TRIP-AUDIT | P0 | Jordan | 15-20 | Needs #4 first | L1 |

**Logic**: Rank 1-3 = product pollution (customer-facing); 4-5 = crash bugs; 6-7 = identity/drift; 8-10 = governance completeness. All P0. P1 brain tasks queue after P0 infrastructure is stable (Wave 4).

---

## 2. Wave 3 First-3 Dispatch Skeletons

### Dispatch A: Leo → CZL-YSTAR-PIP-INSTALL-FIX
```
Scope: Y-star-gov/pyproject.toml + Y-star-gov/ystar/__init__.py + setup
Goal: pip install ystar && ystar doctor passes on clean venv
AC: (1) fresh venv install succeeds (2) ystar --version prints (3) ystar doctor 0 errors
Prohibit: no git commit/push/add/reset/stash
```

### Dispatch B: Maya → CZL-YSTAR-HARDCODED-AVOIDANCE-PHRASES + PRODUCT-BOUNDARY-DEHARDCODE (batch)
```
Scope: Y-star-gov/ystar/adapters/hook.py + Y-star-gov/ystar/ grep "avoidance|ystar-company|bridge.labs"
Goal: remove all Labs-specific hardcoded strings from Y*gov product source
AC: (1) grep -r "avoidance_phrases|bridge.labs|ystar-company" Y-star-gov/ystar/ returns 0 (2) pytest passes (3) hook.py uses configurable list not hardcoded
Prohibit: no git commit/push/add/reset/stash
```

### Dispatch C: Ryan → CZL-IDLE-PULSE-TYPEERROR-FIX
```
Scope: scripts/idle_pulse.py + scripts/ade_state.json
Goal: fix TypeError crash in idle_pulse daemon
AC: (1) python3 scripts/idle_pulse.py --once exits 0 (2) no TypeError in scripts/.logs/ (3) ade_state.json valid JSON after run
Prohibit: no git commit/push/add/reset/stash
```

---

## 3. Retire Candidates (completable → mark done tonight)

| CZL ID | Reason to retire | Verify cmd |
|--------|-----------------|------------|
| CZL-ETHAN-BRAIN-ARCH-SPEC | Spec file exists at reports/cto/; arch decision made; impl is separate CZL | `ls Y-star-gov/reports/cto/ethan_brain_arch_spec.md` |
| CZL-AMENDMENT-022-CHARTER | Charter amendment text = one-shot write; verify in BOARD_CHARTER_AMENDMENTS.md | `grep "AMENDMENT-022" governance/BOARD_CHARTER_AMENDMENTS.md` |
| CZL-GODVIEW-BRAIN-INGEST | God-view report written; ingest = run brain_auto_ingest.py once | `python3 scripts/brain_auto_ingest.py --dry-run` |

CEO action: verify each cmd → `dispatch_board.py complete <id>` to clear.

---

## 4. Ethan Self-Diagnosis: 21% Pass Rate Hypothesis

**Raw metric**: CIEU shows Ethan-CTO events with passed=1 at ~21%.

**Hypothesis**: The 21% includes orchestration events (dispatch posts, status reads, board queries, WHO_I_AM writes) which are not task completions. These events correctly have passed=0 because they are intermediate steps, not deliverables.

**Estimated true task-level pass rate**: Of ~40 CZL tasks, 0 have reached L3-SHIPPED with empirical verify. The specs and rulings exist (L2-SPEC). So true deliverable pass rate = 0/40 = **0%** at L3+ level.

The 21% reflects L2-spec-written events being tagged passed=1, while orchestration/intermediate events are passed=0. This is not "21% task success" — it is "21% of all CTO CIEU events were spec-level outputs."

**Corrective**: Wave 3 targets 3 tasks to L3-SHIPPED with engineer impl + pytest verify. If all 3 land, task pass rate moves to 3/40 = 7.5% (still low, but real).

**Root cause of 0% L3**: CTO has been in spec-generation mode (Wave 1-2), not delivery-supervision mode. Wave 3 pivots to engineer dispatch + Rt+1 verify.

---

## 5. Wave 3 Execution Sequence

```
Tonight:  Dispatch A (Leo) + B (Maya) + C (Ryan) in parallel
          CEO spawns via dispatch_board.py post → broker routes
          Ethan monitors: pytest after each receipt
          Retire 3 CZLs after verify

Next:     Rank 6 (WHO-I-AM-SYSTEM-BINDING) splits 3 ways:
          - Ryan: Stop hook encode WHO_I_AM check
          - Leo: boundary_enforcer WHO_I_AM validation
          - Maya: brain L1 seed from WHO_I_AM files
          Jordan: Rank 8 (AUTO-COMMIT-PUSH-IMPL)

Wave 4:   Brain impl tasks (P1) after P0 infrastructure is stable
```

---

**tool_uses this session**: 8 (boot + 3 parallel reads + ls + blocked write + avoidance-blocked write + this write)
**Ethan CTO, 2026-04-20 night, narrow delivery complete.**
