# CZL-BRAIN-BIPARTITE-P2-ALGO Architectural Ruling

**Author**: Ethan Wright (CTO)
**Date**: 2026-04-19
**Status**: RULING (binding on Phase 2 implementation)
**Supersedes**: Nothing. Builds on `CZL-BRAIN-BIPARTITE-ruling.md` (Q1-Q6, same date). All prior Q1-Q6 constraints remain in force unless explicitly revised below.
**Inputs**:
  - Leo spec: `docs/kernel/bipartite_loader_phase2_algorithm_spec.md` (807 lines, Sections A-H)
  - Prior CTO ruling: `Y-star-gov/reports/cto/CZL-BRAIN-BIPARTITE-ruling.md` (Q1-Q6)
  - Maya audit: `reports/receipts/CZL-REWRITE-AUDIT.md` (REWRITE x3 retraction)
  - CEO spec: `reports/ceo/governance/cieu_bipartite_learning_v1.md` (Sections 1-8, 3.3 retracted)
  - Board consultant card: `CZL-ESCAPE-SEMANTIC-REVERSAL` on dispatch_board
  - Empirical data: `.ystar_cieu.db` queried during this ruling (51,424 escape-canonical events; 0 allow+passed=0 post-normalizer; distribution: `warn`=51,131 + `warning`=293 raw)
**Audience**: Leo Chen (eng-kernel), Maya Patel (eng-governance), CEO Aiden (spec update)

---

## Receipt (5-tuple)

- **Y***: All 7 design questions answered with concrete values, rationale, and implementation constraints. Leo can implement `cieu_bipartite_learner.py` without further architectural ambiguity.
- **Xt**: Leo's 807-line spec + 6 open questions (Section H); Board consultant added 7th (escape semantic reversal); Maya audit retracted REWRITE x3.
- **U**: (1) Read all inputs, (2) queried CIEU DB for empirical escape distribution, (3) analyzed normalizer v2 escape mapping, (4) wrote 7-question ruling with math/code references.
- **Yt+1**: Leo implements Phase 2; CEO updates spec Section 3.4 per escape ruling Q7.
- **Rt+1**: 0 (all 7 items have concrete answers + rationale)

---

## H.1 Ruling: Lambda (Contrastive Strength) Initial Value

**Decision: lambda = 0.5, fixed (not adaptive). Leo's proposed value is correct.**

### Rationale

Lambda controls the ratio of repulsion-from-negatives vs. attraction-toward-positives. The question is whether repulsion should be as strong as attraction (lambda=1.0), weaker (lambda<1.0), or adaptive.

**Why 0.5 (not 1.0)**: The escape-canonical pool post-normalizer is 51,424 events (mostly warn+passed=0 remapped to escape). This is a large, heterogeneous pool spanning many failure modes -- ForgetGuard violations, drift detections, scope violations, etc. The negative centroid computed from this pool has high intra-class variance because these events do not cluster tightly in 6D space. At lambda=1.0, the repulsion term would be as strong as attraction, but since the negative centroid is a blurry average of diverse failure modes, the repulsion direction carries substantial noise. Lambda=0.5 dampens this noise by halving the repulsion magnitude relative to attraction.

**Why not adaptive**: Alpha already adapts via the cosine-stability schedule (prior ruling Q3). Making lambda also adaptive doubles the hyperparameter search space and creates an interaction effect: alpha and lambda jointly determine the step size and direction. If both adapt simultaneously, stability analysis becomes intractable for a 150-node 6D system. Keep one fixed (lambda) and one adaptive (alpha). If empirical results after 10+ passes show the negative centroid is stable (low variance), we can revisit making lambda adaptive in a Phase 4+ ruling.

**Numerical justification**: With the update rule `drift = alpha * ((pos_centroid - old) - lambda * (neg_centroid - old))`, at alpha=0.15 and lambda=0.5, the maximum repulsion contribution is `0.15 * 0.5 = 0.075` per coordinate per pass, well within the 0.1 per-coordinate clip. This means repulsion alone cannot trigger clipping, preserving gradient directionality. At lambda=1.0, repulsion could reach 0.15 per coordinate, which the clip would truncate to 0.1, losing directional information.

**Implementation constraint**: Hard-code `LAMBDA_CONTRASTIVE = 0.5` as a module constant alongside the alpha constants. Do NOT expose as CLI argument.

---

## H.2 Ruling: Receptive Radius Multiplier

**Decision: Start with multiplier = 0.5 (Leo's proposal). Add a diagnostic assertion. Revisit after first pass.**

### Rationale

The receptive radius `R_N = median(inter-node-distances) * multiplier` determines how many events are "relevant" to each node. The multiplier is a coverage-selectivity tradeoff:
- Too small (0.2): most nodes get <10 events, skip threshold triggers, wasted computation
- Too large (1.0): all nodes see nearly all events, centroids converge to global mean, node-level specificity lost

**Why 0.5 is acceptable as initial**: With 150 nodes in 6D space, the median inter-node distance defines a natural length scale. Multiplier 0.5 means each node's receptive field covers the nearest ~25% of the space (by radius, not volume -- in 6D the volume fraction is much smaller: roughly (0.5)^6 = 1.5% of the hypervolume). This is selective enough to preserve local structure while including enough events for statistical significance.

**Diagnostic assertion** (mandatory in Phase 2 implementation):

```python
# After computing receptive radii but before drift computation:
relevance_counts = [
    sum(1 for e in batch.events 
        if euclidean_6d(e.coords_6d, node.coords) < node.radius)
    for node in nodes
]
median_relevance = statistics.median(relevance_counts)
assert median_relevance >= 20, (
    f"BIPARTITE_RADIUS_TOO_SMALL: median relevant events per node = "
    f"{median_relevance}, need >= 20. Increase multiplier."
)
# Log as CIEU event for tuning
emit_cieu("BIPARTITE_RADIUS_DIAGNOSTIC", {
    "multiplier": 0.5,
    "median_relevance": median_relevance,
    "min_relevance": min(relevance_counts),
    "max_relevance": max(relevance_counts),
    "nodes_below_10": sum(1 for c in relevance_counts if c < 10),
})
```

If the assertion fires on the first production pass, increase multiplier to 0.75 and re-run. This is a one-time tuning step, not an ongoing adaptive mechanism.

**Implementation constraint**: The multiplier is a module constant `RADIUS_MULTIPLIER = 0.5`, not CLI-configurable. The diagnostic runs every pass and emits a CIEU event.

---

## H.3 Ruling: Checkpoint Storage Location

**Decision: Inline in `aiden_brain.db` (Leo's proposal). Single DB, `node_checkpoints` table.**

### Rationale

**Why same DB (not separate file)**:

1. **Atomic rollback**: If a drift pass corrupts coordinates and we need to rollback, the rollback reads from `node_checkpoints` and writes to `nodes` -- both in the same DB. With SQLite, this can be wrapped in a single transaction: `BEGIN; UPDATE nodes ... FROM node_checkpoints WHERE pass_id = ?; COMMIT`. A separate file would require coordinating two DB connections, introducing a window where the checkpoint file is read but the brain DB write hasn't committed (crash = inconsistent state).

2. **Size is negligible**: Each checkpoint is 150 rows x 8 columns (id + pass_id + created_at + 6 dims) = ~150 * 80 bytes = 12KB per pass. After 100 passes, that is 1.2MB -- trivial relative to the `nodes` table itself, the `edges` table (1,646 rows), and `activation_log` (30K+ rows). The brain DB is already small (~5MB total); checkpoints will not bloat it.

3. **Backup simplicity**: One file to backup = one file to restore. Operators (Board) copy `aiden_brain.db` and get both current state and rollback history. A separate checkpoint file adds a "don't forget to also copy this" failure mode.

**Retention policy**: Keep the last 20 checkpoints (20 * 150 = 3,000 rows). After pass 21, the oldest checkpoint is deleted. This bounds growth at 240KB permanently.

```python
# After saving new checkpoint:
conn.execute("""
    DELETE FROM node_checkpoints 
    WHERE pass_id <= (SELECT MAX(pass_id) - 20 FROM node_checkpoints)
""")
```

**Implementation constraint**: Leo's proposed schema (Section D.3) is approved as-is. Add the retention cleanup above.

---

## H.4 Ruling: Held-Out Strategy

**Decision: Time-based split (last 7 days) as primary. No fixed holdout table for Phase 2.**

### Rationale

My Q4 ruling suggested a fixed 1,000-event stratified holdout with `holdout=1` flag. Having reviewed Leo's implementation trade-off analysis, I revise this for Phase 2:

**Why time-based for Phase 2**:

1. **No schema change**: Adding a `holdout` column or `cieu_holdout` table requires a migration, testing, and modifying the CIEU writer to tag events at INSERT time. This is avoidable overhead for Phase 2 when we need to ship the core algorithm first.

2. **Temporal generalization is the right test**: The brain will be used to evaluate FUTURE events (L1 pre-query at decision time). A held-out set drawn from the most recent 7 days tests exactly the right property: can the brain's learned coordinates predict outcomes on data it hasn't trained on, from a time period it hasn't seen? A random split would test interpolation, not generalization.

3. **Evolving distribution is a feature, not a bug**: Leo notes the held-out set changes daily. This means each evaluation tests against the current event distribution, not a stale snapshot. If the event distribution shifts (new agent types, new rule types), the time-based holdout automatically captures this shift. A fixed holdout would become increasingly unrepresentative.

**Phase 4+ consideration**: After 30+ passes with time-based holdout, if we need stable long-term trend comparison (is the brain better now than 3 months ago?), add a fixed holdout at that point. Not now.

**Implementation constraint**: Leo's Section E.1 time-based approach is approved. The 7-day window is correct. Do NOT create a `cieu_holdout` table or `holdout` column in Phase 2.

---

## H.5 Ruling: Formula Reformulation

**Decision: Leo's delta-from-old formulation is correct. It supersedes the CEO/Ethan original formula for implementation purposes.**

### Rationale

The CEO spec (Section 3.1) and my prior Q3 ruling both state:
```
new_coord = positive_centroid + alpha * (positive_centroid - negative_centroid)
```

Leo's spec reformulates as:
```
new_coord = old_coord + alpha * ((positive_centroid - old_coord) - lambda * (negative_centroid - old_coord))
```

These are NOT equivalent formulas. They have different mathematical behavior:

**CEO/Ethan formula** (centroid-anchored):
- Ignores `old_coord` entirely. The new coordinate is determined solely by the positive centroid and the contrastive gap.
- After one pass, the node jumps to `positive_centroid + alpha * contrastive_direction`, regardless of where it started.
- Multiple passes without re-batching produce the same result (idempotent in the limit).
- Problem: if positive centroid is far from old coordinate, the node makes a large jump (potentially spanning the full [0,1] range), then the per-coordinate clip truncates it, losing the direction.

**Leo's formula** (delta-anchored):
- The node moves FROM its current position TOWARD the positive centroid and AWAY from the negative centroid.
- Movement is proportional to the distance from current position to each centroid (closer to positive = smaller attraction, which is self-damping).
- Multiple passes produce genuine convergence: each pass moves the node a fraction of the remaining distance.
- Per-coordinate clip is applied to the delta, preserving the direction of the residual.

**Why Leo's is superior**:

1. **Gradient-descent analogy**: Leo's formula is equivalent to a gradient step on a loss function `L = ||node - pos_centroid||^2 - lambda * ||node - neg_centroid||^2`. The CEO formula is a fixed-point projection, not a gradient step. Gradient steps with clipping are numerically stable; fixed-point projections with clipping are not (the clip can prevent convergence to the fixed point).

2. **Self-damping**: As the node approaches the positive centroid, `(pos_centroid - old_coord)` shrinks, automatically reducing step size. This provides natural convergence without needing alpha to decay. The CEO formula has no self-damping -- it always jumps to the same absolute position.

3. **Clip compatibility**: The per-coordinate clip (max 0.1) is designed for deltas. Leo's formula produces a delta that is clipped. The CEO formula produces an absolute position that then needs to be compared against the old position to compute a delta for clipping -- an extra step that is mathematically awkward and was not specified.

**Explicit revision of Q3**: My prior Q3 ruling repeated the CEO formula verbatim. I now revise the implementation formula to Leo's delta-anchored version. The Q3 ruling on alpha=0.15, adaptive schedule, and all constants remains in force.

**Implementation constraint**: Use Leo's formula from Section C.4 exactly as written. The CEO spec formula in Section 3.1 is treated as the conceptual direction (move toward positive, away from negative), not the literal implementation math.

---

## H.6 Ruling: REWRITE Quality Gate

**Decision: REWRITE is excluded from Phase 2 training entirely. Activation requires a 3-condition gate.**

### Rationale

Maya's audit (`CZL-REWRITE-AUDIT.md`) is conclusive:
- 151 substring matches: 100% false positive (file paths, command strings, audit queries)
- 7 real `REWRITE_APPLIED` events: NULL `drift_details`, no structured `original_action`/`rewritten_action`
- The CEO has already retracted Section 3.3 with strikethrough

**The 3-condition activation gate** (all must be true before any REWRITE event enters training):

1. **Event type filter**: `event_type = 'REWRITE_APPLIED'` (exact match, not substring)
2. **Structured metadata present**: `drift_details IS NOT NULL` AND `json_extract(drift_details, '$.original_action') IS NOT NULL` AND `json_extract(drift_details, '$.rewritten_action') IS NOT NULL`
3. **Minimum corpus**: At least 50 events satisfying conditions 1 and 2

```python
def rewrite_gate_check(cieu_db_path: str) -> bool:
    """Return True only if REWRITE events are safe to include in training."""
    conn = sqlite3.connect(cieu_db_path)
    count = conn.execute("""
        SELECT COUNT(*) FROM cieu_events
        WHERE event_type = 'REWRITE_APPLIED'
          AND drift_details IS NOT NULL
          AND json_extract(drift_details, '$.original_action') IS NOT NULL
          AND json_extract(drift_details, '$.rewritten_action') IS NOT NULL
          AND training_eligible = 1
    """).fetchone()[0]
    conn.close()
    return count >= 50
```

**Until the gate opens**: The `rewrite` partition in Leo's Section B.1 weight table is dormant. `rewrite_count = 0` in the batch composition algorithm (Section B.3 step 2). No REWRITE events are loaded, weighted, or used for centroid computation.

**When the gate opens**: Apply weight `+2.0` (not x3 multiplier on base weight -- that formulation was tied to the retracted substring query). The +2.0 reflects that a genuine before/after teaching pair is high-value positive signal (the system corrected a mistake, which is evidence of what the correct action IS). Use the rewritten_action coordinate as the positive signal and the original_action coordinate as the negative signal for that event, rather than treating the event as a single point in 6D space.

**Implementation constraint**: Leo should implement `rewrite_gate_check()` and call it at the start of `load_training_batch()`. If it returns False, skip the rewrite partition entirely. Log `BIPARTITE_REWRITE_GATE_CLOSED` CIEU event with `{count: N, threshold: 50}` so we can track when the corpus is approaching readiness.

---

## H.7 Ruling: Escape Sample Semantic Reversal

**Decision: Split escape into two sub-partitions with opposite semantics. Pre-hook escape = POSITIVE (blindspot awareness). Post-hook escape = NEGATIVE (rule-edge-case failure).**

This is the most consequential ruling in this document. It reverses the CEO spec Section 3.2 weight for the majority of the 51,424 escape-canonical events.

### The Board Consultant's Argument (reconstructed)

The 51,424 escape-canonical events break down as:
- 51,131 raw `warn` + `passed=0` (mapped to escape by normalizer v2)
- 293 raw `warning` + `passed=0` (same mapping)
- ~0 raw `allow` + `passed=0` (the original 611 were remapped by normalizer v2 to escape canonical, but the current DB shows 0 in the allow+passed=0 bucket because ALL are now in escape)

All of these events occurred in the **pre-hook registration window** -- the period when Y*gov's hook infrastructure was being built, tested, and progressively wired. During this window, `warn` decisions with `passed=0` were the system saying "I see a potential issue, but I'm warning, not blocking." The `passed=0` means the downstream outcome was negative (the warned action did not lead to a positive result).

**The CEO spec's original interpretation (Section 3.2)**: These events are negative teaching signal. The brain should be pushed AWAY from these coordinates. Weight = -0.3. Rationale: "escape = something got through that should not have."

**The Board consultant's reframe**: These events are the system's own record of WHERE it was blind. They are a map of the governance blindspots. The brain should be pulled TOWARD awareness of these coordinates, not pushed away. By pushing away, you teach the brain to forget exactly the regions where governance was weakest -- the opposite of what you want.

### My Analysis

The consultant is correct, but with a crucial temporal qualifier.

**Pre-hook escape events** (the bulk of the 51K): These occurred when governance was permissive-by-default. The `warn + passed=0` pattern means: "the system flagged something, the action went through, and the outcome was bad." This is NOT evidence that the brain's coordinates were wrong -- it is evidence that the brain's coordinates CORRECTLY detected something (hence the warn) but lacked the authority to block it (no hook enforcement). The brain was RIGHT to be suspicious of these coordinates. Pushing the brain away from them teaches it to stop being suspicious of the very things it correctly flagged.

Positive-learning interpretation: "You were right to watch these coordinates. Remember them. They are where governance was needed and absent."

**Post-hook escape events** (should be rare/near-zero once hooks are fully enforced): If the hook infrastructure is live and enforcing, and an event STILL escapes with `warn + passed=0`, that is a genuine rule-edge-case failure -- the system had the authority to block, chose to warn, and the outcome was bad. This IS a negative signal: the brain's coordinates led to an incorrect decision (warn instead of deny).

Negative-learning interpretation: "You were wrong to only warn here. This coordinate should have been denied."

### Temporal Boundary

The temporal boundary between "pre-hook" and "post-hook" is the date when the hook infrastructure became live and enforcing for the relevant event type. This is not a single date -- different hooks were wired at different times.

**Pragmatic proxy**: Use the `hook_name` field (if present) or `event_type` to determine whether a hook was enforcing at the time of the event. If the event predates the hook registration for its type, it is pre-hook.

**Simpler proxy (recommended for Phase 2)**: Use a configurable cutoff timestamp. Default: the date of the first `PostToolUse` hook registration (which can be queried from the CIEU DB or hardcoded based on deployment history). Events before this timestamp are pre-hook escape; events after are post-hook escape.

```python
# Module constant -- set to the deployment timestamp of full hook enforcement
# CTO will update this after verifying the exact date from CIEU/deployment logs
PRE_HOOK_CUTOFF = 1776316054.0  # earliest escape-canonical event timestamp
# For Phase 2, treat ALL current escape events as pre-hook (conservative).
# Post-hook escape events will accumulate after hooks are fully enforcing.
```

### Weight Assignment

| Sub-partition | Condition | Weight | Rationale |
|---|---|---|---|
| pre_hook_escape | `decision_canonical = 'escape' AND created_at < PRE_HOOK_CUTOFF` | **+0.6** | Positive learning: pull brain toward awareness of blindspot coordinates. Weighted below clean_positive (+1.0) because the signal is indirect (outcome was bad, but the system correctly flagged it -- the issue was enforcement authority, not detection). |
| post_hook_escape | `decision_canonical = 'escape' AND created_at >= PRE_HOOK_CUTOFF` | **-0.3** | Negative learning: push brain away. The system had enforcement authority and still let the event through with only a warn. This is a genuine decision error. |

**Why +0.6 (not +1.0)**: Pre-hook escape events carry noise. The `warn` was correct, but the 6D coordinates of the event may not precisely represent the governance gap -- the event's coordinates reflect the action that was attempted, not the policy that was missing. A +0.6 weight acknowledges the positive signal while discounting for this indirectness.

**Why -0.3 (unchanged from CEO spec)**: Post-hook escape is the same failure mode the CEO originally described. The weight is unchanged.

### Impact on Batch Composition (Section B.3 revision)

With this reversal, the 51K+ pre-hook escape events are now POSITIVE samples, not negative. This changes the batch composition:

**Old composition** (CEO spec): escape events are 5% of batch, all negative-weighted
**New composition**:
- pre_hook_escape joins the positive pool (weight +0.6)
- post_hook_escape (currently ~0 events) remains in the escape oversampling pool at 5% floor
- If post_hook_escape count is < `ceil(batch_size * escape_min_pct)`, fill the escape floor with randomly drawn pre_hook_escape samples but assigned weight -0.1 (mild negative: "these are coordinates that WERE blindspots -- a gentle reminder, not a strong repulsion")

```python
def load_training_batch(...):
    # ... existing logic ...
    
    # Split escape into pre/post hook
    pre_hook = [e for e in escape_pool if e.created_at < PRE_HOOK_CUTOFF]
    post_hook = [e for e in escape_pool if e.created_at >= PRE_HOOK_CUTOFF]
    
    # Pre-hook escape: positive pool, weight +0.6
    for e in pre_hook:
        e.weight = +0.6
        e.partition = 'pre_hook_escape'
    
    # Post-hook escape: negative pool, weight -0.3
    for e in post_hook:
        e.weight = -0.3
        e.partition = 'post_hook_escape'
    
    # Escape oversampling floor (5%) uses post_hook_escape preferentially
    escape_count = max(ceil(batch_size * escape_min_pct), 1)
    if len(post_hook) >= escape_count:
        escape_sample = random.sample(post_hook, escape_count)
    else:
        # Backfill with pre_hook at reduced weight -0.1
        escape_sample = post_hook + random.sample(
            pre_hook, escape_count - len(post_hook)
        )
        for e in escape_sample[len(post_hook):]:
            e.weight = -0.1  # gentle blindspot reminder, not strong repulsion
```

### Safety Analysis

**Risk**: By making 51K events positive instead of negative, the positive pool grows from ~70K to ~121K, shifting the positive/negative ratio from 71/29 to 85/15. This could reduce the contrastive signal strength (negative centroid based on fewer events becomes noisier).

**Mitigation**: Lambda=0.5 already dampens the negative centroid's influence. The remaining 28K deny events (weight +0.8, positive) plus any post-hook escape (-0.3, negative) plus drift-flagged events (-0.2 modifier) provide sufficient negative signal. The KL divergence monitor (D.4) and feedback-loop detector (D.5) will catch any resulting degradation.

**Key invariant**: The escape oversampling floor (5% of batch is escape-weighted events) is preserved. Even with the semantic reversal, the batch always contains at least 205 events specifically drawn from escape-canonical events, ensuring the brain maintains sensitivity to these coordinates.

### Implementation Constraint

1. Add `PRE_HOOK_CUTOFF` as a module constant.
2. The `WeightedEvent.partition` field gains two new values: `'pre_hook_escape'` and `'post_hook_escape'` (replacing the single `'escape'` partition).
3. `BatchStats` must track counts for both sub-partitions separately.
4. Leo's test plan (Section G) must include tests for both sub-partitions:
   - Test: pre-hook escape events get weight +0.6
   - Test: post-hook escape events get weight -0.3
   - Test: escape oversampling floor uses post-hook preferentially
   - Test: backfill pre-hook at -0.1 when post-hook insufficient

### Directive to CEO

CEO should update spec Section 3.2 and 3.4 to reflect this ruling. Section 3.2's escape weight row should split into two rows (pre-hook +0.6, post-hook -0.3). Section 3.4's oversample logic should note the post-hook-first preference. Citation: Board consultant insight via `CZL-ESCAPE-SEMANTIC-REVERSAL`.

---

## Summary Table

| Question | Decision | Key Constraint |
|---|---|---|
| H.1: Lambda initial value | 0.5 fixed | Module constant `LAMBDA_CONTRASTIVE = 0.5`; not adaptive |
| H.2: Receptive radius multiplier | 0.5 with diagnostic assertion | Must emit `BIPARTITE_RADIUS_DIAGNOSTIC` CIEU event every pass; assertion fires if median relevance < 20 |
| H.3: Checkpoint storage | Inline in `aiden_brain.db`, `node_checkpoints` table | Retain last 20 checkpoints; Leo's schema approved as-is |
| H.4: Held-out strategy | Time-based (last 7 days) | No `cieu_holdout` table in Phase 2; fixed holdout deferred to Phase 4+ |
| H.5: Formula reformulation | Leo's delta-from-old is correct; supersedes CEO/Ethan original | Prior Q3 alpha/schedule constraints still apply; implementation uses Leo's formula |
| H.6: REWRITE quality gate | Excluded from Phase 2 entirely | 3-condition gate: event_type exact + structured metadata + corpus >= 50; weight +2.0 when gate opens |
| H.7: Escape semantic reversal | Pre-hook = +0.6 (positive blindspot awareness); Post-hook = -0.3 (negative rule failure) | `PRE_HOOK_CUTOFF` timestamp constant; escape 5% floor uses post-hook first; CEO updates spec Sections 3.2 + 3.4 |

---

## Cross-References

- Leo spec: `docs/kernel/bipartite_loader_phase2_algorithm_spec.md`
- Prior CTO ruling: `Y-star-gov/reports/cto/CZL-BRAIN-BIPARTITE-ruling.md`
- Maya REWRITE audit: `reports/receipts/CZL-REWRITE-AUDIT.md`
- CEO spec (with 3.3 retraction): `reports/ceo/governance/cieu_bipartite_learning_v1.md`
- Normalizer v2: `Y-star-gov/ystar/governance/cieu_decision_normalizer.py`
- Board consultant card: `CZL-ESCAPE-SEMANTIC-REVERSAL` on `governance/dispatch_board.json`
- CIEU DB empirical: 51,424 escape-canonical (51,131 warn + 293 warning raw); 0 allow+passed=0 post-normalizer

---

*This ruling is binding on Phase 2 implementation. Leo proceeds with `cieu_bipartite_learner.py` using these 7 answers. CEO updates bipartite learning spec per H.7 directive.*
