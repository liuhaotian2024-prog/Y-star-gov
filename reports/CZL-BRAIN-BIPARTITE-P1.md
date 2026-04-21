Audience: CEO (Aiden) for validation, CTO (Ethan) for Phase 2 unblock, Maya (eng-governance) for bipartite loader dependency
Research basis: empirical CIEU distribution from .ystar_cieu.db (415,923 rows, 40 distinct raw decision values); CEO spec reports/ceo/governance/cieu_bipartite_learning_v1.md Section 1-2; CTO ruling reports/cto/CZL-BRAIN-BIPARTITE-ruling.md Q1-Q6 (217 lines)
Synthesis: decision normalizer maps 40 raw values to 6 canonical buckets; ALTER TABLE migration backfilled 415K rows in 1.4s; INSERT-time population verified; self-referential guard tags 85K system events
Purpose: unblock Phase 2 bipartite loader (Maya) which depends on clean decision_canonical column for positive/negative/escape/rewrite partitioning

# CZL-BRAIN-BIPARTITE-P1 Receipt

**Author**: Leo Chen (eng-kernel)
**Date**: 2026-04-19
**Atomic ID**: CZL-BRAIN-BIPARTITE
**Phase**: 1

## 5-Tuple

- **Y***: Normalizer shipped + canonical column live + self-referential guard in place + INSERT-time population verified
- **Xt**: No normalizer existed, 20+ raw decision values with case variance and JSON corruption, no self-ref guard, ~404K rows at task start
- **U**: Created 4 files, edited 1 file, ran migration, verified INSERT path. 44 unit tests pass. Tool uses: 18
- **Yt+1**: `SELECT decision_canonical, COUNT(*) FROM cieu_events GROUP BY 1` shows clean 6-bucket distribution (info 164K / escalate 95K / allow 74K / deny 47K / unknown 34K / rewrite 55), 0 NULL rows
- **Rt+1**: 0

## Files Touched

| File | Action | Lines |
|---|---|---|
| `Y-star-gov/ystar/governance/cieu_decision_normalizer.py` | NEW | 105 |
| `Y-star-gov/ystar/governance/tests/__init__.py` | NEW | 0 |
| `Y-star-gov/ystar/governance/tests/test_cieu_decision_normalizer.py` | NEW | 170 |
| `Y-star-gov/ystar/governance/migrations/__init__.py` | NEW | 0 |
| `Y-star-gov/ystar/governance/migrations/001_add_decision_canonical.py` | NEW | 215 |
| `Y-star-gov/ystar/governance/cieu_store.py` | EDIT | +20 (import + INSERT columns) |

## Test Output

```
48 passed in 0.29s
(44 normalizer unit tests + 4 existing CIEU archive tests)
```

## Migration Output

```
Total rows: 415,923
decision_canonical distribution (6 buckets):
  info                     164,121
  escalate                  95,822
  allow                     74,753
  deny                      47,123
  unknown                   34,048
  rewrite                       55

provenance='system:brain': 85,756 rows
NULL decision_canonical remaining: 0
Migration time: 1.4s
```

## INSERT Path Verification

```
ALLOW -> decision_canonical=allow, provenance=system:brain (system agent)
warn  -> decision_canonical=escalate, provenance=None (regular agent)
```

## Canonical Mapping (6 buckets)

| Canonical | Raw values mapped |
|---|---|
| allow | allow, ALLOW, accept, approved, pass, passed |
| deny | deny, reject, blocked, denied |
| escalate | escalate, warn, warning |
| rewrite | rewrite, route, dispatch |
| info | info, complete, log |
| unknown | unknown, error, partial, embedded-JSON fragments |

## CTO Ruling Compliance

- Q1 (Hebbian parallel): Did NOT modify `aiden_brain.py hebbian_update()` -- normalizer is standalone
- Q2 (ALTER TABLE): Used `ALTER TABLE ADD COLUMN` (metadata-only) + single backfill transaction
- Q5 (Phase 1 first): Normalizer shipped independently, no downstream dependencies
- Q6 (Self-referential guard): `provenance` column added, `system:*` agents tagged `system:brain` (85,756 rows)
