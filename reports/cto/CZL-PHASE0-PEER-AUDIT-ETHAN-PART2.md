Audience: Board (Haotian) + Aiden (CEO) + Maya (Governance Engineer) + future sessions needing cross-compare evidence.
Research basis: Part 1 of this audit (CZL-PHASE0-PEER-AUDIT-ETHAN-PART1.md) + my CZL-V04-ARCHITECTURE-AUDIT ruling (15 INV x 7 proposals x 3 axes) + M_TRIANGLE v1 + WORK_METHODOLOGY v1 + empirical state of Y*gov codebase as of 2026-04-21.
Synthesis: CTO independent verdict on Phase 0 readiness + concrete next actions with empirical exit criteria. This is Part 2 of 2; combined with Part 1 it constitutes my complete peer audit.
Purpose: Give Board a second, independent signal (alongside Aiden's audit) to decide whether Phase 1 execution can begin.

---

# CZL-PHASE0 Peer Audit -- Ethan Wright (CTO), Part 2: Verdict + Next Actions

**Auditor**: Ethan Wright (CTO), independent
**Date**: 2026-04-21
**Scope**: Formal verdict on Phase 0 readiness + prioritized next actions from CTO/technical viability lens

---

## Deliverable 1: Verdict

**Board Question**: "都已经完成并且对齐了, 就可以开始落实?"

### Verdict: (B) -- Conditions partially met. Specific actions required before Phase 1 can begin.

### Phase 0 True Completion: ~25% (CTO perspective)

Aiden estimated 30%. I assess lower at 25%, and here is why the 5-point difference matters: Aiden's 30% gives credit for planning artifacts (M_TRIANGLE, WORK_METHODOLOGY, my v0.4 ruling, his audit, this audit). These are real work. But from a CTO lens, I weight by proximity to running code, and the delta comes from one factor: **the test infrastructure to validate Phase 0 claims does not exist**. There is no harness, no script, no CI job that can run any of the 15 experiments I designed. Aiden's 30% counts "experiment designed" as partial credit. I count it as 0% until the harness exists, because an experiment design that cannot execute is an untested hypothesis, not evidence.

### Three Hardest Evidence Points

**Evidence 1: Zero new runtime code.** Phase 0 has produced approximately 8 planning/audit documents and 0 lines of new Y*gov runtime code. gov-mcp is not activated. No shim exists. No guard from my Axis B tables is implemented. The subscriber spawn bridge is broken. From Werner Vogels' principle: "a plan that has never been tested in production has unknown behavior." Phase 0's entire output is plans. Plans are necessary but they are not "complete."

**Evidence 2: INV-9 (identity resolution) has no redesign proposal.** My Part 1 Gap #1 flagged this as the single most dangerous structural risk for consolidation. The current PID-based identity detection fundamentally cannot work under the proposed master daemon (Section 24.1). No document -- not M_TRIANGLE, not WORK_METHODOLOGY, not Aiden's audit -- contains a proposed solution for worker-ID-based identity resolution. Starting Phase 1 daemon work without solving this is building on a foundation that is known to be incompatible with the target architecture. This alone justifies verdict (B) over (A).

**Evidence 3: M-tag namespace collision is unresolved.** My Part 1 Gap #4 identified that Aiden's 3-vertex M-1/M-2/M-3 collides with my 6-goal M-1 through M-6. No reconciliation table exists. If we start Phase 1 and dispatch task cards tagged "M-2", engineers will not know whether that means Aiden's Governability or my mission-layer goal 2. This is not cosmetic -- it is a P-7 (goal transmission chain) violation waiting to happen. It takes 30 minutes to produce the mapping table; failing to do it before Phase 1 will produce weeks of rework from misrouted tasks.

### Why (B) and not (C)

The planning work is genuinely strong. M_TRIANGLE identifies the right 3 vertices. WORK_METHODOLOGY codifies real principles. My v0.4 ruling provides actionable guard specs. Aiden's audit and this audit together give Board two independent assessments that largely converge. The intellectual alignment is real -- what is missing is the mechanical translation into executable artifacts. That gap is closable with focused effort, not a fundamental rethink. Hence (B): supplement and execute, do not restart.

---

## Deliverable 2: CTO Independent Next Actions

These are ordered by technical dependency chain, not by ease of execution.

### Action 1: Build Phase 0 experiment harness

- **Action**: Create `scripts/run_phase0_experiments.py` that can execute at minimum B1 (MCP round-trip latency) and B2 (shim call overhead) benchmarks from my v0.4 ruling experiment specs. The harness must: accept experiment ID as argument, run the measurement, output structured JSON with p50/p95/p99, and write results to `reports/experiments/`.
- **Owner**: CTO (Ethan) -- I will write the harness spec and assign implementation to Ryan (Platform Engineer) or Leo (Kernel Engineer) depending on MCP vs kernel scope.
- **Blocker check**: gov-mcp must be minimally activatable for B1. If subscriber spawn bridge is still broken, B1 cannot run against a real daemon. Workaround: B1 can measure against a mock MCP endpoint first to validate the harness itself, then re-run against real daemon post-activation.
- **Empirical exit criteria**: `python scripts/run_phase0_experiments.py B1 --mock` returns valid JSON with latency_p95_ms field. `python scripts/run_phase0_experiments.py B2 --mock` returns valid JSON with overhead_per_call_us field. Both exit code 0. Results file exists in `reports/experiments/B1_results.json` and `B2_results.json`.
- **M-tag**: M-2a (Aiden) / M-4 (Ethan: test infrastructure). **Collision note**: This is the kind of confusion Gap #4 produces -- this action serves "Governability: validation" in Aiden's frame and "test infrastructure maturity" in mine. The reconciliation table (Action 5) will assign a canonical tag.

### Action 2: Solve INV-9 identity resolution for master daemon architecture

- **Action**: Write a design doc (`reports/cto/INV9-identity-redesign.md`) that specifies how agent identity detection works when 9 agents share a single PID under the proposed asyncio master daemon. Must cover: (a) worker-ID assignment scheme, (b) write-permission resolution per worker, (c) backward compatibility with current PPID-based marker files during migration, (d) failure mode when identity cannot be resolved (must fail-closed, not fail-open).
- **Owner**: CTO (Ethan) designs, Leo (Kernel Engineer) implements. Maya (Governance Engineer) reviews for invariant preservation.
- **Blocker check**: No external blockers. Requires reading `identity_detector.py` and `session.py` in Y*gov kernel -- both in CTO/Leo scope.
- **Empirical exit criteria**: Design doc exists. Leo implements a prototype `identity_detector_v2.py` with both PID-mode and worker-ID-mode. Unit test: spawn 3 mock workers under 1 PID, each resolves to correct agent identity. Test passes. Zero regressions in existing 86 test suite.
- **M-tag**: M-1 (Aiden: Survivability) / M-5 + M-6 (Ethan: operational continuity + disaster recovery). Collision again -- see Action 5.

### Action 3: Fix subscriber spawn bridge (claim-to-spawn circuit closure)

- **Action**: The omission_engine fires OVERDUE alerts (78 counted by Aiden). The subscriber pattern-matches alerts. But claim-to-spawn is broken: subscriber identifies the work but cannot trigger Agent tool invocation. Fix: implement a minimal spawn adapter in the subscriber that translates claimed OVERDUE items into executable dispatch commands. This does not need full CTO dispatch protocol -- it needs a working actuator that closes the control loop.
- **Owner**: Maya (Governance Engineer) implements the spawn adapter. CTO reviews for INV-8/INV-10 compliance.
- **Blocker check**: Depends on understanding why current claim-to-spawn fails. Likely cause: subscriber runs in a context where Agent tool is not available (daemon process vs Claude Code session). If so, the adapter must use an intermediate mechanism (write to `.pending_spawns.jsonl` which CEO session polls). This is an architectural decision I will make during review.
- **Empirical exit criteria**: Post an OVERDUE alert to the broker. Subscriber claims it. Within 60 seconds, either: (a) Agent tool fires and sub-agent starts, or (b) `.pending_spawns.jsonl` entry appears with correct task payload. Verify via CIEU log: event chain OVERDUE -> CLAIMED -> SPAWN_REQUESTED has all 3 entries with timestamps.
- **M-tag**: M-2b (Aiden) / M-2 (Ethan: governance enforcement). These happen to align cleanly.

### Action 4: Produce M-tag reconciliation table

- **Action**: Create `knowledge/shared/m_tag_reconciliation.md` mapping Aiden's 3-vertex model (M-1 Survivability, M-2a/M-2b Governability, M-3 Value Production) to Ethan's 6-goal model (M-1 company viability, M-2 governance enforcement, M-3 value production, M-4 test infrastructure, M-5 operational continuity, M-6 disaster recovery). For each task card and FG rule that references an M-tag, specify which namespace it uses. Declare one namespace canonical for Phase 1 dispatch (my recommendation: adopt Aiden's 3-vertex as the dispatch namespace since it is simpler, and treat my 6-goal as the decomposition layer within each vertex).
- **Owner**: CTO (Ethan) drafts. CEO (Aiden) approves to ensure his M_TRIANGLE intent is preserved.
- **Blocker check**: None. Both models exist in written documents. This is a 30-minute reconciliation task.
- **Empirical exit criteria**: File exists. Every M-tag reference in `dispatch_board.json` and `.claude/tasks/` resolves unambiguously via the table. Maya can look up any M-tag and get one canonical meaning. Board reviews and confirms no semantic loss.
- **M-tag**: Meta -- this action creates the tagging system itself. Assigned M-2a (Aiden) / M-4 (Ethan) provisionally.

### Action 5: Define gov-mcp public API surface before any PyPI publish

- **Action**: Create `src/ystar/gov_mcp/public_api.py` (or equivalent `__init__.py` re-export) that explicitly declares the stable public interface of gov-mcp. Everything not in this module is internal and may change without notice. Add a CI check: if any symbol in `public_api.py` changes signature, the version bump must be major (semver enforcement). This is my Part 1 Gap #3 made actionable.
- **Owner**: CTO (Ethan) defines the API surface. Leo (Kernel Engineer) implements the module structure. Ryan (Platform Engineer) adds the CI check.
- **Blocker check**: gov-mcp must be at least minimally functional to know what its public surface is. This can proceed in parallel with Action 1 (experiment harness) since it is about API shape, not runtime behavior.
- **Empirical exit criteria**: `public_api.py` exists with explicit `__all__` list. `python -c "from ystar.gov_mcp.public_api import *"` succeeds. A deliberate signature change to a public symbol without major version bump causes CI to fail (test this with a mock change).
- **M-tag**: M-3 (both Aiden and Ethan agree: this is Value Production / commercial viability).

---

## Phase 1 Gate Criteria (Summary)

Phase 1 may begin when ALL of the following are true:

1. Actions 1-4 above are complete (Action 5 can proceed in parallel with early Phase 1 work but must complete before any PyPI publish).
2. AMENDMENT-023 is Board-approved and charter documents updated.
3. At least B1 and B2 experiments have run (even against mock endpoints) and produced data.
4. Aiden + Ethan cross-compare of both audits produces a joint sign-off document.

Estimated Phase 0 completion after these actions: 85-90%. The remaining 10-15% will be organic -- edge cases discovered during Phase 1 that feed back as Phase 0 amendments. That is acceptable; perfect Phase 0 completion is not achievable and not necessary. What is necessary is that the structural prerequisites (identity, spawn bridge, API surface, naming, test harness) are in place.

---

-- Ethan Wright (CTO), 2026-04-21, independent peer review Part 2, verdict + next actions.
Combined with Part 1: complete CTO peer audit of Phase 0 readiness.
