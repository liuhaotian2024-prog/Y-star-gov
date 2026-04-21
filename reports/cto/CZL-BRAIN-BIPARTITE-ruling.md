# CZL-BRAIN-BIPARTITE Architectural Ruling

**Author**: Ethan Wright (CTO)
**Date**: 2026-04-19
**Status**: RULING (binding on implementation)
**Inputs**: CEO spec `reports/ceo/governance/cieu_bipartite_learning_v1.md` Sections 1-7; ARCH-17 canonical; ARCH-18 corpus characterization; `aiden_brain.py` Hebbian sub-system; `.ystar_cieu.db` (401,729 events at time of ruling)
**Audience**: Leo Chen (eng-kernel, normalizer + loader), Maya Patel (eng-governance, outcome weighting + oversample), CEO (validation)

---

## Ruling Q1: Hebbian Compatibility -- Retrofit, Parallel, or Replace?

**Decision: Run parallel, then converge.**

### Rationale

The existing Hebbian sub-system in `scripts/aiden_brain.py` (lines 150-173, function `hebbian_update`) operates on a fundamentally different substrate than the bipartite contrastive system:

| Property | Current Hebbian | Bipartite Contrastive |
|---|---|---|
| Data source | Co-activation of knowledge nodes during recall | CIEU governance events (401K+ rows) |
| Update trigger | `record_co_activation()` called by `aiden_recall.py --learn` | Batch processing of bipartite (passed=0/1) labeled events |
| Weight semantics | Edge weight in [0, 1] between knowledge nodes | 6D coordinate shift of nodes toward/away from event centroids |
| Learning signal | Binary: nodes fired together | Signed: +1.0 (clean pass), -0.3 (escape), etc. per CEO spec 3.2 |
| Decay | Flat subtraction (`apply_decay`, line 288, `weight - 0.01`) | None proposed (contrastive drift is directional, not decaying) |
| Storage | `edges` table in `aiden_brain.db` (1,646 edges, 434 Hebbian) | Would update `nodes` table 6D coordinates (dim_y through dim_c) |

**Why not retrofit**: The Hebbian system's `hebbian_update` function (line 150) strengthens *edge weights* between node pairs using the formula `new_w = min(1.0, old_w + lr * (1.0 - old_w))`. The bipartite system needs to shift *node coordinates* in 6D space using contrastive centroids. These are mathematically orthogonal operations -- one modifies edges, the other modifies nodes. Retrofitting would conflate two distinct learning signals into a single update path, making it impossible to attribute coordinate changes to their cause (Hebbian co-firing vs. governance outcome).

**Why not replace**: The Hebbian system has 434 learned edges encoding genuine co-activation patterns from 10+ days of CEO sessions. Destroying this is information loss. Additionally, the Hebbian system serves a different cognitive function: it captures *which knowledge items are used together* (associative memory), while the bipartite system captures *which governance decisions were correct* (evaluative memory). Both are needed.

**Convergence path**: After bipartite system runs for 30+ sessions and produces measurable coordinate shifts, evaluate whether Hebbian edge weights should be modulated by bipartite node coordinates. Specifically: if two nodes are Hebbian-linked but one has been pushed toward negative centroid (many governance failures in its domain), dampen the edge weight. This is Phase 5+ work, not Phase 1.

**Implementation constraint for Leo/Maya**: Create a new module `cieu_bipartite_learner.py` that reads from `cieu_events` and writes to `nodes.dim_*` columns in `aiden_brain.db`. Do NOT modify `hebbian_update()` or `apply_decay()` in `aiden_brain.py`. The two systems share the `nodes` table but update different columns: Hebbian updates `edges`, bipartite updates `nodes.dim_*`.

---

## Ruling Q2: `decision_canonical` Column Placement -- Migration vs. Materialized View

**Decision: In-table migration (ALTER TABLE ADD COLUMN).**

### Rationale

The CEO spec correctly leans migration. Here is the engineering justification:

**Query performance on 401K+ rows**: The bipartite loader will run queries like `SELECT * FROM cieu_events WHERE decision_canonical = 'allow' AND passed = 1` on every training batch. With a materialized view, this requires a JOIN or subquery against the view for every read. With an in-table column + index, it is a single B-tree lookup. At 401K rows growing at 40-80K/day, the performance difference compounds. SQLite materialized views are not truly materialized -- they are just saved queries that re-execute on read. A CTE or VIEW in SQLite is always virtual, never cached.

**Write amplification**: Adding a column via `ALTER TABLE ADD COLUMN decision_canonical TEXT` is a metadata-only operation in SQLite -- it does NOT rewrite existing rows. The column starts as NULL for all existing rows. A one-time backfill `UPDATE cieu_events SET decision_canonical = normalize(decision)` touches all 401K rows once. Subsequent inserts set the column at write time (single write, no amplification). A materialized view would require either: (a) a trigger to maintain the view on every INSERT, which is equivalent write cost plus trigger overhead, or (b) periodic refresh, which introduces staleness.

**Rollback cost**: If the normalizer mapping proves wrong, `UPDATE cieu_events SET decision_canonical = NULL` and re-run. The original `decision` column is never modified (audit trail preserved, per CEO spec Section 2). Dropping a column in SQLite requires table rebuild, but we would never drop -- we would just stop reading it.

**Implementation constraints for Leo**:

1. Migration script adds column:
```sql
ALTER TABLE cieu_events ADD COLUMN decision_canonical TEXT;
CREATE INDEX idx_decision_canonical ON cieu_events(decision_canonical);
```

2. Backfill existing rows using the canonical mapping from CEO spec Section 2. Run as a single transaction to avoid partial state.

3. Modify the CIEU writer (wherever new events are INSERTed) to populate `decision_canonical` at write time. The normalizer function must be importable and called inline, not via post-hoc batch.

4. Add the column to the `cieu_ai` FTS trigger (line visible in schema) so full-text search covers canonical decisions.

5. Do NOT modify the existing `decision` column or its index. Both coexist.

---

## Ruling Q3: alpha (Contrastive Drift Scale) Initial Value -- 0.15 or 0.25?

**Decision: alpha = 0.15, with adaptive schedule.**

### First-Principles Argument

The contrastive drift formula is:
```
new_coord = positive_centroid + alpha * (positive_centroid - negative_centroid)
```

The term `(positive_centroid - negative_centroid)` is the *contrastive direction* -- the vector pointing from "where failures cluster" to "where successes cluster" in 6D node space. alpha scales how far past the positive centroid we push.

**Why not 0.25**: At alpha = 0.25, each training step pushes node coordinates 25% of the contrastive gap beyond the positive centroid. With our corpus imbalance (71.2% positive, 28.8% negative), the positive centroid is already well-established but the negative centroid is noisier (fewer samples, more heterogeneous failure modes). A noisy negative centroid means the contrastive direction itself has high variance. Amplifying a noisy direction by 0.25 risks oscillation -- one batch's negative centroid may point in a substantially different direction from the next batch's, causing coordinates to jitter.

**Why 0.15**: The 0.15 value provides meaningful contrastive pull (non-degenerate, unlike alpha = 0) while keeping the step size below the estimated noise floor of the contrastive direction. With 113,369 negative samples across heterogeneous failure modes (circuit_breaker: 14.6K, intervention_gate: 12K, external_observation: 7.3K, etc.), the negative centroid has high intra-class variance. A conservative step size lets the centroid stabilize over multiple batches before large coordinate shifts accumulate.

**Bayesian prior from analogous systems**: In contrastive learning literature (SimCLR, MoCo), the temperature parameter (analogous to alpha in controlling the strength of repulsion from negatives) is typically initialized conservatively (tau = 0.07-0.1 in SimCLR, corresponding to strong but not extreme contrast). Our alpha = 0.15 maps to moderate contrast, consistent with these priors when adjusted for our much smaller embedding dimension (6D vs. 128-2048D in vision models -- lower dimensions are more sensitive to perturbation).

**Adaptive schedule**: After each full-corpus training pass, compute the cosine similarity between successive contrastive directions (the `positive_centroid - negative_centroid` vector from batch N vs. batch N+1). If cosine similarity > 0.8 for 3 consecutive passes (stable direction), increase alpha by 0.05 up to max 0.30. If cosine similarity < 0.5 (direction unstable), decrease alpha by 0.05 down to min 0.10. Log every alpha change as a CIEU event for audit.

**Implementation constraint**: Hard-code `ALPHA_INITIAL = 0.15`, `ALPHA_MIN = 0.10`, `ALPHA_MAX = 0.30`, `ALPHA_STEP = 0.05`, `COSINE_STABLE_THRESHOLD = 0.8`, `COSINE_UNSTABLE_THRESHOLD = 0.5`, `STABILITY_WINDOW = 3` as module constants. Do not expose alpha as a CLI argument -- it must be adaptive-only to prevent manual over-tuning.

---

## Ruling Q4: Feedback-Loop Detector Divergence Threshold Metric

**Decision: KL divergence on decision distribution, with cosine on centroid trajectory as secondary alarm.**

### Why KL Divergence (Primary)

The feedback-loop we are guarding against is: the brain increasingly agrees with itself, producing a narrowing decision distribution that converges to a point mass on whatever decision it most frequently saw in training. This is precisely what KL divergence measures -- the information-theoretic distance between two distributions.

**Concrete definition**: Let `D_now` be the distribution of `decision_canonical` values the brain would assign to a held-out test set of 1,000 events, and let `D_30d` be the same distribution using 30-day-old brain weights on the same test set.

```
DKL(D_now || D_30d) = SUM_d D_now(d) * log(D_now(d) / D_30d(d))
```

If `DKL > 0.10 nats` AND the production outcome metrics (actual pass rate on new events) have not improved proportionally, flag as feedback-loop drift.

**Why the AND condition**: KL divergence alone is insufficient. The brain *should* change its decision distribution over time as it learns from new data. Divergence that correlates with improved outcomes is learning, not feedback-loop drift. The alarm fires only when divergence is high but outcomes are flat or worsening.

### Why Not L2 on Weight Deltas

L2 on weight deltas (`||W_now - W_30d||_2`) measures how much the model changed, not whether the change is pathological. A large L2 could indicate healthy learning (many new failure patterns incorporated) or unhealthy drift (feedback loop). It lacks the directional information needed to distinguish the two.

Additionally, "weights" in our system are 6D node coordinates (6 floats per node) and edge weights (1 float per edge). L2 across these heterogeneous dimensions is not physically meaningful without careful normalization, and the normalization itself introduces arbitrary choices.

### Why Not Cosine on Centroid Trajectory (Primary)

Cosine similarity between successive contrastive centroids measures whether the *direction* of learning is stable. This is useful (and is already used in the alpha adaptive schedule above), but it measures a different thing than feedback-loop drift. A stable direction could be either healthy (consistently learning the same lesson, which is correct) or pathological (consistently reinforcing the same bias). Cosine cannot distinguish these cases.

**However**, cosine on centroid trajectory is a useful *secondary* alarm: if the contrastive direction has been identical (cosine > 0.95) for 10+ consecutive passes AND KL divergence is rising, this is strong evidence of a feedback loop (the brain is monotonically moving in one direction without self-correction).

### Implementation Constraints

1. Hold out 1,000 events (stratified sample: 712 passed=1, 288 passed=0, matching corpus ratio) as the fixed test set. These events are NEVER used for training. Tag them with a `holdout=1` flag in a new column or a separate `cieu_holdout` table.

2. After each full training pass, compute `D_now` by running the brain's decision prediction on the holdout set. Store the distribution as a CIEU event (`event_type = 'BRAIN_DIVERGENCE_CHECK'`).

3. Compare against the distribution stored 30 days ago (or the earliest available if brain is younger than 30 days).

4. Thresholds:
   - `DKL > 0.10` AND outcome flat/worsening: WARN, log to CIEU
   - `DKL > 0.20` AND outcome flat/worsening: FREEZE training, emit `FEEDBACK_LOOP_ALARM` CIEU event, require CTO review before resuming
   - `DKL > 0.10` AND outcome improving: No alarm (healthy learning)

---

## Ruling Q5: Order-of-Operations -- Normalizer (Phase 1) vs. DISPATCH-EXEC Fix (CZL-DISPATCH-EXEC)

**Decision: Normalizer (Phase 1) ships first. DISPATCH-EXEC is independent and can proceed in parallel but is not a prerequisite.**

### Rationale

The normalizer is a data-quality prerequisite for ALL downstream bipartite work (Phases 2-6). Without canonical decisions, the bipartite loader cannot correctly partition events into positive/negative/escape/rewrite buckets. The CEO spec's Section 1 empirical data shows 20+ raw decision values including case variance (`ALLOW` vs `allow`), near-synonyms (`warn` vs `warning`), and corruption (embedded JSON). Training on un-normalized decisions would bake noise into the brain from day one.

CZL-DISPATCH-EXEC (dispatch reliability) is a process-infrastructure fix that improves how tasks get assigned to engineers. It does not touch the CIEU data pipeline. There is no data dependency in either direction:
- Normalizer does not need DISPATCH-EXEC to run (it reads `.ystar_cieu.db` directly)
- DISPATCH-EXEC does not need normalizer (it operates on task dispatch, not CIEU learning)

**Implementation order**:

1. Leo ships normalizer + migration (Phase 1) -- unblocks all bipartite work
2. Maya ships bipartite loader with 5 strategies (Phase 2) -- depends on Phase 1
3. CZL-DISPATCH-EXEC proceeds in parallel on a separate engineer track

**Constraint**: Leo must NOT block on CZL-DISPATCH-EXEC. If dispatch infrastructure is broken, CEO can dispatch normalizer work directly to Leo via task card as an exception (per `feedback_dispatch_via_cto.md`, CTO authorizes this specific bypass because the CTO is the one issuing this ruling).

---

## Ruling Q6: Guard Against Self-Referential Training

**Decision: Provenance tagging + exclusion filter.**

### Problem Statement

The bipartite training data includes CIEU events generated BY the brain system itself. Examples:
- `BRAIN_DIVERGENCE_CHECK` events (from the feedback-loop detector)
- `CIEU_BRAIN_QUERY` events (from boot context injection)
- Any future `BRAIN_*` prefixed events from the bipartite learner itself
- `activation_log` entries that get cross-referenced into CIEU

If the brain trains on its own outputs, it creates a self-reinforcing loop that is more insidious than the Tesla-style feedback loop the CEO spec addresses: the brain would literally optimize to produce outputs that look good to itself.

### Concrete Guard

**1. Provenance tag on all brain-generated CIEU events**: Every CIEU event emitted by any brain/learning component must include `agent_id = 'system:brain'` (or a `system:brain_*` prefix). This is a hard constraint on all brain-related code.

**2. Exclusion filter in the bipartite loader**: The bipartite loader's data query must include `WHERE agent_id NOT LIKE 'system:brain%'`. This is a non-negotiable filter, not a configurable option.

**3. Broader system-event exclusion**: Extend the filter to exclude all `system:*` agent events from training. Rationale: system events (k9_subscriber, orchestrator, intervention_engine per ARCH-18 Section 1.4) are infrastructure telemetry, not agent governance decisions. They carry different semantics and would dilute the signal. The brain should learn from *agent* behavior, not from its own infrastructure.

**4. Validation check**: After each training batch load, assert `COUNT(*) WHERE agent_id LIKE 'system:%'` = 0 in the loaded batch. If non-zero, abort the training pass and emit `BRAIN_SELF_REFERENCE_VIOLATION` CIEU event.

**Implementation constraint for Maya**: The exclusion filter must be applied at the SQL query level (WHERE clause), not in Python post-filtering. Post-filtering would load self-referential data into memory before discarding it, which (a) wastes memory on a 400K+ row corpus, and (b) creates a window where the data exists in the training pipeline and could be accidentally included by a future code change.

### Quantitative Impact

From ARCH-18 Section 1.4, `system:k9_subscriber` alone accounts for 47,245 events (11.8% of corpus). Combined system events are likely 80K+ rows. Excluding these reduces the training corpus to ~320K events, which is still ample for the 5 strategies in the CEO spec.

---

## Summary Table

| Question | Decision | Key Constraint |
|---|---|---|
| Q1: Hebbian compatibility | Run parallel, converge later | New module `cieu_bipartite_learner.py`; do not modify `aiden_brain.py` |
| Q2: `decision_canonical` placement | In-table migration (ALTER TABLE ADD COLUMN) | Single backfill transaction; modify CIEU writer to populate at INSERT time |
| Q3: alpha initial value | 0.15 with adaptive schedule | Hard-coded bounds [0.10, 0.30]; cosine stability governs adjustment |
| Q4: Divergence threshold metric | KL divergence (primary) + cosine trajectory (secondary) | DKL > 0.10 + outcome flat = WARN; DKL > 0.20 + outcome flat = FREEZE |
| Q5: Order-of-operations | Normalizer first; DISPATCH-EXEC parallel | No dependency between the two; normalizer unblocks all bipartite phases |
| Q6: Self-referential training guard | Provenance tag (`system:brain`) + SQL-level exclusion | WHERE clause excludes all `system:*` agents; assertion validates each batch |

---

## Cross-References

- CEO spec: `reports/ceo/governance/cieu_bipartite_learning_v1.md`
- ARCH-17: `Y-star-gov/docs/arch/arch17_behavioral_governance_spec.md`
- ARCH-18: `knowledge/cto/arch18_cieu_brain_corpus.md`
- Hebbian system: `scripts/aiden_brain.py` (lines 150-173: `hebbian_update`, lines 278-283: `record_co_activation`, lines 287-295: `apply_decay`)
- CIEU schema: `.ystar_cieu.db` table `cieu_events` (28 columns, 401,729 rows at ruling time)

---

*This ruling is binding on Phases 1-4 implementation. Phase 5+ convergence (Hebbian+bipartite) requires a separate ruling after 30-session empirical data.*
