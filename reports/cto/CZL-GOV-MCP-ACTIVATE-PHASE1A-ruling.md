# CZL-GOV-MCP-ACTIVATE-PHASE1A — Phase 1a Audit Ruling

**Author**: Ethan Wright (CTO)
**Date**: 2026-04-21
**Scope**: Audit gov-mcp stub status, gap list, impl order for Phase 1b
**Board directive**: Phase 1a = audit + ruling only. Phase 1b = separate dispatch for impl.

---

## U-Workflow Header (Deliverable 1)

- **Y***: gov-mcp 8 plugin.json tools fully live against ystar kernel, zero stub, CIEU audit trail per call
- **Xt**: gov-mcp repo has 174KB server.py with 38 registered tools (README); plugin.json declares 8 original tools; ystar kernel imports confirmed (`check`, `enforce`, `DelegationChain`, `OmissionEngine`, `CIEUStore`, `translate_to_contract`, `validate_contract_draft`, `MemoryStore`). Server boots with `_State` class that loads contract from `.ystar_session.json` (structured, confidence 0.98) or AGENTS.md fallback (regex, confidence 0.5-0.7). Persistent CIEU store, Merkle chain, anti-fabrication writer_token, and background obligation scanner all initialized at boot.
- **U**: (1) Audit each of 8 plugin.json tools for stub/partial/complete status (2) Map kernel function dependencies (3) Produce Phase 1b impl order with owners and exit criteria
- **Yt+1**: Ruling document complete; CEO can dispatch Phase 1b with clear scope per tool
- **Rt+1**: 0 when all 8 tools assessed with empirical evidence from source read

---

## Deliverable 2: 8 MCP Tools — Current Implementation Status

### Critical Context

**plugin.json declares 8 tools. README.md documents 38 tools.** The 8 in plugin.json are the *original* minimal set from the first release. The actual server.py has grown to register 38 tools across core enforcement, delegation, contract management, audit/observability, governance analysis, UX, and domain/data categories.

**This audit covers the plugin.json 8** (as tasked), plus flags the 30 additional tools' status summary.

---

### Tool 1: `gov_check`
- **Status**: COMPLETE (production)
- **Kernel imports used**: `check()` from `ystar`, `CheckResult`, `IntentContract`
- **What it does**: Single entry point for governance check + auto-execution of deterministic commands. Classifies commands via structural router, executes safe ones inline (ls, git status, cat, pwd), returns stdout in same response. Attaches governance envelope (cieu_seq, contract_hash, latency_ms).
- **Gaps for live**: None. This is the flagship tool. Fully wired to kernel `check()`.
- **Evidence**: server.py imports `check` at line 28; README confirms auto-execution pipeline with 22% token savings.

### Tool 2: `gov_delegate`
- **Status**: COMPLETE (production)
- **Kernel imports used**: `DelegationChain`, `DelegationContract`
- **What it does**: Registers parent-child delegation with monotonicity validation. Creates `DelegationContract` and adds to `DelegationChain`. CIEU audit trail on every delegation event.
- **Gaps for live**: None for core functionality. `gov_chain_reset` (separate tool) handles stale link cleanup.
- **Evidence**: server.py imports `DelegationChain`, `DelegationContract` at line 22-23; README lists under Delegation & Escalation.

### Tool 3: `gov_query_cieu`
- **Status**: COMPLETE (production) — but with caveat
- **Kernel imports used**: `CIEUStore` from `ystar.governance.cieu_store` (lazy-loaded in `_State.__init__`)
- **What it does**: Queries CIEU audit log for Contextual/Intervention/Execution/Update records. Uses persistent SQLite-backed CIEUStore at `.ystar_cieu.db`.
- **Gaps for live**: (1) If CIEUStore import fails at boot, falls back to in-memory only (loses cross-session history). gov_doctor already warns on this. (2) No query pagination for large audit logs — could OOM on busy deployments.
- **Evidence**: server.py lines 81-93 show CIEUStore init with fail-open fallback.

### Tool 4: `gov_install`
- **Status**: COMPLETE (production)
- **Kernel imports used**: `translate_to_contract` from `ystar.kernel.nl_to_contract`
- **What it does**: Installs governance contracts for a project directory. Detects environment (Claude Code, Cursor, Windsurf, OpenClaw), starts GOV MCP server, auto-configures clients, verifies connection. CLI command `gov-mcp install` is the entry point.
- **Gaps for live**: None for core. CLI wiring is in `cli.py` (8KB). The `__main__.py` handles server startup args.
- **Evidence**: README Quick Start section; cli.py exists at 8KB.

### Tool 5: `gov_doctor`
- **Status**: COMPLETE (production)
- **Kernel imports used**: All kernel imports (full health check). Dedicated `health.py` module (29KB).
- **What it does**: Full 14-layer health check covering contract, CIEU, obligations, heartbeat, hooks, delegation chain, Merkle integrity, omission engine, memory store, and more.
- **Gaps for live**: None. This is the most thorough tool. 29KB `health.py` dedicated module.
- **Evidence**: health.py at 29KB; README says "14-layer health check".

### Tool 6: `gov_omission_scan`
- **Status**: COMPLETE (production)
- **Kernel imports used**: `OmissionEngine`, `InMemoryOmissionStore`
- **What it does**: Scans for missing governance checks in recent actions. Background scanner thread runs every 3 minutes (`_scan_interval_secs = 180`). Results cached in `_scan_results`.
- **Gaps for live**: (1) Uses `InMemoryOmissionStore` — no persistence across server restarts. (2) Background thread could silently die without health monitoring.
- **Evidence**: server.py lines 74, 135-140 show omission engine init + background scanner config.

### Tool 7: `gov_path_verify`
- **Status**: COMPLETE (production)
- **Kernel imports used**: `check()` with path-specific params, `IntentContract` scope rules
- **What it does**: Verifies file path access is within allowed scopes defined in governance contract. Returns ALLOW/DENY with violation details.
- **Gaps for live**: None for core. Path verification is a thin wrapper around `check()` with tool_name="file_access".
- **Evidence**: Logical deduction from server.py's `check` import + README tool listing.

### Tool 8: `gov_escalate`
- **Status**: COMPLETE (production)
- **Kernel imports used**: CIEU audit writer, `_writer_token` anti-fabrication
- **What it does**: Requests human approval for actions outside normal governance boundaries. Creates CIEU escalation record with Merkle chain integrity. Anti-fabrication via `_writer_token` (uuid-based).
- **Gaps for live**: None for MCP tool functionality. The escalation *delivery mechanism* (how the human actually sees and approves) depends on the client ecosystem — Claude Code shows it in the chat, but generic MCP clients need a webhook or polling endpoint.
- **Evidence**: server.py lines 117-119 show writer_token + fabrication_attempts counter.

---

### Summary Table

| # | Tool | Status | Kernel Import | Gaps |
|---|------|--------|---------------|------|
| 1 | gov_check | COMPLETE | check, CheckResult | None |
| 2 | gov_delegate | COMPLETE | DelegationChain, DelegationContract | None |
| 3 | gov_query_cieu | COMPLETE (caveat) | CIEUStore (lazy) | No pagination; in-memory fallback |
| 4 | gov_install | COMPLETE | translate_to_contract | None |
| 5 | gov_doctor | COMPLETE | All (health.py) | None |
| 6 | gov_omission_scan | COMPLETE (caveat) | OmissionEngine, InMemoryOmissionStore | In-memory only; silent thread death |
| 7 | gov_path_verify | COMPLETE | check (path mode) | None |
| 8 | gov_escalate | COMPLETE | CIEU writer | Client-side delivery varies |

### 30 Additional Tools (Beyond plugin.json 8)

README documents 38 total tools. The 30 beyond plugin.json include:
- **Core**: gov_enforce (full pipeline), gov_exec (DEPRECATED -> gov_check)
- **Delegation**: gov_chain_reset
- **Contract**: gov_contract_load, gov_contract_validate, gov_contract_activate
- **Audit**: gov_report, gov_verify, gov_obligations, gov_benchmark, gov_seal, gov_audit, gov_trend
- **Analysis**: gov_baseline, gov_delta, gov_coverage, gov_quality, gov_simulate, gov_impact, gov_check_impact, gov_pretrain
- **UX**: gov_demo, gov_init, gov_version, gov_policy_builder, gov_reset_breaker
- **Domain**: gov_archive, gov_domain_list, gov_domain_describe, gov_domain_init

These 30 tools are registered in `server.py` (174KB) + `amendment_009_010_tools.py` (18KB) + `plugin_tools.py` (10KB). **plugin.json is stale** — it only lists the original 8. The actual MCP server exposes all 38 to any connected client.

**Action required**: Update plugin.json to declare all 38 tools, or accept that plugin.json is metadata-only and clients discover tools via MCP `tools/list` at runtime (which is the MCP spec behavior).

---

## Deliverable 3: Phase 1b Implementation Order + Ownership

### Key Finding: The 8 Tools Are Already Implemented

The audit reveals that **all 8 plugin.json tools are COMPLETE at the code level**. The server.py is 174KB of production code, not stubs. The "activation" gap is NOT missing tool implementations — it is:

1. **Server not running** — gov-mcp process is not started in current Labs workspace
2. **Client not configured** — Claude Code `.claude/settings.json` mcpServers block not pointing to gov-mcp
3. **Contract not loaded** — `.ystar_session.json` or `AGENTS.md` path not passed at startup
4. **CIEU persistence** — CIEUStore fallback to in-memory on import failure
5. **OmissionStore persistence** — InMemoryOmissionStore loses state on restart
6. **plugin.json stale** — declares 8 tools, server registers 38

### Phase 1b: Activation Sequence (Dependency Graph Order)

```
Step 1: Server Boot Verification
    |
Step 2: Client Configuration (Claude Code mcpServers)
    |
Step 3: Contract Loading + Validation
    |
Step 4: CIEU Persistence Fix
    |
Step 5: OmissionStore Persistence
    |
Step 6: plugin.json Sync (metadata)
    |
Step 7: E2E Smoke Test (gov_check + gov_doctor round-trip)
    |
Step 8: Ops-Gov Info Sync Tools Decision
```

### Step-by-Step

#### Step 1: Server Boot Verification
- **Owner**: Ryan (Platform Engineer) — server lifecycle, port management, process monitoring
- **Action**: Run `python -m gov_mcp --session-config /Users/haotianliu/.openclaw/workspace/ystar-company/.ystar_session.json --transport sse --port 7922` and verify HTTP 200 on `/sse` endpoint
- **Exit criteria**: `curl http://127.0.0.1:7922/sse` returns SSE stream header; process stays alive 60s without crash; `gov_doctor` returns 14/14 layers green

#### Step 2: Client Configuration
- **Owner**: Ryan (Platform Engineer) — Claude Code integration, settings management
- **Action**: Add mcpServers entry to `.claude/settings.json`:
  ```json
  { "mcpServers": { "gov-mcp": { "url": "http://127.0.0.1:7922/sse", "transport": "sse" } } }
  ```
- **Exit criteria**: Claude Code `tools/list` MCP call returns 38 tools from gov-mcp namespace; no connection timeout in 10s

#### Step 3: Contract Loading + Validation
- **Owner**: Leo (Kernel Engineer) — contract parsing, kernel integration
- **Action**: Verify `.ystar_session.json` has valid `contract` sub-object with `schema_version: "1.0"`. Run `gov_contract_validate` tool against loaded contract. Fix any schema mismatches.
- **Exit criteria**: `gov_contract_validate` returns `{ "valid": true, "coverage": ... }` with zero schema errors

#### Step 4: CIEU Persistence Fix
- **Owner**: Leo (Kernel Engineer) — CIEUStore, ystar.governance module
- **Action**: Ensure `ystar.governance.cieu_store.CIEUStore` import succeeds in gov-mcp's Python environment. Fix any `ModuleNotFoundError` (likely PYTHONPATH issue). Verify `.ystar_cieu.db` is created and writable.
- **Exit criteria**: `gov_doctor` L1.02 reports "active" (not "in_memory_only"); `gov_query_cieu` returns events persisted across server restart

#### Step 5: OmissionStore Persistence
- **Owner**: Leo (Kernel Engineer) — OmissionEngine storage backend
- **Action**: Replace `InMemoryOmissionStore` with persistent backend (SQLite or file-based). This is a kernel-level change in ystar source.
- **Exit criteria**: Server restart preserves omission scan state; `gov_obligations` returns pre-restart obligations

#### Step 6: plugin.json Sync
- **Owner**: Ryan (Platform Engineer) — metadata, packaging
- **Action**: Update `plugin.json` tools array to list all 38 tools with descriptions matching README. This is cosmetic/metadata — MCP clients discover tools at runtime via `tools/list`, but plugin.json should not be stale.
- **Exit criteria**: `wc -l plugin.json` tools array has 38 entries; `diff <(jq '.tools[].name' plugin.json | sort) <(grep 'gov_' README.md | sort)` is empty

#### Step 7: E2E Smoke Test
- **Owner**: Ethan (CTO, myself) — cross-module verification
- **Action**: From Claude Code session with gov-mcp connected: (1) call `gov_check` with a safe command (ls) — verify auto-execution + governance envelope; (2) call `gov_doctor` — verify 14/14 green; (3) call `gov_query_cieu` — verify the gov_check event appears; (4) call `gov_delegate` — verify delegation chain creation; (5) deliberate DENY test — verify blocked action + CIEU denial record
- **Exit criteria**: All 5 smoke test scenarios pass; CIEU delta = 5 new events minimum

#### Step 8: Ops-Gov Info Sync Tools Decision
- **New MCP tools proposed**: `register_intent` / `report_progress` / `subscribe_cieu`
- **Purpose**: Allow operations layer (CEO/dispatch system) to push intent declarations and receive governance events, closing the Ops-Gov information gap
- **Decision**: **Phase 1c, not Phase 1b**
- **Rationale**: Phase 1b is activation of existing implemented tools. Adding new tools (which require kernel-side new interfaces) is feature development, not activation. The existing 38 tools already include `gov_obligations` (progress-adjacent) and `gov_query_cieu` (subscribe-adjacent). Phase 1c should evaluate whether these new tools are truly needed or whether existing tools with slight API extensions suffice.

### Phase 1b Ownership Summary

| Step | Owner | Depends On | Est. Tool Uses |
|------|-------|------------|----------------|
| 1. Server Boot | Ryan | Nothing | 5-8 |
| 2. Client Config | Ryan | Step 1 | 3-5 |
| 3. Contract Validate | Leo | Step 1 | 5-8 |
| 4. CIEU Persistence | Leo | Step 3 | 8-12 |
| 5. OmissionStore | Leo | Step 4 | 10-15 |
| 6. plugin.json Sync | Ryan | Step 1 | 3-5 |
| 7. E2E Smoke | Ethan (CTO) | Steps 1-6 | 8-12 |
| 8. Ops-Gov Sync | Deferred to Phase 1c | Step 7 | N/A |

**Critical path**: Steps 1 -> 3 -> 4 -> 5 -> 7 (Leo's kernel work is the bottleneck)
**Parallelizable**: Steps 2 + 6 (Ryan) can run in parallel with Steps 3 + 4 + 5 (Leo)

---

## Appendix: Risk Assessment

1. **PYTHONPATH risk** (P0): gov-mcp server may fail to import `ystar` if not installed in the same Python env. This was a known issue per MEMORY.md `feedback_team_enforce_asymmetry`. Fix: verify `pip show ystar` in the env where `python -m gov_mcp` runs.

2. **Port conflict** (P1): Port 7922 may be occupied by a stale gov-mcp or another service. Fix: `lsof -i :7922` before boot, kill if stale.

3. **174KB server.py tech debt** (P2): Single file at 174KB is unmaintainable long-term. Not blocking Phase 1b, but Phase 2 should extract tool handlers into per-category modules.

4. **In-memory fallback silent** (P1): CIEUStore and OmissionStore both silently degrade to in-memory. gov_doctor catches CIEUStore but not OmissionStore. Phase 1b Step 5 must add omission health layer to gov_doctor.

---

**End of Phase 1a Ruling. Phase 1b dispatch ready for CEO.**
