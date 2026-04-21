Audience: CEO (Aiden) for dispatch kickoff + eng-kernel (Leo), eng-platform (Ryan), eng-governance (Maya) for implementation scope
Research basis: Empirical analysis of aiden_brain.db schema (150 nodes, 1902 edges, 1.4M activation_log rows), source review of aiden_import.py / aiden_brain.py / aiden_embed.py / session_close_yml.py / governance_boot.sh, SQLite query confirming WHO_I_AM access_count=0 bug and content_hash column never populated
Synthesis: (c) boot-time + (d) close-time boundary auto-ingest with hash-based dedup is the correct architecture; INSERT OR REPLACE bug in add_node() is a P0 prerequisite fix that currently destroys all Hebbian learning on every re-import
Purpose: Unblock CEO dispatch of 3 engineers (kernel/platform/governance) to implement brain auto-ingest pipeline with concrete file edits, owner split, and testable success criteria

# CZL-BRAIN-AUTO-INGEST Architectural Ruling

**Author**: Ethan Wright (CTO)
**Date**: 2026-04-19
**Status**: RULING ISSUED — ready for CEO kickoff dispatch
**Scope**: Auto-ingestion of session work into `aiden_brain.db`

---

## CIEU 5-Tuple

- **Y***: Every session's written artifacts (receipts, specs, memory updates) flow into `aiden_brain.db` within bounded time of session close, with zero manual `aiden_import` invocations required
- **Xt**: Brain ingestion is fully manual; `aiden_import.py` only scans `knowledge/ceo/wisdom/`; `content_hash` column exists but is never populated; `add_node` uses `INSERT OR REPLACE` which resets `access_count` to 0 on every re-import (confirmed: WHO_I_AM `access_count=0` despite being the most accessed hub node); 150 nodes, 1902 edges, 1.4M activation_log rows
- **U**: Ruling document covering 8 items with concrete implementation plan
- **Yt+1**: CEO dispatches eng-platform + eng-kernel to implement (c)+(d) boundary auto-ingest with hash-based dedup
- **Rt+1**: 0 if all 8 items answered with testable criteria

---

## 1. Chosen Combination: (c) + (d) + hash-guard, NOT (b)

**Decision**: Implement **(c) governance_boot.sh auto-ingest** + **(d) session_close_yml.py auto-ingest**. Reject **(a) cron** and **(b) PostToolUse hot-path**.

**Rationale**:

- **(b) REJECTED** — PostToolUse hook fires on every tool call. Adding a `subprocess.run(aiden_import)` on each `Write` to `reports/*.md` adds 200-800ms latency per file write. With 50-200 writes per session, that is 10-160 seconds of cumulative overhead in the critical path. The hook_wrapper.py already has performance issues (Board has noted "lock-death" from slow hooks). Adding I/O-heavy SQLite writes to the hot path violates Werner Vogels' "don't put non-essential work in the request path" principle. The brain is a read-ahead optimization, not a transactional requirement.

- **(a) REJECTED** — Cron requires a persistent daemon. We already have daemon reliability problems (`.engineer_subscriber.pid` orphaning, socket lock-death). Adding another daemon adds operational surface area for zero marginal benefit over boundary hooks that already fire reliably.

- **(c) + (d) CHOSEN** — Session boundaries are natural batch points:
  - **(c) boot-time**: `governance_boot.sh` already runs deterministically at session start. Adding `python3 scripts/brain_auto_ingest.py --mode delta` as a post-validation step (after `ALL SYSTEMS GO`) means the current session starts with all prior session work already in the brain. Latency is bounded (one-time 2-5 second scan) and non-blocking (brain query is not gated on ingest completion during boot).
  - **(d) close-time**: `session_close_yml.py` already writes continuation + CIEU events. Adding ingest here means work written *during* the current session flows in at session end. If the session crashes without close, (c) catches it at next boot. No data loss, bounded staleness = 1 session.

**Worst-case staleness**: 1 session. If session N crashes without close, session N's work ingests at session N+1 boot. Acceptable for a read-ahead cognitive cache.

---

## 2. Owner Split

| Owner | Scope | Deliverable |
|-------|-------|-------------|
| **eng-kernel** (Leo) | Semantic ingest logic + hash-based dedup + `access_count` preservation bug fix | `scripts/brain_auto_ingest.py` (new file, ~120 LOC); fix `add_node` to not reset `access_count` on re-import |
| **eng-platform** (Ryan) | Hook wiring into `governance_boot.sh` + `session_close_yml.py` | 2 edits: add `brain_auto_ingest.py --mode delta` call to each boundary script |
| **eng-governance** (Maya) | CIEU event emission on ingest complete | Add `BRAIN_INGEST_COMPLETE` event type to `_write_session_lifecycle` calls in the two boundary scripts |

**No cross-scope overlap**. Leo writes the ingest engine, Ryan wires it into session boundaries, Maya ensures observability via CIEU.

---

## 3. Re-ingest vs Incremental: Hash-Based Detection

**Current state**: `content_hash` column exists in `nodes` table schema but is **never populated** by `aiden_import.py`. Line 177 of `aiden_import.py` computes `content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]` but never passes it to `add_node()`. The `add_node()` function signature does not accept `content_hash`.

**Design**:

```
brain_auto_ingest.py --mode delta:
  1. Walk target directories (knowledge/, reports/, memory/)
  2. For each .md file:
     a. Compute sha256(content)[:16]
     b. Query nodes table: SELECT content_hash FROM nodes WHERE file_path = ?
     c. If hash matches -> skip (no change)
     d. If hash differs or row missing -> upsert node with new content_hash
  3. Report: "Ingested N new/changed files, skipped M unchanged"
```

**Required schema fix** (Leo, eng-kernel):
- Fix `add_node()` to accept and store `content_hash` parameter
- Fix `add_node()` to use `INSERT ... ON CONFLICT(id) DO UPDATE` instead of `INSERT OR REPLACE`, preserving `access_count`, `last_accessed`, `created_at` on update (only updating content-derived fields: `name`, `summary`, `dims`, `content_hash`, `updated_at`)
- This is a P0 bug fix independent of auto-ingest: every `aiden_import` run currently zeroes out all Hebbian learning by resetting `access_count=0`

**New column**: Not needed. `content_hash TEXT` already exists in the schema. Just needs to be populated.

---

## 4. Failure Mode

**Principle**: Brain ingest failure must never block session boot or session close. The brain is advisory, not transactional.

| Failure | Response |
|---------|----------|
| `brain_auto_ingest.py` crashes during boot | `governance_boot.sh` catches exit code != 0, prints `[WARN] brain auto-ingest failed: <stderr>`, continues boot. Session is fully functional without brain. No retry needed — next session close or next boot will retry. |
| `brain_auto_ingest.py` crashes during close | `session_close_yml.py` catches exception in try/except (same pattern as existing `secretary_curate` and `priority_brief_validator` calls), prints warning, continues close. Next boot catches the delta. |
| SQLite lock contention (WAL mode) | `brain_auto_ingest.py` uses `PRAGMA busy_timeout=5000` (5 second wait). If still locked after 5s, skip this run, emit `BRAIN_INGEST_LOCK_TIMEOUT` CIEU event. |
| Corrupt `.md` file (encoding error) | Per-file try/except. Skip file, log to stderr, continue with remaining files. |

**No queue. No retry daemon.** Boundary hooks provide natural retry at next session transition. Adding a queue adds complexity for a system that self-heals via temporal redundancy.

**CIEU events emitted on failure**:
- `BRAIN_INGEST_FAILED` with `{"error": str(e), "mode": "boot|close", "files_attempted": N}`

---

## 5. Activation_log Interaction

**Current state**: `activation_log` has 1,426,800 rows. Each row records a query + which nodes activated + session_id + timestamp.

**Auto-ingest must emit activation entries** to keep Hebbian learning informed that newly ingested nodes are "warm". Format:

```python
# In brain_auto_ingest.py, after upserting each new/changed node:
activation_entry = {
    "query": f"auto_ingest:{file_path}",
    "activated_nodes": json.dumps([
        {"node_id": node_id, "activation_level": 0.3}  # moderate warmth
    ]),
    "session_id": current_session_id,  # from .ystar_session.json
    "timestamp": time.time()
}
# INSERT INTO activation_log (query, activated_nodes, session_id, timestamp)
#   VALUES (?, ?, ?, ?)
```

**Activation level**: 0.3 (not 1.0). Auto-ingest indicates the node was refreshed, not that a human queried it. This creates a base warmth that spreading activation can build on, without inflating scores of unread nodes.

**Hebbian**: When multiple files in the same directory are ingested in the same batch, call `record_co_activation([node_ids_in_same_dir])` to strengthen proximity edges. This mimics the "written together -> related" heuristic.

**access_count**: Auto-ingest does NOT increment `access_count`. Only explicit `activate()` queries and `touch_node()` calls increment it. This preserves the semantic distinction between "node exists in brain" vs "node was consulted by an agent".

---

## 6. Implementation Checklist

### eng-kernel (Leo) — `scripts/brain_auto_ingest.py` + `aiden_brain.py` fix

1. **Fix `add_node()` in `aiden_brain.py`**: Change `INSERT OR REPLACE` to `INSERT ... ON CONFLICT(id) DO UPDATE SET name=?, summary=?, node_type=?, depth_label=?, dim_y=?, ..., content_hash=?, updated_at=?`. Preserve `access_count`, `last_accessed`, `created_at`.
2. **Add `content_hash` parameter to `add_node()` signature**: Pass through to the INSERT/UPSERT.
3. **Create `scripts/brain_auto_ingest.py`**: Accept `--mode delta|full` flag. `delta` = hash-compare + skip unchanged. `full` = re-import all.
4. **Scan directories**: `knowledge/`, `reports/`, `memory/` (configurable via `INGEST_DIRS` list at top of file).
5. **Node ID scheme**: `{dir}/{filename_without_ext}` (e.g., `reports/cto/CZL-BRAIN-AUTO-INGEST-ruling`). Use `/` separator, not OS-dependent.
6. **Activation_log emission**: After batch upsert, write one activation_log row per new/changed node with `activation_level=0.3`, `query=auto_ingest:{path}`.
7. **Co-activation for same-dir batch**: Call `record_co_activation()` for nodes in the same directory that were ingested in the same run.
8. **Return JSON summary to stdout**: `{"ingested": N, "skipped": M, "errors": E, "total_scanned": T}` — consumed by boundary scripts for CIEU event payload.

### eng-platform (Ryan) — boundary wiring

1. **Edit `scripts/governance_boot.sh`**: After the `ALL SYSTEMS GO` line, add: `python3 "$COMPANY_ROOT/scripts/brain_auto_ingest.py" --mode delta 2>>"$COMPANY_ROOT/scripts/.logs/brain_ingest.log" || echo "[WARN] brain auto-ingest failed at boot"`
2. **Edit `scripts/session_close_yml.py`**: After the `secretary_curate` try/except block (~line 506), add a new try/except block calling `subprocess.run([sys.executable, brain_ingest_script, "--mode", "delta"], capture_output=True, timeout=30)`. Log result. On failure, print warning and continue.

### eng-governance (Maya) — CIEU observability

1. **Add `BRAIN_INGEST_COMPLETE` event emission** in both boundary scripts after successful ingest, with payload: `{"mode": "boot|close", "ingested": N, "skipped": M, "session_id": sid}`.
2. **Add `BRAIN_INGEST_FAILED` event emission** in both boundary scripts on ingest failure, with payload: `{"error": str(e), "mode": "boot|close"}`.

---

## 7. Success Criteria (L3 SHIPPED)

| # | Criterion | Measurement |
|---|-----------|-------------|
| 1 | **Zero manual ingest required**: After implementation, no session requires manual `python3 scripts/aiden_import.py` to get prior session work into brain | Verified by: run 2 consecutive sessions. Session 1 writes a new `reports/test_ingest_probe.md`. Session 2 boots, then `sqlite3 aiden_brain.db "SELECT id FROM nodes WHERE file_path LIKE '%test_ingest_probe%'"` returns 1 row. |
| 2 | **Hash dedup works**: Re-running `brain_auto_ingest.py --mode delta` twice on unchanged files reports `ingested: 0, skipped: N` on second run | Verified by: stdout JSON output shows `ingested=0` on second consecutive run. |
| 3 | **access_count preserved**: After re-import, nodes that had `access_count > 0` still have the same value | Verified by: `sqlite3 aiden_brain.db "SELECT id, access_count FROM nodes WHERE access_count > 0"` returns same set before and after import. |
| 4 | **CIEU events emitted**: `BRAIN_INGEST_COMPLETE` event appears in `.ystar_cieu.db` after each session boot/close | Verified by: `sqlite3 .ystar_cieu.db "SELECT count(*) FROM cieu_events WHERE event_type='BRAIN_INGEST_COMPLETE'"` > 0 after one full boot+close cycle. |
| 5 | **Boot not blocked by ingest failure**: Deliberately corrupt one `.md` file (invalid UTF-8), run boot. Boot completes with `ALL SYSTEMS GO`. Ingest logs the per-file error and continues. | Verified by: boot output contains `ALL SYSTEMS GO` AND `.logs/brain_ingest.log` contains error for corrupt file AND other files were ingested. |
| 6 | **Bounded latency**: `brain_auto_ingest.py --mode delta` completes in < 10 seconds for the current corpus (~500 .md files across knowledge/reports/memory) | Verified by: `time python3 scripts/brain_auto_ingest.py --mode delta` real time < 10s. |
| 7 | **Brain delta reflects session work**: Write a new file to `reports/` during session, run session close, then verify the node exists with correct `content_hash` populated | Verified by: `sqlite3 aiden_brain.db "SELECT content_hash FROM nodes WHERE file_path LIKE '%{new_file}%'"` returns non-NULL 16-char hex. |

---

## 8. Consultant Catch: WHO_I_AM `access_count=0` Discrepancy

**Root cause identified**: This is a confirmed bug, not a field naming confusion.

**Evidence**:
- `sqlite3 aiden_brain.db "SELECT id, access_count FROM nodes WHERE id='WHO_I_AM'"` returns `access_count=0`
- The schema has exactly ONE field tracking hub visits: `access_count INTEGER DEFAULT 0` in the `nodes` table
- There is no separate `query_count` or `activation_count` column — those do not exist
- `activation_log` table tracks queries but does NOT write back to `nodes.access_count`
- The claim of "15 accesses" likely came from counting `activation_log` rows where WHO_I_AM appeared in `activated_nodes` JSON, but that count is never synced to `nodes.access_count`

**Bug mechanism**: `add_node()` at line 101-114 of `aiden_brain.py` uses `INSERT OR REPLACE`. SQLite's `INSERT OR REPLACE` semantics = `DELETE + INSERT`. This means every time `aiden_import.py` runs (which does `add_node` for every file), ALL nodes get their `access_count` reset to 0, `last_accessed` reset to `time.time()`, and `created_at` reset to `time.time()`. Every re-import destroys all Hebbian learning history stored in node metadata.

**Impact**: The entire brain's learning loop is broken. Spreading activation depends on `access_count` for base activation calculation (line 181: `math.log(count)`). With `access_count=0`, `math.log(max(0,1)) = 0`, so every node has zero base activation. The brain operates on text similarity alone, with no memory of past usage patterns.

**Fix (included in checklist item 1)**: Replace `INSERT OR REPLACE` with `INSERT ... ON CONFLICT(id) DO UPDATE` that explicitly lists which columns to update (content-derived fields only) and which to preserve (access_count, last_accessed, created_at, base_activation). This is the P0 prerequisite for auto-ingest — without it, auto-ingest would amplify the data destruction by running on every session boundary.

**Recommendation**: After the fix ships, run one full `brain_auto_ingest.py --mode full` to repopulate all content_hash values, then let delta mode handle subsequent sessions. The access_count values will start accumulating correctly from that point forward (historical counts are unrecoverable since they were never persisted).

---

## Appendix: Rejected Alternatives Log

| Alternative | Rejection Reason |
|-------------|-----------------|
| fswatch/inotify real-time watcher | macOS fswatch is unreliable for SQLite writes; adds daemon; boundary hooks are sufficient |
| Git post-commit hook ingest | Not all session work is committed; reports/ and memory/ are often in working tree only |
| Embed at ingest time (combine with aiden_embed.py) | Embedding requires Ollama running (localhost:11434); not guaranteed available at session boundary; keep ingest (fast, local SQLite) decoupled from embedding (slow, requires model server) |
| Queue + worker pattern | Over-engineered for bounded-staleness-1-session tolerance; natural retry via boot/close is simpler and more reliable |
