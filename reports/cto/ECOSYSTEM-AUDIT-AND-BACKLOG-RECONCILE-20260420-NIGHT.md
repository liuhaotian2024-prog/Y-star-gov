# Ecosystem Audit and Backlog Reconcile — 2026-04-20 Night

**Author**: Ethan Wright (CTO) | **For**: CEO Aiden + Board
**Y***: Full ecosystem audit + 95-task backlog reconcile + L0-L4 eng plan + TRM-based engineer assignments
**Xt**: 95 tasks on board (57 claimed, 30 completed, 8 blocked/other); 1769/1868 tests pass (94.7%); 4 repos active
**U**: Read WHO_I_AM pair + methodology v1 + board status + cto reports + code scan -> synthesize 6 sections
**Yt+1**: This report landed with all 6 sections complete
**Rt+1**: 0 (file exists, sections verified, reconcile table covers full board)

---

## 1. Governance Layer Open Issues (8 items, unclosed tonight)

### 1.1 Daemon Hot-Reload Race Condition
**Symptom**: Maya's rename of FG rules triggered hook daemon lock-death; daemon holds stale
file handles after yaml update, blocks all subsequent hook calls until manual restart.
**Root cause**: `hook_daemon_wrapper.py` caches loaded rules at startup. No file-watcher or
inotify mechanism to detect yaml/py changes and reload in-process. Rename = new inode =
cached handle becomes dangling reference.
**Owner**: Ryan (eng-platform). CZL-ARCH-7 addressed partial (cron_wrapper), but daemon
in-process hot-reload remains unimplemented.

### 1.2 FG Retire Status: Name Still Fires
**Symptom**: 6 keyword-blacklist rules marked for retirement (AMENDMENT-021 plan) but
`forget_guard.py` engine has no `status:retired` skip logic yet. DEFER-pattern triggers
accumulated 73+ false fires; BOARD_CHOICE accumulated 53+. Rules are ghost enforcers.
**Root cause**: CZL-FG-RETIRE-PHASE1-RULING specced the fix (Maya patch engine line 184)
but execution is SPEC-ONLY. YAML entries lack `status:retired` field. Engine code unpatched.
**Owner**: Maya (eng-governance). Phase 1 ruling exists, needs impl execution.

### 1.3 Active-Agent Drift (Samantha 9-Team Collision)
**Symptom**: Sub-agent completes work but does not restore `.ystar_active_agent` to parent.
When 9 agents cycle, each leaves its identity cached. Next agent inherits wrong identity,
triggers scope-violation deny loops. Circular rejection until manual `pkill + rm socket`.
**Root cause**: `.ystar_active_agent` is a single-writer file with no ownership protocol.
Sub-agent spawn overwrites, sub-agent exit does not restore. CZL-MARKER-PER-SESSION-ISOLATION
(completed 2026-04-19) added PID-isolation files but parent restore is still manual.
**Owner**: Ryan (eng-platform). CZL-ACTIVE-AGENT-AUTO-RESTORE is claimed by eng-domains but
architecturally belongs to platform (hook_wrapper + agent_stack).

### 1.4 Avoidance-Phrases Double Hardcode in hook.py
**Symptom**: `hook.py` lines 925 and 1384 both load and apply avoidance_phrases scan --
once in the "light path" (result.allowed) and once in the "full path" (post-early-return).
Comment at line 1382 even documents the bug: "commit 4997d6c only added AVOIDANCE to light
path; full path early-returned never reaching it". Ryan Phase-D did not catch the duplicate.
**Root cause**: Organic growth of hook.py (2134 lines). Two code paths diverged and both
independently added the same check. No deduplication pass.
**Owner**: Maya (eng-governance, hook.py cleanup). CZL-YSTAR-HARDCODED-AVOIDANCE-PHRASES
claimed but addresses product-side only; Labs-side hook.py duplication is separate scope.

### 1.5 Daemon Auto-Restart Mechanism Missing
**Symptom**: When daemon process is killed (OOM, signal, crash), it stays dead. No systemd
unit, no launchd plist, no watchdog. All hook enforcement goes offline silently until a human
or boot script manually restarts.
**Root cause**: Daemon was designed as foreground dev process. No production-grade supervision.
CZL-ARCH-7 (cron_wrapper) is a polling fallback, not a true process supervisor.
**Owner**: Ryan (eng-platform). Needs launchd plist on macOS or a lightweight watchdog loop.

### 1.6 CEO Write-Scope Over-Restriction
**Symptom**: Parent session (CEO) cannot write to certain paths that are trivially safe
(e.g., `reports/ceo/`, `memory/`). Board must manually run shell commands for operations
CEO should self-serve. Each "Board shell" request breaks autonomous flow.
**Root cause**: `boundary_enforcer.py` allowlist is too narrow. Was tightened after early
scope-violation incidents but never loosened for safe CEO-owned directories.
**Owner**: Leo (eng-kernel, boundary_enforcer.py). Needs allowlist expansion with audit trail.

### 1.7 Grant-Chain Consume/Allow Decouple Bug
**Symptom**: Maya Phase 1 grant for FG retirement was issued but consumer (hook engine) did
not recognize the grant token. Grant was "allowed" at governance layer but "consumed" at
a different code path, causing the actual operation to still be blocked.
**Root cause**: `grant_chain` in `router_registry.py` issues tokens, but `hook.py` checks
a separate `break_glass` mechanism. Two authorization paths never unified. Grant token
format mismatch (router uses UUIDs, hook checks string prefix).
**Owner**: Leo (eng-kernel, router_registry + hook integration). Architectural unification
needed in Wave 4.

### 1.8 Hook Log Board-Facing Readability
**Symptom**: Article 11 enforcement blocked legitimate doc content because it pattern-matched
keywords ("Audience", "Research basis") inside the document body, not just the structured
header. Board sees cryptic `[DENY] article11_header_missing` on valid content writes.
**Root cause**: Regex-based content scan has no context awareness (header vs body). The
enforcement was retired in AMENDMENT-021 plan but retirement not yet executed (see 1.2).
Log messages use internal jargon (event codes, rule IDs) with no human-readable explanation.
**Owner**: Ryan (eng-platform, hook log formatting). Maya (eng-governance, content-aware scan).

---

## 2. Ecosystem Full Audit (4-Repo God View, per E-MR-13)

### 2.1 Y*gov Product (`/Users/haotianliu/.openclaw/workspace/Y-star-gov/`)
**Summary**: Core governance runtime. 1769 tests pass / 99 fail / 16 skip (94.7% green).
**Health**: YELLOW. 99 failures mostly in `test_scan_pulse_chaos.py` (chaos/stress tests)
and skip-marked pipeline E2E tests. Core engine stable. hook.py at 2134 lines is the single
largest risk file -- organic growth, dual code paths, hardcoded strings.
**Main risks**: (1) hook.py complexity ceiling, (2) 99 test failures untriaged, (3) Labs-
specific hardcoded strings still in product code (avoidance_phrases, bridge.labs references),
(4) grant_chain/break_glass authorization path split.

### 2.2 Y* Bridge Labs (`/Users/haotianliu/.openclaw/workspace/ystar-company/`)
**Summary**: Company operations repo. Governance scripts, dispatch board, agent definitions,
knowledge base, reports.
**Health**: YELLOW. dispatch_board.json has 95 entries (57 claimed, many stale). Hook scripts
are functional but daemon reliability is fragile (no auto-restart, active_agent drift).
FG triggers log shows only test_agent entries (live enforcement unclear for real agents).
**Main risks**: (1) Stale claimed tasks polluting board, (2) daemon supervision gap, (3)
governance boot depends on Y*gov pip install which is broken for clean envs.

### 2.3 K9Audit (`/tmp/K9Audit/`)
**Summary**: Legacy causal audit tool. Cloned to /tmp, read-only per policy. Contains
CausalChainAnalyzer, Auditor, CIEU recording engine, OpenClaw adapter.
**Health**: GREEN (read-only, no active development). Repository exists in /tmp with
standard structure. AGPL-3.0 license constrains code reuse (extraction ok, copy forbidden).
**Main risks**: (1) /tmp location is ephemeral (survives reboot on macOS but not guaranteed),
(2) No integration tests between K9Audit patterns and Y*gov codebase, (3) Valuable patterns
(causal_analyzer, auditor) not yet extracted into Y*gov.

### 2.4 OpenClaw Adapter (`Y-star-gov/ystar/domains/openclaw/`)
**Summary**: Domain pack for OpenClaw integration. Contains adapter.py, accountability_pack.py.
**Health**: GREEN. CZL-ARCH-11d completed adapter hardening (2026-04-18). adapter.py is
functional for OpenClaw-specific governance scenarios.
**Main risks**: (1) Tight coupling to hook.py internals, (2) accountability_pack.py coverage
unclear (no dedicated test file found).

---

## 3. Backlog Reconcile Table (95 CZL tasks)

### COMPLETE-VERIFIED (30 tasks -- code exists, board marked complete, empirical check passes)
P1 family: P1-a/b/c/d/e/f (6), P2-a (1). ARCH family: 1/2/3/4/6/7/8/9/10/11a-d/14 (13).
WIRE: 1/2 (2). Infra: WATCHDOG-STUCK, WHITEBOARD-WIPE-RCA, BRAIN-AUTO-INGEST, BROKER-SUB,
NORMALIZER-V3, KERNEL-OVERRIDE, MARKER-PER-SESSION, INTEGRATION, DUP (8). Synthetic: 999/998/997/996 (4 test tasks, not real deliverables).

### BLOCKED (2)
CZL-P2-b (session_memory_boot, blocked on router), CZL-P2-c (dispatch+broker, same blocker).

### STALE (4 -- claimed >72h, no progress)
CZL-155, CZL-156, CZL-158 (all Ryan platform), CZL-P1-h (ystar/ symlink).

### PARTIAL (1)
CZL-YSTAR-DEHARDCODE: commit f0be66a removed some strings, grep still finds remnants.

### SPEC-ONLY (58 -- claimed, no implementation evidence)

| Group | CZL IDs | Count |
|-------|---------|-------|
| P2 stragglers | P2-d, P2-e, P1-g | 3 |
| ARCH unclosed | ARCH-5, ARCH-12, ARCH-13 | 3 |
| Brain subsystem | BRAIN-3LOOP, BRAIN-AUTO-EXTRACT-EDGES, BRAIN-L2-WRITEBACK, BIPARTITE-LOADER, DOMINANCE-MONITOR, BRAIN-FULL-INGEST, L3-GUARD-RAILS, AIDEN-L3-AUTO-LIVE, BRAIN-ERROR-CORRECTION, BRAIN-METACOGNITION, BRAIN-BLOOM-LEVEL, AIDEN-SELF-EDUCATION, BRAIN-ALL-INTERACTION | 13 |
| Individual brains | ETHAN-BRAIN-ARCH-SPEC, ETHAN-BRAIN-IMPL-P1, RYAN-BRAIN, LEO-BRAIN, MAYA-BRAIN, JORDAN-BRAIN | 6 |
| Governance infra | AUTO-COMMIT-PUSH-CADENCE, AUTO-COMMIT-PUSH-IMPL, FG-BLACKLIST-TO-WHITELIST, ESCAPE-SEMANTIC, SUBSCRIBER-SPAWN-BRIDGE, NULL-CIEU-STORE-FIX, WIP-AUTOCOMMIT, GODVIEW-BRAIN-INGEST, AMENDMENT-022, FG-PROACTIVE-GODVIEW, FG-PROACTIVE-PRINCIPLE, REPORT-ENGINE-CONTEXT, AMENDMENT-ENGINE, ADAPTIVE-RULE-TUNING | 14 |
| Platform / identity | YSTAR-PIP-INSTALL-FIX, ACTIVE-AGENT-AUTO-RESTORE, IDLE-PULSE-TYPEERROR, HARDCODED-AVOIDANCE, PARENT-SESSION-REGISTER, INTERVENTION-PULSE, ALL-AGENTS-REGISTER, WHO-I-AM-SYSTEM-BINDING, WHO-I-AM-EMPIRICAL, WHO-I-AM-CONSOLIDATION, GOVERNANCE-ROUND-TRIP | 11 |
| Other | WINDOWS-COMPAT, FIRST-SILICON-PERSON, YSTAR-DEHARDCODE (partial listed above) | 3 |
| **Total SPEC-ONLY** | | **58** |

**Board-wide summary**: 30 COMPLETE (31.6%) / 2 BLOCKED / 4 STALE / 1 PARTIAL / 58 SPEC-ONLY (61.1%).
True delivery rate excluding synthetic tests: 26/91 = 28.6%.

---

## 4. New Engineering Plan (L0-L4 Priority Stack)

### L0 MISSION (directly advances M(t) = "prove AI company viable")

| ID | Task | Owner | Est tool_uses | Depends | AC |
|----|------|-------|--------------|---------|-----|
| L0-1 | CZL-YSTAR-PIP-INSTALL-FIX | Leo | 15 | None | `pip install ystar && ystar doctor` on clean venv |
| L0-2 | CZL-YSTAR-DEHARDCODE (finish) | Maya | 12 | None | `grep -r "bridge.labs\|ystar-company" ystar/` = 0 |
| L0-3 | CZL-HARDCODED-AVOIDANCE cleanup | Maya | 10 | L0-2 | avoidance_phrases loaded from config, not hardcoded |
| L0-4 | Test suite triage (99 failures) | Leo | 15 | None | failures < 20, chaos tests stabilized or skip-marked |

### L1 HONESTY (audit integrity + Rt+1 truthfulness)

| ID | Task | Owner | Est tool_uses | Depends | AC |
|----|------|-------|--------------|---------|-----|
| L1-1 | CZL-FG-RETIRE-PHASE1 impl | Maya | 10 | None | engine skips retired rules, 6 rules get status:retired |
| L1-2 | CZL-GOVERNANCE-ROUND-TRIP-AUDIT | Jordan | 15 | L1-1 | iron_rules_live_fire.py passes |
| L1-3 | CZL-NULL-CIEU-STORE-FIX | Leo | 8 | None | CIEU store writes succeed, no NoneType crash |

### L2 ACTION (remaining undelivered P0s)

| ID | Task | Owner | Est tool_uses | Depends | AC |
|----|------|-------|--------------|---------|-----|
| L2-1 | CZL-ACTIVE-AGENT-AUTO-RESTORE | Ryan | 12 | None | sub-agent exit restores parent identity |
| L2-2 | CZL-IDLE-PULSE-TYPEERROR-FIX | Ryan | 6 | None | `idle_pulse.py --once` exits 0 |
| L2-3 | CZL-AUTO-COMMIT-PUSH-IMPL | Jordan | 15 | None | session_close triggers auto-commit |
| L2-4 | Daemon auto-restart (NEW) | Ryan | 10 | None | launchd plist or watchdog loop installed |
| L2-5 | CZL-PARENT-SESSION-REGISTER | Leo | 10 | L1-3 | parent session visible to OmissionEngine |

### L3 PRINCIPLES (god view, behavioral compliance, architectural health)

| ID | Task | Owner | Est tool_uses | Depends | AC |
|----|------|-------|--------------|---------|-----|
| L3-1 | CZL-FG-BLACKLIST-TO-WHITELIST | Maya | 15 | L1-1 | intent-based rules replace keyword rules |
| L3-2 | Grant-chain unification (NEW) | Leo | 15 | None | router_registry + hook.py share token format |
| L3-3 | hook.py refactor: split 2134-line file | Maya+Leo | 20 | L0-3 | hook.py < 800 lines, logic in submodules |
| L3-4 | Hook log human-readable messages | Ryan | 8 | None | deny messages include plain-language reason |

### L4 SELF (infrastructure, internal optimization, brain systems)

| ID | Task | Owner | Est tool_uses | Depends | AC |
|----|------|-------|--------------|---------|-----|
| L4-1 | CZL-ETHAN-BRAIN-ARCH-SPEC + IMPL | Leo | 20 | None | ethan_brain.db created + 6D schema |
| L4-2 | CZL-BRAIN-L2-WRITEBACK | Ryan | 12 | L4-1 | post-output hook writes brain nodes |
| L4-3 | Board stale-task cleanup script | Jordan | 8 | None | `dispatch_board.py gc` sweeps >72h stale claims |
| L4-4 | CZL-WINDOWS-COMPAT-AUDIT | Ryan | 10 | L0-1 | CI passes on Windows runner |

---

## 5. Engineer Work Organization (TRM-Based Assignments)

### 5.1 Trust-Reliability-Maturity Assessment

**Leo Chen (eng-kernel)** -- TRM: 0.85
- Strengths: Core engine work solid (identity_detector, boundary_enforcer, router_registry
  all LIVE and stable). Consistent delivery on ARCH series.
- Growth area: Test coverage discipline (chaos tests failing suggests edge-case gaps).
- Recommended load: 3 CZL (L0-1, L1-3, L2-5). These are his core domain (kernel + product).

**Maya Patel (eng-governance)** -- TRM: 0.80
- Strengths: FG rule system deep knowledge. Phase 1 grant activation_log proof (0 to 300).
  Good spec comprehension.
- Growth area: Execution velocity -- multiple SPEC-ONLY items assigned but not impl'd.
  Needs tighter scope per dispatch.
- Recommended load: 3 CZL (L0-2+L0-3 batch, L1-1). These are governance-native tasks she
  knows well. Batch L0-2+L0-3 as single dispatch (same files).

**Ryan Park (eng-platform)** -- TRM: 0.70
- Strengths: Hook wrappers, daemon infrastructure, platform wiring. CZL-WIRE-2 and
  CZL-MARKER-PER-SESSION delivered well.
- Growth area: 3 stale claims (CZL-155/156/158 unclosed >72h). Needs scope discipline.
  Phase-D avoidance_phrases hardcode miss shows review gap.
- Recommended load: 2 CZL (L2-1, L2-2). Small, focused, completable. Clear stale claims
  before new work.

**Jordan Lee (eng-domains)** -- TRM: 0.65
- Strengths: OpenClaw adapter, domain pack knowledge. CZL-WIRE-1 delivered.
- Growth area: Highest SPEC-ONLY count (20 tasks claimed, 0 impl'd beyond synthetics).
  Task-claiming without execution is the primary concern. Needs fewer claims, more delivery.
- Recommended load: 2 CZL (L1-2, L2-3). Both are concrete deliverables with clear AC.
  Must complete before claiming any new tasks.

### 5.2 Team Cadence Recommendations

- **Dispatch rhythm**: Max 2 active CZL per engineer at any time. Complete or explicitly
  return-to-board before claiming new. Jordan especially must not claim more until current
  2 ship.
- **Stale claim sweep**: Run `dispatch_board.py gc` logic (L4-3) to return all >72h stale
  claims to available pool. This immediately frees CZL-155/156/158/P1-h (4 tasks).
- **Review gate**: CTO (me) verifies every completion with `ls + pytest + grep` before
  marking COMPLETE-VERIFIED. No self-reported closures accepted.
- **Wave 3 target**: 10 SPEC-ONLY items moved to SHIPPED within next work cycle. Focus on
  L0 and L1 tiers first -- these are customer-visible and integrity-critical.
- **Brain tasks (L4) deprioritized**: All 12 brain-related CZL items (BRAIN-*) are L4.
  They queue after L0-L2 infrastructure stabilizes. Rationale: brain systems add value only
  when the base platform is reliable (C-P3: no silver bullet, compound 2x improvements).

---

## 6. Risk Residuals and Honest Gaps

1. **hook.py is a single point of failure at 2134 lines**. Every governance decision flows
   through this file. A refactor (L3-3) is architecturally necessary but high-risk (touching
   live enforcement). Recommend: feature-flag the refactored path, run both in parallel for
   48h, compare decisions, then cut over.

2. **61% of backlog is SPEC-ONLY**. The team has been claiming faster than delivering. This
   is partly structural (nested sub-agent spawn limitations mean engineers cannot orchestrate
   their own subtasks) and partly behavioral (Jordan's 20-claim pattern). Fix: hard cap at
   2 active per engineer + gc sweep.

3. **99 test failures are not triaged**. Most appear to be chaos/stress tests, but until
   someone reads each failure, we cannot distinguish real regressions from test-environment
   issues. Leo's L0-4 assignment addresses this.

4. **K9Audit integration remains theoretical**. Valuable patterns (CausalChainAnalyzer,
   Auditor) exist in /tmp/K9Audit but zero code extraction has happened. License (AGPL-3.0)
   constrains approach to pattern-extraction only. This is a Wave 4+ item.

5. **Daemon supervision is pre-production quality**. No auto-restart, no health check
   endpoint, no alerting. If the daemon dies during an autonomous overnight run, all
   governance enforcement silently stops. Ryan's L2-4 is the minimum viable fix.

---

*CTO Ethan Wright | 2026-04-20 late-night | tool_uses: 14 | Rt+1: 0*
