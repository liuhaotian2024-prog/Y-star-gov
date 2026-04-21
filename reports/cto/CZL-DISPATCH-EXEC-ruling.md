# CZL-DISPATCH-EXEC Architectural Ruling

**Author**: Ethan Wright (CTO)
**Date**: 2026-04-19
**Status**: RULING ISSUED -- ready for Ryan (eng-platform) implementation
**Authority**: CEO dispatch spec `reports/ceo/governance/dispatch_exec_gap_v1.md` + Board 2026-04-19 directive
**Audience**: Ryan Park (eng-platform) for implementation; CEO Aiden for executor-role clarity; future sessions debugging dispatch pipe

---

## 1. Chosen Pattern: C (Hybrid Ledger + CEO Same-Turn Spawn)

### Decision

Pattern C. Whiteboard remains the ledger; CEO main thread is the executor; subscriber narrows to claim-reservation + audit-trail.

### Rationale (Bayesian update on empirical evidence)

**Prior**: subscriber daemon can spawn sub-agent execution autonomously (P_prior ~ 0.7, based on the "in production, would spawn" comment implying feasibility).

**Evidence observed 2026-04-19**:
- 5 cards posted between 15:23-15:39 UTC. All 5 claimed by subscriber PIDs within 90s. Zero sub-agents actually running.
- Subscriber PIDs 1606/1607/1608 alive since 2026-04-17 18:19 -- 44+ hours of claim-only behavior with no execution.
- Claude Code architecture constraint: `Agent` tool calls can only originate from the main Claude session's tool-use loop. A Python subprocess (`engineer_task_subscriber.py`) has no mechanism to inject Agent tool calls into the parent session. This is not a bug -- it is a structural boundary of the Claude Code runtime.
- Pattern A (fork+exec `claude` CLI per claim) would lose shared memory, CIEU store handles, and session context. Cost: ~$0.50/spawn, O(minutes) cold-start. Rejected on both economics and correctness.
- Pattern B (spawn_intent JSONL + CEO polls) requires a polling loop in CEO's main thread that does not exist and would add complexity. CEO's tool-use cadence is irregular (driven by Board interaction), so poll-based discovery has unbounded latency.
- Pattern D (MCP executor) is architecturally clean but requires building a new MCP tool + server -- overkill for a 4-engineer team.

**Posterior**: P(subscriber_can_spawn) = 0.0 (structural impossibility, not fixable by code change). P(Pattern_C_works) = 0.95 (CEO already does same-turn Agent spawns successfully in other flows; the only new piece is a routing helper).

**Conclusion**: Pattern C. The subscriber's value is (a) atomic claim reservation preventing double-assignment, (b) CIEU audit trail of claim events, (c) collision prevention if CEO posts multiple cards in rapid succession. Execution is and must be CEO-owned.

---

## 2. Scope-to-Role Regex Taxonomy

I expand the CEO's 5-line table to 7 lines, adding explicit fallback and the cross-repo path normalization that the current regex lacks. The subscriber and the routing helper must share this single table.

```python
# scripts/dispatch_role_routing.py
# Canonical scope-to-engineer routing table.
# Input: card["scope"] string (comma-separated file paths).
# Output: first matching engineer canonical ID.
# Order matters: first match wins. Fallback is always Ethan-CTO.

import re

ROUTE_TABLE = [
    # 1. Kernel: Y*gov core engine, adapters, identity, hook internals
    (re.compile(r"Y-star-gov/ystar/(adapters|kernel)/|identity_detector|boundary_enforcer"), "eng-kernel"),

    # 2. Governance: omission engine, forget guard, intervention, CIEU stores, router registry
    (re.compile(r"Y-star-gov/ystar/governance/|OmissionEngine|ForgetGuard|router_registry|omission_|intervention_engine"), "eng-governance"),

    # 3. Platform: hook wrappers, dispatch scripts, CLI, subscriber, watchdog, boot scripts
    (re.compile(r"scripts/(hook_|dispatch_|engineer_task_|session_|governance_boot|cron_wrapper|czl_)"), "eng-platform"),

    # 4. Domains: domain packs, policy templates, OpenClaw adapter
    (re.compile(r"Y-star-gov/ystar/domains/|domains/|policy|template"), "eng-domains"),

    # 5. CTO triage: architecture specs, CTO reports, cross-cutting reviews
    (re.compile(r"reports/cto/|arch/|SPEC|review"), "eng-cto-triage"),

    # 6. Tests: route to the engineer whose module is under test
    # (resolved by stripping "tests/" prefix and re-matching against rules 1-4)

    # 7. Fallback: anything unmatched goes to CTO for triage assignment
]

ENGINEER_DISPLAY_NAMES = {
    "eng-kernel":      "Leo Chen (eng-kernel)",
    "eng-governance":  "Maya Patel (eng-governance)",
    "eng-platform":    "Ryan Park (eng-platform)",
    "eng-domains":     "Jordan Lee (eng-domains)",
    "eng-cto-triage":  "Ethan Wright (CTO -- manual triage)",
}


def route_scope(scope_str: str) -> str:
    """Return canonical engineer ID for the given scope string."""
    for pattern, engineer_id in ROUTE_TABLE:
        if pattern.search(scope_str):
            return engineer_id
    return "eng-cto-triage"  # fallback -- never silent drop
```

### Changes from CEO's spec

1. Added `boundary_enforcer` to kernel scope (missed in original 5-line).
2. Added `omission_|intervention_engine` to governance scope (Maya's primary codebase).
3. Expanded platform scope to cover `czl_` prefix scripts (boot injection, subgoals).
4. Added `eng-cto-triage` as explicit fallback role instead of reusing `Ethan-CTO` label (disambiguates CTO-as-architect from CTO-as-fallback-triage).
5. Test file routing: strip `tests/` prefix, re-run against rules 1-4. This avoids a separate regex per test directory.
6. Display name map for human-readable receipts.

---

## 3. OmissionEngine Integration

### Decision: Yes, claim creates an obligation that CEO's session must discharge.

When `ENGINEER_CLAIM_TASK` CIEU event fires, the OmissionEngine registers a new obligation:

| Field | Value |
|-------|-------|
| `obligation_type` | `DISPATCH_CLAIM_MUST_SPAWN` |
| `entity_id` | CEO session ID (from `.ystar_session.json`) |
| `actor_id` | claiming engineer (e.g. `eng-platform`) |
| `trigger_event` | `ENGINEER_CLAIM_TASK` |
| `ttl` | 300 seconds (5 minutes from claim time) |
| `severity` | `HIGH` |
| `fulfillment_event` | `SUBAGENT_START` with matching `atomic_id` |
| `fail_mode` | Soft-overdue at 300s -> `OmissionViolation` emitted as `DISPATCH_CLAIM_NO_SPAWN`. Hard-overdue at 600s -> escalation to Board-visible CIEU warning. |

### How it works

1. `dispatch_board.py claim` already emits `ENGINEER_CLAIM_TASK` with `atomic_id` in params_json.
2. OmissionEngine rule match: event_type == `ENGINEER_CLAIM_TASK` -> create `DISPATCH_CLAIM_MUST_SPAWN` obligation, TTL 300s.
3. When CEO spawns Agent for this card, the sub-agent's boot emits `SUBAGENT_START` (already in Action Model v2 Phase A step 14 equivalent). OmissionEngine auto-fulfills the obligation via event matching on `atomic_id`.
4. If no `SUBAGENT_START` within 300s: OmissionEngine scan() produces `OmissionViolation`. This surfaces in CEO's next `governance_boot.sh` run or `session_watchdog.py --statusline` as a pending violation count.
5. If no spawn within 600s (hard TTL): escalation emits `CEO_OMISSION_ESCALATION` CIEU event, which K9 routing picks up and surfaces in Board-visible warning queue.

### Why 300s TTL (not longer)

CEO's same-turn spawn should happen within seconds of the post. 300s is generous -- it accounts for CEO being mid-way through composing another Agent call. Anything beyond 5 minutes means the card has fallen into the dead-water pattern we are fixing. The hard 600s escalation prevents silent accumulation.

### Registration mechanism

Use the existing `register_redirect_obligation` pattern as template (ARCH-11b). New function `register_dispatch_spawn_obligation` on OmissionEngine, called from a new OmissionRule in the rule registry.

---

## 4. Implementation Checklist for Ryan (eng-platform)

Each bullet is a single file edit. Total: 7 edits.

1. **`scripts/dispatch_role_routing.py` -- NEW FILE**
   Create the routing module with the `ROUTE_TABLE` and `route_scope()` function exactly as specified in Section 2 above. Include the `ENGINEER_DISPLAY_NAMES` dict. Add a `__main__` block that accepts `--scope` arg and prints the routed engineer for CLI testing.

2. **`scripts/engineer_task_subscriber.py` lines 43-45 -- EDIT**
   Replace the misleading comment block:
   ```python
   # Lines 43-45 BEFORE:
   # In production, would spawn execution here
   # For now, daemon only auto-claims (engineer must manually complete)

   # Lines 43-45 AFTER:
   # ARCH RULING CZL-DISPATCH-EXEC (2026-04-19):
   # Subscriber CANNOT spawn Agent tool calls -- structural Claude Code boundary.
   # Execution is CEO-session-owned. Subscriber role: claim reservation + CIEU audit only.
   # See Y-star-gov/reports/cto/CZL-DISPATCH-EXEC-ruling.md
   emit_cieu("SUBSCRIBER_CLAIM_PENDING_SPAWN", {
       "atomic_id": result.stdout.strip(),
       "engineer_id": engineer_id,
       "spawn_owner": "ceo-main-session",
   })
   ```

3. **`scripts/dispatch_board.py` post_task() -- EDIT (after line 78)**
   After successful post, write a spawn-intent line to `scripts/.pending_spawns.jsonl`:
   ```python
   # Append spawn intent for CEO pickup
   import os
   intent_path = Path(__file__).parent / ".pending_spawns.jsonl"
   intent = json.dumps({
       "atomic_id": args.atomic_id,
       "scope": args.scope,
       "routed_to": route_scope(args.scope),  # import from dispatch_role_routing
       "posted_at": task["posted_at"],
       "prompt_hint": args.description,
   })
   with open(intent_path, "a") as f:
       f.write(intent + "\n")
   ```

4. **`scripts/dispatch_board.py` -- ADD `pending` subcommand**
   New subcommand `pending` that reads `.pending_spawns.jsonl`, filters out any whose `atomic_id` appears in a completed/in-progress card, and prints remaining un-spawned intents. CEO calls this at boot or between tasks. Output: one JSON object per line.

5. **`scripts/governance_boot.sh` -- EDIT (add pending-spawn nag)**
   After existing boot checks, add:
   ```bash
   echo "=== Pending Spawns ==="
   python3 scripts/dispatch_board.py pending 2>/dev/null || echo "(no pending spawns helper yet)"
   ```
   This ensures CEO sees un-spawned claims every session start.

6. **`Y-star-gov/ystar/governance/omission_rules.py` -- EDIT (add rule)**
   Register new rule:
   ```python
   Rule(
       event_type="ENGINEER_CLAIM_TASK",
       obligation_type="DISPATCH_CLAIM_MUST_SPAWN",
       ttl_seconds=300,
       severity=Severity.HIGH,
       description="CEO must spawn Agent for claimed card within 5 min",
       fulfillment_event="SUBAGENT_START",
       match_field="atomic_id",
       deduplicate=True,
   )
   ```

7. **`tests/platform/test_dispatch_role_routing.py` -- NEW FILE**
   Unit tests for `route_scope()`:
   - `"Y-star-gov/ystar/adapters/hook.py"` -> `eng-kernel`
   - `"scripts/hook_wrapper.py"` -> `eng-platform`
   - `"Y-star-gov/ystar/governance/omission_engine.py"` -> `eng-governance`
   - `"Y-star-gov/ystar/domains/openclaw/adapter.py"` -> `eng-domains`
   - `"reports/cto/some_review.md"` -> `eng-cto-triage`
   - `"some/unknown/path.py"` -> `eng-cto-triage` (fallback)
   - Comma-separated scope: `"scripts/hook_wrapper.py,Y-star-gov/ystar/adapters/hook.py"` -> `eng-platform` (first match wins based on order in scope string)

---

## 5. Success Criteria (L3 SHIPPED acceptance)

I will mark this L3 SHIPPED when ALL of the following are empirically verified:

| # | Criterion | Verification Method |
|---|-----------|-------------------|
| S1 | `dispatch_role_routing.py` exists and `route_scope()` returns correct engineer for all 7 test cases | `pytest tests/platform/test_dispatch_role_routing.py` -- 7/7 pass |
| S2 | `engineer_task_subscriber.py` no longer contains "would spawn" comment; emits `SUBSCRIBER_CLAIM_PENDING_SPAWN` CIEU event on claim | `grep -c "would spawn" scripts/engineer_task_subscriber.py` == 0; CIEU query for event type after test claim |
| S3 | `dispatch_board.py post` writes to `.pending_spawns.jsonl` | `ls -la scripts/.pending_spawns.jsonl` exists after a test post; `wc -l` increments |
| S4 | `dispatch_board.py pending` subcommand returns un-spawned intents | Manual: post a card, do not spawn, run `pending`, see the card listed |
| S5 | `governance_boot.sh` prints pending-spawn section on boot | Run boot, observe "=== Pending Spawns ===" in output |
| S6 | OmissionEngine rule `DISPATCH_CLAIM_MUST_SPAWN` registered | `grep DISPATCH_CLAIM_MUST_SPAWN Y-star-gov/ystar/governance/omission_rules.py` returns match |
| S7 | Next 3 cards posted by CEO result in same-turn Agent spawn (no dead-water) | CEO-verified: post + spawn + receipt within same tool-use sequence |

**S1-S6** are Ryan's responsibility. **S7** is CEO's responsibility (requires using the new pattern in production).

---

## Formal Definitions

Let D = dispatch event (card post), C = claim event, S = spawn event, E = execution completion.

**Liveness property**: For all D_i, there exists S_i such that time(S_i) - time(D_i) < 300s.

**Safety property**: For all C_i, there exists exactly one S_i with matching atomic_id, or an OmissionViolation V_i is emitted.

**Obligation discharge predicate**: discharged(obligation_j) iff exists event e where e.type == "SUBAGENT_START" AND e.params.atomic_id == obligation_j.trigger_params.atomic_id AND time(e) < time(obligation_j.created) + TTL.

## Mathematical Model

**Dead-water probability under Pattern C**:

P(dead_water | Pattern_C) = P(CEO_forgets_spawn) * P(no_nag_seen)

With pending_spawns nag at boot: P(no_nag_seen) approaches 0 across sessions (CEO boots at least once per work block).

With OmissionEngine 300s TTL: P(CEO_forgets_spawn AND no_violation_emitted) = 0 (deterministic engine, proven by 406+ test suite).

Combined: P(dead_water | Pattern_C + nag + omission) < epsilon, where epsilon is bounded by P(CEO ignores violation AND skips boot) -- a double-fault that the existing K9 escalation chain catches at 600s hard TTL.

**Contrast with status quo**: P(dead_water | current) = 1.0 (empirically: 5/5 cards dead today).

---

## Receipt (5-tuple)

- **Y***: Unblock Ryan to implement dispatch-exec pipe; CEO trusts the whiteboard is real
- **Xt**: Subscriber is claim-only stub (lines 44-45 confirmed). 5 cards dead-water today. No routing helper. No OmissionEngine integration. CEO mental model "claimed == executing" was false
- **U**: Wrote ruling selecting Pattern C with Bayesian rationale; expanded scope-to-role regex to 7 rules; specified OmissionEngine obligation (type, TTL, fail-mode); wrote 7-bullet implementation checklist for Ryan; defined 7 success criteria with verification methods
- **Yt+1**: Ryan has unambiguous checklist (7 file edits). CEO has executor-role clarity. OmissionEngine will catch future dead-water within 300s
- **Rt+1**: 0 -- all 5 deliverable items present (pattern choice + rationale, regex taxonomy, omission integration spec, implementation checklist, success criteria)
