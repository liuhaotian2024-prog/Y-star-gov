Audience: CEO (Aiden) for dispatch kickoff + eng-platform (Ryan) for implementation
Research basis: AGENTS.md:948 delegated authority + AGENTS.md:1027 Anti-Drift Rule #022 + empirical gap (12+ hours uncommitted today) + CZL-BRAIN-AUTO-INGEST ruling architecture (boundary-hook pattern) + session_close_yml.py + governance_boot.sh source review
Synthesis: Stop-hook + session-close dual trigger with per-repo authority routing, pre-commit safety gates, .gitignore-like exclusion, and shared "state flush" framework with BRAIN-AUTO-INGEST
Purpose: Unblock Ryan to implement auto-commit-push cadence enforcement as a single-script addition with 2 boundary wiring edits

# CZL-AUTO-COMMIT-PUSH Architectural Ruling

**Author**: Ethan Wright (CTO)
**Date**: 2026-04-19
**Status**: RULING ISSUED — ready for CEO kickoff dispatch to eng-platform (Ryan)
**Scope**: Automated enforcement of AGENTS.md #022 commit-push-within-30-min directive

---

## CIEU 5-Tuple

- **Y***: Every session that produces file modifications results in a well-formed commit pushed to origin within 30 minutes of the last file write, with zero manual intervention required
- **Xt**: Directive #022 is prose only; today's session accumulated 100+ modified files over 12+ hours with 0 commits; origin/main HEAD stale at 978d4da4 since 08:00; external consultants reviewing GitHub see a snapshot that is a full workday behind actual state
- **U**: Ruling document covering 8 items (trigger, auth, safety, scope, rollback, integration, checklist, success criteria)
- **Yt+1**: Ryan has concrete implementation path; CEO dispatches eng-platform
- **Rt+1**: 0 if all 8 items answered with rationale and implementation is single-session achievable

---

## 1. Trigger Mechanism

**Decision**: Dual trigger — **(A) session_close_yml.py** (guaranteed) + **(B) Stop-hook cadence check** (opportunistic mid-session). NOT cron.

**Rationale**:

- **(A) session_close_yml.py (mandatory commit-push at session end)**: Every session close already runs this script. Adding a "commit-push if dirty" step here guarantees that no session ends with unpushed work. This is the safety net — even if (B) fails or is bypassed, session close catches the gap. Latency: bounded to session length (worst case = full session duration, but never crosses session boundaries).

- **(B) Stop-hook cadence check (mid-session enforcement)**: The PostToolUse Stop hook (`hook_stop_reply_scan.py`) fires after every assistant reply. Adding a lightweight timestamp check — "has it been >25 minutes since last commit, AND are there staged/unstaged changes?" — triggers a commit-push cycle mid-session. This enforces the 30-minute SLA during long sessions. The check itself is O(1): read a timestamp file, compare to `time.time()`, only invoke git if threshold exceeded. No performance concern.

- **Cron REJECTED**: Same reasoning as CZL-BRAIN-AUTO-INGEST — another daemon adds operational surface area. Boundary hooks + cadence check cover all cases.

**Why 25 minutes, not 30**: 5-minute buffer for the commit-push operation itself (test run, staging, commit message generation, push). If cadence fires at t=25min, the actual push completes by t=27-28min, well within the 30-minute SLA.

---

## 2. Authorization Boundary

**Problem**: AGENTS.md:948 says "CTO pushes CTO commits, CEO pushes CEO commits. Eng-* never push." In an automated system, who is the "committer" when files were written by 3 different sub-agents across a session?

**Decision**: The **active agent at commit time** is the committer of record. Authority routing:

| Active Agent | Can commit? | Can push? | Scope |
|-------------|-------------|-----------|-------|
| ceo (Aiden) | Yes | Yes — ystar-company only | All ystar-company files in scope |
| cto (Ethan) | Yes | Yes — both repos | All Y-star-gov + ystar-company files in scope |
| eng-* | Yes (commit only) | **No** — must leave push for CTO/CEO | Files within eng scope only |

**Implementation**: `scripts/auto_commit_push.py` reads `.ystar_active_agent` to determine current authority level. If active agent is `eng-*`, it commits but skips push and writes a flag file `.ystar_push_pending` with the commit hash. The next CEO/CTO session boot (via governance_boot.sh) detects `.ystar_push_pending` and pushes.

**Commit message format**: Automated commits use a deterministic template:
```
auto: session work batch [{agent_id}] {timestamp}

Files: {count} modified, {count} new
Active agent: {agent_id}
Trigger: {session_close|cadence_25min}

Co-Authored-By: {agent_display_name}
```

This is distinguishable from manual commits (which use free-form messages) and auditable.

**Git author**: Uses the git config user (Aiden Liu / Board), since all agents operate under Board's git identity. The `Active agent:` line in the commit body provides agent-level attribution.

---

## 3. Safety Gates (Pre-Commit Abort List)

Before any auto-commit, `auto_commit_push.py` runs these checks in order. ANY failure aborts the commit and logs the reason to `.logs/auto_commit.log`:

| # | Gate | Check | Abort if |
|---|------|-------|----------|
| 1 | **Test gate** | `python -m pytest --tb=line -q --timeout=60 2>&1` (Y-star-gov only; ystar-company has no test suite) | Exit code != 0. Do not commit broken code. |
| 2 | **CROBA clean window** | Query `.ystar_cieu.db`: `SELECT count(*) FROM cieu_events WHERE event_type LIKE '%CROBA%' AND timestamp > ?` (last 5 min) | Count > 0. Active CROBA violation means scope breach in progress — do not commit evidence of violation. |
| 3 | **No mid-edit state** | Check for `.swp`, `.tmp`, `~` suffix files in the staging area; check `.ystar_active_tool` flag (set by Write tool hook, cleared on completion) | Flag file exists. A Write tool is mid-execution — staging now would capture partial file state. |
| 4 | **Minimum change threshold** | `git diff --stat HEAD` line count | 0 lines changed. Do not create empty commits. |
| 5 | **Secret scan** | `grep -rn "sk-\|OPENAI_API_KEY\|password\s*=" {staged_files}` | Any match. Do not commit secrets. This is a fast grep, not a full secret scanner, but catches the common cases. |
| 6 | **Scope guard** | Verify no files outside permitted scope are staged (e.g., eng-kernel agent should not have modified `sales/`) | Files outside agent scope detected. Log violation, unstage out-of-scope files, proceed with in-scope files only. |

**Test gate skip for ystar-company**: The company repo has no pytest suite. Gate 1 only runs when the repo being committed is Y-star-gov (detected by checking if `pyproject.toml` with `name = "ystar"` exists in repo root).

**On abort**: Write `AUTO_COMMIT_ABORTED` CIEU event with gate number and reason. Do NOT retry automatically — the abort reason likely requires human/agent judgment to resolve.

---

## 4. Scope Rules (What Auto-Commits, What Never)

**Auto-commit include list** (glob patterns):

```
# ystar-company repo
reports/**/*.md
knowledge/**/*.md
memory/*.md
memory/*.json
.czl_subgoals.json
.claude/tasks/**/*.md
governance/**/*.md
products/**/*.md
content/**/*.md
docs/**/*.md

# Y-star-gov repo  
ystar/**/*.py
tests/**/*.py
reports/**/*.md
```

**Auto-commit exclude list** (never staged, never committed by auto-commit):

```
# Secrets and credentials
.env
.env.*
**/credentials*
**/secrets*

# Local state files (machine-specific, not meaningful in git)
.ystar_active_agent
.ystar_session.json
.ystar_session_flags
.ystar_cieu.db*
.ystar_cieu_omission.db*
.ystar_warning_queue_archive.json
.ystar_memory.db*
aiden_brain.db*
.k9_subscriber_state.json
scripts/.session_booted
scripts/.session_call_count
scripts/.engineer_subscriber.pid
scripts/.logs/**
scripts/.ystar_*
scripts/.k9_*

# Binary and generated
*.pyc
__pycache__/
*.whl
dist/
*.egg-info/

# Backup files
*.bak*
*.swp
*~
```

**Implementation**: `auto_commit_push.py` maintains these as two Python lists (`INCLUDE_GLOBS`, `EXCLUDE_GLOBS`). Staging uses explicit `git add {file}` per matched include file, never `git add -A` or `git add .`. Exclude list is checked after include — if a file matches both, exclude wins.

**Rationale for explicit include (not "everything except exclude")**: Defensive. Unknown new file types default to "not auto-committed" rather than "auto-committed." This prevents accidental commit of files we haven't categorized. Manual commits can still include anything.

---

## 5. Rollback

**Problem**: If auto-commit produces a bad commit (wrong files, partial state, test regression discovered post-push), how do we unwind without destructive git ops (`reset --hard`, `push --force`)?

**Decision**: Revert-commit pattern. Never rewrite history.

**Procedure**:

1. **Detection**: Bad commit detected by (a) test failure on next boot, (b) CROBA violation logged against committed file, or (c) manual Board inspection.

2. **Revert**: `git revert {bad_commit_hash} --no-edit` creates a new commit that undoes the bad one. History preserved, no force push needed.

3. **Push the revert**: Normal push (not force). Remote history shows: original commit -> revert commit. Fully auditable.

4. **CIEU event**: `AUTO_COMMIT_REVERTED` with `{"original_hash": X, "revert_hash": Y, "reason": Z}`.

**Pre-push verification** (additional safety for the push step):

After `git push`, verify: `git rev-parse HEAD == git rev-parse origin/main`. If they differ (push failed silently — e.g., network error), write `.ystar_push_pending` flag and emit `PUSH_FAILED` CIEU event. Next session boot retries.

**No `--force` ever**: `auto_commit_push.py` must never invoke `git push --force` or `git reset --hard`. These are Board-only operations. If history needs rewriting, that is a manual escalation.

---

## 6. Integration with CZL-BRAIN-AUTO-INGEST

**Shared pattern**: Both CZL-AUTO-COMMIT-PUSH and CZL-BRAIN-AUTO-INGEST are instances of the same architectural pattern: **internal state must flow to an external persistence layer at session boundaries**.

| Dimension | AUTO-COMMIT-PUSH | BRAIN-AUTO-INGEST |
|-----------|-----------------|-------------------|
| Internal state | Working tree modifications | Session artifacts (.md files) |
| External target | GitHub (origin/main) | aiden_brain.db (SQLite) |
| Trigger | session_close + cadence check | session_close + session_boot |
| Failure mode | Push retry at next boot | Ingest retry at next boot |
| Flag file on failure | `.ystar_push_pending` | (none — boundary retry is sufficient) |

**Shared "state flush" framework**: YES, they should share a common orchestration point.

**Design**: Create `scripts/session_state_flush.py` as the unified coordinator. Both `governance_boot.sh` and `session_close_yml.py` call this ONE script instead of calling `brain_auto_ingest.py` and `auto_commit_push.py` separately.

```python
# scripts/session_state_flush.py --mode {boot|close}

def flush(mode: str):
    results = {}
    
    # 1. Brain ingest (always safe — advisory, non-blocking)
    results["brain"] = run_brain_ingest(mode)
    
    # 2. Auto-commit-push (only at close + cadence; at boot, only push pending)
    if mode == "close":
        results["commit_push"] = run_auto_commit_push()
    elif mode == "boot":
        results["push_pending"] = push_if_pending()
    
    # 3. Emit unified CIEU event
    emit_cieu("SESSION_STATE_FLUSH", {
        "mode": mode,
        "results": results,
        "timestamp": time.time()
    })
    
    return results
```

**Execution order**: Brain ingest BEFORE commit-push at close time. Rationale: ingest may update `aiden_brain.db` (excluded from git via scope rules), but the ingest report goes to `.logs/` (also excluded). No cross-dependency. But sequencing brain first means the commit captures any brain-triggered report updates in `reports/`.

**Boot-time push**: At boot, `session_state_flush.py --mode boot` checks for `.ystar_push_pending`. If found, pushes the pending commit(s) and removes the flag. This handles the case where an eng-* agent committed but could not push.

---

## 7. Implementation Checklist for Ryan (eng-platform)

**Constraint**: Each bullet is a single-file edit or new file creation. Total: 7 items.

1. **Create `scripts/auto_commit_push.py`** (~150 LOC): Core logic — read `.ystar_active_agent`, check safety gates (6 gates per Section 3), stage files per include/exclude lists (Section 4), commit with template message (Section 2), push if authorized, write `.ystar_push_pending` if not. Accept `--repo {ystar-company|Y-star-gov|both}` flag. Return JSON summary to stdout.

2. **Create `scripts/session_state_flush.py`** (~60 LOC): Unified orchestrator per Section 6. Calls `brain_auto_ingest.py` then `auto_commit_push.py`. Accept `--mode {boot|close}`. Handles failures independently (one failing does not block the other). Emits `SESSION_STATE_FLUSH` CIEU event.

3. **Edit `scripts/session_close_yml.py`**: After the existing `secretary_curate` try/except block, add a new try/except block: `subprocess.run([sys.executable, state_flush_script, "--mode", "close"], capture_output=True, timeout=120)`. The 120-second timeout covers test gate (up to 60s) + commit + push. On failure, print warning and continue — session close must never be blocked.

4. **Edit `scripts/governance_boot.sh`**: After the `ALL SYSTEMS GO` line, add: `python3 "$COMPANY_ROOT/scripts/session_state_flush.py" --mode boot 2>>"$COMPANY_ROOT/scripts/.logs/state_flush.log" || echo "[WARN] state flush failed at boot"`. This handles both brain ingest and pending push retry.

5. **Edit `scripts/hook_stop_reply_scan.py`**: Add cadence check function (~30 LOC). On each invocation, read `.ystar_last_commit_ts` (written by `auto_commit_push.py` after each commit). If `time.time() - last_commit_ts > 1500` (25 minutes) AND `git status --porcelain` returns non-empty, invoke `auto_commit_push.py --repo both`. Write result to `.logs/cadence_commit.log`. This check adds <50ms to the Stop hook (one file read + one timestamp comparison; git status only runs when threshold exceeded).

6. **Create `.ystar_autocommit_scope.json`**: Externalize the include/exclude glob lists from Section 4 into a JSON config file so they can be tuned without code changes. `auto_commit_push.py` reads this at startup.

7. **Add test `tests/platform/test_auto_commit_push.py`**: At minimum 4 test cases: (a) safety gate abort on failing test, (b) exclude list prevents `.env` staging, (c) eng-* agent commits but does not push, (d) cadence check triggers after 25-min gap. Use `git init` in a tmpdir for isolation.

---

## 8. Success Criteria

| # | Criterion | Measurement | Target |
|---|-----------|-------------|--------|
| 1 | **Session commit rate** | After implementation, count commits per session. For any session with >0 file modifications, commits > 0. | 100% of productive sessions produce at least 1 commit. |
| 2 | **Push lag p95** | Measure `push_timestamp - last_file_write_timestamp` across 10 sessions. | p95 < 30 minutes. |
| 3 | **No secret leak** | Grep all auto-commits for `sk-`, `API_KEY`, `password=`. | 0 matches across all auto-commits. |
| 4 | **No broken commits** | Run `pytest` at each auto-commit hash for Y-star-gov. | 0 test failures at any auto-committed hash. |
| 5 | **Eng-* push delegation works** | Simulate: set `.ystar_active_agent` to `eng-kernel`, run `auto_commit_push.py`. Verify commit exists locally but `.ystar_push_pending` flag is written and no push occurred. Boot as CTO, verify push completes and flag is cleared. | Flag written, push deferred, next-boot push succeeds. |
| 6 | **Cadence trigger fires** | In a test session, do not manually commit for 26 minutes with dirty working tree. Verify Stop hook triggers `auto_commit_push.py`. | Cadence commit appears in git log with trigger=cadence_25min in message. |
| 7 | **State flush unification** | Verify `SESSION_STATE_FLUSH` CIEU event contains both `brain` and `commit_push` results after session close. | Event payload has both keys with non-null values. |
| 8 | **Origin matches local** | At end of any CTO/CEO session: `git rev-parse HEAD == git rev-parse origin/main` for both repos. | 100% match rate across 10 sessions. |

---

## Formal Definitions

Let `W(t)` = working tree state at time `t`, `C(t)` = set of committed hashes at time `t`, `R(t)` = set of pushed hashes on remote at time `t`.

**Invariant (Directive #022)**: For all `t`, if `exists c in C(t)` such that `c not in R(t)` and `age(c) > 30 min`, then GOVERNANCE_VIOLATION.

**Auto-commit trigger predicate**:
```
SHOULD_COMMIT(t) := 
  (trigger = session_close) 
  OR (trigger = cadence AND t - last_commit_ts > 25min AND |diff(W(t), C(t))| > 0)
```

**Authorization predicate**:
```
CAN_PUSH(agent) := agent in {ceo, cto}
CAN_COMMIT(agent) := agent in {ceo, cto, eng-*}  // all agents can commit
```

**Safety gate conjunction**:
```
SAFE_TO_COMMIT(t) := 
  tests_pass(t) 
  AND croba_clean_window(t, 5min) 
  AND NOT mid_edit(t) 
  AND |diff(W(t), C(t))| > 0 
  AND no_secrets_staged(t) 
  AND all_files_in_scope(t, agent)
```

**State flush composition**:
```
FLUSH(mode, t) := brain_ingest(mode, t) ; auto_commit_push(mode, t)
// Sequential composition: brain first, then commit-push. Independent failure handling.
```

---

## Mathematical Model

**Commit lag distribution**: Let `L_i` = time between file modification and commit containing that modification. Under the cadence-check regime with period `P = 25 min`:

- **Best case**: `L_i = 0` (session close immediately after last edit)
- **Worst case**: `L_i = P + epsilon` (file written just after a cadence check, caught by next check)
- **Expected**: `E[L_i] = P/2 = 12.5 min` (uniform distribution of write times within cadence interval)

**Push lag**: `L_push = L_commit + T_push` where `T_push` ~ 2-5 seconds for a normal git push. For eng-* agents, `L_push = L_commit + T_next_boot` (deferred push). Worst case for eng-* = session duration + next CTO/CEO boot time. Acceptable: eng-* sessions are always followed by CEO coordination sessions.

**Probability of data loss** (commit exists but not pushed, machine fails):
- P(machine_failure_in_30min) is negligible for development machines
- P(push_failure | network_up) ~ 0 (git push to GitHub is reliable)
- P(network_down_at_push_time) ~ rare but handled by `.ystar_push_pending` retry

**Net effect on Directive #022 compliance**: From 0% (current prose-only) to ~100% (automated enforcement with mechanical fallback). The only violation path is: cadence check disabled + session crashes without close + no subsequent session boot. This requires two simultaneous failures.

---

## Appendix: Rejected Alternatives

| Alternative | Rejection Reason |
|-------------|-----------------|
| Git hooks (pre-push, post-commit) | Git hooks fire on manual git operations, not on file writes. They enforce git discipline but cannot enforce commit frequency. Our problem is not "bad pushes" but "no commits at all." |
| Cron daemon every 5 minutes | Adds yet another daemon to manage. We already have daemon reliability issues (lock-death, orphaned PIDs). Boundary hooks + cadence check achieve the same coverage without a persistent process. |
| Real-time commit on every file write | Produces hundreds of micro-commits per session. Pollutes git history, makes `git log` unusable, conflicts with the company's commit style of "batch session work into meaningful commits." |
| Manual discipline ("just remember to push") | Current state. 12+ hours of violation today. Humans and agents both forget. Automation is the only reliable solution. |
| Separate branches per agent, merge at session end | Adds merge complexity, conflict resolution, branch management. Single-branch (main) with sequential commits is simpler and sufficient for a solo company with no concurrent human developers. |
