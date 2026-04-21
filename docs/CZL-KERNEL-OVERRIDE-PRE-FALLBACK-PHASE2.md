Audience: CEO (Aiden) for Samantha#6 re-dispatch decision; CTO (Ethan) for kernel changelog; future eng-kernel sessions for regression context.
Research basis: Samantha#5 receipt (`reports/secretary/AMENDMENT-020-executed-v5.md`) traced the 4-step deadlock at byte level; Phase 1 fix at hook.py:492-511 confirmed immutable hoist pattern; `boundary_enforcer.py:386-463` confirmed `_check_restricted_write_paths` uses identical override-role logic as `_check_immutable_paths`.
Synthesis: The restricted_write_paths check suffered the same pre-fallback ordering bug as immutable_paths (fixed in Phase 1). Hoisting the restricted check before the policy-membership fallback and removing the post-fallback duplicate resolves the Samantha AGENTS.md deadlock. 14 regression tests confirm both phases.
Purpose: Unblock Samantha#6 retry of AMENDMENT-020 paste; CEO can re-dispatch after daemon recycle.

# CZL-KERNEL-OVERRIDE-PRE-FALLBACK-PHASE2 Receipt

**Date**: 2026-04-19
**Executor**: Leo Chen (eng-kernel)
**Status**: COMPLETE
**Maturity**: L4 SHIPPED (fix applied + 14 regression tests PASS + Phase 1 non-regressed)

---

## 5-Tuple

### Y*
Both `_check_restricted_write_paths` AND `_check_immutable_paths` override checks structurally reachable for unregistered roles (secretary) before policy-membership fallback rewrites identity.

### Xt (before this dispatch)
- Phase 1 (CZL-KERNEL-OVERRIDE-PRE-FALLBACK) fixed immutable ordering: `_check_immutable_paths` at hook.py:500 runs before fallback at :517.
- `_check_restricted_write_paths` was at hook.py:530, AFTER the fallback at :517-523.
- Samantha#5 traced the exact 4-step deadlock:
  1. hook sees `who=secretary` (push_agent done)
  2. immutable check passes (secretary in override_roles)
  3. fallback at 517: secretary not in policy -> `who = "agent"`
  4. restricted check at 530: `who="agent"` not in `allowed_roles=["secretary"]` -> DENY
- AMENDMENT-020 paste blocked; Samantha#5 aborted atomically.

### U (actions taken)
1. Read boot context: `.czl_subgoals.json`, Samantha#5 receipt, Phase 1 fix, `boundary_enforcer.py` functions.
2. Diagnosed: restricted check must run pre-fallback with original `who`, same as Phase 1 immutable pattern.
3. Hoisted `_check_restricted_write_paths` to hook.py line 521 (after immutable at 500, before fallback at 534).
4. REMOVED the post-fallback duplicate restricted check (was at line 530). Rationale: restricted_write_paths declares which roles CAN write. Re-checking after fallback with degraded identity (secretary->agent) incorrectly denies the authorized writer. Path set is identical pre/post fallback, so no coverage gap.
5. Created 14 regression tests in `tests/adapters/test_hook_restricted_override_ordering.py`:
   - 6 Phase 2 restricted override ordering tests (Cases 1-6)
   - 3 Combined Phase 1+2 ordering tests (Cases 7-9)
   - 5 Unit tests on `_check_restricted_write_paths` directly
6. Ran all 24 tests (14 new + 10 existing Phase 1): ALL PASSED.

### Yt+1 (state after fix)
- hook.py flow order: immutable(original who) -> restricted(original who) -> fallback(rewrite who) -> tool_restriction -> behavior_rules -> ...
- Secretary writing AGENTS.md: immutable ALLOW (override_roles) -> restricted ALLOW (allowed_roles) -> fallback rewrites who -> continues to downstream checks -> ALLOW.
- CEO writing AGENTS.md: immutable DENY (not in override_roles) -> stops, never reaches restricted.
- Unknown role writing AGENTS.md: immutable DENY -> stops.
- Secretary writing .ystar_active_agent (restricted only, not immutable): immutable PASS (path not matched) -> restricted ALLOW (secretary in allowed_roles) -> ALLOW.
- Non-secretary writing .ystar_active_agent: immutable PASS -> restricted DENY -> stops.

### Rt+1 = 0
Fix landed. Both Phase 1 and Phase 2 regression tests pass (24/24). The Samantha#5 deadlock scenario (Case 1 + Case 7) explicitly verified as ALLOW. No regressions in Phase 1 immutable tests.

---

## Files Modified

1. `/Users/haotianliu/.openclaw/workspace/Y-star-gov/ystar/adapters/hook.py`
   - Inserted pre-fallback `_check_restricted_write_paths` call at line 521 with CIEU write + deny handling (13 lines)
   - Replaced post-fallback restricted check block (11 lines) with explanatory comment (6 lines)
   - Net: moved restricted check before fallback, removed duplicate post-fallback check

2. `/Users/haotianliu/.openclaw/workspace/Y-star-gov/tests/adapters/test_hook_restricted_override_ordering.py` (NEW)
   - 14 test cases across 3 test classes
   - TestRestrictedOverrideOrdering: 6 integration tests through check_hook
   - TestCombinedImmutableAndRestrictedOrdering: 3 combined Phase 1+2 tests
   - TestRestrictedWritePathsUnit: 5 unit tests on _check_restricted_write_paths directly

## Test Output (abbreviated)
```
24 passed in 2.68s
```

## Smoke Simulation

Case 1 (Samantha scenario): secretary writes AGENTS.md via `check_hook(payload, policy, agent_id="secretary")` -> ALLOW (empty dict). Confirms the pre-fix deadlock is resolved.

Case 3: ceo writes AGENTS.md -> DENY with "Immutable path violation". Confirms non-override roles still blocked.

Case 4: secretary writes .ystar_active_agent -> ALLOW. Confirms restricted-only (non-immutable) paths also work with pre-fallback ordering.

Case 5: eng-kernel writes .ystar_active_agent -> DENY with "Restricted write path violation". Confirms non-allowed roles still blocked on restricted paths.

## Next Step
CEO re-dispatches Samantha#6 with the same AMENDMENT-020 v2-revised-diff. After daemon recycle (`pkill -9 -f _hook_daemon && sleep 2`), the identity-switch-first protocol should succeed end-to-end.

## Scope Guard Confirmation
- ONLY touched: `Y-star-gov/ystar/adapters/hook.py` + new test file
- Did NOT touch `boundary_enforcer.py` (check functions correct, only calling order was wrong)
- No git commit / git push / git add
- No files outside declared scope
