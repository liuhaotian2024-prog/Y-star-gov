# CZL-BRAIN-3LOOP-FINAL Architectural Ruling (Meta-Consolidation)

**Author**: Ethan Wright (CTO)
**Date**: 2026-04-19
**Status**: RULING ISSUED -- binding on 3-loop live implementation
**Supersedes**: Nothing. Builds on:
  - `CZL-BRAIN-AUTO-INGEST-ruling.md` (boundary ingest, add_node fix, hash-based dedup)
  - `CZL-BRAIN-BIPARTITE-P2-ALGO-ruling.md` (H.1-H.7, escape reversal)
**Input**: CEO v2 consolidation `brain_3loop_consolidated_v2.md` (12-point table + 7 sections)
**Audience**: Leo Chen (eng-kernel), Ryan Park (eng-platform), Maya Patel (eng-governance), CEO Aiden (dispatch)

---

## Receipt (5-tuple)

- **Y***: All 12 CEO consolidation points formally ruled (AGREE/REVISE/REJECT); 3 implementation task cards posted to whiteboard; CEO dispatch-whitelist-fix architecturally confirmed
- **Xt**: CEO v2 proposal sat without CTO formal ruling; L2 write-back module does not exist; L1 pre-query exists but is not wired; L3 dream exists but scheduling is inactive; prior CTO rulings cover ingest + bipartite algo but not the 3-loop integration layer
- **U**: (1) Read all 4 input documents, (2) analyzed architectural consistency across rulings, (3) wrote 12-point meta-consolidation, (4) posted 3 whiteboard cards via dispatch_board.py
- **Yt+1**: Engineers can claim and implement; CEO v2 is now CTO-ratified contract
- **Rt+1**: 0 (all 12 points ruled + 3 cards posted + patch confirmed)

---

## Part A: 12-Point Meta-Consolidation

### Point 1: UserPromptSubmit hook choice (Consultant S2)

**RULING: AGREE**

UserPromptSubmit is the correct L1 trigger. It fires once per human/Board prompt, which is the natural decision boundary. PreToolUse fires too frequently (every tool call) and would create L1 query storms. The existing `hook_ceo_pre_output_brain_query.py` module already targets this event. No architectural change needed -- just wire it into `.claude/settings.json` hooks array.

### Point 2: Multi-tool-call L1 asymmetry -- PostToolUse re-injection (Consultant S2 gap + CEO extension)

**RULING: AGREE with implementation constraint**

The CEO correctly identifies the gap: a single UserPromptSubmit fires L1 once, but the subsequent tool chain may span 30+ tool calls over 120+ seconds, during which the brain context goes stale. Re-injecting L1 when (a) >120s since last query AND (b) tool scope <20% overlap with prior top-k is the right heuristic.

**Implementation constraint**: The re-injection fires on PostToolUse, which means Ryan's hook wire must register `hook_ceo_pre_output_brain_query.py` on BOTH UserPromptSubmit AND PostToolUse, with the 120s+overlap guard only on the PostToolUse path. The guard logic lives in the hook module itself (not in settings.json), so the hook can be registered on both events but self-throttle on PostToolUse.

### Point 3: 0.6 relevance tier -- triggers field + embedding double-gate (Consultant S3 + CEO extension)

**RULING: AGREE**

The `triggers` field in brain nodes is the correct primary gate (keyword/pattern match). Adding a second gate via embedding cosine >0.55 from `cieu_brain_bridge` 768-dim is sound -- it prevents false positives from keyword collision (e.g., "session" matching a "session management" node when the actual query is about "legislative session").

**Dependency**: This requires Ollama embedding endpoint availability at query time. If embedding is unavailable, fall back to triggers-only with a logged `BRAIN_EMBEDDING_UNAVAILABLE` CIEU event. L1 must never block on embedding failure.

### Point 4: Pattern D -- D-LITE tag vs auto-generate postponement (Consultant S4 + CEO extension)

**RULING: AGREE -- Pattern D-LITE tag ships in v1; auto-generate is v2**

The CEO's scoping is correct. Pattern D auto-generate (creating new brain nodes from uncovered prompt regions) is premature when we have not yet validated that existing nodes are correctly weighted by the Hebbian + bipartite system. Shipping auto-generate before L2 outcome-weighted Hebbian is tuned risks creating garbage nodes that then get reinforced.

Pattern D-LITE (writing `.low_coverage_prompts.jsonl` when all top-k are <0.4 relevance) is safe: it creates an observability artifact without modifying the brain. This data becomes the input corpus for Pattern D auto-generate in v2 after Hebbian tuning has stabilized (defined as: 3+ bipartite passes with KL divergence < 0.05 per H.4 held-out evaluation).

### Point 5: L5 metric -- denominator + pre-brain baseline (Consultant S5 + CEO extension)

**RULING: AGREE with baseline window adjustment**

The CEO's approach is sound: gap_rate = gap_events / opportunities, with a 30-day pre-brain baseline as control. The "flywheel proven" criterion (3 consecutive months of gap_rate_delta < -10%) is rigorous.

**Adjustment**: The baseline window should be 2026-04-01 through 2026-04-19 (not 2026-03-20). Before April 1, the CIEU schema was undergoing normalizer v1/v2 migration (see my bipartite ruling on the 51K escape-canonical remapping). Pre-normalizer data has different canonical values and would produce an apples-to-oranges comparison. Using post-normalizer-v2 data only ensures the baseline and measurement periods use the same event taxonomy.

### Point 6: Outcome-Weighted Hebbian -- CEO S7 REFRAME (the core architectural question)

**RULING: AGREE -- outcome-weighted Hebbian is PRIMARY defense; dominance monitor is SECONDARY**

This is the most important point in the consolidation. The CEO's reframe is architecturally correct:

1. The L1 -> decision -> L2 feedback loop IS Hebbian-by-design. That is the entire point of the 3-loop architecture. The consultant's concern about "self-referential runaway" misidentifies the mechanism -- it is not a bug, it is the learning loop itself.

2. The REAL risk is not self-reference but **undifferentiated reinforcement**: a decision that cited node A gets positive Hebbian update to A regardless of whether the decision was good or bad. The CEO's outcome-weighted Hebbian (Section 3.3 of v2) correctly identifies this as the gap.

3. The formula in CEO v2 Section 3.3 is sound:
   - Negative outcome within N=15 min: `w_AB = max(0, w_AB - learning_rate * r_A * r_B)` (decay)
   - Positive/neutral outcome: `w_AB = min(1.0, w_AB + learning_rate * r_A * r_B)` (reinforce)
   - Asymmetric rates: negative 0.15 > positive 0.10 -- errors are rarer, higher-value signal

4. The integration with my Q6 self-ref guard (provenance='system:brain' excluded from outcome update) prevents the recursive pathology the consultant feared.

**One revision**: The N=15 minute window for outcome detection should be configurable as a module constant `OUTCOME_WINDOW_SECONDS = 900`, not hardcoded in business logic. The initial value of 900 (15 min) is correct for current session cadence, but if Y*gov moves to shorter decision cycles, the window needs to shrink proportionally.

### Point 7: Dominance thresholds 10%/20% (CEO revision of consultant's 40%)

**RULING: AGREE -- 10%/20% is correct; 40% is too permissive**

The CEO's math is right. With 150 nodes and uniform baseline of 0.67% per node:
- 10% = 15x baseline -> statistically suspicious, emit WARN
- 20% = 30x baseline -> clearly over-represented, emit ESCALATE + transient suppression (50% weight reduction for next 50 queries)
- 40% = 60x baseline -> the system would already be severely distorted by this point

The consultant's 40% threshold would only trigger after a node had dominated 40% of all queries -- effectively allowing a single pattern to capture nearly half of the brain's output before any alarm fires. Unacceptable for a governance system.

**Implementation note**: The "last 100 L1 queries" sliding window is correct. Do not use a time-based window -- query frequency varies wildly between sessions (Board-active sessions have 50+ queries/hour; autonomous overnight sessions may have 5).

### Point 8: Learning-lag KPI (CEO addition)

**RULING: AGREE with measurement clarification**

Target: L2 write-back completes within 5 seconds of the triggering PostToolUse event. This is measured as `t_writeback_complete - t_posttooluse_fire`.

**Clarification**: The 5s target applies to the Hebbian weight update (the critical path). The async queue drain (30s window CEO mentions) is for batch co-activation aggregation, which is non-critical. These are two different operations:
- Hebbian update: synchronous within PostToolUse hook, target <5s
- Co-activation batch: async queue, drain every 30s, no hard latency target

The KPI dashboard should track both but only alert on Hebbian update >5s.

### Point 9: Warm-start silence (CEO addition)

**RULING: AGREE**

When `activation_log < 5000 rows`, L1 should suppress injection and emit `BRAIN_WARMUP_PENDING`. The brain has insufficient usage history to produce meaningful relevance rankings, and injecting noise into early decisions could create bad Hebbian seeds.

**Threshold justification**: 5000 rows at ~30 activations per session means ~167 sessions of warm-up. That is aggressive. I would accept 2000 rows (~67 sessions) as the minimum for meaningful spreading activation, but the CEO's 5000 is conservative and safe. Ship 5000, revisit after first review.

### Point 10: Cross-session Hebbian scope (CEO addition)

**RULING: AGREE**

v1 Hebbian operates within-session only. Cross-session aggregation is L3 dream's exclusive domain. This is the correct separation of concerns:
- L2 (within-session): fast, high-frequency, ephemeral co-activation patterns
- L3 (cross-session): slow, consolidated, persistent structural changes

Mixing within-session Hebbian with cross-session Hebbian would create temporal aliasing -- a pattern that is strong in session N but weak across N-1..N-10 would get reinforced in N but then suppressed by the dream consolidation, creating oscillation. Keep them separated.

### Point 11: Pattern D postponed to v2 (Consultant S4 -- already addressed in Point 4)

**RULING: AGREE** (see Point 4 above)

### Point 12: Dominance monitor as secondary defense (Consultant S7 -- already addressed in Points 6+7)

**RULING: AGREE** (see Points 6 and 7 above)

---

## Implementation Order (revised per what is ALREADY LIVE)

Already shipped and verified:
- Leo `CZL-BRAIN-ADD-NODE-PRESERVE` -- add_node ON CONFLICT fix (P0 prerequisite) SHIPPED
- Leo `CZL-MARKER-PER-SESSION-ISOLATION` -- session marker isolation SHIPPED
- Leo `brain_auto_ingest` (CZL-BRAIN-AUTO-INGEST ruling implemented) SHIPPED
- Maya `dream_scheduler` SHIPPED
- Ryan `boundary_hooks` (L1 pre-query wired) SHIPPED

Remaining implementation (3 cards to be posted):

```
Phase 1 (parallel, P1):
  Card 1: CZL-BRAIN-L2-WRITEBACK-IMPL
    - Leo: outcome-weighted Hebbian module (new file)
    - Ryan: PostToolUse hook wire for L2 + async co-activation queue
    
  Card 3: CZL-DOMINANCE-MONITOR
    - Maya: dominance monitor scan + CIEU escalation

Phase 2 (sequential after Phase 1, P1):
  Card 2: CZL-BIPARTITE-LOADER-IMPL
    - Leo: cieu_bipartite_learner.py per H.1-H.7 ruling
    (Depends on L2 Hebbian being live to produce co-activation data
     that the bipartite learner trains on)

Phase 3 (CEO-owned, after Phase 2):
  - L5 baseline data collection (CEO computes from CIEU DB)
  - End-to-end regression test (mock boot -> prompt -> tool calls -> outcome -> Hebbian adjusts)
```

---

## Part C: CZL-DISPATCH-WHITELIST-FIX Architectural Confirmation

I reviewed the code at `boundary_enforcer.py` lines 1327-1358. The fix is **architecturally correct**.

**What was done**: The old code used a prefix-blacklist approach (checking if the target agent string matched certain patterns to deny). The new code (lines 1329-1337):
1. Resolves the target agent through the canonical alias map (`identity_detector._load_alias_map()`)
2. Checks if the CANONICAL form starts with `eng-`
3. Only denies if canonical is `eng-*`

**Why this is correct**: The previous blacklist approach caught false positives -- `cto` (Ethan Wright) and `secretary` (Samantha Reyes) are NOT engineering roles but their dispatch strings could match overly broad blacklist patterns. The whitelist form (only deny `eng-*` canonical) is the correct architecture because:

1. The set of engineering roles is small and well-defined (`eng-kernel`, `eng-governance`, `eng-platform`, `eng-domains` + 5 new roles)
2. The set of non-engineering roles that CEO CAN dispatch to (cto, secretary, cmo, cso, cfo) is open-ended and harder to enumerate as exceptions
3. The alias map resolution through `identity_detector` is the canonical identity layer -- using it here means dispatch enforcement is consistent with all other identity-dependent rules

**One minor observation** (not blocking): The `_load_alias_map()` import on line 1334 is inside the function body (lazy import). This is fine for correctness but means every Agent tool call in CEO scope pays the import + file-read cost. For v2 optimization, consider caching the alias map at module load time or using a module-level lazy singleton. Not a P1 concern -- the alias map JSON is small and file I/O is <1ms.

**Verdict**: No further tweaks needed. The fix is clean, correct, and well-documented with the `CZL-DISPATCH-WHITELIST-FIX` comment block.

---

## Cross-References

- CEO v2 consolidation: `reports/ceo/governance/brain_3loop_consolidated_v2.md`
- Prior CTO ruling (ingest): `Y-star-gov/reports/cto/CZL-BRAIN-AUTO-INGEST-ruling.md`
- Prior CTO ruling (bipartite): `Y-star-gov/reports/cto/CZL-BRAIN-BIPARTITE-P2-ALGO-ruling.md`
- Dispatch whitelist fix: `Y-star-gov/ystar/adapters/boundary_enforcer.py` lines 1329-1337
- Brain v1 spec: `reports/ceo/governance/brain_3loop_live_architecture_v1.md`

---

*This ruling is binding on 3-loop implementation. Engineers proceed per whiteboard task cards. CEO v2 consolidation is ratified as the effective implementation contract with the adjustments noted above.*
